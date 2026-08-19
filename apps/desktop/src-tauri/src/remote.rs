// Gate D §D3/D4 — native remote credential broker + HTTP transport.
//
// The refresh credential never leaves this process: it is stored in the OS
// keyring (keyed server_instance_id:device_id) and only ever read here. The
// renderer submits RELATIVE API paths only; the base origin comes from the
// verified enrollment profile, never from arbitrary renderer input.
//
// Security properties (Gate C §7/§10/§11/§12, Gate D §P1–§P17):
// - No `get_refresh_token() → JS` readback. The renderer never receives the
//   refresh credential and does not even receive the access token: all HTTP
//   is performed here with the Bearer header attached natively.
// - Redirects are fail-closed: no 3xx is ever followed, so a credential-bearing
//   POST cannot be transparently forwarded to another host (P1).
// - Every probe merges `/api/system/capabilities` with `/api/auth/server-info`
//   and rejects inconsistent public metadata (P3).
// - Compatibility is enforced natively before any credential is sent (P2/P4):
//   wrong product / API version / minimum client / runtime / auth mode → block.
// - Stored credentials are only used after an automatic identity preflight
//   against the probed server_instance_id (P5). A replaced server behind the
//   same URL is rejected before the refresh credential leaves the process.
// - Refresh is single-flight: concurrent callers share one rotation (P7) and a
//   rotation that fails to persist to the keyring keeps an in-memory
//   replacement so the only valid credential is never lost (P8). A login whose
//   enrollment profile cannot be saved cleans up the freshly written keyring
//   secret (P9).
// - Renderer-supplied request headers are a positive allowlist (P15); the
//   response only surfaces a safe metadata allowlist (P16); uploads are bounded
//   before and after base64 decoding (P17).

use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use base64::Engine;
#[cfg(not(target_os = "android"))]
use keyring::v1::Entry;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

use crate::{DesktopState, KEYRING_SERVICE};

const ENROLLMENT_FILE: &str = "remote-enrollment.json";
const REMOTE_REFRESH_USER_PREFIX: &str = "remote-refresh";
const CLIENT_APP_VERSION: &str = env!("CARGO_PKG_VERSION");
const ACCESS_TOKEN_GRACE_SECS: i64 = 30;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(45);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(15);

// Frozen compatibility contract (Gate C §8, Gate D §P2/§P4).
const API_PRODUCT: &str = "interest-growth";
const SUPPORTED_API_VERSION: &str = "1";
const RUNTIME_DESKTOP_REMOTE: &str = "desktop-remote";
// Gate R0.3 — the Android shell is its own remote runtime: it must NOT borrow
// desktop-remote to "coincidentally pass" compatibility. A server must
// advertise the exact runtime the client actually runs.
const RUNTIME_ANDROID_REMOTE: &str = "android-remote";
const AUTH_MODE_SINGLE_OWNER_DEVICES: &str = "single_owner_devices";

/// Gate R0.3 — the shipped native remote runtimes. Both require the same
/// frozen auth/transport contract (auth enabled, single-owner-devices,
/// online-first, no offline sync). browser-remote is not a shipped native
/// runtime in this binary.
pub(crate) fn is_remote_runtime_id(runtime_id: &str) -> bool {
    runtime_id == RUNTIME_DESKTOP_REMOTE || runtime_id == RUNTIME_ANDROID_REMOTE
}

// Gate D §P17 — upload bound matches the server product limit (100 MiB).
const MAX_UPLOAD_BYTES: usize = 100 * 1024 * 1024;

// Gate D §9.3 — native API requests only accept the frozen HTTP method set.
// Arbitrary method strings must never reach reqwest.
const ALLOWED_HTTP_METHODS: &[&str] = &["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"];

// ------------------------------------------------------------ error codes
//
// Gate D §P26 — stable remote error taxonomy. The renderer must never guess
// state from fuzzy message text; every remote error carries one of these
// codes in a `{"code": "...", "message": "..."}` payload. Errors never
// contain a password, access token, refresh token or bootstrap token.
pub const ERR_NETWORK_UNAVAILABLE: &str = "NETWORK_UNAVAILABLE";
pub const ERR_RATE_LIMITED: &str = "RATE_LIMITED";
pub const ERR_SERVER_UNAVAILABLE: &str = "SERVER_UNAVAILABLE";
pub const ERR_LOGIN_EXPIRED: &str = "LOGIN_EXPIRED";
pub const ERR_IDENTITY_CHANGED: &str = "IDENTITY_CHANGED";
pub const ERR_UPDATE_REQUIRED: &str = "UPDATE_REQUIRED";
pub const ERR_UNSUPPORTED_SERVER: &str = "UNSUPPORTED_SERVER";
pub const ERR_CREDENTIAL_PERSISTENCE: &str = "CREDENTIAL_PERSISTENCE_FAILURE";
pub const ERR_PROTOCOL: &str = "PROTOCOL_ERROR";
pub const ERR_RUNTIME_MODE_DENIED: &str = "RUNTIME_MODE_DENIED";
pub const ERR_INTERNAL: &str = "INTERNAL_ERROR";
#[cfg(test)]
const RUNTIME_MODE_DENIED_PAYLOAD: &str = "\"code\":\"RUNTIME_MODE_DENIED\"";

pub fn remote_error(code: &str, message: impl Into<String>) -> String {
    serde_json::json!({ "code": code, "message": message.into() }).to_string()
}

// ------------------------------------------------------ HTTP status taxonomy

/// Endpoint classes used by the unified HTTP status classifier (HIGH-1). Each
/// producer maps a non-success HTTP status to the frozen taxonomy in ONE
/// place, so no per-endpoint hand-written `if status != ...` can drift into
/// mis-classifying a transient 429/5xx as a permanent credential/protocol
/// failure (which previously produced `429 -> UnsupportedServer` on metadata
/// and `429/500/503 -> LOGIN_EXPIRED` on login).
#[derive(Clone, Copy, PartialEq, Eq)]
enum EndpointKind {
    /// Unauthenticated server metadata (capabilities / server-info). No
    /// credential is involved, so an auth status here is a protocol error.
    Metadata,
    /// Owner login / bootstrap. Success status is 201.
    Login,
    /// Device refresh. Success status is 200; 401/403 is a real credential
    /// denial (LoginExpired).
    Refresh,
    /// Authenticated business calls (success 200; 401 handled separately in
    /// `send_with_auth`). Kept so the classifier is the single source.
    Business,
}

impl EndpointKind {
    fn expected_success(self) -> u16 {
        match self {
            EndpointKind::Login => 201,
            EndpointKind::Metadata
            | EndpointKind::Refresh
            | EndpointKind::Business => 200,
        }
    }
}

/// Unify non-success HTTP status -> frozen taxonomy code (HIGH-1).
///
/// Returns `Ok(())` when `status` equals the endpoint's success code,
/// otherwise the correct taxonomy code:
///
/// - `429`                     -> RATE_LIMITED
/// - `500..=599`               -> SERVER_UNAVAILABLE
/// - `401 | 403`               -> LOGIN_EXPIRED (Refresh/Login/Business) or
///                                PROTOCOL_ERROR (Metadata, no credential)
/// - `300..=399` and everything else -> PROTOCOL_ERROR
///
/// `429` and `5xx` are transient and are NEVER mapped to LOGIN_EXPIRED,
/// UNSUPPORTED_SERVER or another terminal state.
fn classify_http_status(kind: EndpointKind, status: u16) -> Result<(), &'static str> {
    if status == kind.expected_success() {
        return Ok(());
    }
    match status {
        429 => Err(ERR_RATE_LIMITED),
        500..=599 => Err(ERR_SERVER_UNAVAILABLE),
        401 | 403 if kind != EndpointKind::Metadata => Err(ERR_LOGIN_EXPIRED),
        300..=399 => Err(ERR_PROTOCOL),
        _ => Err(ERR_PROTOCOL),
    }
}

// §11 — durable refresh slot generation envelope.
//
// Every durable refresh rotation stamps the credential with a monotonically
// increasing `gen` so the two-slot crash-recovery design can PROVE that a
// stale PENDING value can never shadow a promoted ACTIVE value:
//
//   * WAL crash window (pending written, active not): pending.gen > active.gen
//     -> the reader prefers pending (it is the newest un-promoted intent).
//   * Stale-pending case (an earlier pending write failed, then active got
//     promoted, then the clear also failed): the leftover pending is a legacy
//     raw token parsed as gen 0 (or an older gen) while the promoted active
//     has a strictly higher gen -> the reader prefers active.
//
// The active slot keeps the legacy raw-token form for existing rc1 installs
// (a raw value decodes as gen 0 and is still the reader's fallback).
const REFRESH_ENVELOPE_PREFIX: &str = "gen:";

/// Encode a rotation replacement with an explicit generation.
fn encode_refresh_envelope(gen: u64, token: &str) -> String {
    format!("{REFRESH_ENVELOPE_PREFIX}{gen}\n{token}")
}

/// Decode a stored durable slot value into `(generation, token)`. A legacy raw
/// token (no envelope) decodes as generation `0` with the whole value as the
/// token, so existing installs remain readable without migration.
fn decode_refresh_envelope(value: &str) -> (u64, &str) {
    let value = value.trim();
    if let Some(rest) = value.strip_prefix(REFRESH_ENVELOPE_PREFIX) {
        if let Some((gen_str, token)) = rest.split_once('\n') {
            if gen_str.trim().parse::<u64>().is_ok() && !token.is_empty() {
                return (gen_str.trim().parse::<u64>().unwrap_or(0), token);
            }
        }
    }
    (0, value)
}

/// Classify a durable slot read: `Ok(Some((gen, token)))` on a readable non-empty
/// value, `Ok(None)` for an absent/empty slot, and a persistence failure for a
/// classified store error (a locked/unavailable backend is NEVER "no credential").
fn read_refresh_slot(
    result: Result<Option<String>, CredentialStoreError>,
) -> Result<Option<(u64, String)>, String> {
    match result {
        Ok(Some(value)) if !value.trim().is_empty() => {
            let (gen, token) = decode_refresh_envelope(&value);
            if token.is_empty() {
                Ok(None)
            } else {
                Ok(Some((gen, token.to_string())))
            }
        }
        Ok(_) => Ok(None),
        Err(error) => Err(remote_error(
            ERR_CREDENTIAL_PERSISTENCE,
            format!("secure store is unavailable: {error}"),
        )),
    }
}

// Gate D §P15 — the ONLY request headers a renderer may set on the native
// remote transport. Content-Type is decided natively by the body kind and
// Authorization is always native.
const ALLOWED_REQUEST_HEADERS: &[&str] = &[
    "accept",
    "x-pg-interest-area",
    "range",
    "if-none-match",
    "if-modified-since",
];

// Gate D §P16 — safe response metadata surfaced to the renderer. Sensitive
// headers (Set-Cookie, Authorization, internal values) are never forwarded.
const ALLOWED_RESPONSE_HEADERS: &[&str] = &[
    "content-type",
    "content-disposition",
    "content-length",
    "etag",
    "last-modified",
    "accept-ranges",
];

// --------------------------------------------------------------- types

/// Non-secret identity a client persists about a server (Gate C §6.4).
/// Never contains a password, access token or refresh token.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteEnrollment {
    pub normalized_origin: String,
    pub server_instance_id: String,
    pub server_display_name: String,
    pub product: String,
    pub api_version: String,
    pub server_version: String,
    pub min_client_version: String,
    pub device_id: String,
    pub device_name: String,
    pub platform: String,
    pub app_version: String,
    pub last_verified_at: String,
}

/// Short-lived access credential kept in memory only.
///
/// `generation` is bumped on every rotation so a 401 handler can tell whether
/// another caller already replaced the access credential it used (Gate D
/// §P7): "generation newer than the snapshot I sent with → reuse, never
/// re-refresh"; "same generation → force a rotation, never reuse the token
/// the server just rejected".
#[derive(Clone, Debug, Default)]
pub struct RemoteSession {
    pub access_token: String,
    pub expires_at_unix: i64,
    pub generation: u64,
}

/// The access generation a request was sent with, captured so the 401
/// recovery path can decide between reuse (another caller rotated) and a
/// forced rotation (this request's own token was rejected). Generation is
/// sufficient: every session write bumps it, so equal generation implies the
/// same access credential.
#[derive(Clone, Debug)]
struct TokenSnapshot {
    generation: u64,
}

/// One completed remote HTTP exchange plus the access snapshot it used.
struct SentRequest {
    status: u16,
    bytes: Vec<u8>,
    content_type: String,
    response_headers: HashMap<String, String>,
    access_snapshot: TokenSnapshot,
}

/// Gate R0.6 — result of streaming an artifact download into a bounded
/// app-private temp file. The bytes stay on disk (never a full base64 Vec);
/// only status + metadata are surfaced and `access_snapshot` drives the single
/// 401 refresh-recovery.
#[derive(Clone, Debug)]
pub(crate) struct DownloadedExport {
    status: u16,
    content_type: String,
    response_headers: HashMap<String, String>,
    access_snapshot: TokenSnapshot,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteServerInfo {
    pub product: String,
    pub server_version: String,
    pub api_version: String,
    pub min_client_version: String,
    pub server_instance_id: String,
    pub server_display_name: String,
    pub runtime_modes: Vec<String>,
    pub auth_mode: String,
    pub auth_enabled: bool,
    pub owner_configured: bool,
    pub tls: bool,
    pub online_first: bool,
    pub offline_sync: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteProbeResult {
    pub normalized_origin: String,
    pub server: RemoteServerInfo,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteLoginResult {
    pub device_id: String,
    pub device_name: String,
    pub server_instance_id: String,
    pub server_display_name: String,
    pub server_version: String,
    pub api_version: String,
    pub min_client_version: String,
    pub expires_in: u64,
    pub refresh_stored: bool,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteSessionStatus {
    pub enrolled: bool,
    pub connected: bool,
    pub auth_expired: bool,
    pub refresh_token_stored: bool,
    pub normalized_origin: String,
    pub server_instance_id: String,
    pub server_display_name: String,
    pub device_id: String,
    pub device_name: String,
    pub server_version: String,
    pub api_version: String,
    pub min_client_version: String,
    pub platform: String,
    pub app_version: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteApiResponse {
    pub status: u16,
    pub body_base64: String,
    pub content_type: String,
    pub response_headers: HashMap<String, String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteLogoutResult {
    pub logged_out: bool,
    pub revoked: bool,
}

/// Injectable refresh-credential store. The real desktop build uses the OS
/// keyring; tests use an in-memory store with failure injection.
///
/// Gate D §P8 — the store is TWO-SLOT so a server-side rotation survives a
/// process crash even when the active write fails:
/// - `pending` receives the rotated replacement FIRST (write order), then the
///   replacement is promoted to `active`, then `pending` is cleared;
/// - reads prefer `pending` (the newest known-valid credential);
/// - the ACTIVE slot keeps the historical `remote-refresh:<server>:<device>`
///   username so existing installed keyring entries stay readable (exact
///   migration compatibility). The pending slot uses the same namespace with
///   a `:pending` suffix.
/// Multi-key keyring operations are not assumed atomic; every step reports
/// its own failure and the read order is what provides crash recovery.
pub trait CredentialStore: Send + Sync {
    /// Active slot: the last successfully promoted credential. `Ok(None)`
    /// means no entry exists; an `Err` means the store itself failed (locked,
    /// backend unavailable, permission denied) and must NOT be treated as
    /// "no credential / please log in" (Gate C/D §4.5).
    fn read_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<Option<String>, CredentialStoreError>;
    /// Pending slot: a rotated replacement that has not yet been promoted.
    fn read_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<Option<String>, CredentialStoreError>;
    /// Promote a replacement into the active slot.
    fn write_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
        token: &str,
    ) -> Result<(), String>;
    /// Stage a rotated replacement in the pending slot.
    fn write_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
        token: &str,
    ) -> Result<(), String>;
    /// Clear the pending slot after promotion.
    fn clear_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<(), String>;
    /// Remove every slot for this server/device (logout).
    fn delete_refresh(&self, server_instance_id: &str, device_id: &str) -> Result<(), String>;
}

/// Gate C/D §4.5 — classified credential-store read failures. `NoEntry` means
/// the key simply does not exist (→ LoginExpired / re-login). Everything else
/// is a store/backend problem (→ CREDENTIAL_PERSISTENCE_FAILURE) so the client
/// never falsely demands a re-login when the OS keychain is merely locked or
/// its backend is unavailable.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CredentialStoreError {
    /// The key does not exist in the store.
    NoEntry,
    /// The secure-store backend is unavailable (keychain/secret-service down).
    BackendUnavailable,
    /// The process/account is not allowed to access the credential.
    PermissionDenied,
    /// The stored value is present but not a usable credential.
    CorruptCredential,
    /// Any other store error.
    Other(String),
}

impl std::fmt::Display for CredentialStoreError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CredentialStoreError::NoEntry => write!(formatter, "no entry"),
            CredentialStoreError::BackendUnavailable => write!(formatter, "store backend unavailable"),
            CredentialStoreError::PermissionDenied => write!(formatter, "permission denied"),
            CredentialStoreError::CorruptCredential => write!(formatter, "corrupt credential"),
            CredentialStoreError::Other(detail) => write!(formatter, "{detail}"),
        }
    }
}

/// Gate C/D §4.5 — map a keyring error to a classified store error so a read
/// that fails because the OS keychain is locked/unavailable is never mistaken
/// for "no credential stored".
#[cfg(not(target_os = "android"))]
fn classify_store_error(error: keyring::Error) -> CredentialStoreError {
    use keyring::Error;
    match error {
        Error::NoEntry => CredentialStoreError::NoEntry,
        Error::NoStorageAccess(_) | Error::PlatformFailure(_) => {
            CredentialStoreError::BackendUnavailable
        }
        Error::BadEncoding(_) | Error::BadDataFormat(..) | Error::BadStoreFormat(_) => {
            CredentialStoreError::CorruptCredential
        }
        Error::Invalid(parameter, _) if parameter.eq_ignore_ascii_case("credential") => {
            CredentialStoreError::PermissionDenied
        }
        Error::NoDefaultStore => CredentialStoreError::BackendUnavailable,
        other => CredentialStoreError::Other(other.to_string()),
    }
}

/// OS keyring backed store (desktop only). One refresh credential per server
/// per device. The active slot keeps the legacy `remote-refresh:<server>:<device>`
/// key so existing installs read their stored credential without any migration.
#[cfg(not(target_os = "android"))]
pub struct KeyringStore;

fn active_username(server_instance_id: &str, device_id: &str) -> String {
    remote_refresh_username(server_instance_id, device_id)
}

fn pending_username(server_instance_id: &str, device_id: &str) -> String {
    format!(
        "{}:pending",
        remote_refresh_username(server_instance_id, device_id)
    )
}

#[cfg(not(target_os = "android"))]
impl CredentialStore for KeyringStore {
    fn read_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<Option<String>, CredentialStoreError> {
        let entry = Entry::new(KEYRING_SERVICE, &active_username(server_instance_id, device_id))
            .map_err(classify_store_error)?;
        match entry.get_password() {
            Ok(value) => Ok(Some(value.trim().to_string()).filter(|v| !v.is_empty())),
            Err(error) if matches!(error, keyring::Error::NoEntry) => Ok(None),
            Err(error) => Err(classify_store_error(error)),
        }
    }

    fn read_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<Option<String>, CredentialStoreError> {
        let entry = Entry::new(KEYRING_SERVICE, &pending_username(server_instance_id, device_id))
            .map_err(classify_store_error)?;
        match entry.get_password() {
            Ok(value) => Ok(Some(value.trim().to_string()).filter(|v| !v.is_empty())),
            Err(error) if matches!(error, keyring::Error::NoEntry) => Ok(None),
            Err(error) => Err(classify_store_error(error)),
        }
    }

    fn write_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
        token: &str,
    ) -> Result<(), String> {
        Entry::new(KEYRING_SERVICE, &active_username(server_instance_id, device_id))
            .map_err(|error| error.to_string())?
            .set_password(token)
            .map_err(|error| error.to_string())
    }

    fn write_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
        token: &str,
    ) -> Result<(), String> {
        Entry::new(KEYRING_SERVICE, &pending_username(server_instance_id, device_id))
            .map_err(|error| error.to_string())?
            .set_password(token)
            .map_err(|error| error.to_string())
    }

    fn clear_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<(), String> {
        let entry = Entry::new(KEYRING_SERVICE, &pending_username(server_instance_id, device_id))
            .map_err(|error| error.to_string())?;
        if entry.get_password().is_ok() {
            entry.delete_credential().map_err(|error| error.to_string())?;
        }
        Ok(())
    }

    fn delete_refresh(&self, server_instance_id: &str, device_id: &str) -> Result<(), String> {
        for username in [
            active_username(server_instance_id, device_id),
            pending_username(server_instance_id, device_id),
        ] {
            let entry = Entry::new(KEYRING_SERVICE, &username)
                .map_err(|error| error.to_string())?;
            if entry.get_password().is_ok() {
                entry.delete_credential().map_err(|error| error.to_string())?;
            }
        }
        Ok(())
    }
}

/// Gate C/D §4.5 — file-backed credential store for HEADLESS harness only
/// (`desktop-native-harness` feature). The production desktop build always uses
/// the OS keyring (`KeyringStore`); Android always uses the Keystore. This
/// plaintext file store exists solely so the CI cross-device gate can run a
/// REAL `RemoteBroker` on a headless Linux runner that has no keyring daemon.
/// It is explicitly NOT a production credential store and must never be
/// selected by product code. The token is written with the platform temp-file
/// pattern (write + rename) and the file mode is tightened to 0600.
#[cfg(all(feature = "desktop-native-harness", not(target_os = "android")))]
pub struct FileCredentialStore {
    path: std::path::PathBuf,
}

#[cfg(all(feature = "desktop-native-harness", not(target_os = "android")))]
impl FileCredentialStore {
    pub fn new(path: impl Into<std::path::PathBuf>) -> Self {
        Self {
            path: path.into(),
        }
    }

    fn read_slot(&self, username: &str) -> Result<Option<String>, CredentialStoreError> {
        let map = read_store_map(&self.path)?;
        Ok(map.get(username).cloned().filter(|value| !value.trim().is_empty()))
    }

    fn write_slot(&self, username: &str, token: &str) -> Result<(), String> {
        write_store_slot(&self.path, username, token.to_string())
    }

    fn delete_slot(&self, username: &str) -> Result<(), String> {
        remove_store_slot(&self.path, username)
    }
}

#[cfg(all(feature = "desktop-native-harness", not(target_os = "android")))]
impl CredentialStore for FileCredentialStore {
    fn read_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<Option<String>, CredentialStoreError> {
        self.read_slot(&active_username(server_instance_id, device_id))
    }

    fn read_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<Option<String>, CredentialStoreError> {
        self.read_slot(&pending_username(server_instance_id, device_id))
    }

    fn write_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
        token: &str,
    ) -> Result<(), String> {
        self.write_slot(&active_username(server_instance_id, device_id), token)
    }

    fn write_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
        token: &str,
    ) -> Result<(), String> {
        self.write_slot(&pending_username(server_instance_id, device_id), token)
    }

    fn clear_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<(), String> {
        self.delete_slot(&pending_username(server_instance_id, device_id))
    }

    fn delete_refresh(&self, server_instance_id: &str, device_id: &str) -> Result<(), String> {
        self.delete_slot(&active_username(server_instance_id, device_id))?;
        self.delete_slot(&pending_username(server_instance_id, device_id))
    }
}

