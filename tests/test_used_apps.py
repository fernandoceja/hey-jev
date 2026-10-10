"""Spoken names for the apps Fernando uses, and the not-installed fallback."""
import os
import plistlib
import tempfile
import unittest
from unittest import mock

import commands
from commands.textutil import _norm


# Phrases that must resolve to one open -a name. Spaces and punctuation are
# already folded by _norm, so each entry is a distinct wording.
ALIASES = {
    "ChatGPT": (
        "codex", "codecs", "code x", "kodex", "open ai", "openai",
        "chat gbt", "chat gpd", "chatgbt", "chad gpt",
    ),
    "Claude": ("clod", "claud", "clawed", "claude ai", "anthropic"),
    "Grok Bot": ("grock", "groc", "grokbot", "rock bot", "grog"),
    "Cursor": (
        "curser", "cursor ai", "cursor editor", "code editor",
        "vscode", "vs code", "visual studio code",
    ),
    "Gemini": ("jemini", "gemeni", "gemini ai", "google gemini"),
    "Muse": ("meta muse", "muse app", "mews"),
    "TikTok": ("tiktok", "tik tok", "tick tock", "tic toc", "tic tac", "tik tock", "tiktoc"),
    "gen1recomp": (
        "gen1recomp", "pokemon", "pokémon", "pokemon red", "pokey mon",
        "poke mon", "gen one", "gen 1", "gameboy game",
    ),
    "MovieBoxPro": ("movie box", "movie box pro", "movies", "moviebox"),
    "CleanMyMac_5": ("clean my mac", "cleanmymac", "clean my mac 5", "clean up", "clean up app", "mac cleaner"),
    "Passwords": (
        "passwords", "password", "password app", "passwords app",
        "apple passwords", "my passwords", "keychain",
    ),
    "iPhone Mirroring": ("iphone", "phone mirroring", "mirror my phone", "iphone mirror", "my phone"),
    "Reminders": ("reminder", "reminders", "my reminders", "to do list", "todo"),
    "Terminal": ("terminal", "terminal app", "command line", "shell"),
    "Apps": ("apps", "launchpad", "launch pad", "all apps", "app launcher"),
    "Messages": ("texts", "text messages", "messaging", "imessage"),
    "Music": ("apple music", "music"),
    "Calendar": ("my calendar", "calender", "ical", "calendar"),
    "Photos": ("photo", "pictures", "photo library", "photos"),
    "Notes": ("note", "apple notes", "notes app", "notes"),
    "Zoho Mail - Desktop": ("zoho male", "zoho mail", "business email"),
    "Numbers Creator Studio": ("number", "spreadsheet", "budget sheet", "numbers"),
    "FaceTime": ("facetime call", "facetime"),
    "System Settings": ("system setting", "mac settings", "settings app", "settings"),
    "Mail": ("email", "apple mail", "my email", "mail"),
    "Spotify": ("spotify", "spot a fy", "spotty fi"),
    "CapCut": ("capcut", "cap cut", "capcat", "cap kit", "kapkut"),
    "Phone": ("phone",),
    "News": ("news",),
    "Google Password Manager": ("password manager", "google passwords"),
}

SITES = {
    "https://app.workjam.com/login": (
        "workjam", "work jam", "work jam app", "my schedule", "my schedule app",
        "workgem", "work gym",
    ),
    "https://sso.prd.mykronos.com": (
        "ukg", "u k g", "ukg pro", "kronos", "you kg", "my pay stub", "my pay stub app",
    ),
}


def _fake_run(calls):
    def run(args, **kwargs):
        calls.append((list(args), kwargs))
        return mock.Mock(returncode=0, stdout="", stderr="")
    return run


def _index(*names):
    return {_norm(name): "/tmp/hey-jev-tests/{0}.app".format(name) for name in names}


