"""Local web server for the review UI:  python -m vodreview serve [--runs runs/] [--port 8000]

A "run" is a subfolder of the runs root holding analysis.json + video.mp4
(made by `python -m vodreview analyze <video> --out runs/<name>`).

API:
  GET /api/runs              list of runs
  GET /api/runs/{id}         that run's analysis.json, plus "detailed_segments" read live
                             from runs/{id}/detailed_segments.csv (user-authored; [] if absent)
                             and "truth", the answer key from runs/{id}/truth.csv (null if absent)
  GET /api/runs/{id}/video   video.mp4 (supports HTTP Range requests, so seeking works)
  GET/PUT /api/runs/{id}/context   learner context.md as {values: {key: text}, extra: text}
  GET /api/runs/{id}/digest        digest.md text (built if missing)
  POST /api/runs/{id}/coach-pack   rebuild digest.md + coach_prompt.md, return the prompt text
  POST /api/runs/{id}/tips         {reply}: Claude's raw reply (```json block extracted),
                                   validated + stored like `import-tips`
Everything else is the built frontend from web/dist.
"""

import contextlib
import csv
import io
import json
import re
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import coach
from . import routes as route_lib
from .digest import CONTEXT_KEYS, write_digest
from .report import parse_clock, read_detailed_segments

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CONTEXT_VALUE_MAX = 500        # chars per context.md key
CONTEXT_EXTRA_MAX = 8000       # chars of free-form learner notes
REPLY_MAX = 512 * 1024         # pasted coach reply
CONTEXT_HEADER = "# Learner context for the coach (key: value). Edited in the review UI."
_STDOUT_LOCK = threading.Lock()  # the coach/digest helpers print; capture one call at a time


def _quiet(fn, *args):
    """Run a CLI helper, capturing what it prints. SystemExit (its error path) -> ValueError."""
    buf = io.StringIO()
    with _STDOUT_LOCK, contextlib.redirect_stdout(buf):
        try:
            result = fn(*args)
        except SystemExit as err:
            raise ValueError(str(err.code) if err.code is not None else "failed") from None
    return result, buf.getvalue()


def _context_key(line):
    """Normalized key of a context.md line, like digest.read_context (None for non key lines)."""
    line = line.strip().lstrip("-* ").strip()
    if not line or line.startswith("#") or ":" not in line:
        return None
    return line.split(":", 1)[0].strip().lower().replace(" ", "_").replace("-", "_") or None


def read_context_file(path):
    """context.md -> {"values": {known key: value}, "extra": every other line, verbatim}."""
    values, extra = {}, []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key = _context_key(line)
            if line.strip() == CONTEXT_HEADER:
                continue
            if key in CONTEXT_KEYS:
                value = line.split(":", 1)[1].strip()
                if value:
                    values[key] = value
            else:
                extra.append(line)
    return {"values": values, "extra": "\n".join(extra).strip()}


