"""Macro splits from the per-sample signals (no CV here - works from the CSVs).

Inputs (all written by `analyze`, so `rebuild-json` can redo this):

* toast observations (toasts.csv): every sample where an advancement toast box
  was found, with its slot, whether it was fully slid in, and the recognised
  title (if it was read);
* the per-sample raw dimension label (samples.csv `dimension`) and the
  reset-dialog flag (samples.csv `reset`).

Steps:

1. **Toast tracks**: observations in the same toast slot that follow each other
   (gaps <= TOAST_GAP_S) are one toast on screen. A toast that slides out while
   the next slides into the same slot shows as full -> partial -> full, which
   splits the track. A track's title is the majority of its reads; its time is
   its *first* observation (the toast appears within ~0.5 s of the event, even
   if it was only readable later - e.g. it popped up in a resized strip).
2. **World resets**: MCSR's "Are you sure you want to reset this world?" dialog,
   or an advancement title that shows up a second time (each advancement can
   only be earned once per world). Only toasts after the last reset count.
3. **Dimension timeline**: the raw labels are smoothed by a sliding majority
   vote and short stays are dropped, giving sustained overworld/nether/end
   stretches.
4. Splits: entered_nether / found_bastion / found_fortress / found_stronghold /
   entered_end from their toasts (dimension transitions as fallback for
   nether/end); finding_stronghold = first sustained nether -> overworld
   transition after the fortress (or bastion/nether entry). overworld = 0:00.
"""

import csv
from collections import Counter
from pathlib import Path

from . import config

SPLIT_ORDER = ["overworld", "entered_nether", "found_bastion", "found_fortress",
               "finding_stronghold", "found_stronghold", "entered_end"]
# Splits that must come after each other in a valid run (bastion and fortress
# can be done in either order, so they are only checked against the others).
SPLIT_RANK = {"overworld": 0, "entered_nether": 1, "found_bastion": 2, "found_fortress": 2,
              "finding_stronghold": 3, "found_stronghold": 4, "entered_end": 5}

TOAST_FIELDS = ["time_s", "window", "slot", "k", "full", "title", "score"]


def mmss(seconds):
    seconds = max(0.0, seconds)
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


# --- toasts.csv -----------------------------------------------------------

def write_toasts_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(TOAST_FIELDS)
        for r in rows:
            writer.writerow([f"{r['time_s']:.2f}", r["window"], r["slot"], f"{r['k']:.2f}",
                             int(r["full"]), r["title"] or "", f"{r['score']:.3f}"])


def read_toasts_csv(path):
    path = Path(path)
    if not path.is_file():
        return []
    with open(path, newline="") as f:
        return [{"time_s": float(r["time_s"]), "window": r["window"], "slot": int(r["slot"]),
                 "k": float(r["k"]), "full": r["full"] == "1", "title": r["title"] or None,
                 "score": float(r["score"])} for r in csv.DictReader(f)]


# --- 1. toast tracks ------------------------------------------------------

