"""Local video quick actions for a screen recording or a chosen movie file.

ffmpeg does the work when it is on PATH or in the usual Homebrew locations.
avconvert (AVFoundation presets) covers convert, compress, and extract audio
when ffmpeg is missing. Trim needs ffmpeg. The new file is written next to
the source and the original is never replaced.

Nothing here uploads a file, listens for connections, reads the Keychain,
or adds a command to the iPhone bridge. Argument lists only: no shell.
"""
import os
import re
import shutil
import subprocess
import threading

from .captures import BOOK, find_ffmpeg

_AUTO = object()
MISSING_FFMPEG = "I need ffmpeg for that. Install it with brew install ffmpeg."
CHOOSE_HINT = "Record the screen first, or say choose a video."
TRIM_HINT = "Say trim the recording from 0:05 to 0:30."
VIDEO_EXTENSIONS = (".mov", ".mp4", ".m4v", ".mkv", ".avi", ".webm", ".mpeg", ".mpg")
FFMPEG_CANDIDATES = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")
AVCONVERT_CANDIDATES = ("/usr/bin/avconvert",)
# Presets that write H.264/AAC. PresetAppleM4A is audio only.
AVCONVERT_PRESETS = {
    "mp4": "Preset1920x1080",
    "compress": "Preset640x480",
    "audio": "PresetAppleM4A",
}
VIDEO_ROUTE_KEYS = (
    "video_mp4",
    "video_trim",
    "video_compress",
    "video_audio",
    "video_choose",
)
_ACTIONS = {
    "video_mp4": "mp4",
    "mp4": "mp4",
    "convert": "mp4",
    "video_trim": "trim",
    "trim": "trim",
    "video_compress": "compress",
    "compress": "compress",
    "video_audio": "audio",
    "audio": "audio",
    "video_choose": "choose",
    "choose": "choose",
}
_WORKING = {
    "mp4": "Converting the recording to MP4.",
    "trim": "Trimming the recording.",
    "compress": "Compressing the recording.",
    "audio": "Extracting the audio.",
}
_DONE = {
    "mp4": "Saved the MP4 next to the recording.",
    "trim": "Saved the trimmed video next to the recording.",
    "compress": "Saved a smaller video next to the recording.",
    "audio": "Saved the audio next to the recording.",
}
_FAIL = {
    "mp4": "I couldn't convert that video.",
    "trim": "I couldn't trim that video.",
    "compress": "I couldn't compress that video.",
    "audio": "I couldn't extract the audio.",
}
_TOOL_UNSAFE = set("\"'`\n\r$\\;|&<>")
_CLOCK_RE_TEXT = r"(?:(?:\d{1,2}:){1,2}\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)"


def _log(detail):
    print("  video: {0}".format(detail))


def is_video_extension(path):
    return os.path.splitext(str(path or ""))[1].lower() in VIDEO_EXTENSIONS


def _safe_tool(path):
    """An absolute tool path with no shell metacharacters, or empty."""
    text = str(path or "")
    if not text.startswith("/") or "\x00" in text:
        return ""
    if any(ch in text for ch in _TOOL_UNSAFE):
        return ""
    return text


