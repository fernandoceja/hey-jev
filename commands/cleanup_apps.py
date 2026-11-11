"""Read app usage metadata without launching apps."""
from datetime import datetime
import os
from pathlib import Path
import stat
import subprocess
import time

from .cleanup_gate import Proposal
from .cleanup_rules import fernando_reason, protected_app, protected_reason, recently_modified

UNUSED_APP_DAYS = 90


def app_paths(roots, *, include_setapp=False):
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
            elif path.name != 'Utilities' and (include_setapp or path.name != 'Setapp') and not path.name.startswith('.'):
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


APPLICATIONS_ROOT = Path('/Applications')


def external_app_path(path, applications=APPLICATIONS_ROOT):
    """Accept only real app bundle paths below the Applications root."""
    return (path.suffix.casefold() == '.app' and applications in path.parents
            and path.resolve() == path and not path.is_symlink())


def app_refusal(path, home, extra, running, *, applications=APPLICATIONS_ROOT, now=None):
    path = Path(path).absolute()
    external = external_app_path(path, applications)
    scope = applications if external else home
    reason = protected_reason(path, scope, extra)
    if reason or protected_app(path, home):
        return 'protected app'
    if any(part.casefold() == 'setapp' for part in path.parts) or path.stem.casefold() in {'eney', 'setapp'}:
        return 'protected Eney or Setapp app'
    if path.resolve() in running:
        return 'app is running'
    if path.resolve() != path:
        return 'app path contains a symlink'
    if external:
        from .cleanup_leftovers import bundle_id
        identifier = bundle_id(path)
        if not identifier or identifier.casefold().startswith('com.apple.') or path.stem.casefold().startswith('xcode'):
            return 'Apple app or bundle identity unavailable'
        try:
            info = path.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                    or not os.access(path, os.W_OK | os.X_OK)
                    or not os.access(path.parent, os.W_OK | os.X_OK)):
                return 'needs administrator rights'
            if recently_modified(info.st_mtime, time.time() if now is None else now):
                return 'modified in the last 24 hours'
        except OSError:
            return 'app metadata unavailable'
    else:
        return fernando_reason(path, home, uid=os.getuid())
    return None


def unused_apps(home, roots, measure, cancel, extra=(), runner=subprocess.run, running=(), now=None,
                applications=APPLICATIONS_ROOT):
    now = time.time() if now is None else now
    for path in app_paths(roots, include_setapp=True):
        if cancel.is_set():
            break
        name = path.stem.casefold()
        if name in {'jev', 'hey jev'}:
            continue
        if name in {'eney', 'setapp'} or any(part.casefold() == 'setapp' for part in path.parts):
            yield Proposal(str(path), 0, path.stem, 'Protected Setapp app',
                           'leave_alone', False, kind='app', bucket='fernando')
            continue
        scope = applications if external_app_path(path, applications) else home
        protection = protected_reason(path, scope, extra)
        if protection or protected_app(path, home):
            reason = ('Protected: Claude Code URL Handler' if protection == 'Claude Code URL Handler'
                      or not protection else 'Protected app')
            yield Proposal(str(path), 0, path.stem, reason,
                           'leave_alone', False, kind='app', bucket='fernando')
            continue
        opened, known = last_opened(path, runner)
        if not known or (opened is not None and now - opened.timestamp() < UNUSED_APP_DAYS * 86400):
            continue
        manual = app_refusal(path, home, extra, running, applications=applications, now=now)
        size, partial = (0, False) if manual and 'protected' in manual else measure(path)
        detail = 'Never opened (or macOS has no record)' if opened is None else f'Last opened {opened.date()}'
        reason = manual or ('Measurement incomplete' if partial else None)
        yield Proposal(str(path), size, path.stem, reason or detail, 'ask_first', not reason,
                       kind='app', bucket='fernando' if reason else 'apps', detail=detail, group=str(path))
