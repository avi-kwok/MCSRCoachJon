"""All tunable knobs live here, so tuning never means hunting through the code."""

from pathlib import Path

# --- Sampling -------------------------------------------------------------
SAMPLES_PER_SECOND = 10          # how many frames per second of video we analyze
MOTION_SIZE = (480, 270)         # (width, height) frames are shrunk to for motion

# --- Motion ---------------------------------------------------------------
# A pixel counts as "changed" if its grayscale value moved by more than this
# (0-255 scale) since the previous sample. Video compression adds small noise,
# so this must sit above that noise floor.
PIXEL_THRESHOLD = 12

# A sample is "still" if less than this % of the (unmasked) pixels changed.
MOTION_THRESHOLD = 1.5

# --- Idle rule ------------------------------------------------------------
MIN_IDLE_SECONDS = 3.0           # still runs shorter than this are ignored
# Screens where "nothing moved" means the runner is idle. Everything else
# (inventory, settings, resized) always counts as active.
# F3 follows the normal motion rule; its changing text is masked out instead
# (see F3_MASK).
IDLE_ELIGIBLE_SCREENS = {"world", "pause", "f3"}

# --- Overlay mask ---------------------------------------------------------
# Rectangles (x0, y0, x1, y1) in *normalized* coordinates (0..1 of width/height)
# that contain overlays which change without the player doing anything.
# These pixels are ignored by the motion signal.
OVERLAY_MASK = {
    # MCSR timer/status panel + advancement/recipe toasts (stack down to ~y=0.40)
    "top_right_panel_and_toasts": (0.635, 0.00, 1.00, 0.40),
    # Sound subtitles box; grows upward from just above the hotbar
    "subtitles": (0.68, 0.33, 1.00, 0.90),
    # Status-effect boxes and the Ninjabrain Bot window (from ~15:40 onward)
    "top_left_effects_and_ninjabrain": (0.00, 0.00, 0.30, 0.42),
    # Chat lines (e.g. "X has made the advancement ..."), above the hearts
    "chat": (0.00, 0.55, 0.36, 0.835),
}

# Extra rectangles masked only while the F3 debug screen is showing. F3 text
# (fps, entity/chunk counts, memory, server tick time) and the shift-F3 pie
# chart change every frame even when the runner stands still.
# Measured on 1080p frames at 05:25, 08:00 and 19:31 (pie chart open).
F3_MASK = {
    # Left text column: version, fps, server ticks, chunk/entity counts,
    # XYZ ... "Sounds:" line (x 0-1110, y 0-930 px)
    "f3_left_column": (0.00, 0.00, 0.58, 0.86),
    # Right column, top block: Java / Mem / CPU / Display lines (y 0-375 px)
    "f3_right_top": (0.39, 0.00, 1.00, 0.35),
    # Right column, lower block: "Targeted Block/Fluid" + block tags (y 380-760 px)
    "f3_right_lower": (0.52, 0.35, 1.00, 0.70),
    # Shift-F3 pie chart and its legend lines, bottom right (x 1610+, y 760-1015 px)
    "f3_pie_chart": (0.84, 0.70, 1.00, 0.94),
}

# --- Resized (tall / thin / wide) view ---------------------------------------
# MCSR "resize" macros shrink the game into a strip in the middle of the
# window; everything else shows the (flat, smoothly shaded) desktop wallpaper.
# The strip rectangles below were measured on 1080p frames of the test VOD
# (x0, y0, x1, y1 in pixels -> normalized):
#   tall (eye measuring, 15:25):   x 816-1104, full height
#   thin (pie-chart reading, 18:55): x 835-1085, y 26-1054
#   wide (planar view, 05:28):     x 18-1902,  y 405-675
RESIZED_LAYOUTS = {
    "tall": (816 / 1920, 0 / 1080, 1104 / 1920, 1080 / 1080),
    "thin": (835 / 1920, 26 / 1080, 1085 / 1920, 1054 / 1080),
    "wide": (18 / 1920, 405 / 1080, 1902 / 1920, 675 / 1080),
}
# Two areas that are outside the game strip in *all* layouts and free of the
# extra overlays (Ninjabrain top-left, eye-measuring ruler left, magnified pie
# chart right of the thin strip). In normal gameplay they hold the MCSR timer
# panel (top right) and the hotbar/subtitles (bottom right), so they are never
# flat then.
RESIZED_FLAT_REGIONS = {
    "top_right": (0.585, 0.00, 1.00, 0.37),
    "bottom_right": (0.585, 0.66, 1.00, 1.00),
}
RESIZED_TILE = 10                # tile size (pixels of the 480x270 motion frame)
RESIZED_TILE_STD = 4.0           # a tile is "flat" if its brightness std dev < this
RESIZED_FLAT_FRACTION = 0.90     # this share of tiles in every flat region must be flat
# A real resized view has a visible edge where the game strip meets the
# wallpaper; a fully black frame (world reset, loading) has none. Mean
# brightness jump across the strip border must exceed this (0-255 scale).
# Measured: resized frames 9.6-158, pure black frame 0.0.
RESIZED_EDGE_CONTRAST = 5.0

