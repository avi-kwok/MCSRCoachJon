"""Self-critique loop for the LLM coach (no API calls, no LLM here).

  critic-pack runs/<id> tips.json  -> runs/<id>/critic_checks.json (automatic evidence checks) and
                                      runs/<id>/critic_prompt.md (critic prompt + rubric + approved lessons
                                      + digest + tips + checks) to paste into Claude by hand
  add-lessons <file> [--run <id>]  -> append the critic's proposed lessons to coach/pending_lessons.md
  golden-score runs/<id> tips.json -> one-line-per-tip checklist for the learner + expected-route match
                                      (coach/golden/README.md; NEVER sent to an LLM), score template in
                                      coach/golden/scores/<id>.md

Checks are heuristics over the tip text (regex for m:ss times, (x,y,z) coordinates, item names): they
catch contradictions with the CSVs, not every bad claim. Levels: error (contradicted / invalid id),
warn (unsupported or suspicious), info (context for the critic).
"""

import csv
import datetime as _dt
import json
import re
from pathlib import Path

from . import routes as route_lib
from .coach import COACH_DIR, catalogue_ids, load_schema, validate

GOLDEN_README = COACH_DIR / "golden" / "README.md"
SPLIT_DIMS = {"overworld": {"overworld"}, "entered_nether": {"nether"}, "found_bastion": {"nether"},
              "found_fortress": {"nether"}, "finding_stronghold": {"overworld", "nether"},
              "found_stronghold": {"overworld"}, "entered_end": {"end"}}
SLACK_S = 2.0            # split-boundary tolerance
COORD_TOL = 8.0          # blocks, xz (and y for triples)
TIME_NEAR_S = 10.0       # a coordinate/item cited next to a time must be read within this of it

# item words in tip text -> predicate on a hotbar.csv item name
ITEMS = {
    "tnt": lambda i: i == "tnt",
    "flint and steel": lambda i: i == "flint_and_steel",
    "fire charge": lambda i: i == "fire_charge",
    "leaves": lambda i: i.endswith("_leaves"),
    "planks": lambda i: i.endswith("_planks"),
    "logs": lambda i: i.endswith("_log") or i.endswith("_wood"),
    "netherrack": lambda i: i == "netherrack",
    "dirt": lambda i: i == "dirt",
    "cobblestone": lambda i: i == "cobblestone",
    "obsidian": lambda i: i == "obsidian",
    "crying obsidian": lambda i: i == "crying_obsidian",
    "ender pearl": lambda i: i == "ender_pearl",
    "eye of ender": lambda i: i == "ender_eye",
    "gold block": lambda i: i == "gold_block",
    "gold ingot": lambda i: i == "gold_ingot",
    "iron pickaxe": lambda i: i == "iron_pickaxe",
    "lava bucket": lambda i: i == "lava_bucket",
    "water bucket": lambda i: i == "water_bucket",
    "bed": lambda i: i.endswith("_bed"),
    "boat": lambda i: i.endswith("_boat"),
}
ITEM_RE = {
    "tnt": r"\btnt\b", "flint and steel": r"flint (?:and|&) steel|flint_and_steel", "fire charge": r"fire.?charge",
    "leaves": r"\bleaves\b", "planks": r"\bplanks\b", "logs": r"\blogs?\b", "netherrack": r"\bnetherrack\b",
    "dirt": r"\bdirt\b", "cobblestone": r"\bcobble(?:stone)?\b", "obsidian": r"(?<!crying )\bobsidian\b",
    "crying obsidian": r"crying.obsidian", "ender pearl": r"\bpearls?\b", "eye of ender": r"\beyes? of ender\b|ender_eye",
    "gold block": r"gold.blocks?", "gold ingot": r"\bingots?\b", "iron pickaxe": r"iron pick",
    "lava bucket": r"lava bucket", "water bucket": r"water bucket", "bed": r"\bbeds?\b", "boat": r"\bboats?\b",
}
# digest UNKNOWN field label (prefix) -> words in a tip that mean it makes a claim about that field
UNKNOWN_TOPICS = {
    "Approach": [r"\bapproach", r"coming in", r"came in"],
    "Route": [r"\bdk\b", r"\bcs\b", r"\bsoog\b", r"route you played", r"you played", r"what you played"],
    "Route end": [r"left the bastion", r"leaving the bastion", r"\bexit(?:ed)? the bastion", r"route end"],
    "Actions": [r"\bpearl", r"bridg(?:ing|ed)"],
    "What was crafted": [r"\bcraft", r"\btrad(?:e|ed|ing)\b", r"\bbarter"],
    "Blind method": [r"\beyes?\b", r"\bthrow", r"ninjabrain", r"triangulat"],
    "Room-by-room": [r"\brooms?\b"],
    "Strategy": [r"\bcycles?\b", r"\bbeds?\b", r"\bperch"],
}
TOOL_EVIDENCE = re.compile(r"frame|get_state|get_inventory|f3\.csv|hotbar|inventory\s*\d", re.I)
HEDGES = re.compile(r"catalogue note|learner'?s? (?:catalogue|note)|not confirmed|assum|presumably|probably", re.I)
TIME_RE = re.compile(r"(?<![\d.:])(\d{1,2}):([0-5]\d(?:\.\d+)?)(?!\d|:\d)")
NUM = r"[+-]?\d+(?:\.\d+)?"
COORD_RE = re.compile(rf"\(\s*({NUM})\s*,\s*({NUM})\s*(?:,\s*({NUM})\s*)?\)")


