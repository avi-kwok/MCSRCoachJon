"""Player movement between F3 anchors (visual odometry): runs/<id>/odometry.csv + odometry_track.csv.

F3 tells us the exact position ~10 times a second, but only while the runner has it open.
Between reads we estimate how the *camera* moved from how the picture moved.

CV ideas, in order:

1. **Tracking (Lucas-Kanade optical flow).** Pick ~400 corners (spots with texture in two
   directions, `cv2.goodFeaturesToTrack`) in frame A and find where each went in frame B
   (`cv2.calcOpticalFlowPyrLK`). Points are tracked back B -> A too; a point that does not
   come home (forward-backward check) was lost and is dropped. Overlays, the HUD, the held
   item and the F3 text are masked out first - they don't move with the world.

2. **Pixels -> rays (pinhole camera).** A pixel (u, v) is the direction
   ray = ((u - cx) / f, (v - cy) / f, 1) in the camera's own frame (x right, y down,
   z forward). f, the focal length in px, follows from the vertical FOV:
   f = (H / 2) / tan(FOV / 2). We don't know the runner's FOV setting, so `fit_fov` tries
   50..120 deg and keeps the one that makes still frames line up best (below).

3. **Derotation.** Turning the camera moves every pixel, walking moves near pixels more than
   far ones. Minecraft has no camera roll, so the camera orientation is just yaw + pitch.
   `camera_rotation(yaw, pitch)` gives the 3x3 matrix whose columns are the camera's
   right / down / forward axes in *world* coordinates; multiplying a camera ray by it gives
   the ray's world direction. Do that with each frame's own facing and the turning is gone
   (this is K R K^-1 of the textbook: K^-1 = pixel -> ray, R = rotate, K = ray -> pixel):
   a point that is far away now has the same world direction in both frames, and what is
   left over is caused only by moving.
   Facing comes from F3 (interpolated between reads) or, without F3, from the flow itself
   (`flow_facing`: 1-point RANSAC on yaw + pitch) - a stand-in for the rotation module.

4. **Direction of travel.** Once the turn is removed, every point slides straight away from
   the direction we move in, so its two rays and the travel direction T lie in one plane:
   (w0 x w1) . T = 0 (the epipolar constraint). RANSAC over pairs of points (T = a1 x a2)
   finds the T most points agree with. Minecraft movement keys are digital, so T is flattened
   onto the ground and snapped to the 8 WASD directions relative to the facing.
   Moving or not: how far the points still move after derotation (median, in px).

5. **Speed (scale).** Flow alone can't tell a big step past a far wall from a small step past
   a near one. A floor-plane ruler (eyes 1.62 blocks up) was tried and dropped: on real
   terrain most tracked points are on far hills / trees / the held item, not the flat floor,
   and it under-read speed ~2.5x. Instead the speed is a Minecraft prior (sprint 5.612 m/s)
   *fitted on the run's F3 anchors*: true distance / time we called "moving" (fit_move_speed).
   Sideways / backwards travel can't be sprinted, so it gets walking speed (4.317 m/s).

6. **Dead reckoning.** Add the steps up. Between two F3 anchors the accumulated error is
   spread over the steps in proportion to the distance each step moved, so the track
   meets both anchors exactly.
"""

import csv
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from . import config
from .f3 import is_valid, read_f3_csv
from .layout import load_layout
from .motion import build_mask
from .report import read_samples_csv
from .video import open_video

TRACK_SCREENS = ("world", "f3")      # screens that show the world (inventories etc. break tracking)


# ---------------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------------

def camera_rotation(yaw, pitch):
    """World-from-camera rotation for a Minecraft yaw / pitch (degrees, arrays ok) -> (..., 3, 3).

    Minecraft: world y is up; yaw 0 faces +Z (south), yaw 90 faces -X (west); pitch > 0 looks down.
    Columns are the camera's right, down and forward axes in world coordinates (OpenCV camera
    convention x right, y down, z forward), so  world_dir = R @ camera_ray.
    """
    y, p = np.radians(yaw), np.radians(pitch)
    sy, cy, sp, cp = np.sin(y), np.cos(y), np.sin(p), np.cos(p)
    forward = np.stack([-sy * cp, -sp, cy * cp], -1)
    right = np.stack([-cy, np.zeros_like(cy), -sy], -1)       # facing south, east (+X) is on your left
    down = np.cross(forward, right)                          # right x down = forward  =>  down = forward x right
    return np.stack([right, down, forward], -1)


def pixels_to_rays(pts, K):
    """(N, 2) pixels -> (N, 3) unit rays in camera coordinates."""
    rays = np.column_stack([(pts[:, 0] - K[0, 2]) / K[0, 0], (pts[:, 1] - K[1, 2]) / K[1, 1], np.ones(len(pts))])
    return rays / np.linalg.norm(rays, axis=1, keepdims=True)


def intrinsics(fov_deg, w, h):
    """Pinhole matrix K for a vertical FOV (Minecraft's FOV slider is vertical) on a w x h image."""
    f = (h / 2) / math.tan(math.radians(fov_deg) / 2)
    return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])


def angle_between(a, b):
    """Row-wise angle (rad) between unit vectors; small-angle safe (uses the chord length)."""
    return 2 * np.arcsin(np.clip(np.linalg.norm(a - b, axis=-1) / 2, 0, 1))


# ---------------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------------

