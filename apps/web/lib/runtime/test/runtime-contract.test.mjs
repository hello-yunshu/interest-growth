// Gate C §21 — ClientRuntime pure contract tests.
//
// Run with: node --test apps/web/lib/runtime/test
// These cover the pure vocabulary only: descriptors, compatibility, semver,
// URL normalization, connection state machine, storage namespace and the
// credential store. No DOM / Tauri shell is required.
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  RUNTIME_IDS,
  CONNECTION_STATES,
  COMPATIBILITY,
  PLATFORM_CAPABILITIES,
  DESKTOP_ONLY_CAPABILITIES,
  API_PRODUCT,
  SUPPORTED_API_VERSION,
  isRuntimeId,
  isPlatformCapability,
} from '../contract.js';
import {
  desktopLocalDescriptor,
  desktopRemoteDescriptor,
  androidRemoteDescriptor,
  browserRemoteDescriptor,
  descriptorFor,
} from '../descriptors.js';
import { checkCompatibility } from '../compatibility.js';
import { compareVersions, parseVersion, isAtLeast } from '../semver.js';
import { normalizeEnrollmentOrigin } from '../url-normalization.js';
import { ConnectionStateMachine } from '../connection-state.js';
import { runtimeNamespaceKey, uiCacheKey, currentAreaKey } from '../storage-namespace.js';
import { CredentialStore, MemoryCredentialStore, credentialNamespace, enrolledServerIdentity } from '../credential-store.js';
import { RetryPolicy, isIdempotentMethod } from '../retry-policy.js';
import { RemoteTransport, parseRemoteErrorCode, remoteErrorEvent, REMOTE_ERROR_CODES } from '../transports/remote.js';

// ---- §21.2 / §4.4 runtime descriptors --------------------------------
test('frozen runtime ids are the only valid identities', () => {
  assert.deepEqual(RUNTIME_IDS, [
    'desktop-local',
    'desktop-remote',
    'android-remote',
    'browser-remote',
  ]);
  for (const id of RUNTIME_IDS) assert.equal(isRuntimeId(id), true);
  assert.equal(isRuntimeId('desktop'), false);
  assert.equal(isRuntimeId('tauri'), false);
});

test('desktop-local descriptor is a local loopback runtime', () => {
  const d = desktopLocalDescriptor('macos');
  assert.equal(d.runtimeId, 'desktop-local');
  assert.equal(d.dataLocation, 'local-device');
  assert.equal(d.transport, 'loopback');
  assert.equal(d.capabilities.canLaunchSidecar, true);
  assert.equal(d.capabilities.canUseDesktopToken, true);
  assert.equal(d.capabilities.canAdminLocalProviderSecret, true);
});

test('desktop-remote descriptor never launches a sidecar and has no local store', () => {
  const d = desktopRemoteDescriptor('macos');
  assert.equal(d.runtimeId, 'desktop-remote');
  assert.equal(d.dataLocation, 'self-hosted-server');
  assert.equal(d.capabilities.canLaunchSidecar, false);
  assert.equal(d.capabilities.canUseDesktopToken, false);
  assert.equal(d.capabilities.canAdminLocalProviderSecret, false);
  assert.equal(d.server, null); // bound only after explicit enrollment
});

test('isTauri does not decide runtime identity — same platform yields distinct runtimes', () => {
  const local = desktopLocalDescriptor('macos');
  const remote = desktopRemoteDescriptor('macos');
  assert.notEqual(local.runtimeId, remote.runtimeId);
  assert.notEqual(local.dataLocation, remote.dataLocation);
  assert.equal(local.platform, 'macos');
  assert.equal(remote.platform, 'macos');
});

test('android-remote and browser-remote descriptors are honest skeletons', () => {
  const android = androidRemoteDescriptor();
  assert.equal(android.runtimeId, 'android-remote');
  assert.equal(android.capabilities.canUseSaveDialog, false);
  assert.equal(android.capabilities.canUseNativeFs, false);
  const browser = browserRemoteDescriptor();
  assert.equal(browser.runtimeId, 'browser-remote');
  assert.equal(browser.transport, 'browser-http');
  assert.equal(browser.auth.mode, 'secure-cookie-planned'); // not release-proven
  assert.equal(browser.capabilities.canUseNativeSecureStore, false);
});

test('descriptorFor rejects unknown runtime ids', () => {
  assert.throws(() => descriptorFor('garbage'), /unknown runtimeId/);
});

