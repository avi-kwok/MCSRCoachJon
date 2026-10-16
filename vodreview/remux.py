"""Make a browser-playable copy of the VOD: <out>/video.mp4.

Browsers can't play MKV, but the streams inside are usually fine, so this is a
*remux* (container change) with stream copy - fast, no quality loss. Audio is
only re-encoded to AAC if its codec isn't one MP4 players handle.

A source that already is an H.264 MP4 with AAC/MP3 (or no) audio is not
copied at all: video.mp4 becomes a hard link to it (same file, no extra disk;
a symlink if the run folder is on another disk, a copy as the last resort).
"""

import os
import shutil
import subprocess
from pathlib import Path

MP4_AUDIO = {"aac", "mp3"}


def _tool(name):
    found = shutil.which(name)
    if found:
        return found
    fallback = Path("/opt/homebrew/bin") / name
    if fallback.exists():
        return str(fallback)
    raise SystemExit(f"{name} not found - install ffmpeg (brew install ffmpeg) or use --no-video.")


def audio_codec(video):
    out = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True)
    return out.stdout.strip() or None


def video_codec(video):
    out = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True)
    return out.stdout.strip() or None


def link_video(video, target):
    """video.mp4 = the source itself: hard link, else symlink, else copy."""
    tmp = target.with_name("video.tmp.mp4")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    try:
        os.link(video, tmp)
        how = "hard link"
    except OSError:
        try:
            os.symlink(video.resolve(), tmp)
            how = "symlink"
        except OSError:
            shutil.copy2(video, tmp)
            how = "copy"
    if target.exists() or target.is_symlink():
        target.unlink()
    tmp.replace(target)
    print(f"{target} -> {video} ({how}; already a browser-playable MP4, no remux)")
    return target


def remux_to_mp4(video, out_dir):
    video = Path(video)
    target = Path(out_dir) / "video.mp4"
    if target.exists():
        same = target.resolve() == video.resolve() or os.path.samefile(target, video)
        if same or target.stat().st_mtime >= video.stat().st_mtime:
            print(f"{target} is up to date - skipping remux.")
            return target
    codec = audio_codec(video)
    if video.suffix.lower() in (".mp4", ".m4v") and video_codec(video) == "h264" and (codec is None or codec in MP4_AUDIO):
        return link_video(video, target)
    if codec is None:
        audio = ["-an"]
    elif codec in MP4_AUDIO:
        audio = ["-c:a", "copy"]
    else:
        audio = ["-c:a", "aac", "-b:a", "192k"]
    tmp = target.with_name("video.tmp.mp4")
    print(f"Remuxing to {target} (video copy, audio {codec or 'none'} -> {audio[1] if codec else 'none'}) ...")
    subprocess.run(
        [_tool("ffmpeg"), "-y", "-v", "error", "-i", str(video),
         "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy", *audio,
         "-movflags", "+faststart", str(tmp)],
        check=True)
    tmp.replace(target)
    return target
