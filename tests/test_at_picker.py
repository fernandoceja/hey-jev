"""Headless contracts for the full-window @ picker."""
import os
from pathlib import Path
from unittest.mock import patch
import at_picker as atp


def test_query_and_utf16_carets():
    assert atp.at_query("@", 1) == (0, "")
    assert atp.at_query("open @saf", 9) == (5, "saf")
    for text in ("me@mail.com", "@saf ", "@" + "x" * 41):
        assert atp.at_query(text, len(text)) is None
    assert atp.at_query("open @saf", 3) is None
    text = "😀 open @saf"
    assert atp.py_index(text, atp.utf16_len(text)) == len(text)
    assert atp.at_query(text, atp.py_index(text, atp.utf16_len(text))) == (7, "saf")


def test_matching_and_apps():
    assert [atp.match_rank(q, n) for q, n in (("saf", "Safari"), ("chrome", "Google Chrome"),
            ("ari", "Safari"), ("zzz", "Safari"), ("SAF", "Safari"))] == [0, 1, 2, None, 0]
    rows = atp.app_rows({"s": "/Applications/Safari.app", "s2": "/Other/Safari.app", "a": "/A.app"})
    assert [r["title"] for r in rows] == ["A", "Safari"]
    assert rows[1]["insert"] == "Safari"


def test_scan_depth_packages_hidden_symlinks_and_cap(tmp_path):
    home = tmp_path / "home"
    docs = home / "Documents"
    docs.mkdir(parents=True)
    for name in ("a b.pdf", ".hidden", "bad\"name.txt", "bad\nname.txt"):
        (docs / name).touch()
    for folder in ("one", "one/two", "Foo.app", "X.photoslibrary"):
        (docs / folder).mkdir(exist_ok=True)
        (docs / folder / "entry.txt").touch()
    (docs / "linked").symlink_to(docs / "one", target_is_directory=True)
    with patch.dict(os.environ, {"HOME": str(home)}):
        rows = atp.scan_files(("~/Documents",))
        assert sorted(r["title"] for r in rows) == ["a b.pdf", "entry.txt"]
        assert next(r for r in rows if r["title"] == "a b.pdf")["insert"] == '"~/Documents/a b.pdf"'
        assert len(atp.scan_files(("~/Documents",), cap=1)) <= 1
        assert len(atp.scan_files(("~/Documents",), depth=1)) == 1


def test_sections_rank_and_recent_files():
    apps = [{"title": "App " + str(i), "kind": "app"} for i in range(10)]
    files = [{"title": "File " + str(i), "kind": "file", "mtime": i} for i in range(10)]
    rows = atp.picker_rows("", apps, files)
    assert len(rows) == 8
    assert [r["kind"] for r in rows] == ["app"] * 4 + ["file"] * 4
    assert rows[4]["mtime"] == 9
    assert len(atp.picker_rows("", apps[:1], files)) == 8
    assert len(atp.picker_rows("", apps, files[:1])) == 8
    assert atp.picker_rows("zzzz", apps, files) == []


def test_insert_and_frame():
    assert atp.insert_pick("open @saf please", 5, 9, {"insert": "Safari"}) == ("open Safari  please", 12)
    assert atp.insert_pick("open @tax", 5, 9, {"insert": '"~/Documents/tax.pdf"'}) == ('open "~/Documents/tax.pdf" ', 27)
    assert atp.picker_frame((10, 100, 400, 44), 2, 560, 28) == (10, 150, 400, 72)
    assert atp.picker_frame((10, 450, 400, 44), 2, 560, 28) == (10, 372, 400, 72)


def test_cache_only_warmer_scans():
    with patch.object(atp, "_files_at", None), patch.object(atp, "scan_files", return_value=[{"title": "test"}]) as scan:
        atp.warm_files()
        atp.warm_files()
        assert atp.cached_files() == [{"title": "test"}]
        scan.assert_called_once()


