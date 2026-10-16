"""Language-free GUI structure: what Minecraft draws, measured in GUI pixels.

Minecraft draws its whole interface on a grid of "GUI pixels"; the GUI scale
(times the recording's resize) decides how many screen pixels one GUI pixel
is: `k` (4.5 on the tuning VOD: 1440p game, GUI scale 6, recorded at 1080p).
Vanilla 1.16 geometry, in GUI pixels:

* hotbar: 182 x 22, centred at the bottom of the game view; slot borders every
  20 px (a black outline, then a light and a mid-grey column);
* container screens (inventory, crafting table, chests, furnace ...): a flat
  light-grey (#C6C6C6) panel, 176 px wide (166-222 tall), centred;
* buttons: 200 x 20 (98/150/204 wide variants), flat mid-grey (~#6F6F6F) fill
  with a black outline, white label text;
* F3 debug text: left-aligned lines at x = 2, y = 2 + 9 i, white (#E0E0E0).

So instead of English text templates the screen classifier looks for these
shapes at the measured scale (layout.k, see layout.py). Everything here works
on numbers only - no words - so it is the same in every game language.
"""

import cv2
import numpy as np

from . import config

# Hotbar column profile (grey level) of the vanilla texture around each slot
# border, in GUI x from the hotbar's left edge (measured on the tuning VOD's
# temporal-median hotbar, middle rows y 5-17, and identical on the 3 other
# players' videos): black outline, light + mid column, dark slot rim.
_HOTBAR_COLS = [(0, 2), (1, 149), (2, 95), (3, 16)]
for _i in range(1, 9):
    _b = 20 * _i
    _HOTBAR_COLS += [(_b - 1, 124), (_b, 93), (_b + 1, 122), (_b + 2, 92), (_b + 3, 17)]
_HOTBAR_COLS += [(179, 124), (180, 93), (181, 70), (182, 2)]
HOTBAR_X = np.array([x + 0.5 for x, _ in _HOTBAR_COLS])
HOTBAR_V = np.array([v for _, v in _HOTBAR_COLS], dtype=np.float64)
HOTBAR_W, HOTBAR_H = 182, 22