// ---- Gate E mobile adaptation contract / desktop-only gate -------------
test('every descriptor carries the full frozen capability vocabulary', () => {
  const cases = [
    ['desktop-local', 'macos'],
    ['desktop-remote', 'macos'],
    ['android-remote', 'android'],
    ['browser-remote', 'browser'],
  ];
  for (const [id, platform] of cases) {
    const d = descriptorFor(id, platform);
    assert.deepEqual(
      Object.keys(d.capabilities).sort(),
      [...PLATFORM_CAPABILITIES].sort(),
      `${id} must carry every frozen capability key`,
    );
  }
});

test('the capability vocabulary and desktop-only gate are frozen', () => {
  for (const key of PLATFORM_CAPABILITIES) assert.equal(isPlatformCapability(key), true);
  assert.equal(isPlatformCapability('canDoAnything'), false);
  for (const key of DESKTOP_ONLY_CAPABILITIES) {
    assert.ok(PLATFORM_CAPABILITIES.includes(key), `${key} must exist in the vocabulary`);
  }
});

test('android-remote never reaches a desktop/local path; mobile adapters are planned', () => {
  const android = androidRemoteDescriptor();
  assert.equal(android.runtimeId, 'android-remote');
  for (const key of DESKTOP_ONLY_CAPABILITIES) {
    assert.equal(android.capabilities[key], false, `${key} must be false on android-remote`);
  }
  // Frozen contract §2 assigns the renewal credential to Android Keystore.
  assert.equal(android.capabilities.canUseNativeSecureStore, true);
  assert.equal(android.capabilities.canOpenExternalUrl, true);
  // Gate R0.4 — the SAF document picker is real now; the rest stay planned.
  assert.equal(android.capabilities.canUseDocumentPicker, true);
  assert.equal(android.capabilities.canUseShareSheet, false);
  assert.equal(android.capabilities.supportsLifecycleSuspendResume, false);
  assert.equal(android.capabilities.canUseBiometricUnlock, false);
});

test('browser-remote never reaches a desktop/local path either', () => {
  const browser = browserRemoteDescriptor();
  for (const key of DESKTOP_ONLY_CAPABILITIES) {
    assert.equal(browser.capabilities[key], false, `${key} must be false on browser-remote`);
  }
  assert.equal(browser.capabilities.canUseNativeSecureStore, false); // secure-cookie planned
});

// ---- §21.3 / §8 compatibility ----------------------------------------
test('compatibility accepts a compatible server', () => {
  assert.equal(checkCompatibility({
    clientVersion: '0.7.0',
    minClientVersion: '0.7.0',
    runtimeId: 'desktop-local',
    runtimeModes: ['desktop-local', 'desktop-remote'],
    authEnabled: true,
    authMode: 'single_owner_devices',
  }), 'Compatible');
});

test('compatibility rejects wrong product / api version', () => {
  assert.equal(checkCompatibility({ clientVersion: '0.7.0', serverProduct: 'other' }), 'WrongProduct');
  assert.equal(checkCompatibility({ clientVersion: '0.7.0', apiVersion: 2 }), 'ApiVersionMismatch');
});

test('0.6 client against min_client_version=0.7.0 is honestly UpdateRequired', () => {
  assert.equal(checkCompatibility({
    clientVersion: '0.6.0',
    minClientVersion: '0.7.0',
    runtimeId: 'desktop-remote',
    runtimeModes: ['desktop-remote'],
    authEnabled: true,
    authMode: 'single_owner_devices',
  }), 'UpdateRequired');
});

test('compatibility rejects unsupported runtime and disabled remote auth', () => {
  assert.equal(checkCompatibility({
    clientVersion: '0.7.0',
    minClientVersion: '0.7.0',
    runtimeId: 'desktop-remote',
    runtimeModes: ['desktop-local'],
    authEnabled: true,
    authMode: 'single_owner_devices',
  }), 'RuntimeUnsupported');
  assert.equal(checkCompatibility({
    clientVersion: '0.7.0',
    minClientVersion: '0.7.0',
    runtimeId: 'desktop-remote',
    runtimeModes: ['desktop-remote'],
    authEnabled: false,
    authMode: 'none',
  }), 'AuthModeUnsupported');
});

test('all compatibility outcomes are in the frozen vocabulary', () => {
  for (const value of COMPATIBILITY) {
    assert.equal(typeof value, 'string');
  }
  assert.ok(COMPATIBILITY.includes('Compatible'));
  assert.ok(COMPATIBILITY.includes('UpdateRequired'));
});

