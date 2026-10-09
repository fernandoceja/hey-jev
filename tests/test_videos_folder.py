"""Open Fernando's Videos folder in Finder. subprocess is mocked, so Finder stays closed."""
import inspect
import os
import tempfile
import unittest
from unittest import mock

import commands
from commands.system import _finder_open_args

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS = "/Users/fernandoceja/Documents/Fernando Ceja/Videos"

PHRASES = (
    "open videos",
    "open my videos",
    "open videos folder",
    "show my videos",
    "please open videos",
    "open videos please",
    "Open Videos.",
    "open my videos!",
    "hey jev, open videos",
    "hey jev, open my videos",
    "hey jev please open videos folder",
    "please hey jev, show my videos",
    "open the videos folder",
    "open my videos folder",
    "show me my videos",
    "  open videos  ",
)

KEPT = {
    "open Apple TV": "app_open",
    "open apple tv": "app_open",
    "open the TV app": "app_open",
    "open TV app": "app_open",
    "open TV": "app_open",
    "open YouTube TV": "app_open",
    "close Apple TV": "app_quit",
    "quit the TV app": "app_quit",
    "open a video file": "video_choose",
    "choose a video": "video_choose",
    "pick a video": "video_choose",
    "convert the recording to mp4": "video_mp4",
    "convert the last recording to mp4": "video_mp4",
    "make the recording an mp4": "video_mp4",
    "trim the recording from 0:05 to 0:30": "video_trim",
    "trim the last recording from 0:05 to 0:30": "video_trim",
    "compress the recording": "video_compress",
    "make the recording smaller": "video_compress",
    "extract the audio from the recording": "video_audio",
    "save the audio from the recording": "video_audio",
    "open downloads": "folder_open",
    "open the desktop folder": "folder_open",
    "show the desktop": "show_desktop",
    "show desktop": "show_desktop",
    "show my screenshots": "captures_open",
    "open my screenshots": "captures_open",
}


def _tv_index(force=False):
    return {
        "vid": "/Applications/Vid.app",
        "tv": "/Applications/TV.app",
        "youtubetv": "/Applications/YouTube TV.app",
    }


class TestVideosFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _folder(self, name="Fernando Ceja"):
        folder = os.path.join(self.tmp.name, name, "Videos")
        os.makedirs(folder)
        return folder

    def _run(self, calls, code=0):
        def fake_run(args, **kwargs):
            self.assertNotIsInstance(args, (str, bytes))
            self.assertIsInstance(args, (list, tuple))
            self.assertNotEqual(kwargs.get("shell"), True)
            calls.append((list(args), kwargs))
            return mock.Mock(returncode=code, stdout="", stderr="open failed" if code else "")
        return fake_run

    def test_the_path_is_a_config_constant_with_spaces(self):
        self.assertEqual(commands.VIDEOS_FOLDER, VIDEOS)
        self.assertEqual(commands.videos_folder_path(), VIDEOS)
        self.assertIn("Fernando Ceja", commands.VIDEOS_FOLDER)
        self.assertGreater(commands.VIDEOS_FOLDER.find(" "), 0)
        self.assertNotIn("~", commands.VIDEOS_FOLDER)
        config = open(os.path.join(ROOT, "commands", "config.py"), encoding="utf-8").read()
        self.assertIn("VIDEOS_FOLDER", config)
        self.assertNotIn("videos_open", open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read())
        self.assertNotIn("VIDEOS_FOLDER", open(os.path.join(ROOT, "secrets_store.py"), encoding="utf-8").read())

    def test_phrases_open_the_folder_and_leave_apps_and_video_tools_alone(self):
        for phrase in PHRASES:
            self.assertEqual(commands.route_before_api(phrase), "videos_open", phrase)
            self.assertNotIn("videos_open", commands.BRIDGE_ALLOW, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)
        self.assertIn("videos_open", commands.ZOE_ALLOW)
        self.assertTrue(commands.zoe_allows("videos_open"))
        for phrase, key in KEPT.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertNotEqual(key, "videos_open", phrase)
        for phrase in ("open video", "show videos", "close videos", "quit videos", "launch videos"):
            self.assertNotEqual(commands.route_before_api(phrase), "videos_open", phrase)

    def test_a_weak_app_guess_does_not_steal_open_videos(self):
        """'videos' can look like a short installed name. The folder still wins."""
        with mock.patch.object(commands.apps, "app_index", _tv_index):
            self.assertTrue(commands.unclear_app_guess("videos"))
            self.assertIsNone(commands.known_app_name("videos"))
            self.assertIsNone(commands.resolve_folder("videos"))
            self.assertEqual(commands.route_before_api("open videos"), "videos_open")
            self.assertEqual(commands.route_before_api("open my videos"), "videos_open")
            self.assertEqual(commands.route_before_api("open videos folder"), "videos_open")
            self.assertEqual(commands.route_before_api("show my videos"), "videos_open")
            for phrase, key in (
                ("open Apple TV", "app_open"),
                ("open the TV app", "app_open"),
                ("open TV", "app_open"),
                ("open YouTube TV", "app_open"),
                ("close Apple TV", "app_quit"),
            ):
                self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertEqual(commands.route_before_api("Open to TV."), "app_open")
            self.assertEqual(
                commands.open_any_app(None, "Open to TV.", {}),
                commands.UNCLEAR_APP,
            )

    def test_apple_tv_still_uses_open_a(self):
        calls = []
        with mock.patch.object(commands.apps, "app_index", _tv_index), \
                mock.patch.object(commands.subprocess, "run", self._run(calls)):
            self.assertEqual(commands.open_any_app(None, "open Apple TV", {}), {"app": "TV"})
            self.assertEqual(commands.open_any_app(None, "open the TV app", {}), {"app": "TV"})
            self.assertEqual(commands.open_any_app(None, "open TV", {}), {"app": "TV"})
            self.assertEqual(commands.open_any_app(None, "open YouTube TV", {}), {"app": "YouTube TV"})
        self.assertEqual(
            [args for args, _kwargs in calls],
            [["open", "-a", "TV"], ["open", "-a", "TV"], ["open", "-a", "TV"],
             ["open", "-a", "YouTube TV"]],
        )

    def test_open_passes_the_spaced_path_as_one_argument(self):
        folder = self._folder()
        calls = []
        with mock.patch.object(commands.subprocess, "run", self._run(calls)):
            spoken = commands.open_videos_folder(folder)
        self.assertEqual(spoken, "Opening your Videos folder.")
        self.assertEqual(spoken, commands.OPENING_VIDEOS)
        self.assertNotEqual(spoken, commands.UNCLEAR_APP)
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args, ["open", folder])
        self.assertEqual(len(args), 2)
        self.assertIn("Fernando Ceja", args[1])
        self.assertIn(" ", args[1])
        self.assertNotIn("shell", kwargs)
        self.assertNotEqual(kwargs.get("shell"), True)
        self.assertTrue(os.path.isdir(folder))

    def test_tilde_expands_without_a_shell_and_the_constant_is_what_opens(self):
        folder = self._folder()
        home = self.tmp.name
        calls = []
        tilde = "~/Fernando Ceja/Videos"
        with mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(commands.subprocess, "run", self._run(calls)):
            expanded = commands.videos_folder_path(tilde)
            spoken = commands.open_videos_folder(tilde)
            self.assertEqual(expanded, folder)
            self.assertNotIn("~", expanded)
            self.assertEqual(spoken, "Opening your Videos folder.")
        self.assertEqual(calls[0][0], ["open", folder])

        calls.clear()
        with mock.patch.object(commands.config, "VIDEOS_FOLDER", folder), \
                mock.patch.object(commands.subprocess, "run", self._run(calls)):
            spoken = commands.open_videos_folder()
        self.assertEqual(spoken, "Opening your Videos folder.")
        self.assertEqual(calls[0][0], ["open", os.path.abspath(folder)])

    def test_a_missing_folder_is_not_created(self):
        missing = os.path.join(self.tmp.name, "Fernando Ceja", "Videos")
        parent = os.path.dirname(missing)
        calls = []
        with mock.patch.object(commands.subprocess, "run", self._run(calls)):
            spoken = commands.open_videos_folder(missing)
        self.assertEqual(spoken, "Your Videos folder isn't there.")
        self.assertEqual(spoken, commands.MISSING_VIDEOS)
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(missing))
        self.assertFalse(os.path.exists(parent))

        calls.clear()
        with mock.patch.object(commands.config, "VIDEOS_FOLDER", missing), \
                mock.patch.object(commands.subprocess, "run", self._run(calls)):
            spoken = commands.open_videos_folder()
        self.assertEqual(spoken, "Your Videos folder isn't there.")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.isdir(missing))

    def test_a_failed_open_does_not_create_the_folder(self):
        folder = self._folder()
        calls = []
        with mock.patch.object(commands.subprocess, "run", self._run(calls, code=1)):
            spoken = commands.open_videos_folder(folder)
        self.assertEqual(spoken, "I couldn't open your Videos folder.")
        self.assertEqual(calls[0][0], ["open", folder])
        self.assertTrue(os.path.isdir(folder))

    def test_a_string_command_is_refused_before_subprocess(self):
        with self.assertRaises(TypeError):
            _finder_open_args(["open", VIDEOS])
        with self.assertRaises(TypeError):
            _finder_open_args(None)
        args = _finder_open_args(VIDEOS)
        self.assertEqual(args, ["open", VIDEOS])
        self.assertIsInstance(args, list)
        source = inspect.getsource(commands.open_videos_folder)
        source += inspect.getsource(commands.videos_folder_path)
        source += inspect.getsource(_finder_open_args)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("makedirs", source)
        self.assertNotIn("mkdir", source)
        self.assertIn('["open", target]', source)

    def test_siri_wires_the_action_and_help_mentions_it(self):
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertIn('"videos_open": lambda _arg, _text: commands.open_videos_folder()', siri)
        self.assertIn("Open videos. Open my videos. Show my videos.", siri)
        self.assertIn("Videos folder", commands.speak_help())
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertIn("Opening your Videos folder.", readme)
        self.assertIn(VIDEOS, readme)
        self.assertIn("VIDEOS_FOLDER", readme)


if __name__ == "__main__":
    unittest.main()
