"""Game state from the F3 debug screen: position, facing, dimension and biome over time.

Whenever the runner has F3 open (`screen == "f3"` in samples.csv), the vanilla 1.16.1
left column tells us exactly where they are:

    minecraft:the_nether FC: 0
                                                   <- empty line
    XYZ: -52.899 / 40.00000 / -269.334             <- position (3 / 5 / 3 decimals)
    Block: -53 40 -270                             <- floor(XYZ)
    Chunk: 11 8 2 in -4 2 -17                      <- Block & 15, Block >> 4
    Facing: west (Towards negative X) (115.6 / 69.3)   <- yaw / pitch
    ...
    Biome: minecraft:nether_wastes

Reading (`F3Reader`):

* **Line grid.** F3 lines are left-aligned at GUI x 2, y 2 + 9 i (i = line number), drawn
  at the GUI scale k measured for the video (layout.json) with 1 font px = 1 GUI px. Mods
  add lines, so line numbers are not fixed: each line is identified by its **prefix**
  ("XYZ:", "Block:", "Chunk:", "Facing:", "Biome:", "minecraft:...FC") - found once by
  reading the whole column, then re-checked on every frame at the cached line numbers.
* **Text mask.** Vanilla 1.16 draws each line on a translucent dark box (#505050, 56%
  opaque) and the text in #E0E0E0 without a shadow, so even over lava or a bright sky the
  background behind the text is at most ~160 grey. A text pixel = light, neutral and
  clearly brighter than its *local* background (a grey-level opening with a 2.5 font px
  square removes the 1-font-px strokes and leaves the background).
* **Glyphs.** The glyph reader (glyphs.py) with the harvested digit + letter templates
  (8-row grid) - at the four videos' k = 3.0-4.5 screen px per font px every glyph
  segments cleanly; the synthesis reader is not needed (it would be below ~2.5 px).
* **Parsing.** Strict regexes on the numbers (decimals count included, so a dropped or
  extra glyph fails); fuzzy only on words (facing direction, biome id).

Validation without hand labels (`check_reads`): the F3 lines are redundant, and the
player obeys physics, so every read can be checked against itself and its neighbours:

* `block`  - Block must equal floor(XYZ) (two independently read lines);
* `chunk`  - Chunk must equal Block & 15 / Block >> 4 (catches a digit misread the same
  way in both XYZ and Block);
* `facing` - the direction word must match the yaw (south = -45..45, west = 45..135,
  north = |yaw| >= 135, east = -135..-45) and "Towards positive/negative X/Z" the word;
* `y`      - feet height inside the world (0 - 257);
* `speed`  - within one dimension consecutive positions must be reachable (<= 15 b/s
  horizontally, 12 up, 80 down, + slack; more across F3-closed gaps). A misread is a
  short run of reads inconsistent with *both* neighbours, which agree with each other;
  a jump between two long consistent runs is an ender pearl (`teleport`, kept).

Reads that fail a position check are flagged and left out of analysis.json's
`state.points`; f3.csv keeps everything.
"""

import csv
import difflib
import math
import re
import time
from pathlib import Path

import cv2
import numpy as np

from . import config
from .dimension import _f3_word
from .glyphs import load_glyph_templates, segment_line

F3_FIELDS = ["time_s", "x", "y", "z", "bx", "by", "bz", "yaw", "pitch", "dim", "biome", "confidence", "flags",
             "facing", "towards", "chunk", "raw"]
VANILLA_OFFSETS = {"dim": -2, "block": 1, "chunk": 2, "facing": 3, "biome": 8}   # line numbers relative to XYZ
NUMERIC_KINDS = ("xyz", "block", "chunk")
NARROW_UNKNOWN = "\u00b7"                # an unreadable glyph 1-2 font px wide (a "." / ":" with a lost cell)
NUMERIC_CHARS = "0123456789-./in"         # what the number lines hold after their prefix ("in": Chunk)
PREFIXES = {"xyz": "XYZ:", "block": "Block:", "chunk": "Chunk:", "facing": "Facing:", "biome": "Biome:"}
DIRECTIONS = ("south", "west", "north", "east")          # Direction.fromRotation order (yaw 0 = south)
TOWARDS = {"south": ("positive", "Z"), "north": ("negative", "Z"), "east": ("positive", "X"),
           "west": ("negative", "X")}
