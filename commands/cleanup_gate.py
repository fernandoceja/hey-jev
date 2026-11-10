"""Single-card, single-use consent for reversible Trash operations only."""
import json
import os
from pathlib import Path
import secrets
import threading
import time
from dataclasses import dataclass
from .cleanup_rules import fernando_reason, protected_reason, load_protected

SYSTEM_PROTECTED = tuple(Path(p) for p in ('/System', '/usr', '/bin', '/sbin', '/private', '/Library', '/Applications/Setapp', '/Applications/Eney.app'))


@dataclass(frozen=True)
class Proposal:
    path: str
    size: int
    category: str
    reason: str
    safety: str
    deletable: bool = True
    irreplaceable: bool = False
    kind: str = 'file'
    bucket: str = ''
    detail: str = ''
    group: str = ''


def mac_trash(path):
    from Foundation import NSFileManager, NSURL
    ok, url, error = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
        NSURL.fileURLWithPath_(str(path)), None, None)
    if not ok:
        raise PermissionError(str(error))
    return str(url.path())


class CleanupGate:
    def __init__(self, home=None, audit=None, trash=None, now=time.time, protected_roots=None):
        self.home = Path(home or Path.home()).resolve()
        self.audit = Path(audit or self.home / 'Library/Application Support/Hey Jev/cleanup-audit.jsonl')
        self.trash = trash or mac_trash
        self.now = now
        self.protected_roots = SYSTEM_PROTECTED if protected_roots is None else tuple(map(Path, protected_roots))
        self.cards = {}
        self.tokens = {}
        self.moves = {}
        self.lock = threading.RLock()
        # Recover completed moves from the JSONL journal after an app restart.
        if self.audit.exists():
            with self.audit.open(encoding='utf8') as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                        if record.get('action') == 'trashed':
                            self.moves[record['move']] = (record['path'], record['trash'])
                        elif record.get('action') == 'restored':
                            self.moves.pop(record['move'], None)
                    except (ValueError, KeyError):
                        continue

    def log(self, action, **fields):
        self.audit.parent.mkdir(parents=True, exist_ok=True)
        with self.audit.open('a', encoding='utf8') as stream:
            stream.write(json.dumps(dict(time=self.now(), action=action, **fields)) + '\n')

    def refusal(self, item):
        if item.safety not in ('safe', 'ask_first') or not item.deletable:
            return 'report only'
        path = Path(item.path).absolute()
        if item.kind == 'app' and self.trash is mac_trash:
            from .cleanup_apps import running_apps
            if path.resolve() in running_apps():
                return 'Quit the app first'
        local_rules = load_protected(self.home / 'Library/Application Support/Hey Jev/cleanup-protected.json')
        reason = protected_reason(path, self.home, local_rules)
        if reason:
            return 'protected path'
        protected = [self.home / p for p in ('.Trash', 'Developer/hey-jev')]
        protected += list(self.protected_roots)
        def inside(p, root):
            return p == root or root in p.parents
        def check(p):
            if protected_reason(p, self.home, local_rules):
                return 'protected path'
            real = p.resolve()
            if not inside(real, self.home) or real == self.home:
                return 'protected path'
            if any(inside(real, root) or inside(root, real) for root in protected):
                return 'protected path'
            if fernando_reason(p, self.home, uid=os.getuid()):
                return 'needs permission'
            if self.now() - p.stat().st_mtime < 86400:
                return 'modified in the last 24 hours'
        try:
            error = check(path)
            if error:
                return error
            count = 0
            if path.is_dir():
                for root, dirs, files in os.walk(path, followlinks=False, onerror=lambda e: (_ for _ in ()).throw(e)):
                    for name in dirs + files:
                        count += 1
                        if count > 100000:
                            return 'safety check limit reached'
                        child = Path(root) / name
                        error = check(child)
                        if error:
                            return error
                        if child.is_symlink():
                            return 'symlink requires separate review'
            if path.is_symlink():
                return 'symlink requires separate review'
        except PermissionError:
            return 'needs permission'
        except OSError:
            return 'path unavailable'
        return None

    def present(self, items):
        with self.lock:
            self.cards.clear()
            self.tokens.clear()
            card = secrets.token_urlsafe(24)
            self.cards[card] = tuple(items)
            self.log('propose', card=card, items=[vars(i) for i in items])
            return card

    def cancel(self, card):
        with self.lock:
            self.cards.pop(card, None)
            self.tokens = {k: v for k, v in self.tokens.items() if v[0] != card}
            self.log('cancel', card=card)

    def approve_click(self, card, indices, *, skip_refused=False):
        """Called only by the visible card's approval button handler."""
        with self.lock:
            items = self.cards.get(card)
            if items is None:
                raise ValueError('approval card is no longer showing')
            if any(not isinstance(i, int) or i < 0 or i >= len(items) for i in indices):
                raise ValueError('invalid card selection')
            selected = tuple(items[i] for i in sorted(set(indices)))
            apps = {item.group for item in selected if item.kind == 'app'}
            if any(item.kind == 'leftover' and item.group and item.group not in apps for item in selected):
                raise ValueError('Select the associated app before its leftovers')
            selected = tuple(sorted(selected, key=lambda item: item.kind != 'app'))
            for item in (() if skip_refused else selected):
                reason = self.refusal(item)
                if reason:
                    self.log('refuse', path=item.path, reason=reason)
                    raise ValueError(reason)
            token = secrets.token_urlsafe(32)
            self.tokens[token] = (card, selected)
            self.log('approve', card=card, paths=[i.path for i in selected])
            return token

    def execute(self, token=None):
        with self.lock:
            if token not in self.tokens:
                raise ValueError('explicit card approval required')
            card, items = self.tokens.pop(token)
            if self.cards.pop(card, None) is None:
                raise ValueError('approval expired')
            self.log('run_started', card=card, count=len(items))
            results = []
            successful_apps = set()
            for item in items:
                if item.kind == 'leftover' and item.group and item.group not in successful_apps:
                    error = 'App was not moved; leftover skipped'
                else:
                    error = self.refusal(item)
                if error:
                    self.log('refuse', path=item.path, reason=error)
                    results.append(error)
                    continue
                original = str(Path(item.path).absolute())
                # Persist intent before changing the filesystem.
                self.log('trash_requested', path=original)
                try:
                    destination = self.trash(original)
                except PermissionError:
                    self.log('refuse', path=original, reason='needs permission')
                    results.append('needs permission')
                    continue
                except OSError as exc:
                    self.log('error', path=original, reason=str(exc))
                    results.append(str(exc))
                    continue
                move = secrets.token_urlsafe(24)
                self.moves[move] = (original, str(destination))
                self.log('trashed', move=move, path=original, trash=str(destination))
                results.append(move)
                if item.kind == 'app':
                    successful_apps.add(item.group)
            self.log('run_finished', card=card, results=results)
            return results

    def undo(self, move):
        with self.lock:
            original, destination = self.moves[move]
            self.log('undo_requested', move=move)
            resolved = Path(original).resolve()
            if self.home not in resolved.parents or Path(original).parent.resolve() != Path(original).parent:
                self.log('undo_refused', move=move, reason='original path changed or outside home')
                raise ValueError('original path changed or outside home')
            if os.path.lexists(original):
                self.log('undo_refused', move=move, reason='destination exists')
                raise FileExistsError('Undo refuses to overwrite')
            # Foundation's move refuses to overwrite; tests inject a rename adapter.
            if self.trash is mac_trash:
                from Foundation import NSFileManager
                ok, error = NSFileManager.defaultManager().moveItemAtPath_toPath_error_(destination, original, None)
                if not ok:
                    self.log('undo_refused', move=move, reason=str(error))
                    raise PermissionError('needs permission')
            else:
                os.rename(destination, original)
            self.log('restored', move=move, path=original, trash=destination)
            del self.moves[move]
