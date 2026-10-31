"""PR 7b: one-shot reactions, the trigger rules, the new eye shapes, and the Spotlight level. Headless, fake clock."""
import ast
import math
import os
import re
import unittest
from types import SimpleNamespace

import orb_character as oc
import orb_spotlight as sp
from mini_bar import chip_title
from orb_character import EYE_SHAPES, REACTIONS, ReactionQueue, eye_shape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class ReactionQueueTests(unittest.TestCase):
    def test_a_reaction_plays_for_its_duration_then_ends(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("get_ready"))
        self.assertEqual(queue.current(), "get_ready")
        clock.now += REACTIONS["get_ready"].seconds
        self.assertIsNone(queue.current())

    def test_success_is_at_most_once_per_twenty_seconds(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("success"))
        clock.now += 19.0
        self.assertFalse(queue.offer("success"))
        clock.now += 1.0
        self.assertTrue(queue.offer("success"))

    def test_failure_cooldown_is_five_seconds_and_dizzy_is_ten(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("failure"))
        clock.now += 5.0
        self.assertTrue(queue.offer("failure"))
        clock.now += 1.0  # the failure has played its 1 s, so the lower-priority dizzy may start
        self.assertTrue(queue.offer("dizzy"))
        clock.now += 9.9
        self.assertFalse(queue.offer("dizzy"))

    def test_heart_cooldown_is_sixty_seconds(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("heart"))
        clock.now += 59.0
        self.assertFalse(queue.offer("heart"))
        clock.now += 1.0
        self.assertTrue(queue.offer("heart"))

    def test_a_lower_priority_reaction_waits_while_a_higher_one_plays(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("failure"))  # priority 3
        self.assertFalse(queue.offer("heart"))  # priority 1
        self.assertEqual(queue.current(), "failure")

    def test_an_equal_or_higher_priority_replaces_the_playing_reaction(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("failure"))  # priority 3
        self.assertTrue(queue.offer("get_ready"))  # priority 3, equal: replaces
        self.assertEqual(queue.current(), "get_ready")
        self.assertFalse(queue.offer("success"))  # priority 2 is lower than get_ready: refused
        self.assertEqual(queue.current(), "get_ready")

    def test_a_refused_offer_does_not_start_its_cooldown(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("failure"))
        self.assertFalse(queue.offer("heart"))
        clock.now += 1.0
        queue.current()  # failure is still playing
        clock.now += 10.0
        self.assertTrue(queue.offer("heart"))  # not blocked by the refused offer

    def test_cancel_all_stops_the_reaction_but_keeps_the_cooldown(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("success"))
        queue.cancel_all()
        self.assertIsNone(queue.current())
        self.assertFalse(queue.offer("success"))  # the cooldown still holds

    def test_wave_is_once_per_launch(self):
        clock = FakeClock()
        queue = ReactionQueue(clock)
        self.assertTrue(queue.offer("wave"))
        clock.now += 10 ** 9
        self.assertFalse(queue.offer("wave"))

    def test_unknown_reactions_are_rejected(self):
        with self.assertRaises(ValueError):
            ReactionQueue(FakeClock()).offer("bogus")

    def test_the_table_matches_the_plan(self):
        table = {name: (r.seconds, r.priority, r.cooldown) for name, r in REACTIONS.items()}
        self.assertEqual(table["get_ready"], (0.35, 3, 0.0))
        self.assertEqual(table["success"], (0.8, 2, 20.0))
        self.assertEqual(table["failure"], (1.0, 3, 5.0))
        self.assertEqual(table["dizzy"], (1.2, 2, 10.0))
        self.assertEqual(table["heart"], (1.0, 1, 60.0))
        self.assertEqual(table["low_disk"], (1.5, 1, 3600.0))
        self.assertEqual(table["wave"][:2], (1.2, 1))
        self.assertEqual(set(REACTIONS), {"get_ready", "success", "failure", "dizzy", "heart", "low_disk", "wave"})


