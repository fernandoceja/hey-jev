"""Open God's Eye from the Quick Commands menu or a spoken phrase.

subprocess, the port check, and the browser are mocked. Nothing listens,
and the iPhone bridge is not asked to run this.
"""
import os
import socket
import tempfile
import unittest
from unittest import mock

import commands
import commands.gods_eye as gods_eye
from mini_bar import plus_item, plus_menu, submission

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NPM = "/opt/homebrew/bin/npm"
URL = "http://127.0.0.1:5827"

PHRASES = (
    "open god's eye",
    "god's eye",
    "gods eye",
    "open gods eye",
    "open the god's eye",
    "open the gods eye",
    "Open God's Eye.",
    "GODS EYE",
    "please open god's eye",
    "open god's eye please",
    "hey jev, open god's eye",
    "hey jev, god's eye",
    "hey jev, gods eye",
    "hey jev please open gods eye",
    "please hey jev, gods eye",
    "  open god's eye  ",
    "open god\u2019s eye",
)

KEPT = {
    "hazard check": "info_hazards",
    "any fires near me": "info_hazards_fires",
    "turn on hazard alerts": "hazard_alerts_on",
    "open videos": "videos_open",
    "open my videos": "videos_open",
    "open Apple TV": "app_open",
    "payday check": "info_payday_check",
    "brief me": "info_brief",
}


