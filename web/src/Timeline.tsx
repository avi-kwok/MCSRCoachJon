import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { DetailedSegment, Opponent, Span, Split, SplitName, Truth, TruthSplit } from "./types";
import { SEGMENT_TONES, SPLITS } from "./colors";
import { mmss, mmssDec, mmssTenths } from "./format";

interface Props {
  runEnd: number;
  splits: Split[];
  detailed: DetailedSegment[];
  opponent?: Opponent | null;
  truth?: Truth | null; // answer key (truth.csv); adds the Answer Key track when present
  finalTimeText?: string | null; // detected final time / result, checked against the answer key
  result?: string | null;
  currentTime: number; // drives the playhead when there is no video
  duration: number; // seconds that map to the full width (the video's length)
  video: HTMLVideoElement | null;
  selectedSplit: SplitName | null;
  stopAtEnd: boolean;
  onSeek: (t: number) => void;
  onToggleSplit: (name: SplitName) => void; // select + seek to its start, or clear if already selected
  onStopAtEndChange: (on: boolean) => void;
}

interface Hover {
  x: number; // px from the timeline's left edge
  title: string;
  range: string;
  notes?: string;
  delta?: { text: string; ahead: boolean }; // you vs the opponent at this split
  check?: { text: string; tone: Tone }; // detected vs answer key
}

type Tone = "good" | "warn" | "bad";

/** How a detected time compares with the answer key: |Δ| <= 1s good, <= 3s warn, else (or missing) bad. */
interface Check {
  truth: TruthSplit;
  detected: number | null;
  delta: number | null; // detected - truth
  tone: Tone;
}
function check(truth: TruthSplit, detected: number | null): Check {
  const delta = detected == null ? null : detected - truth.t_s;
  const tone: Tone = delta == null ? "bad" : Math.abs(delta) <= 1 ? "good" : Math.abs(delta) <= 3 ? "warn" : "bad";
  return { truth, detected, delta, tone };
}
const checkText = (c: Check) =>
  c.detected == null
    ? `truth ${mmssDec(c.truth.t_s)} · not detected`
    : `truth ${mmssDec(c.truth.t_s)} · detected ${mmssDec(c.detected)} (Δ ${signedSeconds(c.delta!)})`;

const pct = (t: number, duration: number) => `${(100 * Math.min(Math.max(t, 0), duration)) / duration}%`;
// Fallback width of a label in the body font (VT323 at 0.82em: ~6.6px per character, measured),
// used until the real font is measured on a canvas.
const LABEL_PX_PER_CHAR = 7;
const BLOCK_PAD_PX = 12; // .split-block / .segment-block horizontal padding (6px each side)
const LABEL_SLACK_PX = 2; // safety margin so a label never touches the block edge

let measureCtx: CanvasRenderingContext2D | null | undefined;
/** Rendered width of `text` in the block-label font, in px (estimate if canvas is unavailable). */
function labelWidth(text: string, fontPx: number): number {
  if (measureCtx === undefined) measureCtx = document.createElement("canvas").getContext("2d");
  if (!measureCtx) return text.length * LABEL_PX_PER_CHAR;
  measureCtx.font = `${fontPx}px VT323, ui-monospace, monospace`;
  return measureCtx.measureText(text).width;
}

/** "+12.3s" / "−8.1s" (U+2212 minus) */
const signedSeconds = (d: number) => `${d >= 0 ? "+" : "\u2212"}${Math.abs(d).toFixed(1)}s`;

/**
 * Segment timeline. It sits directly under the video at exactly the player's
 * width, so horizontal position = video time. Tracks have no side labels for
 * that reason; their names sit above each bar.
 *
 * The Splits track is also the split selector: click a split to jump to its
 * start and select it, click it again (or press Esc) to clear the selection.
 */
