// Gate C §15/§16 — browser platform adapter.
//
// Browser-only implementations of the platform surface. Feature pages use
// this via the ClientRuntime, never by importing @tauri-apps/*.
export const PLATFORM_ID = 'browser';

export async function saveExport(blob, filename) {
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

export async function openExternal(url) {
  window.open(url, '_blank', 'noopener,noreferrer');
  return true;
}

export async function windowControls() {
  return null;
}

export async function checkDesktopUpdate() {
  throw new Error('desktop update check is not available in the browser');
}

export async function installDesktopUpdate() {
  throw new Error('desktop update install is not available in the browser');
}

export async function getProviderSecretStatus(kind) {
  return { kind, configured: false, secureStoreAvailable: false };
}

export async function setProviderSecret(_kind, _secret) {
  throw new Error('native secure store is not available in the browser');
}

export async function deleteProviderSecret(_kind) {
  throw new Error('native secure store is not available in the browser');
}

export async function getDesktopProviderSettings() {
  return null;
}

export async function setDesktopProviderSettings(_settings) {
  throw new Error('local provider settings are only available in the desktop app');
}

// Gate D facade — these are desktop-only in v0.7. The browser shell cannot
// enroll a self-hosted server or hold a native keyring credential; browser
// remote remains a planned (secure-cookie) runtime, so every path stays inert.
export async function getDesktopRuntimeMode() {
  return { runtimeId: 'desktop-local', sidecarLaunch: false, sessionImmutable: true };
}

export async function setDesktopRuntimeMode(_runtimeId) {
  throw new Error('runtime mode switching is only available in the desktop app');
}

export async function restartApp() {
  throw new Error('app restart is only available in the desktop app');
}

export async function remoteProbeServer(_origin) {
  throw new Error('server enrollment is only available in the desktop app');
}

export async function remoteBootstrapOwner() {
  throw new Error('server enrollment is only available in the desktop app');
}

export async function remoteLogin() {
  throw new Error('server login is only available in the desktop app');
}

export async function remoteApiRequest() {
  throw new Error('remote transport is not active in this build');
}

export async function remoteApiUpload() {
  throw new Error('remote transport is not active in this build');
}

export async function remoteSessionStatus() {
  return { enrolled: false, connected: false, authExpired: false };
}

export async function remoteRefreshNow() {
  throw new Error('remote transport is not active in this build');
}

export async function remoteVerifyIdentity() {
  throw new Error('remote transport is not active in this build');
}

export async function remoteLogout() {
  return { loggedOut: true, revoked: false };
}
