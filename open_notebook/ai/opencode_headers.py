"""Open Code Go request headers.

Open Code Go's gateway is browser-only: it rejects requests whose User-Agent
is a library default unless the caller also sends a session header. Every
OpenAI-compatible client in Esperanto funnels its requests through
`_get_headers()`, so one patch covers chat, embeddings, speech-to-text and the
model list, and the detection rule is the same one the learning engine uses:
the host, not the provider name.

The patch is additive and idempotent — an unpatched host keeps exactly the
headers it had.
"""

import base64
import logging
import uuid
from typing import Any, Dict, Optional, Union

import httpx
from esperanto.common_types.stt import TranscriptionResponse
from esperanto.utils.connect import HttpConnectionMixin

from open_notebook.ai.stt import DEFAULT_STT_MODEL, transcription_payload

logger = logging.getLogger(__name__)

OPENCODE_HOST = "opencode.ai"
SESSION_HEADER = "x-opencode-session"
SESSION_VALUE = "open-notebook"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _read_audio_b64_and_mime(model_instance, audio_file: Union[str, Any]) -> tuple[str, str]:
    if isinstance(audio_file, str):
        mime_type = model_instance._get_audio_mime_type(audio_file)
        with open(audio_file, "rb") as f:
            raw = f.read()
    else:
        filename = getattr(audio_file, "name", "audio.mp3")
        mime_type = model_instance._get_audio_mime_type(filename)
        if hasattr(audio_file, "seek"):
            audio_file.seek(0)
        raw = audio_file.read()
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
    return base64.b64encode(raw).decode("ascii"), mime_type


def is_opencode(base_url: Optional[str]) -> bool:
    """True when the endpoint is an Open Code Go gateway."""
    return OPENCODE_HOST in (base_url or "").lower()


def opencode_headers(base_url: Optional[str]) -> Dict[str, str]:
    """The extra headers an Open Code Go gateway requires, or {} for anyone
    else. Callers merge these into their own header dict."""
    if not is_opencode(base_url):
        return {}
    return {"User-Agent": BROWSER_USER_AGENT, SESSION_HEADER: SESSION_VALUE}


def install() -> None:
    """Teach Esperanto's clients about Open Code Go.

    Two seams, because the notebook reaches a model two ways:

    1. `_get_headers()` on the OpenAI-compatible classes — direct requests
       (chat, embeddings, STT, model list).
    2. `HttpConnectionMixin._create_http_clients` / `_create_langchain_http_clients`
       — the LangChain `ChatOpenAI` the chat graph and the podcast builder go
       through builds fresh httpx clients there, and those carry their own
       default headers.

    Called once at import of open_notebook.ai.models, the funnel every model
    instance is built through.
    """
    from esperanto.providers.embedding.openai_compatible import (
        OpenAICompatibleEmbeddingModel,
    )
    from esperanto.providers.llm.openai_compatible import (
        OpenAICompatibleLanguageModel,
    )
    from esperanto.providers.stt.openai_compatible import (
        OpenAICompatibleSpeechToTextModel,
    )

    for cls in (
        OpenAICompatibleLanguageModel,
        OpenAICompatibleEmbeddingModel,
        OpenAICompatibleSpeechToTextModel,
    ):
        if getattr(cls, "_opencode_headers_patched", False):
            continue
        original = cls._get_headers

        def patched(self, _original=original):
            headers = _original(self)
            extra = opencode_headers(getattr(self, "base_url", None))
            for name, value in extra.items():
                headers.setdefault(name, value)
            return headers

        cls._get_headers = patched
        cls._opencode_headers_patched = True
        logger.debug("Open Code Go headers installed on %s", cls.__name__)

    if not getattr(OpenAICompatibleSpeechToTextModel, "_opencode_stt_patched", False):
        orig_transcribe = OpenAICompatibleSpeechToTextModel.transcribe
        orig_atranscribe = OpenAICompatibleSpeechToTextModel.atranscribe

        def patched_transcribe(self, audio_file, language=None, prompt=None):
            if not is_opencode(getattr(self, "base_url", None)):
                return orig_transcribe(self, audio_file, language=language, prompt=prompt)

            b64, mime_type = _read_audio_b64_and_mime(self, audio_file)
            headers = dict(self._get_headers())
            headers["Content-Type"] = "application/json"
            headers["x-opencode-session"] = uuid.uuid4().hex
            chosen = self.get_model_name()
            if not chosen or chosen == "whisper-1":
                chosen = DEFAULT_STT_MODEL
            payload = transcription_payload(b64, mime_type, chosen, prompt=prompt)
            base = str(self.base_url).rstrip("/")
            response = self.client.post(
                f"{base}/chat/completions", headers=headers, json=payload
            )
            self._handle_error(response)
            data = response.json()
            text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            return TranscriptionResponse(
                text=text.strip(),
                language=language,
                model=chosen,
            )

        async def patched_atranscribe(self, audio_file, language=None, prompt=None):
            if not is_opencode(getattr(self, "base_url", None)):
                return await orig_atranscribe(self, audio_file, language=language, prompt=prompt)

            b64, mime_type = _read_audio_b64_and_mime(self, audio_file)
            headers = dict(self._get_headers())
            headers["Content-Type"] = "application/json"
            headers["x-opencode-session"] = uuid.uuid4().hex
            chosen = self.get_model_name()
            if not chosen or chosen == "whisper-1":
                chosen = DEFAULT_STT_MODEL
            payload = transcription_payload(b64, mime_type, chosen, prompt=prompt)
            base = str(self.base_url).rstrip("/")
            response = await self.async_client.post(
                f"{base}/chat/completions", headers=headers, json=payload
            )
            self._handle_error(response)
            data = response.json()
            text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            return TranscriptionResponse(
                text=text.strip(),
                language=language,
                model=chosen,
            )

        OpenAICompatibleSpeechToTextModel.transcribe = patched_transcribe
        OpenAICompatibleSpeechToTextModel.atranscribe = patched_atranscribe
        OpenAICompatibleSpeechToTextModel._opencode_stt_patched = True
        logger.debug("Open Code Go STT installed on OpenAICompatibleSpeechToTextModel")

    # httpx merges client default headers with per-request ones, and a
    # per-request header wins, so nothing is duplicated for other providers.
    if not getattr(HttpConnectionMixin, "_opencode_headers_patched", False):
        def _headers_kwargs(self):
            extra = opencode_headers(getattr(self, "base_url", None))
            return {"headers": extra} if extra else {}

        def direct_clients(self):
            """Original contract: assigns self.client / self.async_client."""
            base_url = getattr(self, "base_url", None)
            if base_url:
                self.base_url = base_url.rstrip("/")
            kwargs = dict(timeout=self._get_timeout(), verify=self._get_ssl_verify())
            kwargs.update(_headers_kwargs(self))
            self.client = httpx.Client(**kwargs)
            self.async_client = httpx.AsyncClient(**kwargs)

        def langchain_clients(self):
            """Original contract: returns a fresh (sync, async) pair, owned by
            LangChain — this is the client the chat graph and podcast builder
            actually send requests on."""
            kwargs = dict(timeout=self._get_timeout(), verify=self._get_ssl_verify())
            kwargs.update(_headers_kwargs(self))
            return httpx.Client(**kwargs), httpx.AsyncClient(**kwargs)

        HttpConnectionMixin._create_http_clients = direct_clients
        HttpConnectionMixin._create_langchain_http_clients = langchain_clients
        HttpConnectionMixin._opencode_headers_patched = True
        logger.debug("Open Code Go headers installed on HttpConnectionMixin")
