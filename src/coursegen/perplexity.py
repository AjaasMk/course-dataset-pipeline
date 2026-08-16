from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from .config import Settings
from .retry import call_with_retry, transport_error_from_response

FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
SCHEMA_NAME_RE = re.compile(r"[^A-Za-z0-9_]")


class ProviderOutputError(RuntimeError):
    def __init__(self, message: str, *, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


@dataclass
class ChunkResponse:
    data: dict[str, Any]
    citations: list[str] = field(default_factory=list)
    search_results: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    raw_content: str = ""


def _strip_fence(text: str) -> str:
    match = FENCE_RE.match(text)
    return match.group(1) if match else text


def _schema_name(chunk_key: str) -> str:
    cleaned = SCHEMA_NAME_RE.sub("_", chunk_key).strip("_") or "course_chunk"
    return cleaned[:64]


class PerplexityClient:
    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=settings.request_timeout_seconds)
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        interval = self._settings.request_interval_seconds
        if interval <= 0:
            return
        if self._last_request_at is not None:
            elapsed = self._clock() - self._last_request_at
            if elapsed < interval:
                self._sleep(interval - elapsed)
        self._last_request_at = self._clock()

    def __enter__(self) -> PerplexityClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def build_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        schema_name: str,
        search_domains: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        settings = self._settings
        domains = settings.search_domains if search_domains is None else search_domains

        web_search: dict[str, Any] = {"type": "web_search"}
        filters: dict[str, Any] = {}
        if domains:
            filters["search_domain_filter"] = list(domains)
        if settings.search_recency:
            filters["search_recency_filter"] = settings.search_recency
        if filters:
            web_search["filters"] = filters

        payload: dict[str, Any] = {
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "tools": [web_search],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": _schema_name(schema_name), "schema": json_schema},
            },
        }
        if settings.perplexity_model:
            payload["model"] = settings.perplexity_model
        else:
            payload["preset"] = settings.perplexity_preset
        if settings.max_output_tokens:
            payload["max_output_tokens"] = settings.max_output_tokens
        return payload

    def complete_json(
        self,
        *,
        operation: str,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        search_domains: tuple[str, ...] | None = None,
    ) -> ChunkResponse:
        settings = self._settings
        payload = self.build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_schema=json_schema,
            schema_name=operation.split(":")[-1],
            search_domains=search_domains,
        )
        headers = {
            "Authorization": f"Bearer {settings.require_api_key()}",
            "Content-Type": "application/json",
        }
        url = f"{settings.perplexity_base_url.rstrip('/')}/v1/agent"

        def send() -> httpx.Response:
            self._throttle()
            response = self._client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                raise transport_error_from_response(response)
            return response

        response = call_with_retry(
            operation,
            send,
            max_retries=settings.transport_max_retries,
            base_delay_seconds=settings.transport_backoff_base_seconds,
            max_delay_seconds=settings.transport_backoff_max_seconds,
        )
        return self.parse(response.json())

    def parse(self, body: dict[str, Any]) -> ChunkResponse:
        if not isinstance(body, dict):
            raise ProviderOutputError("provider response was not a JSON object")

        output = body.get("output")
        if not isinstance(output, list) or not output:
            raise ProviderOutputError(
                "provider response contained no output items", raw=json.dumps(body)[:2000]
            )

        text_parts: list[str] = []
        search_results: list[dict[str, Any]] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "message":
                for part in item.get("content") or []:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        text_parts.append(part["text"])
            elif kind == "search_results":
                for result in item.get("results") or []:
                    if isinstance(result, dict):
                        search_results.append(result)

        content = "".join(text_parts).strip()
        if not content:
            raise ProviderOutputError(
                "provider returned no message text", raw=json.dumps(body)[:2000]
            )

        status = body.get("status")
        if status in {"incomplete", "failed"}:
            raise ProviderOutputError(
                f"provider reported status {status!r} before the JSON closed", raw=content[:2000]
            )

        try:
            data = json.loads(_strip_fence(content))
        except json.JSONDecodeError as exc:
            raise ProviderOutputError(
                f"provider content was not valid JSON: {exc}", raw=content[:2000]
            ) from exc

        if not isinstance(data, dict):
            raise ProviderOutputError("provider returned a non-object JSON value", raw=content[:2000])

        citations = [
            str(result["url"])
            for result in search_results
            if isinstance(result.get("url"), str)
        ]
        seen: list[str] = []
        for url in citations:
            if url not in seen:
                seen.append(url)

        return ChunkResponse(
            data=data,
            citations=seen,
            search_results=search_results,
            usage=dict(body.get("usage") or {}),
            raw_content=content,
        )


__all__ = ["ChunkResponse", "PerplexityClient", "ProviderOutputError"]
