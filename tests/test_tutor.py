"""Tutor: schema, retry, local HTML, visuals, and Quick Command routing.

ask_lm is mocked. AppKit is not imported. mac_guard blocks a real Mac call
if a test reaches one. The page is a file under a temp directory.
"""
import json
import os
import subprocess
import unittest
from unittest import mock

import commands
import commands.tutor as tutor
from commands.clipboard_history import CONCEALED_TYPES, Snapshot
from commands.model import openrouter_model
from mini_bar import plus_item, plus_menu, submission
from tests.mac_guard import RealHardwareCall

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GOOD = {
    "title": "The square",
    "steps": [
        {"latex": "x^{2}", "say": "Start with the square.", "note": "A square."},
        {"latex": "2x", "say": "Then take the derivative."},
    ],
    "answer": "2x",
    "visual": {
        "type": "plot",
        "params": {"expression": "x^2", "x_min": -2, "x_max": 2},
    },
}

PHRASES = (
    "tutor me on the quadratic formula",
    "tutor me on sine and cosine",
    "please tutor me on gravity",
    "tutor me on gravity please",
    "hey jev, tutor me on derivatives",
    "hey jev tutor me on derivatives",
    "hey jev please tutor me on derivatives",
    "please hey jev, tutor me on derivatives",
    "Tutor me on the chain rule.",
    "  tutor me on gravity  ",
    "explain this problem",
    "explain this problem.",
    "please explain this problem",
    "hey jev, explain this problem",
    "hey jev please explain this problem",
    "tutor me",
    "tutor me.",
    "please tutor me",
)


def _dumps(payload):
    return json.dumps(payload)


