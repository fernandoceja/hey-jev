"""Ctrl-Option-J when Jev is closed: the pure helper module, the Swift helper's source, the build and sign scripts, the
Settings row, and the hotkey's behaviour when the Home window is open. Headless; nothing registers with macOS."""
import ast
import os
import unittest

import assistant_layout as al
import hotkey_helper as hh
from mini_bar import BarController

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("no function named " + name)


class FakeService:
    def __init__(self, status=hh.NOT_REGISTERED, ok=True):
        self._status = status
        self.ok = ok
        self.calls = []

    def status(self):
        return self._status

    def registerAndReturnError_(self, _none):
        self.calls.append("register")
        if self.ok:
            self._status = hh.REQUIRES_APPROVAL
        return self.ok, (None if self.ok else "denied")

    def unregisterAndReturnError_(self, _none):
        self.calls.append("unregister")
        self._status = hh.NOT_REGISTERED
        return True, None


class HelperModuleTests(unittest.TestCase):
    def test_identifiers_match_the_swift_helper_and_its_plist(self):
        swift = _source("helper", "JevHotkey", "main.swift")
        plist = _source("helper", "JevHotkey", "Info.plist")
        self.assertIn('"%s"' % hh.SHOW_ORB_NOTIFICATION, swift)
        self.assertIn('"%s"' % hh.SHOW_ORB_ARG, swift)
        self.assertIn("<string>%s</string>" % hh.HELPER_ID, plist)

    def test_status_texts_and_the_switch_state(self):
        self.assertIn("approval", hh.status_text(hh.REQUIRES_APPROVAL))
        self.assertTrue(hh.is_on(hh.ENABLED))
        self.assertTrue(hh.is_on(hh.REQUIRES_APPROVAL))
        self.assertFalse(hh.is_on(hh.NOT_REGISTERED))
        self.assertFalse(hh.is_on(hh.NOT_FOUND))
        self.assertEqual(hh.status_text(99), "Unknown")

    def test_the_show_orb_flag(self):
        self.assertTrue(hh.show_orb_requested(["app", "--show-orb"]))
        self.assertFalse(hh.show_orb_requested(["app"]))
        self.assertFalse(hh.show_orb_requested(None))

    def test_the_helper_lives_in_the_login_items_folder(self):
        self.assertEqual(hh.helper_path("/x/Jev.app"), "/x/Jev.app/Contents/Library/LoginItems/Jev Hotkey.app")

    def test_registering_goes_through_the_service_and_reports_the_new_status(self):
        service = FakeService()
        helper = hh.LoginItemHelper(service)
        self.assertEqual(helper.status(), hh.NOT_REGISTERED)
        status, error = helper.set_enabled(True)
        self.assertEqual((status, error), (hh.REQUIRES_APPROVAL, ""))
        self.assertEqual(service.calls, ["register"])
        status, error = helper.set_enabled(False)
        self.assertEqual((status, error), (hh.NOT_REGISTERED, ""))

    def test_a_failed_register_reports_the_error_and_does_not_raise(self):
        helper = hh.LoginItemHelper(FakeService(ok=False))
        status, error = helper.set_enabled(True)
        self.assertEqual(error, "denied")

    def test_a_broken_service_reads_as_not_found(self):
        class Broken:
            def status(self):
                raise RuntimeError("no such service")
        self.assertEqual(hh.LoginItemHelper(Broken()).status(), hh.NOT_FOUND)


class SwiftHelperTests(unittest.TestCase):
    def setUp(self):
        self.swift = _source("helper", "JevHotkey", "main.swift")

    def test_it_registers_control_option_j_with_a_carbon_hotkey_only(self):
        self.assertIn("RegisterEventHotKey", self.swift)
        self.assertIn("kVK_ANSI_J", self.swift)
        self.assertIn("controlKey | optionKey", self.swift)
        for forbidden in ("CGEvent.tapCreate", "AXIsProcessTrusted", "addGlobalMonitor", "NSAppleScript", "Process(",
                          "URLSession", "socket"):
            self.assertNotIn(forbidden, self.swift, forbidden)

    def test_it_launches_jev_when_closed_and_notifies_it_when_running(self):
        self.assertIn("runningApplications(withBundleIdentifier: jevBundleID)", self.swift)
        self.assertIn("postNotificationName", self.swift)
        self.assertIn("openApplication(at: url", self.swift)
        self.assertIn("config.arguments", self.swift)
        self.assertIn("config.activates = false", self.swift)

    def test_it_retries_the_hotkey_when_jev_holds_it_and_when_jev_quits(self):
        self.assertIn("Timer.scheduledTimer(withTimeInterval: 2.0", self.swift)
        self.assertIn("didTerminateApplicationNotification", self.swift)

    def test_it_is_a_background_agent_with_no_dock_icon(self):
        self.assertIn(".accessory", self.swift)
        self.assertIn("<key>LSUIElement</key><true/>", _source("helper", "JevHotkey", "Info.plist"))

    def test_it_finds_jev_four_levels_up_inside_the_bundle(self):
        self.assertIn("for _ in 0..<4 { url.deleteLastPathComponent() }", self.swift)


