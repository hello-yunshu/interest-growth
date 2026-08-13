import { invoke, isTauri as tauriIsTauri } from '@tauri-apps/api/core';
const WEB_API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000/api';
let runtimePromise = null;

const AREA_STORAGE_KEY = 'interest-growth.current-area';

export function getInterestAreaSelector() {
  if (typeof window === 'undefined') return '';
  return window.localStorage.getItem(AREA_STORAGE_KEY) || '';
}

export function setInterestAreaSelector(value) {
  if (typeof window === 'undefined') return;
  const next = String(value || '').trim();
  if (next) window.localStorage.setItem(AREA_STORAGE_KEY, next);
  else window.localStorage.removeItem(AREA_STORAGE_KEY);
  window.dispatchEvent(new CustomEvent('interest-area-changed', { detail: { area: next } }));
}


function isTauri() {
  return typeof window !== 'undefined' && tauriIsTauri();
}

function normalizeDesktopRuntime(runtime) {
  return {
    apiBase: `${runtime.endpoint}/api`,
    token: runtime.token || '',
    desktop: true,
    ...runtime,
  };
}

async function tauriInvoke(command, args = {}) {
  if (!isTauri()) throw new Error('This action is only available in the desktop app.');
  return invoke(command, args);
}

async function desktopRuntime() {
  if (!isTauri()) return { apiBase: WEB_API_BASE, token: '', desktop: false };
  if (!runtimePromise) {
    runtimePromise = tauriInvoke('desktop_runtime')
      .then(normalizeDesktopRuntime)
      .catch((error) => {
        runtimePromise = null;
        throw error;
      });
  }
  return runtimePromise;
}

async function parse(response) {
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/json')) return await response.json().catch(() => ({}));
  return await response.text().catch(() => '');
}

async function requestHeaders(options = {}, form = false) {
  const runtime = await desktopRuntime();
  return {
    ...(form ? {} : { 'Content-Type': 'application/json' }),
    ...(runtime.token ? { 'X-PG-Desktop-Token': runtime.token } : {}),
    ...(getInterestAreaSelector() ? { 'X-PG-Interest-Area': getInterestAreaSelector() } : {}),
    ...(options.headers || {}),
  };
}

export async function api(path, options = {}) {
  const runtime = await desktopRuntime();
  let response;
  try {
    response = await fetch(`${runtime.apiBase}${path}`, {
      ...options,
      headers: await requestHeaders(options),
      cache: 'no-store',
    });
  } catch (error) {
    throw friendlyApiError(error);
  }
  const data = await parse(response);
  if (!response.ok) {
    const detail = typeof data === 'object' ? data.detail : data;
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail || data);
    throw new Error(message || `HTTP ${response.status}`);
  }
  return data;
}

export function friendlyApiError(error) {
  const raw = String(error?.message || error || '').trim();
  if (/failed to fetch|networkerror|load failed|connection refused|fetch failed/i.test(raw)) {
    const next = new Error('暂时连接不到本地服务。你的内容仍安全保存在设备上，请稍后重试。');
    next.code = 'LOCAL_SERVICE_UNAVAILABLE';
    return next;
  }
  if (/not found/i.test(raw)) return new Error('没有找到这条内容，它可能已被移动或归档。');
  if (/disabled/i.test(raw)) return new Error('这项能力目前没有启用，可以在设置中重新打开。');
  return error instanceof Error ? error : new Error(raw || '刚才没有完成，请再试一次。');
}

export async function apiForm(path, formData, options = {}) {
  const runtime = await desktopRuntime();
  let response;
  try {
    response = await fetch(`${runtime.apiBase}${path}`, {
      ...options,
      method: options.method || 'POST',
      headers: await requestHeaders(options, true),
      body: formData,
      cache: 'no-store',
    });
  } catch (error) {
    throw friendlyApiError(error);
  }
  const data = await parse(response);
  if (!response.ok) {
    const detail = typeof data === 'object' ? data.detail : data;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || data));
  }
  return data;
}

export async function downloadArtifact(artifactId) {
  const runtime = await desktopRuntime();
  const response = await fetch(`${runtime.apiBase}/artifacts/${artifactId}/export`, {
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

  if (runtime.desktop && isTauri()) {
    const [{ save }, { writeFile }] = await Promise.all([
      import('@tauri-apps/plugin-dialog'),
      import('@tauri-apps/plugin-fs'),
    ]);
    const destination = await save({
      title: '导出发布包',
      defaultPath: filename,
      filters: [{ name: 'ZIP Archive', extensions: ['zip'] }],
    });
    if (!destination) return false;
    await writeFile(destination, new Uint8Array(await blob.arrayBuffer()));
    return true;
  }

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return true;
}

export async function wsApiUrl(path) {
  const runtime = await desktopRuntime();
  const base = runtime.apiBase.startsWith('http')
    ? runtime.apiBase.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:')
    : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${runtime.apiBase}`;
  const params = new URLSearchParams();
  if (runtime.token) params.set('token', runtime.token);
  const area = getInterestAreaSelector();
  if (area) params.set('area', area);
  const suffix = params.toString() ? `${path.includes('?') ? '&' : '?'}${params.toString()}` : '';
  return `${base}${path}${suffix}`;
}

export async function getDesktopRuntime() {
  return desktopRuntime();
}

export async function refreshDesktopRuntime() {
  runtimePromise = null;
  return desktopRuntime();
}

export async function getDesktopProviderSettings() {
  if (!isTauri()) return null;
  return tauriInvoke('desktop_provider_settings');
}

export async function setDesktopProviderSettings(settings) {
  return tauriInvoke('set_desktop_provider_settings', { settings });
}

export async function getProviderSecretStatus(kind) {
  if (!isTauri()) return { kind, configured: false, secureStoreAvailable: false };
  return tauriInvoke('provider_secret_status', { kind });
}

export async function setProviderSecret(kind, secret) {
  return tauriInvoke('set_provider_secret', { kind, secret });
}

export async function deleteProviderSecret(kind) {
  return tauriInvoke('delete_provider_secret', { kind });
}

export async function restartDesktopCore() {
  try {
    const runtime = await tauriInvoke('restart_desktop_core');
    const normalized = normalizeDesktopRuntime(runtime);
    runtimePromise = Promise.resolve(normalized);
    return normalized;
  } catch (error) {
    runtimePromise = null;
    throw error;
  }
}

export async function checkDesktopUpdate() {
  return tauriInvoke('check_for_update');
}

export async function installDesktopUpdate() {
  return tauriInvoke('install_available_update');
}

export async function openExternalUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error('Invalid external URL.'); }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Only HTTP/HTTPS external URLs are allowed.');
  if (isTauri()) {
    const { openUrl } = await import('@tauri-apps/plugin-opener');
    await openUrl(url.toString());
    return true;
  }
  window.open(url.toString(), '_blank', 'noopener,noreferrer');
  return true;
}
