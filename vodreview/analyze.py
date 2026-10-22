"""The full pipeline: calibrate the layout -> sample video -> screen type + motion + split signals
-> run end -> idle stretches -> reports."""

import csv
import json
import time
from collections import Counter
from pathlib import Path

import cv2

from . import config
from .idle import Sample, find_idle_stretches, is_still
from .layout import Layout, calibrate, cluster_strips, load_layout, save_layout
from .motion import MotionMeter
from .finaltime import read_final_time
from .privateroom import detect_private_room
from .recdate import recording_date
from .remux import remux_to_mp4
from .report import write_analysis_json, write_run_json
from .runend import DragonWatcher, ResultDetector
from .dimension import DimensionClassifier
from .f3 import F3Reader, print_state, reread, write_f3_csv
from .fortress import brick_shares
from .transition import LoadingDetector, portal_share
from .opponent import OpponentWatcher, write_clock_csv, write_opponent_csv
from .screens import ResetDialogDetector, ScreenClassifier
from .splits import write_toasts_csv
from .toasts import ToastReader, find_toasts
from .video import iter_samples, video_info

REPORT_SCREENS = ["world", "resized", *config.SCREEN_PRIORITY]


def mmss(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def analyze(video_path, out_dir, make_video=True):
    started = time.time()
    fps, _, width, height, duration = video_info(video_path)
    sample_interval = round(fps / config.SAMPLES_PER_SECOND) / fps
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Measure this video's layout first (GUI scale, overlays, panel, clock, strips).
    print("Calibrating the layout ...", flush=True)
    layout_data = calibrate(video_path)
    save_layout(out_dir, layout_data)
    lay = Layout(layout_data)

    classifier = ScreenClassifier(lay)
    motion_meter = MotionMeter(lay)
    dragon = DragonWatcher(lay)
    results = ResultDetector(lay)
    signals = SplitSignals(lay)
    opponent = OpponentWatcher(lay, duration)
    f3_reader = F3Reader(lay)
    f3_rows = []              # one row per F3 sample -> f3.csv (game state)
    strips_seen = []
    missing = classifier.missing_screens()
    if missing:
        print(f"Note: no text templates for {', '.join(missing)} - detected by GUI structure only.")

    samples = []
    run_end, end_reason = duration, "end of video"
    killed_at = None
    outcome = None            # "win" / "loss" / "draw" from the result screen, if seen
    result_seen_at = None     # video time the result screen was first seen
    for t, frame in iter_samples(video_path, config.SAMPLES_PER_SECOND):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        result = results.check(frame, gray)
        if killed_at is not None:
            # Run already over (dragon kill); only looking for the result screen.
            if result or t - killed_at > config.RESULT_LOOKAHEAD_SECONDS:
                if result:
                    outcome, result_seen_at = result, t
                    end_reason = f"dragon kill, result screen at {mmss(t)}: {result}"
                break
            continue
        if result:
            run_end, end_reason, outcome, result_seen_at = t, result, result, t
            if result == "draw":
                # MCSR shows a draw when a match is forfeited in a private room; the
                # streak check means the screen appeared a few samples earlier.
                run_end = result_seen_at = max(0.0, t - (config.RESULT_DRAW_CONFIRM - 1) / config.SAMPLES_PER_SECOND)
                end_reason = "forfeit"
            break
        opponent.update(t, frame)
        small = cv2.resize(gray, config.MOTION_SIZE, interpolation=cv2.INTER_AREA)
        screen = classifier.classify(gray, frame, small)
        strip = classifier.last_strip
        if strip is not None:
            strips_seen.append(strip)
        kill = dragon.update(t, frame, screen)
        if kill is not None:
            killed_at = run_end = kill
            end_reason = "dragon kill"
            samples = [s for s in samples if s.time < kill]   # drop samples after the kill
            signals.toasts = [r for r in signals.toasts if r["time_s"] < kill]
            f3_rows = [r for r in f3_rows if r["time_s"] < kill]
            continue
        if screen == "f3":
            f3_rows.append(f3_reader.read(t, frame))
        motion = motion_meter.measure(gray, f3_visible=(screen == "f3"), small=small)
        sig = signals.update(t, frame, gray, screen, strip)
        samples.append(Sample(t, motion, screen, is_still(motion, screen), **sig))
        if len(samples) % 1000 == 0:
            print(f"  ... {mmss(t)} / {mmss(duration)}", flush=True)

    stretches = find_idle_stretches(samples, sample_interval)
    record_strips(out_dir, layout_data, strips_seen, width, height)
    write_samples_csv(out_dir / "samples.csv", samples)
    write_toasts_csv(out_dir / "toasts.csv", signals.toasts)
    write_idle_csv(out_dir / "idle.csv", stretches)
    opponent.truncate(run_end)
    write_opponent_csv(out_dir / "opponent.csv", opponent.rows)
    write_clock_csv(out_dir / "clock.csv", opponent.clock_rows)
    write_f3_csv(out_dir / "f3.csv", f3_rows)
    print_report(duration, run_end, end_reason, samples, stretches, sample_interval)
    final = {"text": None, "ms": None}
    if result_seen_at is not None and outcome != "draw":   # a draw screen shows no time
        # Second, short pass over the result screen: read "(MM:SS.mmm)" on
        # several frames and take the consensus (see finaltime.py).
        final = read_final_time(video_path, result_seen_at,
                                result_seen_at + config.FINAL_TIME_READ_SECONDS, duration, lay)
    rec_date, date_source = recording_date(video_path, duration)
    print(f"Recording date : {rec_date} ({date_source})")
    private = detect_private_room(video_path, 0.0, run_end)
    run = write_run_json(out_dir, video=video_path, duration_s=duration, run_end_s=run_end,
                         end_reason=end_reason, result=outcome, sample_interval_s=sample_interval,
                         final_time_ms=final["ms"], final_time_text=final["text"],
                         recording_date=rec_date, date_source=date_source, private_room=private)
    analysis_path = write_analysis_json(out_dir, run, samples, stretches, signals.toasts,
                                        opponent.rows, opponent.clock_rows, f3_rows)
    print_splits(analysis_path)
    print_opponent(analysis_path)
    print_state(json.loads(Path(analysis_path).read_text()).get("state"), f3_reader.read_s, f3_reader.reads)
    print(f"\nWrote samples.csv, toasts.csv, idle.csv, opponent.csv, clock.csv, f3.csv, run.json and analysis.json "
          f"in {out_dir}")
    if make_video:
        remux_to_mp4(video_path, out_dir)
    print(f"Analysis took {time.time() - started:.0f}s")


def record_strips(out_dir, layout_data, strips_seen, width, height):
    """Add the resized strips seen in the analysis pass to layout.json ("strips_analysis")."""
    found = cluster_strips(strips_seen, width, height, config.STRIP_MIN_SAMPLES_ANALYSIS)
    layout_data["strips_analysis"] = {n: dict(s, source="analysis pass") for n, s in found.items()}
    save_layout(out_dir, layout_data)
    if found:
        print("Resized strips seen: " + ", ".join(f"{n} {s['rect']} ({s['frames']} samples)" for n, s in found.items()))


class SplitSignals:
    """Per-sample split signals: advancement toasts, dimension, reset dialog."""

    def __init__(self, lay):
        self.lay = lay
        self.reader = ToastReader()
        self.dimension = DimensionClassifier(lay)
        self.reset = ResetDialogDetector(lay)
        self.loading = LoadingDetector(lay)
        self.toasts = []          # toast observations -> toasts.csv

    def update(self, t, frame, gray, screen, strip=None):
        """Record toasts at time t; return the per-sample split signals as a dict
        (dimension, dim_src, reset, loading, brick, portal - the Sample fields).

        `strip` = the resized strip shown in this frame (px), if any.
        """
        for box in find_toasts(frame, self.lay, strip):
            if box.slot > config.TOAST_MAX_SLOT:
                continue
            title, score, _ = self.reader.read(frame, box)
            icon, icon_score, _ = self.reader.read_icon(frame, box)
            self.toasts.append({"time_s": t, "window": box.window, "slot": box.slot, "k": box.k,
                                "full": box.full, "title": title, "score": score,
                                "icon": icon, "icon_score": icon_score})
        dim, src = self.dimension.classify(frame, gray, screen, with_source=True)
        brick, brick_up = brick_shares(frame, self.lay) if screen in ("world", "f3") else (0.0, 0.0)
        return {"dimension": dim, "dim_src": src, "reset": self.reset.check(gray),
                "loading": self.loading.check(frame, strip), "brick": brick, "brick_up": brick_up,
                "portal": portal_share(frame, self.lay) if screen == "world" else 0.0}


def print_splits(analysis_path):
    import json
    analysis = json.loads(Path(analysis_path).read_text())
    print("\n=== Splits ===")
    if not analysis["splits"]:
        print("  (none detected)")
    for sp in analysis["splits"]:
        print(f"  {sp['name']:<19} {mmss(sp['start_s'])} - {mmss(sp['end_s'])}  {sp.get('evidence', '')}")
    advs = analysis.get("advancements", [])
    if advs:
        print("Advancements: " + ", ".join(f"{a['title']} {mmss(a['t_s'])}" for a in advs))


def print_opponent(analysis_path):
    import json
    analysis = json.loads(Path(analysis_path).read_text())
    opp, clock = analysis.get("opponent"), analysis.get("match_clock")
    if clock:
        if clock["offset_s"] is None:
            print("\nMatch clock: no RTA reads")
        else:
            print(f"\nMatch clock: video = match + {clock['offset_s']:.3f}s "
                  f"(spread {clock['spread_s']:.3f}s over {clock['reads']} reads)")
    if opp:
        print(f"=== Opponent: {opp['name'] or '(name not read)'} ===")
        for st in opp["statuses"]:
            print(f"  {mmss(st['t_s'])}  {st['raw']:<19} (seen first at {st['t_s']:.1f}s; "
                  f"changed at most {st['latency_s']:.1f}s earlier)")


def write_samples_csv(path, samples):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "motion_pct", "screen", "still", "dimension", "reset",
                         "dim_src", "loading", "brick", "brick_up", "portal"])
        for s in samples:
            writer.writerow([f"{s.time:.2f}", f"{s.motion:.3f}", s.screen, int(s.still), s.dimension, int(s.reset),
                             s.dim_src, int(s.loading), f"{s.brick:.2f}", f"{s.brick_up:.2f}", f"{s.portal:.2f}"])


