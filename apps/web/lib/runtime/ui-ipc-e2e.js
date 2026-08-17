// Gate R2 §8.2 — Android UI/IPC smoke (renderer driver).
//
// The §10.2 vertical slice proves the native broker → server leg WITHOUT a
// WebView. This driver closes the half that slice deliberately skips:
//
//   WebView/Renderer → ClientRuntime → Tauri invoke → native broker → server
//
// It runs INSIDE the real Android WebView and uses the very same
// `@tauri-apps/api` invoke bridge (through the `tauri-android` platform
// adapter) that the production runtime uses. It only activates when the CI
// emulator job has injected an `ig_uiipc_config.json` trigger accessible via
// the `ui_ipc_e2e_should_run` invoke command.
//
// Inertness guarantees:
//   * non-Tauri shell (browser / Playwright without a trigger) → `isTauri()`
//     false or `ui_ipc_e2e_should_run` unavailable / returns null ⇒ returns.
//   * release APKs → the `ui_ipc_e2e_*` commands are no-ops (Rust side).
//   * desktop → the commands are no-ops outside `debug_assertions + android`.
//
// Every step is recorded through `ui_ipc_e2e_record`, which the Rust side
// persists to `files/ig_uiipc_result.json` for CI to poll, and a `final` step
// carries PASS iff all steps succeeded. A step failure never throws out of the
// driver: faults are recorded so CI sees a deterministic FAIL, then the driver
// stops early.
import { invoke, isTauri } from '@tauri-apps/api/core';

import * as android from './platforms/tauri-android.js';

function record(step, ok, detail) {
  return invoke('ui_ipc_e2e_record', { step, ok, detail }).catch(() => {});
}

function failDetail(err) {
  return String(err?.message ?? err ?? 'unknown');
}

export async function maybeRunUiIpcE2e() {
  // Only ever run inside a real shell; a browser has no trigger to honor.
  if (typeof window === 'undefined' || !isTauri()) return;

  let config = null;
  try {
    config = await invoke('ui_ipc_e2e_should_run');
  } catch {
    return; // command unavailable in this build → inert.
  }
  if (!config?.origin) return; // no injected trigger marker → normal boot.

  const { origin, ownerPassword, bootstrapToken, deviceName } = config;
  const steps = [];
  let aborted = false;
  const step = (name, ok, detail) => {
    steps.push({ step: name, ok, detail });
    record(name, ok, detail);
    if (!ok) aborted = true;
    return ok;
  };

  // 1. Renderer leg: `isTauri()` is true ⇒ we are inside the WebView.
  step('renderer', true, `isTauri=${isTauri()} webview run`);

  // 2. Runtime source of truth: the actual ClientRuntime resolves to
  //    android-remote, never a desktop-local fallback (Gate E / §10).
  let client = null;
  try {
    const { getClientRuntime } = await import('./client-runtime.js');
    client = await getClientRuntime();
  } catch (err) {
    step('runtime_resolve', false, failDetail(err));
    return;
  }
  const runtimeId = client?.descriptor?.runtimeId;
  if (!step('runtime_android_remote', runtimeId === 'android-remote',
    `runtimeId=${runtimeId} platform=${client?.platform}`)) {
    // A desktop-local fallback on Android is itself a failure (§10).
    return;
  }
  if (!step('platform_android', client?.platform === 'android',
    `platform=${client?.platform}`)) {
    return;
  }

  // 3. Probe the real server through the real invoke → remote_probe_server.
  let probe = null;
  try {
    probe = await android.remoteProbeServer(origin);
    step('probe_server', Boolean(probe?.runtime || probe), `origin=${origin}`);
  } catch (err) {
    step('probe_server', false, failDetail(err));
    return;
  }

  // 4. Bootstrap a fresh owner when the server has none enrolled.
  if (!probe?.server?.ownerConfigured) {
    try {
      await android.remoteBootstrapOwner(origin, ownerPassword, bootstrapToken);
      step('bootstrap_owner', true, 'owner bootstrapped');
    } catch (err) {
      step('bootstrap_owner', false, failDetail(err));
      return;
    }
  } else {
    record('bootstrap_owner', true, 'owner already configured');
    steps.push({ step: 'bootstrap_owner', ok: true, detail: 'owner already configured' });
  }

  // 5. Login through the real invoke → remote_login.
  try {
    const login = await android.remoteLogin({
      origin,
      ownerPassword,
      deviceName,
      platform: 'android',
      appVersion: '',
      expectedServerInstanceId: '',
    });
    step('login', Boolean(login?.deviceId), `device=${login?.deviceId}`);
  } catch (err) {
    step('login', false, failDetail(err));
    return;
  }

  // 6. Authenticated session must now report connected.
  try {
    const status = await android.remoteSessionStatus();
    step('session_connected', Boolean(status?.enrolled && status?.connected),
      `enrolled=${status?.enrolled} connected=${status?.connected}`);
  } catch (err) {
    step('session_connected', false, failDetail(err));
    return;
  }

  // 7. One real remote API round-trip (a page-level capability present).
  try {
    const resp = await android.remoteApiRequest('/api/system/capabilities', { method: 'GET' });
    const ok = Number(resp?.status) === 200;
    step('api_get', ok, `status=${resp?.status}`);
  } catch (err) {
    step('api_get', false, failDetail(err));
    return;
  }

  // 8. Logout with server-side revoke.
  try {
    await android.remoteLogout(true);
    step('logout_revoke', true, 'device revoked');
  } catch (err) {
    step('logout_revoke', false, failDetail(err));
  }

  // 9. Final aggregation.
  const pass = !aborted && steps.every((s) => s.ok);
  await record('final', pass, `ui-ipc smoke ${pass ? 'PASS' : 'FAIL'} (${steps.length} steps)`);

  return { steps, result: pass ? 'PASS' : 'FAIL' };
}