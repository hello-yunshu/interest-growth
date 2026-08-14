// Gate C §12 / Gate D §D4 — remote transport.
//
// The renderer submits only RELATIVE API paths. The base origin and the
// Bearer header come from the native broker (Rust), never from arbitrary
// renderer input. The refresh credential stays in the OS keyring and is never
// handed to the renderer; even the access token stays in the native process
// (all HTTP is performed there). This transport marshals results into
// fetch-compatible `Response` objects so api.js keeps working unchanged.
//
// Activation is explicit: the transport is only active in a desktop-remote
// runtime that resolves to the native broker, so the UI never claims a remote
// connection that cannot be proven.
//
// The connection state machine genuinely controls this transport (Gate D
// §P12): mutations are blocked fail-closed in terminal states and real
// request outcomes (network error / 401 / success) update the state, so the
// UI is reactive and no mutation can slip through in an unproven state.
import { CONNECTION_STATES } from '../contract.js';

const MUTATION_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

// Gate D §P17 — upload bound matches the native broker / server product limit.
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const MAX_UPLOAD_MIB = MAX_UPLOAD_BYTES / (1024 * 1024);

// Gate D §P15 — positive request header allowlist. A renderer may only set
// scoping/caching hints; it can never set Authorization, Content-Type,
// Cookie, Host, Origin, Referer, Proxy-Authorization, Connection,
// Transfer-Encoding, Sec-* or any X-Forwarded-* header.
const ALLOWED_REQUEST_HEADERS = new Set([
  'accept',
  'x-pg-interest-area',
  'range',
  'if-none-match',
  'if-modified-since',
]);

function encodeBytesToBase64(bytes) {
  if (typeof btoa === 'function') {
    let binary = '';
    for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }
  return Buffer.from(bytes).toString('base64');
}

function decodeBase64ToBytes(base64) {
  if (typeof atob === 'function') {
    const binary = atob(String(base64 || ''));
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }
  return Uint8Array.from(Buffer.from(String(base64 || ''), 'base64'));
}

function responseFromNative({ status, bodyBase64 = '', contentType = '', responseHeaders = {} }, extraHeaders = {}) {
  const bytes = decodeBase64ToBytes(bodyBase64);
  const blob = new Blob([bytes], { type: contentType || 'application/octet-stream' });
  return new Response(blob, {
    status: Number(status) || 200,
    headers: {
      ...(contentType ? { 'content-type': contentType } : {}),
      // Gate D §P32 (MEDIUM) — the native broker surfaces its safe response
      // metadata allowlist; ETag/Last-Modified reach the renderer so caching
      // behaves like a normal HTTP client.
      ...responseHeaders,
      ...extraHeaders,
    },
  });
}

// Gate D §P26/P11 — stable remote error codes. The native broker rejects with
// `{"code": "...", "message": "..."}` JSON; the renderer must NEVER guess
// state from fuzzy message text. Codes that are not part of the frozen
// taxonomy are treated as transport failures.
export const REMOTE_ERROR_CODES = Object.freeze({
  NETWORK_UNAVAILABLE: 'NETWORK_UNAVAILABLE',
  RATE_LIMITED: 'RATE_LIMITED',
  SERVER_UNAVAILABLE: 'SERVER_UNAVAILABLE',
  LOGIN_EXPIRED: 'LOGIN_EXPIRED',
  IDENTITY_CHANGED: 'IDENTITY_CHANGED',
  UPDATE_REQUIRED: 'UPDATE_REQUIRED',
  UNSUPPORTED_SERVER: 'UNSUPPORTED_SERVER',
  CREDENTIAL_PERSISTENCE_FAILURE: 'CREDENTIAL_PERSISTENCE_FAILURE',
  PROTOCOL_ERROR: 'PROTOCOL_ERROR',
  RUNTIME_MODE_DENIED: 'RUNTIME_MODE_DENIED',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
});

export function parseRemoteErrorCode(error) {
  const message = String(error?.message ?? error ?? '');
  try {
    const parsed = JSON.parse(message);
    if (parsed && typeof parsed.code === 'string') return parsed.code;
  } catch {
    // Not a coded payload: leave it unclassified (transport failure).
  }
  return null;
}

// Map a native rejection to the connection event it honestly represents.
// Terminal classifications only fire for server-side verdicts; anything
// ambiguous stays NETWORK_FAIL so the machine can retry with bounds.
export function remoteErrorEvent(error) {
  switch (parseRemoteErrorCode(error)) {
    case REMOTE_ERROR_CODES.LOGIN_EXPIRED:
      return 'REFRESH_FAIL';
    case REMOTE_ERROR_CODES.IDENTITY_CHANGED:
      return 'IDENTITY_MISMATCH';
    case REMOTE_ERROR_CODES.UPDATE_REQUIRED:
      return 'INCOMPATIBLE';
    case REMOTE_ERROR_CODES.UNSUPPORTED_SERVER:
    case REMOTE_ERROR_CODES.PROTOCOL_ERROR:
      return 'UNSUPPORTED_SERVER';
    case REMOTE_ERROR_CODES.NETWORK_UNAVAILABLE:
    case REMOTE_ERROR_CODES.RATE_LIMITED:
    case REMOTE_ERROR_CODES.SERVER_UNAVAILABLE:
    case REMOTE_ERROR_CODES.CREDENTIAL_PERSISTENCE_FAILURE:
    case REMOTE_ERROR_CODES.RUNTIME_MODE_DENIED:
    case REMOTE_ERROR_CODES.INTERNAL_ERROR:
    default:
      return 'NETWORK_FAIL';
  }
}

