"""Eney-style alive motion for the orb: squash-and-stretch hops, a playful size change, a shadow that follows each hop,
a wandering highlight, a lean toward the pointer, and the summon and landed hops. Headless."""
import ast
import math
import os
import random
import unittest

import orb_character as oc
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


def _extent(tracks):
    """How far the body's top edge rises above rest at each sample: the hop plus the stretch at its top."""
    return [y + om.BODY_SIZE / 2.0 * (sy - 1.0) for (_t, y), (_t2, sy) in zip(tracks["y"], tracks["sy"])]


class HopProfileTests(unittest.TestCase):
    @staticmethod
    def _breath_extra():
        return om.BODY_SIZE / 2.0 * (om.BREATH_SCALE_Y - 1.0)  # the idle breath can add this at the top too

    def test_a_hop_starts_and_ends_at_rest(self):
        for height in (om.HOP_HEIGHT_SMALL, om.HOP_HEIGHT_BIG, om.HOP_HEIGHT_LAND):
            y0, sx0, sy0 = om.hop_profile(0.0, 0.8, height)
            y1, sx1, sy1 = om.hop_profile(0.8, 0.8, height)
            for value in (y0, y1):
                self.assertAlmostEqual(value, 0.0)
            for value in (sx0, sy0, sx1, sy1):
                self.assertAlmostEqual(value, 1.0)

    def test_the_body_never_goes_below_rest_and_peaks_at_the_height(self):
        tracks = om.hop_tracks(0.8, om.HOP_HEIGHT_BIG)
        ys = [v for _t, v in tracks["y"]]
        self.assertGreaterEqual(min(ys), 0.0)
        self.assertAlmostEqual(max(ys), om.HOP_HEIGHT_BIG, delta=0.05)

    def test_it_squashes_before_takeoff_stretches_in_the_air_and_squashes_on_landing(self):
        tracks = om.hop_tracks(0.8, om.HOP_HEIGHT_BIG)
        sy = [v for _t, v in tracks["sy"]]
        sx = [v for _t, v in tracks["sx"]]
        takeoff = int(0.16 * 0.8 * oc.CLIP_FPS)
        self.assertLess(sy[takeoff], 1.0 - 0.8 * om.HOP_SQUASH)  # flat before it jumps
        self.assertGreater(sx[takeoff], 1.0)  # and wide
        self.assertGreater(max(sy), 1.0 + 0.8 * om.HOP_STRETCH)  # stretched in the air
        self.assertLess(min(sx), 1.0)  # and narrower
        landing = int(0.78 * 0.8 * oc.CLIP_FPS)
        self.assertLess(sy[landing], 1.0 - 0.7 * om.HOP_SQUASH)  # flat again on landing

    def test_the_volume_roughly_holds_so_it_reads_as_squash_and_stretch(self):
        tracks = om.hop_tracks(0.8, om.HOP_HEIGHT_BIG)
        for (_t, sx), (_t2, sy) in zip(tracks["sx"], tracks["sy"]):
            self.assertAlmostEqual(sx * sy, 1.0, delta=0.06)

    def test_every_hop_fits_inside_the_orb_window(self):
        """No clipping: hop + stretch + the idle bob stays under the window's top headroom, and the sides under theirs."""
        for height in (om.HOP_HEIGHT_SMALL, om.HOP_HEIGHT_BIG, om.HOP_HEIGHT_LAND):
            tracks = om.hop_tracks(0.8, height)
            self.assertLess(max(_extent(tracks)) + om.BOB_AMPLITUDE + self._breath_extra(), om.TOP_HEADROOM)
            side = max(om.BODY_SIZE / 2.0 * (sx - 1.0) for _t, sx in tracks["sx"])
            self.assertLess(side, om.SIDE_HEADROOM)

    def test_the_summon_hop_is_bigger_than_the_idle_one(self):
        self.assertGreater(om.HOP_HEIGHT_BIG, om.HOP_HEIGHT_SMALL)
        self.assertGreater(om.HOP_HEIGHT_BIG, om.HOP_HEIGHT_LAND)

    def test_tracks_end_exactly_at_the_hop_length(self):
        for samples in om.hop_tracks(0.64, 6.5).values():
            self.assertAlmostEqual(samples[-1][0], 0.64)
            self.assertTrue(all(math.isfinite(v) for _t, v in samples))


