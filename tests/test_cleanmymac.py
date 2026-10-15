"""CleanMyMac Smart Care scan: phrases, routing, and scan-only behavior."""
import unittest

import commands
from commands import cleanmymac as cmm
from commands.config import BRIDGE_ALLOW
from commands.routing import route_before_api

APP5 = "/Applications/CleanMyMac_5.app"
APPX = "/Applications/CleanMyMac X.app"


class FakeRun:
    def __init__(self, out="scanning", fail_open=False, fail_script=False):
        self.calls, self.out = [], out
        self.fail_open, self.fail_script = fail_open, fail_script

    def __call__(self, argv, timeout=30):
        self.calls.append(list(argv))
        if argv[0] == "open" and self.fail_open:
            raise RuntimeError("no")
        if argv[0] == "osascript":
            if self.fail_script:
                raise RuntimeError("not authorized")
            return self.out + "\n"
        return ""


def only(*paths):
    return lambda p: p in paths


class Phrases(unittest.TestCase):
    YES = (
        "run CleanMyMac", "CleanMyMac scan", "scan my Mac", "clean my Mac",
        "clean mymac", "Clean MyMac.", "cleanmy mac", "clean my mack",
        "hey jev, clean my mac please", "run a full scan of my mac",
        "run cleanmymac scan", "start a cleanmymac scan", "cleanmymac smart care",
        "run smart care", "smart care scan", "CleanMyMac X scan", "full mac scan",
        "can you scan my mac",
    )
    NO = (
        "open CleanMyMac", "open clean my mac", "clean up", "clean my room",
        "scan this document", "clean my mac and mute", "quit cleanmymac",
        "play zelda", "screenshot", "",
    )

    def test_phrases_route_to_scan(self):
        for text in self.YES:
            self.assertTrue(cmm.is_cleanmymac_phrase(text), text)
            self.assertEqual(route_before_api(text), "cleanmymac_scan", text)

    def test_other_phrases_do_not(self):
        for text in self.NO:
            self.assertFalse(cmm.is_cleanmymac_phrase(text), text)
            self.assertNotEqual(route_before_api(text), "cleanmymac_scan", text)

    def test_open_cleanmymac_still_opens_the_app(self):
        self.assertNotEqual(route_before_api("open CleanMyMac"), "cleanmymac_scan")
        self.assertEqual(commands.known_app_name("clean my mac"), "CleanMyMac_5")

    def test_games_still_win(self):
        self.assertEqual(route_before_api("play mario sunshine"), "game_open")


class ScanOnly(unittest.TestCase):
    def test_not_mac(self):
        run = FakeRun()
        self.assertEqual(cmm.start_scan(platform="linux", exists=only(APP5), run=run), cmm.CMM_NOT_MAC)
        self.assertEqual(run.calls, [])

    def test_not_installed(self):
        run = FakeRun()
        self.assertEqual(cmm.start_scan(platform="darwin", exists=only(), run=run), cmm.CMM_NOT_INSTALLED)
        self.assertEqual(run.calls, [])

    def test_scan_started_on_cleanmymac_5(self):
        run = FakeRun("scanning")
        self.assertEqual(cmm.start_scan(platform="darwin", exists=only(APP5), run=run), cmm.CMM_SCANNING)
        self.assertEqual(run.calls[0], ["open", APP5])
        self.assertEqual(run.calls[1][0], "osascript")
        self.assertEqual(run.calls[1][-1], "com.macpaw.CleanMyMac5")

    def test_cleanmymac_x_bundle(self):
        run = FakeRun("scanning")
        cmm.start_scan(platform="darwin", exists=only(APPX), run=run)
        self.assertEqual(run.calls[0], ["open", APPX])
        self.assertEqual(run.calls[1][-1], "com.macpaw.CleanMyMac4")

    def test_already_scanning(self):
        self.assertEqual(cmm.start_scan(platform="darwin", exists=only(APP5), run=FakeRun("already")),
                         cmm.CMM_ALREADY)

    def test_honest_fallback_when_scan_not_pressed(self):
        for run in (FakeRun("noscan"), FakeRun("nowindow"), FakeRun(fail_script=True)):
            self.assertEqual(cmm.start_scan(platform="darwin", exists=only(APP5), run=run), cmm.CMM_PRESS_SCAN)
        self.assertIn("Press Scan", cmm.CMM_PRESS_SCAN)

    def test_open_failure(self):
        self.assertEqual(cmm.start_scan(platform="darwin", exists=only(APP5), run=FakeRun(fail_open=True)),
                         cmm.CMM_FAILED)

    def test_script_only_presses_scan(self):
        script = cmm.SMART_CARE_SCRIPT
        self.assertIn('if n is "Scan" then', script)
        for word in cmm.FORBIDDEN_BUTTONS:
            self.assertNotIn('"%s"' % word, script, word)
        self.assertNotIn("keystroke", script)
        self.assertNotIn("do shell script", script)

    def test_argv_lists_only(self):
        run = FakeRun()
        cmm.start_scan(platform="darwin", exists=only(APP5), run=run)
        for argv in run.calls:
            self.assertIsInstance(argv, list)
            self.assertNotIn("rm", argv)


class MacOnly(unittest.TestCase):
    def test_not_on_the_bridge(self):
        self.assertNotIn("cleanmymac_scan", BRIDGE_ALLOW)

    def test_bridge_refuses_the_phrases(self):
        for text in ("scan my mac", "run cleanmymac", "clean my mac"):
            self.assertIsNone(commands.bridge_allowed(text), text)

    def test_zoe_mode_blocks_it(self):
        self.assertFalse(commands.zoe_allows("cleanmymac_scan"))

    def test_siri_has_the_action(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "siri.py"), encoding="utf-8") as handle:
            self.assertIn('"cleanmymac_scan": lambda', handle.read())


if __name__ == "__main__":
    unittest.main()
