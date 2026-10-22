import { useEffect, useRef } from "react";
import type { Route, Tip } from "./types";
import { mmss } from "./format";

interface Props {
  tips: Tip[];
  currentTime: number;
  selected: number | null; // index of the tip picked here or on the timeline's Tips track
  onSelect: (index: number) => void; // seek + highlight
  routes: Map<string, Route>; // route library by id
  onCompare: (index: number) => void; // open the side-by-side reference panel
}

const KIND_LABEL: Record<string, string> = { stat: "Stat", micro: "Micro", macro: "Macro", risk: "Risk" };
const POINT_WINDOW_S = 3; // a tip at a single moment counts as "now" for this long

function isActive(tip: Tip, t: number) {
  if (tip.t_s === 0 && tip.end_s === 0) return false; // summary with no moment in the video
  const end = Math.max(tip.end_s, tip.t_s + (tip.end_s > tip.t_s ? 0 : POINT_WINDOW_S));
  return t >= tip.t_s && t < end;
}

export default function Tips({ tips, currentTime, selected, onSelect, routes, onCompare }: Props) {
  const listRef = useRef<HTMLOListElement>(null);
  // A tip picked on the timeline scrolls into view in the list.
  useEffect(() => {
    if (selected == null) return;
    listRef.current?.children[selected]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);
  if (tips.length === 0) {
    return <p className="muted">No feedback for this run.</p>;
  }
  return (
    <ol className="tips" ref={listRef}>
      {tips.map((tip, i) => {
        const route = tip.coach?.reference_route ? routes.get(tip.coach.reference_route) : undefined;
        return (
        <li key={i}>
          <button
            type="button"
            className={`tip panel ${isActive(tip, currentTime) ? "active" : ""} ${selected === i ? "selected" : ""}`}
            aria-pressed={selected === i}
            onClick={() => onSelect(i)}
            title={`Jump to ${mmss(tip.t_s)}`}
          >
            <span className="tip-head">
              <span className={`badge kind-${tip.kind}`}>{KIND_LABEL[tip.kind] ?? tip.kind}</span>
              <span className="tip-time">
                {mmss(tip.t_s)}
                {tip.end_s > tip.t_s ? `-${mmss(tip.end_s)}` : ""}
              </span>
            </span>
            <span className="tip-title">{tip.title}</span>
            <span className="tip-text">{tip.text}</span>
            {tip.coach && (
              <span className="tip-coach">
                <span className="badge coach-tag">{tip.coach.kind}</span>
                <span className={`badge fix-${tip.coach.fix_type}`}>
                  {tip.coach.fix_type === "easy" ? "easy fix" : "practice"}
                </span>
                {tip.coach.catalogue_id && <span className="badge coach-tag">{tip.coach.catalogue_id}</span>}
                {tip.coach.disagrees_with_catalogue && (
                  <span className="badge coach-disagree" title={tip.coach.disagrees_with_catalogue.reason}>
                    disagrees: {tip.coach.disagrees_with_catalogue.id}
                  </span>
                )}
              </span>
            )}
            {tip.coach && <span className="tip-text tip-known">Known then: {tip.coach.known_at_time}</span>}
            {tip.est_loss_s != null && tip.est_loss_s > 0 && (
              <span className="tip-loss">
                ~{tip.est_loss_s.toFixed(1)}s lost{tip.coach ? ` (${tip.coach.confidence} confidence)` : ""}
              </span>
            )}
          </button>
          {route && (
            <button
              type="button"
              className="mc-button tip-compare"
              onClick={() => onCompare(i)}
              title={`${route.type} - ${route.entry}${route.runner ? ` (${route.runner})` : ""}`}
            >
              Compare with reference
            </button>
          )}
        </li>
        );
      })}
    </ol>
  );
}
