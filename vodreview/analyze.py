"""The full pipeline: sample video -> screen type + motion + split signals -> run end -> idle stretches -> reports."""

import csv
import time
from collections import Counter
from pathlib import Path

import cv2

from . import config
from .idle import Sample, find_idle_stretches, is_still
from .motion import MotionMeter
from .finaltime import read_final_time
from .recdate import recording_date
from .remux import remux_to_mp4
from .report import write_analysis_json, write_run_json
from .runend import DragonWatcher, ResultDetector
from .dimension import DimensionClassifier
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

    classifier = ScreenClassifier(height)
    motion_meter = MotionMeter()
    dragon = DragonWatcher()
    results = ResultDetector(height)
    signals = SplitSignals(height)
    missing = classifier.missing_screens()
    if missing:
        print(f"Note: no calibration templates for {', '.join(missing)} - those screens can't be detected.")

    samples = []
    run_end, end_reason = duration, "end of video"
    killed_at = None
    outcome = None            # "win" / "loss" from the result screen, if seen
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
            break
        screen = classifier.classify(gray)
        kill = dragon.update(t, frame, screen)
        if kill is not None:
            killed_at = run_end = kill
            end_reason = "dragon kill"
            samples = [s for s in samples if s.time < kill]   # drop samples after the kill
            signals.toasts = [r for r in signals.toasts if r["time_s"] < kill]
            continue
        motion = motion_meter.measure(gray, f3_visible=(screen == "f3"))
        dim, reset = signals.update(t, frame, gray, screen)
        samples.append(Sample(t, motion, screen, is_still(motion, screen), dim, reset))
        if len(samples) % 1000 == 0:
            print(f"  ... {mmss(t)} / {mmss(duration)}", flush=True)

    stretches = find_idle_stretches(samples, sample_interval)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_samples_csv(out_dir / "samples.csv", samples)
    write_toasts_csv(out_dir / "toasts.csv", signals.toasts)
    write_idle_csv(out_dir / "idle.csv", stretches)
    print_report(duration, run_end, end_reason, samples, stretches, sample_interval)
    final = {"text": None, "ms": None}
    if result_seen_at is not None:
        # Second, short pass over the result screen: read "(MM:SS.mmm)" on
        # several frames and take the consensus (see finaltime.py).
        final = read_final_time(video_path, result_seen_at,
                                result_seen_at + config.FINAL_TIME_READ_SECONDS, duration)
    rec_date, date_source = recording_date(video_path, duration)
    print(f"Recording date : {rec_date} ({date_source})")
    run = write_run_json(out_dir, video=video_path, duration_s=duration, run_end_s=run_end,
                         end_reason=end_reason, result=outcome, sample_interval_s=sample_interval,
                         final_time_ms=final["ms"], final_time_text=final["text"],
                         recording_date=rec_date, date_source=date_source)
    analysis_path = write_analysis_json(out_dir, run, samples, stretches, signals.toasts)
    print_splits(analysis_path)
    print(f"\nWrote {out_dir / 'samples.csv'}, {out_dir / 'toasts.csv'}, {out_dir / 'idle.csv'}, run.json and analysis.json")
    if make_video:
        remux_to_mp4(video_path, out_dir)
    print(f"Analysis took {time.time() - started:.0f}s")


class SplitSignals:
    """Per-sample split signals: advancement toasts, dimension, reset dialog."""

    def __init__(self, frame_height):
        self.reader = ToastReader()
        self.dimension = DimensionClassifier(frame_height)
        self.reset = ResetDialogDetector(frame_height)
        self.toasts = []          # toast observations -> toasts.csv

    def update(self, t, frame, gray, screen):
        """Record toasts at time t; return (dimension label, reset dialog seen)."""
        for box in find_toasts(frame):
            if box.slot > config.TOAST_MAX_SLOT:
                continue
            title, score, _ = self.reader.read(frame, box)
            self.toasts.append({"time_s": t, "window": box.window, "slot": box.slot, "k": box.k,
                                "full": box.full, "title": title, "score": score})
        return self.dimension.classify(frame, gray, screen), self.reset.check(gray)


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


def write_samples_csv(path, samples):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "motion_pct", "screen", "still", "dimension", "reset"])
        for s in samples:
            writer.writerow([f"{s.time:.2f}", f"{s.motion:.3f}", s.screen, int(s.still), s.dimension, int(s.reset)])


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


def update_run(out_dir, video_path=None):
    """Add/refresh final time + recording date in an existing run (no full analysis).

    Reads the result screen in the video tail after the stored run end, then
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
    final = read_final_time(video_path, start,
                            start + config.RESULT_LOOKAHEAD_SECONDS + config.FINAL_TIME_READ_SECONDS, duration)
    run["final_time_ms"], run["final_time_text"] = final["ms"], final["text"]
    run["recording_date"], run["date_source"] = recording_date(video_path, duration)
    print(f"Recording date: {run['recording_date']} ({run['date_source']})")
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
    _, _, _, height, duration = video_info(video_path)
    signals = SplitSignals(height)
    last = samples[-1].time if samples else 0.0
    for t, frame in iter_samples(video_path, config.SAMPLES_PER_SECOND):
        if t > last + 1e-6:
            break
        s = by_time.get(round(t, 2))
        if s is None:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        s.dimension, s.reset = signals.update(t, frame, gray, s.screen)
        if int(t * 10) % 1200 == 0:
            print(f"  ... {mmss(t)} / {mmss(last)}", flush=True)
    write_samples_csv(out_dir / "samples.csv", samples)
    write_toasts_csv(out_dir / "toasts.csv", signals.toasts)
    print_splits(rebuild_json(out_dir))
    print(f"Split detection took {time.time() - started:.0f}s")
