"""Record model-router decisions without changing the command.

The morning brief and the mail summary (logged as triage) call
observe_command. The flag JEV_ROUTER_SHADOW defaults on. 0, false, no, or
off skips the record. A router error or a timeout leaves the command's
reply and model alone.

Lines are JSON on logs/router-shadow.jsonl. Each line has a timestamp, the
command, the input size, the tier, the router model id, confidence, reasons,
router token counts, and the model that actually ran. Task text stays out of
the file. The summary command reads that file and prints the tier mix, router
token overhead, and estimated savings against the model that ran.

This module opens no socket and does not touch the iPhone bridge or the
Keychain. It never prints a key or the task text.
"""
import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone

from .config import ROUTER_SHADOW_ENABLED
from .model_router import TIERS, route
from .router_eval import CHARS_PER_TOKEN, COMMANDS, OUTPUT_TOKENS, RATES, _usd
from .typesafe_client import task_text

ENV = "JEV_ROUTER_SHADOW"
_OFF = ("0", "false", "no", "off")
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs",
    "router-shadow.jsonl",
)
TIMEOUT = 5
_MIN_TASK = 12
_write_lock = threading.Lock()


def shadow_enabled(environ=None):
    """True unless the env flag is an explicit off value. Blank stays on."""
    env = os.environ if environ is None else environ
    try:
        raw = env.get(ENV)
    except AttributeError:
        raw = None
    if raw is None or not str(raw).strip():
        return bool(ROUTER_SHADOW_ENABLED)
    return str(raw).strip().lower() not in _OFF


def observe_command(task, command, actual_model=None, route_fn=None, path=None, timeout=None, environ=None):
    """Shadow hook for a finished command. Never changes the reply. Swallows router failures."""
    try:
        if command not in COMMANDS or not shadow_enabled(environ):
            return
        if actual_model is None:
            from .model import openrouter_model
            actual_model = openrouter_model()
        observe(
            task,
            command,
            actual_model,
            route_fn=route_fn,
            path=path,
            timeout=TIMEOUT if timeout is None else timeout,
            environ=environ,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return


def observe(task, command, actual_model, route_fn=None, path=None, timeout=None, environ=None):
    """Ask the router and append one log line. Never raises, except interrupt and exit."""
    try:
        _observe(
            task,
            command,
            actual_model,
            route_fn,
            path,
            TIMEOUT if timeout is None else timeout,
            environ,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return


def _observe(task, command, actual_model, route_fn, path, timeout, environ):
    if command not in COMMANDS:
        return
    if not shadow_enabled(environ):
        return
    text = task_text(task)
    box = {}

    def worker():
        try:
            choose = route_fn or route
            box["decision"] = choose(text, command)
        except (KeyboardInterrupt, SystemExit) as exc:
            box["fatal"] = exc
        except BaseException:
            return

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout if timeout is not None else TIMEOUT)
    fatal = box.get("fatal")
    if fatal is not None:
        raise fatal
    if thread.is_alive():
        return
    _write_decision(path or LOG_PATH, text, command, actual_model, box.get("decision"))


def _confidence(reasons):
    if not isinstance(reasons, list):
        return None
    for item in reasons:
        if isinstance(item, str) and item.startswith("confidence:"):
            try:
                value = float(item.split(":", 1)[1])
            except ValueError:
                return None
            if value < 0 or value > 1:
                return None
            return value
    return None


def _tokens(usage):
    raw = usage if isinstance(usage, dict) else {}

    def num(name):
        try:
            return max(0, int(raw.get(name) or 0))
        except (TypeError, ValueError):
            return 0

    return {"input_tokens": num("input_tokens"), "output_tokens": num("output_tokens")}


def _record(text, command, actual_model, decision):
    if not isinstance(decision, dict):
        return None
    tier = decision.get("tier")
    model = decision.get("model")
    reasons = decision.get("reasons")
    if tier not in TIERS or not isinstance(model, str) or not isinstance(reasons, list):
        return None
    clean_reasons = [item for item in reasons if isinstance(item, str)]
    ran = " ".join(str(actual_model or "").split())
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": command,
        "input_size": len(text),
        "tier": tier,
        "model": model,
        "confidence": _confidence(clean_reasons),
        "reasons": clean_reasons,
        "router_tokens": _tokens(decision.get("usage")),
        "actual_model": ran,
    }