class IsThanksTests(unittest.TestCase):
    def test_positives(self):
        for text in ("thanks", "Thanks!", "thank you", "Thank you Jev", "thank you, Jev.", "love you, Jev", "love you Jev"):
            self.assertTrue(oc.is_thanks(text), text)

    def test_negatives(self):
        for text in ("no thanks", "No thanks to the weather", "", None, "what time is it", "thankful for the day",
                     "thanksgiving menu"):
            self.assertFalse(oc.is_thanks(text), repr(text))


class RoughDragTests(unittest.TestCase):
    def test_four_reversals_are_rough(self):
        self.assertFalse(oc.rough_drag(3, 0.0))
        self.assertTrue(oc.rough_drag(4, 0.0))

    def test_three_tenths_of_a_second_fast_is_rough(self):
        self.assertFalse(oc.rough_drag(0, 0.29))
        self.assertTrue(oc.rough_drag(0, 0.3))

    def test_a_hard_shake_through_the_drag_spring_is_rough(self):
        """Simulated: a 150 pt shake at 6 Hz, followed by the real drag spring at 60 Hz, reaches the rough thresholds."""
        import math
        from orb_motion import DRAG_TICK_SECONDS, SPRING_FOLLOW, drag_roughness, follow_step
        pos, vel, samples, t = (0.0, 0.0), (0.0, 0.0), [], 0.0
        while t < 1.0:
            cursor = (150.0 * math.sin(math.tau * 6.0 * t), 0.0)
            pos, vel = follow_step(pos, vel, cursor, DRAG_TICK_SECONDS, *SPRING_FOLLOW)
            samples.append((t, pos[0], pos[1]))
            t += DRAG_TICK_SECONDS
        reversals, fast = drag_roughness(samples)
        self.assertTrue(oc.rough_drag(reversals, fast), (reversals, fast))

    def test_a_gentle_drag_is_not_rough(self):
        import math
        from orb_motion import DRAG_TICK_SECONDS, SPRING_FOLLOW, drag_roughness, follow_step
        pos, vel, samples, t = (0.0, 0.0), (0.0, 0.0), [], 0.0
        while t < 1.0:
            cursor = (60.0 * math.sin(math.tau * 4.0 * t), 0.0)
            pos, vel = follow_step(pos, vel, cursor, DRAG_TICK_SECONDS, *SPRING_FOLLOW)
            samples.append((t, pos[0], pos[1]))
            t += DRAG_TICK_SECONDS
        self.assertFalse(oc.rough_drag(*drag_roughness(samples)))

    def test_the_fast_speed_is_2500_points_a_second(self):
        from orb_motion import ROUGH_SPEED
        self.assertEqual(ROUGH_SPEED, 2500.0)

    def test_bad_input_is_not_rough(self):
        self.assertFalse(oc.rough_drag(None, None))
        self.assertFalse(oc.rough_drag("x", "y"))


class LowDiskTests(unittest.TestCase):
    GB = 1024 ** 3

    def test_under_ten_gigabytes_is_low(self):
        # On a 100 GB disk, 10 GB is 10%, so only the absolute rule decides here.
        self.assertTrue(oc.low_disk(9.9 * self.GB, 100 * self.GB))
        self.assertFalse(oc.low_disk(10.0 * self.GB, 100 * self.GB))

    def test_under_five_percent_is_low_even_above_ten_gigabytes(self):
        self.assertTrue(oc.low_disk(40 * self.GB, 1000 * self.GB))  # 4%
        self.assertFalse(oc.low_disk(60 * self.GB, 1000 * self.GB))  # 6%

    def test_plenty_of_space_is_not_low(self):
        self.assertFalse(oc.low_disk(500 * self.GB, 1000 * self.GB))

    def test_bad_input_is_not_low(self):
        self.assertFalse(oc.low_disk(None, 100))
        self.assertFalse(oc.low_disk(1, 0))
        self.assertFalse(oc.low_disk(float("nan"), 100))

    def test_disk_check_uses_the_injected_usage_and_never_the_real_disk(self):
        calls = []

        def fake_usage(path):
            calls.append(path)
            return SimpleNamespace(free=3 * self.GB, total=500 * self.GB)

        self.assertTrue(oc.disk_check(usage=fake_usage))
        self.assertEqual(calls, ["/"])

    def test_disk_check_treats_an_os_error_as_not_low(self):
        def broken(_path):
            raise OSError("no disk")

        self.assertFalse(oc.disk_check(usage=broken))


