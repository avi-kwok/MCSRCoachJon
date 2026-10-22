"""Bastion rampart reader v0 (bridge bastion first): is each rampart TRIPLE or SINGLE?

Domain (learner, ranked player)
-------------------------------
A bridge bastion has a central gold "chalice" and two ramparts. LEFT / RIGHT are
defined standing at the chalice FACING the ramparts. Each rampart is TRIPLE or
SINGLE, and a triple is exactly 10 blocks TALLER than a single (absolute y varies
per world). Interior cue: a triple's room has a double chest ("Large Chest") and a
single chest; a single's room has one chest. A rampart is KNOWN once the player
could see its height clearly, or entered its room.

Three independent readers, each allowed to say "unknown":

1. feasibility()   - pure geometry: how many screen pixels do 10 blocks span at
                     distance d, and how much of the colour survives the nether fog.
2. f3_labels()     - free labels from the F3 position track: the chalice is the first
                     long stop after the "Those Were the Days" toast; the ramparts are
                     the later long stops away from it. Their y relative to each other
                     (10-block rule) and the chest GUI the player opens there ("Large
                     Chest" = 222 GUI px tall panel) give the type; the chalice ->
                     ramparts direction gives the world orientation of left / right.
3. visual_reader() - exterior: during the approach, segment the dark grey bastion
                     palette, find tower-shaped blobs whose TOP is really visible, and
                     compare two towers' tops in the SAME frame. Relative heights cancel
                     most of the unknown distance; the tower's own width is the ruler.

Camera geometry used throughout (pinhole camera, the standard CV model):
  a point that is `h` blocks above the eye and `d` blocks in front of it appears
  `h * f / d` pixels above the screen centre, where the focal length in pixels is
      f = (screen_height / 2) / tan(vertical_fov / 2).
  So a 10-block height difference at distance d spans 10 * f / d pixels.

Run:  python -m vodreview.bastion <run-id> [<run-id> ...]
Writes runs/<id>/bastion.csv, runs/<id>/bastion.json, runs/<id>/bastion_evidence/*.png
(approach_sheet.png, approach_zoom.png, view_*.png) and bastion_evidence/approach/ (+ manifest.csv)
"""

import csv
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from . import config
from .f3 import read_f3_csv
from .layout import load_layout

RUNS = Path(__file__).resolve().parent.parent / "runs"

# Approach window / chalice arrival / contact sheet (kept here, not in config.py)
PROFILE_FPS = 2.0                  # coarse pass over the nether leg that finds the approach window
GOLD_HSV = ((20, 120, 150), (32, 255, 255))   # gold block: OpenCV hue 20-32, saturated, bright (lava is hue < 20)
GOLD_MIN_FRAC = 0.05               # >= 5% of the game view is gold block ...
SUSTAIN_N, SUSTAIN_OF = 3, 4       # ... in 3 of 4 consecutive profile samples (~1.5 s) = standing at the chalice
VIS_MIN_FRAC = 0.10                # bastion palette in >= 10% of the upper half of the view, sustained the same way
CHALICE_SEARCH = (-20.0, 120.0)    # chalice searched from toast - 20 s to toast + 120 s
APPROACH_PRE_VIS_S = 10.0          # window starts 10 s before first sustained bastion palette ...
APPROACH_PRE_TOAST_S = 45.0        # ... or 45 s before the toast, whichever is earlier (never before nether entry)
APPROACH_POST_CHALICE_S = 15.0     # and ends 15 s after chalice arrival (look-around while mining = route start)
APPROACH_NO_CHALICE_S = 20.0       # no chalice cue: end at toast + 20 s
SHEET_COLS, SHEET_ROWS = 4, 4      # contact sheet: 16 thumbnails ...
THUMB = (320, 180)                 # ... of 320x180 + an 18 px label strip -> 1280x792 (~1.35k image tokens)
LABEL_H = 18
ZOOM = (640, 360)                  # zoom sheet: best 4 frames, 2x2 -> 1280x760
DATASET_SIZE = (640, 360)          # per-thumbnail PNGs saved for the future rampart classifier


# =====================================================================================
# 1. Feasibility: pixels per 10 blocks vs distance, and fog
# =====================================================================================

def focal_px(height_px, vfov_deg):
    """Pinhole focal length in pixels: half the screen height / tan(half the vertical FOV)."""
    return (height_px / 2) / math.tan(math.radians(vfov_deg) / 2)


def fog_fraction(d, render_chunks=config.BASTION_RENDER_CHUNKS):
    """Share of a pixel's colour replaced by fog at distance d (1.16.1 nether "thick fog").

    Vanilla 1.16.1 uses linear fog in the nether: it starts at 5% of the view distance
    and is complete at min(view distance, 192) / 2 blocks (96 blocks at >= 12 chunks).
    Beyond fog end everything is the flat fog colour - no structure can be seen at all.
    """
    view = render_chunks * 16.0
    start, end = 0.05 * view, min(view, 192.0) * 0.5
    return float(np.clip((d - start) / (end - start), 0.0, 1.0))


