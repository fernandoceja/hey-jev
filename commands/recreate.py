"""'Jev, recreate this': Mac-only job cards in a local handoff folder.

Same file pattern as the iPhone bridge (write a .tmp, then os.replace), but in
its own folder and with no bridge code involved. Nothing listens on a port and
no key is read. The Chief of Staff picks up cards from ``inbox/`` and writes a
status file to ``outbox/status.json``; Jev reads that status aloud.

These actions are not in BRIDGE_ALLOW, so the iPhone cannot trigger them.
"""
import json
import os
import re
import shutil
import sys
import time
import uuid

from .textutil import _clean

RECREATE_DIR_ENV = "JEV_RECREATE_DIR"
DEFAULT_RECREATE_DIR = os.path.expanduser("~/Documents/AI-Projects/Jarvis/handoff/recreate")
MAX_REQUEST_CHARS = 500
MAX_STATUS_CHARS = 300

_VERB = r"(?:please\s+)?(?:hey\s+jev\b\s*,?\s+)?(?:please\s+)?(?:can\s+you\s+|could\s+you\s+)?(?:re-?create|recreate|remake|rebuild)"
RECREATE_RE = re.compile(rf"^{_VERB}\b\s*(?P<rest>.*?)[\s.!?]*$", re.I)
STATUS_RE = re.compile(
    r"^(?:please\s+)?(?:hey\s+jev\b\s*,?\s+)?(?:what(?:'s|\s+is)\s+(?:the\s+)?|check\s+(?:the\s+|my\s+)?|)"
    r"(?:recreate|recreation|rebuild)\s+(?:job\s+)?status\??[.!]*$"
    r"|^(?:how(?:'s|\s+is)\s+)(?:my|the)\s+(?:recreate|recreation|rebuild)\s+(?:job\s+)?(?:going|doing)\??$",
    re.I,
)
_IMAGE_WORDS = re.compile(r"^(?:this|that|the|my)?\s*(?:last\s+|latest\s+)?(?:image|picture|photo|screenshot|screen\s*shot|capture)$", re.I)
_BARE_THIS = re.compile(r"^(?:this|that|it)?$", re.I)
_URL_RE = re.compile(
    r"\b((?:https?://)?(?:[a-z0-9-]+\s*(?:\.|\s+dot\s+))+(?:com|org|net|io|ai|app|dev|co|us|edu|gov|me|tv|so|xyz)(?:/[^\s]*)?)\b",
    re.I,
)
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".heic", ".gif", ".webp", ".tiff")


def recreate_dir(env=None):
    env = os.environ if env is None else env
    return env.get(RECREATE_DIR_ENV) or DEFAULT_RECREATE_DIR


def is_recreate_status(text):
    return bool(STATUS_RE.match(_clean(text).strip()))


def is_recreate_phrase(text):
    raw = _clean(text).strip()
    if is_recreate_status(raw):
        return False
    return bool(RECREATE_RE.match(raw))


def _normalize_url(spoken):
    url = re.sub(r"\s+dot\s+", ".", spoken.strip(), flags=re.I)
    url = re.sub(r"\s*\.\s*", ".", url)
    return url.lower() if "://" not in url else url


def parse_target(text, book=None):
    """Return a target dict or None when Jev must ask what to recreate.

    kinds: 'url', 'image', 'spoken'. Image is the last screenshot or image Jev
    captured (the capture book), only when the words point at it.
    """
    raw = _clean(text).strip()
    match = RECREATE_RE.match(raw)
    if not match:
        return None
    rest = match.group("rest").strip(" ,.!?")
    rest = re.sub(r"^(?:for\s+me\s+)", "", rest, flags=re.I).strip()
    if _IMAGE_WORDS.match(rest) or _BARE_THIS.match(rest):
        path = _last_image(book)
        if path:
            return {"kind": "image", "value": path, "spoken": "your last screenshot"}
        return None
    if not rest:
        return None
    url = _URL_RE.search(rest)
    if url:
        value = _normalize_url(url.group(1))
        return {"kind": "url", "value": value, "spoken": value, "detail": rest[:MAX_REQUEST_CHARS]}
    rest = rest[:MAX_REQUEST_CHARS]
    return {"kind": "spoken", "value": rest, "spoken": rest}


def _last_image(book=None):
    if book is None:
        from .captures import BOOK as book
    last = getattr(book, "last", None) or {}
    path = last.get("path") if isinstance(last, dict) else None
    if path and path.lower().endswith(IMAGE_EXTS) and os.path.isfile(path):
        return path
    return None


def _write_json(dest, data):
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, dest)


def write_job_card(target, request_text, base=None, now=None, platform=None, job_id=None):
    """Write one job card to <base>/inbox/<id>.json. Returns the spoken reply."""
    if (sys.platform if platform is None else platform) != "darwin":
        return "Recreate only works on the Mac."
    if not target:
        return "What should I recreate?"
    base = base or recreate_dir()
    now = time.time() if now is None else now
    job_id = job_id or uuid.uuid4().hex[:16]
    inbox = os.path.join(base, "inbox")
    os.makedirs(inbox, exist_ok=True)
    card = {
        "id": job_id,
        "version": 1,
        "created": int(now),
        "kind": target["kind"],
        "target": target["value"],
        "request": _clean(request_text).strip()[:MAX_REQUEST_CHARS],
        "source": "mac",
    }
    if target.get("detail"):
        card["detail"] = target["detail"]
    if target["kind"] == "image":
        # Copy the image next to the card so the handoff folder is self-contained.
        ext = os.path.splitext(target["value"])[1].lower()
        dest = os.path.join(inbox, job_id + ext)
        shutil.copyfile(target["value"], dest)
        card["image"] = os.path.basename(dest)
    _write_json(os.path.join(inbox, job_id + ".json"), card)
    return "Got it. I sent that to your Chief of Staff. Ask me for the recreate status anytime."


def read_status(base=None):
    """Spoken line from <base>/outbox/status.json, written by the Chief of Staff."""
    base = base or recreate_dir()
    path = os.path.join(base, "outbox", "status.json")
    if os.path.islink(path) or not os.path.isfile(path):
        return "No recreate updates yet."
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return "I couldn't read the recreate status."
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, str) or not message.strip():
        return "No recreate updates yet."
    return re.sub(r"\s+", " ", message).strip()[:MAX_STATUS_CHARS]


def confirm_prompt(target):
    return f"Recreate {target['spoken']}? Say yes or no."