class ScriptTests(unittest.TestCase):
    def test_build_script_puts_the_helper_where_smappservice_looks(self):
        text = _source("scripts", "build_hotkey_helper.sh")
        self.assertIn("Contents/Library/LoginItems/Jev Hotkey.app", text)
        self.assertIn("swiftc", text)
        self.assertIn("--dry-run", text)
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        for forbidden in ("spctl", "xattr", "sudo", "--deep"):
            self.assertNotIn(forbidden, code)
        self.assertTrue(os.access(os.path.join(ROOT, "scripts", "build_hotkey_helper.sh"), os.X_OK))

    def test_sign_script_signs_the_helper_before_the_app(self):
        code = "\n".join(l for l in _source("scripts", "sign_local.sh").splitlines() if not l.lstrip().startswith("#"))
        self.assertIn('HELPER_ID="com.heyjev.app.hotkey"', code)
        self.assertLess(code.index('"${HELPER_SIGN[@]}" "$HELPER"'), code.index('"${SIGN[@]}" "$EXE"'))


class SettingsRowTests(unittest.TestCase):
    def setUp(self):
        self.ui = _source("assistant_ui.py")

    def test_the_layout_has_the_four_rows_between_the_mini_bar_and_updates(self):
        page = al.layout_window(900, 700, how_to=("a",), privacy=(("t", "b"),))["settings"]
        for key in ("hot_name", "hot_hint", "hot_toggle", "hot_status"):
            self.assertIn(key, page)
        self.assertLess(page["hot_toggle"][1], page["mini_toggle"][1])  # lower on the page (origin bottom-left)
        self.assertLess(page["update_button"][1], page["hot_status"][1])

    def test_only_the_users_switch_registers_the_helper(self):
        self.assertIn("set_enabled(sender.state() == 1)", _func(self.ui, "hotkeyHelperChanged_"))
        self.assertEqual(self.ui.count("helper.set_enabled("), 1)  # nothing else turns the helper on or off

    def test_building_the_row_only_reads_the_status(self):
        body = _func(self.ui, "_refresh_hotkey_helper_row")
        self.assertIn("helper.status()", body)
        self.assertNotIn("set_enabled", body)


class HotkeyBehaviourTests(unittest.TestCase):
    def test_home_on_screen_can_be_cleared_by_the_hotkey(self):
        bar = BarController()
        bar.main_window_changed(True)
        self.assertFalse(bar.should_show())
        self.assertTrue(bar.hotkey_can_clear_the_way())

    def test_a_disabled_or_quitting_bar_is_left_alone(self):
        bar = BarController()
        bar.main_window_changed(True)
        bar.set_enabled(False)
        self.assertFalse(bar.hotkey_can_clear_the_way())
        bar.set_enabled(True)
        bar.quit()
        self.assertFalse(bar.hotkey_can_clear_the_way())

    def test_with_home_minimized_there_is_nothing_to_clear(self):
        bar = BarController()
        bar.main_window_changed(False)
        self.assertFalse(bar.hotkey_can_clear_the_way())

    def test_the_hotkey_minimizes_home_then_shows_the_orb(self):
        body = _func(self.ui(), "focusTypeField_")
        self.assertIn("hotkey_can_clear_the_way()", body)
        self.assertLess(body.index("miniaturize_"), body.index("self.expandMiniBar_(None)"))
        self.assertIn("if docked:", body)  # the docked full window is still left alone

    def ui(self):
        return _source("assistant_ui.py")

    def test_the_running_app_listens_for_the_helper_and_the_launch_flag(self):
        ui = self.ui()
        self.assertIn("addObserver_selector_name_object_(\n            self, \"showOrbRequested:\", SHOW_ORB_NOTIFICATION", ui)
        self.assertIn("show_orb_requested(", ui)
        self.assertIn("self.focusTypeField_(None)", _func(ui, "showOrbRequested_"))


if __name__ == "__main__":
    unittest.main()
