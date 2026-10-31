"""Full Jev window (PR 5 of the Eney-style redesign).

The popover's expand button opens this window. It shows the same typed
conversation (TypedHistory) as the popover, a history list, the last result
or tool output, the input and mic row, and the quick-action chips. It owns no
backend: every action calls back into the AppDelegate (miniSubmit-style
dispatch, miniChip:, miniMicDown:/miniMicUp:).

Palette follows the REA reference (website/public/assets/styles.css):
ink/muted/line/soft/accent in light and dark variants, system sans for text,
SF Mono for tool output. The layout helpers below are pure Python so they can
be tested without AppKit.
"""

FULL_AUTOSAVE = "JevFullWindow"
FULL_DEFAULT = (760.0, 560.0)
FULL_MIN = (560.0, 420.0)
FULL_MAX = (1600.0, 1200.0)
SIDEBAR_W = 200.0
PAD = 16.0
INPUT_H = 40.0
CHIP_ROW_H = 40.0
RESULT_H = 118.0
TITLEBAR_H = 28.0
CORNER = 16.0
DOCK_ORB = 36.0  # PR 6a: the orb's size when it is docked on the sidebar/chat divider

# REA design tokens (light, dark) as RGB 0-255.
PALETTE = {
    "ink": ((0x20, 0x25, 0x2B), (0xCD, 0xD6, 0xF4)),
    "muted": ((0x5B, 0x65, 0x70), (0xA6, 0xAD, 0xC8)),
    "line": ((0xE0, 0xE5, 0xE9), (0x45, 0x47, 0x5A)),
    "soft": ((0xF4, 0xF6, 0xF8), (0x18, 0x18, 0x25)),
    "accent": ((0x29, 0x4F, 0x82), (0x89, 0xB4, 0xFA)),
    "page": ((0xFF, 0xFF, 0xFF), (0x1E, 0x1E, 0x2E)),
}


def token(name, dark=False):
    """RGB floats 0-1 for one REA token."""
    rgb = PALETTE[name][1 if dark else 0]
    return tuple(round(c / 255.0, 4) for c in rgb)


def clamp_full_size(width, height):
    w = min(max(float(width), FULL_MIN[0]), FULL_MAX[0])
    h = min(max(float(height), FULL_MIN[1]), FULL_MAX[1])
    return (w, h)


def full_chrome(reduce_transparency):
    """Vibrancy normally; a solid page colour when Reduce Transparency is on."""
    if reduce_transparency:
        return {"backing": "solid", "material": None}
    return {"backing": "vibrancy", "material": "sidebar"}


def full_layout(width, height, show_result=True):
    """Frames (x, y, w, h), bottom-left origin, for the full window content."""
    w, h = clamp_full_size(width, height)
    top = h - TITLEBAR_H
    side = (0.0, 0.0, SIDEBAR_W, h)
    side_title = (PAD, top - 24.0, SIDEBAR_W - 2 * PAD, 20.0)
    side_list = (PAD / 2.0, PAD, SIDEBAR_W - PAD, top - 24.0 - PAD - 8.0)
    mx = SIDEBAR_W + PAD
    mw = w - SIDEBAR_W - 2 * PAD
    input_row = (mx, PAD, mw, INPUT_H)
    mic = (mx + mw - INPUT_H, PAD, INPUT_H, INPUT_H)
    field = (mx, PAD, mw - INPUT_H - 8.0, INPUT_H)
    chips = (mx, PAD + INPUT_H + 10.0, mw, CHIP_ROW_H)
    y = chips[1] + CHIP_ROW_H + 12.0
    result = None
    if show_result:
        result = (mx, y, mw, RESULT_H)
        y += RESULT_H + 12.0
    header = (mx, top - 26.0, mw, 24.0)
    conversation = (mx, y, mw, max(60.0, header[1] - 8.0 - y))
    return {
        "size": (w, h), "sidebar": side, "sidebar_title": side_title,
        "history": side_list, "header": header, "conversation": conversation,
        "result": result, "chips": chips, "input": input_row,
        "field": field, "mic": mic,
    }


def dock_rect(layout, dock=DOCK_ORB):
    """The docked orb's frame (x, y, w, h) in window coordinates, for a full_layout result.

    Its centre is dock/2 left of the divider and dock/2 + 12 pt below the titlebar.
    """
    _w, h = layout["size"]
    half = dock / 2.0
    return (SIDEBAR_W - half - half, h - TITLEBAR_H - half - 12.0 - half, dock, dock)


def history_items(rows):
    """Newest-first list of the things you asked, for the sidebar."""
    return [text for who, text in reversed(list(rows or [])) if who == "you"]


def last_result(rows):
    """The latest Jev reply, shown in the result card ('' if none yet)."""
    for who, text in reversed(list(rows or [])):
        if who == "jev":
            return text
    return ""


def conversation_lines(rows):
    """(speaker, text) pairs with display names, oldest first."""
    return [("You" if who == "you" else "Jev", text) for who, text in (rows or [])]


def chip_frames(chip_ids, widths, row_rect, gap=8.0):
    """Lay chips in one row; ones that would not fit are dropped, never clipped."""
    x0, y0, rw, rh = row_rect
    out, x = [], x0
    for cid in chip_ids:
        cw = float(widths.get(cid, 100.0))
        if x + cw > x0 + rw + 0.01:
            break
        out.append({"id": cid, "frame": (x, y0, cw, rh)})
        x += cw + gap
    return out
