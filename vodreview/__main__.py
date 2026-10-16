"""Command line entry point:  python -m vodreview <command> ..."""

import argparse
from pathlib import Path

import cv2

from .analyze import analyze, detect_f3, detect_opponent, detect_splits, layout_command, update_run
from .report import rebuild_json
from .video import read_frame_at

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "out"
DEFAULT_RUNS = Path(__file__).resolve().parent.parent / "runs"


def parse_timestamp(text):
    """'mm:ss', 'mm:ss.s' or plain seconds -> float seconds."""
    if ":" in text:
        minutes, seconds = text.split(":")
        return int(minutes) * 60 + float(seconds)
    return float(text)


def main():
    parser = argparse.ArgumentParser(prog="vodreview", description="MCSR VOD analyzer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="find idle stretches in a video")
    p_analyze.add_argument("video")
    p_analyze.add_argument("--out", default=str(DEFAULT_OUT), help="output folder (default: out/)")
    p_analyze.add_argument("--no-video", action="store_true", help="don't write the browser-playable video.mp4")

    p_rebuild = sub.add_parser("rebuild-json", help="rebuild analysis.json from an analyze output folder (no CV)")
    p_rebuild.add_argument("out_dir")

    p_update = sub.add_parser("update-run", help="read the final time + recording date for an existing run "
                                                "(scans only the video tail) and rebuild analysis.json")
    p_update.add_argument("out_dir")
    p_update.add_argument("--video", help="source video (default: the path stored in run.json)")

    p_splits = sub.add_parser("splits", help="(re)detect only the splits of an analyzed run: toasts, dimension, "
                                             "resets (reuses samples.csv screens) and rebuild analysis.json")
    p_splits.add_argument("out_dir")
    p_splits.add_argument("--video", help="source video (default: the path stored in run.json)")

    p_opp = sub.add_parser("opponent", help="(re)read only the opponent panel + match clock of an analyzed run "
                                            "(opponent.csv, clock.csv) and rebuild analysis.json")
    p_opp.add_argument("out_dir")
    p_opp.add_argument("--video", help="source video (default: the path stored in run.json)")

    p_f3 = sub.add_parser("f3", help="(re)read only the F3 screens of an analyzed run (position, facing, "
                                     "dimension, biome -> f3.csv) and rebuild analysis.json")
    p_f3.add_argument("out_dir")
    p_f3.add_argument("--video", help="source video (default: the path stored in run.json)")

    p_layout = sub.add_parser("layout", help="(re)calibrate a run's layout.json (GUI scale, overlays, panel, clock, "
                                             "strips) and/or draw it on frames of the video")
    p_layout.add_argument("out_dir")
    p_layout.add_argument("--video", help="source video (default: the path stored in run.json)")
    p_layout.add_argument("--image", help="save a contact sheet of the detected layout to this PNG")
    p_layout.add_argument("--recalibrate", action="store_true", help="measure again even if layout.json exists")

    p_serve = sub.add_parser("serve", help="serve the review UI on http://127.0.0.1:PORT")
    p_serve.add_argument("--runs", default=str(DEFAULT_RUNS), help="folder of analyzed runs (default: runs/)")
    p_serve.add_argument("--port", type=int, default=8000)

    p_eval = sub.add_parser("evaluate", help="score analyzed runs against their truth.csv answer keys "
                                             "(scorecard + runs/evaluation.json)")
    p_eval.add_argument("runs", nargs="?", default=str(DEFAULT_RUNS), help="folder of runs (default: runs/)")
    p_eval.add_argument("--tolerance", type=float, default=1.0, help="split hit tolerance in s (default 1.0)")
    p_eval.add_argument("--opp-tolerance", type=float, default=3.0,
                        help="opponent split hit tolerance in s (default 3.0)")
    p_eval.add_argument("--out", help="where to write the JSON (default: <runs>/evaluation.json)")

    p_frame = sub.add_parser("frame", help="save the frame at a timestamp as an image")
    p_frame.add_argument("video")
    p_frame.add_argument("timestamp", help="mm:ss (e.g. 02:20 or 02:20.5)")
    p_frame.add_argument("output", help="image path, e.g. frame.png")

    args = parser.parse_args()
    if args.command == "analyze":
        analyze(args.video, args.out, make_video=not args.no_video)
    elif args.command == "rebuild-json":
        rebuild_json(args.out_dir)
    elif args.command == "update-run":
        update_run(args.out_dir, args.video)
    elif args.command == "splits":
        detect_splits(args.out_dir, args.video)
    elif args.command == "opponent":
        detect_opponent(args.out_dir, args.video)
    elif args.command == "f3":
        detect_f3(args.out_dir, args.video)
    elif args.command == "layout":
        layout_command(args.out_dir, args.video, args.image, args.recalibrate)
    elif args.command == "serve":
        from .server import serve      # imported lazily: analyze doesn't need FastAPI
        serve(args.runs, args.port)
    elif args.command == "evaluate":
        from .evaluate import evaluate
        evaluate(args.runs, args.tolerance, args.opp_tolerance, args.out)
    elif args.command == "frame":
        frame = read_frame_at(args.video, parse_timestamp(args.timestamp))
        if frame is None:
            raise SystemExit("Timestamp is past the end of the video.")
        cv2.imwrite(args.output, frame)
        print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
