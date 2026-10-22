"""Open Fernando's own web games and sites in the Mac's default browser.

Mac-only. Not in BRIDGE_ALLOW, so the iPhone bridge cannot open them.
Only the hardcoded https URLs below are ever opened, with `open <url>`
as an argument list (never a shell string). Nothing is fetched here.
"""
import re
import sys

from .shell import _run

WEB_SITES = (
    {
        "key": "starlight",
        "label": "Starlight Quest",
        "url": "https://fernandoceja.github.io/Zoe-s-Princess-Academy/starlight-quest/",
        "names": ("starlight quest", "zoe's starlight quest", "zoes starlight quest", "starlight",
                  "star light quest", "starlight quests", "star lite quest", "starlite quest",
                  "starlight guest", "star light", "starlight game"),
    },
    {
        "key": "barnaby",
        "label": "Barnaby and Pip",
        "url": "https://barnaby-pip-rainbow-crayon.fernando-ceja.chatgpt.site/",
        "names": ("barnaby pip", "barnaby and pip", "barnaby & pip", "barnaby", "barney pip",
                  "barnabee", "barnabe", "barnaby the rainbow crayon", "the rainbow crayon",
                  "rainbow crayon", "barnaby game", "barnaby and pip rainbow crayon"),
    },
    {
        "key": "calculus",
        "label": "the Calculus 3 visualization",
        "url": "https://fernandoceja.github.io/calculus-3-visualization/",
        "names": ("calculus", "calculus 3", "calculus three", "calc 3", "calc three", "calculus site",
                  "calculus 3 visualization", "calculus visualization", "calculus three visualization",
                  "the math site", "math site", "calcforge", "calc forge", "calculus lab",
                  "calculator site", "calculus app"),
    },
)

WEB_NOT_MAC = "I can open that on the Mac."
WEB_FAILED = "I couldn't open {label}."

_VERBS = r"(?:open|launch|play|start|go\s+to|load|pull\s+up|show(?:\s+me)?|bring\s+up)"


def _norm(text):
    t = (text or "").lower().replace("’", "'").strip()
    t = re.sub(r"^(?:hey\s+)?jev[,\s]+", "", t)
    t = re.sub(r"^(?:please\s+|can\s+you\s+|could\s+you\s+)", "", t)
    t = re.sub(r"[\s.!?,]+$", "", t)
    t = re.sub(r"\s+(?:please|for me|in the browser|in my browser|in safari|in chrome)$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def match_web_site(text):
    """The WEB_SITES entry for "open starlight quest", "play barnaby", ... or None."""
    t = _norm(text)
    m = re.fullmatch(rf"{_VERBS}\s+(?:up\s+)?(?:the\s+|my\s+)?(.+)", t)
    if not m:
        return None
    name = m.group(1).strip()
    names = (name, re.sub(r"\s+(?:game|site|website|page)$", "", name))
    for entry in WEB_SITES:
        for alias in entry["names"]:
            if re.sub(r"^the\s+", "", alias) in names:
                return entry
    return None


def is_web_site_phrase(text):
    return match_web_site(text) is not None


def _safe(url):
    return url.startswith("https://") and not re.search(r"[\s\"'`;|&$<>]", url)


def open_web_site_from_text(text, platform=None, run=_run):
    entry = match_web_site(text)
    if not entry:
        return "Which site should I open?"
    if (platform or sys.platform) != "darwin":
        return WEB_NOT_MAC
    if not _safe(entry["url"]):
        return WEB_FAILED.format(label=entry["label"])
    try:
        run(("open", entry["url"]))
    except Exception:
        return WEB_FAILED.format(label=entry["label"])
    return f"Opening {entry['label']}."
