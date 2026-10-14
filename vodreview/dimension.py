"""Which dimension is the player in? (overworld / nether / end / unknown)

Two signals, both per sample and only on `world` / `f3` screens (GUIs dim or
hide the world, resized strips are too small):

1. **F3 text** (when the debug screen is open): the 9th line of the left
   column reads "minecraft:overworld" / "minecraft:the_nether". The dimension
   word is template-matched (calibration/dimension/*.png, like the screen
   templates). When it matches, that label wins - it is the game telling us.
2. **Colour statistics** of the game view (HUD/overlay areas masked, frame
   shrunk to 64x36). In HSV colour space we count the share of pixels that
   look like
     - nether: saturated red (netherrack, crimson, nether bricks) or teal
       (warped forest, soul sand valley fog), and no blue/green,
     - End: dark purple-black sky *and* pale-yellow end stone,
     - overworld: blue sky / water or green grass / leaves, and no nether colours.
   Simple thresholds on those shares give a label; anything ambiguous (caves,
   dark rooms, soul sand valley without red) is "" (unknown) rather than a guess.

The per-sample labels are smoothed later (splits.dimension_stretches).
"""

import cv2
import numpy as np

from . import config
from .motion import build_mask
from .screens import region

DIMENSIONS = ("overworld", "nether", "end")
THUMB = (64, 36)


def colour_features(frame, mask):
    """Share of (unmasked) pixels per colour class in a BGR frame."""
    # Every 6th pixel first (a full-frame INTER_AREA resize costs ~4 ms, this ~0.5 ms).
    step = max(1, frame.shape[0] // (THUMB[1] * 5))
    small = cv2.resize(frame[::step, ::step], THUMB, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    h, s, v = (hsv[..., i].astype(np.int16) for i in range(3))
    n = max(1, int(mask.sum()))

    def share(cond):
        return float((cond & mask).sum()) / n

    return {
        # Netherrack / crimson nylium / nether bricks: red hue (0-4 or 172-179 on
        # OpenCV's 0-179 scale), clearly saturated. Orange terracotta (desert
        # temples, hue ~8-12) and lava (hue 10-20) are left out on purpose.
        "red": share(((h <= 4) | (h >= 172)) & (s >= 90) & (v >= 30)),
        # Warped forest / soul sand valley: teal-cyan (never seen in the overworld here).
        "teal": share((h >= 80) & (h <= 95) & (s >= 80) & (v >= 40)),
        # End sky: very dark, purple.
        "end_sky": share((h >= 120) & (h <= 165) & (s >= 40) & (v < 80)),
        # End stone: pale yellow (hue ~31; desert sand is ~24).
        "end_stone": share((h >= 28) & (h <= 36) & (s >= 50) & (s <= 130) & (v >= 150)),
        # Overworld sky (blue, bright) and water (blue, saturated, also at night).
        "sky": share((h >= 95) & (h <= 125) & (s >= 40) & (v >= 130)),
        "water": share((h >= 100) & (h <= 125) & (s >= 100) & (v >= 60)),
        # Grass / leaves (gold blocks/ingots are hue ~25-30, left out).
        "green": share((h >= 35) & (h <= 80) & (s >= 70) & (v >= 40)),
    }


def classify_colour(f):
    """Colour shares -> "end" / "nether" / "overworld" / "" (not sure)."""
    c = config
    if f["end_sky"] >= c.DIM_END_SKY_MIN and f["end_stone"] >= c.DIM_END_STONE_MIN and f["red"] < c.DIM_END_MAX_RED:
        return "end"
    blue = max(f["sky"], f["water"])
    if (f["red"] >= c.DIM_NETHER_RED_MIN or f["teal"] >= c.DIM_NETHER_TEAL_MIN) and \
            blue < c.DIM_NETHER_MAX_BLUE and f["green"] < c.DIM_NETHER_MAX_GREEN:
        return "nether"
    if (blue >= c.DIM_OVERWORLD_BLUE_MIN or f["green"] >= c.DIM_OVERWORLD_GREEN_MIN) and \
            f["red"] < c.DIM_OVERWORLD_MAX_RED and f["teal"] < c.DIM_OVERWORLD_MAX_TEAL and \
            f["end_sky"] < c.DIM_END_SKY_MIN:
        return "overworld"
    return ""


class DimensionClassifier:
    def __init__(self, frame_height):
        w, h = THUMB
        self.mask = build_mask(w, h, list(config.OVERLAY_MASK.values()) + list(config.DIM_EXTRA_MASK.values()))
        self.scale = config.DIM_F3_SCALE * frame_height / config.TEMPLATE_SOURCE_HEIGHT
        self.templates = {}
        folder = config.CALIBRATION_DIR / "dimension"
        for path in sorted(folder.glob("*.png")) if folder.is_dir() else []:
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is not None and path.stem in DIMENSIONS:
                self.templates[path.stem] = cv2.resize(image, None, fx=self.scale, fy=self.scale,
                                                       interpolation=cv2.INTER_AREA)

    def f3_label(self, gray):
        """Dimension word on the F3 screen -> (label or "", best score)."""
        if not self.templates:
            return "", 0.0
        crop = region(gray, config.DIM_F3_REGION)
        crop = cv2.resize(crop, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)
        scores = []
        for name, t in self.templates.items():
            if t.shape[0] <= crop.shape[0] and t.shape[1] <= crop.shape[1]:
                scores.append((float(cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED).max()), name))
        if not scores:
            return "", 0.0
        scores.sort(reverse=True)
        best, name = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0.0
        if best >= config.DIM_F3_MIN_SCORE and best - second >= config.DIM_F3_MIN_MARGIN:
            return name, best
        return "", best

    def classify(self, frame, gray, screen):
        """-> "overworld" / "nether" / "end" / "" (unknown or not a world view)."""
        if screen not in ("world", "f3"):
            return ""
        if screen == "f3":
            label, _ = self.f3_label(gray)
            if label:
                return label
        return classify_colour(colour_features(frame, self.mask))