def toast_tracks(rows):
    """Group toast observations into on-screen toasts -> [{start, end, title, reads, score}]."""
    tracks, open_by_slot = [], {}
    for r in sorted(rows, key=lambda r: r["time_s"]):
        tr = open_by_slot.get(r["slot"])
        if tr is not None:
            gap = r["time_s"] - tr["end"]
            # full -> partial (slid out) -> full again = the next toast in this slot
            slid_out = tr["state"] == "out" and r["full"]
            if gap > config.TOAST_GAP_S or slid_out or r["time_s"] - tr["start"] > config.TOAST_MAX_SHOW_S:
                tr = None
        if tr is None:
            tr = {"start": r["time_s"], "end": r["time_s"], "slot": r["slot"], "titles": Counter(),
                  "best": {}, "state": "in", "first_read": None}
            tracks.append(tr)
            open_by_slot[r["slot"]] = tr
        tr["end"] = r["time_s"]
        if r["full"]:
            tr["state"] = "full"
        elif tr["state"] == "full":
            tr["state"] = "out"
        if r["title"]:
            tr["titles"][r["title"]] += 1
            tr["best"][r["title"]] = max(tr["best"].get(r["title"], 0.0), r["score"])
            if tr["first_read"] is None:
                tr["first_read"] = r["time_s"]
    out = []
    for tr in tracks:
        if not tr["titles"]:
            continue                      # never readable (too small / covered): unknown toast
        title, reads = tr["titles"].most_common(1)[0]
        prev = next((o for o in reversed(out) if o["title"] == title), None)
        if prev is not None and tr["start"] - prev["start"] <= config.TOAST_MAX_SHOW_S:
            # Same toast, track broken by a layout switch (e.g. full screen -> thin strip).
            prev["end"] = max(prev["end"], tr["end"])
            prev["reads"] += reads
            prev["score"] = max(prev["score"], tr["best"][title])
            continue
        out.append({"start": tr["start"], "end": tr["end"], "slot": tr["slot"], "title": title,
                    "reads": reads, "score": tr["best"][title], "first_read": tr["first_read"]})
    return out


# --- 2. resets ------------------------------------------------------------

def find_resets(samples, tracks, run_end):
    """Reset times: reset-dialog samples (end of each dialog stretch) + repeated advancements."""
    resets = []
    prev = None
    for s in samples:
        if s.time >= run_end:
            break
        if getattr(s, "reset", False):
            if prev is not None and s.time - prev <= 1.0 and resets and resets[-1][1] == "reset dialog":
                resets[-1] = (s.time, "reset dialog")
            else:
                resets.append((s.time, "reset dialog"))
            prev = s.time
    seen = {}
    for tr in tracks:
        if tr["start"] >= run_end:
            continue
        first = seen.get(tr["title"])
        if first is not None and not any(first < t < tr["start"] for t, _ in resets):
            # Earned twice with no reset seen in between -> the world was reset
            # before the second toast (which is in the new world).
            resets.append((tr["start"] - 0.01, f"'{title_of(tr['title'])}' earned again"))
            resets.sort()
        seen[tr["title"]] = tr["start"]
    return sorted(resets)


# --- 3. dimension timeline ------------------------------------------------

def dimension_stretches(samples, run_end):
    """Sustained dimension stretches [(start, end, dim)] from the raw per-sample labels."""
    labelled = [(s.time, s.dimension) for s in samples
                if s.time < run_end and getattr(s, "dimension", "") in ("overworld", "nether", "end")]
    if not labelled:
        return []
    half = config.DIMENSION_SMOOTH_S / 2
    smoothed, lo, hi, counts = [], 0, 0, Counter()
    for t, _ in labelled:                          # sliding majority over +-half seconds
        while hi < len(labelled) and labelled[hi][0] <= t + half:
            counts[labelled[hi][1]] += 1
            hi += 1
        while labelled[lo][0] < t - half:
            counts[labelled[lo][1]] -= 1
            lo += 1
        smoothed.append((t, counts.most_common(1)[0][0]))
    runs = []
    for t, d in smoothed:
        if runs and runs[-1][2] == d:
            runs[-1][1] = t
        else:
            runs.append([t, t, d])
    # Drop short stays (a dark cave looks like nether for a moment), then merge.
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            if r[1] - r[0] < config.DIMENSION_MIN_STAY_S:
                del runs[i]
                changed = True
                break
        merged = []
        for r in runs:
            if merged and merged[-1][2] == r[2]:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        runs = merged
    return [tuple(r) for r in runs]


def first_transition(stretches, src, dst, after):
    """Start of the first `dst` stretch that directly follows a `src` stretch, at or after `after`."""
    for prev, cur in zip(stretches, stretches[1:]):
        if prev[2] == src and cur[2] == dst and cur[0] >= after:
            return cur[0]
    return None


def first_stretch(stretches, dim, after):
    for s in stretches:
        if s[2] == dim and s[0] >= after:
            return s[0]
    return None


# --- 4. splits ------------------------------------------------------------