class TestGodsEyeRouting(unittest.TestCase):
    def test_phrases_open_gods_eye_and_stay_off_the_bridge(self):
        for phrase in PHRASES:
            self.assertEqual(commands.route_before_api(phrase), "gods_eye_open", phrase)
            self.assertNotIn("gods_eye_open", commands.BRIDGE_ALLOW, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        self.assertNotIn("gods_eye_open", commands.ZOE_ALLOW)
        self.assertIn("gods_eye_open", commands.ZOE_BLOCKED["system"])
        self.assertFalse(commands.zoe_allows("gods_eye_open"))
        for phrase, key in KEPT.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertNotEqual(key, "gods_eye_open", phrase)
        for phrase in (
            "open god",
            "open eye",
            "gods",
            "what is god's eye",
            "launch god's eye",
            "open god's eyes",
            "open god's eye and mute",
            "gods eye and hazard check",
        ):
            self.assertNotEqual(commands.route_before_api(phrase), "gods_eye_open", phrase)

    def test_the_menu_types_the_voice_phrase_next_to_hazard_check(self):
        def quick_rows(menu):
            for item in menu:
                if item.get("id") == "quick":
                    return list(item["items"])
            self.fail("Quick Commands is missing")

        rows = quick_rows(plus_menu())
        ids = [row.get("id") for row in rows]
        hazard = ids.index("hazard")
        self.assertEqual(ids[hazard + 1], "gods_eye")
        self.assertEqual(ids[hazard + 2], "hazard_alerts")
        item = plus_item("gods_eye")
        self.assertEqual(item["kind"], "text")
        self.assertEqual(item["title"], "Open God's Eye")
        self.assertEqual(item["phrase"], "open god's eye")
        self.assertEqual(item["symbol"], "eye")
        self.assertEqual(item["key"], "")
        plan = submission(item["phrase"])
        self.assertEqual(plan["kind"], "run")
        self.assertEqual(plan["control"], ("text", "open god's eye"))
        self.assertFalse(plan["reveal_main"])
        self.assertEqual(commands.route_before_api(plan["control"][1]), "gods_eye_open")
        self.assertNotIn("gods_eye_open", commands.BRIDGE_ALLOW)

    def test_siri_wires_the_action_and_the_bridge_files_are_untouched(self):
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        secrets = open(os.path.join(ROOT, "secrets_store.py"), encoding="utf-8").read()
        source = open(os.path.join(ROOT, "commands", "gods_eye.py"), encoding="utf-8").read()
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertIn('"gods_eye_open": lambda _arg, _text: commands.open_gods_eye()', siri)
        self.assertIn("Open God's Eye. God's eye. Gods eye.", siri)
        self.assertIn("God's Eye", commands.speak_help())
        self.assertIn("Open God's Eye", readme)
        self.assertIn("GODS_EYE_DIR", readme)
        self.assertIn("JEV_GODS_EYE_DIR", readme)
        self.assertIn("127.0.0.1:5827", readme)
        self.assertNotIn("gods_eye", bridge)
        self.assertNotIn("gods_eye_open", bridge)
        self.assertNotIn("5827", bridge)
        self.assertNotIn("GODS_EYE", bridge)
        self.assertIn("hmac.new", bridge)
        self.assertIn("BRIDGE_ALLOW", bridge)
        self.assertNotIn("gods_eye", secrets)
        self.assertNotIn("5827", secrets)
        self.assertNotIn("GODS_EYE", secrets)
        for banned in (
            "shell=True",
            "os.system",
            ".listen(",
            ".bind(",
            "socket.socket",
            "socketserver",
            "HTTPServer",
            "keychain",
            "secrets_store",
            "get_secret",
            "BRIDGE_ALLOW",
        ):
            self.assertNotIn(banned, source, banned)
        self.assertIn("socket.create_connection", source)
        self.assertIn("start_new_session=True", source)
        self.assertIn('"ab"', source)


class TestGodsEyeLaunch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _project(self, name="gods-eye"):
        folder = os.path.join(self.tmp.name, name)
        os.makedirs(folder)
        return folder

    def _clock(self):
        state = {"t": 0.0}
        sleeps = []

        def clock():
            return state["t"]

        def sleep(seconds):
            self.assertGreater(seconds, 0)
            state["t"] += seconds
            sleeps.append(seconds)

        return clock, sleep, sleeps

    def _popen(self, calls, boom=None):
        def fake_popen(args, **kwargs):
            self.assertIsInstance(args, list)
            self.assertNotIsInstance(args, str)
            self.assertNotEqual(kwargs.get("shell"), True)
            self.assertNotIn("shell", kwargs)
            calls.append((list(args), kwargs))
            if boom:
                raise boom
            return mock.Mock(pid=4321)
        return fake_popen

    def _open(self, calls, result=True, boom=None):
        def opener(url):
            calls.append(url)
            if boom:
                raise boom
            return result
        return opener

    def test_the_folder_defaults_to_developer_gods_eye_and_can_be_overridden(self):
        self.assertEqual(commands.GODS_EYE_DIR, os.path.expanduser("~/Developer/gods-eye"))
        self.assertTrue(commands.GODS_EYE_DIR.endswith("/Developer/gods-eye"))
        self.assertFalse(commands.GODS_EYE_DIR.startswith("~"))
        self.assertEqual(commands.GODS_EYE_HOST, "127.0.0.1")
        self.assertEqual(commands.GODS_EYE_PORT, 5827)
        self.assertEqual(commands.GODS_EYE_URL, URL)
        self.assertEqual(commands.gods_eye_url(), URL)
        self.assertEqual(commands.GODS_EYE_WAIT_SECONDS, 15)
        self.assertEqual(commands.GODS_EYE_LOG_NAME, ".dev.log")
        env = os.environ.copy()
        env.pop("JEV_GODS_EYE_DIR", None)
        self.assertEqual(commands.gods_eye_dir(env=env), commands.GODS_EYE_DIR)

        custom = os.path.join(self.tmp.name, "other eye")
        self.assertEqual(
            commands.gods_eye_dir(override=custom, env={"JEV_GODS_EYE_DIR": "/tmp/env-eye"}),
            custom,
        )
        self.assertEqual(
            commands.gods_eye_dir(env={"JEV_GODS_EYE_DIR": custom}),
            custom,
        )
        home = self.tmp.name
        with mock.patch.dict(os.environ, {"HOME": home}):
            expanded = commands.gods_eye_dir(override="~/Developer/gods-eye")
        self.assertEqual(expanded, os.path.join(home, "Developer", "gods-eye"))
        self.assertNotIn("~", expanded)
        self.assertEqual(commands.gods_eye_dir(override="/tmp/bad\neye"), "")
        self.assertEqual(commands.gods_eye_dir(override="/tmp/eye && rm"), "")
        self.assertEqual(commands.dev_command(NPM), [NPM, "run", "dev"])
        self.assertIsNone(commands.dev_command("npm run dev"))
        self.assertIsNone(commands.dev_command("/tmp/npm;rm"))

    def test_find_npm_uses_path_then_homebrew(self):
        def yes(path):
            return path in (NPM, "/usr/local/bin/npm")

        self.assertEqual(commands.find_npm(which=lambda _name: NPM, isfile=yes), NPM)
        self.assertEqual(
            commands.find_npm(which=lambda _name: None, isfile=lambda path: path == "/usr/local/bin/npm"),
            "/usr/local/bin/npm",
        )
        self.assertEqual(commands.find_npm(which=lambda _name: None, isfile=lambda _path: False), "")
        self.assertEqual(commands.find_npm(which=lambda _name: "npm", isfile=yes), NPM)

    def test_a_listening_port_opens_the_browser_and_does_not_start_npm(self):
        missing = os.path.join(self.tmp.name, "not-created")
        started = []
        opened = []
        probed = []

        def probe(host, port):
            probed.append((host, port))
            return True

        def boom(*_args, **_kwargs):
            raise AssertionError("sleep")

        spoken = commands.open_gods_eye(
            folder=missing,
            platform="darwin",
            probe=probe,
            popen=self._popen(started),
            opener=self._open(opened),
            sleep=boom,
            npm=NPM,
        )
        self.assertEqual(spoken, "Opening God's Eye.")
        self.assertEqual(spoken, commands.OPENING_GODS_EYE)
        self.assertEqual(probed, [("127.0.0.1", 5827)])
        self.assertEqual(opened, [URL])
        self.assertEqual(started, [])
        self.assertFalse(os.path.exists(missing))
        self.assertFalse(os.path.exists(os.path.join(missing, ".dev.log")))

    def test_a_closed_port_starts_npm_then_opens_the_page(self):
        folder = self._project("gods eye")
        started = []
        opened = []
        answers = iter((False, False, True))
        clock, sleep, sleeps = self._clock()

        def probe(host, port):
            self.assertEqual((host, port), ("127.0.0.1", 5827))
            return next(answers)

        spoken = commands.open_gods_eye(
            folder=folder,
            platform="darwin",
            probe=probe,
            popen=self._popen(started),
            opener=self._open(opened),
            npm=NPM,
            clock=clock,
            sleep=sleep,
            child_env={"PATH": "/usr/bin", "HOME": "/Users/me"},
            wait_seconds=15,
            poll_seconds=0.25,
        )
        self.assertEqual(spoken, "Opening God's Eye.")
        self.assertEqual(opened, [URL])
        self.assertEqual(len(started), 1)
        args, kwargs = started[0]
        self.assertEqual(args, [NPM, "run", "dev"])
        self.assertNotIn("&&", args)
        self.assertNotIn("cd", args)
        self.assertEqual(kwargs["cwd"], folder)
        self.assertIn(" ", kwargs["cwd"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertTrue(kwargs["close_fds"])
        self.assertIs(kwargs["stdin"], commands.gods_eye.subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], commands.gods_eye.subprocess.STDOUT)
        self.assertEqual(kwargs["env"]["HOME"], "/Users/me")
        self.assertEqual(kwargs["env"]["PATH"], "/opt/homebrew/bin:/usr/bin")
        self.assertEqual(kwargs["stdout"].name, os.path.join(folder, ".dev.log"))
        self.assertTrue(os.path.isfile(os.path.join(folder, ".dev.log")))
        self.assertEqual(sleeps, [0.25])

    def test_the_default_probe_only_connects_as_a_client(self):
        folder = self._project()
        started = []
        opened = []
        sock = mock.Mock()
        calls = []

        def connect(address, timeout):
            calls.append((address, timeout))
            if len(calls) == 1:
                raise ConnectionRefusedError("closed")
            return sock

        with mock.patch.object(gods_eye.socket, "socket", side_effect=AssertionError("listened")), \
                mock.patch.object(gods_eye.socket, "create_connection", side_effect=connect):
            spoken = commands.open_gods_eye(
                folder=folder,
                platform="darwin",
                popen=self._popen(started),
                opener=self._open(opened),
                npm=NPM,
                child_env={"PATH": "/usr/bin"},
            )
        self.assertEqual(spoken, "Opening God's Eye.")
        self.assertEqual(calls[0][0], ("127.0.0.1", 5827))
        self.assertEqual(calls[0][1], commands.GODS_EYE_CONNECT_TIMEOUT)
        self.assertEqual([address for address, _timeout in calls], [("127.0.0.1", 5827), ("127.0.0.1", 5827)])
        sock.close.assert_called_once()
        self.assertEqual(len(started), 1)
        self.assertEqual(opened, [URL])
        sock.listen.assert_not_called()
        sock.bind.assert_not_called()

    def test_a_refused_connection_is_not_an_open_port(self):
        with mock.patch.object(gods_eye.socket, "socket", side_effect=AssertionError("listened")), \
                mock.patch.object(gods_eye.socket, "create_connection", side_effect=ConnectionRefusedError):
            self.assertFalse(commands.port_is_open("127.0.0.1", 5827))
        with mock.patch.object(gods_eye.socket, "create_connection", side_effect=socket.timeout("timed out")):
            self.assertFalse(commands.port_is_open("127.0.0.1", 5827))

    def test_a_port_that_never_answers_speaks_a_short_error(self):
        folder = self._project()
        started = []
        opened = []
        clock, sleep, sleeps = self._clock()
        spoken = commands.open_gods_eye(
            folder=folder,
            platform="darwin",
            probe=lambda _host, _port: False,
            popen=self._popen(started),
            opener=self._open(opened),
            npm=NPM,
            clock=clock,
            sleep=sleep,
            child_env={"PATH": "/usr/bin"},
            wait_seconds=15,
            poll_seconds=0.25,
        )
        self.assertEqual(spoken, "I couldn't open God's Eye.")
        self.assertEqual(spoken, commands.GODS_EYE_FAILED)
        self.assertEqual(opened, [])
        self.assertEqual(len(started), 1)
        self.assertAlmostEqual(sum(sleeps), 15.0)
        self.assertLessEqual(sum(sleeps), 15.0)

    def test_a_missing_folder_is_not_created(self):
        missing = os.path.join(self.tmp.name, "Developer", "gods-eye")
        started = []
        opened = []
        spoken = commands.open_gods_eye(
            folder=missing,
            platform="darwin",
            probe=lambda _host, _port: False,
            popen=self._popen(started),
            opener=self._open(opened),
            npm=NPM,
        )
        self.assertEqual(spoken, "The God's Eye folder isn't there.")
        self.assertEqual(spoken, commands.GODS_EYE_MISSING)
        self.assertEqual(started, [])
        self.assertEqual(opened, [])
        self.assertFalse(os.path.exists(missing))
        self.assertFalse(os.path.exists(os.path.dirname(missing)))

    def test_linux_does_not_connect_or_start_anything(self):
        folder = self._project()

        def refuse(*_args, **_kwargs):
            raise AssertionError("touched the machine")

        spoken = commands.open_gods_eye(
            folder=folder,
            platform="linux",
            probe=refuse,
            popen=refuse,
            opener=refuse,
            npm=NPM,
        )
        self.assertEqual(spoken, "God's Eye runs on this Mac.")
        self.assertEqual(spoken, commands.GODS_EYE_NOT_MAC)

    def test_npm_missing_or_a_failed_start_or_browser_does_not_pretend_success(self):
        folder = self._project()
        started = []
        opened = []
        spoken = commands.open_gods_eye(
            folder=folder,
            platform="darwin",
            probe=lambda _host, _port: False,
            popen=self._popen(started),
            opener=self._open(opened),
            which=lambda _name: None,
            npm_isfile=lambda _path: False,
        )
        self.assertEqual(spoken, commands.GODS_EYE_FAILED)
        self.assertEqual(started, [])
        self.assertEqual(opened, [])

        started.clear()
        spoken = commands.open_gods_eye(
            folder=folder,
            platform="darwin",
            probe=lambda _host, _port: False,
            popen=self._popen(started, boom=OSError("npm failed")),
            opener=self._open(opened),
            npm=NPM,
            child_env={"PATH": "/usr/bin"},
        )
        self.assertEqual(spoken, commands.GODS_EYE_FAILED)
        self.assertEqual(len(started), 1)
        self.assertEqual(opened, [])

        opened.clear()
        spoken = commands.open_gods_eye(
            folder=folder,
            platform="darwin",
            probe=lambda _host, _port: True,
            popen=self._popen(started),
            opener=self._open(opened, result=False),
            npm=NPM,
        )
        self.assertEqual(spoken, commands.GODS_EYE_FAILED)
        self.assertEqual(opened, [URL])

        opened.clear()
        spoken = commands.open_gods_eye(
            folder=folder,
            platform="darwin",
            probe=lambda _host, _port: True,
            popen=self._popen(started),
            opener=self._open(opened, boom=OSError("no browser")),
            npm=NPM,
        )
        self.assertEqual(spoken, commands.GODS_EYE_FAILED)
        self.assertEqual(opened, [URL])

    def test_the_env_folder_is_what_npm_runs_in(self):
        folder = self._project("from-env")
        started = []
        clock, sleep, _sleeps = self._clock()
        answers = iter((False, True))
        spoken = commands.open_gods_eye(
            env={"JEV_GODS_EYE_DIR": folder},
            platform="darwin",
            probe=lambda _host, _port: next(answers),
            popen=self._popen(started),
            opener=self._open([]),
            npm=NPM,
            clock=clock,
            sleep=sleep,
            child_env={"PATH": "/usr/bin"},
        )
        self.assertEqual(spoken, commands.OPENING_GODS_EYE)
        self.assertEqual(started[0][1]["cwd"], folder)
        self.assertEqual(started[0][1]["stdout"].name, os.path.join(folder, ".dev.log"))

    def test_zoe_mode_refuses_it(self):
        path = os.path.join(self.tmp.name, "zoe-mode.txt")
        commands.set_zoe_mode_path(path)
        self.addCleanup(commands.set_zoe_mode_path, None)
        commands.enter_zoe_mode()
        self.assertTrue(commands.zoe_mode_active())
        refused = commands.zoe_guard("open god's eye")
        self.assertEqual(refused["kind"], "speak")
        self.assertIn("grown-up", refused["line"].lower())
        self.assertTrue(commands.zoe_mode_active())
        self.assertEqual(commands.route_before_api("gods eye"), "gods_eye_open")
        self.assertIsNone(commands.bridge_allowed("gods eye"))


if __name__ == "__main__":
    unittest.main()
