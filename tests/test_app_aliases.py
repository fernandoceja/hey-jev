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


INSTALLED = {
    "tv": "/Applications/TV.app",
    "chatgpt": "/Applications/ChatGPT.app",
    "chatgptclassic": "/Applications/ChatGPT Classic.app",
    "youtubetv": "/Applications/YouTube TV.app",
    "superduper": "/Applications/SuperDuper.app",
}


def _installed(force=False):
    return INSTALLED


class TestChatGPTAndTV(unittest.TestCase):
    def test_chatgpt_spellings_resolve_and_classic_does_not(self):
        for spoken in ("chat gpt", "chat g p t", "chatgpt", "chat GPT", "ChatGPT", "ChatGPT."):
            self.assertEqual(commands.known_app_name(spoken), "ChatGPT", spoken)
            self.assertEqual(commands.normalize_app_phrase(spoken), "ChatGPT", spoken)
        self.assertEqual(commands.known_app_name("ChatGPT Classic"), "ChatGPT Classic")
        self.assertEqual(commands.known_app_name("chat gpt classic"), "ChatGPT Classic")
        self.assertNotEqual(commands.normalize_app_phrase("ChatGPT Classic"), "ChatGPT")

    def test_open_and_quit_chatgpt_spellings_are_the_same_app(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=0, stdout="", stderr="")

        phrases = (
            ("open chat gpt", "app_open"),
            ("open chat g p t", "app_open"),
            ("open chatgpt", "app_open"),
            ("launch chat GPT", "app_open"),
        )
        with mock.patch.object(commands.subprocess, "run", fake_run):
            for phrase, key in phrases:
                self.assertEqual(commands.route_before_api(phrase), key, phrase)
                self.assertIsNone(commands.bridge_allowed(phrase), phrase)
                self.assertNotIn(key, commands.BRIDGE_ALLOW)
                opened = commands.open_any_app(None, phrase, {})
                self.assertEqual(opened, {"app": "ChatGPT"}, phrase)
        self.assertTrue(calls)
        self.assertTrue(all(call == ["open", "-a", "ChatGPT"] for call in calls), calls)

        gpt = _App("ChatGPT")
        classic = _App("ChatGPT Classic")
        with mock.patch.object(commands.apps, "running_regular_apps", return_value=[classic, gpt]):
            for phrase in ("quit chat gpt", "close chat g p t", "quit chatgpt"):
                gpt.terminated = False
                classic.terminated = False
                self.assertEqual(commands.route_before_api(phrase), "app_quit", phrase)
                self.assertIsNone(commands.bridge_allowed(phrase), phrase)
                result = commands.quit_any_app(None, phrase, {})
                self.assertEqual(result, {"app": "ChatGPT"}, phrase)
                self.assertTrue(gpt.terminated, phrase)
                self.assertFalse(classic.terminated, phrase)

    def test_apple_tv_and_the_tv_app_are_tv_and_youtube_tv_is_not(self):
        for spoken in ("Apple TV", "apple tv", "the TV app", "TV app", "the tv application"):
            self.assertEqual(commands.known_app_name(spoken), "TV", spoken)
        self.assertEqual(commands.known_app_name("YouTube TV"), "YouTube TV")
        self.assertEqual(commands.known_app_name("youtube tv"), "YouTube TV")
        self.assertEqual(commands.known_app_name("the YouTube TV app"), "YouTube TV")

        calls = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=0, stdout="", stderr="")

        opens = {
            "open Apple TV": "TV",
            "open the TV app": "TV",
            "open TV app": "TV",
            "open YouTube TV": "YouTube TV",
            "open the YouTube TV app": "YouTube TV",
        }
        with mock.patch.object(commands.apps, "app_index", _installed), \
                mock.patch.object(commands.subprocess, "run", fake_run):
            for phrase, display in opens.items():
                self.assertEqual(commands.route_before_api(phrase), "app_open", phrase)
                self.assertIsNone(commands.bridge_allowed(phrase), phrase)
                self.assertEqual(commands.open_any_app(None, phrase, {}), {"app": display}, phrase)
        self.assertEqual(
            calls,
            [["open", "-a", "TV"], ["open", "-a", "TV"], ["open", "-a", "TV"],
             ["open", "-a", "YouTube TV"], ["open", "-a", "YouTube TV"]],
        )

        tv = _App("TV", "com.apple.TV")
        youtube = _App("YouTube TV", "com.google.youtube.tv")
        quits = {
            "close Apple TV.": tv,
            "quit the TV app": tv,
            "close TV app": tv,
            "close YouTube TV": youtube,
            "quit YouTube TV": youtube,
        }
        with mock.patch.object(commands.apps, "running_regular_apps", return_value=[youtube, tv]):
            for phrase, target in quits.items():
                tv.terminated = False
                youtube.terminated = False
                self.assertEqual(commands.route_before_api(phrase), "app_quit", phrase)
                self.assertIsNone(commands.bridge_allowed(phrase), phrase)
                self.assertNotIn("app_quit", commands.BRIDGE_ALLOW)
                result = commands.quit_any_app(None, phrase, {})
                self.assertEqual(result, {"app": target.name}, phrase)
                self.assertTrue(target.terminated, phrase)
                self.assertFalse((youtube if target is tv else tv).terminated, phrase)

    def test_a_short_fuzzy_match_does_not_open_or_quit_tv(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=0, stdout="", stderr="")

        tv = _App("TV", "com.apple.TV")
        youtube = _App("YouTube TV")
        with mock.patch.object(commands.apps, "app_index", _installed), \
                mock.patch.object(commands.subprocess, "run", fake_run), \
                mock.patch.object(commands.apps, "running_regular_apps", return_value=[tv, youtube]):
            self.assertTrue(commands.unclear_app_guess("to TV"))
            self.assertEqual(commands.route_before_api("Open to TV."), "app_open")
            self.assertEqual(commands.open_any_app(None, "Open to TV.", {}), commands.UNCLEAR_APP)
            self.assertEqual(commands.route_before_api("close to TV"), "app_quit")
            self.assertEqual(commands.quit_any_app(None, "close to TV", {}), commands.UNCLEAR_APP)
            self.assertFalse(tv.terminated)
            self.assertFalse(youtube.terminated)
        self.assertEqual(calls, [])

    def test_a_clear_long_fuzzy_match_still_opens(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=0, stdout="", stderr="")

        self.assertIsNone(commands.known_app_name("superdupr"))
        with mock.patch.object(commands.apps, "app_index", _installed), \
                mock.patch.object(commands.subprocess, "run", fake_run):
            self.assertFalse(commands.unclear_app_guess("superdupr"))
            self.assertEqual(commands.route_before_api("open superdupr"), "app_open")
            self.assertEqual(commands.open_any_app(None, "open superdupr", {}), {"app": "SuperDuper"})
        self.assertEqual(calls, [["open", "-a", "SuperDuper"]])

    def test_a_name_that_matches_nothing_is_not_installed(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(commands.apps, "app_index", _installed), \
                mock.patch.object(commands.subprocess, "run", fake_run):
            self.assertFalse(commands.unclear_app_guess("zzzqqqnotanapp"))
            self.assertIsNone(commands.route_before_api("open zzzqqqnotanapp"))
            spoken = commands.open_any_app(None, "open zzzqqqnotanapp", {})
        self.assertIn("isn't installed", spoken)
        self.assertEqual(calls, [])
