import unittest

import mini_bar
from commands import web_sites
from commands.routing import route_before_api


class WebsitesMenuTests(unittest.TestCase):
    def _quick(self):
        for item in mini_bar.plus_menu(can_attach=False, game_library={}):
            if item.get("id") == "quick":
                return item["items"]
        self.fail("no Quick Commands")

    def test_websites_submenu_in_quick_commands(self):
        menus = [i for i in self._quick() if i.get("id") == "websites"]
        self.assertEqual(len(menus), 1)
        self.assertEqual(menus[0]["kind"], "submenu")
        self.assertEqual([r["title"] for r in menus[0]["items"]], [
            "Starlight Quest", "Barnaby & Pip", "Calculus 3", "3D Tetris", "Tetris",
            "Princess Academy", "Princess Chores", "STAR Interview Coach", "Kinetic Typer",
            "80s Obsession Store"])

    def test_every_site_has_a_row(self):
        keys = {r["id"][len("site_"):] for r in mini_bar.websites_menu()["items"]}
        self.assertEqual(keys, {e["key"] for e in web_sites.WEB_SITES})

    def test_rows_route_to_existing_handler(self):
        by_key = {e["key"]: e for e in web_sites.WEB_SITES}
        for row in mini_bar.websites_menu()["items"]:
            key = row["id"][len("site_"):]
            self.assertIs(web_sites.match_web_site(row["phrase"]), by_key[key], row["phrase"])
            self.assertEqual(route_before_api(row["phrase"]), "web_site_open", row["phrase"])

    def test_rows_open_in_default_browser(self):
        for row in mini_bar.websites_menu()["items"]:
            calls = []
            reply = web_sites.open_web_site_from_text(row["phrase"], platform="darwin", run=calls.append)
            self.assertTrue(reply.startswith("Opening "), reply)
            self.assertEqual(calls[0][0], "open")
            self.assertTrue(calls[0][1].startswith("https://"))

    def test_no_urls_in_menu(self):
        for row in mini_bar.websites_menu()["items"]:
            self.assertNotIn("http", row["phrase"])


if __name__ == "__main__":
    unittest.main()
