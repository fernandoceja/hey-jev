"""When to leave for a Brea shift. The drive is MapKit, then a config estimate."""
from datetime import datetime, timedelta
import re
from . import config
from .calendar_shift import _load_plain_events, is_shift_title
from .shift_override import events_with_overrides
from .textutil import _clock, _day_phrase, _hours_minutes
from .travel import expected_travel_seconds


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


def speak_leave_time(now=None, path=None, events=None):
    """Leave time for the next shift. Brea uses MapKit, then the typical drive.

    `events` skips the calendar read. Tests pass a list. Omit it to read
    EventKit the same way the other shift answers do, then apply overrides.
    """
    now = now or datetime.now().astimezone()
    horizon = now + timedelta(days=config.SHIFT_HORIZON_DAYS)
    if events is None:
        loaded = _load_plain_events(now - timedelta(hours=18), horizon)
    else:
        loaded = events
    loaded, error = events_with_overrides(loaded, now, horizon, path=path)
    if error and not loaded:
        return error
    shift, started = _next_shift(loaded, now, horizon)
    if shift is None:
        return "I don't see a shift to leave for."
    place = shift.get("place") or shift.get("title") or "work"
    if started:
        if _is_brea(shift):
            return f"Your Brea shift already started at {_clock(shift['start'])}."
        return f"You're already on {shift['title']}."
    if not _is_brea(shift):
        return (
            f"Your next shift is {shift['title']} {_day_phrase(shift['start'], now)} "
            f"at {_clock(shift['start'])}. I only have a drive time from home to Brea."
        )
    try:
        travel = expected_travel_seconds(
            config.HOME_ADDRESS, config.BREA_STORE_ADDRESS, shift["start"])
    except Exception:
        travel = None
    estimate = travel is None
    if estimate:
        travel_minutes = int(config.LEAVE_TYPICAL_DRIVE_MINUTES)
    else:
        travel_minutes = max(1, int(round(travel / 60.0)))
    buffer = int(config.LEAVE_BUFFER_MINUTES)
    leave = _leave_at(shift["start"], travel_minutes, buffer)
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
    if estimate:
        return f"{head} I'm using a typical drive of {drive} as an estimate, plus a buffer of {cushion}."
    return f"{head} The drive is about {drive}, plus a buffer of {cushion}."
