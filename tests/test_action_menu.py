"""Action menu (PR 5a): four rows after a drop, the drop gate, the fan-out layout, and the wiring. AppKit is not imported.

The pure parts are tested directly. The AppKit parts are checked by reading the source, the same way
tests/test_magic_wand.py does.
"""
import os
import re

import pytest

import orb_motion as om
from mini_bar import capture_choice_actions, menu_on_drop, orb_action_menu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN = (0.0, 0.0, 1440.0, 900.0)


def _ui():
    with open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8") as f:
        return f.read()


def _body(source, header):
    """The text of the function that starts at `header`, up to the next def at the same indent."""
    start = source.index(header)
    indent = len(header) - len(header.lstrip())
    rest = source[start + len(header):]
    match = re.search(r"\n {%d}(def |@)" % indent, rest)
    return rest[:match.start()] if match else rest


# The four rows, in order.

def test_the_action_menu_is_exactly_six_rows_in_order():
    rows = orb_action_menu()
    assert [(row["id"], row["title"]) for row in rows] == [
        ("ask_jev", "Ask"),
        ("summarize", "Summarize"),
        ("translate", "Translate"),
        ("share_copy", "Copy Image"),
        ("ask_google", "Find Image"),
        ("markup", "Mark up"),
    ]


def test_each_row_has_the_sf_symbol_from_the_plan():
    symbols = [row["symbol"] for row in orb_action_menu()]
    assert symbols == ["bubble.left", "text.alignleft", "character.bubble", "doc.on.doc", "magnifyingglass", "pencil.tip"]


def test_menu_ids_reuse_the_post_capture_panel_except_the_new_rows():
    panel_ids = {row["id"] for row in capture_choice_actions(ask_jev=True)}
    new_rows = {"markup", "summarize", "translate"}  # not on the post-capture panel: PR 5b, and the text actions
    for row in orb_action_menu():
        if row["id"] in new_rows:
            assert row["id"] not in panel_ids
        else:
            assert row["id"] in panel_ids


# The drop gate.

def test_menu_on_drop_is_true_only_for_a_real_drag():
    assert menu_on_drop(True) is True
    assert menu_on_drop(False) is False


# The fan-out layout.

def test_stagger_delays_run_thirty_milliseconds_apart_for_six_rows():
    layout = om.menu_layout((600.0, 400.0, 72.0, 72.0), SCREEN)
    assert layout["delays"] == pytest.approx([0.0, 0.03, 0.06, 0.09, 0.12, 0.15])
    assert len(layout["buttons"]) == 6
    assert len(layout["labels"]) == 6


def test_buttons_are_round_forty_points_with_ten_point_gaps():
    layout = om.menu_layout((600.0, 400.0, 72.0, 72.0), SCREEN)
    tops = []
    for x, y, w, h in layout["buttons"]:
        assert (w, h) == (40.0, 40.0)
        tops.append(y)
    # Top row first: each row sits 50 pt (40 + 10) below the one above it.
    gaps = [tops[i] - tops[i + 1] for i in range(5)]
    assert gaps == pytest.approx([50.0] * 5)


def test_the_menu_opens_to_the_right_of_an_orb_near_the_left_edge():
    layout = om.menu_layout((100.0, 400.0, 72.0, 72.0), SCREEN)
    assert layout["side"] == "right"
    px, py, pw, ph = layout["panel"]
    assert px >= 100.0 + 72.0  # clear of the orb
    for bx, _by, bw, _bh in layout["buttons"]:
        assert px <= bx and bx + bw <= px + pw  # buttons sit inside the panel


def test_the_menu_flips_to_the_left_near_the_right_edge():
    orb = (1400.0, 400.0, 72.0, 72.0)
    layout = om.menu_layout(orb, SCREEN)
    assert layout["side"] == "left"
    px, _py, pw, _ph = layout["panel"]
    assert px + pw <= orb[0]  # the panel is clear of the orb on its left
    # The buttons sit on the orb's side, so the fan-out starts from the orb.
    for bx, _by, bw, _bh in layout["buttons"]:
        assert bx + bw >= px + pw - om.MENU_PAD - 1e-6