def title_of(name):
    return config.ADVANCEMENT_TITLES.get(name, name.replace("_", " ").title())


def build_splits(run, samples, toast_rows):
    """-> (splits, advancements). See the module docstring."""
    run_end = run["run_end_s"]
    tracks = [t for t in toast_tracks(toast_rows) if t["start"] < run_end]
    resets = find_resets(samples, tracks, run_end)
    last_reset = resets[-1][0] if resets else 0.0
    stretches = dimension_stretches(samples, run_end)

    advancements = [{"name": t["title"], "title": title_of(t["title"]), "t_s": round(t["start"], 2)}
                    for t in tracks]

    found = {}            # split -> (time, evidence)
    for split, adv in config.SPLIT_ADVANCEMENTS.items():
        for t in tracks:
            if t["title"] == adv and t["start"] >= last_reset:
                note = (f"'{title_of(adv)}' toast from {mmss(t['start'])}"
                        f" (read {t['reads']}x, first at {mmss(t['first_read'])}, score {t['score']:.2f})")
                found[split] = (t["start"], note)
                break

    def cross_check(time, dim_time, what):
        if dim_time is None:
            return f"; no sustained {what} in the dimension signal"
        return f"; dimension signal: {what} at {mmss(dim_time)} ({dim_time - time:+.1f}s)"

    nether_dim = first_transition(stretches, "overworld", "nether", last_reset)
    end_dim = first_stretch(stretches, "end", last_reset)
    if "entered_nether" in found:
        t, note = found["entered_nether"]
        found["entered_nether"] = (t, note + cross_check(t, nether_dim, "overworld -> nether"))
    elif nether_dim is not None:
        found["entered_nether"] = (nether_dim, f"no toast read; first sustained overworld -> nether at {mmss(nether_dim)}")
    if "entered_end" in found:
        t, note = found["entered_end"]
        found["entered_end"] = (t, note + cross_check(t, end_dim, "first End stretch"))
    elif end_dim is not None:
        found["entered_end"] = (end_dim, f"no toast read; first sustained End stretch at {mmss(end_dim)}")

    # finding_stronghold: leaving the nether after the nether goals ("blind" travel).
    nether_goals = [n for n in ("found_fortress", "found_bastion", "entered_nether") if n in found]
    if nether_goals:
        anchor_name = max(nether_goals, key=lambda n: found[n][0])     # the later of bastion/fortress
        anchor = found[anchor_name][0]
        t = first_transition(stretches, "nether", "overworld", anchor)
        if t is not None:
            limit = found.get("found_stronghold", (run_end, ""))[0]
            if t < limit:
                found["finding_stronghold"] = (t, f"first sustained nether -> overworld after "
                                                  f"{anchor_name.replace('_', ' ')} ({mmss(anchor)})")

    # Drop splits that contradict the run order (e.g. a misread toast).
    kept = {"overworld": (0.0, "video start (the match timer keeps running across seed resets)"
                         + (f"; world reset at {', '.join(f'{mmss(t)} ({why})' for t, why in resets)}"
                            if resets else ""))}
    for name in sorted(found, key=lambda n: found[n][0]):
        t, note = found[name]
        if all(SPLIT_RANK[name] >= SPLIT_RANK[k] for k, (tk, _) in kept.items() if tk <= t) and \
           all(SPLIT_RANK[name] <= SPLIT_RANK[k] for k, (tk, _) in kept.items() if tk > t):
            kept[name] = (t, note)

    if not toast_rows and not stretches:
        return [], advancements           # no split signals (e.g. analyzed before v1.3): nothing to show
    ordered = sorted(kept.items(), key=lambda kv: kv[1][0])
    splits = []
    for i, (name, (t, note)) in enumerate(ordered):
        end = ordered[i + 1][1][0] if i + 1 < len(ordered) else run_end
        splits.append({"name": name, "start_s": round(t, 2), "end_s": round(end, 2),
                       "source": "cv", "evidence": note})
    return splits, advancements
