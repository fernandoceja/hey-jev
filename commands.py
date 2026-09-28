"""Local voice commands: apps, calendar, weather, notes, and the iPhone bridge.

Names are parsed from the transcript here, the same way timers parse a duration.
decide() in siri.py calls route_before_api() before any TypeSafe or LLM call.

Nothing in this module listens on a socket. The iPhone bridge only polls an
iCloud Drive folder. App launches, the case-status URL, and shortcut runs go
through argument lists, never a shell string. Message text is returned as
LocalSpeech so the caller can speak it with the macOS say command and must
not send it to Fish or any API.
"""
import csv, difflib, glob, hashlib, hmac, json, os, re, sqlite3, subprocess, threading, time
from datetime import datetime, timedelta

FUZZY_CUTOFF = 0.6
APP_INDEX_TTL = 600  # seconds
CONFIRM_SECONDS = 10
SHORTCUT_FOLDER = "Jev"
# A shift is the next event whose title contains one of these words.
SHIFT_RE = re.compile(r"\b(?:R345|Apple|Brea|shift)\b", re.I)
SHIFT_HORIZON_DAYS = 14
# "What's Zoe got tomorrow": title or calendar name.
ZOE_EVENT_RE = re.compile(r"\b(?:Zoe|school|Cabrillo)\b", re.I)

# "Check my messages from My Love". Phone is an exact handle.id match.
# The email is matched case-insensitively. Edit these here.
MY_LOVE_HANDLES = ("+15623616724", "cgarcilazo6724@icloud.com")
MESSAGES_DB = os.path.expanduser("~/Library/Messages/chat.db")

JEV_DOCS = os.path.expanduser("~/Documents/Jev")
NOTES_PATH = os.path.join(JEV_DOCS, "notes.md")
DUE_PATH = os.path.join(JEV_DOCS, "due.md")
IHSS_PATH = os.path.join(JEV_DOCS, "ihss_hours.csv")
# Today through this many days ahead, including today.
DUE_HORIZON_DAYS = 7

# Upland, CA. Open-Meteo needs no key.
UPLAND_LAT = 34.0975
UPLAND_LON = -117.6484
WEATHER_TIMEOUT = 4

FOCUS_ON_NAME = "Jev Focus On"
FOCUS_OFF_NAME = "Jev Focus Off"
FOCUS_DEFAULT_SECONDS = 25 * 60

# Opened as-is. No receipt number is read or stored.
CASE_STATUS_URL = "https://egov.uscis.gov/"

# Optional Gmail hook. Same Keychain service as the API keys (com.jevsiri.keys).
# The brief stays quiet about mail unless this account holds a token.
GMAIL_TOKEN_ACCOUNT = "GOOGLE_OAUTH_TOKEN"

# iCloud Drive/Jev/inbox. Polled from a background thread. No listening socket.
BRIDGE_INBOX = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/Jev/inbox")
BRIDGE_OUTBOX = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/Jev/outbox")
BRIDGE_SECRET_ACCOUNT = "JEV_BRIDGE_SECRET"
BRIDGE_MAX_AGE = 120
BRIDGE_POLL_SECONDS = 2
NONCE_LOG = os.path.expanduser("~/Library/Application Support/Hey Jev/bridge-nonces.json")
NONCE_LIMIT = 200
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
# Phone commands that may run. No quit-all, no message reading, no confirmation,
# no general shortcut (a Jev shortcut can send a text). Focus runs two fixed names.
BRIDGE_ALLOW = frozenset({
    "info_time",
    "info_date",
    "info_today",
    "info_weather",
    "info_next_event",
    "info_today_schedule",
    "info_next_shift",
    "info_open_apps",
    "info_brief",
    "info_due",
    "info_zoe",
    "note_take",
    "focus_on",
    "ihss_log",
    "case_status",
})
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

