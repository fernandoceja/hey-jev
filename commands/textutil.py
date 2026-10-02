"""Small text and date helpers shared by the command modules."""
from datetime import timedelta
import re

def _clean(text):
    return (text or "").replace("’", "'").replace("‘", "'")


def _norm(text):
    """'cap cut' and 'CapCut' both become 'capcut'."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# --------------------------------------------------------------------------- Time and date
def _ordinal(day):
    day = int(day)
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _clock(when):
    hour = when.strftime("%I").lstrip("0") or "12"
    ampm = when.strftime("%p")
    if when.minute == 0:
        return f"{hour} {ampm}"
    return f"{hour}:{when.minute:02d} {ampm}"


def _in_how_long(later, now):
    seconds = (later - now).total_seconds()
    if seconds < 45:
        return "now"
    minutes = int(round(seconds / 60.0))
    if minutes < 60:
        unit = "minute" if minutes == 1 else "minutes"
        return f"in {minutes} {unit}"
    hours, mins = divmod(minutes, 60)
    if mins >= 45:
        hours += 1
    if hours < 48:
        unit = "hour" if hours == 1 else "hours"
        return f"in {hours} {unit}"
    days = max(1, int(round(seconds / 86400)))
    unit = "day" if days == 1 else "days"
    return f"in {days} {unit}"


def _day_phrase(when, now):
    if when.date() == now.date():
        return "today"
    if when.date() == now.date() + timedelta(days=1):
        return "tomorrow"
    return f"on {when:%A}"


def _join_names(items):
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _month_day(day):
    return f"{day:%B} {_ordinal(day.day)}"


def _spoken_span(seconds):
    seconds = int(seconds)
    if seconds < 90:
        n = max(1, seconds)
        return "1 second" if n == 1 else f"{n} seconds"
    minutes = max(1, int(round(seconds / 60.0)))
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


def _hours_phrase(hours):
    if abs(hours - round(hours)) < 0.001:
        whole = int(round(hours))
        return "1 hour" if whole == 1 else f"{whole} hours"
    text = f"{hours:.2f}".rstrip("0").rstrip(".")
    return f"{text} hours"


def _until_day(day, today):
    delta = (day - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    if delta > 1:
        return f"in {delta} days"
    return f"{abs(delta)} days ago"


def _hours_minutes(minutes):
    minutes = max(0, int(minutes))
    hours, mins = divmod(minutes, 60)
    bits = []
    if hours:
        bits.append("1 hour" if hours == 1 else f"{hours} hours")
    if mins or not bits:
        bits.append("1 minute" if mins == 1 else f"{mins} minutes")
    return " and ".join(bits)


def _weekday_month(day):
    return f"{day:%A}, {day:%B} {_ordinal(day.day)}"
