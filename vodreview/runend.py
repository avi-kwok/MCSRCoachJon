"""Run end: when did the run finish, and how?

Two detectors, both looking at fixed spots on the screen:

* DragonWatcher - reads the "Ender Dragon" boss bar. CV idea: *colour
  thresholding*. Instead of matching shapes we classify single pixels by their
  colour (bright magenta = health left, dark magenta = health lost), then
  measure what fraction of the bar is still bright.
* ResultDetector - finds the MCSR match-result screen with template matching
  ("Match Winner:" label), then reads the title colour in HSV: gold = win,
  red = loss. HSV splits colour into Hue (which colour), Saturation (how
  colourful) and Value (how bright), so "is this gold or red?" becomes a
  simple range check on hue.
"""

import cv2
import numpy as np

from . import config
from .screens import region


def dragon_bar(frame):
    """Read the boss bar in a BGR frame -> (bar_visible, fill_fraction)."""
    row = region(frame, config.DRAGON_BAR_ROW).astype(np.int32).mean(axis=0)  # average the bar's rows
    blue, green, red = row[:, 0], row[:, 1], row[:, 2]
    # Magenta = lots of red and blue, almost no green (both bar parts).
    bar_pixels = (green < 25) & (red > 40) & (blue > 30) & (red > blue)
    if bar_pixels.mean() < config.DRAGON_BAR_MIN_COVERAGE:
        return False, 0.0
    # GUI screens dim the HUD, so a full bar looks dark like an empty one.
    # The white "Ender Dragon" label tells them apart: it is only white when
    # the HUD is not dimmed.
    label = region(frame, config.DRAGON_LABEL_BOX)
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

    def __init__(self):
        self.seen_alive = False
        self.empty_since = None
        self.last_fill = None      # fill at the previous readable sample (None = bar not visible)
        self.last_time = None

    def update(self, t, frame, screen):
        if screen not in ("world", "f3"):
            return None            # HUD hidden or dimmed: can't read the bar
        visible, fill = dragon_bar(frame)
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
    def __init__(self, frame_height):
        self.scale = config.MATCH_SCALE * frame_height / config.TEMPLATE_SOURCE_HEIGHT
        self.templates = []
        for path in sorted((config.CALIBRATION_DIR / "result").glob("*.png")):
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                self.templates.append(
                    cv2.resize(image, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA))

    def check(self, frame, gray_frame):
        """Return "win", "loss" or None (no result screen) for one BGR frame."""
        small = cv2.resize(gray_frame, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)
        search = region(small, config.RESULT_LABEL_REGION)
        best = 0.0
        for template in self.templates:
            if template.shape[0] <= search.shape[0] and template.shape[1] <= search.shape[1]:
                best = max(best, float(cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED).max()))
        if best < config.MATCH_THRESHOLD:
            return None
        # Count strongly coloured, bright pixels in the title area by hue.
        title = cv2.resize(region(frame, config.RESULT_TITLE_REGION), None, fx=self.scale, fy=self.scale,
                           interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(title, cv2.COLOR_BGR2HSV)
        hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        vivid = (sat >= config.RESULT_MIN_SATURATION) & (val >= config.RESULT_MIN_VALUE)
        lo, hi = config.RESULT_GOLD_HUE
        gold = (vivid & (hue >= lo) & (hue <= hi)).sum()
        red_lo, red_hi = config.RESULT_RED_HUE
        red = (vivid & ((hue <= red_lo) | (hue >= red_hi))).sum()
        if gold == 0 and red == 0:
            return None            # label found but no coloured title (yet): wait for the next sample
        return "win" if gold >= red else "loss"