def write_idle_csv(path, stretches):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["start_s", "end_s", "duration_s", "start", "end"])
        for st in stretches:
            writer.writerow([f"{st.start:.1f}", f"{st.end:.1f}", f"{st.duration:.1f}", mmss(st.start), mmss(st.end)])


def print_report(duration, run_end, end_reason, samples, stretches, sample_interval):
    total_idle = sum(st.duration for st in stretches)
    print("\n=== Idle report ===")
    print(f"Video duration : {mmss(duration)} ({duration:.1f}s)")
    print(f"Run ended at   : {mmss(run_end)} ({end_reason})")
    print(f"Total idle     : {total_idle:.1f}s ({100 * total_idle / run_end:.1f}% of run)")
    print(f"Idle stretches : {len(stretches)} (still for >= {config.MIN_IDLE_SECONDS:.0f}s)")
    for i, st in enumerate(stretches, 1):
        print(f"  {i:3d}. {mmss(st.start)} - {mmss(st.end)}  ({st.duration:.1f}s)")

    print("\nTime per screen type (up to the run end):")
    counts = Counter(s.screen for s in samples)
    for screen in REPORT_SCREENS:
        seconds = counts.get(screen, 0) * sample_interval
        print(f"  {screen:<10} {seconds:7.1f}s  ({100 * seconds / run_end:4.1f}%)")


