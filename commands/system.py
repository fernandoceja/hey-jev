"""Chrome sites, folders, Mac controls, screenshots, and battery."""
import ctypes
import os
import re
import shutil
from . import config
from .config import BRIGHTNESS_DOWN_CODE, BRIGHTNESS_UP_CODE, HELP_TEXT, SHOPIFY_ORDERS_URL, SHOW_DESKTOP_CODE
from .textutil import _clean, parse_level_change
from .shell import _run
from .apps import parse_app_name, resolve_folder, resolve_site

OPENING_VIDEOS = "Opening your Videos folder."
MISSING_VIDEOS = "Your Videos folder isn't there."

# Private DisplayServices SPI. CoreDisplay_Display_SetUserBrightness does not
# work on Apple silicon; this is the call the Homebrew brightness tool uses
# there. A return of 0 means the get or set worked.
_DISPLAY_SERVICES = "/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices"
_CORE_GRAPHICS = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
_BRIGHTNESS_CLI = ("/opt/homebrew/bin/brightness", "/usr/local/bin/brightness")

def speak_help():
    return HELP_TEXT


def _https_url(url):
    return isinstance(url, str) and url.startswith("https://") and " " not in url and '"' not in url


def _open_in_chrome(url, spoken):
    """Hand one https URL to Chrome. This does not fetch the page."""
    if not _https_url(url):
        return "That site isn't set up yet. The URL in commands.py needs to be https."
    try:
        _run(("open", "-a", "Google Chrome", url))
    except Exception:
        return "Google Chrome isn't installed, so I couldn't open that."
    return spoken


def open_site_from_text(text):
    """Open a configured site, or the Shopify orders page for an orders phrase."""
    raw = _clean(text)
    if re.search(r"\borders\b", raw, re.I) and not parse_app_name(raw, "open"):
        return _open_in_chrome(SHOPIFY_ORDERS_URL, "Opening Shopify orders.")
    spoken = parse_app_name(raw, "open") or ""
    if re.search(r"\borders\b", spoken, re.I):
        entry = resolve_site("shopify orders")
    else:
        entry = resolve_site(spoken)
    if not entry:
        return "Which site should I open?"
    return _open_in_chrome(entry["url"], f"Opening {entry['label']}.")


def open_folder_from_text(text):
    spoken = parse_app_name(_clean(text), "open") or ""
    path = resolve_folder(spoken)
    if not path:
        return "Which folder should I open?"
    target = os.path.expanduser(path)
    label = os.path.basename(target)
    try:
        _run(("open", target))
    except Exception:
        return f"I couldn't open {label}."
    return f"Opening your {label} folder."


def videos_folder_path(path=None):
    """Absolute Videos path. expanduser does not invoke a shell.

    A leading ~ becomes the home directory. A path that is still a tilde, or
    that is not absolute, is refused so `open` never sees a shell fragment.
    """
    raw = config.VIDEOS_FOLDER if path is None else path
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    if not text or "\x00" in text or "\n" in text or "\r" in text:
        return ""
    expanded = os.path.expanduser(text)
    if not expanded or expanded.startswith("~"):
        return ""
    target = os.path.abspath(expanded)
    if not target.startswith("/"):
        return ""
    return target


def _finder_open_args(target):
    """["open", path]. A single string would be a shell command, so it is refused."""
    if not isinstance(target, str) or not target.startswith("/"):
        raise TypeError("open takes an argument list")
    return ["open", target]


def open_videos_folder(path=None):
    """Reveal the Videos folder in Finder. Does not create it.

    The command is an argument list: ["open", path]. Spaces in the path stay
    inside that one argument. A shell string is never built.
    """
    target = videos_folder_path(path)
    try:
        found = bool(target) and os.path.isdir(target)
    except OSError:
        found = False
    if not found:
        return MISSING_VIDEOS
    try:
        _run(_finder_open_args(target))
    except Exception:
        return "I couldn't open your Videos folder."
    return OPENING_VIDEOS


def _load_display_service():
    """(get, set) for the main display, or None when DisplayServices is absent.

    get() returns a float from 0 to 1. set(level) raises unless the SPI
    returns 0. This is skipped on machines that do not have the framework.
    """
    try:
        lib = ctypes.CDLL(_DISPLAY_SERVICES)
        cg = ctypes.CDLL(_CORE_GRAPHICS)
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        lib.DisplayServicesGetBrightness.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_float)]
        lib.DisplayServicesGetBrightness.restype = ctypes.c_int
        lib.DisplayServicesSetBrightness.argtypes = [ctypes.c_uint32, ctypes.c_float]
        lib.DisplayServicesSetBrightness.restype = ctypes.c_int
        display_id = int(cg.CGMainDisplayID())
    except (OSError, AttributeError):
        return None

    def get():
        value = ctypes.c_float(0.0)
        if lib.DisplayServicesGetBrightness(display_id, ctypes.byref(value)) != 0:
            raise RuntimeError("brightness get failed")
        return float(value.value)

    def set_level(level):
        if lib.DisplayServicesSetBrightness(display_id, ctypes.c_float(float(level))) != 0:
            raise RuntimeError("brightness set failed")
        return 0

    return (get, set_level)


def _brightness_cli(which, cli):
    if cli is False:
        return None
    if isinstance(cli, str) and cli:
        return cli
    probe = shutil.which if which is None else which
    found = None
    if probe is not None:
        try:
            found = probe("brightness")
        except Exception:
            found = None
    for path in (found,) + _BRIGHTNESS_CLI:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _cli_brightness(text):
    match = re.search(r"brightness\s+(\d+(?:\.\d+)?)", str(text or ""), re.I)
    if not match:
        return None
    return max(0.0, min(1.0, float(match.group(1))))