# --- Run end: dragon kill -------------------------------------------------
# The "Ender Dragon" boss bar, top centre (1080p: bar x 553-1363, y 58-72;
# label y 12-48). The filled part is bright magenta (BGR ~150,0,190), the
# empty part dark magenta (~50,0,62).
DRAGON_BAR_ROW = (560 / 1920, 63 / 1080, 1356 / 1920, 68 / 1080)
DRAGON_LABEL_BOX = (800 / 1920, 12 / 1080, 1115 / 1920, 48 / 1080)
DRAGON_BAR_MIN_COVERAGE = 0.90   # share of the row that must be bar-coloured
DRAGON_FILL_RED = 110            # bar pixels with red > this are "filled"
# GUI screens darken the HUD, making a full bar look empty. The white label
# text stays white on a real (undimmed) bar: require this share of label-box
# pixels to be near-white (measured: 0.22 normal, 0.00 dimmed).
DRAGON_LABEL_MIN_WHITE = 0.10
DRAGON_ALIVE_FILL = 0.10         # we must first see the bar at least this full
DRAGON_EMPTY_FILL = 0.02         # "empty" = at most this full
DRAGON_EMPTY_SECONDS = 1.0       # ... for at least this long (death animation ~10s)
DRAGON_NEAR_EMPTY_FILL = 0.05    # bar vanishing right after being this low = kill

# --- Run end: match result text ---------------------------------------------
# MCSR Ranked shows a big title ("Victory!" in gold on a win, red on a loss)
# with a "Match Winner: <name> (<time>)" line under it. The grey
# "Match Winner:" label is found by template matching (colour-independent);
# then the title colour decides win vs loss.
RESULT_LABEL_REGION = (0.00, 0.50, 1.00, 0.66)   # where "Match Winner:" is searched
RESULT_TITLE_REGION = (0.20, 0.28, 0.80, 0.49)   # where the coloured title sits
# OpenCV hue is 0-179. Measured "Victory!" gold: hue 29-31.
RESULT_GOLD_HUE = (22, 38)
RESULT_RED_HUE = (6, 174)        # red = hue <= 6 or >= 174
RESULT_MIN_SATURATION = 120
RESULT_MIN_VALUE = 170
# After a dragon kill, keep reading (but not analyzing) the video for up to
# this long to find the result screen and record win/loss.
RESULT_LOOKAHEAD_SECONDS = 30.0

# --- Screen recognition ---------------------------------------------------
CALIBRATION_DIR = Path(__file__).resolve().parent.parent / "calibration"
TEMPLATE_SOURCE_HEIGHT = 1080    # calibration crops were cut from 1080p frames
MATCH_SCALE = 1 / 3            # match at 1/3 resolution (640x360): 2x faster than 1/2, same results here
MATCH_THRESHOLD = 0.70           # real matches score >= 0.86, non-matches <= 0.52 on the test VOD

# If several screen types match, the first one in this list wins.
# GUI screens come before f3 because F3 text can stay visible behind a GUI.
SCREEN_PRIORITY = ["pause", "settings", "inventory", "f3"]

# Where on screen to look for each type's templates (normalized x0, y0, x1, y1).
# Searching a smaller region is much faster than searching the whole frame.
SEARCH_REGIONS = {
    "pause": (0.25, 0.05, 0.75, 0.45),
    "settings": (0.0, 0.0, 1.0, 1.0),
    "inventory": (0.25, 0.0, 0.75, 0.75),
    "f3": (0.0, 0.80, 0.40, 1.0),
}

