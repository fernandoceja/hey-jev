"""Full Jev window (Eney-style redesign, PR 6b).

The orb opens this window (PR 6a). It is a black-and-REA window with large
rounded corners: a sidebar with "+ New chat" at the top, then the "Get started"
rows, the category sections (Today, Captures, Games, Mac), the other pages
(Dictionary, Apps, Dictation history, Privacy, Settings, Keys) and "Recent" (the
typed history). The main column has a greeting, a large pill input with the mic
at its right, and suggestion pills below it. When there is a conversation, the
greeting gives way to it.

Every action calls back into the AppDelegate: sidebar rows and chips go through
submission() and _dispatch_text_plan, the mic through miniMicDown:/miniMicUp:,
and "+ New chat" only moves the on-screen start point (the typed history and
the popover keep their rows). The orb's dock spot (dock_rect) is kept clear of
every control here. The layout helpers are pure Python so they can be tested
without AppKit.

Palette follows the REA reference (website/public/assets/styles.css), with
ink/muted/line/soft/accent in light and dark variants. The layout is original;
nothing is copied from Eney.
"""

FULL_AUTOSAVE = "JevFullWindow"
FULL_DEFAULT = (760.0, 560.0)
FULL_MIN = (560.0, 420.0)
FULL_MAX = (1600.0, 1200.0)
SIDEBAR_W = 200.0
PAD = 16.0
INPUT_H = 44.0  # PR 6b: a pill, radius INPUT_H / 2
INPUT_MAX_W = 640.0
MIC_D = 36.0  # the mic sits inside the pill at its right end
CHIP_ROW_H = 32.0
TITLEBAR_H = 28.0
CORNER = 16.0
DOCK_ORB = 36.0  # PR 6a: the orb's size when it is docked on the sidebar/chat divider
PLACEHOLDER = "Ask Jev anything…"
GREETING_H = 30.0
GREETING_TOP = 150.0  # the greeting's top edge, measured down from the window's top
CONVERSATION_TOP = 96.0  # the conversation's top edge, measured down from the window's top
HOME_W = 112.0
SIDE_PAD = 26.0  # 18 pt is the docked orb's half-width on the left edge, so the sidebar starts clear of it
NEW_CHAT_H = 32.0
SIDE_RIGHT = SIDEBAR_W - 12.0  # 188: the sidebar's right padding
HEAD_H = 22.0
ROW_H = 28.0
ROW_GAP = 2.0
SECTION_GAP = 12.0
RECENT_MAX = 8
LABEL_MAX = 26

# What the sidebar sends. Every phrase is an existing command, run through submission().
GET_STARTED = (
    ("voice", "Try a voice command", "what time is it"),
    ("capture", "Capture your screen", "take a screenshot"),
    ("plan", "Plan my day", "brief me"),
)
CATEGORIES = (
    ("Today", (("weather", "Weather", "what's the weather"), ("eta_home", "ETA home", "eta home"))),
    ("Captures", (("shots", "Open my screenshots", "open my screenshots"),)),
    ("Games", (("games", "List games", "list games"),)),
    ("Mac", (("mac", "CleanMyMac scan", "cleanmymac scan"),)),
)
# The other main-window pages, by their AssistantUI TABS key (Home is the header button).
PAGES = (
    ("dict", "Dictionary"),
    ("apps", "Apps"),
    ("hist", "Dictation history"),
    ("priv", "Privacy"),
    ("settings", "Settings"),
    ("keys", "Keys"),
)

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


