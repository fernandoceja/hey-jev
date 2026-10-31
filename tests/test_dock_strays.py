"""Nothing but the orb is drawn beside a docked orb (PR 8c): strays are logged and closed, the popover is hidden, and
both come back on collapse."""
import ast
import os
import unittest

from orb_motion import dock_strip, rects_overlap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function " + name)


class StripTests(unittest.TestCase):
    def test_the_strip_reaches_well_past_the_orb_to_the_left(self):
        x, y, w, h = dock_strip((500.0, 300.0, 96.0, 96.0))
        self.assertLess(x, 300.0)
        self.assertGreater(x + w, 596.0)
        self.assertLess(y, 300.0)
        self.assertGreater(y + h, 396.0)

    def test_a_window_to_the_left_of_the_orb_overlaps_the_strip(self):
        strip = dock_strip((500.0, 300.0, 96.0, 96.0))
        self.assertTrue(rects_overlap((380.0, 320.0, 60.0, 40.0), strip))

    def test_a_window_far_away_does_not(self):
        strip = dock_strip((500.0, 300.0, 96.0, 96.0))
        self.assertFalse(rects_overlap((10.0, 10.0, 100.0, 100.0), strip))

    def test_touching_edges_do_not_count_as_overlap(self):
        self.assertFalse(rects_overlap((0.0, 0.0, 10.0, 10.0), (10.0, 0.0, 10.0, 10.0)))


class DockWiringTests(unittest.TestCase):
    def setUp(self):
        self.ui = _source("assistant_ui.py")

    def test_the_dock_logs_and_closes_strays_before_the_orb_syncs(self):
        land = _func(self.ui, "_land_orb_expand")
        self.assertIn("self._clear_dock_strays()", land)
        self.assertLess(land.index("self._clear_dock_strays()"), land.index("self._sync_orb()"))
        self.assertIn("self._apply_dock_visibility()", land)

    def test_the_stray_pass_logs_child_windows_and_nearby_windows(self):
        strays = _func(self.ui, "_clear_dock_strays")
        self.assertIn('print("dock: child window', strays)
        self.assertIn('print("dock: stray window', strays)
        self.assertIn("rects_overlap(frame, strip)", strays)
        self.assertIn("window.orderOut_(None)", strays)
        self.assertIn('self._close_orb_spotlight("dock")', strays)

    def test_the_popover_views_are_hidden_while_docked_and_logged_once(self):
        hide = _func(self.ui, "_apply_dock_visibility")
        self.assertIn('print("dock: hid {0} frame', hide)
        self.assertIn("view.setHidden_(True)", hide)
        self.assertIn("if id(view) in keep:", hide)  # the orb and its ancestors are never hidden

    def test_collapse_restores_the_popover_views(self):
        collapse = _func(self.ui, "_land_orb_collapse")
        self.assertIn("self._apply_dock_visibility()", collapse)
        restore = _func(self.ui, "_apply_dock_visibility")
        self.assertIn("view.setHidden_(was_hidden)", restore)
        self.assertIn("self._layout_mini_bar(", restore)

    def test_a_sync_or_layout_pass_cannot_show_views_beside_a_docked_orb(self):
        self.assertIn("self._apply_dock_visibility()", _func(self.ui, "_sync_orb"))
        self.assertIn("self._apply_dock_visibility()", _func(self.ui, "_layout_mini_bar"))


if __name__ == "__main__":
    unittest.main()