@pytest.mark.parametrize("orb", [
    (0.0, 0.0, 72.0, 72.0),  # bottom-left corner
    (1368.0, 828.0, 72.0, 72.0),  # top-right corner
    (700.0, 0.0, 72.0, 72.0),  # bottom edge
    (20.0, 300.0, 72.0, 72.0),  # left edge
])
def test_the_panel_stays_on_screen_at_every_edge(orb):
    layout = om.menu_layout(orb, SCREEN)
    px, py, pw, ph = layout["panel"]
    assert px >= SCREEN[0] and px + pw <= SCREEN[0] + SCREEN[2]
    assert py >= SCREEN[1] and py + ph <= SCREEN[1] + SCREEN[3]
    for bx, by, bw, bh in layout["buttons"]:
        assert by >= py and by + bh <= py + ph


def test_the_layout_follows_the_popover_side_rule():
    from mini_bar import popover_side
    orb = (1200.0, 300.0, 72.0, 72.0)
    panel_w = 2 * om.MENU_PAD + om.MENU_BUTTON + om.MENU_LABEL_GAP + om.MENU_LABEL_WIDTH
    assert om.menu_layout(orb, SCREEN)["side"] == popover_side(orb, panel_w, SCREEN)


def test_the_layout_module_still_imports_with_no_appkit(monkeypatch):
    import sys
    for blocked in ("AppKit", "Quartz", "Foundation", "objc"):
        monkeypatch.setitem(sys.modules, blocked, None)
    assert om.menu_layout((600.0, 400.0, 72.0, 72.0), SCREEN)["side"] in ("left", "right")


# Wiring, read from the source.

def test_a_real_drop_opens_the_menu_only_after_the_peek_check():
    ui = _ui()
    finalize = _body(ui, "    def _finalize_mini_bar_drag(self, window):")
    assert "self._peek_consider()" in finalize
    assert "menu_on_drop(True)" in finalize
    # The tuck runs first, so a drop that tucks the orb into the edge never opens the menu.
    assert finalize.index("self._peek_consider()") < finalize.index("self._open_action_menu()")
    assert "self._peek_edge is None" in finalize


def test_a_click_never_opens_the_menu():
    ui = _ui()
    click = _body(ui, "    def _collapsed_click_or_drag(self, window, delegate, _event):")
    assert "_open_action_menu" not in click
    assert "expandMiniBar_" in click  # a still click still opens the window


def test_tuck_waits_while_the_menu_is_open():
    ui = _ui()
    busy = _body(ui, "    def _peek_is_busy(self):")
    assert "self._action_menu_open" in busy


def test_the_menu_panel_sits_at_the_bar_level_and_does_not_touch_the_orb_panel():
    ui = _ui()
    build = _body(ui, "    def _build_action_menu(self):")
    assert "panel.setLevel_(BAR_LEVEL)" in build
    assert "panel.setFloatingPanel_(True)" in build
    for header in ("    def _open_action_menu(self):", "    def _fill_action_menu(self, layout):",
                   "    def _close_action_menu(self):"):
        body = _body(ui, header)
        assert "mini_panel.setLevel_" not in body
        assert "mini_panel.setFloatingPanel_" not in body
        assert "setStyleMask_" not in body


def test_the_menu_is_nonactivating_and_uses_the_hud_material():
    ui = _ui()
    build = _body(ui, "    def _build_action_menu(self):")
    assert "NSWindowStyleMaskNonactivatingPanel" in build
    fill = _body(ui, "    def _fill_action_menu(self, layout):")
    assert "NSVisualEffectMaterialHUDWindow" in fill
    assert "MENU_CORNER_RADIUS" in fill


