"""Eney bubble v2, PR 6a: expand from the orb, dock on the divider, collapse back. Pure geometry and state, no AppKit."""
import itertools
import os
import unittest

import full_window as fw
import orb_motion as om

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN = (0.0, 0.0, 1440.0, 900.0)


def _src(name):
    return open(os.path.join(ROOT, name), encoding="utf-8").read()


def _func(source, name):
    """The body of one def, cut at the next sibling def or decorator at the same indent."""
    start = source.index(f"def {name}")
    line_start = source.rfind("\n", 0, start) + 1
    indent = start - line_start
    end = len(source)
    for marker in ("\n" + " " * indent + "def ", "\n" + " " * indent + "@"):
        found = source.find(marker, start + 10)
        if found != -1:
            end = min(end, found)
    return source[start:end]


def _inside(inner, outer):
    x, y, w, h = inner
    ox, oy, ow, oh = outer
    return x >= ox - 0.01 and y >= oy - 0.01 and x + w <= ox + ow + 0.01 and y + h <= oy + oh + 0.01


def _center(rect):
    x, y, w, h = rect
    return (x + w / 2.0, y + h / 2.0)


class ExpandRectsTests(unittest.TestCase):
    def test_start_is_ten_percent_of_target_and_centred_on_orb(self):
        target = (300.0, 200.0, 760.0, 560.0)
        orb = (900.0, 500.0, 72.0, 72.0)
        start, end = om.expand_rects(orb, target, SCREEN)
        self.assertAlmostEqual(start[2], 76.0)
        self.assertAlmostEqual(start[3], 56.0)
        self.assertEqual(_center(start), _center(orb))

    def test_start_stays_on_screen_when_the_orb_is_at_an_edge(self):
        target = (300.0, 200.0, 760.0, 560.0)
        for orb in [(0.0, 0.0, 72.0, 72.0), (1368.0, 828.0, 72.0, 72.0), (1400.0, 10.0, 72.0, 72.0)]:
            start, _end = om.expand_rects(orb, target, SCREEN)
            self.assertTrue(_inside(start, SCREEN), (orb, start))

    def test_end_is_the_target_frame(self):
        target = (120.0, 80.0, 900.0, 640.0)
        _start, end = om.expand_rects((500.0, 400.0, 72.0, 72.0), target, SCREEN)
        self.assertEqual(end, target)

    def test_without_a_screen_the_start_is_clamped_to_the_target(self):
        target = (100.0, 100.0, 760.0, 560.0)
        start, _ = om.expand_rects((0.0, 0.0, 72.0, 72.0), target)
        self.assertTrue(_inside(start, target))


class DockPointTests(unittest.TestCase):
    def test_centre_x_is_window_x_plus_sidebar_minus_18(self):
        for win in [(100.0, 100.0, 760.0, 560.0), (-400.0, 30.0, 900.0, 700.0), (640.0, 10.0, 1100.0, 800.0)]:
            cx, _cy = _center(om.dock_point(win))
            self.assertAlmostEqual(cx, win[0] + fw.SIDEBAR_W - 18.0)

    def test_centre_y_sits_below_the_titlebar(self):
        for win in [(100.0, 100.0, 760.0, 560.0), (0.0, 0.0, 1000.0, 700.0)]:
            _cx, cy = _center(om.dock_point(win))
            top = win[1] + win[3]
            self.assertAlmostEqual(cy, top - fw.TITLEBAR_H - 18.0 - 12.0)

    def test_dock_never_overlaps_the_titlebar(self):
        for win in [(100.0, 100.0, 760.0, 560.0), (0.0, 0.0, 600.0, 420.0), (50.0, 50.0, 1600.0, 1200.0)]:
            x, y, w, h = om.dock_point(win)
            self.assertLessEqual(y + h, win[1] + win[3] - fw.TITLEBAR_H)
            self.assertTrue(_inside((x, y, w, h), win))

    def test_default_dock_is_the_half_size_orb(self):
        self.assertEqual(fw.DOCK_ORB, 36.0)
        _x, _y, w, h = om.dock_point((0.0, 0.0, 760.0, 560.0))
        self.assertEqual((w, h), (36.0, 36.0))

    def test_full_window_dock_rect_matches_dock_point(self):
        win = (100.0, 100.0, 760.0, 560.0)
        local = fw.dock_rect(fw.full_layout(760.0, 560.0))
        expected = om.dock_point(win)
        self.assertAlmostEqual(win[0] + local[0], expected[0])
        self.assertAlmostEqual(win[1] + local[1], expected[1])
        self.assertEqual(local[2:], expected[2:])


class CollapseTargetTests(unittest.TestCase):
    def test_saved_origin_is_kept_when_it_is_on_screen(self):
        self.assertEqual(om.collapse_target((600.0, 300.0), [SCREEN]), (600.0, 300.0))

    def test_unplugged_display_falls_back_on_screen(self):
        external = (1440.0, 0.0, 1920.0, 1080.0)
        saved = (3000.0, 400.0)  # on the external display, which is now gone
        x, y = om.collapse_target(saved, [SCREEN])
        self.assertTrue(_inside((x, y, 72.0, 72.0), SCREEN))
        self.assertNotEqual((x, y), saved)
        self.assertIsNotNone(external)

    def test_fallback_is_centred_on_the_orb_width(self):
        x, _y = om.collapse_target(None, [SCREEN], size=(72.0, 72.0))
        self.assertAlmostEqual(x, (1440.0 - 72.0) / 2.0)

    def test_no_screens_matches_place_bar(self):
        from mini_bar import place_bar
        self.assertEqual(om.collapse_target((10.0, 10.0), []), place_bar((10.0, 10.0), []))


class TrackingTests(unittest.TestCase):
    def test_pupils_track_while_the_bob_is_docked(self):
        # Docking stops the bob (idle_active is False) but the pupils keep following the cursor.
        self.assertFalse(om.idle_active(True, True, True, False))
        self.assertTrue(om.tracking_active(True, True, False))

    def test_tracking_truth_table(self):
        for visible, motion, asleep in itertools.product((False, True), repeat=3):
            self.assertEqual(om.tracking_active(visible, motion, asleep),
                             bool(visible and motion and not asleep))


class OrbStateMachineTests(unittest.TestCase):
    def test_full_cycle(self):
        state = om.ORB_STATE_IDLE
        for event, expected in [("expand", om.ORB_STATE_EXPANDING), ("landed", om.ORB_STATE_OPEN),
                                ("collapse", om.ORB_STATE_COLLAPSING), ("landed", om.ORB_STATE_IDLE)]:
            state = om.orb_window_next(state, event)
            self.assertEqual(state, expected)

    def test_events_that_do_not_apply_are_ignored(self):
        ignored = {
            om.ORB_STATE_IDLE: ("collapse", "landed"),
            om.ORB_STATE_EXPANDING: ("expand", "collapse"),
            om.ORB_STATE_OPEN: ("expand", "landed"),
            om.ORB_STATE_COLLAPSING: ("expand", "collapse"),
        }
        for state, events in ignored.items():
            for event in events:
                self.assertIsNone(om.orb_window_next(state, event), (state, event))

    def test_repeated_clicks_never_get_stuck(self):
        # Ten quick rounds, with clicks that land mid-animation in between. Every round ends idle.
        state = om.ORB_STATE_IDLE
        for _ in range(10):
            state = om.orb_window_next(state, "expand") or state
            state = om.orb_window_next(state, "collapse") or state  # a double click while expanding: ignored
            state = om.orb_window_next(state, "landed") or state
            state = om.orb_window_next(state, "expand") or state  # a click while open is a collapse, not an expand
            state = om.orb_window_next(state, "collapse") or state
            state = om.orb_window_next(state, "collapse") or state  # the close after the click: ignored
            state = om.orb_window_next(state, "landed") or state
            self.assertEqual(state, om.ORB_STATE_IDLE)

    def test_every_state_can_reach_idle(self):
        for start in (om.ORB_STATE_IDLE, om.ORB_STATE_EXPANDING, om.ORB_STATE_OPEN, om.ORB_STATE_COLLAPSING):
            state = start
            for _ in range(4):
                if state == om.ORB_STATE_IDLE:
                    break
                state = om.orb_window_next(state, "landed") or om.orb_window_next(state, "collapse") or state
            self.assertEqual(state, om.ORB_STATE_IDLE, start)


