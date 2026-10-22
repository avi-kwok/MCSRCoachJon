"""Final time: read "(MM:SS.mmm)" from the MCSR match-result screen.

The result screen shows a title ("Victory!" gold on a win, red on a loss) and
under it "Match Winner: <name> (<time>)" on the subtitle row (vanilla title
geometry: 10-26 GUI px below the screen centre, drawn at 2x the GUI scale).
That row is found by GUI geometry at the measured scale - no label template -
and the text line on it is read with the glyph reader in vodreview/glyphs.py
(threshold -> column projection -> font-pixel grid -> template match per
glyph); the "(MM:SS.mmm)" is found in the read by a regex (digits and
brackets are language-free).

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
import numpy as np

from . import config
from .glyphs import keep_shadowed, load_glyph_templates, match_glyph, read_line, segment_line, text_mask
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


def read_result_line(frame, row_box, templates, max_ms=None):
    """Read the subtitle row of the result screen -> (raw_text, parsed (text, ms) or None).

    The row box spans the whole width the centred line can take; the text
    band inside it is the run of rows holding light shadowed text.
    """
    x0, y0, x1, y1 = row_box
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return "", None
    raw, _ = read_line(crop, templates, shadow=True)
    return raw, parse_time(raw, max_ms)


def read_result_time_right(frame, row_box, centre_x, font_px, templates, max_ms=None):
    """Fallback for a cluttered subtitle row (F3 text, bright sand/snow behind it).

    The time is the last part of the centred line, so only the row right of the screen
    centre is read, at the known subtitle font size (2x GUI), with a few mask variants:
    a stricter light threshold drops sand, and an opening (erode + dilate) of ~1.3 GUI px
    removes the 1x F3 strokes but keeps the 2x subtitle strokes. The strict
    "(MM:SS.mmm)" regex decides which variant read it. -> (raw_text, parsed or None)
    """
    x0, y0, x1, y1 = row_box
    crop = frame[y0:y1, max(x0, int(centre_x)):x1]
    if crop.size == 0:
        return "", None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    raw = ""
    for min_light, open_gui in config.RESULT_TIME_MASK_VARIANTS:
        mask = text_mask(crop, min_light=min_light)
        if open_gui:
            n = max(1, int(round(open_gui * font_px / 2)))
            mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((n, n), np.uint8)) > 0
        mask = keep_shadowed(mask, gray, int(round(font_px)))
        _, glyphs = segment_line(mask, font_px)
        text = "".join((" " if gl["gap"] >= 3 else "") + match_glyph(gl["grid"], templates)[0] for gl in glyphs)
        parsed = parse_time(text, max_ms)
        if parsed:
            return text, parsed
        raw = raw or text
    return raw, None


def read_time_in_frame(frame, label_box, templates, max_ms=None):
    """Read the result line in one BGR frame, starting right of the "Match Winner:" label box.

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


def read_final_time(video_path, start_s, end_s, duration_s, lay, verbose=True):
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
    detector = ResultDetector(lay)
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
                    raw = parsed = None
                    if found:
                        # English label found: read right of it (the tuning VOD's original reader) ...
                        raw, parsed = read_time_in_frame(frame, found[1], templates, max_ms)
                    if parsed is None and (found or detector.language_free(frame)):
                        # ... else the whole subtitle row (language-free)
                        raw, parsed = detector.read_time(frame, max_ms)
                    if raw is not None:
                        first_seen = t if first_seen is None else first_seen
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
