"""The orb's speech bubble (PR 8c): held back while docked, kept on screen otherwise, and logged either way."""
import ast
import os
import unittest

from mini_bar import ORB_EDGE_INSET, greeting_bubble_frame, orb_bubble_log_line

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function " + name)


class BubbleFrameTests(unittest.TestCase):
    def test_a_bubble_past_the_left_edge_is_pulled_inside(self):
        x, y, w, h = greeting_bubble_frame((-40.0, 20.0, 200.0, 34.0), (0.0, 0.0, 420.0, 300.0))
        self.assertGreaterEqual(x, ORB_EDGE_INSET)
        self.assertEqual((w, h), (200.0, 34.0))

    def test_a_bubble_past_the_right_edge_is_pulled_inside(self):
        x, _y, w, _h = greeting_bubble_frame((380.0, 20.0, 200.0, 34.0), (0.0, 0.0, 420.0, 300.0))
        self.assertLessEqual(x + w, 420.0 - ORB_EDGE_INSET + 1e-9)

    def test_a_bubble_already_inside_is_unchanged(self):
        frame = (100.0, 100.0, 200.0, 34.0)
        self.assertEqual(greeting_bubble_frame(frame, (0.0, 0.0, 420.0, 300.0)), frame)

    def test_a_bubble_wider_than_the_bounds_keeps_its_width(self):
        x, _y, w, _h = greeting_bubble_frame((-10.0, 20.0, 500.0, 34.0), (0.0, 0.0, 420.0, 300.0))
        self.assertEqual(w, 500.0)
        self.assertEqual(x, ORB_EDGE_INSET)


class BubbleLogTests(unittest.TestCase):
    def test_a_docked_bubble_logs_its_text_and_that_it_was_suppressed(self):
        line = orb_bubble_log_line("Hi, Fernando. What can I help with?", True)
        self.assertIn("suppressed while docked", line)
        self.assertIn("Hi, Fernando. What can I help with?", line)

    def test_a_shown_bubble_logs_its_text(self):
        line = orb_bubble_log_line("Hi there.", False)
        self.assertIn("orb bubble: shown", line)
        self.assertNotIn("suppressed", line)


class BubbleWiringTests(unittest.TestCase):
    def setUp(self):
        self.ui = _source("assistant_ui.py")

    def test_the_popover_hides_the_bubble_label_while_docked(self):
        layout = _func(self.ui, "_layout_mini_bar")
        self.assertIn("label.setHidden_(docked)", layout)
        self.assertIn("self._orb_bubble_docked()", layout)

    def test_the_bubble_frame_is_clamped_inside_the_popover(self):
        layout = _func(self.ui, "_layout_mini_bar")
        self.assertIn("greeting_bubble_frame(", layout)
        self.assertLess(layout.index("greeting_bubble_frame("), layout.index("_place(label"))

    def test_docked_means_the_full_window_or_the_orb_motion(self):
        docked = _func(self.ui, "_orb_bubble_docked")
        self.assertIn("self._orb_docked_now()", docked)
        self.assertIn("full.isVisible()", docked)

    def test_the_sync_path_also_hides_and_logs_the_bubble(self):
        sync = _func(self.ui, "_sync_orb")
        self.assertIn("label.setHidden_(docked or", sync)
        self.assertIn("self._log_orb_bubble(greeting_text(), docked)", sync)

    def test_the_log_is_written_once_per_change(self):
        log = _func(self.ui, "_log_orb_bubble")
        self.assertIn("if getattr(self, \"_orb_bubble_log_key\", None) == key:", log)
        self.assertIn("print(orb_bubble_log_line(text, docked), flush=True)", log)


if __name__ == "__main__":
    unittest.main()
