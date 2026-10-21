"""Emulator voice commands. Nothing launches; _run and the process check are faked."""
import os
import tempfile
import unittest
from unittest import mock

import commands
from commands import games

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OPEN = {
    "switch": ("play switch", "open switch", "play nintendo switch", "hey jev play the switch",
               "turn on switch", "play swich", "please open switch"),
    "wiiu": ("play wii u", "play wiiu", "play Wii-U", "play we you", "open wee you",
             "play nintendo wii u", "play wii you"),
    "gamecube": ("play gamecube", "play game cube", "open the gamecube", "play nintendo gamecube"),
}
CLOSE = {
    "switch": ("turn off switch", "close switch", "quit switch", "shut down the switch"),
    "wiiu": ("turn off wii u", "close we you", "quit wiiu"),
    "gamecube": ("turn off gamecube", "close game cube", "quit gamecube"),
}
APPS = {
    "switch": ("/Applications/Ryujinx.app", "org.ryujinx.Ryujinx", "Ryujinx"),
    "wiiu": ("/Applications/Cemu.app", "info.cemu.Cemu", "Cemu"),
    "gamecube": ("/Applications/Dolphin.app", "org.dolphin-emu.dolphin", "Dolphin"),
}


def emu(emu_id):
    return next(g for g in games.GAMES if g["id"] == emu_id)


class RoutingTests(unittest.TestCase):
    def test_open_phrases(self):
        for emu_id, phrases in OPEN.items():
            for p in phrases:
                self.assertEqual(commands.route_before_api(p), "game_open", p)
                self.assertEqual(games.match_game(p)["id"], emu_id, p)
                self.assertIsNone(commands.bridge_allowed(p), p)

    def test_close_phrases(self):
        for emu_id, phrases in CLOSE.items():
            for p in phrases:
                self.assertEqual(commands.route_before_api(p), "game_close", p)
                self.assertEqual(games.match_game_close(p)["id"], emu_id, p)
                self.assertIsNone(commands.bridge_allowed(p), p)

    def test_bare_words_do_nothing(self):
        for p in ("switch", "smash", "melee", "wii u", "gamecube", "we you",
                  "switch to dark mode", "turn off hazard alerts", "open safari"):
            self.assertNotIn(commands.route_before_api(p), ("game_open", "game_close"), p)

    def test_existing_games_unchanged(self):
        self.assertEqual(games.match_game("play mario sunshine")["id"], "sunshine")
        self.assertEqual(games.match_game("play the game ocarina of time")["id"], "ocarina")
        self.assertEqual(games.match_game_close("close zelda")["id"], "ocarina")

    def test_bundles_match_mac(self):
        for emu_id, (app, bundle, process) in APPS.items():
            g = emu(emu_id)
            self.assertEqual(g["apps"][0], app)
            self.assertEqual(g["bundle_id"], bundle)
            self.assertEqual(g["process"], process)

    def test_guardrails(self):
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)
        for key in ("game_open", "game_close"):
            self.assertNotIn(key, commands.BRIDGE_ALLOW)
            self.assertFalse(commands.zoe_allows(key))
        with tempfile.TemporaryDirectory() as tmp:
            commands.set_zoe_mode_path(os.path.join(tmp, "zoe-mode.txt"))
            try:
                commands.enter_zoe_mode()
                for p in ("play switch", "turn off gamecube", "play wii u", "play gamecube"):
                    guard = commands.zoe_guard(p)
                    self.assertEqual(guard["kind"], "speak", p)
                    self.assertNotIn("action", guard)
            finally:
                commands.clear_confirmation()
                commands.clear_zoe_exit()
                commands.set_zoe_mode_path(None)
        src = open(os.path.join(ROOT, "commands", "games.py"), encoding="utf-8").read()
        for bad in ("import socket", ".listen(", ".bind(", "keychain", "get_secret",
                    "urlopen", "http://", "https://", "bridge_"):
            self.assertNotIn(bad, src, bad)


class ActionTests(unittest.TestCase):
    def test_open_uses_app_path(self):
        with mock.patch.object(games, "_run") as run:
            spoken = games.open_game_from_text("play switch", platform="darwin", exists=lambda p: True)
        run.assert_called_once_with(["open", "/Applications/Ryujinx.app"])
        self.assertEqual(spoken, "Firing up the Switch. Have fun!")

    def test_melee_and_slippi_are_gone(self):
        self.assertFalse(any(g["id"] == "melee" for g in games.GAMES))
        for p in ("play melee", "play smash", "open slippi", "turn off melee"):
            self.assertIsNone(games.match_game(p), p)
            self.assertIsNone(games.match_game_close(p), p)
        src = open(os.path.join(ROOT, "commands", "games.py"), encoding="utf-8").read()
        self.assertNotIn("Slippi", src)

    def test_not_installed(self):
        with mock.patch.object(games, "_run") as run:
            spoken = games.open_game_from_text("play wii u", platform="darwin", exists=lambda p: False)
        run.assert_not_called()
        self.assertEqual(spoken, "The Wii U emulator isn't installed on this Mac.")

    def test_not_mac(self):
        with mock.patch.object(games, "_run") as run:
            spoken = games.open_game_from_text("play switch", platform="linux", exists=lambda p: True)
        run.assert_not_called()
        self.assertEqual(spoken, games.GAMES_NOT_MAC)

    def test_close_is_applescript_quit(self):
        state = {"up": True}

        def fake_run(argv, **kw):
            if argv[0] == "osascript":
                state["up"] = False

        with mock.patch.object(games, "_run", side_effect=fake_run) as run:
            spoken = games.close_game_from_text("turn off switch", platform="darwin",
                                                running=lambda p: state["up"], sleep=lambda s: None)
        argv = run.call_args_list[0][0][0]
        self.assertEqual(argv, ["osascript", "-e", 'tell application id "org.ryujinx.Ryujinx" to quit'])
        self.assertEqual(spoken, "Okay, turning off the Switch.")

    def test_close_never_force_kills(self):
        with mock.patch.object(games, "_run") as run:
            spoken = games.close_game_from_text("turn off gamecube", platform="darwin",
                                                running=lambda p: True, sleep=lambda s: None, wait=0.5)
        for call in run.call_args_list:
            self.assertNotIn(call[0][0][0], ("pkill", "kill", "killall"))
        self.assertIn("still open", spoken)

    def test_close_not_running(self):
        with mock.patch.object(games, "_run") as run:
            spoken = games.close_game_from_text("turn off gamecube", platform="darwin",
                                                running=lambda p: False)
        run.assert_not_called()
        self.assertEqual(spoken, "The GameCube isn't running.")
