"""Compact text digest of one analyzed run, for an LLM coach to reason over.

`python -m vodreview digest runs/<id>` reads runs/<id>/analysis.json (+ the
optional learner-written runs/<id>/context.md) and writes runs/<id>/digest.md.

Pure data -> text: no computer vision, no network. Sections follow the
learner-chosen order (a-j). Anything the CV can't measure yet is written as an
explicit `UNKNOWN - needs <reader>` line so the coach flags it instead of
guessing. Every time is VOD time, m:ss.s.
"""

import json
import math
from pathlib import Path

SPLIT_LABELS = {
    "overworld": "Overworld",
    "entered_nether": "Entered Nether",
    "found_bastion": "Bastion",
    "found_fortress": "Fortress",
    "finding_stronghold": "Blind (finding stronghold)",
    "found_stronghold": "Stronghold",
    "entered_end": "End",
}
NON_WORLD = ("inventory", "f3", "settings", "pause", "resized")

# context.md keys that fill otherwise-UNKNOWN fields (other keys are listed as learner notes)
CONTEXT_KEYS = {
    "overworld": "overworld type",
    "bastion": "bastion type",
    "approach": "bastion approach",
    "bastion_route": "bastion route",
    "post_route": "post-route actions",
    "blind": "blind",
    "stronghold": "stronghold navigation",
    "dragon": "dragon fight",
}


def t(seconds):
    """VOD seconds -> m:ss.s"""
    if seconds is None:
        return "?"
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    return f"{sign}{int(seconds // 60)}:{seconds % 60:04.1f}"


def dur(seconds):
    return f"{seconds:.1f}s" if seconds < 60 else f"{t(seconds)}"


def signed(seconds):
    return f"{'+' if seconds >= 0 else '-'}{abs(seconds):.1f}s"


def read_context(run_dir):
    """runs/<id>/context.md -> {key: value}. Lines like `overworld: village` (leading `-`/`*` ok)."""
    path = Path(run_dir, "context.md")
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("-* ").strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower().replace(" ", "_").replace("-", "_")
        if key and value.strip():
            out[key] = value.strip()
    return out


def known_or_unknown(ctx, key, reader):
    if key in ctx:
        return f"{ctx[key]} (learner context.md)"
    return f"UNKNOWN — needs {reader}"


# --- helpers over analysis.json -----------------------------------------------

def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def points_in(points, t0, t1):
    return [p for p in points if t0 <= p["t_s"] < t1]


def coverage(points, t0, t1):
    """Share of [t0, t1) that has an F3 read within the same 1 s bin."""
    length = t1 - t0
    if length <= 0:
        return 0.0
    bins = {int(p["t_s"]) for p in points if t0 <= p["t_s"] < t1}
    return min(1.0, len(bins) / max(1.0, length))


def pos(p):
    return f"({p['x']:.0f}, {p['y']:.0f}, {p['z']:.0f})"


def path_stats(pts):
    """Straight-line displacement, summed horizontal path between reads, y range."""
    if len(pts) < 2:
        return None
    path = sum(math.hypot(b["x"] - a["x"], b["z"] - a["z"]) for a, b in zip(pts, pts[1:])
               if a.get("dim") == b.get("dim"))
    disp = math.hypot(pts[-1]["x"] - pts[0]["x"], pts[-1]["z"] - pts[0]["z"])
    ys = [p["y"] for p in pts]
    return {"path": path, "disp": disp, "ymin": min(ys), "ymax": max(ys)}