NONFLAMMABLE = ("netherrack", "dirt", "cobblestone", "stone", "blackstone", "basalt", "soul_soil", "soul_sand",
                "nether_bricks", "end_stone", "obsidian", "gravel", "sand", "sandstone", "polished_blackstone_bricks")
FLAMMABLE_SUFFIX = ("_leaves", "_planks", "_log", "_wood", "_wool", "hay_block")


def block_kind(item):
    parts = item.split("|")
    if all(p in NONFLAMMABLE for p in parts):
        return "nonflammable"
    if all(p.endswith(FLAMMABLE_SUFFIX) for p in parts):
        return "flammable"
    return None


def mmss(s):
    return f"{int(s // 60)}:{s % 60:04.1f}" if s is not None else "?"


# --- run data -------------------------------------------------------------------------

def _csv(path):
    if not path.is_file():
        return None
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_run(run_dir):
    run_dir = Path(run_dir)
    analysis = json.loads((run_dir / "analysis.json").read_text())
    run = analysis.get("run", {})
    end = run.get("run_end_s") or run.get("duration_s")
    samples = [(float(r["time_s"]), r.get("dimension") or "") for r in (_csv(run_dir / "samples.csv") or [])]
    f3 = []
    for r in _csv(run_dir / "f3.csv") or []:
        x, y, z = _float(r.get("x")), _float(r.get("y")), _float(r.get("z"))
        if x is not None and z is not None:
            f3.append((float(r["time_s"]), x, y, z, r.get("dim") or ""))
    hb_rows = _csv(run_dir / "hotbar.csv")
    hotbar = None if hb_rows is None else [(float(r["t"]), r["item"]) for r in hb_rows if r.get("item")]
    bastion = json.loads((run_dir / "bastion.json").read_text()) if (run_dir / "bastion.json").is_file() else None
    ctx = {}
    if (run_dir / "context.md").is_file():
        for line in (run_dir / "context.md").read_text().splitlines():
            m = re.match(r"^\s*([A-Za-z_]+)\s*:\s*(.+)$", line)
            if m:
                ctx[m.group(1).lower()] = m.group(2).strip()
    return {"dir": run_dir, "id": run_dir.name, "end_s": end, "splits": analysis.get("splits", []),
            "samples": samples, "f3": f3, "hotbar": hotbar, "bastion": bastion, "ctx": ctx}


def read_digest(run_dir):
    """The digest the coach saw (runs/<id>/digest.md); regenerate only if it is missing."""
    path = Path(run_dir) / "digest.md"
    if not path.is_file():
        from .digest import write_digest
        path = write_digest(run_dir)
    return path.read_text()


