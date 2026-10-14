"""Reading frames from the video file."""

import cv2


def open_video(path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {path}")
    return cap


def iter_samples(path, samples_per_second):
    """Yield (time_seconds, frame) about `samples_per_second` times per second.

    We still have to step through every frame (video is compressed relative to
    earlier frames), but for frames we skip we only call grab(), which decodes
    without converting to an image - noticeably faster than read().
    """
    cap = open_video(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps / samples_per_second))
    index = 0
    try:
        while True:
            if index % step == 0:
                ok, frame = cap.read()
                if not ok:
                    break
                yield index / fps, frame
            elif not cap.grab():
                break
            index += 1
    finally:
        cap.release()


def video_info(path):
    """Return (fps, frame_count, width, height, duration_seconds)."""
    cap = open_video(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return fps, count, width, height, count / fps


def read_frame_at(path, seconds):
    """Return the frame shown at `seconds` into the video (or None)."""
    cap = open_video(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(seconds * fps)))
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None
