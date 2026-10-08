"""Create one Apple Reminders item from "remind me to ...".

EventKit is the path that asks for Reminders access. AppleScript is only the
fallback when that package is not installed, and the task is an argv item,
never pasted into the script. Nothing here opens a socket or calls the network.
The command is Mac-only and is not on the iPhone bridge allowlist.
"""
from datetime import datetime, timedelta, timezone
import os
import re
import threading

from . import config
from .calendar_shift import _wait_for
from .shell import _run
from .shift_override import resolve_shift_day
from .textutil import _clean

# A bare hour is morning. "tomorrow at 9" is 9 AM. Say "pm" for the afternoon.
_WEEKDAY = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_WHEN = (
    r"tonight|tomorrow|today|on\s+(?:(?:this|next)\s+)?(?:" + _WEEKDAY + r")"
    r"|(?:this|next)\s+(?:" + _WEEKDAY + r")|(?:" + _WEEKDAY + r")"
)
_CLOCK_TAIL = r"at\s+.+|morning|afternoon|evening|night|noon|midnight"
_CMD_RE = re.compile(
    r"^(?:please\s+)?remind\s+me\s+to\s+(?P<body>.+?)(?:\s+please)?[.!?]*$",
    re.I,
)
_REL_RE = re.compile(
    r"^(?P<task>.+?)\s+in\s+(?P<qty>half\s+an|half\s+a|an|a|\d+(?:\.\d+)?|[a-z]+(?:\s+[a-z]+)?)\s+"
    r"(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)$",
    re.I,
)
_WHEN_RE = re.compile(
    rf"^(?P<task>.+?)\s+(?P<when>{_WHEN})(?:\s+(?P<clock>{_CLOCK_TAIL}))?$",
    re.I,
)
_AT_RE = re.compile(r"^(?P<task>.+?)\s+at\s+(?P<clock>.+)$", re.I)
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60,
}
_UNITS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
}
_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# "tonight" with no clock. Late enough to be evening, early enough to still be today at 3 PM.
_TONIGHT_HOUR = 20

REMINDERS_DENIED = (
    "I don't have access to Reminders. Allow full access for Hey Jev "
    "in System Settings, Privacy and Security, Reminders, then ask me again."
)
REMINDERS_AUTOMATION = (
    "I couldn't add the reminder. Allow Hey Jev to control Reminders "
    "in System Settings, Privacy and Security, Automation."
)
REMINDERS_FAIL = "I couldn't add that reminder."
REMINDERS_UNCLEAR = "Tell me what to remind you about."
REMINDERS_NO_DEFAULT = "I couldn't find your default Reminders list."

# User text arrives as argv. The script source never contains the task or the list name.
_APPLESCRIPT = """on run argv
    set taskName to item 1 of argv
    set listName to item 2 of argv
    set hasDue to item 3 of argv
    set isAllDay to item 4 of argv
    set dueYear to item 5 of argv
    set dueMonth to item 6 of argv
    set dueDay to item 7 of argv
            set dueHour to item 8 of argv
            set dueMinute to item 9 of argv
            set dueSecond to item 10 of argv
            tell application "Reminders"
        if listName is "" then
            set targetList to default list
        else
            set targetList to first list whose name is listName
        end if
        set newItem to make new reminder at end of targetList with properties {name:taskName}
        if hasDue is "yes" then
            set dueDate to current date
            set day of dueDate to 1
            set year of dueDate to (dueYear as integer)
            set month of dueDate to (dueMonth as integer)
            set day of dueDate to (dueDay as integer)
            set hours of dueDate to (dueHour as integer)
            set minutes of dueDate to (dueMinute as integer)
            set seconds of dueDate to (dueSecond as integer)
            if isAllDay is "yes" then
                set allday due date of newItem to dueDate
            else
                set due date of newItem to dueDate
            end if
        end if
    end tell
end run"""

_access_granted = False


def _squash(text):
    return re.sub(r"\s+", " ", _clean(text or "")).strip()


