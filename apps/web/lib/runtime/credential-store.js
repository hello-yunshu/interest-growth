// Gate C §11 / §6.4 — replaceable credential store interface.
//
// The refresh credential NEVER enters the renderer; there is no
// "get_refresh_token() → JS" path. This module only handles NON-SECRET
// enrollment metadata, keyed by server_instance_id + device_id. Production
// refresh storage/rotation/delete lives in the native broker (Rust), and the
// production adapter is behind the same interface.
//
// Records must never contain: password, access token, refresh token.

export class CredentialStore {
  async save(_namespace, _record) {
    throw new Error('CredentialStore.save must be implemented');
  }

  async read(_namespace) {
    throw new Error('CredentialStore.read must be implemented');
  }

  async delete(_namespace) {
    throw new Error('CredentialStore.delete must be implemented');
  }
}

// In-memory implementation for tests and non-native hosts. Not persisted.
export class MemoryCredentialStore extends CredentialStore {
  constructor() {
    super();
    this.map = new Map();
  }

  async save(namespace, record) {
    this.map.set(namespace, { ...record });
    return true;
  }

  async read(namespace) {
    const value = this.map.get(namespace);
    return value ? { ...value } : null;
  }

  async delete(namespace) {
    return this.map.delete(namespace);
  }

  get size() {
    return this.map.size;
  }
}

// Gate C §6.4 — the non-secret identity a client persists about a server.
export function enrolledServerIdentity({
  normalizedOrigin,
  serverInstanceId,
  serverDisplayName,
  product,
  apiVersion,
  serverVersion,
  lastVerifiedAt,
}) {
  return {
    normalizedOrigin,
    serverInstanceId,
    serverDisplayName,
    product,
    apiVersion,
    serverVersion,
    lastVerifiedAt,
  };
}

export function credentialNamespace(serverInstanceId, deviceId) {
  if (!serverInstanceId || !deviceId) {
    throw new Error('credential namespace requires server_instance_id and device_id');
  }
  return `${serverInstanceId}:${deviceId}`;
}
