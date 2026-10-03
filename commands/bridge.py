"""iPhone bridge: signed iCloud inbox files, no listening socket."""
import hashlib
import hmac
import json
import os
import re
import threading
import time
from .config import BRIDGE_ALLOW, BRIDGE_INBOX, BRIDGE_MAX_AGE, BRIDGE_MAX_CMD, BRIDGE_OUTBOX, BRIDGE_POLL_SECONDS, BRIDGE_SECRET_ACCOUNT, CONFIRM, NONCE_LIMIT, NONCE_LOG, NONCE_RE, OUTBOX_TTL_SECONDS
from .routing import route_before_api

# --------------------------------------------------------------------------- iPhone bridge (iCloud files only, no listener)
_bridge_thread = None
_bridge_lock = threading.Lock()
_bridge_secret_warned = False


def bridge_allowed(text):
    """Action key when a phone command is on the allowlist, else None.

    Quit-all never comes back from route_before_api(). Message reads do, and
    they are absent from BRIDGE_ALLOW, so the body cannot be written to iCloud.
    """
    action = route_before_api(text)
    if not action or action in CONFIRM or action not in BRIDGE_ALLOW:
        return None
    return action


def _canonical_ts(ts):
    """Decimal unix seconds, the form that is signed. None if it is not whole seconds."""
    if isinstance(ts, bool):
        return None
    if isinstance(ts, int):
        return str(ts)
    if isinstance(ts, float):
        if not ts.is_integer():
            return None
        return str(int(ts))
    if isinstance(ts, str) and re.fullmatch(r"-?\d+", ts.strip()):
        return ts.strip()
    return None


def _bridge_secret():
    """Keychain only. A .env value must not be able to stand in for this."""
    from secrets_store import keychain_value
    return keychain_value(BRIDGE_SECRET_ACCOUNT)


def _expected_sig(secret, cmd, ts_canon, nonce):
    payload = f"{cmd}|{ts_canon}|{nonce}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _load_nonces():
    try:
        with open(NONCE_LOG, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str)]


def _remember_nonce(nonce):
    os.makedirs(os.path.dirname(NONCE_LOG), exist_ok=True)
    seen = [item for item in _load_nonces() if item != nonce]
    seen.append(nonce)
    seen = seen[-NONCE_LIMIT:]
    tmp = NONCE_LOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(seen, handle)
    os.replace(tmp, NONCE_LOG)


def _nonce_used(nonce):
    return nonce in _load_nonces()


def _write_outbox(nonce, ok, reply):
    os.makedirs(BRIDGE_OUTBOX, exist_ok=True)
    dest = os.path.join(BRIDGE_OUTBOX, nonce + ".json")
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"ok": bool(ok), "nonce": nonce, "reply": reply}, handle)
        handle.write("\n")
    os.replace(tmp, dest)


def sweep_outbox(now=None):
    """Delete reply files in the outbox that are older than OUTBOX_TTL_SECONDS.

    Only regular files sitting directly in that directory are considered, and
    only when the name is a bridge nonce plus ``.json``. Nothing outside the
    outbox, nothing in a subdirectory, and no other name is removed.
    """
    now = time.time() if now is None else now
    try:
        names = os.listdir(BRIDGE_OUTBOX)
    except OSError:
        return 0
    removed = 0
    for name in names:
        if not name.endswith(".json") or not NONCE_RE.match(name[:-5]):
            continue
        path = os.path.join(BRIDGE_OUTBOX, name)
        # A symlink's name can match while its target lives somewhere else.
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if age <= OUTBOX_TTL_SECONDS:
            continue
        try:
            os.remove(path)
        except OSError:
            continue
        removed += 1
    return removed


def _delete_inbox(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _process_bridge_file(path, run_text):
    """Validate one inbox file, maybe run it, always try to clear it once it is JSON."""
    global _bridge_secret_warned
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        age = time.time() - os.path.getmtime(path)
        if age > 30:
            _delete_inbox(path)
        return
    if not isinstance(data, dict):
        _delete_inbox(path)
        return
    cmd = data.get("cmd")
    nonce = data.get("nonce")
    sig = data.get("sig")
    ts_canon = _canonical_ts(data.get("ts"))
    safe_nonce = isinstance(nonce, str) and bool(NONCE_RE.match(nonce))
    if not isinstance(cmd, str) or not safe_nonce or not isinstance(sig, str) or ts_canon is None:
        if safe_nonce:
            _write_outbox(nonce, False, "That command file was incomplete.")
        _delete_inbox(path)
        return
    secret = _bridge_secret()
    if not secret:
        if not _bridge_secret_warned:
            print("  bridge: no JEV_BRIDGE_SECRET in the Keychain. Run python siri.py --bridge-secret")
            _bridge_secret_warned = True
        return  # leave the file so it can run once a secret exists
    expected = _expected_sig(secret, cmd, ts_canon, nonce)
    if not hmac.compare_digest(expected, sig.strip().lower()):
        _write_outbox(nonce, False, "I couldn't verify that command.")
        _remember_nonce(nonce)
        _delete_inbox(path)
        return
    try:
        age = abs(time.time() - int(ts_canon))
    except ValueError:
        age = BRIDGE_MAX_AGE + 1
    if age > BRIDGE_MAX_AGE:
        _write_outbox(nonce, False, "That command was too old. Try again.")
        _remember_nonce(nonce)
        _delete_inbox(path)
        return
    if _nonce_used(nonce):
        _write_outbox(nonce, False, "I already did that.")
        _delete_inbox(path)
        return
    _remember_nonce(nonce)
    if len(cmd) > BRIDGE_MAX_CMD:
        _write_outbox(nonce, False, "That command is too long.")
        _delete_inbox(path)
        return
    action = bridge_allowed(cmd)
    if not action:
        _write_outbox(nonce, False, "I can't do that from your phone.")
        _delete_inbox(path)
        return
    ok = True
    try:
        reply = run_text(cmd.strip())
    except Exception as exc:
        print(f"  bridge: {type(exc).__name__}")
        ok, reply = False, "I couldn't do that just now."
    if not reply:
        ok, reply = False, "I couldn't do that just now."
    _write_outbox(nonce, ok, reply)
    _delete_inbox(path)


def poll_bridge(run_text):
    """Handle every JSON file currently in the iCloud inbox. No socket is opened."""
    sweep_outbox()
    try:
        os.makedirs(BRIDGE_INBOX, exist_ok=True)
        os.makedirs(BRIDGE_OUTBOX, exist_ok=True)
    except OSError as exc:
        print(f"  bridge: {exc}")
        return
    try:
        names = sorted(os.listdir(BRIDGE_INBOX))
    except OSError as exc:
        print(f"  bridge: {exc}")
        return
    for name in names:
        if name.startswith(".") or not name.endswith(".json"):
            continue
        path = os.path.join(BRIDGE_INBOX, name)
        if not os.path.isfile(path):
            continue
        try:
            _process_bridge_file(path, run_text)
        except Exception as exc:
            print(f"  bridge: {type(exc).__name__}")


def start_bridge_thread(run_text):
    """Poll the inbox every 2 seconds. run_text(cmd) returns the spoken reply."""
    global _bridge_thread

    sweep_outbox()

    def loop():
        while True:
            try:
                poll_bridge(run_text)
            except Exception as exc:
                print(f"  bridge: {type(exc).__name__}")
            time.sleep(BRIDGE_POLL_SECONDS)

    with _bridge_lock:
        if _bridge_thread is not None and _bridge_thread.is_alive():
            return
        _bridge_thread = threading.Thread(target=loop, name="jev-bridge", daemon=True)
        _bridge_thread.start()
