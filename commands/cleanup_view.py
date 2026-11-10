"""Storage card presentation helpers with no Cocoa dependency."""
import os
from pathlib import Path

from .cleanup_rules import bucket_of

SECTIONS = {
    'safe': 'Safe to delete',
    'your_call': 'Your call',
    'apps': 'Remove apps',
    'left_alone': 'Left alone',
    'fernando': 'Fernando does this',
}


def sections(rows):
    grouped = {key: [] for key in SECTIONS}
    for index, row in enumerate(rows):
        key = row.bucket or bucket_of(row)
        grouped[key].append((index, row))
    return grouped


def scan_home(home=None, environ=None):
    home = Path(home or Path.home()).resolve()
    value = (os.environ if environ is None else environ).get('JEV_CLEANUP_HOME')
    if value:
        path = Path(value).expanduser().resolve()
        if (home / 'Documents/.cos-tmp') in path.parents and path.is_dir():
            return path
    return home
