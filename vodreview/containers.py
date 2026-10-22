"""Container screens: which container GUI is open (single chest, large chest, ...)?

Language-free: matches vanilla 1.16 slot grids, in GUI pixels at the measured GUI
scale k (layout.json), against every frame the screen classifier called
`inventory` (samples.csv). A slot is an 18x18 GUI-px frame: a dark (#373737)
top/left edge and a white (#FFFFFF) bottom/right edge around a #8B8B8B square;
items are drawn inside, so the edges stay visible. Each container type has its
own slot positions (vanilla menu classes), so the layout whose edges line up
best is the container:

* chest      - 9x3 slots at (8, 18); GUI 176x168 (ChestMenu.threeRows). A
               BARREL (and a shulker box, 1 px shorter) uses the same menu and
               texture - only the title text differs, so structure can NOT tell
               them apart: "chest" means chest / barrel / shulker box.
* large_chest - 9x6 slots at (8, 18); GUI 176x222.
* inventory  - player inventory (armor column, 2x2 crafting grid).
* crafting_table, furnace (also smoker / blast furnace), hopper.
* other      - the player-inventory rows fit but no known container grid does
               (smithing, anvil, brewing stand, enchanting table, ...).
* none       - not even the inventory rows fit (stale/transition sample).

Output: runs/<id>/containers.csv (t_start, t_end, kind, k, confidence).
Then for the bridge-bastion runs: which rampart room each chest was in
(F3 position, else bastion.json orientation) -> rampart_labels.csv rows
with source=chest (`python -m vodreview.containers labels`).

Thresholds: CONT_* in config.py.
"""

import csv
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from .config import (CONT_BOTTOM_TOL, CONT_DARK_MAX, CONT_F3_MAX_DT, CONT_FRAMES_PER_EVENT, CONT_MERGE_GAP_S,
                     CONT_MIN_BOTTOM, CONT_MIN_TOP, CONT_RECIPE_SHIFT, CONT_ROOM_MIN_DIST, CONT_SEARCH_GUI,
                     CONT_SEARCH_STEP, CONT_SIDE_MIN_LATERAL, CONT_WHITE_MIN)
from .layout import load_layout

RUNS = Path(__file__).resolve().parent.parent / "runs"
LABELS = Path(__file__).resolve().parent.parent / "calibration" / "bastion" / "rampart_labels.csv"

# Thresholds: CONT_* in config.py.


def _grid(x0, y0, cols, rows):
    return [(x0 + 18 * c, y0 + 18 * r) for r in range(rows) for c in range(cols)]


def _inv(y):
    """Player main inventory (3 rows) + hotbar starting at GUI y."""
    return _grid(8, y, 9, 3) + _grid(8, y + 58, 9, 1)


# name -> (panel height, container-specific slots, player-inventory slots)
LAYOUTS = {
    "chest": (168, _grid(8, 18, 9, 3), _inv(85)),
    "large_chest": (222, _grid(8, 18, 9, 6), _inv(139)),
    "inventory": (166, [(8, 8 + 18 * i) for i in range(4)] + _grid(98, 18, 2, 2) + [(77, 62)], _inv(84)),
    "crafting_table": (166, _grid(30, 17, 3, 3), _inv(84)),
    "furnace": (166, [(56, 17), (56, 53)], _inv(84)),
    "hopper": (133, _grid(44, 20, 5, 1), _inv(51)),
}
RECIPE_BOOK = ("inventory", "crafting_table", "furnace")


def _edge_points(slots):
    """GUI-px sample points on the dark (top/left) and white (bottom/right) slot edges."""
    dark, white = [], []
    for sx, sy in slots:
        for i in range(1, 15, 2):
            dark += [(sx + i + 0.5, sy - 0.5), (sx - 0.5, sy + i + 0.5)]
            white += [(sx + i + 0.5, sy + 16.5), (sx + 16.5, sy + i + 0.5)]
    return np.array(dark), np.array(white)


_PTS = {name: (_edge_points(top), _edge_points(bot)) for name, (_, top, bot) in LAYOUTS.items()}


