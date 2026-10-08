"""Proactive leave nudge. Mac-only, and only for the next Brea shift.

The leave time is describe_leave: the same EventKit read, the same overrides,
and the same MapKit drive (or the typical-drive fallback). This module does
not open a socket, does not add a bridge command, and does not read a secret.
MapKit needs no key. There is no third-party traffic lookup.

Each shift gets at most one pre-warning and one "leave now". Those flags live
in a local JSON file so a restart does not say them again. A shift that has
already started is never nudged. While the Mac is muted, a focus timer is
running, notifications were silenced from Jev, or the delivery says it could
not speak, the flag is left unset so a later pass can still fire once.
"""
from datetime import datetime, timedelta
import json
import os
import re
import sys
import threading
import time

from . import config
from .leave import describe_leave
from .shell import _run

_state_lock = threading.Lock()
_thread_lock = threading.Lock()
_thread = None
_hold_notifications = False
_quiet_probe = None

_NOTIFY_SCRIPT = (
    'on run argv\n'
    'display notification (item 1 of argv) with title "Hey Jev"\n'
    'end run'
)


def shift_key(shift):
    """Stable id for one shift. A new start time is a new shift."""
    title = shift.get("title") or ""
    place = shift.get("place") or ""
    return f"{shift['start'].isoformat()}|{title}|{place}"


def nudge_place(shift):
    """Short place for the banner. A Brea title with no place field says Brea."""
    place = (shift.get("place") or "").strip()
    if place:
        return place
    title = shift.get("title") or "work"
    if re.search(r"\bbrea\b", title, re.I):
        return "Brea"
    return title


def _nudge_clock(when):
    hour = int(when.strftime("%I"))
    return f"{hour}:{when.minute:02d} {when.strftime('%p')}"


def nudge_text(kind, plan, now):
    """The line Jev speaks and puts on the notification."""
    shift = plan["shift"]
    start_clock = _nudge_clock(shift["start"])
    place = nudge_place(shift)
    drive = f"~{plan['travel_minutes']} min"
    if plan["estimate"]:
        drive += " estimate"
    tail = f"drive {drive} + {plan['buffer']} min buffer"
    if kind == "now":
        head = f"Leave now for your {start_clock} start at {place}"
    else:
        left = int(round((plan["leave"] - now).total_seconds() / 60.0))
        left = max(1, left)
        unit = "minute" if left == 1 else "minutes"
        head = f"Leave in {left} {unit} for your {start_clock} start at {place}"
    return f"{head} — {tail}"