# Position checks: a read failing any of these is not a valid position.
POSITION_FLAGS = ("no_xyz", "no_block", "block_mismatch", "chunk_mismatch", "y_range", "speed")
BIOMES_116 = """ocean plains desert mountains forest taiga swamp river nether_wastes the_end frozen_ocean
frozen_river snowy_tundra snowy_mountains mushroom_fields mushroom_field_shore beach desert_hills wooded_hills
taiga_hills mountain_edge jungle jungle_hills jungle_edge deep_ocean stone_shore snowy_beach birch_forest
birch_forest_hills dark_forest snowy_taiga snowy_taiga_hills giant_tree_taiga giant_tree_taiga_hills
wooded_mountains savanna savanna_plateau badlands wooded_badlands_plateau badlands_plateau small_end_islands
end_midlands end_highlands end_barrens warm_ocean lukewarm_ocean cold_ocean deep_warm_ocean deep_lukewarm_ocean
deep_cold_ocean deep_frozen_ocean the_void sunflower_plains desert_lakes gravelly_mountains flower_forest
taiga_mountains swamp_hills ice_spikes modified_jungle modified_jungle_edge tall_birch_forest tall_birch_hills
dark_forest_hills snowy_taiga_mountains giant_spruce_taiga giant_spruce_taiga_hills modified_gravelly_mountains
shattered_savanna shattered_savanna_plateau eroded_badlands modified_wooded_badlands_plateau
modified_badlands_plateau bamboo_jungle bamboo_jungle_hills soul_sand_valley crimson_forest warped_forest
basalt_deltas""".split()

# The decimal counts are fixed (x, z: 3, y: 5), so a faint "." read as a gap or as an unknown *narrow*
# glyph, and a "/" broken into one or two unknown glyphs, are unambiguous; digits must all be read
# (a wide unknown glyph where the "." should be is a lost digit: "3?00000" is 35.00000, not 3.0).
_SEP = r" ?(?:/|[?\u00b7]{1,2}) ?"
_DOT = r"[. \u00b7]"
XYZ_RE = re.compile(r"^\s*(-?\d+)" + _DOT + r"(\d{3})" + _SEP + r"(-?\d+)" + _DOT + r"(\d{5})" + _SEP +
                    r"(-?\d+)" + _DOT + r"(\d{3})$")
BLOCK_RE = re.compile(r"^\s*(-?\d+) (-?\d+) (-?\d+)$")
CHUNK_RE = re.compile(r"^\s*(\d+) (\d+) (\d+) in (-?\d+) (-?\d+) (-?\d+)$")
# Facing: anything after the pitch's decimal is ignored, and the pitch is optional - a long
# right-column line (block tags of the targeted block) can be drawn over the end of the line.
FACING_RE = re.compile(r"^\s*(\S+) \(\S+ (\S+) (\S)\)? ?\((-?\d+)[.\u00b7](\d)(?!\d)(?:" + _SEP +
                       r"(-?\d+)[.\u00b7](\d)(?!\d))?")


def f3_templates():
    """Letters (8 rows) + digits and punctuation padded to 8 rows, for the F3 lines."""
    from .opponent import load_letter_templates, name_templates
    digits = load_glyph_templates()
    out = name_templates(load_letter_templates(), digits)
    for ch, grid in digits.items():
        if not ch.isdigit() and grid.shape[0] == 7:
            out[ch] = np.vstack([grid, np.zeros((1, grid.shape[1]), bool)])
    return out


def _prefix_kind(text):
    """Which F3 line is this ("xyz", "block", ... "dim") or None. One wrong / unknown glyph is allowed."""
    for kind, p in PREFIXES.items():
        head = text[:len(p)]
        if len(head) == len(p) and sum(a == b for a, b in zip(head, p)) >= len(p) - 1 and head[-1] in ":." + NARROW_UNKNOWN:
            return kind
    if text.startswith("minecraft") and " FC" in text:
        return "dim"
    return None


def _after_colon(text):
    return text.split(":", 1)[1] if ":" in text else ""


def _body(text, kind):
    """The line after its prefix (the prefix's ':' may have been read as '?')."""
    return text[len(PREFIXES[kind]):] if text else ""


JUNK = "?.:" + NARROW_UNKNOWN


def _strip_junk(text):
    """Drop unknown glyphs at the end of a line: world pixels just right of the text box.

    Safe for the numbers: XYZ has fixed decimals, and a Block / Chunk number cut short would no
    longer agree with XYZ (the cross-checks flag it)."""
    text = text.rstrip()
    while text:
        head, _, last = text.rpartition(" ")
        if last and set(last) <= set(JUNK):
            text = head.rstrip()
        elif text[-1] in JUNK:
            text = text.rstrip(JUNK).rstrip()
        else:
            break
    return text


