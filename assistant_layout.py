"""Geometry for the Hey Jev window.

No AppKit imports, so the resize rules can be tested on Linux. Rectangles are
(x, y, width, height) in AppKit points, origin at the bottom left of the parent.
"""
import re

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
# Three columns only once each card is wide enough for a 28pt value such as
# "None yet" or "$0.0000". The 720-wide default stays on two columns.
COLUMN_BREAK = 640
# Semibold system text is wider than the 0.56em used for body copy. 0.72 matches
# the truncation seen at 28pt in a ~120pt card ("None y…", "$0.00…").
VALUE_EM = 0.72
SUB_EM = 0.60
VALUE_PREFERRED = 28
VALUE_FLOOR = 15
SUB_SIZE = 11
# Lines the Home cards actually show. The layout keeps these from ellipsizing.
HOME_CARD_VALUES = ("None yet", "$0.0000", "12 h 59 min")
HOME_CARD_SUBS = (
    "vs typing at 40 words a minute",
    "Say \u201cHey Jev, open Spotify\u201d",
)


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


def text_width(text, size, em):
    """Estimated rendered width. Spaces count, so a tight card still has slack."""
    return len(text) * float(size) * float(em)


def _fit_font(text, width, preferred, floor, em, max_height):
    """Largest size in [floor, preferred] whose one line fits `width` and `max_height`.

    A few points of inset and leading keep the glyphs off the card edge. The
    point size alone is shorter than the line the field actually draws.
    """
    usable = max(8.0, float(width) - 4.0)
    size = int(preferred)
    while size > int(floor):
        if text_width(text, size, em) <= usable and size + 3 <= max_height:
            return size
        size -= 1
    return int(floor)


def _subtitle_block(text, width):
    """(font size, height) for one or two wrapped lines. Never more than two.

    A line that only just fits is wrapped, so a slightly wider real font still
    has a second line instead of an ellipsis.
    """
    size = SUB_SIZE
    slack = 8.0
    while size > 9 and text_width(text, size, SUB_EM) > 2 * (width - slack):
        size -= 1
    lines = 2 if text_width(text, size, SUB_EM) > width - slack else 1
    return size, lines * (size + 3.0)


