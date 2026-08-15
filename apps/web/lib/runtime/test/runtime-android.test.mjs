// Gate E §6.5 / BLOCKER-2 — real Android runtime resolution tests.
//
// Run with: node --test apps/web/lib/runtime/test/runtime-android.test.mjs
//
// These prove that `android-remote` resolves to an ACTIVE native
// RemoteTransport through the shared resolveNativeRemote resolver — NOT to
// the desktop mock and NOT to the inactive/browser fallback. The resolver is
// adapter-injected (pure, no Tauri import), so the tests drive it with an
// Android-shaped adapter that mirrors the tauri-android.js broker surface
// (same method names, same relative-path contract). This is the real shared
// resolver used by the product, never a desktop-remote stand-in.
import test from 'node:test';
import assert from 'node:assert/strict';

import { resolveNativeRemote } from '../client-runtime.js';
import { RemoteTransport, remoteErrorEvent } from '../transports/remote.js';
import { RUNTIME_IDS } from '../contract.js';

// ---- Android-shaped native broker adapter ------------------------------
// Mirrors the exact surface of apps/web/lib/runtime/platforms/tauri-android.js
// (remoteSessionStatus / remoteRefreshNow / remoteApiRequest / remoteApiUpload)
// so the shared resolver is exercised with the Android broker contract.
function androidAdapter({ status, refreshResult, requestImpl, uploadImpl } = {}) {
  let refreshCalls = 0;
  let sessionCalls = 0;
  return {
    refreshCalls: () => refreshCalls,
    sessionCalls: () => sessionCalls,
    // Broker surface used by resolveNativeRemote / RemoteTransport.
    async remoteSessionStatus() {
      sessionCalls += 1;
      return status ?? { enrolled: false };
    },
    async remoteRefreshNow() {
      refreshCalls += 1;
      if (typeof refreshResult === 'function') return refreshResult();
      return refreshResult ?? { connected: true };
    },
    async remoteApiRequest(path, opts) {
      if (requestImpl) return requestImpl(path, opts);
      return { status: 200, bodyBase64: '', contentType: '' };
    },
    async remoteApiUpload(path, opts) {
      if (uploadImpl) return uploadImpl(path, opts);
      return { status: 200, bodyBase64: '', contentType: '' };
    },
    // Host actions that must be present on the adapter surface.
    async remoteProbeServer() { throw new Error('unused'); },
    async remoteBootstrapOwner() { throw new Error('unused'); },
    async remoteLogin() { throw new Error('unused'); },
    async remoteVerifyIdentity() { throw new Error('unused'); },
    async remoteLogout() { throw new Error('unused'); },
    async openExternal() { return true; },
  };
}

function enrolledStatus(overrides = {}) {
  return {
    enrolled: true,
    connected: true,
    serverDisplayName: 'IG 自托管服务器',
    normalizedOrigin: 'https://ig.example.com',
    serverInstanceId: 'server-A',
    serverVersion: '0.7.0',
    apiVersion: 1,
    minClientVersion: '0.7.0',
    authExpired: false,
    ...overrides,
  };
}

// ---- §1 android-remote resolves to an ACTIVE native RemoteTransport ------
test('android-remote resolves to an active native RemoteTransport (BLOCKER-2)', async () => {
  const adapter = androidAdapter({ status: enrolledStatus() });
  const { descriptor, connection, transport } = await resolveNativeRemote(
    'android-remote',
    'android',
    {},
    adapter,
  );
  assert.equal(descriptor.runtimeId, 'android-remote');
  assert.equal(transport.active, true, 'android-remote must never be an inactive remote transport');
  assert.ok(transport instanceof RemoteTransport);
  // Enrollment state is read from the native broker, so the descriptor is
  // bound to the real verified server.
  assert.equal(descriptor.server.normalizedOrigin, 'https://ig.example.com');
  assert.equal(descriptor.server.serverInstanceId, 'server-A');
  assert.equal(connection.state, 'Connected');
  assert.equal(connection.mutationsAllowed, true);
});

test('android-remote never falls back to desktop-local', async () => {
  const adapter = androidAdapter({ status: { enrolled: false } });
  const { descriptor, transport, connection } = await resolveNativeRemote(
    'android-remote',
    'android',
    {},
    adapter,
  );
  // Even without enrollment the resolver keeps the android-remote identity;
  // it does NOT silently downgrade to a desktop/local loopback store.
  assert.equal(descriptor.runtimeId, 'android-remote');
  assert.equal(descriptor.dataLocation, 'self-hosted-server');
  assert.equal(descriptor.transport, 'native-http');
  assert.equal(descriptor.server, null, 'unbound server stays null');
  assert.equal(transport.active, true, 'broker exists, so the native transport is armed');
  assert.equal(connection.state, 'Initializing');
  assert.equal(connection.mutationsAllowed, false);
});

