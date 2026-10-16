"""Local web server for the review UI:  python -m vodreview serve [--runs runs/] [--port 8000]

A "run" is a subfolder of the runs root holding analysis.json + video.mp4
(made by `python -m vodreview analyze <video> --out runs/<name>`).

API:
  GET /api/runs              list of runs
  GET /api/runs/{id}         that run's analysis.json, plus "detailed_segments" read live
                             from runs/{id}/detailed_segments.csv (user-authored; [] if absent)
                             and "truth", the answer key from runs/{id}/truth.csv (null if absent)
  GET /api/runs/{id}/video   video.mp4 (supports HTTP Range requests, so seeking works)
Everything else is the built frontend from web/dist.
"""

import csv
import json
import re
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .report import parse_clock, read_detailed_segments

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def read_truth(path):
    """Read runs/<id>/truth.csv (the hand-checked answer key) -> (truth or None, warnings).

    Columns: kind,name,time,notes. kind is meta (name=status, time=draft/verified...),
    split / opponent (name = split name, time = m:ss(.s), h:mm:ss or seconds) or
    final (name=final_time -> time text as written; name=result -> win/loss).
    Malformed rows are skipped with a warning.
    """
    path = Path(path)
    if not path.is_file():
        return None, []
    truth = {"status": None, "splits": [], "final_time_text": None, "result": None, "opponent_splits": []}
    warnings = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fields = {(name or "").strip().lower() for name in (reader.fieldnames or [])}
            if not {"kind", "name", "time"} <= fields:
                return None, [f"{path.name}: header must be kind,name,time,notes (got {reader.fieldnames})"]
            for line, row in enumerate(reader, 2):
                row = {(k or "").strip().lower(): (v or "").strip() if isinstance(v, str) else "" for k, v in row.items()}
                kind, name, value = row.get("kind", "").lower(), row.get("name", ""), row.get("time", "")
                try:
                    if kind == "meta":
                        if name.lower() == "status":
                            truth["status"] = value or None
                    elif kind == "final":
                        if name.lower() == "final_time":
                            truth["final_time_text"] = value or None
                        elif name.lower() == "result":
                            truth["result"] = value.lower() or None
                        else:
                            raise ValueError(f"unknown final row {name!r}")
                    elif kind in ("split", "opponent"):
                        if not name:
                            raise ValueError("no split name")
                        entry = {"name": name, "t_s": round(parse_clock(value), 3), "notes": row.get("notes", "")}
                        truth["splits" if kind == "split" else "opponent_splits"].append(entry)
                    else:
                        raise ValueError(f"unknown kind {kind!r}")
                except ValueError as err:
                    warnings.append(f"{path.name} line {line}: {err} - skipped")
    except (OSError, UnicodeDecodeError, csv.Error) as err:
        return None, [f"{path.name}: could not read ({err})"]
    truth["splits"].sort(key=lambda s: s["t_s"])
    truth["opponent_splits"].sort(key=lambda s: s["t_s"])
    return truth, warnings


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
                if not (RUN_ID.match(child.name) and child.resolve().parent == runs_root
                        and (child / "analysis.json").is_file()):
                    continue  # still being analyzed (no analysis.json yet) or not a run
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
        truth, warnings = read_truth(path / "truth.csv")
        for warning in warnings:
            print(f"Warning ({run_id}): {warning}", file=sys.stderr)
        analysis["truth"] = truth
        return JSONResponse(analysis)

    @app.get("/api/runs/{run_id}/video")
    def get_video(run_id: str):
        # The run folder must sit inside the runs root (checked by run_dir), but its video.mp4
        # may be a symlink/hardlink to a recording stored anywhere: follow it.
        video = (run_dir(run_id) / "video.mp4").resolve()
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
