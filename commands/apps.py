"""Resolve, launch, and quit apps, plus site and folder name lookup."""
import difflib
import glob
import os
import re
import time
from .config import APP_DIRS, APP_FUZZY_CUTOFF, APP_INDEX_TTL, APP_NICKNAMES, FINDER_PATH, FOLDER_PATHS, FUZZY_CUTOFF, KNOWN_APPS, PROTECTED_IDS, PROTECTED_NAMES, SITE_CONFIG, _FOCUS_VERBS, _HIDE_VERBS, _OPEN_VERBS, _QUIT_VERBS
from .textutil import _clean, _norm
from .shell import _run
from .confirm import is_quit_all

_index_cache = {"at": 0.0, "idx": None}


def app_alias_map():
    """Normalized spoken name -> `open -a` display name. Nicknames win over the plain name."""
    found = {}
    for name in KNOWN_APPS:
        found.setdefault(_norm(name), name)
    for spoken, name in APP_NICKNAMES.items():
        found[_norm(spoken)] = name
    return found


def site_index():
    """Normalized spoken name -> site config dict."""
    found = {}
    for entry in SITE_CONFIG:
        for phrase in entry["phrases"]:
            found[_norm(phrase)] = entry
    return found


# NSApplicationActivateIgnoringOtherApps. One app comes forward. Nothing is killed.
_ACTIVATE_IGNORING = 2


def _tidy_spoken(spoken):
    """Drop extra spaces and trailing punctuation. Case is left for _norm."""
    text = " ".join(_clean(spoken or "").split())
    return text.strip(".,!?;:").strip()


# "chat gpt", "chat g p t", "chatgpt", and "chat GPT" are one app.
# "ChatGPT Classic" does not match: the pattern is the whole name.
_CHAT_GPT_RE = re.compile(r"(?:chat\s*g\s*p\s*t|chat\s*gpt|chatgpt)", re.I)

# Spoken when a fuzzy hit is too weak or too short to launch. "to TV" is close
# to the two-letter TV app at the loose cutoff, and that used to open it.
UNCLEAR_APP = "I didn't catch which app."
# Fuzzy matches onto "TV" (two letters) are guesses. Exact names still match.
_FUZZY_MIN_LEN = 4


def normalize_app_phrase(spoken):
    """Map ChatGPT spellings to ChatGPT. Every other name is only tidied.

    'chat gpt', 'chat g p t', 'chatgpt', and 'chat GPT' become ChatGPT.
    'ChatGPT Classic' and 'YouTube TV' are unchanged.
    """
    text = _tidy_spoken(spoken)
    if _CHAT_GPT_RE.fullmatch(text):
        return "ChatGPT"
    return text


def _drop_my(spoken):
    """'my phone' stays available for nicknames; callers may also try the shorter form."""
    shorter = re.sub(r"^my\s+", "", (spoken or "").strip(), flags=re.I).strip()
    if shorter and _norm(shorter) != _norm(spoken):
        return shorter
    return None


def _lookup_app(spoken):
    """Display name for a spoken app, or None. Exact nicknames win; fuzzy is strict."""
    if not spoken:
        return None
    aliases = app_alias_map()
    key = _norm(spoken)
    if not key:
        return None
    if key in aliases:
        return aliases[key]
    if len(key) < 4:
        return None
    matches = difflib.get_close_matches(key, list(aliases), n=2, cutoff=APP_FUZZY_CUTOFF)
    if not matches:
        return None
    best = difflib.SequenceMatcher(None, key, matches[0]).ratio()
    if len(matches) > 1:
        second = difflib.SequenceMatcher(None, key, matches[1]).ratio()
        if best - second < 0.05:
            return None
    return aliases[matches[0]]


def _strip_app_words(spoken):
    """'the TV app' becomes 'TV'. A name that does not change is left out."""
    text = re.sub(r"^(?:the|an|a)\s+", "", _tidy_spoken(spoken), flags=re.I).strip()
    text = re.sub(r"\s+(?:app|application)$", "", text, flags=re.I).strip()
    if text and _norm(text) != _norm(spoken):
        return text
    return None


def known_app_name(spoken):
    """Prefer the full phrase, so 'my phone' is iPhone Mirroring and not the Phone app.

    imessage, iMessage, and messages all resolve to Messages. Apple TV, the TV
    app, and TV app resolve to TV. YouTube TV stays YouTube TV. The same map is
    what open, close, quit, hide, and focus consult.
    """
    spoken = normalize_app_phrase(spoken)
    hit = _lookup_app(spoken)
    if hit:
        return hit
    shorter = _drop_my(spoken)
    if shorter:
        hit = _lookup_app(normalize_app_phrase(shorter))
        if hit:
            return hit
    trimmed = _strip_app_words(spoken)
    if not trimmed:
        return None
    trimmed = normalize_app_phrase(trimmed)
    hit = _lookup_app(trimmed)
    if hit:
        return hit
    shorter = _drop_my(trimmed)
    return _lookup_app(shorter) if shorter else None