// Renderer-supplied headers are a positive allowlist (Gate D §P15): only
// scoping/caching hints pass through. Authorization and Content-Type are
// decided natively, and hop-by-hop / security headers are never forwarded.
function sanitizeHeaders(headers = {}) {
  const clean = {};
  for (const [key, value] of Object.entries(headers)) {
    if (ALLOWED_REQUEST_HEADERS.has(String(key).toLowerCase())) {
      clean[key] = value;
    }
  }
  return clean;
}

function isFileLike(value) {
  return (
    (typeof File !== 'undefined' && value instanceof File) ||
    (typeof Blob !== 'undefined' && value instanceof Blob)
  );
}

export class RemoteTransport {
  constructor({ broker, active = false, connection }) {
    this.broker = broker;
    this._active = active;
    this.connection = connection;
  }

  // The broker is the native remote HTTP + credential broker. Without it the
  // transport must stay inert so the UI cannot claim a proven connection.
  get active() {
    return (
      this._active &&
      (typeof this.broker?.apiRequest === 'function' ||
        typeof this.broker?.apiUpload === 'function')
    );
  }

  // Remote auth is performed natively; the renderer never attaches a Bearer.
  get authHeader() {
    return {};
  }

  // Only relative paths may be submitted. Absolute or protocol-relative URLs
  // are rejected so the native transport can never be pointed at an arbitrary
  // host by renderer input (Gate C §12).
  _assertRelativePath(path) {
    if (typeof path !== 'string') {
      throw new Error('remote transport only accepts relative API paths');
    }
    if (/^https?:\/\//i.test(path)) {
      throw new Error('remote transport rejects absolute URLs');
    }
    if (path.startsWith('//')) {
      throw new Error('remote transport rejects protocol-relative URLs');
    }
    if (path.startsWith('/\\')) {
      throw new Error('remote transport rejects backslash URLs');
    }
    if (!path.startsWith('/')) {
      throw new Error('remote transport only accepts relative API paths');
    }
    return path;
  }

  async request(path, options = {}) {
    this._assertRelativePath(path);
    if (!this.active) {
      throw new Error('remote transport is not active in this build');
    }
    const method = String(options.method || 'GET').toUpperCase();
    if (MUTATION_METHODS.has(method) && this.connection && !this.connection.mutationsAllowed) {
      // Fail-closed at the transport layer: terminal states never mutate the
      // canonical server, even if some UI control forgot to disable itself.
      throw new Error(`mutations are blocked while the remote connection is ${this.connection.state}`);
    }
    const body = options.body;
    if (typeof FormData !== 'undefined' && body instanceof FormData) {
      return this._upload(path, options);
    }
    const contentType =
      typeof body === 'string'
        ? options.headers?.['Content-Type'] || 'application/json'
        : undefined;
    let native;
    try {
      native = await this.broker.apiRequest(path, {
        method,
        body: typeof body === 'string' ? body : undefined,
        contentType,
        headers: sanitizeHeaders(options.headers),
      });
    } catch (error) {
      this._recordFailure(error);
      throw error;
    }
    this._recordOutcome(native?.status);
    return responseFromNative(native);
  }

  // Gate D §P12/P26 — a failed request moves the state machine according to
  // the frozen error taxonomy: server verdicts become terminal states, real
  // transport failures move toward Reconnecting/Offline (never auto-flip out
  // of terminal states).
  _recordFailure(error) {
    if (this.connection && !this.connection.isTerminal) {
      this.connection.handle(remoteErrorEvent(error));
    }
  }

  // Gate D §P12 — a final 401 means the native single-flight refresh already
  // failed (LoginExpired); a success after a loss proves the connection again.
  // Terminal states (IdentityChanged/UnsupportedServer/...) never auto-flip.
  _recordOutcome(status) {
    if (!this.connection || this.connection.isTerminal) return;
    if (Number(status) === 401) {
      this.connection.handle('REFRESH_FAIL');
    } else if (this.connection.state !== 'Connected') {
      this.connection.handle('RECONNECT_OK');
    }
  }

  async _upload(path, options) {
    const formData = options.body;
    let fileField = null;
    let file = null;
    for (const [key, value] of formData.entries()) {
      if (isFileLike(value)) {
        fileField = key;
        file = value;
        break;
      }
    }
    if (!file) {
      throw new Error('remote upload requires a file field');
    }
    // Gate D §P17 — bound the payload before materialising a base64 copy in
    // memory (the native broker re-checks the encoded length and decoded size).
    if (file.size > MAX_UPLOAD_BYTES) {
      throw new Error(`file exceeds the ${MAX_UPLOAD_MIB} MiB upload limit`);
    }
    const fileBytes = new Uint8Array(await file.arrayBuffer());
    const fields = {};
    for (const [key, value] of formData.entries()) {
      if (key === fileField) continue;
      if (typeof value === 'string') fields[key] = value;
    }
    let native;
    try {
      native = await this.broker.apiUpload(path, {
        fileField,
        fileName: file.name || 'upload.bin',
        fileBytesB64: encodeBytesToBase64(fileBytes),
        fileContentType: file.type || 'application/octet-stream',
        fields,
      });
    } catch (error) {
      this._recordFailure(error);
      throw error;
    }
    this._recordOutcome(native?.status);
    return responseFromNative(native);
  }
}
