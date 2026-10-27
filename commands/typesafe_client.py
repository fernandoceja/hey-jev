"""One TypeSafe call for the model router.

POST https://api.typesafe.ai/v1/systemone with model jev-latest. The state is
only a task excerpt (at most 1000 characters), the command name, and the input
size. Three questions go in that same call: a Choice named tier, and two Noul
questions, needs_tools_or_code and high_stakes.

The key is TYPESAFE_API_KEY from secrets_store.get_secret (Keychain, with .env
as the dev fallback that helper already has). This module never prints or logs
the key, the excerpt, or the response. It opens no socket of its own. Tests
pass post= so they never touch the network.
"""
import re

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
KEY_NAME = "TYPESAFE_API_KEY"
EXCERPT_CHARS = 1000
COMMAND_CHARS = 80
TIMEOUT = 30

_SPACE = re.compile(r"\s+")


class TypeSafeUnavailable(Exception):
    """The call could not be made or the payload was not an object.

    The message stays empty so a key or a response body cannot ride along.
    """


def questions():
    """The three routing questions, evaluated together in one request."""
    return {
        "tier": {
            "type": "choice",
            "instructions": "Which model tier should handle this task?",
            "criteria": {
                "cheap": "Short and low-risk. A small model can do it without tools or code.",
                "mid": "Ordinary work for a standard model. Not the hardest and not the smallest.",
                "heavy": "Long, difficult, or careful work that needs the largest model.",
            },
        },
        "needs_tools_or_code": {
            "type": "noul",
            "instructions": "Does this task need tools or code?",
            "criteria": {
                "true": "It asks for a program, a tool, or code to be written or run.",
                "false": "Reading or writing plain text is enough.",
            },
        },
        "high_stakes": {
            "type": "noul",
            "instructions": "Would a wrong answer be costly or hard to undo?",
            "criteria": {
                "true": "Money, health, safety, legal standing, or a message sent to another person.",
                "false": "A mistake is cheap to ignore or redo.",
            },
        },
    }


def task_text(task):
    """The task as text. Non-text becomes an empty string."""
    if isinstance(task, str):
        return task
    return ""


def command_name(command):
    """A short command name. Extra whitespace is collapsed and the rest is cut."""
    collapsed = _SPACE.sub(" ", str(command or "")).strip()
    return collapsed[:COMMAND_CHARS]


def state_for(task, command):
    """Short state only: excerpt, command name, and the original input size."""
    text = task_text(task)
    return {
        "command": command_name(command),
        "input_chars": len(text),
        "excerpt": text[:EXCERPT_CHARS],
    }


def request_body(task, command):
    return {
        "model": MODEL,
        "state": state_for(task, command),
        "questions": questions(),
    }


def headers(key):
    return {"Authorization": "Bearer {0}".format(key)}


def api_key(read=None):
    """TYPESAFE_API_KEY, or "" when it is missing. Never raises and never prints."""
    try:
        if read is None:
            from secrets_store import get_secret
            found = get_secret(KEY_NAME)
        else:
            found = read(KEY_NAME)
    except Exception:
        return ""
    if found is None:
        return ""
    return str(found).strip()


def _post(body, key, timeout):
    import requests
    response = requests.post(URL, json=body, headers=headers(key), timeout=timeout)
    response.raise_for_status()
    return response.json()


def ask(task, command, post=None, key=None, timeout=TIMEOUT):
    """Run the routing call. `post(body, key)` replaces the HTTP call in tests.

    Raises TypeSafeUnavailable with an empty message when there is no key or
    the call fails. The key is not included in that error.
    """
    secret = api_key() if key is None else str(key).strip()
    if not secret:
        raise TypeSafeUnavailable()
    body = request_body(task, command)
    try:
        payload = (post or _post)(body, secret) if post is not None else _post(body, secret, timeout)
    except TypeSafeUnavailable:
        raise
    except Exception:
        raise TypeSafeUnavailable() from None
    if not isinstance(payload, dict):
        raise TypeSafeUnavailable()
    return payload
