// Gate C §7 — enrollment origin normalization.
//
// Self-hosted enrollment is distinct from server-side web-research SSRF: a
// self-hosted server may legitimately live on a LAN/VPN. This utility only
// enforces the client-side enrollment rules.
//
// Rejects: embedded credentials, fragment, query, non-root paths, plain HTTP
// for public/LAN endpoints (loopback HTTP allowed only for explicit
// development/test), and anything that implies TLS verification is disabled.

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

export function normalizeEnrollmentOrigin(input, { allowLoopbackHttp = false } = {}) {
  let url;
  try {
    url = new URL(String(input).trim());
  } catch {
    return { ok: false, error: 'INVALID_URL', message: '服务器地址不是有效的 URL' };
  }
  if (url.username || url.password) {
    return { ok: false, error: 'EMBEDDED_CREDENTIALS', message: '服务器地址不能包含用户名或密码' };
  }
  if (url.hash) {
    return { ok: false, error: 'FRAGMENT_NOT_ALLOWED', message: '服务器地址不能包含 # 片段' };
  }
  if (url.search) {
    return { ok: false, error: 'QUERY_NOT_ALLOWED', message: '服务器地址不能包含查询参数' };
  }
  if (url.pathname && url.pathname !== '/') {
    return { ok: false, error: 'SUBPATH_NOT_ALLOWED', message: '服务器地址只能是域名/IP，不能包含路径' };
  }
  const host = (url.hostname || '').toLowerCase();
  const loopback = LOOPBACK_HOSTS.has(host);
  if (url.protocol === 'https:') {
    // TLS verification is always on; no option exists to disable it.
    return { ok: true, origin: `https://${url.host}`, tls: true, loopback };
  }
  if (url.protocol === 'http:') {
    if (!loopback) {
      return { ok: false, error: 'HTTPS_REQUIRED', message: '公网或局域网自托管服务器必须使用 HTTPS' };
    }
    if (!allowLoopbackHttp) {
      return { ok: false, error: 'LOOPBACK_HTTP_NOT_ALLOWED', message: 'loopback HTTP 仅允许开发/测试场景' };
    }
    return { ok: true, origin: `http://${url.host}`, tls: false, loopback: true };
  }
  return { ok: false, error: 'SCHEME_NOT_ALLOWED', message: '只支持 http 或 https 协议' };
}