def full_layout(width, height, has_conversation=False):
    """Frames (x, y, w, h), bottom-left origin, for the full window content.

    With no conversation, the greeting sits high, the input is under it, and the chips are under the input.
    With a conversation, the conversation fills the middle and the input and chips sit at the bottom.
    """
    w, h = clamp_full_size(width, height)
    mx = SIDEBAR_W + PAD
    mw = w - mx - PAD
    pill_w = min(mw, INPUT_MAX_W)
    ix = mx + (mw - pill_w) / 2.0
    greeting_y = h - GREETING_TOP - GREETING_H
    if has_conversation:
        chip_y = PAD + 8.0
        input_y = chip_y + CHIP_ROW_H + 12.0
        conv_bottom = input_y + INPUT_H + 16.0
        conversation = (mx, conv_bottom, mw, max(60.0, (h - CONVERSATION_TOP) - conv_bottom))
        greeting = None
    else:
        input_y = greeting_y - 18.0 - INPUT_H
        chip_y = input_y - 14.0 - CHIP_ROW_H
        conversation = None
        greeting = (mx, greeting_y, mw, GREETING_H)
    list_top = h - TITLEBAR_H - 12.0 - NEW_CHAT_H - 8.0  # the sidebar list starts under "+ New chat"
    return {
        "size": (w, h),
        "sidebar": (0.0, 0.0, SIDEBAR_W, h),
        "new_chat": (SIDE_PAD, h - TITLEBAR_H - 12.0 - NEW_CHAT_H, SIDE_RIGHT - SIDE_PAD, NEW_CHAT_H),
        "sidebar_list": (0.0, PAD, SIDEBAR_W, list_top - PAD),
        "header": (w - PAD - HOME_W, h - TITLEBAR_H - 8.0 - 28.0, HOME_W, 28.0),
        "greeting": greeting,
        "conversation": conversation,
        "input": (ix, input_y, pill_w, INPUT_H),
        "field": (ix + 18.0, input_y, pill_w - 18.0 - MIC_D - 10.0, INPUT_H),
        "mic": (ix + pill_w - MIC_D - 4.0, input_y + (INPUT_H - MIC_D) / 2.0, MIC_D, MIC_D),
        "chips": (ix, chip_y, pill_w, CHIP_ROW_H),
    }


def dock_rect(layout, dock=DOCK_ORB):
    """The docked orb's frame (x, y, w, h) in window coordinates, for a full_layout result.

    Centred on the window's left edge at mid height: half of it sits over the sidebar, half outside the window.
    """
    _w, h = layout["size"]
    half = dock / 2.0
    return (-half, h / 2.0 - half, dock, dock)


def short_label(text, limit=LABEL_MAX):
    cleaned = " ".join(str(text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def sidebar_items(recent=()):
    """The scrolling sidebar list, top to bottom, with frames in list space (y grows down).

    Returns (items, height). Each item has a kind (head, row or empty), a label and, for rows,
    an action: ("send", phrase) runs a command, ("page", key) opens a main-window page,
    ("fill", text) puts a past request back in the field without sending it.
    """
    items = []
    y = 0.0
    width = SIDE_RIGHT - SIDE_PAD

    def head(title):
        nonlocal y
        items.append({"kind": "head", "label": title, "frame": (SIDE_PAD, y, width, HEAD_H)})
        y += HEAD_H

    def row(label, action):
        nonlocal y
        items.append({"kind": "row", "label": short_label(label), "action": action,
                      "frame": (SIDE_PAD, y, width, ROW_H)})
        y += ROW_H + ROW_GAP

    head("Get started")
    for _cid, label, phrase in GET_STARTED:
        row(label, ("send", phrase))
    y += SECTION_GAP
    for title, rows in CATEGORIES:
        head(title)
        for _cid, label, phrase in rows:
            row(label, ("send", phrase))
        y += SECTION_GAP
    head("Pages")
    for key, label in PAGES:
        row(label, ("page", key))
    y += SECTION_GAP
    head("Recent")
    past = [str(t) for t in list(recent or [])][:RECENT_MAX]
    if not past:
        items.append({"kind": "empty", "label": "Nothing yet.", "frame": (SIDE_PAD, y, width, ROW_H)})
        y += ROW_H
    for text in past:
        row(text, ("fill", text))
    return items, y


def chat_rows(rows, added_total, cut_total):
    """The rows on screen: everything typed since "+ New chat".

    TypedHistory counts every row it adds (added_total) and trims the oldest, so the fresh rows
    are the newest (added_total - cut_total) of whatever is still in the list.
    """
    fresh = int(added_total) - int(cut_total)
    if fresh <= 0:
        return []
    return list(rows or [])[-fresh:]


def history_items(rows):
    """Newest-first list of the things you asked, for the Recent section."""
    return [text for who, text in reversed(list(rows or [])) if who == "you"]


def last_result(rows):
    """The latest Jev reply ('' if none yet)."""
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
