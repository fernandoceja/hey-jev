"""Notes and the dated due list in ~/Documents/Jev."""
from datetime import datetime, timedelta
import os
import re
from .config import DUE_HORIZON_DAYS, JEV_DOCS, NOTES_PATH, _NOTE_CMD_RE
from .textutil import _clean, _join_names, _month_day
from .live import _live

def take_note(text):
    """Append one timestamped line to ~/Documents/Jev/notes.md."""
    match = _NOTE_CMD_RE.match(_clean(text).strip())
    body = match.group(1).strip() if match else ""
    body = re.sub(r"\s+", " ", body).strip(" .,!?")
    if not body:
        return "What should I write down?"
    os.makedirs(JEV_DOCS, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    with open(NOTES_PATH, "a", encoding="utf-8") as handle:
        handle.write(f"- {stamp}: {body}\n")
    return "Got it. I added that to your notes."


def _dated_lines(path=None):
    """Every (date, title) in a markdown file. None when the file is missing.

    A line needs a YYYY-MM-DD date. The rest of the line, without the date and
    a leading dash, is the title. Blank lines and dateless lines are skipped.
    """
    path = path or _live("DUE_PATH")
    if not os.path.isfile(path):
        return None
    found = []
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            match = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
            if not match:
                continue
            try:
                day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            title = raw.strip()
            title = re.sub(r"^[-*]\s*", "", title)
            title = title.replace(match.group(1), " ")
            title = re.sub(r"\s+", " ", title).strip(" :-–—")
            if title:
                found.append((day, title))
    found.sort(key=lambda item: (item[0], item[1].lower()))
    return found


def _read_due_lines():
    """(date, title) pairs due from today through DUE_HORIZON_DAYS, soonest first.

    None when the file is missing.
    """
    lines = _dated_lines()
    if lines is None:
        return None
    today = datetime.now().astimezone().date()
    horizon = today + timedelta(days=DUE_HORIZON_DAYS)
    return [(day, title) for day, title in lines if today <= day <= horizon]


def speak_due(limit=7):
    """Items in due.md due in the next 7 days, soonest first."""
    try:
        items = _read_due_lines()
    except OSError:
        return "I couldn't read the due list."
    if items is None:
        return "You don't have a due list yet. Add dated lines to Documents, Jev, due.md."
    if not items:
        return "Nothing is due in the next 7 days."
    shown = items[:limit]
    extra = len(items) - len(shown)
    spoken = [f"{title} on {_month_day(day)}" for day, title in shown]
    line = "Due soon: " + _join_names(spoken) + "."
    if extra == 1:
        line += " And 1 more."
    elif extra:
        line += f" And {extra} more."
    return line
