"""Learner-curated bastion route library: knowledge/routes.md -> list of route dicts.

Format (see the header of knowledge/routes.md): `## <id>` then `key: value` lines.
Entries with `status: example` are skipped everywhere (served list, coach-pack, validation of
`reference_route`).
"""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROUTES_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "routes.md"

TYPES = ("housing", "treasure", "bridge", "stables")
KEYS = ("type", "entry", "url", "start", "end", "runner", "time", "notes", "status")
REQUIRED = ("type", "entry", "url", "start")
STATUSES = ("draft", "confirmed", "example")

_ID = re.compile(r"^[A-Za-z0-9][\w.-]*$")
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
             "youtube-nocookie.com", "www.youtube-nocookie.com"}


def youtube_id(url):
    """YouTube watch / youtu.be / shorts / embed / live URL -> 11-char video id, else None."""
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https"):
        return None
    host = (u.hostname or "").lower()
    parts = [p for p in u.path.split("/") if p]
    vid = None
    if host in ("youtu.be", "www.youtu.be"):
        vid = parts[0] if parts else None
    elif host in _YT_HOSTS:
        if u.path == "/watch":
            vid = (parse_qs(u.query).get("v") or [None])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
            vid = parts[1]
    return vid if vid and _VIDEO_ID.match(vid) else None


def parse_time(text):
    """'m:ss', 'h:mm:ss', 'm:ss.s' or plain seconds -> float seconds, else None."""
    text = text.strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    m = re.fullmatch(r"(?:(\d+):)?(\d+):([0-5]\d(?:\.\d+)?)", text)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + float(s)


def parse_routes(text, include_examples=False):
    """Return (routes, errors). Invalid entries are reported in `errors` and left out."""
    routes, errors, seen = [], [], set()
    entries = []  # (id, line_no, {key: value}, [errors])
    cur = None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith("## "):
            cur = (line[3:].strip(), n, {}, [])
            entries.append(cur)
            continue
        if cur is None or not line or line.startswith("#"):
            continue
        m = re.match(r"^-?\s*([A-Za-z_]+)\s*:\s*(.*)$", line)
        if not m or m.group(1).lower() not in KEYS:
            cur[3].append(f"line {n}: not a known 'key: value' line ({', '.join(KEYS)})")
            continue
        cur[2][m.group(1).lower()] = m.group(2).strip()

    for rid, n, kv, errs in entries:
        where = f"route '{rid}' (line {n})"
        status = kv.get("status", "draft").lower()
        if status == "example" and not include_examples:
            continue
        if not _ID.match(rid):
            errs.append("id must be kebab-case letters/digits/-/_/.")
        elif rid in seen:
            errs.append("duplicate id")
        for key in REQUIRED:
            if not kv.get(key):
                errs.append(f"missing '{key}'")
        rtype = kv.get("type", "").lower()
        if rtype and rtype not in TYPES:
            errs.append(f"type {rtype!r} not one of {', '.join(TYPES)}")
        if status not in STATUSES:
            errs.append(f"status {status!r} not one of {', '.join(STATUSES)}")
        vid = youtube_id(kv["url"]) if kv.get("url") else None
        if kv.get("url") and not vid:
            errs.append("url is not a YouTube watch / youtu.be / shorts link")
        start = parse_time(kv["start"]) if kv.get("start") else None
        if kv.get("start") and start is None:
            errs.append(f"start {kv['start']!r} is not m:ss")
        end = parse_time(kv["end"]) if kv.get("end") else None
        if kv.get("end") and end is None:
            errs.append(f"end {kv['end']!r} is not m:ss")
        if start is not None and end is not None and end <= start:
            errs.append("end must be after start")
        if errs:
            errors += [f"{where}: {e}" for e in errs]
            continue
        seen.add(rid)
        routes.append({
            "id": rid, "type": rtype, "entry": kv["entry"], "url": kv["url"], "video_id": vid,
            "start_s": start, "end_s": end, "runner": kv.get("runner") or None,
            "time": kv.get("time") or None, "notes": kv.get("notes") or None, "status": status,
        })
    return routes, errors


def load_routes(path=None, include_examples=False):
    path = Path(path) if path else ROUTES_PATH
    if not path.is_file():
        return [], []
    return parse_routes(path.read_text(encoding="utf-8"), include_examples)


def route_ids(path=None):
    return {r["id"] for r in load_routes(path)[0]}


def coach_text(path=None):
    """routes.md for the coach-pack: the header plus every non-example entry, verbatim."""
    path = Path(path) if path else ROUTES_PATH
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^(?=## )", text)
    head, entries = sections[0], sections[1:]
    keep = [s for s in entries if not re.search(r"(?mi)^-?\s*status\s*:\s*example\s*$", s)]
    if not keep:
        return head.rstrip() + "\n\n(No routes yet — `reference_route` must be null.)\n"
    return head + "".join(keep)