def _embeds_task(payload, text):
    return len(text) >= _MIN_TASK and text in payload


def _write_decision(path, text, command, actual_model, decision):
    record = _record(text, command, actual_model, decision)
    if record is None:
        return
    line = json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
    if _embeds_task(line, text):
        return
    _append(path, line)


def _append(path, line):
    directory = os.path.dirname(path)
    with _write_lock:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.chmod(path, 0o600)
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)


def tier_for_model(model_id, config_path=None):
    """Tier whose id list contains model_id, or None."""
    from .model_router import CONFIG_PATH, load_models
    path = config_path or CONFIG_PATH
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        load_models(path)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    target = " ".join(str(model_id or "").split())
    if not target:
        return None
    for tier in TIERS:
        listed = data.get(tier)
        if isinstance(listed, str):
            listed = [listed]
        if not isinstance(listed, list):
            continue
        for item in listed:
            if isinstance(item, str) and item.strip() == target:
                return tier
    return None


def load_log(path=None):
    """Parsed log rows. A missing file is an empty log. Bad lines are skipped."""
    target = path or LOG_PATH
    if not os.path.isfile(target):
        return []
    rows = []
    with open(target, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _count(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def summarize(path=None, config_path=None):
    """Tier mix, router token overhead, and estimated savings versus the model that ran.

    Savings are the estimated cost of the actual model minus the estimated
    cost of the routed tier. A positive number means the routed tier is the
    cheaper of the two. Rows whose model id is not in the tier file are left
    out of the savings sum.
    """
    mix = {tier: 0 for tier in TIERS}
    overhead_in = 0
    overhead_out = 0
    savings = 0.0
    priced = 0
    unpriced = 0
    for row in load_log(path):
        tier = row.get("tier")
        if tier in mix:
            mix[tier] += 1
        tokens = row.get("router_tokens") if isinstance(row.get("router_tokens"), dict) else {}
        overhead_in += _count(tokens.get("input_tokens"))
        overhead_out += _count(tokens.get("output_tokens"))
        actual = tier_for_model(row.get("actual_model"), config_path)
        if tier not in RATES or actual not in RATES:
            unpriced += 1
            continue
        size = _count(row.get("input_size"))
        est_in = (size + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN if size else 0
        routed_cost = _usd(tier, est_in, OUTPUT_TOKENS[tier])
        actual_cost = _usd(actual, est_in, OUTPUT_TOKENS[actual])
        savings += actual_cost - routed_cost
        priced += 1
    return {
        "lines": priced + unpriced,
        "mix": mix,
        "router_input_tokens": overhead_in,
        "router_output_tokens": overhead_out,
        "estimated_savings_usd": savings,
        "priced": priced,
        "unpriced": unpriced,
    }


def render(report):
    """Plain-text summary. Log rows are left out."""
    mix = report["mix"]
    lines = [
        "shadow log: {0} lines".format(report["lines"]),
        "tier mix: cheap {0}, mid {1}, heavy {2}".format(mix["cheap"], mix["mid"], mix["heavy"]),
        "router token overhead: input {0}, output {1}".format(
            report["router_input_tokens"], report["router_output_tokens"],
        ),
        "estimated savings vs actual model: {0:.6f} USD".format(report["estimated_savings_usd"]),
        "priced lines: {0}, unpriced lines: {1}".format(report["priced"], report["unpriced"]),
        "A positive savings figure means the routed tier costs less than the model that ran.",
        "Estimates use the Haiku list price for cheap and planning rates for mid and heavy. Not a bill.",
    ]
    return "\n".join(lines) + "\n"


def build_parser():
    parser = argparse.ArgumentParser(description="Summarize the local model-router shadow log.")
    parser.add_argument("--log", default=LOG_PATH, help="Path to the shadow JSONL log.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    sys.stdout.write(render(summarize(args.log)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
