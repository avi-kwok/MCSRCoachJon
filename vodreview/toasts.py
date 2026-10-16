"""Advancement toasts: find the pop-up box, then recognise its title.

In 1.16.1 an advancement toast is a 160x32 GUI-pixel box in the top-right
corner of the game window: an opaque, perfectly flat dark-grey fill
(RGB ~31,31,31) inside a light-grey frame, an icon, "Advancement Made!" in
yellow and the advancement title in white. Toasts stack downwards (slot 0, 1,
2 ... = 32 GUI px apart), slide in from the right over ~0.6 s, stay ~5 s and
slide out again.

CV ideas used here:

1. **Colour keying + connected components** (find_toasts): mark the pixels that
   have exactly the toast fill colour, close the holes left by the text
   (morphological closing), and keep connected blobs that are wide rectangles
   whose top and bottom rows are almost pure fill. The blob height is 26 GUI px
   (32 minus the frame), which gives the GUI scale k (screen px per GUI px) -
   so the same code finds the toast at full screen (k = 4.5 on the test VOD)
   and inside MCSR's resized strips (k ~ 0.74). A blob narrower than
   154 GUI px is a toast still sliding in/out ("partial").
2. **Normalisation**: a fully shown toast is cut out and resized to its
   160x32 GUI-pixel grid, so text size no longer depends on GUI scale or
   recording resolution.
3. **Icon matching** (ToastReader.read_icon): the advancement's item icon is
   drawn at GUI (8, 8), 16x16, on the flat fill. It is cut from the
   canonical toast in colour and compared with icon templates
   (calibration/toasts/icons/<item>.png) by normalised cross-correlation
   with +-1 GUI px slack. Icons are the same in every game language, so this
   is the primary recogniser. One icon can belong to two advancements
   (obsidian: We Need to Go Deeper and Ice Bucket Challenge) - splits.py
   tells those apart (title read, or the overworld -> nether transition).
4. **Title template matching** (ToastReader.read): the start of the title row
   (GUI x 25-68: about 8 characters; the streamer's RTA timer overlay covers
   the rest of slot 0) is compared with saved title crops in
   calibration/toasts/ by normalised cross-correlation with +-2 px slack.
   English only - kept as a secondary check and tie-break.

Where to search comes from the layout (layout.json): the full view's toast
stack (top right, 160 GUI px wide) and the top-right corner of every resized
strip seen; the window a toast belongs to (full view or which strip) is the
one whose right edge it hugs.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import config

TOAST_W, TOAST_H = 160, 32          # toast size in GUI pixels
FRAME_PX = 3                        # frame (border) thickness around the flat fill, GUI px
FILL_W, FILL_H = TOAST_W - 2 * FRAME_PX, TOAST_H - 2 * FRAME_PX   # 154 x 26
# Title row inside the 160x32 grid (text drawn at GUI x 30, y 18; 8 rows incl. descenders).
TITLE_PATCH = (25, 17, 69, 27)      # x0, y0, x1, y1 compared with the templates (RTA overlay starts at x ~71 in slot 0)
TITLE_SLACK = 2                     # search the patch +-2 GUI px (alignment errors)
ICON_XY, ICON_SIZE = (8, 8), 16     # item icon position / size inside the toast, GUI px
ICON_SLACK = 1                      # search the icon +-1 GUI px


@dataclass
class ToastBox:
    x: int          # flat-fill rectangle in full-frame pixels
    y: int
    w: int
    h: int
    k: float        # screen pixels per GUI pixel
    full: bool      # fully slid in (False = sliding in/out)
    window: str     # "full" or a resized layout name
    slot: int       # 0 = top toast, 1 = the one below, ...


def _fill_mask(bgr):
    lo, hi = config.TOAST_FILL_RANGE
    return cv2.inRange(bgr, (lo, lo, lo), (hi, hi, hi))


def _neutral_fill(bgr, max_chroma=None):
    """Strict per-pixel test: toast fill grey and (almost) no colour."""
    lo, hi = config.TOAST_FILL_RANGE
    px = bgr.astype(np.int16)
    mn, mx = px.min(axis=2), px.max(axis=2)
    max_chroma = config.TOAST_FILL_MAX_CHROMA if max_chroma is None else max_chroma
    return (mn >= lo) & (mx <= hi) & (mx - mn <= max_chroma)


def _frame_grey(bgr):
    """The toast's light-grey frame line (RGB ~83, neutral)."""
    lo, hi = config.TOAST_FRAME_RANGE
    px = bgr.astype(np.int16)
    mn, mx = px.min(axis=2), px.max(axis=2)
    return (mn >= lo) & (mx <= hi) & (mx - mn <= config.TOAST_FRAME_MAX_CHROMA)


