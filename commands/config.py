"""Editable constants: apps, sites, shifts, paths, bridge allowlist, and phrase patterns."""
import os
import re

FUZZY_CUTOFF = 0.6
# App names are close together (News/Notes, YouTube/YouTube TV), so typos
# have to be nearer than shortcut names before a fuzzy open is trusted.
APP_FUZZY_CUTOFF = 0.88
APP_INDEX_TTL = 600  # seconds
CONFIRM_SECONDS = 10
SHORTCUT_FOLDER = "Jev"
SHORTCUT_CACHE_SECONDS = 30
# A shift is a calendar event whose title matches any of these. R345 is an
# Apple store code; any R-number counts. Add a store name here if you use one.
SHIFT_TITLE_PATTERNS = (
    r"\bR\d{2,4}\b",
    r"\bshift\b",
    r"\bBrea\b",
    r"\bApple\b",
)
SHIFT_HORIZON_DAYS = 14
# A spoken shift for one date. Plain JSON in the app support folder. No secrets.
# That date replaces the calendar shift. Clearing the date restores the calendar.
SHIFT_OVERRIDE_PATH = os.path.expanduser(
    "~/Library/Application Support/Hey Jev/shift-overrides.json"
)
# "When should I leave for work" drives from home to the Brea store.
# Apple's retail page lists the store as 1016C. 1065 is the mall building.
HOME_ADDRESS = "Upland, CA"
BREA_STORE_ADDRESS = "Apple Brea Mall, 1016C Brea Mall, Brea, CA 92821"
LEAVE_BUFFER_MINUTES = 15
# Used only when MapKit can't return a drive time. The reply says it is an estimate.
LEAVE_TYPICAL_DRIVE_MINUTES = 35
SCHOOL_HORIZON_DAYS = 30
BILL_HORIZON_DAYS = 45
# Apple pay is every other Friday. This date is one payday. Override it in money.md.
DEFAULT_APPLE_PAY_ANCHOR = "2026-09-25"
# Spoken sweep reminder only. Jev never looks up a balance and never moves this money.
# One place for the amount and the account label the payday line says out loud.
SWEEP_AMOUNT = 600
SWEEP_ACCOUNT_LABEL = "Zoe …4157"
# The launch reminder writes the date here so the same day is not spoken again.
SWEEP_SPOKEN_PATH = os.path.expanduser(
    "~/Library/Application Support/Hey Jev/sweep-spoken.txt"
)
PRINCESS_SHORTCUT = "Zoe's Princess Academy"
# Used only when that shortcut is not in the Jev folder. Leave blank to skip the site.
PRINCESS_ACADEMY_URL = ""
# Orders has no store slug here. Paste https://admin.shopify.com/store/YOUR-STORE/orders
SHOPIFY_ORDERS_URL = "https://admin.shopify.com/"
BRIGHTNESS_UP_CODE = 144
BRIGHTNESS_DOWN_CODE = 145
SHOW_DESKTOP_CODE = 103  # F11, the usual Show Desktop shortcut
VOLUME_WORDS = {
    "silent": 0, "zero": 0, "mute": 0, "quiet": 25, "low": 25,
    "medium": 50, "half": 50, "loud": 75, "high": 75, "max": 100, "full": 100, "maximum": 100,
}
# "What's Zoe got tomorrow": title or calendar name.
ZOE_EVENT_RE = re.compile(r"\b(?:Zoe|school|Cabrillo)\b", re.I)

# "Check my messages from My Love". Phone is an exact handle.id match.
# The email is matched case-insensitively. Edit these here.
MY_LOVE_HANDLES = ("+15623616724", "cgarcilazo6724@icloud.com")
MESSAGES_DB = os.path.expanduser("~/Library/Messages/chat.db")

JEV_DOCS = os.path.expanduser("~/Documents/Jev")
NOTES_PATH = os.path.join(JEV_DOCS, "notes.md")
DUE_PATH = os.path.join(JEV_DOCS, "due.md")
IHSS_PATH = os.path.join(JEV_DOCS, "ihss_hours.csv")
# Optional payday anchor. Missing file uses DEFAULT_APPLE_PAY_ANCHOR and IHSS semi-monthly.
MONEY_PATH = os.path.join(JEV_DOCS, "money.md")
# Today through this many days ahead, including today.
DUE_HORIZON_DAYS = 7

