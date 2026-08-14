"use client";

// Gate D §D5 — runtime mode selection, server enrollment, login/logout,
// device management and connection status.
//
// This is the only surface where a user can move between desktop-local
// ("This device") and desktop-remote ("Self-hosted server"). The switch never
// hot-swaps the dataset: it persists the NEXT profile and requires an explicit
// app restart (Gate C §5.3 session immutable). All secrets stay native: the
// renderer only submits owner passwords / relative API paths, and never
// receives a refresh credential.
import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import {
  getDesktopRuntimeMode,
  setDesktopRuntimeMode,
  restartDesktopApp,
  remoteProbeServer,
  remoteBootstrapOwner,
  remoteLogin,
  remoteSessionStatus,
  remoteRefreshNow,
  remoteVerifyIdentity,
  remoteLogout,
  remoteDeviceList,
  remoteRevokeDevice,
  getDesktopRuntime,
} from '../lib/api';
import { getClientRuntime } from '../lib/runtime/client-runtime.js';
import { remoteErrorEvent } from '../lib/runtime/transports/remote.js';
import {
  initialRuntimeConnectState,
  runtimeConnectReducer,
  isRemoteActive,
} from '../lib/runtime/runtime-connect-controller.js';
import { StatusChip, RecordsTable } from './BeautifulUI';

const CONNECTION_META = {
  Initializing: { label: '正在初始化', tone: 'neutral' },
  Connected: { label: '已连接', tone: 'success' },
  Reconnecting: { label: '重新连接中', tone: 'warning' },
  Offline: { label: '离线', tone: 'danger' },
  LoginExpired: { label: '登录已过期', tone: 'danger' },
  IdentityChanged: { label: '服务器身份变化', tone: 'danger' },
  UpdateRequired: { label: '需要更新客户端', tone: 'danger' },
  UnsupportedServer: { label: '服务器不受支持', tone: 'danger' },
  LocalCoreError: { label: '本地服务异常', tone: 'danger' },
};

function shortId(value) {
  return String(value || '').slice(0, 8);
}

function formatSeen(value) {
  if (!value) return '从未在线';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const diff = Date.now() - date.getTime();
  if (diff < 60_000) return '刚刚';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
}