def digest_unknowns(digest):
    """[(section letter, field label, reader)] for every `UNKNOWN — needs …` line."""
    out, sec = [], "?"
    for line in digest.splitlines():
        m = re.match(r"^##\s+([a-z])\.", line)
        if m:
            sec = m.group(1)
        m = re.match(r"^\s*-\s*(.+?):\s*UNKNOWN\s*[—-]+\s*needs\s+(.+)$", line)
        if m:
            out.append((sec, m.group(1).strip(), m.group(2).strip()))
    return out


# --- per-tip checks -------------------------------------------------------------------

def _chunks(tip):
    """(field, text) pieces; evidence items stay separate so a time and a coordinate pair up."""
    out = [("title", tip.get("title") or ""), ("known_at_time", tip.get("known_at_time") or "")]
    out += [("explanation", s) for s in re.split(r"(?<=[.!?])\s+", tip.get("explanation") or "")]
    out += [("evidence", e) for e in tip.get("evidence") or [] if isinstance(e, str)]
    return out


def _times(text):
    return [int(m.group(1)) * 60 + float(m.group(2)) for m in TIME_RE.finditer(text)]


def _dominant_dim(samples, t0, t1):
    counts = {}
    for t, d in samples:
        if t0 <= t <= t1 and d:
            counts[d] = counts.get(d, 0) + 1
    return (max(counts, key=counts.get), counts) if counts else (None, counts)


def _f3_match(f3, coord, times, t0, t1):
    """'near' (read within TIME_NEAR_S of a cited time), 'window', 'elsewhere' (+ time) or 'never'."""
    x, a, b = coord
    pair = b is None
    def hit(p):
        if pair:
            return abs(p[1] - x) <= COORD_TOL and abs(p[3] - a) <= COORD_TOL
        return abs(p[1] - x) <= COORD_TOL and abs(p[3] - b) <= COORD_TOL and \
            (p[2] is None or abs(p[2] - a) <= COORD_TOL)
    hits = [p[0] for p in f3 if hit(p)]
    if not hits:
        return "never", None
    if times and any(abs(h - t) <= TIME_NEAR_S for h in hits for t in times):
        return "near", None
    if any(t0 - TIME_NEAR_S <= h <= t1 + TIME_NEAR_S for h in hits):
        return ("window" if not times else "window-not-near"), min(hits, key=lambda h: min(abs(h - t) for t in times)
                                                                    if times else 0)
    return "elsewhere", hits[0]


def check_tip(tip, run, routes, cats, unknowns):
    C = []
    def add(level, check, msg):
        C.append({"level": level, "check": check, "msg": msg})

    t0, t1 = tip.get("t_start_s"), tip.get("t_end_s")
    end = run["end_s"]
    if not isinstance(t0, (int, float)) or not isinstance(t1, (int, float)):
        add("error", "time", "t_start_s/t_end_s missing or not numbers")
        return C
    # run bounds
    if t0 < 0 or (end and t1 > end + SLACK_S):
        add("error", "time", f"window {mmss(t0)}–{mmss(t1)} outside the run (0:00–{mmss(end)})")
    if t1 < t0:
        add("error", "time", "t_end_s < t_start_s")
    # named split
    split = next((s for s in run["splits"] if s["name"] == tip.get("split")), None)
    if split is None:
        add("error", "split", f"split {tip.get('split')!r} not detected in this run")
    else:
        s0, s1 = split["start_s"], split["end_s"]
        if not (s0 - SLACK_S <= t0 <= s1 + SLACK_S):
            add("error", "split", f"t_start {mmss(t0)} is not inside split {split['name']} ({mmss(s0)}–{mmss(s1)})")
        if t1 > s1 + SLACK_S:
            spans = [s["name"] for s in run["splits"] if s["start_s"] < t1 and s["end_s"] > s1]
            add("warn", "split", f"window runs past the end of {split['name']} ({mmss(s1)}) into {', '.join(spans)} "
                                 f"— a pattern tip across splits, or a wrong split/time")
    # dimension (samples.csv)
    dom, counts = _dominant_dim(run["samples"], t0, max(t1, t0 + 1))
    want = SPLIT_DIMS.get(tip.get("split"), set())
    if dom and want and dom not in want:
        add("warn", "dimension", f"samples.csv: window is mostly {dom} {counts}, split {tip.get('split')} "
                                 f"expects {'/'.join(sorted(want))}")
    # cited times
    for field, text in _chunks(tip):
        for t in _times(text):
            if end and t > end + SLACK_S:
                lvl = "error" if field in ("evidence", "known_at_time") else "warn"
                add(lvl, "time", f"{field}: {mmss(t)} is past the run end {mmss(end)}"
                                 + ("" if lvl == "error" else " (or it is a duration)"))
    kat_times = [t for t in _times(tip.get("known_at_time") or "") if not (end and t > end + SLACK_S)]
    late = [t for t in kat_times if t > t0 + 5]
    if late:
        add("warn", "known-at-time", f"known_at_time cites {', '.join(mmss(t) for t in late)}, after the tip "
                                     f"starts ({mmss(t0)}) — is that information really known at the decision?")
    if HEDGES.search(tip.get("known_at_time") or ""):
        add("warn", "known-at-time", "known_at_time leans on a non-observation source: "
                                     f"\"{HEDGES.search(tip['known_at_time']).group(0)}\"")
    # coordinates vs f3.csv
    if run["f3"]:
        for field, text in _chunks(tip):
            times = [t for t in _times(text) if t0 - 60 <= t <= t1 + 60]   # others are usually durations
            for m in COORD_RE.finditer(text):
                coord = (float(m.group(1)), float(m.group(2)), _float(m.group(3)))
                where, at = _f3_match(run["f3"], coord, times, t0, t1)
                label = m.group(0)
                if where == "never":
                    add("warn", "position", f"{field}: {label} never read in f3.csv (±{COORD_TOL:.0f} blocks) — "
                                            "an estimate/derived value, or wrong")
                elif where == "window-not-near":
                    add("warn", "position", f"{field}: {label} read in the tip window but not within "
                                            f"±{TIME_NEAR_S:.0f}s of the cited time(s) "
                                            f"{', '.join(mmss(t) for t in times)} (nearest read {mmss(at)})")
                elif where == "elsewhere":
                    add("info", "position", f"{field}: {label} read in f3.csv at {mmss(at)}, outside the tip window")
    else:
        add("info", "position", "f3.csv absent: coordinates unverified")
    # items vs hotbar.csv
    mentioned, hotbar_claim = {}, set()
    for field, text in _chunks(tip):
        for name, rx in ITEM_RE.items():
            if re.search(rx, text, re.I):
                mentioned.setdefault(name, []).extend(t for t in _times(text) if t0 - 60 <= t <= t1 + 60)
                if re.search(r"hotbar|slot \d", text, re.I):
                    hotbar_claim.add(name)
    if mentioned and run["hotbar"] is None:
        add("info", "items", f"hotbar.csv absent: item claims unverified ({', '.join(sorted(mentioned))})")
    elif mentioned:
        hb = run["hotbar"]
        for name, times in sorted(mentioned.items()):
            pred = ITEMS[name]
            seen = [t for t, item in hb if any(pred(p) for p in item.split("|"))]
            near = [t for t in times if any(t - 15 <= s <= t + 2 for s in seen)]
            lvl = "warn" if name in hotbar_claim else "info"
            if not seen:
                add(lvl, "items", f"'{name}' never read in the hotbar"
                                  + (" although the tip says hotbar" if lvl == "warn" else " (inventory-only, or wrong)"))
            elif times and not near:
                add(lvl, "items", f"'{name}' not in the hotbar near the cited time(s) "
                                     f"{', '.join(mmss(t) for t in times)}; seen {mmss(seen[0])}–{mmss(seen[-1])}")
            elif not times and not any(t0 - 30 <= s <= t1 for s in seen):
                add("info", "items", f"'{name}' not in the hotbar during the tip window "
                                     f"(seen {mmss(seen[0])}–{mmss(seen[-1])})")
    # ids
    ref = tip.get("reference_route")
    btype = (run["ctx"].get("bastion") or "").lower()
    if ref:
        r = routes.get(ref)
        if r is None:
            add("error", "reference_route", f"{ref!r} is not a route id in knowledge/routes.md")
        elif btype and r["type"] != btype:
            add("error", "reference_route", f"{ref!r} is a {r['type']} route but this bastion is {btype}")
    elif tip.get("split") == "found_bastion" and tip.get("scope") == "macro":
        same = sorted(i for i, r in routes.items() if not btype or r["type"] == btype)
        if same:
            add("warn", "reference_route", f"bastion macro tip without reference_route; routes.md has "
                                           f"{btype or 'bastion'} routes: {', '.join(same)}")
    for key, val in (("catalogue_id", tip.get("catalogue_id")),
                     ("disagrees_with_catalogue", (tip.get("disagrees_with_catalogue") or {}).get("id"))):
        if val and val not in cats:
            add("error", key, f"{val!r} is not an id in knowledge/mistakes.md")
    # resources: building blocks in the hotbar around t_start vs the route's flammable variant
    if ref and ref in routes and run["hotbar"] is not None:
        kinds = {}
        for t, item in run["hotbar"]:
            if t0 - 30 <= t <= t0 + 30:
                c = block_kind(item)
                if c:
                    kinds.setdefault(c, set()).add(item)
        flam_route = "flammable" in ref
        if kinds and not flam_route and set(kinds) == {"flammable"}:
            add("warn", "resources", f"{ref!r} is the normal variant but the hotbar around {mmss(t0)} has only "
                                     f"flammable blocks ({', '.join(sorted(kinds['flammable'])[:3])})")
        elif kinds and flam_route and "nonflammable" in kinds:
            add("info", "resources", f"{ref!r} is the flammable variant; hotbar around {mmss(t0)} also has "
                                     f"non-flammable blocks ({', '.join(sorted(kinds['nonflammable']))})")
        elif not kinds:
            add("info", "resources", f"no building blocks read in the hotbar around {mmss(t0)}")
    # rampart knowledge vs bastion.json
    b = run["bastion"]
    if b:
        vis = b.get("visual_summary") or {}
        labels = ((b.get("f3_labels") or {}).get("ramparts")) or {}
        for sent in re.split(r"(?<=[.;])\s+", tip.get("known_at_time") or ""):
            low = sent.lower()
            if re.search(r"\bno\b|unknown|none|not (?:seen|visible)|neither", low):
                continue
            for side in ("left", "right"):
                m = re.search(rf"\b{side}\b[^.;]*?\b(triple|single)\b", low)
                if not m:
                    continue
                known_at = (vis.get(side) or {}).get("known_at")
                if known_at is None or known_at > t0 + SLACK_S:
                    lab = labels.get(side) or {}
                    add("warn", "rampart-knowledge",
                        f"known_at_time claims the {side} rampart is {m.group(1)}, but the bastion classifier has no "
                        f"sighting by {mmss(t0)} (known_at={known_at}); F3 label '{lab.get('type', '?')}' is from "
                        f"{mmss(lab.get('t'))} (hindsight: player stood there). Needs a frame on the approach/chalice.")
    # claims about digest-UNKNOWN fields
    text = " ".join(t for _, t in _chunks(tip) if _ != "evidence")
    tool_ev = [e for e in tip.get("evidence") or [] if TOOL_EVIDENCE.search(e)]
    for sec, label, reader in unknowns:
        key = max((k for k in UNKNOWN_TOPICS if label.startswith(k)), key=len, default=None)
        if key is None:
            continue
        if key == "Actions" and tip.get("split") != "found_bastion":
            continue
        hits = sorted({m.group(0) for rx in UNKNOWN_TOPICS[key] for m in re.finditer(rx, text, re.I)})
        if not hits:
            continue
        if tool_ev:
            add("info", "unknown-field", f"digest {sec} '{label}' is UNKNOWN (needs {reader}); tip talks about it "
                                         f"({', '.join(hits)}) backed by tool evidence: {'; '.join(tool_ev[:2])}"
                                         " — check the frames really show it")
        else:
            add("warn", "unknown-field", f"digest {sec} '{label}' is UNKNOWN (needs {reader}), but the tip makes "
                                         f"claims about it ({', '.join(hits)}) with digest-only evidence")
    return C