class TestSpokenAliases(unittest.TestCase):
    def test_every_used_alias_resolves(self):
        for display, phrases in ALIASES.items():
            for spoken in phrases:
                self.assertEqual(commands.known_app_name(spoken), display, spoken)

    def test_cloud_and_zoe_mail_are_not_aliases(self):
        blocked = {_norm(item) for item in commands.APP_NOT_APPS}
        self.assertIn("cloud", blocked)
        self.assertIn("zoemail", blocked)
        for spoken, _display in commands.APP_NICKNAMES.items():
            self.assertNotIn(_norm(spoken), blocked, spoken)
        self.assertIsNone(commands.known_app_name("cloud"))
        self.assertIsNone(commands.known_app_name("Cloud."))
        self.assertIsNone(commands.known_app_name("zoe mail"))
        self.assertIsNone(commands.known_app_name("Zoe Mail"))
        self.assertNotEqual(commands.known_app_name("cloud"), "Claude")
        self.assertNotEqual(commands.known_app_name("zoe mail"), "Zoho Mail - Desktop")
        self.assertEqual(commands.known_app_name("zoho male"), "Zoho Mail - Desktop")
        self.assertEqual(commands.known_app_name("news"), "News")
        self.assertEqual(commands.known_app_name("mews"), "Muse")
        self.assertIsNone(commands.known_app_name("code"))
        self.assertNotEqual(commands.known_app_name("code"), "ChatGPT")

    def test_password_manager_stays_google(self):
        self.assertEqual(commands.known_app_name("password manager"), "Google Password Manager")
        self.assertEqual(commands.known_app_name("google passwords"), "Google Password Manager")
        for spoken in ("password app", "passwords app", "apple passwords", "password"):
            self.assertEqual(commands.known_app_name(spoken), "Passwords", spoken)

    def test_codex_name_is_chatgpt_not_classic(self):
        for spoken in ("codex", "Codex", "codecs", "code x", "kodex"):
            self.assertEqual(commands.known_app_name(spoken), "ChatGPT", spoken)
            self.assertNotEqual(commands.known_app_name(spoken), "ChatGPT Classic", spoken)
        self.assertEqual(commands.APP_BUNDLES["ChatGPT"], "com.openai.codex")
        self.assertEqual(commands.APP_BUNDLES["ChatGPT Classic"], "com.openai.chat")
        self.assertIn("ChatGPT", commands.APP_BUNDLE_EXCLUSIVE)
        self.assertEqual(commands.known_app_name("ChatGPT Classic"), "ChatGPT Classic")
        self.assertEqual(commands.known_app_name("chat gpt classic"), "ChatGPT Classic")

    def test_vs_code_is_cursor(self):
        for spoken in ("vs code", "vscode", "visual studio code", "code editor"):
            self.assertEqual(commands.known_app_name(spoken), "Cursor", spoken)
        self.assertNotIn("Visual Studio Code", commands.KNOWN_APPS)

    def test_open_routes_and_nearby_commands_stay_put(self):
        opens = {
            "open codex": "app_open",
            "open pokemon red": "app_open",
            "open tick tock": "app_open",
            "open terminal": "app_open",
            "open launchpad": "app_open",
            "open all apps": "app_open",
            "open password app": "app_open",
            "open apple passwords": "app_open",
            "open vs code": "app_open",
            "open apple music": "app_open",
            "open my calendar": "app_open",
            "play apple music": "media_play",
            "what's my schedule": "info_today_schedule",
            "open my schedule": "site_open",
            "open my schedule app": "site_open",
            "open kronos": "site_open",
            "open ukg pro": "site_open",
            "open workjam": "site_open",
            "open work gym": "site_open",
            "remind me to call mom": "remind_add",
            "take a note: milk": "note_take",
            "quit all apps": None,
        }
        for phrase, key in opens.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            if key in (None, "app_open", "site_open", "media_play", "remind_add"):
                self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        self.assertNotIn("app_open", commands.BRIDGE_ALLOW)
        self.assertNotIn("site_open", commands.BRIDGE_ALLOW)
        self.assertNotIn("media_play", commands.BRIDGE_ALLOW)
        self.assertNotIn("remind_add", commands.BRIDGE_ALLOW)
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)
        self.assertTrue(commands.is_quit_all("quit all apps"))
        self.assertIsNone(commands.parse_app_name("quit all apps", "quit"))

    def test_workjam_and_ukg_stay_websites(self):
        for url, phrases in SITES.items():
            for spoken in phrases:
                found = commands.resolve_site(spoken)
                self.assertIsNotNone(found, spoken)
                self.assertEqual(found["url"], url, spoken)
                self.assertEqual(commands.route_before_api("open " + spoken), "site_open", spoken)
                self.assertIsNone(commands.bridge_allowed("open " + spoken), spoken)

    def test_alias_norms_do_not_point_at_two_apps(self):
        found = {}
        for name in commands.KNOWN_APPS:
            found.setdefault(_norm(name), name)
        for spoken, name in commands.APP_NICKNAMES.items():
            key = _norm(spoken)
            previous = found.get(key)
            if previous is not None and previous != name:
                self.fail("{0!r} is both {1!r} and {2!r}".format(spoken, previous, name))
            found[key] = name