def load_leave_state(path=None):
    """{enabled: True/False/None, fired: {shift_key: {prewarn, now}}}.

    A missing or broken file means no saved choice and nothing fired yet.
    """
    path = path or config.LEAVE_NUDGE_STATE_PATH
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {"enabled": None, "fired": {}}
    if not isinstance(data, dict):
        return {"enabled": None, "fired": {}}
    enabled = data.get("enabled", None)
    if enabled is not None:
        enabled = bool(enabled)
    fired = {}
    raw = data.get("fired") or {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            fired[key] = {
                "prewarn": bool(value.get("prewarn")),
                "now": bool(value.get("now")),
            }
    return {"enabled": enabled, "fired": fired}


def _prune_fired(fired, now):
    cutoff = now - timedelta(days=2)
    kept = {}
    for key, value in fired.items():
        stamp = key.split("|", 1)[0]
        try:
            start = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if start.tzinfo is None and cutoff.tzinfo is not None:
            start = start.replace(tzinfo=cutoff.tzinfo)
        if start >= cutoff:
            kept[key] = value
    return kept


def _write_state(path, state, now):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    payload = {
        "fired": _prune_fired(state.get("fired") or {}, now),
    }
    if state.get("enabled") is not None:
        payload["enabled"] = bool(state["enabled"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def leave_reminders_enabled(path=None):
    """Saved choice, or LEAVE_REMINDERS_ENABLED when nothing is saved."""
    state = load_leave_state(path)
    if state["enabled"] is None:
        return bool(config.LEAVE_REMINDERS_ENABLED)
    return bool(state["enabled"])


def set_leave_reminders(on, path=None):
    """Turn the proactive nudge on or off and say so. Fired flags stay."""
    path = path or config.LEAVE_NUDGE_STATE_PATH
    now = datetime.now().astimezone()
    with _state_lock:
        state = load_leave_state(path)
        state["enabled"] = bool(on)
        _write_state(path, state, now)
    if on:
        return "Leave reminders are on. I'll nudge you before the next Brea shift."
    return "Leave reminders are off."


def hold_leave_nudges(on):
    """Remember a spoken silence-notifications / do-not-disturb toggle.

    This is the in-process flag for Jev's own command. It is cleared by
    "turn off do not disturb". A restart forgets it. Volume mute and a
    running focus timer are checked separately.
    """
    global _hold_notifications
    with _state_lock:
        _hold_notifications = bool(on)


def notifications_held():
    return _hold_notifications


def set_leave_quiet_probe(fn):
    """Callable used by the live scheduler. Tests leave this unset."""
    global _quiet_probe
    with _state_lock:
        _quiet_probe = fn


def quiet_now():
    """True when a nudge should wait instead of firing.

    Silence-notifications holds the nudge. The live probe reports a muted
    Mac or a running focus timer. If that probe raises, this is not quiet:
    a failed read must not hide the reminder forever.
    """
    if _hold_notifications:
        return True
    probe = _quiet_probe
    if probe is None:
        return False
    try:
        return bool(probe())
    except Exception:
        return False


def mac_output_muted(runner=None):
    """True when the Mac output is muted. A failed read is not muted."""
    run = runner or _run
    try:
        out = run(("osascript", "-e", "output muted of (get volume settings)"))
    except Exception:
        return False
    return str(out or "").strip().lower() == "true"


def _due_kind(now, plan, fired, prewarn_minutes):
    if plan["shift"] is None or plan["started"] or not plan["brea"]:
        return None
    leave = plan["leave"]
    if leave is None or now >= plan["shift"]["start"]:
        return None
    done = fired.get(shift_key(plan["shift"])) or {}
    if now >= leave:
        if done.get("now"):
            return None
        return "now"
    if prewarn_minutes <= 0:
        return None
    prewarn_at = leave - timedelta(minutes=prewarn_minutes)
    if now >= prewarn_at and not done.get("prewarn"):
        return "prewarn"
    return None


def due_leave_nudges(now, path=None, events=None, state_path=None, quiet=False,
                     prewarn_minutes=None, plan=None):
    """Nudges that should fire at `now`. Does not write the fired file.

    Each item is {kind, line, shift_key}. Quiet, disabled, a started shift,
    a non-shift, and a non-Brea shift return nothing. A leave-now that is
    already due skips the pre-warning so a late wake does not say both.
    """
    if quiet or not leave_reminders_enabled(state_path):
        return []
    if prewarn_minutes is None:
        prewarn_minutes = int(config.LEAVE_PREWARN_MINUTES)
    if plan is None:
        plan = describe_leave(now=now, path=path, events=events)
    state = load_leave_state(state_path)
    kind = _due_kind(now, plan, state["fired"], int(prewarn_minutes))
    if kind is None:
        return []
    return [{
        "kind": kind,
        "line": nudge_text(kind, plan, now),
        "shift_key": shift_key(plan["shift"]),
    }]


def record_leave_nudge(shift_id, kind, state_path=None, now=None):
    """Remember that this kind already fired for this shift."""
    if kind not in ("prewarn", "now"):
        raise ValueError(kind)
    path = state_path or config.LEAVE_NUDGE_STATE_PATH
    now = now or datetime.now().astimezone()
    with _state_lock:
        state = load_leave_state(path)
        done = dict(state["fired"].get(shift_id) or {})
        done[kind] = True
        state["fired"][shift_id] = done
        _write_state(path, state, now)


def deliver_due_nudges(now, deliver, path=None, events=None, state_path=None,
                       quiet=None, prewarn_minutes=None, plan=None):
    """Speak due nudges. `deliver(line)` returns True when the user was told.

    A True result is recorded. Quiet, and a delivery that returns False,
    leave the record alone so a later pass can still fire once.
    """
    if quiet is None:
        quiet = quiet_now()
    if plan is None and not quiet and leave_reminders_enabled(state_path):
        plan = describe_leave(now=now, path=path, events=events)
    due = due_leave_nudges(
        now, path=path, events=events, state_path=state_path, quiet=quiet,
        prewarn_minutes=prewarn_minutes, plan=plan)
    spoken = []
    for item in due:
        try:
            told = bool(deliver(item["line"]))
        except Exception:
            told = False
        if not told:
            continue
        record_leave_nudge(item["shift_key"], item["kind"], state_path=state_path, now=now)
        spoken.append(item["line"])
    return spoken


def leave_poll_seconds(now, plan, enabled=True):
    """Seconds until the next calendar and drive check."""
    if not enabled:
        return int(config.LEAVE_POLL_CLOSE_SECONDS)
    leave = None if not plan else plan.get("leave")
    if leave is None or not plan.get("brea") or plan.get("started"):
        return int(config.LEAVE_POLL_FAR_SECONDS)
    minutes = (leave - now).total_seconds() / 60.0
    if minutes <= int(config.LEAVE_CLOSE_MINUTES):
        return int(config.LEAVE_POLL_CLOSE_SECONDS)
    if minutes <= int(config.LEAVE_NEAR_MINUTES):
        return int(config.LEAVE_POLL_NEAR_SECONDS)
    return int(config.LEAVE_POLL_FAR_SECONDS)


def run_leave_nudge_once(deliver, now=None, path=None, events=None, state_path=None,
                         quiet=None, prewarn_minutes=None):
    """One scheduler pass. Returns how long to wait before the next one.

    `events` skips EventKit. The live thread omits it and uses the same
    calendar read as the spoken leave answer.
    """
    now = now or datetime.now().astimezone()
    enabled = leave_reminders_enabled(state_path)
    if not enabled:
        return leave_poll_seconds(now, None, enabled=False)
    if quiet is None:
        quiet = quiet_now()
    plan = describe_leave(now=now, path=path, events=events)
    if not quiet:
        deliver_due_nudges(
            now, deliver, path=path, events=events, state_path=state_path,
            quiet=False, prewarn_minutes=prewarn_minutes, plan=plan)
    return leave_poll_seconds(now, plan, enabled=True)


def post_leave_notification(message, runner=None):
    """Show one macOS notification. The words are an argv item, not a script.

    Returns True when osascript accepts it. A failure is False so the caller
    can still try speech, and can skip the fired flag when both fail.
    """
    text = str(message or "").strip()
    if not text:
        return False
    run = runner or _run_notify
    try:
        result = run(["osascript", "-e", _NOTIFY_SCRIPT, text])
    except Exception:
        return False
    if result is None:
        return True
    return getattr(result, "returncode", 0) == 0


def _run_notify(args):
    import subprocess
    return subprocess.run(list(args), capture_output=True, text=True, timeout=15)


def start_leave_nudge_thread(deliver, quiet_check=None):
    """Poll on a daemon thread. Only on macOS. No listening socket.

    `deliver(line)` speaks and notifies. It returns True when the user was
    actually told. Off the Mac this returns None and starts nothing.
    """
    if sys.platform != "darwin":
        return None
    if quiet_check is not None:
        set_leave_quiet_probe(quiet_check)

    def loop():
        while True:
            delay = int(config.LEAVE_POLL_CLOSE_SECONDS)
            try:
                delay = run_leave_nudge_once(deliver)
            except Exception as exc:
                print(f"  leave nudge: {type(exc).__name__}")
            time.sleep(max(1, int(delay)))

    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return _thread
        _thread = threading.Thread(target=loop, name="jev-leave-nudge", daemon=True)
        _thread.start()
        return _thread
