#!/usr/bin/env python3
# Phase 4e — black-box three-stage Android upgrade-in-place CDP driver.
#
# Proves the real N -> N+1 upgrade (prompt §11) entirely through the WebView:
# no `adb shell run-as`, no app-private config injection. The release workflow
# runs it twice around the actual `adb install -r` reinstall on an x86_64
# emulator, against a NON-debuggable RELEASE-test APK:
#
#   stage=create  (OLD APK running before the reinstall):
#      1. enroll/login  ->   reuse android_cdp_enroll.enroll() (real product path)
#      2. create a canonical question on the server (curiosity page POST)
#      3. persist that question's text to --state-file for the verify stage
#
#   [workflow: adb install -r NEW.apk; clear NO data; relaunch the app]
#
#   stage=verify  (NEW APK running after the reinstall, same locked session):
#      4. WITHOUT re-login, navigate to /curiosity and read the pre-upgrade
#         question back  =>  proves session/keystore auto-restored (#8/#9) and
#                            upgrade-before data is still readable (#11)
#      5. assert the login form is NOT shown while reading (no password re-entry)
#      6. mutate (create a second question) and assert it persisted => mutation
#         continues to work with the restored credential (#12)
#
# The runtime helpers (RFC6455 WebSocket + http.client CDP) are stdlib-only so
# the CI runner needs no pip install. Pure JS-generation and result-shaping are
# unit-tested in test_android_upgrade_driver.py with no emulator.
#
# Usage:
#   python3 scripts/ci/android_upgrade_driver.py \
#     --stage create \
#     --package app.psychologygrowth.desktop \
#     --devtools-port 9333 \
#     --origin https://127.0.0.1:18443 \
#     --owner-password 'Ci-Owner-Password-2026!' \
#     --device-name android-upgrade-ci \
#     --state-file /tmp/ig_upgrade_state.json \
#     --result-file /tmp/ig_upgrade_create.json
#
#   python3 scripts/ci/android_upgrade_driver.py --stage verify ... \
#     --result-file /tmp/ig_upgrade_verify.json
import argparse
import json
import os
import re
import sys
import time

import android_cdp_enroll as cae


# ---------------------------------------------------------------------------
# Pure, unit-testable JS generation for the curiosity (create/mutate) surface.
# These are WebView-independent: they only build the CDP Runtime.evaluate body.
# ---------------------------------------------------------------------------
def js_set_textarea(selector, value):
    """Set a React-controlled <textarea> (the PromptBar) so onChange runs.

    React tracks value via the native setter trap; direct `.value =` is
    optimized out. Uses the HTMLTextAreaElement prototype setter (bypasses the
    trap) then re-fires 'input' + 'change' so the onChange handler updates
    state. Mirrors android_cdp_enroll.js_set_input but for textarea.
    """
    selector = cae._double_quote(selector)
    value = cae._double_quote(value)
    return (
        f"(() => {{ const el = document.querySelector({selector});"
        f" if (!el || el.tagName !== 'TEXTAREA') return {{ok:false,step:'find',selector:{selector}}};"
        f" const setter = Object.getOwnPropertyDescriptor("
        f"window.HTMLTextAreaElement.prototype, 'value').set;"
        f" setter.call(el, {value});"
        f" el.dispatchEvent(new Event('input', {{bubbles:true}}));"
        f" el.dispatchEvent(new Event('change', {{bubbles:true}}));"
        f" return {{ok:true,value:el.value.length}}; }})()"
    )


def js_press_enter(selector):
    """Dispatch an Enter keydown/submit on the PromptBar textarea.

    PromptBar's onKeyDown submits when `event.key === 'Enter' && !shiftKey`.
    A bubbling KeyboardEvent with key='Enter' is observed by React's synthetic
    listener. Both keydown and keyup are sent for responsiveness.
    """
    selector = cae._double_quote(selector)
    return (
        f"(() => {{ const el = document.querySelector({selector});"
        f" if (!el) return {{ok:false,step:'find',selector:{selector}}};"
        f" for (const type of ['keydown','keyup']) {{"
        f"   el.dispatchEvent(new KeyboardEvent(type, {{key:'Enter',code:'Enter',"
        f"     keyCode:13,which:13,bubbles:true,cancelable:true,shiftKey:false}}));"
        f" }}"
        f" return {{ok:true}}; }})()"
    )


