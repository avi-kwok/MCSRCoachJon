"""Command line entry point:  python -m vodreview <command> ..."""

import argparse
from pathlib import Path

import cv2

from .analyze import analyze
from .video import read_frame_at

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "out"


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

    p_frame = sub.add_parser("frame", help="save the frame at a timestamp as an image")
    p_frame.add_argument("video")
    p_frame.add_argument("timestamp", help="mm:ss (e.g. 02:20 or 02:20.5)")
    p_frame.add_argument("output", help="image path, e.g. frame.png")

    args = parser.parse_args()
    if args.command == "analyze":
        analyze(args.video, args.out)
    elif args.command == "frame":
        frame = read_frame_at(args.video, parse_timestamp(args.timestamp))
        if frame is None:
            raise SystemExit("Timestamp is past the end of the video.")
        cv2.imwrite(args.output, frame)
        print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
