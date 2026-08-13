// Gate C §4.1 — low-level platform detection ONLY.
//
// This module is the single place that may call `isTauri()`. Feature pages
// and API behavior must NOT import this directly to decide local vs remote;
// they consume the resolved ClientRuntime descriptor instead.
import { isTauri } from '@tauri-apps/api/core';

function userAgentPlatform() {
  if (typeof navigator === 'undefined') return 'development';
  const ua = String(navigator.userAgent || '').toLowerCase();
  if (ua.includes('windows')) return 'windows';
  if (ua.includes('mac os') || ua.includes('macintosh')) return 'macos';
  if (ua.includes('android')) return 'android';
  return 'browser';
}

// Best-effort synchronous platform id. The authoritative value comes from the
// Rust `runtimeInfo.platform` once resolved; this fallback is only used to
// build descriptors before the native runtime answers.
export function detectPlatform() {
  if (typeof window === 'undefined') return 'development';
  return userAgentPlatform();
}

// True only when running inside the Tauri desktop shell. Exists strictly at
// the platform layer; never use it as a runtime identity.
export function isDesktopShell() {
  return typeof window !== 'undefined' && isTauri();
}
