import type { Tip } from "./types";
import { mmss } from "./format";

interface Props {
  tips: Tip[];
  currentTime: number;
  onSeek: (t: number) => void;
}

const KIND_LABEL: Record<string, string> = { stat: "Stat", micro: "Micro", macro: "Macro", risk: "Risk" };
const POINT_WINDOW_S = 3; // a tip at a single moment counts as "now" for this long

function isActive(tip: Tip, t: number) {
  if (tip.t_s === 0 && tip.end_s === 0) return false; // summary with no moment in the video
  const end = Math.max(tip.end_s, tip.t_s + (tip.end_s > tip.t_s ? 0 : POINT_WINDOW_S));
  return t >= tip.t_s && t < end;
}

export default function Tips({ tips, currentTime, onSeek }: Props) {
  if (tips.length === 0) {
    return <p className="muted">No feedback for this run.</p>;
  }
  return (
    <ol className="tips">
      {tips.map((tip, i) => (
        <li key={i}>
          <button
            type="button"
            className={`tip panel ${isActive(tip, currentTime) ? "active" : ""}`}
            onClick={() => onSeek(tip.t_s)}
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
            {tip.est_loss_s != null && tip.est_loss_s > 0 && (
              <span className="tip-loss">~{tip.est_loss_s.toFixed(1)}s lost</span>
            )}
          </button>
        </li>
      ))}
    </ol>
  );
}