def run_checks(run_dir, tips_file):
    run = load_run(run_dir)
    data = json.loads(Path(tips_file).read_text())
    if isinstance(data, list):
        data = {"tips": data}
    routes = {r["id"]: r for r in route_lib.load_routes()[0]}
    cats = catalogue_ids()
    unknowns = digest_unknowns(read_digest(run_dir))
    out = {"run_id": run["id"], "tips_file": str(tips_file),
           "generated": _dt.datetime.now().isoformat(timespec="seconds"),
           "run_end_s": run["end_s"],
           "splits": [{"name": s["name"], "start": mmss(s["start_s"]), "end": mmss(s["end_s"])} for s in run["splits"]],
           "data": {"f3_reads": len(run["f3"]), "hotbar_csv": run["hotbar"] is not None,
                    "bastion_json": run["bastion"] is not None},
           "schema_errors": validate(data, load_schema()), "tips": []}
    for tip in data.get("tips") or []:
        if not isinstance(tip, dict):
            continue
        checks = check_tip(tip, run, routes, cats, unknowns)
        order = {"error": 0, "warn": 1, "info": 2}
        checks.sort(key=lambda c: order[c["level"]])
        out["tips"].append({"id": tip.get("id"), "title": tip.get("title"), "split": tip.get("split"),
                            "scope": tip.get("scope"), "checks": checks,
                            "counts": {lv: sum(c["level"] == lv for c in checks) for lv in order}})
    out["bastion_cv"] = bastion_context(run)
    return out, data


