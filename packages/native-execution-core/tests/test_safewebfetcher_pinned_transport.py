import http.server
import socket
import ssl
import subprocess
import threading

import pytest

from interest_growth_native.errors import ValidationError
from interest_growth_native.web_tools import SafeWebFetcher, resolve_public_ip


def _addrinfo(ip):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))


def test_resolution_blocks_private_and_special_networks(monkeypatch):
    import interest_growth_native.web_tools as wt

    cases = {
        "127.0.0.1": "loopback",
        "10.0.0.5": "rfc1918",
        "172.16.4.4": "rfc1918",
        "192.168.1.1": "rfc1918",
        "169.254.1.1": "link-local",
        "::1": "ipv6-loopback",
        "0.0.0.0": "unspecified",
        "224.0.0.1": "multicast",
        "198.51.100.7": "reserved-doc",
    }
    for ip in cases:
        monkeypatch.setattr(
            wt.socket,
            "getaddrinfo",
            lambda host, port, type=None, ip=ip: [_addrinfo(ip)],
        )
        with pytest.raises(ValidationError):
            resolve_public_ip("example.com")


def test_public_ip_resolves(monkeypatch):
    import interest_growth_native.web_tools as wt

    monkeypatch.setattr(
        wt.socket,
        "getaddrinfo",
        lambda host, port, type=None: [_addrinfo("93.184.216.34")],
    )
    assert resolve_public_ip("example.com") == "93.184.216.34"


def test_mixed_public_and_private_records_blocks_entire_host(monkeypatch):
    import interest_growth_native.web_tools as wt

    monkeypatch.setattr(
        wt.socket,
        "getaddrinfo",
        lambda host, port, type=None: [_addrinfo("93.184.216.34"), _addrinfo("10.0.0.1")],
    )
    with pytest.raises(ValidationError):
        resolve_public_ip("example.com")


def test_fetch_pins_connection_to_validated_ip_with_sni_preserved(monkeypatch):
    import interest_growth_native.web_tools as wt

    getaddrinfo_calls = []

    def fake_getaddrinfo(host, port, type=None):
        getaddrinfo_calls.append(host)
        return [_addrinfo("93.184.216.34")]

    monkeypatch.setattr(wt.socket, "getaddrinfo", fake_getaddrinfo)

    class FakeSock:
        def setsockopt(self, *a):
            pass

        def settimeout(self, *a):
            pass

        def gettimeout(self):
            return 10

    connected = {}

    def fake_create_connection(target, timeout=None, source_address=None):
        connected["target"] = target
        return FakeSock()

    monkeypatch.setattr(wt.socket, "create_connection", fake_create_connection)

    class FakeContext:
        def wrap_socket(self, sock, server_hostname=None):
            connected["server_hostname"] = server_hostname
            return sock

    fetcher = SafeWebFetcher(ssl_context=FakeContext())
    fetcher.ip_resolver = resolve_public_ip
    with pytest.raises(Exception):
        fetcher.fetch("https://example.com/path")
    assert connected.get("target") == ("93.184.216.34", 443)
    assert connected.get("server_hostname") == "example.com"
    assert getaddrinfo_calls == ["example.com"]


def test_redirect_is_not_followed(monkeypatch):
    import interest_growth_native.web_tools as wt
    from urllib.error import HTTPError

    def fake_open(req):
        raise HTTPError(
            "https://example.com/page", 302, "Found",
            {"Location": "https://10.0.0.9/private"}, None,
        )

    class FakeOpener:
        open = staticmethod(fake_open)

    monkeypatch.setattr(
        wt.urllib.request, "build_opener", lambda *handlers: FakeOpener()
    )
    fetcher = SafeWebFetcher(ip_resolver=lambda host, port: "93.184.216.34")
    with pytest.raises(ValidationError, match="redirects are not followed"):
        fetcher.fetch("https://example.com/page")


@pytest.fixture()
def local_https_server(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    conf = tmp_path / "openssl.cnf"
    conf.write_text(
        "[req]\nprompt=no\ndistinguished_name=dn\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost\n"
    )
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key), "-out", str(cert), "-days", "1", "-nodes",
            "-config", str(conf), "-extensions", "ext",
        ],
        check=True, capture_output=True,
    )

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"hello pinned transport"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(str(cert), str(key))
    httpd.socket = server_ctx.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    yield {"port": port, "cert": str(cert)}
    httpd.shutdown()


def test_end_to_end_https_fetch_pins_validated_ip_and_verifies_tls(local_https_server):
    fetcher = SafeWebFetcher(
        ip_resolver=lambda host, port: "127.0.0.1",
        ssl_context=ssl.create_default_context(cafile=local_https_server["cert"]),
    )
    out = fetcher.fetch(f"https://localhost:{local_https_server['port']}/x")
    assert out["text"] == "hello pinned transport"
    assert out["status"] == "candidate_not_evidence"


def test_end_to_end_https_fetch_does_not_disable_certificate_verification(local_https_server):
    fetcher = SafeWebFetcher(
        ip_resolver=lambda host, port: "127.0.0.1",
        ssl_context=ssl.create_default_context(),
    )
    with pytest.raises(Exception) as exc_info:
        fetcher.fetch(f"https://localhost:{local_https_server['port']}/x")
    assert "certificate" in str(exc_info.value).lower() or "ssl" in str(exc_info.value).lower()
