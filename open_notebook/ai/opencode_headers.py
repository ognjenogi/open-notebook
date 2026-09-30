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

import logging
from typing import Dict, Optional

import httpx
from esperanto.utils.connect import HttpConnectionMixin

logger = logging.getLogger(__name__)

OPENCODE_HOST = "opencode.ai"
SESSION_HEADER = "x-opencode-session"
SESSION_VALUE = "open-notebook"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


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