class GrowTests(unittest.TestCase):
    def test_a_playful_size_change_swells_dips_under_and_settles(self):
        values = [om.grow_profile(i / 100.0 * om.GROW_SECONDS) for i in range(101)]
        self.assertAlmostEqual(values[0], 1.0)
        self.assertAlmostEqual(values[-1], 1.0)
        self.assertAlmostEqual(max(values), om.GROW_PEAK, delta=0.01)
        self.assertAlmostEqual(min(values), om.GROW_DIP, delta=0.01)
        self.assertLess(values.index(max(values)), values.index(min(values)))  # up first, then under

    def test_it_stays_inside_the_window(self):
        extra = om.BODY_SIZE / 2.0 * (om.GROW_PEAK - 1.0)
        self.assertLess(extra + om.BOB_AMPLITUDE, om.TOP_HEADROOM)
        self.assertLess(extra, om.SIDE_HEADROOM)


class ShadowAndShineTests(unittest.TestCase):
    def test_the_shadow_shrinks_and_fades_with_height(self):
        low = om.shadow_for_height(0.0, 6.0)
        high = om.shadow_for_height(6.0, 6.0)
        self.assertEqual(low, (1.0, 1.0))
        self.assertAlmostEqual(high[0], om.HOP_SHADOW_MIN_SCALE)
        self.assertAlmostEqual(high[1], om.HOP_SHADOW_MIN_OPACITY)
        mid = om.shadow_for_height(3.0, 6.0)
        self.assertTrue(high[0] < mid[0] < low[0] and high[1] < mid[1] < low[1])

    def test_a_bad_height_leaves_the_shadow_alone(self):
        self.assertEqual(om.shadow_for_height(3.0, 0.0), (1.0, 1.0))
        self.assertEqual(om.shadow_for_height(-5.0, 6.0), (1.0, 1.0))
        self.assertEqual(om.shadow_for_height(99.0, 6.0)[0], om.HOP_SHADOW_MIN_SCALE)

    def test_the_shine_lags_the_hop(self):
        self.assertEqual(om.highlight_shift(0.0), 0.0)
        self.assertLess(om.highlight_shift(6.0), 0.0)
        self.assertAlmostEqual(om.highlight_shift(6.0), -om.HIGHLIGHT_LAG * 6.0)

    def test_the_highlight_wanders_on_two_different_periods_inside_the_body(self):
        self.assertNotEqual(*om.HIGHLIGHT_DRIFT_PERIODS)
        self.assertLess(max(om.HIGHLIGHT_DRIFT), om.BODY_SIZE / 10.0)


class TiltTests(unittest.TestCase):
    def test_the_orb_leans_toward_the_pointer(self):
        self.assertLess(om.tilt_degrees((900, 300), (600, 300)), 0.0)  # pointer on the right: clockwise
        self.assertGreater(om.tilt_degrees((300, 300), (600, 300)), 0.0)  # on the left: counter-clockwise
        self.assertEqual(om.tilt_degrees((600, 900), (600, 300)), 0.0)  # straight above or below: upright

    def test_the_lean_is_small_and_capped(self):
        self.assertAlmostEqual(om.tilt_degrees((600 + 10 ** 6, 0), (600, 0)), -om.TILT_MAX)
        self.assertAlmostEqual(om.tilt_degrees((600 - 10 ** 6, 0), (600, 0)), om.TILT_MAX)
        self.assertLessEqual(om.TILT_MAX, 6.0)

    def test_bad_input_leans_nowhere(self):
        for bad in (None, (), (float("nan"), 0)):
            self.assertEqual(om.tilt_degrees(bad, (0, 0)), 0.0)
        self.assertEqual(om.tilt_degrees((5, 5), None), 0.0)


