"""Private room or ranked match? Read from the MCSR panel's mode line.

Under "Current Match" the MCSR panel shows the match mode: "Ranked Mode" in a ranked
match, "Private Room" in a private room. That line is MCSR's own text (English even in
a Norwegian-language game, like "Match Winner:"), so it is found by template matching
(calibration/panel/*.png), at a few scales because the panel font size varies per video,
on a handful of frames spread over the video. Majority vote -> True / False / None.

Why it matters: a forfeit in a private room ends the match as a draw ("Match is over!" /
"Match Draw!"), while in ranked it is a loss; and a private room has no opponent, so the
panel's player row is our own status.
"""

import cv2
import numpy as np

from . import config
from .video import open_video


def _templates():
    out = {}
    for name, font_px in config.MODE_TEMPLATES.items():
        image = cv2.imread(str(config.CALIBRATION_DIR / "panel" / f"{name}.png"), cv2.IMREAD_GRAYSCALE)
        if image is not None:
            out[name] = (image, font_px)
    return out


def _best(gray, template, base_font_px):
    best = 0.0
    for font_px in config.MODE_FONT_PX:
        s = config.MODE_SEARCH_SCALE * font_px / base_font_px
        t = cv2.resize(template, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        if t.shape[0] < 6 or t.shape[0] > gray.shape[0] or t.shape[1] > gray.shape[1]:
            continue
        best = max(best, float(cv2.minMaxLoc(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))[1]))
    return best


def mode_scores(frame, templates):
    """{template name: best match score} for one BGR frame."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=config.MODE_SEARCH_SCALE, fy=config.MODE_SEARCH_SCALE,
                      interpolation=cv2.INTER_AREA)
    return {name: _best(gray, image, font_px) for name, (image, font_px) in templates.items()}


def detect_private_room(video_path, start_s, end_s, verbose=True):
    """Vote over MODE_FRAMES frames in [start_s, end_s] -> True (private room), False (ranked) or None."""
    templates = _templates()
    if len(templates) < 2 or end_s <= start_s:
        return None
    cap = open_video(video_path)
    votes = {"private_room": 0, "ranked_mode": 0}
    try:
        for t in np.linspace(start_s, end_s, config.MODE_FRAMES + 2)[1:-1]:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            scores = mode_scores(frame, templates)
            name = max(scores, key=scores.get)
            other = min(scores.values())
            if scores[name] >= config.MODE_MIN_SCORE and scores[name] - other >= config.MODE_MIN_MARGIN:
                votes[name] += 1
    finally:
        cap.release()
    private, ranked = votes["private_room"], votes["ranked_mode"]
    decided = (True if private >= config.MODE_MIN_VOTES and private > ranked else
               False if ranked >= config.MODE_MIN_VOTES and ranked > private else None)
    if verbose:
        print(f"Match mode     : private room {private} / ranked {ranked} frames -> "
              f"{ {True: 'private room', False: 'ranked', None: 'unknown'}[decided] }")
    return decided
