"""Hotbar reader: which item (and how many) sits in each of the 9 hotbar slots.

`python -m vodreview hotbar runs/<id>` -> runs/<id>/hotbar.csv (t, slot, item,
count, score) and runs/<id>/hotbar_changes.csv (stable item changes per slot).

CV idea - template matching against the game's own textures:

1. **Where**: the hotbar is 182 x 22 GUI px at the bottom centre; slot i's
   16 x 16 icon starts at GUI (cx - 88 + 20 i, bottom - 19). layout.json gives
   the GUI scale k (screen px per GUI px), so the icon is a 16k x 16k crop,
   area-averaged down to 16 x 16 - one cell per texture pixel, whatever k is.
2. **Templates**: every item/ sprite is drawn flat, 1:1. Block items are drawn
   as 3D isometric cubes: we *render* them from the block's top/side textures
   (rotation 30/225 deg, scale 0.625 as in the vanilla `gui` display transform;
   orthographic, so each face is an affine warp of its 16 x 16 texture),
   supersampled 8x then area-averaged like the video, with per-face shading
   (config.HOTBAR_FACE_SHADE). Builtin-rendered items (beds) can't be rendered
   from textures, so their template is cut from a frame once
   (calibration/items/learned/*.png) and recoloured per wool colour.
3. **Match**: the slot's background is the hotbar texture (73% black) over the
   world, i.e. dark and flat-ish. For each template (colour C, alpha A) the
   prediction is g*A*C + (1-A)*bg (bg = mean of the observed pixels outside
   the template, capped dark; g = least-squares brightness gain, clamped) and
   the error is the mean absolute difference. Pixels under the stack count
   (white digits + shadow) and the durability bar are left out. Best error
   above a threshold, or a different item nearly as good -> unknown ("").
4. **Count**: the white stack-count digits are read with the font glyph
   reader (glyphs.py) at font size k, right-aligned at icon x = 16 (text x+11..15 for one digit).

The selected-slot frame only covers the slot border, never the icon.
Enchant glint (a moving purple sheen) is absorbed by the brightness gain /
error margin; heavy glint can make an item unknown, never a different item.
"""

import csv
import json
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

from . import config, glyphs, gui

CACHE = config.CALIBRATION_DIR / "items" / "sprites.npz"
LEARNED = config.CALIBRATION_DIR / "items" / "learned"
SS = 8                                    # supersampling for the cube renders

# block textures that are never a hotbar block item drawn as a cube
_CUBE_SKIP = ("destroy_stage", "_stage", "fire_", "water_", "lava_", "debug", "_door", "_pane", "structure_block",
              "jigsaw", "command_block", "_particle", "frosted_ice", "nether_portal", "end_portal", "end_gateway",
              "respawn_anchor_side", "piston_top", "redstone_dust", "_overlay", "_inner")
_CUBE_SKIP_SUFFIX = ("_open", "_on", "_off", "_bottom", "_top", "_side", "_front", "_end", "_back", "_sides",
                     "_side0", "_side1", "_side2", "_side3", "_side4", "_moist", "_powered", "_lit")
_FLAT_SKIP = ("_overlay", "bow_pulling", "crossbow_pulling", "crossbow_arrow", "crossbow_firework", "empty_armor_slot",
              "broken_elytra", "fishing_rod_cast", "filled_map_markings", "tipped_arrow", "spawn_egg")
RENAME = {"crossbow_standby": "crossbow"}
LEATHER_RGB = (160, 101, 64)              # default leather armour colour
WOOL = ("white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "light_gray", "cyan",
        "purple", "blue", "brown", "green", "red", "black")


# ------------------------------------------------------------------------------------
# Templates
# ------------------------------------------------------------------------------------

def _load(path):
    if not Path(path).is_file():
        return None
    im = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if im is None:
        return None
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    if im.shape[2] == 3:
        im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
    w = im.shape[1]
    if w != 16 or im.shape[0] < 16:       # only vanilla 16x16 (animated strips: first frame)
        return None
    return im[:16].astype(np.float32)


def _tint(im, rgb):
    out = im.copy()
    out[..., :3] *= np.array(rgb[::-1], np.float32) / 255.0
    return out


