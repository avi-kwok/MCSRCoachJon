"""Score analyzed runs against hand-made answer keys.

For every run folder that has both `truth.csv` (written by a person looking at
the frames) and `analysis.json` (written by the analyzer), compare:

* our splits: signed error = detected - truth (s); |error| <= tolerance is a hit,
  outside it is "off", a truth split with no detection is a miss, a detected
  split the truth doesn't list is a false positive (FP);
* the final time (exact ms match) and the result (win/loss);
* the opponent's splits, same as ours but with a looser tolerance (the panel is
  only read every 0.5 s and can be covered).

truth.csv columns: kind,name,time,notes
    kind  = split | final | opponent | meta
    time  = VIDEO time m:ss.s (blank = unknown, not scored)
    notes = free text; notes starting with "uncertain" mark a truth value that
            is only known to lie in an interval - it is scored but reported
            separately (not counted in hit rate / mean |error|).
    meta,status,draft,... flags an answer key nobody has verified yet.

No computer vision here - pure data, so it is cheap to rerun after every change.
"""

import csv
import json
from pathlib import Path

SPLITS = ["overworld", "entered_nether", "found_bastion", "found_fortress",
          "finding_stronghold", "found_stronghold", "entered_end"]
SHORT = {"overworld": "ow", "entered_nether": "nether", "found_bastion": "bastion",
         "found_fortress": "fortress", "finding_stronghold": "blind",
         "found_stronghold": "sh", "entered_end": "end"}


def parse_time(text):
    """'m:ss.s', 'mm:ss.mmm', 'h:mm:ss' or seconds -> float seconds, None if blank."""
    text = (text or "").strip()
    if not text:
        return None
    seconds = 0.0
    for part in text.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def fmt_time(seconds):
    if seconds is None:
        return "-"
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def read_truth(path):
    truth = {"status": None, "splits": {}, "opponent": {}, "final_time_ms": None, "result": None}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            kind = (row.get("kind") or "").strip().lower()
            name = (row.get("name") or "").strip()
            raw = (row.get("time") or "").strip()
            notes = (row.get("notes") or "").strip()
            if kind == "meta" and name == "status":
                truth["status"] = raw.lower() or None
            elif kind in ("split", "opponent"):
                truth["splits" if kind == "split" else "opponent"][name] = {
                    "t": parse_time(raw), "uncertain": notes.lower().startswith("uncertain"), "notes": notes}
            elif kind == "final" and name == "final_time" and raw:
                truth["final_time_ms"] = round(parse_time(raw) * 1000)
            elif kind == "final" and name == "result" and raw:
                truth["result"] = raw.lower()
    return truth


def detected_splits(analysis):
    """Our splits {name: start_s}, or None if the run predates split detection (no key)."""
    if "splits" not in analysis:
        return None
    return {s["name"]: s["start_s"] for s in analysis["splits"] or [] if "start_s" in s}


def detected_opponent(analysis):
    """Opponent splits {name: t_s}, or None if the run has no opponent data."""
    opp = analysis.get("opponent")
    if not opp:
        return None
    return {s["name"]: s["t_s"] for s in opp.get("splits") or [] if "t_s" in s}


def compare(truth_rows, detected, tolerance):
    """Per-split outcome dicts, in SPLITS order (plus any unknown names at the end)."""
    names = SPLITS + sorted((set(truth_rows) | set(detected or {})) - set(SPLITS))
    out = {}
    for name in names:
        t = truth_rows.get(name)
        d = None if detected is None else detected.get(name)
        cell = {"truth_s": None if t is None else t["t"], "detected_s": d, "error_s": None,
                "uncertain": bool(t and t["uncertain"])}
        if detected is None:
            cell["outcome"] = "no-data" if t and t["t"] is not None else "n/a"
        elif t is None:
            cell["outcome"] = "fp" if d is not None else "n/a"
        elif t["t"] is None:            # truth says "happened but time unknown" -> not scored
            cell["outcome"] = "n/a"
        elif d is None:
            cell["outcome"] = "miss"
        else:
            cell["error_s"] = round(d - t["t"], 2)
            cell["outcome"] = "hit" if abs(cell["error_s"]) <= tolerance + 1e-9 else "off"
        if cell["outcome"] == "n/a" and t is None and d is None:
            continue
        out[name] = cell
    return out


