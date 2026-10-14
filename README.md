# MCSR Coach Jon

A personal coach that reviews and analyzes a user-given Minecraft speedrun (MCSR Ranked, 1.16.1) POV video through Computer Vision and integrated LLM for reasoning. Provides feedback (TBD) based on the run and the user's skill level. Named after the person who introduced me to MCSR and my MCSR coach - Jon

## Development Timeline

1.1 Idle detector
   Motion measurement, screen-type detection, run-end detection (boss bar + result screen).

1.2 UI 
   Local FastAPI + React site, Minecraft dirt theme: video player, Splits track, Detailed Segments track, feedback list.
   v1.2 adds the result-screen time reader and run naming (date + final time + Won/Lost).

**1.3 Ground truth + split detection (Current version)**
   Hand-labelled timeline of the test VOD.
   Detect the 7 splits: advancement pop-ups (toast box + title templates), dimension
   classification (colour statistics + F3 text), world-reset detection.

1.4. Opponent panel reading
   Read the opponent's current split from the MCSR panel; ahead/behind per split.

1.5. Detailed segment detection
   F3 coordinates, item recognition, HUD (hearts, hunger, pearl counts), cursor tracking.
   Optical flow for actions like bridging and pie-raying.

2.0 CV -> AI handoff 
   The AI receives the CV output and requests frames when unsure.
   Measure cost and accuracy against ground truth.

2.1 Feedback engine + Deploy!
   Tips tagged macro/micro x knowledge/mechanics, plus risk; built on given knowledge base.

3.0 Learned CV + polish
    Train  models (scene classifier, object detection), with F3 frames as free labels.
    Run history, starting analyses from the UI, other players' setups.


## Setup

```bash
python3 -m venv .venv          # Python 3.11
source .venv/bin/activate
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..   # review UI (Node 22)
```

`ffmpeg`/`ffprobe` must be on the PATH (or in `/opt/homebrew/bin`) to make the browser-playable video.

Website coming soon!

## Usage

```bash
# 1. Analyze a VOD into its own run folder (~5.5 min for a 21-min 1080p60 VOD)
python -m vodreview analyze "path/to/VOD.mkv" --out runs/my-run [--no-video]

# 2. Open the review UI at http://127.0.0.1:8000/
python -m vodreview serve [--runs runs/] [--port 8000]

# Rebuild analysis.json from the CSVs without re-running the CV pass (seconds, not minutes)
python -m vodreview rebuild-json runs/my-run

# Re-detect only the splits (toasts, dimension, resets) of an analyzed run, reusing the
# screen types in samples.csv (~3 min instead of a full analyze), and rebuild analysis.json
python -m vodreview splits runs/my-run [--video "path/to/VOD.mkv"]

# Add/refresh the final time + recording date of an already analyzed run
# (reads only the video tail after the run end, ~3 s) and rebuild analysis.json
python -m vodreview update-run runs/my-run [--video "path/to/VOD.mkv"]

# Save one frame to check a result by eye
python -m vodreview frame "path/to/VOD.mkv" 02:20 frame.png
```

`analyze` writes into the `--out` folder (default `out/`):

