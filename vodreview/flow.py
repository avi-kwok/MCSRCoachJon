"""Camera rotation (yaw / pitch) from optical flow -> runs/<id>/flow.csv.

CV idea: *sparse feature tracking*. When the player turns the mouse, every
block in view slides across the screen. We pick a few hundred "corners"
(small patches that look different from their neighbours in every direction,
e.g. where two block textures meet - goodFeaturesToTrack), find where each one
went in the next frame (pyramidal Lucas-Kanade: match the patch around the
corner, first on blurred half/quarter-size copies for big jumps, then refine
at full size), and check every track by following it *back* again (the
forward-backward check: a good track returns to where it started).

Camera model (a "pinhole" camera). Camera coordinates: x right, y down, z
forward. A pixel (u, v) looks along the ray

    c = ((u - cx) / f, (v - cy) / f, 1)

where (cx, cy) is the picture centre and f the *focal length* in pixels. f
comes from the field of view: Minecraft's FOV setting is the *vertical* view
angle, so f = (height / 2) / tan(vfov / 2). Turning the camera without moving
(a pure rotation R) maps every ray c to R^T c - this is the homography
H = K R K^-1 of the textbook, done on rays instead of pixels. The player's
position barely matters: blocks a few metres away hardly shift when the
player walks one frame's worth (and those that do are rejected as outliers).

Minecraft's camera is "yaw then pitch": yaw turns around the world's vertical
axis (yaw grows turning right), pitch tilts the view down (+90 = straight
down). From camera to world:  R(yaw, pitch) = Ry(yaw) . Rx(pitch).  Between
two frames the absolute yaw cancels, so a ray moves as

    c' ~ Rx(pitch + dpitch)^T . Ry(dyaw)^T . Rx(pitch) . c

i.e. the picture motion depends on the two deltas *and* the current pitch
(looking straight down, turning left/right spins the picture around its
centre). We fit (dyaw, dpitch) - plus an optional zoom factor for the FOV
change when sprinting starts/stops - robustly:

1. every track proposes its own (dyaw, dpitch) from the small-angle (linear)
   version of the model (1-point RANSAC: one track pins down both angles),
2. the proposal most other tracks agree with (within a few px) wins; tracks
   that disagree are outliers (moving mobs, nearby blocks seen while walking,
   bad tracks),
3. Gauss-Newton refines the exact (non-linear) model on the inliers.

f is unknown per player (and the picture zooms out ~15% when sprinting if
"FOV effects" is on), so `fit_fov` measures it per video by comparing the flow
with the F3 yaw where F3 is visible. Integrated rotation drifts, so the F3
"Facing" reads are anchors: between two anchors the flow fills in the motion
and the small disagreement at the second anchor is spread over the interval.

Frames that can't be tracked are never guessed: menus (the camera can't turn
while a GUI is open -> zero rotation), resized MCSR strips and screen changes
(unknown), and featureless views - sky, fog, darkness (too few corners ->
"lowtex", unknown).
"""

import bisect
import csv
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from . import config
from .f3 import check_reads, is_valid, read_f3_csv
from .layout import load_layout, save_layout
from .report import read_samples_csv
from .video import open_video

TRACK_SCREENS = ("world", "f3")                  # the world is in view: track it
MENU_SCREENS = ("inventory", "pause", "settings")  # a GUI is open: the camera can't turn
FLOW_FIELDS = ["t", "dt", "dyaw", "dpitch", "zoom", "n_tracks", "inliers", "confidence", "src",
               "yaw_flow", "pitch_flow", "yaw", "pitch", "anchor_s"]


def wrap180(a):
    """Angle difference(s) in degrees -> [-180, 180)."""
    return (np.asarray(a) + 180.0) % 360.0 - 180.0


# --- camera model -------------------------------------------------------------------------------

def rot_x(a):
    """Pitch: tilt the view down by `a` radians (camera -> world; y is down, so forward -> (0, sin a, cos a))."""
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, s], [0, -s, c]])


def rot_y(a):
    """Yaw: turn right by `a` radians around the vertical axis (forward -> (sin a, 0, cos a))."""
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def project(xy, pitch, dyaw, dpitch, log_zoom=0.0):
    """Where the rays through normalized points xy (N x 2, = pixel offset / f) land after the camera
    turns by (dyaw, dpitch) radians from `pitch`; log_zoom scales the picture (FOV change)."""
    m = rot_x(pitch + dpitch).T @ rot_y(dyaw).T @ rot_x(pitch)
    c = np.c_[xy, np.ones(len(xy))] @ m.T          # rotate every ray
    z = np.maximum(c[:, 2:3], 1e-6)                 # (rays that end up behind the camera are outliers anyway)
    return math.exp(log_zoom) * c[:, :2] / z        # back to the picture plane (divide by depth)


def jacobian(xy, pitch, params, n):
    """d project / d params, numerically (N x 2 x n) - how each point moves per radian of each parameter."""
    base = project(xy, pitch, *params)
    cols = []
    for i in range(n):
        p = list(params)
        p[i] += 1e-5
        cols.append((project(xy, pitch, *p) - base) / 1e-5)
    return np.stack(cols, axis=2), base