def _corr(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def hotbar_profile(gray, k, game):
    """Mean grey per column over the hotbar's middle rows for scale k (None if off-frame)."""
    x0, y0, x1, y1 = game
    top = y1 - HOTBAR_H * k
    ya, yb = int(round(top + 5 * k)), int(round(top + 17 * k)) + 1
    if ya < 0 or yb > gray.shape[0] or yb <= ya:
        return None
    return gray[ya:yb, int(x0):int(x1)].astype(np.float32).mean(axis=0)


def hotbar_score(gray, k, game, col=None):
    """Correlation of the hotbar-border pattern at scale k (-1..1; ~0.95 on a clean hotbar)."""
    x0, _, x1, _ = game
    col = hotbar_profile(gray, k, game) if col is None else col
    if col is None:
        return -1.0
    cx = (x1 - x0) / 2
    best = -1.0
    xs = np.arange(len(col))
    for dx in (-1, 0, 1):
        pos = cx + dx + (HOTBAR_X - HOTBAR_W / 2) * k
        if pos[0] < 0 or pos[-1] >= len(col) - 1:
            continue
        best = max(best, _corr(np.interp(pos, xs, col).astype(np.float64), HOTBAR_V))
    return best


def measure_gui_scale(median_gray, game):
    """GUI scale k from a temporal-median frame: the k whose hotbar pattern fits best.

    Returns (k, score). Tries k = 1.0 .. 8.0 in 0.01 steps (the hotbar is static,
    so the median of many frames shows it cleanly whatever the world does).
    """
    best = (-1.0, None)
    for k in np.arange(config.GUI_SCALE_RANGE[0], config.GUI_SCALE_RANGE[1], 0.01):
        s = hotbar_score(median_gray, float(k), game)
        if s > best[0]:
            best = (s, float(k))
    score, k = best
    if k is None:
        return None, score
    # Snap to a multiple of 0.25 when within 0.03 (GUI scale x a common
    # resolution ratio: 4.5 = 6 x 1080/1440, 3.75 = 5 x 0.75, 3 = 3 x 1 ...).
    snapped = round(k * 4) / 4
    if abs(snapped - k) <= config.GUI_SCALE_SNAP:
        k = snapped
    return round(k, 3), score


# --- per-frame structure tests (work on a shrunk copy, ~1.5 screen px per GUI px) ----

def shrink_factor(k):
    return min(1.0, config.GUI_STRUCT_PX / k)


def channel_range(small_bgr):
    """(min channel, max channel) per pixel as uint8 arrays (cheap: no int16 copy)."""
    b, g, r = cv2.split(small_bgr)
    return cv2.min(cv2.min(b, g), r), cv2.max(cv2.max(b, g), r)


def _grey_mask(mn, mx, lo, hi, max_chroma):
    """Neutral grey pixels: every channel in [lo, hi] and max - min <= max_chroma (uint8 0/1)."""
    return ((mn >= lo) & (mx <= hi) & (cv2.subtract(mx, mn) <= max_chroma)).astype(np.uint8)


def container_panel(small_bgr, ks, game_small, rng=None):
    """Find a centred #C6C6C6 container panel -> (x0, y0, x1, y1) in small px, or None.

    `ks` = small px per GUI px. The panel is opaque, flat light grey; slots and
    items cut holes in it but its frame keeps it one connected blob, so the
    blob's bounding box is the panel (176 GUI px wide; a recipe book adds a
    second 147-px panel left of it).
    """
    lo, hi = config.GUI_PANEL_GREY
    mn, mx = channel_range(small_bgr) if rng is None else rng
    mask = _grey_mask(mn, mx, lo, hi, config.GUI_PANEL_MAX_CHROMA)
    if cv2.countNonZero(mask) < config.GUI_PANEL_MIN_AREA * ks * ks * 176 * 166:
        return None
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    gx0, gy0, gx1, gy1 = game_small
    cx, cy = (gx0 + gx1) / 2, (gy0 + gy1) / 2
    wmin, wmax = config.GUI_PANEL_W
    hmin, hmax = config.GUI_PANEL_H
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        wg, hg = w / ks, h / ks
        if not (wmin <= wg <= wmax and hmin <= hg <= hmax):
            continue
        if area < config.GUI_PANEL_MIN_FILL * w * h:
            continue
        # Slots: the panel holds dark-grey (#8B8B8B) slot squares.
        bmn, bmx = mn[y:y + h, x:x + w], mx[y:y + h, x:x + w]
        slo, shi = config.GUI_SLOT_GREY
        slots = _grey_mask(bmn, bmx, slo, shi, config.GUI_PANEL_MAX_CHROMA).mean()
        if slots < config.GUI_PANEL_MIN_SLOTS:
            continue
        bx, by = x + w / 2, y + h / 2
        if abs(bx - cx) > config.GUI_PANEL_MAX_OFFSET[0] * ks or abs(by - cy) > config.GUI_PANEL_MAX_OFFSET[1] * ks:
            continue
        return (x, y, x + w, y + h)
    return None


def find_buttons(small_bgr, ks, game_small, rng=None):
    """Vanilla buttons -> list of (x, y, w_gui, h_gui) (small px / GUI px).

    Button fill = flat neutral mid grey. The white label + its shadow cut a
    hole in the middle, but the fill around it (above, below and at both ends)
    stays one ring-shaped connected blob whose bounding box is the button:
    ~20 GUI px tall (minus the bevel rows) and 98-310 wide. (Closing the hole
    would also bridge the 4-px gaps between stacked buttons.)
    """
    lo, hi = config.GUI_BUTTON_GREY
    mn, mx = channel_range(small_bgr) if rng is None else rng
    mask = _grey_mask(mn, mx, lo, hi, config.GUI_BUTTON_MAX_CHROMA)
    # cheap gate: a menu has >= GUI_MIN_BUTTONS buttons' worth of fill (98 x 14 GUI px each, ~half filled)
    if cv2.countNonZero(mask) < config.GUI_MIN_BUTTONS * 0.5 * 98 * 14 * ks * ks:
        return []
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    hmin, hmax = config.GUI_BUTTON_H
    wmin, wmax = config.GUI_BUTTON_W
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        wg, hg = w / ks, h / ks
        if hmin <= hg <= hmax and wmin <= wg <= wmax and area >= config.GUI_BUTTON_MIN_FILL * w * h:
            out.append((x, y, wg, hg))
    return out


def classify_buttons(buttons, ks, game_small):
    """'pause' (a centred column of 200-px buttons), 'settings' (pairs of 150-px buttons) or None."""
    if len(buttons) < config.GUI_MIN_BUTTONS:
        return None
    gx0, _, gx1, _ = game_small
    cx = (gx0 + gx1) / 2
    near = [b for b in buttons if abs(b[0] + b[2] * ks / 2 - cx) <= 170 * ks]
    if len(near) < config.GUI_MIN_BUTTONS:
        return None
    lo150, hi150 = config.GUI_SETTINGS_BUTTON_W
    if sum(1 for b in near if lo150 <= b[2] <= hi150) >= config.GUI_SETTINGS_MIN_BUTTONS:
        return "settings"
    lo200, hi200 = config.GUI_PAUSE_BUTTON_W
    wide = [b for b in near if lo200 <= b[2] <= hi200 and abs(b[0] + b[2] * ks / 2 - cx) <= 12 * ks]
    if wide:
        return "pause"
    return None


def f3_lines(gray, k, game):
    """Number of F3-style text lines in the left column (white text at GUI x 2, y 2 + 9 i).

    A line counts if its 7 text rows hold white glyph pixels near the left
    edge and the row below the line (shadow / gap row) has almost none.
    Chat lines share the 9-px pitch but there are at most 10 of them, the F3
    column has ~20.
    """
    x0, y0, x1, y1 = (int(v) for v in game)
    xa, xb = x0 + int(round(1 * k)), x0 + int(round(config.F3_COLUMN_GUI_W * k))
    col = gray[y0:y1, xa:xb]
    white = (col >= config.F3_TEXT_MIN).astype(np.float32)
    rows = white.mean(axis=1)                      # share of white pixels per screen row
    count = 0
    n_lines = int((y1 - y0) / (9 * k))
    for i in range(n_lines):
        top = (2 + 9 * i) * k
        ya, yb = int(round(top + 0.5 * k)), int(round(top + 6.5 * k))
        gap_a, gap_b = int(round(top + 8.2 * k)), int(round(top + 8.8 * k))
        if gap_b >= len(rows) or yb <= ya:
            break
        text = rows[ya:yb].mean()
        gap = rows[gap_a:max(gap_a + 1, gap_b)].mean()
        # text starts at GUI x 2: the first glyph column must be in the first 8 GUI px
        first = white[ya:yb, :int(round(8 * k))].mean()
        if text >= config.F3_LINE_MIN_TEXT and gap <= config.F3_GAP_MAX * max(text, 1e-6) and first > 0.02:
            count += 1
    return count
