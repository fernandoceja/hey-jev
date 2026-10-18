"""Queue local agent jobs and read back their statuses by voice.

"have an agent build X", "ask an agent to research X", "what's my agent doing",
"agent status". Jev writes a JSON job file to
~/Library/Application Support/Hey Jev/agent-jobs/<id>.json with
{id, text, time, status="queued"} and reads the latest statuses back from that
folder. An external agent (Grok Bot Chief of Staff) picks up queued files and
updates their status; Jev only writes and reads the files.

Requests about paying, buying, purchasing, or transferring money are refused
before any file is written. Nothing here opens a socket or contacts the
network. Mac-only, and not on the iPhone bridge allowlist.
"""
from datetime import datetime
import json
import os
import re
import sys
import uuid

from . import config
from .textutil import _clean

AGENT_JOBS_DIR_ENV = "JEV_AGENT_JOBS_DIR"
DEFAULT_AGENT_JOBS_DIR = os.path.expanduser(
    "~/Library/Application Support/Hey Jev/agent-jobs"
)
MAX_JOB_TEXT_CHARS = 500
MAX_STATUS_CHARS = 240
MAX_JOB_BYTES = 64 * 1024
MAX_SPOKEN_JOBS = 3

AGENT_QUEUED = "Got it, I queued that for your agent."
AGENT_EMPTY = "No agent jobs yet."
AGENT_UNCLEAR = "Tell me what you'd like your agent to build or research."
AGENT_NOT_MAC = "Agent jobs only work on the Mac."
AGENT_MONEY_REFUSED = (
    "I can't queue agent jobs that buy, pay, or transfer money."
)

_LEAD = r"^(?:please\s+)?(?:hey\s+jev\b\s*,?\s+)?(?:please\s+)?(?:can\s+you\s+|could\s+you\s+)?"
_STATUS_RE = re.compile(
    rf"{_LEAD}(?:"
    r"what(?:'s|\s+is|\s+are)\s+(?:my|the)\s+agents?\s+(?:doing|working\s+on|up\s+to)(?:\s+right\s+now)?"
    r"|how(?:'s|\s+is|\s+are)\s+(?:my|the)\s+agents?\s+(?:doing|going)(?:\s+right\s+now)?"
    r"|(?:what(?:'s|\s+is)\s+(?:the\s+|my\s+)?|check\s+(?:the\s+|my\s+)?|)(?:my\s+)?agent(?:'s|s)?\s+(?:job\s+|jobs\s+)?status"
    r"|status\s+of\s+(?:my|the)\s+agents?(?:\s+jobs?)?"
    r")(?:\s+please)?[\s.!?]*$",
    re.I,
)
_JOB_RE = re.compile(
    rf"{_LEAD}(?:"
    r"(?:have|ask|tell|get)\s+(?:an?|my|the)\s+agent\b(?:\s+to\b)?(?:\s+(?P<task>.+?))?"
    r"|queue\s+(?:an?\s+)?agent\s+job\b(?:\s+to\b|\s*:)?(?:\s+(?P<queued>.+?))?"
    r")(?:\s+please)?[\s.!?]*$",
    re.I,
)
_MONEY_RE = re.compile(
    r"(?:"
    r"\b(?:pay|paying|paid|payments?|payday"
    r"|buy|buying|bought"
    r"|purchas(?:e|es|ed|ing)"
    r"|transfer|transferring|transferred|transfers"
    r"|wire|wiring"
    r"|spend|spending|spent"
    r"|checkout|check\s+out"
    r"|venmo|zelle|paypal|cash\s*app|apple\s+pay"
    r"|money|cash|funds|dollars?|bucks|usd|bitcoin|crypto)\b"
    r"|\$\s*\d"
    r"|\b(?:send|sending|move|moving|deposit|depositing|withdraw|withdrawing|sweep|sweeping)\s+"
    r"(?:money|cash|funds|\$|\d)"
    r")",
    re.I,
)


def _squash(text):
    return re.sub(r"\s+", " ", _clean(text or "")).strip()


def agent_jobs_dir(jobs_dir=None, env=None):
    if jobs_dir:
        return os.path.expanduser(jobs_dir)
    env = os.environ if env is None else env
    override = env.get(AGENT_JOBS_DIR_ENV)
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser(getattr(config, "AGENT_JOBS_DIR", DEFAULT_AGENT_JOBS_DIR))


def is_agent_status_phrase(text):
    return bool(_STATUS_RE.match(_squash(text)))


def is_agent_job_phrase(text):
    raw = _squash(text)
    if not raw or is_agent_status_phrase(raw):
        return False
    return bool(_JOB_RE.match(raw))