def fit_pure_rotation(xy0, xy1, pitch_deg, f, fit_zoom=None):
    """Robust (dyaw, dpitch) in degrees between two frames from matched points, camera only turning.

    xy0 / xy1: N x 2 pixel offsets from the picture centre (full-resolution px).
    f: focal length in px. Returns dict(dyaw, dpitch, log_zoom, inliers, rms_px) or None.
    """
    fit_zoom = config.FLOW_FIT_ZOOM if fit_zoom is None else fit_zoom
    if len(xy0) < config.FLOW_MIN_INLIERS:
        return None
    a, b = xy0 / f, xy1 / f                         # pixels -> normalized rays
    p = math.radians(pitch_deg)
    # 1. Small-angle model: motion of point i ~ J_i . (dyaw, dpitch). One point = 2 equations = 2 unknowns,
    #    so every track proposes a rotation (1-point RANSAC). Hypotheses from (at most) 120 tracks.
    J, _ = jacobian(a, p, (0.0, 0.0), 2)
    d = b - a
    hyp_idx = np.arange(len(a)) if len(a) <= 120 else np.linspace(0, len(a) - 1, 120).astype(int)
    Jh = J[hyp_idx]
    det = Jh[:, 0, 0] * Jh[:, 1, 1] - Jh[:, 0, 1] * Jh[:, 1, 0]
    ok = np.abs(det) > 1e-3
    if not ok.any():
        return None
    Jh, dh, det = Jh[ok], d[hyp_idx][ok], det[ok]
    hyp = np.stack([(Jh[:, 1, 1] * dh[:, 0] - Jh[:, 0, 1] * dh[:, 1]) / det,      # 2x2 inverse
                    (-Jh[:, 1, 0] * dh[:, 0] + Jh[:, 0, 0] * dh[:, 1]) / det], axis=1)
    pred = np.einsum("nij,hj->hni", J, hyp)          # every hypothesis applied to every point
    err = np.linalg.norm(pred - d[None], axis=2) * f  # px
    # Linear model error grows with the angle, so allow more slack for big flicks.
    thr = max(config.FLOW_RANSAC_PX, config.FLOW_RANSAC_REL * float(np.median(np.linalg.norm(d, axis=1))) * f)
    score = (err < thr).sum(axis=1)
    best = int(np.argmax(score))
    inl = err[best] < thr
    params = [float(hyp[best, 0]), float(hyp[best, 1]), 0.0]
    n = 3 if fit_zoom else 2
    # 3. Gauss-Newton on the exact model, re-selecting inliers with the exact residual.
    for it in range(config.FLOW_GN_ITERS):
        if inl.sum() < config.FLOW_MIN_INLIERS:
            return None
        Ji, base = jacobian(a[inl], p, params, n)
        r = (b[inl] - base).reshape(-1)
        step, *_ = np.linalg.lstsq(Ji.reshape(-1, n), r, rcond=None)
        for i in range(n):
            params[i] += float(step[i])
        res = np.linalg.norm(project(a, p, *params) - b, axis=1) * f
        inl = res < (thr if it == 0 else config.FLOW_INLIER_PX)
    if inl.sum() < config.FLOW_MIN_INLIERS:
        return None
    return {"dyaw": math.degrees(params[0]), "dpitch": math.degrees(params[1]), "log_zoom": params[2],
            "inliers": int(inl.sum()), "rms_px": float(np.sqrt(np.mean(res[inl] ** 2)))}


def rotation_to_angles(R, pitch_deg):
    """A general 3-D camera rotation (ray mapping c' = R c) -> the Minecraft (dyaw, dpitch) in degrees
    that comes closest (Minecraft never rolls; what's left over is view bobbing / noise)."""
    p = math.radians(pitch_deg)
    # First guess from the rotation vector (axis * angle) of R^T: its component along the world's vertical
    # axis seen from the camera, (0, cos p, sin p), is the yaw change; along the camera's x axis, the pitch.
    w = cv2.Rodrigues(np.ascontiguousarray(R.T))[0].ravel()
    x = np.array([w @ np.array([0.0, math.cos(p), math.sin(p)]), -w[0]])
    for _ in range(5):                      # Gauss-Newton: make the 9 entries of R match
        def resid(v):
            return (rot_x(p + v[1]).T @ rot_y(v[0]).T @ rot_x(p) - R).ravel()
        r0 = resid(x)
        J = np.stack([(resid(x + e) - r0) / 1e-6 for e in np.eye(2) * 1e-6], axis=1)
        x = x - np.linalg.lstsq(J, r0, rcond=None)[0]
    return math.degrees(x[0]), math.degrees(x[1])


def fit_rotation(xy0, xy1, pitch_deg, f):
    """Camera rotation between two frames, allowing the player to move as well.

    Minecraft scenes are close (a tree 3 blocks away shifts several degrees when the player walks one
    step), so a pure rotation often explains only the far points. When it explains too few tracks we fit
    the general motion: the *essential matrix* E (rotation R + direction of travel t; every match must
    satisfy x1^T E x0 = 0 whatever its depth), found with 5-point RANSAC, and keep R.
    -> dict(dyaw, dpitch, log_zoom, inliers, rms_px, model) or None.
    """
    pure = fit_pure_rotation(xy0, xy1, pitch_deg, f)
    n = len(xy0)
    if pure is not None and pure["inliers"] >= config.FLOW_PURE_GOOD_SHARE * n:
        return dict(pure, model="rot")
    if n < config.FLOW_MIN_INLIERS:
        return pure and dict(pure, model="rot")
    K = np.array([[f, 0, 0], [0, f, 0], [0, 0, 1.0]])
    a, b = xy0.astype(np.float64), xy1.astype(np.float64)
    E, inl = cv2.findEssentialMat(a, b, K, cv2.RANSAC, 0.999, config.FLOW_ESSENTIAL_PX)
    if E is None or E.shape[0] < 3:
        return pure and dict(pure, model="rot")
    _, R, _, _ = cv2.recoverPose(E[:3], a, b, K, mask=inl.copy())
    k = int(inl.sum())
    if pure is not None and pure["inliers"] >= k:
        return dict(pure, model="rot")
    if k < config.FLOW_MIN_INLIERS:
        return None
    dyaw, dpitch = rotation_to_angles(R, pitch_deg)
    return {"dyaw": dyaw, "dpitch": dpitch, "log_zoom": 0.0, "inliers": k, "rms_px": config.FLOW_ESSENTIAL_PX / 2,
            "model": "E"}


def focal_from_vfov(vfov_deg, height):
    return (height / 2) / math.tan(math.radians(vfov_deg) / 2)


def vfov_from_focal(f, height):
    return math.degrees(2 * math.atan((height / 2) / f))


# --- tracking ------------------------------------------------------------------------------------

