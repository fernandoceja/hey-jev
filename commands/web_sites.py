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
    {
        "key": "tetris3d",
        "label": "3D Tetris",
        "url": "https://fernandoceja.github.io/3D-Tetris/",
        "names": ("3d tetris", "3 d tetris", "three d tetris", "threed tetris", "3-d tetris", "3d tetras",
                  "3d tetrus", "three d tetras", "tetris 3d", "tetris three d", "3d tetris game"),
    },
    {
        "key": "tetris",
        "label": "Tetris",
        "url": "https://fernandoceja.github.io/Tetris-Game/",
        "names": ("tetris", "classic tetris", "regular tetris", "normal tetris", "2d tetris", "two d tetris",
                  "tetris game", "tetras", "tetrus", "tetris classic", "old tetris", "original tetris"),
    },
    {
        "key": "academy",
        "label": "Zoe's Princess Academy",
        "url": "https://fernandoceja.github.io/Zoe-s-Princess-Academy/",
        "names": ("princess academy", "zoe's princess academy", "zoes princess academy", "zoey's princess academy",
                  "zoeys princess academy", "zoe's academy", "zoes academy", "zoey's academy",
                  "princess academy app", "princes academy", "princess akademy"),
    },
    {
        "key": "chores",
        "label": "Zoe's Princess Chores",
        "url": "https://fernandoceja.github.io/Zoe-s-Princess-Chores/",
        "names": ("princess chores", "zoe's princess chores", "zoes princess chores", "zoey's princess chores",
                  "zoeys princess chores", "zoe's chores", "zoes chores", "zoey's chores", "zoe's chore chart",
                  "chore chart", "princess chore chart", "princess chores app", "princes chores",
                  "princess chors"),
    },
    {
        "key": "interview",
        "label": "the STAR Interview Coach",
        "url": "https://fernandoceja.github.io/AI-star-interview-coach/",
        "names": ("interview coach", "star interview coach", "ai star interview coach", "ai interview coach",
                  "star coach", "star method coach", "interview practice", "star interview",
                  "a i interview coach", "stars interview coach", "interview couch", "star interview couch"),
    },
    {
        "key": "typer",
        "label": "Kinetic Typer",
        "url": "https://fernandoceja.github.io/kinetic-typer/",
        "names": ("kinetic typer", "kinetic typing", "kinetic type", "kinetic typer game", "kinetic tiper",
                  "kinetic taper", "connetic typer", "kenetic typer", "kinetic typewriter", "kinetic writer"),
    },
    {
        # Same URL as the Chrome "store site" entry in config.SITES. Bare "store",
        # Shopify admin, and orders phrases stay with site_open.
        "key": "business",
        "label": "80s Obsession Company",
        "url": "https://80sobsessioncompany.com/",
        "names": ("my business website", "my business site", "my website", "my web site", "my store",
                  "my shop", "my online store", "80s obsession", "80's obsession", "eighties obsession",
                  "80s obsession company", "80's obsession company", "eighties obsession company",
                  "eighty obsession", "80 obsession", "80s obsessions", "eighties obsessions",
                  "ladies obsession", "80s obsession store", "eighties obsession store", "shop site",
                  "the shop site", "business website", "80sobsessioncompany.com",
                  "80s obsession company website"),
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
    m = re.fullmatch(rf"{_VERBS}\s+(?:up\s+)?(.+)", t)
    if not m:
        return None
    rest = m.group(1).strip()
    bare = re.sub(r"^(?:the|my)\s+", "", rest)
    # "open (zoe's) princess academy" stays with the existing zoe_academy command
    # (Shortcut first, then the same URL). Other verbs come here.
    if t.startswith("open ") and re.fullmatch(r"(?:zoe'?s\s+)?princess\s+academy", bare):
        return None
    names = set()
    for n in (rest, bare):
        names.add(n)
        names.add(re.sub(r"\s+(?:game|site|website|page)$", "", n))
    for entry in WEB_SITES:
        for alias in entry["names"]:
            if re.sub(r"^the\s+", "", alias) in names or alias in names:
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
