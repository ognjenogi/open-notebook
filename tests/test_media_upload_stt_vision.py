"""Test media upload STT transcription and vision-only video ingestion.

Verifies:
1. Uploaded video with audio is transcribed via STT and visually described.
2. Silent/transcript-less video ingestion preserves visual blackboard/slide content via vision-only mode.
3. Uploaded audio file (.mp3) is transcribed directly via STT.
4. Video upload fails informatively when both STT and vision are unavailable.
5. extract_audio_from_media handles audio extraction.
"""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_core.common import ExtractionOutput

from open_notebook.graphs.source import (
    content_process,
    extract_audio_from_media,
    transcribe_media_file,
)


def _upload_state(file_path: str) -> Dict[str, Any]:
    return {"content_state": {"file_path": file_path}}


def _empty_extraction() -> ExtractionOutput:
    return ExtractionOutput(title="", content="", metadata={})


@pytest.mark.asyncio
async def test_uploaded_video_with_audio_and_vision():
    """Video with audio gets both STT transcript and visual frame descriptions."""
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_empty_extraction()),
        ),
        patch(
            "open_notebook.graphs.source.transcribe_media_file",
            new=AsyncMock(return_value="audio transcript of math lecture"),
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=True,
        ),
        patch(
            "open_notebook.graphs.source.ffprobe_duration",
            return_value=30.0,
        ),
        patch(
            "open_notebook.graphs.source.extract_frames",
            return_value=[(0.0, "frame0.jpg"), (10.0, "frame10.jpg")],
        ),
        patch(
            "open_notebook.graphs.source.describe_segment",
            new=AsyncMock(return_value="Blackboard: derivation of Hahn-Banach theorem"),
        ),
        patch("os.unlink", return_value=None),
    ):
        result = await content_process(_upload_state("/tmp/lecture.mp4"))

    content = result["extraction"].content
    assert "audio transcript of math lecture" in content
    assert "## Visual detail (from video frames)" in content
    assert "Blackboard: derivation of Hahn-Banach theorem" in content


@pytest.mark.asyncio
async def test_silent_video_ingestion_vision_only():
    """Silent or music-only educational video succeeds via vision pass without losing info."""
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_empty_extraction()),
        ),
        patch(
            "open_notebook.graphs.source.transcribe_media_file",
            new=AsyncMock(return_value=None),  # No audio speech
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=True,
        ),
        patch(
            "open_notebook.graphs.source.ffprobe_duration",
            return_value=25.0,
        ),
        patch(
            "open_notebook.graphs.source.extract_frames",
            return_value=[(0.0, "frame0.jpg")],
        ),
        patch(
            "open_notebook.graphs.source.describe_segment",
            new=AsyncMock(return_value="Slide 1: Definition of Banach space and Cauchy sequences"),
        ),
        patch("os.unlink", return_value=None),
    ):
        result = await content_process(_upload_state("/tmp/silent_slides.mp4"))

    content = result["extraction"].content
    assert "## Visual detail (from video frames)" in content
    assert "Slide 1: Definition of Banach space and Cauchy sequences" in content


@pytest.mark.asyncio
async def test_audio_file_upload_transcribes():
    """Direct audio file upload (.mp3) gets transcribed via STT."""
    stt = AsyncMock()
    stt.atranscribe.return_value = MagicMock(text="Audio lecture on measure theory")
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_empty_extraction()),
        ),
        patch(
            "open_notebook.graphs.source.get_stt_model",
            new=AsyncMock(return_value=stt),
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=False,
        ),
        patch("os.unlink", return_value=None),
    ):
        result = await content_process(_upload_state("/tmp/lecture.mp3"))

    assert "Audio lecture on measure theory" in result["extraction"].content


@pytest.mark.asyncio
async def test_video_fails_when_stt_and_vision_both_unavailable():
    """When both transcription and vision fail/are unavailable, an informative error is raised."""
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_empty_extraction()),
        ),
        patch(
            "open_notebook.graphs.source.get_stt_model",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "open_notebook.graphs.source.vision_available",
            return_value=False,
        ),
    ):
        with pytest.raises(ValueError, match="Could not extract any content from media file"):
            await content_process(_upload_state("/tmp/lecture.mp4"))


def test_extract_audio_from_media_skips_audio_file():
    """Audio files (.mp3, .wav) do not need ffmpeg audio extraction."""
    assert extract_audio_from_media("/path/to/sound.mp3") is None
    assert extract_audio_from_media("/path/to/speech.wav") is None
