import json

import pytest
import socket
import urllib.request
from urllib.error import HTTPError, URLError

from interest_growth_native.errors import (
    ProviderAuthError, ProviderProtocolError, ProviderRateLimited,
    ProviderTimeout, ProviderUnavailable,
)
from interest_growth_native.llm import OpenAICompatibleClient


class FakeHTTPResponse:
    def __init__(self, payload_bytes):
        self._payload = payload_bytes

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _client(monkeypatch, opener):
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    return OpenAICompatibleClient(base_url="https://example.com", api_key="super-secret-key", model="m")


def _mock_status(status):
    def opener(req, timeout=None):
        raise HTTPError(req.full_url, status, "status", {}, None)
    return opener


def _raise(exc):
    def opener(req, timeout=None):
        raise exc
    return opener


def _body(data_bytes):
    def opener(req, timeout=None):
        return FakeHTTPResponse(data_bytes)
    return opener


def test_http_401_and_403_map_to_auth_error(monkeypatch):
    for status in (401, 403):
        with pytest.raises(ProviderAuthError):
            _client(monkeypatch, _mock_status(status)).complete(messages=[{"role": "user", "content": "x"}])


def test_http_429_maps_to_rate_limited(monkeypatch):
    with pytest.raises(ProviderRateLimited):
        _client(monkeypatch, _mock_status(429)).complete(messages=[{"role": "user", "content": "x"}])


def test_http_500_maps_to_unavailable(monkeypatch):
    with pytest.raises(ProviderUnavailable):
        _client(monkeypatch, _mock_status(500)).complete(messages=[{"role": "user", "content": "x"}])


def test_timeout_maps_to_provider_timeout(monkeypatch):
    with pytest.raises(ProviderTimeout):
        _client(monkeypatch, _raise(TimeoutError("read timed out"))).complete(
            messages=[{"role": "user", "content": "x"}]
        )


def test_dns_connection_error_maps_to_unavailable(monkeypatch):
    with pytest.raises(ProviderUnavailable):
        _client(monkeypatch, _raise(URLError(socket.gaierror("nodename nor servname provided")))).complete(
            messages=[{"role": "user", "content": "x"}]
        )


def test_invalid_json_maps_to_protocol_error(monkeypatch):
    c = _client(monkeypatch, _body(b"<html>not json</html>"))
    with pytest.raises(ProviderProtocolError):
        c.complete(messages=[{"role": "user", "content": "x"}])


def test_unexpected_response_schema_maps_to_protocol_error(monkeypatch):
    for body in (b"{}", b'{"choices": []}', b'{"choices": ["x"]}', b'{"choices": [{"message": "x"}]}'):
        c = _client(monkeypatch, _body(body))
        with pytest.raises(ProviderProtocolError):
            c.complete(messages=[{"role": "user", "content": "x"}])


def test_stream_invalid_json_maps_to_protocol_error(monkeypatch):
    class FakeResp:
        def __init__(self):
            self.lines = [b"data: {not-json\n", b"data: [DONE]\n"]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(self.lines)

    c = _client(monkeypatch, lambda req, timeout=None: FakeResp())
    with pytest.raises(ProviderProtocolError):
        list(c.stream(messages=[{"role": "user", "content": "x"}]))


def test_stream_http_error_maps_to_normalized_taxonomy(monkeypatch):
    c = _client(monkeypatch, _mock_status(429))
    with pytest.raises(ProviderRateLimited):
        list(c.stream(messages=[{"role": "user", "content": "x"}]))


def test_normalized_error_messages_never_leak_api_key_or_headers(monkeypatch):
    try:
        _client(monkeypatch, _mock_status(401)).complete(messages=[{"role": "user", "content": "x"}])
    except ProviderAuthError as exc:
        assert "super-secret-key" not in str(exc)
        assert "Authorization" not in str(exc)
    try:
        _client(monkeypatch, _raise(URLError("connection failed"))).complete(
            messages=[{"role": "user", "content": "x"}]
        )
    except ProviderUnavailable as exc:
        assert "super-secret-key" not in str(exc)
        assert "Bearer" not in str(exc)