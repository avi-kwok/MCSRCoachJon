"""Build analysis.json (the UI's input) from the analysis outputs.

Everything here works from plain data - samples, idle stretches and the run
facts in run.json - so `python -m vodreview rebuild-json <out>` can redo it
from the CSVs without running the computer-vision pass again.
"""

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .idle import Sample, Stretch
from .splits import SPLIT_ORDER, build_splits, read_toasts_csv  # noqa: F401  (SPLIT_ORDER re-exported)

ANALYSIS_VERSION = 1
MIN_SCREEN_RUN_S = 0.5      # screen runs shorter than this are flicker -> absorbed into a neighbour
MIN_SEGMENT_S = 1.0         # non-world screen runs shorter than this don't become segments
SCREEN_LABELS = {
    "world": "In world",
    "inventory": "Inventory open",
    "f3": "F3 debug screen",
    "resized": "Resized window",
    "pause": "Paused",
    "settings": "Settings open",
}
SCREEN_ORDER = ["world", "inventory", "f3", "resized", "pause", "settings"]


def mmss(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


# --- run.json -------------------------------------------------------------

def write_run_json(out_dir, *, video, duration_s, run_end_s, end_reason, result, sample_interval_s,
                   final_time_ms=None, final_time_text=None, recording_date=None, date_source=None):
    run = {
        "video": str(Path(video).resolve()),
        "duration_s": round(duration_s, 2),
        "run_end_s": round(run_end_s, 2),
        "end_reason": end_reason,
        "result": result,
        # Time read from the result screen "(MM:SS.mmm)". On a loss this is the
        # *winner's* time (that's what the screen shows).
        "final_time_ms": final_time_ms,
        "final_time_text": final_time_text,
        "recording_date": recording_date,
        "date_source": date_source,
        "sample_interval_s": sample_interval_s,
        "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_run_json(out_dir, run)
    return run


def save_run_json(out_dir, run):
    Path(out_dir, "run.json").write_text(json.dumps(run, indent=2) + "\n")


# --- detailed_segments.csv (user-authored) --------------------------------

def parse_clock(text):
    """'mm:ss', 'm:ss', 'mm:ss.s', 'h:mm:ss' or plain seconds -> float seconds (ValueError if bad)."""
    text = text.strip()
    if not text:
        raise ValueError("empty time")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"bad time {text!r}")
    seconds = float(parts[-1])
    if seconds < 0 or (len(parts) > 1 and seconds >= 60):
        raise ValueError(f"bad time {text!r}")
    for i, part in enumerate(reversed(parts[:-1]), 1):
        if not part.isdigit():
            raise ValueError(f"bad time {text!r}")
        seconds += int(part) * 60 ** i
    return seconds


def read_detailed_segments(path):
    """Read runs/<id>/detailed_segments.csv -> (segments, warnings).

    Columns: start,end,segment,notes. Rows that can't be parsed (bad time,
    end <= start, no name) are skipped with a warning instead of failing.
    """
    segments, warnings = [], []
    path = Path(path)
    if not path.is_file():
        return segments, warnings
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fields = {(name or "").strip().lower() for name in (reader.fieldnames or [])}
            if not {"start", "end", "segment"} <= fields:
                return [], [f"{path.name}: header must be start,end,segment,notes (got {reader.fieldnames})"]
            for line, row in enumerate(reader, 2):
                row = {(k or "").strip().lower(): (v or "").strip() if isinstance(v, str) else "" for k, v in row.items()}
                try:
                    start, end = parse_clock(row.get("start", "")), parse_clock(row.get("end", ""))
                    name = row.get("segment", "")
                    if not name:
                        raise ValueError("no segment name")
                    if end <= start:
                        raise ValueError(f"end {row['end']} is not after start {row['start']}")
                except ValueError as err:
                    warnings.append(f"{path.name} line {line}: {err} - skipped")
                    continue
                segments.append({"name": name, "start_s": round(start, 2), "end_s": round(end, 2),
                                 "notes": row.get("notes", "")})
    except (OSError, UnicodeDecodeError, csv.Error) as err:
        return [], [f"{path.name}: could not read ({err})"]
    segments.sort(key=lambda s: s["start_s"])
    return segments, warnings


# --- reading the CSVs back ------------------------------------------------

def read_samples_csv(path):
    # `dimension` / `reset` were added in v1.3; older files simply lack them.
    with open(path, newline="") as f:
        return [Sample(float(r["time_s"]), float(r["motion_pct"]), r["screen"], r["still"] == "1",
                       r.get("dimension") or "", r.get("reset") == "1")
                for r in csv.DictReader(f)]


def read_idle_csv(path):
    with open(path, newline="") as f:
        return [Stretch(float(r["start_s"]), float(r["end_s"])) for r in csv.DictReader(f)]


# --- screens --------------------------------------------------------------

def screen_runs(samples, sample_interval, run_end):
    """Contiguous runs of the per-sample screen label, as [start, end, screen] lists."""
    runs = []
    for s in samples:
        if s.time >= run_end:
            break
        end = min(s.time + sample_interval, run_end)
        if runs and runs[-1][2] == s.screen:
            runs[-1][1] = end
        else:
            if runs:
                runs[-1][1] = s.time          # close any gap between samples
            runs.append([s.time, end, s.screen])
    return runs


def _coalesce(runs):
    merged = []
    for run in runs:
        if merged and merged[-1][2] == run[2]:
            merged[-1][1] = run[1]
        else:
            merged.append(list(run))
    return merged


def smooth_runs(runs, min_len=MIN_SCREEN_RUN_S):
    """Absorb runs shorter than `min_len` into a neighbour (shortest first).

    A short run takes the label of its longer neighbour, then equal neighbours
    are merged - so world, inventory(0.2s), world becomes one world run.
    """
    runs = _coalesce(runs)
    while len(runs) > 1:
        i = min(range(len(runs)), key=lambda k: runs[k][1] - runs[k][0])
        if runs[i][1] - runs[i][0] >= min_len - 1e-9:
            break
        prev = runs[i - 1] if i > 0 else None
        nxt = runs[i + 1] if i + 1 < len(runs) else None
        target = max((n for n in (prev, nxt) if n), key=lambda n: n[1] - n[0])
        runs[i][2] = target[2]
        runs = _coalesce(runs)
    return runs


# --- tips -----------------------------------------------------------------

def tip(t_s, end_s, kind, title, text, est_loss_s=None):
    return {"t_s": round(t_s, 2), "end_s": round(end_s, 2), "kind": kind,
            "title": title, "text": text, "est_loss_s": est_loss_s}


def build_tips(run, samples, sample_interval, screens, stretches):
    run_end = run["run_end_s"]
    tips = []

    result = run.get("result")
    outcome = {"win": "Won", "loss": "Lost"}.get(result, "Ended")
    tips.append(tip(run_end, run_end, "stat", f"Run end {mmss(run_end)}",
                    f"{outcome} at {mmss(run_end)} ({run['end_reason']}).", None))

    total_idle = sum(st.duration for st in stretches)
    if stretches:
        tips.append(tip(stretches[0].start, stretches[0].end, "stat",
                        f"Idle {total_idle:.1f}s",
                        f"{len(stretches)} idle stretch{'es' if len(stretches) != 1 else ''} "
                        f"(still for at least {config.MIN_IDLE_SECONDS:.0f}s), {total_idle:.1f}s in total "
                        f"({100 * total_idle / run_end:.1f}% of the run).", round(total_idle, 1)))
    else:
        tips.append(tip(0, 0, "stat", "No idle time",
                        f"No idle stretches of {config.MIN_IDLE_SECONDS:.0f}s or longer before the run end.", None))

    counts = Counter(s.screen for s in samples if s.time < run_end)
    for screen in SCREEN_ORDER:
        seconds = counts.get(screen, 0) * sample_interval
        if seconds <= 0:
            continue
        visits = [r for r in screens if r["screen"] == screen]
        label = SCREEN_LABELS.get(screen, screen)
        pct = 100 * seconds / run_end
        if visits:
            longest = max(visits, key=lambda r: r["end_s"] - r["start_s"])
            length = longest["end_s"] - longest["start_s"]
            text = (f"{label} for {mmss(seconds)} ({pct:.1f}% of the run) across {len(visits)} "
                    f"visit{'s' if len(visits) != 1 else ''}; longest {mmss(length)} at {mmss(longest['start_s'])}.")
            t0, t1 = longest["start_s"], longest["end_s"]
        else:   # only flicker samples, all absorbed by smoothing
            text = f"{label} for {mmss(seconds)} ({pct:.1f}% of the run), only in brief flickers."
            t0 = t1 = 0
        tips.append(tip(t0, t1, "stat", f"{label} {mmss(seconds)} ({pct:.1f}%)", text))

    for i, st in enumerate(stretches, 1):
        tips.append(tip(st.start, st.end, "micro", f"Idle {st.duration:.1f}s",
                        f"Idle stretch {i}: nothing moved from {mmss(st.start)} to {mmss(st.end)}.",
                        round(st.duration, 1)))
    return tips


# --- analysis.json --------------------------------------------------------

def build_analysis(run, samples, stretches, toast_rows=()):
    sample_interval = run["sample_interval_s"]
    run_end = run["run_end_s"]
    screens = [{"start_s": round(a, 2), "end_s": round(b, 2), "screen": s}
               for a, b, s in smooth_runs(screen_runs(samples, sample_interval, run_end))]

    segments = [{"name": r["screen"], "start_s": r["start_s"], "end_s": r["end_s"], "source": "cv"}
                for r in screens if r["screen"] != "world" and r["end_s"] - r["start_s"] >= MIN_SEGMENT_S]
    segments += [{"name": "idle", "start_s": round(st.start, 2), "end_s": round(st.end, 2), "source": "cv"}
                 for st in stretches]
    segments.sort(key=lambda s: (s["start_s"], s["name"]))
    splits, advancements = build_splits(run, samples, list(toast_rows))

    return {
        "version": ANALYSIS_VERSION,
        "run": {
            "video": run["video"],
            "video_file": "video.mp4",
            "duration_s": run["duration_s"],
            "run_end_s": run_end,
            "end_reason": run["end_reason"],
            "result": run.get("result"),
            "final_time_ms": run.get("final_time_ms"),
            "final_time_text": run.get("final_time_text"),
            "recording_date": run.get("recording_date"),
            "date_source": run.get("date_source"),
            "analyzed_at": run["analyzed_at"],
        },
        "splits": splits,
        "advancements": advancements,
        "segments": segments,
        "screens": screens,
        "idle": [{"start_s": round(st.start, 2), "end_s": round(st.end, 2), "duration_s": round(st.duration, 2)}
                 for st in stretches],
        "tips": build_tips(run, samples, sample_interval, screens, stretches),
    }


def write_analysis_json(out_dir, run, samples, stretches, toast_rows=()):
    path = Path(out_dir, "analysis.json")
    path.write_text(json.dumps(build_analysis(run, samples, stretches, toast_rows), indent=2) + "\n")
    return path


def rebuild_json(out_dir):
    """Rebuild analysis.json from samples.csv + idle.csv + toasts.csv + run.json (no CV)."""
    out_dir = Path(out_dir)
    for name in ("run.json", "samples.csv", "idle.csv"):
        if not (out_dir / name).exists():
            raise SystemExit(f"Missing {out_dir / name} - run `python -m vodreview analyze` first.")
    run = json.loads((out_dir / "run.json").read_text())
    path = write_analysis_json(out_dir, run, read_samples_csv(out_dir / "samples.csv"),
                               read_idle_csv(out_dir / "idle.csv"), read_toasts_csv(out_dir / "toasts.csv"))
    print(f"Wrote {path}")
    return path
