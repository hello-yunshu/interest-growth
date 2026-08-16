// Gate E §6.8 — Tauri Android platform adapter.
//
// Feature pages must not import @tauri-apps/* directly; every platform
// difference is centralized here and behind the ClientRuntime capabilities.
// The Android shell is ALWAYS `android-remote` (no sidecar, no desktop token,
// no local vaults), so this adapter only carries the native remote broker
// surface plus the small set of Android host actions that are real this round.
//
// Gate R0.4 — the SAF document picker and native upload/export ARE real now
// (`canUseDocumentPicker` is true). Still NOT IMPLEMENTED (documented,
// capabilities stay false, UI stays disabled): share sheet, biometric unlock
// and the suspend/resume lifecycle adapter. The frozen contract declares them
// as supported-by-contract/planned; the descriptor must not claim they exist.
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

// ---- Gate R0.4/R0.5 — SAF document selection & upload --------------------
// The system document picker (ACTION_OPEN_DOCUMENT) is driven natively; the
// renderer only receives a content URI plus metadata (name/size/MIME) and
// never the file bytes (Gate R0.5). Uploads go through the same native broker
// as every remote mutation, so the transport-level mutation gate applies.

// Select a document through SAF. `mimeType` narrows the picker when provided
// (e.g. "application/pdf"); omit it for any file type.
export async function selectDocument(mimeType) {
  return invoke('remote_pick_document', { mimeType });
}

// Upload by SAF content URI. The native broker reads the bytes through the
// Kotlin plugin and streams the multipart upload, so a 100 MiB file never
// materialises as a renderer base64 copy. The renderer only passes the URI,
// filename, MIME and the extra multipart fields.
export async function uploadByUri({
  path,
  uri,
  fileName,
  fileContentType,
  fields,
} = {}) {
  return invoke('remote_api_upload_by_uri', {
    path,
    uri,
    fileName,
    fileContentType,
    fields,
  });
}

// ---- Gate R0.6 — native export -------------------------------------------
// Artifact bytes are downloaded by the native broker and written through SAF
// (ACTION_CREATE_DOCUMENT); the renderer never materialises the artifact.
// api.js routes `downloadArtifact` here for Android, keeping the desktop /
// browser blob path for the other runtimes.
export async function downloadArtifact(artifactId) {
  return invoke('remote_save_export', { path: `/artifacts/${artifactId}/export` });
}

// `saveExport(blob, filename)` is deliberately not a supported Android path:
// export must go through the native broker + SAF above, never a renderer
// materialised blob. The descriptor keeps `canUseSaveDialog: false`.
export async function saveExport() {
  throw new Error('Android 导出走原生 SAF 通道（downloadArtifact），不支持渲染层 Blob 落盘。');
}

// ---- Planned Android adapters (NOT IMPLEMENTED) --------------------------
// Each returns an explicit not-implemented result instead of pretending to
// work. The corresponding capability keys stay `false` and the UI keeps the
// surface disabled, so no Android path claims a share sheet / lifecycle hook
// / biometric gate that does not exist.

function notImplemented(name) {
  return async () => {
    throw new Error(`${name} is NOT IMPLEMENTED in v0.7 Android (planned adapter)`);
  };
}

// Android share sheet (planned).
export const shareText = notImplemented('shareText');
export const shareFile = notImplemented('shareFile');

// Gate R0.4 §R0.4 — system Back. The native host (MainActivity) enables
// WebView-history Back navigation; this adapter provides the renderer-facing
// hook used by the app to keep modal/history state consistent. It delegates to
// history.back() when the WebView has history, matching the native handler.
export async function handleBack() {
  if (typeof window !== 'undefined' && window.history?.length > 1) {
    window.history.back();
    return true;
  }
  return false;
}

// Gate R0.4 §R0.4 — foreground/background + resume re-evaluation.
//
// `resume != Connected`. When the page returns to the foreground after a
// background/suspend, this notifies the registered callback so the app
// re-evaluates the session through the native broker (refresh/recover) instead
// of blindly flipping to Connected. The callback is invoked on
// `visibilitychange` back to visible, and the returned function unsubscribes.
export function onSuspendResume(callback) {
  if (typeof document === 'undefined' || typeof callback !== 'function') {
    return () => {};
  }
  const handler = () => {
    if (document.visibilityState === 'visible') callback();
  };
  document.addEventListener('visibilitychange', handler);
  return () => document.removeEventListener('visibilitychange', handler);
}

// Biometric unlock gate (planned Gate E, optional).
export const requestBiometricUnlock = notImplemented('requestBiometricUnlock');