def _as_now(now):
    if now is None:
        return datetime.now().astimezone()
    if now.tzinfo is None:
        return now.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return now


def _quantity(text):
    raw = re.sub(r"\s+", " ", (text or "").strip().lower())
    if raw in ("half an", "half a"):
        return 0.5
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return float(raw)
    if raw in _NUMBER_WORDS:
        return _NUMBER_WORDS[raw]
    parts = raw.split()
    if len(parts) == 2 and parts[0] in _NUMBER_WORDS and parts[1] in _NUMBER_WORDS:
        tens, ones = _NUMBER_WORDS[parts[0]], _NUMBER_WORDS[parts[1]]
        if tens >= 20 and 0 < ones < 10:
            return tens + ones
    return None


def _spoken_relative(seconds):
    seconds = int(round(seconds))
    if seconds > 0 and seconds % 3600 == 0:
        hours = seconds // 3600
        unit = "hour" if hours == 1 else "hours"
        return "in {0} {1}".format(hours, unit)
    if seconds > 0 and seconds % 60 == 0:
        minutes = seconds // 60
        unit = "minute" if minutes == 1 else "minutes"
        return "in {0} {1}".format(minutes, unit)
    unit = "second" if seconds == 1 else "seconds"
    return "in {0} {1}".format(max(seconds, 0), unit)


def _spoken_clock(hour, minute, style):
    if style == "noon":
        return "noon"
    if style == "midnight":
        return "midnight"
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    if minute:
        return "{0}:{1:02d} {2}".format(hour12, minute, suffix)
    return "{0} {1}".format(hour12, suffix)


def parse_clock(text, prefer_pm=False):
    """(hour, minute, style) in 24-hour time, or None. style is noon, midnight, or clock."""
    raw = re.sub(r"\s+", " ", (text or "").strip().lower())
    raw = re.sub(r"^at\s+", "", raw).strip()
    if raw in ("noon", "midday"):
        return 12, 0, "noon"
    if raw == "midnight":
        return 0, 0, "midnight"
    if raw == "morning":
        return 9, 0, "clock"
    if raw == "afternoon":
        return 15, 0, "clock"
    if raw == "evening":
        return 18, 0, "clock"
    if raw == "night":
        return _TONIGHT_HOUR, 0, "clock"
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", raw)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if minute > 59 or hour > 23:
        return None
    mer = match.group(3)
    if mer:
        mer = mer.lower().replace(".", "")
        if hour < 1 or hour > 12:
            return None
        if mer == "pm" and hour < 12:
            hour += 12
        elif mer == "am" and hour == 12:
            hour = 0
        return hour, minute, "clock"
    if hour == 0 or hour > 12:
        return (hour, minute, "clock") if 0 < hour <= 23 else None
    if prefer_pm and 1 <= hour <= 11:
        hour += 12
    return hour, minute, "clock"


