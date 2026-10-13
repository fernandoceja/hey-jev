"""Idle mic capsule, and the blue mic while Option is held. No AppKit."""
import os
import unittest

from mini_bar import (
    BAR_H,
    BAR_MIN_W,
    BAR_W,
    MIC_TINT_NORMAL,
    MIC_TINT_SPEAKING,
    PLACEHOLDER,
    PillPresentation,
    capsule_click_moved,
    capsule_controls,
    capsule_size,
    collapsed_frame,
    expanded_frame_from_capsule,
    status_shows_in_pill,
)

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


class TestIdleCapsule(unittest.TestCase):
    def test_idle_is_a_collapsed_mic_capsule(self):
        pill = PillPresentation()
        self.assertTrue(pill.collapsed)
        self.assertFalse(pill.expanded)
        self.assertEqual(pill.mic_tint(), MIC_TINT_NORMAL)
        size = capsule_size()
        self.assertEqual(size, (BAR_H, BAR_H))
        self.assertLess(size[0], BAR_MIN_W)
        frames = capsule_controls(size)
        self.assertEqual(list(frames), ["mic"])
        mic = frames["mic"]
        self.assertGreater(mic[2], 16.0)
        self.assertEqual(mic[0] + mic[2] / 2.0, size[0] / 2.0)
        self.assertEqual(mic[1] + mic[3] / 2.0, size[1] / 2.0)
        self.assertGreaterEqual(mic[0], 0.0)
        self.assertLessEqual(mic[0] + mic[2], size[0])

    def test_click_expands_to_the_typing_pill(self):
        pill = PillPresentation()
        expanded = (80.0, 140.0, BAR_W, BAR_H)
        capsule = collapsed_frame(expanded)
        self.assertEqual(pill.click(), "expanded")
        self.assertTrue(pill.expanded)
        self.assertFalse(pill.collapsed)
        # The typing pill is the same default size, and the mic stays on the right edge.
        restored = expanded_frame_from_capsule(capsule, (BAR_W, BAR_H))
        self.assertEqual(restored, expanded)
        self.assertEqual(capsule[0] + capsule[2], expanded[0] + expanded[2])
        self.assertEqual(PLACEHOLDER, "Type to Jev\u2026")

    def test_command_finished_collapses(self):
        pill = PillPresentation()
        pill.click()
        self.assertEqual(pill.command_started(), "expanded")
        self.assertEqual(pill.note_status("Thinking", True), "expanded")
        self.assertEqual(pill.note_status("Ready", True), "expanded")
        self.assertEqual(pill.command_finished(), "collapsed")
        self.assertTrue(pill.collapsed)
        self.assertFalse(pill.busy)

    def test_a_finished_command_with_nothing_to_show_collapses_immediately(self):
        pill = PillPresentation()
        pill.click()
        pill.command_started()
        self.assertEqual(pill.note_status("Ready", False), "collapsed")
        self.assertTrue(pill.collapsed)

    def test_focus_loss_collapses(self):
        pill = PillPresentation()
        pill.click()
        self.assertEqual(pill.focus_lost(), "collapsed")
        self.assertTrue(pill.collapsed)

    def test_focus_loss_during_a_command_waits_until_it_finishes(self):
        pill = PillPresentation()
        pill.click()
        pill.command_started()
        self.assertEqual(pill.focus_lost(), "expanded")
        self.assertTrue(pill.expanded)
        self.assertEqual(pill.command_finished(), "collapsed")

    def test_escape_collapses(self):
        pill = PillPresentation()
        pill.click()
        pill.command_started()
        self.assertEqual(pill.escape(), "collapsed")
        self.assertTrue(pill.collapsed)
        self.assertFalse(pill.busy)
        self.assertEqual(pill.escape(), "collapsed")

    def test_option_down_turns_the_mic_blue_and_release_restores_it(self):
        pill = PillPresentation()
        self.assertEqual(pill.option_changed(True), MIC_TINT_SPEAKING)
        self.assertEqual(pill.mic_tint(), "blue")
        self.assertTrue(pill.collapsed)
        self.assertEqual(pill.option_changed(False), MIC_TINT_NORMAL)
        self.assertEqual(pill.mic_tint(), "normal")
        pill.click()
        self.assertEqual(pill.option_changed(True), "blue")
        self.assertTrue(pill.expanded)
        self.assertEqual(pill.option_changed(False), "normal")
        self.assertTrue(pill.expanded)

    def test_push_to_talk_does_not_unfold_the_capsule(self):
        self.assertFalse(status_shows_in_pill("Listening", option_down=True))
        self.assertFalse(status_shows_in_pill("Listening", option_down=False))
        self.assertFalse(status_shows_in_pill("Ready", option_down=True))
        self.assertTrue(status_shows_in_pill("Ready", option_down=False))
        self.assertFalse(capsule_click_moved((0.0, 0.0), (1.0, 1.0)))
        self.assertTrue(capsule_click_moved((0.0, 0.0), (6.0, 0.0)))

    def test_a_reply_opens_the_pill_and_closing_it_returns_to_the_capsule(self):
        pill = PillPresentation()
        self.assertEqual(pill.reveal_reply(), "expanded")
        self.assertTrue(pill.showing_reply)
        self.assertEqual(pill.display_cleared(), "collapsed")
        pill.click()
        pill.reveal_reply()
        self.assertEqual(pill.keep_typing(), "expanded")
        self.assertFalse(pill.showing_reply)

    def test_the_field_timer_does_not_finish_a_slow_command(self):
        """Thinking starts the 4-second field clock. jev() can outlast it."""
        pill = PillPresentation()
        pill.click()
        pill.command_started()
        self.assertEqual(pill.note_status("Thinking", True), "expanded")
        self.assertEqual(pill.note_status("Doing it", True), "expanded")
        self.assertEqual(pill.display_cleared(), "expanded")
        self.assertTrue(pill.busy)
        self.assertTrue(pill.expanded)
        self.assertEqual(pill.note_status("Ready", True), "expanded")
        self.assertFalse(pill.busy)
        self.assertTrue(pill.expanded)
        self.assertEqual(pill.display_cleared(), "collapsed")
        self.assertTrue(pill.collapsed)

    def test_a_hidden_bar_does_not_leave_the_command_busy(self):
        """A displayable line that was not shown is not a reply on screen."""
        pill = PillPresentation()
        pill.click()
        pill.command_started()
        self.assertEqual(pill.note_status("Thinking", False), "expanded")
        self.assertTrue(pill.busy)
        self.assertFalse(pill.showing_reply)
        self.assertEqual(pill.display_cleared(), "expanded")
        self.assertTrue(pill.busy)
        self.assertEqual(pill.note_status("Ready", False), "collapsed")
        self.assertFalse(pill.busy)
        self.assertFalse(pill.showing_reply)
        again = PillPresentation()
        again.command_started()
        self.assertEqual(again.note_status("Something went wrong", False), "collapsed")
        self.assertFalse(again.busy)