def parse_agent_job(text):
    """Extract the task text from an agent job phrase, or None when missing."""
    raw = _squash(text)
    if not raw or is_agent_status_phrase(raw):
        return None
    match = _JOB_RE.match(raw)
    if not match:
        return None
    task = (match.group("task") or match.group("queued") or "").strip(" ,.!?")
    task = re.sub(r"\s+please$", "", task, flags=re.I).strip(" ,.!?")
    if not task:
        return None
    return task[:MAX_JOB_TEXT_CHARS]


def is_money_job(text):
    """True when the text asks to pay, buy, purchase, or transfer money."""
    return bool(_MONEY_RE.search(text or ""))


def _timestamp(now=None):
    if now is None:
        return datetime.now().astimezone().isoformat(timespec="seconds")
    if isinstance(now, datetime):
        return now.isoformat(timespec="seconds")
    return now


def _write_job_file(dest, payload):
    if os.path.islink(dest):
        raise OSError("refusing to write through a symlink")
    tmp = dest + ".tmp"
    if os.path.islink(tmp):
        raise OSError("refusing to write through a symlink")
    data = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)


def queue_agent_job(text, jobs_dir=None, now=None, job_id=None, platform=None):
    """Save one queued job JSON file and return the spoken confirmation."""
    if (sys.platform if platform is None else platform) != "darwin":
        return AGENT_NOT_MAC
    task = parse_agent_job(text)
    if not task:
        return AGENT_UNCLEAR
    if is_money_job(task) or is_money_job(text):
        return AGENT_MONEY_REFUSED
    folder = agent_jobs_dir(jobs_dir)
    if os.path.islink(folder):
        return "I couldn't save that agent job."
    os.makedirs(folder, exist_ok=True)
    chosen_id = re.sub(r"[^A-Za-z0-9_-]", "", str(job_id or "")) or uuid.uuid4().hex[:12]
    job = {
        "id": chosen_id,
        "text": task,
        "time": _timestamp(now),
        "status": "queued",
    }
    dest = os.path.join(folder, chosen_id + ".json")
    try:
        _write_job_file(dest, job)
    except OSError:
        return "I couldn't save that agent job."
    return AGENT_QUEUED


def _parse_time_value(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        try:
            return float(raw)
        except ValueError:
            pass
        try:
            norm = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
            dt = datetime.fromisoformat(norm)
            if dt.tzinfo is None:
                dt = dt.astimezone()
            return dt.timestamp()
        except ValueError:
            return None
    return None


def read_agent_jobs(jobs_dir=None):
    """Return job dicts from jobs_dir, newest first."""
    folder = agent_jobs_dir(jobs_dir)
    if os.path.islink(folder) or not os.path.isdir(folder):
        return []
    entries = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    for index, name in enumerate(names):
        if name.startswith(".") or not name.lower().endswith(".json"):
            continue
        path = os.path.join(folder, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            if os.path.getsize(path) > MAX_JOB_BYTES:
                continue
            mtime = os.path.getmtime(path)
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        job_text = str(data.get("text") or "").strip()
        job_id = str(data.get("id") or os.path.splitext(name)[0]).strip()
        if not job_text and not job_id:
            continue
        status = str(data.get("status") or "queued").strip() or "queued"
        stamp = _parse_time_value(data.get("time"))
        if stamp is None:
            stamp = mtime
        entries.append((stamp, mtime, index, {
            "id": job_id,
            "text": job_text or job_id,
            "time": data.get("time"),
            "status": status,
            "detail": str(
                data.get("summary") or data.get("result") or data.get("message") or ""
            ).strip(),
        }))
    entries.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [item[3] for item in entries]


def _format_job_status(job):
    text = re.sub(r"\s+", " ", str(job.get("text") or "job")).strip(" .!?")[:MAX_STATUS_CHARS]
    raw_status = re.sub(r"[_-]+", " ", str(job.get("status") or "queued")).strip(" .!?")
    status = re.sub(r"\s+", " ", raw_status).strip() or "queued"
    detail = re.sub(r"\s+", " ", str(job.get("detail") or "")).strip(" .!?")
    if detail:
        detail = detail[:MAX_STATUS_CHARS]
        return f"{text} is {status}: {detail}."
    return f"{text} is {status}."


def speak_agent_status(jobs_dir=None, limit=MAX_SPOKEN_JOBS, platform=None):
    """Read back the latest agent job statuses from jobs_dir."""
    if (sys.platform if platform is None else platform) != "darwin":
        return AGENT_NOT_MAC
    jobs = read_agent_jobs(jobs_dir)
    if not jobs:
        return AGENT_EMPTY
    shown = jobs[: max(1, int(limit))]
    return " ".join(_format_job_status(job) for job in shown)
