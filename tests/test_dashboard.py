"""Local test-results dashboard: static HTML generation and browser open command.

subprocess is mocked so pytest and `open` never touch the real Mac during tests.
"""
import os
import socket
import tempfile
import unittest
from unittest import mock

import commands
from commands import dashboard
from commands.config import BRIDGE_ALLOW, TEST_REPORT_PATH
from commands.routing import route_before_api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_REPORT_PATH = os.path.expanduser(
    "~/Library/Application Support/Hey Jev/test-report.html"
)

PHRASES = (
    "show my test results",
    "Show my test results.",
    "show me my test results",
    "show test results",
    "show the test results",
    "open my test results",
    "open test results",
    "open the test results",
    "show my test report",
    "open my test report",
    "show my test dashboard",
    "open my test dashboard",
    "please show my test results",
    "show my test results please",
    "hey jev, show my test results",
    "hey jev, please show my test results!",
    "  show my test results  ",
)

KEPT = {
    "show my videos": "videos_open",
    "open my videos": "videos_open",
    "show my screenshots": "captures_open",
    "show me my clipboard history": "clipboard_history",
    "open god's eye": "gods_eye_open",
    "open Safari": "app_open",
    "what do my notes say about rent": "notes_ask",
}

SAMPLE_PYTEST_OUTPUT = """
============================= test session starts ==============================
collecting ... collected 5 items

tests/test_access.py::TestPhrases::test_one PASSED                       [ 20%]
tests/test_access.py::test_param[with spaces in param] PASSED            [ 40%]
tests/test_eta_home.py::TestEtaHome::test_drive PASSED                   [ 60%]
tests/test_eta_work.py::TestEtaWork::test_work PASSED                    [ 80%]
tests/test_notes_search.py::NotesSearchTests::test_search FAILED         [100%]

========================= 1 failed, 4 passed in 0.42s ==========================
"""


class TestDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run_recorder(self, calls, code=0):
        def fake_run(args, **kwargs):
            self.assertIsInstance(args, (list, tuple))
            self.assertNotIsInstance(args, (str, bytes))
            self.assertNotEqual(kwargs.get("shell"), True)
            calls.append((list(args), kwargs))
            if code:
                raise RuntimeError("open failed")
            return mock.Mock(returncode=0, stdout="", stderr="")

        return fake_run

    def test_report_path_constant_is_in_application_support(self):
        self.assertEqual(TEST_REPORT_PATH, EXPECTED_REPORT_PATH)
        self.assertEqual(commands.TEST_REPORT_PATH, EXPECTED_REPORT_PATH)
        self.assertEqual(commands.report_path(), EXPECTED_REPORT_PATH)
        self.assertTrue(TEST_REPORT_PATH.endswith("/Library/Application Support/Hey Jev/test-report.html"))
        self.assertIn("Hey Jev", TEST_REPORT_PATH)
        self.assertNotIn("~", TEST_REPORT_PATH)

    def test_voice_phrases_route_locally_and_stay_off_the_bridge(self):
        for phrase in PHRASES:
            self.assertEqual(route_before_api(phrase), "test_results_open", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        self.assertNotIn("test_results_open", BRIDGE_ALLOW)
        self.assertEqual(len(BRIDGE_ALLOW), 30)
        self.assertNotIn("test_results_open", commands.ZOE_ALLOW)
        self.assertIn("test_results_open", commands.ZOE_BLOCKED["system"])
        self.assertFalse(commands.zoe_allows("test_results_open"))
        for phrase, key in KEPT.items():
            self.assertEqual(route_before_api(phrase), key, phrase)
        for non_match in (
            "show my test results and mute",
            "test results",
            "show my test",
            "what are my test results",
        ):
            self.assertNotEqual(route_before_api(non_match), "test_results_open", non_match)

    def test_parses_pass_and_fail_per_command_module(self):
        modules = dashboard.parse_pytest_output(SAMPLE_PYTEST_OUTPUT)
        by_name = {m["module"]: m for m in modules}
        self.assertEqual(set(by_name), {"access", "leave", "notes_search"})
        self.assertEqual(by_name["access"]["status"], "PASS")
        self.assertEqual(by_name["access"]["passed"], 2)
        self.assertEqual(by_name["access"]["failed"], 0)
        self.assertEqual(by_name["leave"]["status"], "PASS")
        self.assertEqual(by_name["leave"]["passed"], 2)
        self.assertEqual(by_name["leave"]["files"], ["test_eta_home.py", "test_eta_work.py"])
        self.assertEqual(by_name["notes_search"]["status"], "FAIL")
        self.assertEqual(by_name["notes_search"]["passed"], 0)
        self.assertEqual(by_name["notes_search"]["failed"], 1)

    def test_dot_output_is_also_parsed(self):
        dot_out = "tests/test_cleanmymac.py ... [ 50%]\ntests/test_games.py ..F [100%]\n"
        by_name = {m["module"]: m for m in dashboard.parse_pytest_output(dot_out)}
        self.assertEqual(by_name["cleanmymac"]["status"], "PASS")
        self.assertEqual(by_name["cleanmymac"]["passed"], 3)
        self.assertEqual(by_name["games"]["status"], "FAIL")
        self.assertEqual(by_name["games"]["passed"], 2)
        self.assertEqual(by_name["games"]["failed"], 1)

    def test_renders_static_html_with_modules_and_last_run_time(self):
        modules = dashboard.parse_pytest_output(SAMPLE_PYTEST_OUTPUT)
        page = dashboard.render_report_html(
            modules,
            ran_at="2026-10-18 09:30:00 PDT",
            returncode=1,
        )
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn("Last run: 2026-10-18 09:30:00 PDT", page)
        self.assertIn("<code>access</code>", page)
        self.assertIn("<code>leave</code>", page)
        self.assertIn("<code>notes_search</code>", page)
        self.assertIn("PASS", page)
        self.assertIn("FAIL", page)
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)

    def test_build_test_report_runs_pytest_and_writes_html_atomically(self):
        report_file = os.path.join(self.tmp.name, "Hey Jev", "test-report.html")
        seen_cmds = []

        def fake_runner(cmd, **kwargs):
            self.assertIsInstance(cmd, list)
            self.assertNotEqual(kwargs.get("shell"), True)
            seen_cmds.append((cmd, kwargs))
            return mock.Mock(returncode=0, stdout="tests/test_access.py::test_ok PASSED\n", stderr="")

        result = dashboard.build_test_report(
            path=report_file,
            runner=fake_runner,
            now="2026-10-18 09:35:00 PDT",
        )
        self.assertEqual(result["path"], report_file)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(len(seen_cmds), 1)
        self.assertIn("-m", seen_cmds[0][0])
        self.assertIn("pytest", seen_cmds[0][0])
        self.assertTrue(os.path.isfile(report_file))
        self.assertFalse(os.path.exists(report_file + ".tmp"))
        content = open(report_file, encoding="utf-8").read()
        self.assertIn("2026-10-18 09:35:00 PDT", content)
        self.assertIn("<code>access</code>", content)
        self.assertIn("PASS", content)

    def test_open_test_results_launches_default_browser_with_argument_list(self):
        report_file = os.path.join(self.tmp.name, "Hey Jev", "test-report.html")
        dashboard.write_test_report("<!DOCTYPE html><title>ok</title>", path=report_file)
        calls = []
        spoken = commands.open_test_results(
            path=report_file,
            platform="darwin",
            run=self._run_recorder(calls),
        )
        self.assertEqual(spoken, commands.OPENING_TEST_RESULTS)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["open", report_file])
        self.assertIn(" ", calls[0][0][1])

    def test_missing_report_or_symlink_or_non_mac_does_not_open(self):
        missing = os.path.join(self.tmp.name, "Hey Jev", "test-report.html")
        calls = []
        self.assertEqual(
            commands.open_test_results(path=missing, platform="darwin", run=self._run_recorder(calls)),
            commands.MISSING_TEST_RESULTS,
        )
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(missing))

        real = os.path.join(self.tmp.name, "real.html")
        open(real, "w", encoding="utf-8").write("<!DOCTYPE html>")
        link = os.path.join(self.tmp.name, "link.html")
        os.symlink(real, link)
        self.assertEqual(
            commands.open_test_results(path=link, platform="darwin", run=self._run_recorder(calls)),
            commands.MISSING_TEST_RESULTS,
        )
        self.assertEqual(calls, [])

        self.assertEqual(
            commands.open_test_results(path=real, platform="linux", run=self._run_recorder(calls)),
            commands.TEST_RESULTS_NOT_MAC,
        )
        self.assertEqual(calls, [])

        self.assertEqual(
            commands.open_test_results(path=real, platform="darwin", run=self._run_recorder(calls, code=1)),
            commands.FAILED_TEST_RESULTS,
        )

    def test_no_sockets_no_network_no_keys_and_wired_in_siri(self):
        source = open(os.path.join(ROOT, "commands", "dashboard.py"), encoding="utf-8").read()
        bridge_src = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        secrets_src = open(os.path.join(ROOT, "secrets_store.py"), encoding="utf-8").read()
        siri_src = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        for banned in (
            "import socket",
            "socket.",
            "http.server",
            "HTTPServer",
            "socketserver",
            ".listen(",
            ".bind(",
            "requests",
            "urllib",
            "secrets_store",
            "get_secret",
            "shell=True",
            "os.system",
        ):
            self.assertNotIn(banned, source, banned)
        self.assertNotIn("test_results_open", bridge_src)
        self.assertNotIn("test-report.html", bridge_src)
        self.assertNotIn("test_results_open", secrets_src)
        self.assertIn('"test_results_open": lambda _arg, _text: commands.open_test_results()', siri_src)
        self.assertIn("Show my test results.", siri_src)
        self.assertIn("test results", commands.speak_help())
        with mock.patch.object(socket, "socket", side_effect=AssertionError("socket opened")):
            page = dashboard.render_report_html(
                dashboard.parse_pytest_output(SAMPLE_PYTEST_OUTPUT),
                ran_at="2026-10-18 09:30:00 PDT",
            )
            self.assertIn("Hey Jev Test Results", page)


if __name__ == "__main__":
    unittest.main()