def js_textarea_value(selector):
    """Return the current value of the PromptBar textarea (diagnostics)."""
    selector = cae._double_quote(selector)
    return (
        f"(() => {{ const el = document.querySelector({selector});"
        f" return {{ok:true,value:(el?el.value:'')}}; }})()"
    )


# ---------------------------------------------------------------------------
# Pure helpers.
# ---------------------------------------------------------------------------
_SEQ = [0]


def unique_marker(prefix="ig-upgrade-ci"):
    """A deterministic-within-a-run question marker (time-seeded, unique even
    when called twice in the same millisecond, no whitespace/'/'/':' so it can
    be matched verbatim in document text)."""
    _SEQ[0] += 1
    return f"{prefix}-{int(time.time() * 1000)}-{_SEQ[0]}"


def _coerce(v, default):
    return v if isinstance(v, dict) else default


class UpgradeError(Exception):
    pass


class ResilientCdp:
    """Reconnect once when Android WebView reloads and closes its CDP socket."""

    def __init__(self, adb, package, devtools_port):
        self.adb = adb
        self.package = package
        self.devtools_port = devtools_port
        self.pid = None
        self._cdp = None
        self._connect()

    def _connect(self):
        self.pid = cae.youtube_forward_devtools(
            self.adb, self.package, self.devtools_port
        )
        ws_url = cae.discover_ws_url(self.devtools_port)
        self._cdp = cae.Cdp(ws_url)

    def evaluate(self, expression):
        try:
            return self._cdp.evaluate(expression)
        except (BrokenPipeError, ConnectionError, OSError, cae.WsError):
            self._connect()
            return self._cdp.evaluate(expression)


# ---------------------------------------------------------------------------
# Flow building blocks.
# ---------------------------------------------------------------------------
def navigate_page(cdp, path, log, deadline):
    """Client-side navigation to a static-export route (no hard reload)."""
    if _on_page(cdp, path):
        log.append({"step": f"nav_{path}", "how": "already_there"})
        return
    expr = (
        "(() => { "
        f"const a = document.querySelector('a[href=\"{path}\"], a[href^=\"{path}?\"], a[href*=\"{path}\"]'); "
        "if (a && typeof a.click === 'function') { a.click(); return 'clicked_anchor'; } "
        "const g = window.next; "
        "const r = (g && (g.router || g.app && g.app.router)); "
        f"if (r && typeof r.push === 'function') {{ r.push({path!r}).catch(()=>{{}}); return 'pushed'; }} "
        "return 'no_router_no_anchor'; })()"
    )
    try:
        res = _coerce(cdp.evaluate(expr), {})
        if isinstance(res, dict):
            res = str(res)
        log.append({"step": f"nav_{path}", "attempt": res})
        if res == "no_router_no_anchor":
            cdp.evaluate(
                f"(() => {{ try {{ history.replaceState({{}}, '', {path!r}); "
                "window.dispatchEvent(new Event('popstate')); } catch(e){} return 1; })()")
    except Exception as e:  # noqa: BLE001
        log.append({"step": f"nav_{path}", "error": str(e)})
    # The exported Next app normally handles the real Nav anchor above. Some
    # old WebView/Next combinations acknowledge the click without committing
    # the route, so give that path a short bounded chance and then use a real
    # document navigation. ResilientCdp reconnects after the reload.
    click_deadline = min(deadline, time.time() + 15)
    if cae._wait_for(cdp, lambda: _on_page(cdp, path),
                     f"navigate to {path} via client route", click_deadline, log):
        return
    log.append({"step": f"nav_{path}", "fallback": "location_assign"})
    try:
        cdp.evaluate(f"(() => {{ location.assign({path!r}); return 1; }})()")
    except Exception as e:  # noqa: BLE001
        log.append({"step": f"nav_{path}", "fallback_error": str(e)})
    if not cae._wait_for(cdp, lambda: _on_page(cdp, path),
                         f"navigate to {path} via document reload", deadline, log):
        state = _coerce(cdp.evaluate("({p: location.pathname, href: location.href})"), {})
        raise UpgradeError(
            f"could not navigate to {path}; location={state}; "
            f"body={_read_body(cdp)[:400]}"
        )