def _closest(word, options, min_ratio=0.75):
    best, ratio = None, 0.0
    for o in options:
        r = difflib.SequenceMatcher(None, word, o).ratio()
        if r > ratio:
            best, ratio = o, r
    return best if ratio >= min_ratio else None


def parse_lines(lines):
    """{kind: text} -> parsed fields (missing / unparsable fields are None)."""
    out = {"x": None, "y": None, "z": None, "bx": None, "by": None, "bz": None, "yaw": None, "pitch": None,
           "dim": "", "biome": "", "facing": "", "towards": "", "chunk": ""}
    m = XYZ_RE.match(_strip_junk(_body(lines.get("xyz", ""), "xyz")))
    if m:
        g = m.groups()
        out["x"], out["y"], out["z"] = (float(f"{g[i]}.{g[i + 1]}") for i in (0, 2, 4))
    m = BLOCK_RE.match(_strip_junk(_body(lines.get("block", ""), "block")))
    if m:
        out["bx"], out["by"], out["bz"] = (int(v) for v in m.groups())
    m = CHUNK_RE.match(_strip_junk(_body(lines.get("chunk", ""), "chunk")))
    if m:
        out["chunk"] = " ".join(m.groups()[:3]) + " in " + " ".join(m.groups()[3:])
    m = FACING_RE.match(_strip_junk(_body(lines.get("facing", ""), "facing")))
    if m:
        word, sign, axis, y0, y1, p0, p1 = m.groups()
        yaw, pitch = f"{y0}.{y1}", (f"{p0}.{p1}" if p0 is not None else None)
        out["facing"] = _closest(word, DIRECTIONS) or ""
        sign = _closest(sign, ("positive", "negative")) or ""
        if sign and axis in "XZ":
            out["towards"] = ("+" if sign == "positive" else "-") + axis
        out["yaw"], out["pitch"] = float(yaw), (float(pitch) if pitch is not None else None)
    biome = _after_colon(_body(lines.get("biome", ""), "biome"))
    if biome:
        out["biome"] = _closest(biome.strip(), BIOMES_116, 0.8) or ""
    if lines.get("dim"):
        out["dim"] = _f3_word(lines["dim"])
    return out