| File | Contents |
|---|---|
| `samples.csv` | one row per analyzed frame up to the run end: `time_s, motion_pct, screen, still, dimension, reset` (`screen` is one of `world, resized, pause, settings, inventory, f3`; `dimension` is `overworld, nether, end` or empty = unknown; `reset` = 1 while MCSR's reset-world dialog shows) |
| `toasts.csv` | one row per advancement-toast box seen (per sample): `time_s, window, slot, k, full, title, score` (`window` = full screen or the resized strip it sits in, `slot` = 0 for the top toast, `k` = screen px per GUI px, `full` = fully slid in, `title` = recognised advancement id or empty) |
| `idle.csv` | one row per idle stretch: start/end (seconds and mm:ss) and duration |
| `run.json` | run facts: source video path, duration, run end, end reason, result, final time (`final_time_ms`, `final_time_text`), `recording_date` + `date_source`, sample interval, analysis time |
| `analysis.json` | everything the UI shows (contract below) |
| `video.mp4` | the VOD remuxed for browsers (video stream copied, audio copied or re-encoded to AAC, `+faststart`); skipped with `--no-video` or when it is already newer than the source |

The console report also prints `Run ended at mm:ss (reason)`, every result-screen frame
the final-time reader looked at (what it read, and the consensus), and the recording date.

You can add one file by hand: `detailed_segments.csv` (see below).

### Review UI

Each subfolder of `runs/` with an `analysis.json` is a run; pick it in the header dropdown.
Runs are titled **recording date — result + final time**, e.g. `Oct 9, 2026 — Won 21:34.123`
("Won" in gold, "Lost" in red). A `~` before the date means it was estimated from the file
times (hover for where the date came from). Without a final time the run end (mm:ss) is shown;
without a result there is no Won/Lost word. The dropdown works with the keyboard (arrows,
Home/End, Enter, Esc). Newest recording first.

Under the video is the timeline, exactly as wide as the player so horizontal position =
video time:

- **Splits** track: the 7 MCSR macro splits (Overworld, Entered Nether, Found Bastion,
  Found Fortress, Finding Stronghold, Found Stronghold, Entered End), each labelled in its
  block. **The track is the split selector:** click a split to jump to its start and select
  it (highlighted, with a navy bar under it); click it again or press **Esc** to clear. While
  a split is selected, a **Stop at split end** checkbox appears at the right of the track's
  label row; it pauses playback at the split's end. The selection is kept in the page URL
  (`#run=<id>&split=<name>`), so a link opens straight on that split. Splits come from the
  split detector (see "Splits" under How it works); undetected splits are simply missing.
- **Detailed Segments** track: your own mini segments from `runs/<id>/detailed_segments.csv`
  (below). Neighbouring blocks alternate between two neutral block colours, the name is drawn
  inside when it fits, hover shows name, times and notes, click jumps to the start. The file is
  read on every page load, so edit it and refresh.

Click anywhere else on the timeline to seek. Time after the run end is hatched.

Below that is the **Feedback** list; click a card to jump to its moment. The card for the
moment under the playhead is highlighted.

### detailed_segments.csv

Optional, written by you, one row per segment, in `runs/<id>/`:

```csv
start,end,segment,notes
0:00,0:41,Spawn & wood,Punched 2 trees then crafted a table
00:41,1:58.5,Village loot,"Bell + 2 houses, slow chest route"
222,330,Nether entry,plain seconds work too
```

- `start` / `end`: `mm:ss`, `m:ss`, `mm:ss.s` (`h:mm:ss` also works) or plain seconds, in
  **video time** (what the player shows).
- `segment`: the name shown on the block; `notes`: optional, shown in the tooltip.
  Quote a field that contains a comma.
- A row with a bad time, no name, or `end` <= `start` is skipped; the server prints a
  warning (`Warning (<run>): detailed_segments.csv line N: ...`) and still serves the rest.

Dev mode (hot reload) uses two terminals:

```bash
python -m vodreview serve --port 8000     # API
cd web && npm run dev                     # UI at http://localhost:5173, /api proxied to :8000
```

The server only binds to `127.0.0.1`. There is no upload endpoint; runs are created with `analyze`.

### analysis.json (version 1)

```json
{
  "version": 1,
  "run": {"video": "/abs/path/VOD.mkv", "video_file": "video.mp4", "duration_s": 1299.4,
          "run_end_s": 1287.0, "end_reason": "dragon kill, result screen at 21:37: win",
          "result": "win", "final_time_ms": 1294123, "final_time_text": "21:34.123",
          "recording_date": "2026-10-11T20:00:41-07:00", "date_source": "estimated",
          "analyzed_at": "2026-10-14T07:00:00+00:00"},
  "splits":   [{"name": "entered_nether", "start_s": 322.9, "end_s": 353.9, "source": "cv",
                "evidence": "'We Need to Go Deeper' toast from 5:22.9 (read 27x, ...)"}],
  "advancements": [{"name": "stone_age", "title": "Stone Age", "t_s": 31.9}],
  "segments": [{"name": "inventory", "start_s": 27.8, "end_s": 29.4, "source": "cv"}],
  "screens":  [{"start_s": 0.0, "end_s": 27.8, "screen": "world"}],
  "idle":     [{"start_s": 0.0, "end_s": 0.0, "duration_s": 0.0}],
  "tips":     [{"t_s": 237.6, "end_s": 253.4, "kind": "stat", "title": "Inventory open 3:03 (14.2%)",
                "text": "Inventory open for 3:03 (14.2% of the run) across 60 visits; longest 0:16 at 3:58.",
                "est_loss_s": null}]
}
```

- `run.result` is `"win"`, `"loss"` (read from the MCSR result screen) or `null` if no result screen was seen.
- `run.final_time_ms` / `run.final_time_text`: the time in parentheses on the result screen,
  as milliseconds and `"MM:SS.mmm"`; both `null` if it couldn't be read. **On a loss the
  result line names the winner, so this is the winner's time**; `result` says which it was.
- `run.recording_date`: ISO date-time in local time (or `null`); `run.date_source` says where it
  came from: `tag`, `filename`, `file_times` or `estimated` (see "Recording date" below).
- `GET /api/runs/{id}` adds `detailed_segments: [{"name", "start_s", "end_s", "notes"}]` from
  `detailed_segments.csv` (`[]` without the file). It is not stored in analysis.json.
- `GET /api/runs` returns per run: `id, video_name, result, run_end_s, final_time_text,
  final_time_ms, recording_date, date_source, analyzed_at, has_video`.
- `screens`: contiguous runs of the per-sample screen type up to the run end (used for the
  stat tips; not drawn as a timeline track). Runs shorter than 0.5 s
  are flicker and are absorbed into the longer neighbour.
- `splits`: the detected MCSR macro splits, in time order. `name` is one of `overworld`,
  `entered_nether`, `found_bastion`, `found_fortress`, `finding_stronghold`, `found_stronghold`,
  `entered_end`. A split runs from its start to the next detected split's start (the last one to
  the run end); a split that wasn't detected is left out (never guessed). `evidence` says which
  signal found it. The UI treats a missing `splits` key as `[]`.
