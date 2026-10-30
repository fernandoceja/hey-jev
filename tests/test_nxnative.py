import os
import unittest

import commands
import mini_bar
from commands import config, games, nxnative

HOL = "/Applications/High On Life.app"
PORTS = [{"id": "nx_1", "title": "High On Life", "title_id": "", "path": HOL},
         {"id": "nx_2", "title": "Mario Kart 8 Deluxe", "title_id": "0100152000022000",
          "path": "/Applications/MK8.app"}]


class TestDiscovery(unittest.TestCase):
    TREE = {
        "/A": ["High On Life.app", "Safari.app", "Ports"],
        "/A/Ports": ["MK8.app", ".hidden.app"],
    }
    PLISTS = {
        "/A/High On Life.app": {"CFBundleIdentifier": "local.fernandoceja.nxnative.highonlife",
                                "CFBundleDisplayName": "High On Life"},
        "/A/Safari.app": {"CFBundleIdentifier": "com.apple.Safari", "CFBundleName": "Safari"},
        "/A/Ports/MK8.app": {"CFBundleIdentifier": "org.example.mk", "DMTitleID": "0100152000022000",
                             "CFBundleName": "Mario Kart 8 Deluxe"},
    }

    def _scan(self, extra_exists=()):
        return nxnative.scan(
            dirs=("/A",), listdir=lambda p: self.TREE[p] if p in self.TREE else (_ for _ in ()).throw(OSError()),
            isdir=lambda p: p in self.TREE, plist_reader=lambda a: self.PLISTS.get(a, {}),
            exists=lambda p: p in extra_exists)

    def test_finds_wrapper_and_packed_ports_not_other_apps(self):
        found = self._scan()
        self.assertEqual([p["title"] for p in found], ["High On Life", "Mario Kart 8 Deluxe"])
        self.assertEqual(found[1]["title_id"], "0100152000022000")

    def test_nxnative_executable_marks_a_port(self):
        found = self._scan(extra_exists=("/A/Safari.app/Contents/MacOS/nxnative",))
        self.assertIn("Safari", [p["title"] for p in found])

    def test_scan_survives_missing_dirs(self):
        self.assertEqual(nxnative.scan(dirs=("/nope/really",)), [])


class TestPhrases(unittest.TestCase):
    def test_play_matches_title_loosely(self):
        for text in ("play high on life", "Hey Jev, launch High-On-Life", "start high on life game"):
            self.assertEqual(nxnative.match_port(text, PORTS)["path"], HOL, text)

    def test_bare_title_or_unknown_does_not_match(self):
        self.assertIsNone(nxnative.match_port("high on life", PORTS))
        self.assertIsNone(nxnative.match_port("play zelda tears", PORTS))

    def test_list_phrases(self):
        for text in ("list games", "show my games", "what games do i have", "list nxnative games"):
            self.assertTrue(nxnative.is_list_phrase(text), text)
        self.assertFalse(nxnative.is_list_phrase("play games"))

    def test_routes(self):
        old = nxnative._CACHE.copy()
        nxnative._CACHE.update({"at": 1e18, "ports": PORTS})
        try:
            self.assertEqual(commands.route_before_api("play high on life"), "nx_play")
            self.assertEqual(commands.route_before_api("list games"), "nx_list")
            self.assertEqual(commands.route_before_api("play switch"), "game_open")
        finally:
            nxnative._CACHE.update(old)

    def test_not_bridged(self):
        self.assertNotIn("nx_play", config.BRIDGE_ALLOW)
        self.assertNotIn("nx_list", config.BRIDGE_ALLOW)


class TestLaunch(unittest.TestCase):
    def test_opens_bundle_with_argument_list(self):
        calls = []
        line = nxnative.play_from_text("play high on life", platform="darwin", found=PORTS,
                                       exists=lambda p: True, run=calls.append)
        self.assertEqual(calls, [["open", HOL]])
        self.assertEqual(line, "Starting High On Life.")

    def test_missing_failed_and_not_mac(self):
        self.assertEqual(nxnative.launch_port(HOL, "High On Life", platform="darwin", exists=lambda p: False,
                                              run=lambda a: None), "I can't find High On Life anymore.")

        def boom(_a):
            raise RuntimeError("x")
        self.assertEqual(nxnative.launch_port(HOL, "High On Life", platform="darwin", exists=lambda p: True,
                                              run=boom), "I couldn't open High On Life.")
        self.assertEqual(nxnative.launch_port(HOL, platform="linux"), nxnative.NOT_MAC)

    def test_list(self):
        self.assertEqual(nxnative.list_ports(platform="darwin", found=PORTS),
                         "Your NXNative games: High On Life, Mario Kart 8 Deluxe.")
        self.assertEqual(nxnative.list_ports(platform="darwin", found=[]), nxnative.NONE_FOUND)

    def test_menu_row_launches_through_launch_rom(self):
        calls = []
        line = games.launch_rom("nxnative", HOL, "High On Life", platform="darwin",
                                exists=lambda p: True, run=calls.append)
        self.assertEqual((line, calls), ("Starting High On Life.", [["open", HOL]]))


class TestMenu(unittest.TestCase):
    def test_submenu_lists_ports(self):
        menu = mini_bar.nxnative_menu(PORTS)
        rows = [r for r in menu["items"] if r.get("kind") == "game_launch"]
        self.assertEqual([(r["title"], r["console"], r["path"]) for r in rows][0],
                         ("High On Life", "nxnative", HOL))
        self.assertIn("nxnative_games", [i.get("id") for i in mini_bar.plus_menu(can_attach=False, nx_ports=[])
                                         for i in ([i] + list(i.get("items", ())))])

    def test_empty_and_chip(self):
        rows = mini_bar.nxnative_menu([])["items"]
        self.assertEqual(rows[-1]["kind"], "games_empty")
        self.assertEqual(mini_bar.POPOVER_CHIPS["games"]["phrase"], "list games")


if __name__ == "__main__":
    unittest.main()