class F3Reader:
    """Reads the F3 left column of one frame at the layout's GUI scale."""

    def __init__(self, lay):
        self.k = lay.k
        self.x0, self.y0, _, self.y1 = lay.game
        self.templates = f3_templates()
        self.numeric = {c: g for c, g in self.templates.items() if c in NUMERIC_CHARS}
        self.numeric_facing = {c: g for c, g in self.templates.items() if c in "0123456789-./)"}
        self.lines = {}               # kind -> line number, from the last full scan
        self.n_lines = min(config.F3_READ_MAX_LINES, int((self.y1 - self.y0) / (9 * self.k)))
        self.kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (int(round(2.5 * self.k)) | 1,) * 2)
        self.read_s = 0.0             # time spent reading (for the report)
        self.reads = 0

    def line_mask(self, frame, i):
        """Text mask of F3 line i -> (mask, cap-top row in the mask, box-row brightness per column)
        or (None, None, None).

        The box row = the line's top box row (GUI row top-1), which never holds glyph pixels: inside
        the box it is the darkened world (<= ~160 grey even over white), outside it the world itself.
        """
        k = self.k
        top = self.y0 + (2 + 9 * i) * k
        ya, yb = int(round(top - 1 * k)), int(round(top + 8 * k))
        xa = int(round(self.x0 + 1 * k))
        xb = min(frame.shape[1], int(round(self.x0 + config.F3_READ_LINE_GUI_W * k)))
        if ya < 0 or yb > frame.shape[0]:
            return None, None, None
        crop = frame[ya:yb, xa:xb]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        box_row = np.median(gray[:max(1, int(round(0.5 * k)))], axis=0)
        bg = cv2.morphologyEx(gray, cv2.MORPH_OPEN, self.kernel).astype(np.int16)
        g = gray.astype(np.int16)
        p = crop.astype(np.int16)
        chroma = p.max(axis=2) - p.min(axis=2)
        step = np.maximum(config.F3_READ_MIN_STEP, (224 - bg) * config.F3_READ_STEP_SHARE)
        mask = (g - bg >= step) & (g >= config.F3_READ_MIN_LIGHT) & (chroma <= config.F3_READ_MAX_CHROMA)
        return mask, int(round(top - ya)), box_row

    def glyphs(self, frame, i):
        """Glyphs of F3 line i -> [(space_before, grid)] (world pixels outside the text box dropped)."""
        mask, top, box_row = self.line_mask(frame, i)
        if mask is None or mask.sum() < 10:
            return []
        _, glyphs = segment_line(mask, self.k, top, rows=8)
        out, prev = [], None
        for g in glyphs:
            if prev is not None and (g["x0"] - prev) / self.k >= config.F3_READ_BREAK_FONT_PX:
                break                                   # right-column text, not this line
            if float(np.median(box_row[g["x0"]:g["x1"]])) > config.F3_BOX_MAX_GREY:
                continue                                # outside the line's dark box: bright world, not text
            # a space is 4 font px wide (+1 px glyph gap); glyphs are 1 px apart
            out.append((prev is not None and (g["x0"] - prev) / self.k >= 2.5, g["grid"]))
            prev = g["x1"]
        return out

    def compose(self, glyphs, kind=None):
        """Glyphs -> (text, lowest glyph score). For the number lines (XYZ, Block, Chunk) the glyphs
        after the prefix are matched against digits and separators only (an S can't be there, a 5 can)."""
        n_prefix = len(PREFIXES[kind]) if kind in NUMERIC_KINDS else None
        text, low, parens = "", 1.0, 0
        for j, (space, grid) in enumerate(glyphs):
            # Facing: after its second "(" come only the yaw / pitch numbers.
            numeric = (n_prefix is not None and j >= n_prefix) or (kind == "facing" and parens >= 2)
            ch, score = self.match(grid, (self.numeric_facing if kind == "facing" else self.numeric)
                                   if numeric else self.templates,
                                   config.F3_NUMERIC_MIN_SCORE if numeric else config.GLYPH_MIN_SCORE)
            parens += ch == "("
            if ch == "?" and grid.shape[1] <= 2:
                ch = NARROW_UNKNOWN                     # can only be a narrow glyph (. : i ...)
            text += (" " if space else "") + ch
            low = min(low, score)
        return text, low

    def read_line(self, frame, i, kind=None):
        """Read F3 line i -> (text, lowest glyph score)."""
        return self.compose(self.glyphs(frame, i), kind)

    def match(self, grid, templates, min_score):
        """Best template; a 1-2 font px wide glyph (: . i l ...) may miss one cell if no other
        template comes close (one cell is already 1/8 of it)."""
        scores = sorted(((float((t == grid).mean()), c) for c, t in templates.items() if t.shape == grid.shape),
                        reverse=True)
        if not scores:
            return "?", 0.0
        best, ch = scores[0]
        if best >= min_score:
            return ch, best
        if grid.shape[1] <= 2 and best >= config.F3_NARROW_MIN_SCORE and \
                (len(scores) == 1 or best - scores[1][0] >= config.F3_NARROW_MIN_MARGIN):
            return ch, best
        return "?", best

    def _scan(self, frame):
        """Read the whole column and locate every known line by its prefix."""
        found, texts = {}, {}
        for i in range(self.n_lines):
            glyphs = self.glyphs(frame, i)
            text, score = self.compose(glyphs)
            kind = _prefix_kind(text)
            if kind and kind not in found:
                found[kind] = i
                texts[kind] = self.compose(glyphs, kind)
        return found, texts

    def read(self, t, frame):
        """One F3 frame -> a row dict (F3_FIELDS; flags are filled in by check_reads)."""
        started = time.perf_counter()
        texts = {}
        if "xyz" in self.lines:
            for kind, i in self.lines.items():
                text, score = self.read_line(frame, i, kind)
                if _prefix_kind(text) == kind:
                    texts[kind] = (text, score)
        if "xyz" not in texts:
            found, texts = self._scan(frame)
            if "xyz" in found:
                # Lines not recognised on this frame: vanilla order around XYZ.
                for kind, off in VANILLA_OFFSETS.items():
                    found.setdefault(kind, found["xyz"] + off)
                self.lines = found
        parsed = parse_lines({kind: text for kind, (text, _) in texts.items()})
        conf = min((texts[k][1] for k in ("xyz", "block") if k in texts), default=0.0)
        row = {"time_s": round(t, 2), **parsed, "confidence": round(conf, 3), "flags": "",
               "raw": " | ".join(texts[k][0] for k in ("xyz", "block", "chunk") if k in texts)}
        self.read_s += time.perf_counter() - started
        self.reads += 1
        return row