def resolve_site(spoken):
    """Site config for a spoken name, or None. Exact phrases only, no fuzzy."""
    if not spoken:
        return None
    found = site_index().get(_norm(spoken))
    if found:
        return found
    shorter = _drop_my(spoken)
    return site_index().get(_norm(shorter)) if shorter else None


def resolve_folder(spoken):
    """~/ path for downloads, documents, or desktop, or None."""
    if not spoken:
        return None
    key = re.sub(r"folder$", "", _norm(spoken))
    found = FOLDER_PATHS.get(key)
    if found:
        return found
    shorter = _drop_my(spoken)
    if not shorter:
        return None
    key = re.sub(r"folder$", "", _norm(shorter))
    return FOLDER_PATHS.get(key)


def music_target(text, spotify_installed):
    """'spotify' only when the utterance names it and the app is on disk. Otherwise Music."""
    if re.search(r"\bspotify\b", text or "", re.I):
        return "spotify" if spotify_installed else None
    return "music"


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


def _rate_fuzzy(wanted, keys):
    """('clear', key), ('weak', key), or ('none', None) for a fuzzy installed name.

    A clear hit is a long name, well above the app cutoff, and not a toss-up
    between two apps. Anything else that still beats the loose cutoff is a
    guess: 'to TV' versus 'TV' is one of those.
    """
    keys = list(keys)
    if not wanted or len(wanted) < 3 or not keys:
        return "none", None
    matches = difflib.get_close_matches(wanted, keys, n=2, cutoff=FUZZY_CUTOFF)
    if not matches:
        return "none", None
    best = difflib.SequenceMatcher(None, wanted, matches[0]).ratio()
    second = difflib.SequenceMatcher(None, wanted, matches[1]).ratio() if len(matches) > 1 else 0.0
    unclear = (
        len(matches[0]) < _FUZZY_MIN_LEN
        or best < APP_FUZZY_CUTOFF
        or (len(matches) > 1 and best - second < 0.05)
    )
    return ("weak" if unclear else "clear"), matches[0]


def _installed_fuzzy(spoken, idx):
    """('exact'|'clear'|'weak'|'none', index key or None). Exact wins over fuzzy."""
    wanted = _norm(known_app_name(spoken) or spoken)
    if not wanted:
        return "none", None
    if wanted in idx:
        return "exact", wanted
    return _rate_fuzzy(wanted, idx.keys())


def resolve_app(spoken, idx=None):
    """Return (path, display name) for a spoken app, or None.

    A low-confidence or very short fuzzy match is not a result. Callers that
    open or quit ask unclear_app_guess and say they didn't catch the name.
    """
    if not spoken:
        return None
    idx = app_index() if idx is None else idx
    kind, key = _installed_fuzzy(spoken, idx)
    if kind not in ("exact", "clear") or key not in idx:
        return None
    return idx[key], _display_name(idx[key])


def unclear_app_guess(spoken, idx=None):
    """True when the only installed hit would be a guess, not a clear name.

    An alias such as Apple TV or chat gpt is clear and returns False.
    """
    if not spoken or known_app_name(spoken):
        return False
    idx = app_index() if idx is None else idx
    kind, _key = _installed_fuzzy(spoken, idx)
    return kind == "weak"


def parse_app_name(text, kind=None):
    """Pull the app name out of 'open cap cut' / 'quit the Claude app'.

    kind is 'open' or 'quit', so a two-part sentence ('quit Chrome and open Notes')
    doesn't hand both actions the first name. The name stops at 'and' or 'then'.
    """
    if is_quit_all(text):
        return None
    verbs = {
        "open": _OPEN_VERBS,
        "quit": _QUIT_VERBS,
        "hide": _HIDE_VERBS,
        "focus": _FOCUS_VERBS,
    }.get(kind, "|".join((_OPEN_VERBS, _QUIT_VERBS, _HIDE_VERBS, _FOCUS_VERBS)))
    match = re.search(
        rf"\b(?:{verbs})\s+(?:up\s+)?(?:the\s+)?(.+?)(?=\s+(?:and|then)\b|[,.!?;:]|$)",
        _clean(text).strip(), re.I,
    )
    if not match:
        return None
    name = match.group(1).strip(" .,!?;:")
    name = re.sub(r"^(?:up|the|an|a)\s+", "", name, flags=re.I)
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
    wanted = _norm(known_app_name(spoken) or spoken)
    if not wanted:
        return None
    apps = running_regular_apps()
    exact = [app for app in apps if _norm(str(app.localizedName() or "")) == wanted]
    if exact:
        return exact[0]
    by_key = {}
    for app in apps:
        key = _norm(str(app.localizedName() or ""))
        if key and key not in by_key:
            by_key[key] = app
    kind, key = _rate_fuzzy(wanted, by_key.keys())
    if kind != "clear":
        return None
    return by_key.get(key)


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


