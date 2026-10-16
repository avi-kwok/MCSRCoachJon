"""Motion signal: how much of the picture changed since the previous sample?

CV idea: *frame differencing*. Subtract two grayscale frames pixel by pixel;
where nothing moved the difference is ~0, where something moved it is large.
Counting the pixels whose difference passes a threshold gives a simple
"how much changed" number. Turning the camera changes almost every pixel,
so mouse movement shows up as high motion; standing still gives ~0%.

Overlays that change on their own (timer, toasts, F3 debug text) are *masked*:
those pixels are simply left out of the count. The overlay rectangles come
from the video's layout.json (measured by layout.calibrate from temporal
statistics; the hand-written config.OVERLAY_MASK is only the fallback), the F3
columns from the GUI scale.
"""

import cv2
import numpy as np

from . import config


def build_mask(width, height, rectangles):
    """Boolean array, True = pixel is used for motion, False = masked overlay."""
    mask = np.ones((height, width), dtype=bool)
    for x0, y0, x1, y1 in rectangles:
        mask[int(y0 * height):int(y1 * height), int(x0 * width):int(x1 * width)] = False
    return mask


class MotionMeter:
    def __init__(self, lay):
        width, height = config.MOTION_SIZE
        overlays = lay.overlay_rects()
        self.mask = build_mask(width, height, overlays)
        # With F3 open we also hide its text columns and pie chart.
        self.f3_mask = build_mask(width, height, overlays + lay.f3_rects())
        self.previous = None

    def measure(self, gray_frame, f3_visible=False, small=None):
        """Return % of unmasked pixels that changed vs the previous call."""
        # Shrinking the frame (INTER_AREA = average neighbouring pixels) makes
        # it faster and also smooths out tiny compression noise.
        if small is None:
            small = cv2.resize(gray_frame, config.MOTION_SIZE, interpolation=cv2.INTER_AREA)
        if self.previous is None:
            self.previous = small
            return 0.0
        diff = cv2.absdiff(small, self.previous)
        self.previous = small
        mask = self.f3_mask if f3_visible else self.mask
        changed = (diff > config.PIXEL_THRESHOLD) & mask
        return 100.0 * changed.sum() / mask.sum()