// ---- §8.2 semver ------------------------------------------------------
test('semver compares numerically, not lexicographically', () => {
  assert.equal(compareVersions('0.10.0', '0.9.0'), 1);
  assert.equal(compareVersions('0.9.0', '0.10.0'), -1);
  assert.equal(compareVersions('0.6.0', '0.7.0'), -1);
  assert.equal(compareVersions('1.0.0', '0.99.99'), 1);
});

test('semver handles prerelease precedence', () => {
  assert.equal(compareVersions('1.0.0-rc.2', '1.0.0-rc.10'), -1);
  assert.equal(compareVersions('1.0.0', '1.0.0-rc.1'), 1);
  assert.equal(compareVersions('0.6.0-rc.2', '0.6.0'), -1);
});

test('semver rejects non-strict versions such as 0.6.0rc2', () => {
  // The Native Core standalone internal label "0.6.0rc2" is not strict SemVer;
  // the compatibility checker never feeds it through compareVersions.
  assert.throws(() => compareVersions('0.6.0rc2', '0.6.0'), /invalid semver/);
});

test('semver ignores build metadata and parses strict versions', () => {
  assert.equal(compareVersions('1.0.0+build.1', '1.0.0+build.2'), 0);
  assert.throws(() => parseVersion('1.0'), /invalid semver/);
  assert.throws(() => parseVersion(''), /invalid semver/);
  assert.equal(isAtLeast('0.10.0', '0.9.0'), true);
  assert.equal(isAtLeast('0.6.0', '0.7.0'), false);
});

// ---- §7 URL normalization ---------------------------------------------
test('normalizes valid self-hosted origins', () => {
  assert.deepEqual(normalizeEnrollmentOrigin('https://ig.example.com'), {
    ok: true, origin: 'https://ig.example.com', tls: true, loopback: false,
  });
  assert.deepEqual(normalizeEnrollmentOrigin('https://192.168.1.20'), {
    ok: true, origin: 'https://192.168.1.20', tls: true, loopback: false,
  });
  assert.deepEqual(normalizeEnrollmentOrigin('https://my-server.local'), {
    ok: true, origin: 'https://my-server.local', tls: true, loopback: false,
  });
});

test('rejects credentials, fragment, query and subpaths', () => {
  assert.equal(normalizeEnrollmentOrigin('https://user:pass@ig.example.com').ok, false);
  assert.equal(normalizeEnrollmentOrigin('https://ig.example.com/#frag').ok, false);
  assert.equal(normalizeEnrollmentOrigin('https://ig.example.com/?a=1').ok, false);
  assert.equal(normalizeEnrollmentOrigin('https://ig.example.com/sub').ok, false);
});

test('requires HTTPS for public/LAN and limits loopback HTTP to explicit dev/test', () => {
  assert.equal(normalizeEnrollmentOrigin('http://192.168.1.20').ok, false); // HTTPS_REQUIRED
  assert.equal(normalizeEnrollmentOrigin('http://ig.example.com').ok, false);
  assert.equal(normalizeEnrollmentOrigin('http://127.0.0.1').ok, false); // no dev flag
  assert.equal(normalizeEnrollmentOrigin('http://127.0.0.1', { allowLoopbackHttp: true }).ok, true);
  assert.equal(normalizeEnrollmentOrigin('ftp://ig.example.com').ok, false); // SCHEME_NOT_ALLOWED
});

// ---- §21.4 connection state machine -----------------------------------
test('Connected -> network fail -> Reconnecting -> Offline with bounded retry', () => {
  const m = new ConnectionStateMachine({ initialState: 'Connected', maxReconnectAttempts: 2 });
  assert.equal(m.handle('NETWORK_FAIL'), 'Reconnecting');
  assert.equal(m.handle('NETWORK_FAIL'), 'Reconnecting');
  assert.equal(m.handle('NETWORK_FAIL'), 'Offline'); // no infinite retry
  assert.equal(m.isConnected, false);
  assert.equal(m.mutationsAllowed, false);
});

test('Connected -> 401 refresh success -> Connected; refresh failure -> LoginExpired', () => {
  const ok = new ConnectionStateMachine({ initialState: 'Connected' });
  assert.equal(ok.handle('REFRESH_OK'), 'Connected');
  const fail = new ConnectionStateMachine({ initialState: 'Connected' });
  assert.equal(fail.handle('REFRESH_FAIL'), 'LoginExpired');
  assert.equal(fail.mutationsAllowed, false);
});

