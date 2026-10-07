"""Ask Jev about one capture, using the Claude model already configured.

The call goes to OpenRouter's Anthropic Messages endpoint with the existing
OpenRouter key and the model id from commands.model. Nothing here stores a
new key. The image is sent only when this function runs. Other handoffs do
not call it.
"""
import base64
import math
import os
import time

from .model import (
    HAIKU_EFFORT,
    LONG_EDGE,
    MAX_TOKENS_VISION,
    MAX_VISUAL_TOKENS,
    PATCH,
    REFUSAL,
    active_model,
    openrouter_model,
    refused,
    usage_cost,
)

MESSAGES_URL = "https://openrouter.ai/api/v1/messages"
# Bytes checked before the request. The migration guide did not raise this cap.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
DEFAULT_QUESTION = "Describe what's on screen"
_MOVIE = (".mov", ".mp4", ".m4v")


def vision_question(text):
    cleaned = " ".join(str(text or "").split())
    return cleaned or DEFAULT_QUESTION


def visual_tokens(width, height):
    return int(math.ceil(width / float(PATCH)) * math.ceil(height / float(PATCH)))


def fitted_size(width, height, long_edge=LONG_EDGE, max_tokens=MAX_VISUAL_TOKENS):
    """The size Haiku 5.5 keeps before it pads to a multiple of 28.

    High-resolution tier: neither side's padded edge past 2576, and at most
    4784 visual tokens. A picture that already fits is unchanged.
    """
    w = max(0, int(width))
    h = max(0, int(height))

    def fits(aw, ah):
        return (
            math.ceil(aw / float(PATCH)) * PATCH <= long_edge
            and math.ceil(ah / float(PATCH)) * PATCH <= long_edge
            and visual_tokens(aw, ah) <= max_tokens
        )

    if w <= 0 or h <= 0 or fits(w, h):
        return w, h
    if h > w:
        tall, wide = fitted_size(h, w, long_edge, max_tokens)
        return wide, tall
    ratio = float(w) / float(h)
    lo, hi = 1, w
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if fits(mid, max(int(round(mid / ratio)), 1)):
            lo = mid
        else:
            hi = mid
    return lo, max(int(round(lo / ratio)), 1)


def sips_commands(src, dest, width=None, height=None, qualities=(80, 60, 40)):
    """JPEG exports. An exact size uses -z. Otherwise the long edge is capped."""
    commands = []
    for quality in qualities:
        if width and height:
            resize = ["-z", str(int(height)), str(int(width))]
        else:
            resize = ["-Z", str(LONG_EDGE)]
        commands.append(
            ["sips"] + resize + [
                "-s", "format", "jpeg",
                "-s", "formatOptions", str(int(quality)),
                src, "--out", dest,
            ]
        )
    return commands


def is_movie(path):
    return os.path.splitext(str(path or ""))[1].lower() in _MOVIE


def offer_ask_jev(path, ffmpeg_present):
    """Screenshots always. A recording only when ffmpeg can lift one frame."""
    if not path:
        return False
    if is_movie(path):
        return bool(ffmpeg_present)
    return True


def duration_command(ffprobe, path):
    return [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", path,
    ]


def middle_second(duration_text):
    try:
        seconds = float(str(duration_text or "").strip())
    except ValueError:
        return 0.0
    if seconds <= 0:
        return 0.0
    return seconds / 2.0


def frame_command(ffmpeg, src, dest, at_seconds):
    return [
        ffmpeg, "-y", "-ss", "{0:.3f}".format(max(0.0, float(at_seconds))),
        "-i", src, "-frames:v", "1", dest,
    ]


def media_type_for(path):
    if os.path.splitext(str(path or ""))[1].lower() == ".png":
        return "image/png"
    return "image/jpeg"


def vision_body(model, question, image_b64, media_type):
    """Anthropic Messages body. No sampling params, tools, or auto-submit.

    Effort is low so a screen description does not spend max_tokens on thinking.
    The model id is the OpenRouter slug for whatever Settings selected.
    """
    return {
        "model": openrouter_model(model if model is not None else active_model()),
        "max_tokens": MAX_TOKENS_VISION,
        "output_config": {"effort": HAIKU_EFFORT},
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type or "image/jpeg",
                        "data": image_b64,
                    },
                },
                {"type": "text", "text": vision_question(question)},
            ],
        }],
    }