def _is_exec(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def locate_tool(name, candidates, which=None, isfile=None):
    """PATH first, then the fallback locations. Empty when nothing is usable."""
    check = isfile or _is_exec
    probe = shutil.which if which is None else which
    found = None
    if probe is not None:
        try:
            found = probe(name)
        except Exception:
            found = None
    safe = _safe_tool(found)
    if safe:
        try:
            if check(safe):
                return safe
        except Exception:
            pass
    for path in candidates:
        safe = _safe_tool(path)
        if not safe:
            continue
        try:
            ok = check(safe)
        except Exception:
            ok = False
        if ok:
            return safe
    return ""


def find_avconvert(which=None, isfile=None):
    return locate_tool("avconvert", AVCONVERT_CANDIDATES, which=which, isfile=isfile)


def parse_clock(text):
    """Seconds from 0:05, 1:02:03, or 90. None when it is not a clock time."""
    raw = str(text or "").strip()
    if not re.fullmatch(_CLOCK_RE_TEXT, raw):
        return None
    if ":" not in raw:
        return float(raw)
    parts = raw.split(":")
    try:
        nums = [float(part) for part in parts]
    except ValueError:
        return None
    if any(num < 0 for num in nums):
        return None
    if len(nums) == 2:
        hours = 0
        minutes, seconds = nums
    else:
        hours, minutes, seconds = nums
    if hours != int(hours) or minutes != int(minutes):
        return None
    if int(minutes) >= 60 or seconds >= 60:
        return None
    return int(hours) * 3600 + int(minutes) * 60 + seconds


def format_clock(seconds):
    """ffmpeg -ss / -to clock. Whole seconds stay HH:MM:SS."""
    total_ms = int(round(float(seconds) * 1000.0))
    if total_ms < 0:
        total_ms = 0
    hours, rem = divmod(total_ms, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    secs, millis = divmod(rem, 1000)
    if millis:
        return "{0:02d}:{1:02d}:{2:02d}.{3:03d}".format(hours, minutes, secs, millis)
    return "{0:02d}:{1:02d}:{2:02d}".format(hours, minutes, secs)


def trim_bounds(text):
    """(start, end) seconds from 'from 0:05 to 0:30', or None."""
    match = re.search(
        r"\bfrom\s+({0})\s+to\s+({0})\b".format(_CLOCK_RE_TEXT),
        str(text or ""),
        re.I,
    )
    if not match:
        return None
    start = parse_clock(match.group(1))
    end = parse_clock(match.group(2))
    if start is None or end is None:
        return None
    return start, end


def output_path(src, action, exists=None):
    """A free path beside src. Never the source path, never an existing file."""
    check = os.path.exists if exists is None else exists
    folder = os.path.dirname(os.path.abspath(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    suffix, out_ext = {
        "audio": (" audio", ".m4a"),
        "trim": (" trimmed", ".mp4"),
        "compress": (" small", ".mp4"),
        "mp4": ("", ".mp4"),
    }[action]
    if suffix:
        names = [stem + suffix + out_ext]
    else:
        names = [stem + out_ext, stem + " converted" + out_ext]
    number = 2
    while number < 100:
        for name in names:
            dest = os.path.join(folder, name)
            if os.path.abspath(dest) == os.path.abspath(src):
                continue
            try:
                taken = bool(check(dest))
            except Exception:
                taken = True
            if not taken:
                return dest
        names = ["{0}{1} {2}{3}".format(stem, suffix or " converted", number, out_ext)]
        number += 1
    raise RuntimeError("no free video name")


def ffmpeg_command(action, ffmpeg, src, dest, start=None, end=None):
    """One ffmpeg argv. No -y, so an existing file is not replaced."""
    head = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", src]
    if action == "trim":
        return head + [
            "-ss", format_clock(start),
            "-to", format_clock(end),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-movflags", "+faststart",
            dest,
        ]
    if action == "compress":
        return head + [
            "-vf", "scale=-2:720",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "32",
            "-c:a", "aac",
            "-b:a", "96k",
            "-movflags", "+faststart",
            dest,
        ]
    if action == "audio":
        return head + ["-vn", "-c:a", "aac", "-b:a", "128k", dest]
    return head + [
        "-c:v", "libx264",
        "-c:a", "aac",
        "-movflags", "+faststart",
        dest,
    ]


def avconvert_command(action, avconvert, src, dest):
    """AVFoundation preset export. No --replace, so an existing file stays."""
    preset = AVCONVERT_PRESETS[action]
    return [avconvert, "--source", src, "--preset", preset, "--output", dest]


def _apple_quote(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def notification_command(message):
    script = 'display notification "{0}" with title "Hey Jev"'.format(_apple_quote(message))
    return ["osascript", "-e", script]


def _run_tool(args, timeout=600):
    """subprocess argv list. A string would be a shell command, so it is refused."""
    if isinstance(args, (str, bytes)) or not isinstance(args, (list, tuple)):
        raise TypeError("video tools take an argument list")
    result = subprocess.run(
        [str(part) for part in args],
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    err = (result.stderr or "").strip()
    if err:
        _log(err)
    if result.returncode:
        detail = err or (result.stdout or "").strip() or "command failed"
        raise RuntimeError(detail)
    return result.stdout or ""


def classify_video(path, isfile=None):
    """(kind, path). kind is ok, missing, type, or bad."""
    text = str(path or "")
    if not text or "\x00" in text or "\n" in text or "\r" in text:
        return "bad", ""
    expanded = os.path.abspath(os.path.expanduser(text))
    check = os.path.isfile if isfile is None else isfile
    if not is_video_extension(expanded):
        return "type", ""
    try:
        found = bool(check(expanded))
    except Exception:
        found = False
    if not found:
        return "missing", ""
    return "ok", expanded


def video_source(book=None, isfile=None):
    """The last recording, else the last capture when that capture is a video."""
    target = book if book is not None else BOOK
    candidates = []
    video = getattr(target, "video", None)
    if video:
        candidates.append(video)
    last = (target.last or {}).get("path") if target.last else ""
    if last and last not in candidates:
        candidates.append(last)
    if not candidates:
        return "none", ""
    saw_missing = False
    saw_type = False
    for path in candidates:
        kind, expanded = classify_video(path, isfile=isfile)
        if kind == "ok":
            return "ok", expanded
        if kind == "missing":
            saw_missing = True
        elif kind == "type":
            saw_type = True
    if saw_missing:
        return "missing", ""
    if saw_type:
        return "type", ""
    return "none", ""


def _source_sentence(kind):
    if kind == "missing":
        return "I couldn't find that video."
    if kind == "type" or kind == "bad":
        return "That isn't a video."
    return CHOOSE_HINT


def _resolve_ffmpeg(explicit, which=None, isfile=None):
    if explicit is not _AUTO:
        return str(explicit or "")
    if which is None and isfile is None:
        return find_ffmpeg() or ""
    return locate_tool("ffmpeg", FFMPEG_CANDIDATES, which=which, isfile=isfile)


def _resolve_avconvert(explicit, which=None, isfile=None):
    if explicit is not _AUTO:
        return str(explicit or "")
    return find_avconvert(which=which, isfile=isfile)


def prepare_video(action, text="", book=None, ffmpeg=_AUTO, avconvert=_AUTO,
                  which=None, tool_isfile=None, file_isfile=None, exists=None):
    """The argv and the lines to speak, or an immediate sentence and no argv."""
    name = _ACTIONS.get(str(action or ""), "")
    if name not in _WORKING:
        return {"now": "I can't do that to a video."}
    start = end = None
    if name == "trim":
        bounds = trim_bounds(text)
        if bounds is None:
            return {"now": TRIM_HINT}
        start, end = bounds
        if end <= start:
            return {"now": "The end time has to be after the start."}
    kind, src = video_source(book, isfile=file_isfile)
    if kind != "ok":
        return {"now": _source_sentence(kind)}
    ff = _safe_tool(_resolve_ffmpeg(ffmpeg, which=which, isfile=tool_isfile))
    av = _safe_tool(_resolve_avconvert(avconvert, which=which, isfile=tool_isfile))
    try:
        dest = output_path(src, name, exists=exists)
    except Exception as exc:
        _log(exc)
        return {"now": _FAIL[name]}
    if os.path.abspath(dest) == os.path.abspath(src):
        return {"now": _FAIL[name]}
    if ff:
        args = ffmpeg_command(name, ff, src, dest, start=start, end=end)
        tool = "ffmpeg"
    elif name in AVCONVERT_PRESETS and av:
        args = avconvert_command(name, av, src, dest)
        tool = "avconvert"
    else:
        return {"now": MISSING_FFMPEG}
    return {
        "action": name,
        "args": args,
        "src": src,
        "dest": dest,
        "tool": tool,
        "working": _WORKING[name],
        "done": _DONE[name],
        "fail": _FAIL[name],
    }


def execute_video(plan, run=None):
    """Run the prepared argv. Speak a failure and leave the original in place."""
    runner = run or _run_tool
    src = plan["src"]
    dest = plan["dest"]
    if os.path.abspath(dest) == os.path.abspath(src):
        return plan["fail"]
    try:
        existed = os.path.exists(dest)
    except Exception:
        existed = False
    if existed:
        return plan["fail"]
    try:
        runner(list(plan["args"]), timeout=600)
    except Exception as exc:
        _log(exc)
        _discard_partial(dest, src)
        return plan["fail"]
    if not os.path.isfile(dest) or os.path.abspath(dest) == os.path.abspath(src):
        _discard_partial(dest, src)
        return plan["fail"]
    if os.path.abspath(dest) == os.path.abspath(src):
        return plan["fail"]
    try:
        runner(notification_command(plan["done"]), timeout=30)
    except Exception as exc:
        _log(exc)
    return plan["done"]


def _discard_partial(dest, src):
    if not dest or os.path.abspath(dest) == os.path.abspath(src):
        return
    try:
        if os.path.isfile(dest):
            os.remove(dest)
    except OSError as exc:
        _log(exc)


def spawn_background(target):
    """Daemon thread so a long export does not block the pill."""
    threading.Thread(target=target, name="jev-video", daemon=True).start()


def video_from_text(action, text="", book=None, run=None, ffmpeg=_AUTO, avconvert=_AUTO,
                    which=None, tool_isfile=None, file_isfile=None, exists=None,
                    spawn=None, on_done=None, panel=None):
    """Run one quick action.

    With no spawn, this thread does the export and the return value is the
    sentence to speak when it finishes. spawn starts that work on another
    thread, the return value is the working line, and on_done receives the
    finished sentence.
    """
    name = _ACTIONS.get(str(action or ""), "")
    if name == "choose":
        return choose_video(book=book, panel=panel)
    plan = prepare_video(
        action, text, book=book, ffmpeg=ffmpeg, avconvert=avconvert,
        which=which, tool_isfile=tool_isfile, file_isfile=file_isfile, exists=exists,
    )
    if plan.get("now"):
        if on_done is not None:
            try:
                on_done(plan["now"])
            except Exception as exc:
                _log(exc)
        return plan["now"]

    def work():
        try:
            sentence = execute_video(plan, run=run)
        except Exception as exc:
            _log(exc)
            sentence = plan.get("fail") or "I couldn't do that."
        if on_done is not None:
            try:
                on_done(sentence)
            except Exception as exc:
                _log(exc)
        return sentence

    if spawn is None:
        return work()
    spawn(work)
    return plan["working"]


def _configure_panel(panel):
    panel.setCanChooseFiles_(True)
    panel.setCanChooseDirectories_(False)
    panel.setAllowsMultipleSelection_(False)
    types = [ext[1:] for ext in VIDEO_EXTENSIONS]
    if hasattr(panel, "setAllowedFileTypes_"):
        panel.setAllowedFileTypes_(types)
    return panel


def _open_panel():
    from AppKit import NSOpenPanel
    panel = NSOpenPanel.openPanel()
    return _configure_panel(panel)


def _chosen_path(panel):
    try:
        code = panel.runModal()
    except Exception as exc:
        _log(exc)
        return ""
    if int(code) != 1:
        return ""
    try:
        urls = panel.URLs()
    except Exception as exc:
        _log(exc)
        return ""
    if not urls:
        return ""
    url = urls[0]
    if hasattr(url, "path"):
        return str(url.path() or "")
    return ""


def remember_video(path, book=None):
    """Keep a chosen movie as the last recording without dropping the question."""
    target = book if book is not None else BOOK
    target.video = path
    target.remember(path, "recording")
    return path


def choose_video(book=None, panel=None):
    """Open panel for one video. Cancelled and non-video picks are spoken."""
    opener = panel
    if opener is None:
        try:
            opener = _open_panel()
        except Exception as exc:
            _log(exc)
            return "I couldn't open the video picker."
    else:
        try:
            _configure_panel(opener)
        except Exception as exc:
            _log(exc)
            return "I couldn't open the video picker."
    path = _chosen_path(opener)
    if not path:
        return "Cancelled."
    kind, expanded = classify_video(path)
    if kind != "ok":
        return _source_sentence(kind)
    remember_video(expanded, book=book)
    return (
        "Using that video. Say convert the recording to mp4, "
        "trim the recording from 0:05 to 0:30, compress the recording, "
        "or extract the audio from the recording."
    )
