"""Shadow logging for brief and triage. No live TypeSafe call, no task text in the log."""
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock

import commands
from commands import brief as brief_mod
from commands import mail_voice as mv
from commands import router_shadow as shadow
from commands.model import HAIKU_INPUT_PER_MTOK, HAIKU_OUTPUT_PER_MTOK, openrouter_model
from commands.router_eval import OUTPUT_TOKENS, _usd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER = "BLUEBLOCKMARKER"
ACTUAL = "anthropic/claude-haiku-5.5"
ROUTER_MODEL = "anthropic/claude-opus-5.5"


def _decision(tier="heavy", reasons=None, model=ROUTER_MODEL, input_tokens=11, output_tokens=7):
    return {
        "tier": tier,
        "model": model,
        "reasons": reasons if reasons is not None else [
            "choice:heavy",
            "confidence:0.9100",
            "needs_tools_or_code:0.1000",
            "high_stakes:0.2000",
            "gate:heavy",
        ],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = os.path.join(self.tmp.name, "router-shadow.jsonl")
        self.env = {"JEV_ROUTER_SHADOW": "1"}

    def tearDown(self):
        self.tmp.cleanup()

    def _observe(self, task, command="brief", route_fn=None, timeout=5, actual=ACTUAL, environ=None):
        shadow.observe(
            task,
            command,
            actual,
            route_fn=route_fn if route_fn is not None else (lambda _task, _command: _decision()),
            path=self.log_path,
            timeout=timeout,
            environ=self.env if environ is None else environ,
        )

    def _rows(self):
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_flag_defaults_on_and_the_off_switch_is_explicit(self):
        self.assertTrue(shadow.ROUTER_SHADOW_ENABLED)
        self.assertTrue(shadow.shadow_enabled({}))
        self.assertTrue(shadow.shadow_enabled({"JEV_ROUTER_SHADOW": "  "}))
        self.assertTrue(shadow.shadow_enabled({"JEV_ROUTER_SHADOW": "1"}))
        for off in ("0", "false", "no", "off", "OFF"):
            self.assertFalse(shadow.shadow_enabled({"JEV_ROUTER_SHADOW": off}), off)

    def test_brief_and_summary_keep_their_output(self):
        seen = []

        def route_fn(task, command):
            seen.append((command, task))
            return _decision()

        with mock.patch.object(brief_mod, "speak_date", return_value="Date line."), \
                mock.patch.object(brief_mod, "speak_weather", return_value="Clear."), \
                mock.patch.object(brief_mod, "speak_today_schedule", return_value="Clear calendar."), \
                mock.patch.object(brief_mod, "speak_next_shift", return_value="No shift."), \
                mock.patch.object(brief_mod, "speak_due", return_value="Nothing is due."), \
                mock.patch.object(brief_mod, "gmail_brief_line", return_value=None), \
                mock.patch.object(brief_mod, "sweep_reminder_line", return_value=None), \
                mock.patch.object(shadow, "LOG_PATH", self.log_path), \
                mock.patch.object(shadow, "route", side_effect=route_fn):
            with mock.patch.dict(os.environ, {"JEV_ROUTER_SHADOW": "0"}, clear=False):
                quiet = commands.speak_brief()
            self.assertEqual(seen, [])
            with mock.patch.dict(os.environ, {"JEV_ROUTER_SHADOW": "1"}, clear=False):
                logged = commands.speak_brief()
        self.assertEqual(logged, quiet)
        self.assertEqual(logged, "Date line. Clear. Clear calendar. No shift. Nothing is due.")
        self.assertEqual(seen[0][0], "brief")
        self.assertEqual(seen[0][1], logged)

        marker_prompt = "1. From: Box\nSubject: Note\n{0}".format(MARKER)
        calls = []

        def ask(prompt):
            calls.append(prompt)
            return "A short synthetic summary."

        inbox = "1" + mv.RECORD + "Box <box@example.com>" + mv.FIELD + "Note" + mv.FIELD + MARKER
        with mock.patch.object(shadow, "LOG_PATH", self.log_path), \
                mock.patch.object(shadow, "route", side_effect=route_fn), \
                mock.patch.dict(os.environ, {"JEV_ROUTER_SHADOW": "1"}, clear=False):
            spoken = mv.summarize_inbox(runner=lambda argv, timeout=30: inbox, ask=ask)
        self.assertEqual(spoken.text, "You have 1 unread email. A short synthetic summary.")
        self.assertIn(MARKER, calls[0])
        self.assertEqual(seen[-1][0], "triage")
        self.assertIn(MARKER, seen[-1][1])
        raw = open(self.log_path, encoding="utf-8").read()
        self.assertNotIn(MARKER, raw)
        self.assertNotIn("box@example.com", raw)
        self.assertNotIn("Date line", raw)
        row = self._rows()[-1]
        self.assertEqual(row["command"], "triage")
        self.assertEqual(row["actual_model"], openrouter_model())
        self.assertNotEqual(row["actual_model"], row["model"])
        self.assertEqual(row["model"], ROUTER_MODEL)

    def test_log_fields_omit_task_text_and_the_file_is_private(self):
        task = "Synthetic shadow sample {0} with no personal data.".format(MARKER)
        self._observe(task, "brief")
        self.assertEqual(len(self._rows()), 1)
        row = self._rows()[0]
        self.assertEqual(sorted(row), [
            "actual_model",
            "command",
            "confidence",
            "input_size",
            "model",
            "reasons",
            "router_tokens",
            "tier",
            "timestamp",
        ])
        self.assertEqual(row["command"], "brief")
        self.assertEqual(row["input_size"], len(task))
        self.assertEqual(row["tier"], "heavy")
        self.assertEqual(row["model"], ROUTER_MODEL)
        self.assertEqual(row["confidence"], 0.91)
        self.assertEqual(row["router_tokens"], {"input_tokens": 11, "output_tokens": 7})
        self.assertEqual(row["actual_model"], ACTUAL)
        self.assertTrue(row["timestamp"].endswith("Z"))
        raw = open(self.log_path, encoding="utf-8").read()
        self.assertNotIn(MARKER, raw)
        self.assertNotIn(task, raw)
        mode = stat.S_IMODE(os.stat(self.log_path).st_mode)
        self.assertEqual(mode, 0o600)
        directory = stat.S_IMODE(os.stat(os.path.dirname(self.log_path)).st_mode)
        self.assertEqual(directory, 0o700)

    def test_errors_timeouts_and_leaks_write_nothing(self):
        task = "Synthetic shadow sample {0} stays off the log.".format(MARKER)

        def explode(task_text, command):
            raise RuntimeError(task_text)

        self._observe(task, route_fn=explode)
        self.assertFalse(os.path.exists(self.log_path))

        class Hardware(BaseException):
            pass

        def hardware(_task, _command):
            raise Hardware(MARKER)

        self._observe(task, route_fn=hardware)
        self.assertFalse(os.path.exists(self.log_path))

        release = threading.Event()

        def block(_task, _command):
            release.wait(2)
            return _decision(reasons=[MARKER, task])

        started = time.monotonic()
        self._observe(task, route_fn=block, timeout=0.05)
        self.assertLess(time.monotonic() - started, 1.0)
        release.set()
        time.sleep(0.15)
        self.assertFalse(os.path.exists(self.log_path))

        self._observe(task, route_fn=lambda _task, _command: _decision(reasons=["confidence:0.2000", task]))
        self.assertFalse(os.path.exists(self.log_path))
        self._observe("other", command="mail_read")
        self.assertFalse(os.path.exists(self.log_path))
        self._observe(task, route_fn=lambda _task, _command: ["nope"])
        self.assertFalse(os.path.exists(self.log_path))
        self._observe(task, environ={"JEV_ROUTER_SHADOW": "0"})
        self.assertFalse(os.path.exists(self.log_path))

    def test_router_failure_still_returns_the_command_result(self):
        def explode(_task, _command):
            raise RuntimeError(MARKER)

        with mock.patch.object(brief_mod, "speak_date", return_value="Date line."), \
                mock.patch.object(brief_mod, "speak_weather", return_value="Clear."), \
                mock.patch.object(brief_mod, "speak_today_schedule", return_value="Clear calendar."), \
                mock.patch.object(brief_mod, "speak_next_shift", return_value="No shift."), \
                mock.patch.object(brief_mod, "speak_due", return_value="Nothing is due."), \
                mock.patch.object(brief_mod, "gmail_brief_line", return_value=None), \
                mock.patch.object(brief_mod, "sweep_reminder_line", return_value=None), \
                mock.patch.object(shadow, "LOG_PATH", self.log_path), \
                mock.patch.object(shadow, "route", side_effect=explode), \
                mock.patch.dict(os.environ, {"JEV_ROUTER_SHADOW": "1"}, clear=False):
            spoken = commands.speak_brief()
        self.assertEqual(spoken, "Date line. Clear. Clear calendar. No shift. Nothing is due.")
        self.assertFalse(os.path.exists(self.log_path))

        def block(_task, _command):
            time.sleep(0.4)
            return _decision()

        inbox = "1" + mv.RECORD + "Box <box@example.com>" + mv.FIELD + "Note" + mv.FIELD + MARKER
        with mock.patch.object(shadow, "LOG_PATH", self.log_path), \
                mock.patch.object(shadow, "route", side_effect=block), \
                mock.patch.object(shadow, "TIMEOUT", 0.05), \
                mock.patch.dict(os.environ, {"JEV_ROUTER_SHADOW": "1"}, clear=False):
            line = mv.summarize_inbox(runner=lambda argv, timeout=30: inbox, ask=lambda prompt: "Done.")
        self.assertEqual(line.text, "You have 1 unread email. Done.")
        self.assertFalse(os.path.exists(self.log_path))

    def test_summary_reports_mix_overhead_and_savings(self):
        cheap_actual = ACTUAL
        heavy_actual = ROUTER_MODEL
        shadow.observe(
            "n" * 400,
            "brief",
            cheap_actual,
            route_fn=lambda _task, _command: _decision(tier="cheap", model=cheap_actual, reasons=["short_input"]),
            path=self.log_path,
            environ=self.env,
        )
        shadow.observe(
            "n" * 400,
            "triage",
            heavy_actual,
            route_fn=lambda _task, _command: _decision(tier="cheap", model=cheap_actual),
            path=self.log_path,
            environ=self.env,
        )
        shadow.observe(
            "n" * 40,
            "brief",
            "unknown/model",
            route_fn=lambda _task, _command: _decision(tier="mid", model="anthropic/claude-sonnet-5.5", reasons=[]),
            path=self.log_path,
            environ=self.env,
        )
        report = shadow.summarize(self.log_path)
        self.assertEqual(report["lines"], 3)
        self.assertEqual(report["mix"], {"cheap": 2, "mid": 1, "heavy": 0})
        self.assertEqual(report["router_input_tokens"], 33)
        self.assertEqual(report["router_output_tokens"], 21)
        self.assertEqual(report["priced"], 2)
        self.assertEqual(report["unpriced"], 1)
        est_in = (400 + 4 - 1) // 4
        same = _usd("cheap", est_in, OUTPUT_TOKENS["cheap"]) - _usd("cheap", est_in, OUTPUT_TOKENS["cheap"])
        saved = _usd("heavy", est_in, OUTPUT_TOKENS["heavy"]) - _usd("cheap", est_in, OUTPUT_TOKENS["cheap"])
        self.assertEqual(report["estimated_savings_usd"], same + saved)
        self.assertGreater(saved, 0)
        self.assertEqual(HAIKU_INPUT_PER_MTOK, 0.10)
        self.assertEqual(HAIKU_OUTPUT_PER_MTOK, 0.50)
        text = shadow.render(report)
        self.assertNotIn(MARKER, text)
        self.assertIn("tier mix: cheap 2, mid 1, heavy 0", text)
        self.assertIn("router token overhead: input 33, output 21", text)
        self.assertEqual(shadow.main(["--log", self.log_path]), 0)
        missing = os.path.join(self.tmp.name, "missing.jsonl")
        self.assertEqual(shadow.summarize(missing)["lines"], 0)
        self.assertEqual(shadow.main(["--log", missing]), 0)

    def test_offline_path_does_not_post_and_the_log_is_gitignored(self):
        posted = []

        def boom(*_args, **_kwargs):
            posted.append(True)
            raise AssertionError("live post")

        from commands import typesafe_client as ts
        with mock.patch.object(ts, "_post", boom), \
                mock.patch.object(ts, "api_key", return_value=""):
            shadow.observe("n" * 400, "brief", ACTUAL, path=self.log_path, environ=self.env)
        self.assertEqual(posted, [])
        row = self._rows()[0]
        self.assertEqual(row["tier"], "mid")
        self.assertEqual(row["reasons"], ["typesafe_unavailable"])
        self.assertNotIn("n" * 12, open(self.log_path, encoding="utf-8").read())

        gitignore = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
        self.assertIn("logs/", gitignore)
        relative = os.path.relpath(shadow.LOG_PATH, ROOT)
        self.assertEqual(relative, os.path.join("logs", "router-shadow.jsonl"))
        source = open(os.path.join(ROOT, "commands", "router_shadow.py"), encoding="utf-8").read().lower()
        for banned in ("import socket", ".listen(", ".bind(", "twingate", "shell=true", "import requests", "--live"):
            self.assertNotIn(banned, source, banned)
        workflow = open(os.path.join(ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8").read()
        self.assertNotIn("--live", workflow)
        for name in ("commands/bridge.py", "secrets_store.py", "siri.py"):
            text = open(os.path.join(ROOT, name), encoding="utf-8").read()
            self.assertNotIn("router_shadow", text, name)
            self.assertNotIn("router-shadow", text, name)
        for name in ("commands/brief.py", "commands/mail_voice.py"):
            text = open(os.path.join(ROOT, name), encoding="utf-8").read()
            self.assertNotIn("model_router", text, name)
            self.assertNotIn("typesafe_client", text, name)
            self.assertNotIn("model_tiers", text, name)

    def test_summary_parser_has_no_live_switch(self):
        self.assertFalse(hasattr(shadow.build_parser().parse_args([]), "live"))
        with open(os.path.join(self.tmp.name, "bad.jsonl"), "w", encoding="utf-8") as handle:
            handle.write("not json\n")
            handle.write("{0}\n".format(json.dumps({
                "tier": "cheap",
                "router_tokens": {"input_tokens": 3, "output_tokens": 4},
                "input_size": 8,
                "actual_model": ACTUAL,
            })))
        report = shadow.summarize(os.path.join(self.tmp.name, "bad.jsonl"))
        self.assertEqual(report["lines"], 1)
        self.assertEqual(report["router_input_tokens"], 3)
        self.assertEqual(report["router_output_tokens"], 4)


if __name__ == "__main__":
    unittest.main()
