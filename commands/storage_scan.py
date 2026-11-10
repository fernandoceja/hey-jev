"""Bounded read-only storage measurements. Cocoa is loaded only on macOS."""
import os
import stat
import time
from pathlib import Path
import subprocess
import sys
import threading
from . import tidy_downloads
from .cleanup_gate import Proposal
from .cleanup_rules import DATABASE_SUFFIXES, load_protected, protected_reason

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
    if folder.is_symlink() or protected_reason(folder, home, local):
        return
    files, _ = tidy_downloads.scan_folder(folder, max_files=limit)
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


def scan(home=None, paths=None, cancel=None, snapshots=None, limit=100000):
    home = Path(home or Path.home())
    cancel = cancel or threading.Event()
    paths = paths or {}
    rows = []
    local = load_protected(home / "Library/Application Support/Hey Jev/cleanup-protected.json")
    for category, relative, safety, deletable, irreplaceable in LOCATIONS:
        if cancel.is_set():
            break
        path = Path(paths.get(category, home / relative))
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
            if not target.exists() or target.is_symlink():
                continue
            guard = lambda item: protected_reason(item, home, local)
            protected = guard(target)
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
            elif newest > time.time() - 86400:
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
        rows.extend(download_rows(Path(paths.get('Downloads', home / 'Downloads')), home, local, cancel, limit))
    for relative in ('Library/iTunes/Software Updates', 'Library/iTunes/iPhone Software Updates', 'Library/iTunes/iPad Software Updates'):
        folder = Path(paths.get(relative, home / relative))
        if folder.is_symlink() or protected_reason(folder, home, local):
            continue
        # Bounded traversal for installer files; no directory symlink traversal.
        count = 0
        for root, dirs, files in os.walk(folder, followlinks=False):
            count += 1
            if count > limit or cancel.is_set():
                break
            dirs[:]  = [d for d in dirs if not (Path(root) / d).is_symlink() and not protected_reason(Path(root) / d, home, local)]
            for name in files:
                count += 1
                if count > limit or cancel.is_set():
                    break
                p = Path(root) / name
                if p.suffix.lower() in ('.dmg', '.pkg', '.ipsw') and not p.is_symlink() and not protected_reason(p, home, local):
                    size, partial = measure(p, cancel, limit)
                    rows.append(Proposal(str(p), size, 'Installers / updates', 'Installer; review first', 'ask_first', not partial))
            if count > limit or cancel.is_set():
                break
    if not cancel.is_set() and sys.platform == 'darwin' and home == Path.home():
        from .cleanup_apps import running_apps, unused_apps
        running = running_apps()
        rows.extend(unused_apps(home, (Path('/Applications'), home / 'Applications'),
                               lambda path: measure(path, cancel, limit), cancel, local, running=running))
    if not cancel.is_set():
        try:
            output = snapshots() if snapshots else (subprocess.run(
                ['tmutil', 'listlocalsnapshots', '/'], capture_output=True, text=True, timeout=10).stdout
                if sys.platform == 'darwin' else 'Unavailable on this platform')
        except (OSError, subprocess.TimeoutExpired):
            output = 'needs permission or unavailable'
        rows.append(Proposal(str(home), 0, 'Time Machine local snapshots', output.strip(), 'leave_alone', False))
    return sorted(rows, key=lambda row: row.size, reverse=True)


class ScanTask:
    def __init__(self, done, **kwargs):
        self.cancel = threading.Event()
        def work():
            try:
                rows = scan(cancel=self.cancel, **kwargs)
                available = free_space(kwargs.get('home') or Path.home())
                done(rows, available, None)
            except Exception as exc:
                done([], None, str(exc))
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
