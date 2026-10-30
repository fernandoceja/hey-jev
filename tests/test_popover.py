"""Orb click popover layout and presentation rules. No AppKit."""
import math
import os
import unittest

from mini_bar import (
    BAR_H,
    BAR_W,
    ORB_PANEL,
    POPOVER_GAP,
    POPOVER_PANEL_PAD,
    PillPresentation,
    greeting_text,
    home_draft_from_popover,
    popover_open_animation,
    popover_side,
    popover_subframes,
    popover_controls,
    window_frame_for_presentation,
    collapsed_frame,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIR = (0.0, 70.0, 1440.0, 806.0)
NARROW = (0.0, 70.0, 220.0, 806.0)


def _func(source, name):
    start = source.index(f"def {name}")
    line_start = source.rfind("\n", 0, start) + 1
    indent = start - line_start
    marker = "\n" + (" " * indent) + "def "
    nxt = source.find(marker, start + 1)
    if nxt < 0:
        nxt = len(source)
    return source[start:nxt]


class TestPopoverLayout(unittest.TestCase):
    def test_greeting_copy_and_home_draft(self):
        self.assertEqual(greeting_text(), "Hi, Fernando. What can I help with?")
        self.assertEqual(home_draft_from_popover("  draft "), "  draft ")
        self.assertEqual(home_draft_from_popover(None), "")

    def test_popover_flips_to_the_right_when_the_left_edge_is_tight(self):
        orb = (16.0, 200.0, ORB_PANEL, ORB_PANEL)
        self.assertEqual(popover_side(orb, 280.0, AIR), "right")
        composer = (900.0, 200.0, BAR_W, BAR_H)
        narrow_orb = (16.0, 200.0, ORB_PANEL, ORB_PANEL)
        composer_tight = (
            narrow_orb[0] + ORB_PANEL + POPOVER_GAP - BAR_W,
            200.0,
            BAR_W,
            BAR_H,
        )
        layout = popover_subframes(composer_tight, NARROW)
        self.assertEqual(layout["side"], "right")
        self.assertGreater(layout["greeting"][0], layout["orb"][0])

    def test_popover_stays_on_the_left_with_room_and_keeps_the_orb_anchor(self):
        composer = (900.0, 200.0, BAR_W, BAR_H)
        layout = popover_subframes(composer, AIR)
        self.assertEqual(layout["side"], "left")
        ox, oy, ow, oh = layout["orb"]
        cx, _cy, cw, _ch = layout["composer"]
        self.assertAlmostEqual(cx + cw + POPOVER_PANEL_PAD + POPOVER_GAP, ox, delta=1.0)
        px, py, pw, ph = layout["panel"]
        self.assertAlmostEqual(px + pw + POPOVER_GAP, ox, delta=1.0)
        self.assertLessEqual(py, layout["footer"]["footer_bottom"])
        frame = window_frame_for_presentation(composer, True, AIR)
        self.assertGreater(frame[2], ORB_PANEL)
        self.assertTrue(all(math.isfinite(v) for v in frame))

    def test_collapsed_window_is_still_the_orb_only(self):
        composer = (400.0, 200.0, BAR_W, BAR_H)
        collapsed = window_frame_for_presentation(composer, False, AIR)
        self.assertEqual(collapsed, collapsed_frame(composer))

    def test_open_animation_respects_reduce_motion(self):
        self.assertEqual(popover_open_animation(True)["duration"], 0.0)
        self.assertGreaterEqual(popover_open_animation(False)["duration"], 0.16)
        self.assertLessEqual(popover_open_animation(False)["duration"], 0.20)

    def test_popover_controls_include_expand(self):
        frames = popover_controls()
        self.assertIn("expand", frames)
        self.assertLess(frames["field"][0] + frames["field"][2], frames["expand"][0])


class TestPopoverBehaviors(unittest.TestCase):
    def test_escape_busy_blur_reply_timeout_and_typing_over_replies(self):
        pill = PillPresentation()
        pill.click()
        pill.command_started()
        self.assertEqual(pill.escape(), "collapsed")
        pill = PillPresentation()
        pill.click()
        pill.command_started()
        self.assertEqual(pill.focus_lost(), "expanded")
        self.assertEqual(pill.command_finished(), "collapsed")
        pill = PillPresentation()
        pill.click()
        pill.command_started()
        self.assertEqual(pill.note_status("Thinking", True), "expanded")
        self.assertEqual(pill.display_cleared(), "expanded")
        self.assertEqual(pill.note_status("Ready", True), "expanded")
        self.assertEqual(pill.display_cleared(), "collapsed")
        pill = PillPresentation()
        pill.reveal_reply()
        self.assertEqual(pill.keep_typing(), "expanded")


class TestPopoverWiring(unittest.TestCase):
    def test_ui_wires_popover_expand_and_hold_mic_tracking(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        expand = _func(ui, "expandMiniBar_")
        self.assertIn("_apply_pill_presentation(animate_open=True)", expand)
        self.assertNotIn("_place_expanded_on_main_screen()", expand)
        self.assertIn("miniExpandHome_", ui)
        home = _func(ui, "miniExpandHome_")
        self.assertIn("home_draft_from_popover", home)
        self.assertIn("_show_full_window", home)
        self.assertIn("showMain_", _func(ui, "fullOpenHome_"))
        dispatch = _func(ui, "_dispatch_text_plan")
        self.assertIn("command_started()", dispatch)
        self.assertIn("miniRefreshChips_", ui)
        self.assertIn("miniChip_", ui)
        hold = ui[ui.index("class HoldMicButton"):ui.index("class PillTextField")]
        self.assertIn("nextEventMatchingMask_", hold)
        self.assertIn("miniMicUp_", hold)
