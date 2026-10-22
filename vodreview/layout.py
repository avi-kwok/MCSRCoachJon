"""Per-video auto-calibration: where is everything on *this* player's screen?

Different players record at different resolutions, use different GUI scales,
put MCSR's panel and their timer in different corners and add their own
overlays (Ninjabrain Bot, eye-measuring projectors, webcams). Instead of fixed
1080p coordinates, `calibrate()` looks at ~100-300 frames spread over the video
(the video's keyframes: decoding only those is ~20x faster than seeking) and
measures, from first principles:

1. **GUI scale** `k` (screen px per GUI px) from the hotbar: Minecraft always
   draws it 182x22 GUI px, centred at the bottom of the game view, with a slot
   border every 20 px. The temporal median of the frames shows it cleanly; the
   k whose border pattern correlates best wins (gui.measure_gui_scale). The game
   view rectangle (letterbox bars) comes from rows/columns that never change.
2. **Overlay mask** from temporal statistics of world frames: pixels that stay
   unchanged while the world behind them changes (static overlays: timers,
   MCSR panel, Ninjabrain, OBS sources) or that hold sharp text-like contrast in
   many frames (subtitles, chat), minus the vanilla HUD (hotbar, hearts,
   crosshair - those stay, they are gameplay). Plus the vanilla toast stack.
3. **MCSR panel**: the static yellow "Current Match" line (bold, 84 font px
   wide - its width gives the panel's own font size), then the white name and
   grey status lines below it, left- or right-aligned depending on the corner.
4. **Match clock**: coloured text lines anywhere on screen that read as
   MM:SS.mmm (or .cc) with the glyph reader and advance with the video.
5. **Resized strips**: frames without the full-size hotbar that are mostly flat
   wallpaper; the non-flat rectangle is the strip.
6. **Toasts**: advancement toasts seen in the sample (their measured scale and
   right edge); otherwise predicted from k (160x32 GUI px, top-right).

Everything is saved to runs/<id>/layout.json and every detector reads it
(see Layout). `default_layout()` reproduces the hand-measured values of the
tuning VOD, used when calibration can't measure something.
"""

import json
import subprocess
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from . import config, gui
from .glyphs import load_glyph_templates, match_glyph, segment_line
from .remux import _tool
from .video import open_video

LAYOUT_VERSION = 1
REF_K = 4.5                    # GUI scale of the tuning VOD (all old 1080p numbers were measured at it)
CM_FONT_W = 84                 # "Current Match" (bold) is 84 font px wide


# ---------------------------------------------------------------------------------
# The Layout object used by the detectors
# ---------------------------------------------------------------------------------

