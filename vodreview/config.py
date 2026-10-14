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
