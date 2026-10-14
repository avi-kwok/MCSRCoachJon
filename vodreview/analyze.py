"""The full pipeline: sample video -> screen type + motion -> run end -> idle stretches -> reports."""

import csv
import time
from collections import Counter
from pathlib import Path

import cv2

from . import config
from .idle import Sample, find_idle_stretches, is_still
from .motion import MotionMeter
from .runend import DragonWatcher, ResultDetector
from .screens import ScreenClassifier
from .video import iter_samples, video_info

REPORT_SCREENS = ["world", "resized", *config.SCREEN_PRIORITY]


def mmss(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def analyze(video_path, out_dir):
    started = time.time()
    fps, _, width, height, duration = video_info(video_path)
    sample_interval = round(fps / config.SAMPLES_PER_SECOND) / fps

    classifier = ScreenClassifier(height)
    motion_meter = MotionMeter()
    dragon = DragonWatcher()
    results = ResultDetector(height)
    missing = classifier.missing_screens()
    if missing:
        print(f"Note: no calibration templates for {', '.join(missing)} - those screens can't be detected.")

    samples = []
    run_end, end_reason = duration, "end of video"
    killed_at = None
    for t, frame in iter_samples(video_path, config.SAMPLES_PER_SECOND):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        result = results.check(frame, gray)
        if killed_at is not None:
            # Run already over (dragon kill); only looking for the result screen.
            if result or t - killed_at > config.RESULT_LOOKAHEAD_SECONDS:
                if result:
                    end_reason = f"dragon kill, result screen at {mmss(t)}: {result}"
                break
            continue
        if result:
            run_end, end_reason = t, result
            break
        screen = classifier.classify(gray)
        kill = dragon.update(t, frame, screen)
        if kill is not None:
            killed_at = run_end = kill
            end_reason = "dragon kill"
            samples = [s for s in samples if s.time < kill]   # drop samples after the kill
            continue
        motion = motion_meter.measure(gray, f3_visible=(screen == "f3"))
        samples.append(Sample(t, motion, screen, is_still(motion, screen)))
        if len(samples) % 1000 == 0:
            print(f"  ... {mmss(t)} / {mmss(duration)}", flush=True)

    stretches = find_idle_stretches(samples, sample_interval)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_samples_csv(out_dir / "samples.csv", samples)
    write_idle_csv(out_dir / "idle.csv", stretches)
    print_report(duration, run_end, end_reason, samples, stretches, sample_interval)
    print(f"\nWrote {out_dir / 'samples.csv'} and {out_dir / 'idle.csv'}")
    print(f"Analysis took {time.time() - started:.0f}s")


def write_samples_csv(path, samples):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "motion_pct", "screen", "still"])
        for s in samples:
            writer.writerow([f"{s.time:.2f}", f"{s.motion:.3f}", s.screen, int(s.still)])


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
