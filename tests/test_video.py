"""Video quick actions. Mocked tools only. mac_guard blocks a real ffmpeg."""
import os
import tempfile
import unittest

import commands
from commands.captures import CaptureBook
from commands.video import (
    AVCONVERT_PRESETS,
    FFMPEG_CANDIDATES,
    MISSING_FFMPEG,
    VIDEO_ROUTE_KEYS,
    _run_tool,
    avconvert_command,
    choose_video,
    ffmpeg_command,
    format_clock,
    locate_tool,
    output_path,
    parse_clock,
    trim_bounds,
    video_from_text,
)
from mini_bar import capture_choice_actions, choice_panel_box, plus_item

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FF = "/opt/homebrew/bin/ffmpeg"
AV = "/usr/bin/avconvert"

PHRASES = (
    ("convert the recording to mp4", "video_mp4"),
    ("convert the last recording to mp4", "video_mp4"),
    ("convert this video to mp4", "video_mp4"),
    ("convert the video to an mp4", "video_mp4"),
    ("make the recording an mp4", "video_mp4"),
    ("please convert the last recording to mp4", "video_mp4"),
    ("trim the recording from 0:05 to 0:30", "video_trim"),
    ("trim the last recording from 0:05 to 0:30", "video_trim"),
    ("trim this video from 1:02:03 to 1:10:00", "video_trim"),
    ("trim the video from 5 to 30", "video_trim"),
    ("trim it from 0:05 to 0:30", "video_trim"),
    ("please trim the recording from 0:05 to 0:30", "video_trim"),
    ("compress the recording", "video_compress"),
    ("compress the last recording", "video_compress"),
    ("compress this video", "video_compress"),
    ("compress the video", "video_compress"),
    ("make the recording smaller", "video_compress"),
    ("make the last recording smaller", "video_compress"),
    ("extract the audio from the recording", "video_audio"),
    ("extract audio from the recording", "video_audio"),
    ("extract the audio from the last recording", "video_audio"),
    ("extract audio from the last recording", "video_audio"),
    ("extract the audio from this video", "video_audio"),
    ("save the audio from the recording", "video_audio"),
    ("save the audio from the last recording", "video_audio"),
    ("choose a video", "video_choose"),
    ("choose a video file", "video_choose"),
    ("pick a video", "video_choose"),
    ("pick a video file", "video_choose"),
    ("open a video file", "video_choose"),
    ("please choose a video", "video_choose"),
)


class _URL:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class _Panel:
    def __init__(self, path="", code=1):
        self._path = path
        self.code = code
        self.configured = {}

    def setCanChooseFiles_(self, value):
        self.configured["files"] = bool(value)

    def setCanChooseDirectories_(self, value):
        self.configured["dirs"] = bool(value)

    def setAllowsMultipleSelection_(self, value):
        self.configured["multi"] = bool(value)

    def setAllowedFileTypes_(self, types):
        self.configured["types"] = list(types)

    def runModal(self):
        return self.code

    def URLs(self):
        if not self._path:
            return []
        return [_URL(self._path)]


def _write(path, payload):
    with open(path, "wb") as handle:
        handle.write(payload)
    return path


def _read(path):
    with open(path, "rb") as handle:
        return handle.read()


def _runner(calls, fail=False, partial=False):
    def run(args, input=None, timeout=None):
        listed = list(args)
        calls.append(listed)
        if listed and listed[0] == "osascript":
            return ""
        dest = listed[-1]
        if fail:
            if partial:
                _write(dest, b"partial")
            raise RuntimeError("tool failed")
        _write(dest, b"out")
        return ""

    return run


class TestClocks(unittest.TestCase):
    def test_parse_and_format(self):
        self.assertEqual(parse_clock("0:05"), 5)
        self.assertEqual(parse_clock("0:30"), 30)
        self.assertEqual(parse_clock("5"), 5)
        self.assertEqual(parse_clock("90"), 90)
        self.assertEqual(parse_clock("1:02:03"), 3723)
        self.assertAlmostEqual(parse_clock("1:30.5"), 90.5)
        self.assertIsNone(parse_clock("0:75"))
        self.assertIsNone(parse_clock("nope"))
        self.assertIsNone(parse_clock("-1"))
        self.assertIsNone(parse_clock(""))
        self.assertEqual(trim_bounds("trim the recording from 0:05 to 0:30"), (5, 30))
        self.assertEqual(trim_bounds("from 1:02:03 to 1:10:00"), (3723, 4200))
        self.assertIsNone(trim_bounds("trim the recording"))
        self.assertEqual(format_clock(5), "00:00:05")
        self.assertEqual(format_clock(30), "00:00:30")
        self.assertEqual(format_clock(3723), "01:02:03")
        self.assertEqual(format_clock(90.5), "00:01:30.500")


