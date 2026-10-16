# Calibration templates

Small reference crops and glyph grids. All were cut from 1920x1080 frames of
`VOD review.mkv` (MCSR Ranked, 1.16.1, game 1440p at GUI scale 6 recorded at 1080p,
so **1 GUI px = 4.5 screen px**). Every detector now rescales them by the GUI scale
measured for each video (`k / 4.5`, see "Per-video layout" at the end) instead of
assuming this VOD's size.

Since the per-video auto-calibration, screen types are recognised primarily by
**GUI structure** (no files - see the end of this page); of the screen crops below
only the F3 lines are still used, as a secondary check. The inventory / pause
crops are kept for reference (English text; the structure tests agreed with them on
all 362 keyframes of this VOD).

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
| `result/match_winner_label.png` | 21:37.5 | 236,582 – 838,662 | "Match Winner:" label on the MCSR match-result screen (used by `runend.py`, not a screen type). MCSR's own text - it stays English in a Norwegian-language game - but the result screen is also found without it (gold/red centred title + a `(MM:SS.mmm)` read by the glyph reader); on the three other players' videos only that language-free path fired |

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

#### `glyphs/letters/` - letters for the opponent-name reader

Same idea as the digits, but **8 rows** tall (row 7 = the descender row of `g p y _` and `Q`'s
tail), so lowercase letters keep their vertical position. File names carry the case because
macOS file names are case-insensitive: `lower_a.png`, `upper_B.png`, `underscore.png`.
`vodreview/opponent.py` adds the 7-row digits (padded with an empty 8th row) for names.

| Characters | Source (all 1 font px = 4.5 screen px) |
|---|---|
| `a b c d e f g h i k l m n o p r s t u v w x y`, `B C D E F H I L M O P R S T X Y Z`, `_` | F3 text at 07:51 (all left-column lines from "Minecraft 1.16.1 (1.16.1/fabric/Fabric)" to "SH S: ..." except "Biome:" (chat overlaps it), "Debug: Pie [shift]: visible FPS + TPS [alt]: hidden", "4.6.0 Compatibility Profile Context 26.8.1.260806", "MCSR Sodium 2.5.1") and 08:00 ("Minecraft 1.16.1 ...", "minecraft:the_nether FC: 0", "Server Light: (0 sky, 3 block)", "#minecraft:soul_fire_base_blocks", "#minecraft:soul_speed_blocks") |
| `Q` | "For help: press F3 + Q" at 07:51 |

Each line was segmented with an 8-row band from its cap top and zipped with the hand-typed
text; lines whose glyph count didn't match the text were skipped. Every character's samples
agreed cell-for-cell (majority vote anyway). Cross-check: the panel's "Ranked Mode" (12:00)
reads identically with these templates, and the opponent name `primeord` reads exactly.
Missing from this VOD's plain white text: `j q z A G J K N U V W`. Eight of them were then
harvested from the **other three videos** (and this one) - see below; `j q K` are still missing.

| Characters | Source | How |
|---|---|---|
| `A G J N V z` (`upper_A.png` ...) | F3 right column ("Java: 22.0.2 64bit", "CPU: 12x AMD Ryzen 5 5600X 6-Core Processor", "Display: 2560x1440 (NVIDIA Corporation)", "NVIDIA GeForce RTX 3060/PCIe/SSE2", "4.6.0 NVIDIA 595.79" and each player's own hardware strings) + "Minecraft 1.16.1 (1.16.1/fabric/Fabric)", on 12 F3 frames per video of sable (k 3.75), tivesflow (3.0), nbb (4.0) and this VOD (4.5) | segmented as above, aligned to the typed text by glyph widths (dynamic programming), a glyph kept only when an aligned neighbour matches an existing template (>= 90% cells); bootstrapped once. Samples / agreement: A 63 (0.99, all 4 videos), N 62 (0.99), V 62 (0.99), J 27 (1.00), G 17 (0.99), z 12 (1.00, nbb + tivesflow). The 29 characters that already had templates came out identical on 23 (the others differed only on noisy harvests with < 80% agreement; the old templates were kept) |
| `U` | "CPU:" on 20 F3 frames of this VOD (the "P" before it read as P) | 20 samples, 0.97 agreement |
| `W` | "Waiting for chunk..." (sable F3, 7:47.6-7:50, line 14) | 14 samples, 1.00 agreement (followed by a read `a` and `i`) |

### `opponent/` - opponent status phrases (MCSR panel)

Each file is a **text mask** of one status phrase in the panel's status box (1080p px
x 1380-1890, y 286-334 -> 510x48 px, right-aligned text; white = grey text pixel with a drop
shadow, see `opponent.status_mask`), averaged over many frames: frames every 0.5 s from the
stretches below (max ~80), a first majority mask, then the mean of the frames that correlate
>= 0.6 with it (drops covered frames); cells < 0.25 set to 0. File name = status id
(`config.OPPONENT_STATUSES` maps it to the panel text and our split name).