def _window_for(box, windows):
    """Pick the game window (full view or a resized strip) the toast sits in.

    The toast is right-aligned in its window, so the window whose right edge is
    closest to the toast's right edge wins (among windows containing the box).
    `windows` = {name: (x0, y0, x1, y1) px}.
    """
    best, best_d = ("full", windows["full"]), None
    right = box[0] + box[2]
    for name, (wx0, wy0, wx1, wy1) in windows.items():
        if not (wx0 - 4 <= box[0] and right <= wx1 + 4 and wy0 - 4 <= box[1] <= wy1):
            continue
        d = abs(wx1 - right)
        if best_d is None or d < best_d:
            best, best_d = (name, (wx0, wy0, wx1, wy1)), d
    return best


def find_toasts(frame, lay, strip=None):
    """All advancement-toast boxes (fully shown or sliding) in a BGR frame.

    `lay` = the video's Layout (search region + windows); `strip` = the
    resized strip shown in this frame (px), if any, also searched.
    """
    windows = lay.windows()
    if strip is not None:
        windows = dict(windows, current=tuple(strip))
    boxes = []
    for region in lay.toast_search_regions(strip):
        for b in _find_in_region(frame, region, windows):
            if not any(abs(b.x - o.x) <= 4 and abs(b.y - o.y) <= 4 for o in boxes):
                boxes.append(b)
    boxes.sort(key=lambda b: (b.window, b.slot))
    return boxes


