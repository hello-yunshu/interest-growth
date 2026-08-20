#!/usr/bin/env python3
# Phase 4c — black-box WebView CDP enrollment driver (Android, no run-as).
#
# Drives the REAL product path on the Android emulator through Chrome
# DevTools Protocol exposed by the WebView:  Renderer -> ClientRuntime ->
# Tauri invoke -> Rust RemoteBroker -> HTTPS server. The upgrade-in-place job
# uses this against a NON-debuggable x86_64 RELEASE-test APK that was built
# with CiFlags.ENABLE_WEBVIEW_REMOTE_DEBUGGING=true (and is never published).
#
# It fills the RuntimeConnect form (apps/web/components/RuntimeConnect.js):
#   1. navigate to the 系统 (system) -> 连接 (connection) tab
#   2. set #remoteServerUrl to the HTTPS origin and press 探测服务器 (probe)
#   3. wait for the probe to complete (login form reveals)
#   4. set #remoteLoginPassword and #remoteDeviceName, press 登录并接入 (login)
#   5. assert an enrolled+connected session (success signal, no error flash)
#
# Runtime helpers are stdlib-only (minimal RFC6455 WebSocket + http.client) so
# the runner needs no pip install.
#
# Usage:
#   python3 scripts/ci/android_cdp_enroll.py \
#     --package app.psychologygrowth.desktop \
#     --devtools-port 9333 \
#     --origin https://127.0.0.1:18443 \
#     --owner-password 'Ci-Owner-Password-2026!' \
#     --device-name android-upgrade-ci \
#     --result-file /tmp/ig_cdp_result.json \
#     [--adb /path/to/adb]
import argparse
import base64
import hashlib
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time

APP = "app.psychologygrowth.desktop"
DEVTOOLS_HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
# Pure, unit-testable form-fill JS generation (no WebView dependency).
# ---------------------------------------------------------------------------
def js_set_input(selector, value):
    """Return CDP Runtime.evaluate body that sets a React-controlled input.

    React tracks value via the input's native setter + a bubbling 'input'
    event; assigning `.value =` directly is optimized out by React. This uses
    the prototype setter (bypasses the value-tracking trap) and then re-fires
    the event so onChange runs.
    """
    selector = _double_quote(selector)
    value = _double_quote(value)
    return (
        f"(() => {{ const el = document.querySelector({selector});"
        f" if (!el) return {{ok:false,step:'find',selector:{selector}}};"
        f" const setter = Object.getOwnPropertyDescriptor("
        f"window.HTMLInputElement.prototype, 'value').set;"
        f" setter.call(el, {value});"
        f" el.dispatchEvent(new Event('input', {{bubbles:true}}));"
        f" el.dispatchEvent(new Event('change', {{bubbles:true}}));"
        f" return {{ok:true,value:el.value}}; }})()"
    )


def js_click(selector):
    selector = _double_quote(selector)
    return (
        f"(() => {{ const el = document.querySelector({selector});"
        f" if (!el) return {{ok:false,step:'find',selector:{selector}}};"
        f" if (typeof el.click !== 'function') return {{ok:false,step:'clickable'}};"
        f" el.click(); return {{ok:true}}; }})()"
    )


def js_snapshot_text(selector):
    """Return the trimmed textContent of nodes matching selector (comma-joined)."""
    selector = _double_quote(selector)
    return (
        f"(() => {{ try {{ const nodes = document.querySelectorAll({selector});"
        f" const t = Array.from(nodes).map(n => (n.innerText||'').trim())"
        f" .filter(Boolean).join(' | '); return {{ok:true,text:t}};}}"
        f" catch (e) {{ return {{ok:false,error:String(e)}};}} }})()"
    )


def js_cdp_hello():
    return 'JSON.stringify({__ig:true})'


def _double_quote(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


# ---------------------------------------------------------------------------
# Minimal RFC6455 WebSocket client (stdlib only).
# ---------------------------------------------------------------------------
class WsError(Exception):
    pass


class WsClient:
    def __init__(self, host, port, path):
        self._sock = socket.create_connection((host, port), timeout=15)
        self._sock.settimeout(30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._sock.sendall(req.encode("latin-1"))
        self._read_handshake()

    def _read_handshake(self):
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self._sock.recv(8192)
            if not chunk:
                raise WsError("websocket handshake closed early")
            buf += chunk
        head = buf.split(b"\r\n\r\n", 1)[0]
        if not re.search(rb"\b101\b", head.split(b"\r\n", 1)[0]):
            raise WsError(f"websocket upgrade rejected:\n{head.decode('latin-1', 'replace')}")

    def send_text(self, payload):
        data = payload.encode("utf-8")
        self._sock.sendall(self._frame(0x1, data))

    def _frame(self, opcode, data):
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        n = len(data)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return header + mask + masked

    def _recv_frame(self):
        h = self._recv_exact(2)
        if not h:
            raise WsError("connection closed")
        _, ln = h[0], h[1]
        masked = bool(ln & 0x80)
        length = ln & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        op = h[0] & 0x0F
        if op == 0x8:  # close
            raise WsError("websocket closed by peer")
        if op == 0x9:  # ping
            self._sock.sendall(self._frame(0xA, payload))
            return None
        return payload

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise WsError("socket closed mid-frame")
            buf += chunk
        return buf

    def read_text(self):
        while True:
            payload = self._recv_frame()
            if payload is not None:
                return payload.decode("utf-8", "replace")

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# adb helpers.
# ---------------------------------------------------------------------------
def sh(cmd, adb=None, timeout=60, check=True):
    argv = [adb] if adb else []
    argv += list(cmd)
    try:
        out = subprocess.run(argv, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"adb timeout: {' '.join(argv)}") from e
    if check and out.returncode != 0:
        raise RuntimeError(
            f"command failed ({out.returncode}): {' '.join(argv)}\n{out.stderr.decode('latin-1','replace')}"
        )
    return out.stdout.decode("utf-8", "replace"), out.stderr.decode("utf-8", "replace")


def adb_pid(adb, pkg):
    out, _ = sh(["shell", "pidof", pkg], adb=adb, check=False)
    m = re.search(r"\d+", out or "")
    return int(m.group(0)) if m else None


def youtube_forward_devtools(adb, pkg, host_port):
    """Forward a local port to the app WebView devtools abstract socket.

    Chromium WebView exposes `localabstract:webview_devtools_remote_<pid>`.
    Returns the app pid used (so we can drop the forward later).
    """
    pid = adb_pid(adb, pkg)
    if pid is None:
        raise RuntimeError(f"app {pkg} not running")
    sh(["forward", f"tcp:{host_port}", f"localabstract:webview_devtools_remote_{pid}"], adb=adb)
    return pid


def adb_reverse(adb, host_port):
    sh(["reverse", f"tcp:{host_port}", f"tcp:{host_port}"], adb=adb)


# ---------------------------------------------------------------------------
# CDP client.
# ---------------------------------------------------------------------------
class Cdp:
    def __init__(self, target_ws_url):
        import urllib.parse
        u = urllib.parse.urlsplit(target_ws_url)
        self._ws = WsClient(u.hostname, u.port or 80, u.path + ("?" + u.query if u.query else ""))
        self._next = 1
        self._pending = {}

    def call(self, method, params=None):
        idx = self._next
        self._next += 1
        msg = {"id": idx, "method": method, "params": params or {}}
        self._ws.send_text(json.dumps(msg))
        deadline = time.time() + 60
        while time.time() < deadline:
            raw = self._ws.read_text()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if obj.get("id") == idx:
                if "error" in obj:
                    raise RuntimeError(f"CDP {method} error: {obj['error']}")
                return obj.get("result", {})
        raise RuntimeError(f"CDP {method} timed out")

    def evaluate(self, expr):
        res = self.call("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if "exceptionDetails" in res:
            return {"ok": False, "step": "exception", "details": res["exceptionDetails"]}
        return res.get("result", {}).get("value")


def discover_ws_url(host_port):
    import urllib.request
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://{DEVTOOLS_HOST}:{host_port}/json/list", timeout=5) as r:
                targets = json.loads(r.read() or b"[]")
            # Prefer a page target of type 'webview' (Android WebView); fall back
            # to any 'page' target.
            for t in targets:
                if t.get("type") == "webview":
                    return t["webSocketDebuggerUrl"]
            for t in targets:
                if t.get("type") == "page":
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("no WebView CDP target discovered")


# ---------------------------------------------------------------------------
# Enrollment flow.
# ---------------------------------------------------------------------------
class EnrollError(Exception):
    pass


def _coerce_result(v, default):
    return v if isinstance(v, dict) else default


def enroll(cdp, origin, owner_password, device_name, timeout=120):
    log = []
    deadline = time.time() + timeout
    # --- navigate to the 系统 settings -> 连接 (connection) tab ---
    # Static export + Next client-side router: a hard `location.href` reload is
    # unreliable, so prefer the serializer/click path. Strategy tiers:
    #   A) already on the connection tab (input present)
    #   B) drive Next router client-side
    #   C) click an <a> whose href matches /system
    _nav(cdp, log, deadline)
    _wait_for(cdp, lambda: _has_input(cdp), "connection form (#remoteServerUrl)", deadline, log)

    # fill server URL + probe
    set_r = _coerce_result(cdp.evaluate(js_set_input("#remoteServerUrl", origin)), {})
    if not set_r.get("ok"):
        raise EnrollError(f"set #remoteServerUrl failed: {set_r}")
    log.append({"step": "set_server_url", "ok": True})
    _click(cdp, "form:has(#remoteServerUrl) button[type='submit']", log, "probe")
    _wait_for(cdp, lambda: _has_input(cdp, "#remoteLoginPassword"),
              "probe result (login form reveals)", deadline, log)

    # fill login + device name + submit
    set_pw = _coerce_result(cdp.evaluate(js_set_input("#remoteLoginPassword", owner_password)), {})
    if not set_pw.get("ok"):
        raise EnrollError(f"set #remoteLoginPassword failed: {set_pw}")
    set_dn = _coerce_result(cdp.evaluate(js_set_input("#remoteDeviceName", device_name)), {})
    if not set_dn.get("ok"):
        raise EnrollError(f"set #remoteDeviceName failed: {set_dn}")
    log.append({"step": "set_credentials", "ok": True})
    _click(cdp, "form:has(#remoteLoginPassword) button[type='submit']", log, "login")

    # --- assert enrolled + connected ---
    # The verified signal is the absence of an error flash and presence of a
    # connected session. We observe the DOM: an error flash renders the msg
    # with tone error; a successful login renders "已登录服务器".
    ok = _wait_for(cdp, lambda: _login_succeeded(cdp), "enrolled+connected session", deadline, log)
    if not ok:
        err = _read_visible_text(cdp)
        raise EnrollError(f"login did not become connected. visible text: {err}")

    log.append({"step": "login", "ok": True, "enrolled": True})
    return log


def _nav(cdp, log, deadline):
    if _has_input(cdp):
        log.append({"step": "nav", "how": "already_on_connection"})
        return
    try:
        # Next.js exposes the router on an element; try a client-side push.
        expr = (
            "(() => { const g = window.next; "
            "const r = (g && (g.router || g.app && g.app.router)); "
            "if (r && typeof r.push === 'function') { r.push('/system').catch(()=>{}); return 'pushed'; } "
            "const a = document.querySelector('a[href*=\"/system\"], a[data-testid*=\"system\"], a[href*=\"system\"]'); "
            "if (a && typeof a.click === 'function') { a.click(); return 'clicked_anchor'; } "
            "return 'no_router_no_anchor'; })()"
        )
        res = _coerce_result(cdp.evaluate(expr), {})
        if isinstance(res, dict):  # __ig marker / object
            res = str(res)
        log.append({"step": "nav", "attempt": res})
        # fall back to a hard rewrite via history if the router did nothing.
        if res == "no_router_no_anchor":
            cdp.evaluate("(() => { try { history.replaceState({}, '', '/system'); "
                         "window.dispatchEvent(new Event('popstate')); } catch(e){} return 1; })()")
    except Exception as e:  # noqa: BLE001
        log.append({"step": "nav", "error": str(e)})
    _wait_for(cdp, lambda: _has_input(cdp), "navigation to connection tab", time.time() + 30, log)


def _has_input(cdp, selector="#remoteServerUrl"):
    r = _coerce_result(cdp.evaluate(
        f"({{ el: document.querySelector({_double_quote(selector)}) !== null }})"), {})
    return bool(r.get("el"))


def _click(cdp, selector, log, label):
    r = _coerce_result(cdp.evaluate(js_click(selector)), {})
    if not r.get("ok"):
        raise EnrollError(f"click {label} ({selector}) failed: {r}")
    log.append({"step": f"click_{label}", "ok": True})


def _login_succeeded(cdp):
    # Success: text contains the logged-in marker and no visible error tone.
    expr = (
        "(() => { const body = (document.body.innerText||''); "
        "const erred = Array.from(document.querySelectorAll('*')).some(el => "
        " el && el.textContent && /已连接|登录已过期|无法|失败|错误/.test(el.textContent) "
        " && (el.getAttribute('role')==='alert' || /danger|error/.test(el.className||''))); "
        "return { connected: /已连接/.test(body) || /已登录服务器/.test(body), erred }; })()"
    )
    r = _coerce_result(cdp.evaluate(expr), {})
    return bool(r.get("connected") and not r.get("erred"))


def _read_visible_text(cdp):
    r = _coerce_result(cdp.evaluate(js_snapshot_text("body")), {})
    return r.get("text", "")


def _wait_for(cdp, predicate, what, deadline, log):
    while time.time() < deadline:
        try:
            if predicate():
                log.append({"step": f"wait_{what}", "done": True})
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    log.append({"step": f"wait_{what}", "done": False})
    return False


def _write_result(path, payload):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Android WebView CDP black-box enrollment")
    ap.add_argument("--package", default=APP)
    ap.add_argument("--devtools-port", type=int, default=9333)
    ap.add_argument("--origin", required=True, help="HTTPS origin of the self-hosted server")
    ap.add_argument("--owner-password", required=True)
    ap.add_argument("--device-name", required=True)
    ap.add_argument("--result-file", required=True)
    ap.add_argument("--adb", default="adb")
    args = ap.parse_args(argv)

    started = time.time()
    payload = {"result": "FAIL", "steps": [], "detail": "", "elapsed_s": 0}
    try:
        # App must be running with WebView debugging on for this release-test APK.
        pid = youtube_forward_devtools(args.adb, args.package, args.devtools_port)
        payload["app_pid"] = pid
        ws_url = discover_ws_url(args.devtools_port)
        cdp = Cdp(ws_url)
        steps = enroll(cdp, args.origin, args.owner_password, args.device_name)
        payload.update({"result": "PASS", "steps": steps})
    except Exception as e:  # noqa: BLE001
        payload["detail"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            sh(["forward", f"--remove", f"tcp:{args.devtools_port}"], adb=args.adb, check=False)
        except Exception:  # noqa: BLE001
            pass
        payload["elapsed_s"] = round(time.time() - started, 2)
        _write_result(args.result_file, payload)
        sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())