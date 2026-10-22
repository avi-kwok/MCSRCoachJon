"""Run end: when did the run finish, and how?

Two detectors, both looking at fixed spots on the screen:

* DragonWatcher - reads the "Ender Dragon" boss bar. CV idea: *colour
  thresholding*. Instead of matching shapes we classify single pixels by their
  colour (bright magenta = health left, dark magenta = health lost), then
  measure what fraction of the bar is still bright.
* ResultDetector - finds the MCSR match-result screen, then reads the title
  colour in HSV: gold = win, red = loss. HSV splits colour into Hue (which
  colour), Saturation (how colourful) and Value (how bright), so "is this gold
  or red?" becomes a simple range check on hue. Two ways to find the screen:
  the "Match Winner:" label template (MCSR's own text - it stays English in a
  Norwegian-language game), rescaled by the GUI scale; or, language-free, a
  big gold/red title centred above the screen centre plus a "(MM:SS.mmm)"
  read by the glyph reader (digits) on the subtitle row below it.
  A draw (what MCSR shows when a match is forfeited in a private room) is an
  aqua title in the 4x title band plus a centred pure-white subtitle with no
  time - also language-free; it must hold on a few consecutive samples.

Positions come from vanilla GUI geometry at the measured GUI scale k
(layout.py): the boss bar is 182 x 5 GUI px at GUI y 12, centred, its name
above it at y 3; a title is drawn 4x at y -40..-12 from the screen centre,
the subtitle 2x at y +10..+26.

The final time on the same screen is read by vodreview/finaltime.py, which
reuses ResultDetector.locate() to find the line.
"""

import cv2
import numpy as np

from . import config
from .screens import region


def dragon_boxes(lay):
    """(bar row box, label box) in px for this layout (GUI geometry, see config.DRAGON_*_GUI)."""
    bx, by0, by1 = config.DRAGON_BAR_GUI
    lx, ly0, ly1 = config.DRAGON_LABEL_GUI
    return (lay.gui_rect(-bx, by0, bx, by1, ax="center"), lay.gui_rect(-lx, ly0, lx, ly1, ax="center"))


def _crop(frame, box):
    x0, y0, x1, y1 = box
    return frame[y0:max(y1, y0 + 1), x0:x1]


def dragon_bar(frame, boxes):
    """Read the boss bar in a BGR frame -> (bar_visible, fill_fraction)."""
    bar_box, label_box = boxes
    row = _crop(frame, bar_box).astype(np.int32).mean(axis=0)  # average the bar's rows
    blue, green, red = row[:, 0], row[:, 1], row[:, 2]
    # Magenta = lots of red and blue, almost no green (both bar parts).
    bar_pixels = (green < 25) & (red > 40) & (blue > 30) & (red > blue)
    if bar_pixels.mean() < config.DRAGON_BAR_MIN_COVERAGE:
        return False, 0.0
    # GUI screens dim the HUD, so a full bar looks dark like an empty one.
    # The white "Ender Dragon" label tells them apart: it is only white when
    # the HUD is not dimmed.
    label = _crop(frame, label_box)
    white = (label.min(axis=2) > 190).mean()
    if white < config.DRAGON_LABEL_MIN_WHITE:
        return False, 0.0
    filled = bar_pixels & (red > config.DRAGON_FILL_RED)
    return True, float(filled.sum() / bar_pixels.sum())


class DragonWatcher:
    """Feed samples in time order; update() returns the kill time once.

    Rule: the dragon died when its health bar emptied. To be safe we need
      - the bar seen with real health first (so we know it's the dragon bar),
      - then the bar empty for DRAGON_EMPTY_SECONDS (the death animation keeps
        an empty bar on screen for ~10 s), OR the bar disappearing right after
        it was nearly empty.
    A bar that disappears while still fairly full is just the player moving
    out of range, not a kill.
    """

    def __init__(self, lay):
        self.boxes = dragon_boxes(lay)
        self.seen_alive = False
        self.empty_since = None
        self.last_fill = None      # fill at the previous readable sample (None = bar not visible)
        self.last_time = None

    def update(self, t, frame, screen):
        if screen not in ("world", "f3"):
            return None            # HUD hidden or dimmed: can't read the bar
        visible, fill = dragon_bar(frame, self.boxes)
        kill = None
        if visible:
            if fill >= config.DRAGON_ALIVE_FILL:
                self.seen_alive = True
            if self.seen_alive and fill <= config.DRAGON_EMPTY_FILL:
                if self.empty_since is None:
                    self.empty_since = t
                if t - self.empty_since >= config.DRAGON_EMPTY_SECONDS - 1e-6:
                    kill = self.empty_since
            else:
                self.empty_since = None
        else:
            self.empty_since = None
            was_nearly_empty = self.last_fill is not None and self.last_fill <= config.DRAGON_NEAR_EMPTY_FILL
            if self.seen_alive and was_nearly_empty:
                kill = self.last_time
        self.last_fill = fill if visible else None
        self.last_time = t
        return kill


