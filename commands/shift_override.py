"""A spoken shift for one date, saved as plain JSON. No secrets, no network.

The file replaces the calendar on that date only. Clearing the date puts the
calendar back. This does not log into WorkJam or read a schedule from the web.
"""
from datetime import datetime, timedelta
import json
import os
import re
from .config import SHIFT_OVERRIDE_PATH, SHIFT_TITLE_PATTERNS
from .textutil import _clean, _clock, _weekday_month

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_WHEN_RE = (
    r"today|tomorrow|(?:this|next)\s+"
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
)
_TIME_RE = r"\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?"
_SET_RE = re.compile(
    rf"^my\s+shift(?:\s+on)?\s+(?P<when>{_WHEN_RE})\s+is\s+"
    rf"(?P<start>{_TIME_RE})\s+(?:to|until)\s+(?P<end>{_TIME_RE})"
    rf"(?:\s+at\s+(?P<place>.+))?$",
    re.I,
)
_CLEAR_ONE_RE = re.compile(
    rf"^(?:clear|forget)\s+my\s+shift(?:\s+on)?\s+(?P<when>{_WHEN_RE})$"
    rf"|^(?:clear|forget)\s+my\s+(?P<when2>{_WHEN_RE})\s+shift$",
    re.I,
)
_CLEAR_ALL_RE = re.compile(
    r"^(?:clear|forget)\s+(?:all\s+)?my\s+shift\s+overrides?$"
    r"|^(?:clear|forget)\s+my\s+shift$",
    re.I,
)
_EXAMPLE = "Say it like: my shift Monday is 9:30 to 6:30 at Brea."
_MAX_SHIFT_MINUTES = 14 * 60


def _strip_cmd(text):
    text = _clean(text).strip()
    text = re.sub(r"^(?:please\s+)", "", text, flags=re.I)
    text = re.sub(r"(?:\s+please)?[.!?]*$", "", text).strip()
    return text


def resolve_shift_day(when, today):
    """The date a spoken day name means. None when it is not a day we know.

    A bare weekday, and "this Monday", are the next one including today.
    "next Monday" skips today when today is already that weekday.
    """
    text = re.sub(r"\s+", " ", (when or "").strip().lower())
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    match = re.fullmatch(
        r"(this|next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        text,
    )
    if match:
        name = match.group(2)
        force_next = match.group(1) == "next"
    elif text in _WEEKDAYS:
        name = text
        force_next = False
    else:
        return None
    delta = (_WEEKDAYS[name] - today.weekday()) % 7
    if force_next and delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _parse_spoken_clock(token):
    """(hour, minute, explicit meridiem) or None. Hour is 0-23 when explicit."""
    match = re.fullmatch(
        r"(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?",
        (token or "").strip(),
        re.I,
    )
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if minute > 59 or hour > 24:
        return None
    mer = match.group(3)
    if not mer:
        if hour > 12:
            return None
        return hour, minute, False
    mer = mer.lower().replace(".", "")
    if hour > 12:
        return None
    if mer == "pm" and hour < 12:
        hour += 12
    elif mer == "am" and hour == 12:
        hour = 0
    return hour, minute, True


def _clock_pair(start_hour, start_min, end_hour, end_min, end_explicit):
    """A forward shift of at most 14 hours, or None.

    With no meridiem on the end, 6:30 after 9:30 becomes 6:30 PM.
    An explicit end that is already past the start lands on the next day.
    """
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        return None
    start_m = start_hour * 60 + start_min
    end_m = end_hour * 60 + end_min
    next_day = False
    if end_m <= start_m and not end_explicit and end_hour < 12:
        end_hour += 12
        end_m = end_hour * 60 + end_min
    if end_m <= start_m:
        next_day = True
    duration = end_m + (1440 if next_day else 0) - start_m
    if duration <= 0 or duration > _MAX_SHIFT_MINUTES or end_hour > 23:
        return None
    return start_hour, start_min, end_hour, end_min


def _resolve_clocks(start_tok, end_tok):
    start = _parse_spoken_clock(start_tok)
    end = _parse_spoken_clock(end_tok)
    if not start or not end:
        return None
    sh, sm, start_explicit = start
    eh, em, end_explicit = end
    if start_explicit:
        return _clock_pair(sh, sm, eh, em, end_explicit)
    # No meridiem. 8-12 stays morning. 1-7 prefers the afternoon reading
    # when that is a real shift, and falls back to the morning one.
    if 8 <= sh <= 12:
        return _clock_pair(sh, sm, eh, em, end_explicit)
    if 1 <= sh <= 7:
        afternoon = _clock_pair(sh + 12, sm, eh, em, end_explicit)
        if afternoon:
            return afternoon
        return _clock_pair(sh, sm, eh, em, end_explicit)
    return None


def _place_name(raw):
    if not raw or not raw.strip():
        return "Brea"
    text = re.sub(r"\s+", " ", raw).strip(" .,!?")
    if not text or len(text) > 40:
        return None
    if re.fullmatch(r"(?:the\s+)?(?:apple(?:\s+store)?(?:\s+at)?\s+)?brea(?:\s+mall)?", text, re.I):
        return "Brea"
    return text