def feasibility(height_px, vfovs=None):
    vfovs = vfovs or config.BASTION_VFOVS_DEG
    rows = []
    for d in config.BASTION_FEAS_DISTANCES:
        row = {"d": d, "fog": round(fog_fraction(d), 2)}
        for name, fov in vfovs.items():
            row[f"px10_{name}"] = round(10 * focal_px(height_px, fov) / d, 1)
        rows.append(row)
    return rows


# =====================================================================================
# Shared helpers
# =====================================================================================

def _split(analysis, name):
    for s in analysis.get("splits", []):
        if s["name"] == name:
            return s
    return None


def _screens(run_dir):
    """samples.csv -> (sorted times array, screens list) for nearest-sample lookups."""
    ts, sc = [], []
    with open(run_dir / "samples.csv", newline="") as f:
        for r in csv.DictReader(f):
            ts.append(float(r["time_s"]))
            sc.append(r["screen"])
    return np.array(ts), sc


def _screen_at(times, screens, t):
    i = int(np.clip(np.searchsorted(times, t), 1, len(times) - 1))
    i = i if abs(times[i] - t) < abs(times[i - 1] - t) else i - 1
    return screens[i]


def _f3_at(rows, t, max_dt=0.6):
    """Nearest valid nether F3 row within max_dt seconds (or None)."""
    best = None
    for r in rows:
        dt = abs(r["time_s"] - t)
        if dt <= max_dt and (best is None or dt < abs(best["time_s"] - t)):
            best = r
    return best


# =====================================================================================
# 0. Approach window + chalice arrival (works without F3)
# =====================================================================================

def clock_offset(run_dir):
    """video time = in-game RTA + offset (layout.json clock line), or None if the clock was not read."""
    try:
        lay = json.loads((run_dir / "layout.json").read_text())
        return ((lay.get("clock") or {}).get("lines") or [{}])[0].get("offset_s")
    except (OSError, ValueError, IndexError):
        return None


