"""Open Apple's Passwords app and type a site or app name into its search field.

Mac only. The only data this module handles is that name. It does not read,
store, speak, log, or send a password or a username. There is no search URL
for the Passwords app (macOS 15+, bundle id com.apple.Passwords). otpauth
links add a one-time code, and the old System Settings link does not search
this app, so System Events writes the name into the search field. It does
not send keystrokes, because those could land on the wrong control.

The script never reads a field value, never touches the clipboard, and never
calls the security tool. If the search field is not there yet, because the
app is locked, it only opens the app. Fernando unlocks it with Touch ID and
copies the login himself. Tests pass a runner so nothing here launches an app.
"""
import re

from .shell import _run
from .textutil import _clean

PASSWORD_LOOKUP = "password_lookup"
PASSWORD_KEYS = frozenset({PASSWORD_LOOKUP})
PASSWORDS_BUNDLE = "com.apple.Passwords"

# Whole-utterance shape, same idea as the other strict commands.
_PLEASE = r"(?:please\s+)?"
_HEY = r"(?:hey\s+jev\b\s*,?\s+)?"
_TAIL = r"(?:\s+please)?[.!?]*$"
_KIND = r"(?:passwords?|logins?|log\s+ins?)"
_LEAD = (
    r"(?:what(?:'s|s| is)\s+)?(?:my\s+|the\s+)?" + _KIND + r"\s+for\s+"
    r"|show(?:\s+me)?\s+(?:my\s+|the\s+)?" + _KIND + r"\s+for\s+"
    r"|(?:find|look\s+up|lookup)\s+(?:my\s+|the\s+)?" + _KIND + r"\s+for\s+"
)
LOOKUP_RE = re.compile(
    r"^" + _PLEASE + _HEY + _PLEASE + r"(?:" + _LEAD + r")(?P<name>.+?)" + _TAIL,
    re.I,
)
# Someone dictating the secret itself. Matched locally so it never reaches an API.
# The secret is not kept on the query object.
DICTATED_RE = re.compile(
    r"^" + _PLEASE + _HEY + _PLEASE
    + r"(?:my\s+|the\s+)?(?:password|passcode)\s*(?:is|=|:)\s*\S.*$",
    re.I,
)
_SECRET_SPLIT = re.compile(r"\s*(?::|\b(?:is|equals)\b)\s+", re.I)
_SITE_CHARS = re.compile(r"[^A-Za-z0-9 .&+'\-]")

OPENED_LINE = "Opened Passwords for {0}. Unlock with Touch ID."
MISSING_LINE = "Passwords needs macOS 15, and it isn't on this Mac."
TYPE_FAIL_LINE = (
    "Opened Passwords for {0}. I couldn't type the search. "
    "Allow Accessibility for Hey Jev, then try again."
)
WHICH_LINE = "Which site or app?"
REFUSE_LINE = "I only search for the site or app. I never take the password itself."
ASK_LINE = "Say password for, and the site or app."

# Writes the name into the search field only. Returns one status word.
# "opened" means the app is up and the search field was not there (often locked).
# The name arrives as argv. It is not pasted into this script.
SEARCH_SCRIPT = '''on run argv
  set query to item 1 of argv
  tell application "System Events"
    if not (exists process "Passwords") then
      repeat 8 times
        delay 0.25
        if exists process "Passwords" then exit repeat
      end repeat
    end if
    if not (exists process "Passwords") then
      return "missing"
    end if
    tell process "Passwords"
      set frontmost to true
      set targetField to missing value
      try
        if exists window 1 then
          if exists toolbar 1 of window 1 then
            repeat with candidate in text fields of toolbar 1 of window 1
              try
                if subrole of candidate is "AXSearchField" then
                  set targetField to candidate
                  exit repeat
                end if
              end try
            end repeat
          end if
          if targetField is missing value then
            repeat with candidate in text fields of window 1
              try
                if subrole of candidate is "AXSearchField" then
                  set targetField to candidate
                  exit repeat
                end if
              end try
            end repeat
          end if
        end if
      end try
      if targetField is missing value then
        return "opened"
      end if
      try
        set focused of targetField to true
        set value of targetField to query
        return "searched"
      on error
        return "opened"
      end try
    end tell
  end tell
end run
'''

_STATUS_WORDS = frozenset({"searched", "opened", "missing"})


class PasswordQuery(object):
    """The site or app name to type. refused means a secret was dictated and dropped."""

    def __init__(self, term, refused=False):
        self.term = term or ""
        self.refused = bool(refused)

    def __repr__(self):
        return "PasswordQuery(term={0!r}, refused={1})".format(self.term, self.refused)


def is_password_lookup(text):
    """True when this utterance must stay on the Mac, joiner or not."""
    raw = _clean(text).strip()
    if not raw:
        return False
    return LOOKUP_RE.match(raw) is not None or DICTATED_RE.match(raw) is not None


def _site_term(name):
    """The words to type, or None when a dictated secret left no site name.

    An empty string means the phrase matched and no name was left.
    Anything after "is", "equals", or a colon is discarded and not returned.
    """
    text = " ".join(_clean(name).split())
    text = re.sub(r"\s+please$", "", text, flags=re.I).strip(" .,!?;\"'")
    parts = _SECRET_SPLIT.split(text, maxsplit=1)
    had_secret = len(parts) > 1
    site = parts[0]
    site = re.sub(r"^(?:my|the)\s+", "", site, flags=re.I).strip()
    site = _SITE_CHARS.sub("", site)
    site = " ".join(site.split())
    if not site or len(site) > 80 or len(site.split()) > 8 or not re.search(r"[A-Za-z0-9]", site):
        return None if had_secret else ""
    return site


def parse_password_query(text):
    """PasswordQuery, or None when this is not a password lookup.

    The object holds the site or app name only. A dictated secret is not stored.
    """
    raw = _clean(text).strip()
    match = LOOKUP_RE.match(raw)
    if match:
        term = _site_term(match.group("name"))
        if term is None:
            return PasswordQuery("", refused=True)
        return PasswordQuery(term, refused=False)
    if DICTATED_RE.match(raw):
        return PasswordQuery("", refused=True)
    return None


def _default_runner(args):
    """Argument list only. The name is an argv item, never a shell string."""
    return _run(args)


def _status(stdout):
    """One known status word. Anything else is ignored so it cannot be spoken."""
    lines = str(stdout or "").splitlines()
    if not lines:
        return "opened"
    token = lines[-1].strip().lower()
    if token in _STATUS_WORDS:
        return token
    return "opened"


def lookup_password(text, runner=None):
    """Open Passwords, type the site name, and return the sentence to speak.

    runner replaces process launches in tests. The return value is a fixed
    sentence plus the site name. It is never a password, a username, or
    whatever the script printed.
    """
    parsed = parse_password_query(text)
    if parsed is None:
        return ASK_LINE
    if parsed.refused:
        return REFUSE_LINE
    if not parsed.term:
        return WHICH_LINE
    run = runner or _default_runner
    try:
        run(["open", "-b", PASSWORDS_BUNDLE])
    except Exception:
        return MISSING_LINE
    try:
        stdout = run(["osascript", "-e", SEARCH_SCRIPT, parsed.term])
    except Exception:
        return TYPE_FAIL_LINE.format(parsed.term)
    if _status(stdout) == "missing":
        return MISSING_LINE
    return OPENED_LINE.format(parsed.term)
