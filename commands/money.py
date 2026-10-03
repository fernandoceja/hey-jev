"""Read-only school, rent, bills, payday, Brea, and IHSS hours.

The sweep reminder is date math only. It does not open a bank, look up a
balance, or move money.
"""
from datetime import datetime, timedelta
import csv
import os
import re
from .config import (
    BILL_HORIZON_DAYS,
    BILL_RE,
    DEFAULT_APPLE_PAY_ANCHOR,
    JEV_DOCS,
    MONEY_PATH,
    SCHOOL_HORIZON_DAYS,
    SCHOOL_RE,
    SWEEP_ACCOUNT_LABEL,
    SWEEP_AMOUNT,
    SWEEP_SPOKEN_PATH,
)
from .textutil import _clean, _clock, _day_phrase, _hours_phrase, _join_names, _month_day, _until_day, _weekday_month
from .shell import _run
from .calendar_shift import _load_plain_events
from .notes_due import _dated_lines
from .live import _live

def _semi_period(day):
    """(start, end) dates of the semi-monthly period that contains day."""
    if day.day <= 15:
        return day.replace(day=1), day.replace(day=15)
    if day.month == 12:
        next_month = day.replace(year=day.year + 1, month=1, day=1)
    else:
        next_month = day.replace(month=day.month + 1, day=1)
    return day.replace(day=16), next_month - timedelta(days=1)


def _parse_ihss(text):
    raw = _clean(text)
    match = re.search(
        r"\blog\s+ihss\s+hours\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:hours?)?\b(?:\s+(today|yesterday))?",
        raw, re.I,
    )
    if not match:
        match = re.search(
            r"\blog\s+(\d+(?:\.\d+)?)\s*(?:hours?)?\s+for\s+grandma\b(?:\s+(today|yesterday))?",
            raw, re.I,
        )
    if not match:
        return None
    hours = float(match.group(1))
    which = (match.group(2) or "today").lower()
    day = datetime.now().astimezone().date()
    if which == "yesterday":
        day = day - timedelta(days=1)
    return hours, day


def _period_total(path, today):
    start, end = _semi_period(today)
    total = 0.0
    if not os.path.isfile(path):
        return total, start, end
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 2 or row[0].strip().lower() == "date":
                continue
            try:
                day = datetime.strptime(row[0].strip(), "%Y-%m-%d").date()
                hours = float(row[1])
            except ValueError:
                continue
            if start <= day <= end:
                total += hours
    return total, start, end


def log_ihss(text):
    """Append date,hours to ihss_hours.csv and speak this period's total."""
    parsed = _parse_ihss(text)
    if not parsed:
        return "Tell me the hours, like: log IHSS hours, 4 hours today."
    hours, when = parsed
    if hours <= 0 or hours > 24:
        return "Hours need to be more than 0 and no more than 24."
    os.makedirs(JEV_DOCS, exist_ok=True)
    new_file = not os.path.isfile(_live("IHSS_PATH"))
    with open(_live("IHSS_PATH"), "a", encoding="utf-8", newline="") as handle:
        if new_file:
            handle.write("date,hours\n")
        handle.write(f"{when.isoformat()},{hours:.2f}\n")
    today = datetime.now().astimezone().date()
    try:
        total, start, end = _period_total(_live("IHSS_PATH"), today)
    except OSError:
        return f"Logged {_hours_phrase(hours)} for {_month_day(when)}. I couldn't total the period."
    return (
        f"Logged {_hours_phrase(hours)} for {_month_day(when)}. "
        f"This period, {_month_day(start)} through {_month_day(end)}, totals {_hours_phrase(total)}."
    )


def brea_from_due(path=None, today=None):
    """Spoken Brea line from due.md, or None when the file or the line is missing."""
    lines = _dated_lines(path)
    if not lines:
        return None
    hits = [(day, title) for day, title in lines if re.search(r"\bbrea\b", title, re.I)]
    if not hits:
        return None
    today = today or datetime.now().astimezone().date()
    future = [item for item in hits if item[0] >= today]
    day, title = future[0] if future else hits[-1]
    return f"The due list says {title} on {_month_day(day)}, {_until_day(day, today)}."


