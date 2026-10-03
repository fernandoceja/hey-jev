"""Read-only EventKit calendar, shifts, and Zoe's day."""
from datetime import datetime, timedelta
import re
import threading
import time
from .config import SHIFT_HORIZON_DAYS, SHIFT_TITLE_PATTERNS, ZOE_EVENT_RE
from .textutil import _clock, _day_phrase, _hours_minutes, _in_how_long, _join_names

_store = None
_calendar_granted = False


# --------------------------------------------------------------------------- Calendar (read-only EventKit)
_CAL_MISSING = "I can't read your calendar yet. Install the EventKit package and rebuild Hey Jev."
_CAL_DENIED = ("I don't have access to your calendar. Allow full calendar access for Hey Jev "
               "in System Settings, Privacy and Security, then ask me again.")
_CAL_FAILED = "I couldn't read your calendar just now."


def _import_eventkit():
    try:
        import EventKit
        import Foundation
    except ImportError:
        return None
    return EventKit, Foundation


def _event_store(EventKit):
    global _store
    if _store is None:
        _store = EventKit.EKEventStore.alloc().init()
    return _store


def _wait_for(done, seconds):
    """Wait for an EventKit completion without deadlocking the main thread.

    On the --text path this runs on the main thread, and the callback is delivered
    through the main run loop. Pump that loop. The voice thread can just wait.
    """
    if threading.current_thread() is not threading.main_thread():
        done.wait(seconds)
        return
    try:
        from Foundation import NSDate, NSRunLoop
    except ImportError:
        done.wait(seconds)
        return
    deadline = time.time() + seconds
    while not done.is_set() and time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))


def _request_full_access(EventKit, store):
    done, box = threading.Event(), {}

    def finish(*args):
        box["ok"] = bool(args[0]) if args else False
        done.set()

    # macOS 14+ (and 27, untested). The older call is only there if the symbol is missing.
    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(finish)
    else:
        store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeEvent, finish)
    _wait_for(done, 30)
    return box.get("ok", False)


def ensure_calendar_access():
    """True, False, or None when EventKit isn't installed.

    Full access is required. Write-only is treated as denied because we only read.
    """
    global _calendar_granted
    if _calendar_granted:
        return True
    imported = _import_eventkit()
    if imported is None:
        return None
    EventKit, _Foundation = imported
    status = int(EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeEvent))
    full = int(getattr(EventKit, "EKAuthorizationStatusFullAccess", 4))
    authorized = int(getattr(EventKit, "EKAuthorizationStatusAuthorized", 3))
    denied = int(getattr(EventKit, "EKAuthorizationStatusDenied", 2))
    restricted = int(getattr(EventKit, "EKAuthorizationStatusRestricted", 1))
    write_only = int(getattr(EventKit, "EKAuthorizationStatusWriteOnly", 5))
    if status in (full, authorized):
        _calendar_granted = True
        return True
    if status in (denied, restricted, write_only):
        return False
    granted = _request_full_access(EventKit, _event_store(EventKit))
    _calendar_granted = bool(granted)
    return _calendar_granted


def _nsdate(Foundation, when):
    return Foundation.NSDate.dateWithTimeIntervalSince1970_(when.timestamp())


def _stamp(nsdate):
    return datetime.fromtimestamp(nsdate.timeIntervalSince1970()).astimezone()


def _title(ev):
    title = ev.title()
    return str(title).strip() if title else "Untitled event"


def _all_day(ev):
    try:
        return bool(ev.isAllDay())
    except Exception:
        return False


def _cancelled(EventKit, ev):
    try:
        return int(ev.status()) == int(getattr(EventKit, "EKEventStatusCanceled", 2))
    except Exception:
        return False


def _events_between(start, end):
    imported = _import_eventkit()
    if imported is None:
        raise RuntimeError("EventKit is not installed")
    EventKit, Foundation = imported
    store = _event_store(EventKit)
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        _nsdate(Foundation, start), _nsdate(Foundation, end), None)
    found = []
    for ev in store.eventsMatchingPredicate_(predicate) or []:
        if _cancelled(EventKit, ev):
            continue
        found.append(ev)
    found.sort(key=lambda ev: ev.startDate().timeIntervalSince1970())
    return found


