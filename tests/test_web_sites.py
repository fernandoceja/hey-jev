"""Fernando's web games/sites: phrases, routing, hardcoded https URLs, not bridged."""
import pathlib
import unittest

from commands import web_sites as ws
from commands.config import BRIDGE_ALLOW
from commands.routing import route_before_api

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAR = "https://fernandoceja.github.io/Zoe-s-Princess-Academy/starlight-quest/"
BARN = "https://barnaby-pip-rainbow-crayon.fernando-ceja.chatgpt.site/"
CALC = "https://fernandoceja.github.io/calculus-3-visualization/"


class FakeRun:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, argv, timeout=30):
        self.calls.append(tuple(argv))
        if self.fail:
            raise RuntimeError("no")
        return ""


class WebSiteTests(unittest.TestCase):
    CASES = {
        STAR: ("open starlight quest", "Hey Jev, play Starlight Quest.", "open zoe's starlight quest",
               "launch star light quest", "open starlite quest", "play the starlight game",
               "open starlight guest"),
        BARN: ("play barnaby", "open barnaby and pip", "open Barnaby & Pip", "play barnabee",
               "open the rainbow crayon", "play the barnaby game", "open barney pip"),
        CALC: ("open calculus", "open the math site", "open calculus 3", "open calc three",
               "open calcforge", "pull up the calculus site", "open calculus 3 visualization please"),
    }

    def test_phrases_match(self):
        for url, phrases in self.CASES.items():
            for p in phrases:
                entry = ws.match_web_site(p)
                self.assertIsNotNone(entry, p)
                self.assertEqual(entry["url"], url, p)

    def test_non_matches(self):
        for p in ("", "open safari", "what is calculus", "starlight quest", "open notes",
                  "tell me about barnaby", "open my calculus homework folder"):
            self.assertIsNone(ws.match_web_site(p), p)

    def test_routing(self):
        for phrases in self.CASES.values():
            for p in phrases:
                self.assertEqual(route_before_api(p), "web_site_open", p)

    def test_opens_only_hardcoded_https_default_browser(self):
        run = FakeRun()
        self.assertEqual(ws.open_web_site_from_text("play barnaby", platform="darwin", run=run),
                         "Opening Barnaby and Pip.")
        self.assertEqual(run.calls, [("open", BARN)])
        self.assertTrue({STAR, BARN, CALC} <= {e["url"] for e in ws.WEB_SITES})
        for e in ws.WEB_SITES:
            self.assertTrue(e["url"].startswith("https://"))
            self.assertTrue(ws._safe(e["url"]))

    def test_unsafe_url_refused(self):
        self.assertFalse(ws._safe("http://example.com"))
        self.assertFalse(ws._safe("https://x.com/;rm -rf"))

    def test_failure_and_not_mac(self):
        self.assertEqual(ws.open_web_site_from_text("open calculus", platform="darwin", run=FakeRun(fail=True)),
                         "I couldn't open the Calculus 3 visualization.")
        run = FakeRun()
        self.assertEqual(ws.open_web_site_from_text("open calculus", platform="linux", run=run), ws.WEB_NOT_MAC)
        self.assertEqual(run.calls, [])
        self.assertEqual(ws.open_web_site_from_text("open nothing", platform="darwin", run=run),
                         "Which site should I open?")

    def test_not_bridged_and_wired(self):
        self.assertNotIn("web_site_open", BRIDGE_ALLOW)
        self.assertIn('"web_site_open": lambda', (ROOT / "siri.py").read_text())


if __name__ == "__main__":
    unittest.main()


T3D = "https://fernandoceja.github.io/3D-Tetris/"
TET = "https://fernandoceja.github.io/Tetris-Game/"
ACAD = "https://fernandoceja.github.io/Zoe-s-Princess-Academy/"
CHORE = "https://fernandoceja.github.io/Zoe-s-Princess-Chores/"
COACH = "https://fernandoceja.github.io/AI-star-interview-coach/"
TYPER = "https://fernandoceja.github.io/kinetic-typer/"
BIZ = "https://80sobsessioncompany.com/"


class ExtraSiteTests(unittest.TestCase):
    CASES = {
        T3D: ("open 3d tetris", "play three d tetris", "open 3 d tetris", "play tetris 3d", "open 3d tetras"),
        TET: ("open tetris", "play tetris", "play classic tetris", "open the tetris game", "play tetras",
              "open regular tetris"),
        ACAD: ("play princess academy", "open zoe's academy", "open zoey's princess academy",
               "launch princess academy"),
        CHORE: ("open zoe's chores", "open princess chores", "open the chore chart", "open zoey's princess chores"),
        COACH: ("open interview coach", "open the star interview coach", "start interview practice",
                "open star coach", "open the interview couch"),
        TYPER: ("open kinetic typer", "play kinetic typer", "open kenetic typer", "open kinetic typing"),
        BIZ: ("open my business website", "open my website", "open my store", "open 80s obsession",
              "open eighties obsession", "open 80s obsession company", "open the shop site", "open my shop",
              "pull up eighties obsession company", "open 80 obsession", "go to my business website"),
    }

    def test_phrases_route_and_match(self):
        for url, phrases in self.CASES.items():
            for p in phrases:
                self.assertEqual(route_before_api(p), "web_site_open", p)
                self.assertEqual(ws.match_web_site(p)["url"], url, p)

    def test_aliases_unique(self):
        self.assertEqual(ws.match_web_site("open 3d tetris")["key"], "tetris3d")
        self.assertEqual(ws.match_web_site("open tetris")["key"], "tetris")
        seen = {}
        for e in ws.WEB_SITES:
            for alias in e["names"]:
                self.assertNotIn(alias, seen, f"{alias} in {seen.get(alias)} and {e['key']}")
                seen[alias] = e["key"]

    def test_existing_commands_kept(self):
        self.assertEqual(route_before_api("open princess academy"), "zoe_academy")
        self.assertEqual(route_before_api("open zoe's princess academy"), "zoe_academy")
        self.assertEqual(ws.match_web_site("open starlight quest")["url"], STAR)
        for p in ("open shopify", "open shopify orders", "any new orders", "open the store", "open store",
                  "open business site", "open our website"):
            self.assertEqual(route_before_api(p), "site_open", p)
        self.assertEqual(route_before_api("open the app store"), "app_open")
        for p in ("open chores", "open academy", "interview", "open the interview", "chores",
                  "open shopify", "open the store", "open orders"):
            self.assertIsNone(ws.match_web_site(p), p)

    def test_no_finance_pages(self):
        urls = " ".join(e["url"] for e in ws.WEB_SITES)
        self.assertNotIn("downpayment", urls)
        self.assertNotIn("fidelity", urls)
        self.assertEqual(len(ws.WEB_SITES), 10)
        for e in ws.WEB_SITES:
            self.assertTrue(ws._safe(e["url"]))

    def test_opens_with_default_browser(self):
        run = FakeRun()
        self.assertEqual(ws.open_web_site_from_text("open my store", platform="darwin", run=run),
                         "Opening 80s Obsession Company.")
        self.assertEqual(run.calls, [("open", BIZ)])
