// Gate C §3 — ClientRuntime is the single client runtime source of truth.
//
// In Gate C only desktop-local is active. Gate D wires desktop-remote to the
// native broker (Rust): the renderer never receives a refresh credential and
// never falls back to a local dataset. This module resolves the runtime
// descriptor, connection state machine, transport and platform adapter, so
// feature pages and api.js never branch on "isTauri()".
import { detectPlatform, isDesktopShell } from './platform.js';
import {
  desktopLocalDescriptor,
  descriptorFor,
  isKnownRuntimeId,
} from './descriptors.js';
import { ConnectionStateMachine } from './connection-state.js';
import {
  resolveDesktopLocalRuntime,
  localAuthHeader,
} from './transports/desktop-local.js';
import { RemoteTransport, remoteErrorEvent } from './transports/remote.js';
import * as tauriDesktop from './platforms/tauri-desktop.js';
import * as tauriAndroid from './platforms/tauri-android.js';
import * as browser from './platforms/browser.js';

// Gate E §6.8 — platform resolution is no longer "Tauri == desktop".
// windows/macos + Tauri → tauri-desktop; android + Tauri → tauri-android;
// anything else → browser. The chosen adapter carries the native broker
// surface (and host actions) for the resolved runtime.
function platformAdapter(platform) {
  if (platform === 'android' && isDesktopShell()) return tauriAndroid;
  if ((platform === 'windows' || platform === 'macos') && isDesktopShell()) {
    return tauriDesktop;
  }
  return browser;
}

// Gate C §5.4 — a remote runtime never silently falls back to a local store.
// Without a native broker it stays inert so the UI honestly reports that the
// remote connection is not proven.
function inactiveRemoteTransport() {
  return {
    active: false,
    async request() {
      throw new Error('remote transport is not active in this build (Gate D)');
    },
    authHeader: {},
  };
}

// Gate D §D4 / Gate E §6.5 — build the native remote transport for a
// desktop-remote OR android-remote runtime. The native broker (Rust) owns the
// origin, the refresh credential and the Bearer header; the renderer only
// submits relative API paths. Enrollment state is read from the native broker
// so the descriptor is bound to the real server. The platform adapter
// (desktop vs Android) is injected so this stays a pure shared resolver with
// no Tauri import, which is what makes the Android runtime tests real (they
// cannot be faked with the desktop mock).
export async function resolveNativeRemote(runtimeId, platform, runtime, adapter) {
  const descriptor = descriptorFor(runtimeId, platform);
  let status = null;
  try {
    status = await adapter.remoteSessionStatus();
  } catch {
    status = null;
  }
  const broker = {
    apiRequest: adapter.remoteApiRequest,
    apiUpload: adapter.remoteApiUpload,
  };
  const connection = new ConnectionStateMachine({ initialState: 'Initializing' });
  const transport = new RemoteTransport({
    broker,
    active: true,
    connection,
    // Gate R0.5/§6.1 — Android only uploads via SAF content:// (uploadByUri);
    // the generic File/Blob byte path is denied structurally, not by UI habit.
    byteUploadAllowed: platform !== 'android',
  });
  if (status?.enrolled) {
    descriptor.server = {
      displayName: status.serverDisplayName || '自托管服务器',
      normalizedOrigin: status.normalizedOrigin || '',
      serverInstanceId: status.serverInstanceId || '',
      serverVersion: status.serverVersion || '',
      apiVersion: status.apiVersion || '',
      minClientVersion: status.minClientVersion || '',
    };
    // Gate E — the Android storage namespace is server_instance_id scoped just
    // like desktop-remote, keyed by the runtime id so the two never collide.
    descriptor.storageNamespace = status.serverInstanceId
      ? `${runtimeId}:${status.serverInstanceId}`
      : null;
    if (status.connected) {
      connection.handle('BOOTSTRAP_OK');
    } else if (status.authExpired) {
      // The server itself denied the refresh credential; do not retry here.
      connection.handle('REFRESH_FAIL');
    } else {
      // HIGH-2: "enrolled + refresh stored + not connected" is a NORMAL restart
      // state, never LoginExpired. Recover through the native broker instead of
      // guessing. The broker single-flights this against any other caller.
      try {
        const refreshed = await adapter.remoteRefreshNow();
        if (refreshed?.connected) connection.handle('BOOTSTRAP_OK');
        else if (refreshed?.authExpired) connection.handle('REFRESH_FAIL');
        else connection.handle('NETWORK_FAIL');
      } catch (error) {
        // The coded error taxonomy decides: a real server verdict becomes its
        // honest state, anything ambiguous is a bounded network retry.
        connection.handle(remoteErrorEvent(error));
      }
    }
  }
  return { descriptor, runtime, connection, transport };
}

