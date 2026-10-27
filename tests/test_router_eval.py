"""Offline golden eval for the model router. No live TypeSafe call."""
import os
import pathlib
import sys
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from commands.model import HAIKU_INPUT_PER_MTOK, HAIKU_OUTPUT_PER_MTOK
from commands.router_eval import (
    OUTPUT_TOKENS,
    UNDER_ROUTING_LIMIT,
    build_parser,
    evaluate,
    load_golden,
    main,
    render,
    score,
    within_under_routing_limit,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
BANNED = (
    "@",
    "$",
    "fernando",
    "zoe",
    "brea",
    "gmail",
    "icloud",
    "password",
    "secret",
    "dollar",
    "http",
    "api_key",
    "bearer",
)


def _row(ident, hard, routed, expected="heavy", chars=400, in_tok=0, out_tok=0):
    return {
        "id": ident,
        "kind": "fixture",
        "hard": hard,
        "expected": expected,
        "routed": routed,
        "input_chars": chars,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
    }


class RouterEvalTests(unittest.TestCase):
    def test_golden_set_is_synthetic_and_covers_the_gates(self):
        tasks = load_golden()
        self.assertEqual(len(tasks), 50)
        self.assertEqual({task["command"] for task in tasks}, {"brief", "triage"})
        hard = [task for task in tasks if task["hard"]]
        self.assertGreaterEqual(len(hard), 20)
        self.assertGreaterEqual(sum(1 for task in tasks if task["kind"] == "short"), 8)
        self.assertGreaterEqual(sum(1 for task in tasks if task["kind"] == "borderline"), 8)
        for task in tasks:
            text = task["task"]
            low = text.lower()
            for word in BANNED:
                self.assertNotIn(word, low, task["id"])
            self.assertFalse(any(char.isdigit() for char in text), task["id"])
            if task["kind"] == "short":
                self.assertLess(len(text), 300, task["id"])
                self.assertEqual(task["expected"], "cheap")
                self.assertFalse(task["hard"])
            else:
                self.assertGreaterEqual(len(text), 300, task["id"])
            if task["hard"]:
                self.assertNotEqual(task["expected"], "cheap")
        by_id = {task["id"]: task for task in tasks}
        self.assertEqual(len(by_id["g05"]["task"]), 299)
        self.assertEqual(by_id["g05"]["recorded"]["choice"], "heavy")
        self.assertEqual(len(by_id["g09"]["task"]), 300)
        self.assertIn("BLUEBLOCKMARKER", by_id["g10"]["task"])

    def test_offline_eval_stays_under_the_under_routing_limit(self):
        """CI runs this path. Under-routing of 5% or more fails."""
        self.assertEqual(UNDER_ROUTING_LIMIT, 0.05)
        requests = types.ModuleType("requests")

        def post(*_args, **_kwargs):
            raise AssertionError("live call")

        requests.post = post
        out = StringIO()
        with mock.patch.dict(sys.modules, {"requests": requests}):
            with redirect_stdout(out):
                code = main([])
            report = evaluate()
        self.assertEqual(code, 0)
        self.assertFalse(report["live"])
        self.assertEqual(report["count"], 50)
        self.assertEqual(report["agreement"], 1)
        self.assertEqual(report["mismatches"], [])
        self.assertLess(report["under_routing"], 0.05)
        self.assertTrue(within_under_routing_limit(report))
        self.assertEqual(report["under_routed"], 0)
        self.assertEqual(report["over_routing"], 0)
        self.assertGreaterEqual(report["hard"], 20)
        for tier, row in report["tiers"].items():
            self.assertGreater(row["tasks"], 0, tier)
            self.assertGreater(row["est_input_tokens"], 0, tier)
            self.assertGreater(row["est_usd"], 0, tier)
        rendered = out.getvalue()
        self.assertIn("offline", rendered)
        self.assertIn("under-routing", rendered)
        self.assertIn("over-routing", rendered)
        self.assertNotIn("BLUEBLOCKMARKER", rendered)
        self.assertNotIn("recorded-eval", rendered)
        rows = {row["id"]: row for row in report["rows"]}
        self.assertEqual(rows["g05"]["routed"], "cheap")
        self.assertEqual(rows["g05"]["usage"]["input_tokens"], 0)
        self.assertEqual(rows["g09"]["routed"], "heavy")
        self.assertGreater(rows["g09"]["usage"]["input_tokens"], 0)
        self.assertEqual(rows["g48"]["routed"], "mid")
        self.assertEqual(rows["g48"]["usage"]["input_tokens"], 0)
        self.assertEqual(rows["g49"]["routed"], "mid")
        workflow = open(os.path.join(ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8").read()
        self.assertNotIn("--live", workflow)

    def test_five_percent_under_routing_fails_and_cost_uses_the_haiku_rate(self):
        rows = [_row(str(i), True, "cheap" if i == 0 else "heavy") for i in range(20)]
        report = score(rows)
        self.assertEqual(report["under_routed"], 1)
        self.assertEqual(report["hard"], 20)
        self.assertEqual(report["under_routing"], 0.05)
        self.assertFalse(within_under_routing_limit(report))
        clean = score([_row(str(i), True, "heavy") for i in range(20)])
        self.assertEqual(clean["under_routing"], 0)
        self.assertTrue(within_under_routing_limit(clean))
        over = score([_row("a", False, "heavy", expected="cheap")])
        self.assertEqual(over["over_routing"], 1)
        self.assertEqual(over["agreement"], 0)
        self.assertEqual(over["under_routed"], 0)
        cheap = score([_row("c", False, "cheap", expected="cheap", chars=400, in_tok=3, out_tok=4)])
        bucket = cheap["tiers"]["cheap"]
        self.assertEqual(bucket["est_input_tokens"], 100)
        self.assertEqual(bucket["est_output_tokens"], OUTPUT_TOKENS["cheap"])
        self.assertEqual(bucket["router_input_tokens"], 3)
        self.assertEqual(bucket["router_output_tokens"], 4)
        expected = (100 * HAIKU_INPUT_PER_MTOK + OUTPUT_TOKENS["cheap"] * HAIKU_OUTPUT_PER_MTOK) / 1e6
        self.assertAlmostEqual(bucket["est_usd"], expected)
        self.assertEqual(cheap["tiers"]["mid"]["tasks"], 0)
        self.assertEqual(cheap["tiers"]["heavy"]["tasks"], 0)

    def test_live_flag_skips_recorded_answers_and_is_not_the_default(self):
        self.assertFalse(build_parser().parse_args([]).live)
        self.assertTrue(build_parser().parse_args(["--live"]).live)
        seen = []

        def fake(task, command, override=None, post=None, key=None, config_path=None):
            seen.append((post, key))
            return {
                "tier": "mid",
                "model": "m",
                "reasons": [],
                "usage": {"input_tokens": 1, "output_tokens": 2},
            }

        tasks = load_golden()[:3]
        live = evaluate(tasks=tasks, live=True, route_fn=fake)
        self.assertTrue(live["live"])
        self.assertTrue(all(post is None and key is None for post, key in seen))
        seen[:] = []
        offline = evaluate(tasks=tasks, live=False, route_fn=fake)
        self.assertFalse(offline["live"])
        self.assertTrue(all(post is not None and key == "recorded-eval" for post, key in seen))

    def test_module_does_not_listen_or_touch_the_bridge(self):
        source = open(os.path.join(ROOT, "commands", "router_eval.py"), encoding="utf-8").read()
        low = source.lower()
        for banned in ("import socket", ".listen(", ".bind(", "twingate", "shell=true", "import requests"):
            self.assertNotIn(banned, low, banned)
        for name in ("commands/bridge.py", "secrets_store.py", "siri.py"):
            text = open(os.path.join(ROOT, name), encoding="utf-8").read()
            self.assertNotIn("router_eval", text, name)
            self.assertNotIn("router_golden", text, name)


if __name__ == "__main__":
    unittest.main()
