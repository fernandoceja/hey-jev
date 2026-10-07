"""Screenshots, recordings, share sheets, and Ask handoffs. No real screencapture."""
import os
import signal
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from urllib.parse import quote

import commands
from commands.captures import (
    CAPTURE_ROUTE_KEYS,
    PRIVACY_URL,
    CaptureBook,
    ask_from_text,
    ask_plan,
    ask_subject,
    capture_name,
    captures_folder,
    clipboard_script,
    delete_script,
    email_script,
    execute_ask,
    imessage_plan,
    notes_script,
    recording_clock,
    recording_command,
    recording_status,
    run_capture_menu,
    screenshot_command,
    share_from_text,
    share_with_service,
    start_screen_recording,
    stop_screen_recording,
    take_screenshot,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHEN = datetime(2026, 10, 6, 6, 31, 4, tzinfo=timezone(timedelta(hours=-7)))
STAMP = "2026-10-06 06-31-04"


def _func(source, name):
    start = source.index("def {0}".format(name))
    line_start = source.rfind("\n", 0, start) + 1
    indent = start - line_start
    marker = "\n" + (" " * indent) + "def "
    nxt = source.find(marker, start + 1)
    if nxt < 0:
        nxt = len(source)
    return source[start:nxt]


class _Proc:
    def __init__(self):
        self.signals = []
        self.waited = False

    def send_signal(self, sig):
        self.signals.append(sig)

    def wait(self, timeout=None):
        self.waited = True
        return 0


class TestNames(unittest.TestCase):
    def test_timestamped_names(self):
        self.assertEqual(capture_name("screenshot", "full", WHEN), "Jev Screenshot {0}.png".format(STAMP))
        self.assertEqual(capture_name("screenshot", "area", WHEN), "Jev Area {0}.png".format(STAMP))
        self.assertEqual(capture_name("screenshot", "window", WHEN), "Jev Window {0}.png".format(STAMP))
        self.assertEqual(capture_name("recording", "full", WHEN), "Jev Recording {0}.mov".format(STAMP))

    def test_folder_override_then_env_then_default(self):
        self.assertEqual(captures_folder(override="/tmp/jev-one"), "/tmp/jev-one")
        self.assertEqual(
            captures_folder(env={"JEV_CAPTURES_DIR": "~/Jev From Env"}),
            os.path.abspath(os.path.expanduser("~/Jev From Env")),
        )
        self.assertIn("Jev Captures", captures_folder(env={}))
        self.assertEqual(os.path.basename(captures_folder(override="~/Jev Override")), "Jev Override")

    def test_screencapture_argument_lists(self):
        self.assertEqual(screenshot_command("full", "/tmp/a.png"), ["screencapture", "-x", "/tmp/a.png"])
        self.assertEqual(screenshot_command("area", "/tmp/a.png"), ["screencapture", "-i", "-x", "/tmp/a.png"])
        self.assertEqual(screenshot_command("window", "/tmp/a.png"), ["screencapture", "-iW", "-x", "/tmp/a.png"])
        self.assertEqual(recording_command("/tmp/a.mov"), ["screencapture", "-v", "-x", "/tmp/a.mov"])
        self.assertEqual(recording_command("/tmp/a.mov", mic=True), ["screencapture", "-V", "-x", "/tmp/a.mov"])
        self.assertEqual(recording_clock(0, 65), "1:05")


class TestShots(unittest.TestCase):
    def test_full_screen_remembers_the_file(self):
        calls = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return ""

        book = CaptureBook()
        with tempfile.TemporaryDirectory() as folder:
            spoken = take_screenshot("full", folder=folder, when=WHEN, run=run, book=book)
            path = os.path.join(folder, "Jev Screenshot {0}.png".format(STAMP))
            self.assertEqual(calls, [["screencapture", "-x", path]])
            self.assertEqual(book.last["path"], path)
            self.assertIn("full screen screenshot", spoken)
            self.assertIn(folder, spoken)
            self.assertTrue(spoken.startswith("Saved"))

    def test_escape_cancels_an_area_and_a_permission_error_opens_privacy(self):
        def cancel(args, input=None, timeout=30):
            raise RuntimeError("user cancelled")

        book = CaptureBook()
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(take_screenshot("area", folder=folder, when=WHEN, run=cancel, book=book), "Cancelled.")
            self.assertIsNone(book.last)

        calls = []

        def denied(args, input=None, timeout=30):
            calls.append(list(args))
            if args[0] == "screencapture":
                raise RuntimeError("screen recording not permitted")
            return ""

        with tempfile.TemporaryDirectory() as folder:
            spoken = take_screenshot("full", folder=folder, when=WHEN, run=denied, book=book)
        self.assertIn("Privacy pane", spoken)
        self.assertEqual(calls[-1], ["open", PRIVACY_URL])


class TestRecording(unittest.TestCase):
    def _start(self, text, book, popen, folder):
        return start_screen_recording(text, folder=folder, when=WHEN, book=book, popen=popen, run=lambda *a, **k: "")

    def test_start_stop_and_a_second_start(self):
        seen = []
        proc = _Proc()

        def popen(args):
            seen.append(list(args))
            return proc

        book = CaptureBook()
        with tempfile.TemporaryDirectory() as folder:
            spoken = self._start("record my screen", book, popen, folder)
            self.assertIn("Recording.", spoken)
            self.assertEqual(seen[0][1], "-v")
            self.assertTrue(seen[0][-1].endswith(".mov"))
            self.assertEqual(self._start("record my screen", book, popen, folder), "Already recording.")
            self.assertEqual(len(seen), 1)
            status = recording_status(book, now=book.recording["started"] + 65)
            self.assertEqual(status["clock"], "1:05")
            stopped = stop_screen_recording(book=book, run=lambda *a, **k: "", ffmpeg="")
            self.assertIn(signal.SIGINT, proc.signals)
            self.assertTrue(proc.waited)
            self.assertIsNone(book.recording)
            self.assertTrue(book.last["path"].endswith(".mov"))
            self.assertTrue(stopped.startswith("Saved"))
            self.assertEqual(stop_screen_recording(book=book, ffmpeg=""), "Nothing is recording.")

    def test_mic_flag_and_h264_copy(self):
        proc = _Proc()
        seen = []

        def popen(args):
            seen.append(list(args))
            return proc

        book = CaptureBook()
        calls = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            if "ffprobe" in args[0]:
                return "h264\n"
            return ""

        with tempfile.TemporaryDirectory() as folder:
            spoken = self._start("record my screen with mic", book, popen, folder)
            self.assertIn("mic", spoken)
            self.assertEqual(seen[0][1], "-V")
            stopped = stop_screen_recording(
                book=book, run=run, ffmpeg="/opt/homebrew/bin/ffmpeg",
            )
        ffmpeg_call = next(call for call in calls if call[0].endswith("ffmpeg"))
        self.assertEqual(ffmpeg_call[ffmpeg_call.index("-c") + 1], "copy")
        self.assertTrue(book.last["path"].endswith(".mp4"))
        self.assertIn("MP4", stopped)

    def test_other_codecs_stay_mov(self):
        proc = _Proc()
        book = CaptureBook()
        calls = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return "prores\n"

        with tempfile.TemporaryDirectory() as folder:
            start_screen_recording(
                "record my screen", folder=folder, when=WHEN, book=book,
                popen=lambda args: proc, run=lambda *a, **k: "",
            )
            stop_screen_recording(book=book, run=run, ffmpeg="/opt/homebrew/bin/ffmpeg")
        self.assertTrue(book.last["path"].endswith(".mov"))
        self.assertFalse(any(call[0].endswith("ffmpeg") for call in calls))

    def test_an_immediate_exit_logs_stderr_and_checks_tcc(self):
        from io import StringIO

        class Dead:
            def __init__(self, err):
                self.stderr = StringIO(err)
                self.code = 1

            def poll(self):
                return self.code

        calls = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return ""

        book = CaptureBook()
        with tempfile.TemporaryDirectory() as folder:
            spoken = start_screen_recording(
                "record my screen", folder=folder, when=WHEN, book=book,
                popen=lambda args: Dead("screencapture: declined TCCs\n"), run=run,
            )
        self.assertIn("Privacy pane", spoken)
        self.assertEqual(calls[0][0], "open")
        self.assertIsNone(book.recording)

        book = CaptureBook()
        with tempfile.TemporaryDirectory() as folder:
            spoken = start_screen_recording(
                "record my screen", folder=folder, when=WHEN, book=book,
                popen=lambda args: Dead("could not create movie"), run=lambda *a, **k: "",
            )
        self.assertEqual(spoken, "Couldn't start a recording.")
        self.assertIsNone(book.recording)

    def test_popen_failure_opens_privacy(self):
        calls = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return ""

        def popen(args):
            raise OSError("not permitted")

        book = CaptureBook()
        with tempfile.TemporaryDirectory() as folder:
            spoken = start_screen_recording(
                "start screen recording", folder=folder, when=WHEN, book=book, popen=popen, run=run,
            )
        self.assertIn("Privacy pane", spoken)
        self.assertEqual(calls[0], ["open", PRIVACY_URL])
        self.assertIsNone(book.recording)


class TestShare(unittest.TestCase):
    def _book(self, path):
        book = CaptureBook()
        book.remember(path, "screenshot")
        return book

    def test_notes_mail_and_a_quoted_path(self):
        notes = notes_script("/tmp/a.png")
        self.assertIn('application "Notes"', notes)
        self.assertIn("attachment", notes)
        self.assertNotIn("send", notes.lower())
        self.assertIn("{name:", notes)

        quoted = email_script('/tmp/jev "shot".png', "ada@example.com")
        self.assertIn('\\"', quoted)
        self.assertIn("outgoing message", quoted)
        self.assertIn("ada@example.com", quoted)
        self.assertIn("attachment", quoted)
        self.assertNotIn("send", quoted.lower())
        self.assertNotIn("to recipient", email_script("/tmp/a.png").lower())

        calls = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return ""

        path = "/tmp/shot.png"
        spoken = share_from_text("email it to ada@example.com", book=self._book(path), run=run)
        self.assertIn("Press Send yourself.", spoken)
        self.assertIn("ada@example.com", calls[0][2])
        self.assertNotIn("send", calls[0][2].lower())

    def test_messages_compose_does_not_send(self):
        path = "/tmp/shot.png"
        plan = imessage_plan(path, "Ada")
        self.assertFalse(plan["sends"])
        self.assertEqual(plan["service"], "com.apple.share.Messages.compose")
        shared = []
        calls = []

        def share(service, file_path, recipient=""):
            shared.append((service, file_path, recipient))
            return True

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return ""

        spoken = share_from_text("text it to Ada", book=self._book(path), run=run, share=share)
        self.assertEqual(shared, [("com.apple.share.Messages.compose", path, "Ada")])
        self.assertEqual(calls, [])
        self.assertIn("Press Send yourself.", spoken)

        def closed(service, file_path, recipient=""):
            return False

        spoken = share_from_text("text it", book=self._book(path), run=run, share=closed)
        self.assertEqual(calls[0], ["open", "-a", "Messages"])
        self.assertEqual(calls[1][:2], ["osascript", "-e"])
        self.assertIn("POSIX file", calls[1][2])
        self.assertIn("Paste it", spoken)

    def test_my_love_is_refused_before_any_process(self):
        calls = []
        shared = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return ""

        def share(*args):
            shared.append(args)
            return True

        book = self._book("/tmp/shot.png")
        self.assertIn("won't message", share_from_text("text it to My Love", book=book, run=run, share=share))
        self.assertIn("won't email", share_from_text("email it to My Love", book=book, run=run, share=share))
        self.assertEqual(calls, [])
        self.assertEqual(shared, [])

    def test_finder_copy_and_trash(self):
        path = "/tmp/shot.png"
        book = self._book(path)
        calls = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return ""

        self.assertEqual(share_from_text("show it in finder", book=book, run=run), "Showing it in Finder.")
        self.assertEqual(calls[0], ["open", "-R", path])
        self.assertIn("POSIX file", clipboard_script(path))
        share_from_text("copy the screenshot", book=book, run=run)
        self.assertIn("clipboard", calls[1][2])
        script = delete_script(path)
        self.assertIn('application "Finder"', script)
        self.assertIn("delete POSIX file", script)
        self.assertNotIn("rm ", script)
        spoken = share_from_text("delete the screenshot", book=book, run=run)
        self.assertEqual(spoken, "Moved it to the Trash.")
        self.assertIsNone(book.last)
        self.assertEqual(share_from_text("email it", book=book, run=run), "Take a screenshot or record the screen first.")


class TestAsk(unittest.TestCase):
    def test_subject_picks_capture_or_question(self):
        self.assertEqual(ask_subject("ask chatgpt about this", True, True), "capture")
        self.assertEqual(ask_subject("google that", True, True), "question")
        self.assertEqual(ask_subject("google this", True, True), "capture")
        self.assertEqual(ask_subject("ask chatgpt", True, True), "question")
        self.assertEqual(ask_subject("ask chatgpt about the screenshot", True, True), "capture")
        self.assertEqual(ask_subject("ask chatgpt", False, False), "")

    def test_question_handoffs_prefill_or_copy_and_never_submit(self):
        question = "why is the sky blue?"
        encoded = quote(question, safe="")
        chat = ask_plan("chatgpt", "question", question=question)
        claude = ask_plan("claude", "question", question=question)
        google = ask_plan("google", "question", question=question)
        gemini = ask_plan("gemini", "question", question=question)
        siri = ask_plan("siri", "question", question=question)
        for plan in (chat, claude, google):
            self.assertTrue(plan["prefills"])
            self.assertFalse(plan["submits"])
            self.assertIn(encoded, plan["url"])
            self.assertNotIn("keystroke", str(plan).lower())
        self.assertTrue(chat["url"].startswith("https://chatgpt.com/?q="))
        self.assertTrue(claude["url"].startswith("https://claude.ai/new?q="))
        self.assertTrue(google["url"].startswith("https://www.google.com/search?q="))
        self.assertFalse(gemini["prefills"])
        self.assertFalse(siri["prefills"])
        self.assertIn("Question copied, paste it in.", gemini["speech"])
        self.assertIn("Question copied, paste it in.", siri["speech"])
        self.assertEqual(siri["app"], "Siri")
        self.assertEqual(gemini["url"], "https://gemini.google.com/app")

        calls = []

        def run(args, input=None, timeout=30):
            calls.append((list(args), input))
            return ""

        spoken = execute_ask(chat, run=run)
        self.assertIn("Press Return", spoken)
        self.assertIn((["pbcopy"], question), calls)
        self.assertIn((["open", chat["url"]], None), calls)
        for args, _payload in calls:
            self.assertIn(args[0], ("open", "pbcopy", "osascript"))
            blob = " ".join(args).lower()
            self.assertNotIn("keystroke", blob)
            self.assertNotIn("key code", blob)
            self.assertNotEqual(args[0], "curl")

        refused = []
        self.assertEqual(execute_ask({"submits": True, "speech": "no"}, run=lambda *a, **k: refused.append(a)), "I won't submit that.")
        self.assertEqual(refused, [])

    def test_capture_handoffs_copy_the_file(self):
        path = "/tmp/shot.png"
        chat = ask_plan("chatgpt", "capture", path=path)
        lens = ask_plan("google", "capture", path=path)
        self.assertEqual(chat["app"], "ChatGPT")
        self.assertFalse(chat["prefills"])
        self.assertTrue(chat["reveal"])
        self.assertEqual(chat["copy_file"], path)
        self.assertFalse(lens["prefills"])
        self.assertEqual(lens["url"], "https://lens.google.com/upload")
        self.assertIn("didn't send", lens["speech"].lower())

        calls = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return ""

        execute_ask(lens, run=run)
        self.assertEqual(calls[0][:2], ["osascript", "-e"])
        self.assertEqual(calls[1], ["open", "-R", path])
        self.assertEqual(calls[2], ["open", "https://lens.google.com/upload"])
        claude = ask_plan("claude", "capture", path=path)
        self.assertEqual(claude["app"], "Claude")
        gemini = ask_plan("gemini", "capture", path=path)
        self.assertEqual(gemini["url"], "https://gemini.google.com/app")
        self.assertEqual(ask_plan("siri", "capture", path=path)["app"], "Siri")

    def test_voice_uses_the_book(self):
        calls = []

        def run(args, input=None, timeout=30):
            calls.append((list(args), input))
            return ""

        empty = CaptureBook()
        self.assertIn("screenshot", ask_from_text("ask chatgpt", book=empty, run=run).lower())
        question = CaptureBook()
        question.question = "why is the sky blue?"
        question.remember("/tmp/shot.png", "screenshot")
        spoken = ask_from_text("google that", book=question, run=run)
        self.assertIn("Google is open", spoken)
        self.assertTrue(any(args[0] == "open" and "google.com/search?q=" in args[1] for args, _inp in calls))
        calls.clear()
        spoken = ask_from_text("ask chatgpt about this", book=question, run=run)
        self.assertIn("Copied the capture", spoken)
        self.assertTrue(any(args[:2] == ["open", "-a"] and args[2] == "ChatGPT" for args, _inp in calls))
        self.assertFalse(any("chatgpt.com" in " ".join(args) for args, _inp in calls))


class TestRoutesAndMenu(unittest.TestCase):
    def test_voice_routes_stay_off_the_bridge(self):
        expect = {
            "take a screenshot": "screenshot",
            "screenshot an area": "screenshot_area",
            "screenshot this window": "screenshot_window",
            "start screen recording": "record_start",
            "record my screen": "record_start",
            "record my screen with mic": "record_start",
            "stop recording": "record_stop",
            "save it to notes": "capture_note",
            "email it": "capture_email",
            "email it to ada@example.com": "capture_email",
            "text it to Ada": "capture_imessage",
            "show it in finder": "capture_finder",
            "copy the screenshot": "capture_copy",
            "delete the screenshot": "capture_delete",
            "ask chatgpt about this": "ask_chatgpt",
            "ask chat gpt": "ask_chatgpt",
            "ask claude about that": "ask_claude",
            "ask gemini": "ask_gemini",
            "ask siri about my question": "ask_siri",
            "google that": "ask_google",
            "google this": "ask_google",
            "search google": "ask_google",
            "stop reading": "screen_stop",
            "start focus mode": "focus_on",
        }
        for phrase, key in expect.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
        self.assertIsNone(commands.route_before_api("screenshot the error message"))
        for key in CAPTURE_ROUTE_KEYS:
            self.assertNotIn(key, commands.BRIDGE_ALLOW)

    def test_menu_kinds_call_the_same_functions(self):
        calls = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return ""

        book = CaptureBook()
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.dict(os.environ, {"JEV_CAPTURES_DIR": folder}):
                spoken = run_capture_menu("screenshot_full", book=book, run=run)
            self.assertTrue(spoken.startswith("Saved"))
            self.assertIn(folder, spoken)
        self.assertEqual(calls[0][0], "screencapture")
        self.assertEqual(calls[0][1], "-x")
        self.assertTrue(calls[0][-1].startswith(folder))

        book.remember("/tmp/shot.png", "screenshot")
        book.question = "why is the sky blue?"
        calls.clear()
        spoken = run_capture_menu("ask_question_gemini", book=book, run=run)
        self.assertIn("Question copied, paste it in.", spoken)
        self.assertTrue(any(call == ["open", "https://gemini.google.com/app"] for call in calls))
        calls.clear()
        spoken = run_capture_menu("ask_capture_google", book=book, run=run)
        self.assertTrue(any(call == ["open", "https://lens.google.com/upload"] for call in calls))
        self.assertIn("upload", spoken.lower())

    def test_sources_do_not_submit_or_touch_the_network(self):
        captures = open(os.path.join(ROOT, "commands", "captures.py"), encoding="utf-8").read()
        for banned in ("urllib.request", "requests", "socket", "chat.db", "keystroke", "key code"):
            self.assertNotIn(banned, captures)
        share = _func(captures, "share_with_service")
        self.assertIn("performWithItems_", share)
        self.assertNotIn("sendMessage", share)
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        note_at = siri.index("commands.note_question(text)")
        ask_at = siri.index("ask_llm(text)", note_at)
        self.assertLess(note_at, ask_at)
        actions = _func(siri, "ACTIONS") if "def ACTIONS" in siri else siri
        for key in CAPTURE_ROUTE_KEYS:
            self.assertIn('"{0}"'.format(key), actions)
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        self.assertIn("stop.circle.fill", ui)
        self.assertIn("systemRedColor", ui)
        self.assertIn("showCaptureResult_", ui)
        self.assertIn("_show_capture_choices", ui)
        self.assertIn("take_screenshot", _func(ui, "_capture_for_bar"))
        self.assertEqual(share_with_service.__module__, "commands.captures")


class TestChoicesAndAskJev(unittest.TestCase):
    def test_only_a_tcc_denial_opens_privacy(self):
        from io import StringIO
        from contextlib import redirect_stdout

        def denied(args, input=None, timeout=30):
            if args and args[0] == "screencapture":
                raise RuntimeError("screencapture: declined TCCs")
            return ""

        calls = []

        def record(args, input=None, timeout=30):
            calls.append(list(args))
            if args and args[0] == "screencapture":
                raise RuntimeError("screencapture: declined TCCs")
            return ""

        with tempfile.TemporaryDirectory() as folder:
            with redirect_stdout(StringIO()):
                spoken = take_screenshot("full", folder=folder, when=WHEN, run=record, book=CaptureBook())
        self.assertIn("Privacy pane", spoken)
        self.assertEqual(calls[-1][0], "open")

        def other(args, input=None, timeout=30):
            raise RuntimeError("could not create image from display")

        buf = StringIO()
        with tempfile.TemporaryDirectory() as folder:
            with redirect_stdout(buf):
                spoken = take_screenshot("full", folder=folder, when=WHEN, run=other, book=CaptureBook())
        self.assertEqual(spoken, "Couldn't take a screenshot.")
        self.assertIn("could not create image", buf.getvalue())
        self.assertNotIn("Privacy", spoken)
        self.assertTrue(denied)

    def test_a_recording_error_is_logged_unless_it_is_tcc(self):
        def popen(args):
            raise OSError("no space left on device")

        book = CaptureBook()
        with tempfile.TemporaryDirectory() as folder:
            spoken = start_screen_recording(
                "record my screen", folder=folder, when=WHEN, book=book, popen=popen, run=lambda *a, **k: "",
            )
        self.assertEqual(spoken, "Couldn't start a recording.")
        self.assertIsNone(book.recording)

    def test_open_captures_folder_creates_and_reveals_it(self):
        calls = []

        def run(args, input=None, timeout=30):
            calls.append(list(args))
            return ""

        from commands.captures import open_captures_folder
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, "Jev Captures")
            spoken = open_captures_folder(folder=target, run=run)
            self.assertTrue(os.path.isdir(target))
        self.assertEqual(calls, [["open", target]])
        self.assertIn("Opening", spoken)
        self.assertEqual(commands.route_before_api("open my screenshots"), "captures_open")
        self.assertNotIn("captures_open", commands.BRIDGE_ALLOW)
        self.assertNotIn("ask_jev", commands.BRIDGE_ALLOW)

    def test_voice_ask_jev_uses_the_last_capture(self):
        self.assertEqual(commands.route_before_api("ask jev about this"), "ask_jev")
        self.assertEqual(commands.route_before_api("what's on my screen"), "ask_jev")
        self.assertEqual(commands.route_before_api("read my screen"), "screen_speak")
        from commands.vision import (
            VISION_MODEL, ask_about_capture, cost_log_line, fitted_size, offer_ask_jev,
            sips_commands, vision_body, vision_question,
        )
        self.assertEqual(fitted_size(3000, 2000), (1568, 1045))
        self.assertEqual(fitted_size(800, 600), (800, 600))
        self.assertEqual(vision_question("  "), "Describe what's on screen")
        self.assertEqual(sips_commands("/tmp/a.png", "/tmp/b.jpg")[0][0], "sips")
        self.assertIn("1568", sips_commands("/tmp/a.png", "/tmp/b.jpg")[0])
        self.assertTrue(offer_ask_jev("/tmp/a.png", False))
        self.assertFalse(offer_ask_jev("/tmp/a.mov", False))
        self.assertTrue(offer_ask_jev("/tmp/a.mov", True))
        posted = []

        def post(body, key):
            posted.append((body, key))
            return {"content": [{"type": "text", "text": "A desktop with a calendar."}], "usage": {"cost": 0.0012}}

        from io import StringIO
        from contextlib import redirect_stdout
        buf = StringIO()
        with redirect_stdout(buf):
            spoken = ask_about_capture(
                "/tmp/shot.png", "", post=post, key="test-key",
                prepare=lambda path: ("/tmp/shot.jpg", "image/jpeg"),
                read=lambda path: b"jpeg-bytes",
            )
        self.assertEqual(spoken, "A desktop with a calendar.")
        body, key = posted[0]
        self.assertEqual(key, "test-key")
        self.assertEqual(body["model"], VISION_MODEL)
        self.assertEqual(body["messages"][0]["content"][1]["text"], "Describe what's on screen")
        self.assertEqual(body["messages"][0]["content"][0]["source"]["data"], __import__("base64").b64encode(b"jpeg-bytes").decode("ascii"))
        self.assertNotIn("tool", body)
        line = buf.getvalue()
        self.assertIn("  jev ", line)
        self.assertAlmostEqual(float(line.rsplit("$", 1)[1]), 0.0012)
        self.assertTrue(cost_log_line(VISION_MODEL, 1, 0.0012).startswith("  jev "))
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertIn('LLM_MODEL = "anthropic/claude-haiku-4.5"', siri)
        self.assertIn('command[0] == "ask_jev"', siri)

        def boom(body, key):
            raise RuntimeError("offline")

        self.assertIn("network", ask_about_capture(
            "/tmp/shot.png", "What is this?", post=boom, key="test-key",
            prepare=lambda path: ("/tmp/shot.jpg", "image/jpeg"),
            read=lambda path: b"jpeg-bytes",
        ).lower())
        called = []
        self.assertIn("OpenRouter", ask_about_capture(
            "/tmp/shot.png", "", post=lambda *a, **k: called.append(a), key="",
            prepare=lambda path: ("/tmp/shot.jpg", "image/jpeg"),
            read=lambda path: b"x",
        ))
        self.assertEqual(called, [])
        self.assertEqual(vision_body(VISION_MODEL, "", "abc", "image/jpeg")["messages"][0]["content"][1]["text"], "Describe what's on screen")

    def test_the_choices_panel_lists_ask_jev_first_and_times_out(self):
        from mini_bar import (
            CHOICE_SECONDS, TypedHistory, capture_choice_actions, capture_saved,
            choice_button_frames, choice_due, choice_origin, type_focus_hotkey,
        )
        actions = capture_choice_actions(True)
        self.assertEqual(actions[0]["id"], "ask_jev")
        self.assertTrue(actions[0]["primary"])
        self.assertIn("captures_open", [row["id"] for row in actions])
        frames, _height = choice_button_frames(actions)
        self.assertEqual(frames[0][0]["id"], "ask_jev")
        self.assertGreater(frames[0][3], frames[1][3])
        self.assertFalse(choice_due(0, CHOICE_SECONDS - 0.1, False))
        self.assertTrue(choice_due(0, CHOICE_SECONDS, False))
        self.assertFalse(choice_due(0, CHOICE_SECONDS + 5, True))
        origin = choice_origin((100, 80, 420, 44), (0, 0, 1440, 900), (300, 420))
        self.assertGreater(origin[1], 80 + 44)
        self.assertTrue(capture_saved("Saved a full screen screenshot to /tmp."))
        self.assertTrue(capture_saved("Saved the recording as an MP4 in /tmp."))
        self.assertFalse(capture_saved("Saved it to a new note in Notes."))
        hidden = capture_choice_actions(False)
        self.assertNotEqual(hidden[0]["id"], "ask_jev")
        self.assertTrue(type_focus_hotkey(38, (1 << 18) | (1 << 19)))
        self.assertFalse(type_focus_hotkey(38, (1 << 18) | (1 << 19) | (1 << 20)))
        self.assertFalse(type_focus_hotkey(36, (1 << 18) | (1 << 19)))
        history = TypedHistory()
        history.note_request("  what time is it  ")
        self.assertEqual(history.note_reply("It's 3:45."), "It's 3:45.")
        self.assertEqual(history.note_reply("It's 3:45."), "")
        self.assertIn("You: what time is it", history.text())
        self.assertIn("Jev: It's 3:45.", history.text())

    def test_home_type_field_sits_above_the_cards(self):
        from assistant_layout import DEFAULT_H, DEFAULT_W, layout_window
        home = layout_window(DEFAULT_W, DEFAULT_H)["home"]
        composer = home["composer"]
        history = home["history"]
        card = home["cards"][0]["box"]
        self.assertGreater(composer[1], card[1] + card[3])
        self.assertGreater(history[1], card[1] + card[3])
        self.assertGreater(composer[2], 80)
        doc = home["document"]
        for rect in (composer, home["composer_send"], home["composer_folder"], history):
            self.assertGreaterEqual(rect[0], 0)
            self.assertGreaterEqual(rect[1], 0)
            self.assertLessEqual(rect[0] + rect[2], doc[2] + 0.1)


if __name__ == "__main__":
    unittest.main()
