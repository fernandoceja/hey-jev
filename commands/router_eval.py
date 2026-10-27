"""Score the model router on a synthetic golden set.

Offline by default: each task carries a recorded TypeSafe answer, and the
gates run on that answer. Nothing here calls the network unless you pass
--live, which is a manual run and is not for CI.

The report is exact agreement with the label, under-routing (hard tasks that
land on cheap), over-routing (a tier above the label), and an estimated token
cost for the tasks routed to each tier. The fixture has no real notes, names,
or secrets. The TypeSafe key is never printed.
"""
import argparse
import json
import os
import sys

from .model import HAIKU_INPUT_PER_MTOK, HAIKU_OUTPUT_PER_MTOK
from .model_router import TIERS, route

GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "router_golden.json")
UNDER_ROUTING_LIMIT = 0.05
# About four characters to a token. Output allowances are planning figures
# for a short reply, a normal reply, and a long reply.
CHARS_PER_TOKEN = 4
OUTPUT_TOKENS = {"cheap": 120, "mid": 400, "heavy": 1200}
# Dollars per million tokens. Cheap is the Haiku list price from model.py.
# Mid and heavy are planning estimates for this report, not a bill.
RATES = {
    "cheap": (HAIKU_INPUT_PER_MTOK, HAIKU_OUTPUT_PER_MTOK),
    "mid": (3.0, 15.0),
    "heavy": (15.0, 75.0),
}
_RECORDED_KEY = "recorded-eval"
COMMANDS = ("brief", "triage")


def load_golden(path=None):
    """Read the committed fixture. A bad shape raises ValueError."""
    target = path or GOLDEN_PATH
    with open(target, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list) or not data:
        raise ValueError("golden set")
    seen = set()
    for task in data:
        if not isinstance(task, dict):
            raise ValueError("golden set")
        ident = task.get("id")
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError("golden set")
        seen.add(ident)
        if task.get("command") not in COMMANDS:
            raise ValueError("golden set")
        if task.get("expected") not in TIERS:
            raise ValueError("golden set")
        if not isinstance(task.get("hard"), bool):
            raise ValueError("golden set")
        if not isinstance(task.get("task"), str) or not task["task"]:
            raise ValueError("golden set")
        if task["hard"] and task["expected"] == "cheap":
            raise ValueError("golden set")
    return data


def _payload(recorded):
    return {
        "model": "jev-latest",
        "answers": {
            "tier": {
                "type": "choice",
                "choice": recorded["choice"],
                "confidence": recorded["confidence"],
                "probabilities": {},
            },
            "needs_tools_or_code": {
                "type": "noul",
                "noul": recorded["needs_tools_or_code"],
            },
            "high_stakes": {"type": "noul", "noul": recorded["high_stakes"]},
        },
        "usage": {
            "input_tokens": int(recorded.get("input_tokens") or 0),
            "output_tokens": int(recorded.get("output_tokens") or 0),
        },
    }


def _recorded_post(recorded):
    def post(_body, _key):
        if not isinstance(recorded, dict) or recorded.get("error"):
            raise RuntimeError("recorded answer unavailable")
        return _payload(recorded)
    return post


def decide_all(tasks, live=False, route_fn=None):
    """Run the router on every task. Offline tasks use the recorded answer."""
    choose = route_fn or route
    rows = []
    for task in tasks:
        text = task["task"]
        if live:
            decision = choose(text, task["command"])
        else:
            decision = choose(
                text,
                task["command"],
                post=_recorded_post(task.get("recorded")),
                key=_RECORDED_KEY,
            )
        rows.append({
            "id": task["id"],
            "kind": task.get("kind") or "",
            "hard": bool(task["hard"]),
            "expected": task["expected"],
            "routed": decision["tier"],
            "input_chars": len(text),
            "usage": {
                "input_tokens": int(decision["usage"]["input_tokens"]),
                "output_tokens": int(decision["usage"]["output_tokens"]),
            },
        })
    return rows


def _blank_tier():
    return {
        "tasks": 0,
        "est_input_tokens": 0,
        "est_output_tokens": 0,
        "est_usd": 0.0,
        "router_input_tokens": 0,
        "router_output_tokens": 0,
    }


def _usd(tier, input_tokens, output_tokens):
    in_rate, out_rate = RATES[tier]
    return (input_tokens * in_rate + output_tokens * out_rate) / 1e6