class TestNames(unittest.TestCase):
    def test_suffixes_do_not_overwrite_the_original_or_an_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            src = _write(os.path.join(folder, "Clip.mov"), b"source-bytes")
            kept = _write(os.path.join(folder, "Clip.mp4"), b"keep-me")
            dest = output_path(src, "mp4")
            self.assertEqual(os.path.basename(dest), "Clip converted.mp4")
            self.assertEqual(os.path.dirname(dest), folder)
            self.assertNotEqual(os.path.abspath(dest), os.path.abspath(src))
            self.assertNotEqual(os.path.abspath(dest), os.path.abspath(kept))
            self.assertFalse(os.path.exists(dest))
            plain = _write(os.path.join(folder, "Take.mov"), b"take")
            self.assertEqual(os.path.basename(output_path(plain, "mp4")), "Take.mp4")
            movie = _write(os.path.join(folder, "Take.mp4"), b"original")
            self.assertEqual(os.path.basename(output_path(movie, "mp4")), "Take converted.mp4")
            self.assertEqual(_read(movie), b"original")
            trimmed = output_path(src, "trim")
            self.assertEqual(os.path.basename(trimmed), "Clip trimmed.mp4")
            _write(trimmed, b"already")
            self.assertEqual(os.path.basename(output_path(src, "trim")), "Clip trimmed 2.mp4")
            self.assertEqual(os.path.basename(output_path(src, "compress")), "Clip small.mp4")
            self.assertEqual(os.path.basename(output_path(src, "audio")), "Clip audio.m4a")
            self.assertEqual(_read(src), b"source-bytes")
            self.assertEqual(_read(kept), b"keep-me")


