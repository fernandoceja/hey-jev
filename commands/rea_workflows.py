"""Local REA intent, preset and durable wishlist helpers. No job starts here."""
import difflib
import json
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path

WISHLIST = Path('~/Documents/Fernando Ceja/Developer/AI-Projects/REA/wishlist.json').expanduser()
_LOCK = threading.RLock()


def intent(text):
    patterns = ((r'study how (.+?) does (.+)', 'research', True),
                (r'research (.+?) in (.+)', 'research', False),
                (r'replicate (.+?) from (.+)', 'replicate', False),
                (r'add (.+?) from (.+?) to (?:the )?REA wishlist', 'wishlist', False))
    for pattern, mode, reverse in patterns:
        match = re.fullmatch(pattern, text.strip().rstrip('.'), re.I)
        if match:
            a, b = match.groups()
            return dict(mode=mode, feature=b if reverse else a, app=a if reverse else b)
    return None


def resolve_app(name, roots=None):
    roots = roots or (Path('/Applications'), Path('~/Applications').expanduser())
    apps = sorted((p for root in roots for p in Path(root).glob('*.app') if p.is_dir()), key=str)
    key = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
    scores = sorted(((difflib.SequenceMatcher(None, key(name), key(p.stem)).ratio(), p) for p in apps), key=lambda pair: pair[0], reverse=True)
    if not scores or scores[0][0] < .65 or (len(scores) > 1 and scores[0][0] == scores[1][0]):
        return None
    return scores[0][1]


def git(repo, *args, run=subprocess.run):
    result = run(['git', '-C', str(repo), *args], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('Git failed: ' + ' '.join(args[:2]))
    return result.stdout.strip()


def presets(developer=None, run=subprocess.run):
    developer = Path(developer or '~/Developer').expanduser()
    found = [(label, developer / name) for label, name in (('Jev', 'hey-jev'), ('NXNative', 'nxnative')) if (developer / name).is_dir()]
    for path in sorted(developer.glob('*')):
        if not path.is_dir() or path.is_symlink():
            continue
        try:
            remote = git(path, 'remote', 'get-url', 'origin', run=run)
        except (ValueError, OSError):
            continue
        if re.fullmatch(r'(?:https://github.com/|git@github.com:)fernandoceja/Zoe[-s]*Princess[-_]Academy(?:\.git)?', remote, re.I):
            found.append(('Zoe Princess Academy', path))
            break
    return found


def diff_context(repo, run=subprocess.run):
    chunks = []
    for args in (('diff', 'HEAD~1', '--stat'), ('diff', 'HEAD~1'), ('log', '-5', '--oneline')):
        try:
            chunks.append(git(repo, *args, run=run))
        except ValueError:
            chunks.append('Unavailable (new or shallow repository): ' + ' '.join(args))
    return '\n\n'.join(chunks)


class Wishlist:
    fields = {'id', 'feature', 'source_app', 'notes', 'added', 'status', 'request_folder'}

    def __init__(self, path=WISHLIST, requests=None):
        from .rea_study import ROOT
        self.path = Path(path)
        self.requests = Path(requests or ROOT).resolve()

    def validate(self, rows):
        if not isinstance(rows, list):
            raise ValueError('Wishlist must be a list.')
        ids = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != self.fields or any(not isinstance(v, str) for v in row.values()):
                raise ValueError('Invalid wishlist schema.')
            if not re.fullmatch(r'[a-f0-9]{32}', row['id']) or row['id'] in ids or not row['feature'].strip() or row['status'] not in ('idea', 'planned', 'built'):
                raise ValueError('Invalid wishlist entry.')
            ids.add(row['id'])
            datetime.fromisoformat(row['added'])
            if row['request_folder']:
                path = Path(row['request_folder'])
                if not path.is_absolute() or path.is_symlink() or path.resolve().parent != self.requests:
                    raise ValueError('Unsafe request folder.')
        return rows

    def read(self):
        if self.path.is_symlink() or self.path.absolute() != self.path.resolve():
            raise ValueError('Linked wishlist refused.')
        if not self.path.exists():
            return []
        try:
            return self.validate(json.loads(self.path.read_text(encoding='utf-8')))
        except (ValueError, TypeError):
            backup = self.path.with_name(self.path.name + '.corrupt-' + uuid.uuid4().hex)
            with backup.open('xb') as stream:
                stream.write(self.path.read_bytes())
            raise ValueError('Wishlist corrupt; preserved at ' + str(backup))

    def change(self, action, id_=None, **values):
        with _LOCK:
            rows = self.read()
            if action == 'add':
                row = dict(id=uuid.uuid4().hex, feature=values['feature'], source_app=values.get('source_app', ''), notes=values.get('notes', ''), added=datetime.now().astimezone().isoformat(), status='idea', request_folder='')
                rows.append(row)
            else:
                row = next((r for r in rows if r['id'] == id_), None)
                if row is None:
                    raise ValueError('Wishlist entry missing.')
                if action == 'remove':
                    rows.remove(row)
                elif action == 'update' and set(values) <= {'status', 'request_folder'}:
                    row.update(values)
                else:
                    raise ValueError('Invalid wishlist operation.')
            self.validate(rows)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name('.wishlist-' + uuid.uuid4().hex)
            try:
                with temporary.open('x', encoding='utf-8') as stream:
                    json.dump(rows, stream, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            return row
