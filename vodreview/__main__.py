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
    p_analyze.add_argument("--flow", action="store_true", help="also measure camera rotation from optical flow "
                                                             "(flow.csv; slow - see `flow`)")

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

    p_flow = sub.add_parser("flow", help="camera rotation (yaw/pitch) from optical flow -> runs/<id>/flow.csv, "
                                         "FOV in layout.json; scored against F3 facing when present")
    p_flow.add_argument("out_dir")
    p_flow.add_argument("--video", help="source video (default: the path stored in run.json)")
    p_flow.add_argument("--fps", type=float, help="frame pairs per second (default config.FLOW_FPS)")
    p_flow.add_argument("--reuse", action="store_true", help="re-fit from the cached tracks (flow_tracks.npz)")
    p_flow.add_argument("--no-eval", action="store_true", help="skip the comparison with F3")

    p_odo = sub.add_parser("odometry", help="player movement between F3 anchors from optical flow "
                                            "(odometry.csv, odometry_track.csv)")
    p_odo.add_argument("out_dir")
    p_odo.add_argument("--video", help="source video (default: the run's video.mp4 / run.json path)")
    p_odo.add_argument("--fps", type=int, help="frames tracked per second (default config.ODO_SAMPLES_PER_SECOND)")
    p_odo.add_argument("--eval", action="store_true", help="also hide F3 for 5/10/30 s windows and score "
                                                          "against it (odometry_eval.json)")
    p_odo.add_argument("--cache", help="save / reuse the tracked points in this .npz (skips the video pass)")

    p_frame = sub.add_parser("frame", help="save the frame at a timestamp as an image")
    p_frame.add_argument("video")
    p_frame.add_argument("timestamp", help="mm:ss (e.g. 02:20 or 02:20.5)")
    p_frame.add_argument("output", help="image path, e.g. frame.png")

    p_hot = sub.add_parser("hotbar", help="read the 9 hotbar slots (item + count) on world/F3 screens -> "
                                          "runs/<id>/hotbar.csv + hotbar_changes.csv")
    p_hot.add_argument("out_dir")
    p_hot.add_argument("--video", help="source video (default: the run's video.mp4 / run.json path)")
    p_hot.add_argument("--fps", type=float, help="reads per second (default config.HOTBAR_FPS)")
    p_hot.add_argument("--rebuild-templates", action="store_true",
                       help="re-render calibration/items/sprites.npz from the texture folder first")

    p_inv = sub.add_parser("inventory", help="save the inventory/container panel last open at or before a time "
                                             "(get_inventory; cheaper than a full frame)")
    p_inv.add_argument("out_dir")
    p_inv.add_argument("timestamp", help="m:ss.s VOD time")
    p_inv.add_argument("output", help="PNG path")

    p_digest = sub.add_parser("digest", help="write runs/<id>/digest.md: compact text summary for an LLM coach")
    p_digest.add_argument("out_dir")

    p_pack = sub.add_parser("coach-pack", help="write runs/<id>/coach_prompt.md (system prompt + knowledge + "
                                               "schema + digest) to paste into Claude by hand")
    p_pack.add_argument("out_dir")

    p_import = sub.add_parser("import-tips", help="validate a coach tips JSON (coach/schema.json) and store it "
                                                  "as tips in runs/<id>/analysis.json")
    p_import.add_argument("out_dir")
    p_import.add_argument("tips_file")

    p_critic = sub.add_parser("critic-pack", help="automatic evidence checks on a coach tips JSON "
                                                  "(runs/<id>/critic_checks.json) + runs/<id>/critic_prompt.md")
    p_critic.add_argument("out_dir")
    p_critic.add_argument("tips_file")

    p_lessons = sub.add_parser("add-lessons", help="append a critic's proposed lessons to coach/pending_lessons.md")
    p_lessons.add_argument("lessons_file", help="critic JSON / reply with a ```json block / markdown bullets")
    p_lessons.add_argument("--run", help="source run id (default: run_id in the file)")
    p_lessons.add_argument("--force", action="store_true", help="also add lessons that look run-specific")

    p_golden = sub.add_parser("golden-score", help="per-tip checklist + expected-route match from "
                                                   "coach/golden/README.md; score template in coach/golden/scores/")
    p_golden.add_argument("out_dir")
    p_golden.add_argument("tips_file")

    args = parser.parse_args()
    if args.command == "analyze":
        analyze(args.video, args.out, make_video=not args.no_video)
        if args.flow:
            from .flow import flow_command
            flow_command(args.out, args.video)
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
    elif args.command == "hotbar":
        from .hotbar import build_templates, hotbar_command
        if args.rebuild_templates:
            build_templates()
        hotbar_command(args.out_dir, args.video, args.fps)
    elif args.command == "inventory":
        from .inventory import get_inventory
        get_inventory(args.out_dir, parse_timestamp(args.timestamp), args.output)
    elif args.command == "digest":
        from .digest import write_digest
        write_digest(args.out_dir)
    elif args.command == "coach-pack":
        from .coach import coach_pack
        coach_pack(args.out_dir)
    elif args.command == "import-tips":
        from .coach import import_tips
        import_tips(args.out_dir, args.tips_file)
    elif args.command == "critic-pack":
        from .critic import critic_pack
        critic_pack(args.out_dir, args.tips_file)
    elif args.command == "add-lessons":
        from .critic import add_lessons
        add_lessons(args.lessons_file, args.run, args.force)
    elif args.command == "golden-score":
        from .critic import golden_score
        golden_score(args.out_dir, args.tips_file)
    elif args.command == "flow":
        from .flow import flow_command
        flow_command(args.out_dir, args.video, args.fps, args.reuse, not args.no_eval)
    elif args.command == "odometry":
        from .odometry import odometry_command
        odometry_command(args.out_dir, args.video, args.fps, args.eval, args.cache)
    elif args.command == "frame":
        frame = read_frame_at(args.video, parse_timestamp(args.timestamp))
        if frame is None:
            raise SystemExit("Timestamp is past the end of the video.")
        cv2.imwrite(args.output, frame)
        print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