def _percent(level):
    return int(round(max(0.0, min(1.0, float(level))) * 100))


def _brightness_service(service, direction, kind, amount):
    get_fn, set_fn = service
    if kind == "absolute":
        target = amount / 100.0
    else:
        step = 10 if amount is None else amount
        current = float(get_fn())
        delta = step / 100.0
        target = current + delta if direction == "up" else current - delta
    target = max(0.0, min(1.0, target))
    status = set_fn(target)
    if status not in (None, 0):
        raise RuntimeError("brightness set failed")
    return f"Brightness is at {_percent(target)} percent."


def _brightness_with_cli(tool, run, direction, kind, amount):
    if kind == "absolute":
        target = amount / 100.0
    else:
        current = _cli_brightness(run((tool, "-l")))
        if current is None:
            raise RuntimeError("brightness list failed")
        step = 10 if amount is None else amount
        delta = step / 100.0
        target = current + delta if direction == "up" else current - delta
    target = max(0.0, min(1.0, target))
    run((tool, f"{target:.2f}"))
    return f"Brightness is at {_percent(target)} percent."


def _key_steps(percent):
    return max(1, min(16, int(round(percent / 100.0 * 16))))


def _brightness_keys(direction, steps, plain, run):
    code = BRIGHTNESS_UP_CODE if direction == "up" else BRIGHTNESS_DOWN_CODE
    code = int(code)
    if plain:
        script = f'tell application "System Events" to key code {code}'
    else:
        script = (
            'tell application "System Events"\n'
            f"  repeat {int(steps)} times\n"
            f"    key code {code}\n"
            "    delay 0.05\n"
            "  end repeat\n"
            "end tell"
        )
    try:
        run(("osascript", "-e", script))
    except Exception:
        return "I couldn't change the brightness. Allow Automation for System Events."
    if plain:
        return "Brighter." if direction == "up" else "Dimmer."
    way = "up" if direction == "up" else "down"
    return f"I moved the brightness {way} by {int(steps)} key steps. I couldn't set an exact percent."


def change_brightness(direction, text="", display=None, runner=None, which=None, cli=None):
    """Change the screen brightness. Percentages prefer DisplayServices.

    On Apple silicon the reliable call is DisplayServicesGetBrightness /
    DisplayServicesSetBrightness. If that framework is missing, the Homebrew
    `brightness` CLI is used when it is installed (`brightness -l`, then
    `brightness 0.50`). Up and down with no exact level can still tap the
    brightness keys (144 and 145). Setting an exact percent does not.
    """
    run = runner or _run
    kind, amount = parse_level_change(text, default=None)
    if direction == "set":
        if kind != "absolute":
            return "What level should I set the brightness to?"
    elif kind == "bad_step":
        return "I can change the brightness by 10, 20, 30, or 50 percent."
    elif kind == "missing":
        kind, amount = "relative", None
    elif kind == "absolute" and direction in {"up", "down"}:
        direction = "set"
    service = None
    if display is False:
        service = None
    elif display is not None:
        service = display
    else:
        service = _load_display_service()
    if service is not None:
        try:
            return _brightness_service(service, direction, kind, amount)
        except Exception:
            pass
    tool = _brightness_cli(which, cli)
    if tool:
        try:
            return _brightness_with_cli(tool, run, direction, kind, amount)
        except Exception:
            pass
    if kind == "absolute" or direction == "set":
        return "I couldn't set the brightness to an exact percent. The brightness keys only move it up or down."
    if direction not in {"up", "down"}:
        return "I couldn't change the brightness."
    steps = 1 if amount is None else _key_steps(amount)
    return _brightness_keys(direction, steps, amount is None, run)


def show_desktop():
    script = f'tell application "System Events" to key code {int(SHOW_DESKTOP_CODE)}'
    try:
        _run(("osascript", "-e", script))
    except Exception:
        return "I couldn't show the desktop. That uses the F11 shortcut."
    return "Showing the desktop."


def speak_battery():
    try:
        out = _run(("pmset", "-g", "batt"))
    except Exception:
        return "I couldn't read the battery."
    match = re.search(r"(\d+)%", out or "")
    if not match:
        return "I couldn't read the battery."
    pct = int(match.group(1))
    lower = out.lower()
    if "ac power" in lower or "charging" in lower and "discharging" not in lower:
        source = "and it's charging" if "charging" in lower and "charged" not in lower else "and it's on power"
    else:
        source = "on battery"
    return f"Battery is at {pct} percent, {source}."


def take_screenshot(mode="full", folder=None, **kwargs):
    """Full screen, an area, or a window. Files go to the Jev Captures folder."""
    from .captures import take_screenshot as shoot
    return shoot(mode, folder=folder, **kwargs)


def empty_trash():
    """Only call this after a spoken yes."""
    try:
        _run(("osascript", "-e", 'tell application "Finder" to empty the trash'))
    except Exception:
        return "I couldn't empty the trash. Allow Automation for Finder."
    return "Trash is empty."


def continue_chatgpt():
    """Activate ChatGPT and type the fixed word continue. Nothing else is typed."""
    script = (
        'tell application "ChatGPT" to activate\n'
        "delay 0.5\n"
        'tell application "System Events"\n'
        'tell process "ChatGPT" to set frontmost to true\n'
        'keystroke "continue"\n'
        "key code 36\n"
        "end tell"
    )
    try:
        _run(("osascript", "-e", script))
    except Exception:
        return "I couldn't continue ChatGPT. Allow Automation for ChatGPT and System Events."
    return "I told ChatGPT to continue."


def open_case_status():
    """Open the USCIS case-status site in Chrome. The receipt number is never stored."""
    entry = resolve_site("case status")
    if not entry:
        return "I couldn't open the case status site."
    return _open_in_chrome(entry["url"], "Opening the case status site.")