def summarize(cells):
    """Counts over certain truth rows; uncertain ones are tallied separately."""
    certain = [c for c in cells.values() if not c["uncertain"]]
    scored = [c for c in certain if c["outcome"] in ("hit", "off", "miss")]
    errors = [abs(c["error_s"]) for c in certain if c["error_s"] is not None]
    hits = sum(c["outcome"] == "hit" for c in certain)
    return {
        "scored": len(scored),
        "hits": hits,
        "off": sum(c["outcome"] == "off" for c in certain),
        "misses": sum(c["outcome"] == "miss" for c in certain),
        "fps": sum(c["outcome"] == "fp" for c in cells.values()),
        "hit_rate": round(hits / len(scored), 3) if scored else None,
        "mean_abs_error_s": round(sum(errors) / len(errors), 2) if errors else None,
        "uncertain": sum(c["uncertain"] and c["outcome"] in ("hit", "off", "miss") for c in cells.values()),
        "uncertain_hits": sum(c["uncertain"] and c["outcome"] == "hit" for c in cells.values()),
    }


def evaluate_run(run_dir, tolerance, opp_tolerance):
    truth = read_truth(run_dir / "truth.csv")
    analysis = json.loads((run_dir / "analysis.json").read_text())
    run = analysis.get("run") or {}

    splits = compare(truth["splits"], detected_splits(analysis), tolerance)
    opp_detected = detected_opponent(analysis)
    opponent = compare(truth["opponent"], opp_detected, opp_tolerance) if truth["opponent"] else {}

    det_ms, true_ms = run.get("final_time_ms"), truth["final_time_ms"]
    final = {"truth_ms": true_ms, "detected_ms": det_ms,
             "outcome": "n/a" if true_ms is None else "miss" if det_ms is None
             else "hit" if det_ms == true_ms else "wrong"}
    det_res, true_res = run.get("result"), truth["result"]
    result = {"truth": true_res, "detected": det_res,
              "outcome": "n/a" if true_res is None else "miss" if det_res in (None, "unknown")
              else "hit" if det_res == true_res else "wrong"}

    return {"run": run_dir.name, "truth_status": truth["status"], "draft": truth["status"] == "draft",
            "splits": splits, "splits_summary": summarize(splits),
            "final_time": final, "result": result,
            "opponent": opponent, "opponent_summary": summarize(opponent) if opponent else None,
            "opponent_data": opp_detected is not None}


def cell_text(cell):
    o = cell["outcome"]
    if o in ("hit", "off"):
        text = f"{cell['error_s']:+.1f}" + ("" if o == "hit" else "!")
    else:
        text = {"miss": "MISS", "fp": "FP", "no-data": "nodata", "n/a": "."}[o]
    return text + ("?" if cell["uncertain"] else "")


def print_table(title, results, key, columns):
    rows = [r for r in results if r[key]]
    if not rows:
        return
    width = max([4] + [len(r["run"]) + (2 if r["draft"] else 0) for r in rows])
    labels = [SHORT.get(c, c)[:8] for c in columns] + (["final", "result"] if key == "splits" else [])
    header = f"{'run':<{width}} " + " ".join(f"{label:>8}" for label in labels)
    print(f"\n{title}\n{header}\n{'-' * len(header)}")
    for r in rows:
        name = r["run"] + (" *" if r["draft"] else "")
        cells = [cell_text(r[key][c]) if c in r[key] else "." for c in columns]
        if key == "splits":
            cells += [r["final_time"]["outcome"].upper() if r["final_time"]["outcome"] != "hit" else "ok",
                      r["result"]["outcome"].upper() if r["result"]["outcome"] != "hit" else "ok"]
        print(f"{name:<{width}} " + " ".join(f"{c:>8}" for c in cells))


def fmt_summary(s):
    if not s or not s["scored"] and not s["fps"]:
        return "nothing scored"
    rate = "-" if s["hit_rate"] is None else f"{100 * s['hit_rate']:.0f}%"
    mae = "-" if s["mean_abs_error_s"] is None else f"{s['mean_abs_error_s']:.2f}s"
    text = (f"hits {s['hits']}/{s['scored']} ({rate}), mean |err| {mae}, "
            f"off {s['off']}, misses {s['misses']}, FPs {s['fps']}")
    if s["uncertain"]:
        text += f"; uncertain truth: {s['uncertain_hits']}/{s['uncertain']} within tolerance"
    return text


