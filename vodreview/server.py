"""Local web server for the review UI:  python -m vodreview serve [--runs runs/] [--port 8000]

A "run" is a subfolder of the runs root holding analysis.json + video.mp4
(made by `python -m vodreview analyze <video> --out runs/<name>`).

API:
  GET /api/runs              list of runs
  GET /api/runs/{id}         that run's analysis.json, plus "detailed_segments" read live
                             from runs/{id}/detailed_segments.csv (user-authored; [] if absent)
  GET /api/runs/{id}/video   video.mp4 (supports HTTP Range requests, so seeking works)
Everything else is the built frontend from web/dist.
"""

import json
import re
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .report import read_detailed_segments

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def create_app(runs_root):
    runs_root = Path(runs_root).resolve()
    app = FastAPI(title="MCSR Coach Jon", docs_url=None, redoc_url=None, openapi_url=None)

    def run_dir(run_id):
        """Resolve a run id to its folder; reject anything that could escape the runs root."""
        if not RUN_ID.match(run_id) or ".." in run_id:
            raise HTTPException(404, "Run not found")
        path = (runs_root / run_id).resolve()
        if path.parent != runs_root or not (path / "analysis.json").is_file():
            raise HTTPException(404, "Run not found")
        return path

    def load(path):
        return json.loads((path / "analysis.json").read_text())

    @app.get("/api/runs")
    def list_runs():
        runs = []
        if runs_root.is_dir():
            for child in sorted(runs_root.iterdir()):
                if not (RUN_ID.match(child.name) and (child / "analysis.json").is_file()):
                    continue
                try:
                    run = load(child)["run"]
                except (ValueError, KeyError):
                    continue
                runs.append({
                    "id": child.name,
                    "video_name": Path(run.get("video", "")).name,
                    "result": run.get("result"),
                    "run_end_s": run.get("run_end_s"),
                    "final_time_text": run.get("final_time_text"),
                    "final_time_ms": run.get("final_time_ms"),
                    "recording_date": run.get("recording_date"),
                    "date_source": run.get("date_source"),
                    "analyzed_at": run.get("analyzed_at"),
                    "has_video": (child / "video.mp4").is_file(),
                })
        # Newest recording first; runs without a date (old run.json) go last.
        runs.sort(key=lambda r: (r["recording_date"] or "", r["analyzed_at"] or ""), reverse=True)
        return runs

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        path = run_dir(run_id)
        analysis = load(path)
        segments, warnings = read_detailed_segments(path / "detailed_segments.csv")
        for warning in warnings:
            print(f"Warning ({run_id}): {warning}", file=sys.stderr)
        analysis["detailed_segments"] = segments
        return JSONResponse(analysis)

    @app.get("/api/runs/{run_id}/video")
    def get_video(run_id: str):
        video = run_dir(run_id) / "video.mp4"
        if not video.is_file():
            raise HTTPException(404, "No video.mp4 for this run (analyzed with --no-video?)")
        return FileResponse(video, media_type="video/mp4")

    @app.get("/api/{rest:path}")
    def api_not_found(rest: str):
        raise HTTPException(404, "Not found")

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    else:
        @app.get("/")
        def no_frontend():
            return JSONResponse({"error": "Frontend not built. Run: cd web && npm install && npm run build"},
                                status_code=503)
    return app


def serve(runs_root, port=8000):
    import uvicorn
    print(f"Serving runs from {Path(runs_root).resolve()} at http://127.0.0.1:{port}/")
    uvicorn.run(create_app(runs_root), host="127.0.0.1", port=port, log_level="warning")