class TestPillCollapseWiring(unittest.TestCase):
    def test_the_window_collapses_and_tints_the_mic_from_the_same_rules(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        flags = _func(ui, "_handle_flags")
        self.assertIn("on_flags", flags)
        self.assertIn("self.controls.put(token)", flags)
        self.assertIn("option_changed(is_down)", flags)
        self.assertIn("_apply_mic_tint", flags)
        tint = _func(ui, "_apply_pill_tint")
        self.assertIn("speakingTint", tint)
        self.assertIn("systemBlueColor", tint)
        expand = _func(ui, "expandMiniBar_")
        self.assertIn("pill.click()", expand)
        self.assertIn("_focus_pill_field", expand)
        dismiss = _func(ui, "miniDismiss_")
        self.assertIn("pill.escape()", dismiss)
        self.assertIn("_restore_front_app", dismiss)
        self.assertIn("_apply_pill_presentation", dismiss)
        self.assertNotIn("bar.dismiss()", dismiss)
        resign = _func(ui, "windowDidResignKey_")
        self.assertIn("pill.focus_lost()", resign)
        self.assertIn("_apply_pill_presentation", resign)
        submit = _func(ui, "miniSubmit_")
        self.assertIn("pill.command_started()", submit)
        self.assertIn('self.controls.put(plan["control"])', submit)
        self.assertLess(submit.index("command_started"), submit.index("_restore_front_app"))
        self.assertLess(submit.index("_restore_front_app"), submit.index("hold_local_reply"))
        tick = _func(ui, "tick_")
        self.assertNotIn("_finish_pill_command", tick)
        self.assertNotIn("command_finished", tick)
        self.assertIn("display_cleared()", tick)
        self.assertLess(tick.index("reply_due_clear"), tick.index("display_cleared()"))
        status = _func(ui, "updateStatus_")
        self.assertIn("note_status(state, displayed)", status)
        self.assertNotIn("bool(shown) and show_line)", status)
        self.assertIn("displayed = False", status)
        self.assertIn("displayed = True", status)
        self.assertLess(status.index("displayed = True"), status.index("_show_bar_reply"))
        self.assertLess(status.index("_show_bar_reply"), status.index("note_status(state, displayed)"))
        self.assertIn("reveal_reply", status)
        self.assertIn("status_shows_in_pill", status)
        self.assertIn("_show_bar_reply", status)
        order = _func(ui, "_order_bar_front")
        self.assertIn("place_bar(saved, screens, size)", order)
        self.assertIn("_apply_pill_presentation", order)
        layout = _func(ui, "_layout_mini_bar")
        self.assertIn("_layout_collapsed_capsule", layout)
        self.assertIn("bar_controls", layout)
        capsule = _func(ui, "_layout_collapsed_capsule")
        self.assertIn("capsule_controls", capsule)
        self.assertIn('setHidden_(True)', capsule)
        self.assertIn('"mic.fill"', capsule)
        background = _func(ui, "mouseDown_")
        self.assertIn("pillCollapsed", background)
        self.assertIn("_collapsed_click_or_drag", background)
        self.assertLess(background.index("resetMiniBarPosition_"), background.index("resize_frame"))
        self.assertLess(background.index("resize_frame"), background.index("drag_origin"))
        capsule_click = _func(ui, "_collapsed_click_or_drag")
        self.assertIn("expandMiniBar_", capsule_click)
        self.assertIn("capsule_click_moved", capsule_click)
        hold = ui[ui.index("class HoldMicButton"):ui.index("class PillTextField")]
        self.assertIn('"pillRole", "mic") == "expand"', hold)
        self.assertIn("expandMiniBar_", hold)
        bar = open(os.path.join(ROOT, "mini_bar.py"), encoding="utf-8").read()
        self.assertNotIn("import socket", bar)
        self.assertNotIn("listen(", bar)