# --- Glyph reader (Minecraft font OCR, vodreview/glyphs.py) ------------------
# Text pixels = light (darkest channel >= GLYPH_MIN_LIGHT) and unsaturated
# (max - min channel <= GLYPH_MAX_CHROMA): white/grey text, not gold names.
GLYPH_MIN_LIGHT = 170
GLYPH_MAX_CHROMA = 40
GLYPH_SHADOW_MAX = 110           # a drop-shadow pixel is darker than this (gray, 0-255)
GLYPH_MIN_FONT_PX = 2.5          # font pixels smaller than this (in screen px) are too blurry to read
GLYPH_MIN_SCORE = 0.88           # share of equal cells needed to accept a glyph match

# --- Final time on the result screen (vodreview/finaltime.py) ----------------
# The "Match Winner: <name> (MM:SS.mmm)" line is read on frames where the
# ResultDetector finds the "Match Winner:" label.
FINAL_TIME_READ_SECONDS = 3.0    # read result-screen frames for up to this long
FINAL_TIME_FRAME_STEP = 2        # read every Nth video frame in that window
FINAL_TIME_MAX_READS = 15        # stop after this many valid reads
FINAL_TIME_SLACK_S = 60.0        # the time shown can't exceed the video duration + this

# --- Advancement toasts (vodreview/toasts.py) --------------------------------
# A 1.16 advancement toast is a flat dark-grey box (RGB ~31,31,31, measured at
# 05:25 / 05:55 / 18:52 / 19:49 on the test VOD) in the top-right corner of the
# game window. Searched in this normalized region, which covers the full-screen
# toast slots 0-2 (y 0-431 px at 1080p) and the top-right corner of every
# resized strip (thin/tall toast at y ~26-60, wide at y ~405-430).
TOAST_SEARCH_REGION = (0.42, 0.00, 1.00, 0.47)
TOAST_FILL_RANGE = (24, 40)      # each BGR channel of a fill pixel is in this range (0-255)
TOAST_FRAME_RANGE = (66, 100)    # the light-grey frame line around the fill (RGB ~83)
TOAST_FILL_MAX_CHROMA = 8        # ... and max - min channel <= this (neutral grey, not End-sky purple)
# The frame line takes on some colour from the background in small (resized)
# toasts - video chroma subsampling bleeds it in (measured up to 14).
TOAST_FRAME_MAX_CHROMA = 16
TOAST_MIN_FILL_PIXELS = 300      # fewer fill pixels in the region = no toast (cheap per-sample gate)
TOAST_MIN_HEIGHT_PX = 12         # fill box at least this tall (thin-strip toast: 21 px)
# The fill rows above "Advancement Made!" and the frame line below the box
# must be this clean (share of matching pixels) - rules out dark world areas.
TOAST_BAND_MIN_FILL = 0.85
# Fill box at most this many GUI px narrower than 154 = fully slid in (frames
# 2-4 GUI px into the slide scored only ~0.7 against the title templates).
TOAST_FULL_SLACK_GUI_PX = 1.5
# Title recognition (normalised cross-correlation of the title crop against
# calibration/toasts/). Measured on the test VOD: right title 0.88-1.00 at full
# screen (best wrong title <= 0.67; MCSR's own "If the opponent agrees..." box
# <= 0.41); 0.68-0.77 in the thin strip (1 GUI px = 0.73 screen px, blurred
# text), where misaligned crops gave wrong titles at <= 0.52 with < 0.05 margin.
# Horizontal scale factors tried when reading (the thin strip measured ~3% wider than tall).
TOAST_X_STRETCHES = (0.98, 1.0, 1.02, 1.04)
TOAST_MIN_READ_K = 0.6           # don't try to read toasts smaller than this (screen px per GUI px)
TOAST_MIN_SCORE = 0.80           # full-size toast (k >= 1.5)
TOAST_MIN_SCORE_SMALL = 0.65     # toast inside a resized strip
TOAST_MIN_MARGIN = 0.15          # best title must beat the runner-up by this much
# A toast stays ~5 s (+0.6 s slide in, 0.6 s slide out). When a title is read,
# walk back over earlier samples with a toast in the same slot to find when it
# appeared; tolerate short gaps (layout switch, a missed frame) of up to:
TOAST_GAP_S = 0.5
TOAST_MAX_SLOT = 4               # boxes lower than this slot are not toasts (stone-brick false positives)
TOAST_MAX_SHOW_S = 6.5           # never walk back further than this from the first read

