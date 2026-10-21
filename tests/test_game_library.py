"""Console game menus: scanning temp dirs, clean titles, and mocked launches."""
import json
import os
import tempfile
import unittest
from unittest import mock

from commands import game_library as gl
from commands import games
import mini_bar


def touch(root, rel):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    return path


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_each_console_by_extension_with_clean_titles(self):
        touch(self.root, "switch/High On Life [0100C1101EE5A000][US][v0][Base].nsp")
        touch(self.root, "switch/Sonic Frontiers.xci")
        touch(self.root, "wiiu/Mario Kart 8 (USA).wua")
        touch(self.root, "wiiu/Zelda BotW [ALZE01]/code/U-King.rpx")
        touch(self.root, "GameCubeDolphin/Legend of Zelda, The - The Wind Waker (USA).iso")
        touch(self.root, "gc/Super Mario Sunshine (USA, Canada).ciso")
        touch(self.root, "gc/Super Smash Bros. Melee (USA) (v1.02).iso")
        found = gl.scan([self.root], title_lookup=lambda tid: "")
        titles = {c: [g["title"] for g in found[c]] for c in found}
        self.assertEqual(titles["switch"], ["High On Life", "Sonic Frontiers"])
        self.assertEqual(titles["wiiu"], ["Mario Kart 8", "Zelda BotW"])
        self.assertEqual(titles["gamecube"], ["Super Mario Sunshine", "The Legend of Zelda - The Wind Waker"])
        self.assertEqual(titles["melee"], ["Super Smash Bros. Melee"])
        rpx = [g for g in found["wiiu"] if g["title"] == "Zelda BotW"][0]
        self.assertTrue(rpx["path"].endswith("U-King.rpx"))

    def test_ignores_wrong_extensions_ps_isos_hidden_and_app_bundles(self):
        touch(self.root, "GBA/Metroid Fusion.zip")
        touch(self.root, "PS1/Crash Bandicoot.iso")
        touch(self.root, "switch/.Hidden.nsp")
        touch(self.root, "Ryujinx.app/Contents/x.nsp")
        touch(self.root, "notes/readme.txt")
        found = gl.scan([self.root], title_lookup=lambda tid: "")
        self.assertEqual(sum(len(v) for v in found.values()), 0)

    def test_ryujinx_title_id_name_wins_and_duplicates_collapse(self):
        touch(self.root, "a/hol [0100C1101EE5A000].nsp")
        touch(self.root, "b/High On Life [0100C1101EE5A000][US].nsp")
        ryu = os.path.join(self.root, "ryu")
        meta = touch(ryu, "games/0100c1101ee5a000/gui/metadata.json")
        with open(meta, "w") as f:
            json.dump({"title": "High On Life"}, f)
        found = gl.scan([os.path.join(self.root, "a"), os.path.join(self.root, "b")],
                        title_lookup=lambda tid: gl.ryujinx_title(tid, ryu))
        self.assertEqual([g["title"] for g in found["switch"]], ["High On Life"])

    def test_reads_emulator_configured_dirs(self):
        cfg = touch(self.root, "Ryujinx/Config.json")
        with open(cfg, "w") as f:
            json.dump({"game_dirs": ["/x/switch", "/y"]}, f)
        self.assertEqual(gl.ryujinx_dirs(os.path.join(self.root, "Ryujinx")), ["/x/switch", "/y"])
        ini = touch(self.root, "Dolphin.ini")
        with open(ini, "w") as f:
            f.write("[General]\nISOPaths = 2\nISOPath0 = /g/GameCube\nISOPath1 = /g/gc\n")
        self.assertEqual(gl.dolphin_dirs(ini), ["/g/GameCube", "/g/gc"])
        xml = touch(self.root, "settings.xml")
        with open(xml, "w") as f:
            f.write("<content><GamePaths><Entry>/w/wiiu</Entry></GamePaths><Other><Entry>/no</Entry></Other></content>")
        self.assertEqual(gl.cemu_dirs(xml), ["/w/wiiu"])
        self.assertEqual(gl.dolphin_dirs(os.path.join(self.root, "missing.ini")), [])

    def test_library_is_cached_until_refresh(self):
        calls = []
        scanner = lambda: calls.append(1) or {"switch": []}
        gl._CACHE.update(at=0.0, games=None)
        gl.library(now=lambda: 100.0, scanner=scanner)
        gl.library(now=lambda: 110.0, scanner=scanner)
        self.assertEqual(len(calls), 1)
        gl.library(refresh=True, now=lambda: 111.0, scanner=scanner)
        gl.library(now=lambda: 200.0, scanner=scanner)
        self.assertEqual(len(calls), 3)
        gl._CACHE.update(at=0.0, games=None)


