"""Which dimension is the player in? (overworld / nether / end / unknown)

Two signals, both per sample and only on `world` / `f3` screens (GUIs dim or
hide the world, resized strips are too small):

1. **F3 text** (when the debug screen is open): the 9th line of the left
   column reads "minecraft:overworld" / "minecraft:the_nether" /
   "minecraft:the_end" - namespaced ids, never translated. The line is read
   with the glyph reader (letter templates) at the measured GUI scale; the old
   word templates (calibration/dimension/*.png, rescaled) are the fallback.
   When it reads, that label wins - it is the game telling us.
2. **Colour statistics** of the game view (the overlays measured for this
   video - layout.json - the vanilla HUD and the held items masked, frame
   shrunk to 64x36). In HSV colour space we count the share of pixels that
   look like
     - nether: saturated red (netherrack, crimson, nether bricks) or teal
       (warped forest, soul sand valley fog), and no blue/green (the nether
       has no sky: teal *with* sky or blue water is warm-ocean water),
     - End: dark purple-black sky *and* pale-yellow end stone,
     - overworld: blue sky / water or green grass / leaves, and no nether colours.
   Simple thresholds on those shares give a label; anything ambiguous (caves,
   dark rooms, night / rain / snow skies that are dark or grey, soul sand
   valley without red) is "" (unknown) rather than a guess - every class needs
   saturated, reasonably bright pixels, so a dark or grey frame can't be called
   nether. Dimension *changes* come from the portal transition first
   (transition.py, splits.py); these labels only say which side is which.

The per-sample labels are smoothed later (splits.dimension_stretches).
"""

import cv2
import numpy as np

from . import config
from .glyphs import keep_shadowed, load_glyph_templates, match_glyph, segment_line, text_mask
from .motion import build_mask

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
    # Teal next to plenty of sky / water is warm-ocean water, not a warped forest: the nether
    # has no sky (blue <= 0.05 on every F3-confirmed nether sample of the four videos).
    teal_ok = f["teal"] < c.DIM_OVERWORLD_MAX_TEAL or blue >= c.DIM_OVERWORLD_TEAL_SKY
    if (blue >= c.DIM_OVERWORLD_BLUE_MIN or f["green"] >= c.DIM_OVERWORLD_GREEN_MIN) and \
            f["red"] < c.DIM_OVERWORLD_MAX_RED and teal_ok and f["end_sky"] < c.DIM_END_SKY_MIN:
        return "overworld"
    return ""


F3_DIM_WORDS = {"overworld": "overworld", "the_nether": "nether", "the_end": "end"}


def _f3_word(text):
    """'minecraft:the_nether FC: 0' (maybe with '?' glyphs) -> dimension or ""."""
    import difflib
    if ":" not in text:
        return ""
    head = text.split(" ")[0]
    if not head.lower().startswith(("minecraft:", "minecraft?", "minecraft")):
        return ""
    word = head.split(":", 1)[1] if ":" in head else ""
    best, ratio = "", 0.0
    for key, dim in F3_DIM_WORDS.items():
        r = difflib.SequenceMatcher(None, word, key).ratio()
        if r > ratio:
            best, ratio = dim, r
    return best if ratio >= config.DIM_F3_MIN_WORD_RATIO else ""


class DimensionClassifier:
    def __init__(self, lay):
        self.lay = lay
        w, h = THUMB
        rects = lay.overlay_rects() + lay.hud_rects() + [config.DIM_EXTRA_MASK[k] for k in ("held_item", "offhand_item")]
        self.mask = build_mask(w, h, rects)
        self.scale = config.DIM_F3_SCALE
        tscale = config.DIM_F3_SCALE * lay.rel
        self.templates = {}
        folder = config.CALIBRATION_DIR / "dimension"
        for path in sorted(folder.glob("*.png")) if folder.is_dir() else []:
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is not None and path.stem in DIMENSIONS:
                self.templates[path.stem] = cv2.resize(image, None, fx=tscale, fy=tscale,
                                                       interpolation=cv2.INTER_AREA)
        x0, y0, x1, y1 = config.DIM_F3_REGION_GUI
        self.f3_region = lay.gui_rect(x0, y0, x1, y1)
        from .opponent import load_letter_templates, name_templates
        self.glyphs = name_templates(load_letter_templates(), load_glyph_templates())
        colon = load_glyph_templates().get(":")
        if colon is not None:
            self.glyphs[":"] = np.vstack([colon, np.zeros((1, colon.shape[1]), bool)])

    def f3_read(self, frame):
        """Read the F3 dimension line with the glyph reader -> dimension or "".

        Tries F3 lines 7-10 (the dimension is line 8 = GUI y 2 + 9*8 in vanilla
        1.16; a mod can add a line above it).
        """
        k = self.lay.k
        x0, y0 = self.lay.game[0], self.lay.game[1]
        for line in config.DIM_F3_LINES:
            top = y0 + (2 + 9 * line) * k
            ya, yb = int(round(top - 1 * k)), int(round(top + 9 * k))
            xa, xb = int(round(x0 + 1 * k)), int(round(x0 + config.DIM_F3_LINE_GUI_W * k))
            crop = frame[max(0, ya):yb, xa:xb]
            if crop.size == 0:
                continue
            mask = keep_shadowed(text_mask(crop), cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), max(1, int(round(k))))
            if mask.sum() < 20:
                continue
            _, glyphs = segment_line(mask, k, int(round(top - ya)), rows=8)
            text = ""
            for g in glyphs:
                if g["gap"] >= 3:
                    text += " "
                text += match_glyph(g["grid"], self.glyphs)[0]
            dim = _f3_word(text)
            if dim:
                return dim
        return ""

    def f3_label(self, gray):
        """Dimension word on the F3 screen by the (rescaled) word templates -> (label or "", best score)."""
        if not self.templates:
            return "", 0.0
        x0, y0, x1, y1 = self.f3_region
        crop = gray[y0:y1, x0:x1]
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

    def classify(self, frame, gray, screen, with_source=False):
        """-> "overworld" / "nether" / "end" / "" (unknown or not a world view).

        with_source: return (label, source) with source "f3" / "colour" / "".
        """
        label, src = "", ""
        if screen in ("world", "f3"):
            if screen == "f3":
                label = self.f3_read(frame) or self.f3_label(gray)[0]
                src = "f3" if label else ""
            if not label:
                label = classify_colour(colour_features(frame, self.mask))
                src = "colour" if label else ""
        return (label, src) if with_source else label
