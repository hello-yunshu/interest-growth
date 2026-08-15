// Gate C §3/§13 — api.js stays the compatibility facade for feature pages.
//
// Public function names and signatures are preserved so feature pages do not
// need to change. Internals route through the ClientRuntime: desktop-local
// uses the loopback transport with X-PG-Desktop-Token; remote transports are
// primitives only and never active in this build.
import { invoke } from '@tauri-apps/api/core';
import {
  getClientRuntime,
  resetClientRuntime,
} from './runtime/client-runtime.js';
import { currentAreaKey } from './runtime/storage-namespace.js';
import { wsUrlWithLoopbackToken } from './runtime/transports/socket.js';

// The Area selector is a runtime-scoped UI preference (Gate C §14), so it is
// isolated per runtime/server. desktop-local (and web dev) share the local
// namespace; a future remote runtime would scope to its server_instance_id.
let syncNamespace = 'desktop-local:local';
getClientRuntime()
  .then((client) => { syncNamespace = client.storageNamespace; })
  .catch(() => {});

function currentAreaStorageKey() {
  return currentAreaKey(syncNamespace);
}

export function getInterestAreaSelector() {
  if (typeof window === 'undefined') return '';
  return window.localStorage.getItem(currentAreaStorageKey()) || '';
}

export function setInterestAreaSelector(value) {
  if (typeof window === 'undefined') return;
  const next = String(value || '').trim();
  const key = currentAreaStorageKey();
  if (next) window.localStorage.setItem(key, next);
  else window.localStorage.removeItem(key);
  window.dispatchEvent(new CustomEvent('interest-area-changed', { detail: { area: next } }));
}

async function requestHeaders(options = {}, form = false) {
  const client = await getClientRuntime();
  const area = getInterestAreaSelector();
  return {
    ...(form ? {} : { 'Content-Type': 'application/json' }),
    ...client.transport.authHeader,
    ...(area ? { 'X-PG-Interest-Area': area } : {}),
    ...(options.headers || {}),
  };
}

async function parse(response) {
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/json')) return await response.json().catch(() => ({}));
  return await response.text().catch(() => '');
}

export async function api(path, options = {}) {
  const client = await getClientRuntime();
  let response;
  try {
    response = await client.transport.request(path, {
      ...options,
      headers: await requestHeaders(options),
      cache: 'no-store',
    });
  } catch (error) {
    throw friendlyApiError(error, client);
  }
  const data = await parse(response);
  if (!response.ok) {
    const detail = typeof data === 'object' ? data.detail : data;
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail || data);
    throw new Error(message || `HTTP ${response.status}`);
  }
  return data;
}

// Gate C §18 — network failure copy is runtime-aware. A remote runtime never
// claims "content is safe on this device".
export function friendlyApiError(error, client) {
  const raw = String(error?.message || error || '').trim();
  const remote = client?.descriptor?.dataLocation === 'self-hosted-server';
  if (/failed to fetch|networkerror|load failed|connection refused|fetch failed/i.test(raw)) {
    if (remote) {
      const next = new Error('暂时连接不到你的自托管服务器。当前版本不会在离线状态提交修改。');
      next.code = 'REMOTE_SERVICE_UNAVAILABLE';
      return next;
    }
    const next = new Error('暂时连接不到本地服务。你的内容仍安全保存在设备上，请稍后重试。');
    next.code = 'LOCAL_SERVICE_UNAVAILABLE';
    return next;
  }
  if (/not found/i.test(raw)) return new Error('没有找到这条内容，它可能已被移动或归档。');
  if (/disabled/i.test(raw)) return new Error('这项能力目前没有启用，可以在设置中重新打开。');
  return error instanceof Error ? error : new Error(raw || '刚才没有完成，请再试一次。');
}

export async function apiForm(path, formData, options = {}) {
  const client = await getClientRuntime();
  let response;
  try {
    response = await client.transport.request(path, {
      ...options,
      method: options.method || 'POST',
      headers: await requestHeaders(options, true),
      body: formData,
      cache: 'no-store',
    });
  } catch (error) {
    throw friendlyApiError(error, client);
  }
  const data = await parse(response);
  if (!response.ok) {
    const detail = typeof data === 'object' ? data.detail : data;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || data));
  }
  return data;
}

// Gate C §16 — fetching artifact bytes and saving them on the platform are
// separated. The save action always uses the platform adapter.
//
// Gate R0.6 — Android downloads and saves natively (native broker → SAF), so
// the artifact bytes never materialise in the renderer. Other runtimes keep
// the transport blob → saveExport path below.
export async function downloadArtifact(artifactId) {
  const client = await getClientRuntime();
  if (typeof client.adapter.downloadArtifact === 'function') {
    return client.adapter.downloadArtifact(artifactId);
  }
  const response = await client.transport.request(`/artifacts/${artifactId}/export`, {
    headers: await requestHeaders({}, true), cache: 'no-store'
  });
  if (!response.ok) {
    const data = await parse(response);
    const detail = typeof data === 'object' ? data.detail : data;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || data));
  }
  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const filename = match?.[1] || `interest-growth-${artifactId}.zip`;
  return client.adapter.saveExport(blob, filename);
}

// Gate R0.5 — Android source upload. The SAF picker returns only a content URI
// plus metadata; the native broker reads and streams the bytes, so a 100 MiB
// file never becomes a renderer base64 copy. Non-Android runtimes return null
// from pickSourceFile and keep the FormData file-input path (apiForm).
export async function pickSourceFile(mimeType) {
  const client = await getClientRuntime();
  if (typeof client.adapter.selectDocument !== 'function') return null;
  return client.adapter.selectDocument(mimeType);
}

