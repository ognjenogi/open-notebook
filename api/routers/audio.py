"""Speech-to-text for Open Notebook, at parity with the learning engine.

Open Code Go has no /audio/transcriptions endpoint: audio goes in as an
`input_audio` part on a chat completion. `mimo-v2.6-pro` is the model that
actually consumes it — `space-bunny-free` answers "no audio attached" and
will emit a bare NO_SPEECH over real speech — so the model is fixed here
rather than taken from the default model, and the caller can override it.

A silent clip comes back as the literal string "NO_SPEECH"; the caller
decides what that means, exactly as the engine does.
"""

import base64
import os
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel

from open_notebook.ai.opencode_headers import is_opencode, opencode_headers
from open_notebook.domain.credential import Credential

router = APIRouter()

DEFAULT_STT_MODEL = os.environ.get("OPEN_NOTEBOOK_STT_MODEL", "mimo-v2.6-pro")
# 30 s matches the engine, but the gateway's transcription latency swings
# between ~6 s and well over 30 s on the same clip, so the ceiling is tunable
# rather than hard-wired.
TIMEOUT_S = float(os.environ.get("OPEN_NOTEBOOK_STT_TIMEOUT_S", "60"))

PROMPT = (
    "Transcribe this audio exactly. Reply with the transcript only, no "
    "commentary. If there is no speech, reply exactly: NO_SPEECH."
)


class TranscribeResponse(BaseModel):
    text: str
    model: str


def _audio_format(mime: str) -> str:
    mime = (mime or "").lower()
    if "mpeg" in mime or "mp3" in mime:
        return "mp3"
    if "webm" in mime:
        return "webm"
    if "ogg" in mime:
        return "ogg"
    if "flac" in mime:
        return "flac"
    if "m4a" in mime or "mp4" in mime:
        return "m4a"
    return "wav"


async def _opencode_credential() -> Optional[dict]:
    """The first stored credential whose endpoint is an Open Code Go gateway."""
    for provider in ("openai_compatible", "openai"):
        try:
            credentials = await Credential.get_by_provider(provider)
        except Exception as e:  # noqa: BLE001 - a missing table must not 500 here
            logger.warning(f"Could not read {provider} credentials: {e}")
            continue
        for cred in credentials or []:
            try:
                config = cred.to_esperanto_config()
            except Exception:  # noqa: BLE001
                continue
            base_url = str(config.get("base_url") or "")
            if is_opencode(base_url) and config.get("api_key"):
                return config
    return None


@router.post("/audio/transcribe", response_model=TranscribeResponse)
async def transcribe(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
) -> TranscribeResponse:
    """Transcribe an audio file with Open Code Go.

    Mirrors POST /api/audio/transcribe in the learning engine: multipart
    `file`, transcript-only answer, literal NO_SPEECH for silence. The
    upstream timeout defaults to 60 s for the gateway's latency swings.
    """
    config = await _opencode_credential()
    if not config:
        raise HTTPException(
            status_code=503,
            detail="No Open Code Go credential is configured",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio file")

    base = str(config["base_url"]).rstrip("/")
    audio = base64.b64encode(raw).decode("ascii")
    chosen = model or DEFAULT_STT_MODEL
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    headers.update(opencode_headers(base))
    # A fresh session id per request: the gateway rejects a reused one.
    headers["x-opencode-session"] = uuid.uuid4().hex

    payload = {
        "model": chosen,
        "max_tokens": 4000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio,
                            "format": _audio_format(file.content_type or ""),
                        },
                    },
                ],
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.post(
                f"{base}/chat/completions", headers=headers, json=payload
            )
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=504, detail=f"Transcription timed out: {e}")
    except httpx.HTTPError as e:
        logger.error(f"Open Code Go transcription error: {e}")
        raise HTTPException(status_code=502, detail=f"Transcription API error: {e}")

    if response.status_code >= 400:
        logger.error(
            f"Open Code Go transcription error: {response.status_code} {response.text[:300]}"
        )
        raise HTTPException(
            status_code=502,
            detail=f"Transcription API error ({response.status_code})",
        )

    try:
        data = response.json()
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"Transcription API error: {e}")

    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
    return TranscribeResponse(text=(text or "").strip(), model=chosen)
