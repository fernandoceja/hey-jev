"""Ask Jev about one capture, using the Anthropic model already configured.

The call goes to OpenRouter's Anthropic Messages endpoint with the existing
OpenRouter key and the same model id as ask_llm. Nothing here stores a new
key. The image is sent only when this function runs. Other handoffs do not
call it.
"""
import base64
import os
import time

# Same id as siri.LLM_MODEL. OpenRouter routes it to Anthropic Haiku.
VISION_MODEL = "anthropic/claude-haiku-4.5"
MESSAGES_URL = "https://openrouter.ai/api/v1/messages"
LONG_EDGE = 1568
# Anthropic's image limit. The bytes are checked before the request.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
DEFAULT_QUESTION = "Describe what's on screen"
# List price used only when the API omits usage.cost. Input then output, per token.
_HAIKU_INPUT = 1.0 / 1e6
_HAIKU_OUTPUT = 5.0 / 1e6
_MOVIE = (".mov", ".mp4", ".m4v")


def vision_question(text):
    cleaned = " ".join(str(text or "").split())
    return cleaned or DEFAULT_QUESTION


def fitted_size(width, height, long_edge=LONG_EDGE):
    """Width and height with the long edge at most `long_edge`."""
    w = max(0, int(width))
    h = max(0, int(height))
    long = max(w, h)
    if long <= long_edge or long <= 0:
        return w, h
    scale = float(long_edge) / float(long)
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def sips_commands(src, dest, qualities=(80, 60, 40)):
    """JPEG exports, long edge capped. Later commands are lower quality."""
    commands = []
    for quality in qualities:
        commands.append([
            "sips", "-Z", str(LONG_EDGE),
            "-s", "format", "jpeg",
            "-s", "formatOptions", str(int(quality)),
            src, "--out", dest,
        ])
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
    """Anthropic Messages body. No tool call and no auto-submit flag."""
    return {
        "model": model or VISION_MODEL,
        "max_tokens": 300,
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
    """Dollars. Prefer the API's cost. Otherwise Haiku list price from the token counts."""
    usage = usage or {}
    if usage.get("cost") is not None:
        try:
            return float(usage["cost"])
        except (TypeError, ValueError):
            pass
    try:
        incoming = float(usage.get("input_tokens") or 0)
        outgoing = float(usage.get("output_tokens") or 0)
    except (TypeError, ValueError):
        return 0.0
    return incoming * _HAIKU_INPUT + outgoing * _HAIKU_OUTPUT


def cost_log_line(model, ms, cost):
    """A line the Home 'Spent on Jev' parser already sums (prefix '  jev ', ends with $)."""
    return "  jev {0} {1}ms  ${2:.6f}".format(model or VISION_MODEL, int(ms), float(cost))


def parse_messages_response(payload):
    payload = payload or {}
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


def prepare_image(path, dest, run, stat):
    """Write a JPEG at `dest` whose long edge and byte size fit the API."""
    runner = run
    size_of = stat or os.path.getsize
    last = None
    for command in sips_commands(path, dest):
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
    body = vision_body(model or VISION_MODEL, question, base64.b64encode(raw).decode("ascii"), media)
    poster = post or _post_messages
    started = time.time()
    try:
        payload = poster(body, secret)
    except Exception as exc:
        print("  capture ask failed: {0}".format(exc))
        return "I couldn't ask about that picture. Check the network and try again."
    answer = parse_messages_response(payload) or "I couldn't read an answer."
    usage = payload.get("usage") if isinstance(payload, dict) else {}
    elapsed = int((time.time() - started) * 1000)
    print(cost_log_line(body["model"], elapsed, vision_cost(usage)))
    return answer