def bastion_context(run):
    b = run["bastion"]
    if not b:
        return None
    vis = b.get("visual_summary") or {}
    labels = ((b.get("f3_labels") or {}).get("ramparts")) or {}
    return {side: {"visual_known_at": (vis.get(side) or {}).get("known_at"),
                   "visual_type": (vis.get(side) or {}).get("type"),
                   "frames_visible": (vis.get(side) or {}).get("frames_visible"),
                   "hindsight_f3_type": (labels.get(side) or {}).get("type"),
                   "hindsight_f3_t": (labels.get(side) or {}).get("t")} for side in ("left", "right")}


def checks_markdown(res):
    L = [f"Run end {mmss(res['run_end_s'])}. Data: f3 reads {res['data']['f3_reads']}, "
         f"hotbar.csv {'yes' if res['data']['hotbar_csv'] else 'NO (item claims unverified)'}, "
         f"bastion.json {'yes' if res['data']['bastion_json'] else 'no'}."]
    L.append("Splits: " + "; ".join(f"{s['name']} {s['start']}–{s['end']}" for s in res["splits"]))
    if res["schema_errors"]:
        L.append("Schema errors: " + "; ".join(res["schema_errors"]))
    bc = res.get("bastion_cv")
    if bc:
        for side, v in bc.items():
            L.append(f"Bastion CV {side} rampart: visual sighting {v['visual_known_at']} ({v['visual_type']}, "
                     f"{v['frames_visible']} frames); HINDSIGHT F3 label {v['hindsight_f3_type']} at "
                     f"{mmss(v['hindsight_f3_t']) if v['hindsight_f3_t'] is not None else '?'} "
                     "(grading only — never as known-at-time)")
    for tip in res["tips"]:
        c = tip["counts"]
        L.append(f"\n### {tip['id']} — {tip['title']}  ({c['error']} error, {c['warn']} warn, {c['info']} info)")
        L += [f"- **{x['level']}** [{x['check']}] {x['msg']}" for x in tip["checks"]] or ["- (no findings)"]
    return "\n".join(L)


# --- critic-pack ----------------------------------------------------------------------

def approved_lessons():
    path = COACH_DIR / "lessons.md"
    return path.read_text() if path.is_file() else "(no approved lessons file)"


