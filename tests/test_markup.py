"""Mark up on screen (PR 5b): the stroke model, decimation, bounds, the empty-save refusal, and save geometry."""
from datetime import datetime

from markup import (
    LINE_WIDTH_PT,
    MIN_STEP_PT,
    Strokes,
    can_save,
    image_line_width,
    markup_folder,
    reference_rect,
    temp_capture_path,
    to_image_points,
)


def _line(strokes, start, *points):
    strokes.begin(start)
    for point in points:
        strokes.extend(point)
    return strokes.end()


def test_a_drag_becomes_one_stroke_and_is_kept():
    strokes = Strokes()
    assert _line(strokes, (0, 0), (10, 0), (20, 0)) is True
    assert strokes.count() == 1
    assert strokes.all_strokes() == [[(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]]
    assert strokes.is_empty() is False


def test_a_click_without_a_drag_is_not_a_stroke():
    strokes = Strokes()
    assert _line(strokes, (5, 5)) is False
    assert strokes.is_empty() is True


def test_extend_without_an_open_stroke_is_ignored():
    strokes = Strokes()
    assert strokes.extend((1, 1)) is False
    assert strokes.count() == 0


def test_points_closer_than_the_minimum_step_are_dropped():
    strokes = Strokes()
    strokes.begin((0, 0))
    assert strokes.extend((1.0, 0.0)) is False  # 1 pt away, under 1.5
    assert strokes.extend((MIN_STEP_PT - 0.01, 0.0)) is False
    assert strokes.extend((MIN_STEP_PT, 0.0)) is True  # exactly 1.5 pt is kept
    strokes.end()
    assert strokes.all_strokes() == [[(0.0, 0.0), (MIN_STEP_PT, 0.0)]]


def test_decimation_measures_from_the_last_kept_point_not_the_last_seen_one():
    strokes = Strokes()
    strokes.begin((0, 0))
    strokes.extend((1.0, 0.0))  # dropped
    strokes.extend((2.0, 0.0))  # 2 pt from the start, kept
    strokes.end()
    assert strokes.all_strokes() == [[(0.0, 0.0), (2.0, 0.0)]]


def test_undo_removes_the_last_stroke_and_reports_when_there_is_none():
    strokes = Strokes()
    _line(strokes, (0, 0), (10, 10))
    _line(strokes, (20, 20), (30, 30))
    assert strokes.undo() is True
    assert strokes.count() == 1
    assert strokes.undo() is True
    assert strokes.is_empty() is True
    assert strokes.undo() is False


def test_undo_finishes_an_open_stroke_first():
    strokes = Strokes()
    _line(strokes, (0, 0), (10, 10))
    strokes.begin((50, 50))
    strokes.extend((60, 60))
    assert strokes.undo() is True  # removes the open stroke, which is the last one
    assert strokes.count() == 1


def test_clear_removes_everything_including_an_open_stroke():
    strokes = Strokes()
    _line(strokes, (0, 0), (10, 10))
    strokes.begin((50, 50))
    strokes.extend((60, 60))
    strokes.clear()
    assert strokes.is_empty() is True
    assert strokes.bounds() is None


def test_bounds_span_every_stroke():
    strokes = Strokes()
    _line(strokes, (10, 10), (20, 30))
    _line(strokes, (-5, 50), (4, 60))
    assert strokes.bounds() == (-5.0, 10.0, 25.0, 50.0)  # left, bottom, width, height


def test_bounds_include_a_stroke_still_in_progress():
    strokes = Strokes()
    strokes.begin((0, 0))
    strokes.extend((0, 8))
    assert strokes.bounds() == (0.0, 0.0, 0.0, 8.0)


def test_an_empty_save_is_refused():
    assert can_save(Strokes()) is False
    assert can_save(None) is False
    strokes = Strokes()
    _line(strokes, (0, 0), (5, 5))
    assert can_save(strokes) is True


def test_temp_files_go_only_in_the_cos_tmp_folder(tmp_path):
    folder = markup_folder(home=str(tmp_path))
    assert folder == str(tmp_path / "Documents" / ".cos-tmp")
    path = temp_capture_path(folder, datetime(2026, 10, 31, 9, 5, 7, 123456))
    assert path.startswith(folder + "/")
    assert path.endswith(".png")


def test_reference_rect_is_the_union_when_the_capture_matches_it():
    screens = [(0, 0, 1000, 800), (1000, 100, 500, 400)]  # main first, second display to its right
    union = reference_rect((3000, 1600), screens)  # ratio 1500/800 across the union
    assert union == (0.0, 0.0, 1500.0, 800.0)


def test_reference_rect_falls_back_to_the_main_screen_for_a_single_display_capture():
    screens = [(0, 0, 1000, 800), (1000, 100, 500, 400)]
    assert reference_rect((2000, 1600), screens) == (0.0, 0.0, 1000.0, 800.0)


def test_strokes_map_into_pixel_space_with_the_bottom_left_origin():
    ref = (0.0, 0.0, 1000.0, 800.0)
    mapped = to_image_points([[(0.0, 0.0), (500.0, 400.0)]], ref, (2000, 1600))
    assert mapped == [[(0.0, 0.0), (1000.0, 800.0)]]


def test_the_line_width_scales_with_the_capture():
    assert LINE_WIDTH_PT == 3.0
    assert image_line_width((2000, 1600), (0.0, 0.0, 1000.0, 800.0)) == 6.0


# The overlay and the save are AppKit code, which CI can't run. These checks read the source for the rules the PR
# and the plan require: level 101, the crosshair, the stroke style, contentsScale, no shadowPath, the log lines, and
# the temp folder.
import os as _os
import re as _re

_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))


