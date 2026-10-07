"""Vision pass: video frames watched by a vision model, merged with transcript.

Covers the YouTube video path in content_process: after extraction + STT
fallback, frames are described per segment and appended under a
"Visual detail (from video frames)" heading. Any vision failure keeps the
transcript-only source instead of raising.
"""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_core.common import ExtractionOutput

from open_notebook.domain.content_settings import ContentSettings
from open_notebook.domain.video_vision import merge_transcript_with_visual
from open_notebook.graphs.source import content_process


def _state(url: str) -> Dict[str, Any]:
    return {"content_state": {"url": url}}


def _empty_extraction() -> ExtractionOutput:
    return ExtractionOutput(title="Video", content="  ", metadata={})


def _transcript_extraction(text: str) -> ExtractionOutput:
    return ExtractionOutput(title="Video", content=text, metadata={})


def test_merge_appends_visual_section_deterministically():
    out = merge_transcript_with_visual("hello", "A diagram of X")
    assert out == "hello\n\n## Visual detail (from video frames)\n\nA diagram of X"


@pytest.mark.asyncio
async def test_vision_merges_visual_notes_with_stt_transcript():
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_empty_extraction()),
        ),
        patch(
            "open_notebook.graphs.source.transcribe_youtube_audio",
            new=AsyncMock(return_value="hello from audio"),
        ),
        patch(
            "open_notebook.graphs.source.download_youtube_video",
            return_value="/tmp/fake.mp4",
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=True,
        ),
        patch(
            "open_notebook.graphs.source.ffprobe_duration",
            return_value=20.0,
        ),
        patch(
            "open_notebook.graphs.source.extract_frames",
            return_value=[(0.0, "f1.jpg"), (10.0, "f2.jpg")],
        ),
        patch(
            "open_notebook.graphs.source.describe_segment",
            new=AsyncMock(return_value="A diagram of X"),
        ),
        patch("os.unlink", return_value=None),
    ):
        out = await content_process(_state("https://www.youtube.com/watch?v=x"))
    assert "hello from audio" in out["extraction"].content
    assert "## Visual detail (from video frames)" in out["extraction"].content
    assert "A diagram of X" in out["extraction"].content


@pytest.mark.asyncio
async def test_vision_failure_keeps_transcript_only():
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_empty_extraction()),
        ),
        patch(
            "open_notebook.graphs.source.transcribe_youtube_audio",
            new=AsyncMock(return_value="hello from audio"),
        ),
        patch(
            "open_notebook.graphs.source.download_youtube_video",
            return_value="/tmp/fake.mp4",
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=True,
        ),
        patch(
            "open_notebook.graphs.source.ffprobe_duration",
            return_value=20.0,
        ),
        patch(
            "open_notebook.graphs.source.extract_frames",
            return_value=[(0.0, "f1.jpg"), (10.0, "f2.jpg")],
        ),
        patch(
            "open_notebook.graphs.source.describe_segment",
            new=AsyncMock(side_effect=RuntimeError("vision boom")),
        ),
        patch("os.unlink", return_value=None),
    ):
        out = await content_process(_state("https://www.youtube.com/watch?v=x"))
    assert "hello from audio" in out["extraction"].content
    assert "Visual detail" not in out["extraction"].content


@pytest.mark.asyncio
async def test_vision_disabled_by_setting():
    download = MagicMock(return_value="/tmp/fake.mp4")
    describe = AsyncMock(return_value="A diagram of X")
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_transcript_extraction("plain transcript here")),
        ),
        patch(
            "open_notebook.graphs.source.ContentSettings.get_instance",
            new=AsyncMock(return_value=ContentSettings(video_vision=False)),
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=True,
        ),
        patch(
            "open_notebook.graphs.source.download_youtube_video",
            download,
        ),
        patch(
            "open_notebook.graphs.source.describe_segment",
            describe,
        ),
    ):
        out = await content_process(_state("https://www.youtube.com/watch?v=x"))
    assert out["extraction"].content == "plain transcript here"
    download.assert_not_called()
    describe.assert_not_awaited()