# --- validation -------------------------------------------------------------------------------

def facing_ok(row):
    """Direction word vs yaw, 'Towards' vs word, angle ranges. None if not read."""
    yaw, pitch, word = row.get("yaw"), row.get("pitch"), row.get("facing")
    if yaw is None or not word:
        return None
    if not (-180.0 <= yaw <= 180.0 and (pitch is None or -90.0 <= pitch <= 90.0)):
        return False
    # Direction.fromRotation: floor(yaw / 90 + 0.5) & 3 -> south, west, north, east. The shown yaw is
    # rounded to 0.1, so a value on a boundary may belong to either side.
    ok_words = {DIRECTIONS[math.floor((yaw + d) / 90.0 + 0.5) & 3] for d in (-0.05, 0.0, 0.05)}
    if word not in ok_words:
        return False
    sign, axis = TOWARDS[word]
    return row.get("towards") in ("", ("+" if sign == "positive" else "-") + axis)


def block_ok(row):
    """Block = floor(XYZ). XYZ is shown rounded (x/z 3, y 5 decimals), so 11.9999 shows as "12.000" with
    Block 11: the shown value may sit up to half a last digit above Block + 1."""
    return all(0 <= row[c] - row["b" + c] <= 1 + tol
               for c, tol in (("x", 0.0005), ("y", 0.000005), ("z", 0.0005)))


def chunk_ok(row):
    if not row.get("chunk") or row.get("bx") is None:
        return None
    b = (row["bx"], row["by"], row["bz"])
    want = " ".join(str(v & 15) for v in b) + " in " + " ".join(str(v >> 4) for v in b)
    return row["chunk"] == want


def _static_flags(row):
    flags = []
    if row.get("x") is None:
        return ["no_xyz"]
    if row.get("bx") is None:
        flags.append("no_block")
    elif not block_ok(row):
        flags.append("block_mismatch")
    if chunk_ok(row) is False:
        flags.append("chunk_mismatch")
    lo, hi = config.F3_Y_RANGE
    if not lo <= row["y"] <= hi:
        flags.append("y_range")
    if facing_ok(row) is False:
        flags.append("facing_mismatch")
    return flags


def plausible(a, b):
    """Can the player get from read a to read b (same dimension) by walking / falling?"""
    dt = max(1e-3, b["time_s"] - a["time_s"])
    c = config
    extra = c.F3_GAP_ALLOWANCE if dt > c.F3_SEGMENT_GAP_S else 0.0
    dh = math.hypot(b["x"] - a["x"], b["z"] - a["z"])
    dv = b["y"] - a["y"]
    return (dh <= c.F3_MAX_H_SPEED * dt + c.F3_SLACK_BLOCKS + extra and
            -(c.F3_MAX_FALL_SPEED * dt + c.F3_SLACK_BLOCKS + extra) <= dv <=
            c.F3_MAX_UP_SPEED * dt + c.F3_SLACK_BLOCKS + extra)


def _segments(rows):
    """Chain reads into runs of mutually plausible ones -> [[rows], ...] with each run's start break
    ("start" = new dimension / long gap, nothing to compare; "jump" = implausible move)."""
    segs = []
    for r in rows:
        if not segs:
            segs.append({"rows": [r], "start": "start"})
            continue
        last = segs[-1]["rows"][-1]
        if r["dim"] != last["dim"] or r["time_s"] - last["time_s"] > config.F3_MAX_CHAIN_GAP_S:
            segs.append({"rows": [r], "start": "start"})
        elif plausible(last, r):
            segs[-1]["rows"].append(r)
        else:
            segs.append({"rows": [r], "start": "jump"})
    return segs