def _on_page(cdp, path):
    r = _coerce(cdp.evaluate(
        f"({{ el: document.querySelector('textarea') !== null, "
        f"p: location.pathname }})"), {})
    if path in ("/curiosity", "/"):
        # The create surface is identified by its PromptBar textarea. A
        # pathname-only check can race a client-side navigation and leave the
        # caller on the prior settings page until the full timeout expires.
        return bool(r.get("el")) and (
            str(r.get("p", "")).startswith(path) or path == "/"
        )
    return str(r.get("p", "")).startswith(path)


def create_question(cdp, text, log, deadline):
    """POST a canonical question via the curiosity PromptBar (Enter submit)."""
    if not cae._wait_for(cdp, lambda: _has_selector(cdp, "textarea"),
                         "curiosity PromptBar (#textarea)", deadline, log):
        raise UpgradeError(
            "curiosity PromptBar did not render after navigation. "
            f"body: {_read_body(cdp)[:400]}"
        )
    set_r = _coerce(cdp.evaluate(js_set_textarea("textarea", text)), {})
    if not set_r.get("ok"):
        raise UpgradeError(f"set PromptBar textarea failed: {set_r}")
    log.append({"step": "prompt_fill", "ok": True, "chars": set_r.get("value")})
    submit_r = _coerce(cdp.evaluate(js_press_enter("textarea")), {})
    if not submit_r.get("ok"):
        raise UpgradeError(f"submit PromptBar textarea failed: {submit_r}")
    log.append({"step": "prompt_submit", "ok": True})
    ok = cae._wait_for(cdp, lambda: _body_contains(cdp, text),
                       "question rendered in the table", deadline, log)
    if not ok:
        raise UpgradeError(
            "question did not surface in the table after submit. "
            f"body: {_read_body(cdp)[:400]}")
    log.append({"step": "post_upgrade_create_question", "ok": True})


def _has_selector(cdp, selector):
    r = _coerce(cdp.evaluate(
        f"({{ el: document.querySelector({cae._double_quote(selector)}) !== null }})"), {})
    return bool(r.get("el"))


def _body_contains(cdp, substring):
    text = _read_body(cdp)
    return bool(substring) and substring in text


def _read_body(cdp):
    r = _coerce(cdp.evaluate(cae.js_snapshot_text("body")), {})
    return r.get("text", "")


def _login_form_shown(cdp):
    return _has_selector(cdp, "#remoteLoginPassword")


# ---------------------------------------------------------------------------
# Stage implementations.
# ---------------------------------------------------------------------------
def stage_create(cdp, origin, owner_password, device_name, bootstrap_token, marker_question, deadline):
    """Login (real product path) then create canonical server data the verify
    stage must be able to read back after the reinstall."""
    log = []
    enrolled = cae.enroll(cdp, origin, owner_password, device_name,
                          bootstrap_token=bootstrap_token,
                          timeout=_remaining(deadline))
    log.extend(enrolled)
    deadline = max(deadline, time.time() + 120)
    navigate_page(cdp, "/curiosity", log, deadline)
    create_question(cdp, marker_question, log, deadline)
    return log


