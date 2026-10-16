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

# Screen types whose old text templates still run as a secondary check after the
# structure tests (screens.py): only F3 (never translated; see screens.py).
SECONDARY_TEMPLATE_SCREENS = ("f3",)

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
# Small toasts (fill box < this many px tall, i.e. < ~1.5 screen px per GUI px - inside resized
# strips): the clean-fill row tests skip this share of the box width at each end and use
# TOAST_FRAME_MAX_CHROMA (blur / chroma subsampling bleed the icon, frame and wallpaper into the
# fill there; nbb's thin strip at k ~1: the sliding Eye Spy toast was missed for 1.4 s).
TOAST_SMALL_FILL_PX = 39
TOAST_SMALL_EDGE_SHARE = 0.15
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
TOAST_FRAME_LEFT_SHARE = 0.35   # if the full-width frame line under a toast is covered, look for it under this left share
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
DIM_OVERWORLD_TEAL_SKY = 0.10    # ... unless blue sky / water covers >= this (warm ocean; nether blue <= 0.05)

# --- Opponent panel + match clock (vodreview/opponent.py) ----------------------
# MCSR's panel in the top-right of the game view (1080p, right-aligned at
# x ~1885, measured at 12:00 / 16:54 / 21:01 on the test VOD):
#   "RTA: MM:SS.mmm" twice (cyan, then yellow) - the match clock,
#   "Current Match" (yellow), "Ranked Mode" (white),
#   opponent head + name (white), status icon + status (grey italic).
# Font pixel = 4.5 screen px at 1080p (text 7 font px = 32 px tall).
OPPONENT_SAMPLE_S = 0.5          # read the panel every this many seconds of video
# Boxes (normalized x0, y0, x1, y1). The status box covers the longest status
# ("Finding Stronghold" + icon starts at x ~1570) with empty margin left of it,
# so a longer status can't fully match a shorter one's template.
OPPONENT_STATUS_BOX = (1380 / 1920, 286 / 1080, 1890 / 1920, 334 / 1080)
OPPONENT_STATUS_SLACK_PX = 6     # search +- this many (1080p) px around the box
OPPONENT_NAME_BOX = (1380 / 1920, 242 / 1080, 1890 / 1920, 288 / 1080)
OPPONENT_NAME_TOP_PX = 6         # cap-top row of the name inside that box (1080p px; y 248)
# Every name glyph must match its template this well (share of equal cells).
# Stricter than GLYPH_MIN_SCORE: a letter we have no template for (see the
# calibration README) must not pass as a similar one (C vs G = 3 cells of 40).
OPPONENT_NAME_MIN_GLYPH_SCORE = 0.95
# The name is accepted if one reading wins >= 3 reads and > half of all readable ones.
# The two RTA lines (cyan y 36-67, yellow y 81-112 at 1080p).
MATCH_CLOCK_LINES = {
    "rta1": (1380 / 1920, 26 / 1080, 1900 / 1920, 76 / 1080),
    "rta2": (1380 / 1920, 72 / 1080, 1900 / 1920, 122 / 1080),
}
# Status text = grey (RGB ~165,165,165 = Minecraft's GRAY) with its dark
# drop shadow 1 font px down-right; white names/labels (~240) are left out.
OPPONENT_GREY_RANGE = (115, 215)  # every channel of a status pixel is in this range
OPPONENT_GREY_MAX_CHROMA = 30     # ... and max - min channel <= this
# Status recognition: TM_CCOEFF_NORMED of the status text mask against
# calibration/opponent/<status>.png. Thresholds: see the README / measured below.
OPPONENT_MIN_SCORE = 0.70
OPPONENT_MIN_MARGIN = 0.10       # best status must beat the runner-up by this much
OPPONENT_CONFIRM_READS = 2       # a new status needs this many confident reads in a row
# Status id (template file name) -> panel text and the split it means.
# "Entered Bastion"/"Entered Fortress" are MCSR's wording for found bastion/fortress.
OPPONENT_STATUSES = {
    "started_match": ("Started Match", "overworld"),
    "entered_nether": ("Entered Nether", "entered_nether"),
    "entered_bastion": ("Entered Bastion", "found_bastion"),
    "entered_fortress": ("Entered Fortress", "found_fortress"),
    "finding_stronghold": ("Finding Stronghold", "finding_stronghold"),
    "found_stronghold": ("Found Stronghold", "found_stronghold"),
    "entered_end": ("Entered The End", "entered_end"),   # MCSR's wording (sable 10:12.8); template synthesized, see font.py
}
# Match clock: RTA text = bright two-channel colour (cyan / yellow): the two
# strong channels >= this, the weak one <= MATCH_CLOCK_WEAK_MAX (white F3
# text behind the panel has all three high and is left out).
MATCH_CLOCK_STRONG_MIN = 170
MATCH_CLOCK_WEAK_MAX = 170
# Reads whose offset (video time - clock) is further than this from the
# median are rejected (misreads, a covered digit).
MATCH_CLOCK_OUTLIER_S = 0.5