/// Read the whole plaintext store map. A missing file is an empty map (all
/// reads return `Ok(None)`), never an error — the store itself failing to load
/// is classified as `Other` so it can never be mistaken for "no credential".
#[cfg(all(feature = "desktop-native-harness", not(target_os = "android")))]
fn read_store_map(path: &std::path::Path) -> Result<HashMap<String, String>, CredentialStoreError> {
    match std::fs::read_to_string(path) {
        Ok(raw) if raw.trim().is_empty() => Ok(HashMap::new()),
        Ok(raw) => serde_json::from_str(&raw)
            .map_err(|error| CredentialStoreError::Other(format!("store corrupt: {error}"))),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(HashMap::new()),
        Err(error) => Err(CredentialStoreError::Other(format!("store unreadable: {error}"))),
    }
}

#[cfg(all(feature = "desktop-native-harness", not(target_os = "android")))]
fn write_store_slot(path: &std::path::Path, username: &str, value: String) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    let mut map = read_store_map(path).map_err(|error| error.to_string())?;
    map.insert(username.to_string(), value);
    let payload = serde_json::to_vec_pretty(&map).map_err(|error| error.to_string())?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let temp = path.with_extension("tmp");
    std::fs::write(&temp, payload).map_err(|error| error.to_string())?;
    let _ = std::fs::set_permissions(&temp, std::fs::Permissions::from_mode(0o600));
    std::fs::rename(&temp, path).map_err(|error| error.to_string())
}

#[cfg(all(feature = "desktop-native-harness", not(target_os = "android")))]
fn remove_store_slot(path: &std::path::Path, username: &str) -> Result<(), String> {
    let mut map = read_store_map(path).map_err(|error| error.to_string())?;
    if map.remove(username).is_some() {
        let payload = serde_json::to_vec_pretty(&map).map_err(|error| error.to_string())?;
        let temp = path.with_extension("tmp");
        std::fs::write(&temp, payload).map_err(|error| error.to_string())?;
        std::fs::rename(&temp, path).map_err(|error| error.to_string())?;
    }
    Ok(())
}

/// Gate E §6.4 — Android OS-backed secure credential store. Wraps the Android
/// Keystore-backed store (android-native-keyring-store): the refresh credential
/// is encrypted and persisted to app-private SharedPreferences with the key
/// held in the hardware/OS Android Keystore. The credential never touches
/// localStorage, plain-text SharedPreferences, or the renderer, and is only
/// ever read/written inside the native Rust broker. Requires the NDK
/// application context, which Tauri Android initializes automatically at
/// startup before setup() runs.
#[cfg(target_os = "android")]
pub struct AndroidKeystoreStore {
    store: Arc<keyring_android::Store>,
}

#[cfg(target_os = "android")]
impl AndroidKeystoreStore {
    pub fn new() -> Result<Arc<Self>, String> {
        let store = keyring_android::Store::new()
            .map_err(|error| format!("failed to open Android Keystore store: {error}"))?;
        Ok(Arc::new(Self { store }))
    }

    fn entry(&self, username: &str) -> Result<keyring_core::Entry, CredentialStoreError> {
        use keyring_core::api::CredentialStoreApi;
        self.store
            .build(KEYRING_SERVICE, username, None)
            .map_err(classify_keyring_core_error)
    }

    fn read_username(&self, username: &str) -> Result<Option<String>, CredentialStoreError> {
        let entry = self.entry(username)?;
        match entry.get_secret() {
            Ok(bytes) => {
                let value = String::from_utf8(bytes).unwrap_or_default();
                Ok(Some(value.trim().to_string()).filter(|v| !v.is_empty()))
            }
            Err(keyring_core::Error::NoEntry) => Ok(None),
            Err(error) => Err(classify_keyring_core_error(error)),
        }
    }

    fn write_username(&self, username: &str, token: &str) -> Result<(), String> {
        self.entry(username)
            .map_err(|error| error.to_string())?
            .set_secret(token.as_bytes())
            .map_err(|error| error.to_string())
    }

    fn delete_username(&self, username: &str) -> Result<(), String> {
        let entry = self.entry(username).map_err(|error| error.to_string())?;
        if entry.get_secret().is_ok() {
            entry.delete_credential().map_err(|error| error.to_string())?;
        }
        Ok(())
    }
}

#[cfg(target_os = "android")]
impl CredentialStore for AndroidKeystoreStore {
    fn read_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<Option<String>, CredentialStoreError> {
        self.read_username(&active_username(server_instance_id, device_id))
    }

    fn read_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<Option<String>, CredentialStoreError> {
        self.read_username(&pending_username(server_instance_id, device_id))
    }

    fn write_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
        token: &str,
    ) -> Result<(), String> {
        self.write_username(&active_username(server_instance_id, device_id), token)
    }

    fn write_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
        token: &str,
    ) -> Result<(), String> {
        self.write_username(&pending_username(server_instance_id, device_id), token)
    }

    fn clear_pending_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
    ) -> Result<(), String> {
        self.delete_username(&pending_username(server_instance_id, device_id))
    }

    fn delete_refresh(&self, server_instance_id: &str, device_id: &str) -> Result<(), String> {
        for username in [
            active_username(server_instance_id, device_id),
            pending_username(server_instance_id, device_id),
        ] {
            self.delete_username(&username)?;
        }
        Ok(())
    }
}

/// Gate E §6.4 — classify an Android Keystore (keyring-core) error identically
/// to the desktop keyring classification so a locked/unavailable Keystore is
/// never misread as "no credential stored".
#[cfg(target_os = "android")]
fn classify_keyring_core_error(error: keyring_core::Error) -> CredentialStoreError {
    use keyring_core::Error;
    match error {
        Error::NoEntry => CredentialStoreError::NoEntry,
        Error::NoStorageAccess(_) | Error::PlatformFailure(_) | Error::NoDefaultStore => {
            CredentialStoreError::BackendUnavailable
        }
        Error::BadEncoding(_) | Error::BadDataFormat(..) | Error::BadStoreFormat(_) => {
            CredentialStoreError::CorruptCredential
        }
        Error::Invalid(parameter, _) if parameter.eq_ignore_ascii_case("credential") => {
            CredentialStoreError::PermissionDenied
        }
        other => CredentialStoreError::Other(other.to_string()),
    }
}

/// Shared mutable broker state owned by the app. The session is split from the
/// credential store so tests can construct a real broker without Tauri.
pub struct RemoteBrokerState {
    pub session: tokio::sync::Mutex<Option<RemoteSession>>,
    /// Serializes refresh so concurrent requests share exactly one rotation.
    pub refresh_lock: tokio::sync::Mutex<()>,
    /// In-memory replacement refresh credential when the keyring write failed
    /// after a server-side rotation (P8). Never exposed to the renderer.
    pub pending_refresh: tokio::sync::Mutex<Option<String>>,
    /// True ONLY after the server explicitly denied the refresh credential
    /// (invalid/expired/revoked). It is never inferred from "no access token":
    /// a normal restart with a stored refresh credential is NOT LoginExpired.
    pub refresh_denied: tokio::sync::Mutex<bool>,
}

impl Default for RemoteBrokerState {
    fn default() -> Self {
        Self::new()
    }
}

impl RemoteBrokerState {
    pub fn new() -> Self {
        Self {
            session: tokio::sync::Mutex::new(None),
            refresh_lock: tokio::sync::Mutex::new(()),
            pending_refresh: tokio::sync::Mutex::new(None),
            refresh_denied: tokio::sync::Mutex::new(false),
        }
    }
}

/// The native remote broker: owns the HTTP client, the credential store and
/// the shared session state. Commands clone this out of `DesktopState`.
#[derive(Clone)]
pub struct RemoteBroker {
    pub client: reqwest::Client,
    pub store: Arc<dyn CredentialStore>,
    pub state: Arc<RemoteBrokerState>,
    // Gate R0.3 — the exact remote runtime this process runs
    // (desktop-remote / android-remote). Credential-bearing flows only accept a
    // server that advertises this runtime; the Android shell must not borrow
    // desktop-remote. Set from the ACTIVE mode at setup; the probe command
    // independently selects the expected runtime.
    expected_runtime_id: Arc<tokio::sync::Mutex<String>>,
}

// ------------------------------------------------------------- helpers

fn now_unix() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(0)
}

/// Keyring user namespace: one refresh credential per server per device.
/// Two different servers (or two devices on the same server) never share a key.
pub fn remote_refresh_username(server_instance_id: &str, device_id: &str) -> String {
    format!("{REMOTE_REFRESH_USER_PREFIX}:{server_instance_id}:{device_id}")
}

fn enrollment_path(app_data: &Path) -> PathBuf {
    app_data.join(ENROLLMENT_FILE)
}

fn load_enrollment(app_data: &Path) -> Option<RemoteEnrollment> {
    let raw = std::fs::read_to_string(enrollment_path(app_data)).ok()?;
    serde_json::from_str::<RemoteEnrollment>(&raw).ok()
}

fn save_enrollment(app_data: &Path, enrollment: &RemoteEnrollment) -> Result<(), String> {
    std::fs::create_dir_all(app_data).map_err(|error| error.to_string())?;
    let path = enrollment_path(app_data);
    let temp = path.with_extension("json.tmp");
    let payload = serde_json::to_vec_pretty(enrollment).map_err(|error| error.to_string())?;
    std::fs::write(&temp, payload).map_err(|error| error.to_string())?;
    std::fs::rename(&temp, &path).map_err(|error| error.to_string())
}

fn clear_enrollment(app_data: &Path) {
    let _ = std::fs::remove_file(enrollment_path(app_data));
}

/// Strict numeric dotted version (semver-lite). Every component is checked
/// parsed so a huge/corrupt value fails closed as PROTOCOL_ERROR instead of
/// silently becoming `0` (Gate C/D §4.3). `0.7.0 < 0.10.0`, `1.2 == 1.2.0`.
#[derive(Clone, Debug, PartialEq, Eq)]
struct ParsedVersion(Vec<u32>);

impl ParsedVersion {
    fn parse(value: &str) -> Result<ParsedVersion, String> {
        if !value.chars().all(|character| character.is_ascii_digit() || character == '.') {
            return Err(remote_error(
                ERR_PROTOCOL,
                format!("malformed version: {value}"),
            ));
        }
        let parts: Vec<&str> = value.split('.').collect();
        if parts.iter().any(|part| part.is_empty()) {
            return Err(remote_error(
                ERR_PROTOCOL,
                format!("malformed version: {value}"),
            ));
        }
        let mut numeric = Vec::with_capacity(parts.len());
        for part in parts {
            let component = part.parse::<u32>().map_err(|error| {
                remote_error(
                    ERR_PROTOCOL,
                    format!("version component overflows: {value} ({error})"),
                )
            })?;
            numeric.push(component);
        }
        Ok(ParsedVersion(numeric))
    }

    fn compare(&self, other: &ParsedVersion) -> std::cmp::Ordering {
        let left = &self.0;
        let right = &other.0;
        let length = left.len().max(right.len());
        for index in 0..length {
            let left_component = left.get(index).copied().unwrap_or(0);
            let right_component = right.get(index).copied().unwrap_or(0);
            let ordering = left_component.cmp(&right_component);
            if ordering != std::cmp::Ordering::Equal {
                return ordering;
            }
        }
        std::cmp::Ordering::Equal
    }
}

/// Numeric semver-lite comparison. Returns PROTOCOL_ERROR when either operand
/// is malformed or overflows so no caller can ever treat a bad version as
/// `0.0.0` (fail-closed, Gate C/D §4.3).
fn compare_versions(left: &str, right: &str) -> Result<std::cmp::Ordering, String> {
    let left = ParsedVersion::parse(left)?;
    let right = ParsedVersion::parse(right)?;
    Ok(left.compare(&right))
}

// Gate C §7 — enrollment origin normalization. Origin-only HTTPS; loopback
// HTTP only for explicit development/test. No userinfo, query, fragment or
// path. The client URL security problem (LAN/VPN self-hosting) is different
// from server-side SSRF rules, so private IPs are allowed.
pub fn normalize_enrollment_origin(value: &str) -> Result<String, String> {
    let trimmed = value.trim();
    let parsed = url::Url::parse(trimmed)
        .map_err(|error| remote_error(ERR_PROTOCOL, format!("invalid server URL: {error}")))?;
    if parsed.host_str().is_none() {
        return Err(remote_error(ERR_PROTOCOL, "server URL must include a host"));
    }
    if !parsed.username().is_empty() || parsed.password().is_some() {
        return Err(remote_error(
            ERR_PROTOCOL,
            "server URL must not contain embedded credentials",
        ));
    }
    let host = parsed.host_str().unwrap_or_default().to_ascii_lowercase();
    let loopback = host == "localhost" || host == "127.0.0.1" || host == "::1";
    let valid_scheme = parsed.scheme() == "https" || (parsed.scheme() == "http" && loopback);
    if !valid_scheme {
        return Err(remote_error(
            ERR_PROTOCOL,
            "server URL must use HTTPS, or loopback HTTP for development",
        ));
    }
    if parsed.query().is_some() || parsed.fragment().is_some() {
        return Err(remote_error(
            ERR_PROTOCOL,
            "server URL must not contain a query or fragment",
        ));
    }
    if parsed.path() != "/" && !parsed.path().is_empty() {
        return Err(remote_error(
            ERR_PROTOCOL,
            "server URL must be an origin without a path",
        ));
    }
    let authority = match parsed.host() {
        Some(url::Host::Ipv6(addr)) => format!("[{addr}]"),
        Some(host) => host.to_string(),
        None => String::new(),
    };
    let authority = if let Some(port) = parsed.port() {
        format!("{authority}:{port}")
    } else {
        authority
    };
    Ok(format!("{}://{authority}", parsed.scheme()))
}

// Gate C §12 — the renderer may only submit relative API paths. Absolute or
// protocol-relative URLs are rejected so the native transport can never be
// pointed at an arbitrary host by renderer input.
pub fn assert_relative_path(path: &str) -> Result<(), String> {
    if !path.starts_with('/') {
        return Err(remote_error(
            ERR_PROTOCOL,
            "remote transport only accepts relative API paths",
        ));
    }
    if path.starts_with("//") {
        return Err(remote_error(
            ERR_PROTOCOL,
            "remote transport rejects protocol-relative URLs",
        ));
    }
    if path.starts_with("/\\") {
        return Err(remote_error(
            ERR_PROTOCOL,
            "remote transport rejects backslash URLs",
        ));
    }
    let lower = path.to_ascii_lowercase();
    if lower.starts_with("http://") || lower.starts_with("https://") {
        return Err(remote_error(
            ERR_PROTOCOL,
            "remote transport rejects absolute URLs",
        ));
    }
    Ok(())
}

/// Shared HTTP client for all remote credential-bearing requests. Builds the
/// client and may carry an additional TLS trust root.
///
/// Gate C §12 / Gate D §P1: redirects are explicitly disabled (fail-closed).
/// A credential-bearing POST must never be transparently forwarded to a
/// redirect target — a 307/308 preserves method and body, and a 301/302/303
/// could still expose the custom bootstrap header. Any 3xx is surfaced as an
/// explicit error instead of being followed.
///
/// Phase 4d — CI-only optional trust root injection. The production broker uses
/// reqwest's rustls backend with the compiled Mozilla root set (this crate does
/// NOT enable rustls-platform-verifier / native-tls, so the Android OS trust
/// store is not consulted). For the upgrade-in-place CDP test the broker must
/// trust an ephemeral CI CA that fronts the self-hosted server over real
/// HTTPS. A loadable PEM root is added here; `None` keeps the exact production
/// behavior (fail-closed: nothing weakened when no root is injected).
fn http_client_with_trust_root(
    trust_root: Option<reqwest::Certificate>,
) -> Result<reqwest::Client, String> {
    let mut builder = reqwest::Client::builder()
        .timeout(REQUEST_TIMEOUT)
        .connect_timeout(CONNECT_TIMEOUT)
        .user_agent(format!("interest-growth-desktop/{CLIENT_APP_VERSION}"))
        .redirect(reqwest::redirect::Policy::none());
    if let Some(cert) = trust_root {
        builder = builder.add_root_certificate(cert);
    }
    builder.build().map_err(|error| error.to_string())
}

/// Load a PEM-encoded certificate as an additional TLS trust root.
///
/// Phase 4d. Fail-closed: an unreadable or invalid PEM is a hard error, never a
/// silent fallthrough to the default roots (an operator who opts into a custom
/// CA must not be silently degraded to no verification of that CA).
pub fn load_pem_trust_root(pem_path: &Path) -> Result<reqwest::Certificate, String> {
    let bytes = std::fs::read(pem_path)
        .map_err(|error| format!("cannot read TLS trust root {}: {error}", pem_path.display()))?;
    reqwest::Certificate::from_pem(&bytes)
        .map_err(|error| format!("invalid PEM TLS trust root {}: {error}", pem_path.display()))
}

/// Android: read a system property via bionic `__system_property_get`.
///
/// Phase 4d. Used only to opt the CI upgrade-test APK into loading an ephemeral
/// TLS trust root. `__system_property_get` is part of the always-linked bionic
/// libc; any app may read system properties, so this introduces no new
/// privilege. Reading an unset property returns `None`.
#[cfg(target_os = "android")]
pub fn android_system_property(name: &str) -> Option<String> {
    use std::ffi::{c_char, CStr, CString};
    // PROP_VALUE_MAX is 92 in bionic libc.
    let mut value = [0i8; 92];
    let name = CString::new(name).ok()?;
    extern "C" {
        fn __system_property_get(name: *const c_char, value: *mut c_char) -> i32;
    }
    // SAFETY: `name` is a valid NUL-terminated CString; `value` is a 92-byte
    // buffer that __system_property_get fills with a NUL-terminated string, so
    // reconstructing a CStr from it afterwards stays within bounds.
    let n = unsafe { __system_property_get(name.as_ptr(), value.as_mut_ptr()) };
    if n <= 0 {
        return None;
    }
    let text = unsafe { CStr::from_ptr(value.as_ptr()) }
        .to_string_lossy()
        .into_owned();
    if text.trim().is_empty() {
        None
    } else {
        Some(text)
    }
}

/// CI-only optional TLS trust root for the Android upgrade test APK.
///
/// Phase 4d. Reads the system property `ig.ci.tls_ca_path`; when set to a PEM
/// path, loads and returns it as an additional trust root. Default (unset) →
/// `Ok(None)` = production Mozilla-roots behavior unchanged. Fail-closed: the
/// property is set but the path is unreadable or invalid → `Err`.
#[cfg(target_os = "android")]
pub fn ci_tls_trust_root() -> Result<Option<reqwest::Certificate>, String> {
    match android_system_property("ig.ci.tls_ca_path") {
        Some(path) => load_pem_trust_root(Path::new(path.trim())).map(Some),
        None => Ok(None),
    }
}

impl RemoteBroker {
    pub fn new(store: Arc<dyn CredentialStore>) -> Result<Self, String> {
        // Default expected runtime is desktop-remote (legacy desktop behavior).
        // lib.rs overrides this with the ACTIVE mode at setup; tests may switch
        // it explicitly (Gate R0.3).
        Self::with_expected_runtime(store, RUNTIME_DESKTOP_REMOTE)
    }

    pub fn with_expected_runtime(
        store: Arc<dyn CredentialStore>,
        runtime_id: &str,
    ) -> Result<Self, String> {
        Self::with_expected_runtime_and_trust_root(store, runtime_id, None)
    }

    /// Like [`with_expected_runtime`], but additionally trusts a TLS root.
    ///
    /// Phase 4d — CI-only. `None` (the production default) is exactly the
    /// `with_expected_runtime` behavior; `Some(cert)` adds one root so the
    /// broker can reach a self-hosted HTTPS server fronted by an ephemeral CI
    /// CA. Used by the upgrade-in-place test APK via [`ci_tls_trust_root`].
    pub fn with_expected_runtime_and_trust_root(
        store: Arc<dyn CredentialStore>,
        runtime_id: &str,
        trust_root: Option<reqwest::Certificate>,
    ) -> Result<Self, String> {
        if !is_remote_runtime_id(runtime_id) {
            return Err(remote_error(
                ERR_INTERNAL,
                format!("expected runtime must be a remote runtime, got: {runtime_id}"),
            ));
        }
        Ok(Self {
            client: http_client_with_trust_root(trust_root).map_err(|error| {
                remote_error(ERR_INTERNAL, format!("cannot build HTTP client: {error}"))
            })?,
            store,
            state: Arc::new(RemoteBrokerState::new()),
            expected_runtime_id: Arc::new(tokio::sync::Mutex::new(runtime_id.to_string())),
        })
    }

    /// Gate R0.3 — the runtime this broker requires for credential-bearing
    /// flows. Callers that know the ACTIVE mode (e.g. the probe command) can
    /// select the exact runtime a server must advertise.
    async fn expected_runtime(&self) -> String {
        self.expected_runtime_id.lock().await.clone()
    }

    /// Gate R0.3 — switch the required runtime for the remainder of this
    /// session. Session-immutable in production; used by tests to prove the
    /// Android client does not borrow desktop-remote.
    #[cfg(test)]
    async fn set_expected_runtime(&self, runtime_id: &str) {
        if is_remote_runtime_id(runtime_id) {
            *self.expected_runtime_id.lock().await = runtime_id.to_string();
        }
    }

    // -------------------------------------------------- session primitives

    async fn session(&self) -> Option<RemoteSession> {
        self.state.session.lock().await.clone()
    }

    /// Gate D §P22 (MEDIUM) — session writes never use `try_lock`: a normal
    /// concurrent writer is not an error and must never be misread as a
    /// poisoned state. Every mutation awaits the lock like any other critical
    /// section.
    async fn set_session(&self, access_token: &str, expires_in: u64) {
        let mut guard = self.state.session.lock().await;
        let generation = guard.as_ref().map(|session| session.generation).unwrap_or(0) + 1;
        *guard = Some(RemoteSession {
            access_token: access_token.to_string(),
            expires_at_unix: now_unix() + expires_in as i64,
            generation,
        });
    }

    async fn clear_session(&self) {
        *self.state.session.lock().await = None;
    }

    /// Gate D §P7 — the access generation a request was sent with, so the 401
    /// recovery path can tell "the server rejected MY token" from "another
    /// caller already rotated since I started".
    async fn token_snapshot(&self) -> TokenSnapshot {
        let session = self.session().await;
        TokenSnapshot {
            generation: session.map(|session| session.generation).unwrap_or(0),
        }
    }

    // ----------------------------------------------- probe + compatibility

    async fn fetch_json(&self, url: &str) -> Result<serde_json::Value, String> {
        let response = self
            .client
            .get(url)
            .send()
            .await
            .map_err(|error| {
                remote_error(ERR_NETWORK_UNAVAILABLE, format!("cannot reach server: {error}"))
            })?;
        let status = response.status().as_u16();
        // HIGH-1 — metadata is not credential-bound: a 429 is RATE_LIMITED and
        // a 5xx is SERVER_UNAVAILABLE (both transient), never UnsupportedServer.
        // Only 3xx / other / malformed bodies are PROTOCOL_ERROR.
        classify_http_status(EndpointKind::Metadata, status).map_err(|code| match status {
            429 => remote_error(
                code,
                "server metadata endpoint is rate limiting this client; retry later",
            ),
            500..=599 => remote_error(
                code,
                format!("server metadata endpoint is unavailable (HTTP {status})"),
            ),
            _ => remote_error(
                code,
                format!("server metadata endpoint returned HTTP {status}"),
            ),
        })?;
        response
            .json()
            .await
            .map_err(|error| {
                remote_error(ERR_PROTOCOL, format!("invalid server metadata response: {error}"))
            })
    }

