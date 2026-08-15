// Gate C §4.4 — runtime descriptors are the single source of truth for what
// a runtime can do. `platform` is injected so these remain pure functions
// (unit-testable without a DOM / Tauri shell) and so `isTauri()` never
// decides runtime identity.
import { DATA_LOCATIONS, RUNTIME_IDS } from './contract.js';

const NATIVE_DESKTOP = new Set(['windows', 'macos']);

function nativeCapabilities(platform) {
  const native = NATIVE_DESKTOP.has(platform);
  return {
    canLaunchSidecar: false,
    canUseDesktopToken: false,
    canUseNativeSecureStore: native,
    canUseSaveDialog: true,
    canUseNativeFs: true,
    canOpenExternalUrl: true,
    canCheckDesktopUpdater: native,
    canAdminLocalProviderSecret: false,
    supportsWindowControls: native,
    // Mobile-only surfaces (planned Gate E adapters) are not desktop surfaces.
    canUseDocumentPicker: false,
    canUseShareSheet: false,
    supportsLifecycleSuspendResume: false,
    canUseBiometricUnlock: false,
  };
}

// Gate E — mobile adaptation contract. Android reuses the remote server
// surface (no sidecar, no desktop token, no local vaults, no desktop updater,
// no window chrome) and adds mobile-specific adapters. `canUseNativeSecureStore`
// is true because the frozen contract (§2) assigns the renewal credential to
// Android Keystore.
//
// Gate R0.4 — the SAF document picker is REAL in v0.7 (selectDocument /
// uploadByUri / downloadArtifact), so `canUseDocumentPicker` is true. The
// suspend/resume lifecycle adapter is also real (onSuspendResume re-evaluates
// the session on foreground return), so `supportsLifecycleSuspendResume` is
// true. The remaining mobile adapters (share sheet, biometric unlock) stay
// PLANNED and false, so the UI never enables a feature that does not exist.
function mobileCapabilities() {
  return {
    canLaunchSidecar: false,
    canUseDesktopToken: false,
    canUseNativeSecureStore: true, // Android Keystore (frozen contract §2); adapter planned in Gate E
    canUseSaveDialog: false, // Android uses the system document picker/share sheet
    canUseNativeFs: false, // no local canonical vaults on Android
    canOpenExternalUrl: true, // system browser
    canCheckDesktopUpdater: false,
    canAdminLocalProviderSecret: false,
    supportsWindowControls: false,
    canUseDocumentPicker: true, // Gate R0.4 — SAF document picker implemented
    canUseShareSheet: false, // planned; not available in v0.7
    supportsLifecycleSuspendResume: true, // Gate R0.4 — onSuspendResume implemented
    canUseBiometricUnlock: false, // planned; not available in v0.7
  };
}

function assertPlatform(platform) {
  if (!['windows', 'macos', 'android', 'browser', 'development'].includes(platform)) {
    throw new Error(`unknown platform: ${platform}`);
  }
}

export function desktopLocalDescriptor(platform = 'browser') {
  assertPlatform(platform);
  const native = NATIVE_DESKTOP.has(platform);
  return {
    runtimeId: 'desktop-local',
    platform,
    dataLocation: 'local-device',
    server: { displayName: 'This device' },
    transport: 'loopback',
    auth: { mode: 'desktop-token' },
    connection: { state: 'Initializing' },
    capabilities: {
      ...nativeCapabilities(platform),
      canLaunchSidecar: true,
      canUseDesktopToken: true,
      canAdminLocalProviderSecret: true,
    },
    storageNamespace: 'desktop-local:local',
  };
}

export function desktopRemoteDescriptor(platform = 'browser') {
  assertPlatform(platform);
  const native = NATIVE_DESKTOP.has(platform);
  return {
    runtimeId: 'desktop-remote',
    platform,
    dataLocation: 'self-hosted-server',
    // Bound to a verified server after enrollment (Gate D). Never blanked by
    // a silent fallback to a local store.
    server: null,
    transport: 'native-http',
    auth: { mode: 'single-owner-devices' },
    connection: { state: 'Initializing' },
    capabilities: nativeCapabilities(platform),
    storageNamespace: null,
  };
}

export function androidRemoteDescriptor(platform = 'android') {
  assertPlatform(platform);
  return {
    runtimeId: 'android-remote',
    platform,
    dataLocation: 'self-hosted-server',
    server: null,
    transport: 'native-http',
    auth: { mode: 'single-owner-devices' },
    connection: { state: 'Initializing' },
    capabilities: mobileCapabilities(),
    storageNamespace: null,
  };
}

export function browserRemoteDescriptor(platform = 'browser') {
  assertPlatform(platform);
  return {
    runtimeId: 'browser-remote',
    platform,
    dataLocation: 'self-hosted-server',
    server: null,
    // Planned only. Secure-cookie auth + CSRF is a separate implementation
    // requirement; this transport is intentionally not release-proven.
    transport: 'browser-http',
    auth: { mode: 'secure-cookie-planned' },
    connection: { state: 'Initializing' },
    capabilities: {
      ...nativeCapabilities(platform),
      canUseNativeSecureStore: false,
      canUseSaveDialog: false,
      canUseNativeFs: false,
      canCheckDesktopUpdater: false,
      supportsWindowControls: false,
    },
    storageNamespace: null,
  };
}

const DESCRIPTORS = {
  'desktop-local': desktopLocalDescriptor,
  'desktop-remote': desktopRemoteDescriptor,
  'android-remote': androidRemoteDescriptor,
  'browser-remote': browserRemoteDescriptor,
};

export function descriptorFor(runtimeId, platform = 'browser') {
  const builder = DESCRIPTORS[runtimeId];
  if (!builder) throw new Error(`unknown runtimeId: ${runtimeId}`);
  return builder(platform);
}

export function isKnownRuntimeId(runtimeId) {
  return RUNTIME_IDS.includes(runtimeId);
}

export function isLocalDeviceDataLocation(location) {
  return location === DATA_LOCATIONS[0];
}
