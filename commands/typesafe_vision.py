"""Experimental: answer some screenshot questions with TypeSafe Jev 1.14 images.

Off by default. It is on only when the flag file holds "on". When it is off,
the question doesn't fit, or anything fails, the caller falls back to the
current OpenRouter vision answer.

Jev returns typed answers, not prose, so only two kinds of question go here:
  "where is X"          -> a Box question plus a Noul "is X there" check
  "is there / do you see / is it X" -> a Noul question
Everything else ("what's on screen", "summarize this") stays on the current path.

The key is read from the Keychain through secrets_store. Nothing here stores a
key, opens a socket, or touches the iPhone bridge.
"""
import base64
import os
import re
import time
import uuid

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.14.0"  # Box needs 1.14; jev-latest may still be 1.13.
DANGER_HEADER = "TypeSafe-Danger-Zone-Images"
# "on" turns it on. A missing file means off. No secrets.
FLAG_PATH = os.path.expanduser(
    "~/Library/Application Support/Hey Jev/typesafe-images.txt"
)
MIN_SIDE = 256
MAX_SIDE = 1568
MIN_PIXELS = 78400
MIN_CONFIDENCE = 0.6
PRICE_PER_MTOK = 0.042  # same per-token input price as text

_WHERE = re.compile(r"^\s*(?:where(?:'s| is| are)|find|locate|point to|show me where)\s+(?:the\s+|my\s+|a\s+|an\s+)?(.+?)[\s?.!]*$", re.I)
_YESNO = re.compile(r"^\s*(?:is|are|does|do|did|can|was|were|has|have)\b.+", re.I)


def enabled(path=None, read=None):
    target = path or FLAG_PATH
    try:
        if read is not None:
            text = read(target)
        else:
            with open(target) as handle:
                text = handle.read()
    except Exception:
        return False
    return str(text or "").strip().lower() == "on"


def set_enabled(on, path=None):
    target = path or FLAG_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as handle:
        handle.write("on\n" if on else "off\n")


def classify(question):
    """("box", target) / ("noul", question) / None."""
    q = " ".join(str(question or "").split())
    if not q:
        return None
    m = _WHERE.match(q)
    if m and m.group(1).strip():
        return ("box", m.group(1).strip())
    if _YESNO.match(q):
        return ("noul", q.rstrip(" ?.!") + "?")
    return None


def size_ok(width, height):
    w, h = int(width or 0), int(height or 0)
    return MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE and w * h >= MIN_PIXELS


def fit_command(src, dest):
    """Long edge at most 1568, the API rejects bigger images instead of resizing."""
    return ["sips", "-Z", str(MAX_SIDE), "-s", "format", "jpeg", src, "--out", dest]


def request_body(kind, subject, image_b64, ref=None):
    ref = ref or "jevshot-" + uuid.uuid4().hex
    if kind == "box":
        questions = {
            "present": {"type": "noul", "instructions": "Is {0} visible in `screen`?".format(subject)},
            "where": {"type": "box", "instructions": "{0} in `screen`".format(subject)},
        }
    else:
        questions = {"answer": {"type": "noul", "instructions": "Looking at `screen`: {0}".format(subject)}}
    return {
        "model": MODEL,
        "state": {"screen": ref, "note": "A screenshot of Fernando's Mac."},
        "assets": {ref: {"type": "image", "format": "jpg", "data_base64": image_b64}},
        "questions": questions,
    }


def headers(key):
    return {"Authorization": "Bearer {0}".format(key), DANGER_HEADER: "true"}


def region(box):
    """Plain words for where the box's center sits on screen."""
    x = (float(box["left"]) + float(box["right"])) / 2.0
    y = (float(box["top"]) + float(box["bottom"])) / 2.0
    row = "top" if y < 1 / 3.0 else ("bottom" if y > 2 / 3.0 else "middle")
    col = "left" if x < 1 / 3.0 else ("right" if x > 2 / 3.0 else "center")
    if row == "middle" and col == "center":
        return "the center"
    if row == "middle":
        return "the middle {0}".format(col)
    if col == "center":
        return "the {0} center".format(row)
    return "the {0} {1}".format(row, col)


def _noul(answer):
    p = float(answer["noul"])
    return p >= 0.5, max(p, 1 - p)


def spoken(kind, subject, answers):
    """A sentence, or None when Jev isn't sure enough (caller falls back)."""
    if kind == "box":
        there, conf = _noul(answers["present"])
        if conf < MIN_CONFIDENCE:
            return None
        if not there:
            return "I don't see {0} on that screenshot.".format(subject)
        where = answers["where"]
        if float(where.get("confidence", 0)) < MIN_CONFIDENCE:
            return None
        return "{0} is in {1} of the screenshot.".format(subject[:1].upper() + subject[1:], region(where["box"]))
    yes, conf = _noul(answers["answer"])
    if conf < MIN_CONFIDENCE:
        return None
    return "Yes." if yes else "No."


def cost(payload):
    return int(((payload or {}).get("usage") or {}).get("input_tokens", 0)) * PRICE_PER_MTOK / 1e6


def _key():
    try:
        from secrets_store import get_secret
        return get_secret("TYPESAFE_API_KEY") or ""
    except Exception:
        return ""


def _post(body, key, timeout=30):
    import requests
    r = requests.post(URL, json=body, headers=headers(key), timeout=timeout)
    r.raise_for_status()
    return r.json()


def try_answer(question, image_path, run, read, post=None, key=None, flag=None):
    """The TypeSafe answer, or None to use the current path. Never raises."""
    try:
        on = enabled() if flag is None else bool(flag)
        if not on:
            return None
        plan = classify(question)
        if not plan:
            return None
        secret = _key() if key is None else key
        if not secret:
            return None
        from .vision import dimension_command, parse_pixel_size
        dest = os.path.splitext(image_path)[0] + "-ts.jpg"
        run(fit_command(image_path, dest))
        found = parse_pixel_size(run(dimension_command(dest)))
        if not found or not size_ok(*found):
            return None
        raw = read(dest)
        body = request_body(plan[0], plan[1], base64.b64encode(raw).decode("ascii"))
        started = time.time()
        payload = (post or _post)(body, secret)
        print("  jev {0} {1}ms  ${2:.6f}".format(MODEL, int((time.time() - started) * 1000), cost(payload)))
        return spoken(plan[0], plan[1], payload["answers"])
    except Exception as exc:
        print("  typesafe image ask fell back: {0}".format(exc))
        return None
