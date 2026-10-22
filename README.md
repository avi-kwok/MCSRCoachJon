# MCSR Coach Jon

A personal coach that reviews and analyzes a user-given Minecraft speedrun (MCSR Ranked, 1.16.1) POV video through Computer Vision and integrated LLM for reasoning. Provides feedback (TBD) based on the run and the user's skill level. Named after the person who introduced me to MCSR and my MCSR coach - Jon

## Development Timeline

1.1 Idle detector
   Motion measurement, screen-type detection, run-end detection (boss bar + result screen).

1.2 UI 
   Local FastAPI + React site, Minecraft dirt theme: video player, Splits track, Detailed Segments track, feedback list.
   v1.2 adds the result-screen time reader and run naming (date + final time + Won/Lost).

1.3 Ground truth + split detection
   Hand-labelled timeline of the test VOD.
   Detect the 7 splits: advancement pop-ups (toast box + title templates), dimension
   classification (colour statistics + F3 text), world-reset detection.

1.4 Opponent panel reading
   Read the opponent's status and name from the MCSR panel, and the match clock to align video time with match time; ahead/behind per split.
   1.1-1.4 hardened for other players' setups: per-video auto-calibration (`layout.json`: GUI
   scale, overlay mask, panel/clock/strip positions) and language-free detectors (GUI structure,
   toast icons, digits)

1.5 Fundamental readers **(In progress)**
   Auto-calibrated building blocks for bastion routes and mistake detection:
    1. F3 coordinates over time (position, height, facing, dimension, biome - done: `f3.csv`,
   analysis.json `state`) 
    2. HUD reading (pearl and item counts)
    3. Optical flow (camera and movement).

2.0 CV -> AI handoff 
   The AI receives the CV output and requests frames when unsure.
   Measure cost and accuracy against ground truth.

2.1 Feedback engine + Deploy!
   Tips tagged macro/micro x knowledge/mechanics, plus risk; built on given knowledge base.

3.0 Learned CV + polish
    Train  models (scene classifier, object detection), with F3 frames as free labels.
    Run history, starting analyses from the UI, other players' setups.


## Setup

Website coming soon!

## Usage

`analyze` writes into the `--out` folder (default `out/`):