def test_every_new_layer_gets_the_window_contents_scale():
    ui = _ui()
    fill = _body(ui, "    def _fill_action_menu(self, layout):")
    assert fill.count("setContentsScale_(scale)") >= 2  # the panel content layer and each button layer
    assert "scale = float(panel.backingScaleFactor())" in fill


def test_the_menu_adds_no_shadow_path():
    ui = _ui()
    for header in ("    def _build_action_menu(self):", "    def _fill_action_menu(self, layout):",
                   "    def _animate_action_menu_button(self, layer, start, end, delay):"):
        assert "shadowPath" not in _body(ui, header)


def test_the_fan_uses_the_section_three_spring_and_stagger():
    ui = _ui()
    fan = _body(ui, "    def _animate_action_menu_button(self, layer, start, end, delay):")
    assert "SPRING_MENU_FAN" in fan
    assert "MENU_FAN_START_SCALE" in ui
    assert om.SPRING_MENU_FAN == (500.0, 30.0)
    opened = _body(ui, "    def _open_action_menu(self):")
    assert "layout[\"delays\"][row]" in opened


def test_close_is_instant_with_order_out_and_no_animation():
    ui = _ui()
    close = _body(ui, "    def _close_action_menu(self):")
    assert "panel.orderOut_(None)" in close
    assert "animator" not in close
    assert "NSAnimationContext" not in close


def test_a_click_on_an_action_closes_first_then_runs_the_capture():
    ui = _ui()
    pick = _body(ui, "    def actionMenuPick_(self, sender):")
    assert pick.index("self._close_action_menu()") < pick.index("_run_action_menu_capture")


def test_the_menu_captures_through_the_existing_area_path_and_respects_esc():
    ui = _ui()
    run = _body(ui, "    def _run_action_menu_capture(self, ident):")
    assert 'take_screenshot("area", book=BOOK)' in run
    assert "capture_outcome(sentence)" in run  # an Esc-cancelled capture returns "Cancelled." and does nothing
    assert 'if outcome != "saved":' in run


def test_menu_actions_never_send_worker_phrases_or_open_the_main_window():
    ui = _ui()
    for header in ("    def _run_action_menu_capture(self, ident):", "    def actionMenuCaptured_(self, payload):"):
        body = _body(ui, header)
        for banned in ("_queue_choice", "controls.put", "showMain", "makeKeyAndOrderFront", "showCaptureResult"):
            assert banned not in body, (header, banned)
    captured = _body(ui, "    def actionMenuCaptured_(self, payload):")
    assert "_show_capture_choices()" in captured and "_open_choice_question()" in captured  # Ask, the thumbnail panel


def test_mark_up_opens_the_overlay_and_no_longer_falls_back_to_preview():
    """PR 5b replaces the PR 5a Preview fallback. Mark up goes to the overlay, not an area capture."""
    ui = _ui()
    pick = _body(ui, "    def actionMenuPick_(self, sender):")
    assert 'if ident == "markup":' in pick and "self._open_markup()" in pick
    run = _body(ui, "    def _run_action_menu_capture(self, ident):")
    assert '"open", "-a", "Preview"' not in ui
    assert 'if ident == "markup"' not in run


def test_esc_and_click_away_and_the_timeout_close_the_menu():
    ui = _ui()
    local = _body(ui, "    def _local_key(self, event):")
    assert "self._action_menu_open" in local and "self._close_action_menu()" in local
    globe = _body(ui, "    def _global_type_key(self, event):")
    assert "self._close_action_menu()" in globe
    click = _body(ui, "    def _action_menu_mouse_down(self, event):")
    assert "self._close_action_menu()" in click
    tick = _body(ui, "    def _sync_action_menu_dismiss(self):")
    assert "choice_due(" in tick and "CHOICE" not in tick  # the same 20 s rule as the post-capture panel
    assert "self._sync_action_menu_dismiss()" in ui


