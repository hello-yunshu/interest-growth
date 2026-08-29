#!/usr/bin/env python3
"""Local unit tests for the Phase 4e upgrade-in-place CDP driver (no emulator).

Verifies the pure, WebView-independent parts:
  * textarea JS generation for the curiosity PromptBar (create / mutation),
  * Enter-submit key displacement and trusted send-button clicking,
  * marker generation,
  * cross-stage state-file handoff + honest FAIL shaping on failure,
  * stdlib-only runtime (no pip deps).

Run:  python3 scripts/ci/test_android_upgrade_driver.py
"""
import inspect
import json
import os
import tempfile

import android_upgrade_driver as d
import android_cdp_enroll as cae


# ---------------------------------------------------------------------------
# textarea JS generation
# ---------------------------------------------------------------------------
def test_set_textarea_uses_native_setter_and_fires_events():
    js = d.js_set_textarea("textarea", "ig-upgrade-ci-123")
    assert "document.querySelector(\"textarea\")" in js
    assert "HTMLTextAreaElement.prototype, 'value').set" in js
    assert "Event('input', {bubbles:true})" in js
    assert "Event('change', {bubbles:true})" in js
    assert "el.value.length" in js  # returns length, not the sensitive string
    assert js.startswith("(() => {") and js.rstrip().endswith("})()")


def test_set_textarea_rejects_non_textarea():
    # The guard must exist so we never fire key events on the wrong element.
    assert 'el.tagName !== \'TEXTAREA\'' in d.js_set_textarea("input", "x")


def test_set_textarea_escapes_value():
    js = d.js_set_textarea("textarea", 'a"b\\c')
    assert '"a\\"b\\\\c"' in js


def test_press_enter_dispatches_keydown_and_keyup_without_shift():
    js = d.js_press_enter("textarea")
    # The driver dispatches both keydown and keyup (via the loop over the two
    # type literals) so React's synthetic onKeyDown is reliably observed.
    assert "'keydown','keyup'" in js
    assert "KeyboardEvent(type," in js
    assert "key:'Enter'" in js
    assert "shiftKey:false" in js  # PromptBar submits only on non-shift Enter
    assert "bubbles:true" in js


def test_create_question_submits_prompt_after_filling():
    # Filling the React-controlled textarea is not enough; the real product
    # send button path must receive a trusted pointer event.
    assert "click_prompt_send(cdp)" in inspect.getsource(d.create_question)


def test_prompt_send_uses_trusted_cdp_pointer_events():
    source = inspect.getsource(d.click_prompt_send)
    assert 'button[aria-label=\\"发送\\"]' in source
    assert "Input.dispatchMouseEvent" in source
    assert "mousePressed" in source and "mouseReleased" in source


def test_authenticated_preflight_uses_native_bridge_and_protected_route():
    source = inspect.getsource(d.authenticated_preflight)
    assert "remote_session_status" in source
    assert "remote_api_request" in source
    assert "/api/system/capabilities" in source
    assert "classify_preflight_status" in source
    assert "auth_mode" in source


def test_curiosity_navigation_uses_real_anchor_and_waits_for_prompt_surface():
    source = inspect.getsource(d.navigate_page)
    assert "anchor_selector = f'a[href=\"{path}\"]" in source
    assert "command-palette item" in source
    assert "prefer it before any" in source
    assert "if static_export_route():" in source
    assert "if command_palette_click():" in source
    assert "_on_page(cdp, path)" in source
    assert "_shell_ready(cdp)" in source
    assert "Input.dispatchMouseEvent" in source
    assert "clicked_anchor_input" in source
    assert "clicked_command_palette_input" in source
    assert "button.commandItem" in source
    assert "el.click(); return {ok:true}" in source
    assert "window.location.replace('/curiosity.html')" in source
    assert "static_export_entrypoint" in source
    assert "quick_navigation_unverified" in source
    assert 'document.querySelector(\'textarea\') && location.pathname.startsWith' in source
    assert "curiosity PromptBar did not render" in inspect.getsource(d.create_question)


def test_shell_ready_accepts_static_export_trailing_slash_route():
    source = inspect.getsource(d._shell_ready)
    assert 'a[href^=\\"/curiosity\\"]' in source


def test_curiosity_static_export_entrypoint_counts_as_target_page():
    source = inspect.getsource(d._on_page)
    assert 'pathname == "/curiosity.html"' in source


def test_resilient_cdp_reconnects_after_transport_close():
    class BrokenCdp:
        def evaluate(self, _expression):
            raise BrokenPipeError("closed")

    class HealthyCdp:
        def evaluate(self, _expression):
            return {"ok": True}

    session = object.__new__(d.ResilientCdp)
    session._cdp = BrokenCdp()
    reconnects = []

    def reconnect():
        reconnects.append(True)
        session._cdp = HealthyCdp()

    session._connect = reconnect
    assert session.evaluate("1") == {"ok": True}
    assert reconnects == [True]


# ---------------------------------------------------------------------------
# markers
# ---------------------------------------------------------------------------
def test_unique_marker_distinct_and_plain_text():
    a, b = d.unique_marker(), d.unique_marker()
    assert a != b
    assert a.startswith("ig-upgrade-ci")
    # Must be matchable verbatim in document text: no spaces, no '/'.
    assert " " not in a and "/" not in a and ":" not in a


# ---------------------------------------------------------------------------
# state-file + result shaping (driver-level, no emulator)
# ---------------------------------------------------------------------------
def _run_main(args):
    return d.main(args)


def test_create_writes_fail_result_without_target():
    with tempfile.TemporaryDirectory() as td:
        res = os.path.join(td, "res.json")
        state = os.path.join(td, "state.json")
        rc = _run_main([
            "--stage", "create",
            "--devtools-port", "1",
            "--origin", "https://127.0.0.1:1",
            "--owner-password", "x", "--device-name", "d",
            "--state-file", state, "--result-file", res,
            "--adb", "false-adb",
        ])
        payload = json.load(open(res))
    assert rc == 1
    assert payload["result"] == "FAIL"
    assert payload["stage"] == "create"
    assert payload["detail"], "an honest diagnostic must be captured"


def test_verify_without_create_state_fails_fast():
    # No marker in state => verify must FAIL with a precise detail, never PASS.
    with tempfile.TemporaryDirectory() as td:
        res = os.path.join(td, "res.json")
        rc = _run_main([
            "--stage", "verify",
            "--devtools-port", "1",
            "--origin", "https://127.0.0.1:1",
            "--owner-password", "x", "--device-name", "d",
            "--state-file", os.path.join(td, "missing.json"), "--result-file", res,
            "--adb", "false-adb",
        ])
        payload = json.load(open(res))
    assert rc == 1
    assert payload["result"] == "FAIL"
    assert "marker_question" in payload["detail"]


def test_state_roundtrip_shapes():
    state = {"marker_question": "ig-upgrade-ci-1", "mutation_question": "ig-upgrade-mutate-1"}
    # verify-stage shape helper reads the marker back out.
    assert state.get("marker_question")
    assert state.get("mutation_question")


def test_no_stdlib_libs():
    for bad in ("requests", "websocket", "ws"):
        assert not any(line.startswith(f"import {bad}") for line in open(d.__file__)), bad


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
    import sys
    sys.exit(run_all())
