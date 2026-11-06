"""PR 7b dizzy: rough drags from RAW cursor event streams, recorded-style. Headless and seeded.

A stream is what NSEvent gives a drag: a sample per mouseDragged_ event, at irregular 8 to 16 ms intervals, with
a little jitter on both axes. The gestures are the ones a hand test produces: a hard shake, a shake up and down,
a steady drag, a jittery hold, a slow wiggle, and a flick.
"""
import math
import random
import unittest

import orb_character as oc
from orb_motion import REVERSAL_MIN_TRAVEL, ROUGH_WINDOW_SECONDS, drag_roughness


def _stream(path, seed=7, jitter=0.6, start=100.0):
    """path(t) -> (x, y) for t in seconds. Event times are irregular, and each sample gets Gaussian jitter."""
    rng = random.Random(seed)
    samples, t = [], 0.0
    duration = path.duration
    while t <= duration:
        x, y = path(t)
        samples.append((start + t, x + rng.gauss(0.0, jitter), y + rng.gauss(0.0, jitter)))
        t += rng.uniform(0.008, 0.016)
    return samples


class _Path:
    def __init__(self, fn, duration):
        self.fn, self.duration = fn, duration

    def __call__(self, t):
        return self.fn(t)


def _shake_x(amplitude, hz, seconds, y_wobble=0.0):
    """A hard shake: side to side in x, with a little wobble in y."""
    return _Path(lambda t: (amplitude * math.sin(math.tau * hz * t), y_wobble * math.sin(math.tau * 9.0 * t)), seconds)


def _shake_y(amplitude, hz, seconds):
    return _Path(lambda t: (0.0, amplitude * math.sin(math.tau * hz * t)), seconds)


def _line(dx, dy, seconds):
    return _Path(lambda t: (dx * t / seconds, dy * t / seconds), seconds)


class HardShakeTests(unittest.TestCase):
    def test_a_hard_shake_side_to_side_is_rough(self):
        r = drag_roughness(_stream(_shake_x(90.0, 4.0, 1.0, y_wobble=3.0)))
        self.assertGreaterEqual(r.peak_window, 3)
        self.assertTrue(oc.rough_drag(r.peak_window, r.seconds_fast))

    def test_a_shake_up_and_down_is_rough_too(self):
        r = drag_roughness(_stream(_shake_y(70.0, 4.0, 1.0)))
        self.assertGreaterEqual(r.peak_window, 3)
        self.assertTrue(oc.rough_drag(r.peak_window, r.seconds_fast))

    def test_a_shake_of_two_swings_and_a_fast_flick_is_rough(self):
        """The hand-test case that logged reversals=2 with the spring path: the raw cursor shows the flick."""
        flick_then_back = _Path(lambda t: (300.0 * min(t / 0.12, 1.0) - 280.0 * max(0.0, min((t - 0.2) / 0.12, 1.0)), 0.0),
                                0.5)
        r = drag_roughness(_stream(flick_then_back, seed=11))
        self.assertTrue(oc.rough_drag(r.peak_window, r.seconds_fast), r)