def test_the_menu_buttons_are_labelled_for_accessibility():
    ui = _ui()
    fill = _body(ui, "    def _fill_action_menu(self, layout):")
    assert "setAccessibilityLabel_(action[\"title\"])" in fill


def test_hover_lightens_the_fill_from_eight_to_eighteen_percent_in_point_one_two_seconds():
    assert om.MENU_FILL_REST == 0.08
    assert om.MENU_FILL_HOVER == 0.18
    assert om.MENU_HOVER_SECONDS == 0.12
    ui = _ui()
    cls = _body(ui, "class ActionMenuButton(NSView):")
    assert "set_action_fill(self.circle_layer, MENU_FILL_HOVER)" in cls
    assert "set_action_fill(self.circle_layer, MENU_FILL_REST)" in cls


def test_click_away_uses_the_app_activation_notification_not_a_global_monitor():
    ui = _ui()
    opened = _body(ui, "    def _open_action_menu(self):")
    assert "addGlobalMonitorForEventsMatchingMask_handler_" not in opened  # no new global monitor, no new permission
    assert "addLocalMonitorForEventsMatchingMask_handler_" in opened
    assert "NSWorkspaceDidActivateApplicationNotification" in opened
    closed = _body(ui, "    def _close_action_menu(self):")
    assert "removeObserver_name_object_" in closed
    assert "def actionMenuAppActivated_" in ui


# PR 5a extra direction: Summarize and Translate, and the dark result panel.

def test_the_text_actions_use_the_exact_prompts_and_headings():
    from orb_motion import TEXT_ACTIONS
    assert TEXT_ACTIONS["summarize"] == ("Summary", "Summarize this")
    assert TEXT_ACTIONS["translate"] == ("Translation", "Translate this to English")


def test_the_result_panel_fits_the_text_and_stays_on_screen():
    for text in ("", "Short.", "x" * 500, "line\n" * 40):
        frames = om.result_frames(text)
        pw, ph = frames["panel"]
        assert pw == om.RESULT_WIDTH
        assert ph == om.result_height(text)
        bx, by, bw, bh = frames["body"]
        assert by >= om.RESULT_PAD + om.RESULT_PILL_HEIGHT  # the body clears the pill row
        hx, hy, hw, hh = frames["heading"]
        assert hy + hh <= ph - om.RESULT_PAD + 1e-6  # the heading stays inside the top pad
        assert by + bh <= hy  # the body sits below the heading


def test_the_result_body_line_count_is_clamped():
    assert om.result_body_lines("") == om.RESULT_MIN_LINES
    assert om.result_body_lines("x" * 10000) == om.RESULT_MAX_LINES
    assert om.result_body_lines("one\ntwo\nthree") == 3


@pytest.mark.parametrize("orb", [(600.0, 400.0, 72.0, 72.0), (1400.0, 400.0, 72.0, 72.0), (0.0, 0.0, 72.0, 72.0)])
def test_the_result_panel_sits_beside_the_orb_and_on_screen(orb):
    layout = om.result_layout(orb, SCREEN, "Some summary text")
    px, py, pw, ph = layout["panel"]
    assert px >= SCREEN[0] and px + pw <= SCREEN[0] + SCREEN[2]
    assert py >= SCREEN[1] and py + ph <= SCREEN[1] + SCREEN[3]
    assert px + pw <= orb[0] or px >= orb[0] + orb[2]  # clear of the orb on one side


def test_the_result_timing_is_a_short_fade_and_scale_without_a_spring():
    assert om.RESULT_FADE_SECONDS == 0.15
    assert om.RESULT_SCALE_FROM == 0.96
    ui = _ui()
    anim = _body(ui, "    def _animate_result_in(self, layer):")
    assert "CABasicAnimation" in anim and "CASpringAnimation" not in anim
    assert "RESULT_FADE_SECONDS" in anim and "RESULT_SCALE_FROM" in anim


