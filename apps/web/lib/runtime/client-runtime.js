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
import { RemoteTransport } from './transports/remote.js';
import * as tauriDesktop from './platforms/tauri-desktop.js';
import * as browser from './platforms/browser.js';

function platformAdapter() {
  return isDesktopShell() ? tauriDesktop : browser;
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

// Gate D §D4 — build the remote transport for a desktop-remote runtime. The
// native broker (Rust) owns the origin, the refresh credential and the Bearer
// header; the renderer only submits relative API paths. Enrollment state is
// read from the native broker so the descriptor is bound to the real server.
async function resolveDesktopRemote(platform, runtime) {
  const descriptor = descriptorFor('desktop-remote', platform);
  let status = null;
  try {
    status = await tauriDesktop.remoteSessionStatus();
  } catch {
    status = null;
  }
  const broker = {
    apiRequest: tauriDesktop.remoteApiRequest,
    apiUpload: tauriDesktop.remoteApiUpload,
  };
  const connection = new ConnectionStateMachine({ initialState: 'Initializing' });
  const transport = new RemoteTransport({ broker, active: true, connection });
  if (status?.enrolled) {
    descriptor.server = {
      displayName: status.serverDisplayName || '自托管服务器',
      normalizedOrigin: status.normalizedOrigin || '',
      serverInstanceId: status.serverInstanceId || '',
      serverVersion: status.serverVersion || '',
      apiVersion: status.apiVersion || '',
      minClientVersion: status.minClientVersion || '',
    };
    descriptor.storageNamespace = status.serverInstanceId
      ? `desktop-remote:${status.serverInstanceId}`
      : null;
    if (status.connected) connection.handle('BOOTSTRAP_OK');
    else if (status.authExpired) connection.handle('REFRESH_FAIL');
    else connection.handle('NETWORK_FAIL');
  }
  return { descriptor, runtime, connection, transport };
}

async function resolve() {
  const platform = detectPlatform();
  const runtime = await resolveDesktopLocalRuntime();
  const runtimeId = isKnownRuntimeId(runtime.runtimeId) ? runtime.runtimeId : 'desktop-local';
  const shell = isDesktopShell();

  if (runtimeId === 'desktop-remote' && shell) {
    const remote = await resolveDesktopRemote(platform, runtime);
    return {
      descriptor: remote.descriptor,
      runtime,
      platform,
      connection: remote.connection,
      adapter: platformAdapter(),
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
    adapter: platformAdapter(),
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
export function buildRuntimeLabels(client) {
  const remote = client?.descriptor?.dataLocation === 'self-hosted-server';
  if (remote) {
    return {
      dataLocation: 'self-hosted-server',
      dataStatusLabel: '自托管服务器 · 已连接',
      bootCopy: '正在连接你的自托管服务器',
      searchEmptyTitle: '正在搜索服务器内容',
      searchEmptyHint: '内容仍保存在你的自托管服务器。',
      savedCopy: '这次内容已经保存到自托管服务器。',
      noteSavedCopy: '学习笔记已保存到自托管服务器。',
      providerCopy: '你的内容由自托管服务器保存',
      offlineCopy: '暂时连接不到你的自托管服务器。当前版本不会在离线状态提交修改。',
      dataFooter: '自托管服务器 · 在线',
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
