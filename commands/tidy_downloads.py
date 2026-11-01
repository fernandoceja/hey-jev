"""Tidy Downloads and Desktop: a scan and a list. SCAN ONLY (PR 8d).

"tidy my downloads" and "tidy my desktop" read the top level of that folder and reply with proposed groupings: old
installers, possible duplicates and large files, plus counts by type and by age. The reply is text first; the existing
read-aloud offer plays audio only on a yes.

Jev never moves, renames, trashes or deletes a file. Fernando decides and acts himself in Finder. Moving files is a later
PR that needs his explicit approval.

Read-only: os.scandir and stat only. Subfolders, symlinks and hidden names are skipped. Duplicates are judged by name
pattern and size, never by reading or hashing contents. Nothing is written, no network call, no model call, no listening
socket.

Mac voice and typed path only, through siri.decide() after route_before_api, the same place as the PR 8c start-my-day
aliases. It is not in route_before_api, not in BRIDGE_ALLOW and not in ZOE_ALLOW, so the iPhone bridge and Zoe mode never
run it.
"""
import os
import re
import time

from .apps import resolve_folder

TIDY_FOLDERS = ("downloads", "desktop")
TIDY_LABELS = {"downloads": "Downloads", "desktop": "Desktop"}
OLD_DAYS = 90
YEAR_DAYS = 365
LARGE_BYTES = 500 * 1024 * 1024
MAX_FILES = 5000
EXAMPLE_COUNT = 3
DAY_SECONDS = 86400.0

