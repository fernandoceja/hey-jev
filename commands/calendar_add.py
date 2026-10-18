"""Add one Apple Calendar event by voice, then read back what was saved.

"put Zoe's party on my calendar Saturday at 2", "add dentist to my calendar
tomorrow at 10 am", "schedule lunch with mom Friday at noon for 2 hours".

Same pattern as reminders.py: EventKit is the path that asks for Calendar
access, and AppleScript is only the fallback when that package is missing. The
title is an argv item, never pasted into the script. Nothing here opens a
socket or calls the network. Mac-only, and not on the iPhone bridge allowlist.
"""
from datetime import timedelta
import re
import threading
import time

from . import config
from .calendar_shift import _wait_for
from .reminders import _as_now, _peel_due, _task_text
from .shell import _run
from .textutil import _clean

_CMD_RE = re.compile(
    r"^(?:please\s+)?(?:can\s+you\s+|could\s+you\s+)?"
    r"(?P<verb>add|put|schedule|create|book|make)\s+(?P<body>.+?)(?:\s+please)?[.!?]*$",
    re.I,
)
_CAL_WORDS = re.compile(r"\s*\b(?:to|on|in|onto|into)\s+(?:my|the)\s+calendar\b\s*", re.I)
_EVENT_LEAD = re.compile(
    r"^(?:an?\s+)?(?:new\s+)?(?:calendar\s+)?(?:event|appointment|meeting)\s+(?:called\s+|named\s+|for\s+)?",
    re.I,
)
_DURATION = re.compile(
    r"\s+for\s+(?P<qty>half\s+an|an|a|one|two|three|four|\d+(?:\.\d+)?)\s+(?P<unit>hours?|hrs?|minutes?|mins?)\b",
    re.I,
)
# A bare "at 2" for an event means the afternoon. 8 to 12 stay morning.
_BARE_PM = re.compile(r"\bat\s+([1-7])(?::([0-5]\d))?\b(?!\s*(?:a\.?m\.?|p\.?m\.?|o'?clock\s+in\s+the\s+morning))", re.I)
_QTY = {"half an": 0.5, "an": 1, "a": 1, "one": 1, "two": 2, "three": 3, "four": 4}

CAL_DENIED = (
    "I don't have access to Calendar. Allow full access for Hey Jev "
    "in System Settings, Privacy and Security, Calendars, then ask me again."
)
CAL_AUTOMATION = (
    "I couldn't add the event. Allow Hey Jev to control Calendar "
    "in System Settings, Privacy and Security, Automation."
)
CAL_FAIL = "I couldn't add that event."
CAL_UNCLEAR = "Tell me what to put on your calendar and when."
CAL_NO_DEFAULT = "I couldn't find your default calendar."

_APPLESCRIPT = """on run argv
    set eventTitle to item 1 of argv
    set calName to item 2 of argv
    set isAllDay to item 3 of argv
    set startStamp to (item 4 of argv) as integer
    set minutesLong to (item 5 of argv) as integer
    set startDate to (current date)
    set epochDate to startDate - ((do shell script "date +%s") as integer)
    set startDate to epochDate + startStamp
    set endDate to startDate + (minutesLong * 60)
    tell application "Calendar"
        if calName is "" then
            set targetCal to first calendar whose writable is true
        else
            set targetCal to first calendar whose name is calName
        end if
        if isAllDay is "yes" then
            make new event at end of events of targetCal with properties {summary:eventTitle, start date:startDate, end date:endDate, allday event:true}
        else
            make new event at end of events of targetCal with properties {summary:eventTitle, start date:startDate, end date:endDate}
        end if
    end tell
end run"""