# --- GUI structure (vodreview/gui.py) -------------------------------------------
# Language-free screen recognition from vanilla GUI geometry at the measured
# GUI scale k (screen px per GUI px, see layout.py). Measured on the tuning VOD
# (k = 4.5) and checked on keyframes of three other players' videos (k = 3.0,
# 3.75, 4.0).
GUI_SCALE_RANGE = (1.0, 8.0)     # k values tried when fitting the hotbar pattern
GUI_SCALE_SNAP = 0.03            # snap k to a multiple of 0.25 when this close
GUI_HOTBAR_MIN_SCORE = 0.6       # hotbar-pattern correlation needed to trust the measured k (clean median: 0.95-0.97)
GUI_STRUCT_PX = 1.5              # structure tests run on a copy shrunk to ~this many px per GUI px
# Container panel (#C6C6C6, inventory/crafting/chest/furnace ...).
GUI_PANEL_GREY = (184, 212)      # every channel of a panel pixel in this range (198 + video noise)
GUI_PANEL_MAX_CHROMA = 12        # ... and max - min channel <= this (neutral; sand/end stone are yellowish)
GUI_PANEL_MIN_AREA = 0.15        # cheap gate: panel-grey pixels >= this share of a 176x166 panel
GUI_PANEL_W = (140, 300)         # panel blob width in GUI px (176; 147+176 with the recipe book overlapping)
GUI_PANEL_H = (120, 235)         # panel blob height in GUI px (hopper 133 ... large chest 222)
GUI_PANEL_MIN_FILL = 0.12        # panel-grey pixels / blob bounding box (slots and items cut holes; large chest ~0.2)
GUI_SLOT_GREY = (126, 152)       # slot squares #8B8B8B (139)
GUI_PANEL_MIN_SLOTS = 0.04       # slot-grey share of the panel box (inventory ~0.15, large chest ~0.1)
GUI_PANEL_MAX_OFFSET = (110, 60)  # blob centre within this many GUI px of the game centre (x, y)
# Buttons (pause menu, options screens).
GUI_BUTTON_GREY = (92, 128)      # button fill ~108 (texture noise +-4, video noise)
GUI_BUTTON_MAX_CHROMA = 10
GUI_BUTTON_H = (11, 21)          # fill blob height in GUI px (20 minus bevel rows)
GUI_BUTTON_W = (40, 320)         # fill blob width in GUI px
GUI_BUTTON_MIN_FILL = 0.35       # fill pixels / bounding box (the label cuts a hole; long labels ~0.45)
GUI_MIN_BUTTONS = 3              # a menu shows at least this many buttons (the reset Yes/No dialog has 2)
GUI_PAUSE_BUTTON_W = (185, 210)  # full-width pause-menu buttons (200 / 204) centred on the screen
GUI_SETTINGS_BUTTON_W = (138, 156)  # options-screen buttons (150) in two columns
GUI_SETTINGS_MIN_BUTTONS = 4
# F3 debug text (left column): lines at GUI y 2 + 9 i, white #E0E0E0.
F3_COLUMN_GUI_W = 60             # look at this many GUI px from the left edge
F3_TEXT_MIN = 190                # a text pixel is at least this bright (grey level)
F3_LINE_MIN_TEXT = 0.06          # share of white pixels in a line's text rows
F3_GAP_MAX = 0.25                # the gap row below a line has <= this share of the text rows' white
F3_MIN_LINES = 11                # chat shows <= 10 lines; F3's left column ~20 (11+ under a Ninjabrain window)