def parse_shift_set(text, today):
    """{date, start, end, place} for a set phrase, or None."""
    match = _SET_RE.match(_strip_cmd(text))
    if not match:
        return None
    day = resolve_shift_day(match.group("when"), today)
    clocks = _resolve_clocks(match.group("start"), match.group("end"))
    place = _place_name(match.group("place"))
    if day is None or clocks is None or place is None:
        return None
    sh, sm, eh, em = clocks
    return {
        "date": day,
        "start": f"{sh:02d}:{sm:02d}",
        "end": f"{eh:02d}:{em:02d}",
        "place": place,
    }


def parse_shift_clear(text, today):
    """{'all': True} or {'date': date}, or None when it is not a clear phrase."""
    raw = _strip_cmd(text)
    one = _CLEAR_ONE_RE.match(raw)
    if one:
        when = one.group("when") or one.group("when2")
        day = resolve_shift_day(when, today)
        if day is None:
            return None
        return {"date": day}
    if _CLEAR_ALL_RE.match(raw):
        return {"all": True}
    return None


def load_shift_overrides(path=None):
    """date string -> {start, end, place}. Missing or broken files are empty."""
    path = path or SHIFT_OVERRIDE_PATH
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    clean = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        try:
            datetime.strptime(key, "%Y-%m-%d")
        except ValueError:
            continue
        start, end = value.get("start"), value.get("end")
        if not (_hhmm(start) and _hhmm(end)):
            continue
        place = value.get("place") or "Brea"
        if not isinstance(place, str) or not place.strip():
            continue
        clean[key] = {"start": start, "end": end, "place": place.strip()}
    return clean


def _hhmm(text):
    match = re.fullmatch(r"(\d{2}):(\d{2})", text or "")
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _write_overrides(path, data):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def _speak_saved(record, day):
    start = datetime(day.year, day.month, day.day, *_hhmm(record["start"]))
    end = datetime(day.year, day.month, day.day, *_hhmm(record["end"]))
    return (
        f"Saved. {_weekday_month(day)}, {record['place']} is {_clock(start)} to {_clock(end)}. "
        "I'll use that instead of the calendar that day."
    )


def set_shift_override(text, today=None, path=None):
    """Save one day's shift and say what was stored."""
    today = today or datetime.now().astimezone().date()
    parsed = parse_shift_set(text, today)
    if not parsed:
        return _EXAMPLE
    path = path or SHIFT_OVERRIDE_PATH
    data = load_shift_overrides(path)
    record = {"start": parsed["start"], "end": parsed["end"], "place": parsed["place"]}
    data[parsed["date"].isoformat()] = record
    _write_overrides(path, data)
    return _speak_saved(record, parsed["date"])


def clear_shift_override(text, today=None, path=None):
    """Remove one date, or every saved shift, and say so."""
    today = today or datetime.now().astimezone().date()
    parsed = parse_shift_clear(text, today)
    if not parsed:
        return "Say which day to clear, like: clear my shift Monday."
    path = path or SHIFT_OVERRIDE_PATH
    data = load_shift_overrides(path)
    if parsed.get("all"):
        if not data:
            return "You don't have any shift overrides."
        _write_overrides(path, {})
        return "Cleared your shift overrides."
    key = parsed["date"].isoformat()
    if key not in data:
        return f"You don't have a shift override for {_weekday_month(parsed['date'])}."
    del data[key]
    _write_overrides(path, data)
    return f"Cleared the shift override for {_weekday_month(parsed['date'])}."


def _is_shift_title(title):
    text = title or ""
    return any(re.search(pattern, text, re.I) for pattern in SHIFT_TITLE_PATTERNS)


def override_events(start, end, path=None, tz=None):
    """Plain event dicts for saved shifts that overlap [start, end)."""
    tz = tz or datetime.now().astimezone().tzinfo
    found = []
    for key, record in load_shift_overrides(path).items():
        day = datetime.strptime(key, "%Y-%m-%d").date()
        start_clock, end_clock = _hhmm(record["start"]), _hhmm(record["end"])
        begin = datetime(day.year, day.month, day.day, start_clock[0], start_clock[1], tzinfo=tz)
        finish = datetime(day.year, day.month, day.day, end_clock[0], end_clock[1], tzinfo=tz)
        if finish <= begin:
            finish += timedelta(days=1)
        if finish <= start or begin >= end:
            continue
        place = record["place"]
        found.append({
            "title": f"Shift at {place}",
            "start": begin,
            "end": finish,
            "all_day": False,
            "calendar": "",
            "place": place,
            "source": "override",
        })
    found.sort(key=lambda ev: ev["start"])
    return found


def merge_shift_overrides(events, now, horizon, path=None):
    """Calendar events, with a saved shift replacing calendar shifts on that date.

    Events that are not shifts stay. The calendar reader itself is unchanged.
    """
    overrides = override_events(now - timedelta(hours=18), horizon, path=path, tz=now.tzinfo)
    if not overrides:
        return list(events)
    # Local import: calendar_shift calls back into this module.
    from .calendar_shift import _covers_day

    days = [ev["start"].date() for ev in overrides]
    kept = []
    for ev in events:
        if _is_shift_title(ev.get("title", "")) and any(_covers_day(ev, day) for day in days):
            continue
        kept.append(ev)
    kept.extend(overrides)
    return kept


def events_with_overrides(loaded, now, horizon, path=None):
    """(events, error). A calendar error is kept only when nothing is saved."""
    if isinstance(loaded, str):
        base = []
        error = loaded
    else:
        base = list(loaded)
        error = None
    events = merge_shift_overrides(base, now, horizon, path=path)
    if error and not events:
        return [], error
    return events, None
