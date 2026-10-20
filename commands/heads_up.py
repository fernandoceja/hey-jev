"""Heads-up alerts. A proactive engine on the Mac. Off until turned on.

Every few minutes it runs the checks Jev already has: the next calendar
event (EventKit, with shift overrides), the hazard watch (collect_hazards,
which uses its own cache), and the drive home (MapKit, after a shift ends).
When something matters, Jev speaks it once and writes one log line. The same
alert id is never spoken twice.

Rules: a voice on/off toggle; quiet hours 10 PM to 7 AM; a rate limit of one
spoken alert per HEADS_UP_MIN_GAP_MINUTES; a money filter that drops any line
about balances, bills, payments, or dollars. This module opens no socket,
adds no bridge command, and reads no secret. Mac-only.
"""
from datetime import datetime, timedelta
import json
import os
import re
import sys
import threading
import time

from . import config

_state_lock = threading.Lock()
_thread_lock = threading.Lock()
_thread = None
_quiet_probe = None

_MONEY_RE = re.compile(
    r"[$€£]|\b(?:balance|balances|bill|bills|payment|payments|pay|paid|payday|"
    r"dollars?|bucks|cents?|money|rent|debt|owe|owed|credit|card|bank|"
    r"account|deposit|transfer|loan|affirm|fidelity|discover|venmo|zelle|"
    r"paypal|invoice|salary|paycheck|usd)\b",
    re.I,
)
_DIGITS_MONEY_RE = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d{2})?\b|\b\d+\.\d{2}\b")


def mentions_money(line):
    """True when a line would speak money details. Those lines are never spoken."""
    text = str(line or "")
    return bool(_MONEY_RE.search(text) or _DIGITS_MONEY_RE.search(text))


def in_quiet_hours(now, start_hour=None, end_hour=None):
    """10 PM to 7 AM by default. No spoken alert in that window."""
    start = int(config.HEADS_UP_QUIET_START_HOUR if start_hour is None else start_hour)
    end = int(config.HEADS_UP_QUIET_END_HOUR if end_hour is None else end_hour)
    hour = now.hour
    if start == end:
        return False
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


# ---------- state ----------

def _blank():
    return {"enabled": None, "spoken": {}, "last_spoken": None}


