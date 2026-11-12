"""The orb settles at the selection's corner and an inline "What is this?" field pops up beside it. Headless."""
import ast
import math
import os
import unittest

import capture_glimmer as cg
import capture_inline as ci

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN = (0.0, 0.0, 1710.0, 1107.0)
ORB = (72.0, 72.0)
RECT = (300.0, 500.0, 420.0, 220.0)


def _ui():
    with open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


class CornerTests(unittest.TestCase):
    def test_the_corner_nearest_the_release_point_is_picked(self):
        self.assertEqual(ci.pick_corner(RECT, (715, 505)), "br")
        self.assertEqual(ci.pick_corner(RECT, (305, 505)), "bl")
        self.assertEqual(ci.pick_corner(RECT, (305, 715)), "tl")
        self.assertEqual(ci.pick_corner(RECT, (715, 715)), "tr")

    def test_a_missing_or_bad_release_point_defaults_to_bottom_right(self):
        for bad in (None, (), (float("nan"), 3), ("x", "y")):
            self.assertEqual(ci.pick_corner(RECT, bad), "br")

    def test_the_orb_centre_sits_just_outside_the_chosen_corner(self):
        for corner, (cx, cy, dx, dy) in {"br": (720, 500, 1, -1), "bl": (300, 500, -1, -1),
                                         "tr": (720, 720, 1, 1), "tl": (300, 720, -1, 1)}.items():
            ox, oy = ci.orb_target_origin(RECT, corner, ORB, SCREEN)
            centre = (ox + ORB[0] / 2, oy + ORB[1] / 2)
            self.assertAlmostEqual(centre[0], cx + dx * ci.CORNER_PUSH * ORB[0])
            self.assertAlmostEqual(centre[1], cy + dy * ci.CORNER_PUSH * ORB[1])

    def test_the_orb_never_leaves_the_screen(self):
        for rect in ((0, 0, 50, 50), (1680, 1090, 30, 17), (-5, 400, 20, 20), (1700, 0, 10, 10)):
            for corner in ci.CORNERS:
                ox, oy = ci.orb_target_origin(rect, corner, ORB, SCREEN)
                self.assertTrue(SCREEN[0] <= ox <= SCREEN[0] + SCREEN[2] - ORB[0], (rect, corner, ox))
                self.assertTrue(SCREEN[1] <= oy <= SCREEN[1] + SCREEN[3] - ORB[1], (rect, corner, oy))

    def test_a_second_display_with_a_negative_origin_works(self):
        screen = (-1440.0, 0.0, 1440.0, 900.0)
        ox, oy = ci.orb_target_origin((-1000, 100, 200, 100), "bl", ORB, screen)
        self.assertTrue(-1440.0 <= ox <= -ORB[0])


class InlineFrameTests(unittest.TestCase):
    def test_the_pill_sits_to_the_right_of_the_orb_when_it_fits(self):
        x, y, w, h, side = ci.inline_frame((700, 450, 72, 72), SCREEN, ci.pill_size())
        self.assertEqual(side, "right")
        self.assertAlmostEqual(x, 700 + 72 + ci.SIDE_GAP)
        self.assertAlmostEqual(y + h / 2.0, 450 + 36.0)  # the field row is level with the orb

    def test_it_flips_to_the_left_near_the_right_edge(self):
        x, y, w, h, side = ci.inline_frame((1600, 450, 72, 72), SCREEN, ci.pill_size())
        self.assertEqual(side, "left")
        self.assertLess(x + w, 1600)

    def test_it_stays_inside_the_screen_in_every_corner(self):
        for orb in ((0, 0, 72, 72), (1638, 0, 72, 72), (0, 1035, 72, 72), (1638, 1035, 72, 72)):
            x, y, w, h, _ = ci.inline_frame(orb, SCREEN, ci.pill_size("word " * 60))
            self.assertTrue(0 <= x and x + w <= 1710 and 0 <= y and y + h <= 1107, orb)

    def test_an_answer_grows_the_pill_downward_keeping_the_field_row_put(self):
        orb = (700, 600, 72, 72)
        _x, y1, _w, h1, _ = ci.inline_frame(orb, SCREEN, ci.pill_size())
        _x, y2, _w, h2, _ = ci.inline_frame(orb, SCREEN, ci.pill_size("an answer that takes a few lines to say " * 3))
        self.assertGreater(h2, h1)
        self.assertAlmostEqual(y1 + h1, y2 + h2)  # the top edge does not move

    def test_answer_lines_wrap_and_are_capped(self):
        self.assertEqual(ci.answer_lines(""), 1)
        self.assertEqual(ci.answer_lines("short"), 1)
        self.assertEqual(ci.answer_lines("word " * 200), ci.ANSWER_MAX_LINES)
        self.assertEqual(ci.answer_lines("x" * 100), 3)
        self.assertGreater(ci.answer_lines("one two three four five six seven eight nine ten eleven twelve thirteen"), 1)

    def test_the_pill_without_an_answer_is_just_the_field_row(self):
        self.assertEqual(ci.pill_size(), (ci.FIELD_W, ci.FIELD_H))
        self.assertEqual(ci.pill_size(""), (ci.FIELD_W, ci.FIELD_H))


