import { useCallback, useEffect, useRef, useState } from "react";
import { getRoutes, getRun, listRuns, videoUrl } from "./api";
import type { Analysis, Route, RunSummary, SplitName, Tip } from "./types";
import Timeline from "./Timeline";
import RunPicker from "./RunPicker";
import Tips from "./Tips";
import CoachPanel from "./CoachPanel";
import Digest from "./Digest";
import ComparePanel from "./ComparePanel";

const hashParam = (key: string) => new URLSearchParams(window.location.hash.slice(1)).get(key);

export default function App() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [runId, setRunId] = useState<string | null>(hashParam("run"));
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [videoDuration, setVideoDuration] = useState<number | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [selectedSplit, setSelectedSplit] = useState<SplitName | null>(null);
  const [stopAtEnd, setStopAtEnd] = useState(false);
  const [selectedTip, setSelectedTip] = useState<number | null>(null); // index into analysis.tips
  const [digestVersion, setDigestVersion] = useState(0);
  const [videoFailed, setVideoFailed] = useState(false); // video.mp4 missing / broken link
  const [routes, setRoutes] = useState<Map<string, Route>>(new Map());
  const [compareTip, setCompareTip] = useState<number | null>(null); // tip shown in the compare panel
  // A split named in the page URL (#run=..&split=..) is selected once its run loads.
  const pendingSplit = useRef<string | null>(hashParam("split"));

  useEffect(() => {
    listRuns()
      .then((list) => {
        setRuns(list);
        setRunId((id) => (id && list.some((r) => r.id === id) ? id : list[0]?.id ?? null));
      })
      .catch((e) => setError(String(e)));
    getRoutes()
      .then(({ routes: list, errors }) => {
        setRoutes(new Map(list.map((r) => [r.id, r])));
        if (errors.length) console.warn("knowledge/routes.md:", errors);
      })
      .catch(() => {}); // the library is optional
  }, []);

  useEffect(() => {
    if (!runId) return;
    setAnalysis(null);
    setSelectedSplit(null);
    setSelectedTip(null);
    setCompareTip(null);
    setVideoDuration(null);
    setVideoFailed(false);
    setCurrentTime(0);
    getRun(runId)
      .then((a) => {
        const splits = a.splits ?? [];
        setAnalysis({ ...a, splits });
        const wanted = splits.find((s) => s.name === pendingSplit.current);
        pendingSplit.current = null;
        if (wanted) setSelectedSplit(wanted.name);
      })
      .catch((e) => setError(String(e)));
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    const split = selectedSplit ? `&split=${encodeURIComponent(selectedSplit)}` : "";
    window.history.replaceState(null, "", `#run=${encodeURIComponent(runId)}${split}`);
  }, [runId, selectedSplit]);

  const seek = useCallback(
    (t: number) => {
      if (video) video.currentTime = t; // without a video the playhead + tips still follow
      setCurrentTime(t);
    },
    [video],
  );

  const tips = analysis?.tips ?? [];
  const selectTip = useCallback(
    (i: number) => {
      const tip = tips[i];
      if (!tip) return;
      setSelectedTip(i);
      seek(tip.t_s);
    },
    [tips, seek],
  );
  const setTips = useCallback((next: Tip[]) => {
    setAnalysis((a) => (a ? { ...a, tips: next } : a));
    setSelectedTip(null);
    setCompareTip(null);
  }, []);
  const bumpDigest = useCallback(() => setDigestVersion((v) => v + 1), []);

  const splits = analysis?.splits ?? [];
  const selected = splits.find((s) => s.name === selectedSplit) ?? null;

  const selectSplit = useCallback(
    (name: SplitName) => {
      const split = splits.find((s) => s.name === name);
      if (!split) return;
      setSelectedSplit(name);
      seek(split.start_s);
    },
    [splits, seek],
  );
  const toggleSplit = (name: SplitName) => (name === selectedSplit ? setSelectedSplit(null) : selectSplit(name));

  // Esc clears the selected split (the run dropdown handles its own Esc first).
  useEffect(() => {
    if (!selectedSplit) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) setSelectedSplit(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedSplit]);

  // "Stop at split end": pause when playback crosses the selected split's end.
  // Checked every animation frame (timeupdate only fires ~4x a second).
  useEffect(() => {
    if (!video || !selected || !stopAtEnd) return;
    const end = selected.end_s;
    let prev = video.currentTime;
    let raf = 0;
    const tick = () => {
      const t = video.currentTime;
      if (!video.paused && prev < end && t >= end) {
        video.pause();
        video.currentTime = end;
      }
      prev = t;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [video, selected, stopAtEnd]);

  const run = runs?.find((r) => r.id === runId);
  const openCompare = useCallback(
    (i: number) => {
      video?.pause(); // the panel has its own copy of the run video
      setCompareTip(i);
    },
    [video],
  );
  const compare = compareTip != null ? tips[compareTip] : undefined;
  const compareRoute = compare?.coach?.reference_route ? routes.get(compare.coach.reference_route) : undefined;
  // The timeline maps the video's real length to its full width; until the
  // video's metadata loads, fall back to the analyzed duration.
  const duration = videoDuration ?? analysis?.run.duration_s ?? 1;

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="title">MCSR Coach Jon</h1>
        <RunPicker runs={runs} value={runId} onChange={setRunId} />
      </header>

      <main className="content">
        {error && <div className="panel notice error">{error}</div>}

        {runs?.length === 0 && (
          <div className="panel notice">
            <h2>No runs yet</h2>
            <p>Analyze a recording, then reload this page:</p>
            <code>python -m vodreview analyze "VOD.mkv" --out runs/my-run</code>
          </div>
        )}

        {analysis && runId && (
          <>
            <section className="review panel" aria-label="Video review">
              <div className="player slot">
                {run?.has_video === false || videoFailed ? (
                  <div className="no-video">
                    <div>
                      <h2 className="no-video-title">Video not available</h2>
                      <p>
                        No playable video.mp4 in runs/{runId}/ (analyzed with <span className="nowrap">--no-video</span>, or its link
                        points nowhere). The timeline and feedback still work.
                      </p>
                    </div>
                  </div>
                ) : (
                  <video
                    key={runId}
                    ref={setVideo}
                    src={videoUrl(runId)}
                    controls
                    preload="metadata"
                    onLoadedMetadata={(e) => {
                      const d = e.currentTarget.duration;
                      if (Number.isFinite(d) && d > 0) setVideoDuration(d);
                      if (selected) e.currentTarget.currentTime = selected.start_s; // split from the URL
                    }}
                    onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
                    onError={() => {
                      setVideoFailed(true);
                      setVideo(null);
                    }}
                  />
                )}
              </div>
              <Timeline
                runEnd={analysis.run.run_end_s}
                splits={splits}
                detailed={analysis.detailed_segments ?? []}
                tips={tips}
                selectedTip={selectedTip}
                onSelectTip={selectTip}
                opponent={analysis.opponent}
                truth={analysis.truth}
                finalTimeText={analysis.run.final_time_text}
                result={analysis.run.result}
                currentTime={currentTime}
                duration={duration}
                video={video}
                selectedSplit={selectedSplit}
                stopAtEnd={stopAtEnd}
                onSeek={seek}
                onToggleSplit={toggleSplit}
                onStopAtEndChange={setStopAtEnd}
              />
            </section>

            {compare && compareRoute && (
              <ComparePanel
                key={`${runId}-${compareTip}`}
                runVideoSrc={run?.has_video === false || videoFailed ? null : videoUrl(runId)}
                tip={compare}
                route={compareRoute}
                onClose={() => setCompareTip(null)}
              />
            )}

            <section className="feedback" aria-label="Feedback">
              <h2 className="section-title">Feedback</h2>
              <Tips
                tips={tips}
                currentTime={currentTime}
                selected={selectedTip}
                onSelect={selectTip}
                routes={routes}
                onCompare={openCompare}
              />
              <CoachPanel runId={runId} onTipsImported={setTips} onDigestChanged={bumpDigest} />
              <Digest runId={runId} version={digestVersion} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
