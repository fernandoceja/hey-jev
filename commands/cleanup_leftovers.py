"""Match Library entries to installed app bundle identifiers."""
import os
from pathlib import Path
import plistlib
import re

from .cleanup_gate import Proposal
from .cleanup_rules import protected_reason

APP_LOCATIONS = ('Application Support', 'Caches', 'Containers', 'Preferences',
                 'Saved Application State', 'HTTPStorages', 'WebKit', 'Logs',
                 'LaunchAgents', 'Group Containers')
ORPHAN_LOCATIONS = ('Application Support', 'Containers', 'Group Containers')
BUNDLE_ID = re.compile(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+){2,}')


def bundle_id(app):
    path = Path(app) / 'Contents/Info.plist'
    try:
        if path.resolve() != path.absolute() or path.stat().st_size > 1024 * 1024:
            return None
        with path.open('rb') as stream:
            value = plistlib.load(stream).get('CFBundleIdentifier')
        return value if isinstance(value, str) and BUNDLE_ID.fullmatch(value) else None
    except (OSError, ValueError, AttributeError):
        return None


def matches(location, name, identifier, app_name):
    if location == 'Group Containers':
        return name.endswith('.' + identifier)
    if location in ('Application Support', 'Logs') and name == app_name:
        return True
    suffix = {'Preferences': '.plist', 'LaunchAgents': '.plist',
              'Saved Application State': '.savedState'}.get(location, '')
    return name == identifier + suffix


def leftovers(home, candidates, installed, measure, cancel, extra=()):
    ids = {app: bundle_id(app) for app in installed}
    known = {identifier for identifier in ids.values() if identifier}
    for location in APP_LOCATIONS:
        root = home / 'Library' / location
        if root.is_symlink() or protected_reason(root, home, extra):
            continue
        try:
            with os.scandir(root) as entries:
                for _, entry in zip(range(5000), entries):
                    if cancel.is_set():
                        return
                    path = Path(entry.path)
                    if entry.is_symlink() or protected_reason(path, home, extra) or entry.name.startswith('com.apple.'):
                        continue
                    groups = [row for row in candidates if ids.get(Path(row.path)) and
                              matches(location, entry.name, ids[Path(row.path)], row.category)]
                    if len(groups) == 1:
                        parent = groups[0]
                        group, bucket = parent.path, parent.bucket
                        reason = f'Associated with {parent.category}'
                    elif (not groups and location in ORPHAN_LOCATIONS
                          and BUNDLE_ID.fullmatch(entry.name) and entry.name not in known
                          and not any(entry.name.endswith('.' + identifier) for identifier in known)):
                        group, bucket = '', 'your_call'
                        reason = 'No installed app with this identifier was found'
                    else:
                        continue
                    size, partial, _, symlink, database = measure(path)
                    if database:
                        reason += '. Contains a database (size only)'
                    if partial or symlink:
                        bucket = 'left_alone'
                    yield Proposal(str(path), size, entry.name, reason, 'ask_first', False,
                                   kind='leftover', bucket=bucket, group=group)
        except OSError:
            continue
