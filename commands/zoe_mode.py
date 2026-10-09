"""Kid-safe Zoe mode for Fernando's daughter.

Entering is immediate: "Zoe mode", "kid mode on", or the Zoe Mode menu item.
Leaving is a second, deliberate step. A spoken or typed exit phrase only asks
for the words "grown ups only". "Yes" does not leave. The menu item opens a
confirmation dialog whose default button keeps the mode on. The on/off flag
is a plain file, so a relaunch stays in Zoe mode. An unfinished exit prompt
does not survive a relaunch, and the mode stays on.

While the mode is on, only a small allowlist runs. Everything else, including
free-form questions, gets one gentle refusal. Jokes and fun facts are a local
list. There is no web search and no tool use. Replies use the existing Fish
[cheerful] tag and short sentences. There is no second voice id in this app.
The dramatic-voice toggle uses that same voice id, so a child may switch it.

The iPhone bridge cannot enter or leave this mode. Those action keys are not
on BRIDGE_ALLOW. A phone command that is on that list still has to pass this
allowlist before it runs, so the phone cannot bypass the mode either.
"""
import os
import re
import threading
import time

from .config import ZOE_MODE_PATH
from .confirm import clear_confirmation, is_private_message_request, is_quit_all
from .routing import route_before_api
from .textutil import _clean

ZOE_EXIT_SECONDS = 30
# Spoken second step. A casual "yes" must not match.
ZOE_EXIT_PHRASE = "grown ups only"
_EXIT_YES_RE = re.compile(r"^grown[\s-]*ups?\s+only[.!?]*$", re.I)
_EXIT_NO_RE = re.compile(
    r"^(?:no|nope|nah|cancel|stop|never mind|nevermind)(?:\s*,?\s*please)?[.!?]*$",
    re.I,
)
_TAG_RE = re.compile(
    r"\[(?:sighing|chuckling|laughing|clear throat|cheerful)\]\s*",
    re.I,
)

# What a child may do. Mode switches are here so the exit phrase can be heard.
# They are still absent from BRIDGE_ALLOW.
ZOE_ALLOW = frozenset({
    "info_time",
    "info_date",
    "info_weather",
    "zoe_joke",
    "zoe_timer",
    "zoe_academy",
    "media_play",
    "media_pause",
    "info_zoe",
    "zoe_mode_on",
    "zoe_mode_off",
    # Same voice id either way. Still absent from BRIDGE_ALLOW.
    "voice_dramatic",
    "voice_normal",
    "voice_which",
    # The Videos folder on this Mac. Still absent from BRIDGE_ALLOW.
    "videos_open",
})

# Existing action keys Zoe mode refuses, grouped the way the spec lists them.
# shell and llm have no action key. A spoken line in those categories is
# refused because it is not on ZOE_ALLOW.
ZOE_BLOCKED = {
    "quit_close_hide": (
        "app_open",
        "app_quit",
        "app_hide",
        "app_minimise",
        "app_focus",
        "apps_quit_all",
    ),
    "messages": ("info_messages",),
    "money": ("info_rent", "info_bills", "info_payday", "info_payday_check"),
    "email": ("capture_email",),
    "captures": (
        "screenshot",
        "screenshot_area",
        "screenshot_window",
        "record_start",
        "record_stop",
        "capture_note",
        "capture_email",
        "capture_imessage",
        "capture_finder",
        "capture_copy",
        "capture_delete",
        "captures_open",
        "ask_jev",
        "ask_chatgpt",
        "ask_claude",
        "ask_gemini",
        "ask_siri",
        "ask_google",
    ),
    "shortcuts": ("shortcut_run", "focus_on"),
    "reminders": ("remind_add", "ihss_remind"),
    "leave": ("leave_reminders_on", "leave_reminders_off", "info_leave", "info_eta_work"),
    "brief": ("brief_play", "brief_stop", "info_brief"),
    "video": (
        "video_mp4",
        "video_trim",
        "video_compress",
        "video_audio",
        "video_choose",
    ),
    "clipboard": (
        "clipboard_history",
        "clipboard_copy",
        "clipboard_paste",
        "clipboard_clear",
        "clipboard_pause",
        "clipboard_resume",
    ),
    "passwords": ("password_lookup",),
    "dictation": ("dictation_scribe", "dictation_openai"),
    "shell": (),
    "system": (
        "volume_up",
        "volume_down",
        "volume_set",
        "volume_mute",
        "volume_unmute",
        "spotify_volume_up",
        "spotify_volume_down",
        "spotify_volume_set",
        "spotify_volume_mute",
        "spotify_volume_unmute",
        "brightness_up",
        "brightness_down",
        "brightness_set",
        "system_lock",
        "system_sleep",
        "show_desktop",
        "empty_trash",
        "notify_off",
        "notify_on",
        "display_dark_on",
        "display_dark_off",
        "display_toggle",
        "voiceover_on",
        "voiceover_off",
        "zoom_in",
        "zoom_out",
        "zoom_on",
        "zoom_off",
        "screen_speak",
        "screen_stop",
        "selection_read",
        "access_invert",
        "access_contrast",
        "access_transparency",
        "access_motion",
        "access_grayscale",
        "access_filters",
        "access_display_contrast",
        "access_pointer",
        "access_mono",
        "access_hover",
        "access_sticky",
        "access_slow",
        "access_voice_control",
        "access_status",
        "youtube_play",
        "media_next",
        "media_previous",
        "media_now",
    ),
    "llm": (),
}

