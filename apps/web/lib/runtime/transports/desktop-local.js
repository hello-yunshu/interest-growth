// Gate C §3/§12 — desktop-local transport.
//
// The loopback transport talks to the local Core sidecar using the
// X-PG-Desktop-Token header. It is the only transport active in v0.6/v0.7
// desktop-local; remote transports are primitives that are not release-active
// yet (see remote.js). The renderer never receives a refresh credential.
import { invoke } from '@tauri-apps/api/core';
import { isDesktopShell } from '../platform.js';
import { isRemoteRuntime } from '../contract.js';

export const WEB_API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000/api';

let runtimePromise = null;

function normalize(runtime) {
  // The native runtime reports the resolved runtimeId (desktop-local,
  // desktop-remote or android-remote). It is passed through so ClientRuntime
  // never infers "desktop-local" from "isTauri()" alone. Android is always
  // android-remote, so its data location is self-hosted-server too.
  return {
    runtimeId: runtime.runtimeId || 'desktop-local',
    dataLocation: isRemoteRuntime(runtime.runtimeId) ? 'self-hosted-server' : 'local-device',
    apiBase: runtime.endpoint ? `${runtime.endpoint}/api` : WEB_API_BASE,
    token: runtime.token || '',
    desktop: true,
    ...runtime,
  };
}

// Resolves the local Core runtime. Outside the Tauri shell it returns a web
// development runtime bound to WEB_API_BASE with no desktop token.
export function resolveDesktopLocalRuntime() {
  if (!isDesktopShell()) {
    return Promise.resolve({
      runtimeId: 'desktop-local',
      dataLocation: 'local-device',
      apiBase: WEB_API_BASE,
      token: '',
      status: 'web',
      desktop: false,
    });
  }
  if (!runtimePromise) {
    runtimePromise = invoke('desktop_runtime')
      .then(normalize)
      .catch((error) => {
        runtimePromise = null;
        throw error;
      });
  }
  return runtimePromise;
}

export function resetDesktopLocalRuntime() {
  runtimePromise = null;
}

export function refreshDesktopLocalRuntime() {
  runtimePromise = null;
  return resolveDesktopLocalRuntime();
}

// Authorization header for the loopback transport. Never used for remote.
export function localAuthHeader(runtime) {
  return runtime.token ? { 'X-PG-Desktop-Token': runtime.token } : {};
}