class ReactionStatusTests(unittest.TestCase):
    def test_success_needs_a_real_reply_after_a_busy_state(self):
        self.assertEqual(oc.reaction_for_status("Doing it", "Ready", "It is 3pm."), "success")
        self.assertEqual(oc.reaction_for_status("Thinking", "Ready", "Pasted 4 words"), "success")

    def test_idle_ready_lines_and_non_busy_starts_are_not_success(self):
        self.assertIsNone(oc.reaction_for_status("Doing it", "Ready", "Ready when you are"))
        self.assertIsNone(oc.reaction_for_status("Doing it", "Ready", ""))
        self.assertIsNone(oc.reaction_for_status("Ready", "Ready", "It is 3pm."))

    def test_errors_are_failure(self):
        self.assertEqual(oc.reaction_for_status("Doing it", "Something went wrong", "x"), "failure")
        self.assertEqual(oc.reaction_for_status("Ready", "Time's up", ""), "failure")

    def test_other_states_have_no_reaction(self):
        self.assertIsNone(oc.reaction_for_status("Ready", "Listening", ""))


class EyeShapeTests(unittest.TestCase):
    def test_every_new_shape_has_the_same_point_count_as_open(self):
        open_points = len(eye_shape("open", 11.0))
        for name in ("happy", "sad", "heart", "spiral", "sceptic", "squint", "wide"):
            self.assertIn(name, EYE_SHAPES)
            self.assertEqual(len(eye_shape(name, 11.0)), open_points, name)

    def test_new_shapes_stay_inside_the_eye(self):
        for name in ("happy", "sad", "heart", "spiral"):
            for x, y in EYE_SHAPES[name]:
                self.assertTrue(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0, name)

    def test_every_reaction_uses_known_shapes(self):
        for reaction in REACTIONS.values():
            for _t, shape in reaction.eyes:
                self.assertIn(shape, EYE_SHAPES, reaction.name)

    def test_reaction_body_tracks_stay_finite_and_end_at_their_length(self):
        for name in REACTIONS:
            tracks = oc.reaction_body_tracks(name)
            for channel, samples in tracks.items():
                self.assertAlmostEqual(samples[-1][0], REACTIONS[name].seconds, places=6, msg=name)
                self.assertTrue(all(math.isfinite(v) for _t, v in samples), (name, channel))

    def test_droop_and_pulse_stay_near_rest(self):
        sy = oc.reaction_body_tracks("failure")["sy"]
        self.assertTrue(all(0.9 <= v <= 1.0 for _t, v in sy))
        scale = oc.reaction_body_tracks("heart")["scale"]
        self.assertTrue(all(1.0 <= v <= 1.09 for _t, v in scale))

    def test_wave_and_balance_accents_are_in_the_table(self):
        names = [accent.name for accent in oc.ACCENTS]
        self.assertIn("wave", names)
        self.assertIn("balance_eyes", names)
        self.assertEqual(oc.accent_seconds("wave"), 1.2)
        self.assertEqual(oc.accent_seconds("balance_eyes"), 1.4)