def _card_labels(card):
    """Value, title, and caption stacked inside the card without covering each other.

    The value stays one line, at a smaller size when the card is narrow or short.
    The caption is two lines when it does not fit on one, so it wraps instead of
    ending in an ellipsis.
    """
    x, y, w, h = card
    pad_x, pad_y, gap = 12.0, 4.0, 2.0
    inner_w = max(20.0, w - 2 * pad_x)
    title_h = 15.0
    longest_sub = max(HOME_CARD_SUBS, key=len)
    sub_size, sub_h = _subtitle_block(longest_sub, inner_w)
    value_h = h - (pad_y * 2 + title_h + sub_h + gap * 2)
    if value_h < VALUE_FLOOR:
        sub_h = float(sub_size + 3)
        value_h = h - (pad_y * 2 + title_h + sub_h + gap * 2)
    value_h = max(1.0, value_h)
    longest_value = max(HOME_CARD_VALUES, key=len)
    value_size = _fit_font(longest_value, inner_w, VALUE_PREFERRED, VALUE_FLOOR, VALUE_EM, value_h)
    sub_y = y + pad_y
    title_y = sub_y + sub_h + gap
    value_y = title_y + title_h + gap
    return (
        (x + pad_x, value_y, inner_w, value_h),
        (x + pad_x, title_y, inner_w, title_h),
        (x + pad_x, sub_y, inner_w, sub_h),
        value_size,
        sub_size,
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
    # The type field and its history sit in the band the title used to use,
    # so the six stat cards stay on the first screen.
    field_top, field_h = 14.0, 28.0
    send_w, folder_w = 64.0, 96.0
    field_w = max(80.0, inner - send_w - folder_w - 2 * GAP)
    history_top = field_top + field_h + 6.0
    history_h = 42.0
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
        value, title, sub, value_font, sub_font = _card_labels(box)
        cards_out.append({
            "box": box,
            "value": value,
            "title": title,
            "sub": sub,
            "value_font": value_font,
            "sub_font": sub_font,
        })
    return {
        "document": (0.0, 0.0, page_w, doc_h),
        "title": (float(MARGIN), _from_top(doc_h, 0.0, 0.0), 1.0, 0.0),
        "subtitle": (float(MARGIN), _from_top(doc_h, 0.0, 0.0), 1.0, 0.0),
        "composer": (float(MARGIN), _from_top(doc_h, field_top, field_h), field_w, field_h),
        "composer_send": (
            float(MARGIN) + field_w + GAP, _from_top(doc_h, field_top, field_h), send_w, field_h,
        ),
        "composer_folder": (
            float(MARGIN) + field_w + GAP + send_w + GAP,
            _from_top(doc_h, field_top, field_h), folder_w, field_h,
        ),
        "history": (float(MARGIN), _from_top(doc_h, history_top, history_h), text_w, history_h),
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
    top = 120.0
    stacked = page_w < 560.0
    text_w = page_w - 2 * MARGIN
    model_top = top + (112.0 if stacked else 90.0)
    mini_top = model_top + (112.0 if stacked else 90.0)
    # The mini-bar switch ends 72pt below mini_top. The update block follows it.
    update_top = mini_top + 88.0
    content_h = update_top + 72.0 + 24.0
    doc_h = max(page_h, content_h)
    header = _header(doc_h, page_w, search=False)
    if stacked:
        name = (float(MARGIN), _from_top(doc_h, top, 20.0), text_w, 20.0)
        hint = (float(MARGIN), _from_top(doc_h, top + 22.0, 18.0), text_w, 18.0)
        popup = (float(MARGIN), _from_top(doc_h, top + 46.0, 26.0), text_w, 26.0)
        message = (float(MARGIN), _from_top(doc_h, top + 80.0, 20.0), text_w, 20.0)
        model_name = (float(MARGIN), _from_top(doc_h, model_top, 20.0), text_w, 20.0)
        model_hint = (float(MARGIN), _from_top(doc_h, model_top + 22.0, 18.0), text_w, 18.0)
        model_field = (float(MARGIN), _from_top(doc_h, model_top + 46.0, 26.0), text_w, 26.0)
    else:
        label_w = min(220.0, text_w * 0.46)
        popup_w = text_w - label_w - GAP
        name = (float(MARGIN), _from_top(doc_h, top, 20.0), label_w, 20.0)
        hint = (float(MARGIN), _from_top(doc_h, top + 22.0, 18.0), label_w, 18.0)
        popup = (MARGIN + label_w + GAP, _from_top(doc_h, top + 8.0, 26.0), popup_w, 26.0)
        message = (float(MARGIN), _from_top(doc_h, top + 56.0, 20.0), text_w, 20.0)
        model_name = (float(MARGIN), _from_top(doc_h, model_top, 20.0), label_w, 20.0)
        model_hint = (float(MARGIN), _from_top(doc_h, model_top + 22.0, 18.0), label_w, 18.0)
        model_field = (MARGIN + label_w + GAP, _from_top(doc_h, model_top + 8.0, 26.0), popup_w, 26.0)
    mini_name = (float(MARGIN), _from_top(doc_h, mini_top, 20.0), text_w, 20.0)
    mini_hint = (float(MARGIN), _from_top(doc_h, mini_top + 22.0, 18.0), text_w, 18.0)
    mini_toggle = (float(MARGIN), _from_top(doc_h, mini_top + 46.0, 26.0), text_w, 26.0)
    update_name = (float(MARGIN), _from_top(doc_h, update_top, 20.0), text_w, 20.0)
    update_hint = (float(MARGIN), _from_top(doc_h, update_top + 22.0, 18.0), text_w, 18.0)
    update_button = (float(MARGIN), _from_top(doc_h, update_top + 46.0, 26.0), min(220.0, text_w), 26.0)
    return {
        "document": (0.0, 0.0, page_w, doc_h),
        "title": header["title"],
        "subtitle": header["subtitle"],
        "name": name,
        "hint": hint,
        "popup": popup,
        "message": message,
        "model_name": model_name,
        "model_hint": model_hint,
        "model_field": model_field,
        "mini_name": mini_name,
        "mini_hint": mini_hint,
        "mini_toggle": mini_toggle,
        "update_name": update_name,
        "update_hint": update_hint,
        "update_button": update_button,
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


def parse_window_frame(text):
    """An autosaved NSWindow frame as (x, y, w, h), or None.

    AppKit stores "{{x, y}, {w, h}}". A plain "x y w h" string is accepted too.
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    nums = re.findall(r"-?\d+(?:\.\d+)?", raw)
    if len(nums) != 4:
        return None
    return tuple(float(n) for n in nums)


def _intersection_area(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1)


def frame_is_usable(frame, screens):
    """False when the frame should be discarded and the window centered.

    `frame` is (x, y, w, h) or None. `screens` are visible frames, origin
    bottom-left. Missing, tiny, and mostly-offscreen frames are unusable.
    So is the uncentered default: the window still sitting on a screen's
    bottom-left corner at the default 720 by 460 size. That is the frame
    AppKit writes when the window was created at (0, 0) and never centered.
    """
    if not frame or not screens:
        return False
    x, y, w, h = frame
    if w < MIN_W or h < MIN_H:
        return False
    area = w * h
    if not any(_intersection_area(frame, screen) >= 0.5 * area for screen in screens):
        return False
    for sx, sy, _sw, _sh in screens:
        if abs(x - sx) <= 2.0 and abs(y - sy) <= 2.0 and abs(w - DEFAULT_W) <= 2.0 and abs(h - DEFAULT_H) <= 2.0:
            return False
    return True


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
