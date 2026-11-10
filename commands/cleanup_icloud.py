"""Metadata-only discovery of local iCloud copies."""
import os
from pathlib import Path
import stat
import time

from .cleanup_gate import Proposal
from .cleanup_rules import protected_reason

MIN_BYTES = 50 * 1024 * 1024
IDLE_SECONDS = 30 * 86400


def metadata(path):
    import Foundation as cocoa
    names = ('IsUbiquitousItem', 'UbiquitousItemIsUploaded', 'UbiquitousItemIsUploading',
             'UbiquitousItemDownloadingStatus', 'UbiquitousItemHasUnresolvedConflicts')
    keys = [getattr(cocoa, 'NSURL' + name + 'Key') for name in names]
    values, _ = cocoa.NSURL.fileURLWithPath_(str(path)).resourceValuesForKeys_error_(keys, None)
    if values is None:
        return {}
    result = dict(zip(names, (values.get(key) for key in keys)))
    status = result['UbiquitousItemDownloadingStatus']
    result['current'] = status == cocoa.NSURLUbiquitousItemDownloadingStatusCurrent
    result['cloud_only'] = status == cocoa.NSURLUbiquitousItemDownloadingStatusNotDownloaded
    return result


def evictable(info, st, now):
    return (bool(info.get('IsUbiquitousItem')) and bool(info.get('UbiquitousItemIsUploaded'))
            and info.get('UbiquitousItemIsUploading') == False
            and info.get('UbiquitousItemHasUnresolvedConflicts') == False
            and info.get('current') is True and st.st_size >= MIN_BYTES
            and now - max(st.st_mtime, st.st_atime) >= IDLE_SECONDS)


def candidates(home, cancel, extra=(), reader=metadata, limit=100000):
    roots = [home / 'Library/Mobile Documents/com~apple~CloudDocs']
    for root in (home / 'Desktop', home / 'Documents'):
        if not root.is_symlink() and root.is_dir() and reader(root).get('IsUbiquitousItem'):
            roots.append(root)
    pending = list(roots)
    rows = []
    now = time.time()
    examined = 0
    while pending and not cancel.is_set() and examined < limit:
        path = pending.pop()
        examined += 1
        if path.name.startswith('.') or protected_reason(path, home, extra):
            continue
        try:
            st = path.lstat()
            if stat.S_ISDIR(st.st_mode) and not path.suffix:
                with os.scandir(path) as entries:
                    for entry in entries:
                        if cancel.is_set() or examined + len(pending) >= limit:
                            break
                        pending.append(Path(entry.path))
            elif stat.S_ISREG(st.st_mode) and st.st_size >= MIN_BYTES:
                info = reader(path)
                if evictable(info, st, now):
                    rows.append(Proposal(str(path), st.st_size, 'iCloud',
                                         'Already in iCloud. Making it cloud-only frees local space.',
                                         'ask_first', False, kind='icloud', bucket='your_call'))
                elif info.get('IsUbiquitousItem') and info.get('UbiquitousItemIsUploading'):
                    rows.append(Proposal(str(path), st.st_size, 'iCloud', 'Still uploading',
                                         'ask_first', False, kind='icloud', bucket='your_call'))
        except OSError:
            continue
    return sorted(rows, key=lambda row: row.size, reverse=True)[:200]