test('identity mismatch blocks and never auto-accepts', () => {
  const m = new ConnectionStateMachine({ initialState: 'Connected' });
  assert.equal(m.handle('IDENTITY_MISMATCH'), 'IdentityChanged');
  assert.equal(m.mutationsAllowed, false);
});

test('incompatible / unsupported server become terminal states', () => {
  const m = new ConnectionStateMachine({ initialState: 'Initializing' });
  assert.equal(m.handle('INCOMPATIBLE'), 'UpdateRequired');
  const m2 = new ConnectionStateMachine({ initialState: 'Initializing' });
  assert.equal(m2.handle('UNSUPPORTED_SERVER'), 'UnsupportedServer');
});

test('every connection state is in the frozen vocabulary', () => {
  for (const state of CONNECTION_STATES) {
    assert.equal(typeof state, 'string');
  }
  assert.ok(CONNECTION_STATES.includes('Initializing'));
  assert.ok(CONNECTION_STATES.includes('Connected'));
  assert.ok(CONNECTION_STATES.includes('Offline'));
  assert.ok(CONNECTION_STATES.includes('IdentityChanged'));
});

test('unknown states and events throw', () => {
  assert.throws(() => new ConnectionStateMachine({ initialState: 'ready' }), /unknown connection state/);
  const m = new ConnectionStateMachine();
  assert.throws(() => m.handle('NOPE'), /unknown connection event/);
});

// ---- §21.9 storage namespace ------------------------------------------
test('area preference is isolated per runtime/server', () => {
  const localKey = currentAreaKey(runtimeNamespaceKey('desktop-local'));
  const serverA = currentAreaKey(runtimeNamespaceKey('desktop-remote', 'server-A'));
  const serverB = currentAreaKey(runtimeNamespaceKey('desktop-remote', 'server-B'));
  assert.notEqual(localKey, serverA);
  assert.notEqual(serverA, serverB);
  assert.ok(localKey.startsWith('interest-growth.desktop-local:local.current-area'));
  assert.ok(serverA.startsWith('interest-growth.desktop-remote:server-A.current-area'));
});

test('desktop-local never leaks into another instance namespace', () => {
  const a = uiCacheKey(runtimeNamespaceKey('desktop-local'), 'current-area');
  const b = uiCacheKey(runtimeNamespaceKey('desktop-remote', 'server-A'), 'current-area');
  assert.notEqual(a, b);
});

test('runtimeNamespaceKey requires an instance for remote runtimes', () => {
  assert.throws(() => runtimeNamespaceKey('desktop-remote'), /requires a server instance id/);
  assert.throws(() => runtimeNamespaceKey('garbage'), /unknown runtimeId/);
});

// ---- §21.8 credential store -------------------------------------------
test('credential namespaces isolate server and device', () => {
  const a1 = credentialNamespace('server-A', 'device-1');
  const a2 = credentialNamespace('server-A', 'device-2');
  const b1 = credentialNamespace('server-B', 'device-1');
  assert.notEqual(a1, a2);
  assert.notEqual(a1, b1);
  assert.equal(a1, 'server-A:device-1');
  assert.throws(() => credentialNamespace('', 'device-1'), /requires server_instance_id/);
});

test('memory credential store isolates namespaces and supports delete', async () => {
  const store = new MemoryCredentialStore();
  const record = enrolledServerIdentity({
    normalizedOrigin: 'https://ig.example.com',
    serverInstanceId: 'server-A',
    serverDisplayName: 'IG Server',
    product: API_PRODUCT,
    apiVersion: SUPPORTED_API_VERSION,
    serverVersion: '0.7.0',
    lastVerifiedAt: '2026-08-13T00:00:00Z',
  });
  await store.save('server-A:device-1', record);
  await store.save('server-B:device-1', record);
  assert.equal(store.size, 2);
  assert.equal((await store.read('server-A:device-1')).serverInstanceId, 'server-A');
  assert.equal(await store.read('server-A:device-2'), null); // device namespace isolation
  await store.delete('server-A:device-1');
  assert.equal(await store.read('server-A:device-1'), null);
  assert.notEqual(await store.read('server-B:device-1'), null); // unaffected by A delete
});

test('enrolled identity records never carry secrets', () => {
  const record = enrolledServerIdentity({
    normalizedOrigin: 'https://ig.example.com',
    serverInstanceId: 's',
    serverDisplayName: 'd',
    product: 'interest-growth',
    apiVersion: 1,
    serverVersion: '0.7.0',
    lastVerifiedAt: 't',
  });
  const keys = Object.keys(record);
  for (const forbidden of ['password', 'refreshToken', 'accessToken', 'token']) {
    assert.ok(!keys.includes(forbidden), `must not contain ${forbidden}`);
  }
});

