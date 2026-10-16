"""The opponent's progress and the match clock, read from MCSR's top-right panel.

MCSR Ranked draws a panel in the top-right corner of the game view:

    RTA: 11:57.554        <- cyan  \  the match clock (two copies, same value)
    RTA: 11:57.554        <- yellow/
    Current Match
    Ranked Mode
    [head] primeord       <- opponent name (white)
    [icon] Entered Bastion  <- opponent status (grey italic)

Where the panel is, how big its font is and which way it is aligned comes from
the per-video calibration (layout.json "panel": the static yellow "Current
Match" line, see layout.find_panel) - top-right right-aligned on most setups,
bottom-left left-aligned and smaller on others. The clock lines are found the
same way (layout.find_clock: coloured MM:SS.mmm text anywhere). All boxes
below are measured relative to "Current Match" in font pixels on the tuning
VOD (font px 4.5) and scaled by the measured font size.

The panel is part of the full-size game view only: in MCSR's resized strips,
on GUI screens with a dark backdrop, under the F3 text or under a third toast
it is hidden or covered. So every read carries a confidence and only
confident reads are used.

CV ideas:

1. **Status = whole-word template matching on a text mask.** The status is one
   of a handful of fixed phrases ("Started Match", "Entered Nether", ...) in
   grey *italic* text. The glyph reader (glyphs.py) can't segment italics -
   slanted letters overlap in the column projection - and we don't need to
   read arbitrary text, only to tell ~7 known phrases apart. So: threshold the
   status box to a binary mask of grey pixels that have Minecraft's dark drop
   shadow down-right (the world behind the panel varies: sand, stone, sky -
   colour + shadow keeps only the text), then compare the mask with one
   template per phrase (calibration/opponent/<status>.png, averaged masks) by
   normalised cross-correlation with a few px of slack. The template covers a
   fixed, right-aligned box including empty space left of the text, so a
   longer phrase can't match a shorter one's template.
2. **Match clock = the glyph reader.** "RTA: MM:SS.mmm" is in the same
   Minecraft font as the result-screen time, only coloured. A colour mask
   (two bright channels, one weak = cyan or yellow) replaces the white/grey
   mask; segmentation and the 5x7 digit templates in calibration/glyphs/ are
   reused unchanged. video time - clock time = the offset between the video
   and the match timer, which is constant (median of many reads, outliers
   from covered digits rejected).
3. **Opponent name = the glyph reader with letter templates** (white text,
   8-row grid for descenders), see read_name().

Timing: a status change is dated at the first confident sighting of the new
status; the true change happened at most `latency_s` earlier (the gap since
the previous confident read).

The CV pass writes opponent.csv (one row per panel read) and clock.csv (one
row per clock line read); build_opponent()/build_match_clock() turn them into
analysis.json's "opponent" / "match_clock" without any CV (rebuild-json).
"""

import csv
import re
import statistics
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from . import config
from .font import load_font
from .glyphs import keep_shadowed, load_glyph_templates, match_glyph, segment_line, text_mask
from .textsynth import SynthReader

FONT_PX_REF = 4.5              # panel font pixel of the tuning VOD; the status templates are at this size
# "RTA: MM:SS.mmm" (or a bare "MM:SS.cc" timer): two-digit minutes right after a
# label / the line start, so a glyph lost at the left edge (a covered "1" in
# "10:11") can't give a wrong time.
CLOCK_RE = re.compile(r"(?:^|[: ?])(\d{2}):(\d{2})\.(\d{2,3})$")
OPPONENT_FIELDS = ["time_s", "status", "score", "margin", "name"]
CLOCK_FIELDS = ["time_s", "line", "text", "clock_ms"]