def render_cube(top, left, right, shade=None):
    """Isometric GUI render of a full block -> (colour 16x16x3, alpha 16x16).

    Vanilla `gui` transform: rotate x 30, y 225, scale 0.625 (a 16-px cube spans
    10 GUI px per edge), orthographic. Projected corners in GUI px: vertical
    edges 10*cos30 = 8.66 long, horizontal edges (+-7.07, 3.54).
    """
    shade = shade or config.HOTBAR_FACE_SHADE
    top_v = np.array([8.0, (16 - (8.66 + 2 * 3.54)) / 2])
    left_v, right_v = top_v + (-7.07, 3.54), top_v + (7.07, 3.54)
    front_v, down = top_v + (0.0, 7.07), np.array([0.0, 8.66])
    canvas = np.zeros((16 * SS, 16 * SS, 4), np.float32)
    faces = [(top, left_v, top_v, front_v, shade[0]),
             (left, left_v, front_v, left_v + down, shade[1]),
             (right, front_v, right_v, front_v + down, shade[2])]
    src = np.float32([[0, 0], [16, 0], [0, 16]])
    for tex, p0, p1, p2, sh in faces:
        m = cv2.getAffineTransform(src, np.float32([p0, p1, p2]) * SS)
        w = cv2.warpAffine(tex, m, (16 * SS, 16 * SS), flags=cv2.INTER_NEAREST, borderValue=(0, 0, 0, 0))
        a = (w[..., 3:] > 127).astype(np.float32)
        canvas[..., :3] = canvas[..., :3] * (1 - a) + w[..., :3] * sh * a
        canvas[..., 3:] = np.maximum(canvas[..., 3:], a)
    return _downsample(canvas)


def _downsample(rgba):
    """Area-average a premultiplied RGBA image to 16x16 -> (colour, alpha)."""
    a = rgba[..., 3] / (255.0 if rgba[..., 3].max() > 1 else 1.0)
    pre = rgba[..., :3] * a[..., None]
    small = cv2.resize(pre, (16, 16), interpolation=cv2.INTER_AREA)
    alpha = cv2.resize(a, (16, 16), interpolation=cv2.INTER_AREA)
    return small / np.maximum(alpha[..., None], 1e-3), alpha


def _flat(im):
    a = im[..., 3] / 255.0
    return im[..., :3], a