def _find_in_region(frame, region, windows):
    rx0, ry0, rx1, ry1 = region
    ox, oy = int(rx0), int(ry0)
    roi = frame[oy:int(ry1), ox:int(rx1)]
    if roi.size == 0:
        return []
    # Blobs are found on every 2nd pixel (4x cheaper); the edges are then
    # measured exactly at full resolution.
    mask = _fill_mask(roi[::2, ::2])
    if cv2.countNonZero(mask) * 4 < config.TOAST_MIN_FILL_PIXELS:
        return []
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(closed)
    boxes = []
    rh, rw = roi.shape[:2]
    for i in range(1, n):
        x, y, w, h0, _ = (int(v) for v in stats[i])
        if 2 * h0 < config.TOAST_MIN_HEIGHT_PX or w < 1.5 * h0:
            continue
        # Small toasts (inside a resized strip, ~1 screen px per GUI px or less): video blur and
        # 4:2:0 chroma subsampling bleed the frame line, the icon and the wallpaper next to the
        # strip a few px into the fill, so the row tests below look at the middle of the box only
        # and accept the frame line's chroma tolerance (the same rule at every scale, in GUI px).
        small = 2 * h0 < config.TOAST_SMALL_FILL_PX
        # Cheap pre-check on the half-size mask: some row near the top is almost all fill.
        mx0 = max(0, int(round(config.TOAST_SMALL_EDGE_SHARE * w))) if small else 0
        if (mask[y:y + max(1, h0 // 6), x + mx0:x + w - mx0].mean(axis=1) < 0.7 * 255).all():
            continue
        x, y = max(0, 2 * x - 2), max(0, 2 * y - 2)
        w, h0 = min(rw - x, 2 * w + 4), min(rh - y, 2 * h0 + 4)
        # The top fill rows (above "Advancement Made!") must be clean, flat,
        # colourless fill across the whole width; the box ends where the
        # light-grey frame line starts below it. (Rows just below the title are
        # blurred by text descenders at small scales, so the frame line is a
        # more reliable bottom edge than the fill itself.)
        strip = roi[y:min(roi.shape[0], y + h0 + 4), x:x + w]
        inner = strip[:, 3:-3]                     # row tests without the padding / blurred ends
        chroma = None
        if small:
            e = int(round(config.TOAST_SMALL_EDGE_SHARE * inner.shape[1]))
            inner = inner[:, e:inner.shape[1] - e] if inner.shape[1] > 2 * e + 4 else inner
            chroma = config.TOAST_FRAME_MAX_CHROMA
        fill_rows = _neutral_fill(inner, chroma).mean(axis=1)
        good = np.flatnonzero(fill_rows[:max(2, int(0.15 * h0) + 1)] >= config.TOAST_BAND_MIN_FILL)
        if len(good) == 0:
            continue
        frame_rows = _frame_grey(inner).mean(axis=1)
        below = [r for r in range(int(0.75 * h0), len(frame_rows)) if frame_rows[r] >= config.TOAST_BAND_MIN_FILL]
        if not below:
            # A timer/clock overlay drawn over the toast's lower right (common: MCSR's RTA
            # lines, speedrun timers) hides the frame line there; the icon side is clear.
            left = _frame_grey(inner[:, :max(4, int(config.TOAST_FRAME_LEFT_SHARE * inner.shape[1]))]).mean(axis=1)
            below = [r for r in range(int(0.75 * h0), len(left)) if left[r] >= config.TOAST_BAND_MIN_FILL]
        if not below:
            continue
        top_row = int(good[0])
        # Exact left/right edges from the clean top fill rows (the blob can be
        # a few px wider where the frame is blurred into the background).
        cols = np.flatnonzero(_neutral_fill(strip[top_row:top_row + max(1, int(0.08 * h0))], chroma).mean(axis=0) >= 0.5)
        if len(cols) < 2:
            continue
        x, w = x + int(cols[0]), int(cols[-1] - cols[0] + 1)
        y, h = y + top_row, int(below[0] - top_row)
        if h < config.TOAST_MIN_HEIGHT_PX or w > FILL_W / FILL_H * h * 1.08:
            continue
        k = h / FILL_H
        # Fully slid in = full width, within 1.5 GUI px (or 3 screen px for tiny, blurred toasts).
        full = w >= FILL_W * k - max(config.TOAST_FULL_SLACK_GUI_PX * k, 3)
        box = (x + ox, y + oy, w, h)
        window, (wx0, wy0, wx1, wy1) = _window_for(box, windows)
        slot = int(round((box[1] - FRAME_PX * k - wy0) / (TOAST_H * k)))
        boxes.append(ToastBox(box[0], box[1], w, h, k, bool(full), window, max(0, slot)))
    return boxes


def canonical(frame, box, x_stretch=1.0, colour=False):
    """Cut a fully shown toast out and resize it to its 160x32 GUI-pixel grid (grayscale).

    Placed by the centre of the fill box. Scale = the larger of width/154 and
    height/26: the fill's edges blur by a px or two, which only ever makes it
    look smaller. `x_stretch` tries a slightly different horizontal scale
    (resized strips are not always scaled exactly uniformly).
    """
    ky = max(box.w / FILL_W, box.h / FILL_H)
    kx = ky * x_stretch
    cx, cy = box.x + box.w / 2, box.y + box.h / 2
    x0, x1 = cx - TOAST_W / 2 * kx, cx + TOAST_W / 2 * kx
    y0, y1 = cy - TOAST_H / 2 * ky, cy + TOAST_H / 2 * ky
    k = min(kx, ky)
    fh, fw = frame.shape[:2]
    xa, ya = max(0, int(round(x0))), max(0, int(round(y0)))
    xb, yb = min(fw, int(round(x1))), min(fh, int(round(y1)))
    crop = frame[ya:yb, xa:xb]
    if crop.size == 0:
        return None
    img = crop if colour else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    interp = cv2.INTER_AREA if k >= 1 else cv2.INTER_LINEAR
    return cv2.resize(img, (TOAST_W, TOAST_H), interpolation=interp)


def icon_patch(canon_bgr, slack=0):
    """The 16x16 GUI-px item icon at GUI (8, 8) of a colour canonical toast (+- slack)."""
    x0, y0 = ICON_XY
    return canon_bgr[y0 - slack:y0 + ICON_SIZE + slack, x0 - slack:x0 + ICON_SIZE + slack]


def load_icon_templates(folder=None):
    """calibration/toasts/icons/<item>.png (16x16 BGR) -> {item: float32 image}."""
    folder = Path(folder or config.CALIBRATION_DIR / "toasts" / "icons")
    out = {}
    for path in sorted(folder.glob("*.png")) if folder.is_dir() else []:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is not None and image.shape[:2] == (ICON_SIZE, ICON_SIZE):
            out[path.stem] = image.astype(np.float32)
    return out


def title_patch(canon, slack=0):
    x0, y0, x1, y1 = TITLE_PATCH
    return canon[y0 - slack:y1 + slack, x0 - slack:x1 + slack]


def load_toast_templates(folder=None):
    """calibration/toasts/*.png (and other/*.png) -> {advancement id: grayscale title patch}.

    `<split>.png` files (entered_nether.png ...) are the split advancements and
    map to their advancement id via config.SPLIT_ADVANCEMENTS; files in
    `other/` are named after the advancement (stone_age.png ...).
    """
    folder = Path(folder or config.CALIBRATION_DIR / "toasts")
    templates = {}
    for path in sorted(folder.glob("*.png")) + sorted(folder.glob("other/*.png")):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is not None:
            templates[config.SPLIT_ADVANCEMENTS.get(path.stem, path.stem)] = image
    return templates


class ToastReader:
    def __init__(self, templates=None, icons=None):
        self.templates = load_toast_templates() if templates is None else templates
        self.icons = load_icon_templates() if icons is None else icons

    def read_icon(self, frame, box):
        """Recognise a fully shown toast's item icon -> (item or None, best score, runner-up score)."""
        if not box.full or box.k < config.TOAST_ICON_MIN_K or not self.icons:
            return None, 0.0, 0.0
        canon = canonical(frame, box, 1.0, colour=True)
        if canon is None or canon.shape[:2] != (TOAST_H, TOAST_W):
            return None, 0.0, 0.0
        search = icon_patch(canon, ICON_SLACK).astype(np.float32)
        scores = sorted(((float(cv2.matchTemplate(search, t, cv2.TM_CCOEFF_NORMED).max()), name)
                         for name, t in self.icons.items()), reverse=True)
        best, name = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0.0
        min_score = config.TOAST_ICON_MIN_SCORE if box.k >= 1.5 else config.TOAST_ICON_MIN_SCORE_SMALL
        if best < min_score or best - second < config.TOAST_ICON_MIN_MARGIN:
            return None, best, second
        return name, best, second

    def read(self, frame, box):
        """Recognise a fully shown toast -> (name or None, best score, runner-up score)."""
        if not box.full or box.k < config.TOAST_MIN_READ_K:
            return None, 0.0, 0.0
        best_by_name = {}
        for stretch in config.TOAST_X_STRETCHES:
            canon = canonical(frame, box, stretch)
            if canon is None or canon.shape != (TOAST_H, TOAST_W):
                continue
            search = title_patch(canon, TITLE_SLACK)
            for name, template in self.templates.items():
                if template.shape[0] > search.shape[0] or template.shape[1] > search.shape[1]:
                    continue
                score = float(cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED).max())
                best_by_name[name] = max(best_by_name.get(name, -1.0), score)
        if not best_by_name:
            return None, 0.0, 0.0
        scores = sorted(((v, n) for n, v in best_by_name.items()), reverse=True)
        best, name = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0.0
        min_score = config.TOAST_MIN_SCORE if box.k >= 1.5 else config.TOAST_MIN_SCORE_SMALL
        if best < min_score or best - second < config.TOAST_MIN_MARGIN:
            return None, best, second
        return name, best, second