def status_mask(crop, font_px=FONT_PX_REF):
    """Grey, drop-shadowed text pixels of a BGR crop -> float32 0/1 mask (shadow 1 font px down-right).

    Below OPPONENT_SMALL_FONT_PX screen px per font px a stroke is narrower
    than the video's blur, so its pixels never reach the text grey: then a
    pixel counts if it is clearly lighter than the pixel one font px down-right
    (its own drop shadow) and roughly neutral.
    """
    p = crop.astype(np.int16)
    lo, hi = p.min(axis=2), p.max(axis=2)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    s = max(1, int(round(font_px)))
    if font_px < config.OPPONENT_SMALL_FONT_PX:
        g = gray.astype(np.int16)
        below = np.zeros_like(g)
        below[:-s, :-s] = g[s:, s:]
        mask = (g - below >= config.OPPONENT_SMALL_SHADOW_STEP) & (g >= config.OPPONENT_SMALL_MIN_LIGHT) & \
            (hi - lo <= config.OPPONENT_SMALL_MAX_CHROMA)
        mask[-s:, :] = False
        mask[:, -s:] = False
        return mask.astype(np.float32)
    gmin, gmax = config.OPPONENT_GREY_RANGE
    mask = (lo >= gmin) & (hi <= gmax) & (hi - lo <= config.OPPONENT_GREY_MAX_CHROMA)
    return keep_shadowed(mask, gray, s).astype(np.float32)


def colour_line_mask(crop, colour):
    """Pixels close to a clock line's measured colour (every channel within CLOCK_COLOUR_DIST)."""
    d = np.abs(crop.astype(np.int16) - np.array(colour, np.int16)).max(axis=2)
    return (d <= config.CLOCK_COLOUR_DIST) & (crop.max(axis=2) >= config.CLOCK_MIN_BRIGHT)


def clock_mask(crop):
    """Bright two-channel (cyan / yellow) text pixels of a BGR crop -> bool mask."""
    c = np.sort(crop, axis=2)                       # per pixel: weakest, middle, strongest channel
    return (c[..., 1] >= config.MATCH_CLOCK_STRONG_MIN) & (c[..., 0] <= config.MATCH_CLOCK_WEAK_MAX)


def parse_clock(text):
    """'RTA: 11:57.554' / '00:47.92' (anything before the time is ignored) -> ms or None."""
    m = CLOCK_RE.search(text)
    if not m:
        return None
    minutes, seconds, frac = m.groups()
    if int(seconds) > 59:
        return None
    return (int(minutes) * 60 + int(seconds)) * 1000 + int(frac) * (10 if len(frac) == 2 else 1)


def load_status_templates(folder=None):
    folder = folder or config.CALIBRATION_DIR / "opponent"
    templates = {}
    for path in sorted(folder.glob("*.png")) if folder.is_dir() else []:
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is not None:
            templates[path.stem] = image.astype(np.float32) / 255.0
    return templates


# Minecraft's default font: advance (glyph width + 1 px gap) in font px; everything else is 6.
FONT_ADVANCE = {"i": 2, "l": 3, "t": 4, "I": 4, "f": 5, "k": 5, " ": 4, "!": 2, ".": 2, ",": 2, ":": 2,
                ";": 2, "'": 2, "|": 2, "[": 4, "]": 4, "(": 5, ")": 5, "<": 5, ">": 5, "*": 5}


def text_width(text):
    """Width of a string in Minecraft's default font, in font px (no trailing gap)."""
    return sum(FONT_ADVANCE.get(c, 6) for c in text) - 1


def _left_aligned(template, text_x, phrase=None):
    """Move a right-aligned status template's text to start at template column text_x.

    The averaged templates hold a few pixels of the status icon left of the
    text; with the phrase known, the text starts text_width(phrase) (+1 font px
    for italics/shadow) left of its right end - everything further left is icon.
    """
    cols = np.flatnonzero(template.sum(axis=0) > 0)
    out = np.zeros_like(template)
    if len(cols) == 0:
        return out
    start = cols[0]
    if phrase:
        start = max(start, int(cols[-1] + 1 - (text_width(phrase) + 1.5) * FONT_PX_REF))
    text = template[:, start:cols[-1] + 1]
    w = min(text.shape[1], out.shape[1] - text_x)
    if w > 0:
        out[:, text_x:text_x + w] = text[:, :w]
    return out