    /// Gate D §P3 — unified server probe. Reads BOTH the frozen capability
    /// contract endpoint and the auth server-info endpoint, strictly parses
    /// every required field, then refuses to connect when the shared public
    /// metadata is inconsistent. Missing/empty/malformed required metadata is
    /// PROTOCOL_ERROR (fail-closed), never a defaulted pass.
    pub async fn probe(&self, origin: &str) -> Result<RemoteProbeResult, String> {
        let capabilities = self
            .fetch_json(&format!("{origin}/api/system/capabilities"))
            .await?;
        let server_info = self
            .fetch_json(&format!("{origin}/api/auth/server-info"))
            .await?;
        let caps = parse_capabilities(&capabilities)?;
        let info = parse_server_info(&server_info)?;

        let shared: [(&str, &str, &str); 6] = [
            ("product", &caps.product, &info.product),
            ("server_version", &caps.server_version, &info.server_version),
            ("api_version", &caps.api_version, &info.api_version),
            (
                "min_client_version",
                &caps.min_client_version,
                &info.min_client_version,
            ),
            (
                "server_instance_id",
                &caps.server_instance_id,
                &info.server_instance_id,
            ),
            (
                "server_display_name",
                &caps.server_display_name,
                &info.server_display_name,
            ),
        ];
        for (name, left, right) in shared {
            if left != right {
                return Err(remote_error(
                    ERR_PROTOCOL,
                    format!(
                        "server capability metadata inconsistent ({name}); refusing to connect"
                    ),
                ));
            }
        }
        if caps.auth_enabled != info.auth_enabled
            || caps.auth_mode != info.auth_mode
            || caps.owner_configured != info.owner_configured
            || caps.online_first != info.online_first
            || caps.offline_sync != info.offline_sync
        {
            return Err(remote_error(
                ERR_PROTOCOL,
                "server capability metadata inconsistent (auth/transport); refusing to connect",
            ));
        }

        Ok(RemoteProbeResult {
            normalized_origin: origin.to_string(),
            server: Self::build_server(&caps, &info),
        })
    }

    /// Gate D §P3 — assemble the unified `RemoteServerInfo` from the two
    /// metadata endpoints (capabilities authoritative for runtime facts, the
    /// auth endpoint for transport facts).
    fn build_server(
        caps: &CapabilityResponseV1,
        info: &AuthServerInfoResponseV1,
    ) -> RemoteServerInfo {
        RemoteServerInfo {
            product: caps.product.clone(),
            server_version: caps.server_version.clone(),
            api_version: caps.api_version.clone(),
            min_client_version: caps.min_client_version.clone(),
            server_instance_id: caps.server_instance_id.clone(),
            server_display_name: caps.server_display_name.clone(),
            runtime_modes: caps.runtime_modes.clone(),
            auth_mode: caps.auth_mode.clone(),
            auth_enabled: caps.auth_enabled,
            owner_configured: caps.owner_configured,
            tls: info.tls,
            online_first: caps.online_first,
            offline_sync: caps.offline_sync,
        }
    }

    /// Gate D §P3/P4 — one-shot fail-closed probe for the desktop-remote
    /// runtime. Cross-validates the two metadata endpoints and then applies the
    /// native compatibility gate so an incompatible server can never produce a
    /// pending enrollment or receive a credential.
    pub async fn probe_desktop_remote(&self, origin: &str) -> Result<RemoteProbeResult, String> {
        self.probe_for_runtime(origin, RUNTIME_DESKTOP_REMOTE).await
    }

    /// Gate R0.3 — probe a server for an explicitly requested remote runtime
    /// (desktop-remote or android-remote). The Android shell probes for
    /// android-remote and must never "coincidentally pass" via a server that
    /// only advertises desktop-remote.
    pub async fn probe_for_runtime(
        &self,
        origin: &str,
        runtime_id: &str,
    ) -> Result<RemoteProbeResult, String> {
        if !is_remote_runtime_id(runtime_id) {
            return Err(remote_error(
                ERR_UNSUPPORTED_SERVER,
                format!("unsupported remote runtime for probe: {runtime_id}"),
            ));
        }
        let result = self.probe(origin).await?;
        self.check_compatibility(&result.server, runtime_id)?;
        Ok(result)
    }

    /// Gate D §P4 — native compatibility gate, fail-closed. Returns a coded
    /// error before any credential is sent when the server violates the frozen
    /// contract for the requested runtime. Wrong product/API/runtime/auth
    /// configurations are UNSUPPORTED_SERVER; a client below the server
    /// minimum is UPDATE_REQUIRED.
    pub fn check_compatibility(
        &self,
        server: &RemoteServerInfo,
        runtime_id: &str,
    ) -> Result<(), String> {
        if server.product != API_PRODUCT {
            return Err(remote_error(
                ERR_UNSUPPORTED_SERVER,
                format!("unsupported product: {}", server.product),
            ));
        }
        if server.api_version != SUPPORTED_API_VERSION {
            return Err(remote_error(
                ERR_UNSUPPORTED_SERVER,
                format!("unsupported API version: {}", server.api_version),
            ));
        }
        // Gate C/D §4.3 — a malformed/overflowing minimum must fail closed as
        // PROTOCOL_ERROR, never be treated as `0.0.0` (which would pass).
        let client_below_minimum =
            compare_versions(CLIENT_APP_VERSION, &server.min_client_version)?
                == std::cmp::Ordering::Less;
        if client_below_minimum {
            return Err(remote_error(
                ERR_UPDATE_REQUIRED,
                format!(
                    "client version {CLIENT_APP_VERSION} is below the server minimum {}",
                    server.min_client_version
                ),
            ));
        }
        if !server.runtime_modes.iter().any(|mode| mode == runtime_id) {
            return Err(remote_error(
                ERR_UNSUPPORTED_SERVER,
                format!("server does not support runtime {runtime_id}"),
            ));
        }
        // Gate R0.3 — every shipped remote runtime (desktop-remote,
        // android-remote) requires the same frozen auth/transport contract.
        if is_remote_runtime_id(runtime_id) {
            if !server.auth_enabled {
                return Err(remote_error(
                    ERR_UNSUPPORTED_SERVER,
                    "remote device authentication is disabled on this server",
                ));
            }
            if server.auth_mode != AUTH_MODE_SINGLE_OWNER_DEVICES {
                return Err(remote_error(
                    ERR_UNSUPPORTED_SERVER,
                    format!(
                        "unsupported authentication mode: {}",
                        server.auth_mode
                    ),
                ));
            }
            if !server.online_first {
                return Err(remote_error(
                    ERR_UNSUPPORTED_SERVER,
                    "server is not online-first",
                ));
            }
            if server.offline_sync {
                return Err(remote_error(
                    ERR_UNSUPPORTED_SERVER,
                    "server enables offline sync which this client does not support",
                ));
            }
        }
        Ok(())
    }

    /// Gate D §P6 — credentials are only ever sent after a FRESH probe of the
    /// server that will receive them. No cached probe result is reused for
    /// credential-bearing flows: a server replaced behind the same URL is
    /// detected right before the credential leaves the process (TOCTOU
    /// closure). The renderer-facing probe result remains a UI display cache
    /// and is never an authorization cache.
    async fn fresh_verified_server(&self, origin: &str) -> Result<RemoteServerInfo, String> {
        let runtime_id = self.expected_runtime().await;
        let result = self.probe(origin).await?;
        self.check_compatibility(&result.server, &runtime_id)?;
        Ok(result.server)
    }

    /// Gate D §P5 — stored credentials are only used after an automatic
    /// identity preflight. A replaced server behind the same URL blocks before
    /// the refresh credential is read or sent.
    async fn identity_preflight(&self, enrollment: &RemoteEnrollment) -> Result<(), String> {
        let runtime_id = self.expected_runtime().await;
        let probe = self.probe(&enrollment.normalized_origin).await?;
        self.check_compatibility(&probe.server, &runtime_id)?;
        if probe.server.server_instance_id != enrollment.server_instance_id {
            return Err(remote_error(
                ERR_IDENTITY_CHANGED,
                "server identity changed; re-verify the server before using stored credentials",
            ));
        }
        Ok(())
    }

    // ------------------------------------------------------------ refresh

    /// Effective refresh credential: the in-memory replacement (keyring write
    /// failed after rotation) takes priority, then the durable PENDING slot
    /// (a rotation that crashed before promotion), then the ACTIVE slot.
    /// The active slot keeps the legacy keyring key so existing installs are
    /// readable without migration.
    async fn read_effective_refresh(&self, enrollment: &RemoteEnrollment) -> Result<String, String> {
        if let Some(pending) = self.state.pending_refresh.lock().await.as_ref() {
            if !pending.is_empty() {
                return Ok(pending.clone());
            }
        }
        // Gate C/D §4.5 — a store read that fails because the backend is
        // locked/unavailable is a persistence failure, NOT a missing
        // credential; only NoEntry means "please log in again".
        //
        // §11 — generation-aware two-slot selection. Read BOTH durable slots
        // and prefer the credential with the HIGHEST generation; on a tie (both
        // still gen 0 / un-promoted intent) prefer the ACTIVE slot. This is
        // what proves a stale PENDING leftover can never shadow a promoted
        // ACTIVE credential even when a prior clear_pending crashed: the
        // promoted active always carries a strictly higher generation.
        let pending = read_refresh_slot(self.store.read_pending_refresh(
            &enrollment.server_instance_id,
            &enrollment.device_id,
        ))?;
        let active = read_refresh_slot(self.store.read_refresh(
            &enrollment.server_instance_id,
            &enrollment.device_id,
        ))?;
        let best = match (pending, active) {
            (Some(p), Some(a)) => {
                // Higher generation wins; a tie prefers ACTIVE (the committed slot).
                if a.0 > p.0 {
                    Some(a)
                } else {
                    Some(p)
                }
            }
            // WAL crash: only the pending intent holds the newest value.
            (Some(p), None) => Some(p),
            (None, Some(a)) => Some(a),
            (None, None) => None,
        };
        match best {
            Some((_, token)) => Ok(token),
            None => Err(remote_error(
                ERR_LOGIN_EXPIRED,
                "no remote refresh credential stored; please log in again",
            )),
        }
    }

    /// Gate D §P8 / Gate C/D §4.4 — persist a rotated refresh credential with
    /// crash recovery. The server has already consumed the old one, so a
    /// keyring write failure must not map to "password invalid". Write order:
    /// pending (durable recovery path) → promote to active → clear pending.
    /// If NOTHING can be written the replacement is staged in memory for this
    /// session and CREDENTIAL_PERSISTENCE_FAILURE is returned so callers never
    /// report a durable success that did not happen.
    async fn rotate_refresh(
        &self,
        enrollment: &RemoteEnrollment,
        next: &str,
    ) -> Result<(), String> {
        // §11 — the next generation is one past the highest currently readable
        // durable slot, so the envelope is monotonically increasing across
        // restarts and a freshly promoted ACTIVE always out-ranks any leftover
        // stale PENDING. Reads here are best-effort: a read failure never fails
        // the rotation, it just yields gen 0 (legacy) for that slot.
        let slot_gen = |read: Result<Option<String>, CredentialStoreError>| {
            read_refresh_slot(read.or_else(|_| Ok(None)))
                .unwrap_or(None)
                .map(|(g, _)| g)
                .unwrap_or(0)
        };
        let next_gen = slot_gen(self.store.read_pending_refresh(
            &enrollment.server_instance_id,
            &enrollment.device_id,
        ))
        .max(slot_gen(self.store.read_refresh(
            &enrollment.server_instance_id,
            &enrollment.device_id,
        )))
        .saturating_add(1);
        let envelope = encode_refresh_envelope(next_gen, next);
        let pending_ok = self
            .store
            .write_pending_refresh(&enrollment.server_instance_id, &enrollment.device_id, &envelope)
            .is_ok();
        let active_ok = self
            .store
            .write_refresh(&enrollment.server_instance_id, &enrollment.device_id, &envelope)
            .is_ok();
        if active_ok {
            // Promoted: the pending slot is now redundant. On a clear failure,
            // repair it to the SAME envelope so it can never hold an older
            // credential than the active slot (the read's generation selection
            // closes the case regardless, this is belt-and-suspenders).
            if self
                .store
                .clear_pending_refresh(&enrollment.server_instance_id, &enrollment.device_id)
                .is_err()
            {
                let _ = self.store.write_pending_refresh(
                    &enrollment.server_instance_id,
                    &enrollment.device_id,
                    &envelope,
                );
            }
            *self.state.pending_refresh.lock().await = None;
            return Ok(());
        }
        if pending_ok {
            // Active write failed but the durable pending slot keeps the only
            // valid replacement readable after a crash (read prefers pending).
            return Ok(());
        }
        // No durable slot written: stage in memory for this session and report
        // the degraded persistence honestly (Gate C/D §4.4).
        *self.state.pending_refresh.lock().await = Some(next.to_string());
        Err(remote_error(
            ERR_CREDENTIAL_PERSISTENCE,
            "secure store is unavailable; the renewed credential is only held in memory for this session",
        ))
    }

    /// Rotate via the refresh endpoint and store the replacement. Caller MUST
    /// hold `refresh_lock`; this is the single-flight critical section.
    async fn force_rotate_locked(
        &self,
        enrollment: &RemoteEnrollment,
    ) -> Result<String, String> {
        // Identity + compatibility preflight before using the stored credential.
        self.identity_preflight(enrollment).await?;
        let refresh_token = self.read_effective_refresh(enrollment).await?;
        let body = serde_json::json!({
            "device_id": enrollment.device_id,
            "refresh_token": refresh_token,
        });
        let response = self
            .client
            .post(format!("{}/api/auth/device/refresh", enrollment.normalized_origin))
            .json(&body)
            .send()
            .await
            .map_err(|error| {
                remote_error(
                    ERR_NETWORK_UNAVAILABLE,
                    format!("refresh request failed: {error}"),
                )
            })?;
        let status = response.status().as_u16();
        // Gate C/D §4.1 / HIGH-1 — classify the refresh outcome by HTTP status
        // through the ONE unified classifier. Only an explicit 401/403 is a
        // credential denial (LoginExpired). 429 and 5xx are transient
        // server/network conditions and must NOT invalidate the credential or
        // force a re-login.
        *self.state.refresh_denied.lock().await = false;
        if let Err(code) = classify_http_status(EndpointKind::Refresh, status) {
            if status == 401 || status == 403 {
                // A 401/denial here means the refresh credential itself is
                // invalid/rotated/revoked. Do not loop: mark LoginExpired.
                *self.state.refresh_denied.lock().await = true;
                let detail = response
                    .json::<serde_json::Value>()
                    .await
                    .ok()
                    .and_then(|payload| {
                        payload
                            .get("detail")
                            .and_then(|value| value.as_str())
                            .map(str::to_string)
                    })
                    .unwrap_or_else(|| "refresh denied".to_string());
                return Err(remote_error(
                    code,
                    format!("refresh denied: {detail}"),
                ));
            }
            if status == 429 {
                return Err(remote_error(
                    code,
                    "refresh endpoint is rate limiting this client; retry later",
                ));
            }
            if (300..400).contains(&status) {
                // Redirects stay disabled on the transport; a 3xx here is a
                // protocol violation, not a credential problem.
                return Err(remote_error(
                    code,
                    format!("refresh endpoint returned an unexpected redirect ({status})"),
                ));
            }
            // 5xx (and any other server-side failure) is transient.
            return Err(remote_error(
                code,
                format!("refresh endpoint is unavailable ({status})"),
            ));
        }
        let payload: serde_json::Value = response
            .json()
            .await
            .map_err(|error| {
                remote_error(ERR_PROTOCOL, format!("invalid refresh response: {error}"))
            })?;
        let tokens = payload
            .get("tokens")
            .ok_or_else(|| remote_error(ERR_PROTOCOL, "refresh response missing tokens"))?;
        let access = tokens
            .get("access_token")
            .and_then(|value| value.as_str())
            .ok_or_else(|| remote_error(ERR_PROTOCOL, "refresh response missing access_token"))?
            .to_string();
        let expires_in = tokens
            .get("expires_in")
            .and_then(|value| value.as_u64())
            .unwrap_or(300);
        if let Some(next_refresh) = tokens.get("refresh_token").and_then(|value| value.as_str()) {
            // Gate C/D §4.4 — a total durable-store failure is surfaced as
            // CREDENTIAL_PERSISTENCE_FAILURE (never reported as durable
            // success), while the access credential stays in memory so the
            // current session can continue.
            if let Err(error) = self.rotate_refresh(enrollment, next_refresh).await {
                self.set_session(&access, expires_in).await;
                return Err(error);
            }
        }
        self.set_session(&access, expires_in).await;
        Ok(access)
    }

    /// Consume the stored refresh credential once and rotate it. Single-flight:
    /// concurrent callers share one rotation, and a caller that acquired the
    /// lock after another refresh already happened reuses the fresh access
    /// credential instead of refreshing again (P7).
    async fn refresh_session_token(
        &self,
        enrollment: &RemoteEnrollment,
    ) -> Result<String, String> {
        let _guard = self.state.refresh_lock.lock().await;
        if let Some(current) = self.session().await {
            if !current.access_token.is_empty()
                && current.expires_at_unix > now_unix() + ACCESS_TOKEN_GRACE_SECS
            {
                return Ok(current.access_token.clone());
            }
        }
        self.force_rotate_locked(enrollment).await
    }

    /// Gate D §P7 (HIGH) — the ONLY correct response to a business 401 is a
    /// forced rotation: the access credential the server just rejected is
    /// never reused, even if it is still inside its local expiry window.
    /// Generation awareness keeps concurrent 401s single-flight: if another
    /// caller already rotated past the snapshot this request used, that newer
    /// access credential is reused instead of refreshing again.
    async fn refresh_after_401(
        &self,
        enrollment: &RemoteEnrollment,
        snapshot: &TokenSnapshot,
    ) -> Result<String, String> {
        let _guard = self.state.refresh_lock.lock().await;
        if let Some(current) = self.session().await {
            if current.generation > snapshot.generation {
                return Ok(current.access_token.clone());
            }
        }
        self.force_rotate_locked(enrollment).await
    }

    /// Return the in-memory access credential, refreshing first if it is
    /// missing or expired (with a grace period so short bursts never cascade
    /// refreshes). This is the "get-or-refresh" path: it never treats a valid
    /// access credential as expired.
    async fn get_session_token(&self, enrollment: &RemoteEnrollment) -> Result<String, String> {
        if let Some(current) = self.session().await {
            if !current.access_token.is_empty()
                && current.expires_at_unix > now_unix() + ACCESS_TOKEN_GRACE_SECS
            {
                return Ok(current.access_token.clone());
            }
        }
        self.refresh_session_token(enrollment).await
    }

    // -------------------------------------------------------- HTTP helpers

    fn sanitize_request_headers(
        extra_headers: &HashMap<String, String>,
    ) -> Vec<(String, String)> {
        extra_headers
            .iter()
            .filter(|(key, _)| {
                let lower = key.to_ascii_lowercase();
                ALLOWED_REQUEST_HEADERS.iter().any(|allowed| *allowed == lower)
            })
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect()
    }

    fn capture_response_headers(headers: &reqwest::header::HeaderMap) -> HashMap<String, String> {
        let mut captured = HashMap::new();
        for (name, value) in headers {
            let lower = name.as_str().to_ascii_lowercase();
            if ALLOWED_RESPONSE_HEADERS.iter().any(|allowed| *allowed == lower) {
                if let Ok(value_str) = value.to_str() {
                    captured.insert(lower, value_str.to_string());
                }
            }
        }
        captured
    }

    /// Gate D §9.3 — native API requests only accept the frozen method set.
    /// reqwest would happily parse arbitrary method strings; that must never
    /// happen for renderer input.
    fn assert_allowed_method(method: &str) -> Result<(), String> {
        if ALLOWED_HTTP_METHODS.contains(&method) {
            return Ok(());
        }
        Err(remote_error(
            ERR_PROTOCOL,
            format!("unsupported HTTP method {method}"),
        ))
    }

    async fn send_once(
        &self,
        enrollment: &RemoteEnrollment,
        method: &str,
        path: &str,
        extra_headers: &HashMap<String, String>,
        body: Option<(String, Vec<u8>)>,
    ) -> Result<SentRequest, String> {
        Self::assert_allowed_method(method)?;
        let access = self.get_session_token(enrollment).await?;
        let snapshot = self.token_snapshot().await;
        let url = format!("{}{}", enrollment.normalized_origin, path);
        let parsed_method = reqwest::Method::from_bytes(method.as_bytes())
            .map_err(|error| remote_error(ERR_PROTOCOL, format!("unsupported HTTP method {method}: {error}")))?;
        let mut builder = self.client.request(parsed_method, &url).bearer_auth(&access);
        if let Some((content_type, bytes)) = &body {
            builder = builder
                .header(reqwest::header::CONTENT_TYPE, content_type)
                .body(bytes.clone());
        }
        // Positive allowlist (P15): renderer headers can never set
        // Authorization, Cookie, Host, Origin, X-Forwarded-*, Connection, etc.
        for (key, value) in Self::sanitize_request_headers(extra_headers) {
            builder = builder.header(key, value);
        }
        let response = builder
            .send()
            .await
            .map_err(|error| {
                remote_error(
                    ERR_NETWORK_UNAVAILABLE,
                    format!("remote request failed: {error}"),
                )
            })?;
        let status = response.status().as_u16();
        let content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or("")
            .to_string();
        let response_headers = Self::capture_response_headers(response.headers());
        let bytes = response
            .bytes()
            .await
            .map_err(|error| {
                remote_error(
                    ERR_NETWORK_UNAVAILABLE,
                    format!("failed reading remote response: {error}"),
                )
            })?
            .to_vec();
        Ok(SentRequest {
            status,
            bytes,
            content_type,
            response_headers,
            access_snapshot: snapshot,
        })
    }

    /// Gate C §10.3 / Gate D §P13 — a clear 401 means the request never entered
    /// the business path, so FORCE a rotation (the rejected access credential
    /// is never reused, even if locally unexpired) and retry the original
    /// request exactly once. A second 401 is LoginExpired (no infinite loop).
    /// Never retried on ambiguous transport failures; mutations are never
    /// auto-retried beyond this single auth recovery.
    async fn send_with_auth(
        &self,
        enrollment: &RemoteEnrollment,
        method: &str,
        path: &str,
        extra_headers: &HashMap<String, String>,
        body: Option<(String, Vec<u8>)>,
    ) -> Result<SentRequest, String> {
        let first = self
            .send_once(enrollment, method, path, extra_headers, body.clone())
            .await?;
        if first.status == 401 {
            self.refresh_after_401(enrollment, &first.access_snapshot)
                .await?;
            let second = self
                .send_once(enrollment, method, path, extra_headers, body)
                .await?;
            if second.status == 401 {
                return Err(remote_error(
                    ERR_LOGIN_EXPIRED,
                    "auth session expired; please log in again",
                ));
            }
            return Ok(second);
        }
        Ok(first)
    }

