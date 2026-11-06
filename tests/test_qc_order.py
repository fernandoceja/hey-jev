"""Shared Quick Command ordering and icon regressions, without Mac hardware."""
import pytest

import mini_bar
from commands import game_library
from commands.nxnative_build import BUILD
from commands.rea_study import STUDY


@pytest.fixture(params=[False, True])
def quick_tree(monkeypatch, request):
    running = request.param
    monkeypatch.setattr(game_library, "installed_apps",
                        lambda: {"ocarina", "switch", "wiiu", "gamecube"})
    monkeypatch.setattr(BUILD, "status", lambda: running)
    monkeypatch.setattr(STUDY, "status", lambda: running)
    games = {"switch": [{"id": "test_rom", "title": "Test ROM",
                          "path": "/games/test.nsp"}]}
    ports = [{"id": "test_port", "title": "Test Port", "path": "/games/Test.app"}]
    return mini_bar.quick_commands(game_library=games, nx_ports=ports), running


def test_shared_group_order(quick_tree):
    items, running = quick_tree
    ids = [item["id"] for item in items if item["kind"] != "separator"]
    first = ["websites", "nxnative_games", "nx_build"]
    if running:
        first.append("nx_cancel")
    first.append("rea")
    assert ids[:len(first)] == first
    assert ("nx_cancel" in ids) == running
    assert ids[len(first):] == [
        "tutor", "play_zelda", "console_switch", "console_wiiu", "console_gamecube",
        "cleanmymac_scan", "offline_brain_on", "offline_brain_off", "brief",
        "play_brief", "next_shift", "leave", "leave_reminders_on",
        "leave_reminders_off", "payday", "hazard", "gods_eye", "hazard_alerts",
        "blue_pill", "red_pill", "silence", "volume", "brightness",
    ]
    assert items[0] == mini_bar.websites_menu()
    rea = next(item for item in items if item.get("id") == "rea")
    assert ("rea_cancel" in [item["id"] for item in rea["items"]]) == running

    titles = [item["title"] for item in mini_bar.quick_command_leaves(items)]
    websites = [i for i, title in enumerate(titles) if title.startswith("Websites / ")]
    native = [i for i, title in enumerate(titles) if title.startswith("NXNative Games / ")]
    rea = [i for i, title in enumerate(titles) if title.startswith("REA / ")]
    assert websites and native and rea
    assert max(websites) < min(native)
    assert max(native) < titles.index("Start NXNative Build") < min(rea)
    if running:
        assert titles.index("Start NXNative Build") < titles.index("Cancel NXNative Build") < min(rea)
    assert max(rea) < titles.index("Tutor") < titles.index("CleanMyMac Scan")


def test_all_commands_have_icons(quick_tree):
    items, _ = quick_tree

    def walk(rows):
        for row in rows:
            if row["kind"] == "separator":
                continue
            yield row
            yield from walk(row.get("items", ()))

    for row in list(walk(items)) + list(mini_bar.quick_command_leaves(items)):
        assert isinstance(row.get("symbol"), str), row
        assert row["symbol"].strip(), row
        if row["id"] == "rea_review":
            assert row["symbol"] == "doc.text.magnifyingglass"
    review = next(row for row in walk(items) if row["id"] == "rea_review")
    assert review["symbol"] == "doc.text.magnifyingglass"