INSTALLER_EXTS = frozenset({".dmg", ".pkg", ".mpkg", ".iso"})
ARCHIVE_EXTS = frozenset({".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".rar", ".7z"})
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp", ".svg"})
DOCUMENT_EXTS = frozenset({
    ".pdf", ".doc", ".docx", ".pages", ".txt", ".rtf", ".md", ".numbers", ".xls", ".xlsx", ".csv", ".ppt", ".pptx",
    ".key", ".odt", ".ods",
})
MEDIA_EXTS = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mp3", ".m4a", ".wav", ".aiff", ".flac", ".aac"})
TYPE_ORDER = ("Installers", "Images", "Documents", "Media", "Archives", "Other")
AGE_ORDER = ("Under 30 days", "30 days to a year", "Over a year")

# "tidy my downloads", "Tidy up the desktop folder", "hey jev, tidy my downloads please". Whole utterance only, so
# "tidy my documents" and "tidy my downloads tomorrow" do not match.
_TIDY = re.compile(
    r"^(?:hey\s+jev\b[\s,]*)?(?:please\s+)?tidy\s+(?:up\s+)?(?:my\s+|the\s+)?(downloads|desktop)"
    r"(?:\s+folder)?(?:\s+please)?[.!?]*$",
    re.I,
)
# "report (1).pdf" or "report copy.pdf" next to "report.pdf". The name pattern only; the size must also match.
_COPY = re.compile(r"^(?P<stem>.+?)(?: \(\d+\)| copy(?: \d+)?)(?P<ext>\.[^.]*)?$")


def tidy_folder_key(text):
    """"downloads" or "desktop" when the whole utterance is a tidy request, else None. Case, spacing and a "hey jev" or
    "please" prefix or suffix do not matter. Empty and non-string input are not requests."""
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    match = _TIDY.match(cleaned)
    return match.group(1).lower() if match else None


def file_type(name):
    """One of TYPE_ORDER, from the extension alone. Case does not matter; a name with no extension is "Other"."""
    ext = os.path.splitext(str(name))[1].lower()
    if ext in INSTALLER_EXTS:
        return "Installers"
    if ext in IMAGE_EXTS:
        return "Images"
    if ext in DOCUMENT_EXTS:
        return "Documents"
    if ext in MEDIA_EXTS:
        return "Media"
    if ext in ARCHIVE_EXTS:
        return "Archives"
    return "Other"


def age_days(mtime, now=None):
    """Whole-file age in days, never negative. A file dated in the future counts as 0 days old."""
    now = time.time() if now is None else float(now)
    return max(0.0, (now - float(mtime)) / DAY_SECONDS)


def age_bucket(days):
    """One of AGE_ORDER."""
    if days < 30:
        return "Under 30 days"
    if days < YEAR_DAYS:
        return "30 days to a year"
    return "Over a year"


def human_size(size):
    """1024-based size with one decimal from KB up, such as "1.2 GB". Bytes stay whole."""
    value = float(max(0, int(size)))
    if value < 1024:
        return "{0} B".format(int(value))
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024 or unit == "TB":
            return "{0:.1f} {1}".format(value, unit)
    return "{0} B".format(int(size))


def scan_folder(path, max_files=MAX_FILES):
    """(files, truncated) for the top level of one folder. Each file is a dict: name, path, size, mtime.

    Subfolders, symlinks, hidden names and anything that cannot be stat'ed are skipped. A missing or unreadable folder
    gives ([], False). At most max_files are kept, and truncated says whether more were there.
    """
    try:
        entries = os.scandir(path)
    except OSError:
        return [], False
    files = []
    truncated = False
    with entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if len(files) >= max_files:
                truncated = True
                break
            files.append({"name": entry.name, "path": entry.path, "size": int(st.st_size), "mtime": float(st.st_mtime)})
    files.sort(key=lambda item: item["name"].lower())
    return files, truncated


def find_duplicates(files):
    """(copy, original) pairs. A copy is "name (2).ext" or "name copy.ext"; its original is "name.ext" in the same list,
    and both must be the same size. Only names and sizes are compared, never contents."""
    by_name = {item["name"]: item for item in files}
    pairs = []
    for item in files:
        match = _COPY.match(item["name"])
        if not match:
            continue
        original = by_name.get(match.group("stem") + (match.group("ext") or ""))
        if original is not None and original is not item and original["size"] == item["size"]:
            pairs.append((item, original))
    return pairs


def _annotate(files, now):
    rows = []
    for item in files:
        days = age_days(item["mtime"], now)
        rows.append(dict(item, type=file_type(item["name"]), days=days, bucket=age_bucket(days)))
    return rows


def _group(rows):
    """count, bytes and the first few names, biggest first."""
    ordered = sorted(rows, key=lambda row: (-row["size"], row["name"].lower()))
    return {
        "count": len(rows),
        "bytes": sum(row["size"] for row in rows),
        "examples": [row["name"] for row in ordered[:EXAMPLE_COUNT]],
    }


def build_report(files, now=None, truncated=False):
    """Groupings for one scan. Pure: takes the scan's dicts, reads no disk.

    Old installers are installers at least OLD_DAYS old. Large files are at least LARGE_BYTES. Duplicates come from
    find_duplicates. Counts by type and by age cover every file.
    """
    now = time.time() if now is None else float(now)
    rows = _annotate(files, now)
    types = {name: {"count": 0, "bytes": 0} for name in TYPE_ORDER}
    ages = {name: 0 for name in AGE_ORDER}
    for row in rows:
        types[row["type"]]["count"] += 1
        types[row["type"]]["bytes"] += row["size"]
        ages[row["bucket"]] += 1
    old_installers = [row for row in rows if row["type"] == "Installers" and row["days"] >= OLD_DAYS]
    large = [row for row in rows if row["size"] >= LARGE_BYTES]
    duplicates = find_duplicates(files)
    return {
        "count": len(rows),
        "bytes": sum(row["size"] for row in rows),
        "truncated": bool(truncated),
        "types": types,
        "ages": ages,
        "old_installers": _group(old_installers),
        "large": _group(large),
        "duplicates": {
            "count": len(duplicates),
            "examples": [copy["name"] for copy, _original in
                         sorted(duplicates, key=lambda pair: pair[0]["name"].lower())[:EXAMPLE_COUNT]],
        },
    }


def _examples(names):
    return ", ".join(names)


def format_report(report, label):
    """One line for the window and the read-aloud offer. It says what was found and that nothing was moved."""
    if report["count"] == 0:
        return "{0} has no files at the top level, so there's nothing to tidy.".format(label)
    by_type = ", ".join("{0} {1}".format(name.lower(), info["count"])
                        for name, info in report["types"].items() if info["count"])
    by_age = ", ".join("{0} {1}".format(name.lower(), report["ages"][name]) for name in AGE_ORDER)
    old = report["old_installers"]
    old_text = ("{0}, {1}, e.g. {2}".format(old["count"], human_size(old["bytes"]), _examples(old["examples"]))
                if old["count"] else "none")
    dupes = report["duplicates"]
    dupe_text = ("{0}, e.g. {1}".format(dupes["count"], _examples(dupes["examples"])) if dupes["count"] else "none")
    large = report["large"]
    large_text = ("{0}, {1}, e.g. {2}".format(large["count"], human_size(large["bytes"]), _examples(large["examples"]))
                  if large["count"] else "none")
    lines = [
        "{0}: {1} files, {2}.".format(label, report["count"], human_size(report["bytes"])),
        "By type: {0}. By age: {1}.".format(by_type, by_age),
        "Old installers over {0} days: {1}.".format(OLD_DAYS, old_text),
        "Possible duplicates: {0}.".format(dupe_text),
        "Large files over {0} MB: {1}.".format(LARGE_BYTES // (1024 * 1024), large_text),
        "Top level only. I haven't moved, renamed or deleted anything. Review them in Finder.",
    ]
    if report["truncated"]:
        lines.append("Only the first {0} files were checked.".format(MAX_FILES))
    return " ".join(lines)


def tidy_scan(folder_key, path, now=None, max_files=MAX_FILES):
    """The reply for one folder on disk. Scan only: the folder is read, never changed."""
    label = TIDY_LABELS.get(folder_key, "That folder")
    if not os.path.isdir(path):
        return "I couldn't find your {0} folder.".format(label.lower())
    files, truncated = scan_folder(path, max_files=max_files)
    return format_report(build_report(files, now=now, truncated=truncated), label)


def tidy_scan_from_text(text, now=None):
    """The reply for a tidy request, or None when the text is not one. The folder comes from resolve_folder, so
    "downloads" and "desktop" use the same paths as the rest of Jev."""
    key = tidy_folder_key(text)
    if key is None:
        return None
    path = resolve_folder(key)
    if not path:
        return "I couldn't find your {0} folder.".format(key)
    return tidy_scan(key, os.path.abspath(os.path.expanduser(path)), now=now)
