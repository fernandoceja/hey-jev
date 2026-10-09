"""Password lookup. Fake processes only. No Mac, no network, no Keychain read."""
import os
import socket
import tempfile
import unittest
import urllib.request
from unittest import mock

import commands
from commands.passwords import (
    DICTATED_RE,
    LOOKUP_RE,
    MISSING_LINE,
    OPENED_LINE,
    PASSWORDS_BUNDLE,
    REFUSE_LINE,
    SEARCH_SCRIPT,
    TYPE_FAIL_LINE,
    WHICH_LINE,
    lookup_password,
    parse_password_query,
)
from commands.stt import WHISPER_HOTWORDS, is_hotword_echo
from mini_bar import submission

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PHRASES = (
    ("password for Netflix", "Netflix"),
    ("passwords for Netflix", "Netflix"),
    ("Password for Netflix", "Netflix"),
    ("PASSWORD FOR NETFLIX", "NETFLIX"),
    ("password for Netflix.", "Netflix"),
    ("password for Netflix!", "Netflix"),
    ("password for Netflix?", "Netflix"),
    ("please password for Netflix", "Netflix"),
    ("password for Netflix please", "Netflix"),
    ("please password for Netflix please", "Netflix"),
    ("what's my password for Chase", "Chase"),
    ("what is my password for Chase", "Chase"),
    ("whats my password for Chase", "Chase"),
    ("what's the password for Chase", "Chase"),
    ("what is the password for Chase", "Chase"),
    ("my password for Chase", "Chase"),
    ("the password for Chase", "Chase"),
    ("login for Amazon", "Amazon"),
    ("logins for Amazon", "Amazon"),
    ("log in for Amazon", "Amazon"),
    ("my login for Amazon", "Amazon"),
    ("the login for Amazon", "Amazon"),
    ("what's my login for Amazon", "Amazon"),
    ("what is my login for Amazon", "Amazon"),
    ("show my logins for Amazon", "Amazon"),
    ("show me my logins for Hulu", "Hulu"),
    ("show my passwords for Spotify", "Spotify"),
    ("show my login for Amazon", "Amazon"),
    ("show me the login for Amazon", "Amazon"),
    ("find my password for Netflix", "Netflix"),
    ("look up my password for Netflix", "Netflix"),
    ("lookup the login for Amazon", "Amazon"),
    ("password for Bank of America", "Bank of America"),
    ("password for my.chase.com", "my.chase.com"),
    ("password for YouTube TV", "YouTube TV"),
    ("password for H&R Block", "H&R Block"),
    ("password for McDonald's", "McDonald's"),
    ("hey jev password for Netflix", "Netflix"),
    ("hey jev, password for Netflix", "Netflix"),
    ("hey jev, what's my password for Chase", "Chase"),
    ("please hey jev login for Amazon", "Amazon"),
    ("hey jev please show my logins for Hulu", "Hulu"),
)

KEPT = {
    "open Safari": "app_open",
    "open Netflix": None,
    "what's the weather": "info_weather",
    "when should I leave for work": "info_leave",
    "what's my ETA to work": "info_eta_work",
    "clipboard history": "clipboard_history",
    "check my messages from My Love": "info_messages",
    "remind me to buy milk": "remind_add",
    "play": "media_play",
    "pause": "media_pause",
    "what time is it": "info_time",
    "blue pill": "matrix_on",
    "take a screenshot": "screenshot",
}


def _result(stdout="", code=0):
    return mock.Mock(returncode=code, stdout=stdout, stderr="")


