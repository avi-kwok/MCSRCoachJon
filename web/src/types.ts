// Shape of runs/<id>/analysis.json (version 1) - written by vodreview/report.py.

export type TipKind = "stat" | "micro" | "macro" | "risk";

export interface RunInfo {
  video: string;
  video_file: string;
  duration_s: number;
  run_end_s: number;
  end_reason: string;
  result: "win" | "loss" | "draw" | null;
  /** Time read from the result screen "(MM:SS.mmm)"; on a loss it is the winner's time. */
  final_time_ms?: number | null;
  final_time_text?: string | null;
  /** ISO local date-time of the recording, and where it came from. */
  recording_date?: string | null;
  date_source?: DateSource | null;
  /** MCSR panel mode line: true = private room, false = ranked, null = not found. */
  private_room?: boolean | null;
  analyzed_at: string;
}

export type DateSource = "tag" | "filename" | "file_times" | "estimated";

export interface Span {
  start_s: number;
  end_s: number;
}

export interface Segment extends Span {
  name: string;
  source: string;
}

/** One MCSR macro split: from its start to the next split's start (last one: run end). */
export interface Split extends Span {
  name: SplitName;
  source: string;
  evidence?: string; // how it was detected (toast / dimension change), for debugging
}

/** A recognised advancement toast (first appearance, video seconds). */
export interface Advancement {
  name: string; // advancement id, e.g. "stone_age"
  title: string; // in-game title, e.g. "Stone Age"
  t_s: number;
}

export type SplitName =
  | "overworld"
  | "entered_nether"
  | "found_bastion"
  | "found_fortress"
  | "finding_stronghold"
  | "found_stronghold"
  | "entered_end";

/** A user-authored mini segment from runs/<id>/detailed_segments.csv (merged in by the server). */
export interface DetailedSegment extends Span {
  name: string;
  notes: string;
}

export interface ScreenRun extends Span {
  screen: string;
}

export interface IdleStretch extends Span {
  duration_s: number;
}

/** Extra fields on a tip imported from the LLM coach (`python -m vodreview import-tips`, coach/schema.json). */
export interface CoachTipInfo {
  id: string;
  split: SplitName;
  kind: "knowledge" | "mechanics";
  known_at_time: string;
  confidence: "low" | "med" | "high";
  fix_type: "easy" | "practice";
  severity_rank: number;
  evidence: string[];
  catalogue_id: string | null;
  disagrees_with_catalogue: { id: string; reason: string } | null;
  reference_route?: string | null; // knowledge/routes.md id
}

/** One entry of the learner's bastion route library (knowledge/routes.md, GET /api/routes). */
export interface Route {
  id: string;
  type: "housing" | "treasure" | "bridge" | "stables";
  entry: string;
  url: string;
  video_id: string;
  start_s: number;
  end_s: number | null;
  runner: string | null;
  time: string | null;
  notes: string | null;
  status: string;
}

export interface Tip {
  t_s: number;
  end_s: number;
  kind: TipKind;
  title: string;
  text: string;
  est_loss_s: number | null;
  source?: "coach"; // missing on CV-generated tips
  coach?: CoachTipInfo;
}

/** One split the opponent reached, read from the MCSR match HUD (video seconds, same clock as ours). */
export interface OpponentSplit {
  name: string; // usually a SplitName; unknown names are shown as-is
  t_s: number;
  raw?: string; // the HUD text it was read from, e.g. "Entered Bastion"
  latency_s?: number;
  source?: string;
}

export interface OpponentStatus {
  raw: string;
  t_s: number;
}

/** The opponent in a ranked match (missing in older files / non-match VODs). */
export interface Opponent {
  name?: string | null;
  splits?: OpponentSplit[];
  statuses?: OpponentStatus[];
}

/** How the in-game match clock maps to video time (video_s = match_s + offset_s). */
export interface MatchClock {
  offset_s: number;
  spread_s?: number;
  reads?: number;
}

/** One time from the answer key (runs/<id>/truth.csv), video seconds. */
export interface TruthSplit {
  name: string; // usually a SplitName
  t_s: number;
  notes: string;
}

/** The hand-checked answer key, merged in by the server (null without truth.csv). */
export interface Truth {
  status: string | null; // "draft" until the user has verified it
  splits: TruthSplit[];
  final_time_text: string | null;
  result: string | null;
  opponent_splits: TruthSplit[];
}

export interface Analysis {
  version: number;
  run: RunInfo;
  splits: Split[]; // detected splits only, in time order (missing in older files)
  advancements?: Advancement[]; // recognised advancement toasts (missing in older files)
  segments: Segment[]; // CV-derived (screens + idle); kept in the file, not drawn
  detailed_segments?: DetailedSegment[]; // added by the server, not in analysis.json
  screens: ScreenRun[];
  idle: IdleStretch[];
  tips: Tip[];
  opponent?: Opponent | null; // missing in older files
  match_clock?: MatchClock | null; // missing in older files
  truth?: Truth | null; // added by the server from truth.csv, not in analysis.json
}

export interface RunSummary {
  id: string;
  video_name: string;
  result: "win" | "loss" | "draw" | null;
  run_end_s: number | null;
  final_time_text: string | null;
  final_time_ms: number | null;
  recording_date: string | null;
  date_source: DateSource | null;
  private_room?: boolean | null;
  analyzed_at: string | null;
  has_video: boolean;
}