class AnswerTextTests(unittest.TestCase):
    def test_markdown_emphasis_and_ticks_are_removed(self):
        self.assertEqual(ci.tidy_answer("This is **Rosalina** from *Galaxy* with `code`."), "This is Rosalina from Galaxy with code.")
        self.assertEqual(ci.tidy_answer("a  \n b\t c"), "a b c")
        self.assertEqual(ci.tidy_answer(None), "")

    def test_a_star_that_is_not_emphasis_is_kept(self):
        self.assertEqual(ci.tidy_answer("5 * 3 = 15"), "5 * 3 = 15")

    def test_a_short_answer_is_left_alone(self):
        self.assertEqual(ci.clip_answer("A cat on a sofa."), "A cat on a sofa.")

    def test_a_long_answer_is_cut_at_a_word_with_an_ellipsis_and_fits(self):
        text = "word " * 120
        clipped = ci.clip_answer(text)
        self.assertTrue(clipped.endswith("\u2026"))
        self.assertLessEqual(ci.answer_lines(clipped), ci.ANSWER_MAX_LINES)
        self.assertFalse(clipped[:-1].endswith(" "))
        self.assertLess(len(clipped), len(text))


class AcceptSuggestionTests(unittest.TestCase):
    def test_tab_and_right_arrow_accept_the_suggestion_in_an_empty_field(self):
        self.assertEqual(ci.accepted_text("", "insertTab:"), "What is this?")
        self.assertEqual(ci.accepted_text("", "moveRight:"), "What is this?")
        self.assertEqual(ci.accepted_text(None, "moveRight:"), "What is this?")

    def test_with_any_text_they_keep_their_normal_meaning(self):
        for text in ("a", "What is this?", " ", "hello world"):
            self.assertIsNone(ci.accepted_text(text, "moveRight:"), text)
            self.assertIsNone(ci.accepted_text(text, "insertTab:"), text)

    def test_other_keys_never_accept_it(self):
        for selector in ("cancelOperation:", "insertNewline:", "moveLeft:", "moveDown:", "deleteBackward:", ""):
            self.assertIsNone(ci.accepted_text("", selector), selector)

    def test_the_wiring_sets_the_text_with_the_caret_at_the_end_and_leaves_escape_alone(self):
        ui = _ui()
        body = _func(ui, "control_textView_doCommandBySelector_")
        inline = body[:body.index("surface = self._at_surface_for(control)")]
        self.assertIn('control == getattr(self, "inline_field", None)', inline)
        self.assertIn("_view.setString_(accepted)", inline)
        self.assertIn("_view.setSelectedRange_((len(accepted), 0))", inline)
        self.assertIn("return False", inline)  # anything else, including Esc, falls through to the default
        self.assertNotIn("cancelOperation", inline)
        self.assertIn("self.inline_field.setDelegate_(self)", _func(ui, "_build_inline_panel"))
        # Esc still opens the capture panel through the panel's handler.
        self.assertIn("panel.escHandler = self._inline_open_capture_panel", _func(ui, "_build_inline_panel"))


