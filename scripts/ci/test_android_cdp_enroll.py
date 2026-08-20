#!/usr/bin/env python3
"""Local unit tests for the Phase 4c CDP driver (no emulator needed).

Verifies the pure, WebView-independent parts:
  * JS generation for React-controlled input setting / clicks / snapshots,
  * the RFC6455 client frame encoder against a real in-process echo server,
  * result-file shaping on success and failure paths.

Run:  python3 scripts/ci/test_android_cdp_enroll.py
"""
import os
import signal
import socket
import struct
import subprocess
import sys
import threading

import android_cdp_enroll as c


# ---------------------------------------------------------------------------
# JS generation
# ---------------------------------------------------------------------------
def test_set_input_uses_native_setter_and_fires_input():
    js = c.js_set_input("#remoteServerUrl", "https://127.0.0.1:18443")
    assert "document.querySelector(\"#remoteServerUrl\")" in js
    assert "HTMLInputElement.prototype, 'value').set" in js
    assert "Event('input', {bubbles:true})" in js
    assert "Event('change', {bubbles:true})" in js
    assert '"https://127.0.0.1:18443"' in js
    # correct object literal for CDP returnByValue
    assert js.startswith("(() => {") and js.rstrip().endswith("})()")


def test_set_input_escapes():
    js = c.js_set_input("#remoteLoginPassword", 'a"b\\c')
    assert '"a\\"b\\\\c"' in js


def test_click_selector_embedded():
    js = c.js_click("form:has(#remoteLoginPassword) button[type='submit']")
    assert "querySelector" in js and "el.click()" in js


def test_double_quote():
    assert c._double_quote("") == '""'
    assert c._double_quote("a b") == '"a b"'
    assert c._double_quote('q"z') == '"q\\"z"'


# ---------------------------------------------------------------------------
# RFC6455 frame encode / decode over a real socket pair
# ---------------------------------------------------------------------------
class _BufferedConn:
    def __init__(self, conn):
        self.conn = conn
        self.buf = b""

    def _fill(self):
        if not self.buf:
            self.buf = self.conn.recv(8192)

    def read_n(self, n):
        while len(self.buf) < n:
            chunk = self.conn.recv(8192)
            if not chunk:
                raise OSError("peer closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def find_headers_end(self):
        while b"\r\n\r\n" not in self.buf:
            chunk = self.conn.recv(8192)
            if not chunk:
                raise OSError("peer closed")
            self.buf += chunk
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        return head


def _echo_server(conn):
    # Handshake 101 response, then echo text frames back (server unmasked).
    conn.sendall(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: dub-welcome\r\n\r\n"
    )
    bc = _BufferedConn(conn)
    try:
        bc.find_headers_end()  # consume the client HTTP upgrade request
        while True:
            h = bc.read_n(2)
            _op, ln = h[0] & 0x0F, h[1]
            masked = bool(ln & 0x80)
            length = ln & 0x7F
            if length == 126:
                length = struct.unpack(">H", bc.read_n(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", bc.read_n(8))[0]
            mask = bc.read_n(4) if masked else b""
            payload = bc.read_n(length)
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            # echo as an unmasked server text frame
            ln2 = len(payload)
            head = bytes([0x81])
            if ln2 < 126:
                head += bytes([ln2])
            elif ln2 < 65536:
                head += bytes([0x7E]) + struct.pack(">H", ln2)
            conn.sendall(head + payload)
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def test_ws_client_roundtrip():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    got = {}

    def accept():
        conn, _ = srv.accept()
        _echo_server(conn)

    t = threading.Thread(target=accept, daemon=True)
    t.start()

    ws = c.WsClient("127.0.0.1", port, "/devtools/page/abc")
    ws.send_text("hello-\u2764")  # non-ASCII to exercise utf-8 framing
    got["text"] = ws.read_text()
    ws.close()

    assert got["text"] == "hello-\u2764", got
    srv.close()


# ---------------------------------------------------------------------------
# Result shaping on failure path (driver-level, no emulator)
# ---------------------------------------------------------------------------
def test_main_writes_fail_result_without_target():
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        # --devtools-port pointing at nothing => discovery fails => FAIL result
        rc = c.main([
            "--devtools-port", "1",  # unlikely to be in use / will time out
            "--origin", "https://127.0.0.1:1",
            "--owner-password", "x", "--device-name", "d",
            "--result-file", path,
            "--adb", "false-adb",  # adb wrapper that never exists
        ])
    finally:
        if os.path.exists(path):
            payload = json_load(path)
            os.remove(path)
        else:
            payload = {}
    # Either the adb pid lookup fails fast, or discovery times out; both are
    # honest FAIL with a diagnostic captured, never a fake PASS.
    assert rc == 1
    assert payload.get("result") == "FAIL"


def json_load(path):
    import json
    with open(path) as fh:
        return json.load(fh)


def test_module_imports_and_no_stdlib_deps():
    # The module must be stdlib-only (no `requests`/`websocket-client`).
    for bad in ("requests", "websocket", "ws"):
        assert not any(line.startswith(f"import {bad}") for line in open(c.__file__)), bad


# ---------------------------------------------------------------------------
def run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_all())