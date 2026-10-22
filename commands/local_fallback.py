"""Offline fallback for plain questions: Apple's on-device `fm serve` (macOS 27).

Used only when the OpenRouter call for a plain question fails with a network
or OpenRouter error. Mac-only. Plain text, no tools, small prompt.

Jev never starts `fm serve` and never opens a socket of its own. It only
connects, as a client, to a server that is already running on localhost.
If nothing is listening, the fallback is skipped.

Never used for money-moving commands or My Love.
"""
import os
import sys

# Override with JEV_FM_URL if `fm serve` listens elsewhere. Localhost only.
DEFAULT_FM_URL = "http://127.0.0.1:8080/v1"
FM_TIMEOUT = 20
FM_MAX_TOKENS = 200
# Short context on the on-device model: keep the prompt small.
FM_MAX_PROMPT_CHARS = 2000

BLOCKED_WORDS = (
    "my love", "pay ", "pay my", "payment", "transfer", "send money", "venmo", "zelle",
    "cash app", "paypal", "wire ", "deposit", "withdraw", "buy ", "purchase", "bank",
    "credit card", "affirm", "fidelity", "e*trade", "etrade", "spark card",
)


def fm_url():
    url = os.environ.get("JEV_FM_URL", DEFAULT_FM_URL).rstrip("/")
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if host not in ("127.0.0.1", "localhost", "::1", "[::1]"):
        return None
    return url


def allowed(text, platform=None):
    """True only on a Mac and only for text with no money or My Love words."""
    if (platform or sys.platform) != "darwin":
        return False
    low = f" {(text or '').lower()} "
    return not any(w in low for w in BLOCKED_WORDS)


def is_network_failure(exc):
    """Network trouble or an OpenRouter-side error (5xx, 429, auth/credit 401/402)."""
    names = {c.__name__ for c in type(exc).__mro__}
    if names & {"ConnectionError", "Timeout", "ConnectTimeout", "ReadTimeout", "TimeoutError"}:
        return True
    if "HTTPError" in names:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        return code is None or code >= 500 or code in (401, 402, 408, 429)
    return False


def fm_body(messages):
    """Plain chat body: no tools, no reasoning, trimmed prompt."""
    trimmed = []
    for m in messages:
        content = str(m.get("content") or "")[:FM_MAX_PROMPT_CHARS]
        trimmed.append({"role": m["role"], "content": content})
    return {"messages": trimmed, "max_tokens": FM_MAX_TOKENS, "stream": False}


def ask_fm(messages, post=None):
    """Answer text from a running local fm server, or None. Never raises."""
    url = fm_url()
    if not url:
        return None
    try:
        if post is None:
            import requests

            def post(u, body):
                r = requests.post(u, json=body, timeout=FM_TIMEOUT)
                r.raise_for_status()
                return r.json()
        data = post(f"{url}/chat/completions", fm_body(messages))
        text = (data["choices"][0]["message"].get("content") or "").strip()
        return text or None
    except Exception:
        return None
