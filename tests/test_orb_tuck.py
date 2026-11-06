"""PR 8: the edge tuck. Edge detection, tucked and untucked frames, eye layout and the persisted value. Headless."""
import unittest

import orb_tuck as ot

SCREEN = (0.0, 0.0, 1440.0, 900.0)
SIZE = (72.0, 72.0)


class EdgeDetectionTests(unittest.TestCase):
    def test_left_and_right_within_24_points_tuck(self):
        self.assertEqual(ot.tuck_edge((10.0, 400.0, 72.0, 72.0), SCREEN, [SCREEN]), "left")
        self.assertEqual(ot.tuck_edge((1440.0 - 72.0 - 20.0, 400.0, 72.0, 72.0), SCREEN, [SCREEN]), "right")

    def test_exactly_at_the_24_point_limit_still_tucks(self):
        self.assertEqual(ot.tuck_edge((24.0, 400.0, 72.0, 72.0), SCREEN, [SCREEN]), "left")

    def test_just_beyond_the_limit_does_not_tuck(self):
        self.assertIsNone(ot.tuck_edge((25.0, 400.0, 72.0, 72.0), SCREEN, [SCREEN]))
        self.assertIsNone(ot.tuck_edge((1440.0 - 72.0 - 25.0, 400.0, 72.0, 72.0), SCREEN, [SCREEN]))

    def test_middle_of_the_screen_does_not_tuck(self):
        self.assertIsNone(ot.tuck_edge((700.0, 400.0, 72.0, 72.0), SCREEN, [SCREEN]))

    def test_an_orb_above_or_below_the_screen_does_not_tuck(self):
        self.assertIsNone(ot.tuck_edge((10.0, 1000.0, 72.0, 72.0), SCREEN, [SCREEN]))
        self.assertIsNone(ot.tuck_edge((10.0, -200.0, 72.0, 72.0), SCREEN, [SCREEN]))

    def test_a_shared_edge_with_another_display_is_never_a_tuck_edge(self):
        left_display = (-1440.0, 0.0, 1440.0, 900.0)
        self.assertIsNone(ot.tuck_edge((10.0, 400.0, 72.0, 72.0), SCREEN, [SCREEN, left_display]))
        self.assertEqual(ot.tuck_edge((1440.0 - 72.0 - 5.0, 400.0, 72.0, 72.0), SCREEN, [SCREEN, left_display]),
                         "right")

    def test_bad_input_returns_none(self):
        self.assertIsNone(ot.tuck_edge(("x", 0, 1, 1), SCREEN, [SCREEN]))


class TuckedFrameTests(unittest.TestCase):
    def test_left_tuck_puts_the_window_edge_on_the_screen_edge(self):
        x, _y, w, _h = ot.tucked_frame(SIZE, SCREEN, "left", 300.0)
        self.assertAlmostEqual(x + w / 2.0, 0.0)  # the body centre is on the edge, so half is off screen

    def test_right_tuck_puts_the_window_edge_on_the_right_screen_edge(self):
        x, _y, w, _h = ot.tucked_frame(SIZE, SCREEN, "right", 300.0)
        self.assertAlmostEqual(x + w / 2.0, 1440.0)

    def test_tucked_height_is_kept_and_stays_on_screen(self):
        self.assertEqual(ot.tucked_frame(SIZE, SCREEN, "left", 300.0)[1], 300.0)
        self.assertEqual(ot.tucked_frame(SIZE, SCREEN, "left", -500.0)[1], 0.0)
        self.assertEqual(ot.tucked_frame(SIZE, SCREEN, "left", 5000.0)[1], 900.0 - 72.0)

    def test_untucked_frame_rests_inset_from_the_edge(self):
        self.assertEqual(ot.untucked_frame(SIZE, SCREEN, "left", 300.0)[0], ot.TUCK_INSET)
        self.assertEqual(ot.untucked_frame(SIZE, SCREEN, "right", 300.0)[0], 1440.0 - 72.0 - ot.TUCK_INSET)

    def test_tuck_and_untuck_share_the_same_height(self):
        tucked = ot.tucked_frame(SIZE, SCREEN, "left", 412.0)
        untucked = ot.untucked_frame(SIZE, SCREEN, "left", 412.0)
        self.assertEqual(tucked[1], untucked[1])

    def test_a_screen_with_a_nonzero_origin_is_respected(self):
        screen = (-1440.0, 60.0, 1440.0, 800.0)
        x, y, _w, _h = ot.tucked_frame(SIZE, screen, "left", 100.0)
        self.assertAlmostEqual(x + 36.0, -1440.0)
        self.assertEqual(y, 100.0)

    def test_unknown_edge_is_rejected(self):
        with self.assertRaises(ValueError):
            ot.tucked_frame(SIZE, SCREEN, "top", 0.0)
        with self.assertRaises(ValueError):
            ot.untucked_frame(SIZE, SCREEN, "top", 0.0)