def _calendar_problem():
    access = ensure_calendar_access()
    if access is None:
        return _CAL_MISSING
    if not access:
        return _CAL_DENIED
    return None


def _upcoming(events, now, horizon, skip_all_day):
    picked = []
    for ev in events:
        if skip_all_day and _all_day(ev):
            continue
        start, finish = _stamp(ev.startDate()), _stamp(ev.endDate())
        if finish <= now or start > horizon:
            continue
        picked.append(ev)
    return picked


def speak_next_event():
    problem = _calendar_problem()
    if problem:
        return problem
    now = datetime.now().astimezone()
    horizon = now + timedelta(days=SHIFT_HORIZON_DAYS)
    try:
        events = _upcoming(_events_between(now - timedelta(hours=12), horizon), now, horizon, skip_all_day=True)
    except Exception:
        return _CAL_FAILED
    if not events:
        return "Nothing coming up on your calendar."
    ev = events[0]
    title, start, finish = _title(ev), _stamp(ev.startDate()), _stamp(ev.endDate())
    if start <= now:
        return f"Now: {title}, until {_clock(finish)}."
    return f"Next up: {title} at {_clock(start)}, {_in_how_long(start, now)}."


def speak_today_schedule():
    problem = _calendar_problem()
    if problem:
        return problem
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    try:
        events = _events_between(start, end)
    except Exception:
        return _CAL_FAILED
    all_day, timed = [], []
    for ev in events:
        finish = _stamp(ev.endDate())
        if finish <= now and not _all_day(ev):
            continue
        if _all_day(ev):
            all_day.append(_title(ev))
        else:
            timed.append(f"{_title(ev)} at {_clock(_stamp(ev.startDate()))}")
    if not all_day and not timed:
        return "Your calendar is clear today."
    shown, extra = timed[:6], max(0, len(timed) - 6)
    timed_line = _join_names(shown) + (f", and {extra} more" if extra else "")
    if all_day and timed_line:
        return f"All day: {_join_names(all_day)}. Today you've got {timed_line}."
    if all_day:
        return f"All day: {_join_names(all_day)}."
    return f"Today you've got {timed_line}."


def is_shift_title(title):
    """True when a calendar title looks like a work shift. Patterns are SHIFT_TITLE_PATTERNS."""
    text = title or ""
    return any(re.search(pattern, text, re.I) for pattern in SHIFT_TITLE_PATTERNS)


def speak_next_shift():
    """Next event in 14 days whose title matches a shift pattern."""
    problem = _calendar_problem()
    if problem:
        return problem
    now = datetime.now().astimezone()
    horizon = now + timedelta(days=SHIFT_HORIZON_DAYS)
    try:
        events = _upcoming(_events_between(now - timedelta(hours=12), horizon), now, horizon, skip_all_day=False)
    except Exception:
        return _CAL_FAILED
    shifts = [ev for ev in events if is_shift_title(_title(ev))]
    if not shifts:
        return "No shift in the next two weeks."
    ev = shifts[0]
    title, start, finish = _title(ev), _stamp(ev.startDate()), _stamp(ev.endDate())
    if _all_day(ev):
        return f"Your next shift is {title} {_day_phrase(start, now)}, all day."
    if start <= now:
        return f"You're on {title} until {_clock(finish)}."
    return f"Your next shift is {title} {_day_phrase(start, now)} at {_clock(start)}."


def _calendar_name(ev):
    try:
        calendar = ev.calendar()
        if calendar is None:
            return ""
        return str(calendar.title() or "")
    except Exception:
        return ""


def speak_zoe_tomorrow():
    """Tomorrow's events whose title or calendar mentions Zoe, school, or Cabrillo."""
    problem = _calendar_problem()
    if problem:
        return problem
    now = datetime.now().astimezone()
    start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    try:
        events = _events_between(start, end)
    except Exception:
        return _CAL_FAILED
    picked = []
    for ev in events:
        blob = f"{_title(ev)} {_calendar_name(ev)}"
        if ZOE_EVENT_RE.search(blob):
            picked.append(ev)
    if not picked:
        return "Zoe has nothing tomorrow."
    parts = []
    for ev in picked[:6]:
        title = _title(ev)
        if _all_day(ev):
            parts.append(f"{title}, all day")
        else:
            parts.append(f"{title} at {_clock(_stamp(ev.startDate()))}")
    extra = len(picked) - len(parts)
    line = "Tomorrow Zoe has " + _join_names(parts) + "."
    if extra:
        line += f" And {extra} more."
    return line