def light_grey(bgr):
    """uint8 mask (255) of light, unsaturated pixels - F3 text (like glyphs.text_mask, but with OpenCV: ~10x faster)."""
    b, g, r = cv2.split(bgr)
    lo, hi = cv2.min(cv2.min(b, g), r), cv2.max(cv2.max(b, g), r)
    return cv2.bitwise_and(cv2.threshold(lo, config.FLOW_TEXT_MIN - 1, 255, cv2.THRESH_BINARY)[1],
                           cv2.threshold(cv2.subtract(hi, lo), config.FLOW_TEXT_MAX_CHROMA, 255,
                                         cv2.THRESH_BINARY_INV)[1])


class Tracker:
    """Corners + Lucas-Kanade between two shrunk grey frames, with the HUD / overlays / hand / F3 text masked."""

    def __init__(self, lay):
        self.lay = lay
        gx0, gy0, gx1, gy1 = lay.game
        self.scale = config.FLOW_WORK_W / (gx1 - gx0)          # full-res px -> work px
        self.size = (int(round(lay.w * self.scale)), int(round(lay.h * self.scale)))
        w, h = self.size
        m = np.zeros((h, w), np.uint8)
        s = self.scale
        m[int(gy0 * s):int(gy1 * s), int(gx0 * s):int(gx1 * s)] = 255   # only the game view
        rects = lay.overlay_rects() + lay.hud_rects()
        hx0, hy0, hx1, hy1 = config.FLOW_HAND_RECT                    # held item / arm (game-view fractions)
        gw, gh = gx1 - gx0, gy1 - gy0
        rects.append(lay.norm((gx0 + hx0 * gw, gy0 + hy0 * gh, gx0 + hx1 * gw, gy0 + hy1 * gh)))
        rects.append(lay.norm(lay.gui_rect(-config.FLOW_CROSSHAIR_GUI, -config.FLOW_CROSSHAIR_GUI,
                                           config.FLOW_CROSSHAIR_GUI, config.FLOW_CROSSHAIR_GUI,
                                           ax="center", ay="center")))
        for x0, y0, x1, y1 in rects:
            m[int(y0 * h):int(np.ceil(y1 * h)), int(x0 * w):int(np.ceil(x1 * w))] = 0
        self.mask = m
        # F3 text: searched for inside the F3 columns (the left one down to the bottom: the "Debug: Pie" /
        # "For help" lines sit there). Every text line has a dark background band that starts at the screen
        # edge and ends just past its last letter; letters and band edges don't move with the world, so each
        # row is masked from the screen edge to its outermost text pixel (+ a pad).
        boxes = [list(r) for r in lay.f3_rects()]
        boxes[0][3] = 1.0
        self.f3_boxes = [(int(x0 * w), int(y0 * h), int(np.ceil(x1 * w)), int(np.ceil(y1 * h)),
                          "left" if x0 < 0.01 else "right") for x0, y0, x1, y1 in boxes]
        self.text_pad = int(round(config.FLOW_TEXT_PAD_GUI * lay.k * s))
        ky = max(3, int(round(config.FLOW_TEXT_DILATE_GUI * lay.k * s)) | 1)
        self.dilate = np.ones((ky, 1), np.uint8)          # grow text rows up/down to cover the band
        self.cx, self.cy = lay.cx, lay.cy
        self.last_shift = None          # previous pair's median shift (work px): LK's starting guess
        self.orb = None
        self.lk = dict(winSize=(config.FLOW_LK_WIN, config.FLOW_LK_WIN), maxLevel=config.FLOW_LK_LEVELS,
                       criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))

    def prepare(self, frame, screen):
        """BGR frame -> (shrunk grey frame, corner mask for it)."""
        small = cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        mask = self.mask
        if screen == "f3":
            mask = mask.copy()
            for x0, y0, x1, y1, side in self.f3_boxes:
                text = cv2.dilate(light_grey(small[y0:y1, x0:x1]), self.dilate) > 0
                rows = text.any(axis=1)
                cols = np.arange(x1 - x0)
                if side == "left":    # left column: band from the left edge to the last letter
                    edge = (x1 - x0 - 1) - np.argmax(text[:, ::-1], axis=1) + self.text_pad
                    band = cols[None, :] <= edge[:, None]
                else:                 # right column is right-aligned: from the first letter to the right edge
                    edge = np.argmax(text, axis=1) - self.text_pad
                    band = cols[None, :] >= edge[:, None]
                mask[y0:y1, x0:x1][band & rows[:, None]] = 0
        return gray, mask

    def track(self, g0, mask0, g1):
        """-> (p0, p1, n_corners, diff): matched points as full-res px offsets from the picture centre, and
        how much the (unmasked) picture changed (mean grey difference)."""
        diff = cv2.mean(cv2.absdiff(g0, g1), mask=mask0)[0]
        pts = cv2.goodFeaturesToTrack(g0, config.FLOW_MAX_CORNERS, config.FLOW_CORNER_QUALITY,
                                      config.FLOW_MIN_DISTANCE, mask=mask0, blockSize=7)
        if pts is None or len(pts) < config.FLOW_MIN_TRACKS:
            self.last_shift = None
            return None, None, 0 if pts is None else len(pts), diff
        # Big jumps (fast turns): Lucas-Kanade only searches near where it starts, and blocky Minecraft
        # textures repeat. Mouse motion is smooth, so the previous pair's median shift is a good starting
        # guess; if few tracks survive with it, try again from zero and keep the better result.
        shift = self.last_shift
        good, p1 = self.lk_pair(g0, g1, pts, shift)
        if shift is not None and good.mean() < config.FLOW_GUESS_MIN_SURVIVE:
            good0, p10 = self.lk_pair(g0, g1, pts, None)
            if good0.sum() > good.sum():
                good, p1 = good0, p10
        moved = (p1 - pts).reshape(-1, 2)[good]
        self.last_shift = tuple(np.median(moved, axis=0)) if len(moved) >= config.FLOW_MIN_TRACKS else None
        a, b = pts.reshape(-1, 2)[good], p1.reshape(-1, 2)[good]
        centre = np.array([self.cx, self.cy])
        return ((a / self.scale - centre).astype(np.float32), (b / self.scale - centre).astype(np.float32),
                len(pts), diff)


    def lk_pair(self, g0, g1, pts, shift):
        """Forward + backward Lucas-Kanade from pts (optionally starting at pts + shift) -> (good, p1)."""
        if shift is None:
            p1, st, _ = cv2.calcOpticalFlowPyrLK(g0, g1, pts, None, **self.lk)
            back, st2, _ = cv2.calcOpticalFlowPyrLK(g1, g0, p1, None, **self.lk)
        else:
            guess = (pts + np.float32(shift)).astype(np.float32)
            p1, st, _ = cv2.calcOpticalFlowPyrLK(g0, g1, pts, guess, flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **self.lk)
            back0 = (p1 - np.float32(shift)).astype(np.float32)
            back, st2, _ = cv2.calcOpticalFlowPyrLK(g1, g0, p1, back0, flags=cv2.OPTFLOW_USE_INITIAL_FLOW,
                                                    **self.lk)
        fb = np.linalg.norm((back - pts).reshape(-1, 2), axis=1)
        return (st.reshape(-1) == 1) & (st2.reshape(-1) == 1) & (fb < config.FLOW_FB_MAX_PX), p1

    def match(self, g0, m0, g1, m1):
        """ORB feature matches between two frames far apart in time -> (p0, p1, n_keypoints) like track()."""
        if self.orb is None:
            self.orb = cv2.ORB_create(config.FLOW_ORB_FEATURES)
            self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        k0, d0 = self.orb.detectAndCompute(g0, m0)
        k1, d1 = self.orb.detectAndCompute(g1, m1)
        if d0 is None or d1 is None or len(k0) < config.FLOW_MIN_TRACKS or len(k1) < config.FLOW_MIN_TRACKS:
            return None, None, 0
        pairs = [m for m in self.matcher.knnMatch(d0, d1, k=2)
                 if len(m) == 2 and m[0].distance < config.FLOW_ORB_RATIO * m[1].distance]   # ratio test
        if len(pairs) < config.FLOW_MIN_TRACKS:
            return None, None, len(k0)
        centre = np.array([self.cx, self.cy])
        a = np.float32([k0[m[0].queryIdx].pt for m in pairs]) / self.scale - centre
        b = np.float32([k1[m[0].trainIdx].pt for m in pairs]) / self.scale - centre
        return a.astype(np.float32), b.astype(np.float32), len(k0)


