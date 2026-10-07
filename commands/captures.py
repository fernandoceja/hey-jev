"""Screenshots, screen recordings, and the follow-ups that open compose sheets.

Nothing here sends mail or a message, reads My Love, talks to the network, or
writes the Keychain. Opening an https URL hands it to the browser. The bytes
of a capture stay on this Mac.

The folder is CAPTURES_DIR in commands/config.py, usually ~/Pictures/Jev Captures.
JEV_CAPTURES_DIR overrides it.

Notes: AppleScript makes a new note and attaches the file with
`make new attachment with data`. Mail: AppleScript makes a visible outgoing
message and attaches the file. It never says send. Messages: NSSharingService
compose sheet when AppKit is available, otherwise Messages is opened and the
file is copied. He presses Send.

Ask handoffs do not submit. ChatGPT, Claude, and Google Search prefill a URL.
Gemini and Siri copy the question and open the app or site. A picture or
recording is copied and revealed so he can paste or upload it. Google images
open the Lens upload page. Jev does not POST the file.
"""
from datetime import datetime
import os
import signal
import subprocess
import tempfile
import threading
import time
from urllib.parse import quote

from .config import CAPTURES_DIR

_AUTO = object()
PRIVACY_URL = "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ScreenCapture"
MESSAGE_SERVICE = "com.apple.share.Messages.compose"
# Real TCC denials. A generic screencapture failure is not one of these.
_TCC_WORDS = ("declined tcc", "not authorized", "not permitted")
_FFMPEG_PATHS = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")


class CaptureBook:
    """Last capture, the recording in progress, and the last question he asked."""

    def __init__(self):
        self.last = None
        self.recording = None
        self.question = ""

    def remember(self, path, kind):
        self.last = {"path": path, "kind": kind}

    def reset(self):
        self.last = None
        self.recording = None
        self.question = ""


BOOK = CaptureBook()


def captures_folder(override=None, env=None, configured=None):
    """Absolute folder for new captures.

    `override` wins, then JEV_CAPTURES_DIR, then CAPTURES_DIR.
    """
    if override:
        return os.path.abspath(os.path.expanduser(str(override)))
    if env is None:
        env = os.environ
    custom = ""
    if hasattr(env, "get"):
        custom = env.get("JEV_CAPTURES_DIR") or ""
    if custom:
        return os.path.abspath(os.path.expanduser(str(custom)))
    base = CAPTURES_DIR if configured is None else configured
    return os.path.abspath(os.path.expanduser(str(base)))


def capture_name(kind, mode, when):
    """Timestamped file name. kind is screenshot or recording."""
    stamp = when.strftime("%Y-%m-%d %H-%M-%S")
    if kind == "recording":
        return "Jev Recording {0}.mov".format(stamp)
    labels = {"full": "Screenshot", "area": "Area", "window": "Window"}
    label = labels.get(mode, "Screenshot")
    return "Jev {0} {1}.png".format(label, stamp)


def screenshot_command(mode, path):
    """screencapture argv. Full screen is silent. Area and window wait for a click."""
    if mode == "area":
        return ["screencapture", "-i", "-x", path]
    if mode == "window":
        return ["screencapture", "-iW", "-x", path]
    return ["screencapture", "-x", path]


def recording_command(path, mic=False):
    """Full-screen video. -V includes the mic. -v is the screen only."""
    flag = "-V" if mic else "-v"
    return ["screencapture", flag, "-x", path]


def permission_command():
    return ["open", PRIVACY_URL]


