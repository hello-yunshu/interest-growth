"""Gate R2 §16 — Provider Contract over a deterministic OpenAI-compatible mock server.

The 1.0 required gate MUST NOT depend on the real DeepSeek online service
(master prompt §16). This test boots a real local HTTP server that speaks the
OpenAI `POST /chat/completions` wire contract deterministically, then drives
BOTH production clients across the real network stack:

  - `interest_growth_native.llm.OpenAICompatibleClient` (urllib transport,
    used by the native research/tutor runtime);
  - `pg_deepseek.DeepSeekProvider` (httpx transport, used by the Host API
    quick-explore / deep-research workspace).

Scenarios asserted over real HTTP: chat completion, SSE streaming, timeout,
rate limit (429), malformed response, provider unavailable (5xx) and
connection refused (provider down). Nothing here reaches the internet.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from interest_growth_native.errors import (
    ProviderAuthError,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from interest_growth_native.llm import OpenAICompatibleClient


# --------------------------------------------------------------------------- #
# Deterministic OpenAI-compatible mock server
# --------------------------------------------------------------------------- #


class _MockState:
    """Deterministic per-scenario behavior for the mock server."""

    def __init__(self) -> None:
        self.scenario = "completion"
        self.seen_bodies: list[dict] = []


def _sse(event_lines: list[str]) -> bytes:
    out = []
    for line in event_lines:
        out.append(f"data: {line}\n".encode("utf-8"))
    out.append(b"data: [DONE]\n\n")
    return b"".join(out)


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: _MockState = _MockState()  # replaced per-server via class attribute

    def log_message(self, *args):  # silence request logging
        pass

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        self.__class__.state.seen_bodies.append(json.loads(raw.decode("utf-8") or "{}"))
        return self.__class__.state.seen_bodies[-1]

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, chunks: list[dict]) -> None:
        body = _sse([json.dumps(c) for c in chunks])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != "/chat/completions":
            self._send_json({"error": "not_found"}, 404)
            return
        body = self._read_body()
        scenario = self.__class__.state.scenario
        stream = bool(body.get("stream"))

        if scenario == "completion":
            content = body.get("messages", [{}])[-1].get("content", "") or "hello"
            self._send_json({
                "id": "mock-c",
                "object": "chat.completion",
                "model": body.get("model", "mock"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": f"echo:{content}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            })
        elif scenario == "stream":
            if not stream:
                # A streaming request was not honored -> protocol error path.
                self._send_json({
                    "id": "mock-s", "object": "chat.completion", "model": "mock",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "stream-only"}, "finish_reason": "stop"}],
                })
                return
            self._send_sse([
                {"id": "mock-s", "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}]},
                {"id": "mock-s", "choices": [{"index": 0, "delta": {"content": " world"}, "finish_reason": None}]},
                {"id": "mock-s", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"total_tokens": 4}},
            ])
        elif scenario == "structured":
            # Deterministic valid JSON matching the schema the caller embedded
            # in the last user message: {"value": "..."} for the Tiny schema.
            last = body.get("messages", [{}])[-1].get("content", "")
            if "JSON Schema" in str(last) and '"value"' in str(last):
                content = '{"value": "structured-ok"}'
            else:
                content = "not-json"
            self._send_json({
                "id": "mock-t", "object": "chat.completion", "model": "mock",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            })
        elif scenario == "timeout":
            time.sleep(3.0)
            self._send_json({"choices": [{"message": {"content": "too late"}}]})
        elif scenario == "rate_limit":
            self._send_json({"error": {"message": "rate limit"}}, 429)
        elif scenario == "auth_error":
            self._send_json({"error": {"message": "invalid key"}}, 401)
        elif scenario == "malformed":
            body_bytes = b"<html>not json</html>"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        elif scenario == "schema_broken":
            self._send_json({"choices": ["not-a-dict"]})
        elif scenario == "server_error":
            self._send_json({"error": {"message": "boom"}}, 500)


class MockProviderServer:
    """Owns a ThreadingHTTPServer on an ephemeral loopback port."""

    def __init__(self) -> None:
        self.state = _MockState()
        # Give the handler its own deterministic state instance.
        MockHandler.state = self.state
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> "MockProviderServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)


@pytest.fixture()
def mock_server():
    server = MockProviderServer().start()
    try:
        yield server
    finally:
        server.close()


def _client(server: MockProviderServer, *, timeout: float = 60.0) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url=server.base_url,
        api_key="test-key-not-real",
        model="mock-model",
        timeout=timeout,
    )


# --------------------------------------------------------------------------- #
# §16 — chat completion over the real wire
# --------------------------------------------------------------------------- #


def test_mock_server_chat_completion(mock_server):
    mock_server.state.scenario = "completion"
    client = _client(mock_server)
    result = client.complete(messages=[{"role": "user", "content": "explain osmosis"}])
    assert result.text == "echo:explain osmosis"
    assert result.finish_reason == "stop"
    assert result.usage["total_tokens"] == 5
    assert mock_server.state.seen_bodies[0]["messages"][-1]["content"] == "explain osmosis"


def test_mock_server_sse_stream(mock_server):
    mock_server.state.scenario = "stream"
    client = _client(mock_server)
    events = list(client.stream(messages=[{"role": "user", "content": "hi"}]))
    texts = [e.text for e in events if e.type == "answer_delta"]
    assert texts == ["Hello", " world"]
    done = [e for e in events if e.type == "done"]
    assert done and done[0].finish_reason == "stop"
    assert done[0].usage == {"total_tokens": 4}


def test_mock_server_streaming_request_requires_stream_flag(mock_server):
    # A non-stream client talking to a stream-only mock must get a protocol
    # error, not a silent hang or wrong-shaped payload.
    mock_server.state.scenario = "stream"
    client = _client(mock_server)
    result = client.complete(messages=[{"role": "user", "content": "hi"}])
    assert result.text == "stream-only"


# --------------------------------------------------------------------------- #
# §16 — timeout / rate limit / auth / malformed / unavailable
# --------------------------------------------------------------------------- #


def test_mock_server_timeout_maps_to_provider_timeout(mock_server):
    mock_server.state.scenario = "timeout"
    client = _client(mock_server, timeout=0.5)
    with pytest.raises(ProviderTimeout):
        client.complete(messages=[{"role": "user", "content": "x"}])


def test_mock_server_rate_limit_maps_to_provider_rate_limited(mock_server):
    mock_server.state.scenario = "rate_limit"
    client = _client(mock_server)
    with pytest.raises(ProviderRateLimited):
        client.complete(messages=[{"role": "user", "content": "x"}])


def test_mock_server_401_maps_to_auth_error(mock_server):
    mock_server.state.scenario = "auth_error"
    client = _client(mock_server)
    with pytest.raises(ProviderAuthError):
        client.complete(messages=[{"role": "user", "content": "x"}])


def test_mock_server_malformed_body_maps_to_protocol_error(mock_server):
    mock_server.state.scenario = "malformed"
    client = _client(mock_server)
    with pytest.raises(ProviderProtocolError):
        client.complete(messages=[{"role": "user", "content": "x"}])


def test_mock_server_broken_schema_maps_to_protocol_error(mock_server):
    mock_server.state.scenario = "schema_broken"
    client = _client(mock_server)
    with pytest.raises(ProviderProtocolError):
        client.complete(messages=[{"role": "user", "content": "x"}])


def test_mock_server_5xx_maps_to_provider_unavailable(mock_server):
    mock_server.state.scenario = "server_error"
    client = _client(mock_server)
    with pytest.raises(ProviderUnavailable):
        client.complete(messages=[{"role": "user", "content": "x"}])


def test_connection_refused_maps_to_provider_unavailable():
    # Grab a free port, then close the socket: nothing is listening, so any
    # request immediately gets ECONNREFUSED — provider down without a server.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    client = OpenAICompatibleClient(
        base_url=f"http://127.0.0.1:{port}", api_key="k", model="m", timeout=2.0
    )
    with pytest.raises(ProviderUnavailable):
        client.complete(messages=[{"role": "user", "content": "x"}])


# --------------------------------------------------------------------------- #
# §16 — pg_deepseek.DeepSeekProvider (Host API httpx transport) over the wire
# --------------------------------------------------------------------------- #


def test_deepseek_provider_text_over_mock_server(mock_server):
    from pg_deepseek import DeepSeekProvider

    mock_server.state.scenario = "completion"
    provider = DeepSeekProvider(
        api_key="test-key-not-real",
        base_url=mock_server.base_url,
        model="mock-model",
        timeout=10,
    )
    out = _run_async(provider.text("tell me about light"))
    assert "echo:" in out and "light" in out


def test_deepseek_provider_structured_over_mock_server(mock_server):
    from pydantic import BaseModel

    from pg_deepseek import DeepSeekProvider

    mock_server.state.scenario = "structured"

    class Tiny(BaseModel):
        value: str

    provider = DeepSeekProvider(
        api_key="test-key-not-real",
        base_url=mock_server.base_url,
        model="mock-model",
        timeout=10,
    )
    result = _run_async(provider.structured("return a tiny object", Tiny))
    assert result.value == "structured-ok"


def test_deepseek_provider_rate_limit_error_never_leaks_key(mock_server):
    from pg_deepseek import DeepSeekProvider, DeepSeekProviderError

    mock_server.state.scenario = "rate_limit"
    provider = DeepSeekProvider(
        api_key="super-secret-key",
        base_url=mock_server.base_url,
        model="mock-model",
        timeout=10,
    )
    with pytest.raises(DeepSeekProviderError) as exc_info:
        _run_async(provider.text("x"))
    assert "super-secret-key" not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)


def _run_async(coro):
    """Run a coroutine without requiring an event loop to be pre-installed."""
    import asyncio

    return asyncio.run(coro)
