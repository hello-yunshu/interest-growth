// Gate E §6.8 — Tauri Android platform adapter.
//
// Feature pages must not import @tauri-apps/* directly; every platform
// difference is centralized here and behind the ClientRuntime capabilities.
// The Android shell is ALWAYS `android-remote` (no sidecar, no desktop token,
// no local vaults), so this adapter only carries the native remote broker
// surface plus the small set of Android host actions that are real this round.
//
// NOT IMPLEMENTED this round (documented, capabilities stay false, UI stays
// disabled): system document picker, share sheet, biometric unlock and the
// suspend/resume lifecycle adapter. The frozen contract declares them as
// supported-by-contract/planned; the descriptor must not claim they exist.
import { invoke } from '@tauri-apps/api/core';

export const PLATFORM_ID = 'tauri-android';

// Native remote broker invocation — identical Tauri commands as the desktop
// adapter, so the renderer only ever submits relative API paths and never
// sees the refresh credential (Gate D §D3/D4 reused for Android).
//
// Gate R0.3 — the Android shell probes for android-remote specifically. It
// must never "coincidentally pass" a server that only advertises
// desktop-remote, and a server that only advertises android-remote must be
// accepted.
export async function remoteProbeServer(origin) {
  return invoke('remote_probe_server', { origin, runtimeId: 'android-remote' });
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

// Open external URLs in the system browser. The mobile capability
// `opener:allow-default-urls` covers https, matching the desktop shell.
export async function openExternal(url) {
  const { openUrl } = await import('@tauri-apps/plugin-opener');
  await openUrl(url);
  return true;
}

// ---- Planned Android adapters (NOT IMPLEMENTED this round) ----
// Each returns an explicit not-implemented result instead of pretending to
// work. The corresponding capability keys stay `false` and the UI keeps the
// surface disabled, so no Android path claims a document picker / share sheet
// / lifecycle hook that does not exist in v0.7.

function notImplemented(name) {
  return async () => {
    throw new Error(`${name} is NOT IMPLEMENTED in v0.7 Android (planned adapter)`);
  };
}

// System document picker / SAF selection (planned Gate E).
export const selectDocument = notImplemented('selectDocument');
// Upload by content URI / SAF stream (planned Gate E; today uploads go through
// the bounded base64 native broker path).
export const uploadByUri = notImplemented('uploadByUri');
// Android share sheet (planned Gate E).
export const shareText = notImplemented('shareText');
export const shareFile = notImplemented('shareFile');
// Android Back handling (planned adapter; today the OS back-navigation falls
// back to the WebView history).
export const handleBack = notImplemented('handleBack');
// Suspend/resume lifecycle notifications (planned Gate E; the remote session
// is recovered from Android Keystore on resume by the native host).
export const onSuspendResume = notImplemented('onSuspendResume');
// Biometric unlock gate (planned Gate E, optional).
export const requestBiometricUnlock = notImplemented('requestBiometricUnlock');