# --- Per-video calibration (vodreview/layout.py) -> runs/<id>/layout.json ------------
CAL_MIN_FRAMES = 80              # use keyframes when the video has at least this many ...
CAL_MAX_FRAMES = 300             # ... and at most this many of them (evenly spread)
CAL_SEEK_FRAMES = 150            # otherwise seek to this many evenly spaced frames (slow on long-GOP files)
CAL_MEDIAN_FRAMES = 150          # frames used for the temporal median of the hotbar band
CAL_KEEP_FRAMES = 40             # full world frames kept for reading the clock
CAL_MIN_WORLD_FRAMES = 20        # fewer world frames -> keep the fallback mask / panel
CAL_SHADOW_MAX = 90              # a drop-shadow / outline pixel is darker than this (grey level)
# Overlay mask from temporal statistics of world frames (480x270 and 960x540 grey):
OVERLAY_PAIR_MIN_CHANGE = 0.5    # a pair of samples counts if >= this share of pixels changed (the world moved)
OVERLAY_MIN_PAIRS = 10           # need this many such pairs for the "static" statistic
OVERLAY_STATIC_DIFF = 6          # "unchanged" = grey level moved by <= this
OVERLAY_STATIC_SHARE = 0.6       # static overlay pixel: unchanged in >= this share of those pairs
OVERLAY_TEXT_CONTRAST = 110      # sharp text-like contrast: max - min grey in a 3x3 window >= this
OVERLAY_TEXT_SHARE = 0.10        # ... in >= this share of world frames (subtitles, chat, panels; world ~0.02)
OVERLAY_JOIN_GUI = 3             # join overlay pixels this many GUI px apart into one rectangle
OVERLAY_MIN_GUI = 6              # drop overlay blobs smaller than this many GUI px square
OVERLAY_MIN_PIXELS = 6           # ... or with fewer candidate pixels (480x270 px)
OVERLAY_TOAST_SLOTS = 3          # always mask the top-right toast stack this many 32-GUI-px slots deep
# Old hand-measured masks expressed in GUI px (tuning VOD at k = 4.5), so they scale with k:
# F3 text columns + pie chart (F3_MASK above): left column 247 x 207 GUI px from the top-left;
# right column 260 x 83 from the top-right, then 204 wide down to y 168; pie chart 69 wide,
# 72 .. 14.4 GUI px above the bottom-right corner.
F3_MASK_GUI = {"left_w": 247, "left_h": 207, "right_top_w": 260, "right_top_h": 83.3,
               "right_lower_w": 204.4, "right_lower_y1": 168, "pie_w": 69, "pie_y0": 72, "pie_y1": 14.4}
