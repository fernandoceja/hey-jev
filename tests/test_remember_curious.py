"""Eney animations, item 3: the remember and curious reactions and their triggers. Headless, fake clock."""
import math
import unittest

import orb_character as oc
from orb_character import EYE_SHAPES, REACTIONS, ReactionQueue


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class TriggerTests(unittest.TestCase):
    def test_a_saved_note_reply_calls_remember(self):
        for line in ("Got it. I added that to your notes.", "Saved it to a new note in Notes."):
            self.assertEqual(oc.reaction_for_status("Doing it", "Ready", line), "remember", line)

    def test_other_replies_still_call_success(self):
        self.assertEqual(oc.reaction_for_status("Doing it", "Ready", "It is 3pm."), "success")

    def test_errors_still_call_failure(self):
        self.assertEqual(oc.reaction_for_status("Doing it", "Something went wrong", "x"), "failure")

    def test_remember_needs_a_busy_state_before_it(self):
        self.assertIsNone(oc.reaction_for_status("Ready", "Ready", "Got it. I added that to your notes."))

    def test_starting_a_lookup_calls_curious(self):
        self.assertEqual(oc.lookup_reaction("Ready", "Doing it"), "curious")
        self.assertEqual(oc.lookup_reaction("Listening", "Doing it"), "curious")

    def test_curious_does_not_fire_mid_turn_or_for_other_states(self):
        self.assertIsNone(oc.lookup_reaction("Thinking", "Doing it"))
        self.assertIsNone(oc.lookup_reaction("Doing it", "Doing it"))
        self.assertIsNone(oc.lookup_reaction("Ready", "Thinking"))
        self.assertIsNone(oc.lookup_reaction("Ready", "Ready"))


class TableTests(unittest.TestCase):
    def test_new_reactions_use_known_eye_shapes(self):
        for name in ("remember", "curious"):
            for _t, shape in REACTIONS[name].eyes:
                self.assertIn(shape, EYE_SHAPES, name)

    def test_nod_dips_and_returns_to_rest(self):
        y = oc.reaction_body_tracks("remember")["y"]
        self.assertLessEqual(min(v for _t, v in y), -2.9)
        self.assertTrue(all(v <= 1e-9 for _t, v in y))
        self.assertAlmostEqual(y[0][1], 0.0)
        self.assertAlmostEqual(y[-1][1], 0.0, places=6)

    def test_tilt_leans_and_returns_to_rest(self):
        rot = oc.reaction_body_tracks("curious")["rot"]
        self.assertAlmostEqual(max(v for _t, v in rot), 5.0, places=1)
        self.assertAlmostEqual(rot[0][1], 0.0)
        self.assertAlmostEqual(rot[-1][1], 0.0, places=6)
        self.assertTrue(all(math.isfinite(v) for _t, v in rot))

    def test_tracks_end_at_the_reaction_length(self):
        for name in ("remember", "curious"):
            for samples in oc.reaction_body_tracks(name).values():
                self.assertAlmostEqual(samples[-1][0], REACTIONS[name].seconds, places=6)


class QueueTests(unittest.TestCase):
    def test_curious_cannot_replace_success(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("success"))
        self.assertFalse(queue.offer("curious"))

    def test_success_replaces_curious(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("curious"))
        self.assertTrue(queue.offer("success"))

    def test_curious_waits_45_seconds_before_replaying(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("curious"))
        clock.now += 30
        self.assertFalse(queue.offer("curious"))
        clock.now += 20
        self.assertTrue(queue.offer("curious"))

    def test_remember_waits_5_seconds_before_replaying(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("remember"))
        clock.now += 2
        self.assertFalse(queue.offer("remember"))
        clock.now += 4
        self.assertTrue(queue.offer("remember"))


class WiringTests(unittest.TestCase):
    def test_status_updates_offer_the_new_reactions(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "assistant_ui.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("reaction_for_status(previous, state, detail) or lookup_reaction(previous, state)", source)


if __name__ == "__main__":
    unittest.main()
