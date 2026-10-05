"""YouTube search and the Mac output volume."""
from urllib.parse import quote_plus
import re
from .config import VOLUME_WORDS
from .textutil import _clean, parse_level_change
from .shell import _run
from .system import _open_in_chrome

def play_on_youtube(text):
    match = re.search(r"\bplay\s+(.+?)\s+on\s+youtube\b", _clean(text), re.I)
    query = match.group(1).strip(" .,!?") if match else ""
    query = re.sub(r"^(?:the|some|a|an)\s+", "", query, flags=re.I).strip()
    if not query:
        return "What should I play on YouTube?"
    url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
    return _open_in_chrome(url, f"Opening {query} on YouTube.")


def parse_volume_level(text):
    """0-100 from 'set volume to 40' or 'half', or None."""
    raw = _clean(text or "")
    match = re.search(r"\b(\d{1,3})\b", raw)
    if match:
        return max(0, min(100, int(match.group(1))))
    for word, level in VOLUME_WORDS.items():
        if re.search(rf"\b{word}\b", raw, re.I):
            return level
    return None


def set_mac_volume(level_name, text, runner=None):
    """Set the Mac output volume. The number is chosen here, never typed into a shell."""
    level = parse_volume_level(text)
    if level is None and level_name:
        level = VOLUME_WORDS.get(str(level_name).lower())
    if level is None:
        return "What level should I set the volume to?"
    return _write_output_volume(level, runner, "Volume's set to {level}.")


def _read_output_volume(run):
    out = run(("osascript", "-e", "output volume of (get volume settings)"))
    return max(0, min(100, int(str(out).strip())))


def _write_output_volume(level, runner, spoken):
    level = max(0, min(100, int(level)))
    run = runner or _run
    try:
        run(("osascript", "-e", f"set volume output volume {level}"))
    except Exception:
        return "I couldn't change the volume."
    return spoken.format(level=level)


def change_mac_volume(direction, text="", runner=None):
    """Raise or lower the Mac output volume by 10, 20, 30, or 50, default 20.

    The current level is read with AppleScript, the result is clamped to
    0–100, and only that integer is placed in `set volume output volume`.
    """
    kind, amount = parse_level_change(text, default=20)
    if kind == "bad_step":
        return "I can change the volume by 10, 20, 30, or 50 percent."
    if kind == "absolute":
        return _write_output_volume(amount, runner, "Volume's set to {level}.")
    if direction not in {"up", "down"}:
        return "I couldn't change the volume."
    run = runner or _run
    try:
        current = _read_output_volume(run)
    except Exception:
        return "I couldn't change the volume."
    target = current + amount if direction == "up" else current - amount
    return _write_output_volume(target, run, "Volume's at {level}.")


def mute_mac_volume(muted=True, runner=None):
    """Mute or unmute the Mac output. The flag is true or false, never spoken text."""
    run = runner or _run
    flag = "true" if muted else "false"
    try:
        run(("osascript", "-e", f"set volume output muted {flag}"))
    except Exception:
        return "I couldn't change the volume."
    return "Muted." if muted else "Unmuted."