| File | Panel text | Frames from (video time) | Frames used |
|---|---|---|---|
| `started_match.png` | Started Match | 00:03-00:27, 00:30-00:40 | 55 of 68 |
| `entered_nether.png` | Entered Nether | 02:23-02:46 | 45 of 46 |
| `entered_bastion.png` | Entered Bastion | 03:00-12:20 | 76 of 80 |
| `entered_fortress.png` | Entered Fortress | 12:30-16:45 | 81 of 85 |
| `finding_stronghold.png` | Finding Stronghold | 16:52-20:58 | 77 of 82 |
| `found_stronghold.png` | Found Stronghold | 21:01-21:24 | 46 of 46 |

| `entered_end.png` | **Entered The End** | *synthesized*, not harvested (below) | - |

`entered_end.png` is MCSR's End status, which never shows on this VOD (seen on sable 10:12.8-10:48,
"Entered The End", not the guessed "Entered End"). It is **rendered** from the font bitmaps
(`vodreview/font.py`): Minecraft's italic = the glyph quad sheared +1 font px at the top, -1 at
the bottom; drawn at 4.5 px per font px, right-aligned like the others. Check: rendering the six
harvested phrases the same way correlates 0.92-0.94 with their averaged masks (Found Stronghold
0.84) at one consistent offset (text top row 6, right end column ~510), and the synthetic
"Entered The End" scores <= 0.39 against every other template. On sable's 2.45-px panel it
reads 0.66-0.78 (bar 0.55) with margin >= 0.20 from 10:12.8 on. No other finish wording
("Completed", "Forfeited" ...) appeared on any of the four videos' panels. To add a phrase:
collect `PanelReader(h, w).status_box_patch(frame)` masks from frames showing it, average them
and save as `calibration/opponent/<status id>.png` (and add the id to `config.OPPONENT_STATUSES`
if new). The statuses were found by surveying the whole VOD (one status crop per second,
clustered by mask overlap) - nothing else appears on the panel (deaths are not shown).

The match clock (`RTA:` lines) needs no new templates: the 5x7 digits above read it.

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

The title templates are English-only and are now the **secondary** recogniser (tie-break /
toasts too small for the icon); the primary one is the item icon below.

Split files are named after the split; `config.SPLIT_ADVANCEMENTS` maps them to the
advancement id. Files in `other/` are named after the advancement id (display titles in
`config.ADVANCEMENT_TITLES`). To add one: find a frame where the toast is fully shown at full
screen, run `toasts.find_toasts` + `toasts.canonical` on it and save `toasts.title_patch(...)`.
Stone Age, Acquire Hardware and Isn't It Iron Pick appear twice in the VOD (before and after
the 02:21 world reset); the second occurrences (02:46-04:10), read with the templates cut from the first ones, score 0.93-1.0.

### `toasts/icons/` - advancement item icons (language-free toast recognition)

Each file is the 16x16 GUI-px item icon drawn at GUI (8, 8) of a 1.16 advancement toast,
in colour (BGR), cut from the canonical 160x32 toast (`toasts.canonical(..., colour=True)`,
`toasts.icon_patch`) and taken as the per-pixel median of 12 fully shown, full-size frames
of that toast on this VOD (the same toasts as the title templates above). File name = item;
`config.TOAST_ICON_ADVANCEMENTS` maps it to the advancement. Matched by normalised
cross-correlation (3 channels) with +-1 GUI px slack.

Icons verified by eye on the frames (the task brief guessed obsidian for "We Need to Go
Deeper" - it is **flint and steel**; obsidian is "Ice Bucket Challenge", so no icon is shared
by two advancements here):

| File | Advancement | Split |
|---|---|---|
| `flint_and_steel.png` | We Need to Go Deeper | entered_nether |
| `polished_blackstone_bricks.png` | Those Were the Days | found_bastion |
| `nether_bricks.png` | A Terrible Fortress | found_fortress |
| `ender_eye.png` | Eye Spy | found_stronghold |
| `end_stone.png` | The End? | entered_end |
| `obsidian.png` | Ice Bucket Challenge | - |
| `wooden_pickaxe.png` | Stone Age | - |
| `iron_ingot.png` | Acquire Hardware | - |
| `iron_pickaxe.png` | Isn't It Iron Pick | - |
| `lava_bucket.png` | Hot Stuff | - |
| `crying_obsidian.png` | Who is Cutting Onions? | - |
| `chest.png` | War Pigs | - |
| `iron_sword.png` | Monster Hunter | - |
| `blaze_rod.png` | Into Fire | - |