class TestPasswordRouting(unittest.TestCase):
    def test_every_phrase_routes_locally_and_stays_off_the_bridge(self):
        for phrase, term in PHRASES:
            self.assertEqual(commands.route_before_api(phrase), "password_lookup", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            self.assertNotIn("password_lookup", commands.BRIDGE_ALLOW, phrase)
            parsed = parse_password_query(phrase)
            self.assertIsNotNone(parsed, phrase)
            self.assertFalse(parsed.refused, phrase)
            self.assertEqual(parsed.term, term, phrase)
            self.assertNotIn("password", parsed.term.lower(), phrase)
        self.assertNotIn("password_lookup", commands.BRIDGE_ALLOW)
        self.assertIn("password_lookup", commands.PASSWORD_KEYS)
        self.assertEqual(commands.PASSWORD_LOOKUP, "password_lookup")
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)

    def test_typed_field_and_pill_use_the_same_route(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        self.assertIn("def miniSubmit_", ui)
        self.assertIn("def homeSubmit_", ui)
        self.assertEqual(ui.count("plan = submission("), 2)
        for raw in (
            "Password for Netflix",
            "  what's my password for Chase? ",
            "please login for Amazon",
            "show my logins for Hulu.",
            "hey jev, password for Bank of America",
        ):
            plan = submission(raw, "")
            self.assertEqual(plan["kind"], "run", raw)
            self.assertFalse(plan["reveal_main"], raw)
            self.assertEqual(plan["control"][0], "text", raw)
            self.assertEqual(
                commands.route_before_api(plan["control"][1]), "password_lookup", raw)

    def test_old_commands_and_unrelated_password_talk_stay_put(self):
        for phrase, key in KEPT.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertNotEqual(key, "password_lookup", phrase)
        for phrase in (
            "password",
            "passwords",
            "change my password",
            "reset my Netflix password",
            "how do I change my password",
            "open passwords",
            "I forgot my password",
        ):
            self.assertNotEqual(commands.route_before_api(phrase), "password_lookup", phrase)
            self.assertIsNone(parse_password_query(phrase), phrase)

    def test_a_dictated_secret_stays_local_and_is_not_kept(self):
        phrases = (
            "password for Netflix is hunter2",
            "what's my password for Chase is hunter2",
            "password for Netflix is hunter2 and what's the weather",
            "my password is hunter2",
            "the password is hunter2",
            "password is hunter2",
            "password: hunter2",
            "my password is hunter2 and open Safari",
        )
        for phrase in phrases:
            self.assertEqual(commands.route_before_api(phrase), "password_lookup", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            parsed = parse_password_query(phrase)
            blob = "{0} {1}".format(parsed.term, parsed.refused)
            self.assertNotIn("hunter2", blob, phrase)
            self.assertNotIn("hunter2", repr(parsed), phrase)
        netflix = parse_password_query("password for Netflix is hunter2")
        self.assertEqual(netflix.term, "Netflix")
        self.assertFalse(netflix.refused)
        chase = parse_password_query("password for Chase: hunter2")
        self.assertEqual(chase.term, "Chase")
        dictated = parse_password_query("my password is hunter2")
        self.assertTrue(dictated.refused)
        self.assertEqual(dictated.term, "")
        self.assertTrue(DICTATED_RE.match("my password is hunter2"))
        self.assertIsNone(LOOKUP_RE.match("my password is hunter2"))

    def test_hotwords_bias_password_without_echoing_a_command(self):
        self.assertIn("password", WHISPER_HOTWORDS)
        self.assertIn("passwords", WHISPER_HOTWORDS)
        self.assertTrue(is_hotword_echo("password"))
        self.assertTrue(is_hotword_echo("passwords"))
        self.assertFalse(is_hotword_echo("password for Netflix"))
        prompt = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        start = prompt.index("COMMAND_PROMPT = (")
        end = prompt.index(")", start)
        self.assertNotIn("Password for", prompt[start:end])
        self.assertNotIn("password for", prompt[start:end].lower())


class TestPasswordHandler(unittest.TestCase):
    def _calls(self, phrase, stdout="searched\n", boom=None):
        calls = []

        def runner(args):
            calls.append(list(args))
            if boom and args[0] == boom:
                raise RuntimeError("blocked")
            if args[0] == "osascript":
                return stdout
            return ""

        line = lookup_password(phrase, runner=runner)
        return line, calls

    def test_it_opens_the_app_and_types_only_the_site_name(self):
        line, calls = self._calls("what's my password for Chase")
        self.assertEqual(line, "Opened Passwords for Chase. Unlock with Touch ID.")
        self.assertEqual(line, OPENED_LINE.format("Chase"))
        self.assertEqual(calls[0], ["open", "-b", PASSWORDS_BUNDLE])
        self.assertEqual(calls[0][2], "com.apple.Passwords")
        self.assertEqual(calls[1][0], "osascript")
        self.assertEqual(calls[1][1], "-e")
        self.assertIs(calls[1][2], SEARCH_SCRIPT)
        self.assertEqual(calls[1][3], "Chase")
        self.assertNotIn("Chase", SEARCH_SCRIPT)
        self.assertNotIn("what's my password", " ".join(calls[1]))

    def test_a_locked_app_still_gets_the_same_sentence(self):
        line, calls = self._calls("password for Netflix", stdout="opened\n")
        self.assertEqual(line, "Opened Passwords for Netflix. Unlock with Touch ID.")
        self.assertEqual(calls[1][-1], "Netflix")

    def test_script_stdout_that_is_not_a_status_is_never_spoken(self):
        leaked = "ada@example.com hunter2"
        line, calls = self._calls("login for Amazon", stdout=leaked + "\n")
        self.assertEqual(line, "Opened Passwords for Amazon. Unlock with Touch ID.")
        self.assertNotIn("hunter2", line)
        self.assertNotIn("ada@", line)
        self.assertNotIn(leaked, line)
        self.assertEqual(calls[1][-1], "Amazon")

    def test_a_dictated_secret_is_not_typed_or_spoken(self):
        line, calls = self._calls("password for Netflix is hunter2")
        self.assertEqual(line, "Opened Passwords for Netflix. Unlock with Touch ID.")
        self.assertNotIn("hunter2", line)
        self.assertEqual(calls[1][-1], "Netflix")
        joined = " ".join(" ".join(call) for call in calls)
        self.assertNotIn("hunter2", joined)
        refused, refused_calls = self._calls("my password is hunter2")
        self.assertEqual(refused, REFUSE_LINE)
        self.assertNotIn("hunter2", refused)
        self.assertEqual(refused_calls, [])

    def test_missing_app_and_accessibility_failure_do_not_echo_a_secret(self):
        missing, calls = self._calls("password for Netflix is hunter2", boom="open")
        self.assertEqual(missing, MISSING_LINE)
        self.assertNotIn("hunter2", missing)
        self.assertEqual(calls, [["open", "-b", PASSWORDS_BUNDLE]])
        failed, failed_calls = self._calls("show my logins for Hulu", boom="osascript")
        self.assertEqual(failed, TYPE_FAIL_LINE.format("Hulu"))
        self.assertNotIn("blocked", failed)
        self.assertEqual(failed_calls[0][0], "open")
        self.assertEqual(failed_calls[1][-1], "Hulu")
        which, which_calls = self._calls("password for .")
        self.assertEqual(which, WHICH_LINE)
        self.assertEqual(which_calls, [])

    def test_the_script_only_types_into_the_search_field(self):
        lowered = SEARCH_SCRIPT.lower()
        for banned in (
            "get value",
            "pbcopy",
            "pbpaste",
            "clipboard",
            "keychain",
            "find-internet-password",
            "find-generic-password",
            "security ",
            "screencapture",
            "screenshot",
            "axsecuretextfield",
            "http://",
            "https://",
        ):
            self.assertNotIn(banned, lowered, banned)
        self.assertLess(
            SEARCH_SCRIPT.index('return "opened"'),
            SEARCH_SCRIPT.index("set value of targetField to query"),
        )
        self.assertLess(
            SEARCH_SCRIPT.index('return "missing"'),
            SEARCH_SCRIPT.index("set value of targetField to query"),
        )
        self.assertNotIn("keystroke", SEARCH_SCRIPT.lower())
        self.assertNotIn("key code", SEARCH_SCRIPT.lower())
        self.assertIn("AXSearchField", SEARCH_SCRIPT)
        self.assertIn("com.apple.Passwords", PASSWORDS_BUNDLE)
        source = open(os.path.join(ROOT, "commands", "passwords.py"), encoding="utf-8").read()
        for banned in (
            "requests",
            "urllib",
            "socket",
            "openrouter",
            "openai",
            "typesafe",
            "http://",
            "https://",
            "find-internet-password",
            "find-generic-password",
            "pbcopy",
            "pbpaste",
            "secrets_store",
            "import subprocess",
        ):
            self.assertNotIn(banned, source.lower(), banned)
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        secrets = open(os.path.join(ROOT, "secrets_store.py"), encoding="utf-8").read()
        self.assertNotIn("password_lookup", bridge)
        self.assertNotIn("password_lookup", secrets)

    def test_handler_makes_no_network_calls(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if args[0] == "osascript":
                return "searched\n"
            return ""

        def refuse_network(*_args, **_kwargs):
            raise AssertionError("password lookup tried to use the network")

        with mock.patch("socket.socket", side_effect=refuse_network), \
             mock.patch("socket.create_connection", side_effect=refuse_network), \
             mock.patch("urllib.request.urlopen", side_effect=refuse_network):
            line = lookup_password("what's my password for Chase", runner=runner)
        self.assertEqual(line, "Opened Passwords for Chase. Unlock with Touch ID.")
        self.assertEqual([call[0] for call in calls], ["open", "osascript"])
        self.assertIs(socket.socket, socket.socket)
        self.assertTrue(callable(urllib.request.urlopen))
        source = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        decide = source.split("def decide(", 1)[1].split("\ndef ", 1)[0]
        self.assertLess(decide.index("route_before_api"), decide.index("jev(") if "jev(" in decide else len(decide))
        self.assertIn("route_before_api", decide)
        handle = source.split("def handle(", 1)[1].split("\ndef ", 1)[0]
        runner = source.split("def _run_local(", 1)[1].split("\ndef ", 1)[0]
        self.assertLess(handle.index("is_password_lookup"), handle.index("zoe_claims"))
        self.assertLess(handle.index("decide(None, text)"), handle.index("jev(text)"))
        self.assertIn("(password lookup, kept on this Mac)", handle)
        self.assertIn("password_lookup", source)
        self.assertIn("lookup_password", source)
        self.assertIn("PASSWORD_KEYS", runner)

    def test_the_default_runner_is_a_stubbed_process_list(self):
        seen = []

        def fake_run(args, **_kwargs):
            seen.append(list(args))
            stdout = "searched\n" if args[0] == "osascript" else ""
            return _result(stdout)

        with mock.patch("commands.shell.subprocess.run", side_effect=fake_run):
            line = lookup_password("login for Amazon")
        self.assertEqual(line, "Opened Passwords for Amazon. Unlock with Touch ID.")
        self.assertEqual(seen[0], ["open", "-b", "com.apple.Passwords"])
        self.assertEqual(seen[1][0], "osascript")
        self.assertEqual(seen[1][-1], "Amazon")
        self.assertNotIn("security", " ".join(seen[0] + seen[1]))
        for call in seen:
            self.assertNotIn("find-internet-password", call)
            self.assertNotIn("find-generic-password", call)
            self.assertNotIn("pbcopy", call)


class TestZoeRefusesPasswordLookup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = os.path.join(self.tmp.name, "zoe-mode.txt")
        commands.set_zoe_mode_path(path)
        self.addCleanup(commands.clear_confirmation)
        self.addCleanup(commands.clear_zoe_exit)
        self.addCleanup(commands.set_zoe_mode_path, None)

    def test_zoe_mode_refuses_password_lookup_and_does_not_open_the_app(self):
        self.assertFalse(commands.zoe_mode_active())
        self.assertIsNone(commands.zoe_guard("password for Netflix"))
        commands.enter_zoe_mode()
        phrases = (
            "password for Netflix",
            "what's my password for Chase",
            "login for Amazon",
            "show my logins for Hulu",
            "my password is hunter2",
        )
        for phrase in phrases:
            self.assertEqual(commands.route_before_api(phrase), "password_lookup", phrase)
            self.assertIn("password_lookup", commands.ZOE_BLOCKED["passwords"], phrase)
            self.assertNotIn("password_lookup", commands.ZOE_ALLOW, phrase)
            self.assertFalse(commands.zoe_allows("password_lookup"), phrase)
            guard = commands.zoe_guard(phrase)
            self.assertEqual(guard["kind"], "speak", phrase)
            self.assertNotIn("action", guard, phrase)
            self.assertIn("grown-up", guard["line"].lower(), phrase)
            self.assertNotIn("hunter2", guard["line"], phrase)
            self.assertNotIn("Netflix", guard["line"], phrase)
            self.assertTrue(commands.zoe_mode_active(), phrase)

        def refuse(*_args, **_kwargs):
            raise AssertionError("Zoe mode tried to open Passwords")

        with mock.patch("commands.passwords.lookup_password", side_effect=refuse):
            again = commands.zoe_guard("password for Netflix")
        self.assertEqual(again["kind"], "speak")
        self.assertIn("grown-up", again["line"].lower())


if __name__ == "__main__":
    unittest.main()
