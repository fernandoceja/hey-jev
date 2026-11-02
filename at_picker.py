"""Pure full-window @ picker helpers. File discovery runs only in the warmer."""
import os
import re
import threading
import time

AT_MAX_ROWS = 8
AT_PER_SECTION = 4
AT_ROW_H = 30.0
AT_PAD = 6.0
AT_GAP = 6.0
AT_RADIUS = 12.0
AT_QUERY_MAX = 40
FILE_ROOTS = ("~/Desktop", "~/Documents", "~/Downloads")
FILE_DEPTH = 2
FILE_SCAN_CAP = 2000
FILE_TTL = 60.0
PACKAGE_SUFFIXES = (".app", ".bundle", ".photoslibrary", ".musiclibrary", ".fcpbundle",
                    ".imovielibrary", ".pkg", ".framework")
_files = []
_files_at = None
_warm_lock = threading.Lock()


def utf16_len(text):
    return len(text.encode("utf-16-le")) // 2


def py_index(text, utf16_offset):
    used = 0
    for i, char in enumerate(text):
        used += utf16_len(char)
        if used > utf16_offset:
            return i
    return len(text)


def at_query(text, caret):
    caret = max(0, min(int(caret), len(text)))
    start = text.rfind("@", 0, caret)
    if start < 0 or (start and not text[start - 1].isspace()):
        return None
    query = text[start + 1:caret]
    if len(query) > AT_QUERY_MAX or any(c.isspace() for c in query):
        return None
    return start, query


def match_rank(query, name):
    query, name = query.casefold(), name.casefold()
    if name.startswith(query):
        return 0
    if any(part.startswith(query) for part in re.split(r"[\s_.-]+", name)):
        return 1
    return 2 if query in name else None


def app_rows(index):
    rows = {}
    for path in index.values():
        title = os.path.basename(path)
        if title.lower().endswith(".app"):
            title = title[:-4]
        rows.setdefault(title.casefold(), {"kind": "app", "title": title, "subtitle": "App",
                                         "insert": title, "path": path})
    return sorted(rows.values(), key=lambda row: row["title"].casefold())


def scan_files(roots=FILE_ROOTS, depth=FILE_DEPTH, cap=FILE_SCAN_CAP):
    rows, seen = [], 0
    home = os.path.realpath(os.path.expanduser("~"))

    def walk(folder, level):
        nonlocal seen
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if seen >= cap:
                        return
                    seen += 1
                    name = entry.name
                    if name.startswith(".") or any(c in name for c in ('"', '\n', '\r')):
                        continue
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if level < depth and not name.lower().endswith(PACKAGE_SUFFIXES):
                                walk(entry.path, level + 1)
                        elif entry.is_file(follow_symlinks=False):
                            path = os.path.abspath(entry.path)
                            if not path.startswith(home + os.sep):
                                continue
                            relative = os.path.relpath(path, home)
                            rows.append({"kind": "file", "title": name,
                                         "subtitle": os.path.dirname(relative),
                                         "insert": '"~/' + relative + '"', "path": path,
                                         "mtime": entry.stat(follow_symlinks=False).st_mtime})
                    except OSError:
                        continue
        except OSError:
            return

    for root in roots:
        folder = os.path.expanduser(root)
        if not os.path.islink(folder) and depth > 0:
            walk(folder, 1)
    return rows


def warm_files():
    global _files, _files_at
    with _warm_lock:
        now = time.monotonic()
        if _files_at is None or now - _files_at >= FILE_TTL:
            rows = scan_files()
            _files = rows
            _files_at = now


def cached_files():
    return _files


def picker_rows(query, apps, files):
    def matches(rows, file_rows=False):
        ranked = [(match_rank(query, r["title"]), r) for r in rows]
        ranked = [(rank, row) for rank, row in ranked if rank is not None]
        ranked.sort(key=lambda pair: (pair[0], -pair[1].get("mtime", 0), pair[1]["title"].casefold())
                    if file_rows else (pair[0], pair[1]["title"].casefold()))
        return [row for rank, row in ranked]
    apps, files = matches(apps), matches(files, True)
    na, nf = min(AT_PER_SECTION, len(apps)), min(AT_PER_SECTION, len(files))
    na = min(len(apps), AT_MAX_ROWS - nf)
    nf = min(len(files), AT_MAX_ROWS - na)
    return apps[:na] + files[:nf]


def insert_pick(text, start, caret, row):
    inserted = row["insert"] + " "
    return text[:start] + inserted + text[caret:], start + len(inserted)


def picker_frame(input_rect, row_count, window_h, top_limit):
    x, y, width, height = input_rect
    list_h = row_count * AT_ROW_H + 2 * AT_PAD
    above = y + height + AT_GAP
    list_y = above if above + list_h <= window_h - top_limit else y - AT_GAP - list_h
    return x, list_y, width, list_h