class PanelReader:
    """Reads the status, name and the clock lines from one frame, at the layout's panel position."""

    def __init__(self, lay):
        self.lay = lay
        self.p = lay.panel if lay.panel.get("found") else None
        self.glyphs = load_glyph_templates()
        self.name_templates = name_templates(load_letter_templates(), self.glyphs)
        self.status_templates = {}
        # Small fonts give noisier text masks: a lower bar (still >= 0.10 ahead of the runner-up).
        self.min_score = config.OPPONENT_MIN_SCORE
        if self.p and self.p["font_px"] < config.OPPONENT_SMALL_FONT_PX:
            self.min_score = config.OPPONENT_MIN_SCORE_SMALL
        if self.p:
            f = self.p["font_px"]
            self.f = f
            g = config.OPPONENT_PANEL_GUI           # boxes in font px relative to "Current Match"
            edge, st, nt = self.p["edge_x"], self.p["status_top"], self.p["name_top"]
            w_out, w_in = g["box_out"] * f, g["box_in"] * f
            self.text_left = None
            if self.p["anchor"] == "right":
                bx0, bx1 = edge - w_in, edge + w_out
            elif self.p.get("status_text_x") is not None:
                # left-aligned, text start measured (layout.refine_panel): the text-at-left
                # templates start a little before it
                # template column 2 = text start; at zero slide offset it sits on status_text_x
                self.text_left = self.p["status_text_x"] - 2 * f / FONT_PX_REF
                bx0, bx1 = self.text_left, self.text_left + w_in + w_out
            else:
                # left-aligned, text start unknown: the status icon comes first and its width
                # varies, so the box reaches further right and the templates slide over it
                bx0, bx1 = edge - w_out, edge + w_in + g["left_slide"] * f
            self.status_box = (bx0, st - g["status_above"] * f, bx1, st + g["status_below"] * f)
            self.name_box = (bx0, nt - g["name_above"] * f, bx1, nt + g["name_below"] * f)
            self.name_top = g["name_above"] * f
            templates = load_status_templates()
            if self.p["anchor"] == "left":
                templates = {k: _left_aligned(t, 2, config.OPPONENT_STATUSES.get(k, ("",))[0]) for k, t in templates.items()}
            self.box_x0 = bx0
            self.status_templates = templates
        self._synth = None

    def _crop(self, frame, box, pad=0.0):
        x0, y0, x1, y1 = box
        h, w = frame.shape[:2]
        return frame[max(0, int(round(y0 - pad))):min(h, int(round(y1 + pad))),
                     max(0, int(round(x0 - pad))):min(w, int(round(x1 + pad)))]

    def status_box_patch(self, frame, pad=0):
        """Status text mask of the status box, rescaled to the templates' 4.5-px font (pad in template px)."""
        crop = self._crop(frame, self.status_box, pad * self.f / FONT_PX_REF)
        mask = status_mask(crop, self.f)
        s = FONT_PX_REF / self.f
        if abs(s - 1) > 1e-3:
            mask = cv2.resize(mask, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR if s > 1 else cv2.INTER_AREA)
        return mask

    def read_status(self, frame, with_x=False):
        """-> (status id or "", score, margin). Best template and its lead over the runner-up.

        with_x: also return the screen x where the best template's text starts.
        """
        empty = ("", 0.0, 0.0, None) if with_x else ("", 0.0, 0.0)
        if not self.status_templates:
            return empty
        pad = config.OPPONENT_STATUS_SLACK_PX
        mask = self.status_box_patch(frame, pad=pad)
        if mask.sum() < 50 * min(1.0, (self.f / FONT_PX_REF) ** 2):    # no grey text at all: panel hidden
            return empty
        scores, locs = {}, {}
        for name, template in self.status_templates.items():
            th, tw = template.shape
            if th > mask.shape[0] or tw > mask.shape[1]:
                continue
            _, scores[name], _, locs[name] = cv2.minMaxLoc(cv2.matchTemplate(mask, template, cv2.TM_CCOEFF_NORMED))
        if not scores:
            return empty
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        best, score = ranked[0]
        margin = score - (ranked[1][1] if len(ranked) > 1 else 0.0)
        if not with_x:
            return best, float(score), float(margin)
        # template column 2 = text start (left-aligned templates); box starts `pad` template px early
        x = self.box_x0 + (locs[best][0] - pad + 2) * self.f / FONT_PX_REF
        return best, float(score), float(margin), x

    def read_clock(self, frame):
        """-> {line: (raw text, ms or None)} for the clock lines in the layout (rta1, rta2)."""
        out = {}
        for i, ln in enumerate(self.lay.clock_lines, 1):
            x0, y0, x1, y1 = ln["box"]
            crop = frame[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            mask = clock_mask(crop) if ln.get("mask") == "two_channel" else colour_line_mask(crop, ln["color"])
            if mask.sum() < 30:
                continue
            _, glyphs = segment_line(mask)
            text = ""
            for g in glyphs:
                if g["gap"] >= 3:
                    text += " "
                text += match_glyph(g["grid"], self.glyphs)[0]
            if text:
                out[f"rta{i}"] = (text, parse_clock(text))
        return out

    @property
    def small_font(self):
        """Panel font too small for the glyph cutter (< OPPONENT_SMALL_FONT_PX screen px per font px)."""
        return bool(self.p) and self.f < config.OPPONENT_SMALL_FONT_PX

    def read_name(self, frame):
        if not self.p:
            return None
        return read_name(self._crop(frame, self.name_box), self.name_templates, self.f, self.name_top)

    def read_name_synth(self, frame):
        """Name by analysis-by-synthesis (textsynth.py) -> (name or None, fit). Slow (~2 s): small panels only."""
        if not self.p:
            return None, -1.0
        if self._synth is None:
            self._synth = SynthReader(load_font(), self.f)
        x0, y0, x1, y1 = self.name_box
        m = 3 * self.f                       # the estimated cap top can be off by a font px or two
        crop = self._crop(frame, (x0, y0 - m, x1, y1 + m))
        top = self.name_top + (y0 - max(0, int(round(y0 - m))))
        text, fit = self._synth.read(crop, top)
        if fit >= config.SYNTH_MIN_FIT and NAME_RE.match(text):
            return text, fit
        return None, fit

    def read(self, frame, synth_name=False):
        """One panel read. `synth_name`: on small panels, also try the (slow) synthesis name reader."""
        status, score, margin = self.read_status(frame) if self.p else ("", 0.0, 0.0)
        confident = score >= self.min_score and margin >= config.OPPONENT_MIN_MARGIN
        # The name is only read when the status is confidently visible (panel not covered).
        name = None
        if confident:
            if self.small_font:
                name = self.read_name_synth(frame)[0] if synth_name else None
            else:
                name = self.read_name(frame)
        return {"status": status, "score": score, "margin": margin, "name": name,
                "clock": self.read_clock(frame)}


# --- opponent name (letters) ---------------------------------------------------

def load_letter_templates(folder=None):
    """calibration/glyphs/letters/*.png -> {char: bool grid (8 rows)}. See the calibration README."""
    folder = folder or config.CALIBRATION_DIR / "glyphs" / "letters"
    templates = {}
    for path in sorted(folder.glob("*.png")) if folder.is_dir() else []:
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        stem = path.stem
        char = {"underscore": "_"}.get(stem, stem[-1] if stem.startswith(("lower_", "upper_")) else stem)
        templates[char] = image >= 128
    return templates


NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")     # valid Minecraft user names


def name_templates(letters, digits):
    """Letter templates (8 rows) + the 7-row digit templates padded with an empty descender row."""
    out = dict(letters)
    for char, grid in digits.items():
        if char.isdigit() and grid.shape[0] == 7:
            out.setdefault(char, np.vstack([grid, np.zeros((1, grid.shape[1]), bool)]))
    return out


def read_name(crop, templates, font_px=FONT_PX_REF, top_px=None):
    """Read the white opponent name in the name box -> str, or None if not cleanly readable.

    The name is right-aligned with the player head left of it. Text mask = white
    pixels with the drop shadow (the head icon has none and drops out); glyphs
    are cut with an 8-row band from the fixed cap-top row of the name line (so
    descenders like p/g/y/_ fit), the last word (closest to the right edge) is
    the name. Every glyph must match a template at OPPONENT_NAME_MIN_GLYPH_SCORE,
    so a letter we have no template for gives None instead of a wrong name.
    """
    if crop.size == 0:
        return None
    top_px = config.OPPONENT_NAME_TOP_PX * font_px / FONT_PX_REF if top_px is None else top_px
    mask = keep_shadowed(text_mask(crop), cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), max(1, int(round(font_px))))
    if mask.sum() < 30 * (font_px / FONT_PX_REF) ** 2:
        return None
    _, glyphs = segment_line(mask, font_px, int(round(top_px)), rows=8, min_font_px=config.OPPONENT_NAME_MIN_FONT_PX)
    word = []
    for g in glyphs:
        if g["gap"] >= 2:            # letters are 1 font px apart; a bigger gap starts a new word
            word = []
        word.append(g)
    text = ""
    for g in word:
        char, score = match_glyph(g["grid"], templates)
        if score < config.OPPONENT_NAME_MIN_GLYPH_SCORE:
            return None
        text += char
    return text if NAME_RE.match(text) else None