def vision_cost(usage):
    """Dollars. Prefer the API's cost. Otherwise Haiku 5.5 list price."""
    return usage_cost(usage)


def cost_log_line(model, ms, cost):
    """A line the Home 'Spent on Jev' parser already sums (prefix '  jev ', ends with $)."""
    shown = model or openrouter_model()
    return "  jev {0} {1}ms  ${2:.6f}".format(shown, int(ms), float(cost))


def parse_messages_response(payload):
    """Answer text. A leading thinking block is skipped. A refusal is empty."""
    payload = payload or {}
    if refused(payload):
        return ""
    content = payload.get("content")
    if isinstance(content, str):
        return content.strip()
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
    if not parts:
        choices = payload.get("choices") or []
        if choices:
            message = (choices[0] or {}).get("message") or {}
            parts.append(str(message.get("content") or ""))
    return " ".join(part.strip() for part in parts if part and part.strip()).strip()


def parse_pixel_size(text):
    """pixelWidth and pixelHeight from `sips -g`, or None."""
    width = height = None
    for line in str(text or "").splitlines():
        if "pixelWidth" in line:
            width = _last_int(line)
        elif "pixelHeight" in line:
            height = _last_int(line)
    if width and height:
        return width, height
    return None


def _last_int(line):
    digits = ""
    for piece in str(line).replace(":", " ").split():
        if piece.isdigit():
            digits = piece
    return int(digits) if digits else None


def dimension_command(path):
    return ["sips", "-g", "pixelWidth", "-g", "pixelHeight", path]


def prepare_image(path, dest, run, stat):
    """Write a JPEG at `dest` that fits the high-resolution tier and the byte cap."""
    runner = run
    size_of = stat or os.path.getsize
    target = None
    try:
        found = parse_pixel_size(runner(dimension_command(path)))
    except Exception:
        found = None
    if found:
        fitted = fitted_size(*found)
        if fitted != found:
            target = fitted
    last = None
    for command in sips_commands(path, dest, *(target or (None, None))):
        try:
            runner(command)
        except Exception as exc:
            last = exc
            continue
        try:
            size = int(size_of(dest))
        except Exception:
            size = MAX_IMAGE_BYTES + 1
        if size <= MAX_IMAGE_BYTES:
            return dest
    if last is not None:
        raise last
    raise RuntimeError("image is still over the size limit")


def _openrouter_key(key):
    if key is not None:
        return str(key)
    try:
        from secrets_store import get_secret
        return get_secret("OPENROUTER_API_KEY") or ""
    except Exception:
        return ""


def _post_messages(body, key, timeout=45):
    import requests
    response = requests.post(
        MESSAGES_URL,
        headers={
            "Authorization": "Bearer {0}".format(key),
            "Content-Type": "application/json",
        },
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def ask_about_capture(path, question="", post=None, key=None, model=None, prepare=None, read=None):
    """Send one still and a question. `prepare` returns (path, media type).

    A missing key or a failed request is a spoken sentence. The image is not
    sent when the key is missing.
    """
    question = vision_question(question)
    if not path:
        return "Take a screenshot or record the screen first."
    secret = _openrouter_key(key)
    if not secret:
        return "Add your OpenRouter key in Settings before I can look at a picture."
    try:
        if prepare is None:
            raise RuntimeError("no image")
        image_path, media = prepare(path)
        raw = (read or _read_bytes)(image_path)
    except Exception as exc:
        print("  capture ask failed: {0}".format(exc))
        return "I couldn't read that capture."
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return "That picture is too large to send."
    body = vision_body(model, question, base64.b64encode(raw).decode("ascii"), media)
    poster = post or _post_messages
    started = time.time()
    try:
        payload = poster(body, secret)
    except Exception as exc:
        print("  capture ask failed: {0}".format(exc))
        return "I couldn't ask about that picture. Check the network and try again."
    if refused(payload):
        print(cost_log_line(body["model"], int((time.time() - started) * 1000), vision_cost(
            payload.get("usage") if isinstance(payload, dict) else {})))
        return REFUSAL
    answer = parse_messages_response(payload) or "I couldn't read an answer."
    usage = payload.get("usage") if isinstance(payload, dict) else {}
    elapsed = int((time.time() - started) * 1000)
    print(cost_log_line(body["model"], elapsed, vision_cost(usage)))
    return answer