def _at(day, hour, minute, tz):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def _iana_local_zone():
    """The machine's IANA zone.

    datetime.now().astimezone() is a fixed offset (PDT, PST). That offset does
    not know a daylight-saving gap, so a relative reminder has to land back in
    the real local zone. macOS keeps that zone behind /etc/localtime.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        return None
    names = []
    env = os.environ.get("TZ")
    if env:
        names.append(env)
    try:
        path = os.path.realpath("/etc/localtime")
    except OSError:
        path = ""
    marker = "zoneinfo/"
    if marker in path:
        names.append(path.split(marker, 1)[1])
    for name in names:
        try:
            return ZoneInfo(name)
        except Exception:
            continue
    return None


def _add_absolute(now, seconds):
    """Add seconds on the UTC timeline, then convert back to local time.

    Adding a timedelta to an aware datetime moves the wall clock. Across the
    fall-back hour, 1:50 AM PDT plus 20 minutes becomes 2:10 AM PST, which is
    80 real minutes later. Relative reminders are a duration, so the add is
    done in UTC. A fixed-offset clock is upgraded to the IANA local zone first,
    which is what EventKit will interpret the components as.
    """
    zone = now.tzinfo
    if not getattr(zone, "key", None):
        zone = _iana_local_zone() or zone
    utc = now.astimezone(timezone.utc) + timedelta(seconds=seconds)
    return utc.astimezone(zone)


def _day_spoken(when, day):
    text = re.sub(r"\s+", " ", when.strip().lower())
    text = re.sub(r"^on\s+", "", text)
    if text == "tomorrow":
        return "tomorrow"
    if text == "today":
        return "today"
    if text == "tonight":
        return "tonight"
    name = _DAY_NAMES[day.weekday()]
    if text.startswith("next "):
        return "next {0}".format(name)
    if text.startswith("this "):
        return "this {0}".format(name)
    return "on {0}".format(name)


def _task_text(text):
    task = re.sub(r"\s+", " ", (text or "")).strip(" .,!?;:")
    task = re.sub(r"\s+please$", "", task, flags=re.I).strip(" .,!?;:")
    return task


def _with_clock(day, hour, minute, now, roll_days):
    due = _at(day, hour, minute, now.tzinfo)
    if roll_days and due <= now:
        due = _at(day + timedelta(days=roll_days), hour, minute, now.tzinfo)
        return due, True
    return due, False


def _apply_when(body_when, clock_text, now):
    """(due, spoken phrase, all_day, unused) or None when the day is not one we know."""
    label = re.sub(r"\s+", " ", body_when.strip().lower())
    if label == "tonight":
        hour, minute, style = _TONIGHT_HOUR, 0, "clock"
        explicit = False
        if clock_text:
            parsed = parse_clock(clock_text, prefer_pm=True)
            if parsed is None:
                return None
            hour, minute, style = parsed
            explicit = True
        due, rolled = _with_clock(now.date(), hour, minute, now, 1)
        if not explicit and not rolled:
            return due, "tonight", False, True
        clock = _spoken_clock(due.hour, due.minute, style if explicit else "clock")
        if rolled:
            return due, "tomorrow at {0}".format(clock), False, False
        return due, "tonight at {0}".format(clock), False, False
    day_token = re.sub(r"^on\s+", "", label)
    day = resolve_shift_day(day_token, now.date())
    if day is None:
        return None
    spoken_day = _day_spoken(label, day)
    if not clock_text:
        due = _at(day, 0, 0, now.tzinfo)
        return due, spoken_day, True, False
    parsed = parse_clock(clock_text)
    if parsed is None:
        return None
    hour, minute, style = parsed
    roll = 0 if day_token in ("today", "tomorrow") else 7
    if day_token == "today":
        roll = 1
    due, rolled = _with_clock(day, hour, minute, now, roll)
    clock = _spoken_clock(hour, minute, style)
    if rolled and day_token == "today":
        spoken_day = "tomorrow"
    elif rolled and day_token not in ("today", "tomorrow"):
        spoken_day = _day_spoken(label, due.date())
    return due, "{0} at {1}".format(spoken_day, clock), False, False


def _peel_due(body, now):
    """(task, due, all_day, spoken_when). due is None when the phrase has no time."""
    relative = _REL_RE.match(body)
    if relative:
        amount = _quantity(relative.group("qty"))
        unit = _UNITS.get(relative.group("unit").lower())
        if amount and unit:
            seconds = int(round(amount * unit))
            if seconds > 0:
                due = _add_absolute(now, seconds)
                return (
                    relative.group("task"),
                    due,
                    False,
                    _spoken_relative(seconds),
                )
    when = _WHEN_RE.match(body)
    if when:
        applied = _apply_when(when.group("when"), when.group("clock"), now)
        if applied is not None:
            due, spoken, all_day, _bare_tonight = applied
            return when.group("task"), due, all_day, spoken
    clock = _AT_RE.match(body)
    if clock:
        parsed = parse_clock(clock.group("clock"))
        if parsed is not None:
            hour, minute, style = parsed
            due, rolled = _with_clock(now.date(), hour, minute, now, 1)
            spoken_clock = _spoken_clock(hour, minute, style)
            if rolled:
                spoken = "tomorrow at {0}".format(spoken_clock)
            else:
                spoken = "at {0}".format(spoken_clock)
            return clock.group("task"), due, False, spoken
    return body, None, False, ""


def parse_reminder_request(text, now=None):
    """The task and optional due moment, or None when this is not "remind me to ..."."""
    now = _as_now(now)
    match = _CMD_RE.match(_squash(text))
    if not match:
        return None
    task, due, all_day, spoken = _peel_due(match.group("body").strip(), now)
    task = _task_text(task)
    if not task:
        return None
    return {"task": task, "due": due, "all_day": all_day, "spoken_when": spoken}


def confirmation_line(parsed):
    when = parsed.get("spoken_when") or ""
    if when:
        return "Okay, I'll remind you to {0} {1}.".format(parsed["task"], when)
    return "Okay, I'll remind you to {0}.".format(parsed["task"])


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

    # macOS 14+ uses the full-access call. The older one is only there if that symbol is missing.
    if hasattr(store, "requestFullAccessToRemindersWithCompletion_"):
        store.requestFullAccessToRemindersWithCompletion_(finish)
    elif hasattr(store, "requestAccessToEntityType_completion_"):
        entity = getattr(EventKit, "EKEntityTypeReminder", 1)
        store.requestAccessToEntityType_completion_(entity, finish)
    else:
        return False
    _wait_for(done, 30)
    return box.get("ok", False)


def ensure_reminders_access(EventKit, store, cache=True):
    """True when Reminders can be written. False when access is denied or declined."""
    global _access_granted
    if cache and _access_granted:
        return True
    entity = getattr(EventKit, "EKEntityTypeReminder", 1)
    status = int(EventKit.EKEventStore.authorizationStatusForEntityType_(entity))
    full = int(getattr(EventKit, "EKAuthorizationStatusFullAccess", 4))
    authorized = int(getattr(EventKit, "EKAuthorizationStatusAuthorized", 3))
    denied = int(getattr(EventKit, "EKAuthorizationStatusDenied", 2))
    restricted = int(getattr(EventKit, "EKAuthorizationStatusRestricted", 1))
    write_only = int(getattr(EventKit, "EKAuthorizationStatusWriteOnly", 5))
    if status in (full, authorized):
        if cache:
            _access_granted = True
        return True
    if status in (denied, restricted, write_only):
        return False
    granted = _request_access(EventKit, store)
    if cache and granted:
        _access_granted = True
    return bool(granted)


def _find_list(store, EventKit, name):
    if not name:
        calendar = store.defaultCalendarForNewReminders()
        if calendar is None:
            return None, "no-default"
        return calendar, None
    wanted = name.strip().lower()
    entity = getattr(EventKit, "EKEntityTypeReminder", 1)
    for calendar in store.calendarsForEntityType_(entity) or []:
        title = calendar.title() if hasattr(calendar, "title") else ""
        if str(title or "").strip().lower() == wanted:
            return calendar, None
    return None, "no-list"


def _tz_name(now):
    tz = now.tzinfo
    key = getattr(tz, "key", None)
    if key:
        return key
    name = now.tzname() if tz else None
    if name and "/" in str(name):
        return str(name)
    return None


def _components(Foundation, parsed):
    comps = Foundation.NSDateComponents.alloc().init()
    due = parsed["due"]
    comps.setYear_(due.year)
    comps.setMonth_(due.month)
    comps.setDay_(due.day)
    if not parsed["all_day"]:
        comps.setHour_(due.hour)
        comps.setMinute_(due.minute)
        # Clock times are minute precision (second 0). A relative reminder keeps
        # the second from the absolute add, so "in 10 seconds" at :45 is not saved as :00.
        if hasattr(comps, "setSecond_"):
            comps.setSecond_(due.second)
    name = _tz_name(due)
    if name and hasattr(Foundation, "NSTimeZone"):
        zone = Foundation.NSTimeZone.timeZoneWithName_(name)
        if zone is not None and hasattr(comps, "setTimeZone_"):
            comps.setTimeZone_(zone)
    return comps


def _saved(result):
    if isinstance(result, tuple):
        result = result[0]
    if result is None:
        return False
    return bool(result)


def _save_eventkit(parsed, list_name, EventKit, Foundation, cache):
    store = EventKit.EKEventStore.alloc().init()
    if not ensure_reminders_access(EventKit, store, cache=cache):
        return "denied"
    calendar, problem = _find_list(store, EventKit, list_name)
    if problem:
        return problem
    if Foundation is None:
        return "fail"
    reminder = EventKit.EKReminder.reminderWithEventStore_(store)
    reminder.setTitle_(parsed["task"])
    reminder.setCalendar_(calendar)
    if parsed["due"] is not None:
        reminder.setDueDateComponents_(_components(Foundation, parsed))
    try:
        saved = store.saveReminder_commit_error_(reminder, True, None)
    except Exception:
        return "fail"
    if not _saved(saved):
        return "fail"
    return "ok"


def _applescript_outcome(exc, list_name):
    text = str(exc).lower()
    if "not authorized" in text or "-1743" in text or "1002" in text:
        return "automation"
    if list_name and ("whose name is" in text or "can't get list" in text or "invalid index" in text):
        return "no-list"
    return "fail"


def _due_args(parsed):
    """AppleScript argv for the due date. The last item is the second.

    Relative reminders keep due.second. An all-day reminder and a clock time
    with no seconds pass 0. The script always reads item 10, including when
    there is no due date.
    """
    due = parsed["due"]
    if due is None:
        return ["no", "no", "0", "0", "0", "0", "0", "0"]
    return [
        "yes",
        "yes" if parsed["all_day"] else "no",
        str(due.year),
        str(due.month),
        str(due.day),
        "0" if parsed["all_day"] else str(due.hour),
        "0" if parsed["all_day"] else str(due.minute),
        "0" if parsed["all_day"] else str(due.second),
    ]


def _save_applescript(parsed, list_name, runner):
    parts = _due_args(parsed)
    args = ["osascript", "-e", _APPLESCRIPT, parsed["task"], list_name or "", *parts]
    try:
        runner(args)
    except Exception as exc:
        return _applescript_outcome(exc, list_name)
    return "ok"


def _speak_outcome(outcome, parsed, list_name):
    if outcome == "ok":
        return confirmation_line(parsed)
    if outcome == "denied":
        return REMINDERS_DENIED
    if outcome == "automation":
        return REMINDERS_AUTOMATION
    if outcome == "no-default":
        return REMINDERS_NO_DEFAULT
    if outcome == "no-list":
        return "I couldn't find a Reminders list called {0}.".format(list_name)
    return REMINDERS_FAIL


def _chosen_list(list_name):
    if list_name is None:
        list_name = config.REMINDERS_LIST
    return str(list_name or "").strip()


def add_reminder(text, now=None, list_name=None, eventkit=None, foundation=None, runner=None):
    """Create the reminder and return the sentence to speak.

    Pass eventkit and foundation to use a store without importing EventKit.
    Pass runner to force the AppleScript fallback. With neither, EventKit is
    imported and AppleScript is used only when that import fails.
    """
    parsed = parse_reminder_request(text, now=now)
    if parsed is None:
        return REMINDERS_UNCLEAR
    chosen = _chosen_list(list_name)
    if eventkit is not None:
        outcome = _save_eventkit(parsed, chosen, eventkit, foundation, cache=False)
    elif runner is not None:
        outcome = _save_applescript(parsed, chosen, runner)
    else:
        imported = _import_eventkit()
        if imported is None:
            outcome = _save_applescript(parsed, chosen, _run)
        else:
            eventkit, foundation = imported
            outcome = _save_eventkit(parsed, chosen, eventkit, foundation, cache=True)
    return _speak_outcome(outcome, parsed, chosen)
