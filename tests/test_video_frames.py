"""ffmpeg frame extraction: fps math and argv shape via mocked subprocess."""

import json
import subprocess

import pytest

from open_notebook.utils import video_frames


def _fake_run_factory(captured):
    def fake_run(argv, **kwargs):
        captured.append(list(argv))
        if argv[0] == "ffprobe":
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"format": {"duration": "600"}}), stderr=""
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    return fake_run


def test_ffprobe_duration_parses_json(monkeypatch):
    import subprocess as sp

    def fake_run(argv, **kwargs):
        assert "-show_entries" in argv
        assert "format=duration" in argv
        return sp.CompletedProcess(
            argv, 0, stdout=json.dumps({"format": {"duration": "600"}}), stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert video_frames.ffprobe_duration("/tmp/fake.mp4") == pytest.approx(600.0)


def test_extract_frames_argv(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))

    frames = video_frames.extract_frames(str(tmp_path / "video.mp4"))

    assert isinstance(frames, list)
    ffmpeg_calls = [c for c in captured if c[0] == "ffmpeg"]
    assert len(ffmpeg_calls) == 1
    argv = ffmpeg_calls[0]
    vf = argv[argv.index("-vf") + 1]
    fps_str = vf.split(",")[0].split("=")[1]
    # duration 600s, defaults max_frames=180 @ min_interval 10s:
    # fps = min(1/10, 180/600) = 0.1
    assert float(fps_str) == pytest.approx(0.1)
    assert "scale=720:-2" in vf
    assert "-q:v" in argv
    assert argv[argv.index("-q:v") + 1] == "5"


def test_extract_frames_respects_max_frames(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))

    video_frames.extract_frames(str(tmp_path / "video.mp4"), max_frames=10)

    ffmpeg_calls = [c for c in captured if c[0] == "ffmpeg"]
    argv = ffmpeg_calls[0]
    vf = argv[argv.index("-vf") + 1]
    fps_str = vf.split(",")[0].split("=")[1]
    # fps = min(1/10, 10/600) = 1/60 ~= 0.0166
    assert float(fps_str) == pytest.approx(1 / 60)