# Whole-utterance commands. Checked before the looser patterns below.
_PLEASE = r"(?:please\s+)?"
_TAIL = r"(?:\s+please)?[.!?]*$"
STRICT_PATTERNS = (
    (re.compile(rf"^{_PLEASE}what(?:'s| is) today{_TAIL}", re.I), "info_today"),
    (re.compile(rf"^{_PLEASE}brief me{_TAIL}", re.I), "info_brief"),
    (re.compile(rf"^{_PLEASE}(?:what(?:'s| is) the weather(?:\s+like)?|how(?:'s| is) the weather|weather){_TAIL}", re.I), "info_weather"),
    (re.compile(rf"^{_PLEASE}what(?:'s| is| does| has)\s+zoe\b.*\btomorrow\b{_TAIL}", re.I), "info_zoe"),
    (re.compile(rf"^{_PLEASE}what(?:'s| is) due(?: this week)?{_TAIL}", re.I), "info_due"),
    (re.compile(
        rf"^{_PLEASE}(?:start\s+)?focus\s+mode(?:\s+for\s+.+?)?{_TAIL}"
        rf"|^{_PLEASE}start\s+focus(?:\s+mode)?(?:\s+for\s+.+?)?{_TAIL}",
        re.I), "focus_on"),
    (re.compile(rf"^{_PLEASE}(?:check\s+(?:my\s+)?)?case\s+status{_TAIL}", re.I), "case_status"),
)
_NOTE_CMD_RE = re.compile(rf"^{_PLEASE}take\s+a\s+note\b\s*[:\-]?\s*(.*)$", re.I | re.S)
_IHSS_CMD_RE = re.compile(r"\blog\s+ihss\s+hours\b", re.I)
# Checked in order. More specific calendar phrases come before "what's next".
LOCAL_PATTERNS = (
    (re.compile(r"\b(?:what day is it|what(?:'s| is) the date|what is the date|what(?:'s| is) the day)\b", re.I), "info_date"),
    (re.compile(r"\b(?:what time is it|what(?:'s| is) the time|what is the time|current time)\b", re.I), "info_time"),
    (re.compile(r"\b(?:what(?:'s| is) my schedule(?: today)?|my schedule today|what(?:'s| is) on my calendar today|on my calendar today|what(?:'s| is) on my calendar(?!\s+(?:tomorrow|yesterday)))\b", re.I), "info_today_schedule"),
    (re.compile(r"\b(?:when(?:'s| is) my next shift|what(?:'s| is) my next shift|my next shift|next shift|do i work tomorrow|what time do i start work)\b", re.I), "info_next_shift"),
    (re.compile(r"\b(?:what(?:'s| is) next(?: on my calendar)?|what(?:'s| is) my next (?:event|meeting|appointment)|when(?:'s| is) my next (?:event|meeting|appointment)|next on my calendar)\b", re.I), "info_next_event"),
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


def is_private_message_request(text):
    """True when this utterance is asking to read messages from My Love.

    The command itself must stay off the network, and the message text must
    never be spoken by Fish or handed to an LLM.
    """
    raw = _clean(text)
    if not re.search(r"\bmy love\b", raw, re.I):
        return False
    return bool(re.search(r"\b(?:messages?|texts?|imessages?)\b", raw, re.I))


def route_before_api(text):
    """Action key for one local command, or None.

    decide() calls this before TypeSafe and before the LLM. A joiner such as
    "and" returns None so a two-part sentence can still be split, except a
    note or an IHSS line, whose words may contain "and". Message reads always
    match, joiner or not, so that phrase is never sent out.
    """
    raw = _clean(text).strip()
    if not raw:
        return None
    if _NOTE_CMD_RE.match(raw):
        return "note_take"
    if _IHSS_CMD_RE.search(raw):
        return "ihss_log"
    if is_private_message_request(raw):
        return "info_messages"
    if JOINER_RE.search(raw):
        return None
    for pattern, key in STRICT_PATTERNS:
        if pattern.match(raw):
            return key
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


def preview_action(text):
    """Action key for phrases we answer locally, or None.

    'what time is it in Tokyo' is left for the LLM. A bare 'what time is it' is not.
    """
    return route_before_api(text)


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
    """Next event in 14 days whose title matches R345, Apple, Brea, or shift."""
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


# --------------------------------------------------------------------------- Weather, brief, notes, due, focus, IHSS, Zoe
class LocalSpeech:
    """A reply the caller must speak with macOS say, never Fish and never an API."""

    def __init__(self, text):
        self.text = text or ""


_WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow",
    80: "light rain showers", 81: "rain showers", 82: "heavy rain showers",
    85: "snow showers", 86: "snow showers",
    95: "a thunderstorm", 96: "a thunderstorm", 99: "a thunderstorm",
}
_WEATHER_FAIL = "I couldn't check the weather just now."


