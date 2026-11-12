"""The capture glimmer: pointer-drag tracking, the hook around take_screenshot, and the overlay wiring. Headless."""
import ast
import os
import tempfile
import unittest

import capture_glimmer as cg
from commands import captures

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


def _feed(tracker, samples):
    for point, pressed in samples:
        tracker.feed(point, pressed)


class RectTests(unittest.TestCase):
    def test_two_points_make_a_rectangle_from_any_corner(self):
        self.assertEqual(cg.rect_from_points((10, 10), (110, 60)), (10.0, 10.0, 100.0, 50.0))
        self.assertEqual(cg.rect_from_points((110, 60), (10, 10)), (10.0, 10.0, 100.0, 50.0))

    def test_a_tiny_or_bad_selection_is_not_a_rectangle(self):
        self.assertIsNone(cg.rect_from_points((10, 10), (12, 80)))
        self.assertIsNone(cg.rect_from_points((10, 10), (80, 11)))
        self.assertIsNone(cg.rect_from_points((10, 10), (float("nan"), 50)))
        self.assertIsNone(cg.rect_from_points(None, (1, 2)))


class DragTrackerTests(unittest.TestCase):
    def test_a_drag_from_press_to_release_gives_its_rectangle(self):
        t = cg.DragTracker()
        _feed(t, [((0, 0), False), ((10, 10), True), ((60, 40), True), ((130, 90), True), ((130, 90), False)])
        self.assertTrue(t.done)
        self.assertEqual(t.rect(), (10.0, 10.0, 120.0, 80.0))

    def test_the_click_that_started_the_capture_is_ignored(self):
        t = cg.DragTracker()
        _feed(t, [((500, 500), True), ((500, 500), True), ((500, 500), False), ((20, 20), True), ((220, 120), True),
                  ((220, 120), False)])
        self.assertEqual(t.rect(), (20.0, 20.0, 200.0, 100.0))

    def test_no_press_means_no_rectangle(self):
        t = cg.DragTracker()
        _feed(t, [((0, 0), False), ((50, 50), False)])
        self.assertIsNone(t.rect())
        self.assertFalse(t.done)

    def test_a_plain_click_is_too_small(self):
        t = cg.DragTracker()
        _feed(t, [((0, 0), False), ((40, 40), True), ((41, 41), False)])
        self.assertTrue(t.done)
        self.assertIsNone(t.rect())

    def test_only_the_first_drag_counts(self):
        t = cg.DragTracker()
        _feed(t, [((0, 0), False), ((10, 10), True), ((90, 90), False), ((300, 300), True), ((500, 500), False)])
        self.assertEqual(t.rect(), (10.0, 10.0, 80.0, 80.0))


class TimingTests(unittest.TestCase):
    def test_the_glimmer_is_short(self):
        self.assertTrue(0.4 <= cg.GLIMMER_SECONDS <= 0.6)
        self.assertTrue(0.3 <= cg.GLIMMER_REDUCED_SECONDS <= 0.6)
        self.assertEqual(cg.glimmer_seconds(False), cg.GLIMMER_SECONDS)
        self.assertEqual(cg.glimmer_seconds(True), cg.GLIMMER_REDUCED_SECONDS)

    def test_the_panel_waits_for_the_glimmer_then_not(self):
        self.assertAlmostEqual(cg.panel_delay(100.0, 100.0, False), cg.GLIMMER_SECONDS + cg.PANEL_AFTER_GLIMMER_GAP)
        self.assertEqual(cg.panel_delay(100.0, 101.0, False), 0.0)
        self.assertEqual(cg.panel_delay(0.0, 5000.0, False), 0.0)  # no glimmer has played
        self.assertLess(cg.panel_delay(100.0, 100.0, True), cg.panel_delay(100.0, 100.0, False))

    def test_the_band_stays_inside_sane_alphas(self):
        for value in (cg.GLIMMER_BASE_ALPHA, cg.GLIMMER_BAND_ALPHA, cg.GLIMMER_REDUCED_ALPHA):
            self.assertTrue(0.0 < value < 1.0)


class FakeBook:
    def __init__(self, log):
        self.log = log

    def remember(self, path, kind):
        self.log.append(("saved", path))


class HookTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        captures.set_area_hooks(lambda: self.log.append("begin") or "watcher",
                                lambda watcher, path: self.log.append(("finish", watcher, path)))

    def tearDown(self):
        captures.set_area_hooks(None, None)

    def _take(self, mode, run):
        with tempfile.TemporaryDirectory() as tmp:
            result = captures.take_screenshot(mode, folder=tmp, run=run, book=FakeBook(self.log))
            return result

    def test_an_area_capture_watches_then_flashes_after_the_file_is_saved(self):
        self._take("area", lambda argv, timeout=0: self.log.append("screencapture"))
        self.assertEqual(self.log[0], "begin")
        self.assertEqual(self.log[1], "screencapture")
        self.assertEqual(self.log[2][0], "saved")
        self.assertEqual(self.log[3][0], "finish")
        self.assertEqual(self.log[3][2], self.log[2][1])  # finish gets the saved path, after it was saved

    def test_a_cancelled_area_capture_finishes_with_no_path(self):
        def cancel(argv, timeout=0):
            raise RuntimeError("could not create image from rect")
        self.assertEqual(self._take("area", cancel), "Cancelled.")
        self.assertEqual(self.log, ["begin", ("finish", "watcher", None)])

    def test_full_and_window_captures_do_not_use_the_hooks(self):
        self._take("full", lambda argv, timeout=0: None)
        self._take("window", lambda argv, timeout=0: None)
        hook_calls = [i for i in self.log if i == "begin" or (isinstance(i, tuple) and i[0] == "finish")]
        self.assertEqual(hook_calls, [])

    def test_a_broken_hook_never_breaks_the_capture(self):
        def boom(*args):
            raise RuntimeError("hook failed")
        captures.set_area_hooks(boom, boom)
        self.assertTrue(self._take("area", lambda argv, timeout=0: None).startswith("Saved"))
        captures.set_area_hooks(lambda: "w", boom)
        self.assertTrue(self._take("area", lambda argv, timeout=0: None).startswith("Saved"))

    def test_the_hooks_are_optional(self):
        captures.set_area_hooks(None, None)
        self.assertTrue(self._take("area", lambda argv, timeout=0: None).startswith("Saved"))


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.ui = _source("assistant_ui.py")

    def test_the_hooks_are_registered_at_launch(self):
        self.assertIn("set_area_hooks(self._glimmer_begin, self._glimmer_finish)", self.ui)

    def test_the_overlay_cannot_be_captured_or_clicked(self):
        body = _func(self.ui, "captureGlimmer_")
        self.assertIn("setSharingType_(0)", body)  # NSWindowSharingNone
        self.assertIn("setIgnoresMouseEvents_(True)", body)
        self.assertIn("NSWindowStyleMaskNonactivatingPanel", body)

    def test_the_glimmer_starts_only_from_the_post_save_finish_hook(self):
        finish = _func(self.ui, "_glimmer_finish")
        self.assertIn("if not path or rect is None:", finish)
        self.assertIn("captureGlimmer:", finish)
        self.assertNotIn("captureGlimmer:", _func(self.ui, "_glimmer_begin"))

    def test_reduce_motion_gets_a_steady_highlight_not_a_sweep(self):
        body = _func(self.ui, "captureGlimmer_")
        reduced = body[body.index("if reduce:"):body.index("else:")]
        self.assertIn("GLIMMER_REDUCED_ALPHA", reduced)
        self.assertNotIn("CABasicAnimation.animationWithKeyPath_(\"locations\")", reduced)
        self.assertIn("glimmer_seconds(reduce)", body)

    def test_the_capture_panel_waits_for_the_glimmer(self):
        body = _func(self.ui, "_show_capture_choices")
        self.assertIn("panel_delay(", body)
        self.assertLess(body.index("panel_delay("), body.index("from commands.captures import BOOK"))
        self.assertIn("showChoicesAfterGlimmer:", body)

    def test_the_overlay_closes_itself(self):
        self.assertIn("captureGlimmerEnd:", _func(self.ui, "captureGlimmer_"))
        self.assertIn("orderOut_", _func(self.ui, "captureGlimmerEnd_"))

    def test_the_ask_shimmer_from_the_capture_panel_is_unchanged(self):
        ask = _func(self.ui, "choiceAsk_")
        self.assertIn("PENDING_CAPTURE_TEXT", ask)
        self.assertIn("_shimmer_body(self.choice_answer)", ask)

    def test_the_watcher_polls_only_the_pointer_and_left_button(self):
        text = self.ui[self.ui.index("class GlimmerWatcher"):self.ui.index("class CaptureChoicePanel")]
        self.assertIn("NSEvent.mouseLocation()", text)
        self.assertIn("pressedMouseButtons()", text)
        self.assertNotIn("addGlobalMonitor", text)  # no event monitor, so no extra permission


if __name__ == "__main__":
    unittest.main()