test('CredentialStore base class requires implementation', async () => {
  const base = new CredentialStore();
  await assert.rejects(base.save('n', {}), /must be implemented/);
});

// ---- §21.5 / §10 retry safety contract -------------------------------
test('idempotent methods may retry on transient failure', () => {
  const p = new RetryPolicy();
  for (const m of ['GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE']) {
    assert.equal(isIdempotentMethod(m), true);
    assert.equal(p.canRetry(m, { isTransient: true }), true);
  }
});

test('POST never auto-retries on ambiguous network failure', () => {
  const p = new RetryPolicy();
  assert.equal(p.canRetry('POST', { isTransient: true }), false);
  assert.equal(p.allowedRetries('POST'), 0);
  assert.equal(isIdempotentMethod('POST'), false);
});

test('POST may retry once after a successful 401 refresh', () => {
  const p = new RetryPolicy();
  assert.equal(p.canRetry('POST', { isTransient: true, afterRefresh: true }), true);
  assert.equal(p.allowedRetries('POST', { afterRefresh: true }), 1);
});

test('retry is bounded and non-transient errors never retry', () => {
  const p = new RetryPolicy({ maxRetries: 2 });
  assert.equal(p.allowedRetries('GET'), 2);
  assert.equal(p.canRetry('GET', { isTransient: false }), false);
  assert.equal(p.canRetry('POST', { isTransient: false, afterRefresh: true }), false);
});

test('refresh failure is terminal and never recurses', () => {
  const m = new ConnectionStateMachine({ initialState: 'Connected' });
  assert.equal(m.handle('REFRESH_FAIL'), 'LoginExpired');
  assert.equal(m.mutationsAllowed, false);
  // A second REFRESH_FAIL cannot recurse into another refresh cycle.
  assert.equal(m.handle('REFRESH_FAIL'), 'LoginExpired');
});

// ---- Gate D §D4 remote transport -------------------------------------
test('remote transport stays inert without a native broker', () => {
  const transport = new RemoteTransport({ broker: null, active: true });
  assert.equal(transport.active, false);
  assert.deepEqual(transport.authHeader, {});
  return assert.rejects(transport.request('/api/system/capabilities'), /not active/);
});

test('remote transport activates only with a native broker', () => {
  const broker = { apiRequest: async () => ({ status: 200, bodyBase64: '', contentType: '' }) };
  const on = new RemoteTransport({ broker, active: true });
  assert.equal(on.active, true);
  const off = new RemoteTransport({ broker, active: false });
  assert.equal(off.active, false);
});

test('remote transport rejects absolute, protocol-relative and non-path inputs', async () => {
  const broker = { apiRequest: async () => ({ status: 200, bodyBase64: '', contentType: '' }) };
  const transport = new RemoteTransport({ broker, active: true });
  await assert.rejects(transport.request('https://evil.example.com/api/x'), /absolute URLs/);
  await assert.rejects(transport.request('//evil.example.com/x'), /protocol-relative/);
  await assert.rejects(transport.request('api/x'), /relative API paths/);
  await assert.rejects(transport.request('/\\evil.example.com/x'), /backslash/);
});

