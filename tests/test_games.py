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
        oc, mm = games.GAMES[:2]
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


CLOSE_OCARINA = ("close zelda", "quit zelda", "Close Zelda.", "hey jev, close zelda",
                 "quit ocarina of time", "close ship of harkinian", "exit the game zelda",
                 "close zelda ocarina", "quit ship of harkin", "close zelda game")
CLOSE_MAJORA = ("close majora's mask", "quit majoras mask", "close 2 ship")


class TestGameClose(unittest.TestCase):
    def test_routes(self):
        for p in CLOSE_OCARINA:
            self.assertEqual(commands.route_before_api(p), "game_close", p)
            self.assertEqual(games.match_game_close(p)["id"], "ocarina", p)
            self.assertIsNone(commands.bridge_allowed(p), p)
        for p in CLOSE_MAJORA:
            self.assertEqual(commands.route_before_api(p), "game_close", p)
            self.assertEqual(games.match_game_close(p)["id"], "majora", p)
        self.assertNotIn("game_close", commands.BRIDGE_ALLOW)
        self.assertFalse(commands.zoe_allows("game_close"))
        self.assertEqual(commands.route_before_api("quit safari"), "app_quit")
        self.assertNotEqual(commands.route_before_api("close zelda and mute"), "game_close")

    def test_osascript_quit_by_bundle(self):
        state = {"up": True}
        def fake(args, **kw):
            if args[0] == "osascript":
                state["up"] = False
        with mock.patch.object(games, "_run", side_effect=fake) as run:
            spoken = games.close_game_from_text("close zelda", platform="darwin",
                                                running=lambda p: state["up"], sleep=lambda s: None)
        args = run.call_args_list[0][0][0]
        self.assertEqual(args[0], "osascript")
        self.assertIn('id "com.shipofharkinian.ShipOfHarkinian"', args[2])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(spoken, "Closing Ocarina of Time.")

    def test_minus_128_but_process_gone_is_success(self):
        # Dolphin: osascript errors -128 "User canceled" yet exits cleanly a moment later.
        checks = {"n": 0}
        def running(p):
            checks["n"] += 1
            return checks["n"] < 4
        calls = []
        def fake(args, **kw):
            calls.append(list(args))
            if args[0] == "osascript":
                raise RuntimeError("execution error: User canceled. (-128)")
        naps = []
        with mock.patch.object(games, "_run", side_effect=fake):
            spoken = games.close_game_from_text("close mario sunshine", platform="darwin",
                                                running=running, sleep=naps.append)
        self.assertEqual(spoken, "Closing Super Mario Sunshine.")
        self.assertEqual([c[0] for c in calls], ["osascript"])
        self.assertIn('id "org.dolphin-emu.dolphin"', calls[0][2])
        self.assertTrue(naps)

    def test_still_running_falls_back_to_pkill(self):
        state = {"up": True}
        calls = []
        def fake(args, **kw):
            calls.append(list(args))
            if args[0] == "osascript":
                raise RuntimeError("-128")
            if args[0] == "pkill":
                state["up"] = False
        naps = []
        with mock.patch.object(games, "_run", side_effect=fake):
            spoken = games.close_game_from_text("quit ocarina of time", platform="darwin",
                                                running=lambda p: state["up"], sleep=naps.append)
        self.assertEqual(calls[-1], ["pkill", "-x", "soh"])
        self.assertEqual(spoken, "Closing Ocarina of Time.")
        self.assertAlmostEqual(sum(naps), games.CLOSE_WAIT_SECONDS, delta=0.5)

    def test_pkill_and_still_running_fails(self):
        with mock.patch.object(games, "_run", side_effect=RuntimeError("x")):
            self.assertEqual(games.close_game_from_text("close zelda", platform="darwin",
                                                        running=lambda p: True, sleep=lambda s: None),
                             "I couldn't close Ocarina of Time.")
        with mock.patch.object(games, "_run"):
            self.assertEqual(games.close_game_from_text("close mario sunshine", platform="darwin",
                                                        running=lambda p: True, sleep=lambda s: None),
                             "I couldn't close Super Mario Sunshine.")

    def test_not_running_and_not_mac(self):
        with mock.patch.object(games, "_run") as run:
            self.assertEqual(games.close_game_from_text("close majora's mask", platform="darwin", running=lambda p: False),
                             "Majora's Mask isn't running.")
            self.assertEqual(games.close_game_from_text("close zelda", platform="linux"), games.GAMES_NOT_MAC)
        run.assert_not_called()

    def test_running_check_uses_exact_pgrep(self):
        with mock.patch.object(games, "_run") as run:
            self.assertTrue(games._is_running("soh"))
        run.assert_called_once_with(["pgrep", "-x", "soh"])


SUNSHINE = ("play mario sunshine", "play super mario sunshine", "super mario sunshine",
            "mario sunshine", "hey jev, play mario sunshine",
            "launch super mario sunshine")


class TestDolphinGames(unittest.TestCase):
    def test_routes(self):
        for p in SUNSHINE:
            self.assertEqual(commands.route_before_api(p), "game_open", p)
            self.assertEqual(games.match_game(p)["id"], "sunshine", p)
        for p in ("sunshine", "play sunshine", "open sunshine", "close sunshine"):
            self.assertIsNone(games.match_game(p), p)
            self.assertIsNone(games.match_game_close(p), p)
            self.assertFalse(games.is_game_phrase(p), p)
            self.assertNotIn(commands.route_before_api(p), ("game_open", "game_close"), p)
        self.assertEqual(games.match_game_close("close mario sunshine")["id"], "sunshine")

    def test_not_on_bridge(self):
        for p in SUNSHINE:
            self.assertIsNone(commands.bridge_allowed(p), p)

    def test_opens_dolphin_with_rom(self):
        g = games.match_game("play mario sunshine")
        rom = os.path.expanduser("~/Games/GameCube/Super Mario Sunshine (USA, Canada).ciso")
        with mock.patch.object(games, "_run") as run:
            spoken = games.open_game(g, platform="darwin", exists=lambda p: True)
        run.assert_called_once_with(["open", "-a", "/Applications/Dolphin.app", "--args", "-e", rom])
        self.assertEqual(spoken, "Opening Super Mario Sunshine.")

    def test_missing_rom_or_not_mac(self):
        g = games.match_game("play mario sunshine")
        with mock.patch.object(games, "_run") as run:
            self.assertEqual(games.open_game(g, platform="darwin", exists=lambda p: p.endswith(".app")),
                             "Super Mario Sunshine isn't installed yet.")
            self.assertEqual(games.open_game(g, platform="linux"), games.GAMES_NOT_MAC)
        run.assert_not_called()

    def test_data_driven_helper(self):
        g = games.dolphin_game("x", "X", "X.iso", ("x game", "xg"))
        self.assertEqual(g["rom"], "~/Games/GameCube/X.iso")
        self.assertEqual(g["needs_verb"], ("xg",))