class TestArgv(unittest.TestCase):
    def _movie(self, folder, name="Clip.mov", payload=b"source-bytes"):
        return _write(os.path.join(folder, name), payload)

    def test_ffmpeg_argv_for_each_action(self):
        with tempfile.TemporaryDirectory() as folder:
            src = self._movie(folder, "My Clip.mov")
            book = CaptureBook()
            book.remember(src, "recording")
            cases = (
                ("video_mp4", "convert the recording to mp4", "My Clip.mp4", "mp4", None, None),
                ("video_trim", "trim the recording from 0:05 to 0:30", "My Clip trimmed.mp4", "trim", 5, 30),
                ("video_compress", "compress the recording", "My Clip small.mp4", "compress", None, None),
                ("video_audio", "extract the audio from the recording", "My Clip audio.m4a", "audio", None, None),
            )
            for action, phrase, leaf, kind, start, end in cases:
                calls = []
                spoken = video_from_text(
                    action, phrase, book=book, run=_runner(calls), ffmpeg=FF, avconvert="",
                )
                self.assertTrue(spoken.startswith("Saved"), spoken)
                dest = os.path.join(folder, leaf)
                expected = ffmpeg_command(kind, FF, src, dest, start=start, end=end)
                self.assertEqual(calls[0], expected, action)
                self.assertIsInstance(calls[0], list)
                self.assertNotIn("-y", calls[0])
                self.assertNotIn("shell=True", calls[0])
                self.assertEqual(calls[0][calls[0].index("-i") + 1], src)
                self.assertEqual(calls[0][-1], dest)
                self.assertEqual(calls[1][0], "osascript")
                self.assertIn("display notification", calls[1][2])
                self.assertNotIn("--replace", calls[0])
                self.assertEqual(_read(src), b"source-bytes")
                self.assertEqual(_read(dest), b"out")
                os.remove(dest)

    def test_trim_clock_is_passed_to_ffmpeg(self):
        with tempfile.TemporaryDirectory() as folder:
            src = self._movie(folder)
            book = CaptureBook()
            book.remember(src, "recording")
            calls = []
            video_from_text(
                "video_trim", "trim the last recording from 1:02:03 to 1:10:00",
                book=book, run=_runner(calls), ffmpeg=FF, avconvert="",
            )
            self.assertEqual(calls[0][calls[0].index("-ss") + 1], "01:02:03")
            self.assertEqual(calls[0][calls[0].index("-to") + 1], "01:10:00")

    def test_avconvert_fallback_covers_convert_compress_and_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            src = self._movie(folder)
            book = CaptureBook()
            book.remember(src, "recording")
            expected = {
                "video_mp4": ("Clip.mp4", "mp4"),
                "video_compress": ("Clip small.mp4", "compress"),
                "video_audio": ("Clip audio.m4a", "audio"),
            }
            for action, (leaf, kind) in expected.items():
                calls = []
                spoken = video_from_text(
                    action, "", book=book, run=_runner(calls), ffmpeg="", avconvert=AV,
                )
                dest = os.path.join(folder, leaf)
                self.assertEqual(calls[0], avconvert_command(kind, AV, src, dest), action)
                self.assertEqual(calls[0][calls[0].index("--preset") + 1], AVCONVERT_PRESETS[kind])
                self.assertNotIn("--replace", calls[0])
                self.assertNotIn("-y", calls[0])
                self.assertTrue(spoken.startswith("Saved"), spoken)
                os.remove(dest)

    def test_trim_without_ffmpeg_does_not_call_avconvert(self):
        with tempfile.TemporaryDirectory() as folder:
            src = self._movie(folder)
            book = CaptureBook()
            book.remember(src, "recording")
            calls = []
            spoken = video_from_text(
                "video_trim", "trim the recording from 0:05 to 0:30",
                book=book, run=_runner(calls), ffmpeg="", avconvert=AV,
            )
            self.assertEqual(spoken, MISSING_FFMPEG)
            self.assertIn("brew install ffmpeg", spoken)
            self.assertEqual(calls, [])

    def test_missing_ffmpeg_and_avconvert_is_spoken(self):
        with tempfile.TemporaryDirectory() as folder:
            src = self._movie(folder)
            book = CaptureBook()
            book.remember(src, "recording")
            calls = []
            spoken = video_from_text(
                "video_compress", "compress the recording",
                book=book, run=_runner(calls), ffmpeg="", avconvert="",
            )
            self.assertEqual(spoken, MISSING_FFMPEG)
            self.assertEqual(calls, [])

    def test_homebrew_path_is_used_when_path_misses_ffmpeg(self):
        self.assertIn("/opt/homebrew/bin/ffmpeg", FFMPEG_CANDIDATES)
        self.assertEqual(
            locate_tool("ffmpeg", FFMPEG_CANDIDATES, which=lambda _name: None, isfile=lambda path: path == FF),
            FF,
        )
        self.assertEqual(
            locate_tool("ffmpeg", FFMPEG_CANDIDATES, which=lambda _name: FF, isfile=lambda path: path == FF),
            FF,
        )
        unsafe = "/tmp/ffmpeg; rm -rf /"
        self.assertEqual(
            locate_tool(
                "ffmpeg", FFMPEG_CANDIDATES,
                which=lambda _name: unsafe,
                isfile=lambda path: path == unsafe,
            ),
            "",
        )
        self.assertEqual(
            locate_tool("avconvert", ("/usr/bin/avconvert",), which=lambda _name: None, isfile=lambda path: path == AV),
            AV,
        )
        with tempfile.TemporaryDirectory() as folder:
            src = self._movie(folder)
            book = CaptureBook()
            book.remember(src, "recording")
            calls = []
            video_from_text(
                "video_mp4", "convert the recording to mp4",
                book=book, run=_runner(calls),
                which=lambda _name: None,
                tool_isfile=lambda path: path == FF,
                avconvert="",
            )
            self.assertEqual(calls[0][0], FF)

    def test_a_failure_keeps_the_original_and_drops_a_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            src = self._movie(folder)
            book = CaptureBook()
            book.remember(src, "recording")
            calls = []
            spoken = video_from_text(
                "video_mp4", "", book=book, run=_runner(calls, fail=True, partial=True),
                ffmpeg=FF, avconvert="",
            )
            self.assertEqual(spoken, "I couldn't convert that video.")
            self.assertEqual(len(calls), 1)
            self.assertEqual(_read(src), b"source-bytes")
            self.assertFalse(os.path.exists(os.path.join(folder, "Clip.mp4")))

    def test_existing_mp4_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            src = self._movie(folder)
            kept = _write(os.path.join(folder, "Clip.mp4"), b"keep-me")
            book = CaptureBook()
            book.remember(src, "recording")
            calls = []
            video_from_text(
                "video_mp4", "convert the last recording to mp4",
                book=book, run=_runner(calls), ffmpeg=FF, avconvert="",
            )
            self.assertEqual(os.path.basename(calls[0][-1]), "Clip converted.mp4")
            self.assertEqual(_read(src), b"source-bytes")
            self.assertEqual(_read(kept), b"keep-me")
            self.assertEqual(_read(calls[0][-1]), b"out")

    def test_non_video_and_missing_files_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            png = _write(os.path.join(folder, "Shot.png"), b"png")
            book = CaptureBook()
            book.remember(png, "screenshot")
            calls = []
            spoken = video_from_text(
                "video_mp4", "convert the recording to mp4",
                book=book, run=_runner(calls), ffmpeg=FF, avconvert="",
            )
            self.assertEqual(spoken, "That isn't a video.")
            self.assertEqual(calls, [])
            odd = os.path.join(folder, "nope.mov")
            book.video = odd
            spoken = video_from_text(
                "video_audio", "", book=book, run=_runner(calls), ffmpeg=FF, avconvert="",
            )
            self.assertEqual(spoken, "I couldn't find that video.")
            self.assertEqual(calls, [])
            book.video = os.path.join(folder, "bad\x00name.mov")
            spoken = video_from_text(
                "video_compress", "", book=book, run=_runner(calls), ffmpeg=FF, avconvert="",
            )
            self.assertEqual(spoken, "That isn't a video.")
            spaced = self._movie(folder, "clip; rm.mov", b"safe")
            book.remember(spaced, "recording")
            video_from_text(
                "video_mp4", "", book=book, run=_runner(calls), ffmpeg=FF, avconvert="",
            )
            self.assertEqual(calls[0][calls[0].index("-i") + 1], spaced)
            self.assertEqual(_read(spaced), b"safe")

    def test_trim_needs_an_end_after_the_start(self):
        with tempfile.TemporaryDirectory() as folder:
            src = self._movie(folder)
            book = CaptureBook()
            book.remember(src, "recording")
            calls = []
            self.assertEqual(
                video_from_text("video_trim", "", book=book, run=_runner(calls), ffmpeg=FF, avconvert=""),
                "Say trim the recording from 0:05 to 0:30.",
            )
            self.assertEqual(
                video_from_text(
                    "video_trim", "trim the recording from 0:30 to 0:05",
                    book=book, run=_runner(calls), ffmpeg=FF, avconvert="",
                ),
                "The end time has to be after the start.",
            )
            self.assertEqual(calls, [])

    def test_no_recording_asks_for_one(self):
        calls = []
        spoken = video_from_text(
            "video_mp4", "convert the recording to mp4",
            book=CaptureBook(), run=_runner(calls), ffmpeg=FF, avconvert="",
        )
        self.assertEqual(spoken, "Record the screen first, or say choose a video.")
        self.assertEqual(calls, [])

    def test_the_last_recording_wins_over_a_later_screenshot(self):
        with tempfile.TemporaryDirectory() as folder:
            movie = self._movie(folder)
            png = _write(os.path.join(folder, "Shot.png"), b"png")
            book = CaptureBook()
            book.remember(movie, "recording")
            book.remember(png, "screenshot")
            self.assertEqual(book.video, movie)
            self.assertEqual(book.last["path"], png)
            calls = []
            video_from_text(
                "video_mp4", "convert the last recording to mp4",
                book=book, run=_runner(calls), ffmpeg=FF, avconvert="",
            )
            self.assertEqual(calls[0][calls[0].index("-i") + 1], movie)

    def test_background_thread_speaks_when_the_job_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            src = self._movie(folder)
            book = CaptureBook()
            book.remember(src, "recording")
            calls = []
            started = []
            finished = []

            def spawn(target):
                started.append(target)

            spoken = video_from_text(
                "video_mp4", "convert the recording to mp4",
                book=book, run=_runner(calls), ffmpeg=FF, avconvert="",
                spawn=spawn, on_done=finished.append,
            )
            self.assertEqual(spoken, "Converting the recording to MP4.")
            self.assertEqual(calls, [])
            self.assertEqual(len(started), 1)
            started[0]()
            self.assertEqual(finished, ["Saved the MP4 next to the recording."])
            self.assertEqual(calls[0][0], FF)
            self.assertEqual(calls[1][0], "osascript")

    def test_a_string_command_is_refused_before_subprocess(self):
        with self.assertRaises(TypeError):
            _run_tool("ffmpeg -i clip.mov clip.mp4")

    def test_choose_video_remembers_a_movie_and_rejects_the_rest(self):
        with tempfile.TemporaryDirectory() as folder:
            movie = self._movie(folder, "Picked.mov")
            png = _write(os.path.join(folder, "Shot.png"), b"png")
            book = CaptureBook()
            panel = _Panel(movie, code=1)
            spoken = choose_video(book=book, panel=panel)
            self.assertIn("convert the recording to mp4", spoken)
            self.assertFalse(panel.configured["dirs"])
            self.assertFalse(panel.configured["multi"])
            self.assertTrue(panel.configured["files"])
            self.assertIn("mov", panel.configured["types"])
            self.assertEqual(book.video, movie)
            book = CaptureBook()
            self.assertEqual(choose_video(book=book, panel=_Panel(png, code=1)), "That isn't a video.")
            self.assertIsNone(book.video)
            self.assertEqual(choose_video(book=book, panel=_Panel(movie, code=0)), "Cancelled.")
            self.assertIsNone(book.video)


