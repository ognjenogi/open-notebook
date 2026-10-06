"""Env-configured multimodal vision client for video segment description."""

import base64
import os

import httpx

DEFAULT_VISION_MODEL = os.environ.get("OPEN_NOTEBOOK_VISION_MODEL", "")

MAX_FRAMES = 6


def _vision_model() -> str:
    return os.environ.get("OPEN_NOTEBOOK_VISION_MODEL", "") or DEFAULT_VISION_MODEL


def _vision_base_url() -> str:
    return os.environ.get("OPEN_NOTEBOOK_VISION_BASE_URL", "")


def _vision_api_key() -> str:
    return os.environ.get("OPEN_NOTEBOOK_VISION_API_KEY", "")


def vision_available() -> bool:
    """True only when model + base URL + key are all configured."""
    return bool(_vision_model() and _vision_base_url() and _vision_api_key())


def _frame_to_data_url(jpeg_path: str) -> str:
    with open(jpeg_path, "rb") as f:
        raw = f.read()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


async def describe_segment(
    frames: list[tuple[float, str]], transcript_excerpt: str, duration_hint: str
) -> str:
    """Describe the visually conveyed teaching content of one video segment."""
    _ = duration_hint
    model = _vision_model()
    base_url = _vision_base_url().rstrip("/")
    api_key = _vision_api_key()
    prompt = (
        "You are a meticulous visual analyst watching one segment of an "
        "educational video. Frames are sampled ~10 seconds apart; each is "
        "prefixed with its timestamp. Transcript excerpt for context:\n"
        f'"""{transcript_excerpt}"""\n'
        "Describe ALL visually conveyed teaching content: diagrams, board work, "
        "on-screen text, code, figures, demonstrations, animations. Preserve "
        "mathematical notation in LaTeX. Plain factual markdown, no preamble."
    )
    content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
    for _, jpeg_path in frames[:MAX_FRAMES]:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": _frame_to_data_url(jpeg_path)},
            }
        )
    payload = {"model": model, "messages": [{"role": "user", "content": content}]}
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            f"{base_url}/chat/completions", headers=headers, json=payload
        )
        response.raise_for_status()
        data = response.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError("Empty vision response") from e
    if not text:
        raise RuntimeError("Empty vision response")
    return text