class TestTutorRouting(unittest.TestCase):
    def test_voice_phrases_route_locally_and_stay_off_the_bridge(self):
        for phrase in PHRASES:
            self.assertEqual(commands.route_before_api(phrase), "tutor_explain", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        self.assertNotIn("tutor_explain", commands.BRIDGE_ALLOW)
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        self.assertNotIn("tutor_explain", commands.ZOE_ALLOW)
        self.assertIn("tutor_explain", commands.ZOE_BLOCKED["system"])
        self.assertFalse(commands.zoe_allows("tutor_explain"))
        for phrase in (
            "explain this",
            "explain the problem",
            "explain this problem and mute",
            "what is a tutor",
            "tutoring me on math",
            "please tutor the class",
            "tutor me on sine and cosine and mute",
        ):
            # The last one still matches: the topic may contain "and".
            if phrase.startswith("tutor me on"):
                self.assertEqual(commands.route_before_api(phrase), "tutor_explain", phrase)
            else:
                self.assertNotEqual(commands.route_before_api(phrase), "tutor_explain", phrase)
        self.assertEqual(commands.route_before_api("hazard check"), "info_hazards")
        self.assertEqual(commands.route_before_api("open god's eye"), "gods_eye_open")
        self.assertIn("tutor me on", commands.speak_help())

    def test_the_quick_command_uses_typed_text_or_the_clipboard_phrase(self):
        def quick_rows(menu):
            for item in menu:
                if item.get("id") == "quick":
                    return list(item["items"])
            self.fail("Quick Commands is missing")

        rows = quick_rows(plus_menu())
        self.assertEqual(rows[0]["id"], "websites")
        self.assertEqual(rows[1]["id"], "tutor")
        item = plus_item("tutor")
        self.assertEqual(item["kind"], "text")
        self.assertEqual(item["title"], "Tutor")
        self.assertEqual(item["phrase"], "tutor me")
        self.assertEqual(item["symbol"], "graduationcap")
        self.assertEqual(commands.route_before_api(item["phrase"]), "tutor_explain")
        self.assertEqual(tutor.tutor_command(""), "explain this problem")
        self.assertEqual(tutor.tutor_command("   "), "explain this problem")
        self.assertEqual(
            tutor.tutor_command("It's 3:45.", "It's 3:45."),
            "explain this problem",
        )
        typed = tutor.tutor_command("the chain rule")
        self.assertEqual(typed, "tutor me on the chain rule")
        self.assertEqual(tutor.tutor_command("tutor me on gravity"), "tutor me on gravity")
        self.assertEqual(tutor.tutor_command("explain this problem"), "explain this problem")
        plan = submission(typed)
        self.assertEqual(plan["kind"], "run")
        self.assertEqual(plan["control"], ("text", "tutor me on the chain rule"))
        self.assertFalse(plan["reveal_main"])
        self.assertEqual(commands.route_before_api(plan["control"][1]), "tutor_explain")
        self.assertNotIn("tutor_explain", commands.BRIDGE_ALLOW)

    def test_siri_wires_the_action_and_the_bridge_is_untouched(self):
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        secrets = open(os.path.join(ROOT, "secrets_store.py"), encoding="utf-8").read()
        ui = open(os.path.join(ROOT, "assistant_ui.py"), encoding="utf-8").read()
        setup = open(os.path.join(ROOT, "setup.py"), encoding="utf-8").read()
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertIn(
            '"tutor_explain": lambda _arg, text: commands.explain_from_text(text)',
            siri,
        )
        self.assertIn("Tutor me on the quadratic formula. Explain this problem.", siri)
        self.assertIn('VOICE_ID = "{0}"'.format(tutor.FISH_VOICE_ID), siri)
        menu = ui[ui.index("def miniPlusItem_"):ui.index("def _queue_bar_phrase")]
        self.assertIn('item_id == "tutor"', menu)
        self.assertIn("tutor_command", menu)
        self.assertNotIn("tutor_explain", bridge)
        self.assertNotIn("tutor", bridge)
        self.assertIn("hmac.new", bridge)
        self.assertIn("BRIDGE_ALLOW", bridge)
        self.assertNotIn("tutor", secrets)
        self.assertIn('"resources": ["assets/tutor"]', setup)
        self.assertIn("py2app -A", setup)
        self.assertIn("Tutor", readme)
        self.assertIn("file://", readme)
        self.assertIn("Application Support/Hey Jev/tutor", readme)


class TestTutorSchema(unittest.TestCase):
    def test_a_valid_lesson_keeps_steps_and_optional_notes(self):
        lesson = tutor.validate_lesson(GOOD)
        self.assertEqual(lesson["title"], "The square")
        self.assertEqual(len(lesson["steps"]), 2)
        self.assertEqual(lesson["steps"][0]["note"], "A square.")
        self.assertNotIn("note", lesson["steps"][1])
        self.assertEqual(lesson["answer"], "2x")
        self.assertEqual(lesson["visual"]["type"], "plot")
        bare = dict(GOOD)
        bare.pop("visual")
        self.assertEqual(tutor.validate_lesson(bare)["visual"]["type"], "none")
        none = dict(GOOD)
        none["visual"] = {"type": "none"}
        self.assertEqual(tutor.validate_lesson(none)["visual"]["params"], {})
        vector = dict(GOOD)
        vector["visual"] = {"type": "vector", "params": {"vectors": [{"x": 1, "y": 0}]}}
        self.assertEqual(tutor.validate_lesson(vector)["visual"]["type"], "vector")
        projectile = dict(GOOD)
        projectile["visual"] = {"type": "projectile", "params": {"v0": 10, "angle": 45}}
        self.assertEqual(tutor.validate_lesson(projectile)["visual"]["type"], "projectile")
        fenced = "```json\n{0}\n```".format(_dumps(GOOD))
        self.assertEqual(tutor.parse_json(fenced)["title"], "The square")
        wrapped = "Here you go:\n{0}\nThanks".format(_dumps(GOOD))
        self.assertEqual(tutor.parse_json(wrapped)["answer"], "2x")

    def test_bad_shapes_are_rejected(self):
        cases = []
        missing_steps = dict(GOOD)
        missing_steps["steps"] = []
        cases.append(missing_steps)
        not_steps = dict(GOOD)
        not_steps["steps"] = "nope"
        cases.append(not_steps)
        bad_step = dict(GOOD)
        bad_step["steps"] = [{"latex": "x"}]
        cases.append(bad_step)
        bad_note = dict(GOOD)
        bad_note["steps"] = [{"latex": "x", "say": "x", "note": 3}]
        cases.append(bad_note)
        bad_type = dict(GOOD)
        bad_type["visual"] = {"type": "html", "params": {}}
        cases.append(bad_type)
        bad_params = dict(GOOD)
        bad_params["visual"] = {"type": "plot", "params": ["x"]}
        cases.append(bad_params)
        no_title = dict(GOOD)
        no_title["title"] = "  "
        cases.append(no_title)
        no_answer = dict(GOOD)
        del no_answer["answer"]
        cases.append(no_answer)
        for payload in cases:
            with self.assertRaises(tutor.LessonError):
                tutor.validate_lesson(payload)
        with self.assertRaises(tutor.LessonError):
            tutor.parse_json("not json")
        long = dict(GOOD)
        long["steps"] = [{"latex": "x", "say": "step {0}".format(i)} for i in range(10)]
        self.assertEqual(len(tutor.validate_lesson(long)["steps"]), 8)

    def test_retry_once_then_fail_with_a_clear_status(self):
        calls = []

        def ask(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                return "not json at all"
            return _dumps(GOOD)

        lesson = tutor.fetch_lesson("the chain rule", ask=ask)
        self.assertEqual(len(calls), 2)
        self.assertIn("the chain rule", calls[0])
        self.assertIn("previous reply", calls[1])
        self.assertEqual(lesson["title"], "The square")

        once = []

        def good(prompt):
            once.append(prompt)
            return "```json\n{0}\n```".format(_dumps(GOOD))

        self.assertEqual(tutor.fetch_lesson("gravity", ask=good)["answer"], "2x")
        self.assertEqual(len(once), 1)

        failed = []

        def bad(prompt):
            failed.append(prompt)
            return "still not json"

        with self.assertRaises(tutor.LessonError) as caught:
            tutor.fetch_lesson("gravity", ask=bad)
        self.assertEqual(len(failed), 2)
        self.assertEqual(caught.exception.status, tutor.TUTOR_FAILED)

        raised = []

        def boom(prompt):
            raised.append(prompt)
            raise OSError("offline")

        with self.assertRaises(tutor.LessonError) as caught:
            tutor.fetch_lesson("gravity", ask=boom)
        self.assertEqual(len(raised), 1)
        self.assertEqual(caught.exception.status, tutor.TUTOR_FAILED)

    def test_ask_lm_uses_the_openrouter_chat_path_and_keeps_the_key(self):
        seen = []

        def post(body, key):
            seen.append((body, key))
            return {"choices": [{"message": {"content": _dumps(GOOD)}}]}

        text = tutor.ask_lm("explain derivatives", post=post, key="test-openrouter-key")
        self.assertEqual(seen[0][1], "test-openrouter-key")
        self.assertEqual(seen[0][0]["model"], openrouter_model())
        self.assertEqual(seen[0][0]["messages"][0]["role"], "system")
        self.assertIn("explain derivatives", seen[0][0]["messages"][1]["content"])
        self.assertIn("The square", text)
        called = []

        def refuse(body, key):
            called.append(key)
            return {"choices": [{"finish_reason": "refusal", "message": {"content": ""}}]}

        with self.assertRaises(tutor.LessonError) as caught:
            tutor.ask_lm("nope", post=refuse, key="test-openrouter-key")
        self.assertEqual(caught.exception.status, tutor.TUTOR_FAILED)
        with self.assertRaises(tutor.LessonError) as caught:
            tutor.ask_lm("nope", post=lambda *_args: called.append("posted"), key="")
        self.assertEqual(caught.exception.status, tutor.TUTOR_NEED_KEY)
        self.assertNotIn("posted", called)
        source = open(os.path.join(ROOT, "commands", "tutor.py"), encoding="utf-8").read()
        self.assertIn("OPENROUTER_API_KEY", source)
        self.assertIn("FISH_AUDIO_API_KEY", source)
        self.assertNotIn("sk-", source)
        self.assertNotIn("BRIDGE_ALLOW", source)


class TestTutorPage(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _lesson(self, **overrides):
        payload = {
            "title": "Safe title",
            "steps": [
                {"latex": "x^{2}", "say": "Start with the square."},
                {"latex": "2x", "say": "Then take the derivative."},
            ],
            "answer": "2x",
            "visual": {"type": "none", "params": {}},
        }
        payload.update(overrides)
        return tutor.validate_lesson(payload)

    def test_html_includes_katex_steps_and_escapes_model_text(self):
        hostile = self._lesson(
            title="</title><script>alert(1)</script>",
            steps=[
                {
                    "latex": "x^{2}</script><script>alert(1)</script>",
                    "say": "<img src=x onerror=alert(1)>",
                    "note": "<script>alert(1)</script>",
                },
                {"latex": "2x", "say": "Then take the derivative."},
            ],
            answer="<svg onload=alert(1)>",
            visual={"type": "plot", "params": {"expression": "alert(1)", "x_min": -1, "x_max": 1}},
        )
        path = tutor.write_lesson_page(hostile, root=self.tmp.name)
        html = open(path, encoding="utf-8").read()
        self.assertTrue(path.endswith("lesson.html"))
        self.assertNotIn("/Downloads", path)
        self.assertNotIn(".cos", path)
        self.assertIn('src="katex/katex.min.js"', html)
        self.assertIn('href="katex/katex.min.css"', html)
        self.assertIn('src="three/three.min.js"', html)
        self.assertIn('src="plot.js"', html)
        self.assertIn("x^{2}", html)
        self.assertIn("Then take the derivative.", html)
        self.assertNotIn("<script>alert", html.lower())
        self.assertNotIn("</script><script>", html.lower())
        self.assertNotIn("<img", html.lower())
        self.assertNotIn("<svg", html.lower())
        self.assertIn("\\u003cscript\\u003ealert", html)
        self.assertIn("\\u003cimg", html)
        self.assertNotIn("alert(1)", html.split("lesson-data", 1)[0])
        self.assertNotIn('"expression"', html)
        folder = os.path.dirname(path)
        self.assertTrue(os.path.isfile(os.path.join(folder, "katex", "katex.min.js")))
        self.assertTrue(os.path.isfile(os.path.join(folder, "katex", "fonts", "KaTeX_Main-Regular.woff2")))
        self.assertTrue(os.path.isfile(os.path.join(folder, "three", "three.min.js")))
        self.assertTrue(os.path.isfile(os.path.join(folder, "plot.js")))
        for license_path in (
            os.path.join(folder, "katex", "LICENSE"),
            os.path.join(folder, "three", "LICENSE"),
        ):
            self.assertIn("MIT", open(license_path, encoding="utf-8").read())
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(folder).st_mode & 0o777, 0o700)
        self.assertTrue(
            tutor.page_directory().endswith("Library/Application Support/Hey Jev/tutor")
        )
        with self.assertRaises(tutor.LessonError):
            tutor.page_directory(os.path.expanduser("~/Downloads/.cos"))
        with self.assertRaises(tutor.LessonError):
            tutor.page_directory(os.path.join(os.path.expanduser("~/Downloads"), "tutor"))

    def test_visual_params_map_to_numbers_only(self):
        points = tutor.sample_plot({"expression": "x^2", "x_min": -2, "x_max": 2})
        by_x = {round(point[0], 4): point[1] for point in points}
        self.assertAlmostEqual(by_x[0.0], 0.0, places=4)
        self.assertAlmostEqual(by_x[2.0], 4.0, places=4)
        self.assertAlmostEqual(by_x[-2.0], 4.0, places=4)
        sine = tutor.sample_plot({"expression": "sin(x)", "x_min": 0, "x_max": 1})
        self.assertAlmostEqual(sine[0][1], 0.0, places=4)
        self.assertIsNone(tutor.compile_expression("__import__('os')"))
        self.assertIsNone(tutor.compile_expression("alert(1)"))
        self.assertEqual(
            tutor.map_visual({"type": "plot", "params": {"expression": "alert(1)"}})["type"],
            "none",
        )
        line = tutor.compile_expression("2*x+1")
        self.assertAlmostEqual(line(3), 7.0, places=4)
        arc = tutor.projectile_points({"v0": 10, "angle": 45, "g": 10})
        self.assertAlmostEqual(arc[0][0], 0.0, places=2)
        self.assertAlmostEqual(arc[0][1], 0.0, places=2)
        self.assertEqual(arc[0][2], 0.0)
        self.assertAlmostEqual(arc[-1][0], 10.0, places=1)
        self.assertAlmostEqual(arc[-1][1], 0.0, places=1)
        peak = max(arc, key=lambda point: point[1])
        self.assertAlmostEqual(peak[1], 2.5, places=1)
        mapped = tutor.map_visual({
            "type": "vector",
            "params": {"vectors": [
                {"x": 3, "y": 4, "z": 0, "label": "F"},
                {"x": "1", "y": "2", "label": "<script>"},
            ]},
        })
        self.assertEqual(mapped["type"], "vector")
        self.assertEqual(mapped["vectors"][0]["x"], 3.0)
        self.assertEqual(mapped["vectors"][0]["y"], 4.0)
        self.assertEqual(mapped["vectors"][0]["label"], "F")
        self.assertEqual(mapped["vectors"][1]["label"], "")
        lesson = self._lesson(visual={
            "type": "projectile",
            "params": {"v0": 10, "angle": 45, "g": 10},
        })
        html = tutor.render_html(lesson)
        self.assertIn('"type":"projectile"', html)
        self.assertNotIn("v0", html)

    def test_alias_builds_load_the_vendored_assets_from_the_checkout(self):
        root = tutor.vendor_root()
        self.assertTrue(root.endswith(os.path.join("assets", "tutor")))
        for relative in (
            "plot.js",
            os.path.join("katex", "katex.min.js"),
            os.path.join("katex", "katex.min.css"),
            os.path.join("katex", "LICENSE"),
            os.path.join("katex", "fonts", "KaTeX_Main-Regular.woff2"),
            os.path.join("three", "three.min.js"),
            os.path.join("three", "LICENSE"),
        ):
            self.assertTrue(os.path.isfile(os.path.join(root, relative)), relative)
        three = open(os.path.join(root, "three", "three.min.js"), encoding="utf-8").read(800)
        self.assertIn(".THREE", three)
        katex = open(os.path.join(root, "katex", "katex.min.js"), encoding="utf-8").read(500)
        self.assertIn("katex", katex)


class TestTutorRun(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, text, ask, clipboard="", speak=None, reader=None, show=None, platform="darwin"):
        shown = []

        def opener(path, session):
            shown.append((path, session))
            if show is not None:
                show(path, session)

        status = tutor.explain_from_text(
            text,
            ask=ask,
            clipboard=clipboard,
            show=opener,
            speak=speak,
            platform=platform,
            page_root=self.tmp.name,
            reader=reader,
        )
        return status, shown

    def test_a_topic_opens_the_page_and_speaks_the_first_step(self):
        spoken = []
        asks = []

        def ask(prompt):
            asks.append(prompt)
            return _dumps(GOOD)

        def reader():
            raise AssertionError("clipboard")

        status, shown = self._run(
            "tutor me on the chain rule",
            ask,
            speak=spoken.append,
            reader=reader,
        )
        self.assertEqual(status, tutor.TUTOR_OPENING)
        self.assertEqual(spoken, ["Start with the square."])
        self.assertIn("the chain rule", asks[0])
        self.assertEqual(len(asks), 1)
        path, session = shown[0]
        html = open(path, encoding="utf-8").read()
        self.assertIn("katex.min.js", html)
        self.assertEqual(session.index, 0)
        session.next()
        self.assertEqual(spoken, ["Start with the square.", "Then take the derivative."])
        session.back()
        session.replay()
        self.assertEqual(spoken[-1], "Start with the square.")
        self.assertTrue(session.toggle_mute())
        session.replay()
        self.assertEqual(spoken[-1], "Start with the square.")
        session.toggle_mute()
        session.replay()
        self.assertEqual(spoken[-1], "Start with the square.")

    def test_explain_this_problem_reads_the_clipboard_and_failures_stay_quiet(self):
        asks = []

        def ask(prompt):
            asks.append(prompt)
            return _dumps(GOOD)

        status, shown = self._run("explain this problem", ask, clipboard="find the roots")
        self.assertEqual(status, tutor.TUTOR_OPENING)
        self.assertIn("find the roots", asks[0])
        self.assertTrue(shown)

        empty, shown = self._run("tutor me", ask, clipboard="  ")
        self.assertEqual(empty, tutor.TUTOR_NEED_PROBLEM)
        self.assertEqual(shown, [])

        private_asks = []

        def private_ask(prompt):
            private_asks.append(prompt)
            return _dumps(GOOD)

        secret = "sk-ant-notarealkey"
        status, shown = self._run(
            "explain this problem",
            private_ask,
            clipboard=secret,
        )
        self.assertEqual(status, tutor.TUTOR_PRIVATE)
        self.assertEqual(private_asks, [])
        self.assertEqual(shown, [])

        def concealed():
            kind = next(iter(CONCEALED_TYPES))
            return Snapshot(1, text="the real problem", types=(kind,))

        status, shown = self._run("explain this problem", private_ask, clipboard=None, reader=concealed)
        self.assertEqual(status, tutor.TUTOR_PRIVATE)
        self.assertEqual(private_asks, [])

        failed = []

        def bad(prompt):
            failed.append(prompt)
            return "nope"

        status, shown = self._run("tutor me on gravity", bad, speak=lambda _line: None)
        self.assertEqual(status, tutor.TUTOR_FAILED)
        self.assertEqual(len(failed), 2)
        self.assertEqual(shown, [])

        status, shown = self._run(
            "tutor me on gravity",
            ask,
            platform="linux",
            speak=lambda _line: (_ for _ in ()).throw(AssertionError("spoke")),
        )
        self.assertEqual(status, tutor.TUTOR_NOT_MAC)
        self.assertEqual(shown, [])

    def test_steps_use_the_normal_fish_voice_and_the_panel_is_a_file_url(self):
        played = []

        def fetch(line):
            played.append(("fetch", line))
            return ("/tmp/tutor-step.wav", 12)

        def play(path):
            played.append(("play", path))

        ms = tutor.speak_step("Start with the square.", fetch=fetch, play=play)
        self.assertEqual(played, [
            ("fetch", "Start with the square."),
            ("play", "/tmp/tutor-step.wav"),
        ])
        self.assertEqual(ms, 12)
        with mock.patch("commands.fish_voice.synthesize_speech", return_value=None) as synth:
            tutor._fetch_fish(
                "Start with the square.",
                post=lambda *_args, **_kwargs: None,
                api_key="fish-key",
                voice_id="voice",
                cache_dir=self.tmp.name,
            )
        self.assertIs(synth.call_args.kwargs["dramatic"], False)
        self.assertEqual(synth.call_args.kwargs["api_key"], "fish-key")
        self.assertEqual(synth.call_args.kwargs["voice_id"], "voice")
        source = open(os.path.join(ROOT, "commands", "tutor.py"), encoding="utf-8").read()
        fetch_src = source.split("def _fetch_fish", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("dramatic=False", fetch_src)
        self.assertIn("synthesize_speech", fetch_src)
        speak_src = source.split("def speak_step", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("play_fish_reply", speak_src)
        panel = source.split("def open_tutor_panel", 1)[1]
        self.assertIn('objc.lookUpClass("WKWebView")', panel)
        self.assertIn("NSPanel", panel)
        self.assertIn("loadFileURL_allowingReadAccessToURL_", panel)
        self.assertIn("fileURLWithPath_", panel)
        self.assertIn("def back_", panel)
        self.assertIn("def next_", panel)
        self.assertIn("def replay_", panel)
        self.assertIn("def mute_", panel)
        head = source.split("def open_tutor_panel", 1)[0]
        self.assertNotIn("import AppKit", head)
        self.assertNotIn("from AppKit", head)
        self.assertNotIn("import WebKit", head)
        self.assertNotIn("HTTPServer", source)
        for banned in (".listen(", ".bind(", "socket.socket"):
            self.assertNotIn(banned, source, banned)
        with self.assertRaises(RealHardwareCall):
            subprocess.run(["/usr/bin/true"])


if __name__ == "__main__":
    unittest.main()