class TestRoutesMenuAndBridge(unittest.TestCase):
    def test_every_phrase_routes_and_stays_off_the_bridge(self):
        for phrase, key in PHRASES:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            self.assertNotIn(key, commands.BRIDGE_ALLOW, phrase)
        for key in VIDEO_ROUTE_KEYS:
            self.assertNotIn(key, commands.BRIDGE_ALLOW, key)
        kept = {
            "copy the recording": "capture_copy",
            "delete the recording": "capture_delete",
            "stop recording": "record_stop",
            "start screen recording": "record_start",
            "record my screen with mic": "record_start",
            "save the recording to notes": "capture_note",
            "open my screenshots": "captures_open",
            "email the video": "capture_email",
        }
        for phrase, key in kept.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)

    def test_menu_and_sources(self):
        for item_id in VIDEO_ROUTE_KEYS:
            item = plus_item(item_id)
            self.assertIsNotNone(item, item_id)
            self.assertEqual(item["kind"], item_id)
            self.assertTrue(item["symbol"])
        actions = capture_choice_actions(True, video=True)
        ids = [row["id"] for row in actions]
        self.assertEqual(ids[0], "ask_jev")
        for item_id in ("video_mp4", "video_trim", "video_compress", "video_audio"):
            self.assertIn(item_id, ids)
        plain = [row["id"] for row in capture_choice_actions(True)]
        self.assertNotIn("video_mp4", plain)
        box = choice_panel_box(actions)
        host_h = box["buttons"][3]
        for _action, _x, top, _w, height in box["frames"]:
            self.assertGreaterEqual(host_h - top - height, 0)
        video = open(os.path.join(ROOT, "commands", "video.py"), encoding="utf-8").read()
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertIn("shell=False", video)
        self.assertNotIn("shell=True", video)
        self.assertIn("NSOpenPanel", video)
        self.assertNotIn("NSOpenPanel", ui)
        self.assertNotIn("urllib", video)
        self.assertNotIn("socket", video)
        self.assertNotIn("secrets_store", video)
        self.assertNotIn("BRIDGE_ALLOW", video)
        self.assertIn("choose_video", ui)
        self.assertIn("video_from_text", ui)
        self.assertIn("_run_video_kind", ui)
        menu = ui[ui.index("def miniPlusItem_"):ui.index("def _queue_bar_phrase")]
        self.assertIn("_run_video_kind", menu)
        self.assertIn("threading.Thread", menu)
        for key in VIDEO_ROUTE_KEYS:
            self.assertIn('"{0}"'.format(key), siri)
        self.assertIn("brew install ffmpeg", readme)
        self.assertIn("Preset1920x1080", readme)
        self.assertIn("PresetAppleM4A", readme)


if __name__ == "__main__":
    unittest.main()
