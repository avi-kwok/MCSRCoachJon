"""Is the player standing on a nether fortress? (nether-brick floor under the player)

"Found Fortress" in this project = the first sustained moment the player is
standing on the fortress (its nether-brick floor / bridges), not the "A
Terrible Fortress" advancement, which can fire much later (tivesflow: on the
bridge at 5:40.4, toast at 6:20.9; the advancement tests the player's position
against the fortress pieces' bounding boxes, and a bridge or a pillar next to
one is not always inside them).

CV idea - colour of the ground right in front of the player's feet:

* Region: the middle third of the game view, from 62% of its height down to
  just above the vanilla HUD (hearts / food / XP / hotbar, 48 GUI px, measured
  with the layout's GUI scale). Looking forward or down, this is the floor the
  player stands on.
* Nether bricks (vanilla texture, average RGB ~44,22,27) are a dark maroon
  whose blue channel is a little *above* green: hue ~330-345 deg (OpenCV 163-172).
  Every other common nether floor is redder: netherrack (~97,39,39) and crimson
  nylium / nether wart (hue 350-360 deg, OpenCV 173-179 - measured on all four
  videos: netherrack 79-92% of its saturated pixels at 173-179, bricks 71-77% at
  166-172), blackstone / basalt are grey, soul sand / soil brown, warped
  blocks teal. Red nether bricks don't generate in 1.16.1 fortresses, and
  bastions are blackstone; nether fossils are bone blocks.
* `brick_shares` = share of region pixels with that hue, saturated (S >= 50)
  and not bright (V 12-140 - lit netherrack is brighter), in the floor region
  and in the upper middle of the view (10-40% of the height). A sample "stands
  on bricks" when the floor share is >= FORTRESS_MIN_SHARE and the upper share
  is below FORTRESS_WALL_MAX: a brick *wall* filling the whole view (pillaring
  up beside a fortress, nbb 3:19) is not a floor. splits.py then wants most
  samples of a FORTRESS_SUSTAIN_S window to agree (a few placed blocks or a
  glance at a wall flicker).

Measured (10 fps, world/F3 samples): before the first fortress the floor
share never stayed >= 0.5 for more than one sample on any of the four videos;
on the fortress floor it is 0.6-0.97 with the upper share <= 0.3.
"""

import cv2
import numpy as np

from . import config


def _share(frame, rect, h):
    xa, ya, xb, yb = rect
    crop = frame[max(0, int(ya)):int(yb), max(0, int(xa)):int(xb)]
    if crop.size == 0:
        return 0.0
    f = min(1.0, 180 / h)                   # shrink to a ~180-px-tall view (area average)
    if f < 1:
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hh, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    hlo, hhi = config.FORTRESS_BRICK_HUE
    vlo, vhi = config.FORTRESS_BRICK_VALUE
    on = (hh >= hlo) & (hh <= hhi) & (s >= config.FORTRESS_BRICK_MIN_SAT) & (v >= vlo) & (v <= vhi)
    return float(on.mean())


def brick_shares(frame, lay):
    """-> (floor share, upper share): nether-brick-coloured pixels in front of the feet and in the
    upper middle of the view (a brick *wall* filling the view - e.g. pillaring up next to a
    fortress - colours both; the floor of a bridge or courtyard only the lower one)."""
    x0, y0, x1, y1 = (float(v) for v in lay.game)
    w, h = x1 - x0, y1 - y0
    k = lay.k
    yb = y1 - (config.DIM_HUD_GUI_H + config.FORTRESS_HUD_GAP_GUI) * k
    ya = y0 + config.FORTRESS_REGION_TOP * h
    if yb - ya < config.FORTRESS_MIN_REGION_H * h:
        ya = yb - config.FORTRESS_MIN_REGION_H * h
    xa, xb = x0 + config.FORTRESS_REGION_X[0] * w, x0 + config.FORTRESS_REGION_X[1] * w
    ua, ub = config.FORTRESS_UPPER_Y
    ux0, ux1 = config.FORTRESS_UPPER_X
    floor = _share(frame, (xa, ya, xb, yb), h)
    upper = _share(frame, (x0 + ux0 * w, y0 + ua * h, x0 + ux1 * w, y0 + ub * h), h)
    return floor, upper
