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


async def get_vision_config() -> tuple[str, str, str]:
    """Return (model, base_url, api_key) using DB defaults if set, else env vars."""
    try:
        from open_notebook.ai.models import DefaultModels, Model
        defaults = await DefaultModels.get_instance()
        if defaults and getattr(defaults, "default_vision_model", None):
            model_id = defaults.default_vision_model
            model_obj = await Model.get(model_id)
            if model_obj:
                model_name = model_obj.name
                cred = await model_obj.get_credential_obj() if model_obj.credential else None
                api_key = cred.api_key.get_secret_value() if (cred and cred.api_key) else ""
                base_url = (cred.base_url or cred.endpoint or "") if cred else ""

                if not base_url:
                    if model_obj.provider == "openai":
                        base_url = "https://api.openai.com/v1"
                    elif model_obj.provider == "openrouter":
                        base_url = "https://openrouter.ai/api/v1"
                    elif model_obj.provider == "groq":
                        base_url = "https://api.groq.com/openai/v1"
                    elif model_obj.provider == "mistral":
                        base_url = "https://api.mistral.ai/v1"
                    elif model_obj.provider == "deepseek":
                        base_url = "https://api.deepseek.com"

                if model_name and base_url and api_key:
                    return model_name, base_url, api_key
    except Exception:
        pass

    return _vision_model(), _vision_base_url(), _vision_api_key()


async def is_vision_available() -> bool:
    """True when either DB defaults or environment variables configure vision."""
    model, base_url, api_key = await get_vision_config()
    return bool(model and base_url and api_key)


def _frame_to_data_url(jpeg_path: str) -> str:
    with open(jpeg_path, "rb") as f:
        raw = f.read()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


async def describe_segment(
    frames: list[tuple[float, str]],
    transcript_excerpt: str,
    duration_hint: str,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Describe the visually conveyed teaching content of one video segment."""
    _ = duration_hint
    if not (model and base_url and api_key):
        cfg_model, cfg_base_url, cfg_api_key = await get_vision_config()
        model = model or cfg_model
        base_url = (base_url or cfg_base_url).rstrip("/")
        api_key = api_key or cfg_api_key
    else:
        base_url = base_url.rstrip("/")
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