def load_heads_up_state(path=None):
    path = path or config.HEADS_UP_STATE_PATH
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _blank()
    if not isinstance(data, dict):
        return _blank()
    state = _blank()
    if data.get("enabled") is not None:
        state["enabled"] = bool(data["enabled"])
    raw = data.get("spoken") or {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                state["spoken"][str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    try:
        state["last_spoken"] = float(data["last_spoken"]) if data.get("last_spoken") is not None else None
    except (TypeError, ValueError):
        state["last_spoken"] = None
    return state


def _write_state(path, state, now_ts):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    cutoff = now_ts - 3 * 24 * 3600
    payload = {
        "spoken": {k: v for k, v in (state.get("spoken") or {}).items() if v >= cutoff},
    }
    if state.get("enabled") is not None:
        payload["enabled"] = bool(state["enabled"])
    if state.get("last_spoken") is not None:
        payload["last_spoken"] = float(state["last_spoken"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def heads_up_enabled(path=None):
    state = load_heads_up_state(path)
    if state["enabled"] is None:
        return bool(config.HEADS_UP_ENABLED)
    return bool(state["enabled"])


def set_heads_up(on, path=None, now=None):
    """Voice toggle. Already-spoken ids stay spoken."""
    path = path or config.HEADS_UP_STATE_PATH
    now = now or datetime.now().astimezone()
    with _state_lock:
        state = load_heads_up_state(path)
        state["enabled"] = bool(on)
        _write_state(path, state, now.timestamp())
    if on:
        return "Heads-up alerts are on. I'll speak up once when something matters, but not between 10 PM and 7 AM."
    return "Heads-up alerts are off."


def log_heads_up(entry, log_path=None):
    """Append one JSON line. A suppressed money line is logged without its words."""
    path = log_path or config.HEADS_UP_LOG_PATH
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except OSError:
        return False


# ---------- checks (existing Jev reads only) ----------

def _travel_minutes(origin, destination, when):
    from .travel import expected_travel_seconds
    try:
        travel = expected_travel_seconds(origin, destination, when, depart=True)
    except Exception:
        return None
    if travel is None:
        return None
    return max(1, int(round(float(travel) / 60.0)))


def _load_events(now, events):
    if events is not None:
        return events
    from .calendar_shift import _load_plain_events
    from .shift_override import events_with_overrides
    horizon = now + timedelta(days=1)
    loaded = _load_plain_events(now - timedelta(hours=18), horizon)
    if isinstance(loaded, str):
        return []
    try:
        loaded, _error = events_with_overrides(loaded, now, horizon)
    except Exception:
        pass
    return loaded or []


def _is_brea(ev):
    return re.search(r"\bbrea\b", f"{ev.get('title', '')} {ev.get('place', '')}", re.I) is not None


def _is_shift(ev):
    from .calendar_shift import is_shift_title
    try:
        return bool(is_shift_title(ev.get("title", "")))
    except Exception:
        return False


def calendar_check(now, events=None, travel=None):
    """The next timed event starting within HEADS_UP_EVENT_MINUTES.

    A Brea shift adds how much traffic adds over the typical drive.
    """
    travel = travel or _travel_minutes
    window = int(config.HEADS_UP_EVENT_MINUTES)
    found = []
    for ev in _load_events(now, events):
        if ev.get("all_day") or not ev.get("start"):
            continue
        left = (ev["start"] - now).total_seconds() / 60.0
        if left <= 0 or left > window:
            continue
        found.append((ev["start"], ev, int(round(left))))
    if not found:
        return []
    found.sort(key=lambda item: item[0])
    start, ev, left = found[0]
    title = (ev.get("title") or "an event").strip()
    unit = "minute" if left == 1 else "minutes"
    if _is_shift(ev) and _is_brea(ev):
        line = f"Your shift at Brea starts in {left} {unit}"
        drive = travel(config.HOME_ADDRESS, config.BREA_STORE_ADDRESS, now)
        extra = None if drive is None else drive - int(config.LEAVE_TYPICAL_DRIVE_MINUTES)
        if extra is not None and extra >= int(config.HEADS_UP_TRAFFIC_MINUTES):
            line += f" and traffic adds {extra}"
        line += "."
    else:
        line = f"{title} starts in {left} {unit}."
    return [{"id": f"cal|{start.isoformat()}|{title}", "kind": "calendar", "line": line}]


def hazard_check(now, collect=None):
    """New nearby fires or earthquakes from the hazard watch's own read."""
    from .hazards import alert_line, collect_hazards
    collect = collect or collect_hazards
    try:
        result = collect(now=now.timestamp(), locate=True)
    except Exception:
        return []
    events = [e for e in (result or {}).get("events") or [] if e.get("id")]
    out = []
    for event in events:
        line = alert_line([event], now.timestamp())
        if line:
            out.append({"id": f"hazard|{event['id']}", "kind": "hazard", "line": line})
    return out


def eta_home_check(now, events=None, travel=None, origin=None):
    """After a shift ends, speak up when traffic home is HEADS_UP_TRAFFIC_MINUTES over typical."""
    travel = travel or _travel_minutes
    recent = None
    for ev in _load_events(now, events):
        end = ev.get("end")
        if not end or not _is_shift(ev):
            continue
        since = (now - end).total_seconds() / 60.0
        if 0 <= since <= int(config.HEADS_UP_HOME_WINDOW_MINUTES):
            if recent is None or end > recent["end"]:
                recent = ev
    if recent is None:
        return []
    if origin is None:
        try:
            from .travel import current_coordinate
            origin = current_coordinate()
        except Exception:
            origin = None
    if origin is None:
        origin = config.BREA_STORE_ADDRESS
    try:
        from .leave import read_home_address
        home, _exact = read_home_address()
    except Exception:
        home = config.HOME_ADDRESS
    minutes = travel(origin, home, now)
    if minutes is None:
        return []
    extra = minutes - int(config.LEAVE_TYPICAL_DRIVE_MINUTES)
    if extra < int(config.HEADS_UP_TRAFFIC_MINUTES):
        return []
    return [{
        "id": f"home|{recent['end'].isoformat()}",
        "kind": "eta_home",
        "line": f"Heads up: about {minutes} minutes to get home right now. Traffic adds {extra}.",
    }]


DEFAULT_CHECKS = (calendar_check, hazard_check, eta_home_check)


# ---------- engine ----------

def set_heads_up_quiet_probe(fn):
    global _quiet_probe
    with _state_lock:
        _quiet_probe = fn


def _probe_quiet():
    probe = _quiet_probe
    if probe is None:
        return False
    try:
        return bool(probe())
    except Exception:
        return False


def run_heads_up_once(deliver, now=None, checks=None, state_path=None, log_path=None, quiet=None):
    """One pass. Speaks at most one alert. Returns the line spoken, or None.

    `deliver(line)` returns True when the user was told; only then is the id
    marked and the rate-limit clock reset.
    """
    now = now or datetime.now().astimezone()
    path = state_path or config.HEADS_UP_STATE_PATH
    if not heads_up_enabled(path):
        return None
    if in_quiet_hours(now):
        return None
    if quiet is None:
        quiet = _probe_quiet()
    if quiet:
        return None
    state = load_heads_up_state(path)
    now_ts = now.timestamp()
    gap = int(config.HEADS_UP_MIN_GAP_MINUTES) * 60
    if state["last_spoken"] is not None and now_ts - state["last_spoken"] < gap:
        return None
    for check in (DEFAULT_CHECKS if checks is None else checks):
        try:
            alerts = check(now) or []
        except Exception:
            continue
        for alert in alerts:
            ident = str(alert.get("id") or "")
            line = str(alert.get("line") or "").strip()
            if not ident or not line or ident in state["spoken"]:
                continue
            if mentions_money(line):
                with _state_lock:
                    fresh = load_heads_up_state(path)
                    fresh["spoken"][ident] = now_ts
                    _write_state(path, fresh, now_ts)
                log_heads_up({"time": now.isoformat(timespec="seconds"), "id": ident,
                              "kind": alert.get("kind"), "result": "suppressed_money"}, log_path)
                state["spoken"][ident] = now_ts
                continue
            try:
                told = bool(deliver(line))
            except Exception:
                told = False
            if not told:
                return None
            with _state_lock:
                fresh = load_heads_up_state(path)
                fresh["spoken"][ident] = now_ts
                fresh["last_spoken"] = now_ts
                _write_state(path, fresh, now_ts)
            log_heads_up({"time": now.isoformat(timespec="seconds"), "id": ident,
                          "kind": alert.get("kind"), "result": "spoken", "line": line}, log_path)
            return line
    return None


def start_heads_up_thread(deliver, quiet_check=None):
    """Poll on a daemon thread. macOS only. No listening socket."""
    if sys.platform != "darwin":
        return None
    if quiet_check is not None:
        set_heads_up_quiet_probe(quiet_check)

    def loop():
        while True:
            try:
                run_heads_up_once(deliver)
            except Exception as exc:
                print(f"  heads-up: {type(exc).__name__}")
            time.sleep(max(1, int(config.HEADS_UP_POLL_SECONDS)))

    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return _thread
        _thread = threading.Thread(target=loop, name="jev-heads-up", daemon=True)
        _thread.start()
        return _thread