def test_file_routing_is_specific_and_bridge_refuses():
    import commands
    from commands.routing import route_before_api
    assert route_before_api('open "~/Documents/a and b.pdf"') == "file_open"
    assert route_before_api("open Safari") == "app_open"
    assert route_before_api("open downloads") == "folder_open"
    assert route_before_api('open "/etc/hosts"') != "file_open"
    assert commands.bridge_allowed('open "~/Documents/a.pdf"') is None
    assert "file_open" not in commands.BRIDGE_ALLOW


def test_file_open_guards_and_argument_list(tmp_path):
    from commands import system
    home = tmp_path / "home"
    home.mkdir()
    (home / "Documents").mkdir()
    file = home / "Documents" / "a and b.txt"
    file.touch()
    outside = tmp_path / "outside.txt"
    outside.touch()
    (home / "link.txt").symlink_to(outside)
    (home / ".hidden").touch()
    with patch.dict(os.environ, {"HOME": str(home)}), patch.object(system, "_run") as run:
        assert system.open_picked_file('open "~/Documents/a and b.txt"') == "Opening a and b.txt."
        run.assert_called_once_with(("open", str(file)))
        run.reset_mock()
        for text in ('open "~/../outside.txt"', 'open "~/link.txt"', 'open "~/.hidden"',
                     'open "~/missing.txt"', 'open "~/Documents/a\nb.txt"', 'open "~/a\0.txt"'):
            assert not system.open_picked_file(text).startswith("Opening")
        run.assert_not_called()


def test_picker_source_wiring_and_logs():
    import ast
    root = Path(__file__).parents[1]
    source = (root / "assistant_ui.py").read_text()
    tree = ast.parse(source)
    delegate = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AppDelegate")
    needed = {"_build_full_window", "control_textView_doCommandBySelector_", "fullSubmit_", "fullNewChat_",
              "controlTextDidEndEditing_", "windowDidResignKey_", "_collapse_orb_from_full"}
    methods = {n.name: ast.get_source_segment(source, n) for n in delegate.body
               if isinstance(n, ast.FunctionDef) and n.name in needed}
    assert "self.full_field.setDelegate_(self)" in methods["_build_full_window"]
    for selector in ("moveDown:", "moveUp:", "insertNewline:", "insertTab:", "cancelOperation:"):
        assert selector in methods["control_textView_doCommandBySelector_"]
    for method in ("fullSubmit_", "fullNewChat_", "controlTextDidEndEditing_", "windowDidResignKey_", "_collapse_orb_from_full"):
        # Two classes own windowDidResignKey_; inspect all source for the AppDelegate hook.
        if method != "windowDidResignKey_":
            assert "self._at_hide()" in methods[method]
    assert '"file_open": lambda _arg, text: commands.open_picked_file(text)' in (root / "siri.py").read_text()
    assert "print(" not in (root / "at_picker.py").read_text()
    logs = [line.strip() for line in source.splitlines() if 'print("at picker:' in line]
    assert len(logs) == 1 and "qlen=" in logs[0]


def test_orb_open_path_warms_picker_when_full_window_becomes_key():
    import ast
    from types import SimpleNamespace
    root = Path(__file__).parents[1]
    source = (root / "assistant_ui.py").read_text()
    tree = ast.parse(source)
    delegate = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AppDelegate")
    node = next(n for n in delegate.body if isinstance(n, ast.FunctionDef) and n.name == "windowDidBecomeKey_")
    # Execute with another window distinct from panel, so the old main-window reveal path exits.
    import threading
    from unittest.mock import Mock
    full, panel = object(), object()
    ui = SimpleNamespace(full_window=full, panel=panel, _at_warm=Mock())
    thread = Mock()
    namespace = {"threading": SimpleNamespace(Thread=thread)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "full window key", "exec"), namespace)
    namespace["windowDidBecomeKey_"](ui, SimpleNamespace(object=lambda: full))
    thread.assert_called_once_with(target=ui._at_warm, daemon=True)
    thread.return_value.start.assert_called_once()
