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

The resized wallpaper is this streamer's desktop background (a smooth purple
gradient). The check only needs it to be smooth and not pure black.
