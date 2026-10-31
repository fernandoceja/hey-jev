"""What's today, and the morning brief."""
import threading
import time
from datetime import datetime, timedelta
from .time_date import speak_date
from .calendar_shift import _CAL_FAILED, _calendar_problem, _events_between, speak_next_shift, speak_today_schedule
from .money import sweep_reminder_line
from .weather import gmail_brief_line, speak_weather
from .notes_due import speak_due

# Every section gets its own hard timeout, so one that never returns (EventKit, osascript, a stalled network call)
# cannot hold the whole brief. The whole brief is capped too.
BRIEF_SECTION_SECONDS = 6.0
BRIEF_TOTAL_SECONDS = 20.0


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


def _gather(sections):
    """Run each (name, fn, fallback) section in its own daemon thread, and return one result per section, in order.

    A section that runs past BRIEF_SECTION_SECONDS, or past the whole brief's BRIEF_TOTAL_SECONDS, gives its fallback
    and the brief goes on without it. A section that raises gives its fallback too. Each outcome is logged as
    "brief: <name> ok in <ms>", "brief: <name> timeout" or "brief: <name> failed: <error>".
    """
    started = time.monotonic()
    jobs = []
    for name, fn, fallback in sections:
        box = {}

        def work(fn=fn, box=box):
            begun = time.monotonic()
            try:
                box["value"] = fn()
            except Exception as exc:
                box["error"] = exc
            box["ms"] = int((time.monotonic() - begun) * 1000)

        thread = threading.Thread(target=work, name="brief-" + name, daemon=True)
        thread.start()
        jobs.append((name, fallback, thread, box))
    results = []
    for name, fallback, thread, box in jobs:
        remaining = min(BRIEF_SECTION_SECONDS, BRIEF_TOTAL_SECONDS - (time.monotonic() - started))
        thread.join(max(0.0, remaining))
        if thread.is_alive():
            print(f"brief: {name} timeout", flush=True)
            results.append(fallback)
        elif "error" in box:
            print(f"brief: {name} failed: {type(box['error']).__name__}", flush=True)
            results.append(fallback)
        else:
            print(f"brief: {name} ok in {box.get('ms', 0)}ms", flush=True)
            results.append(box.get("value"))
    return results


def speak_brief(today=None):
    """Date, weather, today's events, next shift, due items, and a payday sweep when one is due.

    `today` is only for the sweep line. Pass a date in tests. The other parts
    still describe the real current day. Each part has its own timeout, and a
    part that times out is replaced by a short spoken fallback (or left out).
    After the line is built, shadow mode may record a router tier. The spoken
    line stays the same.
    """
    sections = [
        ("date", speak_date, ""),
        ("weather", speak_weather, "I couldn't check the weather just now."),
        ("calendar", speak_today_schedule, "I couldn't check your calendar just now."),
        ("next_shift", speak_next_shift, "I couldn't check your shifts just now."),
        ("due", lambda: speak_due(limit=3), "I couldn't check your due list just now."),
        ("sweep", lambda: sweep_reminder_line(today), None),
        ("mail", gmail_brief_line, None),
    ]
    parts = _gather(sections)
    spoken = " ".join(part.strip() for part in parts if part and part.strip())
    _shadow_brief(spoken)
    return spoken


def _shadow_brief(spoken):
    try:
        from .router_shadow import observe_command
        observe_command(spoken, "brief")
    except Exception:
        return