    async fn send_multipart_once(
        &self,
        enrollment: &RemoteEnrollment,
        path: &str,
        file_field: &str,
        file_name: &str,
        file_content_type: &str,
        file_bytes: &[u8],
        fields: &HashMap<String, String>,
    ) -> Result<SentRequest, String> {
        let access = self.get_session_token(enrollment).await?;
        let snapshot = self.token_snapshot().await;
        let url = format!("{}{}", enrollment.normalized_origin, path);
        let mut form = reqwest::multipart::Form::new();
        for (key, value) in fields {
            form = form.text(key.clone(), value.clone());
        }
        let part = reqwest::multipart::Part::bytes(file_bytes.to_vec())
            .file_name(file_name.to_string())
            .mime_str(file_content_type)
            .map_err(|error| remote_error(ERR_PROTOCOL, error.to_string()))?;
        form = form.part(file_field.to_string(), part);
        let response = self
            .client
            .post(&url)
            .bearer_auth(&access)
            .multipart(form)
            .send()
            .await
            .map_err(|error| {
                remote_error(
                    ERR_NETWORK_UNAVAILABLE,
                    format!("remote upload failed: {error}"),
                )
            })?;
        let status = response.status().as_u16();
        let content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or("")
            .to_string();
        let response_headers = Self::capture_response_headers(response.headers());
        let bytes = response
            .bytes()
            .await
            .map_err(|error| remote_error(ERR_NETWORK_UNAVAILABLE, error.to_string()))?
            .to_vec();
        Ok(SentRequest {
            status,
            bytes,
            content_type,
            response_headers,
            access_snapshot: snapshot,
        })
    }

    async fn send_multipart_with_auth(
        &self,
        enrollment: &RemoteEnrollment,
        path: &str,
        file_field: &str,
        file_name: &str,
        file_content_type: &str,
        file_bytes: &[u8],
        fields: &HashMap<String, String>,
    ) -> Result<SentRequest, String> {
        let first = self
            .send_multipart_once(
                enrollment,
                path,
                file_field,
                file_name,
                file_content_type,
                file_bytes,
                fields,
            )
            .await?;
        if first.status == 401 {
            self.refresh_after_401(enrollment, &first.access_snapshot)
                .await?;
            let second = self
                .send_multipart_once(
                    enrollment,
                    path,
                    file_field,
                    file_name,
                    file_content_type,
                    file_bytes,
                    fields,
                )
                .await?;
            if second.status == 401 {
                return Err(remote_error(
                    ERR_LOGIN_EXPIRED,
                    "auth session expired; please log in again",
                ));
            }
            return Ok(second);
        }
        Ok(first)
    }

    // Gate R0.5 — file-backed multipart upload. The file bytes are streamed
    // from a bounded app-private temp file via `Part::stream(ReaderStream)`
    // instead of `Part::bytes(full_vec)`, so a 100 MiB SAF upload is never
    // materialised as a full Rust Vec in memory.
    async fn send_multipart_file_once(
        &self,
        enrollment: &RemoteEnrollment,
        path: &str,
        file_field: &str,
        file_name: &str,
        file_path: &Path,
        file_content_type: &str,
        fields: &HashMap<String, String>,
    ) -> Result<SentRequest, String> {
        let access = self.get_session_token(enrollment).await?;
        let snapshot = self.token_snapshot().await;
        let url = format!("{}{}", enrollment.normalized_origin, path);
        let mut form = reqwest::multipart::Form::new();
        for (key, value) in fields {
            form = form.text(key.clone(), value.clone());
        }
        let file = tokio::fs::File::open(file_path)
            .await
            .map_err(|error| {
                remote_error(
                    ERR_PROTOCOL,
                    format!("cannot open staged upload: {error}"),
                )
            })?;
        let stream = tokio_util::io::ReaderStream::new(file);
        // `ReaderStream` yields `Result<Bytes, io::Error>`; wrap it as a
        // streaming Body so the multipart part is never materialised as a full
        // Vec (Gate R0.5).
        let body = reqwest::Body::wrap_stream(stream);
        let part = reqwest::multipart::Part::stream(body)
            .file_name(file_name.to_string())
            .mime_str(file_content_type)
            .map_err(|error| remote_error(ERR_PROTOCOL, error.to_string()))?;
        form = form.part(file_field.to_string(), part);
        let response = self
            .client
            .post(&url)
            .bearer_auth(&access)
            .multipart(form)
            .send()
            .await
            .map_err(|error| {
                remote_error(
                    ERR_NETWORK_UNAVAILABLE,
                    format!("remote upload failed: {error}"),
                )
            })?;
        let status = response.status().as_u16();
        let content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or("")
            .to_string();
        let response_headers = Self::capture_response_headers(response.headers());
        let bytes = response
            .bytes()
            .await
            .map_err(|error| remote_error(ERR_NETWORK_UNAVAILABLE, error.to_string()))?
            .to_vec();
        Ok(SentRequest {
            status,
            bytes,
            content_type,
            response_headers,
            access_snapshot: snapshot,
        })
    }

    async fn send_multipart_file_with_auth(
        &self,
        enrollment: &RemoteEnrollment,
        path: &str,
        file_field: &str,
        file_name: &str,
        file_path: &Path,
        file_content_type: &str,
        fields: &HashMap<String, String>,
    ) -> Result<SentRequest, String> {
        let first = self
            .send_multipart_file_once(
                enrollment,
                path,
                file_field,
                file_name,
                file_path,
                file_content_type,
                fields,
            )
            .await?;
        if first.status == 401 {
            self.refresh_after_401(enrollment, &first.access_snapshot)
                .await?;
            let second = self
                .send_multipart_file_once(
                    enrollment,
                    path,
                    file_field,
                    file_name,
                    file_path,
                    file_content_type,
                    fields,
                )
                .await?;
            if second.status == 401 {
                return Err(remote_error(
                    ERR_LOGIN_EXPIRED,
                    "auth session expired; please log in again",
                ));
            }
            return Ok(second);
        }
        Ok(first)
    }

    // ------------------------------------------------------ public API

    pub async fn login(
        &self,
        app_data: &Path,
        origin: &str,
        owner_password: &str,
        device_name: &str,
        platform: &str,
        app_version: &str,
    ) -> Result<RemoteLoginResult, String> {
        let normalized = normalize_enrollment_origin(origin)?;
        // Gate D §P6 (HIGH) — a FRESH native-verified probe gates every login.
        // The renderer's earlier probe result is UI display cache only and is
        // never reused as a credential-send authorization: a server replaced
        // behind the same URL is detected immediately before the owner password
        // leaves this process.
        let server = self.fresh_verified_server(&normalized).await?;
        if !server.auth_enabled {
            return Err(remote_error(
                ERR_UNSUPPORTED_SERVER,
                "remote device authentication is disabled on this server",
            ));
        }
        if !server.owner_configured {
            return Err(remote_error(
                ERR_UNSUPPORTED_SERVER,
                "this server has no owner; create the owner password first",
            ));
        }
        let payload = serde_json::json!({
            "owner_password": owner_password,
            "device_name": device_name,
            "platform": platform,
            "app_version": if app_version.is_empty() {
                CLIENT_APP_VERSION
            } else {
                app_version
            },
        });
        let response = self
            .client
            .post(format!("{normalized}/api/auth/owner/login"))
            .json(&payload)
            .send()
            .await
            .map_err(|error| {
                remote_error(
                    ERR_NETWORK_UNAVAILABLE,
                    format!("login request failed: {error}"),
                )
            })?;
        let status = response.status().as_u16();
        // HIGH-1 — a non-201 login is classified through the ONE unified
        // taxonomy: 401/403 is a real credential denial, 429 -> RATE_LIMITED,
        // 5xx -> SERVER_UNAVAILABLE. A transient 429/503 must never be turned
        // into LoginExpired.
        if let Err(code) = classify_http_status(EndpointKind::Login, status) {
            let body: serde_json::Value = response
                .json()
                .await
                .unwrap_or(serde_json::json!({}));
            let detail = body
                .get("detail")
                .and_then(|value| value.as_str())
                .unwrap_or("login failed");
            return Err(remote_error(code, format!("login failed: {detail}")));
        }
        // status == 201 — the success body must parse and carry every required
        // field; a malformed 201 is a PROTOCOL_ERROR.
        let body: serde_json::Value = response
            .json()
            .await
            .map_err(|error| {
                remote_error(ERR_PROTOCOL, format!("invalid login response: {error}"))
            })?;
        let device = body.get("device").cloned().unwrap_or_default();
        let server_block = body.get("server").cloned().unwrap_or_default();
        let tokens = body.get("tokens").cloned().unwrap_or_default();

        let server_instance_id = server_block
            .get("server_instance_id")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string();
        // Identity binding (Gate C §6.5 / P6): the login must come from the very
        // server that was native-verified. A replaced server is rejected.
        if server_instance_id != server.server_instance_id {
            return Err(remote_error(
                ERR_IDENTITY_CHANGED,
                "server identity changed during login; re-verify the server before enrolling",
            ));
        }
        // §12 — enrollment compatibility metadata is bound to the FRESH verified
        // server (the native preflight result), never to defaulted/untrusted
        // values echoed by the login body. Any metadata the login body does
        // carry must agree with the verified server, otherwise the enrollment
        // is rejected (IDENTITY_CHANGED / PROTOCOL_ERROR) instead of silently
        // persisting conflicting or empty values.
        let binding = |key: &str, verified: &str| -> Result<String, String> {
            match server_block.get(key).and_then(|v| v.as_str()) {
                Some(value) if !value.is_empty() => {
                    if verified.is_empty() {
                        return Err(remote_error(
                            ERR_PROTOCOL,
                            format!("verified server lacks required metadata field `{key}`"),
                        ));
                    }
                    if value != verified {
                        return Err(remote_error(
                            ERR_IDENTITY_CHANGED,
                            format!("login server metadata `{key}` conflicts with the verified server"),
                        ));
                    }
                    Ok(value.to_string())
                }
                // Login body omitted the field → use the verified value (never leave
                // an empty string persisted).
                _ => Ok(verified.to_string()),
            }
        };
        let product = binding("product", &server.product)?;
        let api_version = binding("api_version", &server.api_version)?;
        let server_version = binding("server_version", &server.server_version)?;
        let min_client_version = binding("min_client_version", &server.min_client_version)?;
        let display_name = binding("server_display_name", &server.server_display_name)?;
        let device_id = device
            .get("id")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string();
        let device_name_resolved = device
            .get("name")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string();
        let access_token = tokens
            .get("access_token")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string();
        let refresh_token = tokens
            .get("refresh_token")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string();
        let expires_in = tokens
            .get("expires_in")
            .and_then(|value| value.as_u64())
            .unwrap_or(300);
        if device_id.is_empty() || access_token.is_empty() || refresh_token.is_empty() {
            return Err(remote_error(
                ERR_PROTOCOL,
                "login response missing device or token fields",
            ));
        }

        let enrollment = RemoteEnrollment {
            normalized_origin: normalized,
            server_instance_id: server_instance_id.clone(),
            server_display_name: display_name,
            product,
            api_version,
            server_version,
            min_client_version,
            device_id: device_id.clone(),
            device_name: device_name_resolved.clone(),
            platform: platform.trim().to_string(),
            app_version: if app_version.is_empty() {
                CLIENT_APP_VERSION.to_string()
            } else {
                app_version.to_string()
            },
            last_verified_at: now_unix().to_string(),
        };
        self.store
            .write_refresh(&enrollment.server_instance_id, &enrollment.device_id, &refresh_token)
            .map_err(|error| {
                remote_error(
                    ERR_CREDENTIAL_PERSISTENCE,
                    format!("failed to persist the refresh credential: {error}"),
                )
            })?;
        // Gate D §P9 — if the enrollment profile cannot be persisted, clean up
        // the freshly written refresh secret so we never leave an orphan that a
        // future session cannot bound to an enrollment.
        if let Err(save_error) = save_enrollment(app_data, &enrollment) {
            let _ = self
                .store
                .delete_refresh(&enrollment.server_instance_id, &enrollment.device_id);
            return Err(remote_error(
                ERR_CREDENTIAL_PERSISTENCE,
                format!("failed to persist the enrollment profile: {save_error}"),
            ));
        }
        *self.state.refresh_denied.lock().await = false;
        self.set_session(&access_token, expires_in).await;

        Ok(RemoteLoginResult {
            device_id,
            device_name: device_name_resolved,
            server_instance_id,
            server_display_name: enrollment.server_display_name.clone(),
            server_version: enrollment.server_version.clone(),
            api_version: enrollment.api_version.clone(),
            min_client_version: enrollment.min_client_version.clone(),
            expires_in,
            refresh_stored: true,
        })
    }

    /// Bootstrap a fresh server owner. Only valid when the server reports
    /// `owner_configured == false` and passes the native compatibility gate.
    /// The bootstrap secret header is only sent to a server that passed a
    /// FRESH probe and compatibility check in this very call (P2/P4/P6): the
    /// renderer's probe display cache is never reused as authorization.
    pub async fn bootstrap_owner(
        &self,
        origin: &str,
        owner_password: &str,
        bootstrap_token: &str,
    ) -> Result<serde_json::Value, String> {
        let normalized = normalize_enrollment_origin(origin)?;
        let server = self.fresh_verified_server(&normalized).await?;
        if !server.auth_enabled {
            return Err(remote_error(
                ERR_UNSUPPORTED_SERVER,
                "remote device authentication is disabled on this server",
            ));
        }
        if server.owner_configured {
            return Err(remote_error(
                ERR_UNSUPPORTED_SERVER,
                "owner is already configured on this server",
            ));
        }
        let response = self
            .client
            .post(format!("{normalized}/api/auth/owner/bootstrap"))
            .header("X-PG-Owner-Bootstrap-Token", bootstrap_token)
            .json(&serde_json::json!({ "owner_password": owner_password }))
            .send()
            .await
            .map_err(|error| {
                remote_error(
                    ERR_NETWORK_UNAVAILABLE,
                    format!("bootstrap request failed: {error}"),
                )
            })?;
        let status = response.status().as_u16();
        let payload: serde_json::Value = response
            .json()
            .await
            .unwrap_or(serde_json::json!({ "detail": "bootstrap failed" }));
        // HIGH-1 — a non-201 bootstrap is classified through the ONE unified
        // taxonomy too: 401/403 is a bootstrap-token / auth denial, 429 is
        // RATE_LIMITED, 5xx is SERVER_UNAVAILABLE, 3xx/other is PROTOCOL_ERROR.
        if let Err(code) = classify_http_status(EndpointKind::Login, status) {
            let detail = payload
                .get("detail")
                .and_then(|value| value.as_str())
                .unwrap_or("bootstrap failed");
            return Err(remote_error(code, format!("bootstrap failed: {detail}")));
        }
        Ok(payload)
    }

    pub async fn api_request(
        &self,
        app_data: &Path,
        path: &str,
        method: &str,
        body: Option<(String, Vec<u8>)>,
        headers: &HashMap<String, String>,
    ) -> Result<RemoteApiResponse, String> {
        let enrollment = load_enrollment(app_data)
            .ok_or_else(|| remote_error(ERR_LOGIN_EXPIRED, "not enrolled to a server"))?;
        assert_relative_path(path)
            .map_err(|error| remote_error(ERR_PROTOCOL, error))?;
        let method = method.to_uppercase();
        Self::assert_allowed_method(&method)?;
        let sent = self
            .send_with_auth(&enrollment, &method, path, headers, body)
            .await?;
        Ok(RemoteApiResponse {
            status: sent.status,
            body_base64: base64::engine::general_purpose::STANDARD.encode(sent.bytes),
            content_type: sent.content_type,
            response_headers: sent.response_headers,
        })
    }

    /// Gate D §P17 — uploads are bounded: fail on the encoded length before
    /// decoding and again on the real byte count. The error never includes file
    /// content.
    pub async fn api_upload(
        &self,
        app_data: &Path,
        path: &str,
        file_field: &str,
        file_name: &str,
        file_bytes_b64: &str,
        file_content_type: &str,
        fields: &HashMap<String, String>,
    ) -> Result<RemoteApiResponse, String> {
        let limit_mib = MAX_UPLOAD_BYTES / (1024 * 1024);
        if file_bytes_b64.len() > (MAX_UPLOAD_BYTES * 4) / 3 + 4 {
            return Err(remote_error(
                ERR_PROTOCOL,
                format!("file exceeds the {limit_mib} MiB upload limit"),
            ));
        }
        let file_bytes = base64::engine::general_purpose::STANDARD
            .decode(file_bytes_b64)
            .map_err(|error| remote_error(ERR_PROTOCOL, format!("invalid file payload: {error}")))?;
        self.api_upload_raw(
            app_data,
            path,
            file_field,
            file_name,
            file_bytes,
            file_content_type,
            fields,
        )
        .await
    }

    /// Gate R0.5 — upload already-materialised native bytes (e.g. read from a
    /// SAF content URI by the Android bridge). Shares the product upload bound
    /// and the enrollment/path checks with the base64 path so Android and
    /// desktop observe identical limits.
    pub async fn api_upload_raw(
        &self,
        app_data: &Path,
        path: &str,
        file_field: &str,
        file_name: &str,
        file_bytes: Vec<u8>,
        file_content_type: &str,
        fields: &HashMap<String, String>,
    ) -> Result<RemoteApiResponse, String> {
        let enrollment = load_enrollment(app_data)
            .ok_or_else(|| remote_error(ERR_LOGIN_EXPIRED, "not enrolled to a server"))?;
        assert_relative_path(path)
            .map_err(|error| remote_error(ERR_PROTOCOL, error))?;
        let limit_mib = MAX_UPLOAD_BYTES / (1024 * 1024);
        if file_bytes.len() > MAX_UPLOAD_BYTES {
            return Err(remote_error(
                ERR_PROTOCOL,
                format!("file exceeds the {limit_mib} MiB upload limit"),
            ));
        }
        let sent = self
            .send_multipart_with_auth(
                &enrollment,
                path,
                file_field,
                file_name,
                file_content_type,
                &file_bytes,
                fields,
            )
            .await?;
        Ok(RemoteApiResponse {
            status: sent.status,
            body_base64: base64::engine::general_purpose::STANDARD.encode(sent.bytes),
            content_type: sent.content_type,
            response_headers: sent.response_headers,
        })
    }

    /// Gate R0.5 — upload a bounded app-private temp file by STREAMING it as
    /// the multipart body (never `Part::bytes` of a full Vec). The size was
    /// already enforced while Kotlin staged the file; Rust re-checks cheaply so
    /// the bound holds even if the staged file grows.
    pub async fn api_upload_file(
        &self,
        app_data: &Path,
        path: &str,
        file_field: &str,
        file_name: &str,
        file_path: &Path,
        file_content_type: &str,
        fields: &HashMap<String, String>,
    ) -> Result<RemoteApiResponse, String> {
        let enrollment = load_enrollment(app_data)
            .ok_or_else(|| remote_error(ERR_LOGIN_EXPIRED, "not enrolled to a server"))?;
        assert_relative_path(path)
            .map_err(|error| remote_error(ERR_PROTOCOL, error))?;
        let limit_mib = MAX_UPLOAD_BYTES / (1024 * 1024);
        let size = tokio::fs::metadata(file_path)
            .await
            .map_err(|error| {
                remote_error(
                    ERR_PROTOCOL,
                    format!("cannot stat staged upload: {error}"),
                )
            })?
            .len();
        if size > MAX_UPLOAD_BYTES as u64 {
            return Err(remote_error(
                ERR_PROTOCOL,
                format!("file exceeds the {limit_mib} MiB upload limit"),
            ));
        }
        let sent = self
            .send_multipart_file_with_auth(
                &enrollment,
                path,
                file_field,
                file_name,
                file_path,
                file_content_type,
                fields,
            )
            .await?;
        Ok(RemoteApiResponse {
            status: sent.status,
            body_base64: base64::engine::general_purpose::STANDARD.encode(sent.bytes),
            content_type: sent.content_type,
            response_headers: sent.response_headers,
        })
    }

    /// Gate R0.6 — download an artifact into a bounded app-private temp file by
    /// streaming the HTTP response body (never a full base64 Vec). Validates
    /// `Content-Length` when trustworthy and enforces the bound while reading a
    /// chunked/no-length body. Honors the single 401 refresh-recovery.
    pub async fn download_to_file(
        &self,
        app_data: &Path,
        path: &str,
        dest: &Path,
    ) -> Result<DownloadedExport, String> {
        let enrollment = load_enrollment(app_data)
            .ok_or_else(|| remote_error(ERR_LOGIN_EXPIRED, "not enrolled to a server"))?;
        assert_relative_path(path)
            .map_err(|error| remote_error(ERR_PROTOCOL, error))?;
        let first = self
            .download_to_file_once(&enrollment, path, dest)
            .await?;
        if first.status == 401 {
            self.refresh_after_401(&enrollment, &first.access_snapshot)
                .await?;
            let second = self.download_to_file_once(&enrollment, path, dest).await?;
            if second.status == 401 {
                return Err(remote_error(
                    ERR_LOGIN_EXPIRED,
                    "auth session expired; please log in again",
                ));
            }
            return Ok(second);
        }
        Ok(first)
    }