@pytest.mark.asyncio
async def test_vision_runs_for_upload_with_video_extension():
    ffprobe = MagicMock(return_value=60.0)
    describe = AsyncMock(return_value="visual notes")
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(
                return_value=_transcript_extraction("upload transcript here")
            ),
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=True,
        ),
        patch(
            "open_notebook.graphs.source.ffprobe_duration",
            ffprobe,
        ),
        patch(
            "open_notebook.graphs.source.extract_frames",
            return_value=[(0.0, "f1.jpg")],
        ),
        patch(
            "open_notebook.graphs.source.describe_segment",
            describe,
        ),
        patch("os.unlink", return_value=None),
    ):
        out = await content_process(
            {"content_state": {"file_path": "/uploads/vid.mp4"}}
        )
    assert "upload transcript here" in out["extraction"].content
    assert "## Visual detail (from video frames)" in out["extraction"].content
    assert "visual notes" in out["extraction"].content
    describe.assert_awaited_once()
    # Fast path: extension match skips the resolution probe; the single call
    # is vision_enhance's duration lookup.
    assert ffprobe.call_count == 1


@pytest.mark.asyncio
async def test_vision_runs_for_extensionless_upload_probed_by_ffprobe():
    describe = AsyncMock(return_value="visual notes")
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(
                return_value=_transcript_extraction("upload transcript here")
            ),
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=True,
        ),
        patch(
            "open_notebook.graphs.source.ffprobe_duration",
            return_value=60.0,
        ),
        patch(
            "open_notebook.graphs.source.extract_frames",
            return_value=[(0.0, "f1.jpg")],
        ),
        patch(
            "open_notebook.graphs.source.describe_segment",
            describe,
        ),
        patch("os.unlink", return_value=None),
    ):
        out = await content_process(
            {"content_state": {"file_path": "/uploads/noextfile"}}
        )
    assert "## Visual detail (from video frames)" in out["extraction"].content
    assert "visual notes" in out["extraction"].content
    describe.assert_awaited_once()


@pytest.mark.asyncio
async def test_vision_skipped_when_ffprobe_probe_fails():
    describe = AsyncMock(return_value="visual notes")
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(
                return_value=_transcript_extraction("upload transcript here")
            ),
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=True,
        ),
        patch(
            "open_notebook.graphs.source.ffprobe_duration",
            MagicMock(side_effect=RuntimeError("not media")),
        ),
        patch(
            "open_notebook.graphs.source.describe_segment",
            describe,
        ),
    ):
        out = await content_process(
            {"content_state": {"file_path": "/uploads/document.pdf"}}
        )
    assert out["extraction"].content == "upload transcript here"
    describe.assert_not_awaited()


@pytest.mark.asyncio
async def test_vision_skipped_when_unavailable():
    download = MagicMock(return_value="/tmp/fake.mp4")
    describe = AsyncMock(return_value="A diagram of X")
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_transcript_extraction("plain transcript here")),
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=False,
        ),
        patch(
            "open_notebook.graphs.source.download_youtube_video",
            download,
        ),
        patch(
            "open_notebook.graphs.source.describe_segment",
            describe,
        ),
    ):
        out = await content_process(_state("https://www.youtube.com/watch?v=x"))
    assert out["extraction"].content == "plain transcript here"
    download.assert_not_called()
    describe.assert_not_awaited()


@pytest.mark.asyncio
async def test_vision_persists_frames_and_embeds_urls(tmp_path):
    import os as _os

    from open_notebook.graphs.source import vision_enhance

    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    f1 = frame_dir / "frame0.jpg"
    f1.write_bytes(b"\xff\xd8fake-frame-one")
    f2 = frame_dir / "frame5.jpg"
    f2.write_bytes(b"\xff\xd8fake-frame-two")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    with (
        patch(
            "open_notebook.graphs.source.extract_frames",
            return_value=[(0.0, str(f1)), (10.0, str(f2))],
        ),
        patch(
            "open_notebook.graphs.source.ffprobe_duration",
            return_value=20.0,
        ),
        patch(
            "open_notebook.graphs.source.describe_segment",
            new=AsyncMock(return_value="A diagram of X"),
        ),
        patch("open_notebook.graphs.source.UPLOADS_FOLDER", str(uploads)),
    ):
        md = await vision_enhance("/tmp/fake.mp4", "hello transcript")
    assert md is not None
    assert "![frame" in md
    assert "/assets/uploads/" in md
    assert "A diagram of X" in md
    # First frame of the single segment persisted; second frame not kept.
    persisted = list(uploads.glob("*.jpg"))
    assert len(persisted) == 1
    assert persisted[0].read_bytes() == b"\xff\xd8fake-frame-one"
    # Tempdir still cleaned despite the persistence copy.
    assert not _os.path.exists(str(f1))
    assert not _os.path.exists(str(f2))
