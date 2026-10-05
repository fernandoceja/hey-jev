"""Focus, Speak Screen, VoiceOver, and Accessibility toggles. Mac only.

Nothing here is on the iPhone bridge. Nothing reads the Keychain, opens a
socket, or types a password. A setting macOS 27 will not apply from a
preference write is said out loud, and System Settings is opened instead of
pretending the screen changed.

Speak Screen has no fixed shortcut. Option-Command-Escape is Force Quit, so
that chord is never sent. VoiceOver uses Command-F5. Speak Selection uses
Option-Escape only when that shortcut is enabled.
"""
import re

from .config import FOCUS_OFF_NAME, FOCUS_ON_NAME
from .shell import _run
from .shortcuts import run_jev_folder_shortcut
from .textutil import parse_level_change

_ACC = "x-apple.systempreferences:com.apple.Accessibility-Settings.extension"
PANES = {
    "display": (_ACC + "?Display", "Display"),
    "zoom": (_ACC + "?Zoom", "Zoom"),
    "spoken": (_ACC + "?SpokenContent", "Spoken Content"),
    "audio": (_ACC + "?Audio", "Audio"),
    "keyboard": (_ACC + "?Keyboard", "Keyboard"),
    "pointer": (_ACC + "?PointerControl", "Pointer Control"),
    "voiceover": (_ACC + "?VoiceOver", "VoiceOver"),
    "voice_control": (_ACC + "?VoiceControl", "Voice Control"),
}
FOCUS_PANE = "x-apple.systempreferences:com.apple.Focus-Settings.extension"
_DOMAIN = "com.apple.universalaccess"

# Preference writes. universalaccessd on recent macOS often ignores them
# until the switch is toggled, so each one also opens its pane.
BOOL_FEATURES = {
    "invert": ("Invert Colors", "invertColors", "display"),
    "increase_contrast": ("Increase Contrast", "increaseContrast", "display"),
    "reduce_transparency": ("Reduce Transparency", "reduceTransparency", "display"),
    "reduce_motion": ("Reduce Motion", "reduceMotion", "display"),
    "grayscale": ("Grayscale", "grayscale", "display"),
    "mono": ("Mono Audio", "playStereoAudioAsMono", "audio"),
    "hover": ("Hover Text", "hoverTextEnabled", "zoom"),
    "sticky": ("Sticky Keys", "stickyKey", "keyboard"),
    "slow": ("Slow Keys", "slowKey", "keyboard"),
}
# No preference write. These need a click in System Settings.
PANE_ONLY = {
    "filters": (
        "Color Filters",
        "display",
        "I can't switch color filters from here.",
    ),
    "voice_control": (
        "Voice Control",
        "voice_control",
        "I can't turn Voice Control on or off from here.",
    ),
}
POINTER_STEPS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
_SPEAK_SELECTION = ("com.apple.speech.synthesis.general.prefs", "SpokenUIUseSpeakingHotKeyFlag")
_SPEAK_SCREEN_FLAGS = (
    ("com.apple.Accessibility", "SpeakScreenEnabled"),
    (_DOMAIN, "speakScreenEnabled"),
)

ZOOM_SCRIPTS = {
    "on": 'tell application "System Events" to keystroke "8" using {option down, command down}',
    "off": 'tell application "System Events" to keystroke "8" using {option down, command down}',
    "in": 'tell application "System Events" to keystroke "=" using {option down, command down}',
    "out": 'tell application "System Events" to keystroke "-" using {option down, command down}',
}
VOICEOVER_SCRIPT = 'tell application "System Events" to key code 96 using {command down}'
SPEAK_SELECTION_SCRIPT = 'tell application "System Events" to key code 53 using {option down}'

# Best-effort. The Focus checkbox in Control Center is not a stable API.
FOCUS_UI_SCRIPT = '''tell application "System Events"
  tell process "ControlCenter"
    set frontmost to true
    click menu bar item "Control Center" of menu bar 1
    delay 0.4
    click checkbox "Focus" of window "Control Center"
  end tell
end tell
'''


