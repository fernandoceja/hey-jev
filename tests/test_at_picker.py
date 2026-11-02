"""Headless contracts for the @ picker (8a full window, 8a-2 Home, right-click panel, paste, gate, Esc)."""
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
              "controlTextDidEndEditing_", "windowDidResignKey_", "_collapse_orb_from_full", "_at_command"}
    methods = {n.name: ast.get_source_segment(source, n) for n in delegate.body
               if isinstance(n, ast.FunctionDef) and n.name in needed}
    assert "self.full_field.setDelegate_(self)" in methods["_build_full_window"]
    assert "self._at_command(surface, selector)" in methods["control_textView_doCommandBySelector_"]
    for selector in ("moveDown:", "moveUp:", "insertNewline:", "insertTab:", "cancelOperation:"):
        assert selector in methods["_at_command"]
    for method in ("fullSubmit_", "fullNewChat_", "controlTextDidEndEditing_", "windowDidResignKey_", "_collapse_orb_from_full"):
        # Two classes own windowDidResignKey_; inspect all source for the AppDelegate hook.
        if method != "windowDidResignKey_":
            assert "self._at_hide()" in methods[method]
    assert '"file_open": lambda _arg, text: commands.open_picked_file(text)' in (root / "siri.py").read_text()
    assert "print(" not in (root / "at_picker.py").read_text()
    logs = [line.strip() for line in source.splitlines() if 'print("at picker:' in line]
    assert len(logs) == 2 and "qlen=" in logs[0] and "surface=" in logs[0] and "gate {0} surface=" in logs[1]


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


# PR 8a-2

def test_at_tokens():
    assert atp.at_tokens("open @saf and @tax") == [(5, 9, "saf"), (14, 18, "tax")]
    for text in ("me@mail.com", "@", "meet @ 5", "@" + "x" * 41):
        assert atp.at_tokens(text) == []
    assert atp.at_tokens("\U0001F600 @saf") == [(2, 6, "saf")]
    assert atp.at_tokens("@" + "x" * 40) == [(0, 41, "x" * 40)]


def test_is_bulk_insert():
    assert atp.is_bulk_insert("open", "open ") is False
    assert atp.is_bulk_insert("", "open @picker") is True
    assert atp.is_bulk_insert("open @saf", "open @sa") is False


def test_submit_decision():
    rows = lambda query: [{"insert": "Safari"}] if query == "saf" else []
    assert atp.submit_decision("open safari", rows, None) == ("send", None)
    assert atp.submit_decision("open @saf and @zzqq", rows, None) == ("pick", (5, 9, "saf"))
    assert atp.submit_decision("ping @zzqq", rows, None) == ("nomatch", (5, 10, "zzqq"))
    assert atp.submit_decision("ping @zzqq", rows, "ping @zzqq") == ("send", None)
    assert atp.submit_decision("ping @zzqqx", rows, "ping @zzqq") == ("nomatch", (5, 11, "zzqqx"))
    assert atp.NOTICE_TEMPLATE.format("zzqq") == "No app or file matches \u201c@zzqq\u201d. Press Return again to send as typed."


def test_insert_pick_replaces_whole_token():
    text = "open @saf please"
    start, end, _query = atp.at_tokens(text)[0]
    assert atp.insert_pick(text, start, end, {"insert": "Safari"}) == ("open Safari  please", 12)
    assert atp.insert_pick("hi @saf", 3, 7, {"insert": "Safari"}) == ("hi Safari ", 10)
    assert atp.token_end("open @saf please", 5) == 9


def test_picker_screen_frame():
    visible = (0, 0, 1440, 900)
    h = 2 * atp.AT_ROW_H + 2 * atp.AT_PAD
    assert atp.picker_screen_frame((100, 500, 400, 30), 2, visible, "below") == (100, 500 - atp.AT_GAP - h, 400, h)
    assert atp.picker_screen_frame((100, 20, 400, 30), 2, visible, "below") == (100, 20 + 30 + atp.AT_GAP, 400, h)
    assert atp.picker_screen_frame((100, 500, 400, 30), 2, visible, "above") == (100, 530 + atp.AT_GAP, 400, h)
    assert atp.picker_screen_frame((100, 880, 400, 20), 2, visible, "above") == (100, 880 - atp.AT_GAP - h, 400, h)
    assert atp.picker_screen_frame((1300, 500, 400, 30), 2, visible, "below")[0] == 1440 - 400
    assert atp.picker_screen_frame((-50, 500, 400, 30), 2, visible, "below")[0] == 0
    assert atp.picker_screen_frame((100, 500, 120, 30), 2, visible, "below")[2] == 300
    assert atp.picker_screen_frame((0, 500, 1200, 30), 2, visible, "below")[2] == 640


def _segments(names, cls="AppDelegate"):
    import ast
    source = (Path(__file__).parents[1] / "assistant_ui.py").read_text()
    tree = ast.parse(source)
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    found = {n.name: ast.get_source_segment(source, n) for n in owner.body
             if isinstance(n, ast.FunctionDef) and n.name in names}
    return source, found


def _first_statement(segment):
    import ast
    import textwrap
    func = ast.parse(textwrap.dedent(segment)).body[0]
    body = func.body
    if isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return ast.get_source_segment(textwrap.dedent(segment), body[0]).strip()


def test_wiring_three_surfaces_gate_and_esc():
    source, m = _segments({"controlTextDidChange_", "_spotlight_event", "fullSubmit_", "homeSubmit_",
                           "_send_orb_spotlight_text", "_local_key", "_collapse_orb_from_full"})
    assert '_at_update(self.home_field, "home")' in m["controlTextDidChange_"]
    assert '_at_update(self.full_field, "full")' in m["controlTextDidChange_"]
    assert '_at_update(state["field"], "spotlight")' in m["_spotlight_event"]
    for name in ("fullSubmit_", "homeSubmit_", "_send_orb_spotlight_text"):
        assert _first_statement(m[name]).startswith("if self._at_gate("), name
    esc = m["_local_key"]
    assert esc.index('getattr(self, "_at", None)') < esc.index("self._hint_open")
    event = m["_spotlight_event"]
    assert event.index("self._at_command(") < event.index('selector == "moveDown:"')
    assert _first_statement(m["_collapse_orb_from_full"]) == "self._at_hide()"
    assert "self.full_at" not in source
    assert "mini_field" not in source[source.index("def _at_surface_for"):source.index("def _at_host_is")]


def test_picker_panel_and_rows_never_take_focus():
    _source, panel = _segments({"canBecomeKeyWindow", "canBecomeMainWindow"}, "AtPickerPanel")
    assert "return False" in panel["canBecomeKeyWindow"] and "return False" in panel["canBecomeMainWindow"]
    _source, row = _segments({"configure", "acceptsFirstResponder", "acceptsFirstMouse_", "mouseDown_"}, "AtPickerRow")
    assert 'self.setTitle_("")' in row["configure"]
    assert "return False" in row["acceptsFirstResponder"]
    assert "return True" in row["acceptsFirstMouse_"]
    assert "_at_pick(self.pickIndex)" in row["mouseDown_"]


def test_logs_never_carry_query_names_or_paths():
    source = (Path(__file__).parents[1] / "assistant_ui.py").read_text()
    for line in (l for l in source.splitlines() if 'print("at picker:' in l):
        segment = source[source.index(line):source.index(line) + 300].split("flush=True")[0]
        for leak in ('token[2])', "query)", '["title"]', '["path"]', "text)"):
            assert leak not in segment.replace("len(token[2])", ""), segment