class AccentAndReactionTests(unittest.TestCase):
    def test_hop_and_grow_are_idle_accents_with_real_timelines(self):
        names = [a.name for a in oc.ACCENTS]
        self.assertIn("hop", names)
        self.assertIn("grow", names)
        hop = oc.accent_timeline("hop")
        self.assertEqual(set(hop), {"body_y", "body_sx", "body_sy"})
        self.assertAlmostEqual(hop["body_y"][-1][0], oc.accent_seconds("hop"))
        grow = oc.accent_timeline("grow")
        self.assertEqual(set(grow), {"body_scale"})
        self.assertAlmostEqual(grow["body_scale"][-1][0], oc.accent_seconds("grow"))

    def test_they_come_up_now_and_then_not_constantly(self):
        rng = random.Random(11)
        picks = [oc.pick_accent(rng) for _ in range(20000)]
        share = sum(1 for p in picks if p in ("hop", "grow")) / 20000.0
        self.assertTrue(0.10 < share < 0.30)
        self.assertTrue(4.0 <= oc.next_accent_delay(random.Random(1)) <= 9.0)

    def test_the_hop_reactions_are_in_the_table_with_a_big_hop_body(self):
        for name in ("summon", "landed"):
            self.assertEqual(oc.REACTIONS[name].body[0], "big_hop")
        self.assertGreater(oc.REACTIONS["summon"].body[1], oc.REACTIONS["landed"].body[1])
        tracks = oc.reaction_body_tracks("summon")
        self.assertEqual(set(tracks), {"y", "sx", "sy"})
        self.assertLess(max(_extent(tracks)) + om.BOB_AMPLITUDE + om.BODY_SIZE / 2.0 * (om.BREATH_SCALE_Y - 1.0),
                        om.TOP_HEADROOM)

    def test_summon_and_landed_outrank_curious_and_tie_with_remember_and_success(self):
        pri = {name: r.priority for name, r in oc.REACTIONS.items()}
        for name in ("summon", "landed"):
            self.assertGreater(pri[name], pri["curious"])
            self.assertEqual(pri[name], pri["remember"])
            self.assertEqual(pri[name], pri["success"])

    def test_a_later_remember_replaces_a_landing_hop_but_curious_waits(self):
        now = [100.0]
        queue = oc.ReactionQueue(lambda: now[0])
        self.assertTrue(queue.offer("landed"))
        self.assertFalse(queue.offer("curious"))
        self.assertTrue(queue.offer("remember"))
        self.assertEqual(queue.current(), "remember")

    def test_a_second_summon_inside_its_cooldown_is_ignored(self):
        now = [100.0]
        queue = oc.ReactionQueue(lambda: now[0])
        self.assertTrue(queue.offer("summon"))
        now[0] += 0.3
        self.assertFalse(queue.offer("summon"))
        now[0] += 0.4
        self.assertTrue(queue.offer("summon"))


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.layers = _source("orb_layers.py")
        self.view = _source("orb_view.py")
        self.ui = _source("assistant_ui.py")

    def test_reactions_and_accents_drive_the_shadow_and_the_shine(self):
        self.assertIn("_hop_extras", _func(self.layers, "play_accent"))
        self.assertIn("_hop_extras", _func(self.layers, "play_reaction"))
        stop = _func(self.layers, "stop_reaction")
        self.assertIn('"sx"', stop)
        self.assertIn("shadowScale", stop)
        self.assertIn('"sx": ("transform.scale.x", 1.0)', _func(self.layers, "play_reaction"))
        self.assertIn('"body_sx"', _func(self.layers, "play_accent"))

    def test_the_highlight_drifts_only_while_the_idle_passives_run(self):
        self.assertIn("shineDrift", _func(self.layers, "_add_passives"))
        self.assertIn("shineDriftx", _func(self.layers, "_remove_passives"))

    def test_reset_motion_clears_the_new_layers_and_the_lean(self):
        body = _func(self.layers, "reset_motion")
        self.assertIn("self.shadow, self.highlight", body)
        self.assertIn("self.tilt = 0.0", body)

    def test_the_lean_rides_on_the_body_transform(self):
        self.assertIn("self.lean + self.tilt", self.layers)
        self.assertIn("def set_tilt", self.layers)
        self.assertIn("abs(degrees - self.tilt) < TILT_EPS", _func(self.layers, "set_tilt"))

    def test_the_lean_only_applies_when_the_orb_is_calm(self):
        body = _func(self.view, "applyTilt")
        for needle in ('self.character == "idle"', "not self.cfg[2]", "not self.cfg[3]", "not self.dragActive()",
                       "not self.reduceMotion", "not self.asleep"):
            self.assertIn(needle, body)
        self.assertIn("self.tree.set_tilt(0.0)", body)

    def test_idle_hops_wait_while_dragging_or_typing(self):
        play = _func(self.view, "playAccent_")
        self.assertIn("self.dragActive()", play)
        self.assertIn("self.cfg[3]", play)  # the typing pill (popover)
        sync = _func(self.view, "syncMotion")
        self.assertIn("idle and not popover", sync)  # the accent timer is off while the pill is open
        self.assertIn("not self.dragActive()", sync)

    def test_a_drag_that_ends_without_a_drop_cannot_pause_the_orb_forever(self):
        self.assertIn("time.monotonic() - self.dragStamp < 0.6", _func(self.view, "dragActive"))

    def test_idle_motion_stays_gated_on_visible_and_motion(self):
        sync = _func(self.view, "syncMotion")
        self.assertIn("idle_active(visible, motion, docked, self.asleep)", sync)
        self.assertTrue(om.idle_active(True, True, False, False))
        for args in ((False, True, False, False), (True, False, False, False), (True, True, True, False),
                     (True, True, False, True)):
            self.assertFalse(om.idle_active(*args), args)

    def test_the_pointer_poll_is_cheap_and_off_when_the_orb_is_hidden(self):
        sync = _func(self.view, "syncMotion")
        self.assertIn("tracking_active(visible, motion, self.asleep)", sync)
        self.assertIn("TRACK_PUPILS or TRACK_TILT", sync)
        follow = _func(self.view, "followCursor")
        self.assertIn("if not TRACK_PUPILS:", follow)  # the pupil work stays off
        self.assertEqual(om.CURSOR_POLL_SECONDS, 1.0 / 20.0)

    def test_reduce_motion_plays_only_the_eye_shape_for_the_hops(self):
        body = _func(self.layers, "play_reaction")
        self.assertLess(body.index("if reduce_motion:"), body.index("reaction_body_tracks(name)"))
        self.assertIn("return", body[body.index("if reduce_motion:"):body.index("reaction_body_tracks(name)")])

    def test_the_hotkey_summons_with_a_hop_before_the_pill_opens(self):
        for name in ("focusTypeField_", "hotkeyAfterClear_"):
            body = _func(self.ui, name)
            self.assertIn('self._orb_hop("summon")', body, name)
            self.assertLess(body.index('self._orb_hop("summon")'), body.index("self.expandMiniBar_(None)"), name)

    def test_a_capture_landing_hops_once_on_either_route(self):
        result = _func(self.ui, "showCaptureResult_")
        self.assertIn('self._orb_hop("landed")', result)
        self.assertIn('not getattr(self, "_inline_pending", None)', result)
        self.assertIn('self._orb_hop("landed")', _func(self.ui, "inlineMoveTick_"))

    def test_the_hop_helper_goes_through_the_reaction_queue(self):
        self.assertIn("orb.offerReaction(name)", _func(self.ui, "_orb_hop"))

    def test_the_orb_window_is_never_enlarged_for_a_hop(self):
        """Hops live inside the existing orb window (see the headroom tests), so no wider window can block clicks."""
        self.assertNotIn("setFrame", _func(self.layers, "play_reaction"))
        self.assertNotIn("setFrame", _func(self.layers, "play_accent"))
        self.assertIn("def hitTest_", self.view)  # the orb view still lets clicks through to the background


if __name__ == "__main__":
    unittest.main()
