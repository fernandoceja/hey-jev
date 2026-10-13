"""Mic block level and the capsule meter mapping. No AppKit and no microphone.

mac_guard is installed for the suite. These cases never open a stream.
"""
import math
import os
import unittest

from mini_bar import block_level_db, level_to_unit, smooth

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _func(source, name):
    start = source.index(f"def {name}")
    line_start = source.rfind("\n", 0, start) + 1
    indent = start - line_start
    marker = "\n" + (" " * indent) + "def "
    nxt = source.find(marker, start + 1)
    if nxt < 0:
        nxt = len(source)
    return source[start:nxt]


def _half_sine(n=1600):
    """0.5 * sin, an integer number of cycles so the RMS is amplitude / sqrt(2)."""
    return [0.5 * math.sin(2.0 * math.pi * 1000.0 * i / 16000.0) for i in range(n)]


class TestBlockLevel(unittest.TestCase):
    def test_silence_maps_to_the_floor(self):
        db = block_level_db([0.0] * 1600)
        self.assertAlmostEqual(db, 20.0 * math.log10(1e-6))
        self.assertLessEqual(db, -60.0)
        self.assertEqual(level_to_unit(db), 0.0)
        self.assertEqual(level_to_unit(-60), 0.0)

    def test_a_half_sine_is_about_minus_nine_db(self):
        db = block_level_db(_half_sine())
        expected = 20.0 * math.log10(0.5 / math.sqrt(2.0))
        self.assertAlmostEqual(db, expected, places=2)
        self.assertAlmostEqual(db, -9.0, delta=0.2)

    def test_the_recorder_stores_that_level_on_every_block(self):
        source = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        callback = _func(source, "_cb")
        self.assertIn("x = indata[:, 0]", callback)
        self.assertIn("rms = float(np.sqrt(np.mean(x ** 2)))", callback)
        self.assertIn("self.level_db = 20.0 * float(np.log10(max(rms, 1e-6)))", callback)
        self.assertIn("def level(self):", source)
        self.assertIn("return float(self.level_db)", source)
        # Wake and dictation still own the later RMS. This block does not replace it.
        self.assertIn("self.noise = 0.95 * self.noise + 0.05 * rms", callback)


class TestMeterMapping(unittest.TestCase):
    def test_mapping_edges(self):
        self.assertEqual(level_to_unit(-60), 0.0)
        self.assertEqual(level_to_unit(-120), 0.0)
        self.assertEqual(level_to_unit(0), 1.0)
        self.assertEqual(level_to_unit(3), 1.0)
        self.assertAlmostEqual(level_to_unit(-30), 0.5)
        self.assertEqual(level_to_unit(-40, floor=-40), 0.0)
        self.assertAlmostEqual(level_to_unit(-20, floor=-40), 0.5)
        self.assertGreater(level_to_unit(-15), level_to_unit(-45))
        self.assertEqual(level_to_unit("nope"), 0.0)

    def test_smoothing_converges(self):
        self.assertAlmostEqual(smooth(0.0, 1.0), 0.4)
        self.assertAlmostEqual(smooth(0.0, 1.0, a=0.4), 0.4)
        value = 0.0
        previous = -1.0
        for _ in range(12):
            value = smooth(value, 1.0)
            self.assertGreater(value, previous)
            self.assertLess(value, 1.0)
            previous = value
        for _ in range(80):
            value = smooth(value, 0.8)
        self.assertAlmostEqual(value, 0.8, places=4)
        self.assertAlmostEqual(smooth(0.2, 0.2), 0.2)
