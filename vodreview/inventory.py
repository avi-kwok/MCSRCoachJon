"""get_inventory(t): a small PNG of the inventory/container panel last open at or before t.

`python -m vodreview inventory runs/<id> <m:ss.s> <out.png>`

Finds the latest `inventory` sample in samples.csv at or before t, seeks to it,
locates the light-grey container panel with the same structure test the
screen classifier uses (gui.container_panel, at the run's GUI scale) and saves
only that panel, scaled to config.INVENTORY_PX_PER_GUI screen px per GUI px
(a 176 x 166 inventory -> ~352 x 332 px): much cheaper for a coach than a full
get_frame. Prints the timestamp of the frame it used.
"""

from pathlib import Path

import cv2

from . import config, gui
from .layout import load_layout
from .report import read_samples_csv
from .video import read_frame_at


def _mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def panel_rect(frame, lay):
    """Screen rect (x0, y0, x1, y1) of the container panel, or the vanilla-sized centred box if not found."""
    k, game = lay.k, lay.game
    s = gui.shrink_factor(k)
    small = cv2.resize(frame, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else frame
    box = gui.container_panel(small, k * s, tuple(v * s for v in game))
    if box is not None:
        return tuple(int(round(v / s)) for v in box), True
    # fallback: 176 x 222 GUI px (tallest vanilla container) around the game centre
    return lay.gui_rect(-88, -111, 88, 111, ax="center", ay="center"), False


def get_inventory(run_dir, t, out_png, video=None):
    run_dir = Path(run_dir)
    samples = [s for s in read_samples_csv(run_dir / "samples.csv") if s.screen == "inventory" and s.time <= t + 1e-6]
    if not samples:
        raise SystemExit(f"No inventory screen at or before {_mmss(t)}.")
    ts = samples[-1].time
    if video is None:
        local = run_dir / "video.mp4"
        if local.is_file():
            video = local
        else:
            import json
            video = json.loads((run_dir / "run.json").read_text())["video"]
    frame = read_frame_at(video, ts)
    if frame is None:
        raise SystemExit("Could not read the frame.")
    lay = load_layout(run_dir)
    (x0, y0, x1, y1), found = panel_rect(frame, lay)
    pad = int(round(2 * lay.k))
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(frame.shape[1], x1 + pad), min(frame.shape[0], y1 + pad)
    crop = frame[y0:y1, x0:x1]
    f = config.INVENTORY_PX_PER_GUI / lay.k
    if f < 1:
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(out_png), crop)
    gap = t - ts
    print(f"Saved {out_png} ({crop.shape[1]}x{crop.shape[0]}): inventory screen at {_mmss(ts)}"
          + (f" ({gap:.1f}s before {_mmss(t)})" if gap > 0.05 else "")
          + ("" if found else " [panel not found: centred 176x222 GUI box]"))
    return ts
