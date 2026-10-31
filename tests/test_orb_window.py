"""The orb window survives the reveal-desktop sweep, Spaces and Mission Control. No AppKit."""
import os
import unittest

from mini_bar import (
    BAR_COLLECTION,
    CAN_JOIN_ALL_SPACES,
    FULL_SCREEN_AUXILIARY,
    IGNORES_CYCLE,
    ORB_WINDOW_LEVEL,
    STATIONARY,
    BarController,
    orb_should_reassert,
    orb_window_config,
)
from tests.test_pill_collapse import _func

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# AppKit values, so a typo in mini_bar can't silently change a flag.
NS_CAN_JOIN_ALL_SPACES = 1 << 0
NS_STATIONARY = 1 << 4
NS_IGNORES_CYCLE = 1 << 6
NS_FULL_SCREEN_AUXILIARY = 1 << 8
NS_TRANSIENT = 1 << 3
NS_MOVE_TO_ACTIVE_SPACE = 1 << 1
NS_STATUS_WINDOW_LEVEL = 25


def _ui():
    with open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8") as fh:
        return fh.read()


class TestOrbWindowFlags(unittest.TestCase):
    def test_collection_flags_match_appkit(self):
        self.assertEqual(CAN_JOIN_ALL_SPACES, NS_CAN_JOIN_ALL_SPACES)
        self.assertEqual(STATIONARY, NS_STATIONARY)
        self.assertEqual(IGNORES_CYCLE, NS_IGNORES_CYCLE)
        self.assertEqual(FULL_SCREEN_AUXILIARY, NS_FULL_SCREEN_AUXILIARY)

    def test_collection_is_all_spaces_stationary_ignores_cycle_fullscreen(self):
        want = NS_CAN_JOIN_ALL_SPACES | NS_STATIONARY | NS_IGNORES_CYCLE | NS_FULL_SCREEN_AUXILIARY
        self.assertEqual(BAR_COLLECTION, want)
        self.assertEqual(orb_window_config()["collection"], want)

    def test_never_transient_or_moving_to_the_active_space(self):
        # Transient windows are hidden by Expose; MoveToActiveSpace conflicts with CanJoinAllSpaces.
        self.assertEqual(BAR_COLLECTION & NS_TRANSIENT, 0)
        self.assertEqual(BAR_COLLECTION & NS_MOVE_TO_ACTIVE_SPACE, 0)

    def test_status_level_floating_and_never_hidden(self):
        config = orb_window_config()
        self.assertGreaterEqual(config["level"], NS_STATUS_WINDOW_LEVEL)
        self.assertEqual(config["level"], ORB_WINDOW_LEVEL)
        self.assertTrue(config["floating"])
        self.assertFalse(config["hides_on_deactivate"])
        self.assertFalse(config["can_hide"])

    def test_assistant_ui_level_matches(self):
        self.assertIn("BAR_LEVEL = 28", _ui())
        self.assertEqual(ORB_WINDOW_LEVEL, 28)


class TestOrbWindowWiring(unittest.TestCase):
    def test_flags_are_applied_in_one_place(self):
        ui = _ui()
        apply = _func(ui, "_apply_orb_window_flags")
        for call in ('setLevel_(config["level"])', 'setFloatingPanel_(config["floating"])',
                     'setHidesOnDeactivate_(config["hides_on_deactivate"])',
                     'setCanHide_(config["can_hide"])', 'setCollectionBehavior_(config["collection"])'):
            self.assertIn(call, apply)
        self.assertIn("self._apply_orb_window_flags(self.mini_panel)", _func(ui, "_build_mini_bar"))

    def test_orb_is_reshown_on_close_activate_deactivate_and_space_change(self):
        ui = _ui()
        self.assertIn("orderFrontRegardless", _func(ui, "_reassert_orb"))
        self.assertIn("orb_should_reassert", _func(ui, "_reassert_orb"))
        for name in ("applicationDidBecomeActive_", "applicationDidResignActive_", "activeSpaceDidChange_",
                     "_close_popover_on_click_away", "windowDidResignKey_"):
            self.assertIn("_reassert_orb", _func(ui, name), name)
        presentation = _func(ui, "_apply_pill_presentation")
        self.assertIn("if self.pillCollapsed:", presentation)
        self.assertIn("self._reassert_orb()", presentation)

    def test_reassert_only_when_the_bar_is_wanted(self):
        bar = BarController(enabled=True)
        self.assertEqual(orb_should_reassert(bar.should_show(), True), "none")  # main window up
        bar.main_window_changed(False)
        self.assertEqual(orb_should_reassert(bar.should_show(), True), "front")
        self.assertEqual(orb_should_reassert(bar.should_show(), False), "front")
        bar.quit()
        self.assertEqual(orb_should_reassert(bar.should_show(), False), "none")


if __name__ == "__main__":
    unittest.main()
