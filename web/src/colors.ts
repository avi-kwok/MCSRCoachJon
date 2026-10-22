import type { SplitName } from "./types";

// Detailed Segments are user-authored, so they have no meaning-coded colours:
// neutral Minecraft block tones, alternated so neighbouring blocks stay distinguishable.
export const SEGMENT_TONES: { color: string; ink: string }[] = [
  { color: "#c4b07c", ink: "#1e1e1e" }, // birch planks
  { color: "#6e4f30", ink: "#ffffff" }, // spruce planks
];

// The 7 MCSR macro splits, in run order, for the Splits track.
// `ink` is the label colour drawn on top of `color`; `short` is drawn when `label` doesn't fit.
export const SPLITS: { name: SplitName; label: string; short: string; color: string; ink: string }[] = [
  { name: "overworld", label: "Overworld", short: "Overworld", color: "#5d9c3a", ink: "#ffffff" },          // grass
  { name: "entered_nether", label: "Entered Nether", short: "Nether", color: "#a8352c", ink: "#ffffff" }, // netherrack
  { name: "found_bastion", label: "Found Bastion", short: "Bastion", color: "#d9a52b", ink: "#1e1e1e" },   // gold block
  { name: "found_fortress", label: "Found Fortress", short: "Fortress", color: "#4a1c28", ink: "#ffffff" }, // nether brick
  { name: "finding_stronghold", label: "Finding Stronghold", short: "Blind", color: "#2b8f80", ink: "#ffffff" }, // eye of ender
  { name: "found_stronghold", label: "Found Stronghold", short: "Stronghold", color: "#6f6f6f", ink: "#ffffff" }, // stone bricks
  { name: "entered_end", label: "Entered End", short: "End", color: "#e0dc9c", ink: "#1e1e1e" },       // end stone
];


// Tips track: coach tips coloured by how they get fixed (matches the .fix-easy / .fix-practice badges);
// CV tips (no fix type) in neutral stone.
export const TIP_TONES: Record<"easy" | "practice" | "cv", { color: string; ink: string; label: string }> = {
  easy: { color: "#3f8f2c", ink: "#ffffff", label: "Easy fix" },
  practice: { color: "#b07a1f", ink: "#ffffff", label: "Needs practice" },
  cv: { color: "#7d7d7d", ink: "#ffffff", label: "Stat tip" },
};
