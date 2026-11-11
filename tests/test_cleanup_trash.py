import errno
import os
from pathlib import Path

import pytest

from commands.cleanup_gate import CleanupGate
from commands.cleanup_trash import SOURCE_ACCESS, TRASH_ACCESS, TrashAccessError, recycle_result, summary
from commands.storage_scan import scan


class CocoaError:
    def __init__(self, domain, code, underlying=None):
        self._domain = domain
        self._code = code
        self._underlying = underlying

    def domain(self):
        return self._domain

    def code(self):
        return self._code

    def userInfo(self):
        return {'NSUnderlyingError': self._underlying}

    def localizedDescription(self):
        return 'Finder could not move the file'


def test_recycle_returns_actual_destination_and_preserves_error_type():
    class URL:
        def path(self):
            return '/Trash/renamed item'

    source = object()
    assert recycle_result({source: URL()}, source, None) == '/Trash/renamed item'
    permission = CocoaError('NSPOSIXErrorDomain', errno.EPERM)
    wrapped = CocoaError('NSCocoaErrorDomain', 512, permission)
    with pytest.raises(TrashAccessError, match='Files and Folders'):
        recycle_result({}, source, wrapped)
    with pytest.raises(OSError, match='Finder could not move') as exc:
        recycle_result({}, source, CocoaError('NSPOSIXErrorDomain', errno.ENOENT))
    assert not isinstance(exc.value, PermissionError)


def test_trash_summary_permission_and_count(tmp_path, monkeypatch):
    trash = tmp_path / '.Trash'
    trash.mkdir()
    (trash / 'fixture').touch()
    assert summary(trash, lambda _: (1048576, False)) == ('1 items in home Trash · 1.0 MB', False)

    def denied_scan(_):
        raise PermissionError(errno.EPERM, 'Operation not permitted')

    monkeypatch.setattr(os, 'scandir', denied_scan)
    assert summary(trash, lambda _: pytest.fail('no access')) == (TRASH_ACCESS, True)


def test_scan_and_gate_agree_on_recent_descendant(tmp_path):
    cache = tmp_path / 'Library/Caches/fixture'
    cache.mkdir(parents=True)
    child = cache / 'content'
    child.touch()
    now = child.stat().st_mtime
    old = now - 2 * 86400
    os.utime(cache, (old, old))
    gate = CleanupGate(home=tmp_path, protected_roots=(), now=lambda: now)

    def candidate():
        return next(row for row in scan(home=tmp_path, snapshots=lambda: '')
                    if Path(row.path) == cache)

    fresh = candidate()
    assert fresh.safety != 'safe' and not fresh.deletable
    os.utime(child, (old, old))
    safe = candidate()
    assert safe.safety == 'safe' and gate.refusal(safe) is None
    os.utime(child, (now, now))
    assert 'last 24 hours' in gate.refusal(safe)


def test_gate_reports_actionable_finder_denial(tmp_path):
    path = tmp_path / 'fixture'
    path.touch()
    old = path.stat().st_mtime - 2 * 86400
    os.utime(path, (old, old))

    def reject(_):
        raise TrashAccessError(SOURCE_ACCESS)

    from commands.cleanup_gate import Proposal
    gate = CleanupGate(home=tmp_path, protected_roots=(), trash=reject)
    token = gate.approve_click(gate.present([Proposal(str(path), 0, 'Fixture', '', 'safe')]), [0])
    assert gate.execute(token) == [SOURCE_ACCESS]
    assert path.exists() and not gate.moves
