"""Bounded read-only storage measurements. Cocoa is loaded only on macOS."""
from dataclasses import replace
import os
import stat
import time
from pathlib import Path
import subprocess
import sys
import threading
from . import cleanup_large_files, cleanup_summaries, tidy_downloads
from .cleanup_gate import Proposal
from .cleanup_rules import DATABASE_SUFFIXES, is_dataless, load_protected, protected_reason, recently_modified, skip_storage_path

# category, relative path, safety, deletable, irreplaceable
LOCATIONS = (
    ('User caches', 'Library/Caches', 'safe', True, False),
    ('User logs', 'Library/Logs', 'safe', True, False),
    ('Xcode DerivedData', 'Library/Developer/Xcode/DerivedData', 'safe', True, False),
    ('Xcode Archives', 'Library/Developer/Xcode/Archives', 'ask_first', True, False),
    ('iOS DeviceSupport', 'Library/Developer/Xcode/iOS DeviceSupport', 'safe', True, False),
    ('watchOS DeviceSupport', 'Library/Developer/Xcode/watchOS DeviceSupport', 'safe', True, False),
    ('tvOS DeviceSupport', 'Library/Developer/Xcode/tvOS DeviceSupport', 'safe', True, False),
    ('npm cache', '.npm/_cacache', 'safe', True, False),
    ('CoreSimulator', 'Library/Developer/CoreSimulator', 'leave_alone', False, False),
    ('iOS/iPadOS backups', 'Library/Application Support/MobileSync/Backup', 'ask_first', True, True),
    ('Mail attachments', 'Library/Containers/com.apple.mail/Data/Library/Mail Downloads', 'ask_first', False, False),
    ('Mail Downloads', 'Library/Mail Downloads', 'ask_first', False, False),
    ('Messages attachments', 'Library/Messages/Attachments', 'ask_first', False, False),
    ('Ollama models', '.ollama/models', 'ask_first', True, False),
    ('Trash', '.Trash', 'leave_alone', False, False),
)


