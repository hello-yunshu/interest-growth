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

function responseFromNative({ status, bodyBase64 = '', contentType = '' }, extraHeaders = {}) {
  const bytes = decodeBase64ToBytes(bodyBase64);
  const blob = new Blob([bytes], { type: contentType || 'application/octet-stream' });
  return new Response(blob, {
    status: Number(status) || 200,
    headers: {
      ...(contentType ? { 'content-type': contentType } : {}),
      ...extraHeaders,
    },
  });
}

// Renderer-supplied headers may carry scoping hints (X-PG-Interest-Area) but
// must never attempt to override the native Authorization/Content-Type.
function sanitizeHeaders(headers = {}) {
  const clean = {};
  for (const [key, value] of Object.entries(headers)) {
    if (!/^authorization$/i.test(key) && !/^content-type$/i.test(key)) {
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
    const body = options.body;
    if (typeof FormData !== 'undefined' && body instanceof FormData) {
      return this._upload(path, options);
    }
    const method = String(options.method || 'GET').toUpperCase();
    const contentType =
      typeof body === 'string'
        ? options.headers?.['Content-Type'] || 'application/json'
        : undefined;
    const native = await this.broker.apiRequest(path, {
      method,
      body: typeof body === 'string' ? body : undefined,
      contentType,
      headers: sanitizeHeaders(options.headers),
    });
    return responseFromNative(native);
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
    const fileBytes = new Uint8Array(await file.arrayBuffer());
    const fields = {};
    for (const [key, value] of formData.entries()) {
      if (key === fileField) continue;
      if (typeof value === 'string') fields[key] = value;
    }
    const native = await this.broker.apiUpload(path, {
      fileField,
      fileName: file.name || 'upload.bin',
      fileBytesB64: encodeBytesToBase64(fileBytes),
      fileContentType: file.type || 'application/octet-stream',
      fields,
    });
    return responseFromNative(native);
  }
}