class Tracker:
    """Small Lucas-Kanade tracker: corners in frame A -> positions in frame B, with masks."""

    def __init__(self, lay):
        gx0, gy0, gx1, gy1 = lay.game
        self.crop = (gx0, gy0, gx1, gy1)
        w = config.ODO_SIZE[0]
        h = int(round(w * (gy1 - gy0) / (gx1 - gx0)))
        self.size = (w, h)
        # Rectangles are normalized to the full frame; convert them to the game rect.
        fw, fh = lay.w, lay.h

        def to_game(r):
            x0, y0, x1, y1 = r
            return ((x0 * fw - gx0) / (gx1 - gx0), (y0 * fh - gy0) / (gy1 - gy0),
                    (x1 * fw - gx0) / (gx1 - gx0), (y1 * fh - gy0) / (gy1 - gy0))

        static = [to_game(r) for r in lay.overlay_rects() + lay.hud_rects()] + [config.ODO_HAND_RECT]
        self.mask = build_mask(w, h, static).astype(np.uint8)
        self.f3_area = ~build_mask(w, h, [to_game(r) for r in lay.f3_rects()])
        self.lk = dict(winSize=(config.ODO_LK_WIN, config.ODO_LK_WIN), maxLevel=config.ODO_LK_LEVELS,
                       criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.03))
        self.kernel = np.ones((config.ODO_TEXT_DILATE, config.ODO_TEXT_DILATE), np.uint8)
        self.k = lay.k                     # GUI scale: screen px per GUI px
        self.edge_kernel = np.ones((2 * config.ODO_EDGE_MARGIN + 1,) * 2, np.uint8)

    def undarken_f3_boxes(self, gray, text):
        """Undo the F3 line backgrounds so the world under them joins up with the world around.

        1.16 draws each non-empty F3 line on a translucent grey box (#505050):
            shown = (1 - a) * world + a * 80     ->     world = (shown - a * 80) / (1 - a)
        (a measured on the test VODs, see config.ODO_F3_BOX_ALPHA). Boxes are 9 GUI px tall
        rows (line i at GUI y 1 + 9 i); a left-column box runs from the left edge to ~2 GUI px
        past the line's last glyph, a right-column box mirrored. The correction is never
        perfect, so the box *outline* (where box meets open world) is returned as a mask too -
        those static edges would otherwise drag LK windows.
        gray / text: full-resolution game-rect images; gray (float32) is changed in place.
        """
        k = self.k
        h, w = gray.shape
        a = config.ODO_F3_BOX_ALPHA
        boxes = np.zeros((h, w), np.uint8)
        gap = int(8 * k)                    # wider than a word space: a gap between the two columns
        for i in range(int((h / k - 1) // 9)):
            ya, yb = int(round(k * (1 + 9 * i))), int(round(k * (10 + 9 * i)))
            cols = np.flatnonzero(text[ya:yb].any(axis=0))
            if not len(cols):
                continue
            # split the occupied columns into groups at wide gaps
            breaks = np.flatnonzero(np.diff(cols) > gap)
            starts = np.concatenate([[cols[0]], cols[breaks + 1]])
            ends = np.concatenate([cols[breaks], [cols[-1]]])
            if starts[0] < 4 * k:                                       # left column line
                boxes[ya:yb, :min(w, int(ends[0] + 2 * k))] = 1
            if ends[-1] > w - 4 * k and (len(starts) > 1 or starts[0] >= 4 * k):   # right column line
                boxes[ya:yb, max(0, int(starts[-1] - 2 * k)):] = 1
        inside = boxes > 0
        gray[inside] = (gray[inside] - a * 80) / (1 - a)
        ring = np.ones((int(2 * k) | 1,) * 2, np.uint8)
        return cv2.dilate(boxes, ring) - cv2.erode(boxes, ring)     # the outline, ~2 GUI px wide

    def prepare(self, frame, f3_visible):
        """BGR frame -> (small gray image, usable-pixel mask)."""
        x0, y0, x1, y1 = self.crop
        game = frame[y0:y1, x0:x1]
        mask = self.mask
        if f3_visible:
            # F3 text (and sound subtitles): light and neutral grey, found at full resolution
            # (shrinking blurs the 1-font-px strokes into the background). The text pixels are
            # masked (dilated a little for the blur halo) and painted over below; the line
            # boxes behind them are undone first. A few white world pixels (snow, quartz,
            # bone blocks) are lost too; that's fine.
            lo, hi = game.min(axis=2), game.max(axis=2)
            text = (lo > config.ODO_TEXT_MIN) & ((hi - lo) < config.ODO_TEXT_MAX_CHROMA)
            full = cv2.cvtColor(game, cv2.COLOR_BGR2GRAY).astype(np.float32)
            seams = self.undarken_f3_boxes(full, text)
            gray = cv2.resize(np.clip(full, 0, 255), self.size, interpolation=cv2.INTER_AREA).astype(np.uint8)
            text = cv2.resize((text | (seams > 0)).astype(np.uint8) * 255, self.size, interpolation=cv2.INTER_AREA) > 0
            text = cv2.dilate(text.astype(np.uint8), self.kernel)
            mask = mask & (1 - text)
        else:
            gray = cv2.cvtColor(cv2.resize(game, self.size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        # Paint over everything we can't use with a blur of the usable pixels around it
        # ("normalized convolution": blur(image * mask) / blur(mask)). LK solves for the shift
        # that best explains the *gradients* in its window; the painted areas are smooth and
        # follow the world, so a window (or a coarse pyramid level) that overlaps masked text
        # is no longer dragged towards "didn't move", and the mask border makes no hard edge.
        m = mask.astype(np.float32)
        k = (config.ODO_FILL_BLUR, config.ODO_FILL_BLUR)
        mean = float(gray[mask > 0].mean()) if mask.any() else 0.0
        eps = 0.05                      # far from any usable pixel this fades to the mean grey
        fill = (cv2.blur(gray.astype(np.float32) * m, k) + eps * mean) / (cv2.blur(m, k) + eps)
        gray = np.where(mask > 0, gray, np.clip(fill, 0, 255)).astype(np.uint8)
        # Corners are only picked well inside the usable area.
        return gray, cv2.erode(mask, self.edge_kernel)

    def track(self, a, b):
        """(gray, mask) of frames A and B -> (p0, p1) float32 (N, 2) point pairs."""
        g0, m0 = a
        g1, m1 = b
        p0 = cv2.goodFeaturesToTrack(g0, config.ODO_MAX_POINTS, 0.005, config.ODO_MIN_DISTANCE,
                                     mask=m0, blockSize=5)
        if p0 is None or len(p0) < 8:
            return np.zeros((0, 2), np.float32), np.zeros((0, 2), np.float32)
        p1, st, _ = cv2.calcOpticalFlowPyrLK(g0, g1, p0, None, **self.lk)
        back, st2, _ = cv2.calcOpticalFlowPyrLK(g1, g0, p1, None, **self.lk)
        p0, p1, back = p0.reshape(-1, 2), p1.reshape(-1, 2), back.reshape(-1, 2)
        ok = (st.ravel() == 1) & (st2.ravel() == 1) & (np.linalg.norm(back - p0, axis=1) < config.ODO_FB_MAX_ERR)
        h, w = g1.shape
        xi, yi = np.clip(p1[:, 0], 0, w - 1).astype(int), np.clip(p1[:, 1], 0, h - 1).astype(int)
        ok &= (p1[:, 0] >= 0) & (p1[:, 0] < w) & (p1[:, 1] >= 0) & (p1[:, 1] < h) & (m1[yi, xi] > 0)
        # Leftover overlay: when most of the picture moves, a point that stays put to a fraction
        # of a pixel is almost surely stuck to something drawn on top (text edges, HUD), not world.
        moved = np.linalg.norm(p1 - p0, axis=1)
        if ok.sum() and np.median(moved[ok]) > config.ODO_STATIC_SCENE_PX:
            ok &= moved > config.ODO_STATIC_PT_PX
        return p0[ok], p1[ok]


def screen_lookup(samples):
    """samples.csv -> function t -> screen name of the nearest sample."""
    times = np.array([s.time for s in samples])
    screens = [s.screen for s in samples]

    def at(t):
        i = int(np.clip(np.searchsorted(times, t), 1, len(times) - 1))
        return screens[i if abs(times[i] - t) < abs(times[i - 1] - t) else i - 1]
    return at


def track_run(run_dir, video_path, fps_out=None, verbose=True, t_range=None):
    """Track point pairs through the whole video -> dict of arrays (cached as an .npz by the caller).

    steps: t0, t1, f3 (was F3 on screen), n (points); points: p0, p1 concatenated, offsets.
    """
    run_dir = Path(run_dir)
    lay = load_layout(run_dir)
    tracker = Tracker(lay)
    screen_at = screen_lookup(read_samples_csv(run_dir / "samples.csv"))
    fps_out = fps_out or config.ODO_SAMPLES_PER_SECOND
    cap = open_video(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps / fps_out))
    t0s, t1s, f3s, counts, P0, P1 = [], [], [], [], [], []
    prev = None
    index = 0
    start = time.process_time()
    end_index = None
    if t_range:                      # (start_s, end_s): only part of the video (experiments)
        index = int(t_range[0] * fps) // step * step
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        end_index = int(t_range[1] * fps)
    while end_index is None or index < end_index:
        if index % step:
            if not cap.grab():
                break
            index += 1
            continue
        t = index / fps
        screen = screen_at(t)
        if screen not in TRACK_SCREENS:
            prev = None
            if not cap.grab():
                break
            index += 1
            continue
        ok, frame = cap.read()
        if not ok:
            break
        cur = tracker.prepare(frame, screen == "f3")
        if prev is not None:
            p0, p1 = tracker.track(prev[1], cur)
            t0s.append(prev[0]), t1s.append(t), f3s.append(screen == "f3" and prev[2]), counts.append(len(p0))
            P0.append(p0), P1.append(p1)
        prev = (t, cur, screen == "f3")
        index += 1
        if verbose and index % (step * fps_out * 60) == 0:
            print(f"  tracked {t / 60:.0f} min ({time.process_time() - start:.0f} s CPU)", flush=True)
    cap.release()
    w, h = tracker.size
    return {"t0": np.array(t0s), "t1": np.array(t1s), "f3": np.array(f3s), "n": np.array(counts, int),
            "p0": np.concatenate(P0) if P0 else np.zeros((0, 2)), "p1": np.concatenate(P1) if P1 else np.zeros((0, 2)),
            "size": np.array([w, h]), "cpu_s": np.array(time.process_time() - start),
            "video_s": np.array(index / fps)}


def step_points(tracks, i):
    a = int(tracks["offsets"][i])
    b = a + int(tracks["n"][i])
    return tracks["p0"][a:b], tracks["p1"][a:b]


# ---------------------------------------------------------------------------------
# Facing: F3 (interpolated) or from the flow
# ---------------------------------------------------------------------------------

class F3Facing:
    """Exact yaw / pitch at the F3 read times (no interpolation - see facing_chain for why).

    The pitch number is often unreadable (the right column's text runs into it), so a read
    may have a yaw but pitch = nan; the chain then keeps its own pitch.
    Facing misreads (one read far off while its neighbours agree) are dropped: a read must
    agree with at least one neighbour within 0.2 s, allowing for real turning.
    """

    def __init__(self, rows):
        rows = [r for r in rows if r["yaw"] is not None]
        t = np.array([r["time_s"] for r in rows])
        yaw = np.array([r["yaw"] for r in rows])
        pitch = np.array([np.nan if r["pitch"] is None else r["pitch"] for r in rows])
        keep = np.zeros(len(rows), bool)
        for k in range(len(rows)):
            for j in (k - 1, k + 1):
                if 0 <= j < len(rows) and abs(t[j] - t[k]) <= 0.21:
                    if abs((yaw[j] - yaw[k] + 180) % 360 - 180) + np.nan_to_num(abs(pitch[j] - pitch[k])) < 25:
                        keep[k] = True
        self.t, self.yaw, self.pitch = t[keep], yaw[keep], pitch[keep]
        self.pt = self.t[~np.isnan(self.pitch)]              # reads that have a pitch
        self.pv = self.pitch[~np.isnan(self.pitch)]

    def pitch_near(self, t, max_dt=0.5):
        i = int(np.searchsorted(self.pt, t))
        c = [j for j in (i - 1, i) if 0 <= j < len(self.pt) and abs(self.pt[j] - t) <= max_dt]
        return float(self.pv[min(c, key=lambda j: abs(self.pt[j] - t))]) if c else None

    def read_at(self, t, tol=0.02):
        """(yaw, pitch) of an F3 read taken at time t (same video frame), else None."""
        i = int(np.searchsorted(self.t, t))
        for j in (i - 1, i):
            if 0 <= j < len(self.t) and abs(self.t[j] - t) < tol:
                return float(self.yaw[j]), (None if np.isnan(self.pitch[j]) else float(self.pitch[j]))
        return None

    def near(self, t, max_dt):
        """The read closest to t, if within max_dt: (t_read, yaw, pitch)."""
        i = int(np.searchsorted(self.t, t))
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(self.t) and abs(self.t[j] - t) <= max_dt:
                if best is None or abs(self.t[j] - t) < abs(self.t[best] - t):
                    best = j
        if best is None:
            return None
        pitch = self.pitch_near(self.t[best])
        return None if pitch is None else (float(self.t[best]), float(self.yaw[best]), pitch)


def facing_chain(tracks, K, idx, f3facing=None, start=None, seed=1):
    """Facing (yaw, pitch) at both ends of each step -> {i: ((y0, p0), (y1, p1)) or None}.

    F3 is read only ~10x a second, and the mouse moves in jerks between reads (and the
    recording repeats frames now and then), so *interpolating* F3 facing between reads is
    off by many pixels on fast turns. Instead the rotation between frames comes from the flow
    (flow_facing) and F3 only *re-anchors* it: whenever a step starts on a frame with an F3
    read, the chain restarts from that exact facing. With f3facing=None (no F3) the chain
    starts from `start` and is never corrected - what the rotation module would have to do.
    """
    rng = np.random.default_rng(seed)
    out = {}
    cur = start
    prev_t1 = None
    for i in idx:
        t0, t1 = tracks["t0"][i], tracks["t1"][i]
        if prev_t1 is not None and t0 - prev_t1 > 0.01 and f3facing is not None:
            cur = None                      # tracking broke (inventory etc.): wait for the next read
        prev_t1 = t1
        if f3facing is not None:
            r = f3facing.read_at(t0)
            if r is not None:
                pitch = r[1] if r[1] is not None else (cur[1] if cur is not None else f3facing.pitch_near(t0))
                cur = (r[0], pitch) if pitch is not None else cur
        if cur is None:
            out[i] = None
            continue
        p0, p1 = step_points(tracks, i)
        res = flow_facing(pixels_to_rays(p0, K), pixels_to_rays(p1, K), cur[0], cur[1], rng, 1 / K[0, 0]) if len(p0) >= 6 else None
        if res is None:
            nxt = f3facing.read_at(t1) if f3facing is not None else None
            if nxt is not None:
                nxt = (nxt[0], cur[1] if nxt[1] is None else nxt[1])
            if nxt is None:
                out[i] = (cur, cur)          # lost: assume no turn (a rotation module would bridge this)
                continue
            res = nxt
        out[i] = (cur, (res[0], res[1]))
        cur = (res[0], res[1])
    return out


def flow_facing(c0, c1, yaw0, pitch0, rng, px):
    """Facing in frame B from the flow alone, given the facing in frame A (stand-in for the rotation module).

    A *far* point keeps its world direction d = R(yaw0, pitch0) c0. With no roll, one point is
    enough to solve frame B's pitch and yaw:
      * pitch: a camera ray's world height (y) depends only on pitch:  y = -c_y cos(p) - c_z sin(p),
        so p = phi +- acos(-d_y / rho) with rho, phi the polar form of (c_y, c_z);
      * yaw: turning by yaw only spins the ray's horizontal direction, so
        yaw1 = azimuth(ray at yaw 0) - azimuth(d).
    1-point RANSAC: try some points' solutions, keep the one most other points agree with
    (near points that moved because *we* moved disagree and are ignored), then take the median
    solution of the agreeing points.
    """
    if len(c0) < 6:
        return None
    d = c0 @ camera_rotation(yaw0, pitch0).T                      # world directions in frame A
    rho = np.hypot(c1[:, 1], c1[:, 2])
    phi = np.arctan2(c1[:, 2], c1[:, 1])
    ac = np.arccos(np.clip(-d[:, 1] / rho, -1, 1))
    p0 = math.radians(pitch0)
    cand = np.stack([phi + ac, phi - ac], 1)
    cand = (cand - p0 + np.pi) % (2 * np.pi) - np.pi + p0              # wrap near pitch0
    pitch = np.where(np.abs(cand[:, 0] - p0) < np.abs(cand[:, 1] - p0), cand[:, 0], cand[:, 1])
    a = c1[:, 2] * np.cos(pitch) - c1[:, 1] * np.sin(pitch)            # forward component at yaw 0
    yaw = np.arctan2(-c1[:, 0], a) - np.arctan2(d[:, 0], d[:, 2])
    y0 = math.radians(yaw0)
    yaw = (yaw - y0 + np.pi) % (2 * np.pi) - np.pi + y0
    ok = np.abs(pitch) <= np.pi / 2 + 1e-6
    idx = np.flatnonzero(ok)
    if len(idx) < 6:
        return None
    best = None
    for k in rng.choice(idx, min(30, len(idx)), replace=False):
        R1 = camera_rotation(math.degrees(yaw[k]), math.degrees(pitch[k]))
        inl = angle_between(c1 @ R1.T, d) < config.ODO_ROT_THR_PX * px
        if best is None or inl.sum() > best.sum():
            best = inl
    sel = best & ok
    if sel.sum() < 4:
        return None
    return math.degrees(np.median(yaw[sel])), math.degrees(np.median(pitch[sel])), int(sel.sum())


# ---------------------------------------------------------------------------------
# One step: derotated rays -> direction of travel
# ---------------------------------------------------------------------------------

def epipolar_direction(w0, w1, rng, px):
    """Unit direction of travel from derotated rays (no scale), or None.

    Moving by T, every point's two rays and T lie in one plane: (w0 x w1) . T = 0.
    Two points give T = a1 x a2; RANSAC keeps the direction most points agree with.
    Sign: points slide *away* from where we're heading, so their flow points against T.
    """
    a = np.cross(w0, w1)
    big = np.linalg.norm(a, axis=1) > 2 * px    # points that hardly moved say nothing about direction
    if big.sum() < 8:
        return None
    a = a[big]
    best, bestT = None, None
    for _ in range(40):
        i, j = rng.choice(len(a), 2, replace=False)
        T = np.cross(a[i], a[j])
        nt = np.linalg.norm(T)
        if nt < 1e-9:
            continue
        T /= nt
        inl = np.abs(a @ T) < 0.5 * px
        if best is None or inl.sum() > best.sum():
            best, bestT = inl, T
    if best is None or best.sum() < 8:
        return None
    _, _, vt = np.linalg.svd(a[best])
    T = vt[-1]
    flow = (w1 - w0)[big][best]
    if np.sum(flow @ T) > 0:
        T = -T
    return T


# ---------------------------------------------------------------------------------
# Motion state
# ---------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------
# Whole-run estimation
# ---------------------------------------------------------------------------------

def fit_fov(tracks, f3rows, verbose=True):
    """Vertical FOV that best predicts F3's facing from the flow.

    Between two F3 reads 0.2-0.5 s apart, chain flow_facing from the first read's facing; with
    the right FOV (focal length) the pixel motion converts into the right number of degrees,
    so the chain lands on the second read's facing. Try each candidate FOV, keep the best.
    Note: with "FOV effects" on, sprinting widens the FOV ~15% (dynamic FOV) - those pairs
    fit worse, and the fit lands between the two values.
    """
    facing = F3Facing(f3rows)
    t0s = tracks["t0"]
    pairs = []
    for k in range(len(facing.t)):
        ta = facing.t[k]
        j = int(np.searchsorted(facing.t, ta + 0.19))
        if j >= len(facing.t) or facing.t[j] - ta > 0.5:
            continue
        turn = abs((facing.yaw[j] - facing.yaw[k] + 180) % 360 - 180) + abs(facing.pitch[j] - facing.pitch[k])
        if not 3 < turn < 60:                # (nan pitch -> comparison False -> skipped)
            continue
        idx = np.flatnonzero((t0s >= ta - 0.01) & (tracks["t1"] <= facing.t[j] + 0.01))
        if len(idx) < 2 or abs(t0s[idx[0]] - ta) > 0.02 or abs(tracks["t1"][idx[-1]] - facing.t[j]) > 0.02:
            continue
        if np.any(tracks["n"][idx] < 20):
            continue
        pairs.append((idx, k, j))
    if len(pairs) < 10:
        if verbose:
            print(f"  FOV: only {len(pairs)} turning F3 pairs, using default {config.ODO_DEFAULT_FOV}")
        return config.ODO_DEFAULT_FOV, len(pairs), None
    pairs = pairs[:: max(1, len(pairs) // 150)]
    W, H = tracks["size"]
    lo, hi, st = config.ODO_FOV_RANGE
    scores = {}
    for fov in range(lo, hi + 1, st):
        K = intrinsics(fov, W, H)
        err = []
        for idx, k, j in pairs:
            ch = facing_chain(tracks, K, idx, None, (facing.yaw[k], facing.pitch[k]))
            end = ch[idx[-1]][1]
            err.append(abs((end[0] - facing.yaw[j] + 180) % 360 - 180) + abs(end[1] - facing.pitch[j]))
        scores[fov] = float(np.median(err))
    fov = min(scores, key=scores.get)
    if verbose:
        print(f"  FOV fit on {len(pairs)} turning F3 pairs: {fov} deg (median facing error {scores[fov]:.2f} deg; "
              f"{scores[lo]:.1f} at {lo}, {scores[max(scores)]:.1f} at {max(scores)})")
    return float(fov), len(pairs), scores


def run_steps(tracks, K, idx, f3facing=None, start=None, seed=1):
    """Facing, derotated point motion and direction of travel for steps idx (in order) -> {i: rec}.

    Facing chain: F3 is read only ~10x a second, the mouse moves in jerks between reads and the
    recording repeats frames now and then, so *interpolating* F3 facing between reads is off by
    many px on fast turns. Instead each step's turn comes from the flow (flow_facing) and F3
    only *re-anchors* the chain: a step that starts / ends on a frame with an F3 read uses that
    exact facing. With f3facing=None the chain starts from `start` and is never corrected -
    what the rotation module will have to do on its own.
    """
    rng = np.random.default_rng(seed)
    px = 1 / K[0, 0]                         # radians per pixel near the image centre
    recs = {}
    cur = start
    prev_t1 = None
    for i in idx:
        t0, t1 = tracks["t0"][i], tracks["t1"][i]
        if prev_t1 is not None and t0 - prev_t1 > 0.01 and f3facing is not None:
            cur = None                       # tracking broke (inventory etc.): wait for the next read
        prev_t1 = t1
        if f3facing is not None:
            r = f3facing.read_at(t0)
            if r is not None:
                pitch = r[1] if r[1] is not None else (cur[1] if cur is not None else f3facing.pitch_near(t0))
                cur = (r[0], pitch) if pitch is not None else cur
        rec = {"facing": None, "disp": None, "dir": None, "n": int(tracks["n"][i])}
        recs[i] = rec
        if cur is None:
            continue
        p0, p1 = step_points(tracks, i)
        end = f3facing.read_at(t1) if f3facing is not None else None
        if end is not None and end[1] is None:
            end = None                       # yaw-only read: let the flow find the pitch
        c0, c1 = pixels_to_rays(p0, K), pixels_to_rays(p1, K)
        f1 = end
        if f1 is None:
            ff = flow_facing(c0, c1, cur[0], cur[1], rng, px) if len(p0) >= 6 else None
            f1 = (ff[0], ff[1]) if ff is not None else cur     # lost: assume no turn
        rec["facing"] = (cur, f1)
        if len(p0) >= 8:
            w0 = c0 @ camera_rotation(*cur).T
            w1 = c1 @ camera_rotation(*f1).T
            # how far points still move once the turn is removed (px): ~0 when standing still
            rec["disp"] = float(np.median(angle_between(w0, w1)) / px)
            rec["dir"] = epipolar_direction(w0, w1, rng, px)
        cur = f1
    return recs


def integrate(tracks, recs, idx, move_speed, keep_dir=True):
    """Steps idx (in order) -> rows (t, dx, dz, dy, speed, state, confidence).

    * moving or not: the derotated point motion, median-filtered over 5 steps (one shaky
      step should not start or stop the player), above config.ODO_MOVE_PX;
    * direction: the epipolar direction, flattened onto the ground (Minecraft movement is
      horizontal unless jumping / falling / pillaring); mostly-vertical = "vertical" (no
      horizontal move); no direction found = keep the last one (else straight ahead);
    * speed: `move_speed` (m/s) - flow alone can't measure distance, so this is the runner's
      typical moving speed fitted on F3 stretches (fit_move_speed), close to sprinting.
    """
    idx = list(idx)
    disp = np.array([np.nan if recs[i]["disp"] is None else recs[i]["disp"] for i in idx])
    smooth = disp.copy()
    for k in range(len(idx)):
        win = disp[max(0, k - 2):k + 3]
        win = win[~np.isnan(win)]
        smooth[k] = np.median(win) if len(win) else np.nan
    rows = []
    last_dir = None
    for k, i in enumerate(idx):
        r = recs[i]
        t0, t1 = tracks["t0"][i], tracks["t1"][i]
        dt = t1 - t0
        T, state, conf = np.zeros(3), "unknown", 0.0
        if r["facing"] is not None and not np.isnan(smooth[k]):
            if smooth[k] < config.ODO_MOVE_PX:
                state, conf = "stopped", 0.6
            else:
                d = r["dir"] if keep_dir else None
                if d is not None and abs(d[1]) > config.ODO_VERTICAL_SHARE:
                    state, conf = ("rising" if d[1] > 0 else "falling"), 0.4
                else:
                    if d is not None and math.hypot(d[0], d[2]) > 0.3:
                        # Movement keys are digital: relative to where the player faces, travel is
                        # one of 8 directions (W, W+D, D, ... 45 degrees apart; air drift aside).
                        # Snap the measured direction to the nearest one - most of the time it's W.
                        ahead = -math.radians(r["facing"][1][0])          # world angle atan2(x, z) of "forward"
                        rel = (math.atan2(d[0], d[2]) - ahead + math.pi) % (2 * math.pi) - math.pi
                        snap = config.ODO_KEY_SNAP and math.radians(45) * round(rel / math.radians(45))
                        ang = ahead + (snap if config.ODO_KEY_SNAP else rel)
                        last_dir = np.array([math.sin(ang), math.cos(ang)])
                        conf = 0.5
                    elif last_dir is None or not keep_dir:
                        yaw = math.radians(r["facing"][1][0])
                        last_dir = np.array([-math.sin(yaw), math.cos(yaw)])    # straight ahead
                        conf = 0.2
                    else:
                        conf = 0.3
                    # Sprinting needs W held: travel more than 45 degrees off "ahead" is walking speed.
                    ahead = -math.radians(r["facing"][1][0])
                    off = abs((math.atan2(last_dir[0], last_dir[1]) - ahead + math.pi) % (2 * math.pi) - math.pi)
                    sprinting = off < math.radians(50)
                    v = move_speed if sprinting else min(move_speed, config.ODO_SPEEDS["walk"])
                    T = np.array([last_dir[0], 0.0, last_dir[1]]) * v * dt
                    state = "moving" if sprinting else "walking (strafe/back)"
        speed = math.hypot(T[0], T[2]) / dt
        rows.append((t1, T[0], T[2], T[1], speed, state, conf))
    return rows


def fit_move_speed(tracks, recs, f3rows):
    """Speed scale (m/s) fitted on the F3 anchors: true distance / time this module calls "moving".

    Flow can't measure distance, so the speed comes from Minecraft priors (walk 4.317, sprint
    5.612, sprint-jump ~7.1 m/s) - but a speedrunner mixes all of them with short stops, and
    the moving / stopped detector is imperfect. So we let the F3 anchors decide: over all
    tracked steps that F3 brackets, the distance F3 says was travelled, divided by the time
    our detector said "moving". Falls back to sprint speed without anchors.
    """
    valid = [r for r in f3rows if is_valid(r)]
    if len(valid) < 50:
        return config.ODO_SPEEDS["sprint"]
    vt = np.array([r["time_s"] for r in valid])
    P = np.array([[r["x"], r["z"]] for r in valid])
    idx = sorted(recs)
    rows = integrate(tracks, recs, idx, 1.0)
    dist = moving = 0.0
    for i, row in zip(idx, rows):
        t0, t1 = tracks["t0"][i], tracks["t1"][i]
        a, b = np.searchsorted(vt, t0), np.searchsorted(vt, t1)
        # both ends bracketed by reads at most 0.15 s away, same dimension, no teleport
        if a == 0 or b >= len(vt) or vt[b] - vt[a - 1] > t1 - t0 + 0.15:
            continue
        if valid[a - 1]["dim"] != valid[b]["dim"] or "teleport" in (valid[b]["flags"] or ""):
            continue
        p0 = np.array([np.interp(t0, vt[a - 1:b + 1], P[a - 1:b + 1, k]) for k in (0, 1)])
        p1 = np.array([np.interp(t1, vt[a - 1:b + 1], P[a - 1:b + 1, k]) for k in (0, 1)])
        dist += float(np.linalg.norm(p1 - p0))
        moving += row[4] * (t1 - t0)                 # speed 1 while moving -> moving seconds
    return dist / moving if moving > 30 else config.ODO_SPEEDS["sprint"]


# ---------------------------------------------------------------------------------
# Anchoring + output
# ---------------------------------------------------------------------------------

def anchors_from_f3(rows):
    """Valid F3 reads -> list of (t, x, y, z, dim, teleport_flag)."""
    return [(r["time_s"], r["x"], r["y"], r["z"], r["dim"], "teleport" in (r["flags"] or ""))
            for r in rows if is_valid(r)]


def fuse(steps, anchors, max_gap=60.0):
    """Dead-reckon steps between anchors; spread each gap's end error by distance moved.

    steps: rows (t, dx, dz, dy, speed, state, conf). Returns (track rows, anchored flags per step).
    """
    st = np.array([s[0] for s in steps]) if steps else np.zeros(0)
    track, anchored = [], np.zeros(len(steps), bool)
    for k, (ta, xa, ya, za, dima, _) in enumerate(anchors):
        track.append((ta, xa, ya, za, dima, "f3"))
        if k + 1 == len(anchors):
            break
        tb, xb, yb, zb, dimb, tele = anchors[k + 1]
        if tb - ta > max_gap or dima != dimb or tele:
            continue
        sel = np.flatnonzero((st > ta) & (st < tb))
        if not len(sel):
            continue
        d = np.array([[steps[i][1], steps[i][3], steps[i][2]] for i in sel])       # dx, dy, dz
        pos = np.array([xa, ya, za]) + np.cumsum(d, 0)
        # end-error at anchor b (the steps run a little short of tb; their last position stands in)
        err = np.array([xb, yb, zb]) - pos[-1]
        w = np.linalg.norm(d[:, [0, 2]], axis=1)
        frac = np.cumsum(w) / w.sum() if w.sum() > 0.05 else (st[sel] - ta) / (tb - ta)
        pos = pos + frac[:, None] * err
        anchored[sel] = True
        for i, p in zip(sel, pos):
            track.append((st[i], p[0], p[1], p[2], dima, "odo"))
    track.sort(key=lambda r: r[0])
    return track, anchored


def write_outputs(run_dir, steps, anchored, track):
    run_dir = Path(run_dir)
    with open(run_dir / "odometry.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "dx", "dz", "dy", "speed", "state", "confidence", "anchored"])
        for s, a in zip(steps, anchored):
            w.writerow([f"{s[0]:.3f}", f"{s[1]:.3f}", f"{s[2]:.3f}", f"{s[3]:.3f}", f"{s[4]:.2f}", s[5],
                        f"{s[6]:.2f}", int(a)])
    with open(run_dir / "odometry_track.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "x", "y", "z", "dim", "src"])
        for r in track:
            w.writerow([f"{r[0]:.3f}", f"{r[1]:.3f}", f"{r[2]:.3f}", f"{r[3]:.3f}", r[4], r[5]])


# ---------------------------------------------------------------------------------
# Evaluation: hide F3 position for a window, dead-reckon from its start, compare with F3
# ---------------------------------------------------------------------------------

def evaluate(tracks, K, f3rows, recs_f3, move_speed, windows=(5, 10, 30), min_speed=1.0):
    """Hide F3 *position* for windows of W s, dead-reckon from the window's first read, compare.

    Variants: "f3_facing" (rotation chain still re-anchored on F3 facing reads),
    "flow_facing" (facing only from the window's first read, then flow alone - what the
    rotation module must deliver), "yaw_ahead" (baseline: no flow direction, just move
    straight ahead along F3 facing while the picture moves).
    """
    valid = [r for r in f3rows if is_valid(r)]
    vt = np.array([r["time_s"] for r in valid])
    t0s = tracks["t0"]
    facing = F3Facing(f3rows)
    report = {}
    for W in windows:
        res = {"f3_facing": [], "flow_facing": [], "yaw_ahead": []}
        t = vt[0]
        while t + W < vt[-1]:
            ta = t
            t += W / 2                                      # half-overlapping windows
            ia, ib = np.searchsorted(vt, ta), np.searchsorted(vt, ta + W)
            if ib >= len(vt) or vt[ia] - ta > 0.15 or abs(vt[ib] - (ta + W)) > 0.15:
                continue
            seg = valid[ia:ib + 1]
            if len({r["dim"] for r in seg}) > 1 or any("teleport" in (r["flags"] or "") for r in seg[1:]):
                continue
            if np.max(np.diff(vt[ia:ib + 1])) > 1.0:
                continue
            idx = np.flatnonzero((t0s >= vt[ia] - 1e-6) & (tracks["t1"] <= vt[ib] + 1e-6))
            covered = (tracks["t1"][idx] - t0s[idx]).sum() if len(idx) else 0
            if covered < 0.9 * (vt[ib] - vt[ia]):
                continue
            xs = np.array([[r["x"], r["y"], r["z"]] for r in seg])
            path = np.linalg.norm(np.diff(xs[:, [0, 2]], axis=0), axis=1).sum()
            if path < min_speed * W:
                continue
            true_net = xs[-1] - xs[0]
            true_speed = path / (vt[ib] - vt[ia])
            fa = facing.near(t0s[idx[0]], 0.3)
            variants = {"f3_facing": recs_f3,
                        "yaw_ahead": {i: dict(recs_f3[i], dir=None) for i in idx}}
            if fa is not None:
                variants["flow_facing"] = run_steps(tracks, K, idx, None, fa[1:])
            for name, recs in variants.items():
                rows = integrate(tracks, recs, idx, move_speed, keep_dir=name != "yaw_ahead")
                d = np.array([[r[1], r[3], r[2]] for r in rows])
                net = d.sum(0)
                end_err = math.hypot(net[0] - true_net[0], net[2] - true_net[2])
                tn = math.hypot(true_net[0], true_net[2])
                head = None
                if tn > 2 and math.hypot(net[0], net[2]) > 0.5:
                    head = abs((math.degrees(math.atan2(net[0], net[2]) - math.atan2(true_net[0], true_net[2]))
                                + 180) % 360 - 180)
                pred_speed = np.linalg.norm(d[:, [0, 2]], axis=1).sum() / (vt[ib] - vt[ia])
                res[name].append({"t": round(float(vt[ia]), 2), "path": round(float(path), 2),
                                  "end_err_pct": round(100 * end_err / path, 1),
                                  "heading_err": None if head is None else round(head, 1),
                                  "speed_err_pct": round(100 * abs(pred_speed - true_speed) / true_speed, 1)})
        report[W] = {name: summarize(v) for name, v in res.items()}
        report[W]["_windows"] = res
    return report


def evaluate_gaps(tracks, K, f3rows, move_speed, min_s=2.0, max_s=60.0):
    """Real use: stretches where the runner closed F3 (clean picture, no F3 facing either).

    Dead-reckon from the last read before the gap (facing chained by flow alone) and compare
    with the first read after it.
    """
    valid = [r for r in f3rows if is_valid(r)]
    facing = F3Facing(f3rows)
    out = []
    for a, b in zip(valid, valid[1:]):
        gap = b["time_s"] - a["time_s"]
        if not min_s <= gap <= max_s or a["dim"] != b["dim"] or "teleport" in (b["flags"] or ""):
            continue
        idx = np.flatnonzero((tracks["t0"] >= a["time_s"] - 0.07) & (tracks["t1"] <= b["time_s"] + 0.07))
        if not len(idx) or (tracks["t1"][idx] - tracks["t0"][idx]).sum() < 0.9 * gap:
            continue
        fa = facing.near(a["time_s"], 0.3)
        net_true = math.hypot(b["x"] - a["x"], b["z"] - a["z"])
        if fa is None or net_true < 3:
            continue
        rows = integrate(tracks, run_steps(tracks, K, idx, None, fa[1:]), idx, move_speed)
        d = np.array([[r[1], r[2]] for r in rows]).sum(0)
        err = math.hypot(d[0] - (b["x"] - a["x"]), d[1] - (b["z"] - a["z"]))
        head = abs((math.degrees(math.atan2(d[0], d[1]) - math.atan2(b["x"] - a["x"], b["z"] - a["z"])) + 180)
                   % 360 - 180) if math.hypot(*d) > 0.5 else None
        out.append({"t": a["time_s"], "gap_s": round(gap, 1), "net_true": round(net_true, 1),
                    "end_err_pct_of_net": round(100 * err / net_true, 1), "heading_err": head and round(head, 1)})
    return out


def summarize(v):
    if not v:
        return {"n": 0}
    e = np.array([x["end_err_pct"] for x in v])
    h = np.array([x["heading_err"] for x in v if x["heading_err"] is not None])
    s = np.array([x["speed_err_pct"] for x in v])
    return {"n": len(v), "end_err_pct_median": round(float(np.median(e)), 1),
            "end_err_pct_p75": round(float(np.percentile(e, 75)), 1),
            "share_within_10pct": round(float(np.mean(e <= 10)), 2),
            "heading_err_median": round(float(np.median(h)), 1) if len(h) else None,
            "speed_err_pct_median": round(float(np.median(s)), 1)}


# ---------------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------------

def load_or_track(run_dir, video, fps_out, cache):
    if cache and Path(cache).is_file():
        tracks = dict(np.load(cache))
    else:
        tracks = track_run(run_dir, video, fps_out)
        if cache:
            np.savez_compressed(cache, **tracks)
    tracks["offsets"] = np.concatenate([[0], np.cumsum(tracks["n"])[:-1]]) if len(tracks["n"]) else np.zeros(0, int)
    return tracks


def odometry_command(run_dir, video=None, fps_out=None, do_eval=False, cache=None):
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text()) if (run_dir / "run.json").is_file() else {}
    video = video or (run_dir / "video.mp4" if (run_dir / "video.mp4").is_file() else run.get("video"))
    f3rows = read_f3_csv(run_dir / "f3.csv") or []
    print(f"Odometry for {run_dir.name}: tracking at {fps_out or config.ODO_SAMPLES_PER_SECOND} fps ...")
    t_start = time.process_time()
    tracks = load_or_track(run_dir, video, fps_out, cache)
    W, H = tracks["size"]
    fov, n_fov, _ = fit_fov(tracks, f3rows)
    K = intrinsics(fov, W, H)
    facing = F3Facing(f3rows)
    # Facing: flow rotation re-anchored on every F3 read. Where F3 is closed, the chain just
    # continues from the last read (until tracking breaks) - the rotation module's job later.
    recs = run_steps(tracks, K, range(len(tracks["t0"])), facing)
    move_speed = fit_move_speed(tracks, recs, f3rows)
    steps = integrate(tracks, recs, range(len(recs)), move_speed)
    track, anchored = fuse(steps, anchors_from_f3(f3rows))
    write_outputs(run_dir, steps, anchored, track)
    cpu = float(tracks["cpu_s"]) + time.process_time() - t_start
    minutes = float(tracks["video_s"]) / 60
    print(f"  {len(steps)} steps, FOV {fov:.0f}, moving speed {move_speed:.2f} m/s; "
          f"CPU {float(tracks['cpu_s']):.0f} s tracking + {time.process_time() - t_start:.0f} s estimation "
          f"= {cpu / max(minutes, 1e-9):.1f} s per video minute")
    print(f"  Wrote odometry.csv ({len(steps)} steps) and odometry_track.csv ({len(track)} points)")
    if do_eval:
        rep = evaluate(tracks, K, f3rows, recs, move_speed)
        out = {"fov": fov, "fov_pairs": n_fov, "cpu_s_per_video_min": round(cpu / max(minutes, 1e-9), 1),
               "move_speed": round(move_speed, 2), "windows": rep}
        gaps = evaluate_gaps(tracks, K, f3rows, move_speed)
        out["f3_closed_gaps"] = gaps
        if gaps:
            e = np.array([g["end_err_pct_of_net"] for g in gaps])
            h = [g["heading_err"] for g in gaps if g["heading_err"] is not None]
            print(f"  F3-closed gaps (flow facing, clean picture): n={len(gaps)}, end error % of net distance "
                  f"median {np.median(e):.0f}, within 10%: {np.mean(e <= 10):.2f}, heading median "
                  f"{np.median(h) if h else float('nan'):.0f} deg")
        (run_dir / "odometry_eval.json").write_text(json.dumps(out, indent=1))
        for Wn, r in rep.items():
            for name in ("f3_facing", "flow_facing", "yaw_ahead"):
                print(f"  {Wn:>3} s windows, {name:11}: {r.get(name)}")
    return steps
