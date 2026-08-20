// Gate D §P25 — runtime-connect lifecycle controller tests.
//
// Run with: node --test apps/web/lib/runtime/test/runtime-connect-controller.test.mjs
// The active/pending separation (P10) is the single most safety-relevant
// lifecycle: a persisted switch must never be presented as the active mode,
// and the data-location label must follow the ACTIVE runtime only.
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  initialRuntimeConnectState,
  runtimeConnectReducer,
  dataLocationOf,
  isRemoteActive,
  isRemoteRuntime,
  resumeSessionDecision,
  RUNTIME_LOCAL,
  RUNTIME_REMOTE,
  RUNTIME_ANDROID_REMOTE,
} from '../runtime-connect-controller.js';

test('active local, no pending → local, no restart required', () => {
  const state = initialRuntimeConnectState({ activeRuntimeId: RUNTIME_LOCAL });
  assert.equal(state.activeRuntimeId, RUNTIME_LOCAL);
  assert.equal(state.pendingRuntimeId, RUNTIME_LOCAL);
  assert.equal(state.restartRequired, false);
  assert.equal(dataLocationOf(state), 'local-device');
});

test('persist remote pending keeps active local and requires restart', () => {
  let state = initialRuntimeConnectState({ activeRuntimeId: RUNTIME_LOCAL });
  state = runtimeConnectReducer(state, { type: 'SWITCH_PERSISTED', pendingRuntimeId: RUNTIME_REMOTE });
  assert.equal(state.activeRuntimeId, RUNTIME_LOCAL, 'active must stay local');
  assert.equal(state.pendingRuntimeId, RUNTIME_REMOTE);
  assert.equal(state.restartRequired, true);
  // Data location stays local because active is still local.
  assert.equal(dataLocationOf(state), 'local-device');
  assert.equal(isRemoteActive(state), false);
});

test('after a real restart active becomes remote, pending remote, no restart needed', () => {
  let state = initialRuntimeConnectState({ activeRuntimeId: RUNTIME_LOCAL });
  state = runtimeConnectReducer(state, { type: 'SWITCH_PERSISTED', pendingRuntimeId: RUNTIME_REMOTE });
  assert.equal(state.restartRequired, true);
  state = runtimeConnectReducer(state, { type: 'RESTART_APPLIED' });
  assert.equal(state.activeRuntimeId, RUNTIME_REMOTE);
  assert.equal(state.pendingRuntimeId, RUNTIME_REMOTE);
  assert.equal(state.restartRequired, false);
  assert.equal(dataLocationOf(state), 'self-hosted-server');
});

test('MODE_LOADED (native truth) drives active and pending independently', () => {
  let state = initialRuntimeConnectState({ activeRuntimeId: RUNTIME_LOCAL });
  state = runtimeConnectReducer(state, {
    type: 'MODE_LOADED',
    activeRuntimeId: RUNTIME_LOCAL,
    pendingRuntimeId: RUNTIME_REMOTE,
  });
  assert.equal(state.activeRuntimeId, RUNTIME_LOCAL);
  assert.equal(state.pendingRuntimeId, RUNTIME_REMOTE);
  assert.equal(state.restartRequired, true);
  assert.equal(dataLocationOf(state), 'local-device');

  // Native says this process already restarted into remote.
  state = runtimeConnectReducer(state, {
    type: 'MODE_LOADED',
    activeRuntimeId: RUNTIME_REMOTE,
    pendingRuntimeId: RUNTIME_REMOTE,
  });
  assert.equal(state.activeRuntimeId, RUNTIME_REMOTE);
  assert.equal(state.restartRequired, false);
  assert.equal(dataLocationOf(state), 'self-hosted-server');
});

test('cancelling a pending switch restores local without a restart', () => {
  let state = initialRuntimeConnectState({ activeRuntimeId: RUNTIME_LOCAL });
  state = runtimeConnectReducer(state, { type: 'SWITCH_PERSISTED', pendingRuntimeId: RUNTIME_REMOTE });
  state = runtimeConnectReducer(state, { type: 'RESET_PENDING' });
  assert.equal(state.activeRuntimeId, RUNTIME_LOCAL);
  assert.equal(state.pendingRuntimeId, RUNTIME_LOCAL);
  assert.equal(state.restartRequired, false);
  assert.equal(dataLocationOf(state), 'local-device');
});

test('probe/compatibility/identity/session statuses are tracked', () => {
  let state = initialRuntimeConnectState();
  state = runtimeConnectReducer(state, { type: 'PROBE_START' });
  assert.equal(state.probeState, 'probing');
  state = runtimeConnectReducer(state, { type: 'PROBE_OK', compatible: true, probe: { ok: true } });
  assert.equal(state.probeState, 'ok');
  assert.equal(state.compatibilityState, 'compatible');
  state = runtimeConnectReducer(state, { type: 'IDENTITY_CHANGED' });
  assert.equal(state.identityState, 'changed');
  state = runtimeConnectReducer(state, { type: 'SESSION_LOADED', session: { enrolled: true } });
  assert.equal(state.sessionState, 'enrolled');
  assert.equal(state.session.enrolled, true);
});

