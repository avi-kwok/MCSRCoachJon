"""Screen recognition: which kind of screen is showing (world, inventory, pause, ...)?

Primary: **GUI structure at the measured GUI scale** (vodreview/gui.py,
layout.py) - no words, so it works in every game language and at any GUI
scale:

* `inventory` - a centred #C6C6C6 container panel (176 GUI px wide, 120-235
  tall) holding #8B8B8B slot squares (inventory, crafting table, chests,
  furnace ... - all containers share the look);
* `pause` - a centred column of >= 3 vanilla buttons with at least one
  full-width (200/204 GUI px) button; `settings` - >= 4 options-style
  (150 GUI px) buttons in two columns;
* `f3` - >= 11 left-aligned white text lines on F3's 9-GUI-px line grid;
* `resized` - the full-size hotbar is gone and most of the frame is flat
  wallpaper (layout.find_strip): MCSR's tall/thin/wide macros wherever the
  player's OBS scene puts the strip.

Secondary: the old F3 text templates in `calibration/f3/` (cv2.matchTemplate,
TM_CCOEFF_NORMED), rescaled by the measured GUI scale - F3 text is never
translated, and its bottom lines still show when a Ninjabrain window covers the
top of the left column (fewer than F3_MIN_LINES lines visible). The English
inventory/pause templates are kept in calibration/ but no longer used
(config.SECONDARY_TEMPLATE_SCREENS): on the tuning VOD's 362 keyframes the
structure tests agreed with them on every frame, and they cost ~10 ms a sample.
"""

import cv2
import numpy as np

from . import config, gui
from .layout import find_strip


def load_templates():
    """Load calibration/<screen>/*.png as grayscale images, per screen type."""
    templates = {}
    for screen in config.SCREEN_PRIORITY:
        folder = config.CALIBRATION_DIR / screen
        images = []
        for path in sorted(folder.glob("*.png")) if folder.is_dir() else []:
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                images.append((path.name, image))
        templates[screen] = images
    return templates


def secondary_templates():
    return {k: v for k, v in load_templates().items() if k in config.SECONDARY_TEMPLATE_SCREENS}


def region(image, box):
    """Cut a normalized (x0, y0, x1, y1) box out of an image."""
    h, w = image.shape[:2]
    x0, y0, x1, y1 = box
    return image[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def structure_screen(frame, gray, lay, small_gray=None):
    """Structure-only screen type -> (screen or "world", strip rect in 480x270 px or None).

    `small_gray` = the frame shrunk to config.MOTION_SIZE (made here if not given).
    """
    k, game = lay.k, lay.game
    s = gui.shrink_factor(k)
    ks = k * s
    small = cv2.resize(frame, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else frame
    game_s = tuple(v * s for v in game)
    rng = gui.channel_range(small)
    if gui.container_panel(small, ks, game_s, rng) is not None:
        return "inventory", None
    buttons = gui.find_buttons(small, ks, game_s, rng)
    menu = gui.classify_buttons(buttons, ks, game_s)
    if menu:
        return menu, None
    if gui.f3_lines(gray, k, game) >= config.F3_MIN_LINES:
        return "f3", None
    hb = gui.hotbar_score(gray, k, game)
    if hb < config.RESIZED_MAX_HOTBAR_SCORE:
        if small_gray is None:
            small_gray = cv2.resize(gray, config.MOTION_SIZE, interpolation=cv2.INTER_AREA)
        strip = find_strip(small_gray, hb)
        if strip is not None:
            return "resized", strip
    return "world", None


class ScreenClassifier:
    def __init__(self, lay):
        self.lay = lay
        # Templates were cut from the tuning VOD's 1080p frames (GUI scale 4.5):
        # resize them by the measured GUI scale relative to that.
        self.scale = config.MATCH_SCALE * lay.h / config.TEMPLATE_SOURCE_HEIGHT
        tscale = config.MATCH_SCALE * lay.rel
        self.templates = {}
        for screen, images in secondary_templates().items():
            self.templates[screen] = [
                cv2.resize(img, None, fx=tscale, fy=tscale, interpolation=cv2.INTER_AREA)
                for _, img in images
            ]
        self.last_strip = None       # strip rect (full-frame px) of the last `resized` frame

    def missing_screens(self):
        return []                    # every screen type has a structure test

    def template_scores(self, gray_frame):
        """Best (rescaled) template match score per screen type (0.0 if it has no templates)."""
        f = config.MATCH_SCALE
        small = cv2.resize(gray_frame, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        h, w = small.shape
        result = {}
        for screen, templates in self.templates.items():
            x0, y0, x1, y1 = config.SEARCH_REGIONS[screen]
            reg = small[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
            best = 0.0
            for template in templates:
                th, tw = template.shape
                if th > reg.shape[0] or tw > reg.shape[1] or th < 4 or tw < 4:
                    continue
                best = max(best, float(cv2.matchTemplate(reg, template, cv2.TM_CCOEFF_NORMED).max()))
            result[screen] = best
        return result

    def classify(self, gray_frame, frame=None, small_gray=None):
        """Return the screen type name for one full-resolution frame (grey; BGR for the structure tests)."""
        self.last_strip = None
        if frame is None:
            frame = cv2.cvtColor(gray_frame, cv2.COLOR_GRAY2BGR)
        screen, strip = structure_screen(frame, gray_frame, self.lay, small_gray)
        if screen == "resized":
            sx = self.lay.w / config.MOTION_SIZE[0]
            sy = self.lay.h / config.MOTION_SIZE[1]
            self.last_strip = (int(strip[0] * sx), int(strip[1] * sy), int(strip[2] * sx), int(strip[3] * sy))
            return screen
        if screen != "world":
            return screen
        scores = self.template_scores(gray_frame)
        for name in config.SCREEN_PRIORITY:
            if scores.get(name, 0.0) >= config.MATCH_THRESHOLD:
                return name
        return "world"   # nothing matched: assume normal gameplay view


class ResetDialogDetector:
    """MCSR's "Are you sure you want to reset this world?" confirmation.

    MCSR's own text (not translated by the game language - the panel, result
    screen and status lines are English in a Norwegian-language game too), so
    the template is rescaled by the GUI scale and searched around the screen
    centre. In another MCSR language this would need a new template; a reset
    is also inferred from an advancement earned twice (splits.py).
    """

    def __init__(self, lay):
        self.lay = lay
        self.scale = config.MATCH_SCALE
        tscale = config.MATCH_SCALE * lay.rel
        self.templates = []
        folder = config.CALIBRATION_DIR / "reset"
        for path in sorted(folder.glob("*.png")) if folder.is_dir() else []:
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                self.templates.append(cv2.resize(image, None, fx=tscale, fy=tscale, interpolation=cv2.INTER_AREA))
        # The question sits ~(-50 .. -38) GUI px above the centre (1080p y 305-360 at k 4.5).
        self.box = lay.gui_rect(-config.RESET_SEARCH_GUI[0], -config.RESET_SEARCH_GUI[1],
                                config.RESET_SEARCH_GUI[0], config.RESET_SEARCH_GUI[2], ax="center", ay="center")

    def check(self, gray_frame):
        if not self.templates:
            return False
        x0, y0, x1, y1 = self.box
        crop = cv2.resize(gray_frame[y0:y1, x0:x1], None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)
        for template in self.templates:
            if template.shape[0] <= crop.shape[0] and template.shape[1] <= crop.shape[1]:
                if cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED).max() >= config.MATCH_THRESHOLD:
                    return True
        return False
