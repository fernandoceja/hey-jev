"""Game port launch commands. subprocess is mocked; nothing opens."""
import os
import unittest
from unittest import mock

import commands
from commands import games

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OCARINA = (
    "play zelda", "open zelda", "launch zelda", "Play Zelda.", "hey jev, play zelda",
    "please play zelda", "ocarina of time", "play ocarina of time", "open ocarina of time",
    "ship of harkinian", "open ship of harkinian", "zelda ocarina", "play zelda ocarina",
    "ship of harkin", "open ship of harkin", "play ocarina",
)
MAJORA = (
    "majora's mask", "play majora's mask", "open majoras mask", "majora’s mask",
    "2 ship", "open 2 ship", "play two ship", "open 2 ship 2 harkinian",
)
NOT_GAMES = ("zelda", "open youtube", "play music", "open videos", "what time is it",
             "play zelda and mute")


class TestGames(unittest.TestCase):
    def test_routes(self):
        for p in OCARINA:
            self.assertEqual(commands.route_before_api(p), "game_open", p)
            self.assertEqual(games.match_game(p)["id"], "ocarina", p)
        for p in MAJORA:
            self.assertEqual(commands.route_before_api(p), "game_open", p)
            self.assertEqual(games.match_game(p)["id"], "majora", p)
        for p in NOT_GAMES:
            self.assertNotEqual(commands.route_before_api(p), "game_open", p)

    def test_not_on_bridge_or_zoe(self):
        self.assertNotIn("game_open", commands.BRIDGE_ALLOW)
        for p in OCARINA + MAJORA:
            self.assertIsNone(commands.bridge_allowed(p), p)
        self.assertFalse(commands.zoe_allows("game_open"))
        for name in ("bridge.py", "secrets_store.py"):
            path = os.path.join(ROOT, "commands", name) if name == "bridge.py" else os.path.join(ROOT, name)
            text = open(path, encoding="utf-8").read()
            self.assertNotIn("game_open", text)
            self.assertNotIn("games", text)
        src = open(os.path.join(ROOT, "commands", "games.py"), encoding="utf-8").read()
        for word in ("import socket", ".bind(", ".listen(", "secrets_store", "find-generic-password"):
            self.assertNotIn(word, src.lower())

    def test_map_paths(self):
        oc, mm = games.GAMES
        self.assertEqual(oc["apps"], ("~/Applications/soh.app", "/Applications/soh.app"))
        self.assertEqual(mm["apps"][0], "~/Applications/2s2h.app")

    def test_opens_user_app_first_then_fallback(self):
        oc = games.GAMES[0]
        home = os.path.expanduser("~/Applications/soh.app")
        with mock.patch.object(games, "_run") as run:
            spoken = games.open_game(oc, platform="darwin", exists=lambda p: True)
        run.assert_called_once_with(["open", home])
        self.assertEqual(spoken, "Opening Ocarina of Time.")
        with mock.patch.object(games, "_run") as run:
            games.open_game(oc, platform="darwin", exists=lambda p: p == "/Applications/soh.app")
        run.assert_called_once_with(["open", "/Applications/soh.app"])

    def test_missing_app_says_not_installed(self):
        with mock.patch.object(games, "_run") as run:
            spoken = games.open_game_from_text("play majora's mask", platform="darwin", exists=lambda p: False)
        run.assert_not_called()
        self.assertEqual(spoken, "Majora's Mask isn't installed yet.")

    def test_not_mac_and_failure(self):
        with mock.patch.object(games, "_run") as run:
            self.assertEqual(games.open_game_from_text("play zelda", platform="linux", exists=lambda p: True),
                             games.GAMES_NOT_MAC)
        run.assert_not_called()
        with mock.patch.object(games, "_run", side_effect=RuntimeError("x")):
            self.assertEqual(games.open_game_from_text("play zelda", platform="darwin", exists=lambda p: True),
                             "I couldn't open Ocarina of Time.")

    def test_quick_command(self):
        from mini_bar import plus_item
        item = plus_item("play_zelda")
        self.assertEqual(item["phrase"], "play zelda")
        self.assertEqual(commands.route_before_api(item["phrase"]), "game_open")
