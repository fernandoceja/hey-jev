"""Right Option push-to-talk. Pure Python. No AppKit, so mac_guard has nothing to block."""
import os
import unittest

from ptt import INTERRUPT_MS, RIGHT_OPTION_BIT, RIGHT_OPTION_KEY, PushToTalk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEFT_OPTION = 58
LETTER = 0  # a, not a modifier


class TestPushToTalk(unittest.TestCase):
    def test_constants_match_the_right_option_key(self):
        self.assertEqual(RIGHT_OPTION_KEY, 61)
        self.assertEqual(RIGHT_OPTION_BIT, 0x40)
        self.assertEqual(INTERRUPT_MS, 300)
        source = open(os.path.join(ROOT, "ptt.py"), encoding="utf-8").read()
        self.assertNotIn("import AppKit", source)
        self.assertNotIn("from AppKit", source)
        self.assertNotIn("CGEventTap", source)
        self.assertNotIn("import socket", source)
        self.assertNotIn("socket.socket", source)

    def test_press_and_release_follow_the_right_option_bit(self):
        ptt = PushToTalk()
        self.assertEqual(ptt.on_flags(61, 0x40, 1.0), "press")
        self.assertTrue(ptt.down)
        self.assertIsNone(ptt.on_flags(61, 0x40, 1.1))
        self.assertEqual(ptt.on_flags(61, 0, 1.4), "release")
        self.assertFalse(ptt.down)
        self.assertIsNone(ptt.on_flags(61, 0, 1.5))

    def test_left_option_is_ignored(self):
        ptt = PushToTalk()
        self.assertIsNone(ptt.on_flags(LEFT_OPTION, 0x20 | (1 << 19), 0.0))
        self.assertFalse(ptt.down)
        self.assertIsNone(ptt.on_flags(61, 1 << 19, 0.1))
        self.assertFalse(ptt.down)

    def test_left_option_during_a_right_hold_does_not_release(self):
        ptt = PushToTalk()
        self.assertEqual(ptt.on_flags(61, 0x40, 2.0), "press")
        self.assertIsNone(ptt.on_flags(LEFT_OPTION, 0x40 | 0x20, 2.1))
        self.assertTrue(ptt.down)
        self.assertIsNone(ptt.on_flags(LEFT_OPTION, 0x40, 2.2))
        self.assertTrue(ptt.down)
        self.assertEqual(ptt.on_flags(61, 0x20, 2.3), "release")
        self.assertFalse(ptt.down)

    def test_a_key_inside_the_window_cancels_and_one_after_does_not(self):
        held = PushToTalk()
        start = 10.0
        self.assertEqual(held.on_flags(RIGHT_OPTION_KEY, RIGHT_OPTION_BIT, start), "press")
        self.assertIsNone(held.on_key(56, start + 0.05))
        self.assertFalse(held.interrupted)
        self.assertEqual(held.on_key(LETTER, start + 0.1), "cancel")
        self.assertTrue(held.interrupted)
        self.assertTrue(held.down)
        self.assertIsNone(held.on_key(LETTER, start + 0.2))
        self.assertEqual(held.on_flags(RIGHT_OPTION_KEY, 0, start + 0.4), "release")

        late = PushToTalk()
        self.assertEqual(late.on_flags(61, 0x40, start), "press")
        self.assertEqual(late.on_key(LETTER, start + (INTERRUPT_MS / 1000.0)), "cancel")
        self.assertTrue(late.interrupted)

        after = PushToTalk()
        self.assertEqual(after.on_flags(61, 0x40, start), "press")
        self.assertIsNone(after.on_key(LETTER, start + (INTERRUPT_MS / 1000.0) + 0.05))
        self.assertFalse(after.interrupted)
        self.assertTrue(after.down)

    def test_watchdog_releases_only_when_the_bit_is_gone(self):
        ptt = PushToTalk()
        self.assertIsNone(ptt.watchdog(0.2, 0))
        self.assertEqual(ptt.on_flags(61, 0x40, 0.0), "press")
        self.assertIsNone(ptt.watchdog(0.4, 0x40 | (1 << 19)))
        self.assertTrue(ptt.down)
        self.assertEqual(ptt.watchdog(0.5, 1 << 19), "release")
        self.assertFalse(ptt.down)
        self.assertIsNone(ptt.watchdog(0.6, 0))

    def test_force_release_is_a_no_op_when_the_key_is_up(self):
        idle = PushToTalk()
        self.assertIsNone(idle.force_release("sleep"))
        self.assertIsNone(idle.force_release("space"))
        self.assertFalse(idle.down)
        held = PushToTalk()
        held.on_flags(61, 0x40, 3.0)
        self.assertEqual(held.force_release("sleep"), "release")
        self.assertFalse(held.down)
        self.assertIsNone(held.force_release("space"))


class TestCancelWiring(unittest.TestCase):
    def test_the_window_discards_a_cancelled_hold_without_an_event_tap(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertIn("on_key", ui[ui.index("def _local_key"):ui.index("def _global_type_key")])
        self.assertIn("on_key", ui[ui.index("def _global_type_key"):ui.index("def _handle_flags")])
        cancel = ui[ui.index("def _cancel_ptt"):ui.index("def _release_ptt")]
        self.assertIn('self.controls.put("discard")', cancel)
        self.assertIn('self.controls.put("release")', cancel)
        self.assertLess(cancel.index('"discard"'), cancel.index('"release"'))
        self.assertIn('command == "discard"', siri)
        self.assertIn("def discard_recording", siri)
        self.assertNotIn("CGEventTap", ui)
        self.assertIn("AXIsProcessTrusted", ui)
        self.assertIn("Hold-Option needs Accessibility", ui)
        self.assertIn("NSWorkspaceWillSleepNotification", ui)
        self.assertIn("NSWorkspaceActiveSpaceDidChangeNotification", ui)
        self.assertIn("force_release", ui)