# Upland, CA. Open-Meteo needs no key.
UPLAND_LAT = 34.0975
UPLAND_LON = -117.6484
WEATHER_TIMEOUT = 4

FOCUS_ON_NAME = "Jev Focus On"
FOCUS_OFF_NAME = "Jev Focus Off"
FOCUS_DEFAULT_SECONDS = 25 * 60

# Opened as-is. No receipt number is read or stored.
CASE_STATUS_URL = "https://egov.uscis.gov/casestatus"

# Optional Gmail hook. Same Keychain service as the API keys (com.jevsiri.keys).
# The brief stays quiet about mail unless this account holds a token.
GMAIL_TOKEN_ACCOUNT = "GOOGLE_OAUTH_TOKEN"

# iCloud Drive/Jev/inbox. Polled from a background thread. No listening socket.
BRIDGE_INBOX = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/Jev/inbox")
BRIDGE_OUTBOX = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/Jev/outbox")
BRIDGE_SECRET_ACCOUNT = "JEV_BRIDGE_SECRET"
BRIDGE_MAX_AGE = 120
# Spoken command length. Longer inbox files are rejected before they run.
BRIDGE_MAX_CMD = 2000
BRIDGE_POLL_SECONDS = 2
# Reply files sit in iCloud until something deletes them. The phone shortcut
# is not built yet, so the Mac removes them once they are older than this.
OUTBOX_TTL_SECONDS = 10 * 60
NONCE_LOG = os.path.expanduser("~/Library/Application Support/Hey Jev/bridge-nonces.json")
NONCE_LIMIT = 200
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
# Phone commands that may run. No quit-all, no message reading, no confirmation,
# no general shortcut (a Jev shortcut can send a text). Focus runs two fixed names.
BRIDGE_ALLOW = frozenset({
    "info_time",
    "info_date",
    "info_today",
    "info_weather",
    "info_next_event",
    "info_today_schedule",
    "info_next_shift",
    "info_open_apps",
    "info_brief",
    "info_due",
    "info_school",
    "info_weekend",
    "info_shift_length",
    "info_brea",
    # One name each. The override is a local file. Leave time is a spoken ETA.
    "shift_set",
    "shift_clear",
    "info_leave",
    "info_rent",
    "info_bills",
    "info_payday",
    # Spoken date check only. It does not look up a balance or move money.
    "info_payday_check",
    "info_battery",
    "info_help",
    "media_now",
    "info_zoe",
    "note_take",
    "focus_on",
    "ihss_log",
    "ihss_hours",
    "case_status",
})
# Names `open -a` should use. Edit a spelling here if Launch Services uses another.
KNOWN_APPS = (
    "App Store", "Automator", "Books", "Calculator", "Calendar", "ChatGPT",
    "ChatGPT Classic", "Chess", "Claude", "CleanMyMac_5", "Clock", "Contacts",
    "Cursor", "Dictionary", "FaceTime", "Find My", "Freeform", "Games", "Gemini",
    "Google Chrome", "Google Password Manager", "Grok Bot", "Home",
    "Image Playground", "Journal", "Mail", "Maps", "Messages", "MovieBoxPro",
    "Muse", "Music", "News", "Notes", "Numbers Creator Studio",
    "Pages Creator Studio", "Passwords", "Phone", "Photo Booth", "Photos",
    "Podcasts", "Preview", "QuickTime Player", "Reminders", "Safari", "Shortcuts",
    "Siri", "Stickies", "Stocks", "System Settings", "TV", "TextEdit", "Tips",
    "Voice Memos", "Weather", "YouTube", "YouTube TV", "iPhone Mirroring",
    "Zoho Mail - Desktop", "Finder", "Visual Studio Code", "CapCut", "Spotify", "Slack",
)
# Extra spoken names. The value is what `open -a` is given.
APP_NICKNAMES = {
    "business email": "Zoho Mail - Desktop",
    "zoho": "Zoho Mail - Desktop",
    "zoho mail": "Zoho Mail - Desktop",
    "mirroring": "iPhone Mirroring",
    "my phone": "iPhone Mirroring",
    "numbers": "Numbers Creator Studio",
    "budget app": "Numbers Creator Studio",
    "pages": "Pages Creator Studio",
    "settings": "System Settings",
    "system preferences": "System Settings",
    "preferences": "System Settings",
    "clean my mac": "CleanMyMac_5",
    "gpt": "ChatGPT",
    "chat gpt": "ChatGPT",
    "chrome": "Google Chrome",
    "quicktime": "QuickTime Player",
    "quick time": "QuickTime Player",
    "voice memos": "Voice Memos",
    "voicememos": "Voice Memos",
    "findmy": "Find My",
    "find my": "Find My",
    "grok": "Grok Bot",
    "password manager": "Google Password Manager",
    "google passwords": "Google Password Manager",
    "text edit": "TextEdit",
    "youtube tv": "YouTube TV",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "cap cut": "CapCut",
}
# Spoken phrase -> page opened in Google Chrome. editable=True means swap in your real URL.
# These are public login pages. Jev only hands the URL to `open`. It does not fetch them.
SITE_CONFIG = (
    {"phrases": ("workjam", "work jam"), "url": "https://app.workjam.com/login",
     "label": "WorkJam", "editable": False},
    {"phrases": ("ukg",), "url": "https://www.ukg.com/",
     "label": "UKG", "editable": True},
    {"phrases": ("apple employee portal", "employee portal", "appleconnect", "apple connect"),
     "url": "https://appleconnect.apple.com/", "label": "the Apple employee portal", "editable": True},
    {"phrases": ("umgc", "umgc class", "class site", "school site", "learn umgc"),
     "url": "https://learn.umgc.edu/", "label": "UMGC", "editable": False},
    {"phrases": ("shopify", "shopify admin"), "url": "https://admin.shopify.com/",
     "label": "Shopify admin", "editable": False},
    {"phrases": ("shopify orders", "orders"), "url": SHOPIFY_ORDERS_URL,
     "label": "Shopify orders", "editable": True},
    {"phrases": ("80s obsession", "80s obsession company", "store", "store site", "our store",
                 "business site", "our website"),
     "url": "https://80sobsessioncompany.com/", "label": "the store site", "editable": False},
    {"phrases": ("bookings", "cal.com", "cal com", "my bookings"),
     "url": "https://app.cal.com/bookings", "label": "bookings", "editable": False},
    {"phrases": ("ihss", "ihss portal", "ets", "timesheet portal", "timesheets", "ihss timesheet"),
     "url": "https://etspublic.cdss.ca.gov/", "label": "the IHSS timesheet portal", "editable": True},
    {"phrases": ("case status", "uscis", "uscis case status"),
     "url": CASE_STATUS_URL, "label": "case status", "editable": False},
    {"phrases": ("bank of america", "bofa", "boa"),
     "url": "https://secure.bankofamerica.com/login/sign-in/signOnV2Screen.go",
     "label": "Bank of America", "editable": False},
    {"phrases": ("fidelity",),
     "url": "https://login.fidelity.com/ftgw/Fas/Fidelity/RtlCust/Login/Init",
     "label": "Fidelity", "editable": False},
    {"phrases": ("capital one",),
     "url": "https://verified.capitalone.com/auth/signin",
     "label": "Capital One", "editable": False},
    {"phrases": ("github",), "url": "https://github.com/login",
     "label": "GitHub", "editable": False},
)
FOLDER_PATHS = {
    "downloads": "~/Downloads",
    "download": "~/Downloads",
    "documents": "~/Documents",
    "document": "~/Documents",
    "desktop": "~/Desktop",
}
APP_DIRS = (
    "/System/Applications",
    "/System/Applications/Utilities",
    "/Applications",
    "/Applications/Utilities",
    os.path.expanduser("~/Applications"),
)
FINDER_PATH = "/System/Library/CoreServices/Finder.app"
# terminate() would log the user out or kill the assistant. Matched by bundle id and name.
PROTECTED_IDS = {
    "com.apple.finder",
    "com.apple.loginwindow",
    "com.apple.systempreferences",
    "com.heyjev.app",
}
PROTECTED_NAMES = {"finder", "loginwindow", "system settings", "system preferences"}
# Actions that must be confirmed out loud before they run. Never inside a two-part command.
CONFIRM = {"apps_quit_all", "empty_trash"}

