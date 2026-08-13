// Gate C §17 — WebSocket abstraction (no fake endpoint).
//
// There is no active application WebSocket route, so this module only builds
// the socket abstraction + bounded reconnect state and keeps a future
// authenticated handshake hook. The loopback process token may ride in the
// query for local transport only; a remote bearer/access token is NEVER put
// in a URL query (remote websocket transport is explicitly not active).

export const REMOTE_WS_ACTIVE = false;

export function localWsBase(apiBase) {
  if (!apiBase.startsWith('http')) {
    // Relative/development base: derive from the current page origin.
    const proto = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = typeof window !== 'undefined' ? window.location.host : '127.0.0.1:3000';
    return `${proto}//${host}${apiBase}`;
  }
  return apiBase.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');
}

// Loopback-only query construction. Passing a non-loopback token here is a
// contract violation; remote callers must not use this helper.
export function loopbackWsQuery({ token = '', area = '' } = {}) {
  const params = new URLSearchParams();
  if (token) params.set('token', token);
  if (area) params.set('area', area);
  return params.toString();
}

export function wsUrlWithLoopbackToken(apiBase, path, { token = '', area = '' } = {}) {
  const base = localWsBase(apiBase);
  const query = loopbackWsQuery({ token, area });
  const suffix = query ? `${path.includes('?') ? '&' : '?'}${query}` : '';
  return `${base}${path}${suffix}`;
}

export class ClientSocket {
  constructor({ reconnectLimit = 3 } = {}) {
    this.reconnectAttempts = 0;
    this.reconnectLimit = reconnectLimit;
    this.socket = null;
    this.handshake = null; // future authenticated handshake hook (Gate D)
  }

  get reconnectExhausted() {
    return this.reconnectAttempts >= this.reconnectLimit;
  }
}
