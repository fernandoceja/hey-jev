import os
from pathlib import Path
import plistlib
import threading
from types import SimpleNamespace

from commands.cleanup_apps import unused_apps
from commands.cleanup_gate import CleanupGate
from commands.cleanup_rules import CLAUDE_HANDLER_ID


def setup_apps(tmp_path, names):
    home, root = tmp_path / 'home', tmp_path / 'Applications'
    home.mkdir()
    for name in names:
        app = root / name
        info = app / 'Contents/Info.plist'
        info.parent.mkdir(parents=True)
        identifier = CLAUDE_HANDLER_ID if name == 'Protected.app' else 'org.example.testapp'
        info.write_bytes(plistlib.dumps({'CFBundleIdentifier': identifier}))
        for path in (info, info.parent, app):
            os.utime(path, (1000, 1000))
    return home, root


def rows(home, root, running=(), now=100000):
    return list(unused_apps(home, [root], lambda _: (123, False), threading.Event(),
                            runner=lambda *a, **k: SimpleNamespace(stdout='(null)'),
                            running=running, now=now, applications=root))


def test_app_review_requires_current_owner_nonrunning_and_unprotected(tmp_path, monkeypatch):
    home, root = setup_apps(tmp_path, ['Eligible.app', 'Root.app', 'Running.app',
                                        'Setapp/Example.app', 'Protected.app'])
    lstat = Path.lstat

    def ownership(path, *args, **kwargs):
        info = lstat(path, *args, **kwargs)
        if path == root / 'Root.app':
            return SimpleNamespace(st_mode=info.st_mode, st_uid=os.getuid() + 1)
        return info

    monkeypatch.setattr(Path, 'lstat', ownership)
    by_path = {r.path: r for r in rows(home, root, {root / 'Running.app'})}
    eligible = by_path[str(root / 'Eligible.app')]
    assert eligible.deletable and eligible.bucket == 'apps' and eligible.safety == 'ask_first'
    for name, reason in [('Root.app', 'administrator'), ('Running.app', 'running'),
                         ('Setapp/Example.app', 'Setapp'), ('Protected.app', 'Protected')]:
        row = by_path[str(root / name)]
        assert not row.deletable and row.bucket == 'fernando' and reason in row.reason


def test_external_app_failed_move_and_successful_undo(tmp_path):
    home, root = setup_apps(tmp_path, ['Eligible.app'])
    app = root / 'Eligible.app'
    trash = home / '.Trash'
    trash.mkdir()
    row = rows(home, root)[0]

    def fail(_):
        raise PermissionError('denied')

    gate = CleanupGate(home=home, trash=fail, applications=root,
                       now=lambda: 100000, protected_roots=())
    token = gate.approve_click(gate.present([row]), [0])
    assert gate.execute(token) == ['needs permission']
    assert app.is_dir() and not list(trash.iterdir())

    def move(path):
        destination = trash / app.name
        Path(path).rename(destination)
        return destination

    gate.trash = move
    token = gate.approve_click(gate.present([row]), [0])
    result = gate.execute(token)
    assert not app.exists() and (trash / app.name).is_dir()
    gate.undo(result[0])
    assert app.is_dir() and not list(trash.iterdir())


def test_external_app_recent_bundle_stays_disabled(tmp_path):
    home, root = setup_apps(tmp_path, ['Recent.app'])
    row = rows(home, root, now=2000)[0]
    assert not row.deletable and 'last 24 hours' in row.reason


def test_xcode_named_apps_are_never_offered_anywhere(tmp_path):
    from commands.cleanup_apps import app_refusal
    home, root = setup_apps(tmp_path, ['Xcode-beta.app'])
    mine = home / 'Applications'
    for name in ('xcode.app', 'xcode-beta.app'):
        (mine / name / 'Contents').mkdir(parents=True)
        os.utime(mine / name, (1000, 1000))
    found = list(unused_apps(home, [root, mine], lambda _: (123, False), threading.Event(),
                             runner=lambda *a, **k: SimpleNamespace(stdout='(null)'),
                             now=100000, applications=root))
    assert not [r for r in found if r.deletable and 'xcode' in r.path.casefold()]
    for path in (mine / 'xcode.app', mine / 'xcode-beta.app', root / 'Xcode-beta.app'):
        assert app_refusal(path, home, (), set(), applications=root) == 'protected app'
