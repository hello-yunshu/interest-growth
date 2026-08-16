// Gate D §P25 — pure runtime-connect lifecycle controller.
//
// The active/pending runtime separation (P10) lives here as a pure reducer so
// the mode-switch lifecycle is testable with the Node built-in test runner
// (no browser / Tauri shell required). The reducer never lets `pending`
// masquerade as `active`, so the UI can never present a remote data location
// while the session still runs a local core.
//
// Data-location label is derived ONLY from `activeRuntimeId`; a persisted
// pending switch does not move the label until a real restart applies it.
//
// Frozen runtime ids (Gate C §2.3 / §4).
import { isRemoteRuntime } from './contract.js';
// Gate E / R0.2 — re-export the single remote-runtime helper (desktop-remote,
// android-remote, browser-remote) so feature pages and the controller never
// branch on the literal desktop-remote string.
export { isRemoteRuntime };
export const RUNTIME_LOCAL = 'desktop-local';
export const RUNTIME_REMOTE = 'desktop-remote';
export const RUNTIME_ANDROID_REMOTE = 'android-remote';

// Lifecycle statuses are plain strings so the reducer stays a pure function.
export const PROBE_STATES = ['idle', 'probing', 'ok', 'error'];
export const COMPATIBILITY_STATES = ['idle', 'compatible', 'incompatible'];
export const IDENTITY_STATES = ['idle', 'verified', 'changed'];
export const SESSION_STATES = ['idle', 'enrolled', 'error'];

export function initialRuntimeConnectState({
  activeRuntimeId = RUNTIME_LOCAL,
  pendingRuntimeId = null,
} = {}) {
  const pending = pendingRuntimeId || activeRuntimeId;
  return {
    activeRuntimeId,
    pendingRuntimeId: pending,
    restartRequired: activeRuntimeId !== pending,
    probeState: 'idle',
    compatibilityState: 'idle',
    identityState: 'idle',
    sessionState: 'idle',
    probe: null,
    session: null,
  };
}

function assertRuntimeId(runtimeId, action) {
  if (
    runtimeId !== RUNTIME_LOCAL &&
    runtimeId !== RUNTIME_REMOTE &&
    runtimeId !== RUNTIME_ANDROID_REMOTE
  ) {
    throw new Error(`unknown runtime id in ${action}: ${runtimeId}`);
  }
}

export function runtimeConnectReducer(state, action) {
  switch (action.type) {
    // Native process setup truth (Gate C §5.3): active is process-lifetime
    // immutable; pending is the persisted NEXT profile.
    case 'MODE_LOADED': {
      const activeRuntimeId = action.activeRuntimeId;
      const pendingRuntimeId = action.pendingRuntimeId || activeRuntimeId;
      assertRuntimeId(activeRuntimeId, 'MODE_LOADED');
      assertRuntimeId(pendingRuntimeId, 'MODE_LOADED');
      return {
        ...state,
        activeRuntimeId,
        pendingRuntimeId,
        restartRequired: activeRuntimeId !== pendingRuntimeId,
      };
    }

    // User persisted a switch (native set_desktop_runtime_mode succeeded).
    case 'SWITCH_PERSISTED': {
      const pendingRuntimeId = action.pendingRuntimeId;
      assertRuntimeId(pendingRuntimeId, 'SWITCH_PERSISTED');
      return {
        ...state,
        pendingRuntimeId,
        restartRequired: state.activeRuntimeId !== pendingRuntimeId,
      };
    }

    // A real app restart applied the pending profile as the new active mode.
    case 'RESTART_APPLIED':
      return {
        ...state,
        activeRuntimeId: state.pendingRuntimeId,
        restartRequired: false,
      };

    // User cancelled the pending switch before restarting.
    case 'RESET_PENDING':
      return {
        ...state,
        pendingRuntimeId: state.activeRuntimeId,
        restartRequired: false,
      };

    case 'PROBE_START':
      return { ...state, probeState: 'probing', probe: null, compatibilityState: 'idle' };

    case 'PROBE_OK':
      return {
        ...state,
        probeState: 'ok',
        probe: action.probe || null,
        compatibilityState: action.compatible ? 'compatible' : 'incompatible',
      };

    case 'PROBE_ERROR':
      return { ...state, probeState: 'error', probe: null };

    case 'IDENTITY_VERIFIED':
      return { ...state, identityState: 'verified' };

    case 'IDENTITY_CHANGED':
      return { ...state, identityState: 'changed' };

    case 'SESSION_LOADED':
      return {
        ...state,
        sessionState: action.session?.enrolled ? 'enrolled' : 'idle',
        session: action.session || null,
      };

    default:
      return state;
  }
}

// Gate D §P10/P25 — data location follows the ACTIVE runtime only. A pending
// switch is not applied until a real restart, so the label never lies about
// which dataset this session can touch. Android is always android-remote, so
// its data location is self-hosted-server like any other remote runtime.
export function dataLocationOf(state) {
  return isRemoteRuntime(state.activeRuntimeId) ? 'self-hosted-server' : 'local-device';
}

export function isRemoteActive(state) {
  return isRemoteRuntime(state.activeRuntimeId);
}
