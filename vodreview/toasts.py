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
3. **Template matching** (ToastReader): the start of the title row (GUI x
   25-68: about 8 characters; the streamer's RTA timer overlay covers the
   rest of slot 0) is compared with saved title crops in
   calibration/toasts/ by normalised cross-correlation with +-2 px slack.
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


def _neutral_fill(bgr):
    """Strict per-pixel test: toast fill grey and (almost) no colour."""
    lo, hi = config.TOAST_FILL_RANGE
    px = bgr.astype(np.int16)
    mn, mx = px.min(axis=2), px.max(axis=2)
    return (mn >= lo) & (mx <= hi) & (mx - mn <= config.TOAST_FILL_MAX_CHROMA)


def _frame_grey(bgr):
    """The toast's light-grey frame line (RGB ~83, neutral)."""
    lo, hi = config.TOAST_FRAME_RANGE
    px = bgr.astype(np.int16)
    mn, mx = px.min(axis=2), px.max(axis=2)
    return (mn >= lo) & (mx <= hi) & (mx - mn <= config.TOAST_FRAME_MAX_CHROMA)


def _window_for(box, frame_w, frame_h):
    """Pick the game window (full screen or a resized strip) the toast sits in.

    The toast is right-aligned in its window, so the window whose right edge is
    closest to the toast's right edge wins (among windows containing the box).
    """
    best, best_d = ("full", (0.0, 0.0, 1.0, 1.0)), None
    right = box[0] + box[2]
    windows = {"full": (0.0, 0.0, 1.0, 1.0), **config.RESIZED_LAYOUTS}
    for name, (x0, y0, x1, y1) in windows.items():
        wx0, wy0, wx1, wy1 = x0 * frame_w, y0 * frame_h, x1 * frame_w, y1 * frame_h
        if not (wx0 - 4 <= box[0] and right <= wx1 + 4 and wy0 - 4 <= box[1] <= wy1):
            continue
        d = abs(wx1 - right)
        if best_d is None or d < best_d:
            best, best_d = (name, (wx0, wy0, wx1, wy1)), d
    return best


def find_toasts(frame):
    """All advancement-toast boxes (fully shown or sliding) in a BGR frame."""
    fh, fw = frame.shape[:2]
    rx0, ry0, rx1, ry1 = config.TOAST_SEARCH_REGION
    ox, oy = int(rx0 * fw), int(ry0 * fh)
    roi = frame[oy:int(ry1 * fh), ox:int(rx1 * fw)]
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
        # Cheap pre-check on the half-size mask: some row near the top is almost all fill.
        if (mask[y:y + max(1, h0 // 6), x:x + w].mean(axis=1) < 0.7 * 255).all():
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
        fill_rows = _neutral_fill(inner).mean(axis=1)
        good = np.flatnonzero(fill_rows[:max(2, int(0.15 * h0) + 1)] >= config.TOAST_BAND_MIN_FILL)
        if len(good) == 0:
            continue
        frame_rows = _frame_grey(inner).mean(axis=1)
        below = [r for r in range(int(0.75 * h0), len(frame_rows)) if frame_rows[r] >= config.TOAST_BAND_MIN_FILL]
        if not below:
            continue
        top_row = int(good[0])
        # Exact left/right edges from the clean top fill rows (the blob can be
        # a few px wider where the frame is blurred into the background).
        cols = np.flatnonzero(_neutral_fill(strip[top_row:top_row + max(1, int(0.08 * h0))]).mean(axis=0) >= 0.5)
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
        window, (wx0, wy0, wx1, wy1) = _window_for(box, fw, fh)
        slot = int(round((box[1] - FRAME_PX * k - wy0) / (TOAST_H * k)))
        boxes.append(ToastBox(box[0], box[1], w, h, k, bool(full), window, max(0, slot)))
    boxes.sort(key=lambda b: (b.window, b.slot))
    return boxes


def canonical(frame, box, x_stretch=1.0):
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
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    interp = cv2.INTER_AREA if k >= 1 else cv2.INTER_LINEAR
    return cv2.resize(gray, (TOAST_W, TOAST_H), interpolation=interp)


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
    def __init__(self, templates=None):
        self.templates = load_toast_templates() if templates is None else templates

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
