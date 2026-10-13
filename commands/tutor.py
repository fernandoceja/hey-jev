"""Step-by-step tutor. Mac-only window, local HTML, no listener.

"tutor me on ..." explains the words that follow. "explain this problem"
and a bare "tutor me" use the clipboard. The model reply is strict JSON.
ask_lm posts it through the same OpenRouter chat path as ask_llm. One bad
reply is tried again. A second failure is a spoken status, not a traceback.

The page is written under Application Support/Hey Jev/tutor and loaded with
a file URL in WKWebView. Nothing here accepts a connection.
KaTeX and Three.js are files shipped with the app. The OpenRouter key and
the Fish key stay in the Keychain. Fish speaks each step's say text with
the normal voice. This command is not on the iPhone bridge.
"""
import json
import math
import os
import re
import shutil
import sys
import threading

from .config import _PLEASE, _TAIL
from .textutil import _clean

TUTOR_NOT_MAC = "Tutor runs on this Mac."
TUTOR_NEED_PROBLEM = "Copy a problem, or say tutor me on a topic."
TUTOR_PRIVATE = "That looks private, so I didn't send it."
TUTOR_NEED_KEY = "Add your OpenRouter key in Settings before I can explain that."
TUTOR_FAILED = "I couldn't turn that into steps."
TUTOR_OPENING = "I'll walk through it."

VISUAL_TYPES = ("plot", "projectile", "vector", "none")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TUTOR_MAX_TOKENS = 4096
# Same reference_id siri.py sends as VOICE_ID. Not an API key.
FISH_VOICE_ID = "9a9cf47702da476aa4629e2506d4a857"
PROBLEM_LIMIT = 4000
PAGE_NAME = "lesson.html"

_HEY = r"(?:hey\s+jev\b\s*,?\s+)?"
_TUTOR_RE = re.compile(
    rf"^{_PLEASE}{_HEY}{_PLEASE}tutor\s+me(?:\s+on\b\s*(?P<topic>.*?))?{_TAIL}",
    re.I,
)
_EXPLAIN_RE = re.compile(
    rf"^{_PLEASE}{_HEY}{_PLEASE}explain\s+this\s+problem{_TAIL}",
    re.I,
)
_TOKEN_RE = re.compile(r"\s*(\d+(?:\.\d+)?|[A-Za-z]+|[\+\-\*/\^\(\)])")
_LABEL_RE = re.compile(r"^[A-Za-z0-9 +\-]{0,16}$")
_FUNCS = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sqrt": math.sqrt,
    "abs": abs,
    "ln": math.log,
    "log": math.log10,
    "exp": math.exp,
}
_AUTO = object()
_PRIVATE = object()
_speech_lock = threading.Lock()
_panels = []
_controller_cls = None

SYSTEM_PROMPT = (
    "You are a patient tutor. Return one JSON object and nothing else. "
    "No markdown fences. Required keys: title (string), steps (array), "
    "answer (string), visual (object). Each step has latex (string), "
    "say (string), and optional note (string). visual.type is plot, "
    "projectile, vector, or none. visual.params is an object."
)

_PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Tutor</title>
<link rel="stylesheet" href="katex/katex.min.css">
<script src="katex/katex.min.js"></script>
<script src="three/three.min.js"></script>
<style>
body { margin: 0; background: #f6f4ef; color: #1c1b19;
  font: 17px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { padding: 24px 28px 40px; max-width: 840px; }
h1 { font-size: 26px; line-height: 1.2; margin: 0 0 6px; }
h2 { font-size: 13px; letter-spacing: .04em; text-transform: uppercase;
  color: #6d675e; margin: 22px 0 8px; }
#progress { margin: 0 0 12px; color: #6d675e; }
ol { list-style: none; padding: 0; margin: 0; }
.step { padding: 12px 14px; border-radius: 12px; margin: 0 0 8px; }
.step.current { background: #fff; }
.note { margin: 8px 0 0; color: #5c574e; font-size: 15px; }
#answer, #visual { background: #fff; border-radius: 12px; }
#answer { padding: 8px 12px; min-height: 48px; }
#visual { min-height: 280px; overflow: hidden; }
</style>
</head>
<body>
<main>
<h1 id="title"></h1>
<p id="progress"></p>
<ol id="steps"></ol>
<h2>Answer</h2>
<div id="answer"></div>
<h2>Picture</h2>
<div id="visual"></div>
</main>
<script id="lesson-data" type="application/json">"""

_PAGE_TAIL = """</script>
<script src="plot.js"></script>
</body>
</html>
"""


class LessonError(Exception):
    """A tutor failure the caller can speak. The status is the whole message."""

    def __init__(self, status):
        self.status = status
        super(LessonError, self).__init__(status)


def is_tutor_phrase(text):
    """True for "tutor me on ..." and "explain this problem".

    The topic may contain "and", so routing checks this before the joiner
    split. "explain this problem and mute" does not match.
    """
    return parse_tutor_phrase(text) is not None


def parse_tutor_phrase(text):
    """(topic, use_clipboard) or None.

    An empty topic means the clipboard holds the problem.
    """
    raw = _clean(text).strip()
    if not raw:
        return None
    if _EXPLAIN_RE.match(raw):
        return ("", True)
    match = _TUTOR_RE.match(raw)
    if not match:
        return None
    topic = match.group("topic")
    if topic is None:
        return ("", True)
    cleaned = " ".join(topic.split()).strip(" .,!?;:\"'")
    if not cleaned:
        return ("", True)
    return (cleaned, False)


def tutor_command(field_text, shown_reply=""):
    """Phrase the Tutor Quick Command runs.

    Typed text in the pill becomes "tutor me on ...". An empty field, or a
    field that is only showing the last reply, becomes "explain this problem",
    which reads the clipboard.
    """
    shown = " ".join(str(field_text or "").split()).strip(".,!?;:").strip()
    reply = " ".join(str(shown_reply or "").split()).strip(".,!?;:").strip()
    if not shown or (reply and shown == reply):
        return "explain this problem"
    if parse_tutor_phrase(shown):
        return shown
    return "tutor me on {0}".format(shown)


def build_prompt(problem):
    """The user message sent to ask_lm. The problem is the only live text."""
    body = _plain(problem, PROBLEM_LIMIT)
    return (
        "Explain this problem as strict JSON with keys title, steps, answer, and visual. "
        "steps is an array of objects with latex, say, and optional note. "
        "Use at least two steps. visual is an object with type and params. "
        "type is plot, projectile, vector, or none. "
        "For a function of x, type is plot and params.expression uses x, numbers, "
        "+ - * / ^ parentheses, and sin, cos, tan, sqrt, abs, ln, log, exp. "
        "Include params.x_min and params.x_max. "
        "For a thrown object, type is projectile and params has v0, angle, and g. "
        "For arrows, type is vector and params.vectors is a list of objects with x, y, "
        "and optional z. say is spoken English with no markup. "
        "latex is KaTeX without dollar signs. No markdown.\n\nProblem:\n{0}"
    ).format(body)


def retry_prompt(problem):
    """Second request after the first reply was not valid JSON of that shape."""
    return build_prompt(problem) + (
        "\n\nThe previous reply was not valid JSON of that shape. "
        "Reply again with only the JSON object."
    )


def ask_lm(prompt, post=None, key=None):
    """One OpenRouter chat completion. Same body helper as ask_llm.

    The key is OPENROUTER_API_KEY from the Keychain unless a test passes
    `key`. Returns the assistant text. A missing key or a refused reply
    raises LessonError. This does not log the prompt or the key.
    """
    secret = _openrouter_key(key)
    if not secret:
        raise LessonError(TUTOR_NEED_KEY)
    from .model import chat_body, message_text, refused
    body = chat_body(TUTOR_MAX_TOKENS, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": str(prompt or "")},
    ])
    poster = post or _post_chat
    try:
        payload = poster(body, secret)
    except LessonError:
        raise
    except Exception as exc:
        print("  tutor: {0}".format(type(exc).__name__))
        raise LessonError(TUTOR_FAILED)
    if refused(payload):
        raise LessonError(TUTOR_FAILED)
    text = message_text(payload)
    if not text:
        raise LessonError(TUTOR_FAILED)
    return text


def fetch_lesson(problem, ask=None):
    """Ask once, and once more when the JSON does not match the schema.

    A transport failure is not retried. The second schema failure raises
    LessonError(TUTOR_FAILED).
    """
    caller = ask or ask_lm
    prompts = (build_prompt(problem), retry_prompt(problem))
    for index, prompt in enumerate(prompts):
        try:
            raw = caller(prompt)
        except LessonError:
            raise
        except Exception as exc:
            print("  tutor: {0}".format(type(exc).__name__))
            raise LessonError(TUTOR_FAILED)
        try:
            return validate_lesson(parse_json(raw))
        except LessonError:
            if index == 0:
                print("  tutor: retry")
                continue
            raise LessonError(TUTOR_FAILED)
    raise LessonError(TUTOR_FAILED)


def parse_json(raw):
    """One object from a model reply. Fences and leading words are ignored."""
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LessonError("The tutor reply was not JSON.")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        raise LessonError("The tutor reply was not JSON.")
    if not isinstance(data, dict):
        raise LessonError("The tutor reply was not a JSON object.")
    return data


def validate_lesson(data):
    """The schema {title, steps:[{latex, say, note?}], answer, visual?}."""
    if not isinstance(data, dict):
        raise LessonError("The tutor reply was not a JSON object.")
    title = _bounded(data.get("title"), 160)
    if not title:
        raise LessonError("The tutor reply was missing a title.")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise LessonError("The tutor reply was missing steps.")
    steps = []
    for item in raw_steps[:8]:
        if not isinstance(item, dict):
            raise LessonError("A step was not an object.")
        if "latex" not in item or "say" not in item:
            raise LessonError("A step was missing latex or say.")
        latex = _bounded(item.get("latex"), 1500, allow_empty=True)
        say = _bounded(item.get("say"), 400)
        if latex is None or not say:
            raise LessonError("A step was missing latex or say.")
        step = {"latex": latex, "say": say}
        if "note" in item and item.get("note") not in (None, ""):
            note = _bounded(item.get("note"), 300, allow_empty=True)
            if note is None:
                raise LessonError("A step note was not text.")
            if note:
                step["note"] = note
        steps.append(step)
    if not steps:
        raise LessonError("The tutor reply was missing steps.")
    if "answer" not in data or not isinstance(data.get("answer"), str):
        raise LessonError("The tutor reply was missing an answer.")
    answer = _bounded(data.get("answer"), 500, allow_empty=True)
    if answer is None:
        raise LessonError("The tutor reply was missing an answer.")
    return {
        "title": title,
        "steps": steps,
        "answer": answer,
        "visual": _visual(data.get("visual")),
    }


def map_visual(visual):
    """Numbers the page can draw. Unusable params become type none.

    The expression string is not copied through. A plot is sampled here.
    A projectile is a list of [x, y, z] points. Vectors are numeric.
    """
    if not isinstance(visual, dict):
        return {"type": "none"}
    kind = visual.get("type") or "none"
    params = visual.get("params") if isinstance(visual.get("params"), dict) else {}
    if kind == "plot":
        points = sample_plot(params)
        if not points:
            return {"type": "none"}
        return {"type": "plot", "points": points}
    if kind == "projectile":
        points = projectile_points(params)
        if not points:
            return {"type": "none"}
        return {"type": "projectile", "points": points}
    if kind == "vector":
        vectors = _vectors(params)
        if not vectors:
            return {"type": "none"}
        return {"type": "vector", "vectors": vectors}
    return {"type": "none"}


def sample_plot(params):
    """[[x, y], ...] for a safe function of x, or None."""
    if not isinstance(params, dict):
        return None
    expression = params.get("expression")
    fn = compile_expression(expression)
    if fn is None:
        return None
    x_min = _clamp(_number(params.get("x_min"), -5.0), -1000.0, 1000.0)
    x_max = _clamp(_number(params.get("x_max"), 5.0), -1000.0, 1000.0)
    if x_max <= x_min:
        return None
    count = 81
    span = x_max - x_min
    points = []
    for index in range(count):
        x_value = x_min + span * index / float(count - 1)
        try:
            y_value = float(fn(x_value))
        except Exception:
            continue
        if not _finite(y_value) or abs(y_value) > 1e6:
            continue
        points.append([round(x_value, 6), round(y_value, 6)])
    if len(points) < 2:
        return None
    return points


def compile_expression(expression):
    """A function of x, or None. This does not call eval."""
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 80:
        return None
    try:
        tokens = _tokenize(expression)
        node, index = _parse_add(tokens, 0)
        if index != len(tokens):
            return None
    except Exception:
        return None

    def fn(x_value):
        return _eval_node(node, x_value)

    return fn


def projectile_points(params):
    """Kinematic arc as [x, y, 0] points, or None.

    v0 and angle (degrees) win. vx and vy are the fallback. g defaults to 9.81.
    """
    if not isinstance(params, dict):
        return None
    gravity = _number(params.get("g"), 9.81)
    if gravity <= 0 or gravity > 100:
        return None
    height = _clamp(_number(params.get("height", params.get("y0")), 0.0), 0.0, 1000.0)
    speed = _number(params.get("v0"), None)
    angle = _number(params.get("angle", params.get("angle_deg")), None)
    vx = _number(params.get("vx"), None)
    vy = _number(params.get("vy"), None)
    if speed is not None and angle is not None:
        speed = _clamp(speed, 0.1, 200.0)
        angle = _clamp(angle, 1.0, 89.0)
        radians = math.radians(angle)
        vx = speed * math.cos(radians)
        vy = speed * math.sin(radians)
    if vx is None or vy is None:
        return None
    vx = _clamp(vx, -200.0, 200.0)
    vy = _clamp(vy, -50.0, 200.0)
    if vy <= 0 and height <= 0:
        return None
    disc = vy * vy + 2.0 * gravity * height
    if disc < 0:
        return None
    t_end = (vy + math.sqrt(disc)) / gravity
    if not _finite(t_end) or t_end <= 0 or t_end > 120:
        return None
    count = 61
    points = []
    for index in range(count):
        t_value = t_end * index / float(count - 1)
        x_value = vx * t_value
        y_value = height + vy * t_value - 0.5 * gravity * t_value * t_value
        if y_value < 0 and index == count - 1:
            y_value = 0.0
        points.append([round(x_value, 4), round(max(0.0, y_value), 4), 0.0])
    return points


class TutorSession(object):
    """Which step is showing, and whether Fish should say it.

    Next and Back move one step and speak when they land on a new step.
    Replay speaks the current step again. Mute skips speech.
    """

    def __init__(self, lesson, speak=None):
        self.lesson = lesson
        self.speak = speak
        self.index = 0
        self.muted = False

    def current(self):
        return self.lesson["steps"][self.index]

    def start(self):
        self.index = 0
        return self._announce(True)

    def next(self):
        last = len(self.lesson["steps"]) - 1
        if self.index >= last:
            return self.current()
        self.index += 1
        return self._announce(True)

    def back(self):
        if self.index <= 0:
            return self.current()
        self.index -= 1
        return self._announce(True)

    def replay(self):
        return self._announce(True)

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted

    def _announce(self, speak_now):
        step = self.current()
        if speak_now and not self.muted and self.speak is not None:
            self.speak(step["say"])
        return step


def speak_step(text, fetch=None, play=None, post=None, api_key=None, voice_id=None, cache_dir=None):
    """Speak one step with Fish. The normal voice is the default.

    dramatic is false, so the model header is s2.1-pro-free. The Fish key
    stays in the Keychain and is read only when this call needs it.
    Tests pass fetch and play and never touch the network.
    """
    from .fish_voice import play_fish_reply

    def _fetch(line):
        if fetch is not None:
            return fetch(line)
        return _fetch_fish(line, post=post, api_key=api_key, voice_id=voice_id, cache_dir=cache_dir)

    def _play(path):
        if play is not None:
            play(path)
            return
        import subprocess
        subprocess.run(["afplay", path], check=False)

    with _speech_lock:
        return play_fish_reply(text, _fetch, _play)


def render_html(lesson):
    """One HTML document. Model text is JSON with < > & escaped."""
    payload = {
        "title": lesson["title"],
        "steps": lesson["steps"],
        "answer": lesson["answer"],
        "visual": map_visual(lesson.get("visual")),
    }
    blob = _embed_json(payload)
    return _PAGE_HEAD + blob + _PAGE_TAIL


def write_lesson_page(lesson, root=None, vendor=None):
    """Write lesson.html and copy the vendored assets next to it.

    The folder is Application Support/Hey Jev/tutor unless a test passes
    root. Downloads and any .cos path are refused.
    """
    folder = page_directory(root)
    os.makedirs(folder, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass
    stage_assets(folder, vendor or vendor_root())
    path = os.path.join(folder, PAGE_NAME)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(render_html(lesson))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def page_directory(root=None):
    """Absolute folder for the page. Refuses Downloads and .cos."""
    if root:
        raw = root
    else:
        raw = "~/Library/Application Support/Hey Jev/tutor"
    expanded = os.path.abspath(os.path.expanduser(str(raw)))
    if _forbidden_output(expanded):
        raise LessonError(TUTOR_FAILED)
    return expanded


def vendor_root():
    """KaTeX, Three.js, and plot.js.

    Alias builds (python setup.py py2app -A) run this file from the checkout,
    so the tree next to the source is the one the app loads. A full build
    copies that tree to Contents/Resources/tutor via setup.py resources.
    """
    override = os.environ.get("JEV_TUTOR_ASSETS")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    here = os.path.dirname(os.path.abspath(__file__))
    source = os.path.abspath(os.path.join(here, "..", "assets", "tutor"))
    if _vendor_ready(source):
        return source
    executable = getattr(sys, "executable", "") or ""
    bundled = os.path.abspath(os.path.join(os.path.dirname(executable), "..", "Resources", "tutor"))
    if _vendor_ready(bundled):
        return bundled
    return source


def stage_assets(dest, vendor):
    """Copy plot.js, katex, and three into the page folder."""
    if not _vendor_ready(vendor):
        raise LessonError(TUTOR_FAILED)
    for name in ("plot.js", "katex", "three"):
        src = os.path.join(vendor, name)
        target = os.path.join(dest, name)
        if os.path.isdir(src):
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)


def explain_from_text(text, ask=None, clipboard=None, show=None, speak=_AUTO,
                      platform=None, page_root=None, reader=None):
    """Run one tutor request. Returns a short status to speak.

    On a Mac, a valid lesson opens the panel and Fish says the first step
    unless speak is None. Tests pass ask, show, speak, and platform.
    """
    plat = sys.platform if platform is None else platform
    if plat != "darwin":
        return TUTOR_NOT_MAC
    try:
        return _explain(text, ask, clipboard, show, speak, page_root, reader)
    except LessonError as exc:
        return exc.status
    except Exception as exc:
        print("  tutor: {0}".format(type(exc).__name__))
        return TUTOR_FAILED


def open_tutor_panel(path, session):
    """Show the page in a WKWebView NSPanel. file:// only. No server.

    Back, Next, and Replay call the session, which speaks unless muted.
    AppKit is imported here so tests on Linux never load it.
    """
    def show():
        controller = _panel_class().alloc().initWithPage_session_(path, session)
        if controller is None:
            raise LessonError(TUTOR_FAILED)
        del _panels[:]
        _panels.append(controller)

    _on_main(show)


def _explain(text, ask, clipboard, show, speak, page_root, reader):
    parsed = parse_tutor_phrase(text)
    if parsed is None:
        return TUTOR_NEED_PROBLEM
    topic = parsed[0]
    if topic and _is_private(topic):
        return TUTOR_PRIVATE
    if topic:
        problem = _plain(topic, PROBLEM_LIMIT)
    else:
        board = clipboard if clipboard is not None else _read_clipboard(reader)
        if board is _PRIVATE or _is_private(board):
            return TUTOR_PRIVATE
        problem = _plain(board, PROBLEM_LIMIT)
    if not problem:
        return TUTOR_NEED_PROBLEM
    lesson = fetch_lesson(problem, ask=ask)
    path = write_lesson_page(lesson, root=page_root)
    if speak is _AUTO:
        voice = _speak_later(speak_step)
    else:
        voice = speak
    session = TutorSession(lesson, speak=voice)
    opener = show or open_tutor_panel
    opener(path, session)
    # A test double returns on this thread, so the first step is spoken here.
    # The real panel speaks it when the window is on screen.
    if show is not None:
        session.start()
    return TUTOR_OPENING


def _on_main(fn):
    from Foundation import NSThread
    if NSThread.isMainThread():
        fn()
        return
    from PyObjCTools import AppHelper
    AppHelper.callAfter(fn)


def _panel_class():
    global _controller_cls
    if _controller_cls is not None:
        return _controller_cls
    import objc
    from AppKit import (
        NSApp,
        NSBackingStoreBuffered,
        NSButton,
        NSColor,
        NSFont,
        NSMakeRect,
        NSPanel,
        NSTextField,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSObject, NSURL

    web_view_cls = objc.lookUpClass("WKWebView")
    web_config_cls = objc.lookUpClass("WKWebViewConfiguration")

    class TutorController(NSObject):
        session = objc.ivar()
        web = objc.ivar()
        label = objc.ivar()
        panel = objc.ivar()

        def initWithPage_session_(self, path, session):
            self = objc.super(TutorController, self).init()
            if self is None:
                return None
            self.session = session
            style = (
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskMiniaturizable
                | NSWindowStyleMaskResizable
            )
            self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 760, 640),
                style,
                NSBackingStoreBuffered,
                False,
            )
            self.panel.setTitle_("Tutor")
            self.panel.setFloatingPanel_(False)
            self.panel.setHidesOnDeactivate_(False)
            self.panel.setReleasedWhenClosed_(False)
            content = self.panel.contentView()
            bounds = content.bounds()
            width = float(bounds.size.width)
            height = float(bounds.size.height)
            bar = 48.0
            config = web_config_cls.alloc().init()
            self.web = web_view_cls.alloc().initWithFrame_configuration_(
                NSMakeRect(0, bar, width, max(1.0, height - bar)),
                config,
            )
            # Width and height sizable. The page sits above the buttons.
            self.web.setAutoresizingMask_(18)
            content.addSubview_(self.web)
            self._buttons(content)
            page = os.path.abspath(path)
            url = NSURL.fileURLWithPath_(page)
            root = NSURL.fileURLWithPath_(os.path.dirname(page))
            self.web.loadFileURL_allowingReadAccessToURL_(url, root)
            self._sync(False)
            self.panel.center()
            self.panel.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            self.session.start()
            return self

        def back_(self, _sender):
            self.session.back()
            self._sync(False)

        def next_(self, _sender):
            self.session.next()
            self._sync(False)

        def replay_(self, _sender):
            self.session.replay()
            self._sync(True)

        def mute_(self, sender):
            muted = self.session.toggle_mute()
            sender.setTitle_("Unmute" if muted else "Mute")

        @objc.python_method
        def _buttons(self, content):
            specs = (("Back", "back:"), ("Next", "next:"), ("Replay", "replay:"), ("Mute", "mute:"))
            x_pos = 16.0
            for title, action in specs:
                button = NSButton.alloc().initWithFrame_(NSMakeRect(x_pos, 12, 92, 26))
                button.setTitle_(title)
                button.setBezelStyle_(1)
                button.setTarget_(self)
                button.setAction_(action)
                button.setAutoresizingMask_(32)
                content.addSubview_(button)
                x_pos += 100.0
            self.label = NSTextField.alloc().initWithFrame_(NSMakeRect(x_pos + 8, 14, 180, 22))
            self.label.setBezeled_(False)
            self.label.setDrawsBackground_(False)
            self.label.setEditable_(False)
            self.label.setSelectable_(False)
            self.label.setFont_(NSFont.systemFontOfSize_(13))
            self.label.setTextColor_(NSColor.secondaryLabelColor())
            self.label.setAutoresizingMask_(32)
            content.addSubview_(self.label)

        @objc.python_method
        def _sync(self, replay):
            total = len(self.session.lesson["steps"])
            self.label.setStringValue_("Step {0} of {1}".format(self.session.index + 1, total))
            script = "if (window.tutorShow) window.tutorShow({0});".format(int(self.session.index))
            if replay:
                script += "if (window.tutorReplay) window.tutorReplay();"
            try:
                self.web.evaluateJavaScript_completionHandler_(script, None)
            except Exception as exc:
                print("  tutor: {0}".format(type(exc).__name__))

    _controller_cls = TutorController
    return TutorController


def _speak_later(fn):
    """Fish runs off the main thread so Next and Replay do not freeze the panel."""

    def run(text):
        threading.Thread(
            target=lambda: fn(text),
            name="jev-tutor-voice",
            daemon=True,
        ).start()

    return run


def _fetch_fish(line, post=None, api_key=None, voice_id=None, cache_dir=None):
    from .fish_voice import synthesize_speech
    secret = api_key if api_key is not None else _fish_key()
    if not secret:
        return None, 0
    result = synthesize_speech(
        line,
        post=post or _post_audio,
        api_key=secret,
        voice_id=voice_id or FISH_VOICE_ID,
        dramatic=False,
        cache_dir=cache_dir or _tts_cache(),
    )
    if result is None:
        return None, 0
    return result.path, result.ms


def _visual(raw):
    if raw is None:
        return {"type": "none", "params": {}}
    if not isinstance(raw, dict):
        raise LessonError("The visual wasn't an object.")
    kind = raw.get("type", "none")
    if kind is None:
        kind = "none"
    if not isinstance(kind, str) or kind not in VISUAL_TYPES:
        raise LessonError("The visual type wasn't one I can draw.")
    params = raw.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise LessonError("The visual parameters weren't an object.")
    return {"type": kind, "params": params}


def _vectors(params):
    raw = params.get("vectors") if isinstance(params, dict) else None
    if not isinstance(raw, list) or not raw:
        return None
    found = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        x_value = _number(item.get("x"), None)
        y_value = _number(item.get("y"), None)
        z_value = _number(item.get("z"), 0.0)
        if x_value is None or y_value is None or z_value is None:
            continue
        if not (_finite(x_value) and _finite(y_value) and _finite(z_value)):
            continue
        label = item.get("label") if isinstance(item.get("label"), str) else ""
        if not _LABEL_RE.match(label):
            label = ""
        found.append({
            "x": round(x_value, 4),
            "y": round(y_value, 4),
            "z": round(z_value, 4),
            "label": label,
        })
    return found or None


def _tokenize(expression):
    tokens = []
    pos = 0
    text = expression.strip()
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if not match:
            raise ValueError("bad expression")
        tokens.append(match.group(1))
        pos = match.end()
    if not tokens:
        raise ValueError("empty")
    return tokens


def _parse_add(tokens, index):
    node, index = _parse_mul(tokens, index)
    while index < len(tokens) and tokens[index] in ("+", "-"):
        op = tokens[index]
        right, index = _parse_mul(tokens, index + 1)
        node = ("bin", op, node, right)
    return node, index


def _parse_mul(tokens, index):
    node, index = _parse_pow(tokens, index)
    while index < len(tokens) and tokens[index] in ("*", "/"):
        op = tokens[index]
        right, index = _parse_pow(tokens, index + 1)
        node = ("bin", op, node, right)
    return node, index


def _parse_pow(tokens, index):
    node, index = _parse_unary(tokens, index)
    if index < len(tokens) and tokens[index] == "^":
        right, index = _parse_pow(tokens, index + 1)
        node = ("bin", "^", node, right)
    return node, index


def _parse_unary(tokens, index):
    if index < len(tokens) and tokens[index] == "-":
        node, index = _parse_unary(tokens, index + 1)
        return ("neg", node), index
    return _parse_primary(tokens, index)


def _parse_primary(tokens, index):
    if index >= len(tokens):
        raise ValueError("truncated")
    token = tokens[index]
    if token == "(":
        node, index = _parse_add(tokens, index + 1)
        if index >= len(tokens) or tokens[index] != ")":
            raise ValueError("paren")
        return node, index + 1
    if token == "x":
        return ("x",), index + 1
    if token == "pi":
        return ("num", math.pi), index + 1
    if token == "e" and token not in _FUNCS:
        return ("num", math.e), index + 1
    if token in _FUNCS:
        if index + 1 >= len(tokens) or tokens[index + 1] != "(":
            raise ValueError("call")
        node, index = _parse_add(tokens, index + 2)
        if index >= len(tokens) or tokens[index] != ")":
            raise ValueError("call")
        return ("call", token, node), index + 1
    return ("num", float(token)), index + 1


def _eval_node(node, x_value):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "x":
        return x_value
    if kind == "neg":
        return -_eval_node(node[1], x_value)
    if kind == "call":
        return _FUNCS[node[1]](_eval_node(node[2], x_value))
    left = _eval_node(node[2], x_value)
    right = _eval_node(node[3], x_value)
    op = node[1]
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        return left / right
    if op == "^":
        return math.pow(left, right)
    raise ValueError(op)


def _bounded(value, limit, allow_empty=False):
    if not isinstance(value, str):
        return None
    cleaned = _plain(value, limit)
    if not cleaned and not allow_empty:
        return ""
    return cleaned


def _plain(value, limit):
    if value is _PRIVATE:
        return ""
    text = "".join(ch for ch in str(value or "") if ch in "\n\t" or ord(ch) >= 32)
    text = text.strip()
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _embed_json(payload):
    text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _number(value, default):
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return default
    else:
        return default
    if not _finite(number):
        return default
    return number


def _clamp(value, low, high):
    return min(high, max(low, float(value)))


def _finite(value):
    return isinstance(value, float) and value == value and abs(value) != float("inf")


def _forbidden_output(path):
    parts = os.path.abspath(path).split(os.sep)
    if any(part == ".cos" or part.endswith(".cos") for part in parts if part):
        return True
    downloads = os.path.abspath(os.path.expanduser("~/Downloads"))
    if path == downloads or path.startswith(downloads + os.sep):
        return True
    return False


def _vendor_ready(path):
    return (
        os.path.isfile(os.path.join(path, "plot.js"))
        and os.path.isfile(os.path.join(path, "katex", "katex.min.js"))
        and os.path.isfile(os.path.join(path, "katex", "LICENSE"))
        and os.path.isfile(os.path.join(path, "three", "three.min.js"))
        and os.path.isfile(os.path.join(path, "three", "LICENSE"))
    )


def _openrouter_key(key):
    if key is not None:
        return str(key)
    try:
        from secrets_store import get_secret
        return get_secret("OPENROUTER_API_KEY") or ""
    except Exception:
        return ""


def _fish_key():
    try:
        from secrets_store import get_secret
        return get_secret("FISH_AUDIO_API_KEY") or ""
    except Exception:
        return ""


def _post_chat(body, key):
    import requests
    response = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": "Bearer {0}".format(key),
            "Content-Type": "application/json",
        },
        json=body,
        timeout=45,
    )
    response.raise_for_status()
    return response.json()


def _post_audio(*args, **kwargs):
    import requests
    return requests.post(*args, **kwargs)


def _tts_cache():
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache", "tts")
    folder = os.path.abspath(folder)
    os.makedirs(folder, exist_ok=True)
    return folder


def _read_clipboard(reader):
    if reader is None:
        reader = _pasteboard_reader
    try:
        value = reader()
    except Exception as exc:
        print("  tutor: {0}".format(type(exc).__name__))
        return ""
    if isinstance(value, str) or value is None:
        return "" if value is None else value
    try:
        from .clipboard_history import types_are_concealed
        if types_are_concealed(getattr(value, "types", ())):
            return _PRIVATE
    except Exception:
        pass
    text = getattr(value, "text", "")
    return "" if text is None else str(text)


def _pasteboard_reader():
    from .clipboard_history import read_general_pasteboard
    return read_general_pasteboard()


def _is_private(text):
    if text is _PRIVATE:
        return True
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        from .clipboard_history import looks_like_secret
        return looks_like_secret(text)
    except Exception:
        return False