def test_the_result_panel_is_dark_rounded_and_nonactivating():
    ui = _ui()
    build = _body(ui, "    def _build_result_panel(self):")
    assert "NSWindowStyleMaskNonactivatingPanel" in build
    assert "panel.setLevel_(BAR_LEVEL)" in build
    fill = _body(ui, "    def _fill_result_panel(self, heading, text):")
    assert "NSVisualEffectMaterialHUDWindow" in fill
    assert "MENU_CORNER_RADIUS" in fill  # 14 pt
    assert "setContentsScale_(scale)" in fill
    assert "NSFont.systemFontOfSize_(13)" in fill  # body
    assert "weight=0.8" in fill  # bold white heading
    assert "0.86" in fill  # light grey body


def test_copy_and_close_pills_and_esc_close_the_result():
    ui = _ui()
    assert '"Copy", frames["copy"]' in _body(ui, "    def _fill_result_panel(self, heading, text):")
    assert '"Close", frames["close"]' in _body(ui, "    def _fill_result_panel(self, heading, text):")
    copy = _body(ui, "    def resultCopy_(self, _sender):")
    assert "NSPasteboard.generalPasteboard()" in copy and "NSPasteboardTypeString" in copy
    local = _body(ui, "    def _local_key(self, event):")
    assert "self._close_result_panel()" in local


def test_summarize_and_translate_use_the_existing_ask_path_with_the_prompt():
    ui = _ui()
    run = _body(ui, "    def _run_text_action(self, ident):")
    assert "ask_jev_from_text(\"ask jev about this\", question=prompt)" in run
    assert "from commands.captures import ask_jev_from_text" in run
    captured = _body(ui, "    def actionMenuCaptured_(self, payload):")
    assert "if ident in TEXT_ACTIONS:" in captured
    assert "self._start_text_action(ident)" in captured


def test_the_result_is_not_shown_in_the_jev_window():
    ui = _ui()
    start = _body(ui, "    def _start_text_action(self, ident):")
    assert "_present_result" in start and "showBarSentence_" not in start and "controls.put" not in start
    ready = _body(ui, "    def resultReady_(self, payload):")
    assert "_present_result" in ready and "controls.put" not in ready


# PR 5a hand-test fixes: every menu action starts the area capture, and each uses a real function.

def test_copy_image_and_find_image_call_the_real_functions_in_the_capture_thread():
    ui = _ui()
    run = _body(ui, "    def _run_action_menu_capture(self, ident):")
    assert "run_capture_menu('share_copy', book=BOOK)" in run
    assert "execute_ask(ask_plan(\"google\", \"capture\", path=path))" in run


def test_the_capture_thread_logs_each_click_and_outcome():
    ui = _ui()
    run = _body(ui, "    def _run_action_menu_capture(self, ident):")
    assert 'print(f"  action menu: {ident} clicked")' in run
    assert '"  action menu: capture started (area)"' in run
    assert 'print(f"  action menu: capture {outcome}")' in run  # cancelled or failed
    assert 'print(f"  action menu: capture saved {os.path.basename(path)}")' in run


def test_menu_actions_keep_the_orb_visible():
    ui = _ui()
    for header in ("    def _run_action_menu_capture(self, ident):", "    def actionMenuCaptured_(self, payload):",
                   "    def actionMenuPick_(self, sender):"):
        body = _body(ui, header)
        assert "mini_panel" not in body and "orderOut_" not in body and "bar.dismiss" not in body, header


def test_no_commands_package_book_reference_remains():
    import re
    ui = _ui()
    assert re.search(r"commands\.BOOK\b", ui) is None
    assert "from commands.captures import BOOK" in ui


def test_the_button_is_a_view_with_a_hit_test_so_its_children_never_take_the_click():
    ui = _ui()
    cls = _body(ui, "class ActionMenuButton(NSView):")
    assert "def hitTest_(self, point):" in cls
    assert "def acceptsFirstMouse_(self, _event):" in cls
    assert "return True" in _body(cls, "    def acceptsFirstMouse_(self, _event):")
    assert "self.pick_target.actionMenuPick_(self)" in _body(cls, "    def mouseDown_(self, _event):")


