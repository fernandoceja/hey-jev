import os
import threading

from commands.cleanup_gate import CleanupGate
from commands.cleanup_large_files import BUCKET, candidates, settings
from commands.storage_scan import scan


def fixture(path, logical=8192, modified=1000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as stream:
        stream.write(b'x')
        stream.truncate(logical)
    os.utime(path, (modified, modified))
    return path


def test_home_scan_reports_allocated_bytes_and_requires_selection(tmp_path, monkeypatch):
    archive = fixture(tmp_path / 'Documents/Archives/large.rar', logical=2_000_000)
    monkeypatch.setenv('JEV_LARGE_FILES_MIN_MB', '1')
    rows = scan(home=tmp_path, snapshots=lambda: '')
    row = next(r for r in rows if r.path == str(archive))
    assert row.bucket == BUCKET and row.safety == 'ask_first' and row.deletable
    assert row.size == archive.stat().st_blocks * 512 < archive.stat().st_size

    moved = []
    gate = CleanupGate(home=tmp_path, protected_roots=(), trash=lambda path: moved.append(path) or '/Trash/large.rar')
    card = gate.present(rows)
    gate.execute(gate.approve_click(card, []))
    assert moved == []
    card = gate.present(rows)
    gate.execute(gate.approve_click(card, [rows.index(row)]))
    assert moved == [str(archive)]


def test_home_scan_prunes_protected_paths_and_handles_cloud_and_databases(tmp_path):
    data = fixture(tmp_path / 'Documents/archive.sqlite')
    local = fixture(tmp_path / 'Desktop/local.bin')
    downloaded = fixture(tmp_path / 'Documents/synced.bin')
    cloud = fixture(tmp_path / 'Documents/placeholder.bin')
    secret = fixture(tmp_path / 'Documents/private/file.sqlite')
    for name in ('Documents/Jarvis/secret.bin', 'Library/Caches/file.bin',
                 'Applications/Example.app/Contents/file.bin', '.Trash/deleted.bin',
                 'Documents/repo/file.bin'):
        fixture(tmp_path / name)
    (tmp_path / 'Documents/repo/.git').mkdir()
    (tmp_path / 'shortcut').symlink_to(local)
    queried = set()

    def reader(path):
        queried.add(path)
        if path == cloud:
            return {'cloud_only': True}
        return {'IsUbiquitousItem': path == downloaded}

    rows = list(candidates(tmp_path, threading.Event(), (secret.parent,), min_bytes=4096,
                           min_age=0, reader=reader, now=100000))
    by_path = {r.path: r for r in rows}
    assert set(by_path) == {str(data), str(local), str(downloaded)}
    assert not by_path[str(data)].deletable
    assert not by_path[str(downloaded)].deletable
    assert queried == {local, downloaded, cloud}


def test_age_configuration_and_recent_file(tmp_path):
    recent = fixture(tmp_path / 'recent.bin', modified=195000)
    old = fixture(tmp_path / 'old.bin', modified=1000)
    assert settings({}) == (500_000_000, 0)
    assert settings({'JEV_LARGE_FILES_MIN_MB': '25', 'JEV_LARGE_FILES_MIN_AGE_DAYS': '2'}) == (25_000_000, 172800)
    assert settings({'JEV_LARGE_FILES_MIN_MB': 'nan', 'JEV_LARGE_FILES_MIN_AGE_DAYS': '-1'}) == (500_000_000, 0)
    options = dict(min_bytes=4096, now=200000)
    rows = {r.path: r for r in candidates(tmp_path, threading.Event(), (), min_age=0, **options)}
    assert not rows[str(recent)].deletable
    assert rows[str(old)].deletable
    assert [r.path for r in candidates(tmp_path, threading.Event(), (), min_age=172800, **options)] == [str(old)]


def test_download_candidate_is_only_listed_once(tmp_path, monkeypatch):
    archive = fixture(tmp_path / 'Downloads/installer.dmg', logical=2_000_000)
    monkeypatch.setenv('JEV_LARGE_FILES_MIN_MB', '1')
    rows = [r for r in scan(home=tmp_path, snapshots=lambda: '') if r.path == str(archive)]
    assert len(rows) == 1 and rows[0].bucket == BUCKET
