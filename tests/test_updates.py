"""Upstream update check. The HTTP call is mocked, so this runs in CI."""
import json
import os
import unittest
import urllib.error
from io import BytesIO
from unittest import mock

import updates
from updates import (
    API_URL,
    COMPARE_PAGE,
    HTTP_MESSAGE,
    NETWORK_MESSAGE,
    PARSE_MESSAGE,
    RATE_MESSAGE,
    TIMEOUT,
    UP_TO_DATE,
    check_upstream,
    http_get,
    interpret,
    safe_browser_url,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _commit(sha, date, message):
    return {
        "sha": sha,
        "commit": {
            "message": message,
            "author": {"date": date},
        },
    }


def _body(**fields):
    payload = {"files": [{"filename": "siri.py", "patch": "SECRET PATCH do not show"}]}
    payload.update(fields)
    return json.dumps(payload)


class TestCompare(unittest.TestCase):
    def test_the_request_is_one_public_compare_of_upstream_main(self):
        self.assertEqual(TIMEOUT, 10)
        self.assertEqual(
            API_URL,
            "https://api.github.com/repos/henryklunaris/hey-jev/compare/fernandoceja:main...main",
        )
        self.assertEqual(
            COMPARE_PAGE,
            "https://github.com/henryklunaris/hey-jev/compare/fernandoceja:main...main",
        )
        self.assertNotIn("token", API_URL)
        self.assertNotIn("access_token", API_URL)
        calls = []

        def fetch(url, timeout):
            calls.append((url, timeout))
            return 200, _body(status="identical", ahead_by=0, total_commits=0, commits=[])

        result = check_upstream(fetch=fetch, timeout=TIMEOUT)
        self.assertEqual(calls, [(API_URL, 10)])
        self.assertEqual(result["kind"], "current")
        self.assertEqual(result["title"], UP_TO_DATE)
        self.assertEqual(result["open_url"], COMPARE_PAGE)
        self.assertNotIn("SECRET", result["body"])

    def test_fork_only_commits_still_count_as_up_to_date(self):
        """ahead_by is upstream's commits. Extra commits on our main are not new upstream work."""
        result = interpret(200, _body(status="behind", ahead_by=0, behind_by=3, total_commits=0, commits=[]))
        self.assertEqual(result["title"], UP_TO_DATE)
        diverged = interpret(200, _body(
            status="diverged",
            ahead_by=1,
            behind_by=4,
            total_commits=1,
            commits=[_commit("abcdef1234567890", "2026-10-03T20:48:09Z", "Fix the pill\n\nLonger body.")],
            html_url="https://evil.example/compare",
        ))
        self.assertEqual(diverged["kind"], "updates")
        self.assertEqual(diverged["open_url"], COMPARE_PAGE)
        self.assertNotIn("evil.example", diverged["body"])
        self.assertNotIn("Longer body", diverged["body"])

    def test_new_upstream_commits_list_sha_date_and_subject(self):
        result = interpret(200, _body(
            status="ahead",
            ahead_by=2,
            total_commits=2,
            commits=[
                _commit("aaaabbbbccccdddd", "2026-10-01T01:02:03Z", "First change"),
                _commit("eeeeffffgggghhhh", "2026-10-02T04:05:06Z", "  Second   change  \nmore"),
            ],
        ))
        self.assertEqual(result["kind"], "updates")
        self.assertEqual(result["title"], "2 new commits on henryklunaris/hey-jev")
        self.assertIn("aaaabbb  2026-10-01  First change", result["body"])
        self.assertIn("eeeefff  2026-10-02  Second change", result["body"])
        self.assertNotIn("SECRET", result["body"])
        self.assertNotIn("siri.py", result["body"])
        self.assertEqual(safe_browser_url(result["open_url"]), COMPARE_PAGE)
        self.assertEqual(safe_browser_url("https://github.com/henryklunaris/hey-jev/archive/main.zip"), "")

    def test_network_errors_and_rate_limits_stay_short(self):
        for exc in (TimeoutError("timed out"), OSError("down"), urllib.error.URLError("dns")):
            result = check_upstream(fetch=lambda url, timeout: (_ for _ in ()).throw(exc), timeout=TIMEOUT)
            self.assertEqual(result["kind"], "network")
            self.assertEqual(result["body"], NETWORK_MESSAGE)
            self.assertEqual(result["open_url"], "")
        for status in (403, 429):
            limited = check_upstream(fetch=lambda url, timeout, status=status: (status, "rate limit exceeded"), timeout=4)
            self.assertEqual(limited["kind"], "rate_limit")
            self.assertEqual(limited["body"], RATE_MESSAGE)
            self.assertNotIn("rate limit exceeded", limited["body"])
        broken = interpret(500, "nope")
        self.assertEqual(broken["body"], HTTP_MESSAGE)
        self.assertEqual(interpret(200, "not json")["body"], PARSE_MESSAGE)

    def test_the_real_get_sends_no_token_and_uses_the_timeout(self):
        captured = {}

        class Fake:
            status = 200

            def read(self):
                return b'{"ahead_by": 0, "commits": []}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(request, timeout=None):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["method"] = request.get_method()
            captured["data"] = request.data
            captured["headers"] = {name.lower(): value for name, value in request.header_items()}
            return Fake()

        with mock.patch("urllib.request.urlopen", fake_open):
            status, body = http_get(API_URL, TIMEOUT)
        self.assertEqual(status, 200)
        self.assertIn("ahead_by", body)
        self.assertEqual(captured["url"], API_URL)
        self.assertEqual(captured["timeout"], 10)
        self.assertEqual(captured["method"], "GET")
        self.assertIsNone(captured["data"])
        self.assertNotIn("authorization", captured["headers"])
        self.assertEqual(captured["headers"].get("user-agent"), "hey-jev")
        with self.assertRaises(ValueError):
            http_get("https://github.com/henryklunaris/hey-jev/archive/refs/heads/main.zip", TIMEOUT)

        def limited_open(request, timeout=None):
            raise urllib.error.HTTPError(API_URL, 429, "Too Many Requests", {}, BytesIO(b"slow"))

        with mock.patch("urllib.request.urlopen", limited_open):
            code, text = http_get(API_URL, TIMEOUT)
        self.assertEqual((code, text), (429, "slow"))
        shown = interpret(code, text)
        self.assertEqual(shown["kind"], "rate_limit")
        self.assertNotIn("slow", shown["body"])

    def test_the_window_only_checks_on_click_and_stays_off_the_bridge(self):
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        source = open(os.path.join(ROOT, "updates.py"), encoding="utf-8").read()
        self.assertIn('button("Check for updates", self, "checkForUpdates:"', ui)
        self.assertIn('addItemWithTitle_action_keyEquivalent_("Check for Updates\\u2026", "checkForUpdates:"', ui)
        self.assertIn("check_upstream()", ui)
        self.assertIn("api.github.com", ui)
        self.assertNotIn("api.github.com", bridge)
        self.assertNotIn("check_upstream", bridge)
        for banned in ("subprocess", "urlretrieve", "git pull", "git clone", "Authorization", "get_secret", "Keychain"):
            self.assertNotIn(banned, source)
        start = ui.index("def checkForUpdates_")
        end = ui.index("def build_menu")
        block = ui[start:end]
        for banned in ("get_secret", "save_secret", "subprocess", "urlretrieve", "git pull"):
            self.assertNotIn(banned, block)


if __name__ == "__main__":
    unittest.main()
