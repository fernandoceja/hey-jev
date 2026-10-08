"""close, quit, hide, and focus share the open-app nicknames. No hardware."""
import inspect
import os
import unittest
from unittest import mock

import commands


class _App:
    def __init__(self, name, bundle="com.example.app"):
        self.name = name
        self.bundle = bundle
        self.terminated = False
        self.hidden = False
        self.activated = None

    def localizedName(self):
        return self.name

    def processIdentifier(self):
        return 424242

    def bundleIdentifier(self):
        return self.bundle

    def terminate(self):
        self.terminated = True
        return True

    def hide(self):
        self.hidden = True
        return True

    def activateWithOptions_(self, options):
        self.activated = options
        return True


class TestCloseAliases(unittest.TestCase):
    def test_imessage_names_resolve_to_messages(self):
        for spoken in ("imessage", "iMessage", "i message", "I-Message", "messages", "Messages", "iMessage."):
            self.assertEqual(commands.known_app_name(spoken), "Messages", spoken)

    def test_close_and_quit_phrases_target_only_messages(self):
        phrases = (
            "close imessage",
            "close iMessage.",
            "quit messages",
            "close Messages",
            "  CLOSE    iMessage... ",
            "quit  Messages!",
        )
        messages = _App("Messages", "com.apple.MobileSMS")
        mail = _App("Mail", "com.apple.mail")
        for phrase in phrases:
            self.assertEqual(commands.route_before_api(phrase), "app_quit", phrase)
            self.assertEqual(commands.parse_app_name(phrase, "quit").lower().strip("."), "imessage" if "imessage" in phrase.lower() or "iMessage" in phrase else "messages", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            self.assertNotEqual(commands.route_before_api(phrase), "info_messages", phrase)
            messages.terminated = False
            mail.terminated = False
            with mock.patch.object(commands.apps, "running_regular_apps", return_value=[mail, messages]):
                result = commands.quit_any_app(None, phrase, {})
            self.assertEqual(result, {"app": "Messages"}, phrase)
            self.assertTrue(messages.terminated, phrase)
            self.assertFalse(mail.terminated, phrase)

    def test_typed_punctuation_and_spaces_still_quit_messages(self):
        from mini_bar import submission
        for typed in ("close imessage", "close iMessage.", "quit messages", "close Messages"):
            plan = submission("  " + typed + "  ")
            self.assertEqual(plan["control"][0], "text", typed)
            self.assertEqual(commands.route_before_api(plan["control"][1]), "app_quit", typed)
            self.assertIn("Messages", commands.known_app_name(commands.parse_app_name(plan["control"][1], "quit")) or "", typed)

    def test_quit_is_polite_and_quit_all_still_asks(self):
        source = inspect.getsource(commands.quit_any_app)
        self.assertIn("terminate()", source)
        self.assertNotIn("forceTerminate", source)
        self.assertNotIn("kill", source)
        self.assertIn("apps_quit_all", commands.CONFIRM)
        self.assertIsNone(commands.route_before_api("quit all the apps"))
        self.assertIsNone(commands.route_before_api("close all the apps"))
        self.assertIsNone(commands.route_before_api("force quit all the apps"))
        self.assertTrue(commands.is_quit_all("quit all the apps"))
        self.assertEqual(
            commands.quit_any_app(None, "quit all the apps", {}),
            "Say quit all on its own, then yes to confirm.",
        )
        self.assertEqual(
            commands.quit_any_app(None, "close all", {}),
            "Say quit all on its own, then yes to confirm.",
        )
        messages = _App("Messages", "com.apple.MobileSMS")
        with mock.patch.object(commands.apps, "running_regular_apps", return_value=[messages]):
            self.assertEqual(commands.route_before_api("force quit messages"), "app_quit")
            result = commands.quit_any_app(None, "force quit messages", {})
        self.assertEqual(result, {"app": "Messages"})
        self.assertTrue(messages.terminated)
        with mock.patch.object(commands.apps, "running_regular_apps", return_value=[]):
            self.assertEqual(commands.quit_any_app(None, "close imessage", {}), "Messages isn't running.")

    def test_hide_focus_and_switch_share_the_alias(self):
        self.assertEqual(commands.route_before_api("hide imessage"), "app_hide")
        self.assertEqual(commands.route_before_api("focus iMessage"), "app_focus")
        self.assertEqual(commands.route_before_api("focus on messages"), "app_focus")
        self.assertEqual(commands.route_before_api("switch to imessage"), "app_open")
        self.assertEqual(commands.route_before_api("open imessage"), "app_open")
        self.assertIsNone(commands.bridge_allowed("hide imessage"))
        self.assertIsNone(commands.bridge_allowed("focus messages"))
        self.assertIsNone(commands.bridge_allowed("switch to imessage"))
        self.assertIsNone(commands.bridge_allowed("open imessage"))
        for key in ("app_open", "app_quit", "app_hide", "app_focus"):
            self.assertNotIn(key, commands.BRIDGE_ALLOW)
        self.assertEqual(commands.route_before_api("start focus mode"), "focus_on")
        self.assertEqual(commands.route_before_api("focus mode"), "focus_on")
        self.assertEqual(commands.route_before_api("close the matrix"), "matrix_off")
        self.assertEqual(commands.route_before_api("check my messages from My Love"), "info_messages")
        self.assertIsNone(commands.bridge_allowed("check my messages from My Love"))

        messages = _App("Messages", "com.apple.MobileSMS")
        mail = _App("Mail", "com.apple.mail")
        with mock.patch.object(commands.apps, "running_regular_apps", return_value=[mail, messages]):
            hidden = commands.hide_any_app(None, "hide imessage", {})
            focused = commands.focus_any_app(None, "focus iMessage.", {})
        self.assertEqual(hidden, {"app": "Messages"})
        self.assertTrue(messages.hidden)
        self.assertFalse(mail.hidden)
        self.assertEqual(focused, {"app": "Messages"})
        self.assertEqual(messages.activated, 2)
        self.assertIsNone(mail.activated)

    def test_focus_launches_with_open_a_when_the_app_is_not_running(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(commands.apps, "running_regular_apps", return_value=[]), \
                mock.patch.object(commands.subprocess, "run", fake_run):
            result = commands.focus_any_app(None, "focus imessage", {})
            opened = commands.open_any_app(None, "open imessage", {})
        self.assertEqual(result, {"app": "Messages"})
        self.assertEqual(opened, {"app": "Messages"})
        self.assertEqual(calls, [["open", "-a", "Messages"], ["open", "-a", "Messages"]])

    def test_siri_routes_hide_and_focus_through_the_shared_resolver(self):
        source = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "siri.py"), encoding="utf-8").read()
        self.assertIn('commands.hide_any_app', source)
        self.assertIn('commands.focus_any_app', source)
        self.assertIn('commands.quit_any_app', source)
        self.assertNotIn("forceTerminate", source)
