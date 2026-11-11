import os
from pathlib import Path
import threading

import pytest

from commands.cleanup_gate import CleanupGate
from commands.cleanup_summaries import BUCKET, summary_rows
from commands.cleanup_view import SECTIONS, sections
from commands.storage_scan import scan


@pytest.fixture(autouse=True)
def fake_system_roots(monkeypatch):
    import commands.cleanup_gate as module
    monkeypatch.setattr(module, 'SYSTEM_PROTECTED', ())


def make_home(tmp_path):
    home = tmp_path / 'home'
    (home / 'Documents/Taxes').mkdir(parents=True)
    (home / 'Documents/a.txt').write_text('hello')
    (home / 'Documents/.DS_Store').write_text('x')
    (home / 'Desktop').mkdir()
    (home / 'Desktop/shot.png').write_bytes(b'0' * 2048)
    return home


def test_summary_rows_report_counts_and_sizes_only(tmp_path):
    home = make_home(tmp_path)
    rows = {r.category: r for r in summary_rows(home, lambda p: (4096, False), threading.Event())}
    docs, desk = rows['Documents summary'], rows['Desktop summary']
    assert '2 items' in docs.reason and '1 items' in desk.reason
    assert docs.size == 4096 and 'Report only' in docs.reason
    for row in rows.values():
        assert not row.deletable and row.safety == 'leave_alone' and row.bucket == BUCKET


def test_partial_and_unreadable_are_labelled(tmp_path):
    home = make_home(tmp_path)
    rows = {r.category: r for r in summary_rows(home, lambda p: (10, True), threading.Event())}
    assert 'excludes protected or unreadable' in rows['Documents summary'].reason
    os.chmod(home / 'Desktop', 0)
    try:
        rows = {r.category: r for r in summary_rows(home, lambda p: (10, False), threading.Event())}
        assert 'unreadable' in rows['Desktop summary'].reason and rows['Desktop summary'].size == 0
    finally:
        os.chmod(home / 'Desktop', 0o700)


def test_symlinked_or_missing_folders_are_skipped(tmp_path):
    home = tmp_path / 'home'
    (home / 'elsewhere').mkdir(parents=True)
    (home / 'Documents').symlink_to(home / 'elsewhere', target_is_directory=True)
    assert list(summary_rows(home, lambda p: (1, False), threading.Event())) == []


def test_scan_includes_summaries_and_gate_refuses_them(tmp_path):
    home = make_home(tmp_path)
    rows = scan(home=home, limit=1000, snapshots=lambda: 'none')
    summaries = [r for r in rows if r.bucket == BUCKET]
    assert {r.category for r in summaries} == {'Documents summary', 'Desktop summary'}
    assert BUCKET in SECTIONS
    grouped = sections(rows)
    assert len(grouped[BUCKET]) == 2 and not any(r.deletable for _, r in grouped[BUCKET])
    gate = CleanupGate(home=home, trash=lambda path: pytest.fail('moved'))
    for row in summaries:
        assert gate.refusal(row) == 'report only'
    assert (home / 'Documents/a.txt').read_text() == 'hello'
    assert (home / 'Desktop/shot.png').exists()


def test_module_has_no_destructive_calls():
    source = Path('commands/cleanup_summaries.py').read_text()
    for word in ('rmtree', 'os.remove', 'unlink', 'rmdir', 'open(', 'rename', 'trash'):
        assert word not in source, word
