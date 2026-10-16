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
3. **Portal transitions** (transition.py): every nether-portal trip shows the
   vanilla dirt loading screen (samples.csv `loading`); the first sample after
   it is the first rendered frame of the new dimension. A long purple
   portal-overlay stretch (`portal`) that ends without a sampled loading screen
   is a weaker candidate. Which dimension is on each side comes from the F3
   dimension line (strong) and the colour labels in the seconds before / after,
   and from the alternation overworld <-> nether when one side has no evidence.
4. **Dimension timeline** (fallback when no transition is seen): the raw labels
   are smoothed by a sliding majority vote and short stays are dropped, giving
   sustained overworld/nether/end stretches.
5. Splits: entered_nether = the overworld -> nether transition (its toast when
   no transition was seen); finding_stronghold = the first nether -> overworld
   transition after the nether goals (the "blind" travel); found_fortress = the
   first sustained moment the player stands on nether bricks (fortress.py,
   samples.csv `brick`), never later than the "A Terrible Fortress" toast,
   which is kept as `official_s`; found_bastion / found_stronghold /
   entered_end from their toasts (End colours as fallback). overworld = 0:00.
"""

import csv
from collections import Counter
from itertools import takewhile
from pathlib import Path

from . import config

SPLIT_ORDER = ["overworld", "entered_nether", "found_bastion", "found_fortress",
               "finding_stronghold", "found_stronghold", "entered_end"]
# Splits that must come after each other in a valid run (bastion and fortress
# can be done in either order, so they are only checked against the others).
SPLIT_RANK = {"overworld": 0, "entered_nether": 1, "found_bastion": 2, "found_fortress": 2,
              "finding_stronghold": 3, "found_stronghold": 4, "entered_end": 5}

TOAST_FIELDS = ["time_s", "window", "slot", "k", "full", "title", "score", "icon", "icon_score"]


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
                             int(r["full"]), r["title"] or "", f"{r['score']:.3f}",
                             r.get("icon") or "", f"{r.get('icon_score', 0.0):.3f}"])


def read_toasts_csv(path):
    path = Path(path)
    if not path.is_file():
        return []
    with open(path, newline="") as f:
        # `icon` / `icon_score` were added with the layout calibration; older files lack them.
        return [{"time_s": float(r["time_s"]), "window": r["window"], "slot": int(r["slot"]),
                 "k": float(r["k"]), "full": r["full"] == "1", "title": r["title"] or None,
                 "score": float(r["score"]), "icon": r.get("icon") or None,
                 "icon_score": float(r.get("icon_score") or 0.0)} for r in csv.DictReader(f)]


def advancement_of(row):
    """The advancement a toast observation shows: its item icon (language-free) if recognised,
    else the English title template's read (None if neither)."""
    icon = row.get("icon")
    if icon and icon in config.TOAST_ICON_ADVANCEMENTS:
        return config.TOAST_ICON_ADVANCEMENTS[icon]
    return row.get("title")


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
                  "best": {}, "state": "in", "first_read": None, "how": Counter()}
            tracks.append(tr)
            open_by_slot[r["slot"]] = tr
        tr["end"] = r["time_s"]
        if r["full"]:
            tr["state"] = "full"
        elif tr["state"] == "full":
            tr["state"] = "out"
        adv = advancement_of(r)
        if adv:
            tr["titles"][adv] += 1
            score = r.get("icon_score", 0.0) if r.get("icon") else r["score"]
            tr["best"][adv] = max(tr["best"].get(adv, 0.0), score)
            tr["how"][("icon" if r.get("icon") else "title")] += 1
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
                    "reads": reads, "score": tr["best"][title], "first_read": tr["first_read"],
                    "how": "icon" if tr["how"]["icon"] else "title"})
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


# --- 3. portal transitions --------------------------------------------------

DIMS = ("overworld", "nether", "end")
OTHER = {"overworld": "nether", "nether": "overworld"}


