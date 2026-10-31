"""Start my day: aliases for the morning brief. Pure phrase matching, no data source and no backend.

"start my day", "start my morning", "morning brief" and "start my morning" resolve to the existing "info_brief" action,
the one "brief me" uses. Nothing new runs.

These aliases are checked only on the Mac's own voice and typed path, after route_before_api. They are not in
route_before_api itself, because the iPhone bridge calls it through bridge_allowed(). Keeping the aliases out of it
means the phone gains no new phrases. Zoe mode sees only the same action that "brief me" already gives it.
"""
import re

START_MY_DAY_KEY = "info_brief"

# Whole utterance only, so "play my morning brief" and "start my day tomorrow" keep their own routes or the LLM.
_START_MY_DAY = re.compile(
    r"^(?:hey\s+jev\b[\s,]*)?(?:please\s+)?"
    r"(?:start\s+my\s+(?:day|morning)|(?:the\s+)?morning\s+brief(?:ing)?)"
    r"(?:\s+please)?[.!?]*$",
    re.I,
)


def start_my_day_action(text):
    """"info_brief" when the whole utterance is a start-my-day alias, else None. Case, spacing and trailing punctuation
    do not matter. Empty and non-string input are not aliases."""
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    return START_MY_DAY_KEY if _START_MY_DAY.match(cleaned) else None