    async fn download_to_file_once(
        &self,
        enrollment: &RemoteEnrollment,
        path: &str,
        dest: &Path,
    ) -> Result<DownloadedExport, String> {
        let access = self.get_session_token(enrollment).await?;
        let snapshot = self.token_snapshot().await;
        let url = format!("{}{}", enrollment.normalized_origin, path);
        let response = self
            .client
            .get(&url)
            .bearer_auth(&access)
            .send()
            .await
            .map_err(|error| {
                remote_error(
                    ERR_NETWORK_UNAVAILABLE,
                    format!("artifact download request failed: {error}"),
                )
            })?;
        let status = response.status().as_u16();
        let content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or("")
            .to_string();
        let response_headers = Self::capture_response_headers(response.headers());
        let limit_mib = MAX_UPLOAD_BYTES / (1024 * 1024);
        // Precheck Content-Length when the server provides a trustworthy one.
        if let Some(len) = response.content_length() {
            if len > MAX_UPLOAD_BYTES as u64 {
                return Err(remote_error(
                    ERR_PROTOCOL,
                    format!("export exceeds the {limit_mib} MiB native export limit"),
                ));
            }
        }
        // Stream the body to the temp file with a hard bound regardless of
        // whether the server sent Content-Length.
        use futures_util::StreamExt;
        use tokio::io::AsyncWriteExt;
        let mut file = tokio::fs::File::create(dest)
            .await
            .map_err(|error| {
                remote_error(
                    ERR_PROTOCOL,
                    format!("cannot create export temp file: {error}"),
                )
            })?;
        let mut total: u64 = 0;
        let mut stream = response.bytes_stream();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|error| {
                remote_error(
                    ERR_NETWORK_UNAVAILABLE,
                    format!("artifact download stream failed: {error}"),
                )
            })?;
            total += chunk.len() as u64;
            if total > MAX_UPLOAD_BYTES as u64 {
                return Err(remote_error(
                    ERR_PROTOCOL,
                    format!("export exceeds the {limit_mib} MiB native export limit"),
                ));
            }
            file.write_all(&chunk)
                .await
                .map_err(|error| {
                    remote_error(
                        ERR_PROTOCOL,
                        format!("failed writing export temp file: {error}"),
                    )
                })?;
        }
        file.flush()
            .await
            .map_err(|error| {
                remote_error(
                    ERR_PROTOCOL,
                    format!("failed flushing export temp file: {error}"),
                )
            })?;
        Ok(DownloadedExport {
            status,
            content_type,
            response_headers,
            access_snapshot: snapshot,
        })
    }

    pub async fn refresh_now(&self, app_data: &Path) -> Result<RemoteSessionStatus, String> {
        let enrollment =
            load_enrollment(app_data).ok_or_else(|| remote_error(ERR_LOGIN_EXPIRED, "not enrolled"))?;
        self.refresh_session_token(&enrollment).await?;
        Ok(self.session_status(app_data).await)
    }

    pub async fn session_status(&self, app_data: &Path) -> RemoteSessionStatus {
        let empty = || RemoteSessionStatus {
            enrolled: false,
            connected: false,
            auth_expired: false,
            refresh_token_stored: false,
            normalized_origin: String::new(),
            server_instance_id: String::new(),
            server_display_name: String::new(),
            device_id: String::new(),
            device_name: String::new(),
            server_version: String::new(),
            api_version: String::new(),
            min_client_version: String::new(),
            platform: String::new(),
            app_version: String::new(),
        };
        let Some(enrollment) = load_enrollment(app_data) else {
            return empty();
        };
        let session = self.session().await;
        let connected = session
            .as_ref()
            .map(|session| !session.access_token.is_empty() && session.expires_at_unix > now_unix())
            .unwrap_or(false);
        let refresh_stored = self.read_effective_refresh(&enrollment).await.is_ok();
        // Gate D §P11 (HIGH) — auth_expired is ONLY true when the server
        // explicitly denied the refresh credential (invalid/expired/revoked).
        // "Enrolled + refresh stored + access missing" is a normal restart
        // state and must never surface as LoginExpired.
        let auth_expired = *self.state.refresh_denied.lock().await && !connected;
        RemoteSessionStatus {
            enrolled: true,
            connected,
            auth_expired,
            refresh_token_stored: refresh_stored,
            normalized_origin: enrollment.normalized_origin.clone(),
            server_instance_id: enrollment.server_instance_id.clone(),
            server_display_name: enrollment.server_display_name.clone(),
            device_id: enrollment.device_id.clone(),
            device_name: enrollment.device_name.clone(),
            server_version: enrollment.server_version.clone(),
            api_version: enrollment.api_version.clone(),
            min_client_version: enrollment.min_client_version.clone(),
            platform: enrollment.platform.clone(),
            app_version: enrollment.app_version.clone(),
        }
    }

    pub async fn verify_identity(&self, app_data: &Path) -> Result<serde_json::Value, String> {
        let enrollment = load_enrollment(app_data)
            .ok_or_else(|| remote_error(ERR_LOGIN_EXPIRED, "not enrolled"))?;
        let probe = self.probe(&enrollment.normalized_origin).await?;
        let identity_changed = probe.server.server_instance_id != enrollment.server_instance_id;
        Ok(serde_json::json!({
            "identityChanged": identity_changed,
            "server": probe.server,
        }))
    }

    /// Log out. `revoke` asks the server to revoke this device; local keyring
    /// and enrollment are always cleared regardless of network outcome. The
    /// result is truthful: a failed network revoke reports `revoked: false`.
    pub async fn logout(&self, app_data: &Path, revoke: bool) -> Result<RemoteLogoutResult, String> {
        let Some(enrollment) = load_enrollment(app_data) else {
            return Ok(RemoteLogoutResult {
                logged_out: true,
                revoked: false,
            });
        };
        let mut revoked = false;
        if revoke {
            let body = serde_json::json!({ "device_id": enrollment.device_id });
            if let Ok(sent) = self
                .send_with_auth(
                    &enrollment,
                    "POST",
                    "/api/auth/device/revoke",
                    &HashMap::new(),
                    Some((
                        "application/json".into(),
                        serde_json::to_vec(&body).unwrap_or_default(),
                    )),
                )
                .await
            {
                revoked = sent.status >= 200 && sent.status < 300;
            }
        }
        let _ = self
            .store
            .delete_refresh(&enrollment.server_instance_id, &enrollment.device_id);
        *self.state.pending_refresh.lock().await = None;
        *self.state.refresh_denied.lock().await = false;
        self.clear_session().await;
        clear_enrollment(app_data);
        Ok(RemoteLogoutResult {
            logged_out: true,
            revoked,
        })
    }
}

/// Strictly parsed `GET /api/system/capabilities` (Gate A §4, frozen).
///
/// Gate D §P2/P4 — every field below is REQUIRED and type-checked. A missing,
/// empty or malformed field fails the probe (PROTOCOL_ERROR) instead of
/// defaulting open. `runtime_modes` must be a non-empty string array and
/// `auth.mode`/`auth.enabled`/`owner_configured` must be present and typed.
#[derive(Clone, Debug)]
struct CapabilityResponseV1 {
    product: String,
    server_version: String,
    api_version: String,
    min_client_version: String,
    server_instance_id: String,
    server_display_name: String,
    runtime_modes: Vec<String>,
    auth_mode: String,
    auth_enabled: bool,
    owner_configured: bool,
    online_first: bool,
    offline_sync: bool,
}

/// Strictly parsed `GET /api/auth/server-info` (Gate A §4, frozen).
///
/// Same required-field discipline as capabilities, plus the `tls` transport
/// fact reported through the trusted proxy.
#[derive(Clone, Debug)]
struct AuthServerInfoResponseV1 {
    product: String,
    server_version: String,
    api_version: String,
    min_client_version: String,
    server_instance_id: String,
    server_display_name: String,
    auth_mode: String,
    auth_enabled: bool,
    owner_configured: bool,
    tls: bool,
    online_first: bool,
    offline_sync: bool,
}

fn parse_required_str(payload: &serde_json::Value, key: &str, ctx: &str) -> Result<String, String> {
    let value = payload
        .get(key)
        .and_then(|value| value.as_str())
        .ok_or_else(|| {
            remote_error(
                ERR_PROTOCOL,
                format!("{ctx} is missing required field `{key}`"),
            )
        })?;
    if value.trim().is_empty() {
        return Err(remote_error(
            ERR_PROTOCOL,
            format!("{ctx} field `{key}` must not be empty"),
        ));
    }
    Ok(value.trim().to_string())
}

fn parse_required_bool(payload: &serde_json::Value, key: &str, ctx: &str) -> Result<bool, String> {
    payload.get(key).and_then(|value| value.as_bool()).ok_or_else(|| {
        remote_error(
            ERR_PROTOCOL,
            format!("{ctx} field `{key}` must be a boolean"),
        )
    })
}

fn parse_required_auth(payload: &serde_json::Value, ctx: &str) -> Result<(String, bool, bool), String> {
    let auth = payload
        .get("auth")
        .filter(|value| value.is_object())
        .ok_or_else(|| remote_error(ERR_PROTOCOL, format!("{ctx} is missing required field `auth`")))?;
    let mode = parse_required_str(auth, "mode", ctx)?;
    let enabled = parse_required_bool(auth, "enabled", ctx)?;
    let owner_configured = parse_required_bool(auth, "owner_configured", ctx)?;
    Ok((mode, enabled, owner_configured))
}

fn parse_required_string_array(payload: &serde_json::Value, key: &str, ctx: &str) -> Result<Vec<String>, String> {
    let values = payload
        .get(key)
        .and_then(|value| value.as_array())
        .ok_or_else(|| {
            remote_error(
                ERR_PROTOCOL,
                format!("{ctx} field `{key}` must be a string array"),
            )
        })?;
    let mut out = Vec::with_capacity(values.len());
    for value in values {
        let text = value.as_str().ok_or_else(|| {
            remote_error(
                ERR_PROTOCOL,
                format!("{ctx} field `{key}` must contain only strings"),
            )
        })?;
        if text.trim().is_empty() {
            return Err(remote_error(
                ERR_PROTOCOL,
                format!("{ctx} field `{key}` must not contain empty values"),
            ));
        }
        out.push(text.to_string());
    }
    if out.is_empty() {
        return Err(remote_error(
            ERR_PROTOCOL,
            format!("{ctx} field `{key}` must not be empty"),
        ));
    }
    Ok(out)
}

/// Malformed required versions must never auto-parse and pass (Gate C §8 /
/// Gate D §P4). Numeric dotted semver-lite only: `0.7.0`, `1`, `1.2.3`.
fn validate_required_version(payload: &serde_json::Value, key: &str, ctx: &str) -> Result<String, String> {
    let raw = parse_required_str(payload, key, ctx)?;
    if !raw.chars().all(|character| character.is_ascii_digit() || character == '.')
        || raw.split('.').any(|part| part.is_empty())
    {
        return Err(remote_error(
            ERR_PROTOCOL,
            format!("{ctx} field `{key}` is malformed: {raw}"),
        ));
    }
    Ok(raw)
}

fn parse_capabilities(payload: &serde_json::Value) -> Result<CapabilityResponseV1, String> {
    let ctx = "/api/system/capabilities";
    let (auth_mode, auth_enabled, owner_configured) = parse_required_auth(payload, ctx)?;
    Ok(CapabilityResponseV1 {
        product: parse_required_str(payload, "product", ctx)?,
        server_version: validate_required_version(payload, "server_version", ctx)?,
        api_version: parse_required_str(payload, "api_version", ctx)?,
        min_client_version: validate_required_version(payload, "min_client_version", ctx)?,
        server_instance_id: parse_required_str(payload, "server_instance_id", ctx)?,
        server_display_name: parse_required_str(payload, "server_display_name", ctx)?,
        runtime_modes: parse_required_string_array(payload, "runtime_modes", ctx)?,
        auth_mode,
        auth_enabled,
        owner_configured,
        online_first: parse_required_bool(payload, "online_first", ctx)?,
        offline_sync: parse_required_bool(payload, "offline_sync", ctx)?,
    })
}

fn parse_server_info(payload: &serde_json::Value) -> Result<AuthServerInfoResponseV1, String> {
    let ctx = "/api/auth/server-info";
    let (auth_mode, auth_enabled, owner_configured) = parse_required_auth(payload, ctx)?;
    Ok(AuthServerInfoResponseV1 {
        product: parse_required_str(payload, "product", ctx)?,
        server_version: validate_required_version(payload, "server_version", ctx)?,
        api_version: parse_required_str(payload, "api_version", ctx)?,
        min_client_version: validate_required_version(payload, "min_client_version", ctx)?,
        server_instance_id: parse_required_str(payload, "server_instance_id", ctx)?,
        server_display_name: parse_required_str(payload, "server_display_name", ctx)?,
        auth_mode,
        auth_enabled,
        owner_configured,
        tls: parse_required_bool(payload, "tls", ctx)?,
        online_first: parse_required_bool(payload, "online_first", ctx)?,
        offline_sync: parse_required_bool(payload, "offline_sync", ctx)?,
    })
}

// ------------------------------------------------------------- commands

/// Probe a candidate self-hosted server. Returns normalized origin + verified
/// server metadata so the renderer can present the compatibility result.
///
/// The probe is the ONLY remote command open in every runtime mode: it is
/// public metadata with no credential and is what the renderer uses to
/// DISPLAY the compatibility gate before enrollment. No probe result is ever
/// cached or reused as a credential-send authorization (Gate D §P6): login and
/// bootstrap always re-probe natively within the same call.
///
/// Gate R0.3 — the probe checks the EXACT runtime the client runs. The
/// renderer submits a `runtime_id` (desktop-remote on desktop, android-remote
/// on Android); when absent, it falls back to the ACTIVE mode's runtime id so
/// a credential-bearing flow can never accidentally probe for a different
/// runtime than the one being used.
#[tauri::command]
pub async fn remote_probe_server(
    app: AppHandle,
    origin: String,
    runtime_id: Option<String>,
) -> Result<RemoteProbeResult, String> {
    let normalized = normalize_enrollment_origin(&origin)?;
    let broker = app.state::<DesktopState>().broker.clone();
    let runtime_id = match runtime_id {
        Some(runtime_id) => runtime_id,
        None => app.state::<DesktopState>().mode.as_str().to_string(),
    };
    broker.probe_for_runtime(&normalized, &runtime_id).await
}

/// Gate D §P28 (HIGH) — the native remote broker is only reachable while the
/// ACTIVE runtime is desktop-remote (or, on the Android host, android-remote).
/// Every remote command except the public probe requires this active-mode
/// boundary; a desktop-local renderer must never be able to read enrollment
/// state or reach the remote transport, even if its UI shows no such controls
/// (the renderer is not a security boundary).
pub(crate) fn ensure_remote_mode(mode: crate::runtime_mode::RuntimeMode) -> Result<(), String> {
    use crate::runtime_mode::RuntimeMode;
    if mode != RuntimeMode::DesktopRemote && mode != RuntimeMode::AndroidRemote {
        return Err(remote_error(
            ERR_RUNTIME_MODE_DENIED,
            "remote session commands require the desktop-remote or android-remote runtime mode",
        ));
    }
    Ok(())
}

/// Bootstrap a fresh server owner. Only valid when the server reports
/// `owner_configured == false`. Requires the server-side bootstrap token.
#[tauri::command]
pub async fn remote_bootstrap_owner(
    app: AppHandle,
    origin: String,
    owner_password: String,
    bootstrap_token: String,
) -> Result<serde_json::Value, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    let broker = app.state::<DesktopState>().broker.clone();
    broker.bootstrap_owner(&origin, &owner_password, &bootstrap_token).await
}

/// Login as the owner on the enrolled-origin server. The refresh credential is
/// written to the OS keyring (server_instance_id:device_id namespace) and the
/// access credential stays in memory; neither reaches the renderer. The login
/// is gated by a native-verified probe and identity binding (P4/P6).
#[tauri::command]
pub async fn remote_login(
    app: AppHandle,
    origin: String,
    owner_password: String,
    device_name: String,
    platform: String,
    app_version: String,
) -> Result<RemoteLoginResult, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    broker
        .login(&app_data, &origin, &owner_password, &device_name, &platform, &app_version)
        .await
}

/// Native HTTP request for the enrolled server. The renderer only supplies a
/// relative API path; the base origin and Bearer header come from here.
#[tauri::command]
pub async fn remote_api_request(
    app: AppHandle,
    path: String,
    method: Option<String>,
    body: Option<String>,
    content_type: Option<String>,
    headers: Option<HashMap<String, String>>,
) -> Result<RemoteApiResponse, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    let method = method.unwrap_or_else(|| "GET".into());
    let body_spec = body.map(|value| {
        (
            content_type.clone().unwrap_or_else(|| "application/json".into()),
            value.into_bytes(),
        )
    });
    broker
        .api_request(&app_data, &path, &method, body_spec, &headers.unwrap_or_default())
        .await
}

/// Multipart upload (e.g. knowledge source files) through the native broker.
/// Bounded by the product upload limit before and after base64 decoding (P17).
#[tauri::command]
pub async fn remote_api_upload(
    app: AppHandle,
    path: String,
    file_field: Option<String>,
    file_name: String,
    file_bytes_b64: String,
    file_content_type: Option<String>,
    fields: Option<HashMap<String, String>>,
) -> Result<RemoteApiResponse, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    broker
        .api_upload(
            &app_data,
            &path,
            &file_field.unwrap_or_else(|| "file".into()),
            &file_name,
            &file_bytes_b64,
            &file_content_type.unwrap_or_else(|| "application/octet-stream".into()),
            &fields.unwrap_or_default(),
        )
        .await
}

/// Gate R0.5 — Android SAF upload. The renderer only passes a content URI,
/// filename, MIME type and size; the native layer stages the SAF content URI
/// into a bounded app-private temp file (enforcing the product limit during
/// the copy) and STREAMS that file as the multipart body. A 100 MiB file is
/// never materialised as a renderer base64 copy, a Kotlin ByteArray, or a full
/// Rust Vec simultaneously — it lives on disk until the upload completes.
#[tauri::command]
pub async fn remote_api_upload_by_uri(
    app: AppHandle,
    path: String,
    file_field: Option<String>,
    uri: String,
    file_name: Option<String>,
    file_content_type: Option<String>,
    fields: Option<HashMap<String, String>>,
) -> Result<RemoteApiResponse, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    // Gate HIGH-2 — the renderer may never ask the native layer to read an
    // arbitrary URI. Only `content://` (supplied by SAF) is acceptable;
    // `file://`, `http(s)://`, `android.resource://`, empty/malformed schemes
    // are rejected here at the native boundary (defense in depth with the
    // Kotlin gate).
    crate::android_bridge::assert_content_only_uri(&uri)?;
    // Stage the SAF content URI into a bounded app-private cache file. The
    // Kotlin layer aborts the copy if it would exceed the product limit, so
    // no unbounded buffer is ever built (Gate R0.5).
    let staged =
        crate::android_bridge::stage_upload(&app, &uri, MAX_UPLOAD_BYTES as u64).await?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    let result = broker
        .api_upload_file(
            &app_data,
            &path,
            &file_field.unwrap_or_else(|| "file".into()),
            &file_name.filter(|name| !name.is_empty()).unwrap_or(staged.name),
            Path::new(&staged.path),
            &file_content_type
                .filter(|mime| !mime.is_empty())
                .unwrap_or(staged.mime_type),
            &fields.unwrap_or_default(),
        )
        .await;
    // Always clean up the bounded temp file, regardless of upload outcome.
    let _ = tokio::fs::remove_file(&staged.path).await;
    result
}

/// Gate R0.5 — open the Android SAF document picker natively. Returns only a
/// content URI plus metadata so the renderer passes the URI onward instead of
/// ever reading the file bytes.
#[tauri::command]
pub async fn remote_pick_document(
    app: AppHandle,
    mime_type: Option<String>,
) -> Result<crate::android_bridge::PickedDocument, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    crate::android_bridge::pick_document(&app, mime_type).await
}

/// Gate R0.6 — Android export. The native broker STREAMS the artifact bytes
/// into a bounded app-private temp file (never a full base64 Vec), then the
/// native SAF layer copies that file into the user-selected location. The
/// renderer only passes the relative download path and a default filename; it
/// never materialises the artifact bytes.
#[tauri::command]
pub async fn remote_save_export(
    app: AppHandle,
    path: String,
    file_name: Option<String>,
    file_content_type: Option<String>,
) -> Result<serde_json::Value, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    // Stream the HTTP response into a bounded app-private temp file (Gate
    // R0.6). The body is written to disk in chunks with a hard bound, so an
    // export is never materialised as a full base64/Rust Vec.
    let cache_dir = app.path().app_cache_dir().map_err(|error| error.to_string())?;
    let dest = cache_dir.join(format!("export-{}.tmp", uuid::Uuid::new_v4().simple()));
    // §13 — a RAII cleanup guard guarantees the bounded temp file is removed on
    // EVERY exit path (download error, HTTP throw, user cancel, SAF failure,
    // activity-callback error), never just on the happy path.
    struct TempGuard(std::path::PathBuf);
    impl Drop for TempGuard {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.0);
        }
    }
    let _guard = TempGuard(dest.clone());
    let downloaded = broker.download_to_file(&app_data, &path, &dest).await?;
    if downloaded.status >= 400 {
        return Err(remote_error(
            ERR_SERVER_UNAVAILABLE,
            format!("artifact download failed with status {}", downloaded.status),
        ));
    }
    // Prefer the server-provided Content-Disposition filename, then the
    // caller's default. The disposition is on the native response allowlist.
    let filename = downloaded
        .response_headers
        .get("content-disposition")
        .and_then(|value| extract_filename_from_disposition(value))
        .or_else(|| file_name.filter(|name| !name.is_empty()))
        .unwrap_or_else(|| "interest-growth-export.bin".into());
    let content_type = file_content_type
        .filter(|mime| !mime.is_empty())
        .unwrap_or_else(|| {
            if downloaded.content_type.is_empty() {
                "application/octet-stream".into()
            } else {
                downloaded.content_type
            }
        });
    let saved = crate::android_bridge::save_document_from_file(
        &app,
        &dest.to_string_lossy(),
        &filename,
        &content_type,
    )
    .await?;
    // The guard removes the bounded temp file after the SAF copy completes
    // (or if the user cancels / the copy errors).
    Ok(serde_json::json!({
        "uri": saved.uri,
        "size": saved.size,
        "name": filename,
    }))
}

/// Parse the filename from a `Content-Disposition` header value. Supports the
/// plain `filename="x.zip"` form (the export endpoint's format) and the
/// `filename*=UTF-8''x.zip` extended form.
fn extract_filename_from_disposition(value: &str) -> Option<String> {
    let value = value.trim();
    let (_, rest) = value.split_once("filename*=")
        .or_else(|| value.split_once("filename="))?;
    let rest = rest.trim();
    if let Some(stripped) = rest.strip_prefix('"') {
        return stripped
            .split('"')
            .next()
            .map(str::trim)
            .filter(|name| !name.is_empty())
            .map(ToOwned::to_owned);
    }
    rest.split(';')
        .next()
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .map(ToOwned::to_owned)
}

/// Explicitly refresh the session (used by the connection-status UX).
#[tauri::command]
pub async fn remote_refresh_now(app: AppHandle) -> Result<RemoteSessionStatus, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    broker.refresh_now(&app_data).await
}

#[tauri::command]
pub async fn remote_session_status(app: AppHandle) -> Result<RemoteSessionStatus, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    Ok(broker.session_status(&app_data).await)
}

/// Re-probe the enrolled server and compare its instance identity. A mismatch
/// means the server behind the same URL was replaced (Gate C §6.5): the
/// renderer must surface IdentityChanged and require explicit re-enrollment.
#[tauri::command]
pub async fn remote_verify_identity(app: AppHandle) -> Result<serde_json::Value, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    broker.verify_identity(&app_data).await
}