# Vanilla HUD at the bottom centre (hotbar, hearts, armour, food, XP): masked out of the colour
# statistics (looks the same in every dimension), kept in the motion signal. The old
# DIM_EXTRA_MASK["hotbar"] (0.25-0.75 x 0.80-1.0 at 1080p) = +-107 GUI px, 48 GUI px tall.
DIM_HUD_GUI_HALF_W = 107
DIM_HUD_GUI_H = 48
# Resized view (layout.find_strip): the full-size hotbar must be gone ...
RESIZED_MAX_HOTBAR_SCORE = 0.3   # hotbar-pattern correlation below this = no full-size hotbar (world/GUIs 0.5-0.95, resized <= 0.15)
RESIZED_BLACK_MAX = 12           # a flat tile darker than this is black, not wallpaper
RESIZED_MIN_WALL = 0.30          # ... and >= this share of tiles flat non-black wallpaper,
RESIZED_MIN_BLACK = 0.50         # ... or >= this share flat black (a black desktop)
RESIZED_MIN_CONTENT = 0.04       # ... with >= this share of non-flat tiles (the strip),
RESIZED_MIN_NONBLACK = 0.08      # (black desktop: >= this share of non-black tiles; an all-black frame has none)
RESIZED_MIN_STRIP = 0.02         # the strip blob covers >= this share of the frame ...
RESIZED_MAX_STRIP = 0.75         # ... and <= this share (else it is a HUD-less full view, e.g. the pre-match countdown)
STRIP_MIN_FRAMES = 1             # a strip shape seen in fewer calibration frames isn't recorded
STRIP_MIN_SAMPLES_ANALYSIS = 10  # ... or in fewer analysis samples (1 s)
# MCSR panel ("Current Match" = static yellow shadowed text, bold, 84 x 7 font px):
PANEL_STATIC_SHARE = 0.3         # yellow/white text present in >= this share of world frames
PANEL_STATUS_SHARE = 0.15        # grey status text present in >= this share (the status changes ~6 times)
PANEL_FONT_RANGE = (1.5, 9.0)    # plausible panel font px
PANEL_ASPECT_TOL = 0.35          # height/7 vs width/84 must agree within this (rules out "RTA:" etc.)
PANEL_LINE_W = 115               # panel lines are at most this many font px wide (status box 113 font px at 1080p)
# Match clock lines (any coloured MM:SS.mmm text; layout.find_clock):
CLOCK_MIN_BRIGHT = 160           # brightest channel of a clock text pixel
CLOCK_MIN_CHROMA = 60            # clock text is coloured: max - min channel >= this (white F3/chat text is not)
CLOCK_COLOUR_DIST = 75           # reading mask: every channel within this of the line's measured colour
CLOCK_CAL_MIN_READS = 3          # a clock line must read a valid time on >= this many sample frames
CLOCK_CAL_MAX_DEV_S = 1.0        # ... with video time - clock within this of the median
CLOCK_LINES_MAX_DISAGREE_S = 0.2  # two lines further apart than this are different clocks (keep one)
# Toast search (top-right toast stack of the full view + top-right of every strip):
TOAST_SEARCH_PAD_GUI = 10        # GUI px left of the 160-px toast column also searched
TOAST_SEARCH_SLOTS = 3.5         # how many 32-GUI-px toast slots deep (old region: 507 px at k 4.5)
# Reset dialog search box around the screen centre, GUI px: +-x, from -y0 to y1 (old 1080p region
# 0.15-0.85 x 0.20-0.45).
RESET_SEARCH_GUI = (150, 72, -12)

# --- Toast icons (language-free advancement recognition, vodreview/toasts.py) -------
# Item icon (16x16 GUI px at toast GUI (8, 8)) -> advancement. Templates in
# calibration/toasts/icons/<item>.png, each the median of 12 full-size frames
# of that toast on the tuning VOD (verified by eye in those frames: e.g. "We Need
# to Go Deeper" shows flint and steel, obsidian is "Ice Bucket Challenge").
TOAST_ICON_ADVANCEMENTS = {
    "flint_and_steel": "we_need_to_go_deeper",
    "polished_blackstone_bricks": "those_were_the_days",
    "nether_bricks": "a_terrible_fortress",
    "ender_eye": "eye_spy",
    "end_stone": "the_end",
    "obsidian": "ice_bucket_challenge",
    "wooden_pickaxe": "stone_age",
    "iron_ingot": "acquire_hardware",
    "iron_pickaxe": "isnt_it_iron_pick",
    "lava_bucket": "hot_stuff",
    "crying_obsidian": "who_is_cutting_onions",
    "chest": "war_pigs",
    "iron_sword": "monster_hunter",
    "blaze_rod": "into_fire",
}
# Measured on the tuning VOD (278 toast frames): right icon >= 0.93 at full size
# with >= 0.19 lead; inside the thin strip (k 0.73, icon 12 px) the eye of ender
# still reads 0.90+, flint and steel only 0.19 (left unread - its title or the
# full-size frames 2.5 s later read it).
TOAST_ICON_MIN_K = 0.6           # don't read icons on smaller toasts
TOAST_ICON_MIN_SCORE = 0.75      # full-size toast (k >= 1.5)
TOAST_ICON_MIN_SCORE_SMALL = 0.80  # toast inside a resized strip
TOAST_ICON_MIN_MARGIN = 0.10     # best icon must beat the runner-up by this much

