"""Round 1 voice commands: any app, time and date, calendar, shortcuts.

Jev still decides the intent. It cannot return free text, so names are parsed
from the transcript here, the same way timers parse a duration. Nothing in this
module listens on the network. App launches and shortcut runs go through
argument lists, never a shell string.
"""
import difflib, glob, os, re, subprocess, threading, time
from datetime import datetime, timedelta

FUZZY_CUTOFF = 0.6
APP_INDEX_TTL = 600  # seconds
CONFIRM_SECONDS = 10
SHORTCUT_FOLDER = "Jev"
# A shift is the next event whose title contains one of these words.
SHIFT_RE = re.compile(r"\b(?:R345|Apple|shift)\b", re.I)
SHIFT_HORIZON_DAYS = 14
# Spoken text is matched against these after spaces and punctuation are stripped.
APP_ALIASES = {
    "chatgpt": "ChatGPT",
    "gpt": "ChatGPT",
    "capcut": "CapCut",
    "cursor": "Cursor",
    "claude": "Claude",
    "vscode": "Visual Studio Code",
    "chrome": "Google Chrome",
    "googlechrome": "Google Chrome",
    "spotify": "Spotify",
    "slack": "Slack",
    "finder": "Finder",
    "safari": "Safari",
    "messages": "Messages",
    "notes": "Notes",
}
APP_DIRS = (
    "/System/Applications",
    "/System/Applications/Utilities",
    "/Applications",
    "/Applications/Utilities",
    os.path.expanduser("~/Applications"),
)
FINDER_PATH = "/System/Library/CoreServices/Finder.app"
# terminate() would log the user out or kill the assistant. Matched by bundle id and name.
PROTECTED_IDS = {
    "com.apple.finder",
    "com.apple.loginwindow",
    "com.apple.systempreferences",
    "com.heyjev.app",
}
PROTECTED_NAMES = {"finder", "loginwindow", "system settings", "system preferences"}
# Actions that must be confirmed out loud before they run. Never inside a two-part command.
CONFIRM = {"apps_quit_all"}

_index_cache = {"at": 0.0, "idx": None}
_store = None
_calendar_granted = False
_PENDING = {"action": None, "arg": None, "source": None, "reply_key": None, "fmt": None, "expires": 0.0}

YES_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|confirm|do it)"
    r"(?:\s*,?\s*(?:please|quit(?:\s+them)?|close(?:\s+them)?|do it|confirm))?[.!?]*$",
    re.I,
)
NO_RE = re.compile(r"^(?:no|nope|nah|cancel|stop|never mind|nevermind)(?:\s*,?\s*please)?[.!?]*$", re.I)
QUIT_ALL_RE = re.compile(
    r"\b(?:quit|close|kill|force quit)\s+(?:all\s+(?:the\s+)?apps?|everything|every\s+app)\b"
    r"|^\s*(?:please\s+)?(?:quit|close|kill)\s+all(?:\s+of\s+them)?\s*[.!?]*$",
    re.I,
)
QUIT_ALL_ONLY_RE = re.compile(
    r"(?:please\s+)?(?:quit|close|kill|force quit)\s+"
    r"(?:all(?:\s+(?:the\s+)?apps?|\s+of\s+them)?|everything|every\s+app)"
    r"(?:\s+please)?[.!?]*",
    re.I,
)
_OPEN_VERBS = r"open|launch|start|bring up|switch to"
_QUIT_VERBS = r"force quit|quit|close|kill"
JOINER_RE = re.compile(r"\b(?:and|then)\b", re.I)