def profile_nether(run_dir, analysis, lay, video):
    """2 fps pass over nether entry -> toast + 120 s: per sample (t, screen, gold, palette_up).
    gold = share of the game view that is gold-block coloured; palette_up = share of the upper half
    that is bastion palette (structure_mask)."""
    fb = _split(analysis, "found_bastion")
    ne = _split(analysis, "entered_nether")
    if not fb:
        return []
    t0 = ne["start_s"] if ne and ne["start_s"] < fb["start_s"] else fb["start_s"] - 60
    t1 = min(fb["start_s"] + CHALICE_SEARCH[1], fb["end_s"])
    times, screens = _screens(run_dir)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    step = max(1, round(fps / PROFILE_FPS))
    idx = int(t0 * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    gx0, gy0, gx1, gy1 = (int(v) for v in lay.game)
    SW, SH = config.BASTION_WORK_SIZE
    valid_cache, out = {}, []
    while idx <= t1 * fps:
        if idx % step:
            idx += 1
            if not cap.grab():
                break
            continue
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        idx += 1
        screen = _screen_at(times, screens, t)
        if screen not in ("world", "f3"):
            out.append((round(t, 2), screen, 0.0, 0.0))
            continue
        small = cv2.resize(frame[gy0:gy1, gx0:gx1], (SW, SH), interpolation=cv2.INTER_AREA)
        if screen not in valid_cache:
            valid_cache[screen] = _valid_mask(lay, screen, (SW, SH))
        valid = valid_cache[screen]
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        gold = float((cv2.inRange(hsv, *GOLD_HSV).astype(bool) & (valid > 0)).mean())
        up = float((structure_mask(small) & valid)[:SH // 2].mean())
        out.append((round(t, 2), screen, round(gold, 4), round(up, 4)))
    cap.release()
    return out


def _first_sustained(prof, col, thr, t_from, t_to):
    """First sample time where `col` >= thr in SUSTAIN_N of SUSTAIN_OF consecutive samples."""
    sel = [p for p in prof if t_from <= p[0] <= t_to]
    for i in range(len(sel) - SUSTAIN_OF + 1):
        win = sel[i:i + SUSTAIN_OF]
        if sum(p[col] >= thr for p in win) >= SUSTAIN_N:
            return next(p[0] for p in win if p[col] >= thr)
    return None


def _hotbar_gold_block(run_dir, t_from, t_to):
    """First time a gold block enters the hotbar (hotbar_changes.csv), a cross-check only."""
    path = run_dir / "hotbar_changes.csv"
    if not path.is_file():
        return None
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if t_from <= float(r["t"]) <= t_to and r["to"] == "gold_block":
                return float(r["t"])
    return None


def approach_window(run_dir, analysis, prof, f3_chalice_t=None):
    """Approach window = first bastion sighting -> chalice arrival (+ route start).

    Chalice arrival, in order of trust:
      1. "gold": the first time gold-block colour fills >= 5% of the game view for ~1.5 s
         (3 of 4 samples at 2 fps). In a bridge bastion the chalice top is solid gold blocks,
         so standing on it / mining it floods the view with gold; while approaching, the gold
         is a small speck far away. No F3 needed.
      2. "f3_stop": the first long F3 stop after the toast (old method; wrong when F3 was
         opened late, e.g. vod-review stop at 7:50 vs gold at ~5:58).
      3. "hotbar_gold_block": the first gold block entering the hotbar, minus 3 s.
    """
    fb = _split(analysis, "found_bastion")
    ne = _split(analysis, "entered_nether")
    toast = fb["start_s"]
    nether = ne["start_s"] if ne and ne["start_s"] < toast else max(0.0, toast - 60)
    lo, hi = toast + CHALICE_SEARCH[0], toast + CHALICE_SEARCH[1]
    gold_t = _first_sustained(prof, 2, GOLD_MIN_FRAC, max(lo, nether), hi)
    hot_t = _hotbar_gold_block(run_dir, lo, hi)
    if gold_t is not None:
        chal, method = gold_t, "gold"
    elif f3_chalice_t is not None:
        chal, method = f3_chalice_t, "f3_stop"
    elif hot_t is not None:
        chal, method = hot_t - 3.0, "hotbar_gold_block"
    else:
        chal, method = None, "unknown"
    vis_t = _first_sustained(prof, 3, VIS_MIN_FRAC, nether + 1.0, chal if chal else toast + 20)
    start = min(toast - APPROACH_PRE_TOAST_S, (vis_t - APPROACH_PRE_VIS_S) if vis_t else toast)
    start = max(nether, start)
    end = chal + APPROACH_POST_CHALICE_S if chal is not None else toast + APPROACH_NO_CHALICE_S
    return {"t0": round(start, 1), "t1": round(end, 1), "nether_entry": round(nether, 1),
            "toast": round(toast, 1), "first_palette": vis_t,
            "chalice": {"t": None if chal is None else round(chal, 1), "method": method,
                        "gold_t": gold_t, "f3_stop_t": f3_chalice_t, "hotbar_gold_block_t": hot_t}}


# =====================================================================================
# 2a. Chest GUI reader (interior cue): large chest / single chest / player inventory
# =====================================================================================

def container_kind(frame, lay):
    """-> "large_chest" | "chest" | "inventory" | None for a frame showing a GUI screen.

    Every container GUI is a light-grey panel (RGB ~198) centred on screen. Its height in
    GUI pixels tells the kind: a large (double) chest is 222 GUI px tall, a single chest
    and the player inventory 166. The player inventory has the black player-portrait box
    in its top-left quarter; a chest has grey item slots there instead.
    """
    k = lay.k
    grey = cv2.inRange(frame, (188, 188, 188), (208, 208, 208))
    n, _, stats, _ = cv2.connectedComponentsWithStats(grey, connectivity=4)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = stats[i, :4]
    gw, gh = w / k, h / k
    if not 150 <= gw <= 200:                 # the panel is 176 GUI px wide
        return None
    if 205 <= gh <= 240:
        return "large_chest"
    if 150 <= gh < 190:
        # portrait box: GUI x 26..75, y 8..78 inside the panel; mostly black in the inventory
        px = frame[int(y + 10 * k):int(y + 76 * k), int(x + 28 * k):int(x + 73 * k)]
        dark = (px.max(axis=2) < 40).mean() if px.size else 0
        return "inventory" if dark > 0.25 else "chest"
    return None


# =====================================================================================
# 2b. Free labels from F3 positions
# =====================================================================================

def _stops(rows, t0, t1, min_s, radius):
    """Places the player stayed (within `radius` blocks horizontally) for >= min_s seconds."""
    out, cur = [], []
    for r in rows:
        if not t0 <= r["time_s"] <= t1:
            continue
        if cur and math.hypot(r["x"] - cur[0]["x"], r["z"] - cur[0]["z"]) > radius:
            if cur[-1]["time_s"] - cur[0]["time_s"] >= min_s:
                out.append(cur)
            cur = []
        cur.append(r)
    if cur and cur[-1]["time_s"] - cur[0]["time_s"] >= min_s:
        out.append(cur)
    return [{"t0": c[0]["time_s"], "t1": c[-1]["time_s"],
             "x": float(np.median([r["x"] for r in c])), "z": float(np.median([r["z"] for r in c])),
             "y": float(np.median([r["y"] for r in c])), "y_max": max(r["y"] for r in c)} for c in out]


def f3_labels(run_dir, analysis, rows, lay, video, chalice_t=None):
    """Chalice + rampart stops from F3 -> orientation and per-rampart labels (or None).
    chalice_t (visual gold cue) pins which F3 stop is the chalice; without it, the first stop."""
    fb = _split(analysis, "found_bastion")
    if not fb or not rows:
        return None
    t_in, t_out = fb["start_s"], fb["end_s"]
    stops = _stops(rows, t_in - 5, t_out, config.BASTION_STOP_MIN_S, config.BASTION_STOP_RADIUS)
    if len(stops) < 2:
        return {"status": "no F3 coverage of the bastion visit", "stops": len(stops)}
    ci = 0                                   # the first long stop after the toast = mining the chalice
    if chalice_t is not None:
        near = [i for i, s in enumerate(stops) if s["t1"] >= chalice_t - 2 and s["t0"] <= chalice_t + 20]
        if not near:
            return {"status": f"no F3 stop at the chalice (gold cue at {chalice_t:.1f}s)", "stops": len(stops)}
        ci = near[0]
    chalice = stops[ci]
    far = [s for s in stops[ci + 1:] if math.hypot(s["x"] - chalice["x"], s["z"] - chalice["z"])
           >= config.BASTION_RAMPART_MIN_DIST]
    if not far:
        return {"status": "no rampart stops in F3", "chalice": chalice}

    # Ramparts direction ("forward" when standing at the chalice facing the ramparts):
    # the mean direction from the chalice to the rampart stops, as a horizontal unit vector.
    fx = np.mean([s["x"] - chalice["x"] for s in far])
    fz = np.mean([s["z"] - chalice["z"] for s in far])
    norm = math.hypot(fx, fz)
    fx, fz = fx / norm, fz / norm
    # Minecraft axes: +X east, +Z south, y up. Facing direction (fx, fz) -> your RIGHT hand
    # points to (-fz, fx). Check: facing south (0, 1) -> right = (-1, 0) = west. Correct.
    rx, rz = -fz, fx

    # Group stops by side: a positive projection on the right vector = right rampart.
    sides = {"left": [], "right": []}
    for s in far:
        lateral = (s["x"] - chalice["x"]) * rx + (s["z"] - chalice["z"]) * rz
        if abs(lateral) >= config.BASTION_SIDE_MIN_LATERAL:
            s["lateral"] = round(lateral, 1)
            sides["right" if lateral > 0 else "left"].append(s)

    # Interior cue: chest GUIs opened during each stop (seek a few frames in each GUI stretch)
    times, screens = _screens(run_dir)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    for side_stops in sides.values():
        for s in side_stops:
            kinds = set()
            for t in np.arange(s["t0"], s["t1"] + 0.01, 0.5):
                if _screen_at(times, screens, t) != "inventory":
                    continue
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
                ok, frame = cap.read()
                kind = container_kind(frame, lay) if ok else None
                if kind in ("large_chest", "chest"):
                    kinds.add(kind)
            s["chests"] = sorted(kinds)
    cap.release()

    labels = {}
    for side, ss in sides.items():
        if not ss:
            continue
        top = max(ss, key=lambda s: s["y"])
        labels[side] = {"y_rel_chalice": round(top["y"] - chalice["y"], 1), "t": round(top["t0"], 1),
                        "x": round(top["x"], 1), "z": round(top["z"], 1),
                        "chests": sorted({c for s in ss for c in s["chests"]})}
    # Height rule: a triple is exactly 10 blocks taller than a single.
    if "left" in labels and "right" in labels:
        dy = labels["left"]["y_rel_chalice"] - labels["right"]["y_rel_chalice"]
        if abs(dy) >= config.BASTION_DIFF_TYPE_BLOCKS:
            taller = "left" if dy > 0 else "right"
            for side in labels:
                labels[side]["height_rule"] = "triple" if side == taller else "single"
        elif abs(dy) <= config.BASTION_SAME_TYPE_BLOCKS:
            for side in labels:
                labels[side]["height_rule"] = "same_as_other"
    for side, lab in labels.items():
        rule = lab.get("height_rule")
        if "large_chest" in lab["chests"]:
            lab["type"] = "triple"             # a double chest only generates in a triple's room
        elif rule in ("triple", "single"):
            lab["type"] = rule
        else:
            lab["type"] = "unknown"
    # same-height pairs inherit a confirmed type from the other side
    if len(labels) == 2 and all(l.get("height_rule") == "same_as_other" for l in labels.values()):
        known = {l["type"] for l in labels.values()} - {"unknown"}
        if len(known) == 1:
            for lab in labels.values():
                lab["type"] = known.pop() if lab["type"] == "unknown" else lab["type"]
                known = {lab["type"]}
    return {"status": "ok", "chalice": {k: round(chalice[k], 1) for k in ("x", "y", "z", "t0", "t1")},
            "forward_xz": [round(fx, 3), round(fz, 3)], "right_xz": [round(rx, 3), round(rz, 3)],
            "forward_compass": _compass(fx, fz), "right_compass": _compass(rx, rz), "ramparts": labels}


def _compass(x, z):
    ang = math.degrees(math.atan2(x, z))     # 0 = +Z (south), 90 = +X (east)
    names = ["south (+Z)", "south-east", "east (+X)", "north-east", "north (-Z)", "north-west",
             "west (-X)", "south-west"]
    return names[int(((ang + 22.5) % 360) // 45)]


# =====================================================================================
# 3. Exterior visual reader
# =====================================================================================

def _valid_mask(lay, screen, size):
    """1 where the game world is really visible (not HUD, overlays, F3 text)."""
    w, h = size
    m = np.ones((h, w), np.uint8)
    rects = list(lay.overlay_rects()) + list(lay.hud_rects())
    if screen == "f3":
        rects += lay.f3_rects()
    for x0, y0, x1, y1 in rects:
        m[int(y0 * h):int(math.ceil(y1 * h)), int(x0 * w):int(math.ceil(x1 * w))] = 0
    return m


def structure_mask(small):
    """Bastion palette at ~480x270: blackstone / basalt / polished bricks are dark, grey
    (low saturation) and TEXTURED (brick lines). Netherrack, soul soil and crimson are
    saturated; nether fog is either saturated (soul sand valley teal) or flat (no texture).
    """
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    s, v = hsv[..., 1], hsv[..., 2].astype(np.float32)
    lo, hi = config.BASTION_STRUCT_V
    colour = (s <= config.BASTION_STRUCT_MAX_SAT) & (v >= lo) & (v <= hi)
    # local texture = standard deviation of brightness in a 5x5 window
    mu = cv2.blur(v, (5, 5))
    sd = np.sqrt(np.maximum(cv2.blur(v * v, (5, 5)) - mu * mu, 0))
    m = (colour & (sd >= config.BASTION_STRUCT_MIN_TEXTURE)).astype(np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


def find_towers(small, valid):
    """Tower-shaped structure blobs whose TOP edge is really visible.

    A top is trusted only if the rows just above it are on screen, not hidden by an
    overlay, and not structure (i.e. sky/fog/cave above the tower). A blob touching
    the top of the frame or an overlay has an unknown top -> it is not a tower here.
    """
    H, W = valid.shape
    m = structure_mask(small) & valid
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    hsv_v = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[..., 2].astype(np.float32)
    towers = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if h < config.BASTION_TOWER_MIN_H * H or w < config.BASTION_TOWER_MIN_W * W:
            continue
        if area < 0.35 * w * h or h < 0.8 * w:          # filled and upright
            continue
        cols = range(x + w // 5, x + w - w // 5)        # middle 60% of the columns
        tops = []
        for c in cols:
            rr = np.flatnonzero(lab[:, c] == i)
            if rr.size:
                tops.append(rr[0])
        if not tops:
            continue
        top = int(np.percentile(tops, 20))
        gap = config.BASTION_TOP_CLEAR_PX
        if top < gap + 1:
            continue                                     # clipped by the frame top
        above = slice(top - gap, top)
        band = valid[above, x:x + w]
        if band.size == 0 or band.mean() < 0.9:
            continue                                     # an overlay sits on the top edge
        if m[above, x:x + w].mean() > 0.3:
            continue                                     # structure continues above -> not the top
        # fog contrast: brightness/saturation difference tower vs. the band above its top
        inside = hsv_v[top + 2:top + 2 + gap, x:x + w]
        contrast = abs(float(np.median(hsv_v[above, x:x + w])) - float(np.median(inside)))
        towers.append({"x": int(x), "w": int(w), "top": top, "bottom": int(y + h), "h": int(h),
                       "cx": x + w / 2, "contrast": round(contrast, 1)})
    return towers


def _screen_left_is_left(yaw, forward_xz):
    """With F3: is the player facing roughly the same way as chalice -> ramparts?
    Then the screen-left tower is the LEFT rampart; facing the opposite way flips it."""
    if yaw is None or forward_xz is None:
        return None
    # Minecraft yaw: 0 = +Z (south), 90 = -X (west). Facing vector = (-sin(yaw), cos(yaw)).
    fx, fz = -math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    return (fx * forward_xz[0] + fz * forward_xz[1]) >= 0


def visual_reader(run_dir, analysis, rows, lay, video, forward_xz=None, window=None):
    fb = _split(analysis, "found_bastion")
    if not fb:
        return [], [], {}
    if window:
        t0, t1 = window["t0"], window["t1"]
    else:
        t0 = max(0.0, fb["start_s"] - config.BASTION_APPROACH_BEFORE_S)
        t1 = fb["start_s"] + config.BASTION_APPROACH_AFTER_S
    times, screens = _screens(run_dir)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    step = max(1, round(fps / config.BASTION_FPS))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t0 * fps))
    idx = int(t0 * fps)
    out, frames_kept = [], []
    gx0, gy0, gx1, gy1 = (int(v) for v in lay.game)
    SW, SH = config.BASTION_WORK_SIZE
    valid_cache = {}
    start = idx
    while idx <= t1 * fps:
        if (idx - start) % step:                 # skipped frames: grab() decodes without converting
            idx += 1
            if not cap.grab():
                break
            continue
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        idx += 1
        screen = _screen_at(times, screens, t)
        if screen not in ("world", "f3"):
            continue
        game = frame[gy0:gy1, gx0:gx1]
        small = cv2.resize(game, (SW, SH), interpolation=cv2.INTER_AREA)
        if screen not in valid_cache:
            valid_cache[screen] = _valid_mask(lay, screen, (SW, SH))
        valid = valid_cache[screen]
        towers = find_towers(small, valid)
        f3 = _f3_at(rows, t) if rows else None
        sl = _screen_left_is_left(f3["yaw"] if f3 else None, forward_xz)
        res = {"left": None, "right": None}
        # need two towers clearly apart on screen to compare their tops
        if len(towers) >= 2:
            towers.sort(key=lambda tw: tw["cx"])
            a, b = towers[0], towers[-1]
            if b["cx"] - a["cx"] >= config.BASTION_PAIR_MIN_SEP * SW:
                # ruler: each tower's own on-screen width is ~BASTION_RAMPART_WIDTH_BLOCKS blocks
                bpp = config.BASTION_RAMPART_WIDTH_BLOCKS / ((a["w"] + b["w"]) / 2)
                # screen y grows downwards, so a smaller `top` = a taller tower
                d_blocks = (b["top"] - a["top"]) * bpp           # >0: screen-left tower is taller
                mapping = sl if sl is not None else True         # no F3: assume approach from the front
                map_conf = 1.0 if sl is not None else config.BASTION_NO_F3_MAP_CONF
                fog_conf = min(1.0, min(a["contrast"], b["contrast"]) / config.BASTION_GOOD_CONTRAST)
                margin = abs(d_blocks)
                if margin >= config.BASTION_DIFF_TYPE_BLOCKS:
                    type_conf = min(1.0, (margin - config.BASTION_SAME_TYPE_BLOCKS)
                                    / (config.BASTION_DIFF_TYPE_BLOCKS - config.BASTION_SAME_TYPE_BLOCKS + 3))
                    sides = {"screen_left": "triple" if d_blocks > 0 else "single",
                             "screen_right": "single" if d_blocks > 0 else "triple"}
                else:
                    type_conf, sides = 0.0, {"screen_left": "unknown", "screen_right": "unknown"}
                conf = round(type_conf * fog_conf * map_conf, 2)
                left_key, right_key = ("screen_left", "screen_right") if mapping else ("screen_right",
                                                                                      "screen_left")
                for rampart, key, tw, rel in (("left", left_key, a if mapping else b, None),
                                              ("right", right_key, b if mapping else a, None)):
                    guess = sides[key] if conf >= config.BASTION_MIN_CONF else "unknown"
                    rel_h = d_blocks if key == "screen_left" else -d_blocks
                    res[rampart] = {"tower": tw, "est_height_rel": round(rel_h, 1), "type_guess": guess,
                                    "confidence": conf}
        elif len(towers) == 1:
            pass                                                 # one tower: no relative height, unknown
        for rampart in ("left", "right"):
            r = res[rampart]
            out.append({"t": round(t, 2), "rampart": rampart, "visible": int(r is not None),
                        "est_height_rel": "" if r is None else r["est_height_rel"],
                        "type_guess": "unknown" if r is None else r["type_guess"],
                        "confidence": 0.0 if r is None else r["confidence"],
                        "towers": len(towers), "screen": screen})
        score = max([0.0] + [r["confidence"] for r in res.values() if r])
        # "how much bastion is in view above the middle line" - ranks fallback evidence frames
        area = float((structure_mask(small) & valid)[:SH // 2].mean())
        gold = float((cv2.inRange(cv2.cvtColor(small, cv2.COLOR_BGR2HSV), *GOLD_HSV).astype(bool) & (valid > 0)).mean())
        frames_kept.append((score, area, t, towers, res, screen, gold))
    cap.release()
    return out, frames_kept, {"t0": round(t0, 1), "t1": round(t1, 1)}


def summarize(rows_out):
    """KNOWN = BASTION_KNOWN_FRAMES confident frames that agree within BASTION_KNOWN_WINDOW_S."""
    summary = {}
    for rampart in ("left", "right"):
        hits = [r for r in rows_out if r["rampart"] == rampart and r["type_guess"] != "unknown"]
        summary[rampart] = {"known_at": None, "type": "unknown", "confidence": 0.0,
                            "frames_visible": sum(r["visible"] for r in rows_out if r["rampart"] == rampart)}
        for i, r in enumerate(hits):
            win = [h for h in hits[i:] if h["t"] - r["t"] <= config.BASTION_KNOWN_WINDOW_S]
            same = [h for h in win if h["type_guess"] == r["type_guess"]]
            if len(same) >= config.BASTION_KNOWN_FRAMES and len(same) == len(win):
                summary[rampart].update(known_at=same[-1]["t"], type=r["type_guess"],
                                        confidence=round(float(np.mean([h["confidence"] for h in same])), 2))
                break
    return summary


def save_evidence(run_dir, video, lay, frames_kept, n=3):
    """view_ = the n frames with the most bastion palette above the middle line, full frame, no boxes.
    (The old left_/right_ tower-pair crops are gone: the pair detector boxed the chalice, not ramparts.)"""
    ev = run_dir / "bastion_evidence"
    ev.mkdir(exist_ok=True)
    for p in ev.glob("*.png"):
        p.unlink()
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    gy1 = int(lay.game[3])
    picked = []
    for f in sorted(frames_kept, key=lambda f: f[1], reverse=True):
        if all(abs(f[2] - p[2]) >= 1.5 for p in picked):         # spread the picks in time
            picked.append(f)
        if len(picked) == n:
            break
    saved = []
    for f in picked:
        t = f[2]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, frame = cap.read()
        if not ok:
            continue
        cv2.putText(frame, f"t={t:.1f}s", (20, gy1 - 120), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 3)
        path = ev / f"view_{t:07.1f}s.png"
        cv2.imwrite(str(path), frame)
        saved.append(str(path))
    cap.release()
    return saved


def _sheet_score(f):
    """Palette weighting for sheet picks: bastion palette above the middle line (capped, so a
    wall in the face does not win) + a small bonus for tower-shaped blobs with a visible top
    - a penalty for gold-block close-ups (mining the chalice hides the ramparts)."""
    return min(f[1], 0.5) + 0.05 * min(len(f[3]), 2) - 2.0 * f[6]


def _fmt(sec):
    return "?" if sec is None else f"{'-' if sec < 0 else ''}{int(abs(sec) // 60)}:{abs(sec) % 60:04.1f}"


def _label(img, text):
    strip = np.zeros((LABEL_H, img.shape[1], 3), np.uint8)
    cv2.putText(strip, text, (4, LABEL_H - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([img, strip])


def save_approach_sheet(run_dir, video, lay, frames_kept, window, offset):
    """Contact sheet over the approach window: the window is cut into 16 equal slots and each
    slot shows its most bastion-palette-rich frame, labelled 'v<VOD time> rta <RTA>'.
    Also: approach_zoom.png (best 4 frames, larger) and approach/ (one PNG per sheet frame +
    manifest.csv) as the labelling set for the future rampart classifier."""
    ev = run_dir / "bastion_evidence"
    ev.mkdir(exist_ok=True)
    ds = ev / "approach"
    ds.mkdir(exist_ok=True)
    for p in ds.glob("*"):
        p.unlink()
    if not frames_kept:
        return []
    n = SHEET_COLS * SHEET_ROWS
    t0, t1 = window["t0"], window["t1"]
    width = (t1 - t0) / n
    picks = []
    for i in range(n):
        slot = [f for f in frames_kept if t0 + i * width <= f[2] < t0 + (i + 1) * width]
        if slot:
            picks.append((i, max(slot, key=_sheet_score)))
    zoom = []
    # zoom: distant-structure views (tower blobs, palette capped lower so walls in the face lose)
    zscore = lambda f: 0.15 * min(len(f[3]), 2) + min(f[1], 0.3) - 2.0 * f[6]
    for _, f in sorted(picks, key=lambda x: zscore(x[1]), reverse=True):
        if all(abs(f[2] - z[2]) >= 4.0 for z in zoom):
            zoom.append(f)
        if len(zoom) == 4:
            break
    zoom.sort(key=lambda f: f[2])
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    gx0, gy0, gx1, gy1 = (int(v) for v in lay.game)
    full = {}
    for f in sorted({f[2] for _, f in picks}):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(f * fps)))
        ok, frame = cap.read()
        if ok:
            full[f] = frame[gy0:gy1, gx0:gx1]
    cap.release()

    def text(t):
        return f"v{_fmt(t)}" + (f"  rta {_fmt(t - offset)}" if offset is not None else "")

    tw, th = THUMB
    sheet = np.zeros((SHEET_ROWS * (th + LABEL_H), SHEET_COLS * tw, 3), np.uint8)
    rows = []
    for i, f in picks:
        if f[2] not in full:
            continue
        img = full[f[2]]
        r, c = divmod(i, SHEET_COLS)
        sheet[r * (th + LABEL_H):(r + 1) * (th + LABEL_H), c * tw:(c + 1) * tw] = _label(
            cv2.resize(img, THUMB, interpolation=cv2.INTER_AREA), text(f[2]))
        name = f"a_{f[2]:07.2f}s.png"
        cv2.imwrite(str(ds / name), cv2.resize(img, DATASET_SIZE, interpolation=cv2.INTER_AREA))
        rows.append({"file": name, "slot": i, "t_video": round(f[2], 2),
                     "t_rta": "" if offset is None else round(f[2] - offset, 2),
                     "palette_up": round(f[1], 3), "towers": len(f[3]), "screen": f[5]})
    with open(ds / "manifest.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "slot", "t_video", "t_rta", "palette_up", "towers", "screen"])
        w.writeheader()
        w.writerows(rows)
    out = [ev / "approach_sheet.png"]
    cv2.imwrite(str(out[0]), sheet)
    if len(zoom) == 4:
        zw, zh = ZOOM
        tiles = [_label(cv2.resize(full[f[2]], ZOOM, interpolation=cv2.INTER_AREA), text(f[2]))
                 for f in zoom if f[2] in full]
        if len(tiles) == 4:
            out.append(ev / "approach_zoom.png")
            cv2.imwrite(str(out[1]), np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])]))
    return [str(p) for p in out]


# =====================================================================================
# Driver
# =====================================================================================

def run(run_id):
    run_dir = RUNS / run_id
    analysis = json.loads((run_dir / "analysis.json").read_text())
    lay = load_layout(run_dir)
    video = run_dir / "video.mp4"
    all_rows = read_f3_csv(run_dir / "f3.csv") or []
    rows = [r for r in all_rows if r["dim"] == "nether" and r["x"] is not None and r["y"] is not None
            and r["confidence"] >= config.BASTION_F3_MIN_CONF]

    feas = feasibility(lay.h)
    approach = None
    if _split(analysis, "found_bastion"):
        prof = profile_nether(run_dir, analysis, lay, video)
        approach = approach_window(run_dir, analysis, prof)
        gold_t = approach["chalice"]["gold_t"]
        labels = f3_labels(run_dir, analysis, rows, lay, video, chalice_t=gold_t)
        if gold_t is None:                       # no gold cue: fall back to the F3 stop, then the hotbar
            f3c = (labels or {}).get("chalice")
            approach = approach_window(run_dir, analysis, prof, f3c["t0"] if f3c else None)
    else:
        labels = None
    forward = labels.get("forward_xz") if labels and labels.get("status") == "ok" else None
    out, kept, window = visual_reader(run_dir, analysis, rows, lay, video, forward, approach)
    with open(run_dir / "bastion.csv", "w", newline="") as f:
        cols = ["t", "rampart", "visible", "est_height_rel", "type_guess", "confidence", "towers", "screen"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    summary = summarize(out)
    evidence = save_evidence(run_dir, video, lay, kept)
    offset = clock_offset(run_dir)
    sheets = save_approach_sheet(run_dir, video, lay, kept, window, offset) if approach else []
    result = {"version": 1, "approach_window": window, "approach": approach, "clock_offset_s": offset,
              "feasibility": feas, "f3_labels": labels,
              "visual_summary": summary, "frames": len(kept),
              "frames_with_tower": sum(1 for k in kept if k[3]),
              "frames_with_pair": sum(1 for k in kept if k[4]["left"] is not None),
              "evidence": sheets + evidence}
    (run_dir / "bastion.json").write_text(json.dumps(result, indent=1))
    return result


def evaluate(run_id, res):
    """Compare the visual summary with calibration/bastion/rampart_labels.csv (learner rows).
    Label times are on the in-game RTA clock; video time = RTA + the layout's clock offset."""
    path = config.CALIBRATION_DIR / "bastion" / "rampart_labels.csv"
    lay = json.loads((RUNS / run_id / "layout.json").read_text())
    off = ((lay.get("clock") or {}).get("lines") or [{}])[0].get("offset_s", 0.0)
    lines = []
    with open(path, newline="") as f:
        for lab in csv.DictReader(f):
            if lab["run"] != run_id:
                continue
            got = res["visual_summary"][lab["rampart"]]
            t_video = f"{float(lab['t_s']) + off:.1f}" if lab["t_s"] else "-"
            lines.append(f"  label[{lab['source']}] {lab['rampart']} {lab['type']} @video {t_video}s  ->  "
                         f"reader {got['type']} known_at {got['known_at']} conf {got['confidence']}")
    return lines


def main(argv):
    for run_id in argv or ["shipwreck-bridge"]:
        res = run(run_id)
        print(f"== {run_id}: window {res['approach_window']}, chalice {(res['approach'] or {}).get('chalice')}, "
              f"frames {res['frames']}, "
              f"with tower {res['frames_with_tower']}, with pair {res['frames_with_pair']}")
        lab = res["f3_labels"]
        print("  F3:", json.dumps(lab)[:900])
        print("  visual:", res["visual_summary"])
        print("\n".join(evaluate(run_id, res)))


if __name__ == "__main__":
    main(sys.argv[1:])
