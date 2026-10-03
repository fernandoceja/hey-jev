"""What's today, and the morning brief."""
from datetime import datetime, timedelta
from .time_date import speak_date
from .calendar_shift import _CAL_FAILED, _calendar_problem, _events_between, speak_next_shift, speak_today_schedule
from .money import sweep_reminder_line
from .weather import gmail_brief_line, speak_weather
from .notes_due import speak_due

def speak_today():
    """The date, plus how many events are on the calendar today."""
    date_line = speak_date()
    counted = _count_today_events()
    if isinstance(counted, str):
        return f"{date_line} {counted}"
    if counted == 0:
        return f"{date_line} You have no events today."
    if counted == 1:
        return f"{date_line} You have 1 event today."
    return f"{date_line} You have {counted} events today."


def _count_today_events():
    problem = _calendar_problem()
    if problem:
        return problem
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    try:
        return len(_events_between(start, end))
    except Exception:
        return _CAL_FAILED


def speak_brief(today=None):
    """Date, weather, today's events, next shift, due items, and a payday sweep when one is due.

    `today` is only for the sweep line. Pass a date in tests. The other parts
    still describe the real current day.
    """
    parts = [
        speak_date(),
        speak_weather(),
        speak_today_schedule(),
        speak_next_shift(),
        speak_due(limit=3),
    ]
    sweep = sweep_reminder_line(today)
    if sweep:
        parts.append(sweep)
    mail = gmail_brief_line()
    if mail:
        parts.append(mail)
    return " ".join(part.strip() for part in parts if part and part.strip())
