import os
from pathlib import Path
import threading
import time

import pytest
from commands.cleanup_gate import CleanupGate, Proposal
from commands.storage_scan import scan, measure
from orb_character import MoodState


@pytest.fixture(autouse=True)
def fake_system_roots(monkeypatch):
    import commands.cleanup_gate as module
    monkeypatch.setattr(module, 'SYSTEM_PROTECTED', ())


def aged(path):
    os.utime(path, (time.time() - 172800, time.time() - 172800))
    return path


def item(path, safety='safe', **kwargs):
    return Proposal(str(path), 100, 'Cache', 'Review', safety, **kwargs)


def test_approval_audit_undo(tmp_path):
    trash = tmp_path / '.Trash'
    trash.mkdir()
    source = tmp_path / 'cache'
    source.write_text('old')
    aged(source)
    calls = []
    def move(path):
        calls.append(path)
        target = trash / Path(path).name
        os.rename(path, target)
        return target
    gate = CleanupGate(home=tmp_path, trash=move)
    with pytest.raises(ValueError):
        gate.execute()
    card = gate.present([item(source)])
    token = gate.approve_click(card, [0])
    moves = gate.execute(token)
    assert calls == [str(source)]
    assert not source.exists()
    with pytest.raises(ValueError):
        gate.execute(token)
    source.write_text('collision')
    with pytest.raises(FileExistsError):
        gate.undo(moves[0])
    source.rename(tmp_path / 'collision')
    recovered = CleanupGate(home=tmp_path, trash=move)
    recovered.undo(moves[0])
    assert source.read_text() == 'old'
    log = gate.audit.read_text()
    assert 'trashed' in log and 'restored' in log and 'approve' in log


def test_refusals(tmp_path):
    gate = CleanupGate(home=tmp_path)
    recent = tmp_path / 'recent'
    recent.write_text('new')
    assert '24 hours' in gate.refusal(item(recent))
    for relative in ('Developer/hey-jev', 'Documents/Fernando Ceja/Developer/AI-Projects/Jarvis', '.Trash'):
        p = tmp_path / relative
        p.mkdir(parents=True, exist_ok=True)
        aged(p)
        assert gate.refusal(item(p)) == 'protected path'
    for p in ('/System', '/usr', '/bin', '/sbin', '/private', '/Library', '/Applications/Setapp', '/Applications/Eney.app', tmp_path.parent):
        assert gate.refusal(item(p)) == 'protected path'
    aged(recent)
    assert gate.refusal(item(recent, 'leave_alone'))
    link = tmp_path / 'escape'
    link.symlink_to('/usr')
    assert gate.refusal(item(link)) == 'protected path'
    card = gate.present([item(recent, 'leave_alone')])
    with pytest.raises(ValueError):
        gate.approve_click(card, [0])
    card = gate.present([item(recent)])
    token = gate.approve_click(card, [0])
    gate.cancel(card)
    with pytest.raises(ValueError):
        gate.execute(token)


def test_recent_descendant_and_execution_recheck(tmp_path):
    folder = tmp_path / 'cache'
    folder.mkdir()
    child = folder / 'file'
    child.write_text('x')
    aged(folder)
    gate = CleanupGate(home=tmp_path, trash=lambda p: pytest.fail('must refuse'))
    assert gate.refusal(item(folder))
    aged(child)
    card = gate.present([item(folder)])
    token = gate.approve_click(card, [0])
    child.write_text('changed')
    assert '24 hours' in gate.execute(token)[0]


def test_scan_categories_sorting(tmp_path):
    for relative, size in [('Library/Caches/app', 4096), ('Library/Logs', 8192),
                           ('Library/Application Support/MobileSync/Backup', 16384), ('.ollama/models', 32768)]:
        folder = tmp_path / relative
        folder.mkdir(parents=True)
        (folder / 'data').write_bytes(b'x' * size)
    downloads = tmp_path / 'Downloads'
    downloads.mkdir()
    (downloads / 'update.dmg').write_bytes(b'x' * 100)
    old = time.time() - 91 * 86400
    os.utime(downloads / 'update.dmg', (old, old))
    rows = scan(home=tmp_path, snapshots=lambda: 'snapshot-1')
    assert [r.size for r in rows] == sorted([r.size for r in rows], reverse=True)
    by_category = {r.category: r for r in rows}
    assert by_category['User caches'].safety == 'ask_first'
    backup = by_category['iOS/iPadOS backups']
    assert backup.safety == 'ask_first' and backup.irreplaceable
    assert by_category['Time Machine local snapshots'].safety == 'leave_alone'
    assert not by_category['Time Machine local snapshots'].deletable
    assert by_category['Installers / updates'].safety == 'ask_first'
    assert measure(tmp_path, threading.Event(), limit=1)[1]
    cancel = threading.Event()
    cancel.set()
    assert scan(home=tmp_path, cancel=cancel) == []


def test_no_permanent_removal_code():
    for name in ('cleanup_gate.py', 'storage_scan.py', 'storage_scan_ui.py'):
        source = (Path(__file__).parents[1] / 'commands' / name).read_text()
        for forbidden in ('os.remove', 'shutil.rmtree', '.unlink(', 'rm -'):
            assert forbidden not in source


def test_mood_transitions():
    mood = MoodState()
    for status, expected in [('Listening', 'listening'), ('Thinking', 'thinking'), ('Speaking', 'speaking'), ('Ready', 'idle')]:
        assert mood.update(status) == expected
    assert mood.previous == 'speaking'
    assert mood.update('Listening', reduce_motion=True) == 'still'