test('android-remote never exposes desktop token or a renderer authHeader', async () => {
  const adapter = androidAdapter({ status: enrolledStatus() });
  const { descriptor, transport } = await resolveNativeRemote(
    'android-remote',
    'android',
    {},
    adapter,
  );
  // Android has no desktop token / local credential surface (Gate E).
  assert.equal(descriptor.capabilities.canUseDesktopToken, false);
  assert.equal(descriptor.capabilities.canAdminLocalProviderSecret, false);
  // The remote transport never hands a Bearer to the renderer.
  assert.deepEqual(transport.authHeader, {});
});

test('android-remote storage namespace is server_instance_id scoped', async () => {
  const adapter = androidAdapter({ status: enrolledStatus({ serverInstanceId: 'server-A' }) });
  const a = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  assert.equal(a.descriptor.storageNamespace, 'android-remote:server-A');

  // A different server instance must not collide with desktop-remote's namespace.
  const desktop = await resolveNativeRemote(
    'desktop-remote',
    'macos',
    {},
    androidAdapter({ status: enrolledStatus({ serverInstanceId: 'server-A' }) }),
  );
  assert.notEqual(a.descriptor.storageNamespace, desktop.descriptor.storageNamespace);
  assert.equal(a.descriptor.storageNamespace.startsWith('android-remote:'), true);

  // Unenrolled Android has no server instance, so no storage namespace is claimed.
  const unbound = await resolveNativeRemote(
    'android-remote',
    'android',
    {},
    androidAdapter({ status: { enrolled: false } }),
  );
  assert.equal(unbound.descriptor.storageNamespace, null);
});

// ---- §2 android-remote GET / uploads go through the native broker ---------
test('android-remote GET uses the native broker (relative path only)', async () => {
  const calls = [];
  const adapter = androidAdapter({
    status: enrolledStatus(),
    requestImpl: async (path, opts) => {
      calls.push({ path, opts });
      return {
        status: 200,
        bodyBase64: Buffer.from('{"ok":true}').toString('base64'),
        contentType: 'application/json',
      };
    },
  });
  const { transport } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  const response = await transport.request('/api/system/capabilities');
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/system/capabilities');
  // The renderer can never set Authorization; native broker owns credentials.
  assert.equal(calls[0].opts.headers.Authorization, undefined);
});

test('android-remote upload goes through the native broker with bounded base64', async () => {
  const calls = [];
  const adapter = androidAdapter({
    status: enrolledStatus(),
    uploadImpl: async (path, opts) => {
      calls.push({ path, opts });
      return { status: 200, bodyBase64: '', contentType: '' };
    },
  });
  const { transport } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  const form = new FormData();
  form.append('file', new File([new Uint8Array(64)], 'note.txt', { type: 'text/plain' }));
  await transport.request('/api/knowledge/sources/upload', { method: 'POST', body: form });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/knowledge/sources/upload');
  assert.equal(calls[0].opts.fileName, 'note.txt');
});

test('android-remote rejects absolute / protocol-relative paths like desktop', async () => {
  const adapter = androidAdapter({ status: enrolledStatus() });
  const { transport } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  await assert.rejects(transport.request('https://evil.example.com/x'), /absolute URLs/);
  await assert.rejects(transport.request('//evil.example.com/x'), /protocol-relative/);
});

// ---- §3 fail-closed mutation / single-flight refresh ----------------------
test('android-remote mutation is blocked while not Connected', async () => {
  // Server says the refresh credential is already expired: the machine goes
  // LoginExpired and mutations must be blocked before reaching the broker.
  const adapter = androidAdapter({
    status: enrolledStatus({ connected: false, authExpired: true }),
  });
  const { transport, connection } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  assert.equal(connection.state, 'LoginExpired');
  assert.equal(connection.mutationsAllowed, false);
  let calls = 0;
  adapter.remoteApiRequest = async () => { calls += 1; return { status: 200, bodyBase64: '', contentType: '' }; };
  await assert.rejects(
    transport.request('/api/questions', { method: 'POST', body: '{}' }),
    /mutations are blocked/,
  );
  assert.equal(calls, 0, 'broker must never see a blocked mutation');
});

test('android-remote enrolled-not-connected triggers exactly one native refresh', async () => {
  // HIGH-2: "enrolled + refresh stored + not connected" is a NORMAL restart
  // state. The resolver must recover through the native broker exactly once.
  const adapter = androidAdapter({
    status: enrolledStatus({ connected: false, authExpired: false }),
    refreshResult: () => ({ connected: true }),
  });
  const { connection } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  assert.equal(adapter.refreshCalls(), 1, 'single-flight native refresh must run exactly once');
  assert.equal(connection.state, 'Connected');
});