# --- per-sample watcher (used by analyze and the `opponent` command) -----------

class OpponentWatcher:
    def __init__(self, lay, duration_s=None):
        self.reader = PanelReader(lay)
        self.rows, self.clock_rows = [], []
        self.next_t = 0.0
        # Small panels: the synthesis name reader is slow, so it runs on at most SYNTH_NAME_READS
        # confident frames spread over the video.
        self.synth_every = max(config.OPPONENT_SAMPLE_S, (duration_s or 600.0) / config.SYNTH_NAME_READS)
        self.next_synth = 0.0

    def update(self, t, frame):
        if t < self.next_t - 1e-6:
            return
        self.next_t = t + config.OPPONENT_SAMPLE_S
        synth = self.reader.small_font and t >= self.next_synth
        r = self.reader.read(frame, synth_name=synth)
        if synth and r["score"] >= self.reader.min_score and r["margin"] >= config.OPPONENT_MIN_MARGIN:
            self.next_synth = t + self.synth_every
        # Rows store the score relative to this panel's bar, so build_opponent's fixed
        # OPPONENT_MIN_SCORE test means the same for small and large panels.
        score = r["score"] + (config.OPPONENT_MIN_SCORE - self.reader.min_score if r["score"] else 0.0)
        self.rows.append({"time_s": t, "status": r["status"], "score": score,
                          "margin": r["margin"], "name": r["name"] or ""})
        for line, (text, ms) in r["clock"].items():
            self.clock_rows.append({"time_s": t, "line": line, "text": text, "clock_ms": ms})

    def truncate(self, end_s):
        self.rows = [r for r in self.rows if r["time_s"] < end_s]
        self.clock_rows = [r for r in self.clock_rows if r["time_s"] < end_s]


