"""Final time: read "(MM:SS.mmm)" from the MCSR match-result screen.

The result screen shows a title ("Victory!" gold on a win, red on a loss) and
under it "Match Winner: <name> (<time>)". ResultDetector.locate() already finds
the "Match Winner:" label by template matching; the time is on the same text
row, to the right of it. That row is read with the glyph reader in
vodreview/glyphs.py (threshold -> column projection -> font-pixel grid ->
template match per glyph).

Note: on a *loss* the line names the **winner** and shows the winner's time,
not the runner's. We still read the time shown (it is the match's final time)
and record `result` next to it, so the UI can say "Lost 18:02.441".

One frame can be misread (the subtitle zooms in and fades in for ~0.3 s, a
bright block can sit behind a glyph), so several frames are read and the
majority text wins.
"""

import re
from collections import Counter

import cv2

from . import config
from .glyphs import load_glyph_templates, read_line
from .runend import ResultDetector
from .video import open_video

TIME_IN_PARENS = re.compile(r"\((\d{1,2}):(\d{2})\.(\d{3})\)")


def parse_time(text, max_ms=None):
    """'(21:34.123)' somewhere in `text` -> ('21:34.123', 1294123) or None if invalid."""
    match = TIME_IN_PARENS.search(text)
    if not match:
        return None
    minutes, seconds, millis = (int(g) for g in match.groups())
    if minutes > 59 or seconds > 59:
        return None
    ms = (minutes * 60 + seconds) * 1000 + millis
    if max_ms is not None and ms > max_ms:
        return None
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}", ms


def read_time_in_frame(frame, label_box, templates, max_ms=None):
    """Read the result line next to the "Match Winner:" label in one BGR frame.

    Returns (raw_text, parsed) where parsed is (text, ms) or None.
    """
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = label_box
    pad = (y1 - y0) // 10
    # The line is centred, so it ends about as far from the right edge as the
    # label starts from the left edge.
    right = min(width, width - x0 + (x1 - x0) // 10)
    crop = frame[max(0, y0 - pad):min(height, y1 + pad), x1:right]
    if crop.size == 0:
        return "", None
    raw, _ = read_line(crop, templates, shadow=True)
    return raw, parse_time(raw, max_ms)


def consensus(texts):
    """Majority vote over valid reads; needs >= 2 agreeing reads and > half of them."""
    if not texts:
        return None
    text, count = Counter(texts).most_common(1)[0]
    if count >= 2 and count * 2 > len(texts):
        return text
    return None


def read_final_time(video_path, start_s, end_s, duration_s, verbose=True):
    """Read the final time from the result screen between start_s and end_s.

    Scans forward from start_s; once the "Match Winner:" label is found, reads
    every FINAL_TIME_FRAME_STEP-th frame for FINAL_TIME_READ_SECONDS (or until
    FINAL_TIME_MAX_READS valid reads). Returns
    {"text", "ms", "reads": [(t, raw, text_or_None)]}; text/ms are None if no
    consensus.
    """
    templates = load_glyph_templates()
    max_ms = int((duration_s + config.FINAL_TIME_SLACK_S) * 1000)
    cap = open_video(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    detector = ResultDetector(int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    index = int(round(start_s * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    reads, first_seen = [], None
    try:
        while index / fps <= end_s:
            t = index / fps
            if first_seen is not None and t > first_seen + config.FINAL_TIME_READ_SECONDS:
                break
            if index % config.FINAL_TIME_FRAME_STEP:
                ok = cap.grab()
            else:
                ok, frame = cap.read()
                if ok:
                    found = detector.locate(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                    if found:
                        first_seen = t if first_seen is None else first_seen
                        raw, parsed = read_time_in_frame(frame, found[1], templates, max_ms)
                        reads.append((round(t, 3), raw, parsed[0] if parsed else None))
                        if sum(1 for r in reads if r[2]) >= config.FINAL_TIME_MAX_READS:
                            break
            if not ok:
                break
            index += 1
    finally:
        cap.release()
    text = consensus([r[2] for r in reads if r[2]])
    if verbose:
        valid = [r for r in reads if r[2]]
        print(f"Final time: {len(reads)} result-screen frames read, {len(valid)} valid -> {text or 'no consensus'}")
        for t, raw, parsed in reads:
            print(f"  {int(t // 60)}:{t % 60:06.3f}  read {raw!r:24} -> {parsed or '-'}")
    return {"text": text, "ms": parse_time(f"({text})")[1] if text else None, "reads": reads}