KID_REFUSAL = (
    "That's a grown-up thing. Let's play, hear a joke, or check the weather."
)
ZOE_ON_LINE = (
    "[cheerful] Zoe mode is on. We can check the time, the weather, a joke, "
    "music, a timer, Princess Academy, and your videos."
)
ZOE_ALREADY_ON = "[cheerful] Zoe mode is already on. I'm right here."
ZOE_ALREADY_OFF = "Zoe mode is already off."
ZOE_EXIT_PROMPT = "[cheerful] To leave Zoe mode, say grown ups only."
ZOE_STAY_LINE = "[cheerful] Zoe mode stays on."
ZOE_OFF_LINE = "[cheerful] Zoe mode is off."
ZOE_FAIL_LINE = "I couldn't save Zoe mode."

JOKES = (
    "[cheerful] Why did the teddy bear say no? Because she was stuffed.",
    "[cheerful] What do you call a dinosaur that is sleeping? A dino-snore.",
    "[cheerful] Fun fact. A group of flamingos is called a flamboyance.",
    "[cheerful] Fun fact. Butterflies taste with their feet.",
    "[cheerful] What do you call a princess who forgets her shoes? Cinder-oops.",
    "[cheerful] Fun fact. Octopuses have three hearts.",
)

_lock = threading.Lock()
_path_override = None
_exit = {"armed": False, "expires": 0.0}
_joke_i = 0


def set_zoe_mode_path(path):
    """Tests point this at a temp file. None uses the real support folder."""
    global _path_override
    with _lock:
        _path_override = path
        _exit["armed"] = False
        _exit["expires"] = 0.0


def clear_zoe_exit():
    with _lock:
        _exit["armed"] = False
        _exit["expires"] = 0.0


def _path():
    return _path_override or ZOE_MODE_PATH


def zoe_mode_active():
    """True only when the flag file says on. A missing file is off."""
    try:
        with open(_path(), encoding="utf-8") as handle:
            return handle.read().strip().lower() == "on"
    except OSError:
        return False


def _write_mode(on):
    path = _path()
    folder = os.path.dirname(path)
    try:
        if folder:
            os.makedirs(folder, exist_ok=True)
        if not on:
            try:
                os.remove(path)
            except OSError:
                pass
            return True
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write("on\n")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def zoe_allows(action):
    return action in ZOE_ALLOW


def zoe_pill_label(active):
    """Short badge for the pill. Empty when the mode is off."""
    return "Zoe" if active else ""


def zoe_plain(line):
    """The words without a Fish emotion tag, for the pill."""
    return _TAG_RE.sub("", line or "").strip()


def zoe_friendly(line, action=""):
    """One cheerful sentence. The [cheerful] tag is the friendly voice this app already uses."""
    text = _TAG_RE.sub("", str(line or "")).strip()
    lower = text.lower()
    failed = "couldn't" in lower or "isn't" in lower or "is not" in lower
    if action == "media_play" and not failed:
        text = "The music is playing."
    elif action == "media_pause" and not failed:
        text = "The music is paused."
    if not text:
        text = "Okay."
    return "[cheerful] " + text