class EyeLayoutTests(unittest.TestCase):
    HORIZONTAL = {"L": (32.5, 40.0), "R": (48.5, 40.0)}

    def test_not_tucked_keeps_the_horizontal_layout(self):
        self.assertEqual(ot.tuck_eye_centres(None, self.HORIZONTAL), self.HORIZONTAL)

    def test_tucked_eyes_stack_vertically_on_the_screen_side_of_the_body(self):
        left = ot.tuck_eye_centres("left", self.HORIZONTAL)
        self.assertEqual(left["L"][0], left["R"][0])  # same column: stacked, not side by side
        self.assertNotEqual(left["L"][1], left["R"][1])
        self.assertGreater(left["L"][0], 36.0)  # a left tuck faces right, into the screen
        right = ot.tuck_eye_centres("right", self.HORIZONTAL)
        self.assertLess(right["L"][0], 36.0)

    def test_tucked_eyes_stay_inside_the_body_circle(self):
        import math
        for edge in ("left", "right"):
            for centre in ot.tuck_eye_centres(edge, self.HORIZONTAL).values():
                self.assertLessEqual(math.hypot(centre[0] - 36.0, centre[1] - 36.0), 28.0 - 2.0)

    def test_close_button_sits_outside_the_body_on_the_screen_side(self):
        import math
        x, y = ot.tuck_close_centre("left")
        self.assertGreater(x, 36.0)
        self.assertGreater(y, 36.0)
        self.assertGreater(math.hypot(x - 36.0, y - 36.0), 28.0)  # clear of the round body
        self.assertLessEqual(x + ot.TUCK_CLOSE_SIZE / 2.0, 72.0)
        self.assertLessEqual(y + ot.TUCK_CLOSE_SIZE / 2.0, 72.0)
        self.assertLess(ot.tuck_close_centre("right")[0], 36.0)


class PersistenceTests(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(ot.decode_tuck(ot.encode_tuck("left", 412.25)), ("left", 412.2))
        self.assertEqual(ot.decode_tuck(ot.encode_tuck("right", 0.0)), ("right", 0.0))

    def test_bad_or_missing_values_decode_to_none(self):
        for bad in (None, "", "top:10", "left:", "left:nan", "left", "right:inf", "garbage"):
            self.assertIsNone(ot.decode_tuck(bad), bad)

    def test_encode_rejects_unknown_edges(self):
        with self.assertRaises(ValueError):
            ot.encode_tuck("top", 1.0)

    def test_the_pref_key_is_the_documented_one(self):
        self.assertEqual(ot.TUCK_KEY, "orb_tuck")
        self.assertEqual(ot.TUCK_EDGE_DISTANCE, 24.0)
        self.assertEqual(ot.TUCK_SECONDS, 0.9)


import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


class TuckWiringTests(unittest.TestCase):
    def test_presentation_pass_holds_a_tucked_orb(self):
        ui = _source("assistant_ui.py")
        self.assertIn("_tuck_active", _func(ui, "_apply_pill_presentation"))

    def test_peek_stays_out_of_a_tucked_orb(self):
        self.assertIn("_tuck_active", _func(_source("assistant_ui.py"), "_peek_consider"))

    def test_typing_pill_untucks_first(self):
        self.assertIn('_tuck_untuck("typing"', _func(_source("assistant_ui.py"), "expandMiniBar_"))

    def test_a_drop_near_an_edge_tucks_instead_of_peeking(self):
        finalize = _func(_source("assistant_ui.py"), "_finalize_mini_bar_drag")
        self.assertIn("_tuck_consider", finalize)
        self.assertIn("if not tucked:", finalize)

    def test_press_untucks_on_drag_and_slides_out_then_opens_on_click(self):
        press = _func(_source("assistant_ui.py"), "_tuck_press")
        self.assertIn('_tuck_untuck("drag", instant=True)', press)
        self.assertIn('_tuck_untuck("click", instant=False', press)
        self.assertIn("expandOrbToFull_", press)

    def test_log_lines_match_the_spec(self):
        ui = _source("assistant_ui.py")
        self.assertIn('"orb tuck: edge={0} y={1:.1f}"', ui)
        self.assertIn('"orb untuck: reason={0}"', ui)

    def test_close_button_hides_the_orb_like_the_existing_hide_action(self):
        close = _func(_source("assistant_ui.py"), "tuckCloseClicked_")
        self.assertIn("hideMiniBar_", close)
        self.assertIn('"xmark"', _source("assistant_ui.py"))

    def test_relaunch_restores_the_tuck_from_the_saved_pref(self):
        self.assertIn("_tuck_restore", _func(_source("assistant_ui.py"), "_order_bar_front"))

    def test_new_layers_never_use_shadow_path_and_set_contents_scale(self):
        for name in ("assistant_ui.py", "orb_layers.py", "orb_tuck.py"):
            self.assertNotIn("shadowPath", _source(name), name)
        self.assertIn("setContentsScale_", _func(_source("assistant_ui.py"), "_tuck_button"))

    def test_the_orb_panel_level_is_never_changed_by_the_tuck(self):
        self.assertNotIn("setLevel_", _func(_source("assistant_ui.py"), "_tuck_engage"))
        self.assertNotIn("setLevel_", _func(_source("assistant_ui.py"), "_tuck_move"))


if __name__ == "__main__":
    unittest.main()
