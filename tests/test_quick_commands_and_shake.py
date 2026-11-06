"""Shared navigation and early shake recognition, without AppKit."""
import ast
from pathlib import Path

import full_window
import mini_bar
import orb_motion as motion
import orb_spotlight


def test_all_surfaces_use_the_shared_tree(monkeypatch):
    item = {"id": "sentinel", "kind": "text", "title": "Unique Command",
            "phrase": "unique phrase", "symbol": "bolt"}
    monkeypatch.setattr(mini_bar, "quick_commands", lambda *args, **kwargs: (item,))
    assert mini_bar.plus_menu()[0]["items"] == (item,)
    assert orb_spotlight.search_rows("unique phrase")[0][1] == "send:unique phrase"
    rows, _ = full_window.sidebar_items()
    assert any(row.get("action") == ("send", "unique phrase") for row in rows)
    assert any(row[0] == "Quick Commands" for row in orb_spotlight.SPOTLIGHT_ROWS)


def test_searches_navigation_titles_phrases_and_nested_commands():
    assert orb_spotlight.search_rows("settings")[0][0] == "Settings"
    assert any(row[1] == "send:tutor me" for row in orb_spotlight.search_rows("tutor me"))
    assert any(row[1] == "send:volume to 30" for row in orb_spotlight.search_rows("volume"))
    assert any(row[1] == "send:payday check" for row in orb_spotlight.search_rows(quick=True))
    assert not orb_spotlight.search_rows("no such command xyz")


def test_hazard_toggle_tracks_current_state_on_both_surfaces():
    items = mini_bar.quick_commands(hazard_alerts=True)
    assert any(row[1] == "send:turn off hazard alerts"
               for row in orb_spotlight.search_rows(quick=True, items=items))
    rows, _ = full_window.sidebar_items(hazard_alerts=True)
    assert any(row.get("action") == ("send", "turn off hazard alerts") for row in rows)


def test_shake_recognized_in_150ms_but_not_for_straight_drag_or_jitter():
    shake = [(0, 0, 0), (.05, 30, 0), (.10, -30, 0), (.15, 30, 0)]
    assert not motion.shake_recognized(shake[:3])
    assert motion.shake_recognized(shake)
    assert not motion.shake_recognized([(i * .05, i * 100, 0) for i in range(10)])
    assert not motion.shake_recognized([(i * .05, (-1)**i * 3, 0) for i in range(10)])
    assert not motion.shake_recognized([(i * .5, x, 0) for i, x in enumerate([0, 30, -30, 30])])


def test_both_drag_loops_recognize_before_release_and_skip_settle():
    tree = ast.parse(Path("assistant_ui.py").read_text())
    methods = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name in ("_drag_exactly", "_drag_with_spring"):
        loop = next(node for node in ast.walk(methods[name]) if isinstance(node, ast.While))
        assert any(isinstance(node, ast.Attribute) and node.attr == "_recognize_drag_shake"
                   for node in ast.walk(loop))
    recognition = ast.get_source_segment(Path("assistant_ui.py").read_text(), methods["_recognize_drag_shake"])
    assert recognition.index("_stop_drag_settle") < recognition.index("_open_action_menu")
    assert recognition.index("dropJiggle") < recognition.index("_open_action_menu")
    assert "sleep" not in recognition and "Timer" not in recognition


def test_installed_game_leaves_keep_the_original_menu_handler(monkeypatch):
    game = {"id": "game_test", "title": "My Game", "path": "/games/test.rom",
            "kind": "game_launch", "phrase": "", "symbol": "gamecontroller"}
    monkeypatch.setattr(mini_bar, "quick_commands", lambda *args, **kwargs: (game,))
    assert orb_spotlight.search_rows("My Game")[0][1] == "menu:game_test"
    rows, _ = full_window.sidebar_items()
    assert any(row.get("action") == ("quick", "game_test") for row in rows)
    source = Path("assistant_ui.py").read_text()
    assert 'self.miniPlusItem_(item)' in source
