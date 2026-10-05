"""Mac volume steps, brightness, Focus, and accessibility. Processes are mocked."""
import os
import unittest

import commands
from commands.access import (
    FOCUS_PANE,
    FOCUS_UI_SCRIPT,
    PANES,
    SPEAK_SELECTION_SCRIPT,
    VOICEOVER_SCRIPT,
    ZOOM_SCRIPTS,
    accessibility_status,
    press_zoom,
    read_selection,
    set_access_feature,
    set_voiceover,
    silence_notifications,
    speak_screen,
    stop_reading,
)
from commands.media import change_mac_volume, set_mac_volume
from commands.system import change_brightness

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NEW_KEYS = (
    "brightness_set",
    "notify_off",
    "notify_on",
    "screen_speak",
    "screen_stop",
    "selection_read",
    "voiceover_on",
    "voiceover_off",
    "zoom_on",
    "zoom_off",
    "zoom_in",
    "zoom_out",
    "access_status",
    "access_contrast",
    "access_transparency",
    "access_motion",
    "access_invert",
    "access_filters",
    "access_grayscale",
    "access_display_contrast",
    "access_pointer",
    "access_mono",
    "access_hover",
    "access_sticky",
    "access_slow",
    "access_voice_control",
)


class TestPhrases(unittest.TestCase):
    def test_volume_brightness_and_access_phrases(self):
        phrases = {
            "volume up": "volume_up",
            "raise volume by 20": "volume_up",
            "lower the volume 30 percent": "volume_down",
            "volume to 50": "volume_set",
            "set the volume to 40": "volume_set",
            "mute": "volume_mute",
            "unmute": "volume_unmute",
            "brightness up": "brightness_up",
            "brightness up 30": "brightness_up",
            "brightness to 50": "brightness_set",
            "lower the brightness 30 percent": "brightness_down",
            "silence notifications": "notify_off",
            "do not disturb": "notify_off",
            "turn off do not disturb": "notify_on",
            "start focus mode": "focus_on",
            "read my screen": "screen_speak",
            "stop reading": "screen_stop",
            "read selected text": "selection_read",
            "voiceover on": "voiceover_on",
            "stop voiceover": "voiceover_off",
            "zoom in": "zoom_in",
            "zoom off": "zoom_off",
            "turn on invert colors": "access_invert",
            "grayscale off": "access_grayscale",
            "make the pointer bigger": "access_pointer",
            "reduce motion": "access_motion",
            "contrast up 30": "access_display_contrast",
            "turn on voice control": "access_voice_control",
            "color filters": "access_filters",
            "what accessibility features are on": "access_status",
            "sticky keys off": "access_sticky",
            "mono audio on": "access_mono",
        }
        for phrase, key in phrases.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)

    def test_a_joined_sentence_is_not_one_accessibility_command(self):
        self.assertIsNone(commands.route_before_api("zoom in and open notes"))
        self.assertIsNone(commands.route_before_api("silence notifications and open notes"))

    def test_these_stay_off_the_phone_bridge(self):
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        source = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        for key in NEW_KEYS:
            self.assertNotIn(key, commands.BRIDGE_ALLOW, key)
            self.assertNotIn(key, bridge, key)
            self.assertIn(f'"{key}":', source)
        self.assertIn("commands.silence_notifications", source)
        self.assertIn("commands.change_mac_volume", source)
        self.assertIn("commands.change_brightness", source)