class ScreenLookup:
    """Screen type at any time, from the analysis samples (samples.csv, 10 per second)."""

    def __init__(self, samples):
        self.t = [s.time for s in samples]
        self.screen = [s.screen for s in samples]

    def at(self, t):
        i = bisect.bisect_left(self.t, t)
        best = min((j for j in (i - 1, i) if 0 <= j < len(self.t)), key=lambda j: abs(self.t[j] - t), default=None)
        if best is None or abs(self.t[best] - t) > config.FLOW_SCREEN_MAX_DT:
            return ""
        return self.screen[best]


class F3Facing:
    """Valid F3 facing reads (yaw, pitch) by time - the ground truth / anchors."""

    def __init__(self, rows, fps):
        rows = rows or []
        if rows:
            check_reads(rows)
        good = [r for r in rows if is_valid(r) and r["yaw"] is not None and r["pitch"] is not None
                and "facing_mismatch" not in (r["flags"] or "")]
        self.t = np.array([r["time_s"] for r in good])
        self.frame = np.round(self.t * fps).astype(int)
        self.yaw = np.array([r["yaw"] for r in good])
        self.pitch = np.array([r["pitch"] for r in good])
        self.pos = np.array([[r["x"], r["z"]] for r in good]) if good else np.zeros((0, 2))
        self.by_frame = {int(fr): i for i, fr in enumerate(self.frame)}

    def __len__(self):
        return len(self.t)

    def near(self, t, max_dt):
        """Index of the read nearest to t (within max_dt) or None."""
        if not len(self.t):
            return None
        i = int(np.clip(np.searchsorted(self.t, t), 1, len(self.t) - 1)) if len(self.t) > 1 else 0
        j = min((i - 1, i), key=lambda k: abs(self.t[k] - t)) if len(self.t) > 1 else 0
        return j if abs(self.t[j] - t) <= max_dt else None


def judge(fit, n_points, diff):
    """Is a fitted rotation trustworthy? -> "ok" / "fail" / "blur".

    "blur": the tracks agree on (almost) no rotation, yet the picture changed a lot - during a fast flick
    the world smears, and the only corners left are things fixed to the screen (overlay / text edges).
    """
    if fit is None or fit["inliers"] < config.FLOW_MIN_INLIERS or \
            fit["inliers"] < config.FLOW_MIN_INLIER_SHARE * n_points:
        return "fail"
    if math.hypot(fit["dyaw"], fit["dpitch"]) < config.FLOW_STATIC_DEG and diff > config.FLOW_STATIC_MAX_DIFF:
        return "blur"
    return "ok"