def _ui_source():
    with open(_os.path.join(_ROOT, "assistant_ui.py"), encoding="utf-8") as handle:
        return handle.read()


def _markup_section(source):
    start = source.index("class MarkupWindow(NSWindow):")
    end = source.index("class AppDelegate(NSObject):")
    return source[start:end] + source[source.index("    # PR 5b: Mark up on screen."):source.index("    # PR 5a: the Find Image hint.")]


def test_the_overlay_sits_at_level_101_with_full_screen_auxiliary_and_a_clear_background():
    source = _ui_source()
    assert "MARKUP_LEVEL = 101" in source
    section = _markup_section(source)
    assert "window.setLevel_(MARKUP_LEVEL)" in section
    assert "NSWindowCollectionBehaviorFullScreenAuxiliary" in section
    assert "colorWithCalibratedWhite_alpha_(0.0, 0.01)" in section  # near-clear: see test_the_overlay_takes_input
    assert "NSCursor.crosshairCursor()" in section


def test_strokes_are_three_point_system_red_round_caps_on_every_layer_with_a_contents_scale():
    source = _ui_source()
    section = _markup_section(source)
    assert "LINE_WIDTH_PT" in section and "setLineWidth_(LINE_WIDTH_PT)" in section
    assert "systemRedColor" in section
    assert 'setLineCap_("round")' in section and 'setLineJoin_("round")' in section
    assert "setContentsScale_(" in section
    assert "shadowPath" not in section


def test_the_bar_and_orb_window_levels_are_untouched_by_the_overlay():
    source = _ui_source()
    section = _markup_section(source)
    assert "BAR_LEVEL" not in section
    assert "setFloatingPanel_" not in section


def test_esc_cancels_with_no_file_return_saves_and_an_empty_save_is_refused():
    section = _markup_section(_ui_source())
    assert "if code == 53:" in section and "self._markup_cancel()" in section
    assert "if code in (36, 76):" in section and "self._markup_save()" in section
    assert "can_save(self._markup_strokes)" in section
    assert "save refused, no strokes drawn" in section


def test_each_markup_step_is_logged_to_hey_jev_log_through_print():
    section = _markup_section(_ui_source())
    for line in ('markup: opened on', 'markup: saving', 'markup: saved', 'markup: cancelled', 'markup: save refused'):
        assert line in section, line
    assert "print(" in section


def test_the_save_uses_the_cos_tmp_temp_folder_the_full_screenshot_command_and_the_captures_name():
    section = _markup_section(_ui_source())
    assert "screenshot_command(\"full\", temp)" in section
    assert "capture_name(\"screenshot\", \"full\"" in section
    assert "os.remove(temp)" in section
    assert _re.search(r"markup_folder\(\)", section)
    assert '".cos-tmp"' not in section  # the path lives in markup.py, one place


def test_nothing_in_the_markup_code_uploads_or_opens_the_network():
    section = _markup_section(_ui_source())
    for banned in ("urlopen", "requests.", "http://", "https://", "NSURLSession", "socket"):
        assert banned not in section, banned


def test_the_overlay_takes_input_and_is_not_click_through():
    section = _markup_section(_ui_source())
    assert "def canBecomeKeyWindow(self):" in section and "def acceptsFirstResponder(self):" in section
    assert "window.setIgnoresMouseEvents_(False)" in section
    assert "colorWithCalibratedWhite_alpha_(0.0, 0.01)" in section  # near-clear, not fully transparent
    assert "key_window.makeKeyAndOrderFront_(None)" in section and "NSApp.activateIgnoringOtherApps_(True)" in section
    assert "self._markup_windows.append(window)" in section  # strong reference, so it is not collected


def test_the_hint_never_takes_a_click_and_the_cursor_stays_a_crosshair():
    section = _markup_section(_ui_source())
    assert "class MarkupHint(NSTextField)" in section
    assert "def hitTest_(self, _point):" in section and "return None" in section
    assert "Draw · ⌘Z undo · Return save · Esc cancel" in section
    assert "NSTrackingCursorUpdate" in section and "def cursorUpdate_" in section
    assert "NSCursor.crosshairCursor().set()" in section


def test_mouse_down_key_and_stroke_count_are_logged():
    section = _markup_section(_ui_source())
    for line in ("markup: mouse down at", "markup: mouse up,", "markup: key Esc", "markup: key Return", "markup: key command-Z"):
        assert line in section, line


def test_the_orb_panel_level_and_floating_flags_are_not_touched_in_the_markup_code():
    section = _markup_section(_ui_source())
    assert "self.mini_panel" not in section and "setFloatingPanel_(True)" not in section