test('remote transport sends a relative path to the broker and returns a Response', async () => {
  const calls = [];
  const broker = {
    apiRequest: async (path, opts) => {
      calls.push({ path, opts });
      return { status: 201, bodyBase64: Buffer.from('{"ok":true}').toString('base64'), contentType: 'application/json' };
    },
  };
  const transport = new RemoteTransport({ broker, active: true });
  const response = await transport.request('/api/questions', {
    method: 'POST',
    body: JSON.stringify({ q: 'x' }),
    headers: { 'Content-Type': 'application/json', 'X-PG-Interest-Area': 'a1' },
  });
  assert.equal(response.status, 201);
  const data = await response.json();
  assert.deepEqual(data, { ok: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/questions');
  assert.equal(calls[0].opts.method, 'POST');
  // Authorization may never be supplied by the renderer to the native broker.
  assert.equal(calls[0].opts.headers.Authorization, undefined);
  assert.equal(calls[0].opts.headers['X-PG-Interest-Area'], 'a1');
});

test('remote transport uploads a file via the native broker with base64 bytes', async () => {
  const calls = [];
  const broker = {
    apiUpload: async (path, opts) => {
      calls.push({ path, opts });
      return { status: 200, bodyBase64: Buffer.from('{"ingestion_run_id":"r1"}').toString('base64'), contentType: 'application/json' };
    },
  };
  const transport = new RemoteTransport({ broker, active: true });
  const form = new FormData();
  form.append('file', new File(['hello remote'], 'note.txt', { type: 'text/plain' }));
  form.append('topic_id', 't1');
  const response = await transport.request('/api/knowledge/sources/upload', {
    method: 'POST',
    body: form,
  });
  const data = await response.json();
  assert.equal(data.ingestion_run_id, 'r1');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/knowledge/sources/upload');
  assert.equal(calls[0].opts.fileName, 'note.txt');
  assert.equal(calls[0].opts.fileContentType, 'text/plain');
  assert.equal(calls[0].opts.fileBytesB64, Buffer.from('hello remote').toString('base64'));
  assert.deepEqual(calls[0].opts.fields, { topic_id: 't1' });
});

// ---- Gate D §P12 transport-driven connection state --------------------
test('remote transport blocks mutations fail-closed in terminal states', async () => {
  const calls = [];
  const broker = {
    apiRequest: async (path, opts) => {
      calls.push(path);
      return { status: 200, bodyBase64: '', contentType: '' };
    },
  };
  const m = new ConnectionStateMachine({ initialState: 'Connected' });
  m.handle('REFRESH_FAIL'); // -> LoginExpired (terminal)
  const transport = new RemoteTransport({ broker, active: true, connection: m });
  await assert.rejects(
    transport.request('/api/questions', { method: 'POST', body: '{}' }),
    /mutations are blocked/,
  );
  // Uploads are mutations too and must be blocked before reaching the broker.
  const form = new FormData();
  form.append('file', new File(['x'], 'x.txt'));
  await assert.rejects(
    transport.request('/api/knowledge/sources', { method: 'POST', body: form }),
    /mutations are blocked/,
  );
  // Reads remain allowed in terminal states (no mutation occurs).
  const response = await transport.request('/api/system/capabilities', { method: 'GET' });
  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
});

test('identity-changed blocks mutations even while reads still work', async () => {
  const broker = {
    apiRequest: async () => ({ status: 200, bodyBase64: '', contentType: '' }),
  };
  const m = new ConnectionStateMachine({ initialState: 'Connected' });
  m.handle('IDENTITY_MISMATCH'); // -> IdentityChanged (terminal)
  const transport = new RemoteTransport({ broker, active: true, connection: m });
  await assert.rejects(transport.request('/api/questions', { method: 'DELETE' }), /mutations are blocked/);
  assert.equal(transport.connection.state, 'IdentityChanged'); // never auto-flips
});

test('remote transport records real outcomes into the state machine', async () => {
  // A network failure moves Connected -> Reconnecting; a later success heals it.
  let fail = true;
  const broker = {
    apiRequest: async () => {
      if (fail) throw new Error('connection reset by peer');
      return { status: 200, bodyBase64: '', contentType: '' };
    },
  };
  const m = new ConnectionStateMachine({ initialState: 'Connected' });
  const transport = new RemoteTransport({ broker, active: true, connection: m });
  await assert.rejects(transport.request('/api/system/capabilities'), /connection reset/);
  assert.equal(m.state, 'Reconnecting');
  fail = false;
  await transport.request('/api/system/capabilities');
  assert.equal(m.state, 'Connected');
});

test('remote transport maps a final 401 to LoginExpired (single-flight already tried)', async () => {
  const broker = {
    apiRequest: async () => ({ status: 401, bodyBase64: '', contentType: '' }),
  };
  const m = new ConnectionStateMachine({ initialState: 'Connected' });
  const transport = new RemoteTransport({ broker, active: true, connection: m });
  await transport.request('/api/notes');
  assert.equal(m.state, 'LoginExpired');
  assert.equal(m.mutationsAllowed, false);
});

// ---- Gate D §P15 positive header allowlist ----------------------------
test('remote transport strips dangerous renderer headers via positive allowlist', async () => {
  const calls = [];
  const broker = {
    apiRequest: async (path, opts) => {
      calls.push(opts.headers);
      return { status: 200, bodyBase64: '', contentType: '' };
    },
  };
  const transport = new RemoteTransport({ broker, active: true });
  await transport.request('/api/notes', {
    headers: {
      'X-PG-Interest-Area': 'a1',
      Accept: 'application/json',
      Authorization: 'Bearer stolen',
      Cookie: 'session=evil',
      Host: 'evil.example.com',
      'X-Forwarded-For': '1.2.3.4',
      'Content-Type': 'application/xml',
      'If-None-Match': '"v1"',
      'X-Custom-Junk': 'nope',
    },
  });
  const sent = calls[0];
  assert.deepEqual(Object.keys(sent).sort(), ['Accept', 'If-None-Match', 'X-PG-Interest-Area']);
  assert.equal(sent['X-PG-Interest-Area'], 'a1');
  assert.equal(sent.Authorization, undefined);
  assert.equal(sent.Cookie, undefined);
  assert.equal(sent.Host, undefined);
  assert.equal(sent['X-Forwarded-For'], undefined);
  assert.equal(sent['Content-Type'], undefined);
  assert.equal(sent['X-Custom-Junk'], undefined);
});

// ---- Gate D §P17 client-side upload bound -----------------------------
test('remote transport rejects oversized uploads before touching the broker', async () => {
  let calls = 0;
  const broker = {
    apiUpload: async () => {
      calls += 1;
      return { status: 200, bodyBase64: '', contentType: '' };
    },
  };
  const transport = new RemoteTransport({ broker, active: true });
  const overLimit = new Uint8Array(100 * 1024 * 1024 + 1);
  const form = new FormData();
  // Blob size is enforced client-side without allocating an extra ArrayBuffer.
  form.append('file', new Blob([overLimit.buffer], { type: 'application/pdf' }));
  await assert.rejects(transport.request('/api/knowledge/sources', { method: 'POST', body: form }), /upload limit/);
  assert.equal(calls, 0);
});

test('remote transport accepts an in-limit upload and bounds the encoded copy', async () => {
  const calls = [];
  const broker = {
    apiUpload: async (path, opts) => {
      calls.push(opts);
      return { status: 200, bodyBase64: '', contentType: '' };
    },
  };
  const transport = new RemoteTransport({ broker, active: true });
  const form = new FormData();
  form.append('file', new File([new Uint8Array(1024)], 'medium.pdf', { type: 'application/pdf' }));
  await transport.request('/api/knowledge/sources', { method: 'POST', body: form });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].fileName, 'medium.pdf');
});