class Layout:
    """Read-only view of layout.json with helpers to turn GUI coordinates into pixels."""

    def __init__(self, data):
        self.data = data
        self.w, self.h = data["frame"]["w"], data["frame"]["h"]
        self.game = tuple(data["game"])
        self.k = float(data["gui"]["k"])
        self.panel = data.get("panel") or {}
        self.clock_lines = (data.get("clock") or {}).get("lines", [])
        self.strips = data.get("strips") or {}
        self.toast = data.get("toasts") or {}

    # -- scale helpers --------------------------------------------------------
    @property
    def rel(self):
        """Size factor relative to the tuning VOD's GUI (old 1080p templates x this)."""
        return self.k / REF_K

    @property
    def cx(self):
        return (self.game[0] + self.game[2]) / 2

    @property
    def cy(self):
        return (self.game[1] + self.game[3]) / 2

    def gui_rect(self, gx0, gy0, gx1, gy1, ax="left", ay="top"):
        """GUI-pixel rectangle -> screen pixel (x0, y0, x1, y1).

        ax/ay say which game-view edge the GUI coordinates are measured from:
        "left"/"right"/"center" and "top"/"bottom"/"center"; negative values
        reach left/up from that edge.
        """
        x0, y0, x1, y1 = self.game
        bx = {"left": x0, "right": x1, "center": (x0 + x1) / 2}[ax]
        by = {"top": y0, "bottom": y1, "center": (y0 + y1) / 2}[ay]
        k = self.k
        ra, rb = sorted((bx + gx0 * k, bx + gx1 * k))
        rc, rd = sorted((by + gy0 * k, by + gy1 * k))
        return (max(0, int(round(ra))), max(0, int(round(rc))),
                min(self.w, int(round(rb))), min(self.h, int(round(rd))))

    def norm(self, rect):
        x0, y0, x1, y1 = rect
        return (x0 / self.w, y0 / self.h, x1 / self.w, y1 / self.h)

    # -- overlay mask -----------------------------------------------------------
    def overlay_rects(self):
        """Normalized rectangles masked out of motion / colour statistics."""
        rects = (self.data.get("overlay_mask") or {}).get("rects")
        if rects:
            return [tuple(r) for r in rects]
        return list(config.OVERLAY_MASK.values())

    def f3_rects(self):
        """Normalized rectangles of the F3 text columns + pie chart (masked while F3 shows).

        The tuning VOD's hand-measured F3_MASK, converted to GUI pixels and
        anchored to the edge each block hangs from, so it scales with k.
        """
        r = self.norm
        return [
            r(self.gui_rect(0, 0, config.F3_MASK_GUI["left_w"], config.F3_MASK_GUI["left_h"])),
            r(self.gui_rect(-config.F3_MASK_GUI["right_top_w"], 0, 0, config.F3_MASK_GUI["right_top_h"], ax="right")),
            r(self.gui_rect(-config.F3_MASK_GUI["right_lower_w"], config.F3_MASK_GUI["right_top_h"], 0,
                            config.F3_MASK_GUI["right_lower_y1"], ax="right")),
            r(self.gui_rect(-config.F3_MASK_GUI["pie_w"], -config.F3_MASK_GUI["pie_y0"], 0,
                            -config.F3_MASK_GUI["pie_y1"], ax="right", ay="bottom")),
        ]

    def hud_rects(self):
        """Normalized rectangles of the vanilla HUD at the bottom centre (hotbar, hearts, armour, food, XP)."""
        x = config.DIM_HUD_GUI_HALF_W
        return [self.norm(self.gui_rect(-x, -config.DIM_HUD_GUI_H, x, 0, ax="center", ay="bottom"))]

    # -- windows (full view + resized strips) ---------------------------------------
    def windows(self):
        """{name: (x0, y0, x1, y1) px} - the full game view and every resized strip seen."""
        out = {"full": self.game}
        for name, s in self.strips.items():
            out[name] = tuple(s["rect"])
        return out

    def toast_search_regions(self, strip=None):
        """Pixel boxes searched for toasts: the full view's toast stack + the top-right of every strip
        (and of `strip`, the one shown in the current frame)."""
        boxes = [self.gui_rect(-(160 + config.TOAST_SEARCH_PAD_GUI), 0, 0, config.TOAST_SEARCH_SLOTS * 32, ax="right")]
        rects = [s["rect"] for s in self.strips.values()] + ([strip] if strip is not None else [])
        for sx0, sy0, sx1, sy1 in rects:
            box = (int(sx0 + (sx1 - sx0) // 2), int(sy0), int(sx1), int(sy0 + min(sy1 - sy0, 0.45 * self.h) * 0.9))
            if not any(b[0] <= box[0] and b[1] <= box[1] and box[2] <= b[2] and box[3] <= b[3] for b in boxes):
                boxes.append(box)
        return boxes

    def toast_search_region(self):
        """Bounding box of all toast search regions (for display)."""
        boxes = self.toast_search_regions()
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def summary(self):
        d = self.data
        g = d["gui"]
        lines = [f"Layout ({d.get('sampling', '?')}, {d.get('frames_sampled', 0)} frames): "
                 f"{self.w}x{self.h}, game view {list(self.game)}"
                 f"{' (letterboxed)' if d.get('letterboxed') else ''}",
                 f"  GUI scale     : {self.k:.2f} screen px per GUI px (hotbar fit {g.get('hotbar_score', 0):.2f}, "
                 f"source {g.get('source')})"]
        om = d.get("overlay_mask") or {}
        lines.append(f"  Overlay mask  : {len(om.get('rects', []))} rects, {om.get('coverage_pct') or 0:.1f}% of the frame "
                     f"({om.get('source', 'fallback')})")
        p = self.panel
        if p.get("found"):
            lines.append(f"  MCSR panel    : {p['anchor']}-aligned at x {p['edge_x']}, 'Current Match' y {p['top_y']}, "
                         f"font px {p['font_px']:.2f}; name y {p['name_top']}, status y {p['status_top']}")
        else:
            lines.append("  MCSR panel    : not found")
        if self.clock_lines:
            for i, ln in enumerate(self.clock_lines, 1):
                lines.append(f"  Clock line {i}  : box {ln['box']}, colour BGR {ln['color']}, font px {ln['font_px']:.2f}, "
                             f"{ln['reads']} reads, offset {ln.get('offset_s', 0):.2f}s")
        else:
            lines.append("  Clock         : not found")
        if self.strips:
            for name, s in self.strips.items():
                lines.append(f"  Strip {name:<8}: {s['rect']} ({s['frames']} frames, {s.get('source', 'calibration')})")
        else:
            lines.append("  Strips        : none seen")
        t = self.toast
        lines.append(f"  Toasts        : {t.get('seen', 0)} seen, k {t.get('k', self.k):.2f}, search "
                     + ", ".join(str(list(b)) for b in self.toast_search_regions()))
        return "\n".join(lines)


def default_layout(width, height):
    """The tuning VOD's hand-measured layout, scaled to this frame size (the fallback)."""
    s = height / 1080
    strips = {name: {"rect": [int(round(x0 * width)), int(round(y0 * height)), int(round(x1 * width)),
                              int(round(y1 * height))], "frames": 0, "source": "default"}
              for name, (x0, y0, x1, y1) in config.RESIZED_LAYOUTS.items()}
    return {
        "version": LAYOUT_VERSION, "frame": {"w": width, "h": height}, "sampling": "default",
        "frames_sampled": 0, "game": [0, 0, width, height], "letterboxed": False,
        "gui": {"k": REF_K * s, "k_raw": None, "hotbar_score": 0.0, "source": "default (tuning VOD)"},
        "overlay_mask": {"rects": [list(r) for r in config.OVERLAY_MASK.values()], "coverage_pct": None,
                         "source": "fallback (hand-written OVERLAY_MASK)"},
        "panel": {"found": True, "anchor": "right", "font_px": 4.5 * s, "edge_x": int(round(1880 * s)),
                  "top_y": int(round(144 * s)), "name_top": int(round(248 * s)), "status_top": int(round(292 * s)),
                  "status_text_x": None, "source": "default"},
        "clock": {"lines": [
            {"box": [int(round(v * s)) for v in (1380, 26, 1900, 76)], "color": [255, 255, 85], "font_px": 4.5 * s,
             "reads": 0, "offset_s": 0.0, "mask": "two_channel"},
            {"box": [int(round(v * s)) for v in (1380, 72, 1900, 122)], "color": [85, 255, 255], "font_px": 4.5 * s,
             "reads": 0, "offset_s": 0.0, "mask": "two_channel"}], "source": "default"},
        "strips": strips,
        "toasts": {"seen": 0, "k": REF_K * s},
    }


def save_layout(out_dir, data):
    path = Path(out_dir) / "layout.json"
    path.write_text(json.dumps(data, indent=1) + "\n")
    return path


def load_layout(out_dir, width=None, height=None):
    """runs/<id>/layout.json -> Layout (the default layout if there is none)."""
    path = Path(out_dir) / "layout.json"
    if path.is_file():
        return Layout(json.loads(path.read_text()))
    if width is None:
        raise FileNotFoundError(path)
    return Layout(default_layout(width, height))


# ---------------------------------------------------------------------------------
# Sampling frames
# ---------------------------------------------------------------------------------

def keyframe_times(video_path):
    out = subprocess.run([_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", str(video_path)],
                         capture_output=True, text=True, check=True).stdout
    times = []
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and "K" in parts[1] and parts[0] not in ("", "N/A"):
            times.append(float(parts[0]))
    return sorted(times)


def iter_keyframes(video_path, width, height, keep=None):
    """Yield (time, BGR frame) for the video's keyframes (only those are decoded: fast).

    `keep` = set of keyframe indices to yield (None = all).
    """
    times = keyframe_times(video_path)
    proc = subprocess.Popen([_tool("ffmpeg"), "-v", "error", "-skip_frame", "nokey", "-i", str(video_path),
                             "-an", "-sn", "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                            stdout=subprocess.PIPE)
    size = width * height * 3
    try:
        for i, t in enumerate(times):
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            if keep is None or i in keep:
                yield t, np.frombuffer(buf, np.uint8).reshape(height, width, 3)
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def iter_seek(video_path, times):
    cap = open_video(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    try:
        for t in times:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
            ok, frame = cap.read()
            if ok:
                yield t, frame
    finally:
        cap.release()


class FrameSource:
    """The calibration sample: evenly spread keyframes (or seeks when there are too few)."""

    def __init__(self, video_path, width, height, duration):
        self.path, self.w, self.h = video_path, width, height
        try:
            times = keyframe_times(video_path)
        except (subprocess.CalledProcessError, SystemExit, OSError):
            times = []
        times = [t for t in times if t <= duration]
        if len(times) >= config.CAL_MIN_FRAMES:
            n = min(len(times), config.CAL_MAX_FRAMES)
            idx = sorted({int(round(i * (len(times) - 1) / max(1, n - 1))) for i in range(n)})
            self.mode, self.keep, self.times = "keyframes", set(idx), [times[i] for i in idx]
        else:
            n = config.CAL_SEEK_FRAMES
            self.mode, self.keep = "seek", None
            self.times = [(i + 0.5) * duration / n for i in range(n)]

    def __iter__(self):
        if self.mode == "keyframes":
            yield from iter_keyframes(self.path, self.w, self.h, self.keep)
        else:
            yield from iter_seek(self.path, self.times)


# ---------------------------------------------------------------------------------
# Per-frame helpers shared with the analysis pass
# ---------------------------------------------------------------------------------

def tile_stats(small, tile):
    h, w = small.shape
    h, w = h - h % tile, w - w % tile
    t = small[:h, :w].astype(np.float32).reshape(h // tile, tile, w // tile, tile)
    return t.std(axis=(1, 3)), t.mean(axis=(1, 3))


def find_strip(small_gray, hotbar_score):
    """Resized-view test on the 480x270 grey frame -> strip rect in small px, or None.

    Resized (MCSR's tall / thin / wide macros, and the OBS scene around them) =
    (1) the full-size hotbar is gone from the bottom centre (in every resized
    view the game - hotbar included - is drawn smaller somewhere else), and
    (2) a large part of the frame is flat wallpaper: >= RESIZED_MIN_WALL of the
    tiles flat and not black, or >= RESIZED_MIN_BLACK flat black (a black
    desktop) with some non-black content. An all-black loading frame has no
    content; the dirt-textured loading screen isn't flat.
    The strip = the content blob containing the frame's centre column (MCSR
    centres the window), else the largest one (projector windows for eye
    measuring are separate blobs on the wallpaper). It must not cover most of
    the frame (a pre-match countdown view without HUD looking at the sky).
    """
    if hotbar_score >= config.RESIZED_MAX_HOTBAR_SCORE:
        return None
    sd, mean = tile_stats(small_gray, config.RESIZED_TILE)
    flat = sd < config.RESIZED_TILE_STD
    wall = flat & (mean > config.RESIZED_BLACK_MAX)
    black = flat & ~wall
    if wall.mean() >= config.RESIZED_MIN_WALL and (~flat).mean() >= config.RESIZED_MIN_CONTENT:
        content = ~flat
    elif black.mean() >= config.RESIZED_MIN_BLACK and (~black).mean() >= config.RESIZED_MIN_NONBLACK:
        content = ~black
    else:
        return None
    n, labels, stats, _ = cv2.connectedComponentsWithStats(content.astype(np.uint8), connectivity=8)
    if n <= 1:
        return None
    mid = content.shape[1] // 2
    central = [i for i in range(1, n) if stats[i, cv2.CC_STAT_LEFT] <= mid < stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH]
               and stats[i, cv2.CC_STAT_AREA] >= config.RESIZED_MIN_STRIP * content.size]
    pool = central or list(range(1, n))
    i = max(pool, key=lambda j: stats[j, cv2.CC_STAT_AREA])
    x, y, w, h, _ = (int(v) for v in stats[i])
    if w * h > config.RESIZED_MAX_STRIP * content.size or w * h < config.RESIZED_MIN_STRIP * content.size:
        return None
    t = config.RESIZED_TILE
    rect = refine_strip(small_gray, (x * t, y * t, (x + w) * t, (y + h) * t))
    # A real strip meets the wallpaper along straight edges with a visible brightness jump;
    # the bounding box of loading-screen text on a flat dirt background doesn't.
    if edge_contrast(small_gray, rect) <= config.RESIZED_EDGE_CONTRAST:
        return None
    return rect


def edge_contrast(gray, rect, gap=2):
    """Mean brightness jump across the strip border (edges on the frame border are skipped; 0 if none)."""
    h, w = gray.shape
    x0, y0, x1, y1 = (int(v) for v in rect)
    g = gray.astype(np.float32)
    jumps = []
    if x0 - gap - 1 >= 0 and y1 > y0:
        jumps.append(np.abs(g[y0:y1, min(w - 1, x0 + gap)] - g[y0:y1, x0 - gap - 1]).mean())
    if x1 + gap < w and y1 > y0:
        jumps.append(np.abs(g[y0:y1, max(0, x1 - gap - 1)] - g[y0:y1, x1 + gap]).mean())
    if y0 - gap - 1 >= 0 and x1 > x0:
        jumps.append(np.abs(g[min(h - 1, y0 + gap), x0:x1] - g[y0 - gap - 1, x0:x1]).mean())
    if y1 + gap < h and x1 > x0:
        jumps.append(np.abs(g[max(0, y1 - gap - 1), x0:x1] - g[y1 + gap, x0:x1]).mean())
    return float(np.mean(jumps)) if jumps else 0.0


def refine_strip(small_gray, rect):
    """Snap a tile-aligned strip rect to the strongest brightness edges nearby (small px)."""
    g = small_gray.astype(np.float32)
    h, w = g.shape
    x0, y0, x1, y1 = rect
    t = config.RESIZED_TILE
    colgrad = np.abs(np.diff(g, axis=1)).mean(axis=0)     # edge strength between column x and x+1
    rowgrad = np.abs(np.diff(g, axis=0)).mean(axis=1)

    def snap(v, grad, lo, hi):
        a, b = max(0, v - t), min(len(grad), v + t)
        if b <= a:
            return v
        return a + int(np.argmax(grad[a:b])) + 1 if grad[a:b].max() > 2 else v

    nx0 = 0 if x0 <= 0 else snap(x0, colgrad, 0, w)
    nx1 = w if x1 >= w else snap(x1, colgrad, 0, w)
    ny0 = 0 if y0 <= 0 else snap(y0, rowgrad, 0, h)
    ny1 = h if y1 >= h else snap(y1, rowgrad, 0, h)
    return (nx0, ny0, nx1, ny1)


def strip_name(rect, width, height):
    """tall / thin (narrow strips, thin = not full height) or wide, from the shape."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if w >= 2 * h:
        return "wide"
    if h >= 2 * w:
        return "tall" if h >= 0.97 * height else "thin"
    return "other"


def cluster_strips(found, width, height, min_frames=None):
    """[(rect px)] -> {name: {"rect", "frames"}} (median rect of each shape class)."""
    min_frames = config.STRIP_MIN_FRAMES if min_frames is None else min_frames
    by = {}
    for rect in found:
        by.setdefault(strip_name(rect, width, height), []).append(rect)
    out = {}
    for name, rects in by.items():
        if name == "other" or len(rects) < min_frames:
            continue
        med = [int(np.median([r[i] for r in rects])) for i in range(4)]
        out[name] = {"rect": med, "frames": len(rects)}
    return out


# --- text masks for the panel / clock search ------------------------------------------

def shadow_near(gray, max_shift=5):
    """True where a dark pixel lies 1..max_shift px down-right (Minecraft's drop shadow / an outline)."""
    dark = gray < config.CAL_SHADOW_MAX
    out = np.zeros_like(dark)
    for s in range(1, max_shift + 1):
        out[:-s, :-s] |= dark[s:, s:]
    return out


def colour_masks(frame):
    """Yellow / white / grey shadowed-text masks (bool) of a BGR frame."""
    p = frame.astype(np.int16)
    b, g, r = p[..., 0], p[..., 1], p[..., 2]
    mn, mx = p.min(axis=2), p.max(axis=2)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    sh = shadow_near(gray)
    yellow = (r >= 190) & (g >= 190) & (b <= 140) & sh
    white = (mn >= 190) & (mx - mn <= 30) & sh
    glo, ghi = config.OPPONENT_GREY_RANGE
    grey = (mn >= glo) & (mx <= ghi) & (mx - mn <= config.OPPONENT_GREY_MAX_CHROMA) & sh
    return yellow, white, grey


# ---------------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------------

def _game_rect(half_stack, width, height):
    """Game view rectangle = everything inside the static bands at the frame edges.

    A band row/column is "static" when nearly all of its pixels sit at their
    temporal median in nearly all sampled frames (robust to the odd fade or
    flash frame). That covers letterbox bars (any colour), a window title bar,
    an OS taskbar and window borders around a windowed game; fullscreen VODs
    have no such band, so the rect is the full frame.
    """
    n = len(half_stack)
    if n < 8:
        return [0, 0, width, height]
    sub = half_stack[::max(1, n // config.CAL_RECT_FRAMES)]
    med = np.median(sub, axis=0)
    near = (np.abs(sub.astype(np.int16) - med.astype(np.int16)) <= config.CAL_RECT_PIX_TOL).mean(axis=0)
    static = near >= config.CAL_RECT_FRAME_FRAC
    sh, sw = static.shape
    thr = config.CAL_RECT_LINE_FRAC

    def walk(lines, limit):
        i = 0
        while i < limit and lines[i].mean() >= thr:
            i += 1
        return i if i >= 2 else 0          # a 1-line "band" is noise
    r0 = walk(static, sh // 4)
    r1 = sh - walk(static[::-1], sh // 4)
    c0 = walk(static.T, sw // 4)
    c1 = sw - walk(static.T[::-1], sw // 4)
    sx, sy = width / sw, height / sh
    return [int(round(c0 * sx)), int(round(r0 * sy)), int(round(c1 * sx)), int(round(r1 * sy))]


def _activity(stack, axis):
    """Mean |pixel - temporal median| per row (axis=1) or column (axis=0) of a full-res band stack."""
    sub = stack[::max(1, len(stack) // config.CAL_RECT_FRAMES)]
    med = np.median(sub, axis=0)
    return np.abs(sub.astype(np.int16) - med.astype(np.int16)).mean(axis=0).mean(axis=axis)


def _edge(act, outside, inside):
    """Sub-pixel position (line-centre coordinates) where `act` crosses half-way from its level at index
    `outside` (in the bar) to its level at index `inside` (in the game), scanning from outside in."""
    step = 1 if inside > outside else -1
    lo = float(act[outside])
    hi = float(np.median(act[max(0, min(inside, inside + 8 * step)):max(inside, inside + 8 * step) + 1]))
    mid = (lo + hi) / 2
    i = outside
    while i != inside and act[i + step] < mid:
        i += step
    if i == inside:
        return float(inside)
    a, b = float(act[i]), float(act[i + step])
    return i + step * (mid - a) / max(b - a, 1e-6)


def _refine_game_rect(game, top_band, bot_band, band_y, width, height):
    """Snap the half-res game rect's edges to full-res pixels.

    Each edge sits where the temporal activity rises half-way from the static bar's level to the
    game's (the recording blurs the window edge over ~3 px; F3 text needs it within ~1 px).
    """
    x0, y0, x1, y1 = game
    r = 6
    if y0 > 0 and y0 + 2 * r < top_band.shape[1]:
        act = _activity(top_band[:, :y0 + 2 * r + 1], 1)
        y0 = int(round(_edge(act, max(0, y0 - r), y0 + r)))
    if y1 < height and y1 - 2 * r > band_y:
        off = y1 - 2 * r - band_y
        act = _activity(bot_band[:, off:], 1)                       # act[i] = frame row y1 - 2r + i
        out_i = min(len(act) - 1, 3 * r)
        y1 = int(round(_edge(act, out_i, r) + (y1 - 2 * r))) + 1
    if (x0 > 0 or x1 < width) and y1 - band_y > 8:
        act = _activity(bot_band[:, :y1 - band_y], 0)
        if x0 > 0:
            x0 = int(round(_edge(act, max(0, x0 - r), min(width - 1, x0 + r))))
        if x1 < width:
            x1 = int(round(_edge(act, min(width - 1, x1 + r), max(0, x1 - r)))) + 1
    return [int(x0), int(y0), int(x1), int(y1)]


def _hotbar_dy(median, k, game, reach=4):
    """Vertical shift (px) that best lines the hotbar's border rows up with the game view's bottom edge."""
    from .hotbar import _BORDER_ROWS, _BORDER_V
    x0, _, x1, y1 = game
    xs = [int(round((x0 + x1) / 2 + (-81 + 20 * i) * k)) for i in range(9)]
    best, best_dy = -2.0, 0
    for dy in range(-reach, reach + 1):
        ys = [int(np.floor(y1 + dy - 22 * k + (r + 0.5) * k)) for r in _BORDER_ROWS]
        if min(ys) < 0 or max(ys) >= median.shape[0]:
            continue
        prof = np.array([np.median(median[y, xs]) for y in ys], np.float64)
        sc = gui._corr(prof, _BORDER_V)
        if sc > best + 1e-6 or (abs(sc - best) <= 1e-6 and abs(dy) < abs(best_dy)):
            best, best_dy = sc, dy
    return best_dy


def classify_frame(frame, gray, lay, small_gray=None):
    """Screen type of one frame with the structure tests (calibration's quick version of ScreenClassifier)."""
    from .screens import structure_screen
    return structure_screen(frame, gray, lay, small_gray)


def calibrate(video_path, verbose=True):
    """Measure the layout of one video -> layout dict (see module docstring)."""
    from .video import video_info
    started = time.time()
    fps, _, width, height, duration = video_info(video_path)
    src = FrameSource(video_path, width, height, duration)
    data = default_layout(width, height)
    data.update({"video": str(Path(video_path).resolve()), "sampling": src.mode, "frames_sampled": 0})

    # ---- pass 1: hotbar band median + small frames (letterbox) -----------------
    band_y = int(height * 0.70)
    top_y = int(height * 0.12)
    bands, halves, tops = [], [], []
    for _, frame in src:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        bands.append(gray[band_y:])
        tops.append(gray[:top_y])
        halves.append(cv2.resize(gray, (width // 2, height // 2), interpolation=cv2.INTER_AREA))
    if not bands:
        if verbose:
            print("Calibration: no frames could be read - using the default layout.")
        return data
    data["frames_sampled"] = len(bands)
    game = _game_rect(np.stack(halves), width, height)
    del halves
    if game != [0, 0, width, height]:
        game = _refine_game_rect(game, np.stack(tops), np.stack(bands), band_y, width, height)
    del tops
    data["game"] = game
    data["letterboxed"] = game != [0, 0, width, height]
    sub = bands[::max(1, len(bands) // config.CAL_MEDIAN_FRAMES)]
    median = np.zeros((height, width), np.uint8)
    median[band_y:] = np.median(np.stack(sub), axis=0).astype(np.uint8)
    k, score = gui.measure_gui_scale(median, game)
    if k is not None and game[3] < height:
        # windowed / letterboxed: the bottom edge can be a px off - let the hotbar fit settle it
        game[3] += _hotbar_dy(median, k, game)
        data["game"] = game
    del bands, sub
    if k is not None and score >= config.GUI_HOTBAR_MIN_SCORE:
        data["gui"] = {"k": k, "k_raw": k, "hotbar_score": round(score, 3), "source": "hotbar"}
        x = gui.HOTBAR_W / 2
        gcx = (game[0] + game[2]) / 2
        data["hotbar"] = [int(round(gcx - x * k)), int(round(game[3] - 22 * k)),
                          int(round(gcx + x * k)), game[3]]
    else:
        data["gui"]["hotbar_score"] = round(score, 3)
        data["gui"]["k"] = REF_K * (game[3] - game[1]) / 1080      # the default, scaled to the game view
        if verbose:
            print(f"Calibration: hotbar not found (best fit {score:.2f}) - assuming the tuning VOD's GUI scale.")
    data["strips"] = {}         # the tuning VOD's strips don't apply here; measured below
    lay = Layout(data)

    # ---- pass 2: per-frame screen type, statistics, panel/clock/toast evidence ------
    from .toasts import find_toasts
    screens = Counter()
    world_smalls, world_half = [], []
    acc_y = acc_w = acc_g = None
    n_text = 0
    keep_frames = []        # (t, frame) of world frames for clock reading
    strips_found = []
    toasts_seen = []
    every = max(1, len(src.times) // config.CAL_KEEP_FRAMES)
    for i, (t, frame) in enumerate(src):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, config.MOTION_SIZE, interpolation=cv2.INTER_AREA)
        screen, strip = classify_frame(frame, gray, lay, small)
        screens[screen] += 1
        if strip is not None:
            sx, sy = width / small.shape[1], height / small.shape[0]
            r = refine_strip(small, strip)
            strips_found.append((int(r[0] * sx), int(r[1] * sy), int(r[2] * sx), int(r[3] * sy)))
        for box in find_toasts(frame, lay):
            if box.full:
                toasts_seen.append(box)
        if screen != "world":
            continue
        world_smalls.append(small)
        world_half.append(cv2.resize(gray, (width // 2, height // 2), interpolation=cv2.INTER_AREA))
        y, w, g = colour_masks(frame)
        if acc_y is None:
            acc_y, acc_w, acc_g = (np.zeros(y.shape, np.uint16) for _ in range(3))
        acc_y += y
        acc_w += w
        acc_g += g
        n_text += 1
        if i % every == 0 or len(keep_frames) < 8:
            keep_frames.append((t, frame.copy()))
            if len(keep_frames) > config.CAL_KEEP_FRAMES:
                keep_frames = keep_frames[::2]
    data["screens_in_sample"] = dict(screens)

    if strips_found:
        data["strips"] = {n: dict(s, source="calibration") for n, s in cluster_strips(strips_found, width, height).items()}
    else:
        data["strips"] = {}
    lay = Layout(data)

    # ---- overlay mask -----------------------------------------------------------
    if len(world_smalls) >= config.CAL_MIN_WORLD_FRAMES:
        data["overlay_mask"] = overlay_mask(np.stack(world_smalls), np.stack(world_half), lay)
    elif verbose:
        print(f"Calibration: only {len(world_smalls)} world frames - keeping the hand-written overlay mask.")
    del world_smalls, world_half

    # ---- MCSR panel ----------------------------------------------------------------
    if n_text >= config.CAL_MIN_WORLD_FRAMES:
        panel = find_panel(acc_y / n_text, acc_w / n_text, acc_g / n_text, lay)
        data["panel"] = panel if panel else {"found": False}
    if data["panel"].get("found") and keep_frames:
        data["panel"] = refine_panel(data["panel"], keep_frames, Layout(data))
    # ---- match clock ----------------------------------------------------------------
    clock = find_clock(keep_frames, lay)
    data["clock"] = clock if clock else {"lines": [], "source": "not found"}
    # ---- toasts ---------------------------------------------------------------------
    full = [b for b in toasts_seen if b.window == "full"]
    data["toasts"] = {"seen": len(toasts_seen),
                      "k": round(float(np.median([b.k for b in full])), 3) if full else lay.k,
                      "right_x": int(np.median([b.x + b.w for b in full])) if full else None}
    data["calibration_s"] = round(time.time() - started, 1)
    if verbose:
        print(Layout(data).summary())
        print(f"  (calibration took {data['calibration_s']:.0f}s; sample screens {dict(screens)})")
    return data


def overlay_mask(smalls, halves, lay):
    """Overlay rectangles from temporal statistics of world frames (see module docstring)."""
    n, sh, sw = smalls.shape
    W, H = lay.w, lay.h
    s = smalls.astype(np.int16)
    # (a) static: unchanged while the world behind changed a lot
    d = np.abs(np.diff(s, axis=0))
    moved = (d > config.PIXEL_THRESHOLD).mean(axis=(1, 2)) >= config.OVERLAY_PAIR_MIN_CHANGE
    static = np.zeros((sh, sw), bool)
    if moved.sum() >= config.OVERLAY_MIN_PAIRS:
        unchanged = (d[moved] <= config.OVERLAY_STATIC_DIFF).mean(axis=0)
        static = unchanged >= config.OVERLAY_STATIC_SHARE
    # (b) frequent sharp text-like contrast (subtitles, chat, panels) at half resolution
    kern = np.ones((3, 3), np.uint8)
    pres = np.zeros(halves.shape[1:], np.float32)
    for g in halves:
        pres += (cv2.dilate(g, kern).astype(np.int16) - cv2.erode(g, kern)) >= config.OVERLAY_TEXT_CONTRAST
    pres /= len(halves)
    texty = cv2.resize((pres >= config.OVERLAY_TEXT_SHARE).astype(np.uint8), (sw, sh),
                       interpolation=cv2.INTER_AREA) > 0
    cand = (static | texty).astype(np.uint8)
    # keep the vanilla HUD (gameplay, not an overlay): hotbar/hearts/armour/food/XP, offhand, crosshair
    keep_out = np.zeros_like(cand)
    fx, fy = sw / W, sh / H
    for rect in [lay.gui_rect(-91 - 32, -config.DIM_HUD_GUI_H, 91 + 32, 0, ax="center", ay="bottom"),
                 lay.gui_rect(-10, -10, 10, 10, ax="center", ay="center")]:
        x0, y0, x1, y1 = rect
        keep_out[int(y0 * fy):int(np.ceil(y1 * fy)), int(x0 * fx):int(np.ceil(x1 * fx))] = 1
    cand[keep_out > 0] = 0
    # outside the game view (letterbox bars, title bar, taskbar): masked as whole bands below
    gx0, gy0, gx1, gy1 = lay.game
    inside = np.zeros_like(cand)
    m = 2                                     # + the blurred edge line (would join everything along it)
    ia, ib = int(gy0 * fy) + (m if gy0 > 0 else 0), int(np.ceil(gy1 * fy)) - (m if gy1 < H else 0)
    ja, jb = int(gx0 * fx) + (m if gx0 > 0 else 0), int(np.ceil(gx1 * fx)) - (m if gx1 < W else 0)
    inside[ia:ib, ja:jb] = 1
    cand[inside == 0] = 0
    ks = lay.k * fx                           # small px per GUI px
    r = max(1, int(round(config.OVERLAY_JOIN_GUI * ks)))
    joined = cv2.dilate(cand, np.ones((r, 2 * r + 1), np.uint8))
    nlab, _, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    rects = []
    min_area = (config.OVERLAY_MIN_GUI * ks) ** 2
    for i in range(1, nlab):
        x, y, w, h, area = (int(v) for v in stats[i])
        if w * h < min_area or cand[y:y + h, x:x + w].sum() < config.OVERLAY_MIN_PIXELS:
            continue
        rects.append([x / sw, y / sh, (x + w) / sw, (y + h) / sh])
    # the vanilla toast stack (toasts are short-lived, rarely frequent enough for (b))
    rects.append(list(lay.norm(lay.gui_rect(-160, 0, 0, config.OVERLAY_TOAST_SLOTS * 32, ax="right"))))
    rects = _merge_rects(rects)
    rects += [list(b) for b in ((0, 0, 1, gy0 / H), (0, gy1 / H, 1, 1), (0, 0, gx0 / W, 1), (gx1 / W, 0, 1, 1))
              if b[2] > b[0] and b[3] > b[1]]
    mask = np.zeros((sh, sw), bool)
    for x0, y0, x1, y1 in rects:
        mask[int(y0 * sh):int(np.ceil(y1 * sh)), int(x0 * sw):int(np.ceil(x1 * sw))] = True
    return {"rects": [[round(v, 4) for v in r] for r in rects], "coverage_pct": round(100 * float(mask.mean()), 1),
            "source": f"temporal statistics of {n} world frames", "world_frames": int(n),
            "static_pct": round(100 * float(static.mean()), 1), "text_pct": round(100 * float(texty.mean()), 1)}


def _merge_rects(rects):
    """Merge overlapping normalized rectangles until none overlap."""
    rects = [list(r) for r in rects]
    changed = True
    while changed:
        changed = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    rects[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del rects[j]
                    changed = True
                    break
            if changed:
                break
    return sorted(rects, key=lambda r: (r[1], r[0]))


def find_panel(py, pw, pg, lay):
    """Locate MCSR's panel from the static-text presence maps (yellow / white / grey)."""
    static = (py >= config.PANEL_STATIC_SHARE).astype(np.uint8)
    if static.sum() < 20:
        return None
    # join letters and words of one line, not neighbouring lines
    joined = cv2.dilate(static, np.ones((5, 31), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    best = None
    for i in range(1, n):
        x, y, w, h, _ = (int(v) for v in stats[i])
        ys, xs = np.nonzero(static[y:y + h, x:x + w] & (labels[y:y + h, x:x + w] == i))
        if len(xs) < 20:
            continue
        x0, x1, y0, y1 = x + xs.min(), x + xs.max() + 1, y + ys.min(), y + ys.max() + 1
        f_w = (x1 - x0) / CM_FONT_W
        f_h = (y1 - y0) / 7
        if not (config.PANEL_FONT_RANGE[0] <= f_w <= config.PANEL_FONT_RANGE[1]):
            continue
        if abs(f_h / f_w - 1) > config.PANEL_ASPECT_TOL:
            continue                       # not the 84 x 7 font-px shape of "Current Match"
        strength = float(py[y0:y1, x0:x1].mean())
        if best is None or strength > best[0]:
            best = (strength, x0, y0, x1, y1, f_w)
    if best is None:
        return None
    _, x0, y0, x1, y1, f = best
    anchor = "right" if (x0 + x1) / 2 > lay.cx else "left"
    edge = x1 if anchor == "right" else x0
    span = int(round(config.PANEL_LINE_W * f))
    xa, xb = (edge - span, edge) if anchor == "right" else (edge, edge + span)
    xa, xb = max(0, xa), min(lay.w, xb)

    def first_row(pmap, ya, yb, thr):
        ya, yb = max(0, int(ya)), min(lay.h, int(yb))
        rows = (pmap[ya:yb, xa:xb] >= thr).sum(axis=1)
        hit = np.flatnonzero(rows >= 3)
        return ya + int(hit[0]) if len(hit) else None

    # name (white, static all match) ~23 font px below "Current Match"; status (grey) ~10 below the name
    name_top = first_row(pw, y0 + 18 * f, y0 + 28 * f, config.PANEL_STATIC_SHARE)
    name_measured = name_top is not None and abs(name_top - (y0 + 23 * f)) <= 3 * f
    if not name_measured:
        name_top = int(round(y0 + 23 * f))
    status_top = first_row(pg, name_top + 6 * f, name_top + 15 * f, config.PANEL_STATUS_SHARE)
    if status_top is None or abs(status_top - (name_top + 10 * f)) > 3 * f:
        status_top = int(round(name_top + 9.9 * f))
    status_x = None
    if anchor == "left":
        ya, yb = int(status_top), int(status_top + 7 * f)
        cols = np.flatnonzero((pg[ya:yb, xa:xb] >= config.PANEL_STATUS_SHARE).sum(axis=0) >= 2)
        status_x = int(xa + cols[0]) if len(cols) else None
    return {"found": True, "anchor": anchor, "font_px": round(float(f), 3), "edge_x": int(edge),
            "top_y": int(y0), "current_match": [int(x0), int(y0), int(x1), int(y1)],
            "name_top": int(name_top), "name_measured": bool(name_measured),
            "status_top": int(status_top), "status_text_x": status_x,
            "strength": round(best[0], 3), "source": "calibration"}


def refine_panel(panel, frames, lay):
    """Fit the panel's font size, status row (and a left-aligned status text start) to the status templates.

    The "Current Match" width gives the font size to within a few %, but at
    ~2 px per font px the blurred end strokes vanish and it comes out small;
    the rows below it are only roughly 23 / 33 font px down (icons make the
    spacing vary a little). So: read the status box on the kept world frames
    for sizes around the estimate (then row offsets, then sizes again) and keep
    the setting whose best-template scores are highest (mean of the better half
    of frames - the panel is covered on some). (A left-aligned panel's status
    starts with an icon of varying width; the reader slides its templates over
    a range instead of fixing the start.)
    """
    from .opponent import PanelReader

    def trial_for(f, dy):
        t = dict(panel, font_px=float(f))
        rel = f / panel["font_px"]
        t["status_top"] = int(round(panel["top_y"] + (panel["status_top"] - panel["top_y"]) * rel + dy))
        if panel.get("name_measured"):
            # the name row was seen directly (static white text): keep it
            t["name_top"] = panel["name_top"]
        else:
            t["name_top"] = int(round(t["status_top"] - config.PANEL_NAME_ABOVE_STATUS * f))
        t["status_text_x"] = None
        return t

    def fit(t):
        reader = PanelReader(Layout(dict(lay.data, panel=t)))
        res = [reader.read_status(frame) for _, frame in frames]
        scores = sorted((r[1] for r in res), reverse=True)
        top = scores[:max(1, len(scores) // 2)]
        return float(np.mean(top)) if top else 0.0, res

    f0 = panel["font_px"]
    lo, hi, step = config.PANEL_REFINE_RANGE
    rels = np.arange(lo, hi + 1e-9, step)
    f_best = max((f0 * r for r in rels), key=lambda f: fit(trial_for(f, 0))[0])
    dys = np.arange(-2.0, 2.01, 0.5) * f_best
    dy_best = max(dys, key=lambda dy: fit(trial_for(f_best, dy))[0])
    f_best = max((f_best * r for r in np.arange(0.97, 1.031, 0.01)), key=lambda f: fit(trial_for(f, dy_best))[0])
    trial = trial_for(f_best, dy_best)
    mean, res = fit(trial)
    trial["fit_score"] = round(mean, 3)
    if trial["anchor"] == "left":
        # The status icon slot has a fixed width, so the text starts at a fixed x: measure
        # it (best-match positions of confident reads) and let the reader slide only a little.
        reader = PanelReader(Layout(dict(lay.data, panel=trial)))
        xs = []
        for _, frame in frames:
            st, score, margin, x = reader.read_status(frame, with_x=True)
            if score >= reader.min_score and margin >= config.OPPONENT_MIN_MARGIN:
                xs.append(x)
        if len(xs) >= config.PANEL_MIN_TEXT_X_READS:
            trial["status_text_x"] = int(round(float(np.median(xs))))
    trial["font_px"] = round(trial["font_px"], 3)
    return trial


# --- clock ---------------------------------------------------------------------------

TIME_RE = None


def _read_coloured_line(crop, colour, digits):
    """Read a coloured text line: pixels close to `colour` -> glyph reader -> text."""
    d = np.abs(crop.astype(np.int16) - np.array(colour, np.int16)).max(axis=2)
    mask = (d <= config.CLOCK_COLOUR_DIST) & (crop.max(axis=2) >= config.CLOCK_MIN_BRIGHT)
    _, glyphs = segment_line(mask)
    text = ""
    for g in glyphs:
        if g["gap"] >= 3:
            text += " "
        text += match_glyph(g["grid"], digits)[0]
    return text


def parse_clock_text(text):
    """'RTA: 11:57.554' / '00:47.92' -> ms or None (two-digit minutes, 2-3 decimals, at the line end)."""
    import re
    global TIME_RE
    if TIME_RE is None:
        TIME_RE = re.compile(r"(?:^|[: ?])(\d{2}):(\d{2})\.(\d{2,3})$")
    m = TIME_RE.search(text)
    if not m:
        return None
    minutes, seconds, frac = m.groups()
    if int(seconds) > 59:
        return None
    ms = int(frac) * (10 if len(frac) == 2 else 1)
    return (int(minutes) * 60 + int(seconds)) * 1000 + ms


def find_clock(frames, lay):
    """Coloured MM:SS.mmm lines that advance with the video -> {"lines": [...]} or None."""
    digits = load_glyph_templates()
    cands = []          # (t, box, colour, font_px, ms)
    for t, frame in frames:
        p = frame.astype(np.int16)
        mn, mx = p.min(axis=2), p.max(axis=2)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        coloured = (mx >= config.CLOCK_MIN_BRIGHT) & (mx - mn >= config.CLOCK_MIN_CHROMA) & shadow_near(gray)
        m8 = coloured.astype(np.uint8)
        joined = cv2.dilate(m8, np.ones((3, 15), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
        for i in range(1, n):
            x, y, w, h, _ = (int(v) for v in stats[i])
            if not (10 <= h <= 120 and w >= 3 * h):
                continue
            pad = max(2, h // 4)
            xa, ya, xb, yb = max(0, x - pad), max(0, y - pad), min(lay.w, x + w + pad), min(lay.h, y + h + pad)
            crop = frame[ya:yb, xa:xb]
            sel = m8[ya:yb, xa:xb] > 0
            if sel.sum() < 30:
                continue
            colour = np.median(crop[sel], axis=0).astype(int).tolist()
            text = _read_coloured_line(crop, colour, digits)
            ms = parse_clock_text(text.strip())
            if ms is not None:
                cands.append((t, (xa, ya, xb, yb), colour, (yb - ya - 2 * pad) / 7, ms))
    if not cands:
        return None
    # cluster by position
    clusters = []
    for c in cands:
        cx, cy = (c[1][0] + c[1][2]) / 2, (c[1][1] + c[1][3]) / 2
        for cl in clusters:
            if abs(cl["cx"] - cx) <= 40 and abs(cl["cy"] - cy) <= 0.5 * (c[1][3] - c[1][1]):
                cl["items"].append(c)
                break
        else:
            clusters.append({"cx": cx, "cy": cy, "items": [c]})
    lines = []
    for cl in clusters:
        items = cl["items"]
        offs = np.array([t - ms / 1000 for t, _, _, _, ms in items])
        med = float(np.median(offs))
        good = [it for it, o in zip(items, offs) if abs(o - med) <= config.CLOCK_CAL_MAX_DEV_S]
        if len(good) < config.CLOCK_CAL_MIN_READS or len(good) < 0.6 * len(items):
            continue
        box = [min(it[1][0] for it in good), min(it[1][1] for it in good),
               max(it[1][2] for it in good), max(it[1][3] for it in good)]
        colour = [int(np.median([it[2][j] for it in good])) for j in range(3)]
        fpx = float(np.median([it[3] for it in good]))
        # widen to the left (a longer time / label) and pad
        padx = int(round(4 * fpx))
        box = [max(0, box[0] - 6 * padx), max(0, box[1] - padx // 2), min(lay.w, box[2] + padx), min(lay.h, box[3] + padx // 2)]
        lines.append({"box": box, "color": colour, "font_px": round(fpx, 2), "reads": len(good),
                      "offset_s": round(float(np.median([t - ms / 1000 for t, _, _, _, ms in good])), 3),
                      "mask": "colour"})
    if not lines:
        return None
    lines.sort(key=lambda ln: -ln["reads"])
    lines = lines[:2]
    if len(lines) == 2 and abs(lines[0]["offset_s"] - lines[1]["offset_s"]) > config.CLOCK_LINES_MAX_DISAGREE_S:
        lines = lines[:1]              # two different clocks (e.g. IGT and RTA): keep the most readable
    lines.sort(key=lambda ln: ln["box"][1])
    return {"lines": lines, "source": "calibration"}


# ---------------------------------------------------------------------------------
# Contact sheet: draw the measured layout on frames of the video (for checking by eye)
# ---------------------------------------------------------------------------------

def draw_layout(video_path, data, out_path, width=960):
    """Save an image: a world frame with every measured box drawn, a resized frame with its
    strip, the overlay mask, and the text summary."""
    from .opponent import PanelReader
    from .runend import ResultDetector, dragon_boxes
    from .screens import structure_screen
    lay = Layout(data)
    src = FrameSource(video_path, lay.w, lay.h, 1e9)
    reader = PanelReader(lay) if lay.panel.get("found") else None
    world, resized, best = None, None, -1.0
    for _, frame in src:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        screen, strip = structure_screen(frame, gray, lay)
        if screen == "resized" and resized is None:
            resized = (frame.copy(), strip)
        if screen == "world":
            score = reader.read_status(frame)[1] if reader else 0.0
            if score > best:
                best, world = score, frame.copy()
    world = world if world is not None else np.zeros((lay.h, lay.w, 3), np.uint8)
    img = world.copy()
    over = img.copy()
    for x0, y0, x1, y1 in lay.overlay_rects():
        cv2.rectangle(over, (int(x0 * lay.w), int(y0 * lay.h)), (int(x1 * lay.w), int(y1 * lay.h)), (0, 0, 255), -1)
    img = cv2.addWeighted(over, 0.30, img, 0.70, 0)
    t = max(2, lay.h // 360)

    def box(r, colour, label=None):
        x0, y0, x1, y1 = (int(round(v)) for v in r)
        cv2.rectangle(img, (x0, y0), (x1, y1), colour, t)
        if label:
            cv2.putText(img, label, (x0 + 4, max(14, y0 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * lay.h / 540, colour, t)

    box(lay.game, (0, 255, 0))
    if data.get("hotbar"):
        box(data["hotbar"], (255, 255, 0), f"hotbar k={lay.k:.2f}")
    if reader:
        box(lay.panel["current_match"], (0, 255, 255), "Current Match")
        box(reader.name_box, (255, 255, 255), "name")
        box(reader.status_box, (180, 180, 180), "status")
    for i, ln in enumerate(lay.clock_lines, 1):
        box(ln["box"], (255, 0, 255), f"clock {i}")
    for r in lay.toast_search_regions():
        box(r, (0, 140, 255), "toasts")
    bar, label = dragon_boxes(lay)
    box(bar, (200, 0, 200), "boss bar")
    rd = ResultDetector(lay)
    box(rd.title_region, (0, 200, 255), "result title")
    for name, s in lay.strips.items():
        box(s["rect"], (255, 128, 0), f"strip {name}")
    tiles = [cv2.resize(img, (width, width * lay.h // lay.w), interpolation=cv2.INTER_AREA)]
    if resized is not None:
        rimg, strip = resized
        rimg = rimg.copy()
        sx, sy = lay.w / config.MOTION_SIZE[0], lay.h / config.MOTION_SIZE[1]
        cv2.rectangle(rimg, (int(strip[0] * sx), int(strip[1] * sy)), (int(strip[2] * sx), int(strip[3] * sy)),
                      (255, 128, 0), 2 * t)
        cv2.putText(rimg, "resized strip (this frame)", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, lay.h / 1080, (255, 128, 0), t)
        tiles.append(cv2.resize(rimg, tiles[0].shape[1::-1], interpolation=cv2.INTER_AREA))
    else:
        tiles.append(np.zeros_like(tiles[0]))
    mask = np.zeros(tiles[0].shape[:2], np.uint8)
    mh, mw = mask.shape
    for x0, y0, x1, y1 in lay.overlay_rects():
        mask[int(y0 * mh):int(y1 * mh), int(x0 * mw):int(x1 * mw)] = 255
    mimg = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    cv2.putText(mimg, f"overlay mask {(data.get('overlay_mask') or {}).get('coverage_pct', 0)}%", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    text = np.full_like(tiles[0], 32)
    for i, line in enumerate(Layout(data).summary().splitlines()):
        cv2.putText(text, line[:110], (8, 22 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (230, 230, 230), 1)
    sheet = np.vstack([np.hstack(tiles), np.hstack([mimg, text])])
    cv2.imwrite(str(out_path), sheet)
    return out_path
