"""Screen recognition: which kind of screen is showing (world, inventory, pause, ...)?

CV idea: *template matching*. We keep small reference crops ("templates") of
things that only appear on a given screen, e.g. the word "Crafting" on the
inventory panel. cv2.matchTemplate slides the template over the frame and
reports, at every position, how similar the pixels are. With the
TM_CCOEFF_NORMED method the score is a correlation in [-1, 1]: 1.0 means a
perfect match, and it ignores overall brightness/contrast changes, which helps
when the world behind a semi-transparent text box is brighter or darker.

The resized (tall/thin/wide) view is found differently, by *geometry*: see
is_resized() below.
"""

import cv2
import numpy as np

from . import config


def load_templates():
    """Load calibration/<screen>/*.png as grayscale images, per screen type.

    A screen type with an empty or missing folder simply gets no templates and
    can never be detected (it is not an error).
    """
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


def region(image, box):
    """Cut a normalized (x0, y0, x1, y1) box out of an image."""
    h, w = image.shape[:2]
    x0, y0, x1, y1 = box
    return image[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def flat_fraction(gray_region, tile):
    """Share of tile x tile blocks whose brightness std dev is tiny.

    CV idea: *local variance*. A flat area (wallpaper, even with a smooth
    colour gradient) barely changes inside a small tile, so its standard
    deviation is ~0; text, block textures or HUD icons give a large one.
    """
    h, w = gray_region.shape
    h, w = h - h % tile, w - w % tile
    tiles = gray_region[:h, :w].astype(np.float32).reshape(h // tile, tile, w // tile, tile)
    return float((tiles.std(axis=(1, 3)) < config.RESIZED_TILE_STD).mean())


def edge_contrast(gray, box, gap=2):
    """Mean brightness jump across the border of a strip rectangle.

    Compares the pixel line just inside each edge with the line just outside
    it (`gap` pixels away). Edges that touch the frame border are skipped.
    """
    h, w = gray.shape
    x0, x1 = int(round(box[0] * w)), int(round(box[2] * w))
    y0, y1 = int(round(box[1] * h)), int(round(box[3] * h))
    g = gray.astype(np.float32)
    jumps = []
    if x0 - gap - 1 >= 0:
        jumps.append(np.abs(g[y0:y1, x0 + gap] - g[y0:y1, x0 - gap - 1]).mean())
    if x1 + gap < w:
        jumps.append(np.abs(g[y0:y1, x1 - gap - 1] - g[y0:y1, x1 + gap]).mean())
    if y0 - gap - 1 >= 0:
        jumps.append(np.abs(g[y0 + gap, x0:x1] - g[y0 - gap - 1, x0:x1]).mean())
    if y1 + gap < h:
        jumps.append(np.abs(g[y1 - gap - 1, x0:x1] - g[y1 + gap, x0:x1]).mean())
    return float(np.mean(jumps))


def is_resized(gray_frame):
    """True if the game is shrunk into a tall/thin/wide strip.

    Every MCSR runner gets the same strip positions, so we only look at fixed
    regions: (1) areas outside the strip in every layout must be flat
    wallpaper, and (2) at least one layout's strip border must show a visible
    edge - which rules out an all-black loading/reset frame (flat everywhere).
    """
    small = cv2.resize(gray_frame, config.MOTION_SIZE, interpolation=cv2.INTER_AREA)
    for box in config.RESIZED_FLAT_REGIONS.values():
        if flat_fraction(region(small, box), config.RESIZED_TILE) < config.RESIZED_FLAT_FRACTION:
            return False
    best_edge = max(edge_contrast(small, box) for box in config.RESIZED_LAYOUTS.values())
    return best_edge > config.RESIZED_EDGE_CONTRAST


class ScreenClassifier:
    def __init__(self, frame_height):
        # Templates were cut from 1080p frames. We resize them by the same
        # factor we resize each frame by, so text sizes line up.
        self.scale = config.MATCH_SCALE * frame_height / config.TEMPLATE_SOURCE_HEIGHT
        self.templates = {}
        for screen, images in load_templates().items():
            self.templates[screen] = [
                cv2.resize(img, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)
                for _, img in images
            ]

    def missing_screens(self):
        return [s for s, t in self.templates.items() if not t]

    def scores(self, gray_frame):
        """Best match score per screen type (0.0 if it has no templates)."""
        small = cv2.resize(gray_frame, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)
        h, w = small.shape
        result = {}
        for screen, templates in self.templates.items():
            x0, y0, x1, y1 = config.SEARCH_REGIONS[screen]
            region = small[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
            best = 0.0
            for template in templates:
                th, tw = template.shape
                if th > region.shape[0] or tw > region.shape[1]:
                    continue
                match = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
                best = max(best, float(match.max()))
            result[screen] = best
        return result

    def classify(self, gray_frame):
        """Return the screen type name for one full-resolution grayscale frame."""
        # Checked first: in the resized view the GUI is squeezed into the
        # strip, so the templates (cut from full-size screens) can't match.
        if is_resized(gray_frame):
            return "resized"
        scores = self.scores(gray_frame)
        for screen in config.SCREEN_PRIORITY:
            if scores[screen] >= config.MATCH_THRESHOLD:
                return screen
        return "world"   # nothing matched: assume normal gameplay view


class ResetDialogDetector:
    """MCSR's "Are you sure you want to reset this world?" confirmation (template match)."""

    def __init__(self, frame_height):
        self.scale = config.MATCH_SCALE * frame_height / config.TEMPLATE_SOURCE_HEIGHT
        self.templates = []
        folder = config.CALIBRATION_DIR / "reset"
        for path in sorted(folder.glob("*.png")) if folder.is_dir() else []:
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                self.templates.append(cv2.resize(image, None, fx=self.scale, fy=self.scale,
                                                 interpolation=cv2.INTER_AREA))

    def check(self, gray_frame):
        if not self.templates:
            return False
        crop = cv2.resize(region(gray_frame, config.RESET_SEARCH_REGION), None, fx=self.scale, fy=self.scale,
                          interpolation=cv2.INTER_AREA)
        for template in self.templates:
            if template.shape[0] <= crop.shape[0] and template.shape[1] <= crop.shape[1]:
                if cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED).max() >= config.MATCH_THRESHOLD:
                    return True
        return False