export default function Timeline({
  runEnd,
  splits,
  detailed,
  opponent,
  truth,
  finalTimeText,
  result,
  currentTime,
  duration,
  video,
  selectedSplit,
  stopAtEnd,
  onSeek,
  onToggleSplit,
  onStopAtEndChange,
}: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const playheadRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [hover, setHover] = useState<Hover | null>(null);
  const [labelFontPx, setLabelFontPx] = useState(16.4); // 0.82em of the body font size
  const [, setFontsReady] = useState(0); // bumps once VT323 has loaded so labels are re-measured

  // Track width -> how dense the minute labels can be, and which block labels fit.
  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const measure = () => setLabelFontPx(0.82 * parseFloat(getComputedStyle(el).fontSize || "20"));
    setWidth(el.getBoundingClientRect().width);
    measure();
    const ro = new ResizeObserver(([entry]) => {
      setWidth(entry.contentRect.width);
      measure(); // the body font size changes at the phone breakpoint
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    let alive = true;
    document.fonts?.ready.then(() => alive && setFontsReady((n) => n + 1));
    return () => {
      alive = false;
    };
  }, []);

  // Playhead: follow video.currentTime every animation frame, without re-rendering React.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      if (video && playheadRef.current) {
        playheadRef.current.style.left = pct(video.currentTime, duration);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [video, duration]);
  useEffect(() => {
    if (!video && playheadRef.current) playheadRef.current.style.left = pct(currentTime, duration);
  }, [video, currentTime, duration]);

  const timeAt = (clientX: number) => {
    const rect = rootRef.current!.getBoundingClientRect();
    return (Math.min(Math.max(clientX - rect.left, 0), rect.width) / rect.width) * duration;
  };
  const xAt = (clientX: number) => clientX - rootRef.current!.getBoundingClientRect().left;

  const minutes = Math.floor(duration / 60);
  const pxPerMinute = (width * 60) / duration;
  const labelEvery = [1, 2, 5, 10, 15, 30].find((n) => n * pxPerMinute >= 56) ?? 60;
  const ticks = Array.from({ length: minutes + 1 }, (_, m) => m);

  const widthOf = (b: Span) => `max(2px, ${(100 * (Math.min(b.end_s, duration) - b.start_s)) / duration}%)`;
  const pxOf = (b: Span) => (width * (Math.min(b.end_s, duration) - b.start_s)) / duration;
  const fits = (b: Span, label: string) => pxOf(b) >= labelWidth(label, labelFontPx) + BLOCK_PAD_PX + LABEL_SLACK_PX;
  /** The first label that fits whole in the block, or null (never a clipped half-word). */
  const fittingLabel = (b: Span, ...labels: string[]) => labels.find((l) => fits(b, l)) ?? null;
  const selected = splits.find((s) => s.name === selectedSplit) ?? null;

  const opponentName = opponent?.name?.trim() || null;
  const opponentSplits = (opponent?.splits ?? []).filter((o) => Number.isFinite(o.t_s) && o.t_s >= 0 && o.t_s <= duration);
  const splitInfo = (name: string) => SPLITS.find((x) => x.name === name);

  // Answer key: each truth split matched by name to the detected split / opponent split.
  const truthChecks = (truth?.splits ?? [])
    .filter((t) => Number.isFinite(t.t_s) && t.t_s >= 0 && t.t_s <= duration)
    .map((t) => check(t, splits.find((s) => s.name === t.name)?.start_s ?? null));
  const oppTruthChecks = (truth?.opponent_splits ?? [])
    .filter((t) => Number.isFinite(t.t_s) && t.t_s >= 0 && t.t_s <= duration)
    .map((t) => check(t, opponent?.splits?.find((o) => o.name === t.name && Number.isFinite(o.t_s))?.t_s ?? null));
  const truthByName = new Map(truthChecks.map((c) => [c.truth.name, c]));

  const splitsTrack = (
    <div className="track">
      <div className="track-head">
        <span className="track-label">
          Splits
          {(opponentName || opponentSplits.length > 0) && (
            <span className="track-vs">vs {opponentName ?? "Opponent"}</span>
          )}
        </span>
        {selected && (
          <button
            type="button"
            className="mc-check"
            role="checkbox"
            aria-checked={stopAtEnd}
            onClick={(e) => {
              e.stopPropagation();
              onStopAtEndChange(!stopAtEnd);
            }}
            onMouseMove={(e) => e.stopPropagation()}
          >
            <span className="mc-check-box" aria-hidden>
              {stopAtEnd ? "✔" : ""}
            </span>
            Stop at split end
          </button>
        )}
      </div>
      <div className={`track-bar slot ${selected ? "has-selection" : ""}`}>
        {splits.map((s) => {
          const info = splitInfo(s.name);
          const label = info?.label ?? s.name;
          const shown = fittingLabel(s, label, info?.short ?? label);
          const isSel = s.name === selectedSplit;
          const opp = opponent?.splits?.find((o) => o.name === s.name && Number.isFinite(o.t_s));
          const d = opp ? s.start_s - opp.t_s : null;
          return (
            <button
              key={s.name}
              type="button"
              className={`block split-block ${isSel ? "selected" : ""}`}
              style={{ left: pct(s.start_s, duration), width: widthOf(s), background: info?.color, color: info?.ink }}
              aria-label={`${label} ${mmss(s.start_s)} to ${mmss(s.end_s)}${isSel ? " (selected, click to clear)" : ""}`}
              aria-pressed={isSel}
              onClick={(e) => {
                e.stopPropagation();
                onToggleSplit(s.name);
              }}
              onMouseMove={(e) => {
                e.stopPropagation();
                setHover({
                  x: xAt(e.clientX),
                  title: label,
                  range: `${mmss(s.start_s)} - ${mmss(s.end_s)}`,
                  notes: isSel ? "Click again or press Esc to clear" : "Click to watch this split",
                  delta: d == null ? undefined : { text: `You ${signedSeconds(d)}`, ahead: d < 0 },
                  check: !truth
                    ? undefined
                    : truthByName.has(s.name)
                      ? (() => {
                          const c = truthByName.get(s.name)!;
                          return { text: `Answer key: Δ ${signedSeconds(c.delta!)}`, tone: c.tone };
                        })()
                      : { text: "? not in answer key", tone: "bad" },
                });
              }}
            >
              {shown && <span className="split-name">{shown}</span>}
            </button>
          );
        })}
        {opponentSplits.map((o, i) => {
          const label = splitInfo(o.name)?.label ?? o.raw ?? o.name;
          const title = `${opponentName ?? "Opponent"}: ${label} at ${mmss(o.t_s)}`;
          return (
            <button
              key={`opp-${i}`}
              type="button"
              className="opp-marker"
              style={{ left: pct(o.t_s, duration) }}
              aria-label={`${title}, jump there`}
              onClick={(e) => {
                e.stopPropagation();
                onSeek(o.t_s);
              }}
              onMouseMove={(e) => {
                e.stopPropagation();
                setHover({ x: xAt(e.clientX), title: `${opponentName ?? "Opponent"}:`, range: `${label} at ${mmss(o.t_s)}` });
              }}
            >
              <i className="opp-flag" aria-hidden />
            </button>
          );
        })}
        {oppTruthChecks.map((c, i) => {
          const label = splitInfo(c.truth.name)?.label ?? c.truth.name;
          const who = opponentName ?? "Opponent";
          return (
            <button
              key={`opp-truth-${i}`}
              type="button"
              className="opp-marker opp-truth"
              style={{ left: pct(c.truth.t_s, duration) }}
              aria-label={`${who} answer key: ${label}, ${checkText(c)}, jump there`}
              onClick={(e) => {
                e.stopPropagation();
                onSeek(c.truth.t_s);
              }}
              onMouseMove={(e) => {
                e.stopPropagation();
                setHover({
                  x: xAt(e.clientX),
                  title: `${who} (answer key):`,
                  range: label,
                  check: { text: checkText(c), tone: c.tone },
                  notes: c.truth.notes || undefined,
                });
              }}
            >
              <i className="opp-flag" aria-hidden />
            </button>
          );
        })}
        {splits.length === 0 && <span className="track-empty">No splits detected</span>}
      </div>
      <div className="split-range-row" aria-hidden>
        {selected && (
          <div className="split-range" style={{ left: pct(selected.start_s, duration), width: widthOf(selected) }} />
        )}
      </div>
    </div>
  );

  const within1 = truthChecks.filter((c) => c.tone === "good").length;
  const missed = truthChecks.filter((c) => c.detected == null).length;
  const extra = splits.filter((s) => !truthByName.has(s.name)).length;
  const isDraft = (truth?.status ?? "").toLowerCase() === "draft";
  const finalCheck =
    truth?.final_time_text || truth?.result
      ? {
          ok:
            (!truth.final_time_text || truth.final_time_text === finalTimeText) &&
            (!truth.result || truth.result === result),
          text: `Answer key: ${[truth.result, truth.final_time_text].filter(Boolean).join(" ")} · detected: ${
            [result, finalTimeText].filter(Boolean).join(" ") || "none"
          }`,
        }
      : null;

  const truthTrack = truth && (
    <div className="track truth-track">
      <div className="track-head">
        <span className="track-label">
          Answer Key
          {truth.status && (
            <span className={isDraft ? "truth-draft" : "truth-status"}>
              {isDraft ? " (draft — verify)" : ` (${truth.status})`}
            </span>
          )}
        </span>
        <span className="truth-summary" onMouseMove={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
          <span
            className={`truth-score tone-${truthChecks.length && within1 === truthChecks.length ? "good" : "warn"}`}
            title="Answer-key splits whose detected start is within 1 s"
          >
            {within1}/{truthChecks.length} within 1s
          </span>
          {missed > 0 && <span className="tone-bad"> · {missed} missed</span>}
          {extra > 0 && (
            <span className="tone-bad" title="Detected splits that are not in the answer key">
              {" "}
              · {extra} extra
            </span>
          )}
          {finalCheck && (
            <span className={finalCheck.ok ? "tone-good" : "tone-bad"} title={finalCheck.text}>
              {" "}
              · final {finalCheck.ok ? "✔" : "✘"}
            </span>
          )}
        </span>
      </div>
      <div className="track-bar slot truth-bar">
        {truthChecks.map((c, i) => {
          const info = splitInfo(c.truth.name);
          const label = info?.label ?? c.truth.name;
          const short = info?.short ?? c.truth.name;
          // Label to the right of the tick, only if it fits before the next tick (or the end).
          const next = truthChecks[i + 1]?.truth.t_s ?? duration;
          const room = (width * (next - c.truth.t_s)) / duration;
          const shown = room >= labelWidth(short, labelFontPx) + 14 ? short : null;
          return (
            <button
              key={`truth-${i}`}
              type="button"
              className={`truth-marker tone-${c.tone}`}
              style={{ left: pct(c.truth.t_s, duration) }}
              aria-label={`Answer key ${label}: ${checkText(c)}. Jump to the answer-key time`}
              onClick={(e) => {
                e.stopPropagation();
                onSeek(c.truth.t_s);
              }}
              onMouseMove={(e) => {
                e.stopPropagation();
                setHover({
                  x: xAt(e.clientX),
                  title: `${label} —`,
                  range: "",
                  check: { text: checkText(c), tone: c.tone },
                  notes: [c.truth.notes, "Click to jump there"].filter(Boolean).join(" · "),
                });
              }}
            >
              <i className="truth-tick" aria-hidden />
              <i className="truth-pip" aria-hidden />
              {shown && <span className="truth-name">{shown}</span>}
            </button>
          );
        })}
        {truthChecks.length === 0 && <span className="track-empty">No splits in truth.csv</span>}
      </div>
    </div>
  );

  const detailedTrack = (
    <div className="track">
      <div className="track-head">
        <span className="track-label">Detailed Segments</span>
      </div>
      <div className="track-bar slot">
        {detailed.map((b, i) => {
          const tone = SEGMENT_TONES[i % SEGMENT_TONES.length];
          const range = `${mmssTenths(b.start_s)} - ${mmssTenths(b.end_s)}`;
          return (
            <button
              key={i}
              type="button"
              className="block segment-block"
              style={{ left: pct(b.start_s, duration), width: widthOf(b), background: tone.color, color: tone.ink }}
              aria-label={`${b.name} ${range}${b.notes ? `: ${b.notes}` : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                onSeek(b.start_s);
              }}
              onMouseMove={(e) => {
                e.stopPropagation();
                setHover({ x: xAt(e.clientX), title: b.name, range, notes: b.notes || undefined });
              }}
            >
              {fittingLabel(b, b.name) && <span className="split-name">{b.name}</span>}
            </button>
          );
        })}
        {detailed.length === 0 && (
          <span className="track-empty">No detailed segments yet — add detailed_segments.csv to this run</span>
        )}
      </div>
    </div>
  );

  return (
    <div className="timeline">
      <div
        className="timeline-area"
        ref={rootRef}
        onClick={(e) => onSeek(timeAt(e.clientX))}
        onMouseMove={(e) => setHover({ x: xAt(e.clientX), title: "Jump to", range: mmss(timeAt(e.clientX)) })}
        onMouseLeave={() => setHover(null)}
      >
        {splitsTrack}
        {truthTrack}
        {detailedTrack}

        <div className="ticks" aria-hidden>
          {ticks.map((m) => (
            <div key={m} className={`tick ${m % labelEvery === 0 ? "major" : ""}`} style={{ left: pct(m * 60, duration) }}>
              {m % labelEvery === 0 && <span>{m}:00</span>}
            </div>
          ))}
        </div>

        {runEnd < duration && (
          <div
            className="after-end"
            style={{ left: pct(runEnd, duration), width: `${(100 * (duration - runEnd)) / duration}%` }}
            title={`After run end (${mmss(runEnd)})`}
          />
        )}
        <div className="playhead" ref={playheadRef} aria-hidden />

        {hover && (
          <div className="tooltip" style={{ left: Math.min(Math.max(hover.x, 110), width - 110) }}>
            <div>
              <strong>{hover.title}</strong> {hover.range}
              {hover.check && !hover.range && <span className={`tone-${hover.check.tone}`}>{hover.check.text}</span>}
            </div>
            {hover.check && hover.range && <div className={`tone-${hover.check.tone}`}>{hover.check.text}</div>}
            {hover.delta && (
              <div className={hover.delta.ahead ? "tooltip-ahead" : "tooltip-behind"}>
                {hover.delta.text} vs {opponentName ?? "opponent"}
              </div>
            )}
            {hover.notes && <div className="tooltip-notes">{hover.notes}</div>}
          </div>
        )}
      </div>

      {(runEnd < duration || opponentSplits.length > 0 || truth) && (
        <div className="legend">
          {opponentSplits.length > 0 && (
            <span className="legend-item">
              <i className="opp-legend" />
              {opponentName ?? "Opponent"}'s splits
            </span>
          )}
          {oppTruthChecks.length > 0 && (
            <span className="legend-item">
              <i className="opp-legend hollow" />
              {opponentName ?? "Opponent"} (answer key)
            </span>
          )}
          {truth && (
            <span className="legend-item">
              <i className="truth-legend" />
              Answer key: Δ <span className="tone-good">≤1s</span> <span className="tone-warn">≤3s</span>{" "}
              <span className="tone-bad">more / missed</span>
            </span>
          )}
          {runEnd < duration && (
            <span className="legend-item">
              <i className="hatch" />
              After run end
            </span>
          )}
        </div>
      )}
    </div>
  );
}