class MenuTests(unittest.TestCase):
    GAMES = {"switch": [{"id": "game_switch_abc", "title": "High On Life", "path": "/r/hol.nsp"}],
             "wiiu": [], "gamecube": [], "melee": []}

    def test_console_submenus_shape(self):
        menus = mini_bar.console_menus(self.GAMES)
        self.assertEqual([m["title"] for m in menus], ["Nintendo Switch", "Wii U", "GameCube", "Melee"])
        sw = menus[0]["items"]
        self.assertEqual(sw[0]["title"], "Open Ryujinx")
        self.assertEqual(sw[0]["phrase"], "play switch")
        self.assertEqual(sw[1]["kind"], "separator")
        self.assertEqual((sw[2]["title"], sw[2]["kind"], sw[2]["path"]), ("High On Life", "game_launch", "/r/hol.nsp"))
        self.assertEqual(sw[-1]["title"], "Turn Off")
        self.assertEqual([i["title"] for i in menus[1]["items"] if i.get("kind") != "separator"],
                         ["Open Cemu", "No games found", "Turn Off"])
        self.assertEqual(menus[2]["items"][0]["title"], "Open Dolphin")
        self.assertEqual(menus[3]["items"][0]["title"], "Open Slippi")

    def test_flat_play_items_are_gone_and_game_rows_are_findable(self):
        items = mini_bar.plus_menu(can_attach=False, game_library=self.GAMES)
        top = [i.get("id") for i in items]
        quick = [i for i in mini_bar.walk_menu(items)]
        ids = [i.get("id") for i in quick]
        for gone in ("play_sunshine", "emulators_off"):
            self.assertNotIn(gone, ids)
        self.assertIn("play_zelda", ids)
        self.assertEqual(mini_bar.plus_item("game_switch_abc", items)["path"], "/r/hol.nsp")

    def test_voice_phrases_still_route(self):
        import commands
        self.assertEqual(commands.route_before_api("play switch"), "game_open")
        self.assertEqual(commands.route_before_api("play mario sunshine"), "game_open")
        self.assertEqual(commands.route_before_api("turn off wii u"), "game_close")


class LaunchTests(unittest.TestCase):
    def run_launch(self, console, path="/r/game.bin"):
        run = mock.Mock()
        line = games.launch_rom(console, path, "Game", platform="darwin", exists=lambda p: True, run=run)
        return line, run.call_args[0][0] if run.called else None

    def test_argv_per_console(self):
        line, argv = self.run_launch("switch", "/r/hol.nsp")
        self.assertEqual(argv, ["open", "-a", "/Applications/Ryujinx.app", "--args", "/r/hol.nsp"])
        self.assertEqual(line, "Starting Game.")
        self.assertEqual(self.run_launch("wiiu", "/r/mk8.wua")[1],
                         ["open", "-a", "/Applications/Cemu.app", "--args", "-g", "/r/mk8.wua"])
        self.assertEqual(self.run_launch("gamecube", "/r/sms.ciso")[1][-2:], ["-e", "/r/sms.ciso"])
        self.assertEqual(self.run_launch("melee", "/r/melee.iso")[1], ["open", "/Applications/Slippi Launcher.app"])

    def test_missing_rom_emulator_and_non_mac(self):
        run = mock.Mock()
        self.assertEqual(games.launch_rom("switch", "/gone.nsp", "X", platform="darwin",
                                          exists=lambda p: p.endswith(".app"), run=run),
                         "I can't find X anymore.")
        self.assertIn("isn't installed", games.launch_rom("wiiu", "/a.wua", "X", platform="darwin",
                                                          exists=lambda p: False, run=run))
        self.assertEqual(games.launch_rom("switch", "/a.nsp", "X", platform="linux", run=run), games.GAMES_NOT_MAC)
        run.assert_not_called()

    def test_launch_failure(self):
        run = mock.Mock(side_effect=RuntimeError("x"))
        self.assertEqual(games.launch_rom("switch", "/a.nsp", "X", platform="darwin", exists=lambda p: True, run=run),
                         "I couldn't open X.")


if __name__ == "__main__":
    unittest.main()