def track_video(video_path, lay, screens, run_end, facing, fps_target=None, start_s=0.0):
    """Pass 1 (decode + track): -> list of steps (dicts with t0, t1, src, p0, p1, n_tracks).

    One step per pair of consecutive sampled frames (fps_target per second). A step that fails at that
    rate (too few tracks survive / no consistent rotation: usually a fast flick) is redone frame by frame
    on a second reader (`src` = "retry").
    """
    fps_target = fps_target or config.FLOW_FPS
    tracker = Tracker(lay)
    cap = open_video(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps / fps_target))
    f0 = focal_from_vfov(config.FLOW_DEFAULT_VFOV, lay.game[3] - lay.game[1])
    retry = {"cap": None, "pos": -1}
    steps, prev, index = [], None, int(start_s * fps) // step * step
    if index:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)    # (dev: start part-way in)
    stats = {"retries": 0, "retry_ok": 0}

    def pitch_hint(t):
        i = facing.near(t, 2.0)
        return float(facing.pitch[i]) if i is not None else 0.0

    def try_pair(g0, m0, g1, t):
        p0, p1, n, diff = tracker.track(g0, m0, g1)
        out = {"p0": p0, "p1": p1, "n_tracks": n, "diff": round(diff, 2)}
        if n < config.FLOW_MIN_TRACKS:                 # nothing to track: sky, fog, darkness
            return dict(out, src="lowtex", p0=None, p1=None)
        if p0 is None or len(p0) < config.FLOW_MIN_TRACKS:   # corners there, but the tracks got lost
            return dict(out, src="fail", p0=None, p1=None)
        return dict(out, src=judge(fit_rotation(p0, p1, pitch_hint(t), f0), len(p0), diff))

    def frames_between(i0, i1):
        """Frames i0..i1 (inclusive) from the retry reader (seeks only when it has to go back / far)."""
        if retry["cap"] is None:
            retry["cap"] = open_video(video_path)
        rc = retry["cap"]
        if not (0 <= i0 - retry["pos"] <= 2 * fps):
            rc.set(cv2.CAP_PROP_POS_FRAMES, i0)
            retry["pos"] = i0
        while retry["pos"] < i0:
            rc.grab()
            retry["pos"] += 1
        out = []
        for _ in range(i0, i1 + 1):
            ok, fr = rc.read()
            retry["pos"] += 1
            if not ok:
                break
            out.append(fr)
        return out

    def do_step(a, b):
        """a, b = (index, t, screen, gray, mask) of two sampled frames."""
        base = {"t0": a[1], "t1": b[1], "p0": None, "p1": None, "n_tracks": 0, "diff": 0.0}
        if a[2] in MENU_SCREENS and b[2] in MENU_SCREENS:
            steps.append(dict(base, src="menu"))
            return
        if a[2] not in TRACK_SCREENS or b[2] not in TRACK_SCREENS:
            steps.append(dict(base, src="screen"))
            return
        first = try_pair(a[3], a[4], b[3], a[1])
        if first["src"] not in ("fail", "blur") or b[0] - a[0] < 2:
            steps.append(dict(base, **first))
            return
        # Fast flick: redo this step at the full frame rate (smaller jumps track much better).
        stats["retries"] += 1
        frames = frames_between(a[0], b[0])
        if len(frames) != b[0] - a[0] + 1:
            steps.append(dict(base, **first))
            return
        prepared = [tracker.prepare(fr, a[2] if i == 0 else b[2]) for i, fr in enumerate(frames)]
        tracker.last_shift = None                   # (the guess was for a 4x longer step)
        sub = []
        for i in range(len(prepared) - 1):
            t0 = (a[0] + i) / fps
            r = try_pair(prepared[i][0], prepared[i][1], prepared[i + 1][0], t0)
            sub.append(dict(r, t0=t0, t1=t0 + 1 / fps, src="retry" if r["src"] == "ok" else r["src"]))
        if tracker.last_shift is not None:
            tracker.last_shift = tuple(v * len(sub) for v in tracker.last_shift)
        if all(x["src"] == "retry" for x in sub):
            stats["retry_ok"] += 1
        steps.extend(sub)

    gap, last_world = None, None

    def follow_gap(gap, prev, n_before):
        """Keep track of runs of steps that couldn't be tracked; when tracking resumes, bridge the run.

        Bridging: match the last frame before the run straight to the first frame after it with ORB
        features (binary descriptors of corners: they recognise the same corner after a big jump, where
        Lucas-Kanade only searches nearby). Works while the two views still overlap (flick < ~FOV).
        """
        new = steps[n_before:]
        if any(x["src"] not in ("ok", "retry", "menu") for x in new):
            if gap is None:
                start = prev if prev[3] is not None else last_world
                gap = {"start": start, "first": n_before} if start is not None else None
            return gap
        if gap is None or not all(x["src"] in ("ok", "retry") for x in new):
            return gap                                   # (menus keep a gap open: the camera can't turn)
        a = gap["start"]
        n_cover = n_before - gap["first"]
        if prev[1] - a[1] <= config.FLOW_BRIDGE_MAX_S:
            stats["bridges"] = stats.get("bridges", 0) + 1
            p0, p1, n = tracker.match(a[3], a[4], prev[3], prev[4])
            src = "lowtex" if p0 is None else judge(fit_rotation(p0, p1, pitch_hint(a[1]), f0), len(p0), 0.0)
            if src == "ok":
                stats["bridges_ok"] = stats.get("bridges_ok", 0) + 1
                for x in steps[gap["first"]:n_before]:
                    x["covered"] = True
                steps.insert(n_before, {"t0": a[1], "t1": prev[1], "src": "bridge", "p0": p0, "p1": p1,
                                        "n_tracks": n, "diff": 0.0, "n_cover": n_cover})
        return None

    try:
        while True:
            if index % step == 0:
                ok, frame = cap.read()
                if not ok:
                    break
                t = index / fps
                if t > run_end:
                    break
                screen = screens.at(t)
                gray, mask = tracker.prepare(frame, screen) if screen in TRACK_SCREENS else (None, None)
                if gray is None:
                    tracker.last_shift = None
                cur = (index, t, screen, gray, mask)
                if prev is not None:
                    n_before = len(steps)
                    do_step(prev, cur)
                    gap = follow_gap(gap, prev, n_before)
                if gray is not None:
                    last_world = cur
                prev = cur
                if index % (step * fps_target * 120) == 0 and index:
                    print(f"  ... {int(t) // 60:02d}:{int(t) % 60:02d} / {int(run_end) // 60:02d}:"
                          f"{int(run_end) % 60:02d}", flush=True)
            elif not cap.grab():
                break
            index += 1
    finally:
        cap.release()
        if retry["cap"] is not None:
            retry["cap"].release()
    return steps, fps, stats


# --- geometry pass (FOV, per-step rotation) -----------------------------------------------------