# --- Run end / result screen in GUI px (vodreview/runend.py) -------------------------
# The old 1080p boxes (DRAGON_BAR_ROW, DRAGON_LABEL_BOX, RESULT_*_REGION) divided by the
# tuning VOD's k = 4.5, measured from the top centre / screen centre (vanilla geometry:
# boss bar 182 x 5 at GUI y 12, its name at y 3; title 4x at -40..-12, subtitle 2x at +10..+26).
DRAGON_BAR_GUI = (88.5, 14.0, 15.1)      # +-half width, y0, y1 (middle rows of the bar)
DRAGON_LABEL_GUI = (35, 2.67, 10.67)     # +-half width, y0, y1 (the boss name; "Enderdrage" etc. is shorter)
RESULT_SUBTITLE_GUI = (1000, 0, 38.4)    # subtitle row ("Match Winner: <name> (MM:SS.mmm)"), full width
RESULT_TITLE_GUI = (128, -52.9, -2.4)    # title ("Victory!" gold / loss red)
RESULT_TITLE_CENTRE_TOL = 0.12           # language-free check: title extents centred within this share of the box
RESULT_TITLE_MIN_PX_GUI2 = 400           # ... and >= this many (GUI px)^2 of vivid gold/red ("Victory!" ~2000)

# --- Opponent panel geometry in panel font px, relative to the "Current Match" line ----
# (tuning VOD at font px 4.5: text right edge x 1880, "Current Match" top y 144, name cap
# top 248, status text top 292; old boxes OPPONENT_STATUS_BOX / OPPONENT_NAME_BOX above).
OPPONENT_PANEL_GUI = {
    "box_in": 111.1,          # box reaches this far from the aligned edge into the panel (500 px / 4.5)
    "box_out": 2.22,          # ... and this far past the edge (10 px / 4.5)
    "status_above": 1.33, "status_below": 9.33,   # status box rows around the status text top
    "name_above": 1.33, "name_below": 8.89,       # name box rows around the name cap top
    "left_slide": 20,         # left-aligned panels: text-at-left templates slide over this many font px (icon width varies)
}
# Small panel fonts (< this many screen px per font px): status text = pixels lighter than
# their own drop shadow (1 font px down-right) by OPPONENT_SMALL_SHADOW_STEP grey levels,
# at least OPPONENT_SMALL_MIN_LIGHT bright and roughly neutral (the 2.3-px status text on a
# bright background measured ~100-140 grey with chroma up to ~60).
OPPONENT_SMALL_FONT_PX = 3.0
OPPONENT_MIN_SCORE_SMALL = 0.55  # status template score needed on such small panels (right phrase ~0.6-0.7)
# Calibration fits the panel font size (layout.refine_panel) over this range of factors around
# the "Current Match" width estimate (lo, hi, step).
PANEL_REFINE_RANGE = (0.94, 1.12, 0.01)
PANEL_MIN_TEXT_X_READS = 5      # confident status reads needed to fix a left-aligned panel's text start
PANEL_NAME_ABOVE_STATUS = 9.8    # name cap top is this many font px above the status text top (4.5-px panel: 44 px)
OPPONENT_SMALL_SHADOW_STEP = 30
OPPONENT_SMALL_MIN_LIGHT = 80
OPPONENT_SMALL_MAX_CHROMA = 60
OPPONENT_NAME_MIN_FONT_PX = 2.0   # read names down to this font size (small bottom-left panels: 2.3)
# F3 dimension line read by the glyph reader (dimension.py): F3 left-column lines tried
# (0-based; vanilla 1.16 puts "minecraft:<dimension> FC: n" on line 8), how many GUI px
# of the line are read, and how close the word must be to overworld/the_nether/the_end.
DIM_F3_LINES = (8, 7, 9, 10)
DIM_F3_LINE_GUI_W = 120
DIM_F3_MIN_WORD_RATIO = 0.75
# Old 1080p DIM_F3_REGION (180-560 x 315-390 px) in GUI px from the top-left, for the templates.
DIM_F3_REGION_GUI = (40, 70, 124.4, 86.7)