# Checked in order. More specific calendar phrases come before "what's next".
LOCAL_PATTERNS = (
    (re.compile(r"\b(?:what day is it|what(?:'s| is) the date|what is the date|what(?:'s| is) today|what is today|what(?:'s| is) the day)\b", re.I), "info_date"),
    (re.compile(r"\b(?:what time is it|what(?:'s| is) the time|what is the time|current time)\b", re.I), "info_time"),
    (re.compile(r"\b(?:what(?:'s| is) my schedule(?: today)?|my schedule today|what(?:'s| is) on my calendar today|on my calendar today)\b", re.I), "info_today_schedule"),
    (re.compile(r"\b(?:when(?:'s| is) my next shift|what(?:'s| is) my next shift|my next shift|next shift|do i work tomorrow|what time do i start work)\b", re.I), "info_next_shift"),
    (re.compile(r"\b(?:what(?:'s| is) next(?: on my calendar)?|what(?:'s| is) my next (?:event|meeting|appointment)|next on my calendar)\b", re.I), "info_next_event"),
    (re.compile(r"\b(?:what apps are open|which apps are open|which apps do i have open|what do i have open|what(?:'s| is) running)\b", re.I), "info_open_apps"),
)


def _clean(text):
    return (text or "").replace("’", "'").replace("‘", "'")


