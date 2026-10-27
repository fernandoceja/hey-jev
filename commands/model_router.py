"""Pick a model tier for a brief or a triage-style command.

Nothing in the app calls this yet. It only returns a decision. It does not
run the task, speak, open a listening socket, or touch the iPhone bridge.

The decision is a dict: tier, model (the id from model_tiers.json), reasons,
and usage (input_tokens and output_tokens). Gates, applied in code after one
TypeSafe answer:

- heavy, or high_stakes >= 0.6, routes to heavy.
- A tier confidence below 0.55 moves the tier up one step.
- cheap is kept only when high_stakes < 0.3.
- A manual tier override wins, and the call is skipped.
- Inputs under 300 characters skip the call and stay cheap.
- If TypeSafe is unavailable, the tier is mid.

needs_tools_or_code is asked in the same call and recorded. It does not move
the tier. Model ids are not written in this file.
"""
import json
import os

from .typesafe_client import ask, task_text

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_tiers.json")
TIERS = ("cheap", "mid", "heavy")
SHORT_INPUT_CHARS = 300
HEAVY_STAKES = 0.6
CHEAP_STAKES = 0.3
TIER_CONFIDENCE = 0.55
FALLBACK_TIER = "mid"
_NO_USAGE = {"input_tokens": 0, "output_tokens": 0}


def load_models(path=None):
    """Map each tier to the first model id listed for it. Raises if the file is unusable."""
    target = path or CONFIG_PATH
    with open(target, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("model config")
    return {tier: _model_id(data.get(tier)) for tier in TIERS}


def _model_id(value):
    if isinstance(value, list):
        if not value:
            raise ValueError("model config")
        value = value[0]
    if not isinstance(value, str):
        raise ValueError("model config")
    text = value.strip()
    if not text or any(char.isspace() for char in text):
        raise ValueError("model config")
    return text


def _fmt(value):
    return "{0:.4f}".format(float(value))


def _usage(payload):
    raw = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return dict(_NO_USAGE)

    def num(name):
        try:
            return max(0, int(raw.get(name) or 0))
        except (TypeError, ValueError):
            return 0

    return {"input_tokens": num("input_tokens"), "output_tokens": num("output_tokens")}


def _unit(value):
    """A probability in 0..1, or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 1:
        return None
    return number


def _override(value):
    if value is None:
        return None
    text = " ".join(str(value).split()).lower()
    if text in TIERS:
        return text
    return None


def _bump(tier):
    index = TIERS.index(tier)
    return TIERS[min(index + 1, len(TIERS) - 1)]


def parse_answers(payload):
    """(choice, confidence, needs_tools_or_code, high_stakes) or None."""
    if not isinstance(payload, dict):
        return None
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return None
    tier_answer = answers.get("tier")
    tools_answer = answers.get("needs_tools_or_code")
    stakes_answer = answers.get("high_stakes")
    if not isinstance(tier_answer, dict) or tier_answer.get("type") != "choice":
        return None
    choice = tier_answer.get("choice")
    if choice not in TIERS:
        return None
    confidence = _unit(tier_answer.get("confidence"))
    if not isinstance(tools_answer, dict) or tools_answer.get("type") != "noul":
        return None
    if not isinstance(stakes_answer, dict) or stakes_answer.get("type") != "noul":
        return None
    tools = _unit(tools_answer.get("noul"))
    stakes = _unit(stakes_answer.get("noul"))
    if confidence is None or tools is None or stakes is None:
        return None
    return choice, confidence, tools, stakes


def apply_gates(choice, confidence, high_stakes):
    """Return (tier, gate reasons) from one parsed answer. Order matches the gates."""
    reasons = []
    tier = choice
    if choice == "heavy":
        reasons.append("gate:heavy")
        tier = "heavy"
    if high_stakes >= HEAVY_STAKES:
        reasons.append("gate:high_stakes")
        tier = "heavy"
    if confidence < TIER_CONFIDENCE:
        bumped = _bump(tier)
        if bumped != tier:
            reasons.append("gate:low_confidence")
        tier = bumped
    if tier == "cheap" and not high_stakes < CHEAP_STAKES:
        reasons.append("gate:cheap_blocked")
        tier = "mid"
    return tier, reasons


def _decision(tier, reasons, usage, config_path):
    try:
        model = load_models(config_path)[tier]
    except Exception:
        model = ""
        reasons = list(reasons) + ["config_unavailable"]
    return {
        "tier": tier,
        "model": model,
        "reasons": list(reasons),
        "usage": {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
        },
    }


def _fallback(usage, config_path):
    return _decision(FALLBACK_TIER, ["typesafe_unavailable"], usage, config_path)


def route(task, command, override=None, post=None, key=None, config_path=None):
    """Decide a tier. Never raises. Does not call a model to do the task.

    `post(body, key)` mocks the TypeSafe HTTP call. `key` skips the Keychain
    in tests. `override` is cheap, mid, or heavy and wins over every gate.
    """
    text = task_text(task)
    chosen = _override(override)
    if chosen:
        return _decision(chosen, ["override"], _NO_USAGE, config_path)
    if len(text) < SHORT_INPUT_CHARS:
        return _decision("cheap", ["short_input"], _NO_USAGE, config_path)
    try:
        payload = ask(text, command, post=post, key=key)
    except Exception:
        return _fallback(_NO_USAGE, config_path)
    parsed = parse_answers(payload)
    if parsed is None:
        return _fallback(_usage(payload), config_path)
    choice, confidence, tools, stakes = parsed
    tier, gates = apply_gates(choice, confidence, stakes)
    reasons = [
        "choice:{0}".format(choice),
        "confidence:{0}".format(_fmt(confidence)),
        "needs_tools_or_code:{0}".format(_fmt(tools)),
        "high_stakes:{0}".format(_fmt(stakes)),
    ] + gates
    return _decision(tier, reasons, _usage(payload), config_path)