def build_templates(textures=None, verbose=True):
    """Render every item/block-item template from the texture folder -> sprites.npz (local cache)."""
    textures = Path(textures or config.ITEM_TEXTURES_DIR)
    item_dir, block_dir = textures / "item", textures / "block"
    if not item_dir.is_dir() or not block_dir.is_dir():
        raise SystemExit(f"Item textures not found in {textures} (set MCSR_TEXTURES to a 1.16 textures folder "
                         f"with item/ and block/)")
    names, cols, alphas, dcare, kinds = [], [], [], [], []

    def add(name, col, alpha, kind, dontcare=None):
        names.append(name)
        cols.append(col.astype(np.float32))
        alphas.append(alpha.astype(np.float32))
        dcare.append(np.zeros((16, 16), bool) if dontcare is None else dontcare)
        kinds.append(kind)

    # flat item sprites
    for path in sorted(item_dir.glob("*.png")):
        stem = path.stem
        if any(s in stem for s in _FLAT_SKIP):
            continue
        if stem[:-3] in ("clock", "compass") and stem[-2:].isdigit():
            if stem[-2:] != "00":
                continue
            stem = stem[:-3]
        im = _load(path)
        if im is None:
            continue
        if stem.startswith("leather_") and stem != "leather":
            im = _tint(im, LEATHER_RGB)
        overlay = item_dir / f"{path.stem}_overlay.png"
        dc = None
        if stem in ("potion", "splash_potion", "lingering_potion"):
            overlay = item_dir / "potion_overlay.png"
        if overlay.is_file():                 # tinted overlay (potion liquid, armour trim): colour unknown
            ov = _load(overlay)
            if ov is not None:
                dc = ov[..., 3] > 127
                im[..., 3] = np.maximum(im[..., 3], ov[..., 3])
        add(RENAME.get(stem, stem), *_flat(im), "item", dc)
    have = set(names)

    # 3D block items (full cubes) from block textures
    stems = {p.stem for p in block_dir.glob("*.png")}
    bases = set()
    for s in stems:
        if s.endswith(("_side", "_top")) and s.rsplit("_", 1)[0] not in stems:
            bases.add(s.rsplit("_", 1)[0])      # basalt_side/basalt_top -> basalt
        elif not any(k in s for k in _CUBE_SKIP) and not s.endswith(_CUBE_SKIP_SUFFIX):
            bases.add(s)
    for base in sorted(bases):
        if base in have or any(k in base for k in _CUBE_SKIP):
            continue
        side_name = f"{base}_side" if f"{base}_side" in stems else base
        top_name = next((n for n in (f"{base}_top", f"{base}_end") if n in stems), side_name)
        front_name = f"{base}_front" if f"{base}_front" in stems else side_name
        side, top, front = (_load(block_dir / f"{n}.png") for n in (side_name, top_name, front_name))
        if side is None or top is None or front is None:
            continue
        opaque = (side[..., 3] > 127).mean()
        if base in config.HOTBAR_TINTS:
            rgb = config.HOTBAR_TINTS[base]
            if base == "grass_block":
                top = _tint(top, rgb)
                ov = _load(block_dir / "grass_block_side_overlay.png")
                if ov is not None:
                    o = _tint(ov, rgb)
                    m = ov[..., 3:] > 127
                    side = np.where(m, o, side)
                    front = side
            else:
                side, top, front = (_tint(x, rgb) for x in (side, top, front))
        if opaque < 0.999 and not base.endswith(("_leaves", "glass", "spawner", "_wart_block")):
            # cut-out block texture (plants, torches, rails, ...): its item is the flat sprite
            add(base, *_flat(side), "block-flat")
            continue
        col, alpha = render_cube(top, front, side)
        add(base, col, alpha, "cube")

    # learned templates (builtin-rendered items) + wool recolours of the bed
    for path in sorted(LEARNED.glob("*.png")) if LEARNED.is_dir() else []:
        im = _load(path)
        if im is None:
            continue
        add(path.stem, *_flat(im), "learned")
        if path.stem == "white_bed":
            white = _load(block_dir / "white_wool.png")
            wool_px = (im[..., :3].min(axis=2) > 130) & (im[..., 3] > 127)
            for colour in WOOL[1:]:
                w = _load(block_dir / f"{colour}_wool.png")
                if w is None or white is None:
                    continue
                gain = w[..., :3].mean((0, 1)) / white[..., :3].mean((0, 1))
                v = im.copy()
                v[wool_px, :3] = np.clip(v[wool_px, :3] * gain, 0, 255)
                add(f"{colour}_bed", *_flat(v), "learned")

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, names=np.array(names), cols=np.stack(cols).astype(np.float16),
                        alphas=np.stack(alphas).astype(np.float16), dontcare=np.stack(dcare),
                        kinds=np.array(kinds), source=str(textures))
    if verbose:
        print(f"Built {len(names)} item templates ({kinds.count('cube')} rendered block cubes) -> {CACHE}")
    return CACHE


class Templates:
    """All templates as flat arrays, ready for vectorised matching."""

    def __init__(self, rebuild=False):
        if rebuild or not CACHE.is_file():
            build_templates()
        z = np.load(CACHE)
        self.names = [str(n) for n in z["names"]]
        self.kinds = [str(k) for k in z["kinds"]]
        n = len(self.names)
        self.C = z["cols"].astype(np.float32).reshape(n, 256, 3)
        self.A = z["alphas"].astype(np.float32).reshape(n, 256)
        self.D = z["dontcare"].reshape(n, 256)
        sigma = config.HOTBAR_BLUR_GUI
        if sigma > 0:                                           # blur premultiplied colour + alpha alike
            pre = (self.C * self.A[..., None]).reshape(n, 16, 16, 3)
            a = self.A.reshape(n, 16, 16)
            pre = np.stack([cv2.GaussianBlur(p, (0, 0), sigma) for p in pre]).reshape(n, 256, 3)
            self.A = np.stack([cv2.GaussianBlur(x, (0, 0), sigma) for x in a]).reshape(n, 256)
            self.C = pre / np.maximum(self.A[..., None], 1e-3)
        self.out = (self.A < 0.05).astype(np.float32)     # background pixels of each template
        self.penalty = np.array([0.0 if common(nm) else config.HOTBAR_RARE_PENALTY for nm in self.names], np.float32)
        self.glint = np.array([unstackable(nm) or nm in config.HOTBAR_GLINT_ITEMS for nm in self.names])
        # 4x4 versions for the coarse first pass
        a16 = self.A.reshape(n, 16, 16)
        pre = (self.C * self.A[..., None]).reshape(n, 16, 16, 3)
        self.A4 = np.stack([cv2.resize(x, (4, 4), interpolation=cv2.INTER_AREA) for x in a16]).reshape(n, 16)
        pre4 = np.stack([cv2.resize(x, (4, 4), interpolation=cv2.INTER_AREA) for x in pre]).reshape(n, 16, 3)
        self.C4 = pre4 / np.maximum(self.A4[..., None], 1e-3)
        self.D4 = np.stack([cv2.resize(x.astype(np.float32), (4, 4), interpolation=cv2.INTER_AREA)
                            for x in self.D.reshape(n, 16, 16)]).reshape(n, 16) > 0.5
        self.out4 = (self.A4 < 0.05).astype(np.float32)


