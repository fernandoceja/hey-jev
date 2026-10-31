"""A click outside the popover closes only the popover. The orb stays visible. No AppKit."""
import os
import unittest

from mini_bar import (
    BarController,
    PillPresentation,
    clicked_outside_popover,
    orb_after_click_away,
)
from tests.test_pill_collapse import _func

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POPOVER = (100.0, 100.0, 420.0, 300.0)


def _ui():
    with open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8") as fh:
        return fh.read()


class TestClickOutsideKeepsOrbVisible(unittest.TestCase):
    def _open_popover(self):
        bar = BarController(enabled=True)
        bar.main_window_changed(False)  # main window closed, so the orb is up
        pill = PillPresentation()
        pill.click()
        return bar, pill

    def test_click_outside_keeps_the_orb_visible(self):
        bar, pill = self._open_popover()
        self.assertTrue(clicked_outside_popover(pill.expanded, (20.0, 20.0), POPOVER))
        pill.click_away()
        self.assertTrue(pill.collapsed)
        self.assertTrue(bar.should_show())  # closing the popover never hides the bar
        self.assertEqual(orb_after_click_away(bar.should_show(), True, False), "keep")

    def test_click_outside_brings_back_an_orb_that_a_fade_would_hide(self):
        bar, pill = self._open_popover()
        pill.click_away()
        self.assertEqual(orb_after_click_away(bar.should_show(), True, True), "show")
        self.assertEqual(orb_after_click_away(bar.should_show(), False, False), "show")

    def test_click_away_never_hides(self):
        for show in (True, False):
            for visible in (True, False):
                for pending in (True, False):
                    self.assertNotEqual(orb_after_click_away(show, visible, pending), "hide")

    def test_hidden_bar_is_left_alone(self):
        bar = BarController(enabled=True)  # main window on screen
        self.assertEqual(orb_after_click_away(bar.should_show(), True, False), "none")

    def test_click_away_resets_to_the_greeting(self):
        pill = PillPresentation()
        pill.command_started()
        pill.note_status("Speaking", True)
        self.assertTrue(pill.showing_reply)
        pill.click_away()
        self.assertTrue(pill.collapsed)
        self.assertFalse(pill.busy)
        self.assertFalse(pill.showing_reply)
        pill.click()
        self.assertFalse(pill.showing_reply)

    def test_inside_or_closed_popover_is_not_a_click_away(self):
        self.assertFalse(clicked_outside_popover(True, (150.0, 150.0), POPOVER))
        self.assertFalse(clicked_outside_popover(False, (20.0, 20.0), POPOVER))
        self.assertFalse(clicked_outside_popover(True, None, POPOVER))


class TestClickAwayWiring(unittest.TestCase):
    def test_click_away_closes_popover_and_keeps_orb(self):
        ui = _ui()
        close = _func(ui, "_close_popover_on_click_away")
        self.assertIn("click_away()", close)
        self.assertIn("_keep_orb_visible", close)
        self.assertIn("_popover_history_open = False", close)
        self.assertNotIn("_hide_bar", close)
        self.assertNotIn("orderOut_", close)
        self.assertNotIn("bar.dismiss", close)

    def test_monitor_only_while_popover_is_open(self):
        ui = _ui()
        self.assertIn("_sync_click_away_monitor(not self.pillCollapsed)", _func(ui, "_apply_pill_presentation"))
        handler = _func(ui, "_global_click_away")
        self.assertIn("clicked_outside_popover", handler)
        self.assertIn("_sync_click_away_monitor(False)", ui)

    def test_resign_key_keeps_orb(self):
        self.assertIn("_keep_orb_visible", _func(_ui(), "windowDidResignKey_"))

    def test_late_fade_out_does_not_hide_a_wanted_orb(self):
        ui = _ui()
        hide = _func(ui, "_hide_bar")
        self.assertIn("not self.bar.should_show() and panel.isVisible()", hide)
        self.assertIn("_keep_orb_visible", _func(ui, "_apply_bar_visibility"))


if __name__ == "__main__":
    unittest.main()