# --- CSVs ------------------------------------------------------------------------

def write_opponent_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(OPPONENT_FIELDS)
        for r in rows:
            w.writerow([f"{r['time_s']:.2f}", r["status"], f"{r['score']:.3f}", f"{r['margin']:.3f}", r["name"]])


def read_opponent_csv(path):
    path = Path(path)
    if not path.is_file():
        return None
    with open(path, newline="") as f:
        return [{"time_s": float(r["time_s"]), "status": r["status"], "score": float(r["score"]),
                 "margin": float(r["margin"]), "name": r.get("name") or ""} for r in csv.DictReader(f)]


def write_clock_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CLOCK_FIELDS)
        for r in rows:
            w.writerow([f"{r['time_s']:.3f}", r["line"], r["text"], "" if r["clock_ms"] is None else r["clock_ms"]])


def read_clock_csv(path):
    path = Path(path)
    if not path.is_file():
        return None
    with open(path, newline="") as f:
        return [{"time_s": float(r["time_s"]), "line": r["line"], "text": r["text"],
                 "clock_ms": int(r["clock_ms"]) if r["clock_ms"] else None} for r in csv.DictReader(f)]


# --- building analysis.json fields (no CV) ------------------------------------------

def confident(row):
    return (row["status"] in config.OPPONENT_STATUSES and row["score"] >= config.OPPONENT_MIN_SCORE
            and row["margin"] >= config.OPPONENT_MIN_MARGIN)


