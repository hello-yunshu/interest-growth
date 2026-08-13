// Gate C §14 — runtime-scoped UI cache namespace.
//
// UI state (current Area, recent session refs, disposable presentation cache)
// must be isolated per runtime/server so switching desktop-local / server A /
// server B never leaks state. Device-level preferences (theme) stay global.
import { isRuntimeId } from './contract.js';

export function runtimeNamespaceKey(runtimeId, instance) {
  if (!isRuntimeId(runtimeId)) throw new Error(`unknown runtimeId: ${runtimeId}`);
  if (runtimeId === 'desktop-local') return 'desktop-local:local';
  if (!instance) throw new Error(`${runtimeId} requires a server instance id for its namespace`);
  return `${runtimeId}:${instance}`;
}

export function uiCacheKey(namespace, key) {
  return `interest-growth.${namespace}.${key}`;
}

export function currentAreaKey(namespace) {
  return uiCacheKey(namespace, 'current-area');
}