def stage_verify(cdp, marker_question, mutation_question, deadline):
    """Post-upgrade proof. Deliberately does NOT call enroll/login: reading the
    pre-upgrade data back must succeed from the restored session alone."""
    log = [{"step": "verify_entry", "re_login_attempted": False}]
    navigate_page(cdp, "/curiosity", log, deadline)
    ok = cae._wait_for(cdp, lambda: _body_contains(cdp, marker_question),
                       "pre-upgrade data readable (session auto-restored)", deadline, log)
    if not ok:
        raise UpgradeError(
            "pre-upgrade data NOT readable after reinstall; session may not have "
            f"restored. login_form_shown={_login_form_shown(cdp)} body={_read_body(cdp)[:400]}")
    log.append({"step": "data_readable", "ok": True, "login_form_shown": _login_form_shown(cdp)})

    # The read succeeded without re-login: the login form must be absent.
    if _login_form_shown(cdp):
        raise UpgradeError("login form is still shown while reading post-upgrade data; upgrade did NOT preserve a live session")
    log.append({"step": "no_relogin", "ok": True})

    # Mutation continues to work with the restored credential (a second create).
    create_question(cdp, mutation_question, log, deadline)
    if not cae._wait_for(cdp, lambda: _body_contains(cdp, marker_question),
                         "pre-upgrade data still present after mutation", deadline, log):
        raise UpgradeError("mutation dropped pre-upgrade data")
    log.append({"step": "mutate_ok", "ok": True, "mutation_question": mutation_question})
    return log


def _remaining(deadline):
    return max(1, int(deadline - time.time()))


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def _load_state(path):
    if path and os.path.exists(path):
        try:
            with open(path) as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save_state(path, state):
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def _write_result(path, payload):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Android upgrade-in-place CDP driver (three-stage)")
    ap.add_argument("--stage", required=True, choices=("create", "verify"))
    ap.add_argument("--package", default=cae.APP)
    ap.add_argument("--devtools-port", type=int, default=9333)
    ap.add_argument("--origin", required=True)
    ap.add_argument("--owner-password", required=True)
    ap.add_argument("--device-name", required=True)
    ap.add_argument("--bootstrap-token", help="one-time owner bootstrap token for a fresh CI server")
    ap.add_argument("--state-file", help="shared JSON passed from create -> verify")
    ap.add_argument("--result-file", required=True)
    ap.add_argument("--adb", default="adb")
    ap.add_argument("--timeout-s", type=int, default=240)
    args = ap.parse_args(argv)

    started = time.time()
    payload = {"stage": args.stage, "result": "FAIL", "steps": [], "detail": "",
               "elapsed_s": 0}
    deadline = time.time() + args.timeout_s
    state = _load_state(args.state_file)
    marker = state.get("marker_question")
    mutation = state.get("mutation_question")
    if args.stage == "verify" and not marker:
        # Fail fast on bad orchestration BEFORE touching the device: a verify
        # without a create-stage marker is a misuse, not a network failure.
        payload["detail"] = "no marker_question in --state-file; run --stage create first"
        _write_result(args.result_file, payload)
        sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return 1
    try:
        cdp = ResilientCdp(args.adb, args.package, args.devtools_port)
        payload["app_pid"] = cdp.pid

        if args.stage == "create":
            nmarker = unique_marker()
            nmutation = unique_marker("ig-upgrade-mutate")
            steps = stage_create(cdp, args.origin, args.owner_password,
                                 args.device_name, args.bootstrap_token, nmarker, deadline)
            payload.update({"result": "PASS", "steps": steps,
                            "marker_question": nmarker,
                            "mutation_question": nmutation})
            state.update({"marker_question": nmarker,
                          "mutation_question": nmutation})
        else:  # verify
            steps = stage_verify(cdp, marker, mutation, deadline)
            payload.update({"result": "PASS", "steps": steps,
                            "marker_question": marker,
                            "mutation_question": mutation})
    except Exception as e:  # noqa: BLE001
        payload["detail"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            cae.sh(["forward", "--remove", f"tcp:{args.devtools_port}"],
                   adb=args.adb, check=False)
        except Exception:  # noqa: BLE001
            pass
        payload["elapsed_s"] = round(time.time() - started, 2)
        _write_result(args.result_file, payload)
        _save_state(args.state_file, state)
        sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