def _bool_value(text):
    raw = str(text or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return None


def _float_value(text):
    match = re.search(r"-?\d+(?:\.\d+)?", str(text or ""))
    if not match:
        return None
    return float(match.group(0))


def _feature_on(text, default=True):
    raw = text or ""
    if re.search(r"\b(?:off|disable|disabled)\b", raw, re.I):
        return False
    if re.search(r"\b(?:on|enable|enabled)\b", raw, re.I):
        return True
    return default


def _open_url(url, run):
    try:
        run(("open", url))
    except Exception:
        return False
    return True


def _pane_sentence(opened, label):
    if opened:
        return f"I opened {label} in Accessibility."
    return f"I couldn't open {label} in Accessibility."


def _open_pane(pane_id, run):
    url, label = PANES[pane_id]
    return _open_url(url, run), label


def _read_default(domain, key, run):
    try:
        return run(("defaults", "read", domain, key))
    except Exception:
        return None


def silence_notifications(on=True, run_shortcut=None, runner=None):
    """Silence notifications, or turn them back on.

    Jev Focus On / Jev Focus Off run only through the Jev-folder check.
    If that shortcut is missing, or the folder cannot be verified, nothing
    from Shortcuts is launched. Control Center is the fallback, and Focus
    settings open when that click fails.
    """
    shortcut = run_shortcut or run_jev_folder_shortcut
    run = runner or _run
    name = FOCUS_ON_NAME if on else FOCUS_OFF_NAME
    if shortcut(name) is None:
        return "Notifications are silenced." if on else "Notifications are back."
    try:
        run(("osascript", "-e", FOCUS_UI_SCRIPT))
    except Exception:
        opened = _open_url(FOCUS_PANE, run)
        if opened:
            return "I couldn't change Focus from here. I opened Focus settings."
        return "I couldn't change Focus, and I couldn't open Focus settings."
    if on:
        return "I asked Control Center to turn Focus on. Check the Focus menu if notifications are still coming through."
    return "I asked Control Center to turn Focus off. Check the Focus menu if it looks wrong."


def _voiceover_running(run):
    try:
        out = run(("pgrep", "-x", "VoiceOver"))
    except Exception:
        return False
    return bool(str(out or "").strip())


def set_voiceover(on=True, runner=None):
    """Toggle VoiceOver with Command-F5 only when it is not already in that state."""
    run = runner or _run
    running = _voiceover_running(run)
    if on and running:
        return "VoiceOver is already on."
    if not on and not running:
        return "VoiceOver is already off."
    try:
        run(("osascript", "-e", VOICEOVER_SCRIPT))
    except Exception:
        opened, label = _open_pane("voiceover", run)
        return "I couldn't toggle VoiceOver. " + _pane_sentence(opened, label)
    return "VoiceOver is on." if on else "VoiceOver is off."


def _flag_enabled(pairs, run):
    for domain, key in pairs:
        if _bool_value(_read_default(domain, key, run)) is True:
            return True
    return False


def speak_screen(runner=None):
    """Start Speak Screen only when a preference says the feature is on.

    There is no fixed Speak Screen shortcut to press. Option-Command-Escape
    is Force Quit, so it is not used. When the feature is off, Spoken Content
    is opened and VoiceOver is left alone.
    """
    run = runner or _run
    if not _flag_enabled(_SPEAK_SCREEN_FLAGS, run):
        opened, label = _open_pane("spoken", run)
        return (
            "Speak Screen isn't enabled, and it has no fixed shortcut I can press. "
            + _pane_sentence(opened, label)
            + " Say voiceover on if you want VoiceOver."
        )
    opened, label = _open_pane("spoken", run)
    return (
        "Speak Screen is enabled, but macOS doesn't give it a shortcut I can press safely. "
        + _pane_sentence(opened, label)
    )


def read_selection(runner=None):
    """Press Option-Escape only when Speak Selection's own shortcut is enabled."""
    run = runner or _run
    domain, key = _SPEAK_SELECTION
    enabled = _bool_value(_read_default(domain, key, run)) is True
    if not enabled:
        opened, label = _open_pane("spoken", run)
        return "Speak Selection isn't enabled. " + _pane_sentence(opened, label)
    try:
        run(("osascript", "-e", SPEAK_SELECTION_SCRIPT))
    except Exception:
        opened, label = _open_pane("spoken", run)
        return "I couldn't read the selection. " + _pane_sentence(opened, label)
    return "Reading the selection."


def stop_reading(runner=None):
    """Turn VoiceOver off when it is running. Speak Screen has nothing safe to press."""
    run = runner or _run
    if _voiceover_running(run):
        return set_voiceover(False, runner=run)
    return "VoiceOver isn't running, and Speak Screen has no shortcut I can press to stop it."


def press_zoom(direction, runner=None):
    """Zoom on, off, in, or out with the standard Option-Command shortcuts.

    On and off are the same toggle, so the reply says that instead of claiming
    a direction the shortcut cannot report.
    """
    run = runner or _run
    script = ZOOM_SCRIPTS.get(direction)
    if not script:
        return "I didn't catch whether you wanted to zoom in or out."
    try:
        run(("osascript", "-e", script))
    except Exception:
        opened, label = _open_pane("zoom", run)
        return "I couldn't control Zoom. " + _pane_sentence(opened, label)
    if direction in {"on", "off"}:
        return "I pressed Option-Command-8, which toggles Zoom. Say it again if that went the wrong way."
    if direction == "in":
        return "Zooming in."
    return "Zooming out."


def _set_bool_feature(feature, on, run):
    label, key, pane_id = BOOL_FEATURES[feature]
    state = "on" if on else "off"
    flag = "true" if on else "false"
    try:
        run(("defaults", "write", _DOMAIN, key, "-bool", flag))
    except Exception:
        opened, pane = _open_pane(pane_id, run)
        return f"I couldn't turn {label} {state}. " + _pane_sentence(opened, pane)
    read_back = _bool_value(_read_default(_DOMAIN, key, run))
    opened, pane = _open_pane(pane_id, run)
    where = _pane_sentence(opened, pane)
    if read_back is on:
        return (
            f"{label} is {state} in preferences. "
            f"macOS 27 may not apply that until you toggle it. {where}"
        )
    return f"I couldn't confirm {label} is {state}. {where}"


def _set_pane_only(feature, run):
    label, pane_id, lead = PANE_ONLY[feature]
    opened, pane = _open_pane(pane_id, run)
    return f"{lead} { _pane_sentence(opened, pane) }"


def _nearest_step(value):
    return min(POINTER_STEPS, key=lambda step: abs(step - value))


def set_pointer_size(text, runner=None):
    """Move the pointer one stored step larger or smaller."""
    run = runner or _run
    bigger = not re.search(r"\b(?:smaller|smaller pointer|down)\b", text or "", re.I)
    if re.search(r"\b(?:bigger|larger)\b", text or "", re.I):
        bigger = True
    if re.search(r"\bsmaller\b", text or "", re.I):
        bigger = False
    raw = _read_default(_DOMAIN, "mouseDriverCursorSize", run)
    current = _float_value(raw)
    assumed = current is None
    if assumed:
        current = 1.0
    current = _nearest_step(current)
    index = POINTER_STEPS.index(current)
    if bigger:
        if index >= len(POINTER_STEPS) - 1:
            return "The pointer is already as large as I can set it."
        target = POINTER_STEPS[index + 1]
    else:
        if index <= 0:
            return "The pointer is already as small as I can set it."
        target = POINTER_STEPS[index - 1]
    try:
        run(("defaults", "write", _DOMAIN, "mouseDriverCursorSize", "-float", f"{target:.1f}"))
    except Exception:
        opened, pane = _open_pane("pointer", run)
        return "I couldn't change the pointer size. " + _pane_sentence(opened, pane)
    opened, pane = _open_pane("pointer", run)
    lead = "I couldn't read the current size, so I started from normal. " if assumed else ""
    return (
        f"{lead}Pointer size is {target:g} in preferences. "
        f"macOS 27 may not apply that until you move the slider. {_pane_sentence(opened, pane)}"
    )


def set_display_contrast(text, runner=None):
    """Move the display-contrast slider. The stored value is 0 to 1, spoken as a percent."""
    run = runner or _run
    kind, amount = parse_level_change(text, default=10)
    if kind == "bad_step":
        return "I can change display contrast by 10, 20, 30, or 50 percent."
    if kind == "missing":
        return "What contrast level should I set?"
    raw = _read_default(_DOMAIN, "contrast", run)
    current = _float_value(raw)
    assumed = current is None
    if assumed:
        current = 0.0
    current = max(0.0, min(1.0, current))
    if kind == "absolute":
        target = amount / 100.0
    else:
        delta = amount / 100.0
        if re.search(r"\bdown\b", text or "", re.I):
            target = current - delta
        else:
            target = current + delta
    target = max(0.0, min(1.0, target))
    try:
        run(("defaults", "write", _DOMAIN, "contrast", "-float", f"{target:.2f}"))
    except Exception:
        opened, pane = _open_pane("display", run)
        return "I couldn't change display contrast. " + _pane_sentence(opened, pane)
    opened, pane = _open_pane("display", run)
    percent = int(round(target * 100))
    lead = "I couldn't read the current contrast, so I started from zero. " if assumed and kind != "absolute" else ""
    return (
        f"{lead}Display contrast is {percent} percent in preferences. "
        f"macOS 27 may not apply that until you move the slider. {_pane_sentence(opened, pane)}"
    )


def set_access_feature(feature, text="", runner=None):
    """Apply one accessibility request. Unknown features are not written."""
    run = runner or _run
    if feature == "pointer":
        return set_pointer_size(text, runner=run)
    if feature == "display_contrast":
        return set_display_contrast(text, runner=run)
    if feature in PANE_ONLY:
        return _set_pane_only(feature, run)
    if feature not in BOOL_FEATURES:
        return "I didn't catch which accessibility setting you meant."
    return _set_bool_feature(feature, _feature_on(text, default=True), run)


def _status_bool(label, domain, key, run, on, off, unknown):
    value = _bool_value(_read_default(domain, key, run))
    if value is True:
        on.append(label)
    elif value is False:
        off.append(label)
    else:
        unknown.append(label)


def accessibility_status(runner=None):
    """Read the accessibility preferences and whether VoiceOver is running.

    Zoom has no stored on/off bit that matches the Option-Command-8 toggle,
    so it is reported as unknown. Voice Control is unknown when its key is
    missing. Nothing is changed.
    """
    run = runner or _run
    on, off, unknown = [], [], []
    for feature, (label, key, _pane) in BOOL_FEATURES.items():
        _status_bool(label, _DOMAIN, key, run, on, off, unknown)
    if _voiceover_running(run):
        on.append("VoiceOver")
    else:
        off.append("VoiceOver")
    _status_bool("Voice Control", "com.apple.Accessibility", "VoiceControlEnabled", run, on, off, unknown)
    unknown.append("Zoom")
    contrast = _float_value(_read_default(_DOMAIN, "contrast", run))
    pointer = _float_value(_read_default(_DOMAIN, "mouseDriverCursorSize", run))
    parts = []
    if on:
        parts.append("On: " + ", ".join(on) + ".")
    if off:
        parts.append("Off: " + ", ".join(off) + ".")
    if unknown:
        parts.append("I can't tell: " + ", ".join(unknown) + ".")
    if contrast is not None:
        parts.append(f"Display contrast is {int(round(max(0.0, min(1.0, contrast)) * 100))} percent.")
    else:
        parts.append("I can't tell the display contrast.")
    if pointer is not None:
        parts.append(f"Pointer size is {pointer:g}.")
    else:
        parts.append("I can't tell the pointer size.")
    return " ".join(parts)