def score(rows):
    """Agreement, under-routing, over-routing, and estimated cost per tier.

    Under-routing is hard tasks that were sent to cheap, divided by the
    number of hard tasks. Over-routing is any task sent to a higher tier
    than its label, divided by the number of tasks.
    """
    count = len(rows)
    matched = 0
    hard = 0
    under_routed = 0
    over_routed = 0
    tiers = {tier: _blank_tier() for tier in TIERS}
    mismatches = []
    for row in rows:
        expected = row["expected"]
        routed = row["routed"]
        if expected not in TIERS or routed not in TIERS:
            raise ValueError("tier")
        if routed == expected:
            matched += 1
        else:
            mismatches.append({
                "id": row["id"],
                "expected": expected,
                "routed": routed,
                "hard": bool(row["hard"]),
            })
        if row["hard"]:
            hard += 1
            if routed == "cheap":
                under_routed += 1
        if TIERS.index(routed) > TIERS.index(expected):
            over_routed += 1
        bucket = tiers[routed]
        est_in = (int(row["input_chars"]) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN
        est_out = OUTPUT_TOKENS[routed]
        bucket["tasks"] += 1
        bucket["est_input_tokens"] += est_in
        bucket["est_output_tokens"] += est_out
        bucket["est_usd"] += _usd(routed, est_in, est_out)
        bucket["router_input_tokens"] += int(row["usage"]["input_tokens"])
        bucket["router_output_tokens"] += int(row["usage"]["output_tokens"])
    return {
        "count": count,
        "matched": matched,
        "agreement": (matched / count) if count else 0.0,
        "hard": hard,
        "under_routed": under_routed,
        "under_routing": (under_routed / hard) if hard else 0.0,
        "over_routed": over_routed,
        "over_routing": (over_routed / count) if count else 0.0,
        "tiers": tiers,
        "mismatches": mismatches,
    }


def within_under_routing_limit(report):
    """True when hard tasks sent to cheap stay under the five percent line."""
    return report["under_routing"] < UNDER_ROUTING_LIMIT


def evaluate(path=None, live=False, route_fn=None, tasks=None):
    """Score the golden set. `live` skips the recorded answers and calls TypeSafe."""
    chosen = tasks if tasks is not None else load_golden(path)
    rows = decide_all(chosen, live=live, route_fn=route_fn)
    report = score(rows)
    report["live"] = bool(live)
    report["rows"] = rows
    return report


def render(report):
    """Plain-text report. Task text is left out."""
    lines = [
        "router eval: {0} tasks, {1}".format(
            report["count"], "live" if report.get("live") else "offline",
        ),
        "agreement: {0}/{1} ({2:.3f})".format(
            report["matched"], report["count"], report["agreement"],
        ),
        "under-routing: {0}/{1} hard tasks sent to cheap ({2:.3f}), limit {3:.3f}".format(
            report["under_routed"], report["hard"], report["under_routing"], UNDER_ROUTING_LIMIT,
        ),
        "over-routing: {0}/{1} routed above the label ({2:.3f})".format(
            report["over_routed"], report["count"], report["over_routing"],
        ),
        "tier  tasks  est_input_tokens  est_output_tokens  est_usd  router_input_tokens  router_output_tokens",
    ]
    for tier in TIERS:
        row = report["tiers"][tier]
        lines.append(
            "{0}  {1}  {2}  {3}  {4:.6f}  {5}  {6}".format(
                tier,
                row["tasks"],
                row["est_input_tokens"],
                row["est_output_tokens"],
                row["est_usd"],
                row["router_input_tokens"],
                row["router_output_tokens"],
            )
        )
    lines.append(
        "Estimates use the Haiku list price for cheap and planning rates for mid and heavy. Not a bill."
    )
    if report["mismatches"]:
        lines.append("mismatches:")
        for row in report["mismatches"]:
            lines.append(
                "  {0} expected {1} routed {2}".format(row["id"], row["expected"], row["routed"])
            )
    return "\n".join(lines) + "\n"


def build_parser():
    parser = argparse.ArgumentParser(
        description="Score the model router on the synthetic golden set.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call TypeSafe for real. Manual only. CI stays offline.",
    )
    parser.add_argument("--golden", default=GOLDEN_PATH, help="Path to the golden set.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    report = evaluate(path=args.golden, live=args.live)
    sys.stdout.write(render(report))
    if not within_under_routing_limit(report):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
