"""Read app usage metadata without launching apps."""
from datetime import datetime
import os
from pathlib import Path
import subprocess
import time

from .cleanup_gate import Proposal
from .cleanup_rules import fernando_reason, protected_app, protected_reason

UNUSED_APP_DAYS = 90


def app_paths(roots):
    for root in roots:
        root = Path(root)
        if root.is_symlink():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for path in entries:
            if path.is_symlink() or not path.is_dir():
                continue
            if path.suffix.lower() == '.app':
                yield path
            elif path.name not in ('Setapp', 'Utilities') and not path.name.startswith('.'):
                try:
                    yield from (p for p in path.iterdir()
                                if p.suffix.lower() == '.app' and not p.is_symlink() and p.is_dir())
                except OSError:
                    continue


def last_opened(path, runner=subprocess.run):
    try:
        result = runner(['/usr/bin/mdls', '-name', 'kMDItemLastUsedDate', '-raw', str(path)],
                        capture_output=True, text=True, timeout=3, check=True)
        value = result.stdout.strip()
        if value == '(null)':
            return None, True
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S %z'), True
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, False


def running_apps():
    from AppKit import NSWorkspace
    return {Path(app.bundleURL().path()).resolve()
            for app in NSWorkspace.sharedWorkspace().runningApplications() if app.bundleURL()}


def unused_apps(home, roots, measure, cancel, extra=(), runner=subprocess.run, running=(), now=None):
    now = time.time() if now is None else now
    for path in app_paths(roots):
        if cancel.is_set():
            break
        if protected_app(path, home):
            yield Proposal(str(path), 0, path.stem, 'Protected: Claude Code URL Handler',
                           'leave_alone', False, kind='app', bucket='fernando')
            continue
        name = path.stem.casefold()
        if path.resolve() in running or name in {'jev', 'hey jev', 'eney', 'setapp'}:
            continue
        reason = protected_reason(path, home, extra)
        if reason == 'outside home':
            reason = protected_reason(path, path.parent, extra)
        if reason and reason != 'outside home':
            continue
        if name.startswith('xcode') or any(part.casefold() == 'setapp' for part in path.parts):
            continue
        opened, known = last_opened(path, runner)
        if not known or (opened is not None and now - opened.timestamp() < UNUSED_APP_DAYS * 86400):
            continue
        size, partial = measure(path)
        detail = 'Never opened (or macOS has no record)' if opened is None else f'Last opened {opened.date()}'
        manual = fernando_reason(path, home, uid=os.getuid())
        yield Proposal(str(path), size, path.stem, manual or detail, 'ask_first', not manual and not partial,
                       kind='app', bucket='fernando' if manual else 'apps', detail=detail, group=str(path))
