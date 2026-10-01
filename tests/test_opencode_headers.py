"""Open Code Go header injection.

The gateway refuses a library-shaped request, so every OpenAI-compatible
client has to add a browser User-Agent and a session header when — and only
when — it is talking to that host. These tests pin both halves: the extra
headers go to Open Code Go, and everyone else keeps exactly what they had.
"""

import pytest

from open_notebook.ai.opencode_headers import (
    BROWSER_USER_AGENT,
    SESSION_HEADER,
    install,
    is_opencode,
    opencode_headers,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://opencode.ai/zen/v1", True),
        ("https://OPENCODE.AI/zen/v1", True),
        ("https://openrouter.ai/api/v1", False),
        ("http://ollama:11434/v1", False),
        ("", False),
        (None, False),
    ],
)
def test_is_opencode(url, expected):
    assert is_opencode(url) is expected


def test_headers_only_for_opencode():
    assert opencode_headers("https://opencode.ai/zen/v1") == {
        "User-Agent": BROWSER_USER_AGENT,
        SESSION_HEADER: "open-notebook",
    }
    assert opencode_headers("https://openrouter.ai/api/v1") == {}


def test_install_adds_headers_to_openai_compatible_clients():
    install()
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
        assert cls._opencode_headers_patched is True


def test_patched_headers_respect_the_host():
    install()
    from esperanto.providers.llm.openai_compatible import (
        OpenAICompatibleLanguageModel,
    )

    class Fake:
        base_url = "https://opencode.ai/zen/v1"
        api_key = "k"

        def _original(self):
            return {"Authorization": "Bearer k", "Content-Type": "application/json"}

    # Rebuild the patched method against a stand-in with the original headers,
    # so the assertion is about the patch and not about a live client.
    patched = OpenAICompatibleLanguageModel._get_headers
    fake = Fake()
    fake._get_headers = lambda self: {"Authorization": "Bearer k"}
    headers = patched(fake)
    assert headers[SESSION_HEADER] == "open-notebook"
    assert headers["User-Agent"] == BROWSER_USER_AGENT
    assert headers["Authorization"] == "Bearer k"

    fake.base_url = "https://openrouter.ai/api/v1"
    headers = patched(fake)
    assert SESSION_HEADER not in headers
    assert "User-Agent" not in headers


def test_install_is_idempotent():
    install()
    from esperanto.providers.llm.openai_compatible import (
        OpenAICompatibleLanguageModel,
    )

    first = OpenAICompatibleLanguageModel._get_headers
    install()
    assert OpenAICompatibleLanguageModel._get_headers is first


def test_transcribe_picks_the_audio_format_from_the_mime_type():
    from api.routers.audio import _audio_format

    assert _audio_format("audio/mpeg") == "mp3"
    assert _audio_format("audio/webm") == "webm"
    assert _audio_format("audio/wav") == "wav"
    assert _audio_format("audio/ogg") == "ogg"
    assert _audio_format("") == "wav"


def test_langchain_clients_carry_the_headers():
    """The chat graph and podcast builder go through LangChain, whose
    ChatOpenAI is built on the fresh clients from the connection mixin —
    headers must be on those too, or chat alone misses them."""
    import httpx
    from esperanto.utils.connect import HttpConnectionMixin

    install()
    class Holder(HttpConnectionMixin):
        def _get_provider_type(self):
            return "openai"

        def _get_timeout(self):
            return 30

        def _get_ssl_verify(self):
            return True

    holder = Holder()
    holder.base_url = "https://opencode.ai/zen/v1"
    sync_client, async_client = holder._create_langchain_http_clients()
    try:
        assert "x-opencode-session" in sync_client.headers
        assert "x-opencode-session" in async_client.headers
    finally:
        sync_client.close()

    holder.base_url = "https://openrouter.ai/api/v1"
    sync_client, async_client = holder._create_langchain_http_clients()
    try:
        assert "x-opencode-session" not in sync_client.headers
    finally:
        sync_client.close()


def test_audio_format_accuracy():
    from open_notebook.ai.stt import audio_format

    assert audio_format("audio/mpeg") == "mp3"
    assert audio_format("audio/mp3") == "mp3"
    assert audio_format("audio/webm") == "webm"
    assert audio_format("audio/wav") == "wav"
    assert audio_format("audio/ogg") == "ogg"
    assert audio_format("audio/flac") == "flac"
    assert audio_format("audio/m4a") == "m4a"
    assert audio_format("audio/mp4") == "m4a"
    assert audio_format("unknown") == "wav"
    assert audio_format("") == "wav"
    assert audio_format(None) == "wav"


def test_transcription_payload_builds_expected_input_audio():
    from open_notebook.ai.stt import transcription_payload, PROMPT

    b64_dummy = "AAAA"
    payload = transcription_payload(b64_dummy, "audio/webm", "mimo-v2.6-pro")

    assert payload["model"] == "mimo-v2.6-pro"
    assert payload["max_tokens"] == 4000
    assert len(payload["messages"]) == 1
    msg = payload["messages"][0]
    assert msg["role"] == "user"
    assert len(msg["content"]) == 2
    assert msg["content"][0] == {"type": "text", "text": PROMPT}
    assert msg["content"][1] == {
        "type": "input_audio",
        "input_audio": {
            "data": b64_dummy,
            "format": "webm",
        },
    }


def test_stt_monkeypatch_uses_chat_completions_for_opencode():
    import io
    import httpx
    from esperanto.providers.stt.openai_compatible import OpenAICompatibleSpeechToTextModel

    install()
    posted_urls = []

    def fake_post(url, headers=None, json=None, files=None, data=None):
        posted_urls.append(url)
        if "chat/completions" in url:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Hello world"}}]},
                request=httpx.Request("POST", url),
            )
        else:
            return httpx.Response(
                200,
                json={"text": "Hello non-opencode"},
                request=httpx.Request("POST", url),
            )

    model = OpenAICompatibleSpeechToTextModel(
        model_name="mimo-v2.6-pro",
        api_key="key",
        base_url="https://opencode.ai/zen/v1",
    )
    model.client.post = fake_post

    dummy_file = io.BytesIO(b"fake audio data")
    dummy_file.name = "audio.wav"

    res = model.transcribe(dummy_file)
    assert res.text == "Hello world"
    assert any("chat/completions" in u for u in posted_urls)

    posted_urls.clear()
    other_model = OpenAICompatibleSpeechToTextModel(
        model_name="whisper-1",
        api_key="key",
        base_url="https://other.ai/v1",
    )
    other_model.client.post = fake_post
    dummy_file.seek(0)
    other_res = other_model.transcribe(dummy_file)
    assert other_res.text == "Hello non-opencode"
    assert any("audio/transcriptions" in u for u in posted_urls)
