"""When to leave for a Brea shift. The drive is MapKit, then a config estimate."""
from datetime import datetime, timedelta
import re
from . import config
from .calendar_shift import _load_plain_events, is_shift_title
from .shift_override import events_with_overrides
from .textutil import _clock, _day_phrase, _hours_minutes
from .travel import current_coordinate, expected_travel_seconds


def _is_brea(ev):
    blob = f"{ev.get('title', '')} {ev.get('place', '')}"
    return re.search(r"\bbrea\b", blob, re.I) is not None


def _next_shift(events, now, horizon):
    """(event, already_started). A future shift wins over one already underway."""
    future, started = [], []
    for ev in events:
        if not is_shift_title(ev.get("title", "")):
            continue
        if ev["end"] <= now or ev["start"] > horizon:
            continue
        if ev["start"] <= now:
            started.append(ev)
        else:
            future.append(ev)
    future.sort(key=lambda ev: ev["start"])
    if future:
        return future[0], False
    if started:
        started.sort(key=lambda ev: ev["start"])
        return started[-1], True
    return None, False


def _leave_at(shift_start, travel_minutes, buffer_minutes):
    return shift_start - timedelta(minutes=travel_minutes + buffer_minutes)


def _minutes_from_travel(travel):
    """(minutes, estimate). None from MapKit is the typical drive."""
    if travel is None:
        return int(config.LEAVE_TYPICAL_DRIVE_MINUTES), True
    return max(1, int(round(float(travel) / 60.0))), False


def _shift_context(now, path, events):
    """The next shift, with overrides applied. This does not ask MapKit.

    `events` skips the calendar read. Tests pass a list. Omit it to read
    EventKit the same way the other shift answers do, then apply overrides.
    """
    horizon = now + timedelta(days=config.SHIFT_HORIZON_DAYS)
    if events is None:
        loaded = _load_plain_events(now - timedelta(hours=18), horizon)
    else:
        loaded = events
    loaded, error = events_with_overrides(loaded, now, horizon, path=path)
    plan = {
        "shift": None,
        "started": False,
        "brea": False,
        "error": None,
        "place": "",
    }
    if error and not loaded:
        plan["error"] = error
        return plan
    shift, started = _next_shift(loaded, now, horizon)
    if shift is None:
        return plan
    plan["shift"] = shift
    plan["started"] = started
    plan["place"] = shift.get("place") or shift.get("title") or "work"
    plan["brea"] = _is_brea(shift)
    return plan


def describe_leave(now=None, path=None, events=None):
    """The next leave, for the spoken answer and the proactive nudge.

    `events` skips the calendar read. Tests pass a list. Omit it to read
    EventKit the same way the other shift answers do, then apply overrides.
    MapKit is asked only for a future Brea shift. A started shift and any
    other store do not request a drive time.
    """
    now = now or datetime.now().astimezone()
    found = _shift_context(now, path, events)
    plan = {
        "shift": found["shift"],
        "started": found["started"],
        "brea": found["brea"],
        "error": found["error"],
        "travel_minutes": None,
        "estimate": False,
        "buffer": int(config.LEAVE_BUFFER_MINUTES),
        "leave": None,
        "place": found["place"],
    }
    if plan["error"] and plan["shift"] is None:
        return plan
    if plan["shift"] is None or plan["started"] or not plan["brea"]:
        return plan
    try:
        travel = expected_travel_seconds(
            config.HOME_ADDRESS, config.BREA_STORE_ADDRESS, plan["shift"]["start"])
    except Exception:
        travel = None
    minutes, estimate = _minutes_from_travel(travel)
    plan["travel_minutes"] = minutes
    plan["estimate"] = estimate
    plan["leave"] = _leave_at(plan["shift"]["start"], minutes, plan["buffer"])
    return plan


def speak_leave_time(now=None, path=None, events=None):
    """Leave time for the next shift. Brea uses MapKit, then the typical drive.

    The numbers come from describe_leave, which the leave nudge uses too.
    """
    now = now or datetime.now().astimezone()
    plan = describe_leave(now=now, path=path, events=events)
    if plan["error"] and plan["shift"] is None:
        return plan["error"]
    shift = plan["shift"]
    if shift is None:
        return "I don't see a shift to leave for."
    place = plan["place"]
    if plan["started"]:
        if plan["brea"]:
            return f"Your Brea shift already started at {_clock(shift['start'])}."
        return f"You're already on {shift['title']}."
    if not plan["brea"]:
        return (
            f"Your next shift is {shift['title']} {_day_phrase(shift['start'], now)} "
            f"at {_clock(shift['start'])}. I only have a drive time from home to Brea."
        )
    travel_minutes = plan["travel_minutes"]
    buffer = plan["buffer"]
    leave = plan["leave"]
    drive = _hours_minutes(travel_minutes)
    cushion = _hours_minutes(buffer)
    when = _day_phrase(shift["start"], now)
    start_clock = _clock(shift["start"])
    if leave <= now:
        head = f"Leave now for your {start_clock} start at {place}"
        if when != "today":
            head += f" {when}"
        head += "."
    else:
        head = f"Leave by {_clock(leave)} for your {start_clock} start at {place}"
        if when != "today":
            head += f" {when}"
        head += "."
    if plan["estimate"]:
        return f"{head} I'm using a typical drive of {drive} as an estimate, plus a buffer of {cushion}."
    return f"{head} The drive is about {drive}, plus a buffer of {cushion}."