async function resolve() {
  const platform = detectPlatform();
  const runtime = await resolveDesktopLocalRuntime();
  const runtimeId = isKnownRuntimeId(runtime.runtimeId) ? runtime.runtimeId : 'desktop-local';
  const shell = isDesktopShell();

  // Gate E — desktop-remote and android-remote share the native remote
  // resolver; only their platform adapter differs. A non-native shell
  // (browser) never resolves either, so it honestly stays inactive.
  if (
    (runtimeId === 'desktop-remote' || runtimeId === 'android-remote') &&
    shell
  ) {
    const remote = await resolveNativeRemote(runtimeId, platform, runtime, platformAdapter(platform));
    return {
      descriptor: remote.descriptor,
      runtime,
      platform,
      connection: remote.connection,
      adapter: platformAdapter(platform),
      transport: remote.transport,
      storageNamespace: remote.descriptor.storageNamespace,
    };
  }

  const descriptor =
    runtimeId === 'desktop-local'
      ? desktopLocalDescriptor(platform)
      : descriptorFor(runtimeId, platform);
  const connection = new ConnectionStateMachine({ initialState: 'Initializing' });
  const local = descriptor.runtimeId === 'desktop-local';
  const transport = local
    ? {
        active: 'desktop-local',
        async request(path, options, headers) {
          const response = await fetch(`${runtime.apiBase}${path}`, { ...options, headers });
          return response;
        },
        authHeader: localAuthHeader(runtime),
      }
    : inactiveRemoteTransport();
  return {
    descriptor,
    runtime,
    platform,
    connection,
    adapter: platformAdapter(platform),
    transport,
    storageNamespace: descriptor.storageNamespace,
  };
}

let runtimePromise = null;

export function getClientRuntime() {
  if (!runtimePromise) {
    runtimePromise = resolve().catch((error) => {
      runtimePromise = null;
      throw error;
    });
  }
  return runtimePromise;
}

export function resetClientRuntime() {
  runtimePromise = null;
}

export async function getRuntimeLabels() {
  const client = await getClientRuntime();
  return buildRuntimeLabels(client);
}

// Gate C §18 — user copy is derived from the runtime descriptor, never
// hardcoded per feature page. Offline/remote copy never claims "content is
// safe on this device".
//
// Gate D §P13 — remote labels react to the real connection state so the UI
// never shows "已连接" while the transport is Offline / LoginExpired /
// IdentityChanged. An explicit `connectionState` may be passed (for live UI
// updates); otherwise the client's current state machine is used.
const REMOTE_STATE_META = {
  Initializing: { status: '正在初始化', footer: '连接中' },
  Connected: { status: '已连接', footer: '在线' },
  Reconnecting: { status: '重新连接中', footer: '重新连接中' },
  Offline: { status: '离线', footer: '离线' },
  LoginExpired: { status: '登录已过期', footer: '登录已过期' },
  IdentityChanged: { status: '服务器身份变化', footer: '服务器身份变化' },
  UpdateRequired: { status: '需要更新客户端', footer: '需要更新客户端' },
  UnsupportedServer: { status: '服务器不受支持', footer: '服务器不受支持' },
  LocalCoreError: { status: '本地服务异常', footer: '本地服务异常' },
};

export function buildRuntimeLabels(client, connectionState) {
  const remote = client?.descriptor?.dataLocation === 'self-hosted-server';
  if (remote) {
    const state = connectionState || client?.connection?.state || 'Initializing';
    const meta = REMOTE_STATE_META[state] || { status: '未知连接状态', footer: '连接状态未知' };
    return {
      dataLocation: 'self-hosted-server',
      dataStatusLabel: `自托管服务器 · ${meta.status}`,
      bootCopy: '正在连接你的自托管服务器',
      searchEmptyTitle: '正在搜索服务器内容',
      searchEmptyHint: '内容仍保存在你的自托管服务器。',
      savedCopy: '这次内容已经保存到自托管服务器。',
      noteSavedCopy: '学习笔记已保存到自托管服务器。',
      providerCopy: '你的内容由自托管服务器保存',
      offlineCopy: '暂时连接不到你的自托管服务器。当前版本不会在离线状态提交修改。',
      dataFooter: `自托管服务器 · ${meta.footer}`,
      knowledgeHeadline: '原始资料留在自托管服务器，检索索引随时可以重建。',
      systemTitle: '服务器连接、能力开关与模型通道。',
      systemBadge: '服务器连接',
    };
  }
  return {
    dataLocation: 'local-device',
    dataStatusLabel: '本地保存',
    bootCopy: '内容仍保存在本机',
    searchEmptyTitle: '正在搜索本机内容',
    searchEmptyHint: '问题、笔记和资料仍保存在本机。',
    savedCopy: '这次回顾已经保存在本机。',
    noteSavedCopy: '学习笔记已保存在本机。',
    providerCopy: '你的内容由本地服务保存',
    offlineCopy: '暂时连接不到本地服务。你的内容仍安全保存在设备上，请稍后重试。',
    dataFooter: '本地保存 · 数据仅保存在你的设备上',
    knowledgeHeadline: '原始资料留在本机，检索索引随时可以重建。',
    systemTitle: '本地服务、能力开关与模型通道。',
    systemBadge: '本地优先',
  };
}
