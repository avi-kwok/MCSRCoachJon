"""Dimension changes: the nether-portal transition (portal overlay -> loading screen -> new world).

Every nether-portal trip in 1.16 looks the same on screen, whatever the time of
day, weather, biome or game language:

1. **Portal overlay** - while the player stands in a portal the whole game
   view is tinted with the swirling purple portal texture (~4 s before the
   teleport).
2. **Loading screen** - vanilla's "Loading terrain..." / "Downloading
   terrain..." screen (translated, e.g. "Laster terreng..." in Norwegian) is
   drawn on the options background: the 16x16 dirt texture, darkened to 25%
   (RGB ~31,22,17 on video) and tiled every **32 GUI px** across the whole
   window. It shows for 0.1-0.3 s (sometimes less than one 10 fps sample, when
   the destination chunks are already loaded).
3. **New dimension** - the first rendered frame after it (often just the sky
   colour before chunks appear). Answer-key convention: "first rendered frame
   after the loading screen".

CV ideas:

* **Loading screen = structure, not words.** A cheap colour gate (median
  colour of the window is the dark brown of the darkened dirt, with texture -
  not flat), then a **tiling test**: shrink the window so one 32-GUI-px tile
  becomes 16x16 px, cut it into tiles and compare every tile with the
  per-pixel median tile. On the loading screen the tiles agree (explained
  variance 0.91-1.0 on all four videos); on any other frame, including dark red
  or black ones, the score is <= 0.01. The GUI scale k comes from layout.json;
  inside a resized strip (whose GUI scale is unknown) the tile period is
  estimated from the image's own autocorrelation and then tested the same way.
* **Portal overlay** = share of saturated purple (hue 250-310 deg) pixels in the
  game view. Not used alone (nether portal blocks and purple wallpapers look
  the same) - splits.py only uses the end of a long overlay stretch as a
  candidate transition when the dimension evidence before and after differ.

The End is entered through an end portal: no overlay and (on these videos) no
loading screen - the End split comes from its toast and the End colours.
"""

import cv2
import numpy as np

from . import config

TILE = 16            # px per 32-GUI-px tile after shrinking (the dirt texture is 16x16 texels)


def fold_score(gray, period):
    """How well a grey image repeats with the given tile period (px): median over tiles of
    1 - (tile - median tile)^2 / variance. ~1 for a tiled background, <= 0 otherwise."""
    s = TILE / period
    small = cv2.resize(gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    h, w = small.shape
    ny, nx = h // TILE, w // TILE
    if ny < 2 or nx < 2 or ny * nx < config.LOADING_MIN_TILES:
        return 0.0
    a = small[:ny * TILE, :nx * TILE].reshape(ny, TILE, nx, TILE).transpose(0, 2, 1, 3).reshape(-1, TILE, TILE)
    med = np.median(a, axis=0)
    var = a.reshape(len(a), -1).var(axis=1)
    mse = ((a - med) ** 2).reshape(len(a), -1).mean(axis=1)
    return float(np.median(1 - mse / (var + med.var() + 1e-6)))


def _dirt_gate(bgr):
    """Cheap test: median colour = darkened dirt (dark, brown: R > G > B) and textured (not flat)."""
    px = bgr[::4, ::4].reshape(-1, 3).astype(np.float32)
    b, g, r = np.median(px, axis=0)
    lo, hi = config.LOADING_RED_RANGE
    if not (lo <= r <= hi and config.LOADING_RG_RANGE[0] <= r - g <= config.LOADING_RG_RANGE[1]
            and config.LOADING_GB_RANGE[0] <= g - b <= config.LOADING_GB_RANGE[1]):
        return False
    return float(px.mean(axis=1).std()) >= config.LOADING_MIN_STD


def _period_candidates(gray, n=3):
    """Strongest repeat periods (px) of a grey image from its 1-D autocorrelations (rows and columns)."""
    out = []
    for axis in (0, 1):
        prof = gray - gray.mean(axis=axis, keepdims=True)
        size = gray.shape[axis]
        f = np.fft.rfft(prof, n=2 * size, axis=axis)
        ac = np.fft.irfft(f * np.conj(f), axis=axis).sum(axis=1 - axis)[:size // 2]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        lo = max(8, int(32 * config.LOADING_STRIP_K_RANGE[0]))
        peaks = [i for i in range(lo, len(ac) - 1) if ac[i] >= ac[i - 1] and ac[i] >= ac[i + 1] and ac[i] > 0.1]
        out += sorted(peaks, key=lambda i: -ac[i])[:n]
    return sorted(set(out))


class LoadingDetector:
    """Is the vanilla dirt-background loading screen showing (full view or a resized strip)?"""

    def __init__(self, lay):
        self.lay = lay
        x0, y0, x1, y1 = (int(v) for v in lay.game)
        self.full = (x0, y0, x1, y1)
        self.strips = [tuple(int(v) for v in s["rect"]) for s in lay.strips.values()]
        # The tiling score drops to ~0.5 at 1% off the true period: try the measured k +-1.5%.
        # The exact period goes first: if even it scores ~0 (<= 0.01 on every non-loading frame
        # measured; >= 0.2 when k is 1.5% off) the region is rejected without the jitter.
        self.jitter = sorted(1 + np.arange(-0.015, 0.0151, 0.0025), key=lambda j: abs(j - 1))

    def _check_region(self, frame, rect, periods, min_score):
        """Best tiling score of a region; `periods` = candidate tile periods (px) or None (estimate them)."""
        x0, y0, x1, y1 = rect
        crop = frame[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0 or min(crop.shape[:2]) < 2 * TILE or not _dirt_gate(crop):
            return 0.0
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if periods is None:
            # Inside a resized strip the GUI scale is unknown: the tile period is the strongest
            # repeat of the image itself (autocorrelation), refined below.
            lo, hi = config.LOADING_STRIP_K_RANGE
            periods = [p for p in _period_candidates(gray) if 32 * lo <= p <= 32 * hi]
        best = 0.0
        for p in periods:
            for j in self.jitter:
                score = fold_score(gray, p * j)
                best = max(best, score)
                if best >= min_score or (j == 1.0 and score < config.LOADING_PROBE_MIN):
                    break
            if best >= min_score:
                break
        return best

    def check(self, frame, strip=None):
        """-> True if the loading screen shows in the full view or in a (known / current) strip."""
        if self._check_region(frame, self.full, [32 * self.lay.k], config.LOADING_MIN_SCORE) >= config.LOADING_MIN_SCORE:
            return True
        rects = list(self.strips) + ([tuple(int(v) for v in strip)] if strip is not None else [])
        for rect in rects:
            if self._check_region(frame, rect, None, config.LOADING_MIN_SCORE_STRIP) >= config.LOADING_MIN_SCORE_STRIP:
                return True
        return False


def portal_share(frame, lay):
    """Share of the game view tinted by the nether-portal overlay (saturated purple)."""
    x0, y0, x1, y1 = (int(v) for v in lay.game)
    step = max(1, (y1 - y0) // 90)
    small = frame[y0:y1:step, x0:x1:step]
    hsv = cv2.cvtColor(np.ascontiguousarray(small), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    hlo, hhi = config.PORTAL_HUE
    on = (h >= hlo) & (h <= hhi) & (s >= config.PORTAL_MIN_SAT) & (v >= config.PORTAL_MIN_VALUE)
    return float(on.mean())
