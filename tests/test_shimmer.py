"""PR 1 of the Eney animations: the loading shimmer on the result panel's pending line. Headless."""
import ast
import os
import unittest

import orb_motion as om

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _func(name):
    with open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8") as handle:
        source = handle.read()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


class PendingTextTests(unittest.TestCase):
    def test_ellipsis_lines_are_pending(self):
        self.assertTrue(om.is_pending_text("Reading the capture..."))
        self.assertTrue(om.is_pending_text("Reading the capture…"))
        self.assertTrue(om.is_pending_text("  Working...  "))

    def test_real_answers_are_not_pending(self):
        self.assertFalse(om.is_pending_text("A cat on a sofa."))
        self.assertFalse(om.is_pending_text("Wait... that was fast."))
        self.assertFalse(om.is_pending_text(""))
        self.assertFalse(om.is_pending_text(None))


class ShimmerMathTests(unittest.TestCase):
    def test_constants_are_calm(self):
        self.assertGreaterEqual(om.SHIMMER_SECONDS, 1.0)
        self.assertLessEqual(om.SHIMMER_SECONDS, 2.0)
        self.assertTrue(0.0 < om.SHIMMER_DIM < 1.0)
        self.assertTrue(0.0 < om.SHIMMER_BAND <= 1.0)

    def test_band_starts_off_the_left_and_ends_off_the_right(self):
        start = om.shimmer_locations(0.0)
        end = om.shimmer_locations(1.0)
        self.assertLessEqual(start[2], 0.0)
        self.assertGreaterEqual(end[0], 1.0)

    def test_locations_stay_in_order_and_keep_the_band_width(self):
        for step in range(11):
            low, mid, high = om.shimmer_locations(step / 10.0)
            self.assertLess(low, mid)
            self.assertLess(mid, high)
            self.assertAlmostEqual(high - low, om.SHIMMER_BAND)

    def test_the_sweep_moves_forward(self):
        centres = [om.shimmer_locations(step / 10.0)[1] for step in range(11)]
        self.assertEqual(centres, sorted(centres))


class WiringTests(unittest.TestCase):
    def test_shimmer_runs_only_for_pending_text(self):
        fill = _func("_fill_result_panel")
        self.assertIn("is_pending_text(text)", fill)
        self.assertIn("_shimmer_body(body)", fill)

    def test_reduce_motion_skips_the_sweep(self):
        body = _func("_shimmer_body")
        self.assertIn("reduceMotion", body)
        self.assertLess(body.index("reduceMotion"), body.index("CAGradientLayer.layer()"))
        self.assertIn("setAlphaValue_", body)

    def test_the_sweep_repeats_and_is_linear(self):
        body = _func("_shimmer_body")
        self.assertIn("setRepeatCount_", body)
        self.assertIn('"linear"', body)


if __name__ == "__main__":
    unittest.main()
