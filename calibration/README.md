# Calibration templates

Small grayscale-matched reference crops used by `vodreview/screens.py` for
template matching. All were cut from 1920x1080 frames of `VOD review.mkv`
(MCSR Ranked, 1.16.1). The classifier rescales them to the video's resolution.

`world` has no folder: it is the fallback when no other screen type matches.

| File | Source time | Pixel box (x0,y0 – x1,y1) | What it is |
|---|---|---|---|
| `inventory/crafting_label.png` | 09:20 | 995,188 – 1185,236 | "Crafting" title on the player inventory panel |
| `inventory/inventory_label.png` | 02:00 | 595,485 – 825,530 | "Inventory" label (crafting table GUI; also on chests/furnaces) |
| `inventory/large_chest_label.png` | 07:40 | 595,62 – 880,108 | "Large Chest" title |
| `pause/game_menu_title.png` | 02:20 | 783,175 – 1010,220 | "Game Menu" title (MCSR pause screen, "(#n)" left out) |
| `pause/back_to_game_button.png` | 02:20 | 805,325 – 1110,378 | "Back to Game" button text |
| `f3/debug_pie_line.png` | 08:00 | 5,938 – 380,978 | "Debug: Pie [shift]:" line, bottom-left of F3 screen |
| `f3/help_line.png` | 08:00 | 5,978 – 410,1020 | "For help: press F3" line, bottom-left of F3 screen |
| `result/match_winner_label.png` | 21:37.5 | 236,582 – 838,662 | "Match Winner:" label on the MCSR match-result screen (used by `runend.py`, not a screen type) |

### `glyphs/` - Minecraft font glyphs for the final-time reader

Not screen crops: each file is one character as a **font-pixel grid** (1 image pixel = 1
Minecraft font pixel, white = on, 7 rows tall; digits are 5x7, `:` and `.` 1x7, parentheses
3x7). `vodreview/glyphs.py` shrinks every glyph it finds to this grid before comparing, so
the same files work at any GUI scale / recording size. File names: `0.png`-`9.png`,
`colon.png`, `dot.png`, `lparen.png`, `rparen.png`, `slash.png`, `minus.png`.

How they were made (majority vote per cell over all samples of a character):

| Characters | Source | Size in the video |
|---|---|---|
| `( ) : . 1 2 3 4` | result line "(21:34.123)", 18 consecutive frames 21:37.25-21:37.53, box x 1180-1700, y 575-665 | 1 font px = 9 screen px |
| `0 5 6 7 8 9 / -` (and `1 2 3 4 : .` again as a cross-check) | 9 hand-labelled F3 lines at 07:51 (e.g. "XYZ: -69.396 / 73.00000 / -69.125", "C: 35/400", "E: 30/48, B: 0") | 1 font px = 4.5 screen px |

The result line is the title *subtitle*, drawn at 2x the GUI scale, so its font pixels are
twice the F3 text's (9 vs 4.5 px; the game ran at 1440p with GUI scale 6 and was recorded at
1080p, hence the half pixel). After shrinking to the font grid, the characters present in
both sources (`1 2 3 4 : .`) came out cell-for-cell identical.

### `toasts/` - advancement titles for the split detector

Not screen crops either: each file is the start of an advancement toast's **title row in the
toast's own 160x32 GUI-pixel grid** (GUI x 25-68, y 17-26 -> 44x10 px, grayscale). The toast
box is found by its flat RGB 31,31,31 fill, cut out and resized to 160x32
(`vodreview/toasts.py`), so the files work at any GUI scale / recording size. Each is the
average of all fully-shown full-screen frames of that toast (51-52 frames, 13 for
`entered_nether`, 29 for `found_stronghold`). Only GUI x 25-68 is used because the
streamer's "RTA" timer overlay covers the rest of the title in the top toast slot.

| File | Advancement (title) | Toast on screen (video time) | Slot |
|---|---|---|---|
| `entered_nether.png` | We Need to Go Deeper | 05:22.9-05:26.2 (read at full size from 05:25) | 0 |
| `found_bastion.png` | Those Were the Days | 05:53.9-05:59.4 | 0 |
| `found_fortress.png` | A Terrible Fortress | 09:52.9-09:58.4 | 0 |
| `found_stronghold.png` | Eye Spy | 18:49.4-18:55.0 | 1 (below a recipe toast) |
| `entered_end.png` | The End? | 19:48.3-19:53.9 | 0 |
| `other/acquire_hardware.png` | Acquire Hardware | 00:29.8 | 1 |
| `other/stone_age.png` | Stone Age | 00:31.9 | 2 |
| `other/isnt_it_iron_pick.png` | Isn't It Iron Pick | 02:13.3 | 0 |
| `other/hot_stuff.png` | Hot Stuff | 04:40.9 | 0 |
| `other/ice_bucket_challenge.png` | Ice Bucket Challenge | 07:18.9 | 1 |
| `other/who_is_cutting_onions.png` | Who is Cutting Onions? | 07:29.6 | 1 |
| `other/war_pigs.png` | War Pigs | 07:30.6 | 2 |
| `other/monster_hunter.png` | Monster Hunter | 10:13.1 | 0 |
| `other/into_fire.png` | Into Fire | 10:13.7 | 2 |

