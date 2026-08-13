// Gate C §15/§16 — Tauri desktop platform adapter.
//
// Feature pages must not import @tauri-apps/* directly (except genuinely
// platform-level components). All desktop/browser differences are centralized
// here and behind the ClientRuntime capabilities.
import { invoke } from '@tauri-apps/api/core';

export const PLATFORM_ID = 'tauri-desktop';

export async function saveExport(blob, filename) {
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

export async function openExternal(url) {
  const { openUrl } = await import('@tauri-apps/plugin-opener');
  await openUrl(url);
  return true;
}

export async function windowControls() {
  const { getCurrentWindow } = await import('@tauri-apps/api/window');
  return getCurrentWindow();
}

export async function checkDesktopUpdate() {
  return invoke('check_for_update');
}

export async function installDesktopUpdate() {
  return invoke('install_available_update');
}

export async function getProviderSecretStatus(kind) {
  return invoke('provider_secret_status', { kind });
}

export async function setProviderSecret(kind, secret) {
  return invoke('set_provider_secret', { kind, secret });
}

export async function deleteProviderSecret(kind) {
  return invoke('delete_provider_secret', { kind });
}

export async function getDesktopProviderSettings() {
  return invoke('desktop_provider_settings');
}

export async function setDesktopProviderSettings(settings) {
  return invoke('set_desktop_provider_settings', { settings });
}

// Gate C §5.2 — runtime mode. The mode switch persists the NEXT profile and
// only applies after an explicit restart (session immutable).
export async function getDesktopRuntimeMode() {
  return invoke('desktop_runtime_mode');
}

export async function setDesktopRuntimeMode(runtimeId) {
  return invoke('set_desktop_runtime_mode', { runtimeId });
}

// Gate D §D5 — explicit restart boundary. The mode switch persists the NEXT
// profile; a real app restart is what applies it (session immutable).
export async function restartApp() {
  return invoke('restart_app');
}

// Gate D §D3/D4 — native remote credential broker + HTTP transport. These
// wrap the Rust commands; the renderer only ever submits relative API paths.
export async function remoteProbeServer(origin) {
  return invoke('remote_probe_server', { origin });
}

export async function remoteBootstrapOwner(origin, ownerPassword, bootstrapToken) {
  return invoke('remote_bootstrap_owner', { origin, ownerPassword, bootstrapToken });
}

export async function remoteLogin({
  origin,
  ownerPassword,
  deviceName,
  platform,
  appVersion,
  expectedServerInstanceId,
}) {
  return invoke('remote_login', {
    origin,
    ownerPassword,
    deviceName,
    platform,
    appVersion,
    expectedServerInstanceId,
  });
}

export async function remoteApiRequest(path, { method, body, contentType, headers } = {}) {
  return invoke('remote_api_request', { path, method, body, contentType, headers });
}

export async function remoteApiUpload(path, {
  fileField,
  fileName,
  fileBytesB64,
  fileContentType,
  fields,
} = {}) {
  return invoke('remote_api_upload', {
    path,
    fileField,
    fileName,
    fileBytesB64,
    fileContentType,
    fields,
  });
}

export async function remoteSessionStatus() {
  return invoke('remote_session_status');
}

export async function remoteRefreshNow() {
  return invoke('remote_refresh_now');
}

export async function remoteVerifyIdentity() {
  return invoke('remote_verify_identity');
}

export async function remoteLogout(revoke) {
  return invoke('remote_logout', { revoke });
}