def _weather_phrase(code):
    try:
        return _WMO.get(int(code), "mixed conditions")
    except (TypeError, ValueError):
        return "mixed conditions"


def speak_weather():
    """Current conditions, today's high and low, and the chance of rain in Upland."""
    try:
        import requests
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": UPLAND_LAT,
                "longitude": UPLAND_LON,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "timezone": "America/Los_Angeles",
                "forecast_days": 1,
            },
            timeout=WEATHER_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return _WEATHER_FAIL
    current = data.get("current") or {}
    daily = data.get("daily") or {}
    temp = current.get("temperature_2m")
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    if temp is None or not highs or not lows or highs[0] is None or lows[0] is None:
        return _WEATHER_FAIL
    condition = _weather_phrase(current.get("weather_code"))
    line = f"It's {int(round(temp))} degrees and {condition} in Upland. The high is {int(round(highs[0]))} and the low is {int(round(lows[0]))}."
    rain_list = daily.get("precipitation_probability_max") or []
    rain = rain_list[0] if rain_list else None
    if rain is None:
        line += " I don't have a rain chance right now."
    else:
        line += f" Chance of rain is {int(round(rain))} percent."
    return line


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


def gmail_brief_line():
    """One spoken mail sentence for the brief, or None when the step is off.

    Disabled unless the Keychain (service com.jevsiri.keys, account
    GOOGLE_OAUTH_TOKEN) holds an OAuth token. This is a stub: it does not
    import a Google client library and it does not call Google. To fetch mail
    later, replace the body of this function. Callers already skip a None
    result, so the rest of the brief does not change.
    """
    global _gmail_stub_noted
    try:
        from secrets_store import keychain_value
        token = keychain_value(GMAIL_TOKEN_ACCOUNT)
    except Exception:
        return None
    if not token:
        return None
    if not _gmail_stub_noted:
        print("  gmail: a token is in the Keychain, but the brief does not fetch mail yet")
        _gmail_stub_noted = True
    return None


_gmail_stub_noted = False


def speak_brief():
    """Date, weather, today's events, next shift, and the top due items."""
    parts = [
        speak_date(),
        speak_weather(),
        speak_today_schedule(),
        speak_next_shift(),
        speak_due(limit=3),
    ]
    mail = gmail_brief_line()
    if mail:
        parts.append(mail)
    return " ".join(part.strip() for part in parts if part and part.strip())


def _month_day(day):
    return f"{day:%B} {_ordinal(day.day)}"


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


def _read_due_lines():
    """(date, title) pairs due from today through DUE_HORIZON_DAYS, soonest first.

    None when the file is missing. A line needs a YYYY-MM-DD date. The rest of
    the line, without the date and a leading dash, is the item.
    """
    if not os.path.isfile(DUE_PATH):
        return None
    today = datetime.now().astimezone().date()
    horizon = today + timedelta(days=DUE_HORIZON_DAYS)
    found = []
    with open(DUE_PATH, encoding="utf-8") as handle:
        for raw in handle:
            match = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
            if not match:
                continue
            try:
                day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < today or day > horizon:
                continue
            title = raw.strip()
            title = re.sub(r"^[-*]\s*", "", title)
            title = title.replace(match.group(1), " ")
            title = re.sub(r"\s+", " ", title).strip(" :-–—")
            if title:
                found.append((day, title))
    found.sort(key=lambda item: (item[0], item[1].lower()))
    return found


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


