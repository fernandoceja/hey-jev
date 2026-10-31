"""PR 8: white pill eyes with no pupils, the left-edge dock, the drag hide hooks and the right-click menu wiring."""
import ast
import os
import unittest

import orb_motion as om
import orb_view
from orb_character import CLIPS, EYE_SHAPES, eye_shape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(module_source, name):
    for node in ast.walk(ast.parse(module_source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(module_source, node)
    raise AssertionError("no function named " + name)


class PillEyeTests(unittest.TestCase):
    def test_eyes_are_solid_white(self):
        self.assertEqual(om.EYE_EDGE_RGB, (1.0, 1.0, 1.0))

    def test_eyes_sit_right_of_centre_so_the_orb_looks_turned_right(self):
        geo = om.layer_geometry()
        left = geo["eyeL"][0] + geo["eyeL"][2] / 2.0
        right = geo["eyeR"][0] + geo["eyeR"][2] / 2.0
        self.assertGreater((left + right) / 2.0, om.DESIGN_CENTER)
        self.assertEqual(om.EYE_OFFSET_X, 2.0)

    def test_left_eye_is_a_little_larger_and_the_right_is_the_reference(self):
        kx, ky = om.EYE_PERSPECTIVE["L"]
        self.assertTrue(1.0 < kx <= 1.2 and 1.0 < ky <= 1.2)
        self.assertEqual(om.EYE_PERSPECTIVE["R"], (1.0, 1.0))

    def test_eyes_stay_inside_the_body_with_the_offset_and_perspective(self):
        geo = om.layer_geometry()
        lo, hi = om.BODY_ORIGIN, om.BODY_ORIGIN + om.BODY_SIZE
        for side in ("L", "R"):
            x, y, w, h = geo["eye" + side]
            kx, ky = om.EYE_PERSPECTIVE[side]
            self.assertGreaterEqual(x - (kx - 1) * w / 2, lo)
            self.assertLessEqual(x + w + (kx - 1) * w / 2, hi)

    def test_wide_and_squint_shapes_keep_the_shared_point_count(self):
        self.assertIn("squint", EYE_SHAPES)
        self.assertEqual(len(eye_shape("wide", 11.0)), len(eye_shape("squint", 11.0)))
        self.assertEqual(len(eye_shape("squint", 11.0)), len(eye_shape("open", 11.0)))

    def test_thinking_uses_a_squinted_pill_with_the_spinner(self):
        self.assertEqual(CLIPS["think_1"].eyes, ("squint", "squint"))
        self.assertTrue(CLIPS["think_1"].spinner)

    def test_pupils_are_hidden_and_cursor_tracking_is_off(self):
        self.assertFalse(orb_view.TRACK_PUPILS)
        self.assertIn("TRACK_PUPILS", _source("orb_view.py"))
        self.assertIn("pupil.setHidden_(True)", _source("orb_layers.py"))


class DockWiringTests(unittest.TestCase):
    def test_dock_point_is_centred_on_the_left_edge_at_mid_height(self):
        x, y, w, h = om.dock_point((100.0, 100.0, 760.0, 560.0))
        self.assertAlmostEqual(x + w / 2.0, 100.0)
        self.assertAlmostEqual(y + h / 2.0, 100.0 + 560.0 / 2.0)


class DragAndMenuWiringTests(unittest.TestCase):
    def test_drag_hides_the_pill_and_release_slides_it_back(self):
        ui = _source("assistant_ui.py")
        self.assertIn("_notify_pill_drag(delegate, began=True)", _func(ui, "_drag_with_spring"))
        self.assertIn("_notify_pill_drag(delegate, began=False)", _func(ui, "_drag_with_spring"))
        self.assertIn("_pill_drag_ended", _func(ui, "_notify_pill_drag"))
        self.assertIn("setHidden_(True)", _func(ui, "_pill_drag_began"))
        ended = _func(ui, "_pill_drag_ended")
        self.assertIn("setDuration_(PILL_SLIDE_SECONDS)", ended)
        self.assertIn('functionWithName_("easeOut")', ended)
        self.assertIn("PILL_SLIDE_SECONDS = 0.18", ui)

    def test_right_click_menu_lists_the_popover_actions(self):
        menu = _func(_source("assistant_ui.py"), "_orb_context_menu")
        for title in ("Open Jev", "New Chat", "Capture Area", "Mark Up", "Type to Jev", "Settings", "Quit Jev"):
            self.assertIn(title, menu)
        self.assertIn("NSApp", menu)

    def test_popover_still_reachable_from_control_option_j(self):
        mini = _source("mini_bar.py")
        self.assertIn("Control-Option-J", mini)
        self.assertIn('"focusTypeField:"', _source("assistant_ui.py"))


if __name__ == "__main__":
    unittest.main()