/// Log out. `revoke` asks the server to revoke this device; local keyring and
/// enrollment are always cleared regardless of network outcome.
#[tauri::command]
pub async fn remote_logout(app: AppHandle, revoke: bool) -> Result<RemoteLogoutResult, String> {
    ensure_remote_mode(app.state::<DesktopState>().mode)?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    broker.logout(&app_data, revoke).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::sync::Mutex as StdMutex;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::{TcpListener, TcpStream};

    // --------------------------------------------------------- test fakes

    #[derive(Clone, Default)]
    struct MemoryStore {
        values: Arc<StdMutex<HashMap<String, String>>>,
        write_fail: Arc<AtomicBool>,
        pending_write_fail: Arc<AtomicBool>,
        clear_fail: Arc<AtomicBool>,
        read_fail: Arc<AtomicBool>,
    }

    impl MemoryStore {
        fn new() -> Self {
            Self::default()
        }
        fn set_write_fail(&self, fail: bool) {
            self.write_fail.store(fail, Ordering::SeqCst);
        }
        fn set_pending_write_fail(&self, fail: bool) {
            self.pending_write_fail.store(fail, Ordering::SeqCst);
        }
        fn set_clear_fail(&self, fail: bool) {
            self.clear_fail.store(fail, Ordering::SeqCst);
        }
        fn set_read_fail(&self, fail: bool) {
            self.read_fail.store(fail, Ordering::SeqCst);
        }
    }

    /// Read a durable slot and strip the §11 generation envelope so tests assert
    /// the effective token, not the storage format.
    fn stored_slot_token(
        store: &MemoryStore,
        server: &str,
        device: &str,
        active: bool,
    ) -> Option<String> {
        let raw = if active {
            store.read_refresh(server, device)
        } else {
            store.read_pending_refresh(server, device)
        }
        .unwrap();
        raw.map(|v| decode_refresh_envelope(&v).1.to_string())
    }

    impl CredentialStore for MemoryStore {
        fn read_refresh(
            &self,
            server_instance_id: &str,
            device_id: &str,
        ) -> Result<Option<String>, CredentialStoreError> {
            if self.read_fail.load(Ordering::SeqCst) {
                return Err(CredentialStoreError::BackendUnavailable);
            }
            Ok(self
                .values
                .lock()
                .unwrap()
                .get(&remote_refresh_username(server_instance_id, device_id))
                .cloned())
        }
        fn write_refresh(
            &self,
            server_instance_id: &str,
            device_id: &str,
            token: &str,
        ) -> Result<(), String> {
            if self.write_fail.load(Ordering::SeqCst) {
                return Err("injected keyring write failure".into());
            }
            self.values.lock().unwrap().insert(
                remote_refresh_username(server_instance_id, device_id),
                token.to_string(),
            );
            Ok(())
        }
        fn read_pending_refresh(
            &self,
            server_instance_id: &str,
            device_id: &str,
        ) -> Result<Option<String>, CredentialStoreError> {
            if self.read_fail.load(Ordering::SeqCst) {
                return Err(CredentialStoreError::BackendUnavailable);
            }
            Ok(self
                .values
                .lock()
                .unwrap()
                .get(&pending_username(server_instance_id, device_id))
                .cloned())
        }
        fn write_pending_refresh(
            &self,
            server_instance_id: &str,
            device_id: &str,
            token: &str,
        ) -> Result<(), String> {
            if self.pending_write_fail.load(Ordering::SeqCst) {
                return Err("injected pending keyring write failure".into());
            }
            self.values.lock().unwrap().insert(
                pending_username(server_instance_id, device_id),
                token.to_string(),
            );
            Ok(())
        }
        fn clear_pending_refresh(&self, server_instance_id: &str, device_id: &str) -> Result<(), String> {
            if self.clear_fail.load(Ordering::SeqCst) {
                return Err("injected pending clear failure".into());
            }
            self.values
                .lock()
                .unwrap()
                .remove(&pending_username(server_instance_id, device_id));
            Ok(())
        }
        fn delete_refresh(&self, server_instance_id: &str, device_id: &str) -> Result<(), String> {
            self.values
                .lock()
                .unwrap()
                .remove(&remote_refresh_username(server_instance_id, device_id));
            self.values
                .lock()
                .unwrap()
                .remove(&pending_username(server_instance_id, device_id));
            Ok(())
        }
    }

    struct TempDir(PathBuf);

    impl TempDir {
        fn new(tag: &str) -> Self {
            let dir = std::env::temp_dir().join(format!("ig-broker-{tag}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(&dir).unwrap();
            TempDir(dir)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[derive(Clone, Debug)]
    struct RecordedRequest {
        method: String,
        path: String,
        headers: Vec<(String, String)>,
        body: String,
    }

    struct TestResponse {
        status: u16,
        content_type: &'static str,
        body: String,
        headers: Vec<(String, String)>,
    }

    impl TestResponse {
        fn json(status: u16, body: &str) -> Self {
            TestResponse {
                status,
                content_type: "application/json",
                body: body.to_string(),
                headers: vec![],
            }
        }
        fn redirect(status: u16, location: &str) -> Self {
            TestResponse {
                status,
                content_type: "text/plain",
                body: String::new(),
                headers: vec![("location".to_string(), location.to_string())],
            }
        }
        fn to_bytes(&self) -> String {
            let reason = match self.status {
                200 => "OK",
                201 => "Created",
                204 => "No Content",
                301 => "Moved Permanently",
                302 => "Found",
                303 => "See Other",
                307 => "Temporary Redirect",
                308 => "Permanent Redirect",
                401 => "Unauthorized",
                403 => "Forbidden",
                404 => "Not Found",
                500 => "Internal Server Error",
                _ => "Status",
            };
            let mut out = format!(
                "HTTP/1.1 {} {}\r\nContent-Type: {}\r\n",
                self.status, reason, self.content_type
            );
            for (key, value) in &self.headers {
                out.push_str(&format!("{key}: {value}\r\n"));
            }
            out.push_str(&format!(
                "Content-Length: {}\r\nConnection: close\r\n\r\n{}",
                self.body.len(),
                self.body
            ));
            out
        }
    }

    struct TestServer {
        url: String,
        requests: Arc<StdMutex<Vec<RecordedRequest>>>,
        _handle: tokio::task::JoinHandle<()>,
    }

    impl TestServer {
        async fn start<F>(handler: F) -> Self
        where
            F: Fn(&RecordedRequest) -> TestResponse + Send + Sync + 'static,
        {
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let addr = listener.local_addr().unwrap();
            let requests: Arc<StdMutex<Vec<RecordedRequest>>> = Arc::new(StdMutex::new(Vec::new()));
            let requests_for_task = requests.clone();
            let handler = Arc::new(handler);
            let handle = tokio::spawn(async move {
                loop {
                    let Ok((mut stream, _)) = listener.accept().await else {
                        break;
                    };
                    let requests = requests_for_task.clone();
                    let handler = handler.clone();
                    tokio::spawn(async move {
                        let _ = handle_connection(&mut stream, requests, handler).await;
                    });
                }
            });
            TestServer {
                url: format!("http://{addr}"),
                requests,
                _handle: handle,
            }
        }

        fn url(&self) -> &str {
            &self.url
        }

        fn requests(&self) -> Vec<RecordedRequest> {
            self.requests.lock().unwrap().clone()
        }

        fn paths(&self) -> Vec<String> {
            self.requests().iter().map(|request| request.path.clone()).collect()
        }
    }

    async fn handle_connection(
        stream: &mut TcpStream,
        requests: Arc<StdMutex<Vec<RecordedRequest>>>,
        handler: Arc<dyn Fn(&RecordedRequest) -> TestResponse + Send + Sync>,
    ) -> std::io::Result<()> {
        let mut buffer = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            let count = stream.read(&mut chunk).await?;
            if count == 0 {
                break;
            }
            buffer.extend_from_slice(&chunk[..count]);
            if let Some(position) = find_subsequence(&buffer, b"\r\n\r\n") {
                let head = String::from_utf8_lossy(&buffer[..position]).to_string();
                let mut lines = head.split("\r\n");
                let request_line = lines.next().unwrap_or_default().to_string();
                let mut headers = Vec::new();
                let mut content_length = 0usize;
                for line in lines {
                    if let Some((key, value)) = line.split_once(':') {
                        let name = key.trim().to_ascii_lowercase();
                        let value = value.trim().to_string();
                        if name == "content-length" {
                            content_length = value.parse().unwrap_or(0);
                        }
                        headers.push((name, value));
                    }
                }
                let header_end = position + 4;
                while buffer.len() < header_end + content_length {
                    let count = stream.read(&mut chunk).await?;
                    if count == 0 {
                        break;
                    }
                    buffer.extend_from_slice(&chunk[..count]);
                }
                let available = buffer.len().saturating_sub(header_end);
                let body_bytes = buffer[header_end..header_end + content_length.min(available)].to_vec();
                let body = String::from_utf8_lossy(&body_bytes).to_string();
                let parts: Vec<&str> = request_line.split_whitespace().collect();
                let method = parts.first().copied().unwrap_or("").to_string();
                let path = parts.get(1).copied().unwrap_or("").to_string();
                let recorded = RecordedRequest {
                    method,
                    path,
                    headers,
                    body,
                };
                requests.lock().unwrap().push(recorded.clone());
                let response = handler(&recorded);
                let _ = stream.write_all(response.to_bytes().as_bytes()).await;
                let _ = stream.shutdown().await;
                break;
            }
        }
        Ok(())
    }

    fn find_subsequence(haystack: &[u8], needle: &[u8]) -> Option<usize> {
        haystack
            .windows(needle.len())
            .position(|window| window == needle)
    }

    // ------------------------------------------------------ canned payloads

    const CAPS: &str = r#"{
        "product": "interest-growth",
        "server_version": "0.7.0",
        "api_version": "1",
        "min_client_version": "0.7.0",
        "server_instance_id": "instance-A",
        "server_display_name": "Test Server",
        "runtime_modes": ["desktop-local", "desktop-remote", "android-remote", "browser-remote"],
        "auth": { "mode": "single_owner_devices", "enabled": true, "owner_configured": true },
        "online_first": true,
        "offline_sync": false
    }"#;

    const INFO: &str = r#"{
        "product": "interest-growth",
        "server_version": "0.7.0",
        "api_version": "1",
        "min_client_version": "0.7.0",
        "server_instance_id": "instance-A",
        "server_display_name": "Test Server",
        "auth": { "mode": "single_owner_devices", "enabled": true, "owner_configured": true },
        "tls": false,
        "online_first": true,
        "offline_sync": false
    }"#;

    const LOGIN_OK: &str = r#"{
        "device": { "id": "device-1", "name": "test-device" },
        "tokens": {
            "access_token": "access-1",
            "refresh_token": "refresh-rotated-1",
            "expires_in": 300
        },
        "server": {
            "product": "interest-growth",
            "server_version": "0.7.0",
            "api_version": "1",
            "min_client_version": "0.7.0",
            "server_instance_id": "instance-A",
            "server_display_name": "Test Server"
        }
    }"#;

    const REFRESH_OK: &str = r#"{
        "tokens": {
            "access_token": "access-refreshed",
            "refresh_token": "refresh-rotated-2",
            "expires_in": 300
        }
    }"#;

    fn caps_with(overrides: &[(&str, &str)]) -> String {
        let mut value = serde_json::json!({
            "product": "interest-growth",
            "server_version": "0.7.0",
            "api_version": "1",
            "min_client_version": "0.7.0",
            "server_instance_id": "instance-A",
            "server_display_name": "Test Server",
            "runtime_modes": ["desktop-local", "desktop-remote", "android-remote", "browser-remote"],
            "auth": { "mode": "single_owner_devices", "enabled": true, "owner_configured": true },
            "online_first": true,
            "offline_sync": false,
            "tls": false
        });
        for (key, val) in overrides {
            if *key == "auth.enabled" {
                value["auth"]["enabled"] = serde_json::json!(*val == "true");
            } else if *key == "auth.mode" {
                value["auth"]["mode"] = serde_json::json!(val);
            } else if *key == "auth.owner_configured" {
                // MUST modify the nested auth object, never create a top-level
                // "auth.owner_configured" key (Gate C/D §4.7).
                value["auth"]["owner_configured"] = serde_json::json!(*val == "true");
            } else {
                value[*key] = serde_json::json!(val);
            }
        }
        value.to_string()
    }

    // Gate R0.3 — capabilities with an explicit runtime_modes array (the
    // generic caps_with override would replace the array with a JSON string).
    fn caps_with_modes(modes_json: &str) -> String {
        let mut value = serde_json::json!({
            "product": "interest-growth",
            "server_version": "0.7.0",
            "api_version": "1",
            "min_client_version": "0.7.0",
            "server_instance_id": "instance-A",
            "server_display_name": "Test Server",
            "auth": { "mode": "single_owner_devices", "enabled": true, "owner_configured": true },
            "online_first": true,
            "offline_sync": false,
            "tls": false
        });
        value["runtime_modes"] = serde_json::from_str::<serde_json::Value>(modes_json).unwrap();
        value.to_string()
    }

    fn compatible_handler() -> impl Fn(&RecordedRequest) -> TestResponse + Send + Sync + 'static {
        |request: &RecordedRequest| match request.path.as_str() {
            "/api/system/capabilities" => TestResponse::json(200, CAPS),
            "/api/auth/server-info" => TestResponse::json(200, INFO),
            "/api/auth/owner/login" => TestResponse::json(201, LOGIN_OK),
            "/api/auth/device/refresh" => TestResponse::json(200, REFRESH_OK),
            "/api/auth/device/revoke" => TestResponse::json(204, ""),
            _ => TestResponse::json(404, r#"{"detail":"not found"}"#),
        }
    }

    fn seed_enrollment(
        app_data: &Path,
        origin: &str,
        instance_id: &str,
        device_id: &str,
        store: &dyn CredentialStore,
    ) -> RemoteEnrollment {
        let enrollment = RemoteEnrollment {
            normalized_origin: origin.to_string(),
            server_instance_id: instance_id.to_string(),
            server_display_name: "Test Server".into(),
            product: API_PRODUCT.into(),
            api_version: SUPPORTED_API_VERSION.into(),
            server_version: "0.7.0".into(),
            min_client_version: "0.7.0".into(),
            device_id: device_id.to_string(),
            device_name: "test-device".into(),
            platform: "macos".into(),
            app_version: "0.7.0".into(),
            last_verified_at: "0".into(),
        };
        save_enrollment(app_data, &enrollment).unwrap();
        store
            .write_refresh(instance_id, device_id, "refresh-seed")
            .unwrap();
        enrollment
    }

    // ---------------------------------------------------------- pure units

    #[test]
    fn enrollment_origin_requires_https() {
        assert!(normalize_enrollment_origin("http://ig.example.com").is_err());
        assert!(normalize_enrollment_origin("ftp://ig.example.com").is_err());
        assert!(normalize_enrollment_origin("https://ig.example.com").is_ok());
    }

    #[test]
    fn enrollment_origin_allows_loopback_http_for_development() {
        assert_eq!(
            normalize_enrollment_origin("http://127.0.0.1:8000").unwrap(),
            "http://127.0.0.1:8000"
        );
        assert_eq!(
            normalize_enrollment_origin("http://localhost:8000").unwrap(),
            "http://localhost:8000"
        );
        assert!(normalize_enrollment_origin("http://192.168.1.20").is_err());
    }

    #[test]
    fn enrollment_origin_allows_private_and_lan_hosts_over_https() {
        assert_eq!(
            normalize_enrollment_origin("https://192.168.1.20").unwrap(),
            "https://192.168.1.20"
        );
        assert_eq!(
            normalize_enrollment_origin("https://my-server.local").unwrap(),
            "https://my-server.local"
        );
    }

    // Phase 4d — CI-only optional TLS trust root. Fail-closed: a missing PEM
    // (e.g. the CI property `ig.ci.tls_ca_path` points at a file that is not
    // on disk) must be a hard Err at setup, never a silent fallthrough. (The
    // happy path — sign with an ephemeral CA, trust it via
    // add_root_certificate — is exercised end-to-end by the upgrade-in-place
    // CI CDP job. Content-level DER validity is enforced by rustls at first
    // handshake, not by reqwest's from_pem, so we assert the deterministic
    // missing-file guard here.)
    #[test]
    fn trust_root_missing_file_is_hard_error() {
        let err = load_pem_trust_root(&PathBuilder::for_missing());
        assert!(err.is_err(), "missing trust root must fail-closed");
        assert!(err.unwrap_err().contains("cannot read TLS trust root"));
    }

    /// Minimal helper that yields a guaranteed-missing Path (no filesystem
    /// write needed), avoiding a real temp file for the missing-file case.
    struct PathBuilder;
    impl PathBuilder {
        fn for_missing() -> std::path::PathBuf {
            std::env::temp_dir().join(format!(
                "ig_trust_root_missing_{}.pem",
                std::process::id()
            ))
        }
    }

    #[test]
    fn enrollment_origin_rejects_embedded_credentials_query_fragment_path() {
        assert!(normalize_enrollment_origin("https://user:pass@ig.example.com").is_err());
        assert!(normalize_enrollment_origin("https://ig.example.com?a=1").is_err());
        assert!(normalize_enrollment_origin("https://ig.example.com#frag").is_err());
        assert!(normalize_enrollment_origin("https://ig.example.com/subpath").is_err());
        assert!(normalize_enrollment_origin("not a url").is_err());
    }

    #[test]
    fn enrollment_origin_normalizes_trailing_slash_and_case() {
        assert_eq!(
            normalize_enrollment_origin("https://IG.Example.com/").unwrap(),
            "https://ig.example.com"
        );
    }

    #[test]
    fn relative_path_validation() {
        assert!(assert_relative_path("/api/system/capabilities").is_ok());
        assert!(assert_relative_path("api/foo").is_err());
        assert!(assert_relative_path("https://evil.example.com/api/foo").is_err());
        assert!(assert_relative_path("http://evil.example.com/x").is_err());
        assert!(assert_relative_path("//evil.example.com/x").is_err());
        assert!(assert_relative_path("/\\evil.example.com/x").is_err());
    }

    #[test]
    fn refresh_key_namespace_is_isolated_per_server_and_device() {
        let a1 = remote_refresh_username("server-A", "device-1");
        let a2 = remote_refresh_username("server-A", "device-2");
        let b1 = remote_refresh_username("server-B", "device-1");
        assert_ne!(a1, a2);
        assert_ne!(a1, b1);
        assert_eq!(a1, remote_refresh_username("server-A", "device-1"));
        assert!(a1.starts_with("remote-refresh:server-A:"));
        assert!(b1.starts_with("remote-refresh:server-B:"));
    }

    #[test]
    fn version_comparison_is_numeric() {
        assert_eq!(
            compare_versions("0.7.0", "0.7.0").unwrap(),
            std::cmp::Ordering::Equal
        );
        assert_eq!(
            compare_versions("0.7.0", "0.10.0").unwrap(),
            std::cmp::Ordering::Less
        );
        assert_eq!(
            compare_versions("0.10.0", "0.7.0").unwrap(),
            std::cmp::Ordering::Greater
        );
        assert_eq!(compare_versions("1.2", "1.2.0").unwrap(), std::cmp::Ordering::Equal);
        assert_eq!(
            compare_versions("0.6.0", "0.7.0").unwrap(),
            std::cmp::Ordering::Less
        );
    }

    #[test]
    fn version_parser_accepts_valid_and_rejects_malformed_or_overflowing() {
        // Gate C/D §4.3 — accepted forms.
        for valid in ["0.7.0", "0.10.0", "1", "1.2", "1.2.0"] {
            assert!(ParsedVersion::parse(valid).is_ok(), "{valid} should parse");
        }
        // Gate C/D §4.3 — malformed / overflowing forms must fail closed.
        for invalid in [
            "1..2",
            "1.2.",
            ".1.2",
            "1.a.2",
            "999999999999999999999999999999999.0.0",
            "4294967296",
            "0.7.0-alpha",
        ] {
            assert!(ParsedVersion::parse(invalid).is_err(), "{invalid} must be rejected");
        }
        // A huge server minimum must fail closed as PROTOCOL_ERROR, never be
        // treated as 0.0.0 (which would otherwise pass the compatibility gate).
        let err = compare_versions(CLIENT_APP_VERSION, "999999999999999999999999999999999.0.0")
            .unwrap_err();
        assert!(err.contains(ERR_PROTOCOL), "got: {err}");
    }

    fn broker_with(store: Arc<dyn CredentialStore>) -> RemoteBroker {
        RemoteBroker::new(store).unwrap()
    }

    // ---------------------------------------------------- P1 redirect tests

    #[tokio::test]
    async fn login_rejects_identity_swap_between_fresh_probe_and_login() {
        // HIGH-3 (TOCTOU): the server behind the URL answers instance-A during
        // the fresh probe but instance-B at the login endpoint. The login must
        // be refused and NO credential may be written.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let swapped = LOGIN_OK.replace("instance-A", "instance-B");
        let server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/owner/login" => TestResponse::json(201, &swapped),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("identity-swap-login");
        let result = broker
            .login(&app_data.0, server.url(), "correct-horse", "device", "macos", "0.7.0")
            .await;
        assert!(result.is_err());
        let error = result.unwrap_err();
        assert!(error.contains("identity"), "got: {error}");
        assert!(!error.contains("correct-horse"));
        // Nothing was persisted: no enrollment, no refresh credential.
        assert!(!app_data.0.join(ENROLLMENT_FILE).exists());
        assert!(store.read_refresh("instance-A", "device-1").unwrap().is_none());
        assert!(store.read_refresh("instance-B", "device-1").unwrap().is_none());
    }

    #[tokio::test]
    async fn login_never_follows_307_redirect_and_secret_stays_local() {
        for status in [301u16, 302, 303, 307, 308] {
            let store = Arc::new(MemoryStore::new());
            let broker = broker_with(store.clone());
            let server = TestServer::start(move |request: &RecordedRequest| {
                match request.path.as_str() {
                    "/api/system/capabilities" => TestResponse::json(200, CAPS),
                    "/api/auth/server-info" => TestResponse::json(200, INFO),
                    "/api/auth/owner/login" => TestResponse::redirect(status, "/api/auth/owner/login/evil"),
                    _ => TestResponse::json(404, "{}"),
                }
            })
            .await;
            let app_data = TempDir::new("redirect-login");
            let result = broker
                .login(&app_data.0, server.url(), "correct-horse", "device", "macos", "0.7.0")
                .await;
            assert!(result.is_err(), "redirect {status} must be fail-closed");
            let error = result.unwrap_err();
            assert!(!error.contains("correct-horse"), "error must not leak the password");
            let paths = server.paths();
            assert!(!paths.iter().any(|path| path.contains("evil")));
            assert!(
                paths.iter().filter(|path| path.as_str() == "/api/auth/owner/login").count() == 1
            );
        }
    }

    #[tokio::test]
    async fn refresh_never_follows_redirect_and_token_stays_local() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::redirect(302, "/api/auth/device/refresh/evil"),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("redirect-refresh");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let result = broker.refresh_session_token(&enrollment).await;
        assert!(result.is_err());
        let error = result.unwrap_err();
        assert!(!error.contains("refresh-seed"));
        let paths = server.paths();
        assert!(!paths.iter().any(|path| path.contains("evil")));
    }

    #[tokio::test]
    async fn bootstrap_never_follows_redirect_and_token_stays_local() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => {
                    TestResponse::json(200, &caps_with(&[("auth.owner_configured", "false")]))
                }
                "/api/auth/server-info" => {
                    TestResponse::json(200, &caps_with(&[("auth.owner_configured", "false")]))
                }
                "/api/auth/owner/bootstrap" => TestResponse::redirect(302, "/api/auth/owner/bootstrap/evil"),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let result = broker
            .bootstrap_owner(server.url(), "correct-horse", "bootstrap-secret")
            .await;
        // Gate C/D §4.7 — the server genuinely reports owner_configured=false
        // (nested `auth.owner_configured`, NOT a top-level string key), so the
        // client really enters the bootstrap path and really sends the secret
        // to the ORIGINAL endpoint exactly once. This is not a vacuous pass
        // caused by skipping bootstrap entirely.
        assert!(result.is_err());
        let requests = server.requests();
        let bootstrap_requests: Vec<&RecordedRequest> = requests
            .iter()
            .filter(|request| request.path == "/api/auth/owner/bootstrap")
            .collect();
        assert_eq!(bootstrap_requests.len(), 1, "original bootstrap endpoint must be hit exactly once");
        assert!(
            bootstrap_requests[0]
                .headers
                .iter()
                .any(|(key, value)| key == "x-pg-owner-bootstrap-token" && value == "bootstrap-secret"),
            "the bootstrap secret must reach the original endpoint once"
        );
        // The redirect target never receives any request (fail-closed on 3xx).
        assert!(
            !server
                .paths()
                .iter()
                .any(|path| path.contains("evil")),
            "redirect target must receive 0 requests"
        );
    }

    // ------------------------------------------------- P2/P4 compatibility

    #[tokio::test]
    async fn probe_rejects_wrong_product() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, &caps_with(&[("product", "other-app")])),
                // Consistent across both endpoints so the compatibility gate
                // (not the cross-validation) is what blocks.
                "/api/auth/server-info" => TestResponse::json(200, &caps_with(&[("product", "other-app")])),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let result = broker.probe_desktop_remote(server.url()).await;
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("product"));
    }

    #[tokio::test]
    async fn probe_rejects_wrong_api_version() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, &caps_with(&[("api_version", "2")])),
                "/api/auth/server-info" => TestResponse::json(200, &caps_with(&[("api_version", "2")])),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        assert!(broker.probe_desktop_remote(server.url()).await.is_err());
    }

    #[tokio::test]
    async fn probe_rejects_min_client_above_current() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, &caps_with(&[("min_client_version", "99.0.0")])),
                "/api/auth/server-info" => TestResponse::json(200, &caps_with(&[("min_client_version", "99.0.0")])),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker.probe_desktop_remote(server.url()).await.unwrap_err();
        assert!(error.contains("minimum"));
    }

    #[tokio::test]
    async fn probe_rejects_runtime_not_in_modes() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        // Only desktop-local is advertised, so desktop-remote is unsupported.
        let caps = r#"{"product":"interest-growth","server_version":"0.7.0","api_version":"1",
            "min_client_version":"0.7.0","server_instance_id":"instance-A",
            "server_display_name":"Test","runtime_modes":["desktop-local"],
            "auth":{"mode":"single_owner_devices","enabled":true,"owner_configured":true},
            "online_first":true,"offline_sync":false,"tls":false}"#;
        let server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, caps),
                "/api/auth/server-info" => TestResponse::json(200, caps),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker.probe_desktop_remote(server.url()).await.unwrap_err();
        assert!(error.contains("runtime"));
    }

    // ------------------------------------------- Gate R0.3 expected runtime

    #[tokio::test]
    async fn android_probe_accepts_server_advertising_only_android_remote() {
        // Directed R0.3 case 1: server supports ONLY android-remote and the
        // Android client probes for android-remote → PASS.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let caps = caps_with_modes(r#"["android-remote"]"#);
        let server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, &caps),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let result = broker
            .probe_for_runtime(server.url(), RUNTIME_ANDROID_REMOTE)
            .await;
        assert!(result.is_ok(), "android probe must pass: {:?}", result.err());
    }

    #[tokio::test]
    async fn android_probe_rejects_server_advertising_only_desktop_remote() {
        // Directed R0.3 case 2: server supports ONLY desktop-remote and the
        // Android client probes for android-remote → UNSUPPORTED_SERVER, so it
        // can never "coincidentally pass" via desktop-remote.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let caps = caps_with_modes(r#"["desktop-remote"]"#);
        let server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, &caps),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker
            .probe_for_runtime(server.url(), RUNTIME_ANDROID_REMOTE)
            .await
            .unwrap_err();
        assert!(error.contains(ERR_UNSUPPORTED_SERVER), "got: {error}");
        assert!(error.contains("runtime"), "got: {error}");
    }

    #[tokio::test]
    async fn desktop_probe_rejects_server_advertising_only_android_remote() {
        // Directed R0.3 case 3: server supports ONLY android-remote and a
        // desktop-remote client probes → reject.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let caps = caps_with_modes(r#"["android-remote"]"#);
        let server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, &caps),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker
            .probe_for_runtime(server.url(), RUNTIME_DESKTOP_REMOTE)
            .await
            .unwrap_err();
        assert!(error.contains(ERR_UNSUPPORTED_SERVER), "got: {error}");
        assert!(error.contains("runtime"), "got: {error}");
    }

    #[tokio::test]
    async fn probe_for_runtime_rejects_non_remote_runtime_id() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|_request: &RecordedRequest| TestResponse::json(200, CAPS))
            .await;
        let error = broker
            .probe_for_runtime(server.url(), "desktop-local")
            .await
            .unwrap_err();
        assert!(error.contains(ERR_UNSUPPORTED_SERVER), "got: {error}");
    }

    #[tokio::test]
    async fn android_login_requires_android_remote_advertised() {
        // Directed R0.3 credential path: an Android broker (expected runtime =
        // android-remote) must refuse login to a server that only advertises
        // desktop-remote, BEFORE any credential is sent or persisted.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        broker.set_expected_runtime(RUNTIME_ANDROID_REMOTE).await;
        let caps = caps_with_modes(r#"["desktop-remote"]"#);
        let server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, &caps),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/owner/login" => TestResponse::json(201, LOGIN_OK),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("android-login-incompat");
        let result = broker
            .login(&app_data.0, server.url(), "correct-horse", "device", "android", "0.7.0")
            .await;
        assert!(result.is_err());
        assert!(
            result.unwrap_err().contains(ERR_UNSUPPORTED_SERVER),
            "login must be refused as unsupported before sending credentials"
        );
        // No credential was persisted and the owner password never reached the
        // login endpoint (probe fails before any credential-bearing request).
        assert!(!app_data.0.join(ENROLLMENT_FILE).exists());
        assert!(store.read_refresh("instance-A", "device-1").unwrap().is_none());
    }

    #[tokio::test]
    async fn android_login_accepts_server_advertising_only_android_remote() {
        // Directed R0.3 credential path: an Android broker (expected runtime =
        // android-remote) logs into a server that advertises android-remote.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        broker.set_expected_runtime(RUNTIME_ANDROID_REMOTE).await;
        let caps = caps_with_modes(r#"["android-remote"]"#);
        let server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, &caps),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/owner/login" => TestResponse::json(201, LOGIN_OK),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("android-login-ok");
        let result = broker
            .login(&app_data.0, server.url(), "correct-horse", "device", "android", "0.7.0")
            .await;
        assert!(result.is_ok(), "android login must succeed: {:?}", result.err());
        // The refresh credential was persisted to the OS-backed store.
        assert!(store.read_refresh("instance-A", "device-1").unwrap().is_some());
    }

    #[tokio::test]
    async fn probe_rejects_auth_disabled() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, &caps_with(&[("auth.enabled", "false")])),
                "/api/auth/server-info" => TestResponse::json(200, &caps_with(&[("auth.enabled", "false")])),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker.probe_desktop_remote(server.url()).await.unwrap_err();
        assert!(error.contains("authentication"));
    }

    #[tokio::test]
    async fn probe_rejects_wrong_auth_mode() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => {
                    TestResponse::json(200, &caps_with(&[("auth.mode", "multi_user")]))
                }
                "/api/auth/server-info" => {
                    TestResponse::json(200, &caps_with(&[("auth.mode", "multi_user")]))
                }
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker.probe_desktop_remote(server.url()).await.unwrap_err();
        assert!(error.contains("authentication mode"));
    }

    #[tokio::test]
    async fn incompatible_login_never_reaches_credential_endpoints() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, &caps_with(&[("product", "other-app")])),
                "/api/auth/server-info" => TestResponse::json(200, &caps_with(&[("product", "other-app")])),
                "/api/auth/owner/login" => TestResponse::json(201, LOGIN_OK),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("incompat-login");
        let result = broker
            .login(&app_data.0, server.url(), "correct-horse", "device", "macos", "0.7.0")
            .await;
        assert!(result.is_err());
        // The password must never reach the login endpoint on an incompatible server.
        let login_count = server
            .requests()
            .iter()
            .filter(|request| request.path == "/api/auth/owner/login")
            .count();
        assert_eq!(login_count, 0);
        for request in server.requests() {
            assert!(!request.body.contains("correct-horse"));
        }
    }

    #[tokio::test]
    async fn probe_rejects_inconsistent_metadata_between_endpoints() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                // server-info claims a different instance than capabilities.
                "/api/auth/server-info" => {
                    TestResponse::json(200, &INFO.replace("instance-A", "instance-B"))
                }
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker.probe(server.url()).await.unwrap_err();
        assert!(error.contains("inconsistent"));
    }

    // --------------------------------------------------------- P5 identity

    #[tokio::test]
    async fn identity_preflight_blocks_replaced_server_before_credential() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => {
                    TestResponse::json(200, &caps_with(&[("server_instance_id", "instance-B")]))
                }
                "/api/auth/server-info" => {
                    TestResponse::json(200, &INFO.replace("instance-A", "instance-B"))
                }
                "/api/auth/device/refresh" => TestResponse::json(200, REFRESH_OK),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("identity-block");
        // Enrollment saved for instance-A, but the server behind the URL is now B.
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let result = broker.refresh_session_token(&enrollment).await;
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("identity"));
        // The refresh credential must never leave the process.
        let refresh_count = server
            .requests()
            .iter()
            .filter(|request| request.path == "/api/auth/device/refresh")
            .count();
        assert_eq!(refresh_count, 0);
    }

    #[tokio::test]
    async fn identity_match_allows_credential_use() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(compatible_handler()).await;
        let app_data = TempDir::new("identity-ok");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let result = broker.refresh_session_token(&enrollment).await;
        assert_eq!(result.unwrap(), "access-refreshed");
    }

    // ------------------------------------------------------ P7 single-flight

    #[tokio::test]
    async fn concurrent_callers_share_exactly_one_refresh() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let refresh_calls = Arc::new(AtomicUsize::new(0));
        let refresh_counter = refresh_calls.clone();
        let server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => {
                    refresh_counter.fetch_add(1, Ordering::SeqCst);
                    TestResponse::json(200, REFRESH_OK)
                }
                // Authenticated endpoint always 401s so every caller goes through
                // the auth-recovery path; the rotation must still happen exactly
                // once (generation-coalesced single flight).
                "/api/test/data" => TestResponse::json(401, r#"{"detail":"unauthorized"}"#),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("single-flight");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        // Seed a locally-valid access credential so NO init-refresh happens:
        // the ONLY refresh must be the single forced rotation for the 401s.
        broker.set_session("access-seed", 3600).await;
        let headers = HashMap::new();
        let mut tasks = Vec::new();
        for _ in 0..20 {
            let broker = broker.clone();
            let app_data = app_data.0.clone();
            let headers = headers.clone();
            tasks.push(tokio::spawn(async move {
                broker
                    .api_request(&app_data, "/api/test/data", "GET", None, &headers)
                    .await
            }));
        }
        let mut results = Vec::new();
        for task in tasks {
            results.push(task.await.unwrap());
        }
        // Exactly one forced rotation shared by all concurrent 401s; the access
        // credential that the server rejected is never reused. Every caller
        // converges on LoginExpired (no infinite loop).
        assert_eq!(refresh_calls.load(Ordering::SeqCst), 1);
        for result in results {
            assert!(result.is_err());
            assert!(result.unwrap_err().contains("session expired"));
        }
    }

    #[tokio::test]
    async fn refresh_401_retries_exactly_once_then_login_expired() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(200, REFRESH_OK),
                "/api/test/data" => TestResponse::json(401, r#"{"detail":"unauthorized"}"#),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("retry-once");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        // Seed a locally-valid access credential so the ONLY refresh is the one
        // forced by the 401 itself (HIGH-1: a rejected access credential is
        // never reused, even when locally unexpired).
        broker.set_session("access-seed", 3600).await;
        let result = broker
            .api_request(&app_data.0, "/api/test/data", "GET", None, &HashMap::new())
            .await;
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("session expired"));
        // Exactly one refresh (forced by the 401) and the request was retried
        // exactly once (no retry loop).
        let refresh_count = server
            .requests()
            .iter()
            .filter(|request| request.path == "/api/auth/device/refresh")
            .count();
        assert_eq!(refresh_count, 1);
        let request_count = server
            .requests()
            .iter()
            .filter(|request| request.path == "/api/test/data")
            .count();
        assert_eq!(request_count, 2);
    }

    // ------------------------------------------- Gate C/D §4.1 status classes

    #[tokio::test]
    async fn refresh_401_is_login_expired_and_sets_denied() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(401, r#"{"detail":"refresh denied"}"#),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("refresh-401");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let error = broker.refresh_session_token(&enrollment).await.unwrap_err();
        assert!(error.contains(ERR_LOGIN_EXPIRED), "got: {error}");
        assert!(*broker.state.refresh_denied.lock().await, "401 must set refresh_denied");
    }

    #[tokio::test]
    async fn refresh_429_is_not_login_expired_and_recovers() {
        // Gate C/D §4.1 — a 429 rate limit is transient: it maps to RATE_LIMITED,
        // does NOT set refresh_denied, does NOT force re-login, and a later
        // successful refresh still works.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let refresh_calls = Arc::new(AtomicUsize::new(0));
        let counter = refresh_calls.clone();
        let server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => {
                    let n = counter.fetch_add(1, Ordering::SeqCst);
                    if n == 0 {
                        TestResponse::json(
                            429,
                            r#"{"detail":"too many requests","retry_after":1}"#,
                        )
                    } else {
                        TestResponse::json(200, REFRESH_OK)
                    }
                }
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("refresh-429");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let error = broker.refresh_session_token(&enrollment).await.unwrap_err();
        assert!(error.contains(ERR_RATE_LIMITED), "got: {error}");
        assert!(!*broker.state.refresh_denied.lock().await, "429 must NOT set refresh_denied");
        // Network/rate-limit recovery: the next refresh succeeds.
        let refreshed = broker.refresh_session_token(&enrollment).await;
        assert_eq!(refreshed.unwrap(), "access-refreshed");
    }

    #[tokio::test]
    async fn refresh_503_is_not_login_expired() {
        // Gate C/D §4.1 — a 5xx is a transient server failure: SERVER_UNAVAILABLE,
        // never LoginExpired, never refresh_denied.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(503, "service unavailable"),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("refresh-503");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let error = broker.refresh_session_token(&enrollment).await.unwrap_err();
        assert!(error.contains(ERR_SERVER_UNAVAILABLE), "got: {error}");
        assert!(!*broker.state.refresh_denied.lock().await, "503 must NOT set refresh_denied");
    }

    #[tokio::test]
    async fn refresh_3xx_is_protocol_error() {
        // Gate C/D §4.1 — redirects stay disabled; a 3xx on refresh is a
        // protocol violation, not a credential denial.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(302, "redirect"),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("refresh-3xx");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let error = broker.refresh_session_token(&enrollment).await.unwrap_err();
        assert!(error.contains(ERR_PROTOCOL), "got: {error}");
        assert!(!*broker.state.refresh_denied.lock().await, "3xx must NOT set refresh_denied");
    }

    // ----------------------------------------- HIGH-1: producer taxonomy.

    #[tokio::test]
    async fn metadata_probe_429_is_rate_limited() {
        // The metadata producer is not credential-bound: a 429 is RATE_LIMITED,
        // never UnsupportedServer / PROTOCOL_ERROR (which previously made a 429
        // look like an incompatible server).
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => {
                    TestResponse::json(429, r#"{"detail":"too many requests"}"#)
                }
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker.probe_desktop_remote(server.url()).await.unwrap_err();
        assert!(error.contains(ERR_RATE_LIMITED), "got: {error}");
        assert!(!error.contains(ERR_UNSUPPORTED_SERVER), "got: {error}");
    }

    #[tokio::test]
    async fn metadata_probe_5xx_is_server_unavailable() {
        for status in [500u16, 503] {
            let store = Arc::new(MemoryStore::new());
            let broker = broker_with(store.clone());
            let server = TestServer::start(move |request: &RecordedRequest| {
                match request.path.as_str() {
                    "/api/system/capabilities" => TestResponse::json(status, "boom"),
                    "/api/auth/server-info" => TestResponse::json(200, INFO),
                    _ => TestResponse::json(404, "{}"),
                }
            })
            .await;
            let error = broker.probe_desktop_remote(server.url()).await.unwrap_err();
            assert!(error.contains(ERR_SERVER_UNAVAILABLE), "{status} got: {error}");
            assert!(!error.contains(ERR_UNSUPPORTED_SERVER), "{status} got: {error}");
        }
    }

    #[tokio::test]
    async fn metadata_probe_3xx_is_protocol_error() {
        for status in [301u16, 302, 307, 308] {
            let store = Arc::new(MemoryStore::new());
            let broker = broker_with(store.clone());
            let server = TestServer::start(move |request: &RecordedRequest| {
                match request.path.as_str() {
                    "/api/system/capabilities" => {
                        TestResponse::redirect(status, "/api/system/capabilities/start")
                    }
                    "/api/auth/server-info" => TestResponse::json(200, INFO),
                    _ => TestResponse::json(404, "{}"),
                }
            })
            .await;
            let error = broker.probe_desktop_remote(server.url()).await.unwrap_err();
            assert!(error.contains(ERR_PROTOCOL), "{status} got: {error}");
        }
    }

    #[tokio::test]
    async fn metadata_probe_200_malformed_json_is_protocol_error() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, "not-json{{{"),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker.probe_desktop_remote(server.url()).await.unwrap_err();
        assert!(error.contains(ERR_PROTOCOL), "got: {error}");
    }

    #[tokio::test]
    async fn metadata_probe_200_missing_field_is_protocol_error() {
        // A 200 with a JSON body that misses a required metadata field must
        // fail closed as PROTOCOL_ERROR (never a defaulted pass).
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, r#"{"product":"interest-growth"}"#),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker.probe_desktop_remote(server.url()).await.unwrap_err();
        assert!(error.contains(ERR_PROTOCOL), "got: {error}");
    }

    #[tokio::test]
    async fn login_201_valid_succeeds() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/owner/login" => TestResponse::json(201, LOGIN_OK),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("login-ok");
        let result = broker
            .login(&app_data.0, server.url(), "correct-horse", "device", "macos", "0.7.0")
            .await;
        assert!(result.is_ok(), "valid 201 login must succeed");
        // Enrollment and refresh credential are persisted.
        assert!(app_data.0.join(ENROLLMENT_FILE).exists());
        assert!(store.read_refresh("instance-A", "device-1").unwrap().is_some());
    }

    #[tokio::test]
    async fn login_429_is_rate_limited_not_login_expired() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/owner/login" => {
                    TestResponse::json(429, r#"{"detail":"too many login attempts"}"#)
                }
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("login-429");
        let error = broker
            .login(&app_data.0, server.url(), "correct-horse", "device", "macos", "0.7.0")
            .await
            .unwrap_err();
        assert!(error.contains(ERR_RATE_LIMITED), "got: {error}");
        assert!(!error.contains(ERR_LOGIN_EXPIRED), "got: {error}");
    }

    #[tokio::test]
    async fn login_5xx_is_server_unavailable_not_login_expired() {
        for status in [500u16, 503] {
            let store = Arc::new(MemoryStore::new());
            let broker = broker_with(store.clone());
            let server = TestServer::start(move |request: &RecordedRequest| {
                match request.path.as_str() {
                    "/api/system/capabilities" => TestResponse::json(200, CAPS),
                    "/api/auth/server-info" => TestResponse::json(200, INFO),
                    "/api/auth/owner/login" => TestResponse::json(status, "boom"),
                    _ => TestResponse::json(404, "{}"),
                }
            })
            .await;
            let app_data = TempDir::new("login-5xx");
            let error = broker
                .login(&app_data.0, server.url(), "correct-horse", "device", "macos", "0.7.0")
                .await
                .unwrap_err();
            assert!(error.contains(ERR_SERVER_UNAVAILABLE), "{status} got: {error}");
            assert!(!error.contains(ERR_LOGIN_EXPIRED), "{status} got: {error}");
        }
    }

    #[tokio::test]
    async fn login_401_403_is_credential_denial() {
        for status in [401u16, 403] {
            let store = Arc::new(MemoryStore::new());
            let broker = broker_with(store.clone());
            let server = TestServer::start(move |request: &RecordedRequest| {
                match request.path.as_str() {
                    "/api/system/capabilities" => TestResponse::json(200, CAPS),
                    "/api/auth/server-info" => TestResponse::json(200, INFO),
                    "/api/auth/owner/login" => {
                        TestResponse::json(status, r#"{"detail":"invalid owner password"}"#)
                    }
                    _ => TestResponse::json(404, "{}"),
                }
            })
            .await;
            let app_data = TempDir::new("login-auth");
            let error = broker
                .login(&app_data.0, server.url(), "wrong-horse", "device", "macos", "0.7.0")
                .await
                .unwrap_err();
            assert!(error.contains(ERR_LOGIN_EXPIRED), "{status} got: {error}");
            assert!(!error.contains("wrong-horse"), "{status} error must not leak the password");
        }
    }

    #[tokio::test]
    async fn login_redirect_is_protocol_error() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/owner/login" => {
                    TestResponse::redirect(302, "/api/auth/owner/login/evil")
                }
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("login-redirect");
        let error = broker
            .login(&app_data.0, server.url(), "correct-horse", "device", "macos", "0.7.0")
            .await
            .unwrap_err();
        assert!(error.contains(ERR_PROTOCOL), "got: {error}");
    }

    #[tokio::test]
    async fn login_malformed_201_body_is_protocol_error() {
        // A 201 with a non-JSON body is PROTOCOL_ERROR, never a silently
        // defaulted credential.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/owner/login" => TestResponse::json(201, "not valid json"),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("login-malformed");
        let error = broker
            .login(&app_data.0, server.url(), "correct-horse", "device", "macos", "0.7.0")
            .await
            .unwrap_err();
        assert!(error.contains(ERR_PROTOCOL), "got: {error}");
    }

    // ----------------------------------------- §12: login metadata binding.
    // The enrollment's compatibility metadata must come from the FRESH verified
    // server; any metadata the login body echoes must AGREE, else the login is
    // rejected instead of persisting conflicting/empty values.

    async fn login_with_server_block(server_block: String) -> Result<RemoteEnrollment, String> {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let test_server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/owner/login" => {
                    let body = format!(
                        r#"{{"device":{{"id":"device-1","name":"test-device"}},"tokens":{{"access_token":"access-1","refresh_token":"refresh-rotated-1","expires_in":300}},"server":{server_block}}}"#
                    );
                    TestResponse::json(201, &body)
                }
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("login-meta");
        broker
            .login(
                &app_data.0,
                test_server.url(),
                "correct-horse",
                "device",
                "macos",
                "0.7.0",
            )
            .await
            .map_err(|error| error)?;
        load_enrollment(&app_data.0)
            .ok_or_else(|| "enrollment file was not persisted".to_string())
    }

    #[tokio::test]
    async fn login_conflicting_product_is_identity_changed() {
        let block = r#"{"product":"acme-other","server_version":"0.7.0","api_version":"1","min_client_version":"0.7.0","server_instance_id":"instance-A","server_display_name":"Test Server"}"#;
        let error = login_with_server_block(block.into()).await.unwrap_err();
        assert!(error.contains(ERR_IDENTITY_CHANGED), "got: {error}");
        assert!(error.contains("product"), "got: {error}");
    }

    #[tokio::test]
    async fn login_conflicting_api_version_is_identity_changed() {
        let block = r#"{"product":"interest-growth","server_version":"0.7.0","api_version":"999","min_client_version":"0.7.0","server_instance_id":"instance-A","server_display_name":"Test Server"}"#;
        let error = login_with_server_block(block.into()).await.unwrap_err();
        assert!(error.contains(ERR_IDENTITY_CHANGED), "got: {error}");
        assert!(error.contains("api_version"), "got: {error}");
    }

    #[tokio::test]
    async fn login_conflicting_min_client_is_identity_changed() {
        let block = r#"{"product":"interest-growth","server_version":"0.7.0","api_version":"1","min_client_version":"9.9.9","server_instance_id":"instance-A","server_display_name":"Test Server"}"#;
        let error = login_with_server_block(block.into()).await.unwrap_err();
        assert!(error.contains(ERR_IDENTITY_CHANGED), "got: {error}");
        assert!(error.contains("min_client_version"), "got: {error}");
    }

    #[tokio::test]
    async fn login_conflicting_server_version_is_identity_changed() {
        let block = r#"{"product":"interest-growth","server_version":"1.0.9","api_version":"1","min_client_version":"0.7.0","server_instance_id":"instance-A","server_display_name":"Test Server"}"#;
        let error = login_with_server_block(block.into()).await.unwrap_err();
        assert!(error.contains(ERR_IDENTITY_CHANGED), "got: {error}");
        assert!(error.contains("server_version"), "got: {error}");
    }

    #[tokio::test]
    async fn login_conflicting_display_name_is_identity_changed() {
        let block = r#"{"product":"interest-growth","server_version":"0.7.0","api_version":"1","min_client_version":"0.7.0","server_instance_id":"instance-A","server_display_name":"Evil Mirror"}"#;
        let error = login_with_server_block(block.into()).await.unwrap_err();
        assert!(error.contains(ERR_IDENTITY_CHANGED), "got: {error}");
        assert!(error.contains("server_display_name"), "got: {error}");
    }

    #[tokio::test]
    async fn login_missing_login_body_metadata_uses_verified_values() {
        // The login body omits the compatibility metadata entirely; the
        // enrollment must fall back to the verified preflight values (never an
        // empty string), and the refresh credential is persisted.
        let block = r#"{"server_instance_id":"instance-A"}"#;
        let enrollment = login_with_server_block(block.into()).await.expect("must succeed");
        assert_eq!(enrollment.product, "interest-growth");
        assert_eq!(enrollment.api_version, "1");
        assert_eq!(enrollment.server_version, "0.7.0");
        assert_eq!(enrollment.min_client_version, "0.7.0");
        assert_eq!(enrollment.server_display_name, "Test Server");
        assert!(!enrollment.product.is_empty() && !enrollment.server_display_name.is_empty());
    }

    #[tokio::test]
    async fn bootstrap_429_is_rate_limited() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => {
                    TestResponse::json(200, &caps_with(&[("auth.owner_configured", "false")]))
                }
                "/api/auth/server-info" => {
                    TestResponse::json(200, &caps_with(&[("auth.owner_configured", "false")]))
                }
                "/api/auth/owner/bootstrap" => {
                    TestResponse::json(429, r#"{"detail":"too many requests"}"#)
                }
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker
            .bootstrap_owner(server.url(), "correct-horse", "bootstrap-secret")
            .await
            .unwrap_err();
        assert!(error.contains(ERR_RATE_LIMITED), "got: {error}");
        assert!(!error.contains(ERR_PROTOCOL), "got: {error}");
    }

    #[tokio::test]
    async fn bootstrap_5xx_is_server_unavailable() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => {
                    TestResponse::json(200, &caps_with(&[("auth.owner_configured", "false")]))
                }
                "/api/auth/server-info" => {
                    TestResponse::json(200, &caps_with(&[("auth.owner_configured", "false")]))
                }
                "/api/auth/owner/bootstrap" => TestResponse::json(503, "boom"),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let error = broker
            .bootstrap_owner(server.url(), "correct-horse", "bootstrap-secret")
            .await
            .unwrap_err();
        assert!(error.contains(ERR_SERVER_UNAVAILABLE), "got: {error}");
        assert!(!error.contains(ERR_PROTOCOL), "got: {error}");
    }

    #[tokio::test]
    async fn bootstrap_401_403_is_credential_denial() {
        for status in [401u16, 403] {
            let store = Arc::new(MemoryStore::new());
            let broker = broker_with(store.clone());
            let server = TestServer::start(move |request: &RecordedRequest| {
                match request.path.as_str() {
                    "/api/system/capabilities" => {
                        TestResponse::json(
                            200,
                            &caps_with(&[("auth.owner_configured", "false")]),
                        )
                    }
                    "/api/auth/server-info" => {
                        TestResponse::json(
                            200,
                            &caps_with(&[("auth.owner_configured", "false")]),
                        )
                    }
                    "/api/auth/owner/bootstrap" => {
                        TestResponse::json(status, r#"{"detail":"bootstrap token rejected"}"#)
                    }
                    _ => TestResponse::json(404, "{}"),
                }
            })
            .await;
            let error = broker
                .bootstrap_owner(server.url(), "correct-horse", "bootstrap-secret")
                .await
                .unwrap_err();
            assert!(error.contains(ERR_LOGIN_EXPIRED), "{status} got: {error}");
            assert!(!error.contains("bootstrap-secret"), "{status} error must not leak the token");
        }
    }

    #[tokio::test]
    async fn business_401_refresh_retry_recovers_200() {
        // Gate C/D §4.8 — business request with an old access → 401 → refresh →
        // retry → 200. Exactly one refresh and two business calls.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let refresh_calls = Arc::new(AtomicUsize::new(0));
        let counter = refresh_calls.clone();
        let business_calls = Arc::new(AtomicUsize::new(0));
        let business_counter = business_calls.clone();
        let server = TestServer::start(move |request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => {
                    counter.fetch_add(1, Ordering::SeqCst);
                    TestResponse::json(200, REFRESH_OK)
                }
                // Gate C/D §4.8 — the server rejects the OLD access credential on
                // the first call; after the refresh provides a NEW one the retry
                // succeeds. This truly exercises 401 → refresh → retry → 200.
                "/api/test/data" => {
                    let n = business_counter.fetch_add(1, Ordering::SeqCst);
                    if n == 0 {
                        TestResponse::json(401, r#"{"detail":"unauthorized"}"#)
                    } else {
                        TestResponse::json(200, r#"{"ok":true}"#)
                    }
                }
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("retry-recovers");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        // Seed a locally-valid OLD access credential so the first request 401s.
        broker.set_session("access-old", 3600).await;
        let result = broker
            .api_request(&app_data.0, "/api/test/data", "GET", None, &HashMap::new())
            .await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().status, 200);
        assert_eq!(refresh_calls.load(Ordering::SeqCst), 1, "exactly one refresh");
        assert_eq!(business_calls.load(Ordering::SeqCst), 2, "original + one retry");
    }

    #[tokio::test]
    async fn keyring_read_backend_failure_is_persistence_not_login_expired() {
        // Gate C/D §4.5 — a store READ backend failure must be classified as
        // CREDENTIAL_PERSISTENCE_FAILURE, never "please log in again".
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(compatible_handler()).await;
        let app_data = TempDir::new("read-fail");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        store.set_read_fail(true);
        let error = broker.refresh_session_token(&enrollment).await.unwrap_err();
        assert!(error.contains(ERR_CREDENTIAL_PERSISTENCE), "got: {error}");
        assert!(!error.contains(ERR_LOGIN_EXPIRED), "must not demand re-login: {error}");
    }

    // ------------------------------------------------------- P8 persistence

    #[tokio::test]
    async fn restart_with_stored_refresh_is_not_login_expired() {
        // HIGH-2: after a restart there is NO in-memory access credential, but
        // an enrolled install with a stored refresh credential is NOT
        // LoginExpired. auth_expired only becomes true after the server itself
        // denies the refresh credential.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let app_data = TempDir::new("restart-lifecycle");
        seed_enrollment(&app_data.0, "https://remote.example", "instance-A", "device-1", store.as_ref());
        let status = broker.session_status(&app_data.0).await;
        assert!(status.enrolled);
        assert!(!status.connected);
        assert!(status.refresh_token_stored);
        assert!(!status.auth_expired, "restart with stored refresh must NOT be LoginExpired");

        // Now the server denies the refresh credential → auth_expired flips true.
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(401, r#"{"detail":"refresh denied"}"#),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        // Re-seed with the real loopback origin so the refresh can be attempted.
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let result = broker.refresh_now(&app_data.0).await;
        assert!(result.is_err());
        let error = result.err().unwrap();
        assert!(error.contains("code"), "error must be coded JSON, got: {error}");
        assert!(error.contains(ERR_LOGIN_EXPIRED));
        let status = broker.session_status(&app_data.0).await;
        assert!(status.auth_expired, "server denial must surface as LoginExpired");
        assert!(!status.connected);
    }

    #[tokio::test]
    async fn refresh_rotation_survives_keyring_write_failure() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(compatible_handler()).await;
        let app_data = TempDir::new("persist-rotation");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        // Fail the store write for the rotation.
        store.set_write_fail(true);
        let result = broker.refresh_session_token(&enrollment).await;
        assert_eq!(result.unwrap(), "access-refreshed");
        // The rotated credential survives: the durable PENDING slot holds it
        // (the active write failed), so nothing is staged only in memory.
        assert_eq!(
            stored_slot_token(&store, "instance-A", "device-1", false).as_deref(),
            Some("refresh-rotated-2")
        );
        assert!(broker.state.pending_refresh.lock().await.is_none());
        // Crash recovery: a fresh broker over the same store reads the pending
        // slot as the effective credential (read prefers the higher generation).
        let restarted = broker_with(store.clone());
        assert_eq!(
            restarted.read_effective_refresh(&enrollment).await.unwrap(),
            "refresh-rotated-2"
        );
        // A second refresh reuses the still-valid access credential and must
        // keep the staged replacement (old keyring refresh is already consumed).
        let second = broker.refresh_session_token(&enrollment).await;
        assert_eq!(second.unwrap(), "access-refreshed");
        assert_eq!(
            stored_slot_token(&store, "instance-A", "device-1", false).as_deref(),
            Some("refresh-rotated-2")
        );
        // Once the store recovers, the next real refresh persists the
        // replacement, promotes it to the active slot and clears pending.
        store.set_write_fail(false);
        broker.set_session("", 0).await; // force a real refresh instead of reusing access
        let _ = broker.refresh_session_token(&enrollment).await;
        assert!(store.read_pending_refresh("instance-A", "device-1").unwrap().is_none());
        assert_eq!(
            stored_slot_token(&store, "instance-A", "device-1", true).as_deref(),
            Some("refresh-rotated-2")
        );
    }

    #[tokio::test]
    async fn stale_pending_never_shadows_promoted_active() {
        // §11 — simulate the double-failure that previously left a STALE pending
        // token that shadowed a promoted active credential: the pending write of
        // a rotated replacement fails, the active promotion succeeds, and the
        // subsequent clear also fails. Restart must still read the promoted
        // ACTIVE (highest generation), never the stale older pending value.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(compatible_handler()).await;
        let app_data = TempDir::new("stale-pending");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());

        // Seed a deliberately STALE pending value that predates the seed active
        // (e.g. a leftover from a prior crashed rotation carrying the old token).
        store
            .write_pending_refresh("instance-A", "device-1", "stale-pending-leak")
            .unwrap();

        // Rotate: pending write fails (stale stays), active promotion succeeds,
        // then the clear of pending also fails.
        store.set_pending_write_fail(true);
        store.set_clear_fail(true);
        let result = broker.refresh_session_token(&enrollment).await;
        assert!(result.is_ok(), "rotation must succeed via the active slot: {result:?}");
        store.set_pending_write_fail(false);
        store.set_clear_fail(false);

        // Active now holds the promoted replacement; the stale pending leaked.
        assert_eq!(
            stored_slot_token(&store, "instance-A", "device-1", true).as_deref(),
            Some("refresh-rotated-2")
        );
        assert_eq!(
            stored_slot_token(&store, "instance-A", "device-1", false).as_deref(),
            Some("stale-pending-leak")
        );

        // Restart (fresh process state) MUST read the promoted active, never the
        // stale pending.
        let restarted = broker_with(store.clone());
        assert_eq!(
            restarted.read_effective_refresh(&enrollment).await.unwrap(),
            "refresh-rotated-2"
        );
    }

    #[tokio::test]
    async fn rotation_stages_in_memory_when_every_slot_fails() {
        // Gate C/D §4.4 — both durable slots fail: the replacement is staged
        // in memory for this session and CREDENTIAL_PERSISTENCE_FAILURE is
        // returned (never a fake durable success). The access credential
        // stays in memory so the current session can continue.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(compatible_handler()).await;
        let app_data = TempDir::new("persist-both-fail");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        store.set_write_fail(true);
        store.set_pending_write_fail(true);
        let result = broker.refresh_session_token(&enrollment).await;
        let error = result.unwrap_err();
        assert!(error.contains(ERR_CREDENTIAL_PERSISTENCE), "got: {error}");
        // The replacement is staged in memory for this session.
        assert_eq!(
            broker.state.pending_refresh.lock().await.as_deref(),
            Some("refresh-rotated-2")
        );
        // Nothing durable was written for the replacement (the stale seed from
        // enrollment remains in the active slot, and the pending slot is
        // empty), but the in-memory replacement is the effective credential
        // for the remainder of this process.
        assert!(store.read_pending_refresh("instance-A", "device-1").unwrap().is_none());
        assert_eq!(
            store.read_refresh("instance-A", "device-1").unwrap().as_deref(),
            Some("refresh-seed")
        );
        assert_eq!(
            broker.read_effective_refresh(&enrollment).await.unwrap(),
            "refresh-rotated-2"
        );
        // The freshly rotated access credential is still usable this session.
        assert_eq!(broker.session().await.unwrap().access_token, "access-refreshed");
    }

    // ---------------------------------------------------------- P9 orphan

    #[tokio::test]
    async fn login_profile_save_failure_cleans_up_orphan_secret() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(compatible_handler()).await;
        // app_data is a FILE, so create_dir_all / save_enrollment must fail.
        let file_path = std::env::temp_dir().join(format!("ig-orphan-{}", std::process::id()));
        std::fs::write(&file_path, b"occupied").unwrap();
        let result = broker
            .login(&file_path, server.url(), "correct-horse", "device", "macos", "0.7.0")
            .await;
        let _ = std::fs::remove_file(&file_path);
        assert!(result.is_err());
        // The freshly written refresh credential must have been cleaned up.
        assert_eq!(store.read_refresh("instance-A", "device-1").unwrap(), None);
    }

    // --------------------------------------------------------- P15 headers

    #[tokio::test]
    async fn renderer_dangerous_headers_are_stripped_by_positive_allowlist() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(200, REFRESH_OK),
                "/api/test/data" => TestResponse::json(200, r#"{"ok":true}"#),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("headers");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let mut headers = HashMap::new();
        headers.insert("Authorization".into(), "Bearer renderer-token".into());
        headers.insert("Cookie".into(), "session=evil".into());
        headers.insert("X-Forwarded-For".into(), "1.2.3.4".into());
        headers.insert("Host".into(), "evil.example.com".into());
        headers.insert("X-PG-Interest-Area".into(), "math".into());
        headers.insert("Accept".into(), "application/json".into());
        let result = broker
            .api_request(&app_data.0, "/api/test/data", "GET", None, &headers)
            .await;
        assert_eq!(result.unwrap().status, 200);
        let recorded = server
            .requests()
            .into_iter()
            .find(|request| request.path == "/api/test/data")
            .expect("request must reach the endpoint");
        let lower_headers: Vec<(String, String)> = recorded
            .headers
            .iter()
            .map(|(key, value)| (key.to_ascii_lowercase(), value.clone()))
            .collect();
        assert!(
            lower_headers.iter().all(|(key, value)| key != "authorization" || value != "Bearer renderer-token"),
            "renderer Authorization must never override native Bearer"
        );
        assert!(lower_headers.iter().all(|(key, _)| key != "cookie"));
        assert!(lower_headers.iter().all(|(key, _)| key != "x-forwarded-for"));
        assert!(lower_headers.iter().all(|(key, _)| key != "host" || value_is_local(&lower_headers, key)));
        assert!(
            lower_headers.iter().any(|(key, value)| key == "x-pg-interest-area" && value == "math"),
            "positive allowlist entry must be forwarded"
        );
        assert!(
            lower_headers.iter().any(|(key, value)| key == "accept" && value == "application/json")
        );
    }

    fn value_is_local(headers: &[(String, String)], key: &str) -> bool {
        headers
            .iter()
            .any(|(name, value)| name == key && value.contains("127.0.0.1"))
    }

    // ---------------------------------------------------------- P16 response

    #[tokio::test]
    async fn response_metadata_allowlist_surfaces_safe_headers_only() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(200, REFRESH_OK),
                "/api/artifacts/1/export" => TestResponse {
                    status: 200,
                    content_type: "application/zip",
                    body: "PK\x03\x04payload".to_string(),
                    headers: vec![
                        ("Content-Disposition".into(), "attachment; filename=\"report.zip\"".into()),
                        ("ETag".into(), "\"abc\"".into()),
                        ("Set-Cookie".into(), "session=secret".into()),
                        ("X-Internal".into(), "top-secret".into()),
                    ],
                },
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("response-headers");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let result = broker
            .api_request(&app_data.0, "/api/artifacts/1/export", "GET", None, &HashMap::new())
            .await
            .unwrap();
        assert_eq!(result.status, 200);
        assert_eq!(
            result.response_headers.get("content-disposition").map(String::as_str),
            Some("attachment; filename=\"report.zip\"")
        );
        assert_eq!(result.response_headers.get("etag").map(String::as_str), Some("\"abc\""));
        assert!(result.response_headers.get("set-cookie").is_none());
        assert!(result.response_headers.get("x-internal").is_none());
    }

    // ---------------------------------------------------------- P17 upload

    #[tokio::test]
    async fn upload_is_bounded_before_and_after_base64_decode() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(200, REFRESH_OK),
                "/api/knowledge/sources" => TestResponse::json(200, r#"{"ok":true}"#),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("upload-bounds");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        // Over-limit payload (encoded length check).
        let too_big_b64 = "A".repeat((MAX_UPLOAD_BYTES * 4) / 3 + 8);
        let result = broker
            .api_upload(&app_data.0, "/api/knowledge/sources", "file", "huge.pdf", &too_big_b64, "application/pdf", &HashMap::new())
            .await;
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("upload limit"));
        // Decode-check: a payload that decodes beyond the limit is also rejected.
        let decoded = vec![0u8; MAX_UPLOAD_BYTES + 1];
        let decoded_b64 = base64::engine::general_purpose::STANDARD.encode(decoded);
        let result = broker
            .api_upload(&app_data.0, "/api/knowledge/sources", "file", "huge.pdf", &decoded_b64, "application/pdf", &HashMap::new())
            .await;
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("upload limit"));
        // A small payload is accepted and forwarded.
        let small = base64::engine::general_purpose::STANDARD.encode(b"hello");
        let result = broker
            .api_upload(&app_data.0, "/api/knowledge/sources", "file", "small.txt", &small, "text/plain", &HashMap::new())
            .await;
        assert_eq!(result.unwrap().status, 200);
    }

    // Gate R0.5 — the file-backed streaming upload path is bounded (rejects an
    // over-limit source before any multipart body is streamed) and accepts a
    // small file. Uses a sparse file so the over-limit case costs no heap.
    #[tokio::test]
    async fn api_upload_file_rejects_over_limit_and_streams_small() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(200, REFRESH_OK),
                "/api/knowledge/sources" => TestResponse::json(200, r#"{"ok":true}"#),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("upload-file");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        // Over-limit sparse file: metadata length exceeds the bound, so the
        // upload is rejected before any file bytes are streamed.
        let big = app_data.0.join("huge.bin");
        let file = std::fs::File::create(&big).unwrap();
        file.set_len(MAX_UPLOAD_BYTES as u64 + 1).unwrap();
        drop(file);
        let result = broker
            .api_upload_file(
                &app_data.0,
                "/api/knowledge/sources",
                "file",
                "huge.bin",
                &big,
                "application/octet-stream",
                &HashMap::new(),
            )
            .await;
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("upload limit"));
        // A small file is accepted and forwarded through the multipart stream.
        let small = app_data.0.join("small.txt");
        std::fs::write(&small, b"hello file").unwrap();
        let result = broker
            .api_upload_file(
                &app_data.0,
                "/api/knowledge/sources",
                "file",
                "small.txt",
                &small,
                "text/plain",
                &HashMap::new(),
            )
            .await;
        assert_eq!(result.unwrap().status, 200);
    }

    // Gate R0.6 — the streaming download path writes the HTTP body into the
    // bounded dest file with correct bytes (never a full base64 Vec).
    #[tokio::test]
    async fn download_to_file_streams_into_bounded_dest() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(200, REFRESH_OK),
                "/artifacts/9/export" => TestResponse {
                    status: 200,
                    content_type: "application/pdf",
                    body: "PDFDATA-BYTES-123".to_string(),
                    headers: vec![(
                        "content-disposition".to_string(),
                        "attachment; filename=\"report.pdf\"".to_string(),
                    )],
                },
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("download-file");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let dest = app_data.0.join("out.bin");
        let downloaded = broker
            .download_to_file(&app_data.0, "/artifacts/9/export", &dest)
            .await
            .unwrap();
        assert_eq!(downloaded.status, 200);
        assert!(downloaded.content_type.contains("application/pdf"));
        let bytes = std::fs::read(&dest).unwrap();
        assert_eq!(bytes, b"PDFDATA-BYTES-123");
    }

    #[test]
    fn runtime_gate_denies_desktop_local_and_permits_desktop_remote() {
        use crate::runtime_mode::RuntimeMode;
        let denied = ensure_remote_mode(RuntimeMode::DesktopLocal).unwrap_err();
        assert!(denied.contains(RUNTIME_MODE_DENIED_PAYLOAD));
        assert!(ensure_remote_mode(RuntimeMode::DesktopRemote).is_ok());
    }

    // ---------------------------------------------------- §9.3 method gate

    #[tokio::test]
    async fn method_allowlist_rejects_arbitrary_http_methods() {
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(compatible_handler()).await;
        let app_data = TempDir::new("method-gate");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        // Renderer-supplied method strings must never reach reqwest: CONNECT
        // and TRACE are rejected natively even though HTTP/1.1 allows them.
        for method in ["CONNECT", "TRACE", "BREW", "PRI * HTTP/2.0"] {
            let result = broker
                .api_request(&app_data.0, "/api/test/data", method, None, &HashMap::new())
                .await;
            assert!(result.is_err());
            assert!(result.unwrap_err().contains("unsupported HTTP method"));
        }
        // The frozen set stays usable: DELETE passes the allowlist and the
        // request reaches the server (404 from the handler, not a native
        // rejection).
        let ok = broker
            .api_request(&app_data.0, "/api/test/data", "DELETE", None, &HashMap::new())
            .await;
        assert!(ok.is_ok());
        assert_eq!(ok.unwrap().status, 404);
        let recorded = server.requests();
        let refresh_posts = recorded
            .iter()
            .filter(|request| request.path == "/api/auth/device/refresh")
            .collect::<Vec<_>>();
        for request in &refresh_posts {
            assert_eq!(request.method, "POST");
        }
    }

    // ----------------------------------------------------------- P20 logout

    #[tokio::test]
    async fn logout_reports_truthful_revoke_result() {
        // Server revoke fails (500) → local logout succeeds but revoked=false.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(|request: &RecordedRequest| {
            match request.path.as_str() {
                "/api/system/capabilities" => TestResponse::json(200, CAPS),
                "/api/auth/server-info" => TestResponse::json(200, INFO),
                "/api/auth/device/refresh" => TestResponse::json(200, REFRESH_OK),
                "/api/auth/device/revoke" => TestResponse::json(500, r#"{"detail":"boom"}"#),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("logout-fail");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let result = broker.logout(&app_data.0, true).await.unwrap();
        assert!(result.logged_out);
        assert!(!result.revoked, "failed network revoke must not claim success");
        assert_eq!(store.read_refresh("instance-A", "device-1").unwrap(), None);
        assert!(!app_data.0.join(ENROLLMENT_FILE).exists());

        // Server revoke succeeds (204) → revoked=true.
        let store = Arc::new(MemoryStore::new());
        let broker = broker_with(store.clone());
        let server = TestServer::start(compatible_handler()).await;
        let app_data = TempDir::new("logout-ok");
        seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let result = broker.logout(&app_data.0, true).await.unwrap();
        assert!(result.logged_out);
        assert!(result.revoked);
    }
}