def _norm(text):
    """'cap cut' and 'CapCut' both become 'capcut'."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _run(args, timeout=30):
    """Run a command from an argument list. Never passes a shell string."""
    result = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    return result.stdout


# --------------------------------------------------------------------------- Confirmation
def confirmation_pending():
    return bool(_PENDING["action"]) and time.time() < _PENDING["expires"]


def clear_confirmation():
    _PENDING.update(action=None, arg=None, source=None, reply_key=None, fmt=None, expires=0.0)


def arm_confirmation(action, arg, source, reply_key, fmt, seconds=CONFIRM_SECONDS):
    _PENDING.update(action=action, arg=arg, source=source, reply_key=reply_key,
                    fmt=dict(fmt or {}), expires=time.time() + seconds)


def refresh_confirmation(seconds=CONFIRM_SECONDS):
    """Restart the window once the prompt has finished speaking."""
    if _PENDING["action"]:
        _PENDING["expires"] = time.time() + seconds


def confirmation_status(text):
    """Yes/no for a pending confirmation. Local regex only: no network, no Jev.

    Returns 'yes', 'no', 'expired', 'other', or None when nothing is waiting.
    'other' and 'expired' clear the pending action so the utterance is handled normally.
    """
    if not _PENDING["action"]:
        return None
    if time.time() >= _PENDING["expires"]:
        clear_confirmation()
        return "expired"
    stripped = _clean(text).strip()
    if YES_RE.match(stripped):
        return "yes"
    if NO_RE.match(stripped):
        return "no"
    clear_confirmation()
    return "other"


def take_confirmation():
    """Return the armed action and clear it. Call only after confirmation_status says yes."""
    data = (_PENDING["action"], _PENDING["arg"], _PENDING["source"],
            _PENDING["reply_key"], dict(_PENDING["fmt"] or {}))
    clear_confirmation()
    return data


def isolate_confirmations(actions):
    """Drop the other half of a two-part command when one half needs confirmation."""
    if not actions:
        return actions
    hit = [a for a in actions if a[1] in CONFIRM]
    if hit and len(actions) > 1:
        return hit[:1]
    return actions


def is_quit_all(text):
    raw = _clean(text)
    if re.search(r"\b(?:timer|timers|reminder|reminders)\b", raw, re.I):
        return False
    return bool(QUIT_ALL_RE.search(raw))


def quit_all_is_compound(text, jev_compound):
    """True when this utterance asks for something besides quitting every app.

    A bare 'quit all' is allowed even if Jev marks it compound. 'quit all and open Notes'
    is not: confirmation is never one half of a two-part command.
    """
    raw = _clean(text).strip()
    if JOINER_RE.search(raw):
        return True
    only = bool(QUIT_ALL_ONLY_RE.fullmatch(raw))
    return bool(jev_compound) and not only


def preview_action(text):
    """Action key for phrases we answer locally, or None.

    'what time is it in Tokyo' is left for the LLM. A bare 'what time is it' is not.
    """
    raw = _clean(text).strip()
    if not raw:
        return None
    for pattern, key in LOCAL_PATTERNS:
        if not pattern.search(raw):
            continue
        if key == "info_time" and re.search(r"\b(?:in|for)\s+[A-Za-z]", raw, re.I):
            continue
        # "what's the time left" is a timer check, not the clock.
        if key == "info_time" and re.search(r"\b(?:left|remaining|timer|timers)\b", raw, re.I):
            continue
        return key
    if parse_shortcut_name(raw):
        return "shortcut_run"
    return None


# --------------------------------------------------------------------------- Apps
def app_index(force=False):
    """Map a normalized app name to its .app path. Cached for APP_INDEX_TTL."""
    now = time.time()
    if not force and _index_cache["idx"] is not None and now - _index_cache["at"] < APP_INDEX_TTL:
        return _index_cache["idx"]
    idx = {}
    if os.path.isdir(FINDER_PATH):
        idx["finder"] = FINDER_PATH
    for folder in APP_DIRS:
        if not os.path.isdir(folder):
            continue
        for path in glob.glob(os.path.join(folder, "*.app")):
            idx[_norm(os.path.basename(path)[:-4])] = path
    _index_cache["idx"] = idx
    _index_cache["at"] = now
    return idx


def _display_name(path):
    base = os.path.basename(path)
    return base[:-4] if base.lower().endswith(".app") else base


def resolve_app(spoken, idx=None):
    """Return (path, display name) for a spoken app, or None."""
    if not spoken:
        return None
    idx = app_index() if idx is None else idx
    wanted = _norm(APP_ALIASES.get(_norm(spoken), spoken))
    if not wanted:
        return None
    path = idx.get(wanted)
    if path:
        return path, _display_name(path)
    # One- and two-letter names fuzzy-match almost anything, so require an exact hit.
    if len(wanted) < 3:
        return None
    match = difflib.get_close_matches(wanted, list(idx.keys()), n=1, cutoff=FUZZY_CUTOFF)
    if not match:
        return None
    path = idx[match[0]]
    return path, _display_name(path)


def parse_app_name(text, kind=None):
    """Pull the app name out of 'open cap cut' / 'quit the Claude app'.

    kind is 'open' or 'quit', so a two-part sentence ('quit Chrome and open Notes')
    doesn't hand both actions the first name. The name stops at 'and' or 'then'.
    """
    if is_quit_all(text):
        return None
    verbs = {"open": _OPEN_VERBS, "quit": _QUIT_VERBS}.get(kind, _OPEN_VERBS + "|" + _QUIT_VERBS)
    match = re.search(
        rf"\b(?:{verbs})\s+(?:up\s+)?(?:the\s+)?(.+?)(?=\s+(?:and|then)\b|[,.!?]|$)",
        _clean(text).strip(), re.I,
    )
    if not match:
        return None
    name = match.group(1).strip(" .,!?")
    name = re.sub(r"^(?:up|the|my|an|a)\s+", "", name, flags=re.I)
    name = re.sub(r"\s+(?:app|application|please|for me)$", "", name, flags=re.I).strip(" .,!?")
    if not name or re.fullmatch(r"all|everything|every app|all apps|all of them", name, re.I):
        return None
    return name


def _appkit():
    from AppKit import NSApplicationActivationPolicyRegular, NSWorkspace
    return NSWorkspace, NSApplicationActivationPolicyRegular


def running_regular_apps():
    """Foreground apps. This does not need Automation, unlike System Events processes."""
    NSWorkspace, regular = _appkit()
    return [app for app in NSWorkspace.sharedWorkspace().runningApplications()
            if app.activationPolicy() == regular]


def _own_pids():
    pids = {os.getpid()}
    try:
        pids.add(os.getppid())
    except OSError:
        pass
    return pids


def _is_self(app):
    try:
        if int(app.processIdentifier()) in _own_pids():
            return True
    except (TypeError, ValueError):
        pass
    name = str(app.localizedName() or "").lower()
    return "hey jev" in name


def is_protected(app):
    """Finder, Hey Jev, loginwindow, and System Settings are never quit."""
    if _is_self(app):
        return True
    bundle = str(app.bundleIdentifier() or "")
    if bundle in PROTECTED_IDS:
        return True
    return str(app.localizedName() or "").lower() in PROTECTED_NAMES


def _running_match(spoken):
    """The running regular app that best matches a spoken name, including protected ones."""
    wanted = _norm(APP_ALIASES.get(_norm(spoken), spoken))
    if not wanted:
        return None
    apps = running_regular_apps()
    exact = [app for app in apps if _norm(str(app.localizedName() or "")) == wanted]
    if exact:
        return exact[0]
    if len(wanted) < 3:
        return None
    by_key = {}
    for app in apps:
        key = _norm(str(app.localizedName() or ""))
        if key and key not in by_key:
            by_key[key] = app
    match = difflib.get_close_matches(wanted, list(by_key.keys()), n=1, cutoff=FUZZY_CUTOFF)
    return by_key[match[0]] if match else None


def _is_running(target):
    NSWorkspace, _regular = _appkit()
    want_path = os.path.realpath(target) if target.endswith(".app") else None
    want_name = _norm(_display_name(target) if want_path else target)
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if want_path:
            url = app.bundleURL()
            if url is not None and os.path.realpath(str(url.path())) == want_path:
                return True
        elif _norm(str(app.localizedName() or "")) == want_name:
            return True
    return False


def launch_app(target):
    """open -a with an argument list, then wait until the app reports running.

    The wait is what lets 'open Spotify and play' land the play after the launch.
    """
    _run(("open", "-a", target))
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            if _is_running(target):
                return
        except Exception:
            return
        time.sleep(0.2)


def open_any_app(arg, text, favourites):
    """Launch a spoken app. favourites is the small APPS map, used only when the transcript has no name."""
    spoken = parse_app_name(text, "open")
    from_enum = False
    if not spoken and arg in favourites:
        spoken = favourites[arg]
        from_enum = True
    if not spoken:
        return "Which app should I open?"
    found = resolve_app(spoken) or resolve_app(spoken, app_index(force=True))
    if not found and from_enum:
        # open -a accepts a display name when the .app isn't in the indexed folders.
        found = (favourites[arg], favourites[arg])
    if not found:
        return f"I couldn't find an app called {spoken}."
    path, display = found
    launch_app(path)
    # {app} in the scripted reply is filled in by the caller. Only APPS names are pre-rendered.
    return {"app": display.replace("{", "").replace("}", "")}


def quit_any_app(arg, text, favourites):
    """Polite quit via NSRunningApplication.terminate(). No per-app Automation prompt."""
    if is_quit_all(text):
        return "Say quit all on its own, then yes to confirm."
    spoken = parse_app_name(text, "quit")
    if not spoken and arg in favourites:
        spoken = favourites[arg]
    if not spoken:
        return "Which app should I quit?"
    try:
        app = _running_match(spoken)
    except Exception:
        return "I couldn't check which apps are running."
    if app is None:
        return f"{spoken} isn't running."
    name = str(app.localizedName() or spoken)
    if is_protected(app):
        return f"I won't quit {name}."
    if not app.terminate():
        return f"I couldn't quit {name}."
    return {"app": name.replace("{", "").replace("}", "")}


def quit_all_apps():
    """Quit every regular app except Finder, Hey Jev, and the other protected ones.

    Only call this after a spoken yes. terminate() still lets each app ask to save.
    """
    try:
        apps = [app for app in running_regular_apps() if not is_protected(app)]
    except Exception:
        return "I couldn't check which apps are running."
    if not apps:
        return "There's nothing else to quit."
    quit_names = []
    for app in apps:
        name = str(app.localizedName() or "").strip()
        if app.terminate() and name:
            quit_names.append(name)
    if not quit_names:
        return "I couldn't quit those apps."
    if len(quit_names) == 1:
        return f"Quitting {quit_names[0]}."
    return f"Quitting {len(quit_names)} apps."


def speak_open_apps():
    try:
        apps = running_regular_apps()
    except Exception:
        return "I couldn't check which apps are open."
    names, seen = [], set()
    for app in apps:
        if _is_self(app):
            continue
        name = str(app.localizedName() or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    if not names:
        return "No other apps are open."
    if len(names) == 1:
        return f"You've got {names[0]} open."
    if len(names) == 2:
        return f"You've got {names[0]} and {names[1]} open."
    return "You've got " + ", ".join(names[:-1]) + f", and {names[-1]} open."


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


def speak_time():
    now = datetime.now().astimezone()
    return f"It's {_clock(now)}, {now:%A %B} {_ordinal(now.day)}."


def speak_date():
    now = datetime.now().astimezone()
    return f"Today is {now:%A, %B} {_ordinal(now.day)}, {now.year}."


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


def speak_next_shift():
    """Next event in 14 days whose title matches R345, Apple, or shift."""
    problem = _calendar_problem()
    if problem:
        return problem
    now = datetime.now().astimezone()
    horizon = now + timedelta(days=SHIFT_HORIZON_DAYS)
    try:
        events = _upcoming(_events_between(now - timedelta(hours=12), horizon), now, horizon, skip_all_day=False)
    except Exception:
        return _CAL_FAILED
    shifts = [ev for ev in events if SHIFT_RE.search(_title(ev))]
    if not shifts:
        return "No shift in the next two weeks."
    ev = shifts[0]
    title, start, finish = _title(ev), _stamp(ev.startDate()), _stamp(ev.endDate())
    if _all_day(ev):
        return f"Your next shift is {title} {_day_phrase(start, now)}, all day."
    if start <= now:
        return f"You're on {title} until {_clock(finish)}."
    return f"Your next shift is {title} {_day_phrase(start, now)} at {_clock(start)}."


def _join_names(items):
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


# --------------------------------------------------------------------------- Shortcuts (Jev folder only)
def parse_shortcut_name(text):
    """Name from 'run shortcut Leaving for work', 'run my Focus shortcut', 'do Jev morning'."""
    raw = _clean(text).strip()
    patterns = (
        r"\b(?:run|start|trigger)\s+(?:my\s+)?(?:the\s+)?shortcut(?:\s+named|\s+called)?\s+(.+)$",
        r"\b(?:run|start|do)\s+my\s+(.+?)\s+shortcut\s*$",
        r"\bdo\s+jev\s+(.+)$",
    )
    name = None
    for pattern in patterns:
        match = re.search(pattern, raw, re.I)
        if match:
            name = match.group(1).strip(" .,!?")
            break
    if not name:
        return None
    # "run shortcut Morning and open Notes" — the shortcut name stops at the join.
    name = re.split(r"\s+(?:and|then)\b", name, maxsplit=1, flags=re.I)[0]
    name = re.sub(r"\s+shortcut$", "", name, flags=re.I).strip(" .,!?")
    if not name or re.fullmatch(r"jev", name, re.I):
        return None
    return name


def list_jev_shortcuts():
    """Names from `shortcuts list --folder-name Jev`. None when the command fails."""
    try:
        result = subprocess.run(
            ["shortcuts", "list", "--folder-name", SHORTCUT_FOLDER],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def resolve_shortcut(spoken, names):
    """Fuzzy-match a spoken name against the Jev folder only. Returns the canonical name."""
    if not spoken or not names:
        return None
    for name in names:
        if name.lower() == spoken.lower():
            return name
    by_key = {}
    for name in names:
        by_key.setdefault(_norm(name), name)
    wanted = _norm(spoken)
    if wanted in by_key:
        return by_key[wanted]
    if len(wanted) < 3:
        return None
    match = difflib.get_close_matches(wanted, list(by_key.keys()), n=1, cutoff=FUZZY_CUTOFF)
    return by_key[match[0]] if match else None


def run_named_shortcut(text):
    """Run one shortcut that appears in the Jev folder. Anything else is refused."""
    spoken = parse_shortcut_name(text)
    if not spoken:
        return "Which shortcut should I run?"
    names = list_jev_shortcuts()
    if names is None:
        return "I only run shortcuts in the Jev folder, and I couldn't find that folder."
    if not names:
        return "The Jev shortcuts folder is empty."
    name = resolve_shortcut(spoken, names)
    if not name:
        return f"I couldn't find {spoken} in the Jev shortcuts folder."
    try:
        _run(("shortcuts", "run", name), timeout=120)
    except subprocess.TimeoutExpired:
        return f"{name} took too long, so I stopped waiting."
    except RuntimeError:
        return f"I couldn't run {name}."
    return f"Ran {name}."
