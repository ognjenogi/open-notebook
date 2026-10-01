"""
Tests for discovering models across all configured openai_compatible credentials.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from open_notebook.ai import model_discovery
from open_notebook.ai.model_discovery import discover_openai_compatible_models
from open_notebook.utils.url_validation import PinnedHttpTarget


def make_fake_client(handler):
    """Build a fake httpx.AsyncClient class whose .get() delegates to handler."""

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers=None, params=None, timeout=None, extensions=None):
            return handler(url=url, headers=headers, params=params, timeout=timeout, extensions=extensions)

    return FakeAsyncClient


def json_response(url, payload, status_code=200):
    return httpx.Response(
        status_code, json=payload, request=httpx.Request("GET", url)
    )


class FakeCredential:
    def __init__(self, cred_id: str, name: str, base_url: str, api_key: str):
        self.id = cred_id
        self.name = name
        self.provider = "openai_compatible"
        self._base_url = base_url
        self._api_key = api_key

    def to_esperanto_config(self):
        return {
            "base_url": self._base_url,
            "api_key": self._api_key,
        }


@pytest.mark.asyncio
async def test_discover_openai_compatible_iterates_all_credentials(monkeypatch):
    """Verify that every configured openai_compatible credential is queried and its id preserved."""
    cred1 = FakeCredential(
        cred_id="credential:cred-1",
        name="Gateway 1",
        base_url="https://gw1.example.com/v1",
        api_key="key-1",
    )
    cred2 = FakeCredential(
        cred_id="credential:cred-2",
        name="Gateway 2",
        base_url="https://gw2.example.com/v1",
        api_key="key-2",
    )

    requests = []

    def handler(url, headers, params, timeout, extensions):
        requests.append({"url": url, "headers": headers})
        if "gw1" in url:
            return json_response(url, {"data": [{"id": "model-gw1-chat"}]})
        elif "gw2" in url:
            return json_response(url, {"data": [{"id": "model-gw2-reasoner"}]})
        return json_response(url, {"data": []})

    monkeypatch.setattr(
        model_discovery.Credential,
        "get_by_provider",
        AsyncMock(return_value=[cred1, cred2]),
    )
    # Bypass DNS pinning in test
    monkeypatch.setattr(
        model_discovery,
        "prepare_pinned_http_target",
        AsyncMock(side_effect=lambda url, prov: PinnedHttpTarget(url=url, headers={}, extensions={})),
    )
    monkeypatch.setattr(
        model_discovery.httpx, "AsyncClient", make_fake_client(handler)
    )

    models = await discover_openai_compatible_models()

    assert len(requests) == 2
    assert requests[0]["url"] == "https://gw1.example.com/v1/models"
    assert requests[0]["headers"]["Authorization"] == "Bearer key-1"
    assert requests[1]["url"] == "https://gw2.example.com/v1/models"
    assert requests[1]["headers"]["Authorization"] == "Bearer key-2"

    assert len(models) == 2
    assert models[0].name == "model-gw1-chat"
    assert models[0].provider == "openai_compatible"
    assert models[0].credential == "credential:cred-1"

    assert models[1].name == "model-gw2-reasoner"
    assert models[1].provider == "openai_compatible"
    assert models[1].credential == "credential:cred-2"


@pytest.mark.asyncio
async def test_discover_openai_compatible_fallback_to_env_when_no_credentials(monkeypatch):
    """When no credentials exist, fall back to OPENAI_COMPATIBLE_BASE_URL with credential=None."""
    requests = []

    def handler(url, headers, params, timeout, extensions):
        requests.append({"url": url, "headers": headers})
        return json_response(url, {"data": [{"id": "env-model"}]})

    monkeypatch.setattr(
        model_discovery.Credential,
        "get_by_provider",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://env-gw.example.com/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "env-key")
    monkeypatch.setattr(
        model_discovery,
        "prepare_pinned_http_target",
        AsyncMock(side_effect=lambda url, prov: PinnedHttpTarget(url=url, headers={}, extensions={})),
    )
    monkeypatch.setattr(
        model_discovery.httpx, "AsyncClient", make_fake_client(handler)
    )

    models = await discover_openai_compatible_models()

    assert len(requests) == 1
    assert requests[0]["url"] == "https://env-gw.example.com/v1/models"
    assert requests[0]["headers"]["Authorization"] == "Bearer env-key"

    assert len(models) == 1
    assert models[0].name == "env-model"
    assert models[0].provider == "openai_compatible"
    assert models[0].credential is None