export async function uploadSourceByUri({ path, uri, fileName, fileContentType, fields }) {
  const client = await getClientRuntime();
  if (typeof client.adapter.uploadByUri !== 'function') {
    throw new Error('SAF 上传仅支持 Android 运行时。');
  }
  return client.adapter.uploadByUri({ path, uri, fileName, fileContentType, fields });
}

export async function supportsDocumentPicker() {
  const client = await getClientRuntime();
  return client.descriptor.capabilities.canUseDocumentPicker === true;
}

// Gate C §17 — loopback token may ride in the query for local transport only.
// Remote websockets are not active; a remote bearer/access token is never put
// in a URL query.
export async function wsApiUrl(path) {
  const client = await getClientRuntime();
  if (client.descriptor.runtimeId !== 'desktop-local') {
    throw new Error('远程 WebSocket 通道在当前运行时不可用（仅 desktop-local 提供）。');
  }
  return wsUrlWithLoopbackToken(client.runtime.apiBase, path, {
    token: client.runtime.token || '',
    area: getInterestAreaSelector(),
  });
}

export async function getDesktopRuntime() {
  const client = await getClientRuntime();
  return client.runtime;
}

export async function refreshDesktopRuntime() {
  resetClientRuntime();
  const client = await getClientRuntime();
  return client.runtime;
}

export async function getDesktopProviderSettings() {
  const client = await getClientRuntime();
  return client.adapter.getDesktopProviderSettings();
}

export async function setDesktopProviderSettings(settings) {
  const client = await getClientRuntime();
  return client.adapter.setDesktopProviderSettings(settings);
}

export async function getProviderSecretStatus(kind) {
  const client = await getClientRuntime();
  return client.adapter.getProviderSecretStatus(kind);
}

export async function setProviderSecret(kind, secret) {
  const client = await getClientRuntime();
  return client.adapter.setProviderSecret(kind, secret);
}

export async function deleteProviderSecret(kind) {
  const client = await getClientRuntime();
  return client.adapter.deleteProviderSecret(kind);
}

export async function restartDesktopCore() {
  const { resetDesktopLocalRuntime } = await import('./runtime/transports/desktop-local.js');
  try {
    const runtime = await invoke('restart_desktop_core');
    resetDesktopLocalRuntime();
    const client = await getClientRuntime();
    return { ...client.runtime, ...runtime };
  } catch (error) {
    resetDesktopLocalRuntime();
    throw error;
  }
}

export async function checkDesktopUpdate() {
  const client = await getClientRuntime();
  return client.adapter.checkDesktopUpdate();
}

export async function installDesktopUpdate() {
  const client = await getClientRuntime();
  return client.adapter.installDesktopUpdate();
}

export async function openExternalUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error('Invalid external URL.'); }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Only HTTP/HTTPS external URLs are allowed.');
  const client = await getClientRuntime();
  return client.adapter.openExternal(url.toString());
}

// Gate D §D4/D5 — remote mode facade. These route through the platform adapter
// (native broker) so feature pages never import @tauri-apps/* directly. All
// secret handling stays native: the renderer only ever submits relative paths
// and owner passwords at login; it never receives a refresh credential.
export async function getDesktopRuntimeMode() {
  const client = await getClientRuntime();
  return client.adapter.getDesktopRuntimeMode();
}

export async function setDesktopRuntimeMode(runtimeId) {
  const client = await getClientRuntime();
  return client.adapter.setDesktopRuntimeMode(runtimeId);
}

export async function remoteProbeServer(origin) {
  const client = await getClientRuntime();
  return client.adapter.remoteProbeServer(origin);
}

export async function remoteBootstrapOwner(origin, ownerPassword, bootstrapToken) {
  const client = await getClientRuntime();
  return client.adapter.remoteBootstrapOwner(origin, ownerPassword, bootstrapToken);
}

export async function remoteLogin(options) {
  const client = await getClientRuntime();
  return client.adapter.remoteLogin(options);
}

export async function remoteSessionStatus() {
  const client = await getClientRuntime();
  return client.adapter.remoteSessionStatus();
}

export async function remoteRefreshNow() {
  const client = await getClientRuntime();
  return client.adapter.remoteRefreshNow();
}

export async function remoteVerifyIdentity() {
  const client = await getClientRuntime();
  return client.adapter.remoteVerifyIdentity();
}

export async function remoteLogout(revoke = false) {
  const client = await getClientRuntime();
  resetClientRuntime();
  return client.adapter.remoteLogout(revoke);
}

// Gate D §D5 — explicit restart boundary. A runtime-mode switch is persisted
// as the NEXT profile and only applies after a real app restart, so local and
// remote datasets are never mixed in one session (Gate C §5.3).
export async function restartDesktopApp() {
  const client = await getClientRuntime();
  return client.adapter.restartApp();
}

// Gate D §D5 — remote device management. These route through the active
// transport (the native broker in desktop-remote), so a device can only ever
// be listed or revoked against the server the client is actually enrolled to.
// Revoking another device requires the owner password (server-side rule).
export async function remoteDeviceList() {
  return api('/auth/devices');
}

export async function remoteRevokeDevice(deviceId, ownerPassword) {
  return api('/auth/device/revoke', {
    method: 'POST',
    body: JSON.stringify({ device_id: deviceId, owner_password: ownerPassword || null }),
  });
}