def find_result(video_path, start_s, end_s, lay):
    """First result screen between start_s and end_s at the analysis sample rate -> (t, result) or None."""
    from .video import open_video
    detector = ResultDetector(lay)
    cap = open_video(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps / config.SAMPLES_PER_SECOND))
    index = int(round(start_s * fps / step)) * step
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    try:
        while index / fps <= end_s:
            if index % step:
                ok = cap.grab()
            else:
                ok, frame = cap.read()
                if ok:
                    result = detector.check(frame, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                    if result:
                        return index / fps, result
            if not ok:
                return None
            index += 1
    finally:
        cap.release()
    return None


def update_run(out_dir, video_path=None):
    """Add/refresh final time + recording date in an existing run (no full analysis).

    Reads the result screen in the video tail after the stored run end (and the
    win/loss itself if a dragon-kill run has none) and the match mode (private room?), then
    rewrites run.json and analysis.json.
    """
    import json
    from .report import rebuild_json, save_run_json
    out_dir = Path(out_dir)
    run = json.loads((out_dir / "run.json").read_text())
    video_path = video_path or run["video"]
    if not Path(video_path).is_file():
        raise SystemExit(f"Source video not found: {video_path} (pass --video)")
    duration = run["duration_s"]
    start = run["run_end_s"]
    lay = run_layout(out_dir, video_path)
    if run.get("result") is None and run.get("end_reason") == "dragon kill":
        # result screen missed (e.g. by an older detector): look for it again after the kill
        seen = find_result(video_path, start, start + config.RESULT_LOOKAHEAD_SECONDS, lay)
        if seen:
            t, result = seen
            run["result"] = result
            run["end_reason"] = f"dragon kill, result screen at {mmss(t)}: {result}"
            start = t
            print(f"Result screen at {mmss(t)}: {result}")
    final = read_final_time(video_path, start,
                            start + config.RESULT_LOOKAHEAD_SECONDS + config.FINAL_TIME_READ_SECONDS, duration, lay)
    run["final_time_ms"], run["final_time_text"] = final["ms"], final["text"]
    run["recording_date"], run["date_source"] = recording_date(video_path, duration)
    print(f"Recording date: {run['recording_date']} ({run['date_source']})")
    run["private_room"] = detect_private_room(video_path, 0.0, run["run_end_s"])
    save_run_json(out_dir, run)
    rebuild_json(out_dir)


def detect_splits(out_dir, video_path=None):
    """Dev shortcut: (re)compute only the split signals for an analyzed run.

    Re-reads the video at the stored sample times, reusing the screen types in
    samples.csv (no screen/motion/run-end work), then rewrites samples.csv
    (dimension + reset columns), toasts.csv and analysis.json.
    """
    import json
    from .report import read_samples_csv, rebuild_json
    started = time.time()
    out_dir = Path(out_dir)
    run = json.loads((out_dir / "run.json").read_text())
    video_path = video_path or run["video"]
    if not Path(video_path).is_file():
        raise SystemExit(f"Source video not found: {video_path} (pass --video)")
    samples = read_samples_csv(out_dir / "samples.csv")
    by_time = {round(s.time, 2): s for s in samples}
    lay = run_layout(out_dir, video_path)
    signals = SplitSignals(lay)
    classifier = ScreenClassifier(lay)
    last = samples[-1].time if samples else 0.0
    for t, frame in iter_samples(video_path, config.SAMPLES_PER_SECOND):
        if t > last + 1e-6:
            break
        s = by_time.get(round(t, 2))
        if s is None:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        strip = None
        if s.screen == "resized":
            classifier.classify(gray, frame)
            strip = classifier.last_strip
        for key, value in signals.update(t, frame, gray, s.screen, strip).items():
            setattr(s, key, value)
        if int(t * 10) % 1200 == 0:
            print(f"  ... {mmss(t)} / {mmss(last)}", flush=True)
    write_samples_csv(out_dir / "samples.csv", samples)
    write_toasts_csv(out_dir / "toasts.csv", signals.toasts)
    print_splits(rebuild_json(out_dir))
    print(f"Split detection took {time.time() - started:.0f}s")


def detect_opponent(out_dir, video_path=None):
    """Dev shortcut: (re)read only the opponent panel + match clock of an analyzed run.

    Reads the video at OPPONENT_SAMPLE_S intervals up to the stored run end
    (the same frames `analyze` reads), rewrites opponent.csv + clock.csv and
    rebuilds analysis.json.
    """
    import json
    from .report import rebuild_json
    started = time.time()
    out_dir = Path(out_dir)
    run = json.loads((out_dir / "run.json").read_text())
    video_path = video_path or run["video"]
    if not Path(video_path).is_file():
        raise SystemExit(f"Source video not found: {video_path} (pass --video)")
    run_end = run["run_end_s"]
    watcher = OpponentWatcher(run_layout(out_dir, video_path), run_end)
    for t, frame in iter_samples(video_path, 1 / config.OPPONENT_SAMPLE_S):
        if t >= run_end:
            break
        watcher.update(t, frame)
        if int(round(t / config.OPPONENT_SAMPLE_S)) % 240 == 0:
            print(f"  ... {mmss(t)} / {mmss(run_end)}", flush=True)
    write_opponent_csv(out_dir / "opponent.csv", watcher.rows)
    write_clock_csv(out_dir / "clock.csv", watcher.clock_rows)
    print_opponent(rebuild_json(out_dir))
    print(f"Opponent panel reading took {time.time() - started:.0f}s")


def detect_f3(out_dir, video_path=None):
    """Re-read only the F3 samples of an analyzed run (screen == f3 in samples.csv) -> f3.csv, analysis.json.

    Seeks to each F3 stretch instead of decoding the whole video.
    """
    from .report import read_samples_csv, rebuild_json
    started = time.time()
    out_dir = Path(out_dir)
    run = json.loads((out_dir / "run.json").read_text())
    video_path = video_path or run["video"]
    if not Path(video_path).is_file():
        raise SystemExit(f"Source video not found: {video_path} (pass --video)")
    times = [s.time for s in read_samples_csv(out_dir / "samples.csv")
             if s.screen == "f3" and s.time < run["run_end_s"]]
    print(f"Reading {len(times)} F3 samples ...", flush=True)
    rows, reader = reread(video_path, run_layout(out_dir, video_path), times)
    write_f3_csv(out_dir / "f3.csv", rows)
    path = rebuild_json(out_dir)
    print_state(json.loads(Path(path).read_text()).get("state"), reader.read_s, reader.reads)
    print(f"F3 reading took {time.time() - started:.0f}s")


def run_layout(out_dir, video_path):
    """The run's layout.json, calibrating (and saving) it first if the run predates it."""
    path = Path(out_dir) / "layout.json"
    if path.is_file():
        return load_layout(out_dir)
    print("No layout.json in this run - calibrating ...", flush=True)
    data = calibrate(video_path)
    save_layout(out_dir, data)
    return Layout(data)


def layout_command(out_dir, video_path=None, image=None, recalibrate=False):
    """`python -m vodreview layout <run>`: print (and optionally draw) the run's layout."""
    import json
    from .layout import draw_layout
    out_dir = Path(out_dir)
    if video_path is None:
        run_json = out_dir / "run.json"
        if not run_json.is_file():
            raise SystemExit(f"No run.json in {out_dir} - pass --video")
        video_path = json.loads(run_json.read_text())["video"]
    if recalibrate or not (out_dir / "layout.json").is_file():
        out_dir.mkdir(parents=True, exist_ok=True)
        save_layout(out_dir, calibrate(video_path))
    else:
        print(load_layout(out_dir).summary())
    if image:
        data = json.loads((out_dir / "layout.json").read_text())
        print(f"Saved {draw_layout(video_path, data, image)}")
