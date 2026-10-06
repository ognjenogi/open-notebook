"""Vision client payload: multimodal chat request with base64 frame parts."""

import os
from unittest.mock import patch

import pytest

from open_notebook.ai import vision


@pytest.fixture
def vision_env(monkeypatch):
    monkeypatch.setenv("OPEN_NOTEBOOK_VISION_MODEL", "test-vision-model")
    monkeypatch.setenv("OPEN_NOTEBOOK_VISION_BASE_URL", "https://vision.example.com/v1")
    monkeypatch.setenv("OPEN_NOTEBOOK_VISION_API_KEY", "test-key")


def test_vision_unavailable_with_unset_envs(monkeypatch):
    for var in (
        "OPEN_NOTEBOOK_VISION_MODEL",
        "OPEN_NOTEBOOK_VISION_BASE_URL",
        "OPEN_NOTEBOOK_VISION_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    assert vision.vision_available() is False


def test_vision_available_when_all_set(vision_env):
    assert vision.vision_available() is True


def test_default_model_from_env(monkeypatch):
    monkeypatch.setenv("OPEN_NOTEBOOK_VISION_MODEL", "my-model")
    import importlib

    reloaded = importlib.reload(vision)
    assert reloaded.DEFAULT_VISION_MODEL == "my-model"


@pytest.mark.asyncio
async def test_describe_segment_posts_image_url_parts(vision_env, tmp_path):
    captured = {}

    frame_file = tmp_path / "f0001.jpg"
    frame_file.write_bytes(b"\xff\xd8fakejpeg")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "a diagram of a cell"}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured["kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["payload"] = kwargs.get("json")
            return FakeResponse()

    with patch("httpx.AsyncClient", FakeClient):
        out = await vision.describe_segment(
            frames=[(0.0, str(frame_file))],
            transcript_excerpt="mitochondria",
            duration_hint="60s",
        )

    assert out == "a diagram of a cell"
    assert captured["url"] == "https://vision.example.com/v1/chat/completions"
    assert captured["payload"]["model"] == "test-vision-model"
    content = captured["payload"]["messages"][0]["content"]
    assert isinstance(content, list)
    texts = [p for p in content if p.get("type") == "text"]
    assert any("visual analyst" in p.get("text", "") for p in texts)
    images = [p for p in content if p.get("type") == "image_url"]
    assert len(images) >= 1
    assert images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_describe_segment_caps_frames_at_six(vision_env, tmp_path):
    captured = {}

    frames = []
    for i in range(10):
        f = tmp_path / f"f{i:04d}.jpg"
        f.write_bytes(b"\xff\xd8fakejpeg")
        frames.append((float(i * 10), str(f)))

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            captured["payload"] = kwargs.get("json")
            return FakeResponse()

    with patch("httpx.AsyncClient", FakeClient):
        await vision.describe_segment(
            frames=frames, transcript_excerpt="x", duration_hint="100s"
        )

    content = captured["payload"]["messages"][0]["content"]
    images = [p for p in content if p.get("type") == "image_url"]
    assert len(images) == 6
    assert len(os.environ.get("OPEN_NOTEBOOK_VISION_MODEL", "")) > 0
