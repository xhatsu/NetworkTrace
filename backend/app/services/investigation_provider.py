"""Small injected provider boundary for the fixed investigation prompt."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from backend.app.models.investigation import AssessmentV1


class ProviderFailure(RuntimeError):
    def __init__(self, code: str, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class GenerationRequest:
    run_id: str
    model: str
    messages: list[dict[str, str]]
    max_tokens: int = 4000
    response_mode: str = "json_object"


@dataclass(frozen=True)
class ProviderReply:
    content: dict[str, Any]
    reported_model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_tokens: bool = False
    finish_reason: str | None = None
    latency_ms: int = 0


class LLMProvider(Protocol):
    async def generate(self, request: GenerationRequest, deadline_ms: int) -> ProviderReply: ...


def _parse_object(value: str) -> dict[str, Any]:
    def reject(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ProviderFailure("invalid_output")
            result[key] = item
        return result

    if not isinstance(value, str):
        raise ProviderFailure("invalid_output")

    clean_value = value.strip()
    if "<think>" in clean_value and "</think>" in clean_value:
        clean_value = clean_value.split("</think>", 1)[1].strip()

    if clean_value.startswith("```"):
        lines = clean_value.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            if lines[-1].strip() == "```":
                clean_value = "\n".join(lines[1:-1]).strip()
            else:
                clean_value = "\n".join(lines[1:]).strip()

    if not clean_value.startswith("{") and "{" in clean_value:
        start_idx = clean_value.find("{")
        end_idx = clean_value.rfind("}")
        if end_idx > start_idx:
            clean_value = clean_value[start_idx:end_idx + 1].strip()

    try:
        parsed = json.loads(clean_value, object_pairs_hook=reject, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except ProviderFailure:
        raise
    except Exception as exc:
        raise ProviderFailure("invalid_output") from exc
    if not isinstance(parsed, dict):
        raise ProviderFailure("invalid_output")
    return parsed


class OpenAICompatibleProvider:
    name = "openai_compatible_relay"

    def __init__(self, settings_obj: Any, client: httpx.AsyncClient | None = None):
        self.settings = settings_obj
        self._client = client
        self._validate_settings()

    def _validate_settings(self) -> None:
        if not getattr(self.settings, "llm_base_url", ""):
            raise ProviderFailure("provider_unconfigured")
        parsed = urlparse(self.settings.llm_base_url)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.rstrip("/") not in {"", "/v1"}:
            raise ProviderFailure("invalid_provider_url")
        loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback and getattr(self.settings, "llm_allow_loopback_http", False)):
            raise ProviderFailure("provider_https_required")
        if not getattr(self.settings, "llm_model", "") or not getattr(self.settings, "llm_api_key", ""):
            raise ProviderFailure("provider_unconfigured")
        if getattr(self.settings, "llm_response_mode", "") not in {"json_schema", "json_object"}:
            raise ProviderFailure("invalid_response_mode")

    async def generate(self, request: GenerationRequest, deadline_ms: int) -> ProviderReply:
        if not request.messages or request.model != self.settings.llm_model or request.response_mode != self.settings.llm_response_mode:
            raise ProviderFailure("invalid_provider_request")
        started = time.monotonic()
        response_format: dict[str, Any] = {"type": request.response_mode}
        if request.response_mode == "json_schema":
            response_format["json_schema"] = {"name": "assessment_v1", "strict": True, "schema": AssessmentV1.model_json_schema()}
        if deadline_ms <= int(time.time() * 1000):
            raise ProviderFailure("provider_timeout", True)
        payload = {"model": request.model, "messages": request.messages, "max_tokens": min(4000, request.max_tokens), "response_format": response_format}
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(base_url=self.settings.llm_base_url, verify=True,
            timeout=httpx.Timeout(45.0, connect=3.0, read=45.0), follow_redirects=False, trust_env=False,
            headers={"Authorization": "Bearer " + getattr(self.settings, "llm_api_key", ""), "Content-Type": "application/json"})
        try:
            remaining = (deadline_ms - int(time.time() * 1000)) / 1000.0
            if remaining <= 0:
                raise ProviderFailure("provider_timeout", True)
            try:
                response = await asyncio.wait_for(client.post("chat/completions", json=payload, headers={
                    "Authorization": "Bearer " + getattr(self.settings, "llm_api_key", ""),
                    "Content-Type": "application/json",
                }), timeout=min(45.0, remaining))
            except asyncio.TimeoutError as exc:
                raise ProviderFailure("provider_timeout", True) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise ProviderFailure("provider_unavailable", True) from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                raise ProviderFailure("provider_redirect")
            if response.status_code in {401, 403}:
                raise ProviderFailure("provider_auth")
            if response.status_code == 429:
                raise ProviderFailure("provider_rate_limited", True)
            if response.status_code >= 500:
                raise ProviderFailure("provider_server_error", True)
            if response.status_code != 200 or len(response.content) > 64 * 1024:
                raise ProviderFailure("provider_invalid_response")
            try:
                envelope = response.json()
                if not isinstance(envelope, dict) or not isinstance(envelope.get("choices"), list) or not envelope["choices"]:
                    raise ProviderFailure("invalid_output")
                choice = envelope["choices"][0]
                if not isinstance(choice, dict):
                    raise ProviderFailure("invalid_output")
                message = choice.get("message", {})
                if not isinstance(message, dict):
                    raise ProviderFailure("invalid_output")
                if message.get("tool_calls") or message.get("refusal"):
                    raise ProviderFailure("provider_refused")
                content = message.get("content")
                if not isinstance(content, str):
                    raise ProviderFailure("invalid_output")
                parsed = _parse_object(content)
            except ProviderFailure:
                raise
            except Exception as exc:
                raise ProviderFailure("invalid_output") from exc
            usage = envelope.get("usage", {})
            if not isinstance(usage, dict):
                usage = {}
            finish = choice.get("finish_reason")
            reported_model = envelope.get("model")
            if not isinstance(reported_model, str):
                reported_model = None
            return ProviderReply(content=parsed, reported_model=reported_model,
                input_tokens=int(usage["prompt_tokens"]) if isinstance(usage.get("prompt_tokens"), int) and not isinstance(usage.get("prompt_tokens"), bool) and usage["prompt_tokens"] >= 0 else None,
                output_tokens=int(usage["completion_tokens"]) if isinstance(usage.get("completion_tokens"), int) and not isinstance(usage.get("completion_tokens"), bool) and usage["completion_tokens"] >= 0 else None,
                finish_reason=finish if finish in {"stop", "length", "content_filter"} else None,
                latency_ms=int((time.monotonic() - started) * 1000))
        finally:
            if own_client:
                await client.aclose()