class ExpandWiringTests(unittest.TestCase):
    def setUp(self):
        self.ui = _src("assistant_ui.py")

    def test_single_click_expands_and_right_click_opens_the_popover(self):
        self.assertIn("expandOrbToFull_", _func(self.ui, "_collapsed_click_or_drag"))
        right = _func(self.ui, "rightMouseDown_")
        self.assertIn("expandMiniBar_", right)
        self.assertIn("not docked", right)

    def test_typing_while_docked_focuses_the_window_instead_of_a_popover(self):
        mini = _func(self.ui, "expandMiniBar_")
        self.assertLess(mini.index("_orb_docked_now()"), mini.index("_apply_pill_presentation"))
        self.assertIn("_focus_docked_window()", mini)
        focus = _func(self.ui, "_focus_docked_window")
        self.assertIn("isVisible()", focus)
        self.assertIn("makeFirstResponder_(self.full_field)", focus)

    def test_a_docked_orb_collapses_on_click_and_never_drags(self):
        docked = _func(self.ui, "_docked_click")
        self.assertIn("NSEventMaskLeftMouseUp", docked)
        self.assertIn("collapseOrbFromFull_", docked)
        self.assertNotIn("setFrameOrigin_", docked)

    def test_expand_builds_the_window_then_ghosts_out_of_the_orb(self):
        expand = _func(self.ui, "_expand_orb_to_full")
        self.assertLess(expand.index("_build_full_window"), expand.index("_snapshot_full_window"))
        self.assertIn("_make_orb_ghost", expand)
        self.assertIn("orb_layers.animate_ghost", expand)
        self.assertIn("dock_point", expand)
        self.assertIn("_sync_orb()", expand)  # the bob stops before the orb moves
        self.assertIn("_start_orb_spring", expand)

    def test_landing_shows_the_real_window_and_docks_the_orb(self):
        land = _func(self.ui, "_land_orb_expand")
        self.assertIn("makeKeyAndOrderFront_", land)
        self.assertIn("addChildWindow_ordered_", land)
        self.assertIn("_remove_orb_ghost()", land)

    def test_collapse_is_the_exact_reverse_and_resumes_the_bob(self):
        collapse = _func(self.ui, "_collapse_orb_from_full")
        self.assertLess(collapse.index("removeChildWindow_"), collapse.index("orderOut_"))
        self.assertIn("setLevel_(BAR_LEVEL)", collapse)
        self.assertIn("collapse_target", collapse)
        self.assertIn("EXPAND_START_SCALE", collapse)
        land = _func(self.ui, "_land_orb_collapse")
        self.assertIn("_sync_orb()", land)  # the bob resumes once the orb is free

    def test_closing_the_window_collapses_it(self):
        self.assertIn("_collapse_orb_from_full", _func(self.ui, "windowWillClose_"))

    def test_every_transition_lands_through_one_timer(self):
        self.assertIn("orbTransitionLanded:", self.ui)
        self.assertIn("_schedule_orb_landing(duration)", _func(self.ui, "_expand_orb_to_full"))
        self.assertIn("_schedule_orb_landing(duration)", _func(self.ui, "_collapse_orb_from_full"))

    def test_reduce_motion_jumps_the_orb_and_crossfades_the_ghost(self):
        expand = _func(self.ui, "_expand_orb_to_full")
        collapse = _func(self.ui, "_collapse_orb_from_full")
        self.assertIn("reduce_motion=reduce", expand)
        self.assertIn("reduce_motion=reduce", collapse)
        self.assertIn("_place_orb_rect(dock_point", expand)
        self.assertIn("_place_orb_rect(target)", collapse)
        layers = _src("orb_layers.py")
        self.assertIn("REDUCE_CROSSFADE_SECONDS", layers)

    def test_transitions_are_logged(self):
        for marker in ("orb expand: start", "orb expand: done", "orb collapse: start", "orb collapse: done"):
            self.assertIn(marker, self.ui)

    def test_guards_stop_window_moves_from_saving_the_docked_origin(self):
        self.assertIn("_orb_docked_now()", _func(self.ui, "windowDidMove_"))
        self.assertIn("_orb_docked_now()", _func(self.ui, "windowDidResize_"))
        self.assertIn("_orb_docked_now()", _func(self.ui, "_peek_consider"))


class GhostLayerTests(unittest.TestCase):
    def test_new_layers_set_contents_scale_and_avoid_shadow_path(self):
        layers = _src("orb_layers.py")
        ghost = layers[layers.index("def ghost_layer"):layers.index("def animate_ghost")]
        self.assertIn("setContentsScale_", ghost)
        self.assertNotIn("shadowPath", layers)
        self.assertNotIn("shadowPath", _src("assistant_ui.py"))

    def test_docking_does_not_touch_window_levels_beyond_the_documented_restore(self):
        ui = _src("assistant_ui.py")
        expand = _func(ui, "_expand_orb_to_full") + _func(ui, "_land_orb_expand")
        self.assertNotIn("setLevel_", expand)
        self.assertNotIn("setFloatingPanel_", expand)
        collapse = _func(ui, "_collapse_orb_from_full")
        self.assertEqual(collapse.count("setLevel_"), 1)

    def test_orb_pupils_track_while_docked(self):
        view = _src("orb_view.py")
        sync = _func(view, "syncMotion")
        self.assertIn("tracking_active", sync)
        self.assertIn("self.tracking", _func(view, "followCursor"))
        self.assertNotIn("self.alive", _func(view, "followCursor"))

    def test_no_sockets_or_secrets_in_the_new_geometry(self):
        for name in ("orb_motion.py", "full_window.py"):
            src = _src(name)
            for bad in ("socket", "Keychain", "bridge_secret", "subprocess"):
                self.assertNotIn(bad, src, (name, bad))


if __name__ == "__main__":
    unittest.main()
