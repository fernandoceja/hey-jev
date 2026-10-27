"""Model router gates. TypeSafe is mocked. No live call, no Keychain, no secrets."""
import json
import os
import pathlib
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

from commands import model_router
from commands import typesafe_client as ts

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET = "ts-test-key-not-real"
LONG = "Synthetic routing sample. " * 20  # well over 300 characters, no personal data


def _answers(choice, confidence, stakes, tools=0.1, input_tokens=11, output_tokens=7):
    return {
        "model": "jev-latest",
        "answers": {
            "tier": {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": {}},
            "needs_tools_or_code": {"type": "noul", "noul": tools},
            "high_stakes": {"type": "noul", "noul": stakes},
        },
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def _post_returning(payload, seen=None):
    def post(body, key):
        if seen is not None:
            seen.append((body, key))
        return payload
    return post


class RouterTests(unittest.TestCase):
    def test_config_holds_the_model_ids_and_the_code_does_not(self):
        with open(model_router.CONFIG_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["cheap"][0], model_router.load_models()["cheap"])
        self.assertGreaterEqual(len(data["cheap"]), 2)
        self.assertIn("haiku", data["cheap"][0].lower())
        self.assertIn("flash", data["cheap"][1].lower())
        self.assertIn("sonnet", data["mid"][0].lower())
        self.assertIn("opus", data["heavy"][0].lower())
        source = ""
        for name in ("model_router.py", "typesafe_client.py"):
            source += open(os.path.join(ROOT, "commands", name), encoding="utf-8").read().lower()
        for banned in ("claude", "gemini", "haiku", "sonnet", "opus", "anthropic/", "google/"):
            self.assertNotIn(banned, source, banned)
        self.assertNotIn("print(", source)
        self.assertNotIn("logging", source)
        for banned in ("import socket", ".listen(", ".bind(", "twingate", "shell=true"):
            self.assertNotIn(banned, source, banned)

    def test_nothing_calls_the_router_and_bridge_and_secrets_stay_untouched(self):
        for name in (
            "siri.py",
            "commands/__init__.py",
            "commands/brief.py",
            "commands/brief_memo.py",
            "commands/bridge.py",
            "commands/mail_voice.py",
            "secrets_store.py",
        ):
            text = open(os.path.join(ROOT, name), encoding="utf-8").read()
            self.assertNotIn("model_router", text, name)
            self.assertNotIn("typesafe_client", text, name)
            self.assertNotIn("model_tiers", text, name)

    def test_one_call_sends_three_questions_and_short_state_only(self):
        marker = "TAILMARKER"
        text = ("sample " * 200) + marker
        self.assertGreater(len(text), ts.EXCERPT_CHARS)
        seen = []
        decision = model_router.route(
            text, "brief\nextra", post=_post_returning(_answers("mid", 0.9, 0.1), seen), key=SECRET,
        )
        self.assertEqual(len(seen), 1)
        body, key = seen[0]
        self.assertEqual(key, SECRET)
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(set(body["questions"]), {"tier", "needs_tools_or_code", "high_stakes"})
        self.assertEqual(body["questions"]["tier"]["type"], "choice")
        self.assertEqual(set(body["questions"]["tier"]["criteria"]), {"cheap", "mid", "heavy"})
        self.assertEqual(body["questions"]["needs_tools_or_code"]["type"], "noul")
        self.assertEqual(body["questions"]["high_stakes"]["type"], "noul")
        self.assertEqual(set(body["state"]), {"command", "input_chars", "excerpt"})
        self.assertEqual(body["state"]["command"], "brief extra")
        self.assertEqual(body["state"]["input_chars"], len(text))
        self.assertEqual(len(body["state"]["excerpt"]), 1000)
        self.assertNotIn(marker, json.dumps(body))
        self.assertNotIn(SECRET, json.dumps(body))
        self.assertEqual(decision["tier"], "mid")
        self.assertEqual(decision["model"], model_router.load_models()["mid"])
        self.assertEqual(decision["usage"], {"input_tokens": 11, "output_tokens": 7})
        self.assertIn("needs_tools_or_code:0.1000", decision["reasons"])

    def test_tools_alone_do_not_move_the_tier(self):
        decision = self._route("cheap", 0.91, 0.1, tools=0.99)
        self.assertEqual(decision["tier"], "cheap")
        self.assertNotIn("gate:cheap_blocked", decision["reasons"])
        self.assertIn("needs_tools_or_code:0.9900", decision["reasons"])

    def test_heavy_choice_routes_to_heavy(self):
        decision = self._route("heavy", 0.9, 0.1)
        self.assertEqual(decision["tier"], "heavy")
        self.assertEqual(decision["model"], model_router.load_models()["heavy"])
        self.assertIn("gate:heavy", decision["reasons"])
        self.assertNotIn("gate:high_stakes", decision["reasons"])

    def test_high_stakes_at_the_line_routes_to_heavy(self):
        decision = self._route("cheap", 0.95, 0.6)
        self.assertEqual(decision["tier"], "heavy")
        self.assertIn("gate:high_stakes", decision["reasons"])
        just_under = self._route("mid", 0.95, 0.5999)
        self.assertEqual(just_under["tier"], "mid")
        self.assertNotIn("gate:high_stakes", just_under["reasons"])

    def test_low_confidence_bumps_one_tier_and_the_line_does_not(self):
        bumped = self._route("cheap", 0.5499, 0.0)
        self.assertEqual(bumped["tier"], "mid")
        self.assertIn("gate:low_confidence", bumped["reasons"])
        held = self._route("cheap", 0.55, 0.0)
        self.assertEqual(held["tier"], "cheap")
        self.assertNotIn("gate:low_confidence", held["reasons"])
        from_mid = self._route("mid", 0.0, 0.0)
        self.assertEqual(from_mid["tier"], "heavy")
        self.assertIn("gate:low_confidence", from_mid["reasons"])
        already = self._route("heavy", 0.1, 0.0)
        self.assertEqual(already["tier"], "heavy")
        self.assertNotIn("gate:low_confidence", already["reasons"])

    def test_cheap_is_allowed_only_under_the_stakes_line(self):
        allowed = self._route("cheap", 0.9, 0.2999)
        self.assertEqual(allowed["tier"], "cheap")
        self.assertNotIn("gate:cheap_blocked", allowed["reasons"])
        blocked = self._route("cheap", 0.9, 0.3)
        self.assertEqual(blocked["tier"], "mid")
        self.assertEqual(blocked["model"], model_router.load_models()["mid"])
        self.assertIn("gate:cheap_blocked", blocked["reasons"])
        still_not_heavy = self._route("cheap", 0.99, 0.5999)
        self.assertEqual(still_not_heavy["tier"], "mid")
        self.assertIn("gate:cheap_blocked", still_not_heavy["reasons"])
        self.assertNotIn("gate:high_stakes", still_not_heavy["reasons"])

    def test_low_confidence_and_blocked_cheap_and_heavy_stakes_compose(self):
        # Cheap, unsure, stakes in the middle: bump once, then stop. Not heavy.
        mixed = self._route("cheap", 0.2, 0.4)
        self.assertEqual(mixed["tier"], "mid")
        self.assertIn("gate:low_confidence", mixed["reasons"])
        self.assertNotIn("gate:cheap_blocked", mixed["reasons"])
        # Stakes at the heavy line win even when the choice was cheap.
        forced = self._route("cheap", 0.2, 0.6)
        self.assertEqual(forced["tier"], "heavy")
        self.assertIn("gate:high_stakes", forced["reasons"])

    def test_manual_override_wins_and_skips_the_call(self):
        def post(*_args):
            raise AssertionError("posted")

        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            heavy = model_router.route("x" * 20, "brief", override="Heavy", post=post, key=SECRET)
            cheap = model_router.route(LONG, "triage", override="cheap", post=post, key=SECRET)
        self.assertEqual(heavy["tier"], "heavy")
        self.assertEqual(heavy["model"], model_router.load_models()["heavy"])
        self.assertEqual(heavy["reasons"], ["override"])
        self.assertEqual(heavy["usage"], {"input_tokens": 0, "output_tokens": 0})
        self.assertEqual(cheap["tier"], "cheap")
        self.assertEqual(cheap["reasons"], ["override"])
        self.assertNotIn(SECRET, out.getvalue() + err.getvalue())
        ignored = model_router.route(
            LONG, "brief", override="nope", post=_post_returning(_answers("mid", 0.9, 0.1)), key=SECRET,
        )
        self.assertEqual(ignored["tier"], "mid")

    def test_short_input_skips_the_call_and_the_boundary_does_not(self):
        def post(*_args):
            raise AssertionError("posted")

        short = model_router.route("n" * 299, "brief", post=post, key=SECRET)
        self.assertEqual(short["tier"], "cheap")
        self.assertEqual(short["model"], model_router.load_models()["cheap"])
        self.assertEqual(short["reasons"], ["short_input"])
        self.assertEqual(short["usage"], {"input_tokens": 0, "output_tokens": 0})
        empty = model_router.route(None, "brief", post=post, key=SECRET)
        self.assertEqual(empty["reasons"], ["short_input"])
        seen = []
        at_line = model_router.route(
            "n" * 300, "triage", post=_post_returning(_answers("heavy", 0.8, 0.0), seen), key=SECRET,
        )
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0]["state"]["input_chars"], 300)
        self.assertEqual(at_line["tier"], "heavy")

    def test_typesafe_unavailable_falls_back_to_mid(self):
        def explode(*_args):
            raise RuntimeError("down " + SECRET)

        cases = [
            model_router.route(LONG, "brief", post=explode, key=SECRET),
            model_router.route(LONG, "brief", post=lambda body, key: ["nope"], key=SECRET),
            model_router.route(LONG, "brief", post=lambda body, key: {"answers": {}}, key=SECRET),
            model_router.route(LONG, "brief", post=lambda body, key: _answers("huge", 0.9, 0.1), key=SECRET),
            model_router.route(LONG, "brief", post=lambda body, key: _answers("cheap", 1.2, 0.1), key=SECRET),
            model_router.route(LONG, "brief", post=lambda body, key: _answers("cheap", 0.9, 1.4), key=SECRET),
            model_router.route(LONG, "brief", key=""),
            model_router.route(LONG, "brief", key="   "),
        ]
        for decision in cases:
            self.assertEqual(decision["tier"], "mid", decision)
            self.assertEqual(decision["reasons"], ["typesafe_unavailable"], decision)
            self.assertEqual(decision["model"], model_router.load_models()["mid"])
            self.assertNotIn(SECRET, json.dumps(decision))

    def test_a_partial_payload_keeps_token_usage_on_the_fallback(self):
        payload = _answers("cheap", 0.9, 0.1)
        del payload["answers"]["needs_tools_or_code"]
        decision = model_router.route(LONG, "brief", post=lambda body, key: payload, key=SECRET)
        self.assertEqual(decision["tier"], "mid")
        self.assertEqual(decision["reasons"], ["typesafe_unavailable"])
        self.assertEqual(decision["usage"], {"input_tokens": 11, "output_tokens": 7})

    def test_missing_key_does_not_post_or_print(self):
        def post(*_args):
            raise AssertionError("posted")

        out, err = StringIO(), StringIO()

        def run(get_secret):
            fake = types.ModuleType("secrets_store")
            fake.get_secret = get_secret
            with mock.patch.dict(sys.modules, {"secrets_store": fake}):
                with redirect_stdout(out), redirect_stderr(err):
                    return model_router.route(LONG, "brief", post=post)

        missing = run(lambda _name: None)
        blank = run(lambda _name: "   ")

        def boom(_name):
            raise RuntimeError("boom " + SECRET)

        failed = run(boom)
        for decision in (missing, blank, failed):
            self.assertEqual(decision["tier"], "mid", decision)
            self.assertEqual(decision["reasons"], ["typesafe_unavailable"], decision)
            self.assertNotIn(SECRET, json.dumps(decision))
        self.assertNotIn(SECRET, out.getvalue() + err.getvalue())

    def test_key_is_read_the_way_the_store_reads_it(self):
        fake = types.ModuleType("secrets_store")
        seen = []

        def get_secret(name):
            seen.append(name)
            return "  " + SECRET + "  "

        fake.get_secret = get_secret
        captured = []

        def post(body, key):
            captured.append(key)
            return _answers("mid", 0.8, 0.1)

        with mock.patch.dict(sys.modules, {"secrets_store": fake}):
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                decision = model_router.route(LONG, "brief", post=post)
        self.assertEqual(seen, [ts.KEY_NAME])
        self.assertEqual(captured, [SECRET])
        self.assertEqual(decision["tier"], "mid")
        self.assertNotIn(SECRET, json.dumps(decision))
        self.assertNotIn(SECRET, out.getvalue() + err.getvalue())

    def test_real_post_uses_the_endpoint_and_hides_the_key(self):
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return _answers("cheap", 0.2, 0.9)

        class FakeRequests:
            def post(self, url, json=None, headers=None, timeout=None):
                calls.append((url, json, headers, timeout))
                return FakeResponse()

        with mock.patch.dict(sys.modules, {"requests": FakeRequests()}):
            decision = model_router.route(LONG, "brief", key=SECRET)
        self.assertEqual(len(calls), 1)
        url, body, headers, timeout = calls[0]
        self.assertEqual(url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(timeout, 30)
        self.assertEqual(headers["Authorization"], "Bearer {0}".format(SECRET))
        self.assertNotIn(SECRET, json.dumps(body))
        self.assertEqual(decision["tier"], "heavy")
        self.assertIn("gate:high_stakes", decision["reasons"])

        class Boom:
            def post(self, url, json=None, headers=None, timeout=None):
                raise RuntimeError("status 500 " + headers["Authorization"])

        out, err = StringIO(), StringIO()
        with mock.patch.dict(sys.modules, {"requests": Boom()}):
            with redirect_stdout(out), redirect_stderr(err):
                failed = model_router.route(LONG, "brief", key=SECRET)
        self.assertEqual(failed["reasons"], ["typesafe_unavailable"])
        self.assertNotIn(SECRET, json.dumps(failed))
        self.assertNotIn(SECRET, out.getvalue() + err.getvalue())

    def test_a_replacement_config_supplies_the_model_id(self):
        path = self._write_config({
            "cheap": ["cheap-model-a", "cheap-model-b"],
            "mid": "mid-model",
            "heavy": ["heavy-model"],
        })
        decision = model_router.route("n" * 10, "brief", config_path=path)
        self.assertEqual(decision["model"], "cheap-model-a")
        broken = model_router.route("n" * 10, "brief", config_path=path + ".missing")
        self.assertEqual(broken["tier"], "cheap")
        self.assertEqual(broken["model"], "")
        self.assertIn("config_unavailable", broken["reasons"])

    def _route(self, choice, confidence, stakes, tools=0.1):
        return model_router.route(
            LONG, "brief",
            post=_post_returning(_answers(choice, confidence, stakes, tools=tools)),
            key=SECRET,
        )

    def _write_config(self, data):
        folder = self._tmp()
        path = os.path.join(folder, "models.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return path

    def _tmp(self):
        import tempfile
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        return held.name


if __name__ == "__main__":
    unittest.main()
