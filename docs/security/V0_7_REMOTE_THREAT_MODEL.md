# Interest Growth v0.7 — Remote Threat Model (Gate A, frozen)

Single-owner, multi-device self-hosted deployment. This is the reference
threat model for the v0.7 remote authentication and device-session design.
It is additive to `11_SECURITY_AND_PRIVACY.md` and `V0_7_RUNTIME_CONTRACT.md`.

## 1. Assets

| Asset | Where it lives | Sensitivity |
|---|---|---|
| Owner password | only as salted hash in server DB | high |
| Access credential (short-lived) | client memory; SHA-256 hash on server | medium |
| Renewal credential (per-device) | OS secure storage / secure cookie; SHA-256 hash on server | high |
| Provider secrets | server environment/secret store only | high |
| Canonical DB + Sources + Artifacts | server persistent volumes | high (personal learning/reflection) |
| Security events | server DB | medium (bounded metadata) |
| Per-launch desktop token | local sidecar process pair only | low (loopback only) |

## 2. Trust boundaries

1. **TLS boundary**: an external reverse proxy terminates client-facing
   HTTPS/WSS. Its trusted loopback or private container-network hop to the API
   may use HTTP; Uvicorn is never bound directly to an untrusted network.
2. **Auth boundary**: every non-health HTTP route and every WebSocket
   connection must present a valid device session before any product code
   runs.
3. **Interest Area boundary**: Area scoping answers "where does the owner's
   work belong"; it is not account authorization and never substitutes for
   session authentication.
4. **Provider boundary**: model-provider calls originate server-side; client
   JavaScript never receives provider secrets.
5. **Local desktop boundary**: the per-launch desktop token authenticates a
   shell to its own loopback sidecar. It is never used as remote identity.

## 3. Assumptions

- The server host is operated by the owner (single-owner deployment).
- The operator keeps the server OS, Docker engine, TLS certificates and
  `.env` secrets under their control and applies updates.
- The owner password is strong and unique; it is the master secret that can
  register devices and revoke them.
- Clients are the owner's own devices. Android unknown-source install is the
  user's explicit choice, and APKs are signed by the project key.

## 4. Attacker model

| Adversary | Capabilities | Mitigations |
|---|---|---|
| Unauthenticated network attacker (LAN/Internet) | send HTTP/WS requests | mandatory device auth on all non-health routes; rate limits; TLS; no open registration |
| Brute-force / credential stuffing | many login attempts | per-IP rate limiting, bounded attempts, security events |
| Stolen access credential | use a short-lived token before expiry | short TTL (default 15 min); revocation; hashes at rest |
| Stolen renewal credential | refresh to get a new pair | per-device rotation: each refresh invalidates the previous renewal credential; device revocation kills the path |
| Compromised one device | act as that device | per-device revocation without breaking other devices; no cross-device secret material |
| Replay attacker | re-send captured requests | TLS 1.2+; credentials never in URLs/logs; CORS is not auth |
| Malicious remote web page | drive the renderer | secure cookie semantics; narrow CORS origins; CSP without provider endpoints |
| Server compromise | read DB/files | password/token hashes only; provider secrets not in DB; backup is one consistency unit |

## 5. Authentication design decisions

- **Single owner, many devices.** Owner password creates the first device;
  there is no public registration endpoint. `PG_OWNER_BOOTSTRAP_TOKEN` gates
  the one-time owner creation so an uninitialized server cannot be claimed by
  whoever reaches it first.
- **Short-lived access + rotated renewal.** Access credentials expire in a
  bounded window. Renewal credentials are single-use: a refresh issues a new
  pair and invalidates the previous renewal credential.
- **Hash-at-rest only.** Passwords use a salted memory-hard KDF (scrypt).
  Tokens are stored as SHA-256 digests; the plaintext value exists only in
  the issuing response and client secure storage.
- **Per-device revocation.** Revoking a device invalidates that device's
  renewal path and its outstanding access credentials without touching other
  devices. Only the owner password (or a device revoking itself with its own
  credential) can revoke.
- **Rate limits and security events.** Login/bootstrap/refresh are rate
  limited per client IP; authentication events are recorded with bounded
  metadata and never contain passwords, tokens or request bodies.
- **WebSocket handshakes re-authenticate.** The same device access check
  applies to WebSocket upgrade requests before any message is processed.

## 6. Deployment profiles and TLS requirements

| Profile | Exposure | TLS | Notes |
|---|---|---|---|
| Loopback (default Compose) | 127.0.0.1 only | not required | local Docker/proxy upstream; never exposed to LAN/Internet |
| LAN-only | trusted private subnet | required at client-facing reverse proxy | personal/team use inside home/office |
| VPN | trusted private network | required at client-facing reverse proxy | recommended before public exposure |
| Public Internet | any network | required, valid certificate, no insecure downgrade | most demanding; requires all controls below |

Remote profile requirements (frozen):

- Client-facing HTTPS/WSS behind a TLS reverse proxy with a valid certificate;
  no HTTP→HTTPS downgrade of authenticated traffic. Plain HTTP is allowed only
  on loopback or the private proxy-to-container network.
- The default remote Compose profile publishes API/UI HTTP only on
  `127.0.0.1`; an external Nginx/Caddy edge forwards to those ports.
- The edge overwrites forwarded client-IP/scheme headers. The API trusts those
  headers only because the remote profile remains loopback-bound; changing
  `REMOTE_BIND` to a public/LAN address violates this deployment boundary.
- Strict origin/host allow-list; authentication on every non-health route.
- Bounded request/upload sizes and timeouts.
- Secret injection via environment/secret store, never image or source.
- Restart policy, health checks and a consistent backup job.
- Server-version compatibility metadata checked by clients before enrollment.

## 7. Logging and audit

- Security events record: event type, timestamp, client IP (when available),
  device id (when known), bounded metadata. They never record passwords,
  token values, provider secrets or sensitive request bodies.
- Product logs do not include credentials or renewal material.
- The event log is bounded (retention/pruning) to avoid unbounded growth.

## 8. Residual risks

1. OS-user compromise of the server host defeats server-side controls; the
   owner must secure the host.
2. A device that is lost before its renewal credential is revoked remains a
   valid session until revocation; revocation is the recovery path.
3. Self-hosting does not make the deployment automatically secure; the
   deployment profile checklist must be followed.
4. This model assumes the server is the single writer. Horizontal replicas,
   offline mutation queues and multi-tenancy require a new explicit threat
   model before implementation.
