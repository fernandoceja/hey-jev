"""PR 7b follow-up: the Spotlight closes on every other Jev entry point, and on any mouse-down outside it."""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


class CloseTriggerTests(unittest.TestCase):
    def setUp(self):
        self.ui = _source("assistant_ui.py")

    def test_every_other_jev_entry_point_closes_the_spotlight_with_a_reason(self):
        expected = {
            "_show_full_window": "full window",
            "_expand_orb_to_full": "full window",
            "expandOrbToFull_": "orb click",
            "expandMiniBar_": "type box",
            "focusTypeField_": "hotkey",
            "captureAreaWand_": "capture area",
            "_open_markup": "mark up",
            "_pill_drag_began": "orb drag",
        }
        for name, reason in expected.items():
            self.assertIn('self._close_orb_spotlight("{0}")'.format(reason), _func(self.ui, name), name)

    def test_the_mouse_down_monitors_are_added_on_open_and_removed_on_close(self):
        opener = _func(self.ui, "_open_orb_spotlight")
        self.assertIn("addGlobalMonitorForEventsMatchingMask_handler_", opener)
        self.assertIn("addLocalMonitorForEventsMatchingMask_handler_", opener)
        self.assertIn("NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown | NSEventMaskOtherMouseDown", opener)
        self.assertIn('"click outside"', opener)
        closer = _func(self.ui, "_close_orb_spotlight")
        self.assertIn("NSEvent.removeMonitor_(monitor)", closer)
        self.assertIn('print("orb spotlight: close ({0})"', closer)

    def test_the_monitors_only_watch_mouse_buttons(self):
        opener = _func(self.ui, "_open_orb_spotlight")
        self.assertNotIn("NSEventMaskKeyDown", opener)
        self.assertNotIn("NSEventMaskKeyUp", opener)


class RetryTests(unittest.TestCase):
    def test_key_is_retried_once_through_app_activation_and_logged(self):
        after = _func(_source("assistant_ui.py"), "spotlightAfterOpen_")
        self.assertIn('if not panel.isKeyWindow() and not state.get("retried"):', after)
        self.assertIn('state["retried"] = True', after)
        self.assertIn("NSApp.activate()", after)
        self.assertIn("activateIgnoringOtherApps_(True)", after)  # the fallback before macOS 14


if __name__ == "__main__":
    unittest.main()
