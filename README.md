# MCSR Coach Jon

A personal coach that reviews and analyzes a user-given Minecraft speedrun (MCSR Ranked, 1.16.1) POV video through Computer Vision and integrated LLM for reasoning. Provides feedback (TBD) based on the run and the user's skill level. Named after the person who introduced me to MCSR and my MCSR coach - Jon

```bash
Current features:
- Identify idle time during run
- Identify dragon death, or match loss
```

## Setup

```bash
python3 -m venv .venv          # Python 3.11
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Full analysis: console report + out/samples.csv + out/idle.csv
python -m vodreview analyze "path/to/VOD.mkv" [--out DIR]

# Save one frame to check a result by eye
python -m vodreview frame "path/to/VOD.mkv" 02:20 frame.png
```

`samples.csv` has one row per analyzed frame up to the run end: `time_s, motion_pct, screen, still`
(`screen` is one of `world, resized, pause, settings, inventory, f3`).
`idle.csv` has one row per idle stretch: start/end (seconds and mm:ss) and duration.
The console report also prints `Run ended at mm:ss (reason)`.

## How it works

1. **Sample** ~10 frames per second (skipped frames are only `grab()`-ed, which is faster).
2. **Screen type** (`vodreview/screens.py`):
   - `resized` first, found by *geometry*: MCSR's resize macros (tall = eye measuring,
     thin = pie-chart reading, wide = planar view) put the game in a strip at fixed
     positions and show flat desktop wallpaper around it. Two areas that are outside
     the strip in every layout (top-right and bottom-right) must be flat — split into
     small tiles, ≥ 90% of tiles with brightness std dev < 4 — and at least one
     layout's strip border must show a brightness jump (so an all-black loading frame
     doesn't count). In normal gameplay those areas hold the timer panel and hotbar,
     so they are never flat.
   - otherwise template matching (`cv2.matchTemplate`) against the crops in
     `calibration/`: `pause`, `settings`, `inventory`, `f3`; nothing matched = `world`.
3. **Motion**: grayscale, shrink to 480x270, subtract the previous sample. A pixel
   "changed" if the difference is > `PIXEL_THRESHOLD`; motion = % of pixels changed.
   Overlay regions (timer panel, toasts, subtitles, status effects/Ninjabrain, chat)
   are masked out because they change without the player doing anything. When F3 is
   showing, its left and right text columns and the shift-F3 pie chart are masked too
   (fps, counters and the pie change every frame).
4. **Run end** (`vodreview/runend.py`) — analysis stops at the first of:
   - **dragon kill**: the "Ender Dragon" boss bar (top centre) is read by colour —
     bright magenta = health left, dark magenta = health lost. Once the bar has been
     seen with health, the dragon counts as killed when the bar stays empty for 1 s
     (it stays on screen, empty, during the ~10 s death animation) or disappears right
     after being ≤ 5% full. A bar that disappears while fuller (player out of range)
     is ignored. The white "Ender Dragon" label must be bright, because inventory/pause
     screens dim the HUD and make a full bar look empty.
   - **match result**: the grey "Match Winner:" line is found by template matching,
     then the title above it is read in HSV colour space — gold = **win**, red = **loss**.
   - **end of video** (forfeits, resets, cut recordings).

   After a dragon kill the video is read for up to 30 s more, only to find the result
   screen and record win/loss. Idle stretches and time per screen only cover samples
   before the run end.
5. **Idle rule**: a sample is *still* if motion < `MOTION_THRESHOLD` and the screen is
   `world`, `pause` or `f3` (inventory/settings/resized always count as active). A run
   of still samples lasting >= 3 s is an idle stretch; the whole run counts.

All thresholds, mask rectangles and detector regions are in `vodreview/config.py`.
A 21.6-minute 1080p60 VOD takes about 4.5 minutes to analyze on an Apple Silicon Mac.

## Known limitations

- Thresholds were tuned on a single VOD. Other recording setups (bitrate, resolution,
  GUI scale, resource packs, overlay layout) may need re-tuning and a new mask.
- The mask is a fixed set of rectangles for this streamer's layout; a webcam or a
  differently placed overlay would have to be added to `OVERLAY_MASK`.
- Anything moving in the world while the player stands still (mobs, lava, fire,
  particles, the dragon) adds motion, so some real idle time can be missed.
- No settings screen appears in the calibration VOD, so `settings` is never detected
  until templates are added to `calibration/settings/`.
- Particles, mobs, lava, fire or the dragon moving can push motion over the threshold
  while the runner is actually waiting, so real waits can be hidden (e.g. waiting in
  the End or next to lava).
- The resized check assumes MCSR's standard strip positions on a 16:9 recording and a
  wallpaper that is smooth (not a busy picture) and not pure black. A different window
  size or a textured wallpaper would need new `RESIZED_*` values.
- With F3 open, most of the screen is masked (only ~14% of pixels are left, mostly
  around the hotbar), so the motion signal is coarser there.
- **The dragon-kill rule was tuned on one kill only** (bed one-cycle in the test VOD,
  bar empties at 21:27). Other kill styles, a recording where the HUD is hidden (F1),
  or a different GUI scale are untested.
- The loss path (red title) is **unverified**: the test VOD is a win ("Victory!" in
  gold). The red hue range is a guess based on Minecraft's red text colour.
- Template matching assumes the default GUI scale used in this VOD.

## License

MIT — see [LICENSE](LICENSE).