# --- Portal transitions (vodreview/transition.py) and dimension around them (splits.py) ---------
# Loading screen = vanilla options background: 16x16 dirt texture darkened to 25%, tiled every
# 32 GUI px. Median colour on video (all four runs): BGR ~(15-17, 22-23, 30-32).
LOADING_RED_RANGE = (18, 50)     # median red channel of the window
LOADING_RG_RANGE = (3, 16)       # median R - G (brown)
LOADING_GB_RANGE = (2, 12)       # median G - B
LOADING_MIN_STD = 3.0            # grey-level std dev: the dirt is textured (a flat dark frame is not loading)
LOADING_MIN_TILES = 12           # need at least this many 32-GUI-px tiles to test the tiling
LOADING_MIN_SCORE = 0.6          # tiling score at the layout's k (loading 0.91-1.0, anything else <= 0.01)
LOADING_PROBE_MIN = 0.1         # tiling score at the exact period below this: not a loading screen (skip the jitter)
LOADING_MIN_SCORE_STRIP = 0.75   # inside a resized strip k is scanned, so a stricter bar
LOADING_STRIP_K_RANGE = (0.4, 2.5)   # plausible GUI scales inside a strip (thin strip ~0.75; period = 32 k)
LOADING_GAP_S = 0.35             # loading samples closer than this are one loading screen
# Portal overlay (standing in a nether portal): saturated purple over the game view.
PORTAL_HUE = (125, 155)          # OpenCV hue (250-310 deg)
PORTAL_MIN_SAT = 90
PORTAL_MIN_VALUE = 50
PORTAL_MIN_SHARE = 0.5           # share of the game view
PORTAL_MIN_STAY_S = 0.8          # an overlay stretch at least this long ...
PORTAL_MAX_GAP_S = 0.5           # ... whose end is followed by the new world within this (or a loading screen)
# Dimension evidence around a transition: F3 reads count TRANSITION_F3_WEIGHT colour reads.
TRANSITION_WINDOW_S = 20.0       # look at most this far after (and before) a transition
TRANSITION_F3_WEIGHT = 5
TRANSITION_MIN_VOTES = 3         # weighted votes needed to call a side's dimension from evidence
TRANSITION_MIN_SHARE = 0.6       # ... with at least this share for the winner

# --- Found Fortress = standing on nether bricks (vodreview/fortress.py, splits.py) ----------------
FORTRESS_REGION_X = (0.35, 0.65)    # middle third of the game view ...
FORTRESS_REGION_TOP = 0.62          # ... from 62% of its height ...
FORTRESS_HUD_GAP_GUI = 4            # ... down to this many GUI px above the 48-GUI-px HUD
FORTRESS_MIN_REGION_H = 0.06        # (at least this share of the height tall)
FORTRESS_BRICK_HUE = (163, 172)     # OpenCV hue of nether bricks on video (netherrack/nylium 173-179)
FORTRESS_BRICK_MIN_SAT = 50
FORTRESS_BRICK_VALUE = (12, 140)
FORTRESS_UPPER_X = (0.30, 0.70)     # upper middle of the view (wall test) ...
FORTRESS_UPPER_Y = (0.10, 0.40)
FORTRESS_MIN_SHARE = 0.45           # a sample shows the brick floor if >= this share of the floor region is brick
FORTRESS_WALL_MAX = 0.5             # ... and < this share of the upper region (else it is a wall in front)
FORTRESS_SUSTAIN_S = 1.5            # ... and >= FORTRESS_SUSTAIN_FRAC of the world samples in the next
FORTRESS_SUSTAIN_FRAC = 0.8         #     FORTRESS_SUSTAIN_S do too
FORTRESS_MIN_SAMPLES = 8            # (at least this many world samples in that window)
FORTRESS_NO_TOAST_SUSTAIN_S = 3.0   # without an "A Terrible Fortress" toast, the floor must hold this long
TRANSITION_TOAST_LEAD_S = 5.0    # entered_nether: a transition up to this long before the toast is the same entry