def _block_cat(item):
    c = category(item)
    return c if c in ("flammable", "nonflammable") else ""


def unstackable(item):
    """Items that never stack (tools, beds, boats, filled buckets, potions ...): count is always 1."""
    return all(p.endswith(config.HOTBAR_UNSTACKABLE_SUFFIXES) or p in config.HOTBAR_UNSTACKABLE
               for p in item.split("|"))


def common(item):
    """Plausible in a speedrunner's hotbar (gets the tie-break bonus, see config.HOTBAR_RARE_PENALTY)."""
    return (item in config.HOTBAR_COMMON_ITEMS or item in config.KEY_ITEMS
            or item in config.HOTBAR_COMMON_TOOLS or item.endswith(config.HOTBAR_COMMON_SUFFIXES))


# ------------------------------------------------------------------------------------
# Reading one hotbar
# ------------------------------------------------------------------------------------

def slot_origin(lay, slot):
    """Screen (x, y) of slot `slot`'s (0-8) icon top-left."""
    x0, _, x1, y1 = lay.game
    return (x0 + x1) / 2 + (-88 + 20 * slot) * lay.k, y1 - 19 * lay.k


def band_rect(lay):
    """Screen rectangle of the whole 182 x 22 hotbar (x0, y0, x1, y1)."""
    x0, _, x1, y1 = lay.game
    cx, k = (x0 + x1) / 2, lay.k
    return (max(0, int(cx - 92 * k)), max(0, int(y1 - 23 * k)), min(lay.w, int(np.ceil(cx + 92 * k))),
            min(lay.h, int(np.ceil(y1))))


_BORDER_ROWS = np.array([0, 1, 2, 19, 20, 21])                 # hotbar rows outside the icons
_BORDER_V = np.array([0, 147, 93, 126, 93, 0], np.float64)      # their grey in widgets.png (slot centres)


def hotbar_present(frame, lay, off=(0, 0)):
    """Correlation of the hotbar's top/bottom border rows with the vanilla texture (~0.9 when it shows).

    Sampled at the 9 slot centres (median), rows 0-2 and 19-21 - never covered by item icons.
    samples.csv `world` also covers pre-match / loading overlays and F1 (no HUD): no hotbar there.
    """
    x0, _, x1, y1 = lay.game
    k = lay.k
    top = y1 - 22 * k - off[1]
    xs = [int(round((x0 + x1) / 2 - off[0] + (-91 + 10 + 20 * i) * k)) for i in range(9)]
    ys = [int(np.floor(top + (r + 0.5) * k)) for r in _BORDER_ROWS]
    if min(ys) < 0 or max(ys) >= frame.shape[0] or min(xs) < 0 or max(xs) >= frame.shape[1]:
        return -1.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    prof = np.median(gray[np.ix_(ys, xs)].astype(np.float64), axis=1)
    if prof[1] < config.HOTBAR_MIN_BORDER_GREY:
        return 0.0          # pattern there but darkened: the HUD behind an open inventory/container screen
    return gui._corr(prof, _BORDER_V)


def match_digit(grid, digits):
    """Best digit for a glyph grid, or "?" - looser than glyphs.match_glyph (thin 1-font-px strokes blur
    at k ~4), but the winner must clearly beat the runner-up."""
    scores = sorted(((float((t == grid).mean()), c) for c, t in digits.items() if t.shape == grid.shape),
                    reverse=True)
    if not scores or scores[0][0] < config.HOTBAR_DIGIT_MIN_SCORE:
        return "?"
    if len(scores) > 1 and scores[0][0] - scores[1][0] < config.HOTBAR_DIGIT_MIN_GAP:
        return "?"
    return scores[0][1]


