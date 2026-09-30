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
    """Teach Esperanto's OpenAI-compatible clients about Open Code Go.

    Called once at import of open_notebook.ai.models, which is the funnel
    every model instance is built through.
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