Measured on this VOD (278 toast frames): the right icon scores >= 0.93 at full size with
>= 0.19 lead over the next icon; closest pair iron pickaxe / wooden pickaxe (0.71 between
the templates). Inside MCSR's thin strip (k = 0.73, the icon is 12 screen px) the eye of
ender still reads 0.90+, flint and steel only ~0.2 (rejected; its full-size frames 2.5 s
later read it). No icon was harvested from the three other players' videos.

### `reset/` - world-reset dialog

| File | Source time | Pixel box (x0,y0 – x1,y1) | What it is |
|---|---|---|---|
| `reset/reset_world_confirm.png` | 02:21.0 | 460,305 – 1460,360 | MCSR's "Are you sure you want to reset this world?" text (shown 02:20.8-02:21.1) |

Matched at 1/3 scale (rescaled by `k / 4.5`) in a box around the screen centre
(`config.RESET_SEARCH_GUI`): 0.89 on the dialog, <= 0.43 anywhere else in the VOD. The
question is MCSR's own (English) text; no language-free cue was added - a reset is also
inferred when an advancement is earned twice (`splits.py`).

### Loading screen and fortress floor (no files)

The portal-transition detector (`vodreview/transition.py`) needs no template: the vanilla loading
screen's dirt background (16x16 dirt texture at 25% brightness, tiled every 32 GUI px) is
recognised by its median colour - BGR ~(15-17, 22-23, 30-32) on all four videos - and by the
tiling itself at the measured GUI scale. The nether-brick floor (`vodreview/fortress.py`) is a hue
band: nether bricks on video at OpenCV hue 163-172 (71-77% of their saturated pixels), netherrack /
crimson nylium at 173-179 (79-92%), measured on the floor in front of the player on all four videos.

### `dimension/` - F3 dimension word

| File | Source time | Pixel box (x0,y0 – x1,y1) | What it is |
|---|---|---|---|
| `dimension/nether.png` | 05:25.5 | 226,330 – 481,372 | "the_nether" from the F3 line "minecraft:the_nether FC: 0" |
| `dimension/overworld.png` | 18:48.0 | 226,330 – 458,372 | "overworld" from "minecraft:overworld FC: 0" |

Matched at 1/2 scale (rescaled by `k / 4.5`), only on `f3` samples: all 1305 F3 samples of
the VOD got a label (nether 0.94+, overworld 0.98+), matching the visible dimension. There is
no `end.png`: the runner never opened F3 in the End. These are now the fallback: the F3
dimension line ("minecraft:the_end" etc. - namespaced ids, never translated) is first read
with the glyph reader and the letter templates above at the measured GUI scale, which also
covers `the_end`.

### F3 game-state lines (no new files)

