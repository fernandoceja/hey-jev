#!/usr/bin/env python3
"""Build the idle orb icon. Requires Pillow at build time only.

Run from any directory: python scripts/build_orb_icon.py
Matches orb_layers' axial body gradient, radial shadow, eye paths and highlight.
Core Animation's bottom-left coordinates are flipped for PNG's top-left origin.
"""
import io
import math
from pathlib import Path
import struct
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import orb_motion as orb
from orb_character import eye_shape


def render(size=1024):
    """Rasterize at 2x resolution, then antialias down to the requested size."""
    pixels = size * 2
    scale = pixels / orb.DESIGN_SIZE
    geometry = orb.layer_geometry()
    image = Image.new("RGBA", (pixels, pixels))
    raw = bytearray(pixels * pixels * 4)
    angle = math.radians(orb.ORB_GRADIENT_ANGLE)
    dx, dy = math.cos(angle), math.sin(angle)
    bx, by, _, _ = geometry["body"]
    sx, sy = orb.SHADOW_ORIGIN
    sw, sh = orb.SHADOW_SIZE
    # SHADOW_RADIUS is a legacy constant; orb_layers._shadow_image uses
    # SHADOW_SIZE / 2 for its radial extent, with no Gaussian blur.
    for row in range(pixels):
        y = orb.DESIGN_SIZE - (row + 0.5) / scale
        for col in range(pixels):
            x = (col + 0.5) / scale
            i = (row * pixels + col) * 4
            if math.hypot(x - bx - orb.BODY_SIZE / 2,
                          y - by - orb.BODY_SIZE / 2) <= orb.BODY_SIZE / 2:
                t = max(0.0, min(1.0, 0.5 + (
                    (x - bx - orb.BODY_SIZE / 2) * dx
                    + (y - by - orb.BODY_SIZE / 2) * dy) / orb.BODY_SIZE))
                segment = min(int(t * (len(orb.ORB_PALETTE) - 1)), len(orb.ORB_PALETTE) - 2)
                mix = t * (len(orb.ORB_PALETTE) - 1) - segment
                a, b = orb.ORB_PALETTE[segment:segment + 2]
                raw[i:i + 4] = bytes([round(255 * (v + (w - v) * mix))
                                      for v, w in zip(a, b)] + [255])
            else:
                distance = math.hypot((x - sx - sw / 2) / (sw / 2),
                                      (y - sy - sh / 2) / (sh / 2))
                alpha = round(255 * orb.SHADOW_OPACITY * max(0.0, 1 - distance))
                if alpha:
                    raw[i:i + 4] = bytes([round(c * 255) for c in orb.SHADOW_RGB] + [alpha])
    image = Image.frombytes("RGBA", image.size, bytes(raw))

    def point(x, y):
        return (x * scale, (orb.DESIGN_SIZE - y) * scale)

    overlay = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(overlay)
    hx, hy = orb.HIGHLIGHT_ORIGIN
    hw, hh = orb.HIGHLIGHT_SIZE
    draw.ellipse((*point(hx, hy + hh), *point(hx + hw, hy)),
                 fill=(255, 255, 255, round(255 * orb.HIGHLIGHT_ALPHA)))
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)
    # Use the live open-eye Bezier, rather than approximating it with an ellipse.
    for side in ("L", "R"):
        ex, ey, _, _ = geometry["eye" + side]
        kx, ky = orb.EYE_PERSPECTIVE[side]
        path = eye_shape("open", orb.EYE_SIZE)
        polygon = []
        for start in range(0, 12, 3):
            controls = path[start:start + 4]
            for step in range(33):
                t = step / 32.0
                weights = ((1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3)
                x, y = (sum(p[axis] * w for p, w in zip(controls, weights))
                        for axis in (0, 1))
                polygon.append(point(ex + orb.EYE_SIZE / 2 + (x - orb.EYE_SIZE / 2) * kx,
                                     ey + orb.EYE_SIZE / 2 + (y - orb.EYE_SIZE / 2) * ky))
        draw.polygon(polygon, fill=tuple(round(c * 255) for c in orb.EYE_EDGE_RGB) + (255,))
    return image.resize((size, size), Image.Resampling.LANCZOS)


def write_icns(image, path):
    """PNG-backed ICNS entries for standard 1x and Retina representations."""
    entries = ((b"icp4", 16), (b"icp5", 32), (b"icp6", 64),
               (b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024),
               (b"ic11", 32), (b"ic12", 64), (b"ic13", 256), (b"ic14", 512))
    chunks = []
    for kind, size in entries:
        buffer = io.BytesIO()
        image.resize((size, size), Image.Resampling.LANCZOS).save(buffer, format="PNG")
        data = buffer.getvalue()
        chunks.append(kind + struct.pack(">I", len(data) + 8) + data)
    data = b"".join(chunks)
    path.write_bytes(b"icns" + struct.pack(">I", len(data) + 8) + data)


if __name__ == "__main__":
    master = render()
    master.save(ROOT / "assets/icon.png")
    write_icns(master, ROOT / "assets/icon.icns")
