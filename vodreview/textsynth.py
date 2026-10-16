"""Reading a line of Minecraft text by analysis-by-synthesis (small, blurred text).

The glyph reader (glyphs.py) cuts a line into glyphs by its column profile and
shrinks each to its font grid. That needs >= ~2.5 screen px per font px: below
it the 1-font-px gaps between letters blur shut and the cut fails (sable's
bottom-left panel: 2.45 px per font px - the opponent's name was never read).

Here nothing is cut. Minecraft text is fully determined by its characters:
each glyph is a known bitmap (font.py) with a known advance, so a candidate
glyph can be *rendered* at the measured font size - including the recording's
area-averaging downscale - and compared with the video. Reading = finding the
glyph sequence whose rendering explains the observed pixels best:

* Observation: the grey crop of the text row, high-passed (minus a Gaussian
  blur of ~2 font px) so the slowly varying world behind the panel drops out,
  scaled so the text's contrast is ~1.
* Model: observed ~ a * (rendered glyph, high-passed). For glyph c whose cell
  starts at font-px position p the gain over "no text there" is
  sum(2 a O T_c - a^2 T_c^2) over its cell's columns.
* Dynamic programming over positions on the font's own grid (font px) picks
  the best *contiguous* glyph sequence - glyph i+1 starts exactly advance(c_i)
  after glyph i - with free blank space before and after it. The sub-pixel
  phase of the grid and the row offset are searched.
* `fit` = normalised correlation of the whole rendered word with the
  observation over the word's span: a reading is only trusted when the
  synthetic word explains the pixels (opponent.py also wants the same name on
  several frames).
"""

import cv2
import numpy as np

from . import config
from .font import ROWS, advance, render

NAME_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"


def _highpass(img, font_px):
    sigma = max(1.0, config.SYNTH_HIGHPASS_FONT_PX * font_px)
    return img - cv2.GaussianBlur(img, (0, 0), sigma)