def extract_reply_json(reply):
    """The JSON in a pasted coach reply: the last ```json fence, else any ``` fence, else the raw text."""
    fences = re.findall(r"```[ \t]*json[^\n]*\n(.*?)```", reply, flags=re.S | re.I)
    if not fences:
        fences = [f for f in re.findall(r"```[^\n]*\n(.*?)```", reply, flags=re.S) if f.strip()[:1] in "[{"]
    if fences:
        return fences[-1].strip()
    text = reply.strip()
    if text[:1] not in "[{":  # prose around a bare object: take the outermost braces
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return text[start:end + 1]
    return text


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
                    "private_room": run.get("private_room"),
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

    @app.get("/api/runs/{run_id}/context")
    def get_context(run_id: str):
        out = read_context_file(run_dir(run_id) / "context.md")
        out["keys"] = CONTEXT_KEYS
        return out

    @app.put("/api/runs/{run_id}/context")
    def put_context(run_id: str, body: dict = Body(...)):
        path = run_dir(run_id)
        values, extra = body.get("values") or {}, body.get("extra") or ""
        if not isinstance(values, dict) or not isinstance(extra, str):
            raise HTTPException(422, "Expected {values: {key: text}, extra: text}")
        unknown = sorted(set(values) - set(CONTEXT_KEYS))
        if unknown:
            raise HTTPException(422, f"Unknown context keys: {', '.join(unknown)} (allowed: {', '.join(CONTEXT_KEYS)})")
        if len(extra) > CONTEXT_EXTRA_MAX:
            raise HTTPException(422, f"Notes too long ({len(extra)} > {CONTEXT_EXTRA_MAX} chars)")
        lines = [CONTEXT_HEADER, ""]
        for key in CONTEXT_KEYS:
            value = values.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise HTTPException(422, f"{key}: must be text")
            value = " ".join(value.split())  # one line per key
            if len(value) > CONTEXT_VALUE_MAX:
                raise HTTPException(422, f"{key}: too long ({len(value)} > {CONTEXT_VALUE_MAX} chars)")
            if value:
                lines.append(f"{key}: {value}")
        extra_lines = [ln for ln in extra.replace("\r\n", "\n").split("\n")]
        if any(_context_key(ln) in CONTEXT_KEYS for ln in extra_lines):
            raise HTTPException(422, "Notes must not repeat a context key - use its field instead")
        if extra.strip():
            lines += ["", *extra_lines]
        (path / "context.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        out = read_context_file(path / "context.md")
        out["keys"] = CONTEXT_KEYS
        return out

    @app.get("/api/runs/{run_id}/digest")
    def get_digest(run_id: str):
        path = run_dir(run_id)
        digest = path / "digest.md"
        if not digest.is_file():
            try:
                _quiet(write_digest, path)
            except (ValueError, OSError) as err:
                raise HTTPException(500, f"Could not build digest: {err}")
        return {"text": digest.read_text(encoding="utf-8")}

    @app.post("/api/runs/{run_id}/coach-pack")
    def post_coach_pack(run_id: str):
        path = run_dir(run_id)
        try:
            out, _ = _quiet(coach.coach_pack, path)
        except (ValueError, OSError) as err:
            raise HTTPException(500, f"coach-pack failed: {err}")
        text = Path(out).read_text(encoding="utf-8")
        return {"text": text, "chars": len(text), "approx_tokens": len(text) // 4}

    @app.post("/api/runs/{run_id}/tips")
    def post_tips(run_id: str, body: dict = Body(...)):
        path = run_dir(run_id)
        reply = body.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            raise HTTPException(422, {"errors": ["Paste Claude's reply (with its ```json block)"]})
        if len(reply) > REPLY_MAX:
            raise HTTPException(422, {"errors": [f"Reply too large ({len(reply)} > {REPLY_MAX} chars)"]})
        raw = extract_reply_json(reply)
        try:
            json.loads(raw)
        except json.JSONDecodeError as err:
            raise HTTPException(422, {"errors": [f"Not valid JSON: {err}"]})
        with tempfile.TemporaryDirectory() as tmp:
            tips_file = Path(tmp) / "tips.json"
            tips_file.write_text(raw, encoding="utf-8")
            try:
                _, printed = _quiet(coach.import_tips, path, tips_file)
            except ValueError as err:
                lines = [ln.strip() for ln in str(err).splitlines()]
                errors = [ln for ln in lines[1:] if ln] if lines and lines[0].startswith("Invalid") else lines
                raise HTTPException(422, {"errors": errors or ["Import failed"]})
        tips = load(path).get("tips", [])
        warnings = [ln.removeprefix("warning: ") for ln in printed.splitlines() if ln.startswith("warning:")]
        return {"imported": sum(1 for t in tips if t.get("source") == "coach"), "warnings": warnings, "tips": tips}

    @app.get("/api/routes")
    def get_routes():
        try:
            routes, errors = route_lib.load_routes()
        except OSError as err:
            raise HTTPException(500, f"Could not read knowledge/routes.md: {err}")
        return {"routes": routes, "errors": errors}

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