def read_count(crop, k, digits):
    """Stack count from a screen-res icon crop (origin = icon top-left) -> (count or None, bbox in GUI px).

    The count is drawn right-aligned (`x + 19 - 2 - width`, `y + 9`): with 5-px digits + 1-px spacing the
    last digit always covers icon x 11-15 and a second one x 5-9, rows 9-15 (shadow +1 px). So the
    digit cells sit at known places - no segmentation needed (segmenting splits/merges blurry strokes).
    """
    ya, yb = int(round(9 * k)), int(round(17 * k)) + 1
    xb = min(crop.shape[1], int(round(17 * k)) + 1)
    region = crop[ya:yb, :xb]
    if region.shape[0] < 7 * k or region.shape[1] < 16 * k:
        return None, None
    mask = glyphs.text_mask(region, min_light=config.HOTBAR_COUNT_MIN_LIGHT)    # pure white #FFFFFF
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    mask = glyphs.keep_shadowed(mask, gray, max(1, int(round(k)))).astype(np.float32)
    h, w = int(round(7 * k)), int(round(5 * k))
    pad = int(np.ceil(k / 2))                     # the digits sit within +-half a GUI px of their nominal place
    mask = cv2.copyMakeBorder(mask, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)

    def cells(x0, dx, dy):
        xa = int(round(x0 * k)) + pad + dx
        sub = mask[pad + dy:pad + dy + h, xa:xa + w]
        return cv2.resize(sub, (5, 7), interpolation=cv2.INTER_AREA) >= 0.5

    def aligned(x0):
        """Digit cells at x0, nudged by up to half a GUI px to where they fit a digit best."""
        best = None
        for dy in range(-pad, pad + 1):
            for dx in range(-pad, pad + 1):
                g = cells(x0, dx, dy)
                sc = max((float((t == g).mean()) for t in digits.values()), default=0.0)
                if best is None or sc > best[0]:
                    best = (sc, g)
        return best[1]

    right, left = aligned(11), aligned(5)
    if right.sum() < 6:
        return None, None
    text = match_digit(right, digits)
    if left.sum() >= 6:
        text = match_digit(left, digits) + text
    if not text.isdigit() or text.startswith("0"):
        return None, None
    n = int(text)
    if not 2 <= n <= 64:
        return None, None
    return n, ((5 if n >= 10 else 11) - 0.5, 8.5, 17, 17)


def count_ink(crop, k):
    """Share of pure-white pixels in the (two-digit) stack-count box, icon x 5-16, y 9-16."""
    box = crop[int(round(9 * k)):int(round(17 * k)), int(round(5 * k)):int(round(17 * k))]
    if box.size == 0:
        return 0.0
    m = glyphs.text_mask(box, min_light=config.HOTBAR_COUNT_MIN_LIGHT)
    m = glyphs.keep_shadowed(m, cv2.cvtColor(box, cv2.COLOR_BGR2GRAY), max(1, int(round(k))))
    return float(m[:int(round(7 * k)), :int(round(11 * k))].mean())


def durability_bar(cell):
    """True if the 16x16 cell shows a durability bar (black rows 13-14 under a coloured row-13 fill)."""
    row13, row14 = cell[13, 2:15], cell[14, 2:15]
    if row14.max(axis=1).mean() > 45:
        return False
    sat = row13.max(axis=1) - row13.min(axis=1)
    return bool(sat[:3].mean() > 60 and row13[:3].max(axis=1).mean() > 90)