def total(summaries):
    summaries = [s for s in summaries if s]
    keys = ("scored", "hits", "off", "misses", "fps", "uncertain", "uncertain_hits")
    out = {k: sum(s[k] for s in summaries) for k in keys}
    out["hit_rate"] = round(out["hits"] / out["scored"], 3) if out["scored"] else None
    # mean |error| weighted by the number of matched splits in each run
    pairs = [(s["mean_abs_error_s"], s["hits"] + s["off"]) for s in summaries if s["mean_abs_error_s"] is not None]
    n = sum(k for _, k in pairs)
    out["mean_abs_error_s"] = round(sum(m * k for m, k in pairs) / n, 2) if n else None
    return out


def evaluate(runs_dir, tolerance=1.0, opp_tolerance=3.0, out_path=None):
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        raise SystemExit(f"No such folder: {runs_dir}")
    candidates = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    results, skipped = [], []
    for d in candidates:
        has_truth, has_analysis = (d / "truth.csv").is_file(), (d / "analysis.json").is_file()
        if has_truth and has_analysis:
            try:
                results.append(evaluate_run(d, tolerance, opp_tolerance))
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as err:
                skipped.append((d.name, f"could not evaluate: {err}"))
        elif has_truth or has_analysis:
            skipped.append((d.name, "no analysis.json yet" if has_truth else "no truth.csv"))

    print(f"Evaluated {len(results)} run(s) in {runs_dir}  (tolerance {tolerance:g}s, opponent {opp_tolerance:g}s)")
    print("cells: signed error detected-truth in s; '!' outside tolerance; MISS not detected; "
          "FP detected but not in truth; ? = uncertain truth; * = draft truth")
    print_table("Our splits + final time + result", results, "splits", SPLITS)
    print_table("Opponent splits", results, "opponent", SPLITS)

    print()
    for r in results:
        flag = "  [truth is a DRAFT - verify it]" if r["draft"] else ""
        print(f"{r['run']}{flag}")
        print(f"  splits:   {fmt_summary(r['splits_summary'])}")
        ft = r["final_time"]
        if ft["outcome"] != "n/a":
            print(f"  final:    {ft['outcome']} (truth {ft['truth_ms']} ms, detected {ft['detected_ms']} ms);"
                  f" result {r['result']['outcome']} (truth {r['result']['truth']}, detected {r['result']['detected']})")
        if r["opponent"]:
            note = "" if r["opponent_data"] else " (analysis.json has no opponent data)"
            print(f"  opponent: {fmt_summary(r['opponent_summary'])}{note}")
    for name, why in skipped:
        print(f"{name}: skipped - {why}")

    overall = {"splits": total([r["splits_summary"] for r in results]),
               "opponent": total([r["opponent_summary"] for r in results]),
               "final_time_exact": sum(r["final_time"]["outcome"] == "hit" for r in results),
               "result_correct": sum(r["result"]["outcome"] == "hit" for r in results),
               "runs": len(results), "draft_runs": [r["run"] for r in results if r["draft"]]}
    if results:
        print(f"\nOVERALL splits:   {fmt_summary(overall['splits'])}")
        print(f"OVERALL opponent: {fmt_summary(overall['opponent'])}")
        print(f"OVERALL final time exact {overall['final_time_exact']}/{len(results)}, "
              f"result correct {overall['result_correct']}/{len(results)}")
        if overall["draft_runs"]:
            print(f"Draft truth (unverified): {', '.join(overall['draft_runs'])}")

    out_path = Path(out_path) if out_path else runs_dir / "evaluation.json"
    out_path.write_text(json.dumps({"tolerance_s": tolerance, "opponent_tolerance_s": opp_tolerance,
                                    "overall": overall, "runs": results,
                                    "skipped": [{"run": n, "reason": w} for n, w in skipped]}, indent=2) + "\n")
    print(f"\nWrote {out_path}")
    return results
