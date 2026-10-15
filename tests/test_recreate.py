import json
import os
import socket

import pytest

import commands
from commands import recreate
from commands.bridge import bridge_allowed
from commands.config import BRIDGE_ALLOW, CONFIRM
from commands.routing import route_before_api


class Book:
    def __init__(self, path=None):
        self.last = {"path": path, "kind": "screenshot"} if path else None


@pytest.mark.parametrize("text", [
    "recreate airbnb.com",
    "Hey Jev, recreate a budget tracker",
    "please recreate airbnb dot com and add dark mode",
    "rebuild this screenshot",
    "recreate this",
])
def test_routes_to_recreate(text):
    assert route_before_api(text) == "recreate_this"


@pytest.mark.parametrize("text", ["recreate status", "what's the recreate status", "how's my recreate job going"])
def test_routes_status(text):
    assert route_before_api(text) == "recreate_status"


def test_not_on_phone_bridge():
    for key in ("recreate_this", "recreate_status"):
        assert key not in BRIDGE_ALLOW
    assert "recreate_this" in CONFIRM
    assert bridge_allowed("recreate airbnb.com") is None
    assert bridge_allowed("recreate status") is None


def test_parse_url_and_spoken():
    t = recreate.parse_target("recreate Airbnb dot com")
    assert t["kind"] == "url" and t["value"] == "airbnb.com"
    t = recreate.parse_target("recreate https://example.com/pricing please")
    assert t["kind"] == "url" and t["value"].startswith("https://example.com/pricing")
    t = recreate.parse_target("recreate a budget tracker")
    assert t == {"kind": "spoken", "value": "a budget tracker", "spoken": "a budget tracker"}
    assert "a budget tracker" in recreate.confirm_prompt(t)


def test_parse_image_uses_last_capture(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"png")
    t = recreate.parse_target("recreate this screenshot", book=Book(str(img)))
    assert t["kind"] == "image" and t["value"] == str(img)
    assert recreate.parse_target("recreate this", book=Book(None)) is None
    assert recreate.parse_target("recreate", book=Book(None)) is None


def test_write_job_card(tmp_path):
    t = recreate.parse_target("recreate airbnb.com")
    reply = recreate.write_job_card(t, "recreate airbnb.com", base=str(tmp_path), now=100, platform="darwin", job_id="abc12345")
    assert "Chief of Staff" in reply
    card = json.loads((tmp_path / "inbox" / "abc12345.json").read_text())
    assert card["kind"] == "url" and card["target"] == "airbnb.com" and card["created"] == 100
    assert card["source"] == "mac"
    assert not list((tmp_path / "inbox").glob("*.tmp"))


def test_write_job_card_copies_image(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"png")
    base = tmp_path / "handoff"
    t = recreate.parse_target("recreate this image", book=Book(str(img)))
    recreate.write_job_card(t, "recreate this image", base=str(base), platform="darwin", job_id="img12345")
    card = json.loads((base / "inbox" / "img12345.json").read_text())
    assert card["image"] == "img12345.png"
    assert (base / "inbox" / "img12345.png").read_bytes() == b"png"


def test_mac_only(tmp_path):
    t = recreate.parse_target("recreate airbnb.com")
    assert "Mac" in recreate.write_job_card(t, "x", base=str(tmp_path), platform="linux")
    assert not (tmp_path / "inbox").exists()


def test_read_status(tmp_path):
    assert recreate.read_status(base=str(tmp_path)) == "No recreate updates yet."
    out = tmp_path / "outbox"
    out.mkdir()
    (out / "status.json").write_text("not json")
    assert "couldn't" in recreate.read_status(base=str(tmp_path))
    (out / "status.json").write_text(json.dumps({"message": "Your recreate plan is\nready to review."}))
    assert recreate.read_status(base=str(tmp_path)) == "Your recreate plan is ready to review."


def test_status_ignores_symlink(tmp_path):
    out = tmp_path / "outbox"
    out.mkdir()
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"message": "secret"}))
    os.symlink(real, out / "status.json")
    assert recreate.read_status(base=str(tmp_path)) == "No recreate updates yet."


def test_no_sockets(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("socket opened")
    monkeypatch.setattr(socket, "socket", boom)
    t = recreate.parse_target("recreate airbnb.com")
    recreate.write_job_card(t, "recreate airbnb.com", base=str(tmp_path), platform="darwin")
    recreate.read_status(base=str(tmp_path))


def test_exports():
    assert commands.recreate_target and commands.recreate_write_job and commands.recreate_status
