"""The pill can become the key window. AppKit is a fake. No hardware."""
import os
import unittest

import commands
from mini_bar import (
    ACTIVATE_IGNORING_OTHERS,
    PILL_BECOMES_KEY_ONLY_IF_NEEDED,
    PillKeyFocus,
    activate_for_typing,
    background_action,
    bar_controls,
    caret_range,
    is_our_app,
    keyable_panel,
    normalize_typed,
    pill_can_become_key,
    pill_can_become_main,
    restore_front_app,
    submission,
    undo_main_reveal,
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


class _PanelBase:
    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return True


class _FrontApp:
    def __init__(self, name, pid=4242, bundle="com.apple.MobileSMS"):
        self.name = name
        self.pid = pid
        self.bundle = bundle
        self.options = None

    def processIdentifier(self):
        return self.pid

    def bundleIdentifier(self):
        return self.bundle

    def localizedName(self):
        return self.name

    def activateWithOptions_(self, options):
        self.options = options
        return True


class _Field:
    def __init__(self, text=""):
        self.text = text

    def stringValue(self):
        return self.text


class _Window:
    def __init__(self, log):
        self.log = log
        self.first = "unset"

    def makeKeyAndOrderFront_(self, sender):
        self.log.append("makeKeyAndOrderFront")

    def makeFirstResponder_(self, responder):
        self.first = responder
        self.log.append("makeFirstResponder")


class _ModernApp:
    def __init__(self, log):
        self.log = log

    def activate(self):
        self.log.append("activate")

    def yieldActivationToApplication_(self, other):
        self.log.append(("yield", other))


class _LegacyApp:
    def __init__(self, log):
        self.log = log

    def activate(self):
        raise TypeError("activate takes no part in this OS")

    def activateIgnoringOtherApps_(self, flag):
        self.log.append(("activateIgnoringOtherApps", flag))


class TestPillKeyWindow(unittest.TestCase):
    def test_the_panel_can_become_key_and_not_the_main_window(self):
        self.assertTrue(pill_can_become_key())
        self.assertFalse(pill_can_become_main())
        self.assertFalse(PILL_BECOMES_KEY_ONLY_IF_NEEDED)
        Panel = keyable_panel(_PanelBase)
        panel = Panel()
        self.assertTrue(panel.canBecomeKeyWindow())
        self.assertFalse(panel.canBecomeMainWindow())
        self.assertTrue(issubclass(Panel, _PanelBase))

    def test_a_click_focuses_the_field_and_return_or_esc_gives_it_back(self):
        log = []
        panel = _Window(log)
        field = _Field("close imessage")
        front = _FrontApp("Safari")
        app = _ModernApp(log)
        keys = PillKeyFocus()
        caret = keys.focus_field(panel, field, app, front, False)
        self.assertEqual(caret, (len("close imessage"), 0))
        self.assertEqual(caret_range(""), (0, 0))
        self.assertEqual(log, ["makeKeyAndOrderFront", "activate", "makeFirstResponder"])
        self.assertIs(panel.first, field)
        # Hey Jev is now in front. A second click must keep Safari as the app to restore.
        again = _Window([])
        keys.focus_field(again, field, app, _FrontApp("Hey Jev", pid=os.getpid()), True)
        self.assertEqual(keys.release(app, panel), "yield")
        self.assertEqual(log[-1], ("yield", front))
        self.assertIsNone(panel.first)
        self.assertEqual(keys.release(app, panel), "none")

    def test_older_macos_uses_activate_ignoring_other_apps(self):
        log = []
        app = _LegacyApp(log)
        self.assertEqual(activate_for_typing(app), "activateIgnoringOtherApps")
        self.assertEqual(log, [("activateIgnoringOtherApps", True)])
        front = _FrontApp("Notes")
        self.assertEqual(restore_front_app(app, front), "activateWithOptions")
        self.assertEqual(front.options, ACTIVATE_IGNORING_OTHERS)
        self.assertEqual(restore_front_app(app, None), "none")

    def test_our_own_app_is_not_the_one_we_restore(self):
        self.assertTrue(is_our_app(_FrontApp("Safari", pid=9), 9))
        self.assertTrue(is_our_app(_FrontApp("Hey Jev", bundle="com.heyjev.app"), 3))
        self.assertTrue(is_our_app(_FrontApp("Hey Jev"), 3))
        self.assertFalse(is_our_app(_FrontApp("Safari"), 3))
        self.assertFalse(is_our_app(None, 3))

    def test_activation_does_not_leave_the_main_window_up(self):
        self.assertEqual(undo_main_reveal(False, True, True, False), "miniaturize")
        self.assertEqual(undo_main_reveal(False, False, True, False), "orderOut")
        self.assertIsNone(undo_main_reveal(False, False, False, False))
        self.assertIsNone(undo_main_reveal(True, False, True, False))

    def test_drag_resize_and_double_click_reset_stay_on_the_background(self):
        frames = bar_controls()
        field = frames["field"]
        self.assertEqual(background_action(1, field[0] + 4, field[1] + 4), "control")
        self.assertEqual(background_action(1, 2, 2), "resize")
        # The band just above the field is background: drag, and a double-click resets.
        self.assertEqual(background_action(1, 200, 8), "drag")
        self.assertEqual(background_action(2, 200, 8), "reset")

    def test_return_queues_the_same_command_path_and_normalizes_typed_text(self):
        plan = submission("  close   iMessage. ")
        self.assertEqual(plan["kind"], "run")
        self.assertEqual(plan["control"], ("text", "close iMessage"))
        self.assertFalse(plan["reveal_main"])
        self.assertEqual(normalize_typed("  QUIT   messages! "), "QUIT messages")
        self.assertEqual(commands.route_before_api(plan["control"][1]), "app_quit")
        echo = submission("It's 3:45.", shown_reply="It's 3:45.")
        self.assertEqual(echo["kind"], "clear")

    def test_the_window_source_keeps_fullscreen_and_wires_the_key_window(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        bar = open(os.path.join(ROOT, "mini_bar.py"), encoding="utf-8").read()
        self.assertIn("keyable_panel(NSPanel)", ui)
        self.assertIn("def canBecomeKeyWindow", bar)
        self.assertIn("return pill_can_become_key()", bar)
        self.assertIn("NSWindowStyleMaskNonactivatingPanel", _func(ui, "_build_mini_bar"))
        self.assertIn("setBecomesKeyOnlyIfNeeded_(PILL_BECOMES_KEY_ONLY_IF_NEEDED)", ui)
        self.assertIn("NSWindowCollectionBehaviorCanJoinAllSpaces", _func(ui, "_build_mini_bar"))
        self.assertIn("NSWindowCollectionBehaviorFullScreenAuxiliary", _func(ui, "_build_mini_bar"))
        self.assertIn("NSWindowCollectionBehaviorStationary", _func(ui, "_build_mini_bar"))
        self.assertIn("setMovableByWindowBackground_(True)", _func(ui, "_build_mini_bar"))
        field_cls = ui[ui.index("class PillTextField"):ui.index("class ClickAwayView")]
        self.assertIn("def acceptsFirstMouse_", field_cls)
        self.assertIn("return True", field_cls)
        self.assertIn("pillFieldClicked_", field_cls)
        self.assertIn("makeKeyAndOrderFront_", bar)
        self.assertIn("activateIgnoringOtherApps_", bar)
        self.assertIn("yieldActivationToApplication_", bar)
        focus = _func(ui, "_focus_pill_field")
        self.assertIn("undo_main_reveal", focus)
        self.assertIn("focus_field", focus)
        self.assertNotIn("showMain_", focus)
        self.assertNotIn("deminiaturize_", focus)
        submit = _func(ui, "miniSubmit_")
        self.assertIn("_restore_front_app", submit)
        self.assertIn('self.controls.put(plan["control"])', submit)
        for banned in ("deminiaturize_", "makeKeyAndOrderFront_", "activateIgnoringOtherApps_", "showMain_"):
            self.assertNotIn(banned, submit)
        self.assertIn("_restore_front_app", _func(ui, "miniDismiss_"))
        self.assertIn("_focus_pill_field", _func(ui, "focusTypeField_"))
        self.assertIn("focusTypeField_", ui)
        self.assertIn("_show_bar_reply", _func(ui, "updateStatus_"))
        background = _func(ui, "mouseDown_")
        self.assertIn("resetMiniBarPosition_", background)
        self.assertIn("resize_frame", background)
        self.assertIn("drag_origin", background)
        self.assertNotIn("import socket", bar)
        self.assertNotIn("listen(", bar)
        self.assertNotIn("app_quit", commands.BRIDGE_ALLOW)
        self.assertNotIn("app_open", commands.BRIDGE_ALLOW)