def _loading_screens(samples, run_end):
    """Stretches of loading-screen samples -> [{"start", "end", "t": first sample after}]."""
    out = []
    for i, s in enumerate(samples):
        if s.time >= run_end:
            break
        if not getattr(s, "loading", False):
            continue
        if out and s.time - out[-1]["end"] <= config.LOADING_GAP_S:
            out[-1]["end"], out[-1]["last_i"] = s.time, i
        else:
            out.append({"start": s.time, "end": s.time, "last_i": i, "kind": "loading"})
    for ev in out:
        nxt = next((s for s in samples[ev["last_i"] + 1:] if not getattr(s, "loading", False)), None)
        ev["t"] = nxt.time if nxt is not None else ev["end"]
    return out


def _portal_ends(samples, run_end):
    """Long purple portal-overlay stretches on world frames -> [{"start", "end", "t": first sample after}]."""
    out, cur = [], None
    for i, s in enumerate(samples):
        if s.time >= run_end:
            break
        on = s.screen == "world" and getattr(s, "portal", 0.0) >= config.PORTAL_MIN_SHARE
        if on:
            if cur is not None and s.time - cur["end"] <= 0.3:
                cur["end"], cur["last_i"] = s.time, i
            else:
                cur = {"start": s.time, "end": s.time, "last_i": i, "kind": "portal"}
                out.append(cur)
    keep = []
    for ev in out:
        if ev["end"] - ev["start"] < config.PORTAL_MIN_STAY_S or ev["last_i"] + 1 >= len(samples):
            continue
        nxt = samples[ev["last_i"] + 1]
        if nxt.time - ev["end"] > config.PORTAL_MAX_GAP_S:
            continue
        ev["t"] = nxt.time
        keep.append(ev)
    return keep


def _side_dimension(samples, a, b):
    """Dimension evidence in [a, b): F3 reads weigh TRANSITION_F3_WEIGHT, colour reads 1 -> (dim or "", note)."""
    votes = Counter()
    for s in samples:
        if s.time < a:
            continue
        if s.time >= b:
            break
        if s.dimension in DIMS and not getattr(s, "loading", False) and getattr(s, "portal", 0.0) < 0.3:
            votes[s.dimension] += config.TRANSITION_F3_WEIGHT if getattr(s, "dim_src", "") == "f3" else 1
    total = sum(votes.values())
    note = ", ".join(f"{d} {n}" for d, n in votes.most_common())
    if total < config.TRANSITION_MIN_VOTES:
        return "", note
    dim, n = votes.most_common(1)[0]
    return (dim if n / total >= config.TRANSITION_MIN_SHARE else ""), note


def portal_transitions(samples, run_end):
    """Dimension changes through nether portals -> [{"t", "start", "kind", "before", "after", "how"}].

    `t` = the first sample after the loading screen (first rendered frame of the new
    dimension); `before` / `after` = dimension on each side ("" if unknown), `how` says
    whether each side came from evidence or from the overworld <-> nether alternation.
    """
    events = _loading_screens(samples, run_end)
    for ev in _portal_ends(samples, run_end):
        # A portal overlay followed by a sampled loading screen is the same trip.
        if not any(-0.05 <= lo["start"] - ev["end"] <= config.PORTAL_MAX_GAP_S + 0.5 for lo in events):
            events.append(ev)
    events.sort(key=lambda e: e["t"])
    W = config.TRANSITION_WINDOW_S
    for i, ev in enumerate(events):
        prev_t = events[i - 1]["t"] if i > 0 else 0.0
        next_start = events[i + 1]["start"] if i + 1 < len(events) else run_end
        ev["before"], ev["before_note"] = _side_dimension(samples, max(prev_t, ev["start"] - W), ev["start"])
        ev["after"], ev["after_note"] = _side_dimension(samples, ev["t"], min(next_start, ev["t"] + W))
        ev["how"] = {"before": "evidence" if ev["before"] else "", "after": "evidence" if ev["after"] else ""}
    # Weak (overlay-only) candidates need evidence on both sides that the dimension changed.
    events = [e for e in events if e["kind"] == "loading" or (e["before"] and e["after"] and e["before"] != e["after"])]
    # Fill unknown sides: nether portals alternate overworld <-> nether, and the side after one
    # trip is the side before the next.
    for _ in range(2):
        for i, ev in enumerate(events):
            if not ev["before"] and i > 0 and events[i - 1]["after"]:
                ev["before"], ev["how"]["before"] = events[i - 1]["after"], "previous transition"
            if not ev["after"] and ev["before"] in OTHER:
                ev["after"], ev["how"]["after"] = OTHER[ev["before"]], "alternation"
            if not ev["before"] and ev["after"] in OTHER and i > 0:
                ev["before"], ev["how"]["before"] = OTHER[ev["after"]], "alternation"
    return events


