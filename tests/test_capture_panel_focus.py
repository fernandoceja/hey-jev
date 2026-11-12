"""The post-capture panel takes keyboard focus, and its answer line shimmers while Jev reads the picture."""
import ast
import os
import unittest

import orb_motion as om

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


def _class(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no class named " + name)


class KeyFocusTests(unittest.TestCase):
    def setUp(self):
        self.ui = _source("assistant_ui.py")

    def test_the_panel_class_can_become_key_but_never_main(self):
        body = _class(self.ui, "CaptureChoicePanel")
        self.assertIn("(NSPanel)", body)
        key = body[body.index("def canBecomeKeyWindow"):body.index("def canBecomeMainWindow")]
        self.assertIn("return True", key)
        self.assertIn("return False", body[body.index("def canBecomeMainWindow"):])

    def test_the_choice_panel_is_built_from_that_class_and_stays_nonactivating(self):
        build = _func(self.ui, "_build_choice_panel")
        self.assertIn("CaptureChoicePanel.alloc()", build)
        self.assertNotIn("NSPanel.alloc()", build)
        self.assertIn("NSWindowStyleMaskNonactivatingPanel", build)
        self.assertIn("setBecomesKeyOnlyIfNeeded_(True)", build)  # still key only when a field needs it

    def test_asking_jev_focuses_the_question_field(self):
        body = _func(self.ui, "_open_choice_question")
        self.assertLess(body.index("makeKeyAndOrderFront_"), body.index("makeFirstResponder_(self.choice_question)"))

    def test_the_cleanup_confirm_is_left_alone(self):
        confirm = _source("commands/storage_scan_ui.py")
        self.assertNotIn("CaptureChoicePanel", confirm)
        self.assertIn("setRefusesFirstResponder_(True)", confirm)  # #130: the confirm button still cannot take keyboard focus

    def test_a_borderless_panel_really_cannot_become_key_without_the_subclass(self):
        try:
            from AppKit import (NSBackingStoreBuffered, NSMakeRect, NSPanel, NSWindowStyleMaskBorderless,
                                NSWindowStyleMaskNonactivatingPanel)
            import assistant_ui as ui
        except Exception as exc:  # AppKit is not available off the Mac
            self.skipTest(str(exc))
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        rect = NSMakeRect(0, 0, 300, 420)
        plain = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(rect, style, NSBackingStoreBuffered, False)
        mine = ui.CaptureChoicePanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False)
        self.assertFalse(plain.canBecomeKeyWindow())
        self.assertTrue(mine.canBecomeKeyWindow())
        self.assertFalse(mine.canBecomeMainWindow())


class CommandWShimmerTests(unittest.TestCase):
    def setUp(self):
        self.ui = _source("assistant_ui.py")

    def test_the_pending_text_counts_as_pending(self):
        self.assertTrue(om.is_pending_text(om.PENDING_CAPTURE_TEXT))
        self.assertTrue(om.PENDING_CAPTURE_TEXT.startswith("Reading the capture"))

    def test_the_hotkey_path_ends_on_the_choice_panel(self):
        wand = _func(self.ui, "captureAreaWand_")
        self.assertIn("target=self._capture_for_bar", wand)
        self.assertIn("_show_capture_choices", _func(self.ui, "_maybe_show_choices"))

    def test_asking_on_the_choice_panel_shows_the_pending_line_and_shimmers_it(self):
        ask = _func(self.ui, "choiceAsk_")
        self.assertIn("PENDING_CAPTURE_TEXT", ask)
        self.assertIn("_shimmer_body(self.choice_answer)", ask)
        self.assertLess(ask.index("self.controls.put"), ask.index("_shimmer_body(self.choice_answer)"))
        self.assertLess(ask.index("Add your API keys"), ask.index("_shimmer_body(self.choice_answer)"))

    def test_the_real_answer_stops_the_shimmer(self):
        update = _func(self.ui, "updateStatus_")
        self.assertLess(update.index("_stop_shimmer(self.choice_answer)"),
                        update.index("self.choice_answer.setStringValue_(shown)"))

    def test_a_new_capture_clears_a_leftover_shimmer(self):
        self.assertIn("_stop_shimmer(self.choice_answer)", _func(self.ui, "_fill_choice_panel"))

    def test_stop_restores_alpha_and_removes_the_mask(self):
        stop = _func(self.ui, "_stop_shimmer")
        self.assertIn("setAlphaValue_(1.0)", stop)
        self.assertIn("setMask_(None)", stop)

    def test_reduce_motion_still_skips_the_sweep(self):
        body = _func(self.ui, "_shimmer_body")
        self.assertLess(body.index("reduceMotion"), body.index("CAGradientLayer.layer()"))


if __name__ == "__main__":
    unittest.main()