def build_opponent(run, rows):
    """opponent.csv rows -> {"name", "splits", "statuses"} (or None without data)."""
    if rows is None:
        return None
    run_end = run["run_end_s"]
    reads = [r for r in rows if r["time_s"] < run_end and confident(r)]
    statuses = []                  # status changes: first confident sighting of each new status
    current, last_t = None, 0.0    # current status and time of its latest confident read
    i = 0
    while i < len(reads):
        r = reads[i]
        if r["status"] == current:
            last_t = r["time_s"]
            i += 1
            continue
        # A new status must be confirmed by the next confident read(s) (one misread != a change).
        run_ = reads[i:i + config.OPPONENT_CONFIRM_READS]
        if len(run_) < config.OPPONENT_CONFIRM_READS or any(x["status"] != r["status"] for x in run_):
            i += 1
            continue
        statuses.append({"raw": config.OPPONENT_STATUSES[r["status"]][0], "id": r["status"],
                         "t_s": round(r["time_s"], 2), "latency_s": round(r["time_s"] - last_t, 2)})
        current, last_t = r["status"], r["time_s"]
        i += 1

    splits, seen = [], set()
    for st in statuses:
        split = config.OPPONENT_STATUSES[st["id"]][1]
        if split == "overworld" and seen - {"overworld"}:
            # Back to "Started Match" after progress: the opponent reset - later splits start over.
            splits = [s for s in splits if s["name"] == "overworld"]
            seen = {"overworld"}
            continue
        if split in seen:
            continue
        seen.add(split)
        splits.append({"name": split, "t_s": st["t_s"], "raw": st["raw"],
                       "latency_s": st["latency_s"], "source": "cv"})

    names = Counter(r["name"] for r in rows if r["time_s"] < run_end and r["name"])
    name = None
    if names:
        text, count = names.most_common(1)[0]
        total = sum(names.values())
        if count >= 3 and count * 2 > total:
            name = text
    return {"name": name, "splits": splits,
            "statuses": [{"raw": s["raw"], "t_s": s["t_s"], "latency_s": s["latency_s"]} for s in statuses]}


def build_match_clock(run, rows):
    """clock.csv rows -> {"offset_s", "spread_s", "reads"} or None without data.

    offset_s = video time - match clock (median), spread_s = standard deviation
    of the accepted per-sample offsets, reads = samples used. Per sample the two
    RTA lines show the same value: if both were read they must agree (else the
    sample is dropped as a misread); one line is enough (the other may be
    covered, e.g. by an icon or a toast). Offsets further than
    MATCH_CLOCK_OUTLIER_S from the median are dropped too.
    """
    if rows is None:
        return None
    run_end = run["run_end_s"]
    per_sample = {}
    for r in rows:
        if r["clock_ms"] is not None and r["time_s"] < run_end:
            per_sample.setdefault(round(r["time_s"], 3), set()).add(r["clock_ms"])
    offsets = []
    for t, values in sorted(per_sample.items()):
        if max(values) - min(values) <= 1:          # both lines agree (or only one was read)
            offsets.append(t - min(values) / 1000)
    if not offsets:
        return {"offset_s": None, "spread_s": None, "reads": 0}
    med = statistics.median(offsets)
    inliers = [o for o in offsets if abs(o - med) <= config.MATCH_CLOCK_OUTLIER_S]
    med = statistics.median(inliers)
    spread = statistics.pstdev(inliers) if len(inliers) > 1 else 0.0
    return {"offset_s": round(med, 3), "spread_s": round(spread, 3), "reads": len(inliers)}
