import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { DetailedSegment, Span, Split, SplitName } from "./types";
import { SEGMENT_TONES, SPLITS } from "./colors";
import { mmss, mmssTenths } from "./format";

interface Props {
  runEnd: number;
  splits: Split[];
  detailed: DetailedSegment[];
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
}

const pct = (t: number, duration: number) => `${(100 * Math.min(Math.max(t, 0), duration)) / duration}%`;
// Rough width of a label in the body font (VT323 at 0.82em: ~6.6px per character, measured).
const LABEL_PX_PER_CHAR = 7;

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

  // Track width -> how dense the minute labels can be, and which block labels fit.
  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
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
  const fits = (b: Span, label: string) => pxOf(b) >= label.length * LABEL_PX_PER_CHAR + 12;
  const selected = splits.find((s) => s.name === selectedSplit) ?? null;

  const splitsTrack = (
    <div className="track">
      <div className="track-head">
        <span className="track-label">Splits</span>
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
          const info = SPLITS.find((x) => x.name === s.name);
          const label = info?.label ?? s.name;
          const isSel = s.name === selectedSplit;
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
                });
              }}
            >
              <span className="split-name">{label}</span>
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
              {fits(b, b.name) && <span className="split-name">{b.name}</span>}
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
            </div>
            {hover.notes && <div className="tooltip-notes">{hover.notes}</div>}
          </div>
        )}
      </div>

      {runEnd < duration && (
        <div className="legend">
          <span className="legend-item">
            <i className="hatch" />
            After run end
          </span>
        </div>
      )}
    </div>
  );
}