class SynthReader:
    def __init__(self, font, font_px, chars=NAME_CHARS):
        self.font = font
        self.f = float(font_px)
        self.chars = [c for c in chars if c in font]
        self.pad = int(np.ceil(3 * self.f)) + 2
        self._cache = {}
        q = config.SYNTH_SUBPX
        self.subs = np.arange(0, 1, q)

    def _render_hp(self, text, x_phase, y_phase, band_h, width):
        """High-passed rendering of `text` in band coordinates: cell starts at x = x_phase,
        cap top at y = y_phase; returns band_h x width."""
        pad = self.pad
        img = render(text, self.font, self.f, italic=False, shadow=False, pad=pad, x_phase=x_phase, y_phase=y_phase)
        if img is None:
            return None
        canvas = np.zeros((band_h + 2 * pad, max(img.shape[1], width + 2 * pad)), np.float32)
        h = min(img.shape[0], canvas.shape[0])
        canvas[:h, :img.shape[1]] = img[:h]
        return _highpass(canvas, self.f)[pad:pad + band_h, pad:pad + width]

    def _glyph(self, ch, x_phase, y_phase, band_h):
        key = (ch, round(x_phase, 3), round(y_phase, 3), band_h)
        g = self._cache.get(key)
        if g is None:
            w = int(np.ceil(advance(ch) * self.f + 1))
            g = self._cache[key] = self._render_hp(ch, x_phase, y_phase, band_h, w)
        return g

    def read(self, bgr, top_px):
        """Read the best contiguous word in a BGR crop of one text line.

        `top_px` = approximate cap-top row of the text in the crop (searched +-2.5 font px).
        Returns (text, fit); ("", -1) if nothing was found.
        """
        f = self.f
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        # Minecraft text here is white / grey: strongly coloured pixels (player-head icon, status
        # icon, coloured world) are replaced by their surroundings before high-passing.
        px = bgr.astype(np.int16)
        chroma = px.max(axis=2) - px.min(axis=2)
        smooth = cv2.GaussianBlur(gray, (0, 0), max(1.0, 2 * f))
        gray = np.where(chroma > config.SYNTH_MAX_CHROMA, smooth, gray)
        obs = _highpass(gray, f)
        H = obs.shape[0]
        band_h = int(np.ceil((ROWS + 1) * f)) + 1
        best = ("", -1.0)
        q = config.SYNTH_SUBPX
        for dy in np.arange(-2.5, 2.51, 0.5) * f:
            y = top_px + dy
            y0 = int(np.floor(y))
            if y0 < 0 or y0 + band_h > H:
                continue
            py = round((y - y0) / q) * q % 1.0
            band = obs[y0:y0 + band_h]
            scale = float(np.percentile(np.abs(band), 99)) or 1.0
            band = band / scale
            corr = self._correlations(band, py, band_h)
            for phase in np.arange(0, 1, config.SYNTH_PHASE_STEP):
                text, span = self._dp(corr, band.shape[1], phase * f)
                if text:
                    text, span = self._trim(band, text, span, phase * f, py, band_h)
                if text:
                    fit = self._fit(band, text, span, phase * f, py, band_h)
                    if fit > best[1]:
                        best = (text, fit)
        return best

    def _correlations(self, band, py, band_h):
        """{(ch, sub): (sum g*o for every x offset, sum g*g)} for every glyph and quantised sub-pixel phase."""
        out = {}
        for ch in self.chars:
            for sub in self.subs:
                g = self._glyph(ch, sub, py, band_h)
                if g.shape[1] > band.shape[1]:
                    continue
                c = cv2.matchTemplate(band, g, cv2.TM_CCORR)[0]
                out[(ch, sub)] = (c, float((g * g).sum()))
        return out

    def _gain(self, corr, ch, x):
        q = config.SYNTH_SUBPX
        x0 = int(np.floor(x))
        sub = round((x - x0) / q) * q
        if sub >= 1.0:
            x0, sub = x0 + 1, 0.0
        c = corr.get((ch, self.subs[int(round(sub / q))]))
        if c is None or x0 >= len(c[0]) or x0 < 0:
            return -np.inf
        amp = config.SYNTH_AMPLITUDE
        return 2 * amp * c[0][x0] - amp * amp * c[1]

    def _dp(self, corr, W, phase_x):
        f = self.f
        n = int((W - phase_x) / f)
        gains = {ch: np.array([self._gain(corr, ch, phase_x + p * f) for p in range(n)]) for ch in self.chars}
        best = np.full(n + 1, -np.inf)
        back = [None] * (n + 1)
        for p in range(1, n + 1):
            for ch in self.chars:
                s = p - advance(ch)
                if s < 0 or not np.isfinite(gains[ch][s]):
                    continue
                cont = np.isfinite(best[s]) and best[s] > 0
                cand = gains[ch][s] + (best[s] if cont else 0.0)
                if cand > best[p]:
                    best[p], back[p] = cand, (ch, s, cont)
        finite = np.where(np.isfinite(best), best, -1e18)
        end = int(np.argmax(finite))
        if finite[end] <= 0:
            return "", None
        text, p, start = "", end, end
        while back[p] is not None:
            ch, s, cont = back[p]
            text, start = ch + text, s
            if not cont:
                break
            p = s
        return text, (start, end)

    def _cells(self, text, p0):
        out, p = [], p0
        for ch in text:
            out.append((ch, p))
            p += advance(ch)
        return out

    def _trim(self, band, text, span, phase_x, py, band_h):
        """Drop glyphs at either end of the word that don't look like their rendering (icons, junk)."""
        cells = self._cells(text, span[0])
        f = self.f

        def local(ch, p):
            x = phase_x + p * f
            x0 = int(np.floor(x))
            g = self._glyph(ch, x - x0, py, band_h)
            w = min(g.shape[1], int(np.ceil(advance(ch) * f)))
            o = band[:, x0:x0 + w]
            if o.shape[1] < w or w == 0:
                return -1.0
            a, b = o - o.mean(), g[:, :w] - g[:, :w].mean()
            d = np.sqrt((a * a).sum() * (b * b).sum())
            return float((a * b).sum() / d) if d > 0 else -1.0

        while cells and local(*cells[0]) < config.SYNTH_MIN_GLYPH_FIT:
            cells.pop(0)
        while cells and local(*cells[-1]) < config.SYNTH_MIN_GLYPH_FIT:
            cells.pop()
        if not cells:
            return "", None
        ch, p = cells[-1]
        return "".join(c for c, _ in cells), (cells[0][1], p + advance(ch))

    def _fit(self, band, text, span, phase_x, phase_y, band_h):
        """Normalised correlation of the rendered word with the observation over its span."""
        f = self.f
        p0, p1 = span
        x = phase_x + p0 * f
        x0, x1 = int(np.floor(x)), int(np.ceil(phase_x + p1 * f))
        if x1 > band.shape[1] or x1 <= x0:
            return -1.0
        syn = self._render_hp(text, x - x0, phase_y, band_h, x1 - x0)
        if syn is None:
            return -1.0
        obs = band[:, x0:x1]
        a, b = obs - obs.mean(), syn - syn.mean()
        d = np.sqrt((a * a).sum() * (b * b).sum())
        return float((a * b).sum() / d) if d > 0 else -1.0