def _speed_outliers(rows):
    """Mark misreads among position-checked reads (in place: row["_speed"] = True); return teleports."""
    for _ in range(5):
        live = [r for r in rows if not r.get("_speed")]
        segs = _segments(live)
        changed = False
        for i, seg in enumerate(segs):
            n = len(seg["rows"])
            if n >= config.F3_MIN_SEGMENT:
                continue
            after = segs[i + 1]["start"] if i + 1 < len(segs) else "start"
            before = seg["start"]
            if before == "start" and after == "start":
                continue                  # alone in its dimension / time window: nothing to compare with
            # Short run with an implausible move on at least one side: a misread, unless both its
            # neighbours (across it) also disagree with each other *and* it is bounded by real context.
            prev_ok = i > 0 and before == "jump" and len(segs[i - 1]["rows"]) >= 1
            next_ok = i + 1 < len(segs) and after == "jump"
            if prev_ok and next_ok and not plausible(segs[i - 1]["rows"][-1], segs[i + 1]["rows"][0]):
                # Two jumps in a row with no agreement across: keep the run if its neighbours are
                # short too (pearl chains), drop it if both neighbours are long, consistent runs.
                if len(segs[i - 1]["rows"]) < config.F3_MIN_SEGMENT or len(segs[i + 1]["rows"]) < config.F3_MIN_SEGMENT:
                    continue
            for r in seg["rows"]:
                r["_speed"] = True
            changed = True
        if not changed:
            break
    live = [r for r in rows if not r.get("_speed")]
    teleports = []
    for seg in _segments(live):
        if seg["start"] == "jump":
            teleports.append(seg["rows"][0])
    return teleports


def check_reads(rows):
    """Fill every row's `flags` (in place) from the physics self-consistency checks."""
    rows.sort(key=lambda r: r["time_s"])
    # Dimension: carry the last read dimension over frames where its line wasn't readable.
    last_dim, last_t = "", -1e9
    for r in rows:
        r.pop("_speed", None)
        if r.get("dim"):
            last_dim, last_t = r["dim"], r["time_s"]
        elif last_dim and r["time_s"] - last_t <= config.F3_SEGMENT_GAP_S:
            r["_dim"] = last_dim
    static = {id(r): _static_flags(r) for r in rows}
    cand = []
    for r in rows:
        if not any(f in POSITION_FLAGS for f in static[id(r)]):
            cand.append(dict(r, dim=r.get("dim") or r.get("_dim", ""), _row=r))
    teleports = _speed_outliers(cand)
    for c in cand:
        if c.get("_speed"):
            static[id(c["_row"])].append("speed")
    for c in teleports:
        static[id(c["_row"])].append("teleport")
    for r in rows:
        r.pop("_dim", None)
        r["flags"] = ";".join(static[id(r)])
    return rows


def is_valid(row):
    flags = set(filter(None, (row.get("flags") or "").split(";")))
    return row.get("x") is not None and not flags & set(POSITION_FLAGS)


# --- f3.csv ------------------------------------------------------------------------------------

def _fmt(v, nd=None):
    if v is None or v == "":
        return ""
    return f"{v:.{nd}f}" if nd is not None else str(v)


def write_f3_csv(path, rows):
    check_reads(rows)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(F3_FIELDS)
        for r in rows:
            w.writerow([f"{r['time_s']:.2f}", _fmt(r["x"], 3), _fmt(r["y"], 5), _fmt(r["z"], 3),
                        _fmt(r["bx"]), _fmt(r["by"]), _fmt(r["bz"]), _fmt(r["yaw"], 1), _fmt(r["pitch"], 1),
                        r["dim"], r["biome"], f"{r['confidence']:.3f}", r["flags"], r["facing"], r["towards"],
                        r["chunk"], r["raw"] if r["flags"] and r["flags"] != "teleport" else ""])


def read_f3_csv(path):
    path = Path(path)
    if not path.is_file():
        return None

    def num(v, cast=float):
        return cast(v) if v not in ("", None) else None

    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"time_s": float(r["time_s"]), "x": num(r["x"]), "y": num(r["y"]), "z": num(r["z"]),
                         "bx": num(r["bx"], int), "by": num(r["by"], int), "bz": num(r["bz"], int),
                         "yaw": num(r["yaw"]), "pitch": num(r["pitch"]), "dim": r["dim"], "biome": r["biome"],
                         "confidence": float(r["confidence"] or 0), "flags": r["flags"], "facing": r["facing"],
                         "towards": r["towards"], "chunk": r["chunk"], "raw": r.get("raw", "")})
    return rows


# --- analysis.json "state" + cross-checks -------------------------------------------------------

CHECKS = ("block", "chunk", "facing", "y", "speed")
SPLIT_DIMS = {"overworld": "overworld", "entered_nether": "nether", "found_bastion": "nether",
              "found_fortress": "nether", "finding_stronghold": "overworld", "found_stronghold": "overworld",
              "entered_end": "end"}


