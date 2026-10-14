// Shape of runs/<id>/analysis.json (version 1) - written by vodreview/report.py.

export type TipKind = "stat" | "micro" | "macro" | "risk";

export interface RunInfo {
  video: string;
  video_file: string;
  duration_s: number;
  run_end_s: number;
  end_reason: string;
  result: "win" | "loss" | null;
  /** Time read from the result screen "(MM:SS.mmm)"; on a loss it is the winner's time. */
  final_time_ms?: number | null;
  final_time_text?: string | null;
  /** ISO local date-time of the recording, and where it came from. */
  recording_date?: string | null;
  date_source?: DateSource | null;
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

export interface Tip {
  t_s: number;
  end_s: number;
  kind: TipKind;
  title: string;
  text: string;
  est_loss_s: number | null;
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
}

export interface RunSummary {
  id: string;
  video_name: string;
  result: "win" | "loss" | null;
  run_end_s: number | null;
  final_time_text: string | null;
  final_time_ms: number | null;
  recording_date: string | null;
  date_source: DateSource | null;
  analyzed_at: string | null;
  has_video: boolean;
}
