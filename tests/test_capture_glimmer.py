"""The capture glimmer: pointer-drag tracking, the hook around take_screenshot, and the overlay wiring. Headless."""
import ast
import math
import os
import random
import re
import tempfile
import unittest

import capture_glimmer as cg
import orb_motion as om
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
        self.assertTrue(0.4 <= cg.GLIMMER_SECONDS <= 0.6 + 1e-9)
        self.assertTrue(0.3 <= cg.GLIMMER_REDUCED_SECONDS <= 0.6)
        self.assertEqual(cg.glimmer_seconds(False), cg.GLIMMER_SECONDS)
        self.assertEqual(cg.glimmer_seconds(True), cg.GLIMMER_REDUCED_SECONDS)

    def test_the_panel_waits_for_the_glimmer_then_not(self):
        self.assertAlmostEqual(cg.panel_delay(100.0, 100.0, False), cg.GLIMMER_SECONDS + cg.PANEL_AFTER_GLIMMER_GAP)
        self.assertEqual(cg.panel_delay(100.0, 101.0, False), 0.0)
        self.assertEqual(cg.panel_delay(0.0, 5000.0, False), 0.0)  # no glimmer has played
        self.assertLess(cg.panel_delay(100.0, 100.0, True), cg.panel_delay(100.0, 100.0, False))

    def test_the_alphas_stay_in_range(self):
        for value in (cg.GLIMMER_WASH_ALPHA, cg.GLIMMER_REDUCED_WASH_ALPHA, cg.GLIMMER_BAND_ALPHA,
                      cg.GLIMMER_BORDER_ALPHA, cg.GLIMMER_GLOW_OPACITY):
            self.assertTrue(0.0 < value <= 1.0)

    def test_the_wash_is_a_translucent_20_to_30_percent(self):
        self.assertTrue(0.20 <= cg.GLIMMER_WASH_ALPHA <= 0.30)
        self.assertTrue(0.20 <= cg.GLIMMER_REDUCED_WASH_ALPHA <= 0.35)


class ColorTests(unittest.TestCase):
    """Every glimmer color is the orb's own, not a new hard-coded one."""

    def test_the_colors_are_the_orbs(self):
        self.assertIs(cg.WASH_RGB, om.ORB_PALETTE[1])  # the orb's blue body
        self.assertIs(cg.BORDER_RGB, om.RING_RGB)  # the orb's cyan-blue ring
        self.assertIs(cg.SPARKLE_RGB, om.LISTEN_GLYPH_RGB)  # the orb's light cyan highlight
        self.assertIs(cg.BAND_RGB, om.LISTEN_GLYPH_RGB)

    def test_blue_and_cyan_not_pink(self):
        for rgb in (cg.WASH_RGB, cg.BORDER_RGB, cg.SPARKLE_RGB):
            r, g, b = rgb
            self.assertGreater(b, r)  # blue-led
            self.assertGreater(b, 0.5 * g)
        self.assertGreater(cg.BORDER_RGB[2], 0.9)
        self.assertGreater(cg.SPARKLE_RGB[1], cg.SPARKLE_RGB[0])  # cyan: green and blue above red

    def test_the_module_has_no_color_literals_of_its_own(self):
        text = _source("capture_glimmer.py")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        self.assertIsNone(re.search(r"\(\s*[01]?\.\d+\s*,\s*[01]?\.\d+\s*,\s*[01]?\.\d+\s*\)", code))  # no RGB tuples

    def test_rgba_builds_a_color_tuple_from_an_orb_color(self):
        self.assertEqual(cg.rgba(om.RING_RGB, 0.5), (om.RING_RGB[0], om.RING_RGB[1], om.RING_RGB[2], 0.5))


