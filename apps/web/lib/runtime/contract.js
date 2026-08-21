// Gate C §4 — frozen ClientRuntime vocabulary.
//
// These are the ONLY valid runtime identities. A business feature page must
// never branch on "desktop true/false"; it consumes `runtimeId` from the
// resolved ClientRuntime descriptor.
export const RUNTIME_IDS = Object.freeze([
  'desktop-local',
  'desktop-remote',
  'android-remote',
  'browser-remote',
]);

// Platform is orthogonal to runtime (Gate C §4.2): windows/macos/… describe
// the host, never "tauri". runtimeId == desktop-local must never be inferred
// from platform == tauri.
export const PLATFORM_IDS = Object.freeze([
  'windows',
  'macos',
  'android',
  'browser',
  'development',
]);

export const DATA_LOCATIONS = Object.freeze([
  'local-device',
  'self-hosted-server',
]);

// Gate C §9 — explicit connection state vocabulary. Do not reduce this to a
// single "ready/error" boolean.
export const CONNECTION_STATES = Object.freeze([
  'Initializing',
  'Connected',
  'Reconnecting',
  'Offline',
  'LoginExpired',
  'IdentityChanged',
  'UpdateRequired',
  'UnsupportedServer',
  'LocalCoreError',
]);

// Compatibility checker vocabulary (Gate C §8).
export const COMPATIBILITY = Object.freeze([
  'Compatible',
  'WrongProduct',
  'ApiVersionMismatch',
  'UpdateRequired',
  'RuntimeUnsupported',
  'AuthModeUnsupported',
]);

export const API_PRODUCT = 'interest-growth';
export const SUPPORTED_API_VERSION = 1;

// The shipping client package version. The compatibility checker requires an
// explicit version input so a 0.6 client against min_client_version=0.7.0 is
// honestly judged UpdateRequired (Gate C §8.3) rather than bypassed.
export const CLIENT_VERSION = '1.0.5';

// Gate E — frozen capability vocabulary. Every runtime descriptor's
// `capabilities` object uses exactly these keys; feature pages branch on
// these booleans instead of sniffing the platform.
export const PLATFORM_CAPABILITIES = Object.freeze([
  // desktop-local loopback Python Core
  'canLaunchSidecar',
  // desktop-local per-launch process token
  'canUseDesktopToken',
  // OS keyring / Android Keystore for the renewal credential
  'canUseNativeSecureStore',
  // desktop OS save dialog
  'canUseSaveDialog',
  // desktop local Source/Artifact vaults
  'canUseNativeFs',
  // system browser / webview opener for external links
  'canOpenExternalUrl',
  // desktop updater channel
  'canCheckDesktopUpdater',
  // desktop-local provider-secret administration surface
  'canAdminLocalProviderSecret',
  // desktop window chrome controls
  'supportsWindowControls',
  // mobile system document picker (planned Gate E adapter)
  'canUseDocumentPicker',
  // mobile share sheet (planned Gate E adapter)
  'canUseShareSheet',
  // mobile suspend/resume lifecycle contract (planned Gate E)
  'supportsLifecycleSuspendResume',
  // mobile biometric gate for local unlock (planned Gate E, optional)
  'canUseBiometricUnlock',
]);

// Desktop-only gate (Gate E): these capabilities MUST be false on every
// non-desktop runtime so a mobile build cannot silently reach a desktop/local
// path (sidecar, token, vaults, updater, window chrome, provider secrets).
export const DESKTOP_ONLY_CAPABILITIES = Object.freeze([
  'canLaunchSidecar',
  'canUseDesktopToken',
  'canUseSaveDialog',
  'canUseNativeFs',
  'canCheckDesktopUpdater',
  'supportsWindowControls',
  'canAdminLocalProviderSecret',
]);

export function isRuntimeId(value) {
  return RUNTIME_IDS.includes(value);
}

// Gate E / R0.2 — a remote runtime always shares the self-hosted-server data
// location and the native broker transport. Feature pages and controllers
// must use this helper instead of branching on the literal "desktop-remote"
// string, so android-remote (and the planned browser-remote) are never
// misclassified as local.
export function isRemoteRuntime(runtimeId) {
  return runtimeId === 'desktop-remote' || runtimeId === 'android-remote' || runtimeId === 'browser-remote';
}

export function isPlatformId(value) {
  return PLATFORM_IDS.includes(value);
}

export function isDataLocation(value) {
  return DATA_LOCATIONS.includes(value);
}

export function isConnectionState(value) {
  return CONNECTION_STATES.includes(value);
}

export function isCompatibility(value) {
  return COMPATIBILITY.includes(value);
}

export function isPlatformCapability(value) {
  return PLATFORM_CAPABILITIES.includes(value);
}
