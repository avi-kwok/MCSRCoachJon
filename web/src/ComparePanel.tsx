import { useEffect, useRef, useState } from "react";
import type { Route, Tip } from "./types";
import { mmss } from "./format";

/* Minimal typings for the YouTube IFrame Player API (https://www.youtube.com/iframe_api). */
interface YTPlayer {
  playVideo(): void;
  pauseVideo(): void;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  getCurrentTime(): number;
  destroy(): void;
}
interface YTNamespace {
  Player: new (
    el: HTMLElement,
    opts: {
      host?: string;
      videoId: string;
      playerVars?: Record<string, number | string>;
      events?: {
        onReady?: () => void;
        onStateChange?: (e: { data: number }) => void;
        onError?: (e: { data: number }) => void;
      };
    },
  ) => YTPlayer;
}
declare global {
  interface Window {
    YT?: YTNamespace;
    onYouTubeIframeAPIReady?: () => void;
  }
}
const YT_PLAYING = 1;

let apiPromise: Promise<YTNamespace> | null = null;
function loadYouTubeApi(): Promise<YTNamespace> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (apiPromise) return apiPromise;
  apiPromise = new Promise<YTNamespace>((resolve, reject) => {
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      prev?.();
      if (window.YT) resolve(window.YT);
    };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.async = true;
    script.onerror = () => {
      apiPromise = null;
      script.remove();
      reject(new Error("YouTube API failed to load"));
    };
    document.head.appendChild(script);
  });
  return apiPromise;
}

interface Props {
  runVideoSrc: string | null; // null: the run has no playable video
  tip: Tip;
  route: Route;
  onClose: () => void;
}

/** Run video at the tip next to the reference route on YouTube. Start-point sync only. */
export default function ComparePanel({ runVideoSrc, tip, route, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const playerRef = useRef<YTPlayer | null>(null);
  const waitingRef = useRef(false); // local video waits for YouTube to actually start playing
  const [ytReady, setYtReady] = useState(false);
  const [ytFailed, setYtFailed] = useState(false);
  const [playing, setPlaying] = useState(false);
  const start = route.start_s;
  const ytLink = `https://www.youtube.com/watch?v=${route.video_id}&t=${Math.floor(start)}s`;

  useEffect(() => {
    panelRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    loadYouTubeApi()
      .then((YT) => {
        if (cancelled || !hostRef.current) return;
        const mount = document.createElement("div"); // the API replaces this node with its iframe
        hostRef.current.appendChild(mount);
        playerRef.current = new YT.Player(mount, {
          host: "https://www.youtube-nocookie.com",
          videoId: route.video_id,
          playerVars: { start: Math.floor(start), playsinline: 1, rel: 0, modestbranding: 1 },
          events: {
            onReady: () => !cancelled && setYtReady(true),
            onStateChange: (e) => {
              if (e.data !== YT_PLAYING || !waitingRef.current) return;
              // YouTube is rolling: start the run video at the same offset past its start point.
              waitingRef.current = false;
              const v = videoRef.current;
              const yt = playerRef.current;
              if (v && yt) {
                const lag = Math.max(0, yt.getCurrentTime() - start);
                v.currentTime = tip.t_s + lag;
                void v.play().catch(() => {});
              }
            },
            // 101/150: owner disabled embedding; 2/5/100: bad id / not found / HTML5 error.
            onError: () => {
              if (!cancelled) setYtFailed(true);
            },
          },
        });
      })
      .catch(() => !cancelled && setYtFailed(true));
    return () => {
      cancelled = true;
      playerRef.current?.destroy();
      playerRef.current = null;
    };
  }, [route.video_id, start, tip.t_s]);

  const ytUsable = ytReady && !ytFailed && playerRef.current != null;

  const play = () => {
    const v = videoRef.current;
    setPlaying(true);
    if (ytUsable) {
      waitingRef.current = !!v;
      playerRef.current!.playVideo();
    } else if (v) {
      void v.play().catch(() => {});
    }
  };
  const pause = () => {
    waitingRef.current = false;
    setPlaying(false);
    videoRef.current?.pause();
    if (ytUsable) playerRef.current!.pauseVideo();
  };
  const restart = () => {
    pause();
    if (videoRef.current) videoRef.current.currentTime = tip.t_s;
    if (ytUsable) playerRef.current!.seekTo(start, true);
    play();
  };

  return (
    <section className="compare panel" aria-label="Compare with reference route" ref={panelRef}>
      <header className="compare-head">
        <h2 className="compare-title">Compare with reference</h2>
        <button type="button" className="mc-button" onClick={onClose}>
          Close
        </button>
      </header>
      <div className="compare-grid">
        <figure className="compare-pane">
          <figcaption>
            Your run - {tip.title} ({mmss(tip.t_s)})
          </figcaption>
          <div className="compare-video slot">
            {runVideoSrc ? (
              <video
                ref={videoRef}
                src={runVideoSrc}
                controls
                playsInline
                preload="metadata"
                onLoadedMetadata={(e) => {
                  e.currentTarget.currentTime = tip.t_s;
                }}
              />
            ) : (
              <p className="compare-msg">No playable video for this run.</p>
            )}
          </div>
        </figure>
        <figure className="compare-pane">
          <figcaption>
            Reference: {route.id} - {route.type}, {route.entry}
            {route.runner ? ` - ${route.runner}` : ""}
            {route.time ? ` (${route.time})` : ""}
          </figcaption>
          <div className="compare-video slot">
            {ytFailed ? (
              <p className="compare-msg">
                This video can't be embedded here.{" "}
                <a href={ytLink} target="_blank" rel="noopener noreferrer">
                  Open on YouTube at {mmss(start)}
                </a>
              </p>
            ) : (
              <div className="yt-host" ref={hostRef} />
            )}
          </div>
          {route.notes && <p className="compare-notes">{route.notes}</p>}
        </figure>
      </div>
      <div className="compare-controls">
        <button type="button" className="mc-button" onClick={playing ? pause : play}>
          {playing ? "Pause both" : "Play both"}
        </button>
        <button type="button" className="mc-button" onClick={restart}>
          Restart both
        </button>
        <span className="muted compare-hint">
          Starts both together at {mmss(tip.t_s)} / {mmss(start)}; each video keeps its own scrubber.
        </span>
      </div>
    </section>
  );
}