class SparkleTests(unittest.TestCase):
    def test_a_sparkle_is_a_four_point_star_around_the_origin(self):
        pts = cg.star_points(10.0)
        self.assertEqual(len(pts), 8)
        self.assertAlmostEqual(max(y for _x, y in pts), 5.0)
        self.assertAlmostEqual(min(y for _x, y in pts), -5.0)
        self.assertAlmostEqual(sum(x for x, _y in pts), 0.0, places=6)
        tips = [p for i, p in enumerate(pts) if i % 2 == 0]
        notches = [p for i, p in enumerate(pts) if i % 2 == 1]
        self.assertGreater(min(math.hypot(*t) for t in tips), max(math.hypot(*n) for n in notches))

    def test_specs_are_deterministic_for_a_seed_and_the_right_count(self):
        a = cg.sparkle_specs(300, 200, rng=random.Random(7))
        b = cg.sparkle_specs(300, 200, rng=random.Random(7))
        self.assertEqual(a, b)
        self.assertEqual(len(a), cg.SPARKLE_COUNT)

    def test_the_first_sparkle_is_at_a_corner_and_the_rest_hug_the_edges(self):
        for seed in range(20):
            specs = cg.sparkle_specs(300, 200, rng=random.Random(seed))
            first = specs[0]
            self.assertTrue(min(abs(first["x"]), abs(first["x"] - 300)) <= 4.0)
            self.assertTrue(min(abs(first["y"]), abs(first["y"] - 200)) <= 4.0)
            for spec in specs[1:]:
                near_x = min(abs(spec["x"]), abs(spec["x"] - 300)) <= 6.0
                near_y = min(abs(spec["y"]), abs(spec["y"] - 200)) <= 6.0
                self.assertTrue(near_x or near_y, spec)

    def test_every_sparkle_stays_inside_the_overlay_pad(self):
        for seed in range(20):
            for spec in cg.sparkle_specs(120, 80, rng=random.Random(seed)):
                self.assertTrue(-cg.GLIMMER_PAD < spec["x"] < 120 + cg.GLIMMER_PAD)
                self.assertTrue(-cg.GLIMMER_PAD < spec["y"] < 80 + cg.GLIMMER_PAD)

    def test_sparkles_twinkle_in_turn_and_finish_inside_the_glimmer(self):
        for spec in cg.sparkle_specs(300, 200, rng=random.Random(3)):
            self.assertTrue(cg.SPARKLE_SIZE[0] <= spec["size"] <= cg.SPARKLE_SIZE[1])
            self.assertTrue(cg.SPARKLE_LIFE[0] <= spec["life"] <= cg.SPARKLE_LIFE[1])
            self.assertLessEqual(spec["delay"], cg.GLIMMER_SECONDS * cg.SPARKLE_SPREAD)
            self.assertLessEqual(spec["delay"] + spec["life"], cg.GLIMMER_SECONDS)


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

    def test_reduce_motion_gets_a_steady_wash_and_border_not_a_sweep_or_sparkles(self):
        body = _func(self.ui, "captureGlimmer_")
        self.assertIn("GLIMMER_REDUCED_WASH_ALPHA if reduce else GLIMMER_WASH_ALPHA", body)
        motion = body[body.index("if not reduce:"):body.index("# A smooth fade")]
        self.assertIn("CAGradientLayer.layer()", motion)  # the sweep
        self.assertIn("sparkle_specs(", motion)  # the sparkles
        before = body[:body.index("if not reduce:")]
        self.assertNotIn("CAGradientLayer.layer()", before)
        self.assertNotIn("sparkle_specs(", before)
        self.assertIn("glimmer_seconds(reduce)", body)

    def test_it_has_a_wash_a_glowing_border_a_sweep_sparkles_and_a_fade(self):
        body = _func(self.ui, "captureGlimmer_")
        for needle in ("setBackgroundColor_", "setBorderWidth_(GLIMMER_BORDER_WIDTH)", "setShadowRadius_(GLIMMER_GLOW_RADIUS)",
                       "glimmerSweep", "glimmerTwinkle", "glimmerFade", "CAShapeLayer", "setMasksToBounds_(True)"):
            self.assertIn(needle, body, needle)

    def test_every_color_comes_from_the_orb_constants(self):
        body = _func(self.ui, "captureGlimmer_")
        for name in ("WASH_RGB", "BORDER_RGB", "SPARKLE_RGB", "BAND_RGB"):
            self.assertIn(name, body)
        for banned in ("colorWithCalibratedWhite", "systemPink", "systemRed", "colorWithSRGBRed", "0xFF"):
            self.assertNotIn(banned, body, banned)

    def test_the_overlay_is_padded_so_the_glow_is_not_clipped(self):
        body = _func(self.ui, "captureGlimmer_")
        self.assertIn("pad = GLIMMER_PAD", body)
        self.assertIn("x - pad, y - pad, w + 2 * pad, h + 2 * pad", body)

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
