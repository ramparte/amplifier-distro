"""Provider API Tests

Validates the live provider API interaction layer:
1. list_models() for each provider (filtering, sorting, fallback)
2. test_provider() connectivity checks (auth, errors, latency)

All HTTP calls are mocked — no real network traffic.
"""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from amplifier_distro.provider_api import (
    ModelListResult,
    ProviderTestResult,
    list_models,
)
from amplifier_distro.provider_api import (
    test_provider as run_test_provider,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


@pytest.fixture
def mock_client():
    """Create a mock httpx.AsyncClient as async context manager."""
    client = AsyncMock()
    with patch("amplifier_distro.provider_api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        yield client


# ---------------------------------------------------------------------------
# list_models tests
# ---------------------------------------------------------------------------


class TestListModelsErrors:
    """Tests for list_models error / fallback paths."""

    @pytest.mark.asyncio
    async def test_list_models_unknown_provider(self):
        result = await list_models("nonexistent")

        assert isinstance(result, ModelListResult)
        assert result.models == []
        assert result.from_api is False
        assert result.error is not None
        assert "Unknown provider" in result.error

    @pytest.mark.asyncio
    async def test_list_models_missing_api_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = await list_models("anthropic")

        assert result.from_api is False
        assert result.error is not None
        assert "not set" in result.error
        # Should return fallback models from the PROVIDERS catalog
        assert len(result.models) > 0

    @pytest.mark.asyncio
    async def test_list_models_api_error_falls_back(self, mock_client: AsyncMock):
        mock_client.get.side_effect = httpx.ConnectError("connection refused")

        result = await list_models("anthropic", api_key="test-key")

        assert result.from_api is False
        assert result.error is not None
        assert len(result.models) > 0  # fallback models

    @pytest.mark.asyncio
    async def test_list_models_azure_fallback(self):
        result = await list_models("azure")

        assert result.from_api is False
        assert result.error is not None
        assert "deployment-specific" in result.error
        assert len(result.models) > 0


class TestListModelsAnthropic:
    """Tests for Anthropic model listing."""

    @pytest.mark.asyncio
    async def test_list_models_anthropic_success(self, mock_client: AsyncMock):
        mock_client.get.return_value = _mock_response(
            json_data={
                "data": [
                    {"id": "claude-sonnet-4-5"},
                    {"id": "claude-3-opus-20240229"},
                    {"id": "claude-haiku-4-5"},
                    {"id": "some-new-model"},
                ]
            }
        )

        result = await list_models("anthropic", api_key="test-key")

        assert result.from_api is True
        assert result.error is None
        # Legacy model claude-3-opus-20240229 should be filtered out
        assert "claude-3-opus-20240229" not in result.models
        # Aliases prepended first
        assert result.models[:3] == [
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "claude-opus-4-5",
        ]
        # New model from API should be included
        assert "some-new-model" in result.models


class TestListModelsOpenAI:
    """Tests for OpenAI model listing."""

    @pytest.mark.asyncio
    async def test_list_models_openai_success(self, mock_client: AsyncMock):
        mock_client.get.return_value = _mock_response(
            json_data={
                "data": [
                    {"id": "gpt-4o"},
                    {"id": "gpt-4o-mini"},
                    {"id": "gpt-5"},
                    {"id": "tts-1"},
                    {"id": "text-embedding-ada-002"},
                    {"id": "gpt-3.5-turbo"},
                    {"id": "o3-mini"},
                ]
            }
        )

        result = await list_models("openai", api_key="test-key")

        assert result.from_api is True
        # tts-1: no include substring match
        assert "tts-1" not in result.models
        # text-embedding-ada-002: no include substring match
        assert "text-embedding-ada-002" not in result.models
        # gpt-3.5-turbo: legacy prefix gpt-3
        assert "gpt-3.5-turbo" not in result.models
        # Priority sort: gpt-5 > o3-mini > gpt-4o
        remaining = [m for m in result.models if m in {"gpt-5", "o3-mini", "gpt-4o"}]
        assert remaining == ["gpt-5", "o3-mini", "gpt-4o"]


class TestListModelsGoogle:
    """Tests for Google Gemini model listing."""

    GOOGLE_RESPONSE: ClassVar[dict] = {
        "models": [
            {"name": "models/gemini-2.5-pro"},
            {"name": "models/gemini-2.5-flash"},
            {"name": "models/gemini-1.5-pro"},
            {"name": "models/text-embedding-004"},
            {"name": "models/gemini-3-ultra"},
        ]
    }

    @pytest.mark.asyncio
    async def test_list_models_google_success(self, mock_client: AsyncMock):
        mock_client.get.return_value = _mock_response(json_data=self.GOOGLE_RESPONSE)

        result = await list_models("google", api_key="test-key")

        assert result.from_api is True
        # gemini-1.5-pro excluded (legacy prefix)
        assert "gemini-1.5-pro" not in result.models
        # text-embedding-004 excluded (no "gemini" in name)
        assert "text-embedding-004" not in result.models
        # models/ prefix stripped
        assert all(not m.startswith("models/") for m in result.models)
        # gemini-3-ultra sorts first (gemini-3 priority)
        assert result.models[0] == "gemini-3-ultra"

    @pytest.mark.asyncio
    async def test_list_models_alias_resolution(self, mock_client: AsyncMock):
        """Calling with 'gemini' resolves to 'google' provider."""
        mock_client.get.return_value = _mock_response(json_data=self.GOOGLE_RESPONSE)

        result = await list_models("gemini", api_key="test-key")

        assert result.from_api is True
        assert result.provider == "google"
        assert "gemini-3-ultra" in result.models


class TestListModelsXAI:
    """Tests for xAI Grok model listing."""

    @pytest.mark.asyncio
    async def test_list_models_xai_success(self, mock_client: AsyncMock):
        mock_client.get.return_value = _mock_response(
            json_data={
                "data": [
                    {"id": "grok-4"},
                    {"id": "grok-3"},
                    {"id": "grok-2-vision"},
                    {"id": "some-other-model"},
                ]
            }
        )

        result = await list_models("xai", api_key="test-key")

        assert result.from_api is True
        # grok-2-vision excluded (legacy prefix grok-2)
        assert "grok-2-vision" not in result.models
        # some-other-model excluded (no "grok" in name)
        assert "some-other-model" not in result.models
        # grok-4 sorts first
        assert result.models[0] == "grok-4"


class TestListModelsOllama:
    """Tests for Ollama model listing."""

    @pytest.mark.asyncio
    async def test_list_models_ollama(self, mock_client: AsyncMock):
        mock_client.get.return_value = _mock_response(
            json_data={
                "models": [
                    {"name": "llama3.1"},
                    {"name": "mistral"},
                ]
            }
        )

        result = await list_models("ollama")

        assert result.from_api is True
        assert "llama3.1" in result.models
        assert "mistral" in result.models


# ---------------------------------------------------------------------------
# test_provider tests
# ---------------------------------------------------------------------------


class TestProviderErrors:
    """Tests for test_provider error paths."""

    @pytest.mark.asyncio
    async def test_provider_unknown(self):
        result = await run_test_provider("nonexistent")

        assert isinstance(result, ProviderTestResult)
        assert result.success is False
        assert result.error is not None
        assert "Unknown provider" in result.error

    @pytest.mark.asyncio
    async def test_provider_missing_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = await run_test_provider("anthropic")

        assert result.success is False
        assert result.error is not None
        assert "not set" in result.error

    @pytest.mark.asyncio
    async def test_provider_connection_error(self, mock_client: AsyncMock):
        """ConnectError caught inside _test_anthropic → partial result."""
        mock_client.post.side_effect = httpx.ConnectError("connection refused")

        result = await run_test_provider("anthropic", api_key="test-key")

        assert result.success is False
        assert result.latency_ms >= 0
        # Connection failed inside _test_anthropic
        assert result.tests["connection"] is False


class TestProviderAnthropic:
    """Tests for Anthropic provider connectivity."""

    @pytest.mark.asyncio
    async def test_provider_anthropic_success(self, mock_client: AsyncMock):
        mock_client.post.return_value = _mock_response(status_code=200)

        result = await run_test_provider("anthropic", api_key="test-key")

        assert result.success is True
        assert result.tests["connection"] is True
        assert result.tests["authentication"] is True
        assert result.tests["model_call"] is True
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_provider_anthropic_auth_failure(self, mock_client: AsyncMock):
        mock_client.post.return_value = _mock_response(status_code=401)

        result = await run_test_provider("anthropic", api_key="bad-key")

        assert result.success is False
        assert result.tests["connection"] is True
        assert result.tests["authentication"] is False


class TestProviderOpenAI:
    """Tests for OpenAI provider connectivity."""

    @pytest.mark.asyncio
    async def test_provider_openai_success(self, mock_client: AsyncMock):
        # OpenAI test does GET /models then POST /chat/completions
        mock_client.get.return_value = _mock_response(status_code=200)
        mock_client.post.return_value = _mock_response(status_code=200)

        result = await run_test_provider("openai", api_key="test-key")

        assert result.success is True
        assert result.tests["connection"] is True
        assert result.tests["authentication"] is True
        assert result.tests["model_list"] is True
        assert result.tests["model_call"] is True


class TestProviderGoogle:
    """Tests for Google Gemini provider connectivity."""

    @pytest.mark.asyncio
    async def test_provider_google_success(self, mock_client: AsyncMock):
        mock_client.post.return_value = _mock_response(status_code=200)

        result = await run_test_provider("google", api_key="test-key")

        assert result.success is True
        assert result.tests["connection"] is True
        assert result.tests["authentication"] is True
        assert result.tests["model_call"] is True

    @pytest.mark.asyncio
    async def test_provider_google_auth_failure(self, mock_client: AsyncMock):
        mock_client.post.return_value = _mock_response(status_code=403)

        result = await run_test_provider("google", api_key="bad-key")

        assert result.success is False
        assert result.tests["connection"] is True
        assert result.tests["authentication"] is False


class TestProviderXAI:
    """Tests for xAI Grok provider connectivity."""

    @pytest.mark.asyncio
    async def test_provider_xai_success(self, mock_client: AsyncMock):
        mock_client.post.return_value = _mock_response(status_code=200)

        result = await run_test_provider("xai", api_key="test-key")

        assert result.success is True
        assert result.tests["connection"] is True
        assert result.tests["authentication"] is True
        assert result.tests["model_call"] is True


class TestProviderOllama:
    """Tests for Ollama provider connectivity."""

    @pytest.mark.asyncio
    async def test_provider_ollama_success(self):
        """Mock _list_ollama to simulate a running Ollama instance."""
        with patch(
            "amplifier_distro.provider_api._list_ollama",
            new_callable=AsyncMock,
            return_value=["llama3.1", "mistral"],
        ):
            result = await run_test_provider("ollama")

        assert result.success is True
        assert result.tests["connection"] is True
        assert result.tests["model_list"] is True
        assert result.models == ["llama3.1", "mistral"]