YES_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|confirm|do it)"
    r"(?:\s*,?\s*(?:please|quit(?:\s+them)?|close(?:\s+them)?|do it|confirm))?[.!?]*$",
    re.I,
)
NO_RE = re.compile(r"^(?:no|nope|nah|cancel|stop|never mind|nevermind)(?:\s*,?\s*please)?[.!?]*$", re.I)
QUIT_ALL_RE = re.compile(
    r"\b(?:quit|close|kill|force quit)\s+(?:all\s+(?:the\s+)?apps?|everything|every\s+app)\b"
    r"|^\s*(?:please\s+)?(?:quit|close|kill)\s+all(?:\s+of\s+them)?\s*[.!?]*$",
    re.I,
)
QUIT_ALL_ONLY_RE = re.compile(
    r"(?:please\s+)?(?:quit|close|kill|force quit)\s+"
    r"(?:all(?:\s+(?:the\s+)?apps?|\s+of\s+them)?|everything|every\s+app)"
    r"(?:\s+please)?[.!?]*",
    re.I,
)
_OPEN_VERBS = r"open|launch|start|bring up|switch to"
_QUIT_VERBS = r"force quit|quit|close|kill"
JOINER_RE = re.compile(r"\b(?:and|then)\b", re.I)

# Whole-utterance commands. Checked before the looser patterns below.
_PLEASE = r"(?:please\s+)?"
_TAIL = r"(?:\s+please)?[.!?]*$"
# "my shift Monday is 9:30 to 6:30 at Brea" and "clear my shift Monday".
_SHIFT_WHEN = (
    r"(?:today|tomorrow|(?:this|next)\s+"
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
)
_SHIFT_TIME = r"\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?"
_PLAY = (
    rf"^{_PLEASE}(?:play|resume)"
    rf"(?:\s+spotify|\s+(?:the\s+)?(?:music|song)|\s+apple\s+music|\s+on\s+apple\s+music)?{_TAIL}"
)
STRICT_PATTERNS = (
    (re.compile(rf"^{_PLEASE}what can you do{_TAIL}", re.I), "info_help"),
    (re.compile(rf"^{_PLEASE}what do you do{_TAIL}", re.I), "info_help"),
    (re.compile(rf"^{_PLEASE}what are your commands{_TAIL}", re.I), "info_help"),
    (re.compile(rf"^{_PLEASE}help{_TAIL}", re.I), "info_help"),
    (re.compile(rf"^{_PLEASE}what(?:'s| is) today{_TAIL}", re.I), "info_today"),
    (re.compile(rf"^{_PLEASE}brief me{_TAIL}", re.I), "info_brief"),
    (re.compile(rf"^{_PLEASE}(?:what(?:'s| is) the weather(?:\s+like)?|how(?:'s| is) the weather|weather){_TAIL}", re.I), "info_weather"),
    (re.compile(rf"^{_PLEASE}what(?:'s| is| does| has)\s+zoe\b.*\btomorrow\b{_TAIL}", re.I), "info_zoe"),
    (re.compile(rf"^{_PLEASE}open\s+(?:zoe'?s\s+)?princess\s+academy{_TAIL}", re.I), "zoe_academy"),
    (re.compile(rf"^{_PLEASE}(?:start|set)\s+(?:a\s+|an\s+)?(?:[\w.]+\s+)*timer\s+for\s+zoe\b.*{_TAIL}", re.I), "zoe_timer"),
    (re.compile(rf"^{_PLEASE}what(?:'s| is)\s+due(?:\s+this\s+week)?\s+for\s+(?:umgc|school|class|my\s+class){_TAIL}", re.I), "info_school"),
    (re.compile(rf"^{_PLEASE}what(?:'s| is)\s+due\s+for\s+(?:umgc|school|class|my\s+class){_TAIL}", re.I), "info_school"),
    (re.compile(rf"^{_PLEASE}(?:any|what(?:'s| is))\s+(?:umgc|school)\s+(?:work\s+)?due{_TAIL}", re.I), "info_school"),
    (re.compile(rf"^{_PLEASE}what(?:'s| is)\s+due\s+today{_TAIL}", re.I), "info_payday_check"),
    (re.compile(rf"^{_PLEASE}payday\s+check{_TAIL}", re.I), "info_payday_check"),
    (re.compile(rf"^{_PLEASE}any\s+reminders?\s+today{_TAIL}", re.I), "info_payday_check"),
    (re.compile(rf"^{_PLEASE}what(?:'s| is) due(?: this week)?{_TAIL}", re.I), "info_due"),
    (re.compile(rf"^{_PLEASE}when(?:'s| is)\s+rent\s+due{_TAIL}", re.I), "info_rent"),
    (re.compile(rf"^{_PLEASE}what\s+bills\s+are\s+coming\s+up{_TAIL}", re.I), "info_bills"),
    (re.compile(rf"^{_PLEASE}(?:any\s+)?bills\s+coming\s+up{_TAIL}", re.I), "info_bills"),
    (re.compile(rf"^{_PLEASE}how\s+long\s+until\s+payday{_TAIL}", re.I), "info_payday"),
    (re.compile(rf"^{_PLEASE}when(?:'s| is)\s+(?:my\s+)?payday{_TAIL}", re.I), "info_payday"),
    (re.compile(rf"^{_PLEASE}(?:am\s+i|do\s+i)\s+work(?:ing)?\s+this\s+weekend{_TAIL}", re.I), "info_weekend"),
    (re.compile(rf"^{_PLEASE}how\s+long\s+is\s+(?:my\s+)?(?:the\s+)?shift{_TAIL}", re.I), "info_shift_length"),
    (re.compile(rf"^{_PLEASE}when\s+do\s+i\s+start(?:\s+work)?\s+at\s+brea{_TAIL}", re.I), "info_brea"),
    (re.compile(rf"^{_PLEASE}when\s+does\s+brea\s+start{_TAIL}", re.I), "info_brea"),
    (re.compile(rf"^{_PLEASE}what\s+time\s+do\s+i\s+start\s+at\s+brea{_TAIL}", re.I), "info_brea"),
    (re.compile(
        rf"^{_PLEASE}my\s+shift(?:\s+on)?\s+{_SHIFT_WHEN}\s+is\s+{_SHIFT_TIME}\s+(?:to|until)\s+{_SHIFT_TIME}(?:\s+at\s+.+)?{_TAIL}",
        re.I), "shift_set"),
    (re.compile(
        rf"^{_PLEASE}(?:clear|forget)\s+my\s+shift(?:\s+on)?\s+{_SHIFT_WHEN}{_TAIL}"
        rf"|^{_PLEASE}(?:clear|forget)\s+my\s+{_SHIFT_WHEN}\s+shift{_TAIL}",
        re.I), "shift_clear"),
    (re.compile(
        rf"^{_PLEASE}(?:clear|forget)\s+(?:all\s+)?my\s+shift\s+overrides?{_TAIL}"
        rf"|^{_PLEASE}(?:clear|forget)\s+my\s+shift{_TAIL}",
        re.I), "shift_clear"),
    (re.compile(
        rf"^{_PLEASE}when\s+should\s+i\s+leave(?:\s+for\s+(?:work|brea))?{_TAIL}"
        rf"|^{_PLEASE}what\s+time\s+should\s+i\s+leave(?:\s+for\s+(?:work|brea))?{_TAIL}"
        rf"|^{_PLEASE}when\s+do\s+i\s+(?:need\s+to\s+)?leave\s+for\s+(?:work|brea){_TAIL}",
        re.I), "info_leave"),
    (re.compile(rf"^{_PLEASE}how\s+many\s+(?:ihss\s+)?hours(?:\s+do\s+i\s+have)?\s+this\s+pay\s+period{_TAIL}", re.I), "ihss_hours"),
    (re.compile(rf"^{_PLEASE}how\s+many\s+hours\s+have\s+i\s+logged(?:\s+this\s+pay\s+period)?{_TAIL}", re.I), "ihss_hours"),
    (re.compile(rf"^{_PLEASE}remind\s+me\s+to\s+submit\s+(?:my\s+)?(?:ihss\s+)?timesheet{_TAIL}", re.I), "ihss_remind"),
    (re.compile(rf"^{_PLEASE}play\s+(.+?)\s+on\s+youtube{_TAIL}", re.I), "youtube_play"),
    (re.compile(rf"^{_PLEASE}what(?:'s| is)\s+playing{_TAIL}", re.I), "media_now"),
    (re.compile(rf"^{_PLEASE}what(?:'s| is)\s+this\s+song{_TAIL}", re.I), "media_now"),
    (re.compile(rf"^{_PLEASE}what\s+song\s+is\s+this{_TAIL}", re.I), "media_now"),
    (re.compile(_PLAY, re.I), "media_play"),
    (re.compile(rf"^{_PLEASE}pause(?:\s+spotify|\s+(?:the\s+)?(?:music|song)|\s+apple\s+music)?{_TAIL}", re.I), "media_pause"),
    (re.compile(rf"^{_PLEASE}(?:next\s+(?:track|song)|skip(?:\s+(?:the\s+)?(?:track|song))?){_TAIL}", re.I), "media_next"),
    (re.compile(rf"^{_PLEASE}(?:previous\s+(?:track|song)|last\s+(?:track|song)|go\s+back(?:\s+a|\s+one)?\s+(?:track|song)){_TAIL}", re.I), "media_previous"),
    (re.compile(rf"^{_PLEASE}(?:turn\s+(?:it|the\s+volume)\s+up|(?:turn\s+)?(?:the\s+)?(?:mac\s+|system\s+)?volume\s+up|louder){_TAIL}", re.I), "volume_up"),
    (re.compile(rf"^{_PLEASE}(?:turn\s+(?:it|the\s+volume)\s+down|(?:turn\s+)?(?:the\s+)?(?:mac\s+|system\s+)?volume\s+down|quieter){_TAIL}", re.I), "volume_down"),
    (re.compile(rf"^{_PLEASE}set\s+(?:the\s+)?volume\s+to\s+.+{_TAIL}", re.I), "volume_set"),
    (re.compile(rf"^{_PLEASE}mute(?:\s+(?:the\s+)?(?:mac|volume|sound)|\s+it)?{_TAIL}", re.I), "volume_mute"),
    (re.compile(rf"^{_PLEASE}unmute(?:\s+(?:the\s+)?(?:mac|volume|sound)|\s+it)?{_TAIL}", re.I), "volume_unmute"),
    (re.compile(rf"^{_PLEASE}(?:(?:turn\s+)?(?:the\s+)?brightness\s+up|brighter){_TAIL}", re.I), "brightness_up"),
    (re.compile(rf"^{_PLEASE}(?:(?:turn\s+)?(?:the\s+)?brightness\s+down|dimmer|dim\s+the\s+screen){_TAIL}", re.I), "brightness_down"),
    (re.compile(rf"^{_PLEASE}(?:what(?:'s| is)\s+(?:my\s+)?battery(?:\s+level)?|how(?:'s| is)\s+my\s+battery|battery\s+level|how\s+much\s+battery(?:\s+do\s+i\s+have)?){_TAIL}", re.I), "info_battery"),
    (re.compile(rf"^{_PLEASE}lock\s+(?:the\s+)?(?:screen|mac|computer){_TAIL}", re.I), "system_lock"),
    (re.compile(rf"^{_PLEASE}(?:take\s+(?:a\s+)?screenshot|screenshot|capture\s+the\s+screen){_TAIL}", re.I), "screenshot"),
    (re.compile(rf"^{_PLEASE}empty\s+(?:the\s+)?trash{_TAIL}", re.I), "empty_trash"),
    (re.compile(rf"^{_PLEASE}show\s+(?:me\s+)?(?:the\s+)?desktop{_TAIL}", re.I), "show_desktop"),
    (re.compile(rf"^{_PLEASE}continue(?:\s+(?:in|on|with))?\s+chat\s*gpt{_TAIL}", re.I), "continue_chatgpt"),
    (re.compile(rf"^{_PLEASE}(?:are\s+there\s+)?any\s+new\s+orders{_TAIL}", re.I), "site_open"),
    (re.compile(rf"^{_PLEASE}(?:check|show)(?:\s+me)?\s+(?:the\s+)?(?:new\s+)?orders{_TAIL}", re.I), "site_open"),
    (re.compile(
        rf"^{_PLEASE}(?:start\s+)?focus\s+mode(?:\s+for\s+.+?)?{_TAIL}"
        rf"|^{_PLEASE}start\s+focus(?:\s+mode)?(?:\s+for\s+.+?)?{_TAIL}",
        re.I), "focus_on"),
    (re.compile(rf"^{_PLEASE}(?:check\s+(?:my\s+)?)?case\s+status{_TAIL}", re.I), "case_status"),
)
_NOTE_CMD_RE = re.compile(rf"^{_PLEASE}take\s+a\s+note\b\s*[:\-]?\s*(.*)$", re.I | re.S)
_IHSS_CMD_RE = re.compile(
    r"\blog\s+ihss\s+hours\b|\blog\s+\d+(?:\.\d+)?\s*(?:hours?)?\s+for\s+grandma\b",
    re.I,
)
_BARE_RUN_RE = re.compile(rf"^{_PLEASE}run\s+(.+?){_TAIL}", re.I)
# Checked in order. More specific calendar phrases come before "what's next".
LOCAL_PATTERNS = (
    (re.compile(r"\b(?:what day is it|what(?:'s| is) the date|what is the date|what(?:'s| is) the day)\b", re.I), "info_date"),
    (re.compile(r"\b(?:what time is it|what(?:'s| is) the time|what is the time|current time)\b", re.I), "info_time"),
    (re.compile(r"\b(?:what(?:'s| is) my schedule(?: today)?|my schedule today|what(?:'s| is) on my calendar today|on my calendar today|what(?:'s| is) on my calendar(?!\s+(?:tomorrow|yesterday)))\b", re.I), "info_today_schedule"),
    (re.compile(r"\b(?:when(?:'s| is) my next shift|what(?:'s| is) my next shift|my next shift|next shift|do i work tomorrow|what time do i start work)\b", re.I), "info_next_shift"),
    (re.compile(r"\b(?:what(?:'s| is) next(?: on my calendar)?|what(?:'s| is) my next (?:event|meeting|appointment)|when(?:'s| is) my next (?:event|meeting|appointment)|next on my calendar)\b", re.I), "info_next_event"),
    (re.compile(r"\b(?:what apps are open|which apps are open|which apps do i have open|what do i have open|what(?:'s| is) running)\b", re.I), "info_open_apps"),
)


# --------------------------------------------------------------------------- Round 2: sites, Mac, work, school, money, IHSS, Zoe
HELP_TEXT = (
    "I can open your apps and work sites, control volume, brightness, and the Mac, "
    "and play Apple Music or a YouTube search. I can read your calendar, shifts, school, "
    "and bills, log IHSS hours, remind you on payday, save a shift for one day, "
    "and say when to leave for Brea. I can run shortcuts that are in the Jev folder. "
    "I can also help with Zoe. I won't send a message or move money."
)
SCHOOL_RE = re.compile(r"(?:#|\b)(?:umgc|school|class)\b", re.I)
BILL_RE = re.compile(
    r"(?:#bill\b|\b(?:rent|bill|bills|electric|gas|water|internet|insurance|mortgage|utilities|utility|phone)\b)",
    re.I,
)
