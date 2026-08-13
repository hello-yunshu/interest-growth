from __future__ import annotations

import json
import socket
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable, Protocol
from urllib.error import HTTPError, URLError

from .errors import (
    ProviderAuthError, ProviderProtocolError, ProviderRateLimited,
    ProviderTimeout, ProviderUnavailable,
)

@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    tool_calls: tuple[dict[str, Any], ...] = ()
    usage: dict[str, int] | None = None
    finish_reason: str | None = None
    # auto: text is answer-visible only when no tool calls occur in that round.
    # answer/narration allow adapters to explicitly classify upstream segments.
    text_visibility: str = "auto"

@dataclass(frozen=True, slots=True)
class LLMStreamEvent:
    type: str  # answer_delta | narration_delta | tool_call | done
    text: str = ""
    tool_call: dict[str, Any] | None = None
    usage: dict[str, int] | None = None
    finish_reason: str | None = None

class LLMClient(Protocol):
    available: bool
    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse: ...

class UnavailableLLM:
    available = False
    def complete(self, **kwargs) -> LLMResponse:
        raise ProviderUnavailable("no LLM execution provider is configured")

class DeterministicLLM:
    """TEST-ONLY deterministic executor."""
    available = True
    test_only = True
    def __init__(self, prefix: str = "TEST") -> None:
        self.prefix = prefix

    def complete(self, *, messages, tools=None, temperature=0.2, response_format=None):
        _ = tools, temperature, response_format
        last = next(
            (str(x.get("content", "")) for x in reversed(messages) if x.get("role") == "user"),
            "",
        )
        return LLMResponse(f"{self.prefix}:{last}")

    def stream(self, **kwargs):
        response = self.complete(**kwargs)
        if response.text:
            yield LLMStreamEvent("answer_delta", text=response.text)
        yield LLMStreamEvent("done", finish_reason="stop")

class OpenAICompatibleClient:
    """Minimal OpenAI-compatible HTTP client with real SSE streaming.

    For complete(), finish_reason=length is continued with a strict bounded
    number of requests. For stream(), text is streamed to the caller and tool
    call deltas are assembled before emitting the tool_call event.
    """
    available = True

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        max_continuations: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_continuations = max(0, min(int(max_continuations), 4))

    @staticmethod
    def _merge_usage(total: dict[str, int], current: dict[str, Any] | None):
        for key, value in (current or {}).items():
            if isinstance(value, (int, float)):
                total[key] = total.get(key, 0) + int(value)

    @staticmethod
    def _decode_args(raw: Any) -> dict[str, Any]:
        value = raw
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return {"raw": value}
        if isinstance(value, dict):
            return value
        return {"value": value}

    @classmethod
    def _decode_tool_calls(cls, message: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        out = []
        for raw in message.get("tool_calls") or ():
            fn = raw.get("function") or {}
            out.append({
                "id": raw.get("id", ""),
                "name": fn.get("name", ""),
                "arguments": cls._decode_args(fn.get("arguments", {})),
            })
        return tuple(out)

    def _payload(self, *, messages, tools, temperature, response_format, stream=False):
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        if response_format:
            payload["response_format"] = response_format
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    @staticmethod
    def _raise_http(exc: HTTPError) -> None:
        # Normalized transport taxonomy. Messages never echo request headers,
        # API keys, tokens or the request body.
        status = int(exc.code)
        if status in (401, 403):
            raise ProviderAuthError("provider rejected credentials") from exc
        if status == 429:
            raise ProviderRateLimited("provider rate limit exceeded") from exc
        if status >= 500:
            raise ProviderUnavailable("provider server error") from exc
        raise ProviderProtocolError("provider returned unexpected HTTP status") from exc

    @staticmethod
    def _raise_transport(exc: BaseException | str) -> None:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            raise ProviderTimeout("provider request timed out") from exc
        cause = exc if isinstance(exc, BaseException) else None
        raise ProviderUnavailable("provider connection failed") from cause

    def _open(self, req: urllib.request.Request):
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except HTTPError as exc:
            self._raise_http(exc)
        except URLError as exc:
            self._raise_transport(exc.reason if getattr(exc, "reason", None) is not None else exc)
        except (TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
            self._raise_transport(exc)

    def _request_json(self, payload):
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self._open(req) as resp:
            raw = resp.read().decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderProtocolError("provider returned invalid JSON") from exc

    def _complete_data(self, data):
        if not isinstance(data, dict):
            raise ProviderProtocolError("provider response schema unexpected")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderProtocolError("provider response schema unexpected")
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ProviderProtocolError("provider response schema unexpected")
        return choice

    def complete(self, *, messages, tools=None, temperature=0.2, response_format=None):
        work = list(messages)
        parts: list[str] = []
        usage_total: dict[str, int] = {}
        final_reason = None
        for continuation in range(self.max_continuations + 1):
            data = self._request_json(self._payload(
                messages=work, tools=tools, temperature=temperature,
                response_format=response_format,
            ))
            choice = self._complete_data(data)
            msg = choice["message"]
            reason = choice.get("finish_reason")
            final_reason = str(reason) if reason is not None else None
            self._merge_usage(usage_total, data.get("usage"))
            text = msg.get("content") or ""
            calls = self._decode_tool_calls(msg)
            if text:
                parts.append(text)
            if calls:
                return LLMResponse(
                    "".join(parts), calls, usage_total or None, final_reason, "auto"
                )
            if reason != "length" or continuation >= self.max_continuations:
                return LLMResponse(
                    "".join(parts), (), usage_total or None, final_reason, "answer"
                )
            work.extend([
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": (
                        "Continue exactly from where the previous response was truncated. "
                        "Do not restart or repeat prior text."
                    ),
                },
            ])
        return LLMResponse("".join(parts), (), usage_total or None, final_reason, "answer")

    def _open_stream(self, payload):
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        return self._open(req)

    def stream(self, *, messages, tools=None, temperature=0.2, response_format=None):
        payload = self._payload(
            messages=messages, tools=tools, temperature=temperature,
            response_format=response_format, stream=True,
        )
        tool_acc: dict[int, dict[str, Any]] = {}
        finish_reason = None
        usage = None
        with self._open_stream(payload) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise ProviderProtocolError("provider stream event invalid JSON") from exc
                if obj.get("usage"):
                    usage = obj["usage"]
                choices = obj.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or {}
                content = delta.get("content") or ""
                # OpenAI-compatible streams don't reliably classify narration
                # before tool_calls. Buffer it until the round's nature is known.
                if content:
                    yield LLMStreamEvent("answer_delta" if not tools else "narration_delta", text=content)
                for raw_call in delta.get("tool_calls") or ():
                    idx = int(raw_call.get("index", 0))
                    entry = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments_raw": ""})
                    if raw_call.get("id"):
                        entry["id"] += str(raw_call["id"])
                    fn = raw_call.get("function") or {}
                    if fn.get("name"):
                        entry["name"] += str(fn["name"])
                    if fn.get("arguments"):
                        entry["arguments_raw"] += str(fn["arguments"])
        if tool_acc:
            for idx in sorted(tool_acc):
                item = tool_acc[idx]
                yield LLMStreamEvent(
                    "tool_call",
                    tool_call={
                        "id": item["id"],
                        "name": item["name"],
                        "arguments": self._decode_args(item["arguments_raw"]),
                    },
                )
        yield LLMStreamEvent(
            "done", usage=usage, finish_reason=finish_reason
        )