def critic_pack(run_dir, tips_file):
    run_dir = Path(run_dir)
    res, data = run_checks(run_dir, tips_file)
    (run_dir / "critic_checks.json").write_text(json.dumps(res, indent=2) + "\n")
    parts = [(COACH_DIR / "critic_prompt.md").read_text().replace("<RUN_ID>", run_dir.name),
             "# Rubric: coach/rubric.md\n\n" + (COACH_DIR / "rubric.md").read_text(),
             "# Approved lessons: coach/lessons.md\n\n" + approved_lessons(),
             "# Output schema for revised_tips: coach/schema.json\n\n```json\n"
             + (COACH_DIR / "schema.json").read_text().strip() + "\n```",
             read_digest(run_dir),
             f"# Coach tips under review ({tips_file})\n\n```json\n" + json.dumps(data, indent=2) + "\n```",
             "# Automatic evidence checks (runs/" + run_dir.name + "/critic_checks.json)\n\n" + checks_markdown(res)]
    text = "\n\n---\n\n".join(p.strip() for p in parts) + "\n"
    out = run_dir / "critic_prompt.md"
    out.write_text(text, encoding="utf-8")
    for tip in res["tips"]:
        c = tip["counts"]
        print(f"  {tip['id']}: {c['error']} error, {c['warn']} warn, {c['info']} info — {tip['title']}")
    print(f"Wrote {run_dir / 'critic_checks.json'} and {out}: {len(text)} chars, ~{len(text) // 4} tokens")
    return out


# --- add-lessons ----------------------------------------------------------------------

RUN_SPECIFIC = re.compile(r"\b\d{1,2}:[0-5]\d\b|\(\s*-?\d+\s*,\s*-?\d+")


def _parse_lessons(text):
    """Critic JSON (whole reply, a ```json block, {"proposed_lessons": [...]}, or a list) or '- ' bullets."""
    m = re.search(r"```json\s*(.*?)```", text, re.S)
    blob = m.group(1) if m else text
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None, [ {"lesson": b.strip()} for b in re.findall(r"^\s*[-*]\s+(.+)$", text, re.M)]
    run_id = data.get("run_id") if isinstance(data, dict) else None
    items = data.get("proposed_lessons", []) if isinstance(data, dict) else data
    out = []
    for it in items:
        out.append({"lesson": it} if isinstance(it, str) else it)
    return run_id, out


def add_lessons(lessons_file, run_id=None, force=False):
    run_from_file, lessons = _parse_lessons(Path(lessons_file).read_text())
    run_id = run_id or run_from_file or "?"
    path = COACH_DIR / "pending_lessons.md"
    existing = path.read_text() if path.is_file() else "# Pending lessons (awaiting learner approval)\n"
    keep, skipped = [], []
    for it in lessons:
        txt = (it.get("lesson") or "").strip()
        if not txt or txt in existing:
            continue
        if not force and (RUN_SPECIFIC.search(txt) or (run_id != "?" and run_id in txt)):
            skipped.append(txt)
            continue
        keep.append(it)
    if keep:
        today = _dt.date.today().isoformat()
        L = [f"\n## {today} — source run: {run_id} (critic, file {Path(lessons_file).name})"]
        for it in keep:
            item = f" (rubric {it['rubric_item']})" if it.get("rubric_item") is not None else ""
            why = f"\n  - why: {it['why']}" if it.get("why") else ""
            L.append(f"- [ ]{item} {it['lesson'].strip()}{why}")
        path.write_text(existing.rstrip("\n") + "\n" + "\n".join(L) + "\n")
    print(f"Appended {len(keep)} lesson(s) to {path}" + (f"; skipped {len(skipped)} that look run-specific "
          "(timestamps/coordinates/run id; --force to add):" if skipped else ""))
    for s in skipped:
        print(f"  - {s}")


# --- golden-score ---------------------------------------------------------------------