| File | Contents |
|---|---|
| `layout.json` | the video's measured layout (auto-calibration, see "How it works" 0): GUI scale `gui.k`, game view rectangle, overlay-mask rectangles + coverage, MCSR panel position / alignment / font size, match-clock line boxes + colours, resized strips (`strips` from the calibration sample, `strips_analysis` from the full pass), toasts seen. Every detector reads it |
| `samples.csv` | one row per analyzed frame up to the run end: `time_s, motion_pct, screen, still, dimension, reset, dim_src, loading, brick, brick_up, portal` (`screen` is one of `world, resized, pause, settings, inventory, f3`; `dimension` is `overworld, nether, end` or empty = unknown, `dim_src` = `f3` / `colour` (where it came from); `reset` = 1 while MCSR's reset-world dialog shows; `loading` = 1 on the vanilla dirt loading screen of a portal trip; `brick` / `brick_up` = share of nether-brick colour in the floor in front of the feet / the upper middle of the view; `portal` = share of the view under the purple portal overlay) |
| `toasts.csv` | one row per advancement-toast box seen (per sample): `time_s, window, slot, k, full, title, score, icon, icon_score` (`window` = `full` or the resized strip it sits in (`current` = a strip not in layout.json), `slot` = 0 for the top toast, `k` = screen px per GUI px, `full` = fully slid in, `title` = advancement read by the English title template or empty, `icon` = item recognised from the toast's icon or empty) |
| `opponent.csv` | one row per read of MCSR's opponent panel (every 0.5 s up to the run end): `time_s, status, score, margin, name` (`status` = best-matching status template id, e.g. `entered_bastion`, empty if the panel showed no grey text; `score` = its correlation, `margin` = lead over the runner-up; `name` = opponent name read on that frame, empty if not readable) |
| `clock.csv` | one row per match-clock line read (the lines found by calibration) (same samples): `time_s, line, text, clock_ms` (`line` = `rta1`/`rta2`, `text` = raw glyph read, `?` = unknown glyph; `clock_ms` = parsed match clock or empty) |
| `f3.csv` | one row per `f3` sample (F3 debug screen open): `time_s, x, y, z, bx, by, bz, yaw, pitch, dim, biome, confidence, flags, facing, towards, chunk, raw` (XYZ position, Block line, yaw/pitch, `dim` = overworld/nether/end from the dimension line, `biome` = 1.16 biome id; empty = not read; `confidence` = lowest glyph match score of the XYZ + Block lines; `flags` = failed self-consistency checks (`no_xyz`, `no_block`, `block_mismatch`, `chunk_mismatch`, `y_range`, `speed`, `facing_mismatch`) plus `teleport` (an ender-pearl-like jump, kept); `facing` = direction word, `towards` = `+X`/`-Z`..., `chunk` = the Chunk line; `raw` = the read XYZ / Block / Chunk text for flagged rows) |
| `idle.csv` | one row per idle stretch: start/end (seconds and mm:ss) and duration |
| `run.json` | run facts: source video path, duration, run end, end reason, result, final time (`final_time_ms`, `final_time_text`), `recording_date` + `date_source`, sample interval, analysis time |
| `analysis.json` | everything the UI shows (contract below) |
| `video.mp4` | the VOD remuxed for browsers (video stream copied, audio copied or re-encoded to AAC, `+faststart`); an H.264 `.mp4` source with AAC/MP3 audio is not copied but **hard-linked** (symlink if on another disk, copy as a last resort); skipped with `--no-video` or when it is already up to date |

The console report also prints `Run ended at mm:ss (reason)`, every result-screen frame
the final-time reader looked at (what it read, and the consensus), and the recording date.

You can add one file by hand: `detailed_segments.csv` (see below).

### Review UI

Each subfolder of `runs/` with an `analysis.json` is a run; pick it in the header dropdown.
Runs are titled **recording date — result + final time**, e.g. `Oct 9, 2026 — Won 21:34.123`
("Won" in gold, "Lost" in red). A muted **est.** after the date means it was estimated from the file
times (hover for where the date came from). Without a final time the run end (mm:ss) is shown;
without a result there is no Won/Lost word. The dropdown works with the keyboard (arrows,
Home/End, Enter, Esc). Newest recording first.

Under the video is the timeline, exactly as wide as the player so horizontal position =
video time:

- **Splits** track: the 7 MCSR macro splits (Overworld, Entered Nether, Found Bastion,
  Found Fortress, Finding Stronghold, Found Stronghold, Entered End), each labelled in its
  block (a short name such as *Nether* or *Blind* when the full one doesn't fit, no label in
  very short blocks; hover shows the full name and times). **The track is the split selector:** click a split to jump to its start and select
  it (highlighted, with a navy bar under it); click it again or press **Esc** to clear. While
  a split is selected, a **Stop at split end** checkbox appears at the right of the track's
  label row; it pauses playback at the split's end. The selection is kept in the page URL
  (`#run=<id>&split=<name>`), so a link opens straight on that split. Splits come from the
  split detector (see "Splits" under How it works); undetected splits are simply missing.
  In a ranked match with a detected opponent, the label row reads **vs <name>** (**vs Opponent**
  when the name couldn't be read) and the
  opponent's splits are small red flags on the track (hover for split and time, click to jump
  there). A split's tooltip shows how far ahead or behind you were when the opponent reached the
  same split: `You −8.1s` (ahead, green) / `You +12.3s` (behind, red) = your split start minus
  their split time.
- **Answer Key** track (only when `runs/<id>/truth.csv` exists), directly under Splits: a gold
  tick per answer-key split, with a coloured square for how close the detected split is (green
  |Δ| ≤ 1 s, yellow ≤ 3 s, red more or not detected). Hover shows `truth · detected (Δ)`; click
  jumps to the answer-key time so you can check the frame. The label row shows `(draft — verify)`
  while `meta,status` is `draft`, plus a summary (`N/M within 1s · k missed · j extra · final ✔/✘`).
  The opponent's answer-key splits are hollow red flags at the bottom of the Splits bar.
- **Detailed Segments** track: your own mini segments from `runs/<id>/detailed_segments.csv`
  (below). Neighbouring blocks alternate between two neutral block colours, the name is drawn
  inside when it fits (never cut off), hover shows name, times and notes, click jumps to the start. The file is
  read on every page load, so edit it and refresh.

Click anywhere else on the timeline to seek. Time after the run end is hatched.

Below that is the **Feedback** list; click a card to jump to its moment. The card for the
moment under the playhead is highlighted.

### Accuracy check (`evaluate`)

`python -m vodreview evaluate [runs/] [--tolerance 1.0] [--opp-tolerance 3.0]` scores every run
folder that has both `analysis.json` and a hand-made answer key `truth.csv`
(`kind,name,time,notes`; kind = split | final | opponent | meta; times are VIDEO time m:ss.s).
Per split it prints the signed error (detected − truth, s): within tolerance = hit, `!` = outside,
`MISS` = not detected, `FP` = detected but not in the key; final time must match to the ms, result
must match. Opponent splits use a looser default tolerance (3 s) because the panel is sampled every
0.5 s. Truth rows whose notes start with "uncertain" are reported separately; a blank time means
"unknown, don't score". Keys with a `meta,status,draft` row are flagged as unverified (`*`).
Numbers are also written to `runs/evaluation.json`.

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
                "est_loss_s": null}],
  "opponent": {"name": "primeord",
               "splits":   [{"name": "found_bastion", "t_s": 173.0, "raw": "Entered Bastion",
                             "latency_s": 6.0, "source": "cv"}],
               "statuses": [{"raw": "Entered Bastion", "t_s": 173.0, "latency_s": 6.0}]},
  "match_clock": {"offset_s": 2.455, "spread_s": 0.012, "reads": 2118},
  "state": {"source": "f3", "reads": 1321, "valid": 1285,
            "points": [{"t_s": 1024.7, "x": -52.9, "y": 40.0, "z": -269.33, "yaw": 115.6, "pitch": 69.3,
                        "dim": "nether", "biome": "nether_wastes"}],
            "checks": {"block": {"checked": 1286, "passed": 1286}, "chunk": {...}, "facing": {...},
                       "y": {...}, "speed": {...}},
            "portal_pairs": [...], "dimension_agreement": {"compared": 1272, "agree": 1272},
            "at_splits": [...]}
}
```

- `run.result` is `"win"`, `"loss"`, `"draw"` (read from the MCSR result screen; a draw has no time) or `null` if no result screen was seen.
- `run.private_room` is `true` / `false` from the MCSR panel's mode line ("Private Room" / "Ranked Mode", MCSR's own English text, templates in `calibration/panel/`), or `null` if not found. The UI shows a draw as "Forfeit" plus a "Private room" tag.
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
  signal found it. `found_fortress` also carries `official_s`: the time of the "A Terrible
  Fortress" advancement toast (our split starts when the player first stands on the fortress, see
  How it works 7; the opponent panel uses MCSR's own, advancement-based definition). The UI treats
  a missing `splits` key as `[]`.
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

- `opponent`: the opponent's progress read from MCSR's panel (`null` for runs analyzed before
  v1.4 that never had `python -m vodreview opponent` run on them). The UI hides opponent markers when it is `null`.
  - `name`: the opponent's name, or `null` if it couldn't be read reliably (see limitations).
  - `statuses`: every status change on the panel, in time order: `raw` = the panel text
    (`Started Match`, `Entered Nether`, `Entered Bastion`, `Entered Fortress`, `Finding Stronghold`,
    `Found Stronghold`, `Entered The End`), `t_s` = **video** seconds of the first confident sighting
    of the new status, `latency_s` = time since the previous confident read: the change really
    happened in `[t_s - latency_s, t_s]` (large when the panel was covered).
  - `splits`: the statuses mapped to our split names (`overworld`, `entered_nether`,
    `found_bastion`, `found_fortress`, `finding_stronghold`, `found_stronghold`, `entered_end`),
    first occurrence of each, with the same `t_s`/`latency_s` and the `raw` text; `source` is `"cv"`.
    MCSR's "Entered Bastion"/"Entered Fortress" = our found bastion/fortress. The opponent's
    deaths are not shown on the panel, so they are not in here.
- `match_clock`: `offset_s` = video time - match time (the panel's `RTA:` clock), so
  `match = video - offset_s`; `spread_s` = standard deviation of the per-sample offsets; `reads` =
  samples used. All `null`/0 if the clock was never read. `null` (the whole object) like `opponent`.
- `state`: the game state read from the F3 screen (`null` without `f3.csv` - runs analyzed before
  1.5 until `python -m vodreview f3` is run). `reads` = F3 samples read, `valid` = reads that pass
  every position check (How it works 10). `points` = the valid reads thinned to <= 5 per second
  (`t_s`, `x/y/z` rounded to 0.01, `yaw`/`pitch` (`null` if the Facing line wasn't read or failed its
  check; `pitch` alone can be `null` when the right column covers it), `dim`, `biome`, and
  `"teleport": true` on the first read after a pearl-like jump); f3.csv keeps every read.
  `checks` = per check how many reads it applied to and passed; `portal_pairs` = overworld / 8 vs
  nether position around each portal transition with F3 reads on both sides; `at_splits` = the
  valid read nearest each split start (<= 30 s) with its dimension check;
  `dimension_agreement` = F3 dimension vs samples.csv's per-sample dimension label.

## How it works

0. **Auto-calibration → `layout.json`** (`vodreview/layout.py`, `vodreview/gui.py`). Players
   record at different resolutions, use different GUI scales, put MCSR's panel and their timer
   in different corners and add their own overlays, so nothing below uses fixed 1080p
   coordinates. `analyze` first looks at the video's **keyframes** (100-300 frames spread over
   the video; decoding only keyframes takes ~5-10 s) and measures, from vanilla 1.16 GUI
   geometry (everything Minecraft draws is laid out in *GUI pixels*; `k` = screen px per GUI px):
   - **GUI scale** from the hotbar - always 182x22 GUI px, centred at the bottom, with a slot
     border every 20 px. The temporal median of the frames shows it cleanly whatever the world
     does; the k (1.00-8.00) whose border pattern correlates best wins. Measured: tuning VOD
     4.50, sable 3.75, tivesflow 3.00, nbb 4.00 (fit 0.95-0.97). The **game view** rectangle
     (letterbox bars) = edge rows/columns that never change.
   - **Overlay mask** from temporal statistics of world frames: pixels that stay unchanged while
     the world behind them changes a lot (timers, MCSR panel, Ninjabrain, OBS images) or show
     sharp text-like contrast in >= 10% of frames (subtitles, chat), joined into rectangles,
     **minus the vanilla HUD** (hotbar, hearts/armour/food/XP rows, offhand slot, crosshair - those
     are gameplay and stay in the motion signal; the HUD is masked only out of the dimension colour
     statistics), **plus** the vanilla toast stack (top right, 160 x 3x32 GUI px - toasts are too
     rare to show up statistically). The hand-written `OVERLAY_MASK` is only the fallback.
   - **MCSR panel**: the static, yellow, drop-shadowed "Current Match" line, recognised by its
     bold 84 x 7 font-px shape (its width gives the panel's own font size - sable's panel is
     2.45 px/font px in the bottom-left, the others 3-4.5 top-right); which side it hugs gives
     the alignment; the name and status rows follow below it. The size and status row are then
     refined by fitting the status templates on ~40 world frames.
   - **Match clock**: coloured (not white) drop-shadowed text lines anywhere whose glyph read
     parses as `MM:SS.mmm` (MCSR's cyan/yellow `RTA:` lines) or `MM:SS.cc` (a purple
     SpeedRunIGT-style timer on sable) and gives a consistent video-minus-clock offset; their
     box and measured colour are stored.
   - **Resized strips** and **toasts** seen in the sample (below).

   `layout.json` is saved in the run folder with a printed summary; `python -m vodreview layout
   runs/<id> --image sheet.png` draws all boxes on frames of the video.
1. **Sample** ~10 frames per second (skipped frames are only `grab()`-ed, which is faster).
2. **Screen type** (`vodreview/screens.py`, `vodreview/gui.py`) - by **GUI structure at the
   measured scale**, no words (same in every game language):
   - `inventory`: a centred #C6C6C6 container panel (176 GUI px wide, 120-235 tall - inventory,
     crafting table, chests, furnace...; a recipe book beside it is fine) holding #8B8B8B slots;
   - `pause`: >= 3 vanilla buttons (flat grey fill, ~20 GUI px tall; the fill around the label
     is one ring-shaped blob, so its bounding box is the button) with a centred 200-204 px one;
     `settings`: >= 4 options-style 150-px buttons (this now finds the Options screen the
     tuning VOD shows at 11:03 and 15:38, which used to count as `world`);
   - `f3`: >= 11 left-aligned white text lines on F3's 9-GUI-px line grid (chat has <= 10); the
     old F3 line templates (rescaled by k/4.5) are a secondary check for when a Ninjabrain
     window covers the top of the column. The English inventory/pause templates are no longer
     used (they agreed with the structure tests on all 362 keyframes of the tuning VOD);
   - `resized`: the full-size hotbar is **gone** (pattern correlation < 0.3) and >= 30% of the
     frame is flat non-black wallpaper (or >= 50% flat black - tivesflow's desktop is black)
     around a strip blob with straight edges. Works wherever the player's OBS scene puts the
     strip (tivesflow's tall strip is at the far left).
   - nothing matched = `world`.
3. **Motion**: grayscale, shrink to 480x270, subtract the previous sample. A pixel
   "changed" if the difference is > `PIXEL_THRESHOLD`; motion = % of pixels changed.
   The measured overlay rectangles are masked out because they change without the player
   doing anything. When F3 is showing, its left and right text columns and the shift-F3 pie
   chart are masked too (fps, counters and the pie change every frame), sized from k.
4. **Run end** (`vodreview/runend.py`) — analysis stops at the first of:
   - **dragon kill**: the "Ender Dragon" boss bar (top centre: 182x5 GUI px at GUI y 12, placed
     with the measured k) is read by colour —
     bright magenta = health left, dark magenta = health lost. Once the bar has been
     seen with health, the dragon counts as killed when the bar stays empty for 1 s
     (it stays on screen, empty, during the ~10 s death animation) or disappears right
     after being ≤ 5% full. A bar that disappears while fuller (player out of range)
     is ignored. The white "Ender Dragon" label must be bright, because inventory/pause
     screens dim the HUD and make a full bar look empty.
   - **match result**: the grey "Match Winner:" label template (MCSR's own text, English even in
     a Norwegian game; rescaled by k/4.5), **or, language-free**, a centred vivid gold/red title
     in the title area plus a `(MM:SS.mmm)` read by the glyph reader on the subtitle row below
     (vanilla title geometry: title 4x at -40..-12 GUI px from the centre, subtitle 2x at
     +10..+26). The title is read in HSV colour space — gold = **win**, red = **loss**. On the
     three other players' videos only the language-free path fired.
   - **draw** (a forfeit in a private room): an aqua title ("Match is over!") inside the 4x title
     band plus a centred pure-white subtitle ("Match Draw!", no time), on 3 consecutive samples
     -> `result: "draw"`, `end_reason: "forfeit"`. Private rooms title wins "Match is over!" in
     gold too, which the gold path already reads.
   - **end of video** (forfeits, resets, cut recordings).

   After a dragon kill the video is read for up to 30 s more, only to find the result
   screen and record win/loss. Idle stretches and time per screen only cover samples
   before the run end.
5. **Final time** (`vodreview/finaltime.py`, `vodreview/glyphs.py`) — a tiny classical OCR.
   Minecraft's font is a fixed bitmap font, so on the result-screen frames (found as above) the
   text row right of the label (or, without the label, the whole subtitle row) is **thresholded** (light,
   unsaturated pixels that have the font's dark drop shadow down-right), **segmented** into
   glyphs by a column projection (Minecraft leaves one empty font pixel between characters),
   each glyph is **shrunk to its font-pixel grid** (5x7 for digits; the pixel size is the line
   height / 7, so GUI scale and recording resolution don't matter) and **matched** cell by cell
   against `calibration/glyphs/`. The `(MM:SS.mmm)` is checked by regex and range (<= 59:59.999
   and <= video length + 60 s); the result screen is read on several frames (about 3 s, every
   2nd frame) and the majority wins. On the test VOD: 9 of 9 readable frames give `21:34.123`;
   sable 15/15 `10:57.045`, tivesflow 15/15 `11:23.405`, nbb 15/15 `05:58.323`.
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
     pixels of exactly that colour are keyed out of the toast areas from layout.json (the full
     view's toast stack and the top-right of every resized strip, including the one detected in
     the current frame), holes left by the text
     are closed (morphological closing), and connected blobs are kept if they look like a toast:
     wide, clean fill rows at the top, the light-grey frame line right below (only under the
     icon side if a timer overlay covers the toast's lower right). The blob height
     gives the GUI scale, so the same code finds toasts at full screen (1 GUI px = 4.5 screen px
     here) *and* inside MCSR's resized strips (0.73 px), and tells fully shown toasts from ones
     still sliding in (narrower). A fully shown toast is cut out and resized to its 160x32 GUI grid.
     **Primary recogniser: the item icon** (16x16 GUI px at GUI (8, 8)), compared in colour with
     `calibration/toasts/icons/` (flint and steel = We Need to Go Deeper, polished blackstone
     bricks = Those Were the Days, nether bricks = A Terrible Fortress, eye of ender = Eye Spy,
     end stone = The End?, plus 9 others) - language-free; right icons score >= 0.93 at full size.
     Secondary (English tie-break / toasts too small for the icon): the start of its title row (GUI x 25-68, ~8 characters - the streamer's RTA timer
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
   - **Dimension** per `world`/`f3` sample: with F3 open, the 9th F3 line ("minecraft:the_nether"
     / "overworld" / "the_end" - namespaced ids, never translated) is read with the glyph reader at
     the measured k (the old word templates are the fallback). Otherwise colour statistics of
     the shrunk frame (HUD, held items and overlays masked) in HSV: nether = saturated red
     (netherrack, crimson, nether bricks; hue 0-4/172-179, which leaves out orange terracotta and
     lava) or teal (warped forest, soul sand valley) with no sky; End = dark purple sky *and*
     pale-yellow end stone; overworld = blue sky/water or green, with no nether colours - teal next
     to >= 10% sky/water is warm-ocean water, not a warped forest (the nether never showed > 5% sky
     on any F3-confirmed nether frame). Anything else is unknown (caves, dark rooms; every class
     needs saturated, reasonably bright pixels, so a dark or grey night/rain sky gives unknown, never
     nether). These labels no longer *date* dimension changes - they only say which side is which.
   - **Portal transitions** (`vodreview/transition.py`): every nether-portal trip looks the same in
     any biome, weather, time of day or language: the purple **portal overlay** (~4 s), then the
     vanilla **loading screen** ("Loading terrain...", "Laster terreng..." in Norwegian - drawn on
     the options background: the 16x16 dirt texture at 25% brightness, **tiled every 32 GUI px**),
     then the new dimension. The loading screen is found structurally: a cheap colour gate (median
     colour = the darkened dirt's brown, textured), then a **tiling test** at the measured GUI scale -
     shrink so one tile is 16x16 px, compare every tile with the per-pixel median tile; loading
     screens score 0.91-1.0, every other frame of the four videos <= 0.01 (inside a resized strip,
     whose GUI scale is unknown, the period comes from the image's own autocorrelation). It shows
     for 0.1-0.3 s; the transition time is the **first sample after it** = the first rendered frame
     of the new dimension (the answer-key convention). A long portal-overlay stretch that ends
     without a sampled loading screen (the loading screen can be shorter than one 10 fps sample when
     the chunks are cached - nbb 4:19.3, vod-review 15:55.5) is a weaker candidate, kept only if the
     dimension evidence on both sides says the dimension changed. Each side's dimension = a weighted
     vote of the samples within 20 s (F3 reads x5, colour x1, needs >= 60%), else the alternation
     overworld <-> nether (portals alternate). The End is entered through an end portal - no overlay
     and no loading screen on these videos - so it stays toast-based.
     **Entered Nether** = the overworld -> nether transition (0.2-0.4 s before its toast; the toast
     is the fallback); **Finding Stronghold** = the first nether -> overworld transition after the
     nether goals (later of fortress / bastion) - the "blind" travel. Without any transition, the
     old colour fallback is used (labels smoothed by a 6 s sliding majority, stays < 8 s dropped).
     Detected: nbb 4, sable 4, tivesflow 2, vod-review 4 loading screens (incl. nbb's video start and vod-review's seed reset), no
     false ones; all four blind transitions within 0.0 s of the answer key.
   - **Found Fortress = standing on the fortress** (`vodreview/fortress.py`, a project decision):
     the "A Terrible Fortress" advancement can fire long after the player is on the fortress
     (tivesflow: on the bridge at 5:40.4, toast at 6:20.9 - the advancement tests the fortress
     pieces' bounding boxes). The split starts at the first *sustained* moment the floor in front
     of the feet is nether brick: in the middle third of the view, from 62% of its height down to
     the HUD, the share of pixels with nether-brick hue (330-345 deg; the vanilla texture's blue is a
     little above its green - netherrack / crimson nylium / nether wart are 350-360 deg, blackstone /
     basalt grey, soul soil brown, warped blocks teal; red nether bricks don't generate in 1.16.1
     fortresses, bastions are blackstone, fossils bone) must be >= 0.45 while the upper middle of
     the view is < 0.5 brick (a brick *wall* filling the view - pillaring up beside a fortress - is
     not a floor), in >= 80% of the world samples over 1.5 s. Search window: from Entered Nether up
     to the toast (the visual arrival can't be later); no floor seen -> the toast time, said in
     `evidence`; no toast -> the floor must hold 3 s. The toast time is kept as `official_s`.
     Before the first fortress the floor share never held for more than one sample on any video.
   - **World resets**: MCSR's "Are you sure you want to reset this world?" dialog (template in
     `calibration/reset/`, rescaled; MCSR's English text - no language-free cue for the dialog
     itself), or an advancement earned a second time (each can only be earned
     once per world). Only toasts after the last reset count for splits. On the test VOD the
     dialog shows at 2:20.8-2:21.1 and Stone Age / Acquire Hardware / Isn't It Iron Pick repeat.
   - **Overworld** starts at 0:00: the MCSR match timer keeps running across a seed reset, so the
     time on the abandoned seed is part of the overworld split.
   - Splits that contradict the run order (e.g. Found Stronghold before Entered Nether) are
     dropped. Bastion and fortress may come in either order.

   On the test VOD all 7 splits are found; detected vs. match data (+~3 s video offset):
   Entered Nether 5:22.5 (first nether frame in the thin strip; toast 5:22.9, match 5:23), Found
   Bastion 5:53.9 (5:54), Found Fortress 9:51.6 (onto the bridge; advancement 9:52.9 / 9:53),
   Finding Stronghold 15:10.8 (15:11), Found Stronghold 18:49.4 (18:50), Entered End 19:48.3 (19:48).
8. **Opponent panel + match clock** (`vodreview/opponent.py`), at the panel position, alignment and
   font size from layout.json (boxes below are the tuning VOD's, in font px relative to "Current
   Match"). MCSR draws a panel (top right on most setups, bottom left on sable) of the game view: `RTA: MM:SS.mmm` twice (cyan, yellow), "Current Match", "Ranked Mode",
   the opponent's head + name (white) and their status (grey italic, e.g. "Entered Bastion"). It
   is read every 0.5 s up to the run end (in `analyze`, or alone with `opponent`).
   - **Status** - whole-phrase template matching. Surveying the test VOD (one crop per second,
     clustered) gave 6 distinct statuses: Started Match, Entered Nether, Entered Bastion, Entered
     Fortress, Finding Stronghold, Found Stronghold. The status box is thresholded to a mask of
     grey pixels (all channels 115-215, near-neutral) that have Minecraft's dark drop shadow 4.5 px
     down-right - the world behind the panel varies (sand, stone, sky, netherrack) and only the
     text has that colour + shadow - and compared with one template per phrase
     (`calibration/opponent/`, averaged masks) by normalised cross-correlation with +-6 px slack.
     *Why templates and not the glyph reader:* the text is italic, so slanted letters overlap in
     the column projection and can't be segmented; and the vocabulary is small and fixed, so
     telling ~7 phrases apart is all we need. Each template covers the same right-aligned box,
     including the empty space left of shorter phrases, so a longer phrase can't fully match a
     shorter one. A read counts if its score is >= 0.70 and beats the runner-up by >= 0.10.
     A left-aligned panel gets left-aligned templates: the text is cut from each template using
     the phrase's width in Minecraft's font (fixed glyph advances) so the icon fragments drop out,
     and the text start - fixed, after the icon slot - is measured once in calibration. Below
     3 screen px per font px (sable: 2.45) strokes are thinner than the video blur, so a text pixel
     is one clearly lighter than its own drop shadow, and the bar is 0.55 (margin still 0.10).
     The status text is MCSR's and is English in the Norwegian game too.
     Measured on the test VOD: 2420 of 2574 reads confident, 0 wrong; right phrases score
     median 0.96 (the closest pair, Finding/Found Stronghold, cross-scores 0.70, min margin seen
     0.19); the panel is hidden in resized strips and covered by toasts in the third slot,
     by F3 text and some GUIs - those reads are simply not confident.
   - **Status changes**: a new status needs 2 confident reads in a row; its time is the first
     one, and `latency_s` is the gap since the previous confident read (0.5 s when the panel was
     visible). Statuses map to splits (table in `config.OPPONENT_STATUSES`); a return to
     "Started Match" after progress counts as an opponent reset (later splits start over).
   - **Match clock** - the glyph reader from the final time: the clock text is in the same
     Minecraft font, only coloured, so the white mask is swapped for "close to the line's colour
     measured in calibration" (cyan / yellow `RTA:` lines, or e.g. purple / pink timers) and the
     existing 5x7 digit templates read it unchanged (`???: 11:57.554`, the letters of "RTA" are
     unknown glyphs). Valid = two-digit minutes right after the label's colon (or at the line
     start), 3 or 2 decimals. Per sample the two
     lines must agree (one is enough - an icon touches the cyan line's last digits on some
     frames); offset = video time - clock; median, after dropping offsets > 0.5 s from it.
     Test VOD: **video = match + 2.455 s, spread 0.012 s over 2118 samples** (rare 0.05-0.24 s
     lags when the game stutters).
   - **Name** - panels with >= 3 screen px per font px: the glyph reader with letter templates
     (`calibration/glyphs/letters/`, harvested from F3 text of all four videos - 52 characters, `j q K`
     still missing) on an 8-row band (descenders of p/g/y/_), white shadowed text (the head icon
     has no drop shadow and drops out), the last word before the right edge. Every glyph must
     match at >= 0.95, else the read gives no name. Test VOD: `primeord` on 1991 reads, nothing else.
     Smaller panels (sable, 2.45 px): **analysis by synthesis** (`vodreview/textsynth.py`,
     `vodreview/font.py`). Nothing is cut: every candidate glyph is *rendered* from the font bitmaps
     at the measured font size with the recording's area-averaging downscale, high-passed like the
     video crop (strongly coloured pixels - head icon, world - replaced by their surroundings), and a
     dynamic program over the font's own grid (glyph i+1 starts exactly one advance after glyph i,
     free blank space before/after the word; sub-pixel phase and row offset searched) picks the
     glyph sequence that explains the pixels best; end glyphs that don't look like their rendering
     are trimmed, and the read counts only if the rendered word correlates >= 0.6 with the video.
     It takes ~2 s a frame, so it runs on <= 24 confident frames spread over the run. sable:
     `truecelfoid` (fit 0.80-0.88). In both cases the name is the majority of >= 3 reads.
     The same renderer synthesized the "Entered The End" status template (MCSR's End wording,
     seen on sable): italics = the glyph quad sheared +-1 font px; rendering the six harvested
     phrases the same way correlates 0.92-0.94 with their templates.

   Detected vs. match data on the test VOD (match time + 2.455 s = expected video time):

   | Opponent milestone | Match time | Expected video | Detected (status) | Latency |
   |---|---|---|---|---|
   | entered nether | 2:19 | 2:21.5 | 2:21.5 (Entered Nether) | 0.5 s |
   | found bastion | 2:47 | 2:49.5 | 2:53.0 (Entered Bastion) | 6.0 s (status covered by toasts 2:47-2:53) |
   | found fortress | 12:23 | 12:25.5 | 12:26.0 (Entered Fortress) | 0.5 s |
   | blind travel | 16:44 | 16:46.5 | 16:47.0 (Finding Stronghold) | 0.5 s |
   | found stronghold | 20:57 | 20:59.5 | 20:59.5 (Found Stronghold) | 0.5 s |
   | deaths (16:55, 21:04) | | | not shown on the panel | |
   | entered end | never | | none (correct) | |

   "Started Match" is first read at 0:02.5 - the match clock's 0:00 is at 0:02.455.

9. **Idle rule**: a sample is *still* if motion < `MOTION_THRESHOLD` and the screen is
   `world`, `pause` or `f3` (inventory/settings/resized always count as active). A run
   of still samples lasting >= 3 s is an idle stretch; the whole run counts.

10. **Game state from F3** (`vodreview/f3.py`). On every `f3` sample the vanilla 1.16.1 left column is
   read: `XYZ: x / y / z` (3 / 5 / 3 decimals), `Block: bx by bz`, `Chunk: ... in ...`,
   `Facing: <dir> (Towards positive/negative X/Z) (yaw / pitch)`, the dimension line
   (`minecraft:the_nether FC: 0`) and `Biome: minecraft:<id>`.
   - **Lines by prefix.** F3 lines sit on the 9-GUI-px grid (GUI y 2 + 9 i, x 2, 1 font px = 1 GUI px
     = k screen px). Mods add lines, so each line is found by its prefix (one wrong glyph allowed)
     in a scan of the whole column, cached, and re-checked on every frame (missing lines fall back to
     vanilla order around XYZ). All four videos have XYZ on line 10.
   - **Text mask over any background.** Vanilla 1.16 draws each line on a translucent dark box
     (#505050 at 56%) and the text in #E0E0E0 *without* a shadow, so the background behind a glyph is
     <= ~160 grey even over lava, snow or sky. A text pixel = light, neutral and clearly brighter than
     its local background (a grey-level opening with a 2.5-font-px square erases the 1-px strokes and
     leaves the background). The box's top row (one GUI row above the caps) never holds glyphs:
     "glyphs" under a brighter-than-box top row are world pixels outside the box and are dropped.
   - **Glyphs.** The glyph reader (5) with the harvested digit + letter templates on an 8-row grid;
     after the prefix the number lines are matched against digits and `- . / i n` only (a blurred 5
     can't become an S), 1-2-px-wide glyphs may miss one cell. At k = 3.0-4.5 every glyph segments
     cleanly, so the synthesis reader (8) isn't needed (it would be below ~2.5 px per font px).
   - **Strict numbers.** Regexes with the fixed decimal counts; a lost `.` (gap or unknown narrow
     glyph) and a broken `/` are accepted because the decimals pin the structure, a wide unknown glyph
     is a lost digit and fails the read. Unknown glyphs trailing the line (world just right of the
     box) are dropped. Words (direction, biome id) are matched fuzzily against their known lists.
   - **Validation without hand labels - physics self-consistency** (`check_reads`). The F3 lines are
     redundant and the player obeys physics, so every read is checked against itself and its
     neighbours:
     - `block`: Block must equal floor(XYZ) (XYZ is shown rounded: 11.9999 shows as `12.000` with
       Block 11, so up to half a last digit above Block + 1 is allowed). Two independently read lines
       agreeing on every integer digit is the main guard against misread digits;
     - `chunk`: Chunk must equal Block & 15 / Block >> 4 - catches a glyph confused the same way in
       both XYZ and Block (a systematic confusion that `block` alone can't see);
     - `facing`: the direction word must match the yaw (`floor(yaw / 90 + 0.5) & 3` -> south, west,
       north, east, +-0.05 deg for rounding), "Towards positive/negative X/Z" the word, |pitch| <= 90;
     - `y`: feet height 0-257;
     - `speed`: within one dimension, consecutive reads are chained while the move is reachable
       (<= 15 b/s horizontally - sprint 5.6, sprint-jump ~7 - 12 up, 80 down (terminal velocity
       ~78), + 1.5 blocks; + 60 blocks across an F3-closed gap > 2 s; reads > 60 s apart or in another
       dimension aren't compared). A run of < 3 reads that breaks the chain on both sides while its
       neighbours agree with each other is a misread (`speed`); a break between two long consistent
       runs is an ender pearl (`teleport`, kept). Dimension changes reset continuity.
     A read is **valid** (goes into `state.points`) when XYZ and Block were read and `block`,
     `chunk`, `y` and `speed` pass; a failed `facing` only nulls yaw/pitch.
     Cross-checks that use other detectors: around each portal transition (transition.py) the
     overworld position / 8 must be near the nether position (sable's new nether portal landed 19.5
     nether blocks from the scaled point, so 32 + walking distance is allowed); the read nearest each
     split must be in the split's dimension; the F3 dimension is compared with dimension.py's label.

   | Run (k) | F3 samples | valid | block | chunk | facing | speed | portal pairs | dim vs dimension.py | ms/read |
   |---|---|---|---|---|---|---|---|---|---|
   | vod-review (4.5) | 1321 | 1285 (97.3%) | 1286/1286 | 1265/1266 | 1263/1263 | 1285/1285 | 1/1 (off 1.9) | 1272/1272 | 39 |
   | sable (3.75) | 1061 | 1037 (97.7%) | 1037/1037 | 1027/1027 | 1014/1014 | 1037/1037 | 3/3 (0.2-20.5) | 1024/1031 | 36 |
   | tivesflow (3.0) | 463 | 445 (96.1%) | 445/445 | 443/443 | 427/427 | 445/445 | - | 443/443 | 36 |
   | nbb (4.0) | 318 | 292 (91.8%) | 292/292 | 285/285 | 285/285 | 292/292 | 2/2 (0.8-7.1) | 274/276 | 38 |

   Every read whose numbers parse passes `block` (the strict parsing already rejects misreads); the
   failures are reads that don't parse: busy *bright* backgrounds that bleed into the strokes (End
   stone, end-crystal beams and cages through the text - most of nbb's and sable's failures are in
   the End), the right column's long block-tag lines drawn over the end of the left lines (pitch
   lost on vod-review's soul-sand frames), and frames smeared by fast camera motion. The 9
   dimension disagreements are all dimension.py *colour* labels (its F3 line read failed) on the
   first frames after a portal or in the End - the F3 reader was right. Sanity: sable's first End
   read is (100.0, 49, 0.0), the obsidian spawn platform; portal pairs agree with the 1:8 ratio.
   `python -m vodreview f3` takes 14-63 s per run (seeking to each F3 stretch).

All thresholds are in `vodreview/config.py` (the old hand-measured 1080p boxes are kept there as
GUI-px values `*_GUI` and as the fallback layout). A 21.6-minute 1080p60 VOD takes about 6 minutes
to analyze on an Apple Silicon Mac (calibration ~40 s of it); the 6-12 minute MP4s 2-3 minutes.

### Other players' videos (held-out test)

The auto-calibration and structure tests were built from first principles and tuned only on the
tuning VOD; three other players' 1080p60 MP4s were then analyzed without per-video changes:

| Run | GUI k | Panel | Clock offset | Splits found | Final time / result | Opponent |
|---|---|---|---|---|---|---|
| vod-review (tuning) | 4.50 | top-right, 4.5 px | 2.455 s (0.013) | 7/7 | 21:34.123 win | primeord, 6 statuses |
| sable | 3.75 | bottom-left, 2.45 px | 12.070 s (0.006) | 7/7 | 10:57.045 win | truecelfoid (synthesis reader, 13 of 22 reads), 7 statuses incl. Entered The End |
| tivesflow | 3.00 | top-right, 3.0 px | 6.114 s (0.005) | 7/7 | 11:23.405 win | hiegh, 6 statuses |
| nbb (Norwegian) | 4.00 | top-right, 4.0 px | 10.367 s (0.005) | 7/7 | 05:58.323 win | vorbh, 5 statuses |

`python -m vodreview evaluate` (draft hand-made answer keys): our splits **28/28** within 1 s
(mean |error| 0.14 s; before the portal-transition / fortress / small-toast fixes 25/28, 0.77 s -
note the `found_fortress` answer-key rows were re-drafted for the new "standing on nether bricks"
definition), final time 4/4 exact, result 4/4; opponent splits **20/21** within 3 s (was 19/21; the
remaining miss is sable's "Entered Nether" +5.8 s, panel hidden). See Known limitations.

## Known limitations

- The detectors are first-principles (vanilla GUI geometry at a measured scale), but their
  thresholds were tuned on one VOD and checked on three others. Resource packs that change the
  hotbar, container, button or toast textures/colours would break the structure tests.
- GUI scale comes from the hotbar: a hidden HUD (F1) for most of the video, or a very short video,
  leaves the tuning VOD's scale (printed as `source: default`).
- The overlay mask only finds overlays that are static or show text often. A webcam or an overlay
  that changes constantly without text is not masked (it adds motion); overlays that only appear
  in a few calibration frames are missed.
- Anything moving in the world while the player stands still (mobs, lava, fire, particles, the
  dragon) adds motion, so some real idle time can be missed (e.g. waiting in the End or next to lava).
- With F3 open, most of the screen is masked, so the motion signal is coarser there.
- `resized` needs flat wallpaper (or a black desktop) around the strip. A textured wallpaper, or an
  OBS scene that zooms the resized game window to (almost) the full frame (nbb's 0.1-0.2 s zoom
  animation frames at 4:58.6 / 5:00.5) is classified `world` - no general rule tells such a frame
  from gameplay without a HUD; those frames are only an animation, nothing is read there. A pre-match "Waiting for players" frame can be taken for a strip in the
  calibration sample (nbb: an extra toast search region, harmless).
- Dimension changes need the portal transition. A loading screen shorter than one sample is only
  caught through the portal overlay + dimension evidence; with neither (e.g. F3 closed, night and
  rain greying the sky, *and* no sampled loading screen) the old colour fallback dates the change
  late. **No night, rain or snow occurs in the four videos** (checked on overworld frames of every
  run - MCSR seeds start at day and these runs stay in daylight), so that case is untested: dark or
  grey frames give "unknown", the transition time does not depend on colour, and the side's
  dimension then comes from F3 or the overworld <-> nether alternation.
- Found Fortress is a visual proxy ("brick floor in front of the feet"): a player who never looks
  at the floor, a resource pack, or a fortress reached through its inside (brick walls and ceiling
  in view) can delay it up to the toast, which is the fallback. A floor of player-placed nether
  bricks before the fortress would count (none in these videos).
- A toast whose first sliding-in frames are only a few px wide inside a small strip is dated from
  the first frame its box is recognised (nbb Found Stronghold +0.4 s; before the small-toast fix
  +1.4 s).
- Reset dialog: MCSR's English text (template); resets are also inferred from an advancement earned
  twice.
- Opponent panel:
  - 7 status templates: the 6 harvested on the tuning VOD + the synthesized "Entered The End". No
    other wording (e.g. a forfeit / completion text) appeared on any of the four videos; one would
    read as no confident status.
  - Small panels (sable, 2.45 px per font px): statuses read with a lower bar; the first status after
    a gap can be late (sable's "Entered Nether" +5.8 s - the panel was covered / hidden by the
    resized strip). Names there come from the slower synthesis reader (<= 24 frames).
  - Deaths and resets of the opponent are not shown on the panel (a reset is only inferred from a
    return to "Started Match", untested). `latency_s` says how late a change may be dated.
  - Name: `j q K` have no bitmap yet (never shown as plain text in the four videos) - a name with one
    gives `null` on large panels; the synthesis reader can't render them either and would misread
    or reject such a name (the majority vote + fit threshold make `null` the likely outcome). A
    right-aligned *small* panel whose head icon is mostly white/grey can add junk glyphs in front of
    the name (seen when testing the synthesis reader on tivesflow's 3-px panel - which uses the glyph
    reader instead). Bold/coloured names are not handled. When no name is read the UI shows
    **vs Opponent**.
- F3 state: only where the runner has F3 open (10-16% of samples on these videos; none near most
  splits). Reads over very bright, busy backgrounds (End stone, end crystals) or with the right
  column drawn over the line fail and are left out (never guessed). Line prefixes and the number
  formats are vanilla 1.16.1's; a mod that renames them, or a resource pack that changes the font,
  breaks the reader. Validation is self-consistency, not ground truth: a decimal digit misread can
  pass (< 1 block error); a misread integer digit must be repeated identically in XYZ, Block *and*
  Chunk and agree with the movement to slip through. Yaw/pitch decimals have no cross-check.
  Below ~2.5 screen px per GUI px the glyph reader can't segment the text (not seen: k >= 3 here).
- Match clock: needs two-digit minutes (< 1 h) and 2-3 decimals in a Minecraft-style font; two
  clocks that disagree (e.g. IGT and RTA) keep only the more readable one.
- Recording date of a copied file is the copy date (`estimated`).


## License

MIT — see [LICENSE](LICENSE).