class TestVolume(unittest.TestCase):
    def test_raise_by_20_reads_then_sets_the_clamped_level(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if "output volume of" in args[2]:
                return "30\n"
            return ""

        spoken = change_mac_volume("up", "raise volume by 20", runner=runner)
        self.assertEqual(spoken, "Volume's at 50.")
        self.assertEqual(calls[1][2], "set volume output volume 50")
        calls.clear()

        def plain(args):
            calls.append(list(args))
            if "output volume of" in args[2]:
                return "40\n"
            return ""

        self.assertEqual(change_mac_volume("up", "volume up", runner=plain), "Volume's at 60.")
        self.assertEqual(calls[1][2], "set volume output volume 60")

    def test_lower_and_raise_clamp_at_the_ends(self):
        def runner(args):
            if "output volume of" in args[2]:
                return "10\n" if "down" in seen else "90\n"
            return ""

        seen = "down"
        self.assertEqual(change_mac_volume("down", "lower the volume 30 percent", runner=runner), "Volume's at 0.")
        seen = "up"
        self.assertEqual(change_mac_volume("up", "raise volume by 20", runner=runner), "Volume's at 100.")

    def test_a_step_outside_10_20_30_50_does_not_call_osascript(self):
        calls = []
        spoken = change_mac_volume("up", "raise volume by 15", runner=lambda args: calls.append(list(args)))
        self.assertIn("10, 20, 30, or 50", spoken)
        self.assertEqual(calls, [])

    def test_volume_to_clamps_at_100(self):
        calls = []
        spoken = set_mac_volume(None, "volume to 150", runner=lambda args: calls.append(list(args)))
        self.assertEqual(spoken, "Volume's set to 100.")
        self.assertIn("output volume 100", calls[0][2])
        self.assertEqual(calls[0][:2], ["osascript", "-e"])


class TestBrightness(unittest.TestCase):
    def test_display_services_sets_a_fraction(self):
        seen = {}

        def get():
            return 0.4

        def set_level(level):
            seen["level"] = level
            return 0

        spoken = change_brightness("up", "brightness up 30", display=(get, set_level), cli=False)
        self.assertEqual(spoken, "Brightness is at 70 percent.")
        self.assertAlmostEqual(seen["level"], 0.7)
        spoken = change_brightness("set", "brightness to 50", display=(get, set_level), cli=False)
        self.assertEqual(spoken, "Brightness is at 50 percent.")
        self.assertAlmostEqual(seen["level"], 0.5)

    def test_homebrew_brightness_is_the_next_fallback(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if args[-1] == "-l":
                return "display 0: brightness 0.400000\n"
            return ""

        spoken = change_brightness(
            "up", "brightness up 30", display=False, cli="/opt/homebrew/bin/brightness", runner=runner,
        )
        self.assertEqual(spoken, "Brightness is at 70 percent.")
        self.assertEqual(calls[0], ["/opt/homebrew/bin/brightness", "-l"])
        self.assertEqual(calls[1], ["/opt/homebrew/bin/brightness", "0.70"])

    def test_keys_nudge_when_nothing_else_can_set_a_percent(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            return ""

        plain = change_brightness("up", display=False, cli=False, runner=runner)
        stepped = change_brightness("up", "brightness up 30", display=False, cli=False, runner=runner)
        exact = change_brightness("set", "brightness to 50", display=False, cli=False, runner=runner)
        self.assertEqual(plain, "Brighter.")
        self.assertIn("key code 144", calls[0][2])
        self.assertNotIn("repeat", calls[0][2])
        self.assertIn("5 key steps", stepped)
        self.assertIn("repeat 5 times", calls[1][2])
        self.assertIn("key code 144", calls[1][2])
        self.assertIn("exact percent", exact)
        self.assertEqual(len(calls), 2)

    def test_plain_down_still_uses_the_dim_key(self):
        calls = []
        spoken = change_brightness("down", display=False, cli=False, runner=lambda args: calls.append(list(args)))
        self.assertEqual(spoken, "Dimmer.")
        self.assertIn("key code 145", calls[0][2])


class TestFocusAndReading(unittest.TestCase):
    def test_silence_uses_the_jev_shortcut_when_it_is_verified(self):
        calls = []
        names = []

        def run_shortcut(name):
            names.append(name)
            return None

        spoken = silence_notifications(True, run_shortcut=run_shortcut, runner=lambda args: calls.append(list(args)))
        self.assertEqual(spoken, "Notifications are silenced.")
        self.assertEqual(names, ["Jev Focus On"])
        self.assertEqual(calls, [])

    def test_a_missing_folder_falls_through_to_control_center(self):
        calls = []

        def run_shortcut(_name):
            return "I only run shortcuts in the Jev folder, and I couldn't verify that folder, so I didn't run anything."

        def runner(args):
            calls.append(list(args))
            return ""

        spoken = silence_notifications(False, run_shortcut=run_shortcut, runner=runner)
        self.assertIn("Control Center", spoken)
        self.assertEqual(calls[0][:2], ["osascript", "-e"])
        self.assertEqual(calls[0][2], FOCUS_UI_SCRIPT)
        self.assertIn("ControlCenter", calls[0][2])
        self.assertNotIn("Jev Focus", calls[0][2])

    def test_a_failed_click_opens_focus_settings(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if args[0] == "osascript":
                raise RuntimeError("no checkbox")
            return ""

        spoken = silence_notifications(True, run_shortcut=lambda _name: "missing", runner=runner)
        self.assertIn("I opened Focus settings", spoken)
        self.assertNotIn("Notifications are silenced", spoken)
        self.assertEqual(calls[-1], ["open", FOCUS_PANE])

    def test_voiceover_toggles_only_when_the_state_is_different(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if args[0] == "pgrep":
                return "42\n"
            return ""

        self.assertEqual(set_voiceover(True, runner=runner), "VoiceOver is already on.")
        self.assertEqual(calls[0][:2], ["pgrep", "-x"])
        self.assertNotIn("osascript", [call[0] for call in calls])
        calls.clear()

        def stopped(args):
            calls.append(list(args))
            if args[0] == "pgrep":
                raise RuntimeError("not running")
            return ""

        self.assertEqual(set_voiceover(True, runner=stopped), "VoiceOver is on.")
        script = next(call[2] for call in calls if call[0] == "osascript")
        self.assertEqual(script, VOICEOVER_SCRIPT)
        self.assertIn("key code 96", script)
        self.assertNotIn("option down", script)

    def test_speak_selection_presses_option_escape_only_when_enabled(self):
        calls = []

        def disabled(args):
            calls.append(list(args))
            if args[0] == "defaults":
                return "0\n"
            return ""

        spoken = read_selection(runner=disabled)
        self.assertIn("isn't enabled", spoken)
        self.assertEqual(calls[-1][0], "open")
        self.assertNotIn("osascript", [call[0] for call in calls])

        calls.clear()

        def enabled(args):
            calls.append(list(args))
            if args[0] == "defaults":
                return "1\n"
            return ""

        self.assertEqual(read_selection(runner=enabled), "Reading the selection.")
        script = next(call[2] for call in calls if call[0] == "osascript")
        self.assertEqual(script, SPEAK_SELECTION_SCRIPT)
        self.assertIn("option down", script)
        self.assertNotIn("command down", script)

    def test_speak_screen_does_not_send_a_keystroke(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if args[0] == "defaults":
                raise RuntimeError("missing")
            return ""

        spoken = speak_screen(runner=runner)
        self.assertIn("no fixed shortcut", spoken)
        self.assertIn("voiceover on", spoken)
        self.assertEqual([call[0] for call in calls if call[0] == "osascript"], [])
        self.assertEqual(calls[-1][:2], ["open", PANES["spoken"][0]])

    def test_stop_reading_turns_voiceover_off(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if args[0] == "pgrep":
                return "9\n"
            return ""

        spoken = stop_reading(runner=runner)
        self.assertEqual(spoken, "VoiceOver is off.")
        self.assertIn(VOICEOVER_SCRIPT, [call[2] for call in calls if call[0] == "osascript"])


class TestAccessibility(unittest.TestCase):
    def test_zoom_in_uses_the_option_command_shortcut(self):
        calls = []
        spoken = press_zoom("in", runner=lambda args: calls.append(list(args)))
        self.assertEqual(spoken, "Zooming in.")
        self.assertEqual(calls[0][2], ZOOM_SCRIPTS["in"])
        self.assertIn('keystroke "="', calls[0][2])
        self.assertIn("option down, command down", calls[0][2])

    def test_zoom_on_admits_it_is_a_toggle(self):
        spoken = press_zoom("on", runner=lambda _args: "")
        self.assertIn("toggles Zoom", spoken)
        self.assertIn("Option-Command-8", spoken)

    def test_invert_colors_writes_defaults_and_opens_the_pane(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if args[0] == "defaults" and args[1] == "read":
                return "1\n"
            return ""

        spoken = set_access_feature("invert", "turn on invert colors", runner=runner)
        self.assertIn("may not apply", spoken)
        self.assertIn("I opened Display", spoken)
        self.assertEqual(calls[0], ["defaults", "write", "com.apple.universalaccess", "invertColors", "-bool", "true"])
        self.assertEqual(calls[-1], ["open", PANES["display"][0]])

    def test_grayscale_off_writes_false(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if args[1] == "read":
                return "0\n"
            return ""

        spoken = set_access_feature("grayscale", "grayscale off", runner=runner)
        self.assertIn("Grayscale is off", spoken)
        self.assertEqual(
            calls[0],
            ["defaults", "write", "com.apple.universalaccess", "grayscale", "-bool", "false"],
        )

    def test_voice_control_and_color_filters_only_open_settings(self):
        for feature, text, pane in (
            ("voice_control", "turn on voice control", "voice_control"),
            ("filters", "color filters off", "display"),
        ):
            calls = []
            spoken = set_access_feature(feature, text, runner=lambda args: calls.append(list(args)))
            self.assertTrue(spoken.startswith("I can't"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0], ["open", PANES[pane][0]])
            self.assertNotEqual(calls[0][0], "defaults")

    def test_pointer_and_contrast_move_in_steps(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if args[0] == "defaults" and args[1] == "read" and args[3] == "mouseDriverCursorSize":
                return "1\n"
            if args[0] == "defaults" and args[1] == "read" and args[3] == "contrast":
                return "0.2\n"
            return ""

        pointer = set_access_feature("pointer", "make the pointer bigger", runner=runner)
        self.assertIn("Pointer size is 1.5", pointer)
        self.assertIn(
            ["defaults", "write", "com.apple.universalaccess", "mouseDriverCursorSize", "-float", "1.5"],
            calls,
        )
        calls.clear()
        contrast = set_access_feature("display_contrast", "contrast up", runner=runner)
        self.assertIn("Display contrast is 30 percent", contrast)
        self.assertIn(
            ["defaults", "write", "com.apple.universalaccess", "contrast", "-float", "0.30"],
            calls,
        )
        refused = set_access_feature(
            "display_contrast", "contrast up 15", runner=lambda args: calls.append(list(args)),
        )
        self.assertIn("10, 20, 30, or 50", refused)

    def test_status_reads_preferences_and_does_not_write(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            if args[0] == "pgrep":
                raise RuntimeError("absent")
            if args[0] == "defaults" and args[3] == "invertColors":
                return "1\n"
            if args[0] == "defaults" and args[3] == "reduceMotion":
                return "0\n"
            if args[0] == "defaults" and args[3] == "contrast":
                return "0.4\n"
            if args[0] == "defaults" and args[3] == "mouseDriverCursorSize":
                return "2\n"
            raise RuntimeError("missing")

        spoken = accessibility_status(runner=runner)
        self.assertIn("On: Invert Colors.", spoken)
        self.assertIn("Off:", spoken)
        self.assertIn("Reduce Motion", spoken)
        self.assertIn("VoiceOver", spoken)
        self.assertIn("I can't tell: ", spoken)
        self.assertIn("Zoom", spoken)
        self.assertIn("Display contrast is 40 percent.", spoken)
        self.assertIn("Pointer size is 2.", spoken)
        self.assertFalse(any(call[0] == "defaults" and call[1] == "write" for call in calls))

    def test_scripts_do_not_type_a_password_or_force_quit(self):
        source = open(os.path.join(ROOT, "commands", "access.py"), encoding="utf-8").read()
        self.assertNotIn("import socket", source)
        self.assertNotIn("urllib", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("find-generic-password", source)
        self.assertNotIn("http://", source)
        self.assertNotIn("https://", source)
        self.assertNotIn("key code 53 using {option down, command down}", source)
        joined = "\n".join((FOCUS_UI_SCRIPT, VOICEOVER_SCRIPT, SPEAK_SELECTION_SCRIPT, *ZOOM_SCRIPTS.values()))
        self.assertNotIn("password", joined.lower())
        self.assertNotIn("key code 53 using {option down, command down}", joined)


if __name__ == "__main__":
    unittest.main()