def speak_brea_start(now=None, path=None, events=None):
    now = now or datetime.now().astimezone()
    today = now.date()
    due_line = brea_from_due(today=today)
    horizon = now + timedelta(days=60)
    if events is None:
        loaded = _load_plain_events(now - timedelta(days=2), horizon)
    else:
        loaded = events
    from .shift_override import events_with_overrides

    events, _error = events_with_overrides(loaded, now, horizon, path=path)
    cal_line = None
    brea = [ev for ev in events if re.search(r"\bbrea\b", f"{ev.get('title', '')} {ev.get('place', '')}", re.I) and ev["end"] > now]
    brea.sort(key=lambda ev: ev["start"])
    if brea:
        ev = brea[0]
        if ev.get("source") == "override":
            cal_line = (
                f"Your saved shift is {ev.get('place') or 'Brea'} "
                f"{_day_phrase(ev['start'], now)} at {_clock(ev['start'])}."
            )
        else:
            cal_line = f"The calendar has {ev['title']} {_day_phrase(ev['start'], now)} at {_clock(ev['start'])}."
    parts = [part for part in (due_line, cal_line) if part]
    if parts:
        return " ".join(parts)
    if isinstance(loaded, str) and due_line is None and not os.path.isfile(_live("DUE_PATH")):
        return "I don't see a Brea start. Add a dated line to Documents, Jev, due.md."
    return "I don't see a Brea start in your due list. Add a dated line to Documents, Jev, due.md."


def _filtered_due(pattern, horizon_days, path=None, today=None):
    lines = _dated_lines(path)
    if lines is None:
        return None
    today = today or datetime.now().astimezone().date()
    horizon = today + timedelta(days=horizon_days)
    found = [(day, title) for day, title in lines if today <= day <= horizon and pattern.search(title)]
    found.sort(key=lambda item: (item[0], item[1].lower()))
    return found


def _speak_item_list(items, empty, label):
    if items is None:
        return "You don't have a due list yet. Add dated lines to Documents, Jev, due.md."
    if not items:
        return empty
    shown = items[:5]
    extra = len(items) - len(shown)
    spoken = [f"{title} on {_month_day(day)}" for day, title in shown]
    line = label + _join_names(spoken) + "."
    if extra == 1:
        line += " And 1 more."
    elif extra:
        line += f" And {extra} more."
    return line


def speak_school_due(today=None, path=None):
    items = _filtered_due(SCHOOL_RE, SCHOOL_HORIZON_DAYS, path=path, today=today)
    return _speak_item_list(items, "Nothing for school is due in the next 30 days.", "For school: ")


def speak_rent(today=None, path=None):
    lines = _dated_lines(path)
    if lines is None:
        return "You don't have a due list yet. Add a dated rent line to Documents, Jev, due.md."
    today = today or datetime.now().astimezone().date()
    rent = [(day, title) for day, title in lines if day >= today and re.search(r"\brent\b", title, re.I)]
    if not rent:
        return "I don't see an upcoming rent date. Add a dated line to Documents, Jev, due.md."
    day, title = rent[0]
    return f"{title} is due {_month_day(day)}, {_until_day(day, today)}."


def speak_bills(today=None, path=None):
    items = _filtered_due(BILL_RE, BILL_HORIZON_DAYS, path=path, today=today)
    return _speak_item_list(items, "No bills are coming up in the next 45 days.", "Bills coming up: ")


def next_biweekly(anchor, today):
    """Next date on a 14-day cadence, including today when today is a payday."""
    if today <= anchor:
        return anchor
    delta = (today - anchor).days
    steps = (delta + 13) // 14
    return anchor + timedelta(days=steps * 14)


def _month_end(year, month):
    if month == 12:
        return datetime(year + 1, 1, 1).date() - timedelta(days=1)
    return datetime(year, month + 1, 1).date() - timedelta(days=1)