def recording_clock(started, now):
    elapsed = max(0, int(now - started))
    return "{0}:{1:02d}".format(elapsed // 60, elapsed % 60)


def wants_mic(text):
    import re
    return bool(re.search(r"\b(?:with\s+(?:the\s+)?(?:mic|audio|microphone)|and\s+(?:the\s+)?mic)\b", str(text or ""), re.I))


def _apple_quote(path):
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def _run_capture(args, input=None, timeout=30):
    result = subprocess.run(list(args), input=input, capture_output=True, text=True, timeout=timeout)
    err = (result.stderr or "").strip()
    if err:
        print("  capture stderr: {0}".format(err))
    if result.returncode:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise RuntimeError(detail)
    return result.stdout or ""


def permission_failure(text):
    """True only for a Screen Recording TCC denial, not every screencapture error."""
    lowered = str(text or "").lower()
    return any(word in lowered for word in _TCC_WORDS)


def _permission_failure(exc):
    return permission_failure(exc)


def _log_capture(kind, detail):
    print("  capture {0} failed: {1}".format(kind, detail or "command failed"))


def _open_privacy(run):
    try:
        run(permission_command())
        return True
    except Exception:
        return False


def _saved_sentence(kind, path):
    folder = os.path.dirname(path)
    labels = {
        "full": "full screen screenshot",
        "area": "area screenshot",
        "window": "window screenshot",
        "recording": "recording",
    }
    return "Saved a {0} to {1}.".format(labels.get(kind, "screenshot"), folder)


def take_screenshot(mode="full", folder=None, when=None, run=None, book=None, env=None):
    """Capture the screen. mode is full, area, or window."""
    mode = mode if mode in ("full", "area", "window") else "full"
    when = when or datetime.now().astimezone()
    dest = captures_folder(override=folder, env=env)
    os.makedirs(dest, exist_ok=True)
    path = os.path.join(dest, capture_name("screenshot", mode, when))
    runner = run or _run_capture
    timeout = 30 if mode == "full" else 180
    try:
        runner(screenshot_command(mode, path), timeout=timeout)
    except Exception as exc:
        detail = str(exc).strip() or "command failed"
        _log_capture("screenshot", detail)
        if permission_failure(detail):
            opened = _open_privacy(runner)
            if opened:
                return "I couldn't take a screenshot. Allow Screen Recording for Hey Jev. I opened the Privacy pane."
            return "I couldn't take a screenshot. Allow Screen Recording for Hey Jev."
        if mode != "full":
            return "Cancelled."
        return "Couldn't take a screenshot."
    target = book if book is not None else BOOK
    target.remember(path, "screenshot")
    return _saved_sentence(mode, path)


def _popen(args):
    """stderr is a pipe so a denial can be logged. The caller drains it."""
    return subprocess.Popen(list(args), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def _drain_stderr(proc):
    stream = getattr(proc, "stderr", None)
    if stream is None:
        return
    try:
        err = stream.read()
    except Exception:
        return
    text = str(err or "").strip()
    if text:
        print("  capture stderr: {0}".format(text))


def _early_exit(proc):
    """Return code if screencapture quit immediately, else None while it is still recording."""
    poll = getattr(proc, "poll", None)
    if not callable(poll):
        return None
    try:
        code = poll()
    except Exception:
        return None
    if code is not None:
        return code
    time.sleep(0.25)
    try:
        return poll()
    except Exception:
        return None


def _read_stderr(proc):
    stream = getattr(proc, "stderr", None)
    if stream is None:
        return ""
    try:
        return str(stream.read() or "")
    except Exception:
        return ""


def start_screen_recording(text="", folder=None, when=None, book=None, popen=None, env=None, run=None):
    """Start screencapture video. Returns as soon as the process is up."""
    target = book if book is not None else BOOK
    if target.recording:
        return "Already recording."
    when = when or datetime.now().astimezone()
    dest = captures_folder(override=folder, env=env)
    os.makedirs(dest, exist_ok=True)
    path = os.path.join(dest, capture_name("recording", "full", when))
    mic = wants_mic(text)
    args = recording_command(path, mic=mic)
    try:
        proc = (popen or _popen)(args)
    except Exception as exc:
        detail = str(exc).strip() or "command failed"
        _log_capture("recording", detail)
        if permission_failure(detail):
            _open_privacy(run or _run_capture)
            return "I couldn't start a recording. Allow Screen Recording for Hey Jev. I opened the Privacy pane."
        return "Couldn't start a recording."
    code = _early_exit(proc)
    if code is not None:
        detail = _read_stderr(proc).strip() or "screencapture exited {0}".format(code)
        _log_capture("recording", detail)
        if permission_failure(detail):
            _open_privacy(run or _run_capture)
            return "I couldn't start a recording. Allow Screen Recording for Hey Jev. I opened the Privacy pane."
        return "Couldn't start a recording."
    if getattr(proc, "stderr", None) is not None:
        threading.Thread(target=_drain_stderr, args=(proc,), daemon=True).start()
    target.recording = {
        "path": path,
        "started": when.timestamp(),
        "mic": mic,
        "proc": proc,
        "args": list(args),
    }
    if mic:
        return "Recording with the mic. Say stop recording when you want me to save it."
    return "Recording. Say stop recording when you want me to save it."


def is_recording(book=None):
    target = book if book is not None else BOOK
    return bool(target.recording)


def recording_status(book=None, now=None):
    """Red-dot clock for the pill, or None when nothing is recording."""
    target = book if book is not None else BOOK
    rec = target.recording
    if not rec:
        return None
    moment = datetime.now().timestamp() if now is None else now
    return {
        "clock": recording_clock(rec["started"], moment),
        "path": rec["path"],
        "mic": bool(rec.get("mic")),
    }


def find_ffmpeg(which=None):
    probe = which
    if probe is None:
        import shutil
        probe = shutil.which
    found = None
    try:
        found = probe("ffmpeg")
    except Exception:
        found = None
    for path in (found,) + _FFMPEG_PATHS:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def codec_command(ffprobe, path):
    return [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name", "-of", "csv=p=0", path,
    ]


def mp4_command(ffmpeg, src):
    """Copy the video into an MP4. Used only when the codec is already H.264."""
    dest = os.path.splitext(src)[0] + ".mp4"
    return [ffmpeg, "-y", "-i", src, "-c", "copy", dest], dest


def _interrupt(proc):
    proc.send_signal(signal.SIGINT)


def _wait_proc(proc, timeout=20):
    proc.wait(timeout=timeout)


def stop_screen_recording(book=None, run=None, interrupt=None, wait=None, ffmpeg=_AUTO, now=None):
    """SIGINT the recording, then copy it to MP4 when ffmpeg is present and the video is H.264."""
    target = book if book is not None else BOOK
    rec = target.recording
    if not rec:
        return "Nothing is recording."
    proc = rec.get("proc")
    try:
        if proc is not None:
            (interrupt or _interrupt)(proc)
            (wait or _wait_proc)(proc, timeout=20)
    except Exception:
        pass
    target.recording = None
    path = rec["path"]
    runner = run or _run_capture
    final = path
    if ffmpeg is _AUTO:
        ffmpeg = find_ffmpeg() or ""
    if ffmpeg:
        ffprobe = os.path.join(os.path.dirname(ffmpeg), "ffprobe")
        codec = ""
        try:
            codec = runner(codec_command(ffprobe, path)).strip().lower()
        except Exception:
            codec = ""
        if codec == "h264":
            args, dest = mp4_command(ffmpeg, path)
            try:
                runner(args)
                final = dest
            except Exception:
                final = path
    target.remember(final, "recording")
    if final.endswith(".mp4"):
        return "Saved the recording as an MP4 in {0}.".format(os.path.dirname(final))
    return _saved_sentence("recording", final)


def note_question(text, book=None):
    """Remember a question that is about to go to the LLM. Local commands do not call this."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    target = book if book is not None else BOOK
    target.question = cleaned
    return cleaned


def _blocked_person(text):
    import re
    return bool(re.search(r"\bmy\s+love\b", str(text or ""), re.I))


def recipient_from(text):
    import re
    match = re.search(r"\bto\s+(.+)$", str(text or "").strip(), re.I)
    if not match:
        return ""
    who = match.group(1).strip(" .!?")
    who = re.sub(r"\s+please$", "", who, flags=re.I).strip()
    return who


def notes_script(path):
    quoted = _apple_quote(path)
    return (
        'set theFile to POSIX file "{0}"\n'
        'tell application "Notes"\n'
        "activate\n"
        'set theNote to make new note with properties {{name:"Jev capture", body:"Captured with Jev."}}\n'
        "tell theNote to make new attachment with data theFile\n"
        "end tell"
    ).format(quoted)


def email_script(path, recipient=""):
    """A visible outgoing message. This script does not send it."""
    quoted = _apple_quote(path)
    lines = [
        'set theFile to POSIX file "{0}"'.format(quoted),
        'tell application "Mail"',
        "activate",
        "set theMessage to make new outgoing message with properties {visible:true, subject:\"Jev capture\"}",
        "tell theMessage",
    ]
    if recipient:
        lines.append(
            'make new to recipient at end of to recipients with properties {{address:"{0}"}}'.format(
                _apple_quote(recipient)
            )
        )
    lines.extend((
        "make new attachment with properties {file name:theFile} at after the last paragraph",
        "end tell",
        "end tell",
    ))
    return "\n".join(lines)


def clipboard_script(path):
    return 'set the clipboard to (POSIX file "{0}")'.format(_apple_quote(path))


def imessage_plan(path, recipient=""):
    """Compose sheet only. sends is always false."""
    return {
        "service": MESSAGE_SERVICE,
        "path": path,
        "recipient": recipient or "",
        "sends": False,
        "fallback": ["open", "-a", "Messages"],
    }


def delete_script(path):
    """Finder delete moves the file to the Trash."""
    return 'tell application "Finder" to delete POSIX file "{0}"'.format(_apple_quote(path))


def share_with_service(service, path, recipient=""):
    """Open the system compose sheet for Messages. performWithItems_ does not send."""
    try:
        from AppKit import NSSharingService, NSURL
    except Exception:
        return False
    svc = NSSharingService.sharingServiceNamed_(service)
    if svc is None:
        return False
    if recipient and hasattr(svc, "setRecipients_"):
        svc.setRecipients_([str(recipient)])
    svc.performWithItems_([NSURL.fileURLWithPath_(path)])
    return True


def _require_capture(book):
    if book.last and book.last.get("path"):
        return book.last["path"]
    return ""


def save_capture_to_notes(path, run=None):
    runner = run or _run_capture
    try:
        runner(["osascript", "-e", notes_script(path)])
    except Exception:
        return "I couldn't save that to Notes. Allow Automation for Notes."
    return "Saved it to a new note in Notes."


def email_capture(path, recipient="", run=None):
    if _blocked_person(recipient):
        return "I won't email My Love from here."
    runner = run or _run_capture
    try:
        runner(["osascript", "-e", email_script(path, recipient)])
    except Exception:
        return "I couldn't open Mail. Allow Automation for Mail."
    return "Mail is open with the capture attached. Press Send yourself."


def message_capture(path, recipient="", run=None, share=None):
    if _blocked_person(recipient):
        return "I won't message My Love from here."
    plan = imessage_plan(path, recipient)
    if plan["sends"]:
        return "I won't send that."
    runner = run or _run_capture
    opener = share if share is not None else share_with_service
    opened = False
    try:
        opened = bool(opener(plan["service"], path, plan["recipient"]))
    except Exception:
        opened = False
    if not opened:
        try:
            runner(plan["fallback"])
            runner(["osascript", "-e", clipboard_script(path)])
        except Exception:
            return "I couldn't open Messages."
        return "Messages is open. The capture is copied. Paste it and press Send yourself."
    if recipient:
        return "Messages is open with that person filled in. Press Send yourself."
    return "Messages is open with the capture. Press Send yourself."


def reveal_capture(path, run=None):
    runner = run or _run_capture
    try:
        runner(["open", "-R", path])
    except Exception:
        return "I couldn't show that in Finder."
    return "Showing it in Finder."


def copy_capture(path, run=None):
    runner = run or _run_capture
    try:
        runner(["osascript", "-e", clipboard_script(path)])
    except Exception:
        return "I couldn't copy that."
    return "Copied the capture."


def delete_capture(path, run=None, book=None):
    runner = run or _run_capture
    try:
        runner(["osascript", "-e", delete_script(path)])
    except Exception:
        return "I couldn't move that to the Trash."
    target = book if book is not None else BOOK
    if target.last and target.last.get("path") == path:
        target.last = None
    return "Moved it to the Trash."


def share_from_text(text, book=None, run=None, share=None):
    """Voice follow-up for the last capture. Mail and Messages stay unsent."""
    import re
    target = book if book is not None else BOOK
    path = _require_capture(target)
    if not path:
        return "Take a screenshot or record the screen first."
    raw = str(text or "")
    who = recipient_from(raw)
    if _blocked_person(who) or _blocked_person(raw):
        if re.search(r"\bemail\b", raw, re.I):
            return "I won't email My Love from here."
        return "I won't message My Love from here."
    if re.search(r"\bnotes?\b", raw, re.I):
        return save_capture_to_notes(path, run=run)
    if re.search(r"\bemail\b", raw, re.I):
        return email_capture(path, who, run=run)
    if re.search(r"\b(?:text|imessage|i\s*message|message)\b", raw, re.I):
        return message_capture(path, who, run=run, share=share)
    if re.search(r"\bfinder\b", raw, re.I):
        return reveal_capture(path, run=run)
    if re.search(r"\bcopy\b", raw, re.I):
        return copy_capture(path, run=run)
    if re.search(r"\b(?:delete|trash)\b", raw, re.I):
        return delete_capture(path, run=run, book=target)
    return "Take a screenshot or record the screen first."


def _query(text):
    return quote(str(text or ""), safe="")


def _ask_name(target):
    names = {
        "chatgpt": "chatgpt",
        "chat gpt": "chatgpt",
        "claude": "claude",
        "gemini": "gemini",
        "siri": "siri",
        "google": "google",
    }
    return names.get(str(target or "").strip().lower(), "")


def target_from_phrase(text):
    import re
    raw = str(text or "")
    match = re.search(r"\b(chat\s*gpt|chatgpt|claude|gemini|siri|google)\b", raw, re.I)
    if not match:
        return ""
    return _ask_name(match.group(1))


def ask_subject(phrase, has_capture, has_question):
    """capture, question, or empty when there is nothing to hand off."""
    import re
    raw = str(phrase or "").lower()
    if has_capture and re.search(r"\b(?:screenshot|recording|picture|photo|video|capture|image)\b", raw):
        return "capture"
    if has_question and re.search(r"\b(?:question|what i asked)\b", raw):
        return "question"
    if has_capture and re.search(r"\bthis\b", raw):
        return "capture"
    if has_question and re.search(r"\bthat\b", raw):
        return "question"
    if has_question:
        return "question"
    if has_capture:
        return "capture"
    return ""


def ask_plan(target, subject, question="", path=""):
    """How to open another app. submits is always false. prefills means the URL carries the question."""
    name = _ask_name(target)
    subject = "capture" if subject == "capture" else "question"
    if name == "google" and subject == "capture":
        return {
            "target": "google",
            "subject": "capture",
            "prefills": False,
            "submits": False,
            "url": "https://lens.google.com/upload",
            "app": "",
            "copy_text": "",
            "copy_file": path,
            "path": path,
            "reveal": True,
            "speech": "Lens is open. The capture is copied for you to upload. I didn't send it.",
        }
    if name == "google":
        return {
            "target": "google",
            "subject": "question",
            "prefills": True,
            "submits": False,
            "url": "https://www.google.com/search?q=" + _query(question),
            "app": "",
            "copy_text": question,
            "copy_file": "",
            "path": "",
            "reveal": False,
            "speech": "Google is open with your question. Press Return when you want to search.",
        }
    if subject == "question" and name == "chatgpt":
        return _question_plan(
            "chatgpt", "https://chatgpt.com/?q=" + _query(question), question, True,
            "ChatGPT is open with your question. Press Return when you want to send it.",
        )
    if subject == "question" and name == "claude":
        return _question_plan(
            "claude", "https://claude.ai/new?q=" + _query(question), question, True,
            "Claude is open with your question. Press Return when you want to send it.",
        )
    if subject == "question" and name == "gemini":
        return _question_plan(
            "gemini", "https://gemini.google.com/app", question, False,
            "Question copied, paste it in.",
        )
    if subject == "question" and name == "siri":
        return {
            "target": "siri",
            "subject": "question",
            "prefills": False,
            "submits": False,
            "url": "",
            "app": "Siri",
            "copy_text": question,
            "copy_file": "",
            "path": "",
            "reveal": False,
            "speech": "Question copied, paste it in.",
        }
    apps = {"chatgpt": "ChatGPT", "claude": "Claude", "siri": "Siri"}
    urls = {"gemini": "https://gemini.google.com/app"}
    return {
        "target": name,
        "subject": "capture",
        "prefills": False,
        "submits": False,
        "url": urls.get(name, ""),
        "app": apps.get(name, ""),
        "copy_text": "",
        "copy_file": path,
        "path": path,
        "reveal": True,
        "speech": "Copied the capture. Paste it in and press Return yourself.",
    }


def _question_plan(target, url, question, prefills, speech):
    return {
        "target": target,
        "subject": "question",
        "prefills": bool(prefills),
        "submits": False,
        "url": url,
        "app": "",
        "copy_text": question,
        "copy_file": "",
        "path": "",
        "reveal": False,
        "speech": speech,
    }


def execute_ask(plan, run=None):
    """Open the handoff. This does not press Return, so nothing is submitted."""
    if plan.get("submits"):
        return "I won't submit that."
    runner = run or _run_capture
    if plan.get("copy_text"):
        runner(["pbcopy"], input=plan["copy_text"])
    if plan.get("copy_file"):
        runner(["osascript", "-e", clipboard_script(plan["copy_file"])])
    if plan.get("reveal") and plan.get("path"):
        runner(["open", "-R", plan["path"]])
    if plan.get("url"):
        runner(["open", plan["url"]])
    if plan.get("app"):
        runner(["open", "-a", plan["app"]])
    return plan.get("speech") or ""


def ask_from_text(text, book=None, run=None):
    target_book = book if book is not None else BOOK
    name = target_from_phrase(text)
    if not name:
        return "Say ask ChatGPT, Claude, Gemini, Siri, or Google."
    subject = ask_subject(text, target_book.last is not None, bool(target_book.question))
    if subject == "capture":
        path = _require_capture(target_book)
        if not path:
            return "Take a screenshot or record the screen first."
        plan = ask_plan(name, "capture", path=path)
    elif subject == "question":
        if not target_book.question:
            return "Ask me something first."
        plan = ask_plan(name, "question", question=target_book.question)
    else:
        return "Take a screenshot or ask me something first."
    return execute_ask(plan, run=run)


def open_captures_folder(folder=None, run=None, env=None):
    """Create the captures folder if needed and reveal it in Finder."""
    dest = captures_folder(override=folder, env=env)
    os.makedirs(dest, exist_ok=True)
    runner = run or _run_capture
    try:
        runner(["open", dest])
    except Exception:
        return "I couldn't open the captures folder."
    return "Opening your captures folder."


def prepare_capture_still(path, run=None, ffmpeg=_AUTO):
    """One JPEG the vision call can send. Recordings use the middle frame."""
    from .vision import (
        duration_command,
        frame_command,
        is_movie,
        media_type_for,
        middle_second,
        prepare_image,
    )
    runner = run or _run_capture
    work = tempfile.mkdtemp(prefix="jev-ask-")
    source = path
    if is_movie(path):
        tool = find_ffmpeg() if ffmpeg is _AUTO else (ffmpeg or "")
        if not tool:
            raise RuntimeError("no ffmpeg for a recording")
        frame = os.path.join(work, "frame.png")
        probe = os.path.join(os.path.dirname(tool), "ffprobe")
        duration = runner(duration_command(probe, path))
        runner(frame_command(tool, path, frame, middle_second(duration)))
        source = frame
    dest = os.path.join(work, "ask.jpg")
    prepare_image(source, dest, runner, os.path.getsize)
    return dest, media_type_for(dest)


def ask_jev_from_text(text, book=None, question=None, post=None, key=None, run=None, prepare=None, ffmpeg=_AUTO):
    """Look at the last capture. Voice uses the default question. He has to ask."""
    from .vision import ask_about_capture, is_movie
    target = book if book is not None else BOOK
    path = _require_capture(target)
    if not path:
        return "Take a screenshot or record the screen first."
    if prepare is None and is_movie(path):
        tool = find_ffmpeg() if ffmpeg is _AUTO else (ffmpeg or "")
        if not tool:
            return "I can describe a screenshot. This capture is a recording."

    def _prepare(image_path):
        return prepare_capture_still(image_path, run=run, ffmpeg=ffmpeg)

    return ask_about_capture(
        path,
        "" if question is None else question,
        post=post,
        key=key,
        prepare=prepare or _prepare,
    )


def run_capture_menu(kind, book=None, run=None, popen=None, share=None, ffmpeg=_AUTO):
    """One + menu or follow-up row. kind matches the menu item id."""
    target = book if book is not None else BOOK
    kind = str(kind or "")
    if kind in ("screenshot", "screenshot_full"):
        return take_screenshot("full", book=target, run=run)
    if kind == "screenshot_area":
        return take_screenshot("area", book=target, run=run)
    if kind == "screenshot_window":
        return take_screenshot("window", book=target, run=run)
    if kind == "record_start":
        return start_screen_recording("start screen recording", book=target, popen=popen, run=run)
    if kind == "record_stop":
        return stop_screen_recording(book=target, run=run, ffmpeg=ffmpeg)
    path = _require_capture(target)
    if kind == "share_notes":
        if not path:
            return "Take a screenshot or record the screen first."
        return save_capture_to_notes(path, run=run)
    if kind == "share_email":
        if not path:
            return "Take a screenshot or record the screen first."
        return email_capture(path, "", run=run)
    if kind == "share_imessage":
        if not path:
            return "Take a screenshot or record the screen first."
        return message_capture(path, "", run=run, share=share)
    if kind == "share_finder":
        if not path:
            return "Take a screenshot or record the screen first."
        return reveal_capture(path, run=run)
    if kind == "share_copy":
        if not path:
            return "Take a screenshot or record the screen first."
        return copy_capture(path, run=run)
    if kind == "share_delete":
        if not path:
            return "Take a screenshot or record the screen first."
        return delete_capture(path, run=run, book=target)
    if kind == "captures_open":
        return open_captures_folder(run=run)
    if kind == "ask_jev":
        return ask_jev_from_text("ask jev about this", book=target, run=run, ffmpeg=ffmpeg)
    if kind.startswith("ask_capture_"):
        name = kind.split("_")[-1]
        return ask_from_text("ask {0} about this".format(name), book=target, run=run)
    if kind.startswith("ask_question_"):
        name = kind.split("_")[-1]
        return ask_from_text("ask {0} about that".format(name), book=target, run=run)
    return ""


CAPTURE_ROUTE_KEYS = (
    "screenshot",
    "screenshot_area",
    "screenshot_window",
    "record_start",
    "record_stop",
    "capture_note",
    "capture_email",
    "capture_imessage",
    "capture_finder",
    "capture_copy",
    "capture_delete",
    "ask_chatgpt",
    "ask_claude",
    "ask_gemini",
    "ask_siri",
    "ask_google",
    "ask_jev",
    "captures_open",
)