class ResultDetector:
    def __init__(self, lay):
        self.lay = lay
        self.scale = config.MATCH_SCALE
        tscale = config.MATCH_SCALE * lay.rel     # templates: tuning VOD's 1080p at GUI 4.5
        self.templates = []
        for path in sorted((config.CALIBRATION_DIR / "result").glob("*.png")):
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                self.templates.append(
                    cv2.resize(image, None, fx=tscale, fy=tscale, interpolation=cv2.INTER_AREA))
        sx, sy0, sy1 = config.RESULT_SUBTITLE_GUI
        tx, ty0, ty1 = config.RESULT_TITLE_GUI
        self.label_region = lay.gui_rect(-sx, sy0, sx, sy1, ax="center", ay="center")
        self.title_region = lay.gui_rect(-tx, ty0, tx, ty1, ax="center", ay="center")
        self.glyphs = None
        band0, band1 = config.RESULT_TITLE_BAND_GUI
        self.title_band = (lay.gui_rect(0, band0, 0, band1, ax="center", ay="center")[1::2])
        self.sub_band = lay.gui_rect(-sx, config.RESULT_SUB_BAND_GUI[0], sx, config.RESULT_SUB_BAND_GUI[1],
                                     ax="center", ay="center")
        self.draw_streak = 0
        self.notime_streak = 0

    def locate(self, gray_frame):
        """Find the "Match Winner:" label -> (score, (x0, y0, x1, y1) in full-frame pixels) or None."""
        rx0, ry0, rx1, ry1 = self.label_region
        search = cv2.resize(gray_frame[ry0:ry1, rx0:rx1], None, fx=self.scale, fy=self.scale,
                            interpolation=cv2.INTER_AREA)
        best = None
        for template in self.templates:
            th, tw = template.shape[:2]
            if th <= search.shape[0] and tw <= search.shape[1]:
                _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED))
                if best is None or score > best[0]:
                    box = (rx0 + x / self.scale, ry0 + y / self.scale,
                           rx0 + (x + tw) / self.scale, ry0 + (y + th) / self.scale)
                    best = (float(score), tuple(int(round(v)) for v in box))
        if best is None or best[0] < config.MATCH_THRESHOLD:
            return None
        return best

    def title_colour(self, frame):
        """Count vivid gold / red pixels in the title area -> (gold, red, centred?)."""
        x0, y0, x1, y1 = self.title_region
        title = cv2.resize(frame[y0:y1, x0:x1], None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(title, cv2.COLOR_BGR2HSV)
        hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        vivid = (sat >= config.RESULT_MIN_SATURATION) & (val >= config.RESULT_MIN_VALUE)
        lo, hi = config.RESULT_GOLD_HUE
        gold_m = vivid & (hue >= lo) & (hue <= hi)
        red_lo, red_hi = config.RESULT_RED_HUE
        red_m = vivid & ((hue <= red_lo) | (hue >= red_hi))
        both = gold_m | red_m
        centred = False
        if both.any():
            xs = np.flatnonzero(both.any(axis=0))
            mid = title.shape[1] / 2
            # a centred title: its left and right extents are about equally far from the centre
            centred = abs((xs[0] + xs[-1]) / 2 - mid) <= config.RESULT_TITLE_CENTRE_TOL * title.shape[1]
        return int(gold_m.sum()), int(red_m.sum()), centred

    def line_box(self):
        """Pixel box of the subtitle row (where "Match Winner: <name> (MM:SS.mmm)" is drawn)."""
        return self.label_region

    def read_time(self, frame, max_ms=None, fallback=True):
        """Read "(MM:SS.mmm)" on the subtitle row: whole row, then (fallback) the cluttered-row reads."""
        from .finaltime import read_result_line, read_result_time_right
        if self.glyphs is None:
            from .glyphs import load_glyph_templates
            self.glyphs = load_glyph_templates()
        raw, parsed = read_result_line(frame, self.line_box(), self.glyphs, max_ms)
        if parsed is None and fallback:
            gx0, _, gx1, _ = self.lay.game
            raw2, parsed = read_result_time_right(frame, self.line_box(), (gx0 + gx1) / 2, 2 * self.lay.k,
                                                  self.glyphs, max_ms)
            raw = raw2 if parsed else raw
        return raw, parsed

    def language_free(self, frame):
        """Result screen without words: a centred gold/red title + "(MM:SS.mmm)" on the subtitle row.

        If the time can't be read (F3 text drawn over it), the title structure alone counts
        once it holds on RESULT_NO_TIME_CONFIRM consecutive samples (see check())."""
        gold, red, centred = self.title_colour(frame)
        need = config.RESULT_TITLE_MIN_PX_GUI2 * (self.lay.k * self.scale) ** 2
        if max(gold, red) < need or not centred:
            return None
        outcome = "win" if gold >= red else "loss"
        _, parsed = self.read_time(frame, fallback=False)
        if parsed is not None:
            return outcome
        # cheap structure test before the slower fallback reads (gold blocks in a bastion
        # pass the colour test above, but are not a title-shaped band)
        if not self.title_structure(frame, self.gold_red_mask(frame), centred_sub=False):
            return None
        _, parsed = self.read_time(frame)
        return outcome if parsed is not None else outcome + "?"

    def gold_red_mask(self, frame):
        x0, y0, x1, y1 = self.title_region
        hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        vivid = (sat >= config.RESULT_MIN_SATURATION) & (val >= config.RESULT_MIN_VALUE)
        lo, hi = config.RESULT_GOLD_HUE
        red_lo, red_hi = config.RESULT_RED_HUE
        return vivid & (((hue >= lo) & (hue <= hi)) | (hue <= red_lo) | (hue >= red_hi))

    def aqua_mask(self, frame):
        x0, y0, x1, y1 = self.title_region
        hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        lo, hi = config.RESULT_AQUA_HUE
        return ((hue >= lo) & (hue <= hi) & (sat >= config.RESULT_AQUA_MIN_SATURATION)
                & (val >= config.RESULT_AQUA_MIN_VALUE))

    def title_structure(self, frame, mask, centred_sub=True):
        """Title-shaped colour mask (full-res title region) + white subtitle text below it.

        Title: enough pixels, >= RESULT_DRAW_BAND_SHARE of them inside the 4x title band, centred.
        Subtitle: white text on the subtitle row; with centred_sub the text block under the
        screen centre must be centred (a short line like "Match Draw!")."""
        x0, y0, x1, y1 = self.title_region
        total = int(mask.sum())
        if total < config.RESULT_TITLE_MIN_PX_GUI2 * self.lay.k ** 2:
            return False
        b0, b1 = self.title_band
        if mask[max(0, b0 - y0):max(0, b1 - y0)].sum() < config.RESULT_DRAW_BAND_SHARE * total:
            return False          # spread over all rows: sky / water / soul fire / gold blocks, not a title
        xs = np.flatnonzero(mask.any(axis=0))
        if abs((xs[0] + xs[-1]) / 2 - mask.shape[1] / 2) > config.RESULT_TITLE_CENTRE_TOL * mask.shape[1]:
            return False
        sx0, sy0, sx1, sy1 = self.sub_band
        per_col = (frame[sy0:sy1, sx0:sx1].min(axis=2) >= config.RESULT_SUB_WHITE_MIN).sum(axis=0)
        cols = np.flatnonzero(per_col)
        need = config.RESULT_SUB_MIN_PX_GUI2 * self.lay.k ** 2
        if not len(cols):
            return False
        if not centred_sub:
            return per_col.sum() >= need
        # Group white columns into text blocks (a word gap is ~10 GUI px); stray white pixels
        # elsewhere on the row (snow, sky, F3 text) form their own blocks and are ignored.
        breaks = np.flatnonzero(np.diff(cols) > config.RESULT_SUB_GAP_GUI * self.lay.k)
        starts = np.concatenate(([cols[0]], cols[breaks + 1]))
        ends = np.concatenate((cols[breaks], [cols[-1]]))
        gx0, _, gx1, _ = self.lay.game
        mid = (gx0 + gx1) / 2 - sx0
        for a, b in zip(starts, ends):
            if a <= mid <= b:   # the block under the screen centre must be the centred subtitle
                return (per_col[a:b + 1].sum() >= need and
                        abs((a + b) / 2 - mid) <= config.RESULT_SUB_CENTRE_TOL * (gx1 - gx0))
        return False

    def draw_screen(self, frame):
        """One frame of the draw screen? Aqua title in the title band + centred white subtitle."""
        return self.title_structure(frame, self.aqua_mask(frame), centred_sub=True)

    def check(self, frame, gray_frame):
        """Return "win", "loss", "draw" or None (no result screen) for one BGR frame."""
        if self.locate(gray_frame) is None:
            result = self.language_free(frame)
            if result and not result.endswith("?"):
                self.notime_streak = self.draw_streak = 0
                return result
            # time unreadable: the title structure must hold on a few consecutive samples
            self.notime_streak = self.notime_streak + 1 if result else 0
            if self.notime_streak >= config.RESULT_NO_TIME_CONFIRM:
                return result.rstrip("?")
            if result:
                return None
            self.draw_streak = self.draw_streak + 1 if self.draw_screen(frame) else 0
            if self.draw_streak >= config.RESULT_DRAW_CONFIRM:
                return "draw"
            return None
        gold, red, _ = self.title_colour(frame)
        if gold == 0 and red == 0:
            return None            # label found but no coloured title (yet): wait for the next sample
        return "win" if gold >= red else "loss"
