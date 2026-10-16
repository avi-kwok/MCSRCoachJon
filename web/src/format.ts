import type { DateSource, RunSummary } from "./types";

/** 412.3 -> "6:52" */
export function mmss(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** 412.3 -> "6:52.3" (one decimal, for user-authored segment times) */
export function mmssTenths(seconds: number): string {
  const tenths = Math.max(0, Math.round(seconds * 10));
  const s = Math.floor(tenths / 10);
  const frac = tenths % 10;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}${frac ? `.${frac}` : ""}`;
}

/** 412.3 -> "6:52.3", 412 -> "6:52.0" (always one decimal, for answer-key comparisons) */
export function mmssDec(seconds: number): string {
  const tenths = Math.max(0, Math.round(seconds * 10));
  const s = Math.floor(tenths / 10);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}.${tenths % 10}`;
}

/** "2026-10-09T21:10:00-07:00" -> "Oct 9, 2026" (the date as recorded, no timezone shift). */
export function shortDate(iso: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export interface RunTitle {
  date: string; // "Oct 9, 2026" or the run id if no date
  estimated: boolean; // the date was estimated from file times (shown as a muted "est.")
  outcome: "Won" | "Lost" | null;
  time: string; // final time, or run end mm:ss as a fallback
  tooltip: string;
}

const DATE_NOTES: Record<DateSource, string> = {
  tag: "date from the video's creation_time tag",
  filename: "date from the OBS file name",
  file_times: "date from the file's creation time",
  estimated: "date estimated from file times",
};

/** Run picker title: date + result + final time, e.g. "Oct 9, 2026 — Won 21:34.123". */
export function runTitle(r: RunSummary): RunTitle {
  const day = r.recording_date ? shortDate(r.recording_date) : null;
  const estimated = r.date_source === "estimated";
  const date = day ?? r.id;
  const outcome = r.result === "win" ? "Won" : r.result === "loss" ? "Lost" : null;
  const time = r.final_time_text ?? (r.run_end_s != null ? mmss(r.run_end_s) : "?");
  const notes = [
    `Run folder: ${r.id}`,
    r.date_source ? DATE_NOTES[r.date_source] : "no recording date",
    r.final_time_text
      ? r.result === "loss"
        ? "time from the result screen (the winner's time)"
        : "time from the result screen"
      : "no final time read: run end shown",
  ];
  return { date, estimated: estimated && day != null, outcome, time, tooltip: notes.join(" · ") };
}