def tell_zoe_joke():
    """The next local joke or fun fact. No network."""
    global _joke_i
    with _lock:
        line = JOKES[_joke_i % len(JOKES)]
        _joke_i += 1
        return line


def enter_zoe_mode():
    """Turn the mode on and remember it. Clears any adult yes/no that was waiting."""
    clear_confirmation()
    clear_zoe_exit()
    if zoe_mode_active():
        return ZOE_ALREADY_ON
    if not _write_mode(True):
        return ZOE_FAIL_LINE
    return ZOE_ON_LINE


def leave_zoe_mode():
    """Turn the mode off. Call this only after the dialog or the spoken phrase."""
    clear_zoe_exit()
    if not _write_mode(False):
        return ZOE_FAIL_LINE
    return ZOE_OFF_LINE


def ask_leave_zoe_mode():
    """First exit step. Does not turn the mode off."""
    if not zoe_mode_active():
        return ZOE_ALREADY_OFF
    with _lock:
        _exit["armed"] = True
        _exit["expires"] = time.time() + ZOE_EXIT_SECONDS
    return ZOE_EXIT_PROMPT


def _exit_status(text):
    """'yes', 'no', 'expired', 'other', or None when no exit is waiting.

    'yes' here means the adult phrase, not the word yes.
    """
    with _lock:
        if not _exit["armed"]:
            return None
        if time.time() >= _exit["expires"]:
            _exit["armed"] = False
            return "expired"
        stripped = _clean(text).strip()
        if _EXIT_YES_RE.match(stripped):
            _exit["armed"] = False
            return "yes"
        if _EXIT_NO_RE.match(stripped):
            _exit["armed"] = False
            return "no"
        _exit["armed"] = False
        return "other"


def zoe_exit_pending():
    with _lock:
        if not _exit["armed"]:
            return False
        if time.time() >= _exit["expires"]:
            _exit["armed"] = False
            return False
        return True


def menu_toggle_plan(active=None):
    """What the menu item should do. Off enters. On asks before it leaves.

    The cancel button is the default so pressing Return keeps Zoe mode on.
    """
    on = zoe_mode_active() if active is None else bool(active)
    if not on:
        return {
            "action": "enter",
            "title": "Zoe Mode",
            "checked": False,
        }
    return {
        "action": "confirm_exit",
        "title": "Turn Off Zoe Mode",
        "message": (
            "Turn off Zoe mode? The assistant can do grown-up things again after this."
        ),
        "confirm": "Turn Off Zoe Mode",
        "cancel": "Keep Zoe Mode",
        "checked": True,
    }


def _refusal():
    return {"kind": "speak", "line": "[cheerful] " + KID_REFUSAL}


def zoe_claims(text):
    """True when this turn must not take the adult path."""
    if zoe_exit_pending() or zoe_mode_active():
        return True
    action = route_before_api(text)
    return action in ("zoe_mode_on", "zoe_mode_off")


def zoe_guard(text):
    """None means the adult path. Otherwise the caller speaks or runs one allowlisted action.

    kind speak: say line and do nothing else.
    kind run: run that action key, then speak zoe_friendly of the result.
    Free-form questions are refused. They are not sent to an LLM.
    """
    pending = _exit_status(text)
    if pending == "yes":
        return {"kind": "speak", "line": leave_zoe_mode()}
    if pending == "no":
        return {"kind": "speak", "line": ZOE_STAY_LINE}
    if not zoe_mode_active():
        action = route_before_api(text)
        if action == "zoe_mode_on":
            return {"kind": "speak", "line": enter_zoe_mode()}
        if action == "zoe_mode_off":
            return {"kind": "speak", "line": ZOE_ALREADY_OFF}
        return None
    if is_quit_all(text) or is_private_message_request(text):
        return _refusal()
    action = route_before_api(text)
    if action == "zoe_mode_off":
        return {"kind": "speak", "line": ask_leave_zoe_mode()}
    if action == "zoe_mode_on":
        return {"kind": "speak", "line": ZOE_ALREADY_ON}
    if action == "zoe_joke":
        return {"kind": "speak", "line": tell_zoe_joke()}
    if action in ZOE_ALLOW:
        return {"kind": "run", "action": action}
    return _refusal()