export default function RuntimeConnect({ onRuntimeChanged }) {
  const [desktop, setDesktop] = useState(false);
  const [runtimeState, dispatch] = useReducer(runtimeConnectReducer, { activeRuntimeId: 'desktop-local' }, initialRuntimeConnectState);
  const [confirmTarget, setConfirmTarget] = useState(null);
  // "稍后重启" only hides the reminder; the persisted pending switch stays.
  const [dismissedRestart, setDismissedRestart] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState({ tone: 'success', text: '' });

  const [session, setSession] = useState(null);
  // HIGH-5: the ConnectionStateMachine is the ONE source of truth for the
  // connection state. This component only MIRRORS it through a subscription —
  // it never derives its own verdict from status fields.
  const [connectionState, setConnectionState] = useState('Initializing');
  const machineRef = useRef(null);

  const [serverUrl, setServerUrl] = useState('');
  const [probe, setProbe] = useState(null);
  const [ownerPassword, setOwnerPassword] = useState('');
  const [bootstrapToken, setBootstrapToken] = useState('');
  const [deviceName, setDeviceName] = useState('');

  const [devices, setDevices] = useState([]);
  const [devicesLoaded, setDevicesLoaded] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState(null);
  const [revokePassword, setRevokePassword] = useState('');

  const isRemote = isRemoteActive(runtimeState);
  const needsRestart = runtimeState.restartRequired && !dismissedRestart;

  function flash(text, tone = 'success') {
    setMsg({ tone, text });
  }

  async function loadSession() {
    const status = await remoteSessionStatus();
    setSession(status);
    return status;
  }

  // HIGH-5: connection state is mirrored from the machine only. The machine is
  // resolved once by ClientRuntime (which performs the HIGH-2 startup
  // recovery); every transition here comes from its subscription, never from a
  // local re-derivation of native status fields.
  useEffect(() => {
    let active = true;
    let unsubscribe = null;
    (async () => {
      try {
        const client = await getClientRuntime();
        if (!active || !client?.connection) return;
        machineRef.current = client.connection;
        if (active) setConnectionState(client.connection.state);
        unsubscribe = client.connection.subscribe((next) => {
          if (active) setConnectionState(next);
        });
      } catch {
        if (active) setConnectionState('LocalCoreError');
      }
    })();
    return () => {
      active = false;
      unsubscribe?.();
    };
  }, []);

  async function loadDevices() {
    try {
      const result = await remoteDeviceList();
      setDevices(result?.devices || []);
    } catch (error) {
      setDevices([]);
      flash(`无法读取设备列表：${error.message}`, 'error');
    } finally {
      setDevicesLoaded(true);
    }
  }

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const runtime = await getDesktopRuntime();
        if (active) setDesktop(Boolean(runtime?.desktop));
      } catch { /* not desktop */ }
      try {
        const modeInfo = await getDesktopRuntimeMode();
        // Gate D §P10 — native is the active source of truth: `active` is the
        // process-lifetime mode, `pending` is the NEXT profile after restart.
        if (active) dispatch({
          type: 'MODE_LOADED',
          activeRuntimeId: modeInfo?.activeRuntimeId,
          pendingRuntimeId: modeInfo?.pendingRuntimeId,
        });
      } catch {
        if (active) dispatch({ type: 'MODE_LOADED', activeRuntimeId: 'desktop-local' });
      }
      try {
        const status = await remoteSessionStatus();
        if (active) setSession(status);
      } catch {
        if (active) setSession({ enrolled: false });
      }
    })();
    return () => { active = false; };
  }, []);

  // Load devices once the remote session becomes connected.
  useEffect(() => {
    if (isRemote && session?.enrolled && session?.connected && !devicesLoaded) {
      loadDevices();
    }
  }, [isRemote, session, devicesLoaded]);

  async function chooseMode(target) {
    if (busy || target === runtimeState.activeRuntimeId) return;
    setConfirmTarget(target);
  }

  async function confirmSwitch() {
    const target = confirmTarget;
    if (!target) return;
    setConfirmTarget(null);
    setBusy(true);
    setMsg({ tone: 'success', text: '' });
    try {
      const info = await setDesktopRuntimeMode(target);
      // Only the pending mode changes; the active mode stays immutable until a
      // real restart applies it (Gate D §P10/P25).
      dispatch({
        type: 'SWITCH_PERSISTED',
        pendingRuntimeId: info?.pendingRuntimeId || info?.activeRuntimeId || target,
      });
      setDismissedRestart(false);
      flash(`已保存运行时切换。切换将在应用重启后生效。`);
    } catch (error) {
      flash(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function doRestart() {
    setBusy(true);
    try {
      await restartDesktopApp();
    } catch (error) {
      flash(error.message, 'error');
      setBusy(false);
    }
  }

  async function doProbe(event) {
    event?.preventDefault();
    if (busy) return;
    setBusy(true);
    setMsg({ tone: 'success', text: '' });
    setProbe(null);
    try {
      const result = await remoteProbeServer(serverUrl);
      setProbe(result);
      setOwnerPassword('');
      setBootstrapToken('');
      flash(`已连接到服务器：${result?.server?.serverDisplayName || result?.normalizedOrigin || serverUrl}`);
    } catch (error) {
      flash(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function doBootstrap(event) {
    event?.preventDefault();
    if (busy) return;
    if (!probe) return;
    setBusy(true);
    setMsg({ tone: 'success', text: '' });
    try {
      await remoteBootstrapOwner(probe.normalizedOrigin, ownerPassword, bootstrapToken);
      setOwnerPassword('');
      setBootstrapToken('');
      flash('管理员密码已创建。现在可以用它登录这台服务器。');
      setProbe({ ...probe, server: { ...probe.server, ownerConfigured: true } });
    } catch (error) {
      flash(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function doLogin(event) {
    event?.preventDefault();
    if (busy) return;
    const origin = probe?.normalizedOrigin || session?.normalizedOrigin;
    if (!origin) return;
    setBusy(true);
    setMsg({ tone: 'success', text: '' });
    try {
      const runtime = await getDesktopRuntime();
      await remoteLogin({
        origin,
        ownerPassword,
        deviceName: deviceName || (runtime?.platform === 'windows' ? '这台电脑' : '这台 Mac'),
        platform: runtime?.platform || 'macos',
        appVersion: runtime?.version || '0.7.0',
        expectedServerInstanceId: probe?.server?.serverInstanceId || session?.serverInstanceId || '',
      });
      setOwnerPassword('');
      setDeviceName('');
      setProbe(null);
      const status = await loadSession();
      machineRef.current?.handle('BOOTSTRAP_OK');
      if (status?.enrolled && status?.connected) {
        setDevicesLoaded(false);
        setDevices([]);
      }
      flash('已登录服务器，凭据已安全保存到系统钥匙串。');
      onRuntimeChanged?.();
    } catch (error) {
      flash(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function doRefresh() {
    setBusy(true);
    setMsg({ tone: 'success', text: '' });
    try {
      const status = await remoteRefreshNow();
      setSession(status);
      machineRef.current?.handle('RECONNECT_OK');
      flash('连接状态已刷新，会话有效。');
    } catch (error) {
      machineRef.current?.handle(remoteErrorEvent(error));
      flash(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function doVerifyIdentity() {
    setBusy(true);
    setMsg({ tone: 'success', text: '' });
    try {
      const result = await remoteVerifyIdentity();
      if (result?.identityChanged) {
        machineRef.current?.handle('IDENTITY_MISMATCH');
        flash('检测到服务器身份变化：同一地址后面的服务器实例已被替换。请重新验证后再接入。', 'error');
      } else {
        machineRef.current?.handle('RECONNECT_OK');
        flash('服务器身份验证通过：与接入时是同一实例。');
      }
    } catch (error) {
      flash(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function doLogout(revoke) {
    setBusy(true);
    setMsg({ tone: 'success', text: '' });
    try {
      // Gate D §P20 — the native result is truthful: a failed network revoke
      // reports `revoked: false` and the UI must not claim the device was
      // revoked. Local credentials are always removed either way.
      const result = await remoteLogout(revoke);
      setSession(null);
      setDevices([]);
      setDevicesLoaded(false);
      machineRef.current?.handle('RESET');
      if (revoke && result && !result.revoked) {
        flash('已从本机移除登录信息，但服务器端设备撤销未确认。', 'error');
      } else if (revoke) {
        flash('已退出登录并撤销这台设备。');
      } else {
        flash('已退出登录。');
      }
      onRuntimeChanged?.();
    } catch (error) {
      flash(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function doRevoke(device) {
    if (device?.current) {
      await doLogout(true);
      return;
    }
    setRevokeTarget(device);
    setRevokePassword('');
  }

  async function confirmRevoke() {
    if (!revokeTarget) return;
    const target = revokeTarget;
    setRevokeTarget(null);
    setRevokePassword('');
    setBusy(true);
    setMsg({ tone: 'success', text: '' });
    try {
      await remoteRevokeDevice(target.id, revokePassword);
      flash(`设备“${target.name}”已撤销，其本地凭据将失效。`);
      await loadDevices();
    } catch (error) {
      flash(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  const connectionMeta = CONNECTION_META[connectionState] || { label: connectionState, tone: 'neutral' };

  const deviceColumns = useMemo(() => [
    { key: 'name', label: '设备', render: row => <strong>{row.name}{row.current ? '（当前）' : ''}</strong> },
    { key: 'platform', label: '平台', render: row => row.platform || '—' },
    { key: 'seen', label: '最近在线', render: row => formatSeen(row.last_seen_at) },
    { key: 'state', label: '状态', render: row => <StatusChip tone={row.revoked_at ? 'neutral' : 'success'}>{row.revoked_at ? '已撤销' : '活跃'}</StatusChip> },
    { key: 'action', label: '操作', render: row => row.revoked_at ? <span className="muted smallText">—</span> : <button className="tableLink danger" onClick={() => doRevoke(row)} disabled={busy}>{row.current ? '退出并撤销' : '撤销'}</button> },
  ], [busy]);

  if (!desktop) {
    return <section className="card">
      <div className="cardHeader"><div><div className="eyebrow">连接</div><h3>本机应用</h3></div><StatusChip tone="neutral">浏览器开发模式</StatusChip></div>
      <p className="muted">运行时切换与自托管服务器接入只在桌面应用内可用。浏览器远程访问（安全 Cookie 认证）仍为规划能力，v0.7 未提供。</p>
    </section>;
  }

  return <div className="stack">
    <section className="card">
      <div className="cardHeader">
        <div>
          <div className="eyebrow">运行时模式</div>
          <h3>数据保存在哪里</h3>
          <p className="muted">运行时模式决定数据源与安全边界。切换会保存为下一次启动的配置，并需要重启应用后生效。</p>
        </div>
        <StatusChip tone={isRemote ? 'accent' : 'success'}>{isRemote ? '自托管服务器' : '本机'}</StatusChip>
      </div>
      <div className="runtimeModeGrid">
        <button type="button" className={`runtimeModeCard ${!isRemote ? 'is-active' : ''}`} onClick={() => chooseMode('desktop-local')} disabled={busy}>
          <span className="runtimeModeMark">本机</span>
          <span className="runtimeModeCopy"><strong>This device · 本机</strong><small>数据保存在这台设备，由本机 Core 提供服务。</small></span>
          {!isRemote && <StatusChip tone="success">当前</StatusChip>}
        </button>
        <button type="button" className={`runtimeModeCard ${isRemote ? 'is-active' : ''}`} onClick={() => chooseMode('desktop-remote')} disabled={busy}>
          <span className="runtimeModeMark">服务器</span>
          <span className="runtimeModeCopy"><strong>Self-hosted server · 自托管服务器</strong><small>数据保存在你的服务器，通过安全凭据连接，不在本机复制。</small></span>
          {isRemote && <StatusChip tone="accent">当前</StatusChip>}
        </button>
      </div>
      {confirmTarget && (
        <div className="runtimeConfirm">
          <p>确定切换到 {confirmTarget === 'desktop-remote' ? '自托管服务器' : '本机'} 吗？切换只会在应用重启后生效，本机数据与服务器数据不会被自动合并。</p>
          <div className="row">
            <button className="secondary" onClick={() => setConfirmTarget(null)} disabled={busy}>取消</button>
            <button onClick={confirmSwitch} disabled={busy}>保存并切换</button>
          </div>
        </div>
      )}
      {needsRestart && (
        <div className="notice">
          <strong>需要重启应用才能进入 {runtimeState.pendingRuntimeId === 'desktop-remote' ? '自托管服务器' : '本机'} 模式。</strong>
          <span> 重启后当前会话将切换到所选数据源；本机数据与服务器数据保持分离，不会被自动合并。</span>
          <div className="row sectionTop">
            <button className="secondary" onClick={() => setDismissedRestart(true)} disabled={busy}>稍后重启</button>
            <button onClick={doRestart} disabled={busy}>{busy ? '正在重启…' : '立即重启'}</button>
          </div>
        </div>
      )}
    </section>

    {msg.text && <p className={`notice ${msg.tone === 'error' ? 'error' : 'success'}`}>{msg.text}</p>}

    {isRemote && (
      <section className="card">
        <div className="cardHeader">
          <div><div className="eyebrow">服务器连接</div><h3>自托管服务器</h3></div>
          <StatusChip tone={connectionMeta.tone} pulse={connectionState === 'Reconnecting'}>{connectionMeta.label}</StatusChip>
        </div>

        {!session?.enrolled && (
          <div className="stack">
            <p className="muted">输入服务器地址并探测。服务器地址必须是 HTTPS（局域网或开发环境允许本机 HTTP）。连接凭据会安全保存到系统钥匙串，不会暴露给应用界面。</p>
            <form className="fieldGroup" onSubmit={doProbe}>
              <label htmlFor="remoteServerUrl">服务器地址</label>
              <div className="row">
                <input id="remoteServerUrl" type="text" autoComplete="url" placeholder="https://ig.example.com" value={serverUrl} onChange={event => setServerUrl(event.target.value)} disabled={busy}/>
                <button type="submit" className="secondary" disabled={busy || !serverUrl.trim()}>{busy ? '探测中…' : '探测服务器'}</button>
              </div>
            </form>

            {probe && (
              <div className="subcard">
                <div className="row"><strong>{probe.server?.serverDisplayName || '未命名服务器'}</strong><StatusChip tone="neutral">{probe.normalizedOrigin}</StatusChip></div>
                <div className="providerHeroRow"><span>服务器版本</span><strong>{probe.server?.serverVersion || '—'}</strong></div>
                <div className="providerHeroRow"><span>实例 ID</span><strong className="pathEllipsis" style={{ maxWidth: 220 }}>{probe.server?.serverInstanceId || '—'}</strong></div>
                <div className="providerHeroRow"><span>认证模式</span><StatusChip tone={probe.server?.authEnabled ? 'success' : 'warning'}>{probe.server?.authEnabled ? '单机主设备（已启用）' : '未启用远程认证'}</StatusChip></div>
                {!probe.server?.authEnabled && <p className="notice error">这台服务器没有启用远程设备认证，无法接入。</p>}

                {probe.server?.authEnabled && !probe.server?.ownerConfigured && (
                  <form className="stack sectionTop" onSubmit={doBootstrap}>
                    <p className="muted">这台服务器还没有设置管理员。创建管理员密码需要服务器管理员提供的一次性引导令牌。</p>
                    <div className="fieldGroup">
                      <label htmlFor="remoteOwnerPassword">管理员密码（至少 10 个字符）</label>
                      <input id="remoteOwnerPassword" type="password" autoComplete="new-password" value={ownerPassword} onChange={event => setOwnerPassword(event.target.value)} disabled={busy}/>
                    </div>
                    <div className="fieldGroup">
                      <label htmlFor="remoteBootstrapToken">引导令牌</label>
                      <input id="remoteBootstrapToken" type="text" autoComplete="off" value={bootstrapToken} onChange={event => setBootstrapToken(event.target.value)} disabled={busy}/>
                    </div>
                    <div className="row">
                      <button type="submit" className="secondary" disabled={busy || ownerPassword.length < 10 || !bootstrapToken.trim()}>{busy ? '创建中…' : '创建管理员'}</button>
                    </div>
                  </form>
                )}

                {probe.server?.authEnabled && probe.server?.ownerConfigured && (
                  <form className="stack sectionTop" onSubmit={doLogin}>
                    <div className="fieldGroup">
                      <label htmlFor="remoteLoginPassword">管理员密码</label>
                      <input id="remoteLoginPassword" type="password" autoComplete="current-password" value={ownerPassword} onChange={event => setOwnerPassword(event.target.value)} disabled={busy}/>
                    </div>
                    <div className="fieldGroup">
                      <label htmlFor="remoteDeviceName">这台设备的名称</label>
                      <input id="remoteDeviceName" type="text" autoComplete="off" placeholder="例如：工作室的电脑" value={deviceName} onChange={event => setDeviceName(event.target.value)} disabled={busy}/>
                    </div>
                    <div className="row">
                      <button type="submit" disabled={busy || !ownerPassword}>{busy ? '登录中…' : '登录并接入'}</button>
                      <button type="button" className="ghost" onClick={() => { setProbe(null); setOwnerPassword(''); }} disabled={busy}>换一个服务器</button>
                    </div>
                  </form>
                )}
              </div>
            )}
          </div>
        )}

        {session?.enrolled && (
          <div className="stack">
            <div className="subcard">
              <div className="row"><strong>{session.serverDisplayName || '自托管服务器'}</strong><StatusChip tone="neutral">{session.normalizedOrigin}</StatusChip></div>
              <div className="providerHeroRow"><span>服务器版本</span><strong>{session.serverVersion || '—'}</strong></div>
              <div className="providerHeroRow"><span>实例 ID</span><strong className="pathEllipsis" style={{ maxWidth: 220 }}>{shortId(session.serverInstanceId)}…</strong></div>
              <div className="providerHeroRow"><span>本机设备</span><strong>{session.deviceName || session.deviceId || '—'}</strong></div>
              {session.authExpired && <p className="notice warning">会话已过期，需要重新登录。</p>}
            </div>

            {session.authExpired && (
              <form className="fieldGroup" onSubmit={doLogin}>
                <div className="row"><label htmlFor="remoteReloginPassword">管理员密码</label></div>
                <div className="row">
                  <input id="remoteReloginPassword" type="password" autoComplete="current-password" placeholder="重新输入管理员密码" value={ownerPassword} onChange={event => setOwnerPassword(event.target.value)} disabled={busy}/>
                  <button type="submit" className="secondary" disabled={busy || !ownerPassword}>{busy ? '登录中…' : '重新登录'}</button>
                </div>
              </form>
            )}

            <div className="row">
              <button className="secondary" onClick={doRefresh} disabled={busy}>立即刷新会话</button>
              <button className="secondary" onClick={doVerifyIdentity} disabled={busy}>验证服务器身份</button>
              <button className="ghost danger" onClick={() => doLogout(false)} disabled={busy}>退出登录</button>
              <button className="ghost danger" onClick={() => doLogout(true)} disabled={busy}>退出并撤销这台设备</button>
            </div>
          </div>
        )}
      </section>
    )}

    {isRemote && session?.enrolled && session?.connected && (
      <section className="card">
        <div className="cardHeader">
          <div><div className="eyebrow">设备管理</div><h3>已接入的设备</h3></div>
          {!devicesLoaded && <StatusChip tone="neutral">加载中</StatusChip>}
        </div>
        <RecordsTable columns={deviceColumns} rows={devices} empty="还没有读取到设备列表。" rowKey="id"/>
        {revokeTarget && (
          <form className="runtimeConfirm" onSubmit={confirmRevoke}>
            <p>撤销设备“{revokeTarget.name}”？撤销后它的本地凭据立即失效。撤销其他设备需要输入管理员密码。</p>
            <div className="fieldGroup"><label htmlFor="remoteRevokePassword">管理员密码</label><input id="remoteRevokePassword" type="password" autoComplete="current-password" value={revokePassword} onChange={event => setRevokePassword(event.target.value)} disabled={busy}/></div>
            <div className="row">
              <button type="button" className="secondary" onClick={() => setRevokeTarget(null)} disabled={busy}>取消</button>
              <button type="submit" disabled={busy || !revokePassword}>{busy ? '撤销中…' : '确认撤销'}</button>
            </div>
          </form>
        )}
      </section>
    )}
  </div>;
}