def next_semi_payday(today):
    """Next 15th or last day of the month, including today."""
    candidates = []
    year, month = today.year, today.month
    for _ in range(4):
        candidates.append(datetime(year, month, 15).date())
        candidates.append(_month_end(year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    future = [day for day in candidates if day >= today]
    return min(future)


def _schedule(anchor, default):
    """Anchor plus the sweep amount and account label from config."""
    return {
        "anchor": anchor,
        "default": default,
        "amount": SWEEP_AMOUNT,
        "account": SWEEP_ACCOUNT_LABEL,
    }


def load_pay_schedule(path=None):
    """Apple anchor date, and whether money.md was missing so the default is in use.

    The file is local. Bank sites are never contacted from here. The sweep
    amount and account label always come from config, not from this file.
    """
    path = path or MONEY_PATH
    anchor = datetime.strptime(DEFAULT_APPLE_PAY_ANCHOR, "%Y-%m-%d").date()
    if not os.path.isfile(path):
        return _schedule(anchor, True)
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return _schedule(anchor, True)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"apple\s*:\s*(\d{4}-\d{2}-\d{2})", line, re.I)
        if match:
            try:
                anchor = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
    return _schedule(anchor, False)


def speak_payday(today=None, path=None):
    today = today or datetime.now().astimezone().date()
    schedule = load_pay_schedule(path)
    apple = next_biweekly(schedule["anchor"], today)
    ihss = next_semi_payday(today)
    apple_line = f"Apple payday is {_weekday_month(apple)}, {_until_day(apple, today)}."
    ihss_line = f"IHSS payday is {_month_day(ihss)}, {_until_day(ihss, today)}."
    if apple <= ihss:
        first, second = apple_line, ihss_line
    else:
        first, second = ihss_line, apple_line
    note = ""
    if schedule["default"]:
        note = " That's the default schedule. Edit Documents, Jev, money.md to change the Apple Friday."
    return f"{first} {second}{note}"


def _plain_amount(amount):
    if isinstance(amount, float) and amount.is_integer():
        return str(int(amount))
    return str(amount)


def is_apple_payday(today, anchor):
    """True on the anchor Friday and every 14 days after it.

    A Friday before the anchor is not a payday, even when it sits on the
    same 14-day cadence.
    """
    if today < anchor:
        return False
    return (today - anchor).days % 14 == 0


def is_ihss_payday(today):
    """True on the 15th and on the last day of the month, including leap day."""
    if today.day == 15:
        return True
    return today == _month_end(today.year, today.month)


def is_timesheet_day(today):
    """True on the 14th and on the last day of the month."""
    if today.day == 14:
        return True
    return today == _month_end(today.year, today.month)


def sweep_reminder_line(today=None, path=None):
    """Spoken sweep and timesheet lines for one date, or None when nothing is due.

    `today` is a datetime.date. Omit it to use the local calendar day.
    This reads the Apple anchor from money.md when that file exists and
    otherwise uses the config anchor. It does not touch the network.
    """
    today = today or datetime.now().astimezone().date()
    schedule = load_pay_schedule(path)
    move = f"move ${_plain_amount(schedule['amount'])} to {schedule['account']}."
    apple = is_apple_payday(today, schedule["anchor"])
    ihss = is_ihss_payday(today)
    lines = []
    if apple and ihss:
        lines.append(f"Apple and IHSS payday today — {move}")
    elif apple:
        lines.append(f"Apple payday today — {move}")
    elif ihss:
        lines.append(f"IHSS payday today — {move}")
    if is_timesheet_day(today):
        lines.append("Time to submit your timesheet.")
    if not lines:
        return None
    return " ".join(lines)


def speak_payday_check(today=None, path=None):
    """Answer "payday check" / "what's due today" / "any reminders today"."""
    line = sweep_reminder_line(today, path=path)
    if line:
        return line
    return "Nothing to sweep today."


def _read_sweep_stamp(state_path):
    try:
        with open(state_path, encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _write_sweep_stamp(state_path, today):
    folder = os.path.dirname(state_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(today.isoformat() + "\n")
    os.replace(tmp, state_path)


def claim_daily_sweep(today=None, state_path=None, path=None):
    """The launch reminder for today, once.

    Returns the spoken line the first time this date has something to say,
    and None after that stamp is written. A quiet day returns None and
    leaves the stamp alone. Asking out loud does not use this stamp.
    """
    today = today or datetime.now().astimezone().date()
    state_path = state_path or SWEEP_SPOKEN_PATH
    if _read_sweep_stamp(state_path) == today:
        return None
    line = sweep_reminder_line(today, path=path)
    if not line:
        return None
    _write_sweep_stamp(state_path, today)
    return line


def speak_ihss_period(today=None):
    today = today or datetime.now().astimezone().date()
    start, end = _semi_period(today)
    if not os.path.isfile(_live("IHSS_PATH")):
        return (
            f"No IHSS hours logged yet. This period is {_month_day(start)} through {_month_day(end)}."
        )
    try:
        total, start, end = _period_total(_live("IHSS_PATH"), today)
    except OSError:
        return "I couldn't read the IHSS log."
    return (
        f"This pay period, {_month_day(start)} through {_month_day(end)}, "
        f"is {_hours_phrase(total)}."
    )


def remind_timesheet():
    """Create one fixed Reminders item. The title is not taken from speech."""
    script = (
        'tell application "Reminders"\n'
        "if (count of lists) is 0 then error \"no lists\"\n"
        "set targetList to default list\n"
        'make new reminder at end of targetList with properties {name:"Submit IHSS timesheet"}\n'
        "end tell"
    )
    try:
        _run(("osascript", "-e", script))
    except Exception:
        return "I couldn't add the reminder. Allow Automation for Reminders."
    return "I added a reminder called Submit IHSS timesheet."