def test_quick_command_order():
    from mini_bar import quick_commands, quick_command_leaves
    rows = quick_commands(nx_ports=[])
    ids = [r.get('id') for r in rows]
    assert ids.index('storage_scan') == ids.index('rea') + 1
    assert ids.index('websites') < ids.index('nxnative_games') < ids.index('rea')
    assert any(r['id'] == 'storage_scan' for r in quick_command_leaves(rows))


def test_permission_failure_audited(tmp_path):
    source = tmp_path / 'cache'
    source.write_text('old')
    aged(source)
    def refuse(path):
        raise PermissionError('denied')
    gate = CleanupGate(home=tmp_path, trash=refuse)
    token = gate.approve_click(gate.present([item(source)]), [0])
    assert gate.execute(token) == ['needs permission']
    assert source.exists()
    assert 'needs permission' in gate.audit.read_text()


def test_report_only_and_symlink_descendant(tmp_path):
    folder = tmp_path / 'cache'
    folder.mkdir()
    (folder / 'escape').symlink_to('/usr')
    aged(folder)
    gate = CleanupGate(home=tmp_path)
    assert gate.refusal(item(folder)) == 'protected path'
    assert gate.refusal(item(folder, 'ask_first', deletable=False)) == 'report only'


def test_home_field_clean_up_mac_opens_the_scan():
    import re
    from mini_bar import opens_cleanup, submission
    assert opens_cleanup(submission('clean up mac', ''))
    assert opens_cleanup(submission('  Clean Up Mac ', ''))
    assert not opens_cleanup(submission('what time is it', ''))
    assert not opens_cleanup(None)
    source = open('assistant_ui.py', encoding='utf-8').read()
    body = source[source.index('def homeSubmit_'):source.index('def openCaptures_')]
    assert 'if opens_cleanup(plan):' in body and 'start(self)' in body
    assert body.index('opens_cleanup(plan)') < body.index('self.worker_started')


class _Button:
    def __init__(self, title):
        self.title, self.key, self.refuses = title, None, False
    def setKeyEquivalent_(self, key):
        self.key = key
    def setRefusesFirstResponder_(self, value):
        self.refuses = value
    def cell(self):
        return ('cell', self.title)


class _Alert:
    def __init__(self, *titles):
        self._buttons = [_Button(t) for t in titles]
        self.default = self.first = None
        outer = self
        class Window:
            def setDefaultButtonCell_(self, cell): outer.default = cell
            def setInitialFirstResponder_(self, view): outer.first = view
        self._window = Window()
    def buttons(self): return self._buttons
    def window(self): return self._window


def test_confirmation_cards_default_to_cancel():
    from commands.storage_scan_ui import make_cancel_default
    for titles in (('Cancel', 'Move to Trash'), ('Cancel', 'Make cloud-only')):
        alert = _Alert(*titles)
        make_cancel_default(alert)
        cancel, confirm = alert.buttons()
        assert cancel.key == '\r' and confirm.key == '' and confirm.refuses and not cancel.refuses
        assert alert.default == ('cell', 'Cancel') and alert.first is cancel
    source = open('commands/storage_scan_ui.py', encoding='utf-8').read()
    for confirm in ("alert.addButtonWithTitle_('Move to Trash')", "alert.addButtonWithTitle_('Make cloud-only')"):
        at = source.index(confirm)
        assert source[at:].split('runModal', 1)[0].count('make_cancel_default(alert)') == 1


def test_row_details_wrap_instead_of_clipping():
    source = open('commands/storage_scan_ui.py', encoding='utf-8').read()
    assert 'wrappingLabelWithString_' in source and 'def detail_label' in source
    assert "self.detail_label(f'{row.path}\\n{row.reason}'" in source
    assert "self.label(f'{row.path}" not in source


def test_scan_timeout_finishes_once_even_when_worker_is_stuck(monkeypatch):
    from commands import storage_scan

    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    results = []
    stages = []

    def scan_stuck(*, cancel, progress):
        progress('Downloads')
        entered.set()
        release.wait(5)
        assert cancel.is_set()
        progress('Late progress')
        return ['late result']

    def done(*result):
        results.append(result)
        finished.set()

    monkeypatch.setattr(storage_scan, 'scan', scan_stuck)
    task = storage_scan.ScanTask(done, timeout=0.25, progress=stages.append)
    try:
        assert entered.wait(2)
        assert finished.wait(2)
        assert task.thread.is_alive()
        assert results == [([], None, 'Storage scan timed out after 0.25 seconds. Nothing selected for Trash.')]
    finally:
        release.set()
        task.thread.join(2)
    assert len(results) == 1
    assert stages == ['Downloads']


def test_scan_skips_mobile_documents_dataless_and_jarvis(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from commands import cleanup_rules

    cloud = tmp_path / 'Library/Mobile Documents'
    dataless = tmp_path / 'Documents/placeholder'
    jarvis = tmp_path / 'Documents/Jarvis'
    for folder in (cloud, dataless, jarvis):
        folder.mkdir(parents=True)
    original_lstat = Path.lstat
    original_scandir = os.scandir

    def lstat(path):
        info = original_lstat(path)
        if path == dataless:
            return Mock(wraps=info, st_mode=info.st_mode, st_flags=cleanup_rules.SF_DATALESS)
        return info

    def scandir(path):
        assert Path(path) not in (cloud, dataless, jarvis)
        return original_scandir(path)

    monkeypatch.setattr(Path, 'lstat', lstat)
    monkeypatch.setattr(os, 'scandir', scandir)
    stages = []
    rows = scan(home=tmp_path, paths={'User caches': cloud, 'Downloads': dataless},
                snapshots=lambda: '', progress=stages.append)
    assert 'Documents and Desktop' in stages and 'Large files' in stages
    assert not {str(cloud), str(dataless), str(jarvis)} & {row.path for row in rows}