# PR 5a: the Find Image hint bubble.

from mini_bar import FIND_IMAGE_HINT


def test_the_hint_text_is_exact_and_uses_the_command_key():
    assert FIND_IMAGE_HINT == "Image copied. Press \u2318V in Lens to search."


def test_the_hint_is_five_seconds_and_fits_beside_the_orb_on_screen():
    assert om.HINT_SECONDS == 5.0
    for orb in ((600.0, 400.0, 72.0, 72.0), (1400.0, 400.0, 72.0, 72.0), (0.0, 0.0, 72.0, 72.0)):
        px, py, pw, ph = om.hint_layout(orb, SCREEN)["panel"]
        assert (pw, ph) == (om.HINT_WIDTH, om.HINT_HEIGHT)
        assert px >= SCREEN[0] and px + pw <= SCREEN[0] + SCREEN[2]
        assert py >= SCREEN[1] and py + ph <= SCREEN[1] + SCREEN[3]
        assert px + pw <= orb[0] or px >= orb[0] + orb[2]  # clear of the orb


def test_the_hint_is_built_nonactivating_at_bar_level_in_the_result_style():
    ui = _ui()
    build = _body(ui, "    def _build_hint_panel(self):")
    assert "NSWindowStyleMaskNonactivatingPanel" in build
    assert "panel.setLevel_(BAR_LEVEL)" in build
    show = _body(ui, "    def _show_hint(self, text):")
    assert "NSVisualEffectMaterialHUDWindow" in show
    assert "MENU_CORNER_RADIUS" in show  # 14 pt
    assert "self._animate_result_in(content.layer())" in show  # the same 0.96 to 1, 0.15 s entrance
    for header in ("    def _build_hint_panel(self):", "    def _show_hint(self, text):",
                   "    def _close_hint(self):", "    def findImageHint_(self, _payload):"):
        body = _body(ui, header)
        for banned in ("activateIgnoringOtherApps", "makeKeyAndOrderFront", "makeKey", "showMain"):
            assert banned not in body, (header, banned)


def test_the_hint_is_shown_only_after_the_copy_and_the_lens_open_both_succeed():
    ui = _ui()
    run = _body(ui, "    def _run_action_menu_capture(self, ident):")
    branch = run[run.index('if ident == "ask_google":'):run.index('payload = json.dumps')]
    assert "execute_ask(ask_plan(" in branch
    # The hint call sits after execute_ask, with no except path that could still reach it.
    assert branch.index("execute_ask(") < branch.index("findImageHint:")
    assert "except" not in branch.split("findImageHint:")[0].split("execute_ask(")[1]


def test_the_hint_closes_on_its_timer_on_esc_and_on_a_click():
    ui = _ui()
    assert "self._sync_hint_dismiss()" in ui
    assert "self._sync_hint_dismiss" in ui and "HINT_SECONDS" in _body(ui, "    def _sync_hint_dismiss(self):")
    local = _body(ui, "    def _local_key(self, event):")
    assert "self._hint_open" in local and "self._close_hint()" in local
    globe = _body(ui, "    def _global_type_key(self, event):")
    assert "self._close_hint()" in globe
    click = _body(ui, "    def mouseDown_(self, _event):")  # HintClickView
    assert "self.dismiss_target.hintDismiss_(self)" in ui


def test_the_hint_never_touches_the_orb_panel_level_or_flags():
    ui = _ui()
    for header in ("    def _show_hint(self, text):", "    def _build_hint_panel(self):", "    def _close_hint(self):"):
        body = _body(ui, header)
        assert "mini_panel.setLevel_" not in body and "mini_panel.setFloatingPanel_" not in body