def biomes(pts):
    counts = {}
    for p in pts:
        b = p.get("biome")
        if b:
            counts[b] = counts.get(b, 0) + 1
    return ", ".join(f"{b}×{n}" for b, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def opp_status_at(opponent, t_s):
    """Latest opponent HUD status visible at t_s (info the player had on screen)."""
    if not opponent:
        return None
    seen = [s for s in opponent.get("statuses") or opponent.get("splits") or [] if s["t_s"] <= t_s]
    return seen[-1] if seen else None


def screen_time(screens, t0, t1):
    out = {}
    for r in screens:
        if r["screen"] == "world":
            continue
        o = overlap(r["start_s"], r["end_s"], t0, t1)
        if o > 0:
            out[r["screen"]] = out.get(r["screen"], 0.0) + o
    return out


def idle_time(idle, t0, t1):
    return sum(overlap(s["start_s"], s["end_s"], t0, t1) for s in idle)


def split_by_name(splits, name):
    return next((s for s in splits if s["name"] == name), None)


def source_note(split):
    ev = (split.get("evidence") or "").lower()
    if "toast" in ev and ("transition" in ev or "standing" in ev or "dimension" in ev):
        return "toast+dim"
    if "toast" in ev:
        return "toast"
    if "transition" in ev or "dimension" in ev:
        return "dim change"
    if "video start" in ev:
        return "video start"
    return split.get("source", "?")


# --- sections -------------------------------------------------------------------

def hotbar_lines(hb, splits):
    """'## k. Hotbar' section: per-split hotbar at the split's end + key item changes (hotbar.csv)."""
    from .hotbar import block_totals, category, format_snapshot, snapshot
    rows, changes = hb["rows"], hb["changes"]
    L = ["## k. Hotbar (HUD reader, 2 Hz on world/F3 screens)",
         "Slots 1-9 at each split's end (latest item read twice in a row, last 15 s): item×count; – empty, ? unread, "
         "a|b = one of two look-alike items. Changes = stable item swaps of key items / building blocks."]
    for s in splits:
        a, b = s["start_s"], s["end_s"]
        snap = snapshot(rows, b)
        label = SPLIT_LABELS.get(s["name"], s["name"])
        if not snap:
            L.append(f"- {label} (end {t(b)}): Hotbar no reads")
            continue
        tot = block_totals(snap)
        L.append(f"- {label} (end {t(b)}): Hotbar {format_snapshot(snap)}; building blocks non-flammable "
                 f"{tot['nonflammable']}, flammable {tot['flammable']}")
        ev = [c for c in changes if a <= c["t"] < b and (category(c["to"]) or category(c["from"]))]
        if ev:
            shown = ev[:10]
            txt = []
            for c in shown:
                if c["from"] in ("", "air"):
                    txt.append(f"{t(c['t'])} slot {c['slot']}: {c['to']}" + (f" ×{c['count']}" if c["count"] else "") + " appeared")
                elif c["to"] == "air":
                    txt.append(f"{t(c['t'])} slot {c['slot']}: {c['from']} gone")
                else:
                    txt.append(f"{t(c['t'])} slot {c['slot']}: {c['from']} → {c['to']}")
            L.append("  - " + "; ".join(txt) + (f"; +{len(ev) - len(shown)} more" if len(ev) > len(shown) else ""))
    return L


# --- bastion section (bastion.json + containers.csv + f3.csv of this run) -------

CONTAINER_NAMES = {"chest": "single chest", "large_chest": "LARGE chest", "crafting_table": "crafting table",
                   "inventory": "inventory", "furnace": "furnace", "hopper": "hopper", "other": "other GUI"}


def _compass(x, z):
    """Horizontal unit vector -> nearest compass direction (Minecraft: +Z south, +X east)."""
    if abs(x) >= abs(z):
        return "east (+X)" if x > 0 else "west (-X)"
    return "south (+Z)" if z > 0 else "north (-Z)"


def _evidence_time(name):
    try:
        return float(name.rsplit("_", 1)[1].removesuffix(".png").removesuffix("s"))
    except (IndexError, ValueError):
        return None


def load_bastion(run_dir):
    """This run's own bastion data: bastion.json, containers.csv, f3.csv nether positions (None if no files)."""
    import csv
    run_dir = Path(run_dir)
    out = {"bastion": None, "containers": None, "f3": [], "run_id": run_dir.name}
    if (run_dir / "bastion.json").is_file():
        out["bastion"] = json.loads((run_dir / "bastion.json").read_text())
    if (run_dir / "containers.csv").is_file():
        with open(run_dir / "containers.csv", newline="") as f:
            out["containers"] = [{"t0": float(r["t_start"]), "t1": float(r["t_end"]), "kind": r["kind"]}
                                 for r in csv.DictReader(f)]
    if (run_dir / "f3.csv").is_file():
        with open(run_dir / "f3.csv", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    if r["dim"] == "nether" and r["x"] and float(r["confidence"] or 0) >= 0.5:
                        out["f3"].append((float(r["time_s"]), float(r["x"]), float(r["z"])))
                except (KeyError, ValueError):
                    pass
    if out["bastion"] is None and out["containers"] is None:
        return None
    return out


def _room(bd, t_s):
    """Which rampart room the player was in at t_s, from F3 vs. the chalice (same rule as containers.py)."""
    from .config import CONT_F3_MAX_DT, CONT_ROOM_MIN_DIST, CONT_SIDE_MIN_LATERAL
    lab = (bd.get("bastion") or {}).get("f3_labels") or {}
    chal, rxz, f3 = lab.get("chalice"), lab.get("right_xz"), bd.get("f3")
    if not (chal and rxz and f3):
        return None
    near = min(f3, key=lambda p: abs(p[0] - t_s))
    if abs(near[0] - t_s) > CONT_F3_MAX_DT:
        return None
    dx, dz = near[1] - chal["x"], near[2] - chal["z"]
    lat = dx * rxz[0] + dz * rxz[1]
    if math.hypot(dx, dz) >= CONT_ROOM_MIN_DIST and abs(lat) >= CONT_SIDE_MIN_LATERAL:
        return "right" if lat > 0 else "left"
    return "not in a rampart"


def bastion_lines(bd, b0, b1):
    """'Bastion' subsection of e: chalice, orientation, container events, rampart knowledge, evidence frames."""
    L = ["### e2. Bastion (rampart reader + container screens; this run's own F3/GUI data only)"]
    bj = bd.get("bastion")
    lab = (bj or {}).get("f3_labels") or {}
    chal = lab.get("chalice")
    if bj is None:
        L.append("- Bastion reader not run on this VOD (no bastion.json): chalice, orientation and rooms UNKNOWN.")
    else:
        ap = bj.get("approach") or {}
        ch = ap.get("chalice") or {}
        how = {"gold": "gold blocks fill the view for ~1.5 s = standing on / mining the chalice; no F3 needed",
               "f3_stop": "first long F3 stop after the toast; no gold-view cue",
               "hotbar_gold_block": "first gold block entering the hotbar - 3 s (no gold-view or F3 cue)"}
        if ch.get("t") is not None:
            L.append(f"- Chalice arrival: ~{t(ch['t'])} ({how.get(ch['method'], ch['method'])}).")
        elif chal:
            L.append(f"- Chalice arrival: {t(chal['t0'])} (first long F3 stop after the toast).")
        else:
            L.append("- Chalice arrival: UNKNOWN (no gold-view, F3 or hotbar cue; may not be a bridge bastion).")
        if ap:
            off = bj.get("clock_offset_s")
            rta = (f"; RTA = VOD time {'−' if off >= 0 else '+'} {abs(off):.1f}s" if off is not None
                   else "; RTA offset unknown")
            fp = f", bastion palette first sustained {t(ap['first_palette'])}" if ap.get("first_palette") else ""
            L.append(f"- Approach window (first possible sighting → chalice + route start): {t(ap['t0'])}–{t(ap['t1'])} "
                     f"(nether entry {t(ap['nether_entry'])}{fp}, bastion toast {t(ap['toast'])}{rta}).")
        if lab.get("right_xz"):
            rx, rz = lab["right_xz"]
            L.append(f"- Orientation (standing at the chalice facing the ramparts = {lab.get('forward_compass')}): "
                     f"LEFT rampart = {_compass(-rx, -rz)}, RIGHT rampart = {lab.get('right_compass')}.")
        else:
            L.append("- Orientation (left/right in world coords): UNKNOWN — needs F3 at both rampart rooms.")
    ev = [e for e in bd.get("containers") or [] if b0 <= e["t0"] < b1]
    rooms = {}
    if bd.get("containers") is None:
        L.append("- Container events: not read (no containers.csv).")
    else:
        main = [e for e in ev if e["kind"] != "inventory"]
        inv = [e for e in ev if e["kind"] == "inventory"]
        txt = []
        for e in main:
            room = _room(bd, e["t0"])
            rooms.setdefault(room, []).append(e)
            where = f" [{room} rampart room]" if room in ("left", "right") else f" [{room}]" if room else ""
            txt.append(f"{CONTAINER_NAMES.get(e['kind'], e['kind'])} {t(e['t0'])} ({e['t1'] - e['t0']:.1f}s){where}")
        L.append("- Container screens in split: " + ("; ".join(txt) if txt else "no chest / crafting screens") + ".")
        if inv:
            shown = ", ".join(t(e["t0"]) for e in inv[:12])
            L.append(f"  - Inventory opens: {len(inv)} ({sum(e['t1'] - e['t0'] for e in inv):.1f}s total): {shown}"
                     + (f", +{len(inv) - 12} more" if len(inv) > 12 else "") + ".")
        L.append("  - \"single chest\" = chest / barrel / shulker box (same GUI)"
                 + ("; in a bridge bastion a LARGE (double) chest only generates in a TRIPLE rampart's room." if bj else "."))
    know = []
    ramparts = lab.get("ramparts") or {}
    for side in ("left", "right"):
        large = [e for e in rooms.get(side, []) if e["kind"] == "large_chest"]
        if large:
            know.append(f"{side} = TRIPLE known from {t(large[0]['t0'])} (large chest opened in the {side} rampart room)")
        elif (ramparts.get(side) or {}).get("height_rule") in ("triple", "single"):
            r = ramparts[side]
            know.append(f"{side} = {r['height_rule'].upper()} by the F3 height rule (triple = single + 10 blocks; "
                        f"its top reached {t(r['t'])})")
    unplaced = [e for r, es in rooms.items() if r not in ("left", "right") for e in es if e["kind"] == "large_chest"]
    if bj is not None and unplaced and not any(k.endswith("rampart room)") for k in know):
        know.append(f"at least one rampart = TRIPLE known from {t(unplaced[0]['t0'])} (large chest opened; its rampart "
                    f"room not placed by F3) — which side: UNKNOWN")
    vs = (bj or {}).get("visual_summary") or {}
    for side in ("left", "right"):
        v = vs.get(side) or {}
        if v.get("known_at") is not None and v.get("type") not in (None, "unknown"):
            know.append(f"{side} = {v['type']} per exterior reader from {t(v['known_at'])} (conf {v.get('confidence', 0):.2f})")
    if bj is None:
        L.append("- Rampart knowledge: UNKNOWN — no rampart-reader data for this run (no evidence frames).")
    else:
        L.append("- Rampart knowledge (what this run's data supports): "
                 + ("; ".join(know) + ". Anything not listed: UNKNOWN — check evidence frames." if know
                    else "UNKNOWN — check evidence frames (exterior reader gave no confident read; it never guesses)."))
    paths = [Path(p).name for p in (bj or {}).get("evidence") or []]
    base = f"runs/{bd['run_id']}/bastion_evidence/"
    if paths:
        L.append("- Evidence (view with get_evidence; each image counts toward the frame budget):")
        if "approach_sheet.png" in paths:
            L.append(f"  - VIEW FIRST: {base}approach_sheet.png — contact sheet, 1 image, 16 thumbnails evenly "
                     "spread over the approach window (each slot's most bastion-filled frame), each labelled "
                     "with VOD time (v) and RTA; use it to find WHEN ramparts were in view, then get_frame those times.")
        if "approach_zoom.png" in paths:
            L.append(f"  - {base}approach_zoom.png — 4 of the sheet's frames enlarged (distant-structure views).")
        views = sorted((n for n in paths if n.startswith("view_")), key=lambda n: _evidence_time(n) or 0)[:3]
        if views:
            L.append("  - full frames with the most bastion in view: "
                     + ", ".join(f"{base}{n} ({t(_evidence_time(n))})" for n in views))
    return L


def build_digest(analysis, ctx, run_id, hotbar=None, bastion=None):
    run = analysis["run"]
    splits = analysis.get("splits") or []
    screens = analysis.get("screens") or []
    idle = analysis.get("idle") or []
    opp = analysis.get("opponent") or None
    clock = analysis.get("match_clock") or None
    if clock and clock.get("offset_s") is None:  # no clock reads (e.g. no RTA overlay)
        clock = None
    state = analysis.get("state") or {}
    points = state.get("points") or []
    pairs = state.get("portal_pairs") or []
    advs = analysis.get("advancements") or []
    run_end = run["run_end_s"]
    L = []

    # header
    L.append(f"# Run digest: {run_id}")
    res = run.get("result") or "unknown"
    if res == "draw" and run.get("end_reason") == "forfeit":
        res = "forfeit (shown as a draw: private room)"
    if run.get("private_room"):
        res += "; private room (no opponent)"
    L.append(f"- Result: {res}; final time on result screen {run.get('final_time_text') or '?'}"
             f"{' (winner time, not ours)' if res.startswith('loss') else ' (a draw screen shows no time)' if res.startswith(('draw', 'forfeit')) else ''}; run end {t(run_end)} VOD ({run['end_reason']}).")
    if clock:
        L.append(f"- Match clock: match_time = VOD − {clock['offset_s']:.1f}s "
                 f"(spread {clock.get('spread_s', 0):.2f}s over {clock.get('reads', '?')} reads).")
    L.append(f"- F3 state: {len(points)} position reads"
             + (f" ({state.get('valid', '?')}/{state.get('reads', '?')} valid; only while F3 is open)" if state else "")
             + ". Times below are VOD m:ss.s.")
    for k in ctx:
        if k not in CONTEXT_KEYS:
            L.append(f"- Learner note ({k}): {ctx[k]}")
    L.append("")

    # a. overworld + bastion type
    L.append("## a. Overworld type + bastion type")
    ow = split_by_name(splits, "overworld")
    ow_b = biomes(points_in(points, 0, ow["end_s"])) if ow else ""
    L.append(f"- Overworld: {known_or_unknown(ctx, 'overworld', 'overworld/structure classifier (village, shipwreck, ruined portal, desert temple…)')}")
    if ow_b:
        L.append(f"  - F3 biome reads in overworld split: {ow_b}")
    L.append(f"- Bastion: {known_or_unknown(ctx, 'bastion', 'bastion classifier (housing / treasure / bridge / stables)')}")
    L.append("")

    # b. progression
    L.append("## b. Progression (splits, VOD time)")
    opp_by = {s["name"]: s for s in (opp or {}).get("splits") or []}
    L.append(f"Opponent: {(opp or {}).get('name') or 'none read'}. Δ = ours − opponent at split start (negative = we were ahead).")
    L.append("| split | start | dur | src | opp start | Δ |")
    L.append("|---|---|---|---|---|---|")
    for s in splits:
        o = opp_by.get(s["name"])
        delta = signed(s["start_s"] - o["t_s"]) if o and s["name"] != "overworld" else "–"
        L.append(f"| {SPLIT_LABELS.get(s['name'], s['name'])} | {t(s['start_s'])} | {dur(s['end_s'] - s['start_s'])} "
                 f"| {source_note(s)} | {t(o['t_s']) if o else '–'} | {delta} |")
    if ow and clock:
        L.append(f"- Overworld row starts at VOD start; from match start ({t(clock['offset_s'])}) it lasted "
                 f"{dur(ow['end_s'] - clock['offset_s'])}.")
    missing = [n for n in SPLIT_LABELS if not split_by_name(splits, n)]
    if missing:
        L.append(f"- Splits not detected: {', '.join(missing)}.")
    if opp and opp.get("splits"):
        lat = max((s.get("latency_s") or 0) for s in opp["splits"] if s["name"] != "overworld")
        L.append(f"- Opponent times are when the HUD changed (read latency up to {lat:.1f}s); the 'overworld' row is match start.")
    if advs:
        L.append("- Advancements: " + "; ".join(f"{a['title']} {t(a['t_s'])}" for a in advs))
    L.append("")

    # c. decision tree
    L.append("## c. Decision points")
    L.append("Options column = only what the player could know at that moment. Opp = opponent HUD status on screen then.")
    decisions = []
    for s in splits:
        if s["name"] == "overworld":
            continue
        decisions.append((s["start_s"], f"split → {SPLIT_LABELS.get(s['name'], s['name'])}"))
    for p in pairs:
        best = min(range(len(decisions)), key=lambda i: abs(decisions[i][0] - p["t_s"]), default=None)
        if best is not None and abs(decisions[best][0] - p["t_s"]) < 1.0:
            d0, d1 = decisions[best]
            decisions[best] = (d0, d1 + f" (portal {p['from']}→{p['to']})")
        else:
            decisions.append((p["t_s"], f"portal {p['from']} → {p['to']}"))
    decisions.sort()
    for d_t, what in decisions:
        near = sorted((p for p in points if abs(p["t_s"] - d_t) <= 3.0), key=lambda p: abs(p["t_s"] - d_t))
        before = [p for p in points if d_t - 30 <= p["t_s"] < d_t]
        if near:
            where = f"{pos(near[0])} {near[0]['dim']} @{t(near[0]['t_s'])}"
        elif before:
            where = f"last F3 {pos(before[-1])} {before[-1]['dim']} ({d_t - before[-1]['t_s']:.0f}s earlier)"
        else:
            where = "pos unknown (no F3 within 30s before)"
        st = opp_status_at(opp, d_t)
        L.append(f"- {t(d_t)} {what}; {where}; Opp: {st['raw'] if st else '–'}")
    L.append("  - Options available at each point: UNKNOWN — needs explored-map reader (what terrain/structures were "
             "visible) + HUD reader (inventory/resources at that time)")
    L.append("")

    # d. approach to bastion
    L.append("## d. Position approaching bastion")
    nether = split_by_name(splits, "entered_nether")
    bast = split_by_name(splits, "found_bastion")
    if nether and bast:
        pts = points_in(points, nether["start_s"], bast["start_s"])
        cov = coverage(points, nether["start_s"], bast["start_s"])
        if bast["start_s"] - nether["start_s"] < 3:
            L.append(f"- Bastion toast {bast['start_s'] - nether['start_s']:.1f}s after nether entry: portal "
                     f"spawned at/next to the bastion (entry {pos(pts[0]) if pts else 'pos unread'}).")
        elif pts:
            ps = path_stats(pts)
            L.append(f"- First nether read {pos(pts[0])} @{t(pts[0]['t_s'])} → last read before bastion "
                     f"{pos(pts[-1])} @{t(pts[-1]['t_s'])} (no reads for the last "
                     f"{bast['start_s'] - pts[-1]['t_s']:.1f}s before the bastion toast).")
            if ps:
                L.append(f"  - Read path {ps['path']:.0f} blocks, displacement {ps['disp']:.0f}, y {ps['ymin']:.0f}–{ps['ymax']:.0f} "
                         f"(F3 coverage {cov:.0%} of split).")
        else:
            L.append(f"- No F3 reads between nether entry and bastion (coverage 0%).")
    elif bast:
        L.append(f"- No separate Entered Nether split detected; bastion at {t(bast['start_s'])}.")
    L.append(f"- Approach: {known_or_unknown(ctx, 'approach', 'explored-map reader + bastion classifier (side/height of entry)')}")
    L.append("- Alternatives: UNKNOWN — needs explored-map reader")
    L.append("")

    # e. bastion route
    L.append("## e. Bastion route taken")
    if bast:
        b0, b1 = bast["start_s"], bast["end_s"]
        pts = points_in(points, b0, b1)
        sc = screen_time(screens, b0, b1)
        L.append(f"- Bastion split {t(b0)}–{t(b1)} ({dur(b1 - b0)}); inventory {sc.get('inventory', 0):.1f}s, "
                 f"F3 {sc.get('f3', 0):.1f}s in split.")
        if pts:
            ps = path_stats(pts)
            L.append(f"  - F3 reads {len(pts)} (coverage {coverage(points, b0, b1):.0%}); y {ps['ymin']:.0f}–{ps['ymax']:.0f}, "
                     f"read path {ps['path']:.0f} blocks." if ps else f"  - F3 reads {len(pts)}.")
        bad = [a for a in advs if b0 <= a["t_s"] < b1]
        if bad:
            L.append("  - Advancements in split: " + "; ".join(f"{a['title']} {t(a['t_s'])}" for a in bad))
        if hotbar:
            from .hotbar import block_totals, snapshot
            snap = snapshot(hotbar["rows"], b1)
            if snap:
                tot = block_totals(snap)
                verdict = "adequate" if tot["nonflammable"] >= 30 else "below"
                L.append(f"  - Building blocks in hotbar leaving the bastion ({t(b1)}): non-flammable "
                         f"{tot['nonflammable']}, flammable {tot['flammable']} → {verdict} the learner's rule "
                         f"(adequate = 30+ non-flammable). Hotbar only: blocks in the main inventory are not counted.")
    L.append(f"- Route: {known_or_unknown(ctx, 'bastion_route', 'bastion classifier + optical flow / HUD reader (gold blocks, chests, piglin aggro)')}")
    L.append("- Route end (leaving bastion): UNKNOWN — needs bastion-exit detector (route/post-route boundary)")
    if bast and bastion:
        L += bastion_lines(bastion, bast["start_s"], bast["end_s"])
    L.append("")

    # f. post-route before fortress
    L.append("## f. Post-route actions before fortress find")
    fort = split_by_name(splits, "found_fortress")
    if bast and fort:
        pts = points_in(points, bast["start_s"], fort["start_s"])
        tail = [p for p in pts if p["t_s"] >= fort["start_s"] - 60]
        if tail:
            ps = path_stats(tail)
            L.append(f"- Last 60s before fortress: {len(tail)} F3 reads, {pos(tail[0])} @{t(tail[0]['t_s'])} → "
                     f"{pos(tail[-1])} @{t(tail[-1]['t_s'])}"
                     + (f"; y {ps['ymin']:.0f}–{ps['ymax']:.0f}, read path {ps['path']:.0f} blocks" if ps else "")
                     + f" (coverage {coverage(points, fort['start_s'] - 60, fort['start_s']):.0%}).")
        L.append(f"- Fortress found {t(fort['start_s'])} ({source_note(fort)}"
                 + (f"; official toast {t(fort['official_s'])}" if fort.get("official_s") else "") + ").")
    L.append(f"- Actions: {known_or_unknown(ctx, 'post_route', 'HUD/inventory reader + optical flow (bridging, pearls, terrain height choice)')}")
    L.append("")

    # g. optimizations
    L.append("## g. Optimizations (time off-world per split)")
    L.append("| split | dur | inv | F3 | settings/pause | resized | idle | in-world |")
    L.append("|---|---|---|---|---|---|---|---|")
    tot = {k: 0.0 for k in NON_WORLD}
    tot_idle = 0.0
    for s in splits:
        a, b = s["start_s"], s["end_s"]
        sc = screen_time(screens, a, b)
        idl = idle_time(idle, a, b)
        for k in NON_WORLD:
            tot[k] += sc.get(k, 0.0)
        tot_idle += idl
        off = sum(sc.values())
        L.append(f"| {SPLIT_LABELS.get(s['name'], s['name'])} | {dur(b - a)} | {sc.get('inventory', 0):.1f} "
                 f"| {sc.get('f3', 0):.1f} | {sc.get('settings', 0) + sc.get('pause', 0):.1f} | {sc.get('resized', 0):.1f} "
                 f"| {idl:.1f} | {max(0.0, (b - a) - off):.1f} |")
    L.append(f"- Totals: inventory {tot['inventory']:.1f}s, F3 {tot['f3']:.1f}s, settings/pause "
             f"{tot['settings'] + tot['pause']:.1f}s, resized {tot['resized']:.1f}s, idle {tot_idle:.1f}s "
             f"(idle = no motion ≥3s; screens smoothed, flicker <0.5s absorbed).")
    longest_inv = sorted((r for r in screens if r["screen"] == "inventory"),
                         key=lambda r: r["start_s"] - r["end_s"])[:3]
    if longest_inv:
        L.append("- Longest inventory visits: " + "; ".join(
            f"{t(r['start_s'])} {r['end_s'] - r['start_s']:.1f}s" for r in longest_inv))
    if idle:
        L.append("- Idle stretches: " + "; ".join(f"{t(s['start_s'])} {s['duration_s']:.1f}s" for s in idle))
    L.append("- What was crafted/traded/used in each menu: UNKNOWN — needs HUD/inventory reader")
    L.append("")

    # h. blind
    L.append("## h. Blind")
    blind = split_by_name(splits, "finding_stronghold")
    if blind:
        L.append(f"- Blind split {t(blind['start_s'])}–{t(blind['end_s'])} ({dur(blind['end_s'] - blind['start_s'])}).")
        bp = next((p for p in pairs if p["from"] == "nether" and p["to"] == "overworld"
                   and abs(p["t_s"] - blind["start_s"]) < 2), None)
        if bp and bp.get("checked"):
            ox, oz = bp["overworld"]
            L.append(f"- Blind portal: nether ({bp['nether'][0]:.0f}, {bp['nether'][1]:.0f}) → overworld "
                     f"({ox:.0f}, {oz:.0f}); distance from 0,0 = {math.hypot(ox, oz):.0f} blocks "
                     f"(coord check ok={bp.get('ok')}).")
        else:
            near = [p for p in points if abs(p["t_s"] - blind["start_s"]) <= 5 and p.get("dim") == "overworld"]
            if near:
                p = near[0]
                L.append(f"- First overworld read after blind {pos(p)} @{t(p['t_s'])}; distance from 0,0 = "
                         f"{math.hypot(p['x'], p['z']):.0f} blocks.")
            else:
                L.append("- Blind coords: not read (no F3 at the portal).")
    L.append(f"- Blind method/eye throws: {known_or_unknown(ctx, 'blind', 'eye-throw detector + HUD reader (F3 angle at throw)')}")
    L.append("")

    # i. stronghold
    L.append("## i. Stronghold navigation")
    sh = split_by_name(splits, "found_stronghold")
    if sh:
        a, b = sh["start_s"], sh["end_s"]
        pts = points_in(points, a, b)
        L.append(f"- Eye Spy {t(a)} → End entry {t(b)} ({dur(b - a)}); F3 reads {len(pts)} "
                 f"(coverage {coverage(points, a, b):.0%}).")
        if blind:
            L.append(f"- Blind start → Eye Spy: {dur(a - blind['start_s'])}.")
        later = [p for p in pairs if blind and p["t_s"] > blind["start_s"] + 1]
        for p in later:
            L.append(f"  - Extra portal {p['from']} → {p['to']} at {t(p['t_s'])}.")
    L.append(f"- Room-by-room route: {known_or_unknown(ctx, 'stronghold', 'stronghold room reader / explored-map reader')}")
    L.append("")

    # j. dragon
    L.append("## j. Dragon fight")
    end = split_by_name(splits, "entered_end")
    if end:
        a, b = end["start_s"], end["end_s"]
        sc = screen_time(screens, a, b)
        pts = points_in(points, a, b)
        L.append(f"- End {t(a)} → run end {t(b)} ({dur(b - a)}); inventory {sc.get('inventory', 0):.1f}s; "
                 f"F3 reads {len(pts)} (coverage {coverage(points, a, b):.0%})"
                 + (f"; y {min(p['y'] for p in pts):.0f}–{max(p['y'] for p in pts):.0f}" if pts else "") + ".")
    L.append(f"- Strategy/cycles: {known_or_unknown(ctx, 'dragon', 'dragon-phase reader + HUD reader (beds/pearls used)')}")
    L.append("")
    if hotbar:
        L += hotbar_lines(hotbar, splits)
        L.append("")
    return "\n".join(L)


def write_digest(run_dir):
    run_dir = Path(run_dir)
    path = run_dir / "analysis.json"
    if not path.is_file():
        raise SystemExit(f"Missing {path}")
    analysis = json.loads(path.read_text())
    hotbar = None
    if (run_dir / "hotbar.csv").is_file():
        import csv
        from .hotbar import read_hotbar_csv
        changes = []
        if (run_dir / "hotbar_changes.csv").is_file():
            with open(run_dir / "hotbar_changes.csv", newline="") as f:
                changes = [{"t": float(r["t"]), "slot": int(r["slot"]), "from": r["from"], "to": r["to"],
                            "count": int(r["count"]) if r["count"].isdigit() else 0} for r in csv.DictReader(f)]
        hotbar = {"rows": read_hotbar_csv(run_dir / "hotbar.csv"), "changes": changes}
    text = build_digest(analysis, read_context(run_dir), run_dir.name, hotbar, load_bastion(run_dir))
    out = run_dir / "digest.md"
    out.write_text(text + "\n", encoding="utf-8")
    print(f"Wrote {out} (~{len(text) // 4} tokens)")
    return out