def canon_route(text):
    """Route id / phrase -> canonical bridge route name, or None."""
    t = (text or "").lower().replace("-", " ").replace("_", " ")
    t = re.sub(r"\b(bridge|chalice|flammable|leaves|wood|version)\b", " ", t)
    t = " ".join(t.split())
    if re.search(r"left dk (to|→|->|then) cs", t):
        return "left dk → cs"
    for name, rx in (("soog", r"\bsoog\b"), ("left dk", r"\bleft dk\b"), ("right dk", r"\bright dk\b"),
                     ("cs", r"\bcs\b")):
        if re.search(rx, t):
            return name
    return None


def golden_expected(run_id):
    if not GOLDEN_README.is_file():
        return None, []
    text = GOLDEN_README.read_text()
    m = re.search(rf"(?ms)^## {re.escape(run_id)}\b.*?(?=^## |\Z)", text)
    if not m:
        return None, []
    sec = m.group(0)
    notes = [ln.strip("- ").strip() for ln in sec.splitlines()[1:] if ln.strip().startswith("-")]
    exp = None
    for ln in sec.splitlines():
        if "table row" in ln.lower() or "expected" in ln.lower():
            r = re.search(r"(?:→|->)\s*([^.;()]+)", ln)
            exp = canon_route(r.group(1)) if r else exp
            if exp:
                break
    m = re.search(r"(?i)expected routes? confirmed:\s*([^.(]+)", sec)
    if exp is None and m:
        exp = canon_route(m.group(1))
    return exp, notes


def coach_route(tips):
    """Recommended route = the best-ranked bastion macro tip's reference_route, else its title."""
    cand = sorted((t for t in tips if t.get("split") == "found_bastion" and t.get("scope") == "macro"),
                  key=lambda t: t.get("severity_rank", 99))
    for t in cand:
        r = canon_route(t.get("reference_route")) or canon_route(t.get("title"))
        if r:
            return r, t.get("id")
    return None, None


def golden_score(run_dir, tips_file):
    run_dir = Path(run_dir)
    rid = run_dir.name
    data = json.loads(Path(tips_file).read_text())
    tips = sorted(data["tips"] if isinstance(data, dict) else data, key=lambda t: t.get("severity_rank", 99))
    exp, notes = golden_expected(rid)
    print(f"Golden check — {rid} — {tips_file}")
    lines = []
    for t in tips:
        lines.append(f"[ ] {t.get('id')} #{t.get('severity_rank')} {t.get('split')}/{t.get('scope')} "
                     f"{mmss(t.get('t_start_s'))}–{mmss(t.get('t_end_s'))} ~{t.get('est_seconds_lost')}s "
                     f"{t.get('confidence')}: {t.get('title')}")
    print("\n".join(lines))
    got, tid = coach_route(tips)
    if exp:
        verdict = "MATCH" if got == exp else ("NO ROUTE PARSED" if got is None else "MISMATCH")
        print(f"Bastion route: expected {exp} | coach {got or '?'}" + (f" ({tid})" if tid else "") + f" → {verdict}")
    elif not notes:
        print("Bastion route: no golden entry for this run")
    else:
        print(f"Bastion route: golden entry has no parseable expected route | coach {got or '?'}")
    if not notes:
        return
    scores = GOLDEN_README.parent / "scores" / f"{rid}.md"
    if not scores.is_file():
        scores.parent.mkdir(parents=True, exist_ok=True)
        body = [f"# Golden scores — {rid}", "",
                "Score each tip: correct (Y/N/partial), useful (1–5), verdict you'd give (keep/revise/drop), note.",
                "Append one section per tips file you score.", ""]
        scores.write_text("\n".join(body) + "\n")
    if f"— {tips_file}\n" in scores.read_text():
        print(f"Score section for {tips_file} already in {scores}")
        return
    with open(scores, "a") as f:
        f.write(f"\n## {_dt.date.today().isoformat()} — {tips_file}\n"
                f"Route: expected {exp or '?'} | coach {got or '?'}\n\n"
                "| tip | title | correct | useful | verdict | note |\n|---|---|---|---|---|---|\n"
                + "".join(f"| {t.get('id')} | {t.get('title')} |  |  |  |  |\n" for t in tips))
    print(f"Score template appended to {scores}")