test('reducer rejects unknown runtime ids fail-closed', () => {
  const state = initialRuntimeConnectState();
  assert.throws(
    () => runtimeConnectReducer(state, { type: 'SWITCH_PERSISTED', pendingRuntimeId: 'garbage' }),
    /unknown runtime id/,
  );
  assert.throws(
    () => runtimeConnectReducer(state, { type: 'MODE_LOADED', activeRuntimeId: 'tauri', pendingRuntimeId: RUNTIME_LOCAL }),
    /unknown runtime id/,
  );
});

// Gate R0.1 — android-remote is a first-class runtime id. The reducer must
// accept it and the controller must classify it as remote everywhere the
// desktop-remote checks used to be hardcoded.
test('reducer accepts android-remote as a native runtime id', () => {
  let state = initialRuntimeConnectState({ activeRuntimeId: RUNTIME_ANDROID_REMOTE });
  assert.equal(state.activeRuntimeId, RUNTIME_ANDROID_REMOTE);
  assert.equal(state.pendingRuntimeId, RUNTIME_ANDROID_REMOTE);
  // Native process setup resolves android-remote without an error.
  state = runtimeConnectReducer(state, {
    type: 'MODE_LOADED',
    activeRuntimeId: RUNTIME_ANDROID_REMOTE,
    pendingRuntimeId: RUNTIME_ANDROID_REMOTE,
  });
  assert.equal(state.activeRuntimeId, RUNTIME_ANDROID_REMOTE);
  assert.equal(state.restartRequired, false);
});

test('android-remote is classified remote: data location and isRemoteActive', () => {
  const state = initialRuntimeConnectState({ activeRuntimeId: RUNTIME_ANDROID_REMOTE });
  assert.equal(isRemoteRuntime(RUNTIME_ANDROID_REMOTE), true);
  assert.equal(isRemoteActive(state), true);
  // Android never exposes a local-device data location (R0.1).
  assert.equal(dataLocationOf(state), 'self-hosted-server');
});

test('desktop local is never classified remote', () => {
  const state = initialRuntimeConnectState({ activeRuntimeId: RUNTIME_LOCAL });
  assert.equal(isRemoteRuntime(RUNTIME_LOCAL), false);
  assert.equal(isRemoteActive(state), false);
  assert.equal(dataLocationOf(state), 'local-device');
});

// ---- Gate R0.4 §R0.4 / §6.3 — resume re-evaluation decision ----------------
// Fresh install + background/resume must resolve to RESET/Initializing and
// NEVER to the terminal LoginExpired state (which is reserved for a revoked /
// expired credential on a device that WAS enrolled).
test('fresh install resume → RESET, never LoginExpired (§6.3)', () => {
  const status = { enrolled: false };
  assert.equal(resumeSessionDecision({ status, identity: null, refreshed: null }), 'RESET');
  // Even if a bogus identity/refresh result leaks in, not-enrolled wins first.
  assert.equal(
    resumeSessionDecision({ status, identity: { identityChanged: true }, refreshed: { authExpired: true } }),
    'RESET',
  );
});

test('enrolled + server replaced resume → IdentityChanged (§6.3)', () => {
  const status = { enrolled: true, connected: true };
  assert.equal(
    resumeSessionDecision({ status, identity: { identityChanged: true }, refreshed: null }),
    'IDENTITY_MISMATCH',
  );
});

test('enrolled + connected resume → BOOTSTRAP_OK (§6.3)', () => {
  const status = { enrolled: true, connected: true };
  assert.equal(
    resumeSessionDecision({ status, identity: { identityChanged: false }, refreshed: null }),
    'BOOTSTRAP_OK',
  );
});

test('enrolled + not-connected + refresh ok → BOOTSTRAP_OK (§6.3)', () => {
  const status = { enrolled: true, connected: false };
  assert.equal(
    resumeSessionDecision({ status, identity: {}, refreshed: { connected: true } }),
    'BOOTSTRAP_OK',
  );
});

test('enrolled + revoked credential resume → REFRESH_FAIL (LoginExpired) (§6.3)', () => {
  const status = { enrolled: true, connected: false };
  assert.equal(
    resumeSessionDecision({ status, identity: {}, refreshed: { authExpired: true } }),
    'REFRESH_FAIL',
  );
});

test('enrolled + transient network failure resume → NETWORK_FAIL (§6.3)', () => {
  const status = { enrolled: true, connected: false };
  assert.equal(
    resumeSessionDecision({ status, identity: {}, refreshed: { connected: false, authExpired: false } }),
    'NETWORK_FAIL',
  );
  // A thrown coded error short-circuits to the mapped event.
  assert.equal(resumeSessionDecision({ status, identity: {}, refreshed: null, error: 'NETWORK_FAIL' }), 'NETWORK_FAIL');
});
