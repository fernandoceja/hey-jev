"""My Love messages. Results are LocalSpeech so they stay on the Mac say command."""
import os
import re
import sqlite3
from .config import MESSAGES_DB, MY_LOVE_HANDLES

class LocalSpeech:
    """A reply the caller must speak with macOS say, never Fish and never an API."""

    def __init__(self, text):
        self.text = text or ""


# --------------------------------------------------------------------------- Messages (local say only)
_FDA_MESSAGE = (
    "I can't read Messages yet. Turn on Full Disk Access for Hey Jev "
    "in System Settings, Privacy and Security, then ask me again."
)


def _is_fda_error(exc):
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (1, 13):
        return True
    text = str(exc).lower()
    return any(needle in text for needle in (
        "authorization", "operation not permitted", "permission denied",
        "unable to open database", "not authorized",
    ))


def decode_attributed_body(blob):
    """Plain text from message.attributedBody when the text column is null.

    The blob is a typedstream NSAttributedString. After an NSString marker
    there is a short preamble ending in '+', then a length (one byte, or
    0x81 plus a little-endian uint16), then that many UTF-8 bytes.
    """
    if not blob:
        return ""
    if not isinstance(blob, (bytes, bytearray)):
        try:
            blob = bytes(blob)
        except Exception:
            return ""
    marker = b"NSString"
    start = 0
    while True:
        idx = blob.find(marker, start)
        if idx < 0:
            return ""
        window = blob[idx + len(marker):idx + len(marker) + 8]
        plus = window.find(b"+")
        if plus < 0:
            start = idx + len(marker)
            continue
        content = blob[idx + len(marker) + plus + 1:]
        text = _typedstream_string(content)
        if text:
            return text
        start = idx + len(marker)


def _typedstream_string(content):
    if not content:
        return ""
    if content[0] == 0x81:
        if len(content) < 3:
            return ""
        length = int.from_bytes(content[1:3], "little")
        raw = content[3:3 + length]
    else:
        length = content[0]
        raw = content[1:1 + length]
    if length <= 0 or len(raw) != length:
        return ""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    if not text:
        return ""
    printable = sum(ch.isprintable() or ch in "\n\t" for ch in text)
    if printable < max(1, int(len(text) * 0.85)):
        return ""
    return text


def _message_body(text, blob):
    if text is not None and str(text).strip():
        return str(text).strip()
    decoded = decode_attributed_body(blob)
    return decoded.strip() if decoded else ""


def _clip_speech(text, limit=400):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + ", and more"


def _probe_messages_db():
    """'ok', 'missing', 'fda', or 'error'. A one-byte read is the permission check."""
    try:
        with open(MESSAGES_DB, "rb") as handle:
            handle.read(16)
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        return "fda" if _is_fda_error(exc) else "error"
    return "ok"


def _open_messages_db():
    """A read-only connection, plus a cleanup callable.

    Opens chat.db in place when SQLite allows it. A WAL database sometimes
    refuses mode=ro because it cannot create a shared-memory file beside
    Messages, so then the db and its wal are copied to a temp folder and
    read from there. The Messages folder itself is never written.
    """
    import shutil
    import tempfile
    from urllib.parse import quote

    uri = "file:" + quote(MESSAGES_DB) + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("PRAGMA query_only = ON")
        return conn, conn.close
    except sqlite3.Error:
        pass
    folder = tempfile.mkdtemp(prefix="jev-msg-")
    try:
        dest = os.path.join(folder, "chat.db")
        shutil.copy2(MESSAGES_DB, dest)
        for suffix in ("-wal", "-shm"):
            src = MESSAGES_DB + suffix
            if os.path.isfile(src):
                shutil.copy2(src, dest + suffix)
        conn = sqlite3.connect(dest)
        conn.execute("PRAGMA query_only = ON")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    def cleanup():
        conn.close()
        shutil.rmtree(folder, ignore_errors=True)

    return conn, cleanup


def speak_my_love_messages():
    """Latest 3 incoming messages from My Love. Always a LocalSpeech result.

    Read-only sqlite. The body is not logged. Full Disk Access errors become
    a short local sentence instead of a traceback.
    """
    probed = _probe_messages_db()
    if probed == "fda":
        return LocalSpeech(_FDA_MESSAGE)
    if probed == "missing":
        return LocalSpeech("I couldn't find the Messages database.")
    if probed != "ok":
        return LocalSpeech("I couldn't read Messages just now.")
    clauses, params = [], []
    for handle_id in MY_LOVE_HANDLES:
        if "@" in handle_id:
            clauses.append("lower(h.id) = lower(?)")
        else:
            clauses.append("h.id = ?")
        params.append(handle_id)
    sql = f"""
        SELECT m.text, m.attributedBody
        FROM message AS m
        JOIN handle AS h ON h.ROWID = m.handle_id
        WHERE m.is_from_me = 0
          AND ifnull(m.associated_message_type, 0) = 0
          AND ({' OR '.join(clauses)})
        ORDER BY m.date DESC
        LIMIT 15
    """
    conn, cleanup = None, None
    try:
        conn, cleanup = _open_messages_db()
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # Older chat.db builds may not have associated_message_type.
            sql_plain = sql.replace("AND ifnull(m.associated_message_type, 0) = 0\n          ", "")
            rows = conn.execute(sql_plain, params).fetchall()
    except Exception as exc:
        if _is_fda_error(exc):
            return LocalSpeech(_FDA_MESSAGE)
        return LocalSpeech("I couldn't read Messages just now.")
    finally:
        if cleanup is not None:
            cleanup()
    bodies = []
    for text, blob in rows:
        body = _message_body(text, blob)
        if body:
            bodies.append(_clip_speech(body))
        if len(bodies) == 3:
            break
    if not bodies:
        if rows:
            return LocalSpeech("I found messages from My Love, but I couldn't read them.")
        return LocalSpeech("No messages from My Love.")
    bodies.reverse()  # oldest of the three first, so they play in order
    if len(bodies) == 1:
        return LocalSpeech("My Love said: " + bodies[0])
    labels = ("First", "Second", "Third")
    pieces = [f"{labels[i]}: {bodies[i]}." for i in range(len(bodies))]
    return LocalSpeech(f"{len(bodies)} messages from My Love. " + " ".join(pieces))
