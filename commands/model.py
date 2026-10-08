"""The one Claude model id Jev sends.

Settings can replace it. The default is Claude Haiku 5.5, whose Claude API
id is `claude-haiku-5-5`. Questions and Ask Jev still go through OpenRouter
with the existing OpenRouter key. OpenRouter's slug for that model is
`anthropic/claude-haiku-5.5`. Nothing here stores a key.
"""
import re

# Claude API id. Dateless and pinned, per Anthropic's model overview.
CLAUDE_MODEL = "claude-haiku-5-5"
# OpenRouter slug for CLAUDE_MODEL. A Settings value that already contains
# "/" is sent as-is, so a full slug can override this.
OPENROUTER_SLUG = "anthropic/claude-haiku-5.5"
MODEL_PREF = "claude_model"

# List price for a prompt of at most 100,000 tokens. Above that, Haiku 5.5
# charges the long-context rates. Dollars per million tokens.
HAIKU_INPUT_PER_MTOK = 0.10
HAIKU_OUTPUT_PER_MTOK = 0.50
HAIKU_LONG_INPUT_PER_MTOK = 0.50
HAIKU_LONG_OUTPUT_PER_MTOK = 2.50
LONG_PROMPT_TOKENS = 100000

# Haiku 4.5 answered these calls with no thinking budget. Haiku 5.5 thinks
# unless effort is lowered, and thinking tokens count against max_tokens.
# Low effort is the migration guide's lever for a short, latency-sensitive reply.
HAIKU_EFFORT = "low"

# Old ceilings were 40, 120, 80, and 300. The same text is about 30% more
# tokens on this tokenizer, and a thinking block can spend the ceiling
# before any answer text. These leave room for both.
MAX_TOKENS_URL = 256
MAX_TOKENS_REMINDER = 512
MAX_TOKENS_ANSWER = 256
MAX_TOKENS_VISION = 1024

# Haiku 5.5 is a Claude 4.7-and-later model, so images use the high-resolution
# tier: 2576 px on the long edge and 4784 visual tokens. The API downsizes
# anything larger. Ask Jev resizes first so the upload matches that limit.
LONG_EDGE = 2576
MAX_VISUAL_TOKENS = 4784
PATCH = 28

_VERSION = re.compile(r"^(?P<head>.+)-(?P<major>\d+)-(?P<minor>\d+)$")
REFUSAL = "I can't answer that."


def configured_model(saved=None):
    """Claude API id, or whatever Settings stored. Blank keeps Haiku 5.5."""
    text = " ".join(str(saved or "").split())
    return text or CLAUDE_MODEL


def openrouter_model(model_id=None):
    """Slug posted to OpenRouter.

    `claude-haiku-5-5` becomes `anthropic/claude-haiku-5.5`. A value that
    already contains a slash is an OpenRouter slug and is left alone.
    """
    raw = configured_model(model_id)
    if "/" in raw:
        return raw
    match = _VERSION.match(raw)
    if match:
        return "anthropic/{0}-{1}.{2}".format(
            match.group("head"), match.group("major"), match.group("minor"),
        )
    return "anthropic/" + raw


def _read_pref():
    try:
        from Foundation import NSUserDefaults
        return NSUserDefaults.standardUserDefaults().stringForKey_(MODEL_PREF) or ""
    except Exception:
        return ""


def active_model(saved=None, read=None):
    """The id to use now. Pass `saved` in tests so this never touches defaults."""
    if saved is None:
        saved = read() if read is not None else _read_pref()
    return configured_model(saved)


def chat_body(max_tokens, messages, model=None, response_format=None, usage=False):
    """OpenRouter chat-completions body.

    Sampling params are omitted. Haiku 5.5 rejects a non-default temperature,
    top_p, or top_k. Effort is the OpenRouter reasoning field, which it maps
    to Anthropic's output_config.effort.
    """
    body = {
        "model": openrouter_model(model if model is not None else active_model()),
        "max_tokens": int(max_tokens),
        "messages": messages,
        "reasoning": {"effort": HAIKU_EFFORT},
    }
    if response_format:
        body["response_format"] = response_format
    if usage:
        body["usage"] = {"include": True}
    return body


def message_text(payload):
    """Assistant text from a chat-completions payload. Skips thinking blocks."""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text"):
                parts.append(str(block.get("text") or ""))
    return " ".join(part.strip() for part in parts if part and str(part).strip()).strip()


def refused(payload):
    """Haiku 5.5 can decline with stop_reason or finish_reason refusal."""
    if not isinstance(payload, dict):
        return False
    if payload.get("stop_reason") == "refusal":
        return True
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return False
    return choices[0].get("finish_reason") in ("refusal", "content_filter")


def token_cost(input_tokens, output_tokens):
    """Dollars at Haiku 5.5 list price. The long rate starts above 100,000 input tokens."""
    try:
        incoming = float(input_tokens or 0)
        outgoing = float(output_tokens or 0)
    except (TypeError, ValueError):
        return 0.0
    long = incoming > LONG_PROMPT_TOKENS
    in_rate = (HAIKU_LONG_INPUT_PER_MTOK if long else HAIKU_INPUT_PER_MTOK) / 1e6
    out_rate = (HAIKU_LONG_OUTPUT_PER_MTOK if long else HAIKU_OUTPUT_PER_MTOK) / 1e6
    return incoming * in_rate + outgoing * out_rate


def usage_cost(usage):
    """Prefer the API's dollar cost. Otherwise the Haiku 5.5 token rates."""
    usage = usage or {}
    if usage.get("cost") is not None:
        try:
            return float(usage["cost"])
        except (TypeError, ValueError):
            pass
    incoming = usage.get("input_tokens")
    if incoming is None:
        incoming = usage.get("prompt_tokens")
    outgoing = usage.get("output_tokens")
    if outgoing is None:
        outgoing = usage.get("completion_tokens")
    return token_cost(incoming, outgoing)