# Split advancements: split name -> advancement id. Their title templates are
# calibration/toasts/<split>.png; other advancements are in
# calibration/toasts/other/<advancement id>.png (recorded, not used for splits).
SPLIT_ADVANCEMENTS = {
    "entered_nether": "we_need_to_go_deeper",
    "found_bastion": "those_were_the_days",
    "found_fortress": "a_terrible_fortress",
    "found_stronghold": "eye_spy",
    "entered_end": "the_end",
}
# Display titles (advancement id -> in-game title) for the templates we have.
ADVANCEMENT_TITLES = {
    "we_need_to_go_deeper": "We Need to Go Deeper",
    "those_were_the_days": "Those Were the Days",
    "a_terrible_fortress": "A Terrible Fortress",
    "eye_spy": "Eye Spy",
    "the_end": "The End?",
    "stone_age": "Stone Age",
    "acquire_hardware": "Acquire Hardware",
    "isnt_it_iron_pick": "Isn't It Iron Pick",
    "hot_stuff": "Hot Stuff",
    "ice_bucket_challenge": "Ice Bucket Challenge",
    "who_is_cutting_onions": "Who is Cutting Onions?",
    "war_pigs": "War Pigs",
    "monster_hunter": "Monster Hunter",
    "into_fire": "Into Fire",
}

# --- Reset dialog -------------------------------------------------------------
# MCSR asks "Are you sure you want to reset this world?" before a seed reset
# (02:20-02:21 on the test VOD). Template: calibration/reset/; searched here.
RESET_SEARCH_REGION = (0.15, 0.20, 0.85, 0.45)

# --- Dimension (vodreview/dimension.py) ------------------------------------------
DIMENSION_SMOOTH_S = 6.0         # sliding majority window over the labelled samples (seconds)
DIMENSION_MIN_STAY_S = 8.0       # stretches shorter than this are noise (dark cave, lava pool)
# F3 dimension line ("minecraft:overworld" / "minecraft:the_nether", 9th line of
# the left column; 1080p: x 230-480, y 332-372, measured at 05:25 and 18:48).
# Templates: calibration/dimension/<dimension>.png (just the word).
DIM_F3_REGION = (180 / 1920, 315 / 1080, 560 / 1920, 390 / 1080)
DIM_F3_SCALE = 1 / 2             # match at half resolution
DIM_F3_MIN_SCORE = 0.75
DIM_F3_MIN_MARGIN = 0.10
# Extra areas left out of the colour statistics: the hotbar/hearts strip and
# the held items (main hand bottom right, off-hand bottom left - this runner
# keeps red cooked meat there), which look the same in every dimension.
DIM_EXTRA_MASK = {
    "hotbar": (0.25, 0.80, 0.75, 1.00),
    "held_item": (0.55, 0.55, 1.00, 1.00),
    "offhand_item": (0.00, 0.55, 0.30, 1.00),
}
# Colour rules (shares of unmasked pixels, see dimension.py). Tuned on the test
# VOD's world/f3 samples against the known dimension timeline: per-sample
# labels came out overworld 1382 right / 36 wrong (rest unknown), nether
# 3778 / 4, End 518 / 5. Medians: End end_sky 0.47, end_stone 0.33;
# nether red 0.20; overworld red 0.00.
DIM_END_SKY_MIN = 0.15
DIM_END_STONE_MIN = 0.02
DIM_END_MAX_RED = 0.02
DIM_NETHER_RED_MIN = 0.10
DIM_NETHER_TEAL_MIN = 0.10
DIM_NETHER_MAX_BLUE = 0.02
DIM_NETHER_MAX_GREEN = 0.05
DIM_OVERWORLD_BLUE_MIN = 0.03
DIM_OVERWORLD_GREEN_MIN = 0.05
DIM_OVERWORLD_MAX_RED = 0.05
DIM_OVERWORLD_MAX_TEAL = 0.03
