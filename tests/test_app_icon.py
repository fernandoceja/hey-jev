"""Check bundled icon formats without build-time imaging dependencies."""
from pathlib import Path
import struct


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    assert data[24:26] == bytes((8, 6))  # 8-bit RGBA
    return struct.unpack(">II", data[16:24])


def test_orb_icon_master():
    assert png_size((ASSETS / "icon.png").read_bytes()) == (1024, 1024)


def test_orb_icns_representations():
    data = (ASSETS / "icon.icns").read_bytes()
    assert data[:4] == b"icns"
    assert struct.unpack(">I", data[4:8])[0] == len(data)
    entries = {}
    offset = 8
    while offset < len(data):
        kind, length = struct.unpack(">4sI", data[offset:offset + 8])
        assert length > 8
        entries[kind] = png_size(data[offset + 8:offset + length])
        offset += length
    assert offset == len(data)
    assert entries == {kind.encode(): (size, size) for kind, size in (
        ("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128),
        ("ic08", 256), ("ic09", 512), ("ic10", 1024),
        ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512))}
