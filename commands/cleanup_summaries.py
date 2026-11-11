"""Report-only Documents and Desktop summaries. Metadata only: nothing is opened, moved or deleted."""
import os
from pathlib import Path

from .cleanup_gate import Proposal

BUCKET = 'folders'
CATEGORY = 'Folder summaries (report only)'
FOLDERS = ('Documents', 'Desktop')
IGNORED = ('.DS_Store', '.localized')


def human(size):
    return f'{size / 1073741824:.2f} GB' if size >= 1073741824 else f'{size / 1048576:.1f} MB'


def top_level_count(folder, limit):
    """Top-level item count from directory entries alone; (count, readable)."""
    count = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name in IGNORED:
                    continue
                count += 1
                if count >= limit:
                    break
    except OSError:
        return 0, False
    return count, True


def summary_rows(home, measure, cancel, limit=100000, paths=None):
    """One non-selectable row per folder. `measure(path)` returns (allocated bytes, partial)."""
    home, paths = Path(home), paths or {}
    for name in FOLDERS:
        if cancel.is_set():
            break
        folder = Path(paths.get(name, home / name))
        if folder.is_symlink() or not folder.is_dir():
            continue
        count, readable = top_level_count(folder, limit)
        if not readable:
            yield Proposal(str(folder), 0, f'{name} summary', 'Needs permission or unreadable. Report only.',
                           'leave_alone', False, bucket=BUCKET)
            continue
        size, partial = measure(folder)
        note = ' (excludes protected or unreadable items)' if partial else ''
        yield Proposal(str(folder), size, f'{name} summary',
                       f'{count} items, {human(size)} allocated{note}. Report only: Jev never moves or deletes this folder.',
                       'leave_alone', False, bucket=BUCKET)