def _transition_note(ev):
    what = (f"loading screen {mmss(ev['start'])}-{mmss(ev['end'])}" if ev["kind"] == "loading"
            else f"portal overlay {mmss(ev['start'])}-{mmss(ev['end'])}, no loading screen sampled")
    sides = []
    for side in ("before", "after"):
        how = ev["how"].get(side) or "unknown"
        detail = ev.get(f"{side}_note") if how == "evidence" else how
        sides.append(f"{side}: {ev[side] or '?'} ({detail})")
    return f"{ev['before'] or '?'} -> {ev['after'] or '?'} portal transition: {what}, first frame {mmss(ev['t'])}; " + "; ".join(sides)


# --- 4b. fortress: standing on nether bricks -----------------------------------

def fortress_arrival(samples, start, end, sustain_s):
    """First sample in [start, end] where the nether-brick floor share holds for `sustain_s`
    (>= FORTRESS_SUSTAIN_FRAC of the world samples) -> (time, median share) or (None, 0)."""
    world = [s for s in samples if start <= s.time <= end + sustain_s and s.screen in ("world", "f3")]

    def floor(w):
        return w.brick >= config.FORTRESS_MIN_SHARE and getattr(w, "brick_up", 0.0) < config.FORTRESS_WALL_MAX

    for i, s in enumerate(world):
        if s.time > end:
            break
        if not floor(s):
            continue
        win = list(takewhile(lambda w: w.time <= s.time + sustain_s, world[i:]))
        if len(win) < config.FORTRESS_MIN_SAMPLES * sustain_s / config.FORTRESS_SUSTAIN_S:
            continue
        on = [w for w in win if floor(w)]
        if len(on) >= config.FORTRESS_SUSTAIN_FRAC * len(win):
            return s.time, float(sorted(w.brick for w in win)[len(win) // 2])
    return None, 0.0


# --- 5. splits ------------------------------------------------------------

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
                        f" (read {t['reads']}x by {t.get('how', 'title')}, first at {mmss(t['first_read'])}, "
                        f"score {t['score']:.2f})")
                found[split] = (t["start"], note)
                break

    def cross_check(time, dim_time, what):
        if dim_time is None:
            return f"; no sustained {what} in the dimension signal"
        return f"; dimension signal: {what} at {mmss(dim_time)} ({dim_time - time:+.1f}s)"

    events = [e for e in portal_transitions(samples, run_end) if e["t"] >= last_reset]
    extra = {}            # split -> extra fields for analysis.json (found_fortress: official_s)

    # entered_nether: the overworld -> nether transition (first rendered nether frame); its
    # toast ("We Need to Go Deeper", ~0.2-0.4 s later) when no transition was seen.
    nether_dim = first_transition(stretches, "overworld", "nether", last_reset)
    into_nether = next((e for e in events if e["after"] == "nether" and e["before"] != "nether"), None)
    if "entered_nether" in found:
        t, note = found["entered_nether"]
        if into_nether is not None and t - config.TRANSITION_TOAST_LEAD_S <= into_nether["t"] <= t + 1.0:
            found["entered_nether"] = (into_nether["t"], _transition_note(into_nether)
                                       + f"; toast: {note} ({t - into_nether['t']:+.1f}s)")
        else:
            found["entered_nether"] = (t, note + cross_check(t, nether_dim, "overworld -> nether"))
    elif into_nether is not None:
        found["entered_nether"] = (into_nether["t"], _transition_note(into_nether) + "; no toast read")
    elif nether_dim is not None:
        found["entered_nether"] = (nether_dim, f"no toast or transition seen; first sustained overworld -> nether "
                                               f"(colour) at {mmss(nether_dim)}")

    end_dim = first_stretch(stretches, "end", last_reset)
    if "entered_end" in found:
        t, note = found["entered_end"]
        found["entered_end"] = (t, note + cross_check(t, end_dim, "first End stretch"))
    elif end_dim is not None:
        found["entered_end"] = (end_dim, f"no toast read; first sustained End stretch at {mmss(end_dim)}")

    # found_fortress: first sustained moment standing on nether bricks, never after the toast.
    blind_after_entry = None
    if "entered_nether" in found:
        n0 = found["entered_nether"][0]
        blind_after_entry = next((e["t"] for e in events if e["t"] > n0 and e["before"] == "nether"
                                  and e["after"] == "overworld"), None)
        toast = found.get("found_fortress")
        if toast is not None:
            official = toast[0]
            t_vis, share = fortress_arrival(samples, n0, official, config.FORTRESS_SUSTAIN_S)
            extra["found_fortress"] = {"official_s": round(official, 2)}
            if t_vis is not None:
                found["found_fortress"] = (t_vis, f"standing on nether bricks from {mmss(t_vis)} (floor share "
                                                  f"{share:.2f}, held {config.FORTRESS_SUSTAIN_S:.1f}s); official: "
                                                  f"{toast[1]} ({official - t_vis:+.1f}s after)")
            else:
                found["found_fortress"] = (official, f"no nether-brick floor seen before the toast - using the "
                                                     f"advancement time; {toast[1]}")
        else:
            limit = blind_after_entry if blind_after_entry is not None else run_end
            t_vis, share = fortress_arrival(samples, n0, limit, config.FORTRESS_NO_TOAST_SUSTAIN_S)
            if t_vis is not None:
                found["found_fortress"] = (t_vis, f"standing on nether bricks from {mmss(t_vis)} (floor share "
                                                  f"{share:.2f}, held {config.FORTRESS_NO_TOAST_SUSTAIN_S:.1f}s); "
                                                  f"no 'A Terrible Fortress' toast read")

    # finding_stronghold: leaving the nether after the nether goals ("blind" travel).
    nether_goals = [n for n in ("found_fortress", "found_bastion", "entered_nether") if n in found]
    if nether_goals:
        anchor_name = max(nether_goals, key=lambda n: found[n][0])     # the later of bastion/fortress
        anchor = found[anchor_name][0]
        limit = found.get("found_stronghold", (run_end, ""))[0]
        ev = next((e for e in events if e["t"] >= anchor and e["before"] == "nether" and e["after"] == "overworld"), None)
        if ev is not None and ev["t"] < limit:
            found["finding_stronghold"] = (ev["t"], _transition_note(ev) + f"; first after "
                                                    f"{anchor_name.replace('_', ' ')} ({mmss(anchor)})")
        else:
            t = first_transition(stretches, "nether", "overworld", anchor)
            if t is not None and t < limit:
                found["finding_stronghold"] = (t, f"no portal transition seen; first sustained nether -> overworld "
                                                  f"(colour) after {anchor_name.replace('_', ' ')} ({mmss(anchor)})")

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
                       "source": "cv", "evidence": note, **extra.get(name, {})})
    return splits, advancements
