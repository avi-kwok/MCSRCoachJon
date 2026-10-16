"""Minecraft's default font as bitmaps, and text rendering at any scale (analysis by synthesis).

The 1.16 default font is a fixed bitmap font: every character is a grid of
"font pixels" 8 rows tall (7 rows above the baseline + 1 descender row for
g j p q y and the underscore), drawn with a 1-font-px gap after it and, for
chat / HUD text, a drop shadow 1 font px down-right in 25% of the text colour.
Italic text (MCSR's status line) is the same glyph quad sheared: the top edge
moves +1 font px right, the bottom edge -1 (0.25 px per row).

The glyph bitmaps come from `calibration/glyphs/` (digits / punctuation, 7
rows) and `calibration/glyphs/letters/` (8 rows), all harvested from the
videos (see the calibration README for which frames).

Rendering (`render`): each glyph is drawn on a fine grid (SUPER sub-pixels per
font px), optionally sheared and shadowed, then shrunk to the target scale
with area averaging - the same blending of neighbouring font pixels that the
recording's downscale does. The result is a float image with 1.0 = text,
`shadow_level` = shadow, 0 = background; readers compare it with what the
video shows instead of trying to cut tiny blurred glyphs apart.
"""

import cv2
import numpy as np

from . import config

ROWS = 8                    # font px per line incl. the descender row
SUPER = 8                   # sub-pixels per font px when rendering
# Advance (glyph width + 1 px gap) in font px; everything else is 6. Same table as opponent.text_width.
ADVANCE = {"i": 2, "l": 3, "t": 4, "I": 4, "f": 5, "k": 5, " ": 4, "!": 2, ".": 2, ",": 2, ":": 2,
           ";": 2, "'": 2, "|": 2, "[": 4, "]": 4, "(": 5, ")": 5, "<": 5, ">": 5, "*": 5}
GLYPH_FILES = {"colon": ":", "dot": ".", "lparen": "(", "rparen": ")", "slash": "/", "minus": "-",
               "underscore": "_"}


def advance(ch):
    return ADVANCE.get(ch, 6)


def text_width(text):
    """Width of a string in font px (no trailing gap)."""
    return sum(advance(c) for c in text) - 1


def load_font(folder=None):
    """{char: bool array (8 rows x width)} from the harvested glyph files (letters win over digits)."""
    folder = folder or config.CALIBRATION_DIR / "glyphs"
    glyphs = {}
    for path in sorted(folder.glob("*.png")):
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        g = img >= 128
        if g.shape[0] == 7:
            g = np.vstack([g, np.zeros((1, g.shape[1]), bool)])
        glyphs[GLYPH_FILES.get(path.stem, path.stem)] = g
    for path in sorted((folder / "letters").glob("*.png")):
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        stem = path.stem
        ch = GLYPH_FILES.get(stem, stem[-1] if stem.startswith(("lower_", "upper_")) else stem)
        glyphs[ch] = img >= 128
    glyphs[" "] = np.zeros((ROWS, 3), bool)
    return glyphs


def _bitmap(text, font):
    """Text -> bool bitmap in font px (8 rows, glyphs at their advances); None if a glyph is missing."""
    width = max(1, text_width(text))
    out = np.zeros((ROWS, width + 1), bool)
    x = 0
    for ch in text:
        g = font.get(ch)
        if g is None:
            return None
        w = min(g.shape[1], out.shape[1] - x)
        out[:, x:x + w] |= g[:, :w]
        x += advance(ch)
    return out


def render(text, font, font_px, italic=False, shadow=True, shadow_level=-1.0, pad=2, x_phase=0.0, y_phase=0.0):
    """Render text at `font_px` screen px per font px -> float32 image (text 1, shadow `shadow_level`, else 0).

    The text's top-left corner (cap top) sits at (pad + x_phase, pad + y_phase) screen px.
    Returns None if a glyph is missing from the font.
    """
    bm = _bitmap(text, font)
    if bm is None:
        return None
    S = SUPER
    h, w = bm.shape
    m = 3                                           # font px margin around the text
    canvas = np.zeros(((h + 2 * m) * S, (w + 2 * m) * S), np.float32)
    up = np.kron(bm.astype(np.float32), np.ones((S, S), np.float32))
    if italic:
        # top edge +1 font px, bottom edge (row 8) -1: x' = x + (1 - 0.25 * y) font px
        rows = np.arange(up.shape[0], dtype=np.float32) / S + 0.5 / S
        sheared = np.zeros_like(up)
        for r in range(up.shape[0]):
            shift = int(round((1 - 0.25 * rows[r]) * S))
            if shift >= 0:
                sheared[r, shift:] = up[r, :up.shape[1] - shift] if shift else up[r]
            else:
                sheared[r, :shift] = up[r, -shift:]
        up = sheared
    y0, x0 = m * S, m * S
    if shadow:
        canvas[y0 + S:y0 + S + up.shape[0], x0 + S:x0 + S + up.shape[1]] = np.where(up > 0, shadow_level, 0)
    region = canvas[y0:y0 + up.shape[0], x0:x0 + up.shape[1]]
    canvas[y0:y0 + up.shape[0], x0:x0 + up.shape[1]] = np.where(up > 0, 1.0, region)
    # place: text cap-top-left at (pad + phase) after scaling
    f = font_px / S
    M = np.float32([[f, 0, pad + x_phase - m * font_px], [0, f, pad + y_phase - m * font_px]])
    out_w = int(np.ceil(pad * 2 + (w + 2) * font_px))
    out_h = int(np.ceil(pad * 2 + (h + 2) * font_px))
    if f < 1:
        # area-average down to the target scale (what the recording's downscale does)
        small = cv2.resize(canvas, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        M = np.float32([[1, 0, pad + x_phase - m * font_px], [0, 1, pad + y_phase - m * font_px]])
        return cv2.warpAffine(small, M, (out_w, out_h), flags=cv2.INTER_LINEAR)
    return cv2.warpAffine(canvas, M, (out_w, out_h), flags=cv2.INTER_AREA)