- `advancements`: every advancement toast whose title was recognised, with the time it first
  appeared (all worlds, including ones abandoned by a reset). For future detailed segments.
- `segments`: CV-derived named time ranges: each non-world screen run >= 1 s (named after the
  screen) and the idle stretches (`"idle"`), all `"source": "cv"`. Kept for analysis/tips; the
  UI no longer draws them (the Detailed Segments track shows your CSV instead).
- `idle`: the idle stretches (same as `idle.csv`).
- `tips`: the feedback list, in display order. `kind` is `stat | micro | macro | risk`; `t_s`/`end_s`
  is the moment the card jumps to / highlights; `est_loss_s` is the estimated time lost, or `null`.
  v1 tips are rule-based and factual: the run end, an idle summary, one stat per screen type
  (time, % of run, visits, longest visit) and one per idle stretch.

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
5. **Final time** (`vodreview/finaltime.py`, `vodreview/glyphs.py`) — a tiny classical OCR.
   Minecraft's font is a fixed bitmap font, so on the result-screen frames (found by the
   "Match Winner:" template above) the text row right of the label is **thresholded** (light,
   unsaturated pixels that have the font's dark drop shadow down-right), **segmented** into
   glyphs by a column projection (Minecraft leaves one empty font pixel between characters),
   each glyph is **shrunk to its font-pixel grid** (5x7 for digits; the pixel size is the line
   height / 7, so GUI scale and recording resolution don't matter) and **matched** cell by cell
   against `calibration/glyphs/`. The `(MM:SS.mmm)` is checked by regex and range (<= 59:59.999
   and <= video length + 60 s); the result screen is read on several frames (about 3 s, every
   2nd frame) and the majority wins. On the test VOD: 9 of 9 readable frames give `21:34.123`.
6. **Recording date** (`vodreview/recdate.py`), first that applies:
   1. `creation_time` tag in the container (format or stream) -> `tag`;
   2. OBS's default file name `YYYY-MM-DD HH-MM-SS` anywhere in the name -> `filename`;
   3. the file's birth time, if `mtime - birth time` is within 15% of the video duration
      (a live recording is written for the whole match) -> `file_times`;
   4. otherwise the birth time anyway -> `estimated` (the file was copied/moved, so this is
      the copy date). The test VOD has no tag and was copied (written in 42 s for a
      21.6-min video), so it is `estimated` (Oct 11; the match was ~Oct 9).
7. **Splits** (`vodreview/toasts.py`, `vodreview/dimension.py`, `vodreview/splits.py`):
   - **Advancement toasts.** A 1.16 toast is a 160x32 GUI-pixel box with a perfectly flat
     dark-grey fill (RGB 31,31,31) in the top-right corner of the game window. Every sample,
     pixels of exactly that colour are keyed out of the top-right area, holes left by the text
     are closed (morphological closing), and connected blobs are kept if they look like a toast:
     wide, clean fill rows at the top, the light-grey frame line right below. The blob height
     gives the GUI scale, so the same code finds toasts at full screen (1 GUI px = 4.5 screen px
     here) *and* inside MCSR's resized strips (0.73 px), and tells fully shown toasts from ones
     still sliding in (narrower). A fully shown toast is cut out, resized to its 160x32 GUI grid
     and the start of its title row (GUI x 25-68, ~8 characters - the streamer's RTA timer
     overlay covers the rest of the top slot) is compared with the title templates in
     `calibration/toasts/` by normalised cross-correlation. Right titles score >= 0.86 at full
     size (~0.76 in the thin strip), wrong ones <= 0.67.
     *Why templates instead of the glyph reader:* the title is partly covered by the timer
     overlay and, in resized strips, a font pixel is < 1 screen pixel - too small to segment
     letters - while a whole-word template still correlates; we only need to tell ~15 known
     titles apart, not read arbitrary text.
   - **Toast timing.** Observations in the same toast slot that follow each other are one toast;
     its time is its *first* observation (the toast appears within ~0.5 s of the event), even if
     the title only became readable later - e.g. "We Need to Go Deeper" popped up while the
     runner was in the thin strip and was read at full size 2.5 s later. full -> sliding ->
     full in one slot starts a new toast. Splits: "We Need to Go Deeper" = Entered Nether,
     "Those Were the Days" = Found Bastion, "A Terrible Fortress" = Found Fortress, "Eye Spy" =
     Found Stronghold, "The End?" = Entered End. Other recognised toasts go to `advancements`.
   - **Dimension** per `world`/`f3` sample: with F3 open, the dimension word on the 9th F3 line
     ("minecraft:the_nether" / "overworld") is template-matched. Otherwise colour statistics of
     the shrunk frame (HUD, held items and overlays masked) in HSV: nether = saturated red
     (netherrack, crimson, nether bricks; hue 0-4/172-179, which leaves out orange terracotta and
     lava) or teal (warped forest, soul sand valley); End = dark purple sky *and* pale-yellow end
     stone; overworld = blue sky/water or green, with no nether colours. Anything else is unknown
     (caves, dark rooms). The labels are smoothed by a 6 s sliding majority and stays < 8 s are
     dropped. **Finding Stronghold** = the first sustained nether -> overworld change after the
     fortress (bastion / nether entry if those are missing) - the "blind" travel. Nether and End
     entries come from their toasts; the dimension change is the fallback when the toast was
     never read, and is shown as a cross-check in `evidence`.
   - **World resets**: MCSR's "Are you sure you want to reset this world?" dialog (template in
     `calibration/reset/`), or an advancement earned a second time (each can only be earned
     once per world). Only toasts after the last reset count for splits. On the test VOD the
     dialog shows at 2:20.8-2:21.1 and Stone Age / Acquire Hardware / Isn't It Iron Pick repeat.
   - **Overworld** starts at 0:00: the MCSR match timer keeps running across a seed reset, so the
     time on the abandoned seed is part of the overworld split.
   - Splits that contradict the run order (e.g. Found Stronghold before Entered Nether) are
     dropped. Bastion and fortress may come in either order.

   On the test VOD all 7 splits are found; detected vs. match data (+~3 s video offset):
   Entered Nether 5:22.9 (5:23), Found Bastion 5:53.9 (5:54), Found Fortress 9:52.9 (9:53),
   Finding Stronghold 15:10.9 (15:11), Found Stronghold 18:49.4 (18:50), Entered End 19:48.3 (19:48).
8. **Idle rule**: a sample is *still* if motion < `MOTION_THRESHOLD` and the screen is
   `world`, `pause` or `f3` (inventory/settings/resized always count as active). A run
   of still samples lasting >= 3 s is an idle stretch; the whole run counts.

All thresholds, mask rectangles and detector regions are in `vodreview/config.py`.
A 21.6-minute 1080p60 VOD takes about 5.5 minutes to analyze on an Apple Silicon Mac
(the split signals add ~6 ms per sample: toast search ~3 ms, dimension ~1 ms, reset dialog ~1.5 ms).

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
- Template matching assumes the default GUI scale used in this VOD.


## License

MIT — see [LICENSE](LICENSE).