def _spoken_target(text, kind, arg, favourites):
    """(spoken, display name) using the open-app nicknames, or (None, None)."""
    spoken = parse_app_name(text, kind)
    if not spoken and arg in favourites:
        spoken = favourites[arg]
    spoken = _tidy_spoken(spoken)
    if not spoken:
        return None, None
    return spoken, (known_app_name(spoken) or spoken)


def open_any_app(arg, text, favourites):
    """Launch a spoken app with `open -a`. favourites is used only when the transcript has no name."""
    spoken = parse_app_name(text, "open")
    from_enum = False
    if not spoken and arg in favourites:
        spoken = favourites[arg]
        from_enum = True
    if not spoken:
        return "Which app should I open?"
    display = known_app_name(spoken)
    if display is None and from_enum:
        display = favourites[arg]
    if display is None:
        found = resolve_app(spoken) or resolve_app(spoken, app_index(force=True))
        if found:
            display = found[1]
        elif unclear_app_guess(spoken):
            return UNCLEAR_APP
    if not display:
        return f"{spoken} isn't installed."
    try:
        _run(("open", "-a", display))
    except Exception:
        return f"{display} isn't installed."
    # {app} in the scripted reply is filled in by the caller. Only APPS names are pre-rendered.
    return {"app": display.replace("{", "").replace("}", "")}


def _one_app_name(name):
    return str(name or "").replace("{", "").replace("}", "")


def quit_any_app(arg, text, favourites):
    """Quit one app with NSRunningApplication.terminate().

    The spoken name uses the same nicknames as open. terminate() lets the app
    ask to save. One app only. Quit-all still asks for a spoken yes.
    """
    if is_quit_all(text):
        return "Say quit all on its own, then yes to confirm."
    spoken, display = _spoken_target(text, "quit", arg, favourites)
    if not spoken:
        return "Which app should I quit?"
    if unclear_app_guess(spoken):
        return UNCLEAR_APP
    try:
        app = _running_match(spoken)
    except Exception:
        return "I couldn't check which apps are running."
    if app is None:
        return f"{display} isn't running."
    name = str(app.localizedName() or display)
    if is_protected(app):
        return f"I won't quit {name}."
    if not app.terminate():
        return f"I couldn't quit {name}."
    return {"app": _one_app_name(name)}


def hide_any_app(arg, text, favourites):
    """Hide one running app. Same nicknames as open. Finder and Hey Jev stay put."""
    spoken, display = _spoken_target(text, "hide", arg, favourites)
    if not spoken:
        return "Which app should I hide?"
    if unclear_app_guess(spoken):
        return UNCLEAR_APP
    try:
        app = _running_match(spoken)
    except Exception:
        return "I couldn't check which apps are running."
    if app is None:
        return f"{display} isn't running."
    name = str(app.localizedName() or display)
    if is_protected(app):
        return f"I won't hide {name}."
    try:
        ok = bool(app.hide())
    except Exception:
        ok = False
    if not ok:
        return f"I couldn't hide {name}."
    return {"app": _one_app_name(name)}


def focus_any_app(arg, text, favourites):
    """Bring one app forward. Same nicknames as open.

    A running app is activated. One that is not running is launched with
    `open -a`, the same call open uses. Nothing is force-quit.
    """
    spoken, display = _spoken_target(text, "focus", arg, favourites)
    if not spoken:
        return "Which app should I switch to?"
    if unclear_app_guess(spoken):
        return UNCLEAR_APP
    app = None
    try:
        app = _running_match(spoken)
    except Exception:
        app = None
    if app is not None:
        name = str(app.localizedName() or display)
        try:
            if app.activateWithOptions_(_ACTIVATE_IGNORING):
                return {"app": _one_app_name(name)}
        except Exception:
            pass
    try:
        _run(("open", "-a", display))
    except Exception:
        return f"I couldn't switch to {display}."
    return {"app": _one_app_name(display)}


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


def app_is_installed(display_name):
    """True when a .app with this name is in the indexed app folders. No fuzzy match."""
    if not display_name:
        return False
    return _norm(display_name) in app_index()