def _errors(O, w, C, A, D, out, penalty, glint=None):
    """Match error of every template (rows of C/A/D/out) against observed pixels O (P,3), weights w (P,)."""
    W = w[None, :] * (~D)                                       # (N,P)
    # background colour per template: mean of observed pixels outside it, capped dark
    bw = out * W
    bsum = bw.sum(1, keepdims=True)
    fallback = np.median(O[w > 0], axis=0) if (w > 0).any() else np.zeros(3, np.float32)
    bg = np.where(bsum > 0.25 * O.shape[0] / 16, (bw @ O) / np.maximum(bsum, 1e-6), fallback[None, :])
    bg = np.minimum(bg, config.HOTBAR_BG_MAX)[:, None, :]       # (N,1,3)
    A = A[..., None]
    B = (1 - A) * bg
    AC = A * C
    WAC = W[..., None] * AC
    num = (WAC * (O[None] - B)).sum((1, 2))
    den = (WAC * AC).sum((1, 2))
    g = np.clip(num / np.maximum(den, 1e-6), *config.HOTBAR_GAIN)
    pred = g[:, None, None] * AC + B
    err = (np.abs(pred - O[None]).mean(2) * W).sum(1) / np.maximum(W.sum(1), 1e-6)
    if glint is not None and glint.any():
        # Enchant glint = an additive purple sheen over the item's own pixels (its phase drifts, so it
        # can be faint): for glint-able items (tools, armour, books, potions) also try a non-negative
        # purple offset - blue/red free, green at most half of them, so stone can't brighten into iron.
        WA = (W[..., None] * A)[glint]
        d = (WA * (O[None] - pred[glint])).sum(1) / np.maximum((WA * A[glint]).sum(1), 1e-6)
        d = np.clip(d, 0, config.HOTBAR_GLINT_MAX)
        d[:, 1] = np.minimum(d[:, 1], 0.5 * np.minimum(d[:, 0], d[:, 2]))
        pg = pred[glint] + A[glint] * d[:, None, :]
        eg = (np.abs(pg - O[None]).mean(2) * W[glint]).sum(1) / np.maximum(W[glint].sum(1), 1e-6)
        err[glint] = np.minimum(err[glint], eg)
    return err + penalty


def classify(cell, weight, tpl):
    """Best template for a 16x16x3 cell -> (name, err, runner-up (another item), its err, shape IoU of the two).

    Two stages for speed: every template is scored on 4x4 averages, then the
    best config.HOTBAR_SHORTLIST are scored at full 16x16 resolution.
    """
    O4 = cv2.resize(cell, (4, 4), interpolation=cv2.INTER_AREA).reshape(16, 3)
    w4 = cv2.resize(weight, (4, 4), interpolation=cv2.INTER_AREA).reshape(16)
    coarse = _errors(O4, (w4 > 0.99).astype(np.float32), tpl.C4, tpl.A4, tpl.D4, tpl.out4, tpl.penalty, tpl.glint)
    idx = np.argsort(coarse)[:config.HOTBAR_SHORTLIST]
    err = _errors(cell.reshape(256, 3), weight.reshape(256), tpl.C[idx], tpl.A[idx], tpl.D[idx], tpl.out[idx],
                  tpl.penalty[idx], tpl.glint[idx])
    order = np.argsort(err)
    best = order[0]
    nb = tpl.names[idx[best]]
    other = next((i for i in order[1:] if tpl.names[idx[i]] != nb), None)
    if other is None:
        return nb, float(err[best]), "", 1e9, 0.0
    a, b = tpl.A[idx[best]] > 0.5, tpl.A[idx[other]] > 0.5
    iou = float((a & b).sum() / max(1, (a | b).sum()))
    return nb, float(err[best]), tpl.names[idx[other]], float(err[other]), iou


