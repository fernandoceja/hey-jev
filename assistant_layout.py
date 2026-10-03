"""Geometry for the Hey Jev window.

No AppKit imports, so the resize rules can be tested on Linux. Rectangles are
(x, y, width, height) in AppKit points, origin at the bottom left of the parent.
"""

SIDEBAR = 210
HEADER = 72
# The window used to be a fixed 900 by 600. The default below is 20% narrower
# and about 23% shorter. The minimum still fits the sidebar and the stat cards.
OLD_W, OLD_H = 900, 600
DEFAULT_W, DEFAULT_H = 720, 460
MIN_W, MIN_H = 640, 420
FRAME_AUTOSAVE_NAME = "HeyJevMainWindow"

MARGIN = 24
GAP = 12
# Three columns once a card stays about 140pt wide. Narrower than that, two columns.
COLUMN_BREAK = 480


def clamp_size(width, height):
    """Content size the window is allowed to take, never under the minimum."""
    return max(float(width), MIN_W), max(float(height), MIN_H)


def wrapped_height(text, width, size=13, min_h=36):
    """A height that fits wrapping text, so a short window scrolls instead of clipping."""
    line_h = size + 5
    char_w = size * 0.56
    width = max(char_w, float(width))
    per_line = max(1, int(width / char_w))
    lines = 0
    for para in str(text).split("\n"):
        lines += max(1, (len(para) + per_line - 1) // per_line)
    return float(max(min_h, lines * line_h))


def _overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def layout_window(width, height, how_to="", privacy=()):
    """Frames for one content size. `privacy` is a sequence of body strings.

    The window enforces MIN_W and MIN_H. This uses the size it is given so a
    restored frame lays out at that size, with a floor that keeps the page
    from going negative.
    """
    width = max(float(width), float(SIDEBAR + 160))
    height = max(float(height), float(HEADER + 200))
    page_w = width - SIDEBAR
    page_h = height - HEADER
    page_frame = (SIDEBAR, 0.0, page_w, page_h)
    return {
        "size": (width, height),
        "page": (page_w, page_h),
        "chrome": _chrome(width, height, page_frame),
        "sidebar": _sidebar(height),
        "home": _home(page_w, page_h, how_to),
        "dictionary": _table_page(page_w, page_h, (0.34, 0.66), search=True),
        "apps": _table_page(page_w, page_h, (0.28, 0.32, 0.40), search=False),
        "history": _table_page(page_w, page_h, (), search=False),
        "privacy": _privacy(page_w, page_h, privacy),
        "settings": _settings(page_w, page_h),
        "keys": _keys(page_w, page_h, 4),
    }


def _chrome(width, height, page_frame):
    x = SIDEBAR + MARGIN
    mode_w, mode_h = 172.0, 26.0
    mode_x = width - MARGIN - mode_w
    detail_w = max(80.0, mode_x - 12.0 - x)
    return {
        "sidebar": (0.0, 0.0, float(SIDEBAR), height),
        "backdrop": (float(SIDEBAR), 0.0, width - SIDEBAR, height),
        "dot": (x, height - 42.0, 20.0, 24.0),
        "status": (x + 22.0, height - 42.0, max(40.0, detail_w - 22.0), 24.0),
        "detail": (x, height - 64.0, detail_w, 20.0),
        "mode": (mode_x, height - 46.0, mode_w, mode_h),
        "separator": (float(SIDEBAR), height - HEADER, width - SIDEBAR, 1.0),
        "page_frame": page_frame,
    }


def _sidebar(height):
    """Tabs stay under the title and above the timers, packed tighter when the window is short."""
    title_bottom = height - 82.0
    timer_top = 116.0  # top of the highest countdown row
    available = title_bottom - 12.0 - (timer_top + 8.0)
    pitch, box_h = 34.0, 30.0
    if 6.0 * pitch + box_h > available:
        box_h = 26.0
        pitch = (available - box_h) / 6.0
    first_top = title_bottom - 12.0
    tabs = []
    for i in range(7):
        top = first_top - i * pitch
        y = top - box_h
        button_h = min(24.0, box_h - 4.0)
        tabs.append(((10.0, y, SIDEBAR - 20.0, box_h), (20.0, y + 2.0, SIDEBAR - 40.0, button_h)))
    timers = []
    for i in range(3):
        y = 52.0 + (2 - i) * 22.0
        timers.append(((20.0, y, 110.0, 20.0), (130.0, y, SIDEBAR - 150.0, 20.0)))
    return {
        "title": (20.0, title_bottom, SIDEBAR - 40.0, 22.0),
        "tabs": tabs,
        "timers": timers,
        "hint": (20.0, 10.0, SIDEBAR - 36.0, 32.0),
    }


def _from_top(doc_h, top, height):
    return doc_h - top - height


def _card_labels(card):
    """Value, title, and caption stacked inside the card without covering each other."""
    x, y, w, h = card
    pad = 12.0
    inner_w = max(20.0, w - 2 * pad)
    sub_h, title_h = 13.0, 15.0
    sub_y = y + 4.0
    title_y = sub_y + sub_h
    value_y = title_y + title_h + 2.0
    value_h = max(14.0, (y + h - 6.0) - value_y)
    return (
        (x + pad, value_y, inner_w, value_h),
        (x + pad, title_y, inner_w, title_h),
        (x + pad, sub_y, inner_w, sub_h),
    )


def _home(page_w, page_h, how_to):
    cols = 3 if page_w >= COLUMN_BREAK else 2
    rows = (6 + cols - 1) // cols
    cards_top = 96.0
    bottom_pad = 8.0
    available = page_h - cards_top - bottom_pad
    natural = 104.0 * rows + GAP * (rows - 1)
    if natural <= available:
        card_h = 104.0
    else:
        card_h = (available - GAP * (rows - 1)) / float(rows)
    card_h = max(68.0, card_h)
    inner = page_w - 2 * MARGIN
    card_w = (inner - GAP * (cols - 1)) / float(cols)
    cards = []
    for i in range(6):
        col, row = i % cols, i // cols
        x = MARGIN + col * (card_w + GAP)
        top = cards_top + row * (card_h + GAP)
        cards.append((x, top, card_w, card_h))
    cards_bottom = cards_top + rows * card_h + (rows - 1) * GAP
    cursor = cards_bottom + 20.0
    most_top, most_h = cursor, 20.0
    cursor += most_h + 4.0
    actions_top, actions_h = cursor, 40.0
    cursor += actions_h + 14.0
    how_label_top, how_label_h = cursor, 20.0
    cursor += how_label_h + 4.0
    text_w = page_w - 2 * MARGIN
    how_h = wrapped_height(how_to or " ", text_w, min_h=72.0)
    content_h = cursor + how_h + 16.0
    # Grow the how-to block when the window is tall enough to show it.
    doc_h = max(page_h, content_h)
    if doc_h == page_h:
        how_h += page_h - content_h
    cards_out = []
    for x, top, w, h in cards:
        box = (x, _from_top(doc_h, top, h), w, h)
        value, title, sub = _card_labels(box)
        cards_out.append({"box": box, "value": value, "title": title, "sub": sub})
    return {
        "document": (0.0, 0.0, page_w, doc_h),
        "title": (float(MARGIN), _from_top(doc_h, 20.0, 30.0), min(420.0, text_w), 30.0),
        "subtitle": (float(MARGIN), _from_top(doc_h, 52.0, 36.0), text_w, 36.0),
        "cards": cards_out,
        "columns": cols,
        "most_label": (float(MARGIN), _from_top(doc_h, most_top, most_h), text_w, most_h),
        "top_actions": (float(MARGIN), _from_top(doc_h, actions_top, actions_h), text_w, actions_h),
        "how_label": (float(MARGIN), _from_top(doc_h, how_label_top, how_label_h), text_w, how_label_h),
        "how": (float(MARGIN), _from_top(doc_h, cursor, how_h), text_w, how_h),
    }


def _header(doc_h, page_w, search):
    text_w = page_w - 2 * MARGIN
    title_w = text_w
    search_rect = None
    if search:
        search_w = min(200.0, max(120.0, page_w * 0.32))
        search_rect = (page_w - MARGIN - search_w, _from_top(doc_h, 22.0, 26.0), search_w, 26.0)
        title_w = max(80.0, text_w - search_w - GAP)
    return {
        "title": (float(MARGIN), _from_top(doc_h, 20.0, 30.0), title_w, 30.0),
        "subtitle": (float(MARGIN), _from_top(doc_h, 52.0, 36.0), text_w, 36.0),
        "search": search_rect,
    }


def _fields_and_button(page_w, doc_h, top, weights):
    button_w = 116.0
    n = len(weights)
    gaps = GAP * n  # between fields, and between the last field and the button
    available = page_w - 2 * MARGIN - gaps
    if available - button_w < 40.0 * n:
        button_w = max(88.0, available - 40.0 * n)
    usable = max(40.0, available - button_w)
    x = float(MARGIN)
    fields = []
    for weight in weights:
        fw = usable * weight / float(sum(weights))
        fields.append((x, _from_top(doc_h, top, 26.0), fw, 26.0))
        x += fw + GAP
    button = (x, _from_top(doc_h, top - 2.0, 30.0), button_w, 30.0)
    return fields, button


def _table_page(page_w, page_h, weights, search):
    form_top = 96.0
    form_h = 36.0 if weights else 0.0
    table_top = form_top + form_h + (8.0 if weights else 0.0)
    bottom = 56.0
    min_table = 120.0
    content_h = table_top + min_table + bottom
    doc_h = max(page_h, content_h)
    table_h = doc_h - table_top - bottom
    header = _header(doc_h, page_w, search)
    fields, button = ([], None)
    if weights:
        fields, button = _fields_and_button(page_w, doc_h, form_top, weights)
    table = (float(MARGIN), bottom, page_w - 2 * MARGIN, table_h)
    message_w = max(40.0, page_w - 150.0)
    return {
        "document": (0.0, 0.0, page_w, doc_h),
        "title": header["title"],
        "subtitle": header["subtitle"],
        "search": header["search"],
        "fields": fields,
        "button": button,
        "table": table,
        "remove": (20.0, 14.0, 100.0, 30.0),
        "message": (130.0, 20.0, message_w, 20.0),
        "columns": _column_widths(table[2], weights),
    }


def _column_widths(table_w, weights):
    usable = max(80.0, table_w - 16.0)
    if not weights:
        return (130.0, max(80.0, usable - 130.0))
    if len(weights) == 2:
        ratios = (0.28, 0.72)
    else:
        ratios = (0.24, 0.30, 0.46)
    return tuple(usable * part for part in ratios)


def _privacy(page_w, page_h, bodies):
    text_w = page_w - 2 * MARGIN
    cursor = 96.0
    placed = []
    for body in bodies:
        title_h = 20.0
        body_h = wrapped_height(body, text_w, min_h=56.0)
        placed.append((cursor, title_h, body_h))
        cursor += title_h + 4.0 + body_h + 18.0
    content_h = max(cursor + 16.0, 96.0)
    doc_h = max(page_h, content_h)
    header = _header(doc_h, page_w, search=False)
    blocks = []
    for top, title_h, body_h in placed:
        blocks.append((
            (float(MARGIN), _from_top(doc_h, top, title_h), text_w, title_h),
            (float(MARGIN), _from_top(doc_h, top + title_h + 4.0, body_h), text_w, body_h),
        ))
    return {
        "document": (0.0, 0.0, page_w, doc_h),
        "title": header["title"],
        "subtitle": header["subtitle"],
        "blocks": blocks,
    }


def _settings(page_w, page_h):
    doc_h = page_h
    header = _header(doc_h, page_w, search=False)
    top = 120.0
    stacked = page_w < 560.0
    text_w = page_w - 2 * MARGIN
    if stacked:
        name = (float(MARGIN), _from_top(doc_h, top, 20.0), text_w, 20.0)
        hint = (float(MARGIN), _from_top(doc_h, top + 22.0, 18.0), text_w, 18.0)
        popup = (float(MARGIN), _from_top(doc_h, top + 46.0, 26.0), text_w, 26.0)
        message = (float(MARGIN), _from_top(doc_h, top + 80.0, 20.0), text_w, 20.0)
    else:
        label_w = min(220.0, text_w * 0.46)
        popup_w = text_w - label_w - GAP
        name = (float(MARGIN), _from_top(doc_h, top, 20.0), label_w, 20.0)
        hint = (float(MARGIN), _from_top(doc_h, top + 22.0, 18.0), label_w, 18.0)
        popup = (MARGIN + label_w + GAP, _from_top(doc_h, top + 8.0, 26.0), popup_w, 26.0)
        message = (float(MARGIN), _from_top(doc_h, top + 56.0, 20.0), text_w, 20.0)
    return {
        "document": (0.0, 0.0, page_w, doc_h),
        "title": header["title"],
        "subtitle": header["subtitle"],
        "name": name,
        "hint": hint,
        "popup": popup,
        "message": message,
    }


def _keys(page_w, page_h, count):
    text_w = page_w - 2 * MARGIN
    stacked = page_w < 560.0
    cursor = 96.0
    rows_top = []
    for _ in range(count):
        if stacked:
            block = 18.0 + 2.0 + 16.0 + 6.0 + 26.0 + 14.0
        else:
            block = 64.0
        rows_top.append(cursor)
        cursor += block
    button_top = cursor + 8.0
    content_h = button_top + 30.0 + 16.0
    doc_h = max(page_h, content_h)
    header = _header(doc_h, page_w, search=False)
    rows = []
    for top in rows_top:
        if stacked:
            title = (float(MARGIN), _from_top(doc_h, top, 18.0), text_w, 18.0)
            use = (float(MARGIN), _from_top(doc_h, top + 20.0, 16.0), text_w, 16.0)
            field = (float(MARGIN), _from_top(doc_h, top + 42.0, 26.0), text_w, 26.0)
        else:
            label_w = min(240.0, text_w * 0.48)
            field_w = text_w - label_w - GAP
            title = (float(MARGIN), _from_top(doc_h, top, 20.0), label_w, 20.0)
            use = (float(MARGIN), _from_top(doc_h, top + 22.0, 16.0), label_w, 16.0)
            field = (MARGIN + label_w + GAP, _from_top(doc_h, top + 6.0, 26.0), field_w, 26.0)
        rows.append((title, use, field))
    save = (page_w - MARGIN - 116.0, _from_top(doc_h, button_top, 30.0), 116.0, 30.0)
    message = (float(MARGIN), _from_top(doc_h, button_top + 6.0, 20.0), max(40.0, page_w - MARGIN * 2 - 130.0), 20.0)
    return {
        "document": (0.0, 0.0, page_w, doc_h),
        "title": header["title"],
        "subtitle": header["subtitle"],
        "rows": rows,
        "save": save,
        "message": message,
    }


def rects_inside(rect, bounds):
    """True when rect sits fully inside bounds. Both are (x, y, w, h)."""
    x, y, w, h = rect
    bx, by, bw, bh = bounds
    return x >= bx - 0.1 and y >= by - 0.1 and x + w <= bx + bw + 0.1 and y + h <= by + bh + 0.1


def visible_on_first_screen(rect, document_h, page_h):
    """True when the rect is inside the top `page_h` points of the document."""
    _x, y, _w, h = rect
    top_from_top = document_h - (y + h)
    bottom_from_top = document_h - y
    return top_from_top >= -0.1 and bottom_from_top <= page_h + 0.1