def _plain_event(ev):
    return {
        "title": _title(ev),
        "start": _stamp(ev.startDate()),
        "end": _stamp(ev.endDate()),
        "all_day": _all_day(ev),
        "calendar": _calendar_name(ev),
    }


def _load_plain_events(start, end):
    """A list of plain event dicts, or a spoken error string."""
    problem = _calendar_problem()
    if problem:
        return problem
    try:
        return [_plain_event(ev) for ev in _events_between(start, end)]
    except Exception:
        return _CAL_FAILED


def weekend_bounds(now):
    """Saturday and Sunday of this weekend. On Sunday, Saturday is yesterday."""
    day = now.date()
    weekday = day.weekday()  # Monday is 0
    if weekday == 6:
        saturday = day - timedelta(days=1)
    else:
        saturday = day + timedelta(days=(5 - weekday))
    return saturday, saturday + timedelta(days=1)


def _covers_day(ev, day):
    start = ev["start"].date()
    if ev.get("all_day"):
        return start == day
    end = ev["end"]
    end_day = end.date()
    if end.hour == 0 and end.minute == 0 and end_day > start:
        end_day = end_day - timedelta(days=1)
    return start <= day <= end_day


def describe_work_weekend(events, now):
    saturday, sunday = weekend_bounds(now)
    found = []
    for ev in events:
        if not is_shift_title(ev.get("title", "")):
            continue
        if _covers_day(ev, saturday) or _covers_day(ev, sunday):
            found.append(ev)
    if not found:
        return "You're not working this weekend."
    found.sort(key=lambda ev: ev["start"])
    parts = []
    for ev in found[:4]:
        when = ev["start"]
        if when.date() == saturday:
            day_name = "Saturday"
        elif when.date() == sunday:
            day_name = "Sunday"
        else:
            day_name = when.strftime("%A")
        if ev.get("all_day"):
            parts.append(f"{day_name}, {ev['title']}, all day")
        else:
            parts.append(f"{day_name}, {ev['title']} at {_clock(when)}")
    return "You're working this weekend: " + _join_names(parts) + "."


def describe_shift_length(events, now):
    horizon = now + timedelta(days=SHIFT_HORIZON_DAYS)
    upcoming = []
    for ev in events:
        if not is_shift_title(ev.get("title", "")):
            continue
        if ev["end"] <= now or ev["start"] > horizon:
            continue
        upcoming.append(ev)
    upcoming.sort(key=lambda ev: ev["start"])
    if not upcoming:
        return "No shift in the next two weeks."
    ev = upcoming[0]
    start, end = ev["start"], ev["end"]
    title = ev["title"]
    if ev.get("all_day"):
        return f"Your next shift, {title}, is all day {_day_phrase(start, now)}."
    span = _hours_minutes(int(round((end - start).total_seconds() / 60.0)))
    if start <= now:
        left = _hours_minutes(int(round((end - now).total_seconds() / 60.0)))
        return f"This shift, {title}, is {span}, until {_clock(end)}. About {left} left."
    return (
        f"Your next shift, {title}, is {span}, {_day_phrase(start, now)} "
        f"from {_clock(start)} to {_clock(end)}."
    )


def speak_working_weekend():
    now = datetime.now().astimezone()
    saturday, sunday = weekend_bounds(now)
    start = datetime.combine(saturday, datetime.min.time()).astimezone()
    end = datetime.combine(sunday + timedelta(days=1), datetime.min.time()).astimezone()
    loaded = _load_plain_events(start, end)
    if isinstance(loaded, str):
        return loaded
    return describe_work_weekend(loaded, now)


def speak_shift_length():
    now = datetime.now().astimezone()
    horizon = now + timedelta(days=SHIFT_HORIZON_DAYS)
    loaded = _load_plain_events(now - timedelta(hours=18), horizon)
    if isinstance(loaded, str):
        return loaded
    return describe_shift_length(loaded, now)