def _fit(gray, pts, ox, oy, k):
    (d, w) = pts
    h, wd = gray.shape

    def look(p):
        xs = np.clip((ox + p[:, 0] * k).astype(int), 0, wd - 1)
        ys = np.clip((oy + p[:, 1] * k).astype(int), 0, h - 1)
        return gray[ys, xs]

    return 0.5 * ((look(d) <= CONT_DARK_MAX).mean() + (look(w) >= CONT_WHITE_MIN).mean())


def classify_frame(gray, lay):
    """-> (kind, score) for one grey frame showing a container GUI."""
    k = lay.k
    cx, cy = lay.cx, lay.cy
    steps = np.arange(-CONT_SEARCH_GUI, CONT_SEARCH_GUI + 1e-6, CONT_SEARCH_STEP)
    best = {}
    for name, (hgt, _, _) in LAYOUTS.items():
        top_pts, bot_pts = _PTS[name]
        shifts = [0, CONT_RECIPE_SHIFT] if name in RECIPE_BOOK else [0]
        b = (0.0, 0.0)
        for sh in shifts:
            for dy in steps:
                oy = cy + (-hgt / 2 + dy) * k
                for dx in steps:
                    ox = cx + (-88 + sh + dx) * k
                    sb = _fit(gray, bot_pts, ox, oy, k)
                    if sb < CONT_MIN_BOTTOM:
                        continue
                    st = _fit(gray, top_pts, ox, oy, k)
                    if st + sb > sum(b):
                        b = (st, sb)
        best[name] = b
    # Every container shares the player-inventory rows; a layout whose rows fit clearly
    # worse than the best is the wrong one (a hopper's 5 slots line up with a chest row
    # but its inventory rows then miss). Among the rest, the container slots decide.
    top_sb = max(sb for _, sb in best.values())
    cands = sorted((n for n in best if best[n][1] >= top_sb - CONT_BOTTOM_TOL), key=lambda n: -best[n][0])
    name = cands[0]
    st, sb = best[name]
    second = best[cands[1]][0] if len(cands) > 1 else 0.0
    if sb < CONT_MIN_BOTTOM:
        return "none", 0.0           # no player-inventory grid: not a container frame (stale sample)
    if st < CONT_MIN_TOP:
        return "other", 0.0
    return name, round(st - second, 2)


def _stretches(run_dir):
    out, cur = [], None
    with open(run_dir / "samples.csv", newline="") as f:
        for r in csv.DictReader(f):
            if r["screen"] != "inventory":
                continue
            t = float(r["time_s"])
            if cur and t - cur[1] <= CONT_MERGE_GAP_S:
                cur[1] = t
            else:
                cur = [t, t]
                out.append(cur)
    return out


def detect(run_id, verbose=True):
    run_dir = RUNS / run_id
    lay = load_layout(run_dir)
    cap = cv2.VideoCapture(str(run_dir / "video.mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    rows = []
    for t0, t1 in _stretches(run_dir):
        n = max(1, min(CONT_FRAMES_PER_EVENT, int(round((t1 - t0) / 0.1)) + 1))
        votes = {}
        for t in np.linspace(t0, t1, n):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
            ok, frame = cap.read()
            if not ok:
                continue
            kind, sc = classify_frame(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), lay)
            votes.setdefault(kind, []).append(sc)
        if not votes:
            continue
        cand = [kd for kd in votes if kd != "none"] or list(votes)
        kind = max(cand, key=lambda kd: (len(votes[kd]), np.mean(votes[kd])))
        conf = len(votes[kind]) / sum(len(v) for v in votes.values()) * min(1.0, 2.5 * max(0.0, float(np.mean(votes[kind]))))
        rows.append({"t_start": f"{t0:.1f}", "t_end": f"{t1 + 0.1:.1f}", "kind": kind, "k": lay.k,
                     "confidence": f"{conf:.2f}"})
    cap.release()
    with open(run_dir / "containers.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t_start", "t_end", "kind", "k", "confidence"])
        w.writeheader()
        w.writerows(rows)
    if verbose:
        counts = {}
        for r in rows:
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        print(f"{run_id}: {len(rows)} container screens {counts}")
    return rows