test('android-remote refresh failure maps to LoginExpired (server verdict)', async () => {
  const adapter = androidAdapter({
    status: enrolledStatus({ connected: false, authExpired: false }),
    refreshResult: () => ({ authExpired: true }),
  });
  const { connection } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  assert.equal(adapter.refreshCalls(), 1);
  assert.equal(connection.state, 'LoginExpired');
  assert.equal(connection.mutationsAllowed, false);
});

test('android-remote 401 after a successful refresh → LoginExpired, no renderer retry', async () => {
  let requests = 0;
  const adapter = androidAdapter({
    status: enrolledStatus({ connected: true }),
    requestImpl: async () => {
      requests += 1;
      return { status: 401, bodyBase64: '', contentType: '' };
    },
  });
  const { transport, connection } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  assert.equal(connection.state, 'Connected');
  // The native broker already ran its single-flight refresh before the final
  // 401; the transport must map it to LoginExpired and must NOT re-request.
  await transport.request('/api/notes');
  assert.equal(connection.state, 'LoginExpired');
  assert.equal(requests, 1, 'the transport never issues its own second request');
});

// ---- §4 coded error taxonomy mapping for android-remote -------------------
test('android-remote IdentityChanged maps to a terminal blocking state', async () => {
  const adapter = androidAdapter({
    status: enrolledStatus({ connected: true }),
    requestImpl: async () => {
      throw new Error('{"code":"IDENTITY_CHANGED","message":"server identity replaced"}');
    },
  });
  const { transport, connection } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  await assert.rejects(transport.request('/api/notes'), /replaced/);
  assert.equal(connection.state, 'IdentityChanged');
  assert.equal(connection.mutationsAllowed, false);
  await assert.rejects(
    transport.request('/api/notes', { method: 'POST', body: '{}' }),
    /mutations are blocked/,
  );
});

test('android-remote UpdateRequired / UnsupportedServer map via the coded taxonomy', async () => {
  assert.equal(remoteErrorEvent('{"code":"UPDATE_REQUIRED","message":"upgrade"}'), 'INCOMPATIBLE');
  assert.equal(remoteErrorEvent('{"code":"UNSUPPORTED_SERVER","message":"older"}'), 'UNSUPPORTED_SERVER');
  assert.equal(remoteErrorEvent('{"code":"PROTOCOL_ERROR","message":"proto"}'), 'UNSUPPORTED_SERVER');

  for (const [code, event] of [
    ['UPDATE_REQUIRED', 'INCOMPATIBLE'],
    ['UNSUPPORTED_SERVER', 'UNSUPPORTED_SERVER'],
  ]) {
    const adapter = androidAdapter({
      status: enrolledStatus({ connected: true }),
      requestImpl: async () => {
        throw new Error(`{"code":"${code}","message":"verdict"}`);
      },
    });
    const { transport, connection } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
    await assert.rejects(transport.request('/api/notes'), /verdict/);
    assert.equal(connection.state, event === 'INCOMPATIBLE' ? 'UpdateRequired' : 'UnsupportedServer');
    assert.equal(connection.mutationsAllowed, false);
  }
});

test('android-remote transient network failure stays recoverable (never LoginExpired)', async () => {
  const adapter = androidAdapter({
    status: enrolledStatus({ connected: true }),
    requestImpl: async () => {
      throw new Error('connection reset by peer');
    },
  });
  const { transport, connection } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  await assert.rejects(transport.request('/api/notes'), /connection reset/);
  assert.equal(connection.state, 'Reconnecting');
  assert.equal(connection.isTerminal, false);
});

// ---- §5 platform isolation -------------------------------------------------
test('android-remote is a frozen runtime id and never claims desktop-only surfaces', async () => {
  assert.ok(RUNTIME_IDS.includes('android-remote'));
  const adapter = androidAdapter({ status: enrolledStatus() });
  const { descriptor } = await resolveNativeRemote('android-remote', 'android', {}, adapter);
  // Desktop-only capability keys must stay false on the Android descriptor.
  for (const key of ['canUseDesktopToken', 'canAdminLocalProviderSecret', 'canUseSaveDialog']) {
    assert.equal(descriptor.capabilities[key], false, `${key} must be false on android-remote`);
  }
  // Android-native store is the renewal-credential home (Keystore), external
  // URL opening is the system browser — both real this round.
  assert.equal(descriptor.capabilities.canUseNativeSecureStore, true);
  assert.equal(descriptor.capabilities.canOpenExternalUrl, true);
  // Planned mobile adapters are honestly disabled until implemented.
  for (const key of ['canUseDocumentPicker', 'canUseShareSheet', 'supportsLifecycleSuspendResume', 'canUseBiometricUnlock']) {
    assert.equal(descriptor.capabilities[key], false, `${key} must be false (planned adapter)`);
  }
});
