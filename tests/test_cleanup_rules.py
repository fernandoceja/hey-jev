import os
import time

import pytest

from commands.cleanup_gate import CleanupGate, Proposal
from commands.cleanup_rules import fernando_reason, load_protected, protected_reason


@pytest.mark.parametrize("relative", [
    ".cache/huggingface", "Developer/repo", "Library/Caches/com.example.jarvisnotes",
    "Library/Developer/Xcode/DerivedData/DmIOS-abc", "Apps/Xcode-beta.app",
    "Library/Developer/Xcode/UserData", "Downloads/file.download/payload",
    "Library/Notes/NoteStore.sqlite", "Library/Caches/omnivoice.db",
    "Library/Support/data.sqlite", "Documents/.cos-tmp/file",
    "Library/Application Support/Hey Jev/data", "Library/Caches/VoiceStudio",
])
def test_protected_paths_cannot_be_approved(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.touch()
    gate = CleanupGate(home=tmp_path, protected_roots=(), trash=lambda _: pytest.fail("unexpected move"))
    row = Proposal(str(path), 0, "Test", "", "safe")
    assert protected_reason(path, tmp_path)
    with pytest.raises(ValueError, match="protected path"):
        gate.approve_click(gate.present([row]), [0])


def test_git_ancestor(tmp_path):
    repo = tmp_path / "Documents" / "repo"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    assert protected_reason(repo / "file", tmp_path) == "developer work"
    assert protected_reason(repo.parent / "file", tmp_path) is None


def test_protection_added_after_approval(tmp_path):
    folder = tmp_path / "candidate"
    folder.mkdir()
    aged = time.time() - 172800
    os.utime(folder, (aged, aged))
    gate = CleanupGate(home=tmp_path, protected_roots=(), trash=lambda _: pytest.fail("unexpected move"))
    row = Proposal(str(folder), 0, "Test", "", "safe")
    token = gate.approve_click(gate.present([row]), [0])
    (folder / "NoteStore.sqlite").touch()
    os.utime(folder, (aged, aged))
    assert gate.execute(token) == ["protected path"]


def test_local_config_and_permission(tmp_path):
    config = tmp_path / "cleanup-protected.json"
    assert load_protected(config) == ()
    config.write_text("broken")
    assert load_protected(config) == ()
    config.write_text('{"paths": []}')
    assert load_protected(config) == ()
    assert fernando_reason(config, tmp_path, uid=os.getuid() + 1)
    assert fernando_reason(config, tmp_path, uid=os.getuid(), writable=False)
    assert fernando_reason(config, tmp_path, uid=os.getuid(), writable=True) is None