# ---------------------------------------------------------------------------------
# Rampart interior labels from chest events
# ---------------------------------------------------------------------------------

def _read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _f3_rows(run_dir):
    out = []
    p = run_dir / "f3.csv"
    if not p.is_file():
        return out
    for r in _read_rows(p):
        try:
            if r["dim"] == "nether" and r["x"] and float(r["confidence"] or 0) >= 0.5:
                out.append((float(r["time_s"]), float(r["x"]), float(r["z"])))
        except ValueError:
            pass
    return out


def rampart_labels(run_id):
    """Chest events in the bastion split -> per-rampart [(t_video, kind, how)] and a type."""
    run_dir = RUNS / run_id
    analysis = json.loads((run_dir / "analysis.json").read_text())
    bastion = json.loads((run_dir / "bastion.json").read_text())
    fb = next((s for s in analysis["splits"] if s["name"] == "found_bastion"), None)
    if fb is None:
        return None
    ev = [r for r in _read_rows(run_dir / "containers.csv")
          if r["kind"] in ("chest", "large_chest") and fb["start_s"] - 5 <= float(r["t_start"]) <= fb["end_s"]]
    lab = bastion.get("f3_labels") or {}
    f3 = _f3_rows(run_dir)
    sides = {"left": [], "right": [], "?": []}
    chal = lab.get("chalice")
    rxz = lab.get("right_xz")
    for e in ev:
        t = float(e["t_start"])
        side, how = "?", "no position"
        near = min(f3, key=lambda p: abs(p[0] - t)) if f3 else None
        if near and abs(near[0] - t) <= CONT_F3_MAX_DT and chal and rxz:
            dx, dz = near[1] - chal["x"], near[2] - chal["z"]
            lat = dx * rxz[0] + dz * rxz[1]
            if math.hypot(dx, dz) >= CONT_ROOM_MIN_DIST and abs(lat) >= CONT_SIDE_MIN_LATERAL:
                side, how = ("right" if lat > 0 else "left"), f"F3 ({near[1]:.0f},{near[2]:.0f}) lateral {lat:+.0f}"
            else:
                how = f"F3 ({near[1]:.0f},{near[2]:.0f}) not in a rampart"
        sides[side].append((t, e["kind"], how))
    return sides, ev, lab


def _clock_offset(run_dir):
    lay = json.loads((run_dir / "layout.json").read_text())
    return ((lay.get("clock") or {}).get("lines") or [{}])[0].get("offset_s", 0.0)


def write_labels(run_id):
    """Append source=chest rows (left/right only) to rampart_labels.csv; returns the summary.

    A large chest in a rampart's room -> triple; only single chests -> single.
    Events with no position are reported but not written (side unknown).
    """
    res = rampart_labels(run_id)
    if res is None:
        return {}
    sides, _, _ = res
    off = _clock_offset(RUNS / run_id)
    have = {(r["run"], r["rampart"]) for r in _read_rows(LABELS) if r["source"] == "chest"}
    out, new = {}, []
    for side, evs in sides.items():
        if not evs:
            continue
        kinds = {e[1] for e in evs}
        typ = "triple" if "large_chest" in kinds else "single"
        out[side] = (typ, evs)
        if side == "?" or (run_id, side) in have:
            continue
        t = evs[0][0]
        notes = "; ".join(f"{kd} RTA {tt - off:.1f} (video {tt:.1f}) {how}" for tt, kd, how in evs)
        new.append([run_id, f"{t - off:.1f}", side, typ, "", "chest",
                    f"t_s=RTA; containers.py chest GUI events in the room: {notes}"])
    if new:
        with open(LABELS, "a", newline="") as f:
            csv.writer(f).writerows(new)
    return out


def main(argv):
    if argv and argv[0] == "labels":
        for run_id in argv[1:] or ["shipwreck-bridge", "tivesflow", "vod-review"]:
            print(run_id, write_labels(run_id))
        return
    for run_id in argv or sorted(p.name for p in RUNS.iterdir() if (p / "samples.csv").is_file()):
        detect(run_id)


if __name__ == "__main__":
    main(sys.argv[1:])