Split files are named after the split; `config.SPLIT_ADVANCEMENTS` maps them to the
advancement id. Files in `other/` are named after the advancement id (display titles in
`config.ADVANCEMENT_TITLES`). To add one: find a frame where the toast is fully shown at full
screen, run `toasts.find_toasts` + `toasts.canonical` on it and save `toasts.title_patch(...)`.
Stone Age, Acquire Hardware and Isn't It Iron Pick appear twice in the VOD (before and after
the 02:21 world reset); the second occurrences (02:46-04:10), read with the templates cut from the first ones, score 0.93-1.0.

### `reset/` - world-reset dialog

| File | Source time | Pixel box (x0,y0 – x1,y1) | What it is |
|---|---|---|---|
| `reset/reset_world_confirm.png` | 02:21.0 | 460,305 – 1460,360 | MCSR's "Are you sure you want to reset this world?" text (shown 02:20.8-02:21.1) |

Matched at 1/3 scale in `config.RESET_SEARCH_REGION`: 0.89 on the dialog, <= 0.43 anywhere
else in the VOD.

### `dimension/` - F3 dimension word

| File | Source time | Pixel box (x0,y0 – x1,y1) | What it is |
|---|---|---|---|
| `dimension/nether.png` | 05:25.5 | 226,330 – 481,372 | "the_nether" from the F3 line "minecraft:the_nether FC: 0" |
| `dimension/overworld.png` | 18:48.0 | 226,330 – 458,372 | "overworld" from "minecraft:overworld FC: 0" |

Matched at 1/2 scale in `config.DIM_F3_REGION`, only on `f3` samples: all 1305 F3 samples of
the VOD got a label (nether 0.94+, overworld 0.98+), matching the visible dimension. There is
no `end.png`: the runner never opened F3 in the End.

`settings/` is intentionally empty: no options/video-settings screen appears
anywhere in this video, so there was nothing to crop. Drop crops (e.g. the
"Options" / "Video Settings" title) into `calibration/settings/` from another
VOD and they will be picked up automatically.

Bottom-left F3 lines were chosen over the top-left "Minecraft 1.16.1" line
because from ~15:40 onward the Ninjabrain Bot window covers the top-left corner.

## Fixed regions (no image files)

These are measured rectangles in `vodreview/config.py`, not template crops.
All pixel values are on 1920x1080 frames of the same VOD.

| Setting | Measured at | Pixels | What it is |
|---|---|---|---|
| `F3_MASK` left column | 05:25, 08:00 | x 0–1110, y 0–930 | F3 text lines from "Minecraft 1.16.1" to "Sounds:" |
| `F3_MASK` right top | 05:25, 08:00 | x 750–1920, y 0–375 | Java / Mem / CPU / Display lines |
| `F3_MASK` right lower | 08:00, 19:31 | x 1000–1920, y 380–760 | "Targeted Block/Fluid" and block tags |
| `F3_MASK` pie chart | 08:00, 19:31 | x 1610–1920, y 760–1015 | shift-F3 pie chart and its legend |
| `RESIZED_LAYOUTS` tall | 15:25–15:31 | x 816–1104, full height | eye-measuring strip |
| `RESIZED_LAYOUTS` thin | 18:53–19:05 | x 835–1085, y 26–1054 | thin strip (pie-chart reading) |
| `RESIZED_LAYOUTS` wide | 05:26–05:30, 21:38 | x 18–1902, y 405–675 | wide/planar strip |
| `RESIZED_FLAT_REGIONS` | all of the above | x 1123–1920, y 0–400 and y 713–1080 | wallpaper in every layout |
| `DRAGON_BAR_ROW` | 20:12, 21:27 | x 560–1356, y 63–68 | middle rows of the boss bar |
| `DRAGON_LABEL_BOX` | 20:12 | x 800–1115, y 12–48 | "Ender Dragon" label |
| `RESULT_TITLE_REGION` | 21:37 | x 384–1536, y 302–529 | where "Victory!" (gold) / the loss title appears |
| `TOAST_SEARCH_REGION` | 05:24, 05:25, 18:52 | x 806–1920, y 0–507 | full-screen toast slots 0-2 (toast x 1197–1917, 144 px per slot) and the top-right corner of the resized strips (thin: toast x 966–1083, y 27–50) |
| `TOAST_FILL_RANGE` / `TOAST_FRAME_RANGE` | 05:25 | fill RGB 31,31,31; frame RGB ~83 | toast colours |
| `DIM_F3_REGION` | 05:25, 18:48 | x 180–560, y 315–390 | the F3 dimension line |

The resized wallpaper is this streamer's desktop background (a smooth purple
gradient). The check only needs it to be smooth and not pure black.
