"""When was the VOD recorded?  -> (recording_date ISO local time, date_source)

Sources, most to least trustworthy:
  "tag"        - a `creation_time` tag in the container (format or any stream);
  "filename"   - OBS's default file name pattern "YYYY-MM-DD HH-MM-SS" anywhere in the name;
  "file_times" - the file's birth time, trusted only when the file looks like the
                 live recording: a recorder writes for the whole match, so the last
                 write (mtime) is about one video duration after the birth time;
  "estimated"  - otherwise the birth time anyway (a copied/moved file: the copy
                 date, which is usually soon after the match), marked as a guess.
"""

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from .remux import _tool

OBS_NAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ _T](\d{2})-(\d{2})-(\d{2})")
FILE_TIMES_TOLERANCE = 0.15      # mtime - birth time must be within 15% of the duration


def _local_iso(dt):
    return dt.astimezone().isoformat(timespec="seconds")


def tag_creation_time(video):
    """creation_time from the container (format tags first, then streams), or None."""
    try:
        out = subprocess.run(
            [_tool("ffprobe"), "-v", "error", "-show_entries", "format_tags:stream_tags", "-of", "json", str(video)],
            capture_output=True, text=True, check=True).stdout
        info = json.loads(out)
    except (subprocess.CalledProcessError, ValueError, SystemExit):
        return None
    tag_sets = [info.get("format", {}).get("tags", {})] + [s.get("tags", {}) for s in info.get("streams", [])]
    for tags in tag_sets:
        for key, value in tags.items():
            if key.lower() == "creation_time" and value:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    continue
    return None


def filename_time(video):
    match = OBS_NAME.search(Path(video).name)
    if not match:
        return None
    try:
        return datetime(*(int(g) for g in match.groups())).astimezone()   # OBS names use local time
    except ValueError:
        return None


def recording_date(video, duration_s):
    """Return (iso_local_datetime or None, source)."""
    tagged = tag_creation_time(video)
    if tagged:
        return _local_iso(tagged), "tag"
    named = filename_time(video)
    if named:
        return _local_iso(named), "filename"
    try:
        stat = os.stat(video)
    except OSError:
        return None, "estimated"
    birth = getattr(stat, "st_birthtime", None)
    if birth is None:                 # Linux usually has no birth time: mtime is the best guess
        return _local_iso(datetime.fromtimestamp(stat.st_mtime)), "estimated"
    written_for = stat.st_mtime - birth
    if abs(written_for - duration_s) <= FILE_TIMES_TOLERANCE * duration_s:
        return _local_iso(datetime.fromtimestamp(birth)), "file_times"
    return _local_iso(datetime.fromtimestamp(birth)), "estimated"