class RuleTests(unittest.TestCase):
    def test_only_a_visible_quiet_collapsed_orb_with_a_rect_moves(self):
        self.assertTrue(ci.should_start(True, True, False, False, True))
        for args in ((False, True, False, False, True), (True, False, False, False, True),
                     (True, True, True, False, True), (True, True, False, True, True), (True, True, False, False, False)):
            self.assertFalse(ci.should_start(*args), args)

    def test_the_field_closes_after_a_quiet_stretch_unless_hovered_or_editing(self):
        self.assertTrue(ci.idle_expired(0.0, ci.IDLE_SECONDS + 1, False, False))
        self.assertFalse(ci.idle_expired(0.0, ci.IDLE_SECONDS - 1, False, False))
        self.assertFalse(ci.idle_expired(0.0, ci.IDLE_SECONDS + 100, True, False))
        self.assertFalse(ci.idle_expired(0.0, ci.IDLE_SECONDS + 100, False, True))

    def test_the_placeholder_is_what_is_this(self):
        self.assertEqual(ci.PLACEHOLDER, "What is this?")


class ReleasePointTests(unittest.TestCase):
    def test_the_tracker_reports_where_the_button_came_up(self):
        t = cg.DragTracker()
        for point, down in [((0, 0), False), ((10, 10), True), ((60, 50), True), ((130, 90), True), ((130, 90), False)]:
            t.feed(point, down)
        self.assertEqual(t.release_point(), (130, 90))
        self.assertEqual(t.rect(), (10.0, 10.0, 120.0, 80.0))

    def test_no_drag_means_no_release_point(self):
        t = cg.DragTracker()
        t.feed((0, 0), False)
        self.assertIsNone(t.release_point())


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.ui = _ui()

    def test_only_the_area_capture_path_asks_for_the_inline_field(self):
        body = _func(self.ui, "_capture_for_bar")
        self.assertIn('self._inline_expected = mode == "area"', body)
        self.assertIn("finally:", body)
        self.assertIn("self._inline_expected = False", body)
        finish = _func(self.ui, "_glimmer_finish")
        self.assertIn('"inline": bool(getattr(self, "_inline_expected", False))', finish)
        self.assertIn('"release"', finish)

    def test_the_inline_route_runs_after_the_glimmer_and_before_the_capture_panel(self):
        body = _func(self.ui, "_show_capture_choices")
        self.assertLess(body.index("panel_delay("), body.index("_inline_begin(pending)"))
        self.assertLess(body.index("_inline_begin(pending)"), body.index("from commands.captures import BOOK"))
        self.assertIn("return  # the capture panel opens later", body)

    def test_a_refused_start_falls_back_to_the_capture_panel(self):
        body = _func(self.ui, "_inline_begin")
        self.assertIn("inline_should_start(", body)
        self.assertIn("return False", body)
        self.assertIn("self._tuck_untuck(", body)

    def test_the_capture_panel_opens_only_from_a_second_click_or_escape(self):
        click = _func(self.ui, "expandOrbToFull_")
        self.assertLess(click.index("_inline_open_capture_panel()"), click.index("_close_orb_spotlight"))
        key = _func(self.ui, "_local_key")
        self.assertLess(key.index("_inline_open_capture_panel()"), key.index('getattr(self, "_at", None)'))
        opener = _func(self.ui, "_inline_open_capture_panel")
        self.assertIn("self._inline_end(restore=False)", opener)
        self.assertIn("self._show_capture_choices()", opener)
        # Nothing else opens the capture panel while the inline field is up: enter and the answer never call it.
        for name in ("inlineAsk_", "_inline_set_answer", "inlineShow_"):
            self.assertNotIn("_show_capture_choices", _func(self.ui, name), name)

    def test_the_panel_class_sends_escape_to_the_inline_handler(self):
        cls = self.ui[self.ui.index("class CaptureChoicePanel"):self.ui.index("# PR 8: the orb's Spotlight-style")]
        self.assertIn("def cancelOperation_", cls)
        self.assertIn("escHandler", cls)
        self.assertIn("panel.escHandler = self._inline_open_capture_panel", _func(self.ui, "_build_inline_panel"))

    def test_return_asks_on_the_existing_ask_path_with_the_default_question(self):
        body = _func(self.ui, "inlineAsk_")
        self.assertIn('self.controls.put(("ask_jev", question))', body)
        self.assertIn("INLINE_PLACEHOLDER", body)
        self.assertIn("PENDING_CAPTURE_TEXT", body)
        self.assertIn("self._inline_waiting = True", body)

    def test_the_answer_shows_inline_only_after_asking_and_stops_the_shimmer(self):
        update = _func(self.ui, "updateStatus_")
        self.assertIn('getattr(self, "_inline_waiting", False)', update)
        self.assertIn("self._inline_set_answer(shown, pending=False)", update)
        body = _func(self.ui, "_inline_set_answer")
        self.assertIn("self._stop_shimmer(self.inline_answer)", body)
        self.assertIn("self._shimmer_body(self.inline_answer)", body)

    def test_reduce_motion_moves_the_orb_without_a_spring_and_skips_the_pop(self):
        move = _func(self.ui, "_inline_move_orb")
        self.assertIn("if reduce or", move)
        self.assertLess(move.index("if reduce or"), move.index("NSTimer.scheduledTimer"))
        show = _func(self.ui, "inlineShow_")
        self.assertIn("if not self._inline_reduce():", show)
        tick = _func(self.ui, "inlineMoveTick_")
        self.assertIn('self._orb_hop("landed")', tick)  # the hop is a reaction, so Reduce Motion handles itself

    def test_the_move_uses_the_orbs_existing_snap_spring(self):
        self.assertIn("*SPRING_SNAP", _func(self.ui, "inlineMoveTick_"))

    def test_ending_the_session_can_send_the_orb_home_or_leave_it(self):
        body = _func(self.ui, "_inline_end")
        self.assertIn("if restore and home is not None", body)
        self.assertIn("self._inline_move_orb(home)", body)
        self.assertIn("self._inline_active = False", body)

    def test_dragging_the_orb_or_pressing_the_hotkey_ends_it_where_the_orb_is(self):
        self.assertIn("self._inline_end(restore=False)", _func(self.ui, "_pill_drag_began"))
        self.assertIn("self._inline_end(restore=False)", _func(self.ui, "focusTypeField_"))

    def test_the_orb_stays_out_of_the_peek_dock_while_the_field_is_up(self):
        self.assertIn("self._inline_active_now()", _func(self.ui, "_peek_is_busy"))

    def test_a_quiet_field_closes_by_itself_on_the_tick(self):
        self.assertIn("self._inline_sync()", _func(self.ui, "tick_"))
        sync = _func(self.ui, "_inline_sync")
        self.assertIn("inline_idle_expired(", sync)
        self.assertIn("self._inline_end(restore=True)", sync)

    def test_the_inline_panel_is_key_capable_and_never_blocks_other_apps(self):
        build = _func(self.ui, "_build_inline_panel")
        self.assertIn("CaptureChoicePanel.alloc()", build)
        self.assertIn("NSWindowStyleMaskNonactivatingPanel", build)
        self.assertIn("setBecomesKeyOnlyIfNeeded_(True)", build)
        self.assertIn("setHidesOnDeactivate_(False)", build)

    def test_the_main_pill_stays_out_of_the_way_while_the_inline_field_is_up(self):
        update = _func(self.ui, "updateStatus_")
        self.assertIn("and not self._inline_active_now()", update[update.index("show_line = "):update.index("displayed = False")])

    def test_the_saved_sentence_is_not_pushed_into_the_orb_on_the_inline_route(self):
        body = _func(self.ui, "showCaptureResult_")
        self.assertIn('getattr(self, "_inline_pending", None)', body)
        self.assertLess(body.index("capture_saved(sentence)"), body.index("self._show_bar_reply("))

    def test_the_reply_is_tidied_and_clipped_before_it_is_shown(self):
        body = _func(self.ui, "_inline_set_answer")
        self.assertIn("clip_answer(tidy_answer(text))", body)

    def test_the_inline_field_is_laid_out_beside_the_orb_inside_the_screen(self):
        body = _func(self.ui, "_inline_layout")
        self.assertIn("inline_frame(", body)
        self.assertIn("pill_size(answer)", body)


if __name__ == "__main__":
    unittest.main()
