"""Eney animations, item 4: the result panel's Copy pill pops and says Copied. Headless."""
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


class CopyPopTests(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(om.copy_pill_title(False), "Copy")
        self.assertIn("Copied", om.copy_pill_title(True))

    def test_done_title_fits_the_pill(self):
        self.assertLessEqual(len(om.copy_pill_title(True)), 9)

    def test_constants_are_short_and_calm(self):
        self.assertTrue(1.0 < om.COPY_POP_SCALE <= 1.2)
        self.assertLessEqual(om.COPY_POP_SECONDS, 0.3)
        self.assertTrue(0.4 <= om.COPY_CLOSE_DELAY <= 1.0)
        self.assertGreater(om.COPY_CLOSE_DELAY, om.COPY_POP_SECONDS)


class WiringTests(unittest.TestCase):
    def test_copy_still_writes_the_clipboard_then_pops_and_closes_after_a_beat(self):
        body = _func("resultCopy_")
        self.assertLess(body.index("setString_forType_"), body.index("_pop_copy_pill(sender)"))
        self.assertIn("COPY_CLOSE_DELAY", body)
        self.assertNotIn("self._close_result_panel()", body)  # it no longer closes at once

    def test_reduce_motion_swaps_the_label_and_does_not_animate(self):
        body = _func("_pop_copy_pill")
        self.assertIn("setTitle_(copy_pill_title(True))", body)
        self.assertIn("reduceMotion", body)
        self.assertLess(body.index("reduceMotion"), body.index("addAnimation_forKey_"))

    def test_the_pop_scales_about_the_centre_and_reverses(self):
        body = _func("_pop_copy_pill")
        self.assertIn("setAutoreverses_(True)", body)
        self.assertIn("CATransform3DMakeTranslation(-w / 2.0, -h / 2.0, 0.0)", body)

    def test_a_new_result_cancels_the_pending_close(self):
        self.assertIn("cancelPreviousPerformRequestsWithTarget_selector_object_", _func("_present_result"))


if __name__ == "__main__":
    unittest.main()