class TestNotInstalled(unittest.TestCase):
    def test_spotify_and_capcut_open_in_chrome_when_missing(self):
        calls = []
        empty = {}
        with mock.patch.object(commands.apps, "app_index", return_value=empty), \
                mock.patch.object(commands.subprocess, "run", _fake_run(calls)):
            spotify = commands.open_any_app(None, "open spotify", {})
            capcut = commands.open_any_app(None, "open cap cut", {})
            slack = commands.open_any_app(None, "open slack", {})
        self.assertEqual(spotify, "Opening Spotify on the web.")
        self.assertEqual(capcut, "Opening CapCut on the web.")
        self.assertEqual(slack, "Slack isn't installed.")
        self.assertEqual(calls[0][0], ["open", "-a", "Google Chrome", "https://open.spotify.com"])
        self.assertEqual(calls[1][0], ["open", "-a", "Google Chrome", "https://www.capcut.com/editor"])
        self.assertEqual(len(calls), 2)
        for args, kwargs in calls:
            self.assertNotEqual(kwargs.get("shell"), True)
            self.assertTrue(args[3].startswith("https://"))
        for entry in commands.APP_WEB_FALLBACK.values():
            self.assertTrue(entry["url"].startswith("https://"), entry)
            self.assertNotIn(" ", entry["url"])

    def test_installed_spotify_still_launches_the_app(self):
        calls = []
        with mock.patch.object(commands.apps, "app_index", return_value=_index("Spotify")), \
                mock.patch.object(commands.subprocess, "run", _fake_run(calls)):
            opened = commands.open_any_app(None, "open spotty fi", {})
        self.assertEqual(opened, {"app": "Spotify"})
        self.assertEqual(calls[0][0], ["open", "-a", "Spotify"])

    def test_missing_cursor_is_spoken_and_vs_code_does_not_launch_itself(self):
        calls = []
        with mock.patch.object(commands.apps, "app_index", return_value={}), \
                mock.patch.object(commands.subprocess, "run", _fake_run(calls)):
            spoken = commands.open_any_app(None, "open visual studio code", {})
        self.assertEqual(spoken, "Cursor isn't installed.")
        self.assertEqual(calls, [])

    def test_installed_names_use_open_a(self):
        calls = []
        names = (
            ("open password app", "Passwords"),
            ("open passwords app", "Passwords"),
            ("open apple passwords", "Passwords"),
            ("open password manager", "Google Password Manager"),
            ("open pokemon", "gen1recomp"),
            ("open pokemon red", "gen1recomp"),
            ("open tick tock", "TikTok"),
            ("open terminal", "Terminal"),
            ("open launchpad", "Apps"),
            ("open all apps", "Apps"),
            ("open vs code", "Cursor"),
            ("open business email", "Zoho Mail - Desktop"),
        )
        installed = _index(*(display for _phrase, display in names))
        with mock.patch.object(commands.apps, "app_index", return_value=installed), \
                mock.patch.object(commands.subprocess, "run", _fake_run(calls)):
            for phrase, display in names:
                self.assertEqual(commands.open_any_app(None, phrase, {}), {"app": display}, phrase)
        self.assertEqual([call[0] for call in calls], [["open", "-a", display] for _phrase, display in names])

    def test_apps_module_does_not_use_a_shell(self):
        source = open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "commands", "apps.py"),
            encoding="utf-8",
        ).read()
        self.assertNotIn("shell=True", source)
        self.assertNotIn("socket", source)


class TestCodexBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.codex = self._app("ChatGPT.app", "com.openai.codex")
        self.classic = self._app("ChatGPT Classic.app", "com.openai.chat")
        self._saved = dict(commands.apps._index_cache)
        commands.apps._index_cache.update(at=0.0, idx=None, bundles={})
        self.addCleanup(self._restore_index)

    def _restore_index(self):
        commands.apps._index_cache.clear()
        commands.apps._index_cache.update(self._saved)

    def _app(self, filename, bundle):
        path = os.path.join(self.root, filename)
        os.makedirs(os.path.join(path, "Contents"))
        with open(os.path.join(path, "Contents", "Info.plist"), "wb") as handle:
            plistlib.dump({"CFBundleIdentifier": bundle}, handle)
        return path

    def _located(self):
        with mock.patch.object(commands.apps, "APP_DIRS", (self.root,)), \
                mock.patch.object(commands.apps, "FINDER_PATH", os.path.join(self.root, "no-finder")):
            commands.app_index(force=True)
            return commands.locate_app("ChatGPT"), commands.locate_app("ChatGPT Classic")

    def test_codex_locates_chatgpt_app_not_classic(self):
        codex, classic = self._located()
        self.assertEqual(codex, self.codex)
        self.assertEqual(classic, self.classic)
        self.assertEqual(commands.apps._read_bundle_id(codex), "com.openai.codex")
        self.assertEqual(commands.apps._read_bundle_id(classic), "com.openai.chat")
        self.assertNotEqual(codex, classic)

    def test_open_codex_launches_the_codex_bundle_path(self):
        calls = []
        phrases = ("open codex", "open codecs", "open code x", "open kodex", "open openai")
        with mock.patch.object(commands.apps, "APP_DIRS", (self.root,)), \
                mock.patch.object(commands.apps, "FINDER_PATH", os.path.join(self.root, "no-finder")), \
                mock.patch.object(commands.subprocess, "run", _fake_run(calls)):
            commands.app_index(force=True)
            for phrase in phrases:
                self.assertEqual(commands.route_before_api(phrase), "app_open", phrase)
                self.assertIsNone(commands.bridge_allowed(phrase), phrase)
                self.assertNotIn("app_open", commands.BRIDGE_ALLOW)
                opened = commands.open_any_app(None, phrase, {})
                self.assertEqual(opened, {"app": "ChatGPT"}, phrase)
            classic = commands.open_any_app(None, "open chat gpt classic", {})
        self.assertEqual(classic, {"app": "ChatGPT Classic"})
        launched = [call[0] for call in calls]
        self.assertEqual(launched[:-1], [["open", "-a", self.codex]] * len(phrases))
        self.assertEqual(launched[-1], ["open", "-a", self.classic])
        for _args, kwargs in calls:
            self.assertNotEqual(kwargs.get("shell"), True)