def check_stats(rows):
    """Per check: reads it could be applied to and how many passed."""
    out = {c: {"checked": 0, "passed": 0} for c in CHECKS}
    for r in rows:
        flags = set(filter(None, r["flags"].split(";")))
        if r["x"] is None:
            continue
        if r["bx"] is not None:
            out["block"]["checked"] += 1
            out["block"]["passed"] += "block_mismatch" not in flags
        if chunk_ok(r) is not None:
            out["chunk"]["checked"] += 1
            out["chunk"]["passed"] += "chunk_mismatch" not in flags
        if facing_ok(r) is not None:
            out["facing"]["checked"] += 1
            out["facing"]["passed"] += "facing_mismatch" not in flags
        out["y"]["checked"] += 1
        out["y"]["passed"] += "y_range" not in flags
        if not flags & {"no_block", "block_mismatch", "chunk_mismatch", "y_range"}:
            out["speed"]["checked"] += 1
            out["speed"]["passed"] += "speed" not in flags
    return out


def portal_pairs(valid, samples, run_end):
    """Nether <-> overworld coordinate check around each portal transition (overworld = 8 x nether)."""
    from .splits import portal_transitions
    out = []
    for ev in portal_transitions(samples, run_end):
        sides = {ev.get("before"), ev.get("after")}
        if sides != {"overworld", "nether"}:
            continue
        before = [r for r in valid if r["dim"] == ev["before"] and
                  ev["start"] - config.F3_PORTAL_WINDOW_S <= r["time_s"] <= ev["start"]]
        after = [r for r in valid if r["dim"] == ev["after"] and
                 ev["t"] <= r["time_s"] <= ev["t"] + config.F3_PORTAL_WINDOW_S]
        if not before or not after:
            out.append({"t_s": ev["t"], "from": ev["before"], "to": ev["after"], "checked": False})
            continue
        a, b = before[-1], after[0]
        ow, ne = (a, b) if ev["before"] == "overworld" else (b, a)
        err = math.hypot(ow["x"] / 8 - ne["x"], ow["z"] / 8 - ne["z"])        # nether blocks
        # The reads are taken a while before / after the trip: allow for walking that far.
        dt_ow = abs(ev["t"] - ow["time_s"])
        dt_ne = abs(ev["t"] - ne["time_s"])
        allowed = config.F3_PORTAL_RADIUS + config.F3_MAX_H_SPEED * (dt_ow / 8 + dt_ne)
        out.append({"t_s": ev["t"], "from": ev["before"], "to": ev["after"], "checked": True,
                    "overworld": [round(ow["x"], 1), round(ow["z"], 1)], "nether": [round(ne["x"], 1), round(ne["z"], 1)],
                    "read_gap_s": [round(a["time_s"] - ev["start"], 1), round(b["time_s"] - ev["t"], 1)],
                    "error_nether_blocks": round(err, 1), "allowed": round(allowed, 1), "ok": err <= allowed})
    return out


def split_checks(valid, splits):
    """The valid read nearest to each split's start (within F3_SPLIT_WINDOW_S). If it lies inside the
    split, its dimension must be the split's (nether for entered nether .. found fortress, ...)."""
    out = []
    for sp in splits:
        near = [r for r in valid if abs(r["time_s"] - sp["start_s"]) <= config.F3_SPLIT_WINDOW_S]
        if not near:
            out.append({"split": sp["name"], "t_s": sp["start_s"], "read_t_s": None})
            continue
        r = min(near, key=lambda r: abs(r["time_s"] - sp["start_s"]))
        inside = sp["start_s"] <= r["time_s"] < sp["end_s"]
        want = SPLIT_DIMS.get(sp["name"]) if inside else None
        out.append({"split": sp["name"], "t_s": sp["start_s"], "read_t_s": r["time_s"],
                    "pos": [round(r["x"], 1), round(r["y"], 1), round(r["z"], 1)], "dim": r["dim"],
                    "expected_dim": want, "ok": (r["dim"] == want) if r["dim"] and want else None})
    return out


def dimension_agreement(rows, samples):
    """F3-read dimension vs the per-sample dimension label in samples.csv (dimension.py)."""
    by_t = {round(s.time, 2): s for s in samples}
    agree = total = 0
    for r in rows:
        s = by_t.get(round(r["time_s"], 2))
        if s is None or not r["dim"] or not s.dimension:
            continue
        total += 1
        agree += s.dimension == r["dim"]
    return {"compared": total, "agree": agree}