def fit_steps(steps, facing, f):
    """Pass 2: fit every tracked step with focal length f -> fills dyaw/dpitch/zoom/inliers/confidence.

    The pitch the model needs comes from the nearest F3 read when there is one (< FLOW_PITCH_ANCHOR_S
    away), otherwise from the flow itself (integrated)."""
    pitch = 0.0
    for i, s in enumerate(steps):
        if s.get("n_cover"):                         # (re-fits: the bridge decides again below)
            for x in steps[i - s["n_cover"]:i]:
                x["covered"] = True
        s["src"] = s.setdefault("track_src", s["src"])     # (re-fits start from the tracking result)
        i = facing.near(s["t0"], config.FLOW_PITCH_ANCHOR_S)
        if i is not None:
            pitch = float(facing.pitch[i])
        s.update(dyaw=0.0 if s["src"] == "menu" else None, dpitch=0.0 if s["src"] == "menu" else None,
                 zoom=1.0, inliers=0, confidence=1.0 if s["src"] == "menu" else 0.0)
        if s["src"] not in ("ok", "retry") or s["p0"] is None:
            continue
        fit = fit_rotation(s["p0"], s["p1"], pitch, f)
        verdict = judge(fit, len(s["p0"]), s.get("diff", 0.0))
        if verdict != "ok":
            s["src"] = verdict
            if s.get("n_cover"):                     # a failed bridge leaves its gap uncovered
                for x in steps[i - s["n_cover"]:i]:
                    x["covered"] = False
            continue
        share = fit["inliers"] / len(s["p0"])
        # Confidence: enough inliers, most tracks agreeing, small leftover error.
        conf = min(1.0, fit["inliers"] / config.FLOW_FULL_CONF_INLIERS) * min(1.0, share / 0.7) * \
            min(1.0, config.FLOW_INLIER_PX / max(fit["rms_px"], 1e-3) * 0.5)
        s.update(dyaw=fit["dyaw"], dpitch=fit["dpitch"], zoom=math.exp(fit["log_zoom"]),
                 inliers=fit["inliers"], confidence=round(conf, 3))
        pitch = float(np.clip(pitch + fit["dpitch"], -90.0, 90.0))
    return steps


def integrate(steps):
    """Cumulative flow yaw / pitch at every step end (unknown steps add nothing) -> (t, yaw, pitch, known)."""
    t = np.array([s["t1"] for s in steps])
    dy = np.array([s["dyaw"] if s["dyaw"] is not None else 0.0 for s in steps])
    dp = np.array([s["dpitch"] if s["dpitch"] is not None else 0.0 for s in steps])
    known = np.array([s["dyaw"] is not None or bool(s.get("covered")) for s in steps])
    return t, np.cumsum(dy), np.cumsum(dp), known


def aligned_pairs(steps, facing, fps, max_pair_s):
    """Consecutive F3 reads that both sit exactly on a step boundary, with only known steps between them
    -> list of (step index a, step index b, F3 index a, F3 index b)."""
    t1_frames = {int(round(s["t1"] * fps)): i for i, s in enumerate(steps)}
    on_grid = [(t1_frames[int(fr)], k) for k, fr in enumerate(facing.frame) if int(fr) in t1_frames]
    known = np.array([s["dyaw"] is not None or bool(s.get("covered")) for s in steps])
    bad = np.concatenate([[0], np.cumsum(~known)])
    out = []
    for (ia, ka), (ib, kb) in zip(on_grid, on_grid[1:]):
        if 0 < facing.t[kb] - facing.t[ka] <= max_pair_s and bad[ib + 1] - bad[ia + 1] == 0:
            out.append((ia, ib, ka, kb))
    return out


def fit_fov(steps, facing, fps, height, speed_band=None):
    """Focal length (px) from flow vs F3 yaw on F3-visible stretches -> (f, n_pairs) or (None, n).

    The yaw a pixel shift means scales ~ 1/f, so with a first guess f0: f = f0 / slope, slope = F3 yaw
    change / flow yaw change (robust: median of per-pair ratios, then least squares on the pairs that
    agree). Repeated twice because the model is only ~linear in 1/f.
    speed_band=(lo, hi): only pairs where the player moves lo..hi blocks/s (sprint FOV check).
    """
    f = focal_from_vfov(config.FLOW_DEFAULT_VFOV, height)
    n = 0
    for _ in range(3):
        fit_steps(steps, facing, f)
        _, Y, _, _ = integrate(steps)
        xs, ys = [], []
        for ia, ib, ka, kb in aligned_pairs(steps, facing, fps, config.FLOW_FOV_PAIR_S):
            flow = Y[ib] - Y[ia]
            truth = float(wrap180(facing.yaw[kb] - facing.yaw[ka]))
            if not config.FLOW_FOV_MIN_DEG <= abs(truth) <= config.FLOW_FOV_MAX_DEG or abs(flow) < 0.5:
                continue
            if speed_band is not None:
                lo_i, hi_i = facing.near(facing.t[ka] - 0.5, 0.3), facing.near(facing.t[kb] + 0.5, 0.3)
                if lo_i is None or hi_i is None:
                    continue
                v = np.linalg.norm(facing.pos[hi_i] - facing.pos[lo_i]) / max(1e-3, facing.t[hi_i] - facing.t[lo_i])
                if not speed_band[0] <= v < speed_band[1]:
                    continue
            xs.append(flow)
            ys.append(truth)
        n = len(xs)
        if n < config.FLOW_FOV_MIN_PAIRS:
            return None, n
        xs, ys = np.array(xs), np.array(ys)
        ratio = ys / xs
        med = np.median(ratio)
        keep = np.abs(ratio - med) < 0.15 * abs(med)
        slope = float((xs[keep] @ ys[keep]) / (xs[keep] @ xs[keep]))
        f = f / slope
    return f, n