class SpotlightLevelTests(unittest.TestCase):
    def test_spotlight_is_above_the_floating_orb_and_other_apps(self):
        self.assertEqual(sp.SPOTLIGHT_LEVEL, 101)
        self.assertGreater(sp.SPOTLIGHT_LEVEL, sp.ORB_PANEL_LEVEL)

    def test_the_mirror_of_the_orb_level_matches_assistant_ui(self):
        match = re.search(r"^BAR_LEVEL = (\d+)", _source("assistant_ui.py"), re.M)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1)), sp.ORB_PANEL_LEVEL)

    def test_the_panel_sets_its_level_joins_spaces_logs_and_stays_key_capable(self):
        opener = _func(_source("assistant_ui.py"), "_open_orb_spotlight")
        self.assertIn("setLevel_(SPOTLIGHT_LEVEL)", opener)
        self.assertIn("NSWindowCollectionBehaviorTransient", opener)
        self.assertIn("NSWindowCollectionBehaviorCanJoinAllSpaces", opener)
        self.assertIn("NSWindowCollectionBehaviorFullScreenAuxiliary", opener)
        self.assertIn("orb spotlight: level={0} key={1}", opener)
        self.assertIn("makeKeyAndOrderFront_", opener)
        self.assertIn("NSApp.activateIgnoringOtherApps_(True)", opener)
        self.assertIn("def canBecomeKeyWindow", _source("assistant_ui.py"))


class ChipTitleTests(unittest.TestCase):
    def test_only_the_mac_health_chip_is_marked_when_alerted(self):
        self.assertEqual(chip_title("mac_health", "Mac health", True), "• Mac health")
        self.assertEqual(chip_title("eta_home", "ETA home", True), "ETA home")

    def test_nothing_is_marked_without_an_alert(self):
        self.assertEqual(chip_title("mac_health", "Mac health", False), "Mac health")


class ReactionWiringTests(unittest.TestCase):
    def test_orb_view_logs_each_reaction_and_offers_get_ready_on_listening(self):
        view = _source("orb_view.py")
        self.assertIn('print("orb reaction: %s" % name', view)
        self.assertIn('offerReaction("get_ready")', _func(view, "enterCharacter"))
        self.assertIn('offerReaction("wave")', _func(view, "configure"))

    def test_the_status_and_drop_and_heart_triggers_are_wired(self):
        ui = _source("assistant_ui.py")
        self.assertIn("reaction_for_status(previous, state, detail)", _func(ui, "updateStatus_"))
        finalize = _func(ui, "_finalize_mini_bar_drag")
        self.assertIn('offerReaction("dizzy")', finalize)
        self.assertLess(finalize.index("offerReaction(\"dizzy\")"), finalize.index("_tuck_consider"))
        self.assertEqual(ui.count("self._note_turn_text("), 5)  # the five typed or sent turns

    def test_low_disk_runs_on_a_background_thread_and_only_reads(self):
        ui = _source("assistant_ui.py")
        worker = _func(ui, "_disk_check_worker")
        self.assertIn("disk_check()", worker)
        self.assertIn("performSelectorOnMainThread_withObject_waitUntilDone_", worker)
        self.assertIn("threading.Thread", _func(ui, "_run_disk_check"))
        self.assertIn("3600.0", _func(ui, "_start_disk_watch"))
        done = _func(ui, "diskCheckDone_")
        self.assertIn('offerReaction("low_disk")', done)
        self.assertNotIn("removeItem", ui[ui.index("def diskCheckDone_"):ui.index("def diskCheckDone_") + 900])

    def test_new_layers_never_use_shadow_path_and_no_sockets_are_added(self):
        for name in ("orb_layers.py", "orb_character.py", "orb_view.py", "orb_spotlight.py", "mini_bar.py"):
            source = _source(name)
            self.assertNotIn("shadowPath", source, name)
            self.assertIsNone(re.search(r"^\s*import socket|socket\.socket|socket\.AF_", source, re.M), name)

    def test_reduce_motion_reactions_change_the_eye_shape_only(self):
        layers = _func(_source("orb_layers.py"), "play_reaction")
        self.assertIn("if reduce_motion:", layers)
        reduced = layers[layers.index("if reduce_motion:"):layers.index("for side in (\"L\", \"R\"):\n            morph")]
        self.assertNotIn("addAnimation_forKey_", reduced)


if __name__ == "__main__":
    unittest.main()
