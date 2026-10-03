"""YouTube search and the Mac output volume."""
from urllib.parse import quote_plus
import re
from .config import VOLUME_WORDS
from .textutil import _clean
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


def set_mac_volume(level_name, text):
    """Set the Mac output volume. The number is chosen here, never typed into a shell."""
    level = parse_volume_level(text)
    if level is None and level_name:
        level = VOLUME_WORDS.get(str(level_name).lower())
    if level is None:
        return "What level should I set the volume to?"
    level = max(0, min(100, int(level)))
    try:
        _run(("osascript", "-e", f"set volume output volume {level}"))
    except Exception:
        return "I couldn't change the volume."
    return f"Volume's set to {level}."
