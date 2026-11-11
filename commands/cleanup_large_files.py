"""Read-only home scan for large files, with an optional modification age."""
from collections import deque
import errno
import math
import os
from pathlib import Path
import stat
import time

from .cleanup_gate import Proposal
from .cleanup_rules import DATABASE_SUFFIXES, protected_reason, recently_modified

CATEGORY = 'Large & Old Files'
BUCKET = 'large_files'
DEFAULT_MIN_MB = 500
PACKAGE_SUFFIXES = frozenset({
    '.photoslibrary', '.app', '.bundle', '.framework', '.plugin', '.appex',
    '.pkg', '.xpc', '.rtfd', '.pages', '.numbers', '.key', '.playground',
    '.xcassets', '.xcworkspace', '.xcodeproj', '.photolibrary', '.musiclibrary',
    '.imovielibrary', '.fcpbundle', '.sparsebundle', '.vmwarevm', '.parallels', '.pvm',
})
# Darwin's stat.h: a placeholder without local file contents.
SF_DATALESS = 0x40000000


def _number(environ, key, default, minimum):
    try:
        value = float(environ.get(key, default))
        if math.isfinite(value) and minimum <= value <= 1e9:
            return value
    except (ValueError, TypeError):
        pass
    return default


def settings(environ):
    mb = _number(environ, 'JEV_LARGE_FILES_MIN_MB', DEFAULT_MIN_MB, 1)
    days = _number(environ, 'JEV_LARGE_FILES_MIN_AGE_DAYS', 0, 0)
    return int(mb * 1_000_000), days * 86400


def candidates(home, cancel, local, *, min_bytes, min_age, reader=None, limit=100000, now=None):
    """Yield one row per qualifying path. Never read file contents or follow symlinks."""
    home = Path(home).resolve()
    now = time.time() if now is None else now
    pending = deque([home])
    examined = 0
    permission_skips = 0
    other_errors = 0
    remaining_directories = 0
    packages_skipped = 0
    skipped_roots = {home / 'Library', home / '.Trash', home / '.ollama/models',
                     home / '.npm/_cacache'}
    while pending and not cancel.is_set():
        directory = pending.popleft()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if cancel.is_set():
                        return
                    if examined >= limit:
                        remaining_directories = len(pending) + 1
                        pending.clear()
                        break
                    examined += 1
                    path = Path(entry.path)
                    if path in skipped_roots:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if path.suffix.casefold() in PACKAGE_SUFFIXES:
                                packages_skipped += 1
                                continue
                            if not protected_reason(path, home, local) and not (path / '.git').exists():
                                pending.append(path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        info = entry.stat(follow_symlinks=False)
                        if not stat.S_ISREG(info.st_mode) or info.st_size < min_bytes:
                            continue
                        if min_age and now - info.st_mtime < min_age:
                            continue
                        database = path.name.casefold().endswith(DATABASE_SUFFIXES)
                        protection = protected_reason(path, home, local)
                        if protection and not (database and protection.endswith('(size only)')):
                            continue
                        if getattr(info, 'st_flags', 0) & SF_DATALESS:
                            continue
                        cloud = reader(path) if reader is not None and not database else {}
                        if cloud.get('cloud_only'):
                            continue
                        size = info.st_blocks * 512
                        reason = 'Select to review a move to Trash. Size is disk space allocated.'
                        actionable = True
                        if database:
                            reason, actionable = 'Database · path and size only', False
                        elif cloud.get('IsUbiquitousItem'):
                            reason, actionable = 'iCloud file · use the iCloud cleanup action for local copies', False
                        elif recently_modified(info.st_mtime, now):
                            reason, actionable = 'Changed in the last 24 hours', False
                        yield Proposal(str(path), size, CATEGORY, reason, 'ask_first', actionable, bucket=BUCKET)
                    except OSError as error:
                        if error.errno in (errno.EACCES, errno.EPERM):
                            permission_skips += 1
                        else:
                            other_errors += 1
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EPERM):
                permission_skips += 1
            else:
                other_errors += 1
    if cancel.is_set():
        return
    details = [f'{examined:,} entries visited', f'{packages_skipped:,} packages skipped']
    if permission_skips:
        details.append(f'{permission_skips:,} paths skipped (permission denied)')
    if other_errors:
        details.append(f'{other_errors:,} paths skipped (other filesystem errors)')
    if remaining_directories:
        details.append(f'{limit:,}-entry limit reached; {remaining_directories:,} directories unfinished')
    status = 'Scan incomplete' if permission_skips or other_errors or remaining_directories else 'Scan complete'
    yield Proposal(str(home), 0, CATEGORY, status + ': ' + '. '.join(details) + '.',
                   'leave_alone', False, bucket=BUCKET)