def build_state(rows, run=None, samples=None, splits=None):
    """f3.csv rows -> analysis.json "state" (None when the run has no f3.csv)."""
    if rows is None:
        return None
    check_reads(rows)
    valid = [r for r in rows if is_valid(r)]
    points, last = [], -1e9
    min_dt = 1.0 / config.F3_POINTS_PER_S - 1e-6
    for r in valid:
        if r["time_s"] - last < min_dt:
            continue
        last = r["time_s"]
        good_facing = "facing_mismatch" not in r["flags"]
        points.append({"t_s": round(r["time_s"], 2), "x": round(r["x"], 2), "y": round(r["y"], 2),
                       "z": round(r["z"], 2),
                       "yaw": r["yaw"] if good_facing else None, "pitch": r["pitch"] if good_facing else None,
                       "dim": r["dim"] or None, "biome": r["biome"] or None,
                       **({"teleport": True} if "teleport" in r["flags"] else {})})
    state = {"source": "f3", "reads": len(rows), "valid": len(valid), "points": points,
             "checks": check_stats(rows)}
    if samples is not None and run is not None:
        state["portal_pairs"] = portal_pairs(valid, samples, run["run_end_s"])
        state["dimension_agreement"] = dimension_agreement(rows, samples)
    if splits is not None:
        state["at_splits"] = split_checks(valid, splits)
    return state


def print_state(state, read_s=None, reads=None):
    if not state:
        print("\n=== F3 state: no f3.csv ===")
        return
    print(f"\n=== F3 state: {state['valid']}/{state['reads']} reads valid, {len(state['points'])} points ===")
    for name, c in state["checks"].items():
        rate = 100 * c["passed"] / c["checked"] if c["checked"] else float("nan")
        print(f"  check {name:<7} {c['passed']:5d}/{c['checked']:<5d} pass ({rate:5.1f}%)")
    if read_s is not None and reads:
        print(f"  read time: {1000 * read_s / reads:.1f} ms per F3 frame ({reads} frames)")
    da = state.get("dimension_agreement")
    if da:
        print(f"  F3 dimension vs samples.csv label: {da['agree']}/{da['compared']} agree")
    for p in state.get("portal_pairs", []):
        if not p["checked"]:
            print(f"  portal {p['t_s']:7.1f}s {p['from']}->{p['to']}: no reads on both sides")
        else:
            print(f"  portal {p['t_s']:7.1f}s {p['from']}->{p['to']}: overworld {p['overworld']} / 8 vs nether "
                  f"{p['nether']} -> off by {p['error_nether_blocks']} nether blocks (allowed {p['allowed']}, "
                  f"reads {p['read_gap_s'][0]}s / +{p['read_gap_s'][1]}s) {'ok' if p['ok'] else 'FAIL'}")
    for s in state.get("at_splits", []):
        if s.get("read_t_s") is None:
            print(f"  split {s['split']:<19} {s['t_s']:7.1f}s: no F3 read within {config.F3_SPLIT_WINDOW_S:.0f} s")
        else:
            ok = {True: "dim ok", False: "WRONG DIM", None: "(before the split)"}[s["ok"]]
            print(f"  split {s['split']:<19} {s['t_s']:7.1f}s: read at {s['read_t_s']:.1f}s {s['dim'] or '?':<9} "
                  f"pos {s['pos']} {ok}")


# --- `python -m vodreview f3 <run>`: re-read only the F3 samples --------------------------------

def reread(video_path, lay, times):
    """Read the F3 frames at the given sample times, seeking to each F3 stretch (no full decode)."""
    from .video import open_video
    reader = F3Reader(lay)
    cap = open_video(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    rows, pos = [], None
    stretches, cur = [], []
    for t in sorted(times):
        if cur and t - cur[-1] > config.F3_SEGMENT_GAP_S:
            stretches.append(cur)
            cur = []
        cur.append(t)
    if cur:
        stretches.append(cur)
    try:
        for n, stretch in enumerate(stretches):
            first = int(round(stretch[0] * fps))
            if pos is None or first < pos or first - pos > 4 * fps:
                cap.set(cv2.CAP_PROP_POS_FRAMES, first)
                pos = first
            for t in stretch:
                idx = int(round(t * fps))
                while pos < idx and cap.grab():
                    pos += 1
                ok, frame = cap.read()
                if not ok:
                    break
                pos += 1
                rows.append(reader.read(t, frame))
            if n % 20 == 0:
                print(f"  ... stretch {n + 1}/{len(stretches)} ({len(rows)} reads)", flush=True)
    finally:
        cap.release()
    return rows, reader