def run_jev_folder_shortcut(name):
    """Run one shortcut by its real name, if it is in the Jev folder.

    Returns None on success, or a sentence describing why it did not run.
    """
    names = list_jev_shortcuts()
    if names is None:
        return "I only run shortcuts in the Jev folder, and I couldn't find that folder."
    resolved = resolve_shortcut(name, names)
    if not resolved:
        return f"Add a shortcut named {name} to the Jev folder."
    try:
        _run(("shortcuts", "run", resolved), timeout=120)
    except subprocess.TimeoutExpired:
        return f"{name} took too long, so I stopped waiting."
    except RuntimeError:
        return f"I couldn't run {name}."
    return None


def _spoken_span(seconds):
    seconds = int(seconds)
    if seconds < 90:
        n = max(1, seconds)
        return "1 second" if n == 1 else f"{n} seconds"
    minutes = max(1, int(round(seconds / 60.0)))
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


def begin_focus(seconds, arm):
    """Run 'Jev Focus On' and arm a timer. arm(seconds) is called only on success."""
    problem = run_jev_folder_shortcut(FOCUS_ON_NAME)
    if problem:
        return problem
    try:
        arm(int(seconds))
    except Exception:
        return "Focus is on, but I couldn't start the timer."
    return f"Focus is on for {_spoken_span(seconds)}."


def finish_focus():
    """Run 'Jev Focus Off' and return the line to announce."""
    problem = run_jev_folder_shortcut(FOCUS_OFF_NAME)
    if problem:
        return "Focus time is up. " + problem
    return "Focus is off."


def _semi_period(day):
    """(start, end) dates of the semi-monthly period that contains day."""
    if day.day <= 15:
        return day.replace(day=1), day.replace(day=15)
    if day.month == 12:
        next_month = day.replace(year=day.year + 1, month=1, day=1)
    else:
        next_month = day.replace(month=day.month + 1, day=1)
    return day.replace(day=16), next_month - timedelta(days=1)


def _hours_phrase(hours):
    if abs(hours - round(hours)) < 0.001:
        whole = int(round(hours))
        return "1 hour" if whole == 1 else f"{whole} hours"
    text = f"{hours:.2f}".rstrip("0").rstrip(".")
    return f"{text} hours"


