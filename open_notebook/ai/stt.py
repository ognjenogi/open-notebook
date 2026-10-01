"""Speech-to-text shared helpers for OpenAI-compatible audio models."""

import os
from typing import Optional

DEFAULT_STT_MODEL = os.environ.get("OPEN_NOTEBOOK_STT_MODEL", "mimo-v2.6-pro")

PROMPT = (
    "Transcribe this audio exactly. Reply with the transcript only, no "
    "commentary. If there is no speech, reply exactly: NO_SPEECH."
)


def audio_format(mime: str) -> str:
    """Map MIME type to audio format expected by input_audio payload."""
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


def transcription_payload(
    b64: str, mime: str, model: str, prompt: Optional[str] = None
) -> dict:
    """Build a chat completions payload with input_audio for transcription."""
    return {
        "model": model,
        "max_tokens": 4000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt or PROMPT},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": b64,
                            "format": audio_format(mime),
                        },
                    },
                ],
            }
        ],
    }