class HotbarReader:
    def __init__(self, lay, templates=None):
        self.lay = lay
        self.tpl = templates or Templates()
        self.digits = {c: g for c, g in glyphs.load_glyph_templates().items() if c.isdigit()}
        self._last = {}

    def icon(self, frame, slot, off=(0, 0)):
        """Screen-res crop + 16x16 cell of a slot's icon (frame may be a band crop starting at `off`)."""
        k = self.lay.k
        x, y = slot_origin(self.lay, slot)
        x, y = int(round(x - off[0])), int(round(y - off[1]))
        s = int(round(16 * k))
        crop = frame[y:y + int(round(19 * k)) + 1, x:x + int(round(19 * k)) + 1]
        cell = cv2.resize(np.ascontiguousarray(crop[:s, :s]), (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
        return crop, cell

    def read_slot(self, frame, slot, off=(0, 0)):
        """-> dict(item, count, score, err, alt). item "" = unknown, "air" = empty slot."""
        crop, cell = self.icon(frame, slot, off)
        count, box = read_count(crop, self.lay.k, self.digits)
        weight = np.ones((16, 16), np.float32)
        if box:
            weight[int(box[1]):, max(0, int(np.floor(box[0]))):] = 0
        ink = not box and count_ink(crop, self.lay.k) >= config.HOTBAR_COUNT_INK
        if ink:
            weight[8:, 5:] = 0                          # unreadable digits: keep them out of the item match
        if durability_bar(cell):
            weight[13:15, 2:15] = 0
        name, err, alt, alt_err, iou = classify(cell, weight, self.tpl)
        air = float(np.abs(cell - cell.reshape(-1, 3).mean(0)).mean())     # flat dark slot = empty
        if count is None and air < config.HOTBAR_EMPTY_MAX_ERR and air <= err + 1:
            return {"item": "air", "count": 0, "score": round(max(0.0, 1 - air / 50), 3), "err": round(air, 1),
                    "alt": f"air/{name}"}
        score = max(0.0, 1 - err / 50)
        ok = err <= config.HOTBAR_MAX_ERR
        if ok and alt_err - err < config.HOTBAR_MIN_MARGIN:
            # near-twins (iron/stone pickaxe, soul sand/soil, leaf types): name both, never pick one
            ok = (common(name) and common(alt) and _block_cat(name) == _block_cat(alt)
                  and err <= config.HOTBAR_TWIN_MAX_ERR and iou >= config.HOTBAR_TWIN_MIN_IOU)
            name, alt = "|".join(sorted((name, alt))), name
        n = count if count else ("" if ink and not unstackable(name) else 1)
        return {"item": name if ok else "", "count": n if ok else (count or ""),
                "score": round(score, 3), "err": round(err, 1), "alt": f"{name}/{alt}+{alt_err - err:.1f}"}

    def read(self, frame, off=(0, 0)):
        """All 9 slots. A slot whose pixels barely changed since the last read reuses that result (fast)."""
        out = []
        for i in range(9):
            crop, _ = self.icon(frame, i, off)
            small = cv2.resize(crop, (19, 19), interpolation=cv2.INTER_AREA).astype(np.float32)
            prev = self._last.get(i)
            if prev is not None and np.abs(prev[0] - small).mean() < config.HOTBAR_REUSE_DIFF:
                out.append(prev[1])
                continue
            r = self.read_slot(frame, i, off)
            self._last[i] = (small, r)
            out.append(r)
        return out


# ------------------------------------------------------------------------------------
# Whole video
# ------------------------------------------------------------------------------------

def iter_band(video_path, lay, fps, until=None):
    """Yield (t, hotbar band crop) at `fps` via ffmpeg (decodes once, converts only the band)."""
    from .remux import _tool
    x0, y0, x1, y1 = band_rect(lay)
    w, h = x1 - x0, y1 - y0
    hw = ["-hwaccel", config.HOTBAR_HWACCEL] if config.HOTBAR_HWACCEL else []
    stop = ["-t", f"{until:.2f}"] if until else []
    proc = subprocess.Popen([_tool("ffmpeg"), "-v", "error", *hw, "-i", str(video_path), *stop, "-an", "-sn",
                             "-vf", f"fps={fps},crop={w}:{h}:{x0}:{y0}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                            stdout=subprocess.PIPE)
    size = w * h * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield i / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3), (x0, y0)
            i += 1
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def _screens(out_dir):
    from .report import read_samples_csv
    s = read_samples_csv(Path(out_dir) / "samples.csv")
    return np.array([x.time for x in s]), [x.screen for x in s]


def same_item(a, b):
    """Equal labels, or twin labels sharing an item (acacia_leaves|dark_oak_leaves ~ dark_oak_leaves|oak_leaves)."""
    return a == b or bool(set(a.split("|")) & set(b.split("|")))


def stable_changes(rows, need=None):
    """Per-slot item changes that persisted `need` reads -> [(t, slot, old, new, count)].

    Unknown reads are skipped; twin labels that share an item count as the same item (no flip-flops).
    """
    need = need or config.HOTBAR_STABLE_READS
    by_slot = {}
    for r in rows:
        by_slot.setdefault(r["slot"], []).append(r)
    out = []
    for slot, rs in by_slot.items():
        cur, cand, run, first = None, None, 0, None
        for r in rs:
            item = r["item"]
            if not item:
                continue
            if cand is not None and same_item(item, cand):
                run += 1
            else:
                cand, run, first = item, 1, r
            if run == need and (cur is None or not same_item(cand, cur)):
                out.append((first["t"], slot, cur or "", cand, first["count"]))
                cur = cand
    return sorted(out, key=lambda c: (c[0], c[1]))


def hotbar_command(out_dir, video_path=None, fps=None):
    from .layout import load_layout
    started = time.time()
    out_dir = Path(out_dir)
    if video_path is None:
        local = out_dir / "video.mp4"
        video_path = local if local.is_file() else json.loads((out_dir / "run.json").read_text())["video"]
    lay = load_layout(out_dir)
    reader = HotbarReader(lay)
    times, screens = _screens(out_dir)
    fps = fps or config.HOTBAR_FPS
    rows, n_read = [], 0
    run_json = out_dir / "run.json"
    until = None
    if run_json.is_file():                       # stop shortly after the run ends (result screen etc.)
        end = json.loads(run_json.read_text()).get("run_end_s")
        until = end + 2.0 if end else None
    for t, band, off in iter_band(video_path, lay, fps, until):
        # every samples.csv row within +-HOTBAR_SCREEN_MAX_DT must be world/F3 (a GUI opening between
        # samples would otherwise give a darkened, item-less hotbar)
        lo = int(np.searchsorted(times, t - config.HOTBAR_SCREEN_MAX_DT))
        hi = int(np.searchsorted(times, t + config.HOTBAR_SCREEN_MAX_DT, side="right"))
        if hi <= lo or any(screens[j] not in config.HOTBAR_SCREENS for j in range(lo, hi)):
            continue
        if hotbar_present(band, lay, off) < config.HOTBAR_MIN_PRESENT:
            continue
        n_read += 1
        for slot, r in enumerate(reader.read(band, off)):
            rows.append({"t": round(t, 2), "slot": slot + 1, **r})
    with open(out_dir / "hotbar.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["t", "slot", "item", "count", "score"])
        for r in rows:
            wr.writerow([f"{r['t']:.1f}", r["slot"], r["item"], r["count"], f"{r['score']:.3f}"])
    changes = stable_changes(rows)
    with open(out_dir / "hotbar_changes.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["t", "slot", "from", "to", "count"])
        for c in changes:
            wr.writerow([f"{c[0]:.1f}", *c[1:]])
    took = time.time() - started
    known = sum(1 for r in rows if r["item"]) / max(1, len(rows))
    dur = times[-1] if len(times) else 0
    print(f"Read {n_read} hotbars ({known:.0%} slots identified), {len(changes)} item changes -> "
          f"{out_dir / 'hotbar.csv'}; took {took:.0f}s ({took / max(dur / 60, 1e-6):.1f}s per video minute)")


# ------------------------------------------------------------------------------------
# Categories + digest helpers
# ------------------------------------------------------------------------------------

def category(item):
    """'flammable' / 'nonflammable' building block, 'key' item, or ''. A twin label "a|b" has a category
    only when both parts share it."""
    if not item or item == "air":
        return ""
    if "|" in item:
        cats = {category(part) for part in item.split("|")}
        return cats.pop() if len(cats) == 1 else ""
    if item in config.NONFLAMMABLE_BLOCKS:
        return "nonflammable"
    if item in config.FLAMMABLE_BLOCKS or item.endswith(config.FLAMMABLE_BLOCK_SUFFIXES):
        return "flammable"
    if item in config.KEY_ITEMS or item.endswith(config.KEY_ITEM_SUFFIXES):
        return "key"
    return ""


def read_hotbar_csv(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"t": float(r["t"]), "slot": int(r["slot"]), "item": r["item"],
                         "count": int(r["count"]) if r["count"].isdigit() else 0, "score": float(r["score"])})
    return rows


def snapshot(rows, t, window=15.0):
    """Hotbar at time t -> {slot: (item, count)}: per slot the latest item read twice in a row (unknown
    reads skipped) within `window` s before t, else its latest read; count = that item's latest count."""
    out = {}
    for slot in range(1, 10):
        rs = [r for r in rows if r["slot"] == slot and t - window <= r["t"] <= t and r["item"]]
        if not rs:
            continue
        pick = rs[-1]
        for later, earlier in zip(rs[::-1], rs[-2::-1]):
            if same_item(later["item"], earlier["item"]):
                pick = later
                break
        out[slot] = (pick["item"], pick["count"])
    return out


def format_snapshot(snap):
    parts = []
    for slot in range(1, 10):
        if slot not in snap:
            parts.append(f"{slot}:?")
        elif snap[slot][0] == "air":
            parts.append(f"{slot}:–")
        else:
            item, n = snap[slot]
            parts.append(f"{slot}:{item}" + (f"×{n}" if n > 1 else ""))
    return " ".join(parts)


def block_totals(snap):
    tot = {"flammable": 0, "nonflammable": 0}
    for item, n in snap.values():
        c = category(item)
        if c in tot:
            tot[c] += max(n, 1)
    return tot
