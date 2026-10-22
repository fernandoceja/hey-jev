"""On-device fm fallback: localhost only, Mac only, no money or My Love, no tools. No network."""
import os
import unittest
from unittest import mock


from commands import local_fallback as lf


class HTTPError(Exception):
    def __init__(self, response=None):
        self.response = response


class Timeout(OSError):
    pass


def ok(text):
    return {"choices": [{"message": {"content": text}}]}


class FmFallbackTests(unittest.TestCase):
    def test_blocks_money_and_my_love(self):
        for t in ("Pay my Discover card", "transfer $50 to savings", "Read my messages from My Love",
                  "send money to mom on Zelle"):
            self.assertFalse(lf.allowed(t, platform="darwin"), t)

    def test_allows_plain_question_on_mac_only(self):
        self.assertTrue(lf.allowed("What's the capital of Peru?", platform="darwin"))
        self.assertFalse(lf.allowed("What's the capital of Peru?", platform="linux"))
        self.assertFalse(lf.allowed("What's the capital of Peru?", platform="ios"))

    def test_network_errors_trigger_but_bad_request_does_not(self):
        self.assertTrue(lf.is_network_failure(ConnectionError()))
        self.assertTrue(lf.is_network_failure(Timeout()))
        for code, want in ((503, True), (429, True), (402, True), (400, False)):
            resp = mock.Mock(status_code=code)
            self.assertEqual(lf.is_network_failure(HTTPError(response=resp)), want)
        self.assertFalse(lf.is_network_failure(ValueError()))

    def test_body_has_no_tools_and_is_trimmed(self):
        body = lf.fm_body([{"role": "user", "content": "x" * 9000, "tool_calls": [1]}])
        self.assertNotIn("tools", body)
        self.assertNotIn("tool_calls", body["messages"][0])
        self.assertEqual(len(body["messages"][0]["content"]), lf.FM_MAX_PROMPT_CHARS)

    def test_ask_fm_answers_and_never_raises(self):
        seen = []
        def post(url, body):
            seen.append(url)
            return ok(" Lima. ")
        self.assertEqual(lf.ask_fm([{"role": "user", "content": "q"}], post), "Lima.")
        self.assertEqual(seen[0], "http://127.0.0.1:1976/v1/chat/completions")
        def down(url, body):
            raise ConnectionError()
        self.assertIsNone(lf.ask_fm([{"role": "user", "content": "q"}], down))

    def test_remote_url_refused(self):
        with mock.patch.dict(os.environ, {"JEV_FM_URL": "http://evil.example.com/v1"}):
            self.assertIsNone(lf.fm_url())
            self.assertIsNone(lf.ask_fm([{"role": "user", "content": "q"}], lambda u, b: ok("x")))

    def test_jev_never_starts_a_server(self):
        src = open(lf.__file__).read()
        for bad in ("subprocess", "socket.socket", ".bind(", ".listen(", "Popen"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