def _parse_ihss(text):
    match = re.search(
        r"\blog\s+ihss\s+hours\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:hours?)?\b(?:\s+(today|yesterday))?",
        _clean(text), re.I,
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
    new_file = not os.path.isfile(IHSS_PATH)
    with open(IHSS_PATH, "a", encoding="utf-8", newline="") as handle:
        if new_file:
            handle.write("date,hours\n")
        handle.write(f"{when.isoformat()},{hours:.2f}\n")
    today = datetime.now().astimezone().date()
    try:
        total, start, end = _period_total(IHSS_PATH, today)
    except OSError:
        return f"Logged {_hours_phrase(hours)} for {_month_day(when)}. I couldn't total the period."
    return (
        f"Logged {_hours_phrase(hours)} for {_month_day(when)}. "
        f"This period, {_month_day(start)} through {_month_day(end)}, totals {_hours_phrase(total)}."
    )


def open_case_status():
    """Open the USCIS case-status site. The receipt number is never stored."""
    try:
        subprocess.run(["open", CASE_STATUS_URL], check=True)
    except Exception:
        return "I couldn't open the case status site."
    return "Opening the case status site."


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


# --------------------------------------------------------------------------- Messages (local say only)
_FDA_MESSAGE = (
    "I can't read Messages yet. Turn on Full Disk Access for Hey Jev "
    "in System Settings, Privacy and Security, then ask me again."
)


def _is_fda_error(exc):
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (1, 13):
        return True
    text = str(exc).lower()
    return any(needle in text for needle in (
        "authorization", "operation not permitted", "permission denied",
        "unable to open database", "not authorized",
    ))


def decode_attributed_body(blob):
    """Plain text from message.attributedBody when the text column is null.

    The blob is a typedstream NSAttributedString. After an NSString marker
    there is a short preamble ending in '+', then a length (one byte, or
    0x81 plus a little-endian uint16), then that many UTF-8 bytes.
    """
    if not blob:
        return ""
    if not isinstance(blob, (bytes, bytearray)):
        try:
            blob = bytes(blob)
        except Exception:
            return ""
    marker = b"NSString"
    start = 0
    while True:
        idx = blob.find(marker, start)
        if idx < 0:
            return ""
        window = blob[idx + len(marker):idx + len(marker) + 8]
        plus = window.find(b"+")
        if plus < 0:
            start = idx + len(marker)
            continue
        content = blob[idx + len(marker) + plus + 1:]
        text = _typedstream_string(content)
        if text:
            return text
        start = idx + len(marker)


def _typedstream_string(content):
    if not content:
        return ""
    if content[0] == 0x81:
        if len(content) < 3:
            return ""
        length = int.from_bytes(content[1:3], "little")
        raw = content[3:3 + length]
    else:
        length = content[0]
        raw = content[1:1 + length]
    if length <= 0 or len(raw) != length:
        return ""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    if not text:
        return ""
    printable = sum(ch.isprintable() or ch in "\n\t" for ch in text)
    if printable < max(1, int(len(text) * 0.85)):
        return ""
    return text


def _message_body(text, blob):
    if text is not None and str(text).strip():
        return str(text).strip()
    decoded = decode_attributed_body(blob)
    return decoded.strip() if decoded else ""


def _clip_speech(text, limit=400):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + ", and more"


def _probe_messages_db():
    """'ok', 'missing', 'fda', or 'error'. A one-byte read is the permission check."""
    try:
        with open(MESSAGES_DB, "rb") as handle:
            handle.read(16)
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        return "fda" if _is_fda_error(exc) else "error"
    return "ok"


def _open_messages_db():
    """A read-only connection, plus a cleanup callable.

    Opens chat.db in place when SQLite allows it. A WAL database sometimes
    refuses mode=ro because it cannot create a shared-memory file beside
    Messages, so then the db and its wal are copied to a temp folder and
    read from there. The Messages folder itself is never written.
    """
    import shutil
    import tempfile
    from urllib.parse import quote

    uri = "file:" + quote(MESSAGES_DB) + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("PRAGMA query_only = ON")
        return conn, conn.close
    except sqlite3.Error:
        pass
    folder = tempfile.mkdtemp(prefix="jev-msg-")
    try:
        dest = os.path.join(folder, "chat.db")
        shutil.copy2(MESSAGES_DB, dest)
        for suffix in ("-wal", "-shm"):
            src = MESSAGES_DB + suffix
            if os.path.isfile(src):
                shutil.copy2(src, dest + suffix)
        conn = sqlite3.connect(dest)
        conn.execute("PRAGMA query_only = ON")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    def cleanup():
        conn.close()
        shutil.rmtree(folder, ignore_errors=True)

    return conn, cleanup


def speak_my_love_messages():
    """Latest 3 incoming messages from My Love. Always a LocalSpeech result.

    Read-only sqlite. The body is not logged. Full Disk Access errors become
    a short local sentence instead of a traceback.
    """
    probed = _probe_messages_db()
    if probed == "fda":
        return LocalSpeech(_FDA_MESSAGE)
    if probed == "missing":
        return LocalSpeech("I couldn't find the Messages database.")
    if probed != "ok":
        return LocalSpeech("I couldn't read Messages just now.")
    clauses, params = [], []
    for handle_id in MY_LOVE_HANDLES:
        if "@" in handle_id:
            clauses.append("lower(h.id) = lower(?)")
        else:
            clauses.append("h.id = ?")
        params.append(handle_id)
    sql = f"""
        SELECT m.text, m.attributedBody
        FROM message AS m
        JOIN handle AS h ON h.ROWID = m.handle_id
        WHERE m.is_from_me = 0
          AND ifnull(m.associated_message_type, 0) = 0
          AND ({' OR '.join(clauses)})
        ORDER BY m.date DESC
        LIMIT 15
    """
    conn, cleanup = None, None
    try:
        conn, cleanup = _open_messages_db()
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # Older chat.db builds may not have associated_message_type.
            sql_plain = sql.replace("AND ifnull(m.associated_message_type, 0) = 0\n          ", "")
            rows = conn.execute(sql_plain, params).fetchall()
    except Exception as exc:
        if _is_fda_error(exc):
            return LocalSpeech(_FDA_MESSAGE)
        return LocalSpeech("I couldn't read Messages just now.")
    finally:
        if cleanup is not None:
            cleanup()
    bodies = []
    for text, blob in rows:
        body = _message_body(text, blob)
        if body:
            bodies.append(_clip_speech(body))
        if len(bodies) == 3:
            break
    if not bodies:
        if rows:
            return LocalSpeech("I found messages from My Love, but I couldn't read them.")
        return LocalSpeech("No messages from My Love.")
    bodies.reverse()  # oldest of the three first, so they play in order
    if len(bodies) == 1:
        return LocalSpeech("My Love said: " + bodies[0])
    labels = ("First", "Second", "Third")
    pieces = [f"{labels[i]}: {bodies[i]}." for i in range(len(bodies))]
    return LocalSpeech(f"{len(bodies)} messages from My Love. " + " ".join(pieces))


# --------------------------------------------------------------------------- iPhone bridge (iCloud files only, no listener)
_bridge_thread = None
_bridge_lock = threading.Lock()
_bridge_secret_warned = False


def bridge_allowed(text):
    """Action key when a phone command is on the allowlist, else None.

    Quit-all never comes back from route_before_api(). Message reads do, and
    they are absent from BRIDGE_ALLOW, so the body cannot be written to iCloud.
    """
    action = route_before_api(text)
    if not action or action in CONFIRM or action not in BRIDGE_ALLOW:
        return None
    return action


def _canonical_ts(ts):
    """Decimal unix seconds, the form that is signed. None if it is not whole seconds."""
    if isinstance(ts, bool):
        return None
    if isinstance(ts, int):
        return str(ts)
    if isinstance(ts, float):
        if not ts.is_integer():
            return None
        return str(int(ts))
    if isinstance(ts, str) and re.fullmatch(r"-?\d+", ts.strip()):
        return ts.strip()
    return None


def _bridge_secret():
    """Keychain only. A .env value must not be able to stand in for this."""
    from secrets_store import keychain_value
    return keychain_value(BRIDGE_SECRET_ACCOUNT)


def _expected_sig(secret, cmd, ts_canon, nonce):
    payload = f"{cmd}|{ts_canon}|{nonce}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _load_nonces():
    try:
        with open(NONCE_LOG, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str)]


