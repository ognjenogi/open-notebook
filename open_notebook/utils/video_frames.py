"""ffmpeg-based frame extraction for video vision analysis."""

import glob
import json
import os
import subprocess
import tempfile

Frame = tuple[float, str]


def ffprobe_duration(path: str) -> float:
    """Return the media duration in seconds via ffprobe JSON output."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def extract_frames(
    path: str, max_frames: int = 180, min_interval_s: float = 10.0
) -> list[Frame]:
    """Extract JPEG frames evenly across the video.

    Sampling rate is ``min(1/min_interval_s, max_frames/duration)`` so output
    honors both the minimum spacing and the frame cap. Frames land in a fresh
    temp dir; the caller owns cleanup.
    """
    duration = ffprobe_duration(path)
    fps = min(1.0 / min_interval_s, max_frames / duration)
    tmpdir = tempfile.mkdtemp(prefix="on_frames_")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            path,
            "-vf",
            f"fps={fps},scale=720:-2",
            "-q:v",
            "5",
            os.path.join(tmpdir, "f%04d.jpg"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    frames: list[Frame] = []
    for i, jpeg in enumerate(sorted(glob.glob(os.path.join(tmpdir, "*.jpg")))):
        frames.append((i / fps if fps > 0 else 0.0, jpeg))
    return frames
