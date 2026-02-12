"""Live provider API interactions for model listing and connectivity testing.

This module provides two public async functions — ``list_models`` and
``test_provider`` — that reach out to each provider's REST API to enumerate
available models or verify that credentials work.  Both functions return
result dataclasses and **never raise**; errors are captured in the result's
``error`` field with graceful fallback to the catalog defaults defined in
``features.py``.

Public API
----------
- ``ModelListResult``   — result of a model-listing call
- ``ProviderTestResult`` — result of a connectivity / auth test
- ``list_models()``      — list models for a provider (async)
- ``test_provider()``    — test provider health (async)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import httpx

from amplifier_distro.features import PROVIDERS, resolve_provider

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ModelListResult:
    """Outcome of a model-listing request."""

    provider: str
    models: list[str]
    from_api: bool  # True if live API call succeeded
    error: str | None = None


@dataclass
class ProviderTestResult:
    """Outcome of a provider connectivity test."""

    provider: str
    success: bool
    tests: dict[str, bool] = field(default_factory=dict)
    latency_ms: int = 0
    models: list[str] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_TIMEOUT = 15.0

# ---------------------------------------------------------------------------
# Private: model listing per provider
# ---------------------------------------------------------------------------


async def _list_anthropic(api_key: str) -> list[str]:
    """List Anthropic models, filtering legacy and prepending aliases."""

    aliases = ["claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-5"]

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        resp.raise_for_status()

    ids: list[str] = [m["id"] for m in resp.json()["data"]]

    # Filter out legacy families
    legacy_prefixes = ("claude-3-", "claude-2", "claude-instant")
    ids = [mid for mid in ids if not any(mid.startswith(p) for p in legacy_prefixes)]

    # Prepend aliases, then API models — deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for mid in aliases + ids:
        if mid not in seen:
            seen.add(mid)
            result.append(mid)

    return result


async def _list_openai(api_key: str) -> list[str]:
    """List OpenAI models, filtering to chat-relevant ones with priority sort."""

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()

    ids: list[str] = [m["id"] for m in resp.json()["data"]]

    # Include only models containing at least one of these substrings
    include = ("gpt-4o", "gpt-5", "o1", "o3", "o4", "chatgpt")
    ids = [mid for mid in ids if any(sub in mid for sub in include)]

    # Exclude non-chat modalities
    exclude = (
        "tts",
        "transcribe",
        "whisper",
        "embed",
        "moderation",
        "realtime",
        "audio",
        "search",
    )
    ids = [mid for mid in ids if not any(sub in mid for sub in exclude)]

    # Exclude legacy families
    legacy_prefixes = ("gpt-4-", "gpt-3", "davinci", "babbage", "curie", "gpt-4-turbo")
    ids = [mid for mid in ids if not any(mid.startswith(p) for p in legacy_prefixes)]

    # Priority sort — models matching earlier prefixes rank higher
    priority = ["gpt-5.2", "gpt-5.1", "gpt-5", "o4", "o3", "o1", "gpt-4o"]

    def _sort_key(model_id: str) -> tuple[int, str]:
        for idx, prefix in enumerate(priority):
            if model_id.startswith(prefix):
                return (idx, model_id)
        return (len(priority), model_id)

    ids.sort(key=_sort_key)
    return ids[:20]


async def _list_google(api_key: str) -> list[str]:
    """List Google Gemini models."""

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key},
        )
        resp.raise_for_status()

    # Names arrive as "models/gemini-2.5-pro" — strip prefix
    names: list[str] = [
        m["name"].removeprefix("models/") for m in resp.json()["models"]
    ]

    # Keep only gemini, exclude embeddings
    names = [n for n in names if "gemini" in n and "embedding" not in n]

    # Exclude legacy families
    legacy_prefixes = ("gemini-1.0", "gemini-1.5", "gemini-pro", "gemini-nano")
    names = [n for n in names if not any(n.startswith(p) for p in legacy_prefixes)]

    # Priority sort: gemini-3 first, gemini-2.5 second, others third
    def _sort_key(name: str) -> tuple[int, str]:
        if name.startswith("gemini-3"):
            return (0, name)
        if name.startswith("gemini-2.5"):
            return (1, name)
        return (2, name)

    names.sort(key=_sort_key)
    return names[:15]


async def _list_xai(api_key: str) -> list[str]:
    """List xAI Grok models."""

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()

    ids: list[str] = [m["id"] for m in resp.json()["data"]]

    # Keep only grok models
    ids = [mid for mid in ids if "grok" in mid.lower()]

    # Exclude legacy families
    legacy_prefixes = ("grok-1", "grok-2")
    ids = [mid for mid in ids if not any(mid.startswith(p) for p in legacy_prefixes)]

    # grok-4 first, rest alphabetical
    def _sort_key(model_id: str) -> tuple[int, str]:
        if model_id.startswith("grok-4"):
            return (0, model_id)
        return (1, model_id)

    ids.sort(key=_sort_key)
    return ids[:15]


async def _list_ollama(host: str) -> list[str]:
    """List locally-running Ollama models."""

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"http://{host}/api/tags")
        resp.raise_for_status()

    return [m["name"] for m in resp.json()["models"]]


# ---------------------------------------------------------------------------
# Private: provider testing
# ---------------------------------------------------------------------------


async def _test_anthropic(api_key: str) -> dict:
    """Test Anthropic connectivity, auth, and model call."""

    result = {
        "connection": False,
        "authentication": False,
        "model_list": True,
        "model_call": False,
    }
    models: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )
        result["connection"] = True
        result["authentication"] = resp.status_code != 401
        result["model_call"] = resp.status_code == 200
    except (httpx.HTTPError, KeyError, ValueError, OSError):
        pass  # Connection/request failed; partial result returned

    return {**result, "models": models}


async def _test_openai(api_key: str) -> dict:
    """Test OpenAI connectivity, auth, model listing, and model call."""

    result = {
        "connection": False,
        "authentication": False,
        "model_list": False,
        "model_call": False,
    }
    models: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # 1) Model list
            list_resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            result["connection"] = True
            result["authentication"] = list_resp.status_code != 401
            result["model_list"] = list_resp.status_code == 200

            # 2) Chat completion
            chat_resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )
            result["model_call"] = chat_resp.status_code == 200
    except (httpx.HTTPError, KeyError, ValueError, OSError):
        pass  # Connection/request failed; partial result returned

    return {**result, "models": models}


async def _test_google(api_key: str) -> dict:
    """Test Google Gemini connectivity, auth, and model call."""

    result = {
        "connection": False,
        "authentication": False,
        "model_list": True,
        "model_call": False,
    }
    models: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent",
                params={"key": api_key},
                json={"contents": [{"parts": [{"text": "Hi"}]}]},
            )
        result["connection"] = True
        result["authentication"] = resp.status_code != 403
        result["model_call"] = resp.status_code == 200
    except (httpx.HTTPError, KeyError, ValueError, OSError):
        pass  # Connection/request failed; partial result returned

    return {**result, "models": models}


async def _test_xai(api_key: str) -> dict:
    """Test xAI Grok connectivity, auth, and model call."""

    result = {
        "connection": False,
        "authentication": False,
        "model_list": True,
        "model_call": False,
    }
    models: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "grok-3",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )
        result["connection"] = True
        result["authentication"] = resp.status_code != 401
        result["model_call"] = resp.status_code == 200
    except (httpx.HTTPError, KeyError, ValueError, OSError):
        pass  # Connection/request failed; partial result returned

    return {**result, "models": models}


async def _test_ollama(host: str) -> dict:
    """Test Ollama connectivity by listing local models."""

    result = {
        "connection": False,
        "authentication": True,
        "model_list": False,
        "model_call": False,
    }
    models: list[str] = []

    try:
        models = await _list_ollama(host)
        result["connection"] = True
        result["model_list"] = len(models) > 0
        result["model_call"] = result["model_list"]
    except (httpx.HTTPError, KeyError, ValueError, OSError):
        pass  # Connection/request failed; partial result returned

    return {**result, "models": models}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Dispatch tables for provider-specific implementations
_LIST_DISPATCH: dict[str, object] = {
    "anthropic": _list_anthropic,
    "openai": _list_openai,
    "google": _list_google,
    "xai": _list_xai,
}

_TEST_DISPATCH: dict[str, object] = {
    "anthropic": _test_anthropic,
    "openai": _test_openai,
    "google": _test_google,
    "xai": _test_xai,
}


async def list_models(
    provider_name: str, api_key: str | None = None
) -> ModelListResult:
    """List available models for a provider.

    Calls the provider's model-listing API and returns the results.  On any
    failure the response falls back to the catalog defaults from
    ``features.PROVIDERS`` so callers always get a usable model list.

    Args:
        provider_name: Provider identifier (accepts aliases like "gemini").
        api_key: Optional API key override; falls back to the provider's
            configured environment variable.

    Returns:
        ``ModelListResult`` with the model list and metadata.  Check
        ``from_api`` to know whether the list is live or a fallback.
    """

    name = resolve_provider(provider_name)

    if name not in PROVIDERS:
        return ModelListResult(
            provider=name, models=[], from_api=False, error=f"Unknown provider: {name}"
        )

    provider = PROVIDERS[name]
    key = api_key or os.environ.get(provider.env_var, "")

    # Azure — deployment-specific, cannot enumerate generically
    if name == "azure":
        return ModelListResult(
            provider=name,
            models=list(provider.fallback_models),
            from_api=False,
            error="Azure OpenAI requires deployment-specific configuration",
        )

    # Ollama — no auth, uses host instead of API key
    if name == "ollama":
        host = key or "localhost:11434"
        try:
            models = await _list_ollama(host)
            return ModelListResult(provider=name, models=models, from_api=True)
        except (httpx.HTTPError, KeyError, ValueError, OSError) as exc:
            return ModelListResult(
                provider=name,
                models=list(provider.fallback_models),
                from_api=False,
                error=str(exc),
            )

    # All other providers require an API key
    if not key:
        return ModelListResult(
            provider=name,
            models=list(provider.fallback_models),
            from_api=False,
            error=f"{provider.env_var} not set",
        )

    try:
        fn = _LIST_DISPATCH[name]
        models = await fn(key)  # type: ignore[operator]
        return ModelListResult(provider=name, models=models, from_api=True)
    except (httpx.HTTPError, KeyError, ValueError, OSError) as exc:
        return ModelListResult(
            provider=name,
            models=list(provider.fallback_models),
            from_api=False,
            error=str(exc),
        )


async def test_provider(
    provider_name: str, api_key: str | None = None
) -> ProviderTestResult:
    """Test provider connectivity, authentication, and model calling.

    Performs a lightweight end-to-end health check against the provider's
    API and returns structured results.

    Args:
        provider_name: Provider identifier (accepts aliases like "gemini").
        api_key: Optional API key override; falls back to the provider's
            configured environment variable.

    Returns:
        ``ProviderTestResult`` with per-check booleans and overall success.
    """

    name = resolve_provider(provider_name)

    if name not in PROVIDERS:
        return ProviderTestResult(
            provider=name,
            success=False,
            error=f"Unknown provider: {name}",
        )

    provider = PROVIDERS[name]
    key = api_key or os.environ.get(provider.env_var, "")

    # Azure — deployment-specific, cannot test generically
    if name == "azure":
        return ProviderTestResult(
            provider=name,
            success=False,
            error="Azure OpenAI requires deployment-specific configuration",
        )

    # Ollama — no auth, uses host
    if name == "ollama":
        host = key or "localhost:11434"
        start = time.monotonic()
        try:
            info = await _test_ollama(host)
            latency_ms = int((time.monotonic() - start) * 1000)
            tests = {k: v for k, v in info.items() if k != "models"}
            return ProviderTestResult(
                provider=name,
                success=all(tests.values()),
                tests=tests,
                latency_ms=latency_ms,
                models=info["models"],
            )
        except (httpx.HTTPError, KeyError, ValueError, OSError) as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            return ProviderTestResult(
                provider=name,
                success=False,
                latency_ms=latency_ms,
                error=str(exc),
            )

    # All other providers require an API key
    if not key:
        return ProviderTestResult(
            provider=name,
            success=False,
            error=f"{provider.env_var} not set",
        )

    fn = _TEST_DISPATCH.get(name)
    if fn is None:
        return ProviderTestResult(
            provider=name,
            success=False,
            error=f"No test implementation for provider: {name}",
        )

    start = time.monotonic()
    try:
        info = await fn(key)  # type: ignore[operator]
        latency_ms = int((time.monotonic() - start) * 1000)
        tests = {k: v for k, v in info.items() if k != "models"}
        return ProviderTestResult(
            provider=name,
            success=all(tests.values()),
            tests=tests,
            latency_ms=latency_ms,
            models=info["models"],
        )
    except (httpx.HTTPError, KeyError, ValueError, OSError) as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return ProviderTestResult(
            provider=name,
            success=False,
            latency_ms=latency_ms,
            error=str(exc),
        )
