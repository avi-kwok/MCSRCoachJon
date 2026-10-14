"""Reading Minecraft text by glyph template matching (a tiny classical OCR).

CV idea: Minecraft's font is a fixed *bitmap* font - every character is a
small grid of on/off "font pixels" (digits are 5 wide x 7 tall), drawn at an
integer GUI scale and then scaled again by the recording (here 1440p -> 1080p,
so one font pixel is 4.5 or 9 screen pixels). So instead of a general OCR
model we can:

1. **Threshold**: mark light, unsaturated pixels as "text" (white/grey text;
   gold names and coloured world pixels are left out). Optionally require the
   1-font-pixel drop shadow Minecraft draws down-right of chat/title text, so a
   bright block behind the text doesn't count.
2. **Segment**: a column projection (how many text pixels per column) splits
   the line into glyphs, because Minecraft leaves one empty font pixel between
   characters.
3. **Normalise**: estimate the font-pixel size s from the glyph height
   (7 font pixels), and shrink every glyph to its font grid (w x 7 cells) with
   area averaging -> a tiny binary image that no longer depends on GUI scale
   or recording resolution.
4. **Match**: compare that grid with the saved templates in
   `calibration/glyphs/` (same grid size) and pick the one with the most equal
   cells.
"""

import cv2
import numpy as np

from . import config

FONT_ROWS = 7                  # cap height of Minecraft's font, in font pixels
GLYPH_FILES = {"colon": ":", "dot": ".", "lparen": "(", "rparen": ")", "slash": "/", "minus": "-"}


def text_mask(bgr, min_light=None, max_chroma=None):
    """Boolean mask of light, unsaturated (white/grey) pixels in a BGR image."""
    min_light = config.GLYPH_MIN_LIGHT if min_light is None else min_light
    max_chroma = config.GLYPH_MAX_CHROMA if max_chroma is None else max_chroma
    pixels = bgr.astype(np.int16)
    lo, hi = pixels.min(axis=2), pixels.max(axis=2)
    return (lo >= min_light) & (hi - lo <= max_chroma)


def keep_shadowed(mask, gray, shift):
    """Keep text pixels whose drop-shadow pixel (shift px down-right) is dark or also text."""
    if shift < 1:
        return mask
    h, w = mask.shape
    below = np.zeros_like(mask)                      # True where the shadow position is dark/text
    shadow_ok = (gray[shift:, shift:] < config.GLYPH_SHADOW_MAX) | mask[shift:, shift:]
    below[:h - shift, :w - shift] = shadow_ok
    return mask & below


def column_runs(mask, min_pixels):
    """Split a text line into [x0, x1) runs of columns that hold >= min_pixels text pixels."""
    on = mask.sum(axis=0) >= min_pixels
    runs, start = [], None
    for x, value in enumerate(on):
        if value and start is None:
            start = x
        elif not value and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, len(on)))
    return runs


def segment_line(mask, font_px=None, top=None):
    """Cut a one-line text mask into glyph grids.

    Returns (font_px, glyphs) where glyphs is a list of
    {"x0", "x1", "grid" (bool array FONT_ROWS x width-in-font-pixels), "gap"}
    and "gap" is the empty space before the glyph in font pixels (>= 3 = a space).
    """
    runs = column_runs(mask, min_pixels=2)
    if not runs:
        return None, []
    tops, bottoms = [], []
    for x0, x1 in runs:
        rows = np.flatnonzero(mask[:, x0:x1].any(axis=1))
        tops.append(rows[0])
        bottoms.append(rows[-1] + 1)
    if font_px is None:
        # The tallest common glyph height is 7 font pixels (digits, capitals, brackets).
        font_px = float(np.median([b - t for t, b in zip(tops, bottoms)])) / FONT_ROWS
    if font_px < config.GLYPH_MIN_FONT_PX:
        return font_px, []
    # The recording's downscale blends neighbouring font pixels, so a glyph can
    # show a 1-px empty column at a corner. Real gaps between glyphs are a whole
    # font pixel wide, so join runs separated by less than half a font pixel.
    merged = [list(runs[0])]
    for x0, x1 in runs[1:]:
        if x0 - merged[-1][1] < 0.5 * font_px:
            merged[-1][1] = x1
        else:
            merged.append([x0, x1])
    runs = merged
    if top is None:
        top = int(np.median(tops))
    band = mask[top:top + int(round(FONT_ROWS * font_px))].astype(np.float32)
    if band.shape[0] < FONT_ROWS:
        return font_px, []
    glyphs, prev_end = [], None
    for x0, x1 in runs:
        width = max(1, int(round((x1 - x0) / font_px)))
        cells = cv2.resize(band[:, x0:x1], (width, FONT_ROWS), interpolation=cv2.INTER_AREA)
        gap = 0 if prev_end is None else int(round((x0 - prev_end) / font_px))
        glyphs.append({"x0": x0, "x1": x1, "grid": cells >= 0.5, "gap": gap})
        prev_end = x1
    return font_px, glyphs


def load_glyph_templates(folder=None):
    """calibration/glyphs/*.png -> {char: bool grid}. White = font pixel on."""
    folder = folder or config.CALIBRATION_DIR / "glyphs"
    templates = {}
    for path in sorted(folder.glob("*.png")):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        templates[GLYPH_FILES.get(path.stem, path.stem)] = image >= 128
    return templates


def match_glyph(grid, templates):
    """Best (char, score) for one glyph grid; score = share of equal cells (0..1)."""
    best, best_score = "?", 0.0
    for char, template in templates.items():
        if template.shape != grid.shape:
            continue
        score = float((template == grid).mean())
        if score > best_score:
            best, best_score = char, score
    if best_score < config.GLYPH_MIN_SCORE:
        return "?", best_score
    return best, best_score


def read_line(bgr, templates, shadow=False):
    """Read one line of light Minecraft text in a BGR crop -> (text, font_px).

    Unknown glyphs come out as "?", gaps of >= 3 font pixels as a space.
    """
    mask = text_mask(bgr)
    font_px, _ = segment_line(mask)
    if font_px is None:
        return "", None
    if shadow:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        mask = keep_shadowed(mask, gray, int(round(font_px)))
        font_px, _ = segment_line(mask)
        if font_px is None:
            return "", None
    font_px, glyphs = segment_line(mask, font_px)
    text = ""
    for glyph in glyphs:
        if glyph["gap"] >= 3:
            text += " "
        text += match_glyph(glyph["grid"], templates)[0]
    return text, font_px