# --- Analysis-by-synthesis text reading (vodreview/textsynth.py, font.py) -------------------------
SYNTH_HIGHPASS_FONT_PX = 2.0     # high-pass: minus a Gaussian blur of sigma = this many font px
SYNTH_AMPLITUDE = 1.0            # text contrast after scaling the band by its 99th |value| percentile
SYNTH_PHASE_STEP = 0.25          # sub-pixel phases of the font grid tried (fraction of a font px)
SYNTH_SUBPX = 0.25               # glyph renderings are cached at this sub-pixel step (screen px)
SYNTH_MAX_CHROMA = 60            # pixels more coloured than this (max - min channel) are not text
SYNTH_MIN_GLYPH_FIT = 0.3        # end glyphs whose own rendering correlates less than this are dropped
SYNTH_MIN_FIT = 0.6              # a name read is kept if the rendered word correlates >= this with the video
SYNTH_NAME_READS = 24            # names are read by synthesis on at most this many frames (spread over the run)

# --- F3 game-state reader (vodreview/f3.py) ---------------------------------------------------------
# Left-column lines sit at GUI y 2 + 9 i on a translucent dark box (#505050 at 56% opacity) that
# spans GUI rows top-1 .. top+8; the text is #E0E0E0 without a drop shadow. A text pixel = clearly
# brighter than the local background (grey opening with a ~2.5 font px square), light and neutral.
F3_READ_LINE_GUI_W = 330        # read this many GUI px of a line (the right column starts further right)
F3_READ_MAX_LINES = 30          # lines searched for the prefixes ("XYZ:", "Block:" ...)
F3_READ_MIN_STEP = 25           # text is >= this many grey levels above the local background ...
F3_READ_STEP_SHARE = 0.45       # ... and >= this share of the way from the background to #E0 (224)
F3_READ_MIN_LIGHT = 140
F3_READ_MAX_CHROMA = 50
F3_READ_BREAK_FONT_PX = 8       # a gap this wide ends the line (right-column text beyond it)
F3_NUMERIC_MIN_SCORE = 0.80     # glyphs of the number lines, matched against digits / separators only
F3_NARROW_MIN_SCORE = 0.75      # 1-2 font px wide glyphs (: . i): one wrong cell allowed ...
F3_NARROW_MIN_MARGIN = 0.12     # ... if the runner-up template is this much worse
F3_BOX_MAX_GREY = 165           # the line's box row (GUI row above the caps) is darker than this inside the
                                # box (0.44 x world + 0.56 x 80 <= 157): a "glyph" under a brighter one is world
# Physics self-consistency (f3.check_reads): plausible movement between two reads in one dimension.
F3_MAX_H_SPEED = 15.0           # b/s horizontally (sprint 5.6, sprint-jump ~7.1, soul speed / boats a bit more)
F3_MAX_UP_SPEED = 12.0          # b/s upwards (jumps, pillaring, bubble columns)
F3_MAX_FALL_SPEED = 80.0        # b/s downwards (terminal velocity ~78)
F3_SLACK_BLOCKS = 1.5           # + this many blocks (rounding, frame timing)
F3_GAP_ALLOWANCE = 60.0         # + this many blocks per gap longer than 2 s between reads (pearls while F3 was closed)
F3_MAX_CHAIN_GAP_S = 60.0       # reads further apart than this are not compared
F3_MIN_SEGMENT = 3              # a run of mutually consistent reads shorter than this, inconsistent with
                                # both neighbours (which agree with each other), is a misread
F3_Y_RANGE = (0.0, 257.0)       # player feet height in 1.16 (build limit 256, standing on top of it)
F3_POINTS_PER_S = 5             # analysis.json "state.points" thinning
F3_SEGMENT_GAP_S = 2.0          # F3 samples closer than this are one stretch (one seek in `f3`)
F3_PORTAL_WINDOW_S = 20.0       # portal-pair check: reads at most this far from a transition
F3_SPLIT_WINDOW_S = 30.0        # split check: the valid read nearest to a split start, at most this far
F3_PORTAL_RADIUS = 32.0         # nether blocks: the arrival portal lies within this of overworld pos / 8
                                # (portal search / placement radius; sable's new nether portal landed 19.5 off)