def _remember_nonce(nonce):
    os.makedirs(os.path.dirname(NONCE_LOG), exist_ok=True)
    seen = [item for item in _load_nonces() if item != nonce]
    seen.append(nonce)
    seen = seen[-NONCE_LIMIT:]
    tmp = NONCE_LOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(seen, handle)
    os.replace(tmp, NONCE_LOG)


def _nonce_used(nonce):
    return nonce in _load_nonces()


def _write_outbox(nonce, ok, reply):
    os.makedirs(BRIDGE_OUTBOX, exist_ok=True)
    dest = os.path.join(BRIDGE_OUTBOX, nonce + ".json")
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"ok": bool(ok), "nonce": nonce, "reply": reply}, handle)
        handle.write("\n")
    os.replace(tmp, dest)


def _delete_inbox(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _process_bridge_file(path, run_text):
    """Validate one inbox file, maybe run it, always try to clear it once it is JSON."""
    global _bridge_secret_warned
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        age = time.time() - os.path.getmtime(path)
        if age > 30:
            _delete_inbox(path)
        return
    if not isinstance(data, dict):
        _delete_inbox(path)
        return
    cmd = data.get("cmd")
    nonce = data.get("nonce")
    sig = data.get("sig")
    ts_canon = _canonical_ts(data.get("ts"))
    safe_nonce = isinstance(nonce, str) and bool(NONCE_RE.match(nonce))
    if not isinstance(cmd, str) or not safe_nonce or not isinstance(sig, str) or ts_canon is None:
        if safe_nonce:
            _write_outbox(nonce, False, "That command file was incomplete.")
        _delete_inbox(path)
        return
    secret = _bridge_secret()
    if not secret:
        if not _bridge_secret_warned:
            print("  bridge: no JEV_BRIDGE_SECRET in the Keychain. Run python siri.py --bridge-secret")
            _bridge_secret_warned = True
        return  # leave the file so it can run once a secret exists
    expected = _expected_sig(secret, cmd, ts_canon, nonce)
    if not hmac.compare_digest(expected, sig.strip().lower()):
        _write_outbox(nonce, False, "I couldn't verify that command.")
        _remember_nonce(nonce)
        _delete_inbox(path)
        return
    try:
        age = abs(time.time() - int(ts_canon))
    except ValueError:
        age = BRIDGE_MAX_AGE + 1
    if age > BRIDGE_MAX_AGE:
        _write_outbox(nonce, False, "That command was too old. Try again.")
        _remember_nonce(nonce)
        _delete_inbox(path)
        return
    if _nonce_used(nonce):
        _write_outbox(nonce, False, "I already did that.")
        _delete_inbox(path)
        return
    _remember_nonce(nonce)
    if len(cmd) > 2000:
        _write_outbox(nonce, False, "That command is too long.")
        _delete_inbox(path)
        return
    action = bridge_allowed(cmd)
    if not action:
        _write_outbox(nonce, False, "I can't do that from your phone.")
        _delete_inbox(path)
        return
    ok = True
    try:
        reply = run_text(cmd.strip())
    except Exception as exc:
        print(f"  bridge: {type(exc).__name__}")
        ok, reply = False, "I couldn't do that just now."
    if not reply:
        ok, reply = False, "I couldn't do that just now."
    _write_outbox(nonce, ok, reply)
    _delete_inbox(path)


def poll_bridge(run_text):
    """Handle every JSON file currently in the iCloud inbox. No socket is opened."""
    try:
        os.makedirs(BRIDGE_INBOX, exist_ok=True)
        os.makedirs(BRIDGE_OUTBOX, exist_ok=True)
    except OSError as exc:
        print(f"  bridge: {exc}")
        return
    try:
        names = sorted(os.listdir(BRIDGE_INBOX))
    except OSError as exc:
        print(f"  bridge: {exc}")
        return
    for name in names:
        if name.startswith(".") or not name.endswith(".json"):
            continue
        path = os.path.join(BRIDGE_INBOX, name)
        if not os.path.isfile(path):
            continue
        try:
            _process_bridge_file(path, run_text)
        except Exception as exc:
            print(f"  bridge: {type(exc).__name__}")


def start_bridge_thread(run_text):
    """Poll the inbox every 2 seconds. run_text(cmd) returns the spoken reply."""
    global _bridge_thread

    def loop():
        while True:
            try:
                poll_bridge(run_text)
            except Exception as exc:
                print(f"  bridge: {type(exc).__name__}")
            time.sleep(BRIDGE_POLL_SECONDS)

    with _bridge_lock:
        if _bridge_thread is not None and _bridge_thread.is_alive():
            return
        _bridge_thread = threading.Thread(target=loop, name="jev-bridge", daemon=True)
        _bridge_thread.start()


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