_access_granted = False
# "schedule dentist" asks when. The title waits here for one answer such as "tomorrow at 10".
PENDING_SECONDS = 60
_pending = {}
_WHEN_START = re.compile(
    r"^(?:today|tomorrow|tonight|at\s|on\s|this\s|next\s|in\s|noon|midnight|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)


def is_calendar_add_phrase(text):
    if parse_event_request(text) is not None:
        return True
    return _from_pending(text) is not None


def _arm_pending(parsed, clock=None):
    _pending.clear()
    _pending.update({"title": parsed["title"], "minutes": parsed["minutes"],
                     "until": (clock or time.monotonic)() + PENDING_SECONDS})


def clear_pending():
    _pending.clear()


def _from_pending(text, now=None, clock=None):
    """The event when this turn answers "When should I put X on your calendar?", else None."""
    if not _pending or (clock or time.monotonic)() > _pending["until"]:
        _pending.clear()
        return None
    raw = re.sub(r"\s+", " ", _clean(text or "")).strip().rstrip(".!?")
    if not _WHEN_START.match(raw):
        return None
    when = _BARE_PM.sub(lambda m: "at {0}{1} pm".format(m.group(1), ":" + m.group(2) if m.group(2) else ""), raw)
    title, start, all_day, spoken = _peel_due("{0} {1}".format(_pending["title"], when), _as_now(now))
    if start is None or _task_text(title) != _pending["title"]:
        return None
    minutes = 24 * 60 if all_day else _pending["minutes"]
    return {"title": _pending["title"], "start": start, "all_day": all_day,
            "minutes": minutes, "spoken_when": spoken}


def _minutes(match):
    qty = match.group("qty").lower()
    amount = _QTY.get(re.sub(r"\s+", " ", qty))
    if amount is None:
        try:
            amount = float(qty)
        except ValueError:
            return None
    unit = match.group("unit").lower()
    total = amount * (60 if unit.startswith("h") else 1)
    return int(round(total)) if total > 0 else None


def parse_event_request(text, now=None):
    """{title, start, all_day, minutes, spoken_when} or None when this is not an add-event phrase.

    A phrase needs "calendar", "event/appointment/meeting", or the verb
    "schedule", so "add milk" or "make a note" never land here. A phrase with no
    day or time returns a dict with start None, so the caller can ask when.
    """
    now = _as_now(now)
    raw = re.sub(r"\s+", " ", _clean(text or "")).strip()
    match = _CMD_RE.match(raw)
    if not match:
        return None
    verb, body = match.group("verb").lower(), match.group("body")
    has_cal = bool(_CAL_WORDS.search(body))
    has_event = bool(_EVENT_LEAD.match(body))
    if not (has_cal or has_event or verb == "schedule"):
        return None
    if re.match(r"^(?:a\s+)?(?:note|reminder|timer)\b", body, re.I):
        return None
    body = _CAL_WORDS.sub(" ", body).strip()
    stripped = _EVENT_LEAD.sub("", body).strip()
    if stripped and not _WHEN_START.match(stripped):
        body = stripped
    else:
        # "schedule meeting Friday at 2": "meeting" is the title, not a word to drop.
        body = re.sub(r"^(?:an?\s+)?(?:new\s+)?", "", body, flags=re.I).strip()
    minutes = int(config.CALENDAR_EVENT_MINUTES)
    dur = _DURATION.search(body)
    if dur:
        minutes = _minutes(dur) or minutes
        body = (body[:dur.start()] + body[dur.end():]).strip()
    body = _BARE_PM.sub(lambda m: "at {0}{1} pm".format(m.group(1), ":" + m.group(2) if m.group(2) else ""), body)
    title, start, all_day, spoken = _peel_due(body, now)
    title = _task_text(title)
    if not title:
        return None
    if all_day:
        minutes = 24 * 60
    return {"title": title, "start": start, "all_day": all_day, "minutes": minutes, "spoken_when": spoken}


def confirmation_line(parsed):
    when = parsed.get("spoken_when") or ""
    tail = " {0}".format(when) if when else ""
    if parsed.get("all_day"):
        return "Added {0} to your calendar{1}, all day.".format(parsed["title"], tail)
    mins = parsed.get("minutes") or 60
    if mins % 60 == 0:
        hours = mins // 60
        length = "{0} hour{1}".format(hours, "" if hours == 1 else "s")
    else:
        length = "{0} minutes".format(mins)
    return "Added {0} to your calendar{1}, for {2}.".format(parsed["title"], tail, length)


def _import_eventkit():
    try:
        import EventKit
        import Foundation
    except ImportError:
        return None
    return EventKit, Foundation


def _request_access(EventKit, store):
    done, box = threading.Event(), {}

    def finish(*args):
        box["ok"] = bool(args[0]) if args else False
        done.set()

    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(finish)
    elif hasattr(store, "requestAccessToEntityType_completion_"):
        store.requestAccessToEntityType_completion_(getattr(EventKit, "EKEntityTypeEvent", 0), finish)
    else:
        return False
    _wait_for(done, 30)
    return box.get("ok", False)


def ensure_calendar_write(EventKit, store, cache=True):
    """True when events can be written. Write-only access is enough to add one."""
    global _access_granted
    if cache and _access_granted:
        return True
    entity = getattr(EventKit, "EKEntityTypeEvent", 0)
    status = int(EventKit.EKEventStore.authorizationStatusForEntityType_(entity))
    ok = {
        int(getattr(EventKit, "EKAuthorizationStatusFullAccess", 4)),
        int(getattr(EventKit, "EKAuthorizationStatusAuthorized", 3)),
        int(getattr(EventKit, "EKAuthorizationStatusWriteOnly", 5)),
    }
    blocked = {
        int(getattr(EventKit, "EKAuthorizationStatusDenied", 2)),
        int(getattr(EventKit, "EKAuthorizationStatusRestricted", 1)),
    }
    if status in ok:
        _access_granted = _access_granted or cache
        return True
    if status in blocked:
        return False
    granted = bool(_request_access(EventKit, store))
    if cache and granted:
        _access_granted = True
    return granted


def _find_calendar(store, EventKit, name):
    if not name:
        cal = store.defaultCalendarForNewEvents()
        return (cal, None) if cal is not None else (None, "no-default")
    wanted = name.strip().lower()
    for cal in store.calendarsForEntityType_(getattr(EventKit, "EKEntityTypeEvent", 0)) or []:
        title = cal.title() if hasattr(cal, "title") else ""
        if str(title or "").strip().lower() == wanted:
            return cal, None
    return None, "no-calendar"


def _end(parsed):
    return parsed["start"] + timedelta(minutes=parsed["minutes"])


def _save_eventkit(parsed, cal_name, EventKit, Foundation, cache):
    store = EventKit.EKEventStore.alloc().init()
    if not ensure_calendar_write(EventKit, store, cache=cache):
        return "denied"
    cal, problem = _find_calendar(store, EventKit, cal_name)
    if problem:
        return problem
    if Foundation is None:
        return "fail"
    event = EventKit.EKEvent.eventWithEventStore_(store)
    event.setTitle_(parsed["title"])
    event.setCalendar_(cal)
    event.setAllDay_(bool(parsed["all_day"]))
    event.setStartDate_(Foundation.NSDate.dateWithTimeIntervalSince1970_(parsed["start"].timestamp()))
    event.setEndDate_(Foundation.NSDate.dateWithTimeIntervalSince1970_(_end(parsed).timestamp()))
    try:
        saved = store.saveEvent_span_commit_error_(event, 0, True, None)
    except Exception:
        return "fail"
    if isinstance(saved, tuple):
        saved = saved[0]
    return "ok" if saved else "fail"


def _save_applescript(parsed, cal_name, runner):
    args = [
        "osascript", "-e", _APPLESCRIPT, parsed["title"], cal_name or "",
        "yes" if parsed["all_day"] else "no",
        str(int(parsed["start"].timestamp())), str(int(parsed["minutes"])),
    ]
    try:
        runner(args)
    except Exception as exc:
        text = str(exc).lower()
        if "not authorized" in text or "-1743" in text:
            return "automation"
        if cal_name and ("whose name is" in text or "can't get calendar" in text):
            return "no-calendar"
        return "fail"
    return "ok"


def _speak(outcome, parsed, cal_name):
    return {
        "ok": lambda: confirmation_line(parsed),
        "denied": lambda: CAL_DENIED,
        "automation": lambda: CAL_AUTOMATION,
        "no-default": lambda: CAL_NO_DEFAULT,
        "no-calendar": lambda: "I couldn't find a calendar called {0}.".format(cal_name),
    }.get(outcome, lambda: CAL_FAIL)()


def add_event(text, now=None, calendar_name=None, eventkit=None, foundation=None, runner=None):
    """Create the event and return the sentence to speak (the read-back)."""
    parsed = parse_event_request(text, now=now)
    if parsed is None:
        parsed = _from_pending(text, now=now)
        if parsed is None:
            return CAL_UNCLEAR
    if parsed["start"] is None:
        _arm_pending(parsed)
        return "When should I put {0} on your calendar?".format(parsed["title"])
    clear_pending()
    chosen = str(config.CALENDAR_ADD_NAME if calendar_name is None else calendar_name or "").strip()
    if eventkit is not None:
        outcome = _save_eventkit(parsed, chosen, eventkit, foundation, cache=False)
    elif runner is not None:
        outcome = _save_applescript(parsed, chosen, runner)
    else:
        imported = _import_eventkit()
        if imported is None:
            outcome = _save_applescript(parsed, chosen, _run)
        else:
            outcome = _save_eventkit(parsed, chosen, imported[0], imported[1], cache=True)
    return _speak(outcome, parsed, chosen)