def fuse(steps, facing):
    """Integrated flow + F3 anchors -> absolute (yaw, pitch) per step end, and distance to nearest anchor.

    Between two anchors A, B (<= FLOW_FUSE_MAX_GAP_S apart) the flow's change is trusted and the
    mismatch at B (drift) is spread over the interval in proportion to how much the camera turned
    (scale errors grow with rotation) plus a little per second (slow drift). Before the first / after
    the last anchor the flow just continues from the nearest one.
    """
    t, Y, P, _ = integrate(steps)
    n = len(t)
    yaw, pitch, dist = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    if not len(facing) or not n:
        return yaw, pitch, dist
    # Flow's cumulative rotation at the anchor times (linear between step ends).
    Ya, Pa = np.interp(facing.t, t, Y), np.interp(facing.t, t, P)
    dy = np.abs(np.diff(np.concatenate([[0.0], Y])))
    effort = np.cumsum(dy) + config.FLOW_FUSE_DEG_PER_S * t
    Ea = np.interp(facing.t, t, effort)
    k = np.searchsorted(facing.t, t, side="right") - 1        # anchor at or before each step end
    for i in range(n):
        a = k[i]
        b = a + 1
        if a < 0:                                             # before the first anchor
            yaw[i] = facing.yaw[0] + Y[i] - Ya[0]
            pitch[i] = facing.pitch[0] + P[i] - Pa[0]
            dist[i] = facing.t[0] - t[i]
            continue
        base_y = facing.yaw[a] + Y[i] - Ya[a]
        base_p = facing.pitch[a] + P[i] - Pa[a]
        dist[i] = t[i] - facing.t[a]
        if b < len(facing) and facing.t[b] - facing.t[a] <= config.FLOW_FUSE_MAX_GAP_S:
            span = max(Ea[b] - Ea[a], 1e-6)
            w = (effort[i] - Ea[a]) / span
            drift_y = float(wrap180(facing.yaw[b] - facing.yaw[a] - (Ya[b] - Ya[a])))
            drift_p = (facing.pitch[b] - facing.pitch[a]) - (Pa[b] - Pa[a])
            base_y += w * drift_y
            base_p += w * drift_p
            dist[i] = min(dist[i], facing.t[b] - t[i])
        yaw[i] = float(wrap180(base_y))
        pitch[i] = float(np.clip(base_p, -90, 90))
    return yaw, pitch, dist


# --- evaluation against F3 -----------------------------------------------------------------------

def evaluate_flow(steps, facing, fps):
    """Flow vs F3 (pretending F3 is absent): per-pair error, 10 s drift, usable share -> dict."""
    out = {}
    tracked = [s for s in steps if s["src"] not in ("menu", "screen")]
    out["steps_world"] = len(tracked)
    out["usable_pct"] = round(100 * sum(s["dyaw"] is not None for s in tracked) / max(1, len(tracked)), 1)
    out["lowtex_pct"] = round(100 * sum(s["src"] == "lowtex" for s in tracked) / max(1, len(tracked)), 1)
    out["retry_steps"] = sum(s["src"] == "retry" for s in steps)
    _, Y, P, known = integrate(steps)
    pairs = aligned_pairs(steps, facing, fps, 0.25)
    if pairs:
        ey = np.array([Y[ib] - Y[ia] - wrap180(facing.yaw[kb] - facing.yaw[ka]) for ia, ib, ka, kb in pairs])
        ep = np.array([P[ib] - P[ia] - (facing.pitch[kb] - facing.pitch[ka]) for ia, ib, ka, kb in pairs])
        ey = np.abs(wrap180(ey))
        ep = np.abs(ep)
        dt = np.median([facing.t[kb] - facing.t[ka] for *_, ka, kb in pairs])
        out["pair_dt_s"] = round(float(dt), 3)
        out["pairs"] = len(pairs)
        out["yaw_err_med"], out["yaw_err_p90"] = round(float(np.median(ey)), 3), round(float(np.percentile(ey, 90)), 3)
        out["pitch_err_med"], out["pitch_err_p90"] = (round(float(np.median(ep)), 3),
                                                      round(float(np.percentile(ep, 90)), 3))
        steps_per_pair = dt / np.median([s["t1"] - s["t0"] for s in steps])
        out["steps_per_pair"] = round(float(steps_per_pair), 2)
    # Drift: start at an F3 read, integrate flow only, compare with the F3 read ~10 s later.
    t1_frames = {int(round(s["t1"] * fps)): i for i, s in enumerate(steps)}
    grid = [(t1_frames[int(fr)], k) for k, fr in enumerate(facing.frame) if int(fr) in t1_frames]
    bad = np.concatenate([[0], np.cumsum(~known & np.array([s["src"] != "menu" for s in steps]))])
    gt = np.array([facing.t[k] for _, k in grid])
    clean, gappy = [], []
    last = -1e9
    for ia, ka in grid:
        if facing.t[ka] - last < config.FLOW_EVAL_WINDOW_STRIDE_S:
            continue
        j = np.searchsorted(gt, facing.t[ka] + config.FLOW_EVAL_WINDOW_S)
        if j >= len(grid) or abs(gt[j] - facing.t[ka] - config.FLOW_EVAL_WINDOW_S) > 0.3:
            continue
        last = facing.t[ka]
        ib, kb = grid[j]
        err = abs(float(wrap180(Y[ib] - Y[ia] - (facing.yaw[kb] - facing.yaw[ka]))))
        (clean if bad[ib + 1] - bad[ia + 1] == 0 else gappy).append(err)
    for name, errs in (("drift10", clean), ("drift10_gaps", gappy)):
        if errs:
            out[name] = {"windows": len(errs), "med": round(float(np.median(errs)), 2),
                         "p90": round(float(np.percentile(errs, 90)), 2),
                         "le5_pct": round(100 * float(np.mean(np.array(errs) <= 5)), 1)}
    return out


# --- command -------------------------------------------------------------------------------------

