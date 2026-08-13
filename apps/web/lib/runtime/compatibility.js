// Gate C §8 — pure version / compatibility checker.
//
// Inputs mirror the additive server capabilities contract. Output is one of
// the frozen COMPATIBILITY values. remote runtimes additionally require an
// enabled single-owner-devices auth mode.
import { API_PRODUCT, SUPPORTED_API_VERSION, isRuntimeId } from './contract.js';
import { compareVersions } from './semver.js';

const REMOTE_RUNTIMES = new Set(['desktop-remote', 'android-remote', 'browser-remote']);

export function checkCompatibility({
  clientVersion,
  serverProduct = API_PRODUCT,
  apiVersion = SUPPORTED_API_VERSION,
  minClientVersion,
  runtimeId,
  runtimeModes = [],
  authEnabled = false,
  authMode = 'none',
} = {}) {
  if (serverProduct !== API_PRODUCT) return 'WrongProduct';
  if (Number(apiVersion) !== SUPPORTED_API_VERSION) return 'ApiVersionMismatch';
  if (minClientVersion && compareVersions(clientVersion, minClientVersion) < 0) {
    return 'UpdateRequired';
  }
  if (!isRuntimeId(runtimeId) || !runtimeModes.includes(runtimeId)) {
    return 'RuntimeUnsupported';
  }
  if (REMOTE_RUNTIMES.has(runtimeId)) {
    if (!authEnabled || authMode !== 'single_owner_devices') {
      return 'AuthModeUnsupported';
    }
  }
  return 'Compatible';
}