`vodreview/f3.py` reads the F3 left column (`XYZ:`, `Block:`, `Chunk:`, `Facing:`, `Biome:` and the
dimension line) with the **existing** `glyphs/` digits + punctuation and `glyphs/letters/` (8-row
grid) - no new templates. Every character those lines need is covered except `,` (only in the
light lines, not read) and `j q K` (no 1.16 biome id needs `q`; `jungle*` biomes read with one
unknown glyph and are matched fuzzily against the 1.16 biome list). Geometry used (vanilla 1.16.1
`DebugHud`, GUI px, 1 font px = 1 GUI px): line i's caps start at y = 2 + 9 i, x = 2; its
translucent box (#505050, alpha 0x90) spans rows top-1 .. top+7 and x 1 .. width+3; the text is
#E0E0E0 with no shadow. Checked on all four videos (k 3.0 / 3.75 / 4.0 / 4.5): XYZ is line 10,
Block 11, Chunk 12, Facing 13, Biome 18, dimension 8. Thresholds: `config.F3_READ_*`, `F3_BOX_MAX_GREY`,
`F3_NUMERIC_MIN_SCORE`, `F3_NARROW_*`; physics checks `config.F3_MAX_*_SPEED`, `F3_GAP_ALLOWANCE`,
`F3_MIN_SEGMENT`, `F3_Y_RANGE`, `F3_PORTAL_RADIUS`.

`settings/` is intentionally empty: no options/video-settings screen appears
anywhere in this video, so there was nothing to crop. Drop crops (e.g. the
"Options" / "Video Settings" title) into `calibration/settings/` from another
VOD and they will be picked up automatically.

Bottom-left F3 lines were chosen over the top-left "Minecraft 1.16.1" line
because from ~15:40 onward the Ninjabrain Bot window covers the top-left corner.

## Fixed regions (no image files)

These rectangles were hand-measured on 1920x1080 frames of the same VOD. They are no
longer used as fixed pixels: each was converted to **GUI pixels** (divided by 4.5) relative
to the screen edge or centre it hangs from (`config.*_GUI`, e.g. `DRAGON_BAR_GUI`,
`RESULT_TITLE_GUI`, `F3_MASK_GUI`, `OPPONENT_PANEL_GUI` in panel font px from "Current
Match"), and is placed with the GUI scale / panel font measured per video. The resized
strip rectangles and `OVERLAY_MASK` are only the fallback (`layout.default_layout`), used
when calibration can't measure something.

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
| `OPPONENT_STATUS_BOX` | 12:00, 16:54, 21:01 | x 1380–1890, y 286–334 | opponent status line (text y 292–323, right edge x 1881) |
| `OPPONENT_NAME_BOX` | 12:00 | x 1380–1890, y 242–288 | opponent name line (cap top y 248, descender to 282) |
| `MATCH_CLOCK_LINES` | 12:00 | x 1380–1900, y 26–76 / 72–122 | the cyan / yellow `RTA:` lines (text y 36–67 / 81–112) |
| `OPPONENT_GREY_RANGE` | 12:00 | RGB ~165,165,165 | status text grey |

The resized wallpaper is this streamer's desktop background (a smooth purple
gradient). The check only needs it to be smooth and not pure black.

## Per-video layout (`runs/<id>/layout.json`, no image files)

`analyze` starts with `vodreview/layout.py`'s calibration pass over the video's keyframes
(100-300 frames; only keyframes are decoded, ~5-10 s) and every detector reads the result.
`python -m vodreview layout runs/<id> --image sheet.png` draws it. What is measured, and
from which vanilla 1.16 geometry (all in GUI px):

| Field | How |
|---|---|
| `gui.k` | hotbar 182 x 22, centred at the bottom, slot borders every 20 px: the column profile of the temporal-median frame is correlated with the border pattern for k = 1.00-8.00 (best wins, snapped to a multiple of 0.25 within 0.03). Tuning VOD 4.50 (0.95); the other three 3.75 / 3.00 / 4.00 (0.95-0.97) |
| `game`, `letterboxed` | rows / columns at the frame edges that never change and stay dark |
| `overlay_mask` | world frames only: pixels unchanged while the world behind them changed (static overlays), plus pixels with sharp text-like contrast in >= 10% of frames (subtitles, chat, panels); minus the vanilla HUD (hotbar, hearts, armour, food, XP, offhand, crosshair - gameplay, kept); joined into rectangles; plus the vanilla toast stack (top right, 160 x 3 x 32) |
| `panel` | MCSR's "Current Match": static yellow drop-shadowed text whose width / height match its bold 84 x 7 font px shape -> position, alignment (corner) and the panel's own font size; then the size and the status row are refined by fitting the status templates on ~40 world frames |
| `clock.lines` | coloured (not white) drop-shadowed text lines anywhere whose glyph read parses as `MM:SS.mmm` / `MM:SS.cc` and gives a consistent video-minus-clock offset; box + measured colour |
| `strips` | frames without the full-size hotbar that are mostly flat wallpaper: the non-flat blob (centre one, else largest) with straight bright/dark edges; the analysis pass adds the strips it saw (`strips_analysis`) |
| `toasts` | toast boxes seen in the sample (their own height gives their scale) |

### Structure tests (`vodreview/gui.py`, thresholds `config.GUI_*`, `F3_*`)

| Screen | Structure at the measured k |
|---|---|
| `inventory` | a #C6C6C6 (184-212, neutral) blob 140-300 x 120-235 GUI px near the centre, >= 12% filled, with >= 4% #8B8B8B slot grey inside |
| `pause` | >= 3 vanilla buttons (neutral fill 92-128 forming a ring around the label, 11-21 GUI px tall) near the centre, one of them 185-210 wide and centred |
| `settings` | >= 4 options buttons 138-156 GUI px wide |
| `f3` | >= 11 left-aligned white (>= 190) text lines on the 9-GUI-px F3 line grid (chat has <= 10) |
| `resized` | hotbar-pattern correlation < 0.3 and >= 30% flat non-black tiles (or >= 50% flat black with >= 8% non-black) and a strip blob of 2-75% of the frame with edge contrast > 5 |