def _shift_gap(now, arrive, path, events):
    """Early or late against a shift today that has not started. Else ''."""
    found = _shift_context(now, path, events)
    shift = found["shift"]
    if shift is None or found["started"]:
        return ""
    start = shift["start"]
    if start.date() != now.date():
        return ""
    delta = int(round((start - arrive).total_seconds() / 60.0))
    start_clock = _clock(start)
    if delta > 0:
        return f"Your shift starts at {start_clock}, so you'd be about {_hours_minutes(delta)} early."
    if delta < 0:
        return f"Your shift starts at {start_clock}, so you'd be about {_hours_minutes(-delta)} late."
    return f"Your shift starts at {start_clock}, so you'd be right on time."


def read_home_address(path=None):
    """(address, exact). exact is True when the local file has one line.

    The address is for MapKit only. Say "home". Never log or speak the line.
    A missing, unreadable, or blank file is HOME_ADDRESS ("Upland, CA").
    """
    target = config.HOME_ADDRESS_PATH if path is None else path
    try:
        with open(target, encoding="utf-8") as handle:
            line = handle.readline().strip()
    except OSError:
        return config.HOME_ADDRESS, False
    if not line:
        return config.HOME_ADDRESS, False
    return line, True


def _hide_street(spoken, address, exact):
    """Drop a street if one ever lands in the words we say."""
    if not exact or not address or len(address) < 8:
        return spoken
    if address.lower() not in spoken.lower():
        return spoken
    return re.sub(re.escape(address), "home", spoken, flags=re.I)


def _with_home_hint(spoken, exact):
    if exact:
        return spoken
    return f"{spoken} {config.HOME_EXACT_HINT}"


def speak_eta_choice():
    """Bare ETA. Work and home are both real answers, so this does not guess.

    The next phrase is "ETA work" or "ETA home". A one-word "home" is left
    alone so it is not confused with the Home app.
    """
    return "Work or home?"


def speak_eta_to_work(now=None, path=None, events=None, home_path=None):
    """How long the drive to work is if you leave now.

    MapKit is asked for a departure of now, from home to the Brea store.
    Home is the one line in home-address.txt when that file exists. Otherwise
    it is HOME_ADDRESS, and the reply says to set the file.
    A missing or failed MapKit result uses the typical drive and says so.
    A shift today that has not started, including a saved override, adds
    whether that arrival is early or late. A started shift, or none today,
    skips that part.
    """
    now = now or datetime.now().astimezone()
    origin, exact = read_home_address(home_path)
    try:
        travel = expected_travel_seconds(
            origin, config.BREA_STORE_ADDRESS, now, depart=True)
    except Exception:
        travel = None
    minutes, estimate = _minutes_from_travel(travel)
    arrive = now + timedelta(minutes=minutes)
    drive = _hours_minutes(minutes)
    arrival = _clock(arrive)
    if estimate:
        spoken = (
            f"About {drive} to work right now. "
            f"I'm using a typical drive of {drive} as an estimate. "
            f"You'd get there around {arrival}."
        )
    else:
        spoken = f"About {drive} to work right now. You'd get there around {arrival}."
    gap = _shift_gap(now, arrive, path, events)
    if gap:
        spoken = f"{spoken} {gap}"
    return _hide_street(_with_home_hint(spoken, exact), origin, exact)


def speak_eta_home(now=None, home_path=None, origin=None, locate=True):
    """How long the drive home is if you leave now.

    The start is this Mac's location when `locate` finds one. Otherwise it is
    the Brea store, and the reply says so. The lookup waits a few seconds on
    a side thread, so a location permission panel cannot hold the command
    turn. The end is home-address.txt, or HOME_ADDRESS when that file is
    missing. The street is not spoken. `origin` skips the location lookup.
    Tests pass a coordinate or None.
    """
    now = now or datetime.now().astimezone()
    home, exact = read_home_address(home_path)
    if origin is None and locate:
        try:
            origin = current_coordinate()
        except Exception:
            origin = None
    from_here = origin is not None
    if origin is None:
        origin = config.BREA_STORE_ADDRESS
    try:
        travel = expected_travel_seconds(origin, home, now, depart=True)
    except Exception:
        travel = None
    minutes, estimate = _minutes_from_travel(travel)
    arrive = now + timedelta(minutes=minutes)
    drive = _hours_minutes(minutes)
    arrival = _clock(arrive)
    if estimate:
        spoken = (
            f"About {drive} to get home right now. "
            f"I'm using a typical drive of {drive} as an estimate. "
            f"You'd get there around {arrival}."
        )
    else:
        spoken = f"About {drive} to get home right now. You'd get there around {arrival}."
    if not from_here:
        spoken += " I'm starting from the Brea store, since I can't see where this Mac is."
    return _hide_street(_with_home_hint(spoken, exact), home, exact)
