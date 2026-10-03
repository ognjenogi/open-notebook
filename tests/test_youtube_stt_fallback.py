"""YouTube audio fallback: when captions are missing, download audio and
transcribe with the configured STT model instead of failing."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from content_core.common import ExtractionOutput

from open_notebook.graphs.source import content_process


def _state(url: str) -> Dict[str, Any]:
    return {"content_state": {"url": url}}


def _empty_extraction() -> ExtractionOutput:
    return ExtractionOutput(title="Video", content="  ", metadata={})


def _run(state):
    import asyncio

    return asyncio.get_event_loop().run_until_complete(content_process(state))


@pytest.mark.asyncio
async def test_youtube_falls_back_to_stt_transcript():
    stt = AsyncMock()
    stt.atranscribe.return_value = MagicMock(text="hello from audio")
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_empty_extraction()),
        ),
        patch(
            "open_notebook.graphs.source.download_youtube_audio",
            return_value="/tmp/fake.mp3",
        ),
        patch(
            "open_notebook.graphs.source.get_stt_model",
            new=AsyncMock(return_value=stt),
        ),
        patch("os.unlink", return_value=None),
    ):
        out = await content_process(_state("https://www.youtube.com/watch?v=x"))
    assert "hello from audio" in out["extraction"].content
    stt.atranscribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_youtube_still_fails_without_stt():
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_empty_extraction()),
        ),
        patch(
            "open_notebook.graphs.source.get_stt_model",
            new=AsyncMock(return_value=None),
        ),
    ):
        with pytest.raises(ValueError, match="Speech-to-Text"):
            await content_process(_state("https://youtu.be/x"))


@pytest.mark.asyncio
async def test_non_youtube_empty_still_raises_generic():
    with (
        patch(
            "open_notebook.graphs.source.extract_content",
            new=AsyncMock(return_value=_empty_extraction()),
        ),
    ):
        with pytest.raises(ValueError, match="Could not extract any text"):
            await content_process(_state("https://example.com/page"))