def write_flow_csv(path, steps, yaw, pitch, dist):
    _, Y, P, _ = integrate(steps)

    def fmt(v, nd):
        return "" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{nd}f}"

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FLOW_FIELDS)
        for i, s in enumerate(steps):
            w.writerow([f"{s['t1']:.3f}", f"{s['t1'] - s['t0']:.3f}", fmt(s["dyaw"], 3), fmt(s["dpitch"], 3),
                        f"{s['zoom']:.4f}", s["n_tracks"], s["inliers"], f"{s['confidence']:.3f}", s["src"],
                        f"{Y[i]:.2f}", f"{P[i]:.2f}", fmt(float(yaw[i]), 2), fmt(float(pitch[i]), 2),
                        fmt(float(dist[i]), 2)])


def flow_command(out_dir, video_path=None, fps_target=None, reuse=False, evaluate=True):
    """`python -m vodreview flow runs/<id>`: camera rotation from optical flow -> flow.csv (+ fov in layout.json)."""
    started, cpu0 = time.time(), time.process_time()
    out_dir = Path(out_dir)
    run = json.loads((out_dir / "run.json").read_text())
    video_path = video_path or run["video"]
    if not Path(video_path).is_file():
        local = out_dir / "video.mp4"
        if not local.is_file():
            raise SystemExit(f"Source video not found: {video_path} (pass --video)")
        video_path = str(local)
    lay = load_layout(out_dir)
    height = lay.game[3] - lay.game[1]
    screens = ScreenLookup(read_samples_csv(out_dir / "samples.csv"))
    fps_v = cv2.VideoCapture(str(video_path)).get(cv2.CAP_PROP_FPS) or 30.0
    facing = F3Facing(read_f3_csv(out_dir / "f3.csv"), fps_v)
    cache = out_dir / "flow_tracks.npz"
    if reuse and cache.is_file():
        steps, fps, stats = load_tracks(cache)
        print(f"Reusing {len(steps)} tracked steps from {cache.name}")
    else:
        print(f"Tracking at {fps_target or config.FLOW_FPS} fps ...", flush=True)
        steps, fps, stats = track_video(video_path, lay, screens, run["run_end_s"], facing, fps_target)
        save_tracks(cache, steps, fps, stats)
    track_cpu = time.process_time() - cpu0

    f, n_pairs = fit_fov(steps, facing, fps, height)
    fov = {"source": "flow vs F3 yaw", "pairs": n_pairs}
    if f is None:
        f = focal_from_vfov(config.FLOW_DEFAULT_VFOV, height)
        fov = {"source": f"default ({n_pairs} F3 pairs < {config.FLOW_FOV_MIN_PAIRS})", "pairs": n_pairs}
    else:
        # Sprint check: the same fit on pairs where the player stands/walks vs sprints (F3 positions).
        bands = {"still_walk": (0.0, 4.6), "sprint": (5.0, 9.0)}
        for name, band in bands.items():
            fb, nb = fit_fov(steps, facing, fps, height, band)
            fov[name] = {"vfov_deg": round(vfov_from_focal(fb, height), 2) if fb else None, "pairs": nb}
    fit_steps(steps, facing, f)
    fov.update(vfov_deg=round(vfov_from_focal(f, height), 2),
               hfov_deg=round(math.degrees(2 * math.atan((lay.game[2] - lay.game[0]) / 2 / f)), 2),
               focal_px=round(f, 1))
    yaw, pitch, dist = fuse(steps, facing)
    write_flow_csv(out_dir / "flow.csv", steps, yaw, pitch, dist)
    data = json.loads((out_dir / "layout.json").read_text())   # re-read: only the "fov" key is ours
    data["fov"] = fov
    save_layout(out_dir, data)
    print(f"FOV: vertical {fov['vfov_deg']} deg (horizontal {fov['hfov_deg']}), {fov['source']}, "
          f"{n_pairs} pairs" + "".join(f"; {k} {v['vfov_deg']} ({v['pairs']})" for k, v in fov.items()
                                       if isinstance(v, dict)))
    report = {"fov": fov, "track_stats": stats, "steps": len(steps)}
    if evaluate and len(facing):
        report["eval"] = evaluate_flow(steps, facing, fps)
        print("Flow vs F3: " + json.dumps(report["eval"]))
    minutes = run["run_end_s"] / 60
    report["cpu_s"] = round(time.process_time() - cpu0, 1)
    report["track_cpu_s"] = round(track_cpu, 1)
    report["wall_s"] = round(time.time() - started, 1)
    report["cpu_s_per_min"] = round(track_cpu / minutes, 2)
    print(f"Wrote {out_dir / 'flow.csv'}; {report['wall_s']}s wall, tracking CPU {report['track_cpu_s']}s "
          f"({report['cpu_s_per_min']} s per minute of video), total CPU {report['cpu_s']}s")
    return report


def save_tracks(path, steps, fps, stats):
    """Cache pass 1 (tracked point pairs) so the geometry can be re-fitted without decoding the video."""
    keys = ("t0", "t1", "n_tracks", "diff", "n_cover")
    meta = np.array([[s.get(k, 0) for k in keys] for s in steps], dtype=np.float64)
    src = np.array([s["src"] for s in steps])
    counts = np.array([0 if s["p0"] is None else len(s["p0"]) for s in steps])
    p0 = np.concatenate([s["p0"] for s in steps if s["p0"] is not None] or [np.zeros((0, 2), np.float32)])
    p1 = np.concatenate([s["p1"] for s in steps if s["p1"] is not None] or [np.zeros((0, 2), np.float32)])
    np.savez(path, meta=meta, src=src, counts=counts, p0=p0, p1=p1, fps=fps, stats=json.dumps(stats))


def load_tracks(path):
    z = np.load(path)
    steps, at = [], 0
    for (t0, t1, n, diff, n_cover), src, c in zip(z["meta"], z["src"], z["counts"]):
        s = {"t0": float(t0), "t1": float(t1), "n_tracks": int(n), "diff": float(diff), "src": str(src),
             "p0": None, "p1": None, "n_cover": int(n_cover)}
        if c:
            s["p0"], s["p1"] = z["p0"][at:at + c], z["p1"][at:at + c]
            at += c
        steps.append(s)
    return steps, float(z["fps"]), json.loads(str(z["stats"]))
