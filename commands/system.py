"""Chrome sites, folders, Mac controls, screenshots, and battery."""
from datetime import datetime
import os
import re
from .config import BRIGHTNESS_DOWN_CODE, BRIGHTNESS_UP_CODE, HELP_TEXT, SHOPIFY_ORDERS_URL, SHOW_DESKTOP_CODE
from .textutil import _clean
from .shell import _run
from .apps import parse_app_name, resolve_folder, resolve_site

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


def change_brightness(direction):
    code = BRIGHTNESS_UP_CODE if direction == "up" else BRIGHTNESS_DOWN_CODE
    script = f'tell application "System Events" to key code {int(code)}'
    try:
        _run(("osascript", "-e", script))
    except Exception:
        return "I couldn't change the brightness. Allow Automation for System Events."
    return "Brighter." if direction == "up" else "Dimmer."


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


def take_screenshot():
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H-%M-%S")
    path = os.path.expanduser(f"~/Desktop/Jev {stamp}.png")
    try:
        _run(("screencapture", "-x", path))
    except Exception:
        return "I couldn't take a screenshot. Allow Screen Recording for Hey Jev."
    return "Saved a screenshot to your Desktop."


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