def _measure(path, cancel, limit=100000, protected=None):
    """Allocated bytes where available; partial measurements are explicitly labelled."""
    total, count, partial = 0, 0, False
    newest, symlink, database = 0, False, False
    pending = [Path(path)]
    while pending and not cancel.is_set():
        p = pending.pop()
        count += 1
        if count > limit:
            partial = True
            break
        try:
            st = p.lstat()
            if is_dataless(st):
                partial = True
                continue
            newest = max(newest, st.st_mtime)
            database |= p.name.lower().endswith(DATABASE_SUFFIXES)
            if stat.S_ISLNK(st.st_mode):
                symlink = True
                continue
            if protected and protected(p):
                partial = True
                continue
            total += getattr(st, 'st_blocks', (st.st_size + 511) // 512) * 512
            if stat.S_ISDIR(st.st_mode):
                with os.scandir(p) as entries:
                    for entry in entries:
                        if cancel.is_set() or len(pending) + count >= limit:
                            partial = True
                            break
                        pending.append(Path(entry.path))
        except PermissionError:
            partial = True
        except OSError:
            partial = True
    return total, partial or cancel.is_set(), newest, symlink, database


def measure(path, cancel, limit=100000):
    return _measure(path, cancel, limit)[:2]


def free_space(home):
    if sys.platform != 'darwin':
        return None
    from Foundation import NSURL, NSURLVolumeAvailableCapacityForImportantUsageKey
    values, error = NSURL.fileURLWithPath_(str(home)).resourceValuesForKeys_error_(
        [NSURLVolumeAvailableCapacityForImportantUsageKey], None)
    return values.get(NSURLVolumeAvailableCapacityForImportantUsageKey) if values else None


def download_rows(folder, home, local, cancel, limit):
    if skip_storage_path(folder, home) or folder.is_symlink() or protected_reason(folder, home, local):
        return
    files, _ = tidy_downloads.scan_folder(folder, max_files=limit)
    files = [item for item in files if not skip_storage_path(item['path'], home)]
    copies = {copy['path'] for copy, _ in tidy_downloads.find_duplicates(files)}
    now = time.time()
    for item in files:
        if cancel.is_set():
            break
        path = Path(item['path'])
        reason = protected_reason(path, home, local)
        if reason:
            yield Proposal(str(path), 0, 'Downloads', reason, 'leave_alone', False)
            continue
        days = tidy_downloads.age_days(item['mtime'], now)
        category = 'Downloads'
        if item['path'] in copies:
            reason = 'Possible copy based on name and size'
        elif days >= tidy_downloads.OLD_DAYS and tidy_downloads.file_type(path.name) == 'Installers':
            reason, category = 'Installer at least 90 days old', 'Installers / updates'
        elif item['size'] >= tidy_downloads.LARGE_BYTES:
            reason = 'Large download'
        elif days >= tidy_downloads.YEAR_DAYS:
            reason = 'Download at least one year old'
        else:
            continue
        size, partial = measure(path, cancel, limit)
        yield Proposal(str(path), size, category, reason, 'ask_first', not partial and days >= 1)


def scan(home=None, paths=None, cancel=None, snapshots=None, limit=100000, progress=None):
    home = Path(home or Path.home())
    cancel = cancel or threading.Event()
    paths = paths or {}
    rows = []
    local = load_protected(home / "Library/Application Support/Hey Jev/cleanup-protected.json")

    def guard(item):
        return skip_storage_path(item, home) or protected_reason(item, home, local)

    def report(stage):
        if progress and not cancel.is_set():
            progress(stage)

    for category, relative, safety, deletable, irreplaceable in LOCATIONS:
        if cancel.is_set():
            break
        report(category)
        path = Path(paths.get(category, home / relative))
        if skip_storage_path(path, home):
            continue
        targets = [path]
        split = category in ('User caches', 'User logs', 'Xcode DerivedData') or category.endswith('DeviceSupport')
        if split and path.is_dir() and not path.is_symlink() and not protected_reason(path, home, local):
            try:
                with os.scandir(path) as entries:
                    targets = [Path(entry.path) for _, entry in zip(range(min(1000, limit)), entries)]
            except OSError:
                targets = [path]
                deletable = False
        for target in targets:
            if cancel.is_set():
                break
            if skip_storage_path(target, home) or not target.exists() or target.is_symlink():
                continue
            protected = protected_reason(target, home, local)
            size, partial, newest, symlink, database = _measure(target, cancel, limit, guard)
            reason = 'Review before moving to Trash'
            label = category
            if category == 'User caches':
                label = {'pip': 'pip cache', 'homebrew': 'Homebrew cache'}.get(target.name.lower(), category)
            allowed = deletable and not partial and not symlink
            effective = safety
            bucket = ''
            if protected:
                effective, allowed, reason = 'leave_alone', False, protected
            elif partial or symlink:
                effective, allowed = 'leave_alone', False
                reason = 'Contains a symlink' if symlink else 'Measurement incomplete or contains protected items'
            elif recently_modified(newest, time.time()):
                effective, allowed, reason = 'ask_first', False, 'Changed in the last 24 hours'
            elif safety == 'safe':
                reason = 'The app or tool can rebuild these files'
            if database:
                reason += '. Contains a database (size only)'
            if category == 'CoreSimulator':
                bucket, reason = 'fernando', 'Manage simulators in Xcode'
            if category == 'Trash':
                bucket, reason = 'your_call', 'Review the whole Trash separately'
            rows.append(Proposal(str(target), size, label, reason, effective,
                                 allowed, irreplaceable, bucket=bucket))
    if not cancel.is_set():
        report('Downloads')
        rows.extend(download_rows(Path(paths.get('Downloads', home / 'Downloads')), home, local, cancel, limit))
    if not cancel.is_set():
        report('Documents and Desktop')
        rows.extend(cleanup_summaries.summary_rows(
            home, lambda folder: _measure(folder, cancel, limit,
                                          guard)[:2],
            cancel, limit, paths))
    for relative in ('Library/iTunes/Software Updates', 'Library/iTunes/iPhone Software Updates', 'Library/iTunes/iPad Software Updates'):
        if cancel.is_set():
            break
        report('Installers and updates')
        folder = Path(paths.get(relative, home / relative))
        if skip_storage_path(folder, home) or folder.is_symlink() or protected_reason(folder, home, local):
            continue
        # Bounded traversal for installer files; no directory symlink traversal.
        count = 0
        for root, dirs, files in os.walk(folder, followlinks=False):
            count += 1
            if count > limit or cancel.is_set():
                break
            dirs[:]  = [d for d in dirs if not skip_storage_path(Path(root) / d, home) and not (Path(root) / d).is_symlink() and not protected_reason(Path(root) / d, home, local)]
            for name in files:
                count += 1
                if count > limit or cancel.is_set():
                    break
                p = Path(root) / name
                if p.suffix.lower() in ('.dmg', '.pkg', '.ipsw') and not skip_storage_path(p, home) and not p.is_symlink() and not protected_reason(p, home, local):
                    size, partial = measure(p, cancel, limit)
                    rows.append(Proposal(str(p), size, 'Installers / updates', 'Installer; review first', 'ask_first', not partial))
            if count > limit or cancel.is_set():
                break
    if not cancel.is_set() and sys.platform == 'darwin' and home == Path.home():
        report('Applications')
        from .cleanup_apps import app_paths, running_apps, unused_apps
        from .cleanup_leftovers import leftovers
        roots = (Path('/Applications'), home / 'Applications')
        def app_measure(path):
            scan_root = home if home in path.parents else path.parent
            return _measure(path, cancel, limit,
                            lambda item: protected_reason(item, scan_root, local))[:2]
        apps = list(unused_apps(home, roots, app_measure,
                                cancel, local, running=running_apps()))
        rows.extend(apps)
        installed = [path for path in app_paths((*roots, '/System/Applications', '/Applications/Utilities',
                                                 '/Applications/Setapp'))
                     if path.stem.casefold() not in {'eney', 'setapp'}
                     and not protected_reason(path, home if home in path.parents else path.parent, local)]
        # The new system Applications eligibility applies to bundles only.
        leftover_apps = [replace(row, bucket='fernando') if home not in Path(row.path).parents else row
                         for row in apps if row.group and row.reason != 'app is running']
        rows.extend(leftovers(home, leftover_apps, installed,
                              lambda path: _measure(path, cancel, limit,
                                                    guard),
                              cancel, local))
    if not cancel.is_set():
        report('Large files')
        reader = None
        if sys.platform == 'darwin' and home == Path.home():
            from .cleanup_icloud import metadata
            reader = metadata
        min_bytes, min_age = cleanup_large_files.settings(os.environ)
        large = cleanup_large_files.candidates(home, cancel, local, min_bytes=min_bytes,
                                               min_age=min_age, reader=reader, limit=limit)
        large = {row.path: row for row in large}
        rows = [row for row in rows if row.path not in large]
        rows.extend(large.values())
    if not cancel.is_set():
        report('Time Machine snapshots')
        try:
            output = snapshots() if snapshots else (subprocess.run(
                ['tmutil', 'listlocalsnapshots', '/'], capture_output=True, text=True, timeout=10).stdout
                if sys.platform == 'darwin' else 'Unavailable on this platform')
        except (OSError, subprocess.TimeoutExpired):
            output = 'needs permission or unavailable'
        rows.append(Proposal(str(home), 0, 'Time Machine local snapshots', output.strip(), 'leave_alone', False))
    return sorted(rows, key=lambda row: row.size, reverse=True)


class ScanTask:
    def __init__(self, done, *, timeout=25, progress=None, **kwargs):
        self.cancel = threading.Event()
        finished = threading.Event()
        lock = threading.Lock()

        def complete(rows, available, error, *, timed_out=False):
            with lock:
                if finished.is_set() or self.cancel.is_set():
                    return
                finished.set()
                if timed_out:
                    self.cancel.set()
            timer.cancel()
            done(rows, available, error)

        def report(stage):
            with lock:
                if progress and not finished.is_set() and not self.cancel.is_set():
                    progress(stage)

        def expire():
            complete([], None, f'Storage scan timed out after {timeout:g} seconds. Nothing selected for Trash.',
                     timed_out=True)

        def work():
            try:
                rows = scan(cancel=self.cancel, progress=report, **kwargs)
                if self.cancel.is_set():
                    return
                report('Free space')
                available = free_space(kwargs.get('home') or Path.home())
                complete(rows, available, None)
            except Exception as exc:
                complete([], None, str(exc))

        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        self.thread = threading.Thread(target=work, daemon=True)
        timer.start()
        self.thread.start()
