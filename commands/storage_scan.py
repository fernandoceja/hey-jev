"""Bounded read-only storage measurements. Cocoa is loaded only on macOS."""
import os
import re
from pathlib import Path
import subprocess
import sys
import threading
from .cleanup_gate import Proposal

# category, relative path, safety, deletable, irreplaceable
LOCATIONS = (
    ('User caches', 'Library/Caches', 'safe', True, False),
    ('User logs', 'Library/Logs', 'safe', True, False),
    ('Xcode DerivedData', 'Library/Developer/Xcode/DerivedData', 'safe', True, False),
    ('Xcode Archives', 'Library/Developer/Xcode/Archives', 'ask_first', True, False),
    ('iOS DeviceSupport', 'Library/Developer/Xcode/iOS DeviceSupport', 'safe', True, False),
    ('CoreSimulator', 'Library/Developer/CoreSimulator', 'leave_alone', False, False),
    ('iOS/iPadOS backups', 'Library/Application Support/MobileSync/Backup', 'ask_first', True, True),
    ('Mail attachments', 'Library/Containers/com.apple.mail/Data/Library/Mail Downloads', 'ask_first', False, False),
    ('Mail Downloads', 'Library/Mail Downloads', 'ask_first', False, False),
    ('Messages attachments', 'Library/Messages/Attachments', 'ask_first', False, False),
    ('Hugging Face models', '.cache/huggingface', 'leave_alone', False, False),
    ('Ollama models', '.ollama/models', 'ask_first', True, False),
    ('Trash', '.Trash', 'leave_alone', False, False),
)


def measure(path, cancel, limit=100000):
    """Allocated bytes where available; partial measurements are explicitly labelled."""
    total, count, partial = 0, 0, False
    pending = [Path(path)]
    while pending and not cancel.is_set():
        p = pending.pop()
        count += 1
        if count > limit:
            partial = True
            break
        try:
            st = p.lstat()
            if p.is_symlink():
                continue
            total += getattr(st, 'st_blocks', (st.st_size + 511) // 512) * 512
            if p.is_dir():
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
    return total, partial or cancel.is_set()


def free_space(home):
    if sys.platform != 'darwin':
        return None
    from Foundation import NSURL, NSURLVolumeAvailableCapacityForImportantUsageKey
    values, error = NSURL.fileURLWithPath_(str(home)).resourceValuesForKeys_error_(
        [NSURLVolumeAvailableCapacityForImportantUsageKey], None)
    return values.get(NSURLVolumeAvailableCapacityForImportantUsageKey) if values else None


def scan(home=None, paths=None, cancel=None, snapshots=None, limit=100000):
    home = Path(home or Path.home())
    cancel = cancel or threading.Event()
    paths = paths or {}
    rows = []
    for category, relative, safety, deletable, irreplaceable in LOCATIONS:
        if cancel.is_set():
            break
        path = Path(paths.get(category, home / relative))
        targets = [path]
        if category == 'User caches' and path.is_dir() and not path.is_symlink():
            try:
                with os.scandir(path) as entries:
                    targets = [Path(e.path) for _, e in zip(range(1000), entries)]
            except PermissionError:
                pass
        if category == 'Xcode DerivedData' and path.is_dir() and not path.is_symlink():
            try:
                with os.scandir(path) as entries:
                    targets = [Path(e.path) for e in entries if e.is_dir(follow_symlinks=False)]
            except PermissionError:
                targets = [path]
        for target in targets:
            if not target.exists() or target.is_symlink():
                continue
            size, partial = measure(target, cancel, limit)
            reason = 'Partial measurement; needs permission or scan limit reached' if partial else 'Review before moving to Trash'
            effective = safety
            allowed = deletable and not partial
            from .cleanup_rules import protected_reason, load_protected
            local = load_protected(home / 'Library/Application Support/Hey Jev/cleanup-protected.json')
            if protected_reason(target, home, local):
                effective, allowed = 'leave_alone', False
            rows.append(Proposal(str(target), size, category, reason, effective,
                                 allowed, irreplaceable))
    for relative in ('Downloads', 'Library/iTunes/Software Updates', 'Library/iTunes/iPhone Software Updates', 'Library/iTunes/iPad Software Updates'):
        folder = Path(paths.get(relative, home / relative))
        # Bounded traversal for installer files; no directory symlink traversal.
        count = 0
        for root, dirs, files in os.walk(folder, followlinks=False):
            count += 1
            if count > limit or cancel.is_set():
                break
            dirs[:]  = [d for d in dirs if not (Path(root) / d).is_symlink()]
            for name in files:
                count += 1
                if count > limit or cancel.is_set():
                    break
                p = Path(root) / name
                if p.suffix.lower() in ('.dmg', '.pkg', '.ipsw') and not p.is_symlink():
                    size, partial = measure(p, cancel, limit)
                    rows.append(Proposal(str(p), size, 'Installers / updates', 'Installer; review first', 'ask_first', not partial))
            if count > limit or cancel.is_set():
                break
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