// ---- Gate D §P30/P31 connection state is a single, recoverable source ----

test('Offline is recoverable: a later success flips it back to Connected', () => {
  const m = new ConnectionStateMachine({ initialState: 'Connected', maxReconnectAttempts: 1 });
  assert.equal(m.handle('NETWORK_FAIL'), 'Reconnecting');
  assert.equal(m.handle('NETWORK_FAIL'), 'Offline'); // bounded retry rest
  assert.equal(m.isTerminal, false); // Offline is NOT terminal
  assert.equal(m.mutationsAllowed, false); // but never mutates
  // The whole point of the MEDIUM-4 fix: a success recovers Offline.
  assert.equal(m.handle('RECONNECT_OK'), 'Connected');
  assert.equal(m.isConnected, true);
  assert.equal(m.mutationsAllowed, true);
  const m2 = new ConnectionStateMachine({ initialState: 'Offline' });
  assert.equal(m2.handle('BOOTSTRAP_OK'), 'Connected');
});

test('machine exposes subscribe(): listeners see every transition', () => {
  const m = new ConnectionStateMachine({ initialState: 'Initializing' });
  const seen = [];
  const unsubscribe = m.subscribe((next) => seen.push(next));
  m.handle('BOOTSTRAP_OK');
  m.handle('NETWORK_FAIL');
  assert.deepEqual(seen, ['Connected', 'Reconnecting']);
  unsubscribe();
  m.handle('RECONNECT_OK');
  assert.deepEqual(seen, ['Connected', 'Reconnecting']); // no more notifications
  assert.throws(() => m.subscribe('not-a-function'), /listener function/);
  // A throwing listener never breaks the machine.
  m.subscribe(() => { throw new Error('boom'); });
  assert.equal(m.handle('RESET'), 'Initializing');
});

// ---- Gate D §P32 (MEDIUM) response headers reach the renderer -----------

test('remote transport surfaces the native response metadata allowlist', async () => {
  const broker = {
    apiRequest: async () => ({
      status: 200,
      bodyBase64: Buffer.from('{}').toString('base64'),
      contentType: 'application/json',
      responseHeaders: { etag: '"v1"', 'last-modified': 'Thu, 14 Aug 2026 00:00:00 GMT' },
    }),
  };
  const transport = new RemoteTransport({ broker, active: true });
  const response = await transport.request('/api/system/capabilities');
  assert.equal(response.headers.get('etag'), '"v1"');
  assert.equal(response.headers.get('last-modified'), 'Thu, 14 Aug 2026 00:00:00 GMT');
  assert.equal(response.headers.get('content-type'), 'application/json');
});