class CountingTests(unittest.TestCase):
    def test_reversals_are_counted_on_the_raw_cursor_not_a_smoothed_path(self):
        # Clean, known swings: 4 reversals of 60 pt, 0.25 s apart, with no jitter.
        zigzag = [(i * 0.02, 60.0 * ((-1) ** (i // 12)), 0.0) for i in range(50)]  # +60, -60, +60, -60, +60
        r = drag_roughness(zigzag)
        self.assertEqual(r.reversals, 3)

    def test_jitter_under_the_travel_threshold_is_not_a_reversal(self):
        rng = random.Random(3)
        hold = [(i * 0.012, rng.gauss(0.0, 2.0), rng.gauss(0.0, 2.0)) for i in range(200)]
        r = drag_roughness(hold)
        self.assertEqual(r.reversals, 0)
        self.assertFalse(oc.rough_drag(r.peak_window, r.seconds_fast))

    def test_one_sample_that_flips_both_axes_counts_once(self):
        samples = [(0.00, 0.0, 0.0), (0.02, 30.0, 30.0), (0.04, 0.0, 0.0)]
        r = drag_roughness(samples)
        self.assertEqual(r.reversals, 1)

    def test_reversals_only_count_inside_the_rolling_window(self):
        # Three reversals spread over 4 s: no 1.5 s window holds three, so the drag is not rough on reversals alone.
        spread = _stream(_Path(lambda t: (70.0 * math.sin(math.tau * t / 2.7), 0.0), 4.0), seed=5)
        r = drag_roughness(spread)
        self.assertGreaterEqual(r.reversals, 3)
        self.assertLess(r.peak_window, 3)
        self.assertLessEqual(r.peak_window, r.reversals)
        self.assertLessEqual(ROUGH_WINDOW_SECONDS, 1.5)

    def test_the_travel_threshold_is_twelve_points(self):
        self.assertEqual(REVERSAL_MIN_TRAVEL, 12.0)


class SpeedTests(unittest.TestCase):
    def test_a_steady_drag_is_not_rough_and_has_its_peak_speed(self):
        r = drag_roughness(_stream(_line(300.0, 0.0, 0.8), seed=2))
        self.assertEqual(r.reversals, 0)
        self.assertFalse(oc.rough_drag(r.peak_window, r.seconds_fast))
        self.assertGreater(r.peak_speed, 300.0 / 0.8)  # the jitter adds some speed on top of the 375 pt/s drag
        self.assertLess(r.peak_speed, 1000.0)
        self.assertEqual(r.samples, len(_stream(_line(300.0, 0.0, 0.8), seed=2)))

    def test_a_flick_faster_than_1800_points_a_second_for_a_tenth_of_a_second_is_rough(self):
        flick = _stream(_line(300.0, 0.0, 0.12), seed=4)  # 2500 pt/s
        r = drag_roughness(flick)
        self.assertGreaterEqual(r.seconds_fast, 0.1)
        self.assertTrue(oc.rough_drag(r.peak_window, r.seconds_fast))

    def test_a_slow_fling_under_1800_points_a_second_is_not_rough(self):
        fling = _stream(_line(300.0, 0.0, 0.25), seed=6)  # 1200 pt/s
        r = drag_roughness(fling)
        self.assertEqual(r.seconds_fast, 0.0)
        self.assertFalse(oc.rough_drag(r.peak_window, r.seconds_fast))


class RecordTests(unittest.TestCase):
    def test_empty_and_single_sample_streams_are_calm(self):
        for samples in ([], [(0.0, 1.0, 1.0)]):
            r = drag_roughness(samples)
            self.assertEqual((r.reversals, r.peak_window, r.seconds_fast, r.peak_speed), (0, 0, 0.0, 0.0))

    def test_duplicate_timestamps_are_skipped(self):
        r = drag_roughness([(0.0, 0.0, 0.0), (0.0, 500.0, 0.0), (0.1, 0.0, 0.0)])
        self.assertTrue(math.isfinite(r.peak_speed))
        self.assertEqual(r.samples, 2)

    def test_the_record_has_named_fields(self):
        r = drag_roughness([(0.0, 0.0, 0.0), (0.1, 3.0, 0.0)])
        self.assertEqual(r._fields, ("reversals", "peak_window", "seconds_fast", "peak_speed", "samples"))


if __name__ == "__main__":
    unittest.main()


class DragWiringTests(unittest.TestCase):
    def _source(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "assistant_ui.py"), encoding="utf-8") as handle:
            return handle.read()

    def _func(self, source, name):
        import ast
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.get_source_segment(source, node)
        raise AssertionError(name)

    def test_the_drag_paths_sample_the_raw_cursor_on_the_event_clock(self):
        ui = self._source()
        spring = self._func(ui, "_drag_with_spring")
        self.assertIn("samples.append((_drag_clock(), point[0], point[1]))", spring)
        self.assertNotIn("samples.append((stamp, pos[0], pos[1]))", spring)
        exact = self._func(ui, "_drag_exactly")
        self.assertIn("samples.append((_drag_clock(), point[0], point[1]))", exact)
        window_drag = self._func(ui, "mouseDown_")
        self.assertIn("samples.append((_drag_clock(), float(now.x), float(now.y)))", window_drag)

    def test_every_drop_logs_the_samples_and_peak_speed(self):
        finalize = self._func(self._source(), "_finalize_mini_bar_drag")
        self.assertIn('"orb drag: samples={0} peak_speed={1:.0f}"', finalize)
        self.assertIn('"orb drag: end reversals={0} fast_s={1:.2f} rough={2}"', finalize)

    def test_the_retuned_thresholds_are_the_plans_real_numbers(self):
        from orb_motion import ROUGH_REVERSALS, ROUGH_SECONDS, ROUGH_SPEED, ROUGH_WINDOW_SECONDS
        self.assertEqual((ROUGH_REVERSALS, ROUGH_WINDOW_SECONDS, ROUGH_SECONDS, ROUGH_SPEED), (3, 1.5, 0.1, 1800.0))