// ---- Gate D §P26 (P11) stable error-code taxonomy -----------------------

test('coded native errors parse into the frozen taxonomy', () => {
  assert.equal(parseRemoteErrorCode('{"code":"LOGIN_EXPIRED","message":"x"}'), 'LOGIN_EXPIRED');
  assert.equal(parseRemoteErrorCode(new Error('{"code":"NETWORK_UNAVAILABLE","message":"x"}')), 'NETWORK_UNAVAILABLE');
  assert.equal(parseRemoteErrorCode('{"message":"no code here"}'), null);
  assert.equal(parseRemoteErrorCode('plain transport error'), null);
  assert.equal(parseRemoteErrorCode(undefined), null);
});

test('remote error events: server verdicts become their honest states', () => {
  assert.equal(remoteErrorEvent('{"code":"LOGIN_EXPIRED","message":"x"}'), 'REFRESH_FAIL');
  assert.equal(remoteErrorEvent('{"code":"IDENTITY_CHANGED","message":"x"}'), 'IDENTITY_MISMATCH');
  assert.equal(remoteErrorEvent('{"code":"UPDATE_REQUIRED","message":"x"}'), 'INCOMPATIBLE');
  assert.equal(remoteErrorEvent('{"code":"UNSUPPORTED_SERVER","message":"x"}'), 'UNSUPPORTED_SERVER');
  assert.equal(remoteErrorEvent('{"code":"PROTOCOL_ERROR","message":"x"}'), 'UNSUPPORTED_SERVER');
  assert.equal(remoteErrorEvent('{"code":"NETWORK_UNAVAILABLE","message":"x"}'), 'NETWORK_FAIL');
  // Gate C/D §4.1 — rate-limit and 5xx are transient, never LoginExpired.
  assert.equal(remoteErrorEvent('{"code":"RATE_LIMITED","message":"busy"}'), 'NETWORK_FAIL');
  assert.equal(remoteErrorEvent('{"code":"SERVER_UNAVAILABLE","message":"busy"}'), 'NETWORK_FAIL');
  // Ambiguous / unknown / non-coded failures are NEVER terminal verdicts.
  assert.equal(remoteErrorEvent('{"code":"NONSENSE","message":"x"}'), 'NETWORK_FAIL');
  assert.equal(remoteErrorEvent('connection reset by peer'), 'NETWORK_FAIL');
  assert.equal(REMOTE_ERROR_CODES.CREDENTIAL_PERSISTENCE_FAILURE, 'CREDENTIAL_PERSISTENCE_FAILURE');
  assert.equal(REMOTE_ERROR_CODES.RATE_LIMITED, 'RATE_LIMITED');
  assert.equal(REMOTE_ERROR_CODES.SERVER_UNAVAILABLE, 'SERVER_UNAVAILABLE');
});

test('transport records coded verdicts into the machine (single source)', async () => {
  const m = new ConnectionStateMachine({ initialState: 'Connected' });
  const broker = { apiRequest: async () => { throw new Error('{"code":"LOGIN_EXPIRED","message":"denied"}'); } };
  const transport = new RemoteTransport({ broker, active: true, connection: m });
  await assert.rejects(transport.request('/api/notes'), /denied/);
  assert.equal(m.state, 'LoginExpired'); // server verdict, not a guess

  const m2 = new ConnectionStateMachine({ initialState: 'Connected' });
  const broker2 = { apiRequest: async () => { throw new Error('{"code":"NETWORK_UNAVAILABLE","message":"offline"}'); } };
  const transport2 = new RemoteTransport({ broker: broker2, active: true, connection: m2 });
  await assert.rejects(transport2.request('/api/notes'), /offline/);
  assert.equal(m2.state, 'Reconnecting'); // transport failure stays recoverable
});

test('identity-changed verdict blocks mutations through the transport', async () => {
  const broker = { apiRequest: async () => { throw new Error('{"code":"IDENTITY_CHANGED","message":"replaced"}'); } };
  const m = new ConnectionStateMachine({ initialState: 'Connected' });
  const transport = new RemoteTransport({ broker, active: true, connection: m });
  await assert.rejects(transport.request('/api/notes'), /replaced/);
  assert.equal(m.state, 'IdentityChanged');
  await assert.rejects(transport.request('/api/notes', { method: 'POST', body: '{}' }), /mutations are blocked/);
});
