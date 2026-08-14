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
const AUTH_MODE_SINGLE_OWNER_DEVICES: &str = "single_owner_devices";

// Gate D §P17 — upload bound matches the server product limit (100 MiB).
const MAX_UPLOAD_BYTES: usize = 100 * 1024 * 1024;

// Gate D §P6 — a probed enrollment must be fresh before login/bootstrap.
const PROBE_FRESHNESS_SECS: i64 = 300;

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
#[derive(Clone, Debug, Default)]
pub struct RemoteSession {
    pub access_token: String,
    pub expires_at_unix: i64,
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

#[derive(Clone, Debug)]
pub struct PendingEnrollment {
    pub origin: String,
    pub server: RemoteServerInfo,
    pub probed_at: i64,
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
pub trait CredentialStore: Send + Sync {
    fn read_refresh(&self, server_instance_id: &str, device_id: &str) -> Option<String>;
    fn write_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
        token: &str,
    ) -> Result<(), String>;
    fn delete_refresh(&self, server_instance_id: &str, device_id: &str) -> Result<(), String>;
}

/// OS keyring backed store. One refresh credential per server per device.
pub struct KeyringStore;

impl CredentialStore for KeyringStore {
    fn read_refresh(&self, server_instance_id: &str, device_id: &str) -> Option<String> {
        let username = remote_refresh_username(server_instance_id, device_id);
        Entry::new(KEYRING_SERVICE, &username)
            .ok()?
            .get_password()
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
    }

    fn write_refresh(
        &self,
        server_instance_id: &str,
        device_id: &str,
        token: &str,
    ) -> Result<(), String> {
        let username = remote_refresh_username(server_instance_id, device_id);
        Entry::new(KEYRING_SERVICE, &username)
            .map_err(|error| error.to_string())?
            .set_password(token)
            .map_err(|error| error.to_string())
    }

    fn delete_refresh(&self, server_instance_id: &str, device_id: &str) -> Result<(), String> {
        let username = remote_refresh_username(server_instance_id, device_id);
        let entry = Entry::new(KEYRING_SERVICE, &username).map_err(|error| error.to_string())?;
        if entry.get_password().is_ok() {
            entry.delete_credential().map_err(|error| error.to_string())?;
        }
        Ok(())
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
    /// Short-lived native-verified probe used to gate login/bootstrap (P6).
    pub pending_enrollment: tokio::sync::Mutex<Option<PendingEnrollment>>,
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
            pending_enrollment: tokio::sync::Mutex::new(None),
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

fn parse_version_parts(value: &str) -> Vec<u32> {
    value
        .split(|character: char| !character.is_ascii_digit())
        .filter(|part| !part.is_empty())
        .map(|part| part.parse::<u32>().unwrap_or(0))
        .collect()
}

/// Numeric semver-lite comparison (0.7.0 < 0.10.0, 1.2 < 1.2.0).
fn compare_versions(left: &str, right: &str) -> std::cmp::Ordering {
    let left_parts = parse_version_parts(left);
    let right_parts = parse_version_parts(right);
    let length = left_parts.len().max(right_parts.len());
    for index in 0..length {
        let left_part = left_parts.get(index).copied().unwrap_or(0);
        let right_part = right_parts.get(index).copied().unwrap_or(0);
        let ordering = left_part.cmp(&right_part);
        if ordering != std::cmp::Ordering::Equal {
            return ordering;
        }
    }
    std::cmp::Ordering::Equal
}

// Gate C §7 — enrollment origin normalization. Origin-only HTTPS; loopback
// HTTP only for explicit development/test. No userinfo, query, fragment or
// path. The client URL security problem (LAN/VPN self-hosting) is different
// from server-side SSRF rules, so private IPs are allowed.
pub fn normalize_enrollment_origin(value: &str) -> Result<String, String> {
    let trimmed = value.trim();
    let parsed = url::Url::parse(trimmed).map_err(|error| format!("invalid server URL: {error}"))?;
    if parsed.host_str().is_none() {
        return Err("server URL must include a host".into());
    }
    if !parsed.username().is_empty() || parsed.password().is_some() {
        return Err("server URL must not contain embedded credentials".into());
    }
    let host = parsed.host_str().unwrap_or_default().to_ascii_lowercase();
    let loopback = host == "localhost" || host == "127.0.0.1" || host == "::1";
    let valid_scheme = parsed.scheme() == "https" || (parsed.scheme() == "http" && loopback);
    if !valid_scheme {
        return Err("server URL must use HTTPS, or loopback HTTP for development".into());
    }
    if parsed.query().is_some() || parsed.fragment().is_some() {
        return Err("server URL must not contain a query or fragment".into());
    }
    if parsed.path() != "/" && !parsed.path().is_empty() {
        return Err("server URL must be an origin without a path".into());
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
        return Err("remote transport only accepts relative API paths".into());
    }
    if path.starts_with("//") {
        return Err("remote transport rejects protocol-relative URLs".into());
    }
    if path.starts_with("/\\") {
        return Err("remote transport rejects backslash URLs".into());
    }
    let lower = path.to_ascii_lowercase();
    if lower.starts_with("http://") || lower.starts_with("https://") {
        return Err("remote transport rejects absolute URLs".into());
    }
    Ok(())
}

/// Shared HTTP client for all remote credential-bearing requests.
///
/// Gate C §12 / Gate D §P1: redirects are explicitly disabled (fail-closed).
/// A credential-bearing POST must never be transparently forwarded to a
/// redirect target — a 307/308 preserves method and body, and a 301/302/303
/// could still expose the custom bootstrap header. Any 3xx is surfaced as an
/// explicit error instead of being followed.
fn http_client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(REQUEST_TIMEOUT)
        .connect_timeout(CONNECT_TIMEOUT)
        .user_agent(format!("interest-growth-desktop/{CLIENT_APP_VERSION}"))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|error| error.to_string())
}

impl RemoteBroker {
    pub fn new(store: Arc<dyn CredentialStore>) -> Result<Self, String> {
        Ok(Self {
            client: http_client()?,
            store,
            state: Arc::new(RemoteBrokerState::new()),
        })
    }

    // -------------------------------------------------- session primitives

    async fn session(&self) -> Option<RemoteSession> {
        self.state.session.lock().await.clone()
    }

    fn set_session(&self, access_token: &str, expires_in: u64) -> Result<(), String> {
        *self.state.session.try_lock().map_err(|_| "remote session state poisoned")? =
            Some(RemoteSession {
                access_token: access_token.to_string(),
                expires_at_unix: now_unix() + expires_in as i64,
            });
        Ok(())
    }

    async fn clear_session(&self) {
        *self.state.session.lock().await = None;
    }

    // ----------------------------------------------- probe + compatibility

    async fn fetch_json(&self, url: &str) -> Result<serde_json::Value, String> {
        let response = self
            .client
            .get(url)
            .send()
            .await
            .map_err(|error| format!("cannot reach server: {error}"))?;
        let status = response.status().as_u16();
        if status != 200 {
            return Err(format!("server metadata endpoint returned HTTP {status}"));
        }
        response
            .json()
            .await
            .map_err(|error| format!("invalid server metadata response: {error}"))
    }

    fn parse_metadata(payload: &serde_json::Value) -> ParsedMetadata {
        let get_str = |keys: &[&str]| {
            keys.iter()
                .find_map(|key| payload.get(*key).and_then(|value| value.as_str()))
                .unwrap_or_default()
                .to_string()
        };
        let auth = |key: &str| {
            payload
                .get("auth")
                .and_then(|auth| auth.get(key))
                .and_then(|value| value.as_str())
        };
        ParsedMetadata {
            product: get_str(&["product"]),
            server_version: get_str(&["server_version"]),
            api_version: get_str(&["api_version"]),
            min_client_version: get_str(&["min_client_version"]),
            server_instance_id: get_str(&["server_instance_id"]),
            server_display_name: get_str(&["server_display_name"]),
            auth_mode: auth("mode").unwrap_or_default().to_string(),
            auth_enabled: payload
                .get("auth")
                .and_then(|auth| auth.get("enabled"))
                .and_then(|value| value.as_bool())
                .unwrap_or(false),
            owner_configured: payload
                .get("auth")
                .and_then(|auth| auth.get("owner_configured"))
                .and_then(|value| value.as_bool())
                .unwrap_or(false),
            online_first: payload
                .get("online_first")
                .and_then(|value| value.as_bool())
                .unwrap_or(true),
            offline_sync: payload
                .get("offline_sync")
                .and_then(|value| value.as_bool())
                .unwrap_or(false),
            runtime_modes: payload
                .get("runtime_modes")
                .and_then(|value| value.as_array())
                .map(|modes| {
                    modes
                        .iter()
                        .filter_map(|mode| mode.as_str())
                        .map(|mode| mode.to_string())
                        .collect()
                })
                .unwrap_or_default(),
            tls: payload
                .get("tls")
                .and_then(|value| value.as_bool())
                .unwrap_or(false),
        }
    }

    /// Gate D §P3 — unified server probe. Reads BOTH the frozen capability
    /// contract endpoint and the auth server-info endpoint, then refuses to
    /// connect when the shared public metadata is inconsistent.
    pub async fn probe(&self, origin: &str) -> Result<RemoteProbeResult, String> {
        let capabilities = self
            .fetch_json(&format!("{origin}/api/system/capabilities"))
            .await?;
        let server_info = self
            .fetch_json(&format!("{origin}/api/auth/server-info"))
            .await?;
        let from_capabilities = Self::parse_metadata(&capabilities);
        let from_server_info = Self::parse_metadata(&server_info);

        let shared: [(&str, &str, &str); 6] = [
            ("product", &from_capabilities.product, &from_server_info.product),
            (
                "server_version",
                &from_capabilities.server_version,
                &from_server_info.server_version,
            ),
            ("api_version", &from_capabilities.api_version, &from_server_info.api_version),
            (
                "min_client_version",
                &from_capabilities.min_client_version,
                &from_server_info.min_client_version,
            ),
            (
                "server_instance_id",
                &from_capabilities.server_instance_id,
                &from_server_info.server_instance_id,
            ),
            (
                "server_display_name",
                &from_capabilities.server_display_name,
                &from_server_info.server_display_name,
            ),
        ];
        for (name, left, right) in shared {
            if left != right {
                return Err(format!(
                    "server capability metadata inconsistent ({name}); refusing to connect"
                ));
            }
        }
        if from_capabilities.auth_enabled != from_server_info.auth_enabled
            || from_capabilities.auth_mode != from_server_info.auth_mode
            || from_capabilities.online_first != from_server_info.online_first
            || from_capabilities.offline_sync != from_server_info.offline_sync
        {
            return Err(
                "server capability metadata inconsistent (auth/transport); refusing to connect"
                    .into(),
            );
        }

        Ok(RemoteProbeResult {
            normalized_origin: origin.to_string(),
            server: Self::build_server(&from_capabilities, &from_server_info),
        })
    }

    /// Gate D §P3 — assemble the unified `RemoteServerInfo` from the two
    /// metadata endpoints (capabilities authoritative for runtime facts, the
    /// auth endpoint for transport facts).
    fn build_server(
        from_capabilities: &ParsedMetadata,
        from_server_info: &ParsedMetadata,
    ) -> RemoteServerInfo {
        RemoteServerInfo {
            product: from_capabilities.product.clone(),
            server_version: from_capabilities.server_version.clone(),
            api_version: from_capabilities.api_version.clone(),
            min_client_version: from_capabilities.min_client_version.clone(),
            server_instance_id: from_capabilities.server_instance_id.clone(),
            server_display_name: from_capabilities.server_display_name.clone(),
            runtime_modes: from_capabilities.runtime_modes.clone(),
            auth_mode: from_capabilities.auth_mode.clone(),
            auth_enabled: from_capabilities.auth_enabled,
            owner_configured: from_capabilities.owner_configured,
            tls: from_server_info.tls,
            online_first: from_capabilities.online_first,
            offline_sync: from_capabilities.offline_sync,
        }
    }

    /// Gate D §P3/P4 — one-shot fail-closed probe for the desktop-remote
    /// runtime. Cross-validates the two metadata endpoints and then applies the
    /// native compatibility gate so an incompatible server can never produce a
    /// pending enrollment or receive a credential.
    pub async fn probe_desktop_remote(&self, origin: &str) -> Result<RemoteProbeResult, String> {
        let result = self.probe(origin).await?;
        self.check_compatibility(&result.server, RUNTIME_DESKTOP_REMOTE)?;
        Ok(result)
    }

    /// Gate D §P4 — native compatibility gate, fail-closed. Returns an error
    /// before any credential is sent when the server violates the frozen
    /// contract for the requested runtime.
    pub fn check_compatibility(
        &self,
        server: &RemoteServerInfo,
        runtime_id: &str,
    ) -> Result<(), String> {
        if server.product != API_PRODUCT {
            return Err(format!("unsupported product: {}", server.product));
        }
        if server.api_version != SUPPORTED_API_VERSION {
            return Err(format!("unsupported API version: {}", server.api_version));
        }
        if !server.min_client_version.is_empty()
            && compare_versions(CLIENT_APP_VERSION, &server.min_client_version)
                == std::cmp::Ordering::Less
        {
            return Err(format!(
                "client version {CLIENT_APP_VERSION} is below the server minimum {}",
                server.min_client_version
            ));
        }
        if !server.runtime_modes.iter().any(|mode| mode == runtime_id) {
            return Err(format!("server does not support runtime {runtime_id}"));
        }
        if runtime_id == RUNTIME_DESKTOP_REMOTE {
            if !server.auth_enabled {
                return Err("remote device authentication is disabled on this server".into());
            }
            if server.auth_mode != AUTH_MODE_SINGLE_OWNER_DEVICES {
                return Err(format!(
                    "unsupported authentication mode: {}",
                    server.auth_mode
                ));
            }
            if !server.online_first {
                return Err("server is not online-first".into());
            }
            if server.offline_sync {
                return Err("server enables offline sync which this client does not support".into());
            }
        }
        Ok(())
    }

    /// Resolve a fresh, native-verified server for the given origin. Prefers a
    /// recent pending enrollment (from the probe the renderer just ran) and
    /// otherwise performs a fail-closed internal probe (P6).
    async fn verified_server_for_login(&self, origin: &str) -> Result<RemoteServerInfo, String> {
        if let Some(pending) = self.state.pending_enrollment.lock().await.as_ref() {
            if pending.origin == origin && now_unix() - pending.probed_at < PROBE_FRESHNESS_SECS {
                self.check_compatibility(&pending.server, RUNTIME_DESKTOP_REMOTE)?;
                return Ok(pending.server.clone());
            }
        }
        let result = self.probe(origin).await?;
        self.check_compatibility(&result.server, RUNTIME_DESKTOP_REMOTE)?;
        *self.state.pending_enrollment.lock().await = Some(PendingEnrollment {
            origin: origin.to_string(),
            server: result.server.clone(),
            probed_at: now_unix(),
        });
        Ok(result.server)
    }

    /// Gate D §P5 — stored credentials are only used after an automatic
    /// identity preflight. A replaced server behind the same URL blocks before
    /// the refresh credential is read or sent.
    async fn identity_preflight(&self, enrollment: &RemoteEnrollment) -> Result<(), String> {
        let probe = self.probe(&enrollment.normalized_origin).await?;
        self.check_compatibility(&probe.server, RUNTIME_DESKTOP_REMOTE)?;
        if probe.server.server_instance_id != enrollment.server_instance_id {
            return Err(
                "server identity changed; re-verify the server before using stored credentials"
                    .into(),
            );
        }
        Ok(())
    }

    // ------------------------------------------------------------ refresh

    /// Effective refresh credential: the in-memory replacement (keyring write
    /// failed after rotation) takes priority, then the store.
    async fn read_effective_refresh(&self, enrollment: &RemoteEnrollment) -> Result<String, String> {
        if let Some(pending) = self.state.pending_refresh.lock().await.as_ref() {
            if !pending.is_empty() {
                return Ok(pending.clone());
            }
        }
        self.store
            .read_refresh(&enrollment.server_instance_id, &enrollment.device_id)
            .ok_or_else(|| "no remote refresh credential stored; please log in again".to_string())
    }

    /// Gate D §P8 — persist a rotated refresh credential. The server has
    /// already consumed the old one, so a keyring write failure must not map to
    /// "password invalid": the replacement is staged in memory for this session
    /// and retried on the next refresh instead of being lost.
    async fn rotate_refresh(&self, enrollment: &RemoteEnrollment, next: &str) {
        match self
            .store
            .write_refresh(&enrollment.server_instance_id, &enrollment.device_id, next)
        {
            Ok(()) => {
                *self.state.pending_refresh.lock().await = None;
            }
            Err(_) => {
                *self.state.pending_refresh.lock().await = Some(next.to_string());
            }
        }
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
            .map_err(|error| format!("refresh request failed: {error}"))?;
        let status = response.status().as_u16();
        let payload: serde_json::Value = response
            .json()
            .await
            .map_err(|error| format!("invalid refresh response: {error}"))?;
        if status != 200 {
            // A 401 here means the refresh credential itself is invalid/rotated.
            // Do not loop: surface LoginExpired to the renderer.
            let detail = payload
                .get("detail")
                .and_then(|value| value.as_str())
                .unwrap_or("refresh failed");
            return Err(format!("refresh denied: {detail}"));
        }
        let tokens = payload
            .get("tokens")
            .ok_or_else(|| "refresh response missing tokens".to_string())?;
        let access = tokens
            .get("access_token")
            .and_then(|value| value.as_str())
            .ok_or_else(|| "refresh response missing access_token".to_string())?
            .to_string();
        let expires_in = tokens
            .get("expires_in")
            .and_then(|value| value.as_u64())
            .unwrap_or(300);
        if let Some(next_refresh) = tokens.get("refresh_token").and_then(|value| value.as_str()) {
            self.rotate_refresh(enrollment, next_refresh).await;
        }
        self.set_session(&access, expires_in)?;
        Ok(access)
    }

    /// Return the in-memory access credential, refreshing first if it is
    /// missing or expired (with a grace period so short bursts never cascade
    /// refreshes).
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

    async fn send_once(
        &self,
        enrollment: &RemoteEnrollment,
        method: &str,
        path: &str,
        extra_headers: &HashMap<String, String>,
        body: Option<(String, Vec<u8>)>,
    ) -> Result<(u16, Vec<u8>, String, HashMap<String, String>), String> {
        let access = self.get_session_token(enrollment).await?;
        let url = format!("{}{}", enrollment.normalized_origin, path);
        let parsed_method = reqwest::Method::from_bytes(method.as_bytes())
            .map_err(|error| format!("unsupported HTTP method {method}: {error}"))?;
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
            .map_err(|error| format!("remote request failed: {error}"))?;
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
            .map_err(|error| format!("failed reading remote response: {error}"))?
            .to_vec();
        Ok((status, bytes, content_type, response_headers))
    }

    /// Gate C §10.3 / Gate D §P13 — a clear 401 means the request never entered
    /// the business path, so refresh once and retry the original request
    /// exactly once. A second 401 is LoginExpired (no infinite loop). Never
    /// retried on ambiguous transport failures; mutations are never auto-retried
    /// beyond this single auth recovery.
    async fn send_with_auth(
        &self,
        enrollment: &RemoteEnrollment,
        method: &str,
        path: &str,
        extra_headers: &HashMap<String, String>,
        body: Option<(String, Vec<u8>)>,
    ) -> Result<(u16, Vec<u8>, String, HashMap<String, String>), String> {
        let first = self
            .send_once(enrollment, method, path, extra_headers, body.clone())
            .await?;
        if first.0 == 401 {
            self.refresh_session_token(enrollment).await?;
            let second = self
                .send_once(enrollment, method, path, extra_headers, body)
                .await?;
            if second.0 == 401 {
                return Err("auth session expired; please log in again".into());
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
    ) -> Result<(u16, Vec<u8>, String, HashMap<String, String>), String> {
        let access = self.get_session_token(enrollment).await?;
        let url = format!("{}{}", enrollment.normalized_origin, path);
        let mut form = reqwest::multipart::Form::new();
        for (key, value) in fields {
            form = form.text(key.clone(), value.clone());
        }
        let part = reqwest::multipart::Part::bytes(file_bytes.to_vec())
            .file_name(file_name.to_string())
            .mime_str(file_content_type)
            .map_err(|error| error.to_string())?;
        form = form.part(file_field.to_string(), part);
        let response = self
            .client
            .post(&url)
            .bearer_auth(&access)
            .multipart(form)
            .send()
            .await
            .map_err(|error| format!("remote upload failed: {error}"))?;
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
            .map_err(|error| error.to_string())?
            .to_vec();
        Ok((status, bytes, content_type, response_headers))
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
    ) -> Result<(u16, Vec<u8>, String, HashMap<String, String>), String> {
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
        if first.0 == 401 {
            self.refresh_session_token(enrollment).await?;
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
            if second.0 == 401 {
                return Err("auth session expired; please log in again".into());
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
        // Native-verified probe (fresh pending enrollment or internal) gates the
        // login; the renderer cannot choose to skip identity verification (P6).
        let server = self.verified_server_for_login(&normalized).await?;
        if !server.auth_enabled {
            return Err("remote device authentication is disabled on this server".into());
        }
        if !server.owner_configured {
            return Err("this server has no owner; create the owner password first".into());
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
            .map_err(|error| format!("login request failed: {error}"))?;
        let status = response.status().as_u16();
        let body: serde_json::Value = response
            .json()
            .await
            .map_err(|error| format!("invalid login response: {error}"))?;
        if status != 201 {
            let detail = body
                .get("detail")
                .and_then(|value| value.as_str())
                .unwrap_or("login failed");
            return Err(format!("login failed: {detail}"));
        }
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
            return Err(
                "server identity changed during login; re-verify the server before enrolling"
                    .into(),
            );
        }
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
            return Err("login response missing device or token fields".into());
        }

        let enrollment = RemoteEnrollment {
            normalized_origin: normalized,
            server_instance_id: server_instance_id.clone(),
            server_display_name: server_block
                .get("server_display_name")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .to_string(),
            product: server_block
                .get("product")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .to_string(),
            api_version: server_block
                .get("api_version")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .to_string(),
            server_version: server_block
                .get("server_version")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .to_string(),
            min_client_version: server_block
                .get("min_client_version")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .to_string(),
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
            .write_refresh(&enrollment.server_instance_id, &enrollment.device_id, &refresh_token)?;
        // Gate D §P9 — if the enrollment profile cannot be persisted, clean up
        // the freshly written refresh secret so we never leave an orphan that a
        // future session cannot bound to an enrollment.
        if let Err(save_error) = save_enrollment(app_data, &enrollment) {
            let _ = self
                .store
                .delete_refresh(&enrollment.server_instance_id, &enrollment.device_id);
            return Err(save_error);
        }
        self.set_session(&access_token, expires_in)?;

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
    /// The bootstrap secret header is only sent to a verified, compatible
    /// server (P2/P4/P6).
    pub async fn bootstrap_owner(
        &self,
        origin: &str,
        owner_password: &str,
        bootstrap_token: &str,
    ) -> Result<serde_json::Value, String> {
        let normalized = normalize_enrollment_origin(origin)?;
        let server = self.verified_server_for_login(&normalized).await?;
        if !server.auth_enabled {
            return Err("remote device authentication is disabled on this server".into());
        }
        if server.owner_configured {
            return Err("owner is already configured on this server".into());
        }
        let response = self
            .client
            .post(format!("{normalized}/api/auth/owner/bootstrap"))
            .header("X-PG-Owner-Bootstrap-Token", bootstrap_token)
            .json(&serde_json::json!({ "owner_password": owner_password }))
            .send()
            .await
            .map_err(|error| format!("bootstrap request failed: {error}"))?;
        let status = response.status().as_u16();
        let payload: serde_json::Value = response
            .json()
            .await
            .unwrap_or(serde_json::json!({ "detail": "bootstrap failed" }));
        if status != 201 {
            let detail = payload
                .get("detail")
                .and_then(|value| value.as_str())
                .unwrap_or("bootstrap failed");
            return Err(format!("bootstrap failed: {detail}"));
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
        let enrollment = load_enrollment(app_data).ok_or_else(|| "not enrolled to a server".to_string())?;
        assert_relative_path(path)?;
        let method = method.to_uppercase();
        let (status, bytes, content_type, response_headers) =
            self.send_with_auth(&enrollment, &method, path, headers, body).await?;
        Ok(RemoteApiResponse {
            status,
            body_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
            content_type,
            response_headers,
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
        let enrollment = load_enrollment(app_data).ok_or_else(|| "not enrolled to a server".to_string())?;
        assert_relative_path(path)?;
        let limit_mib = MAX_UPLOAD_BYTES / (1024 * 1024);
        if file_bytes_b64.len() > (MAX_UPLOAD_BYTES * 4) / 3 + 4 {
            return Err(format!("file exceeds the {limit_mib} MiB upload limit"));
        }
        let file_bytes = base64::engine::general_purpose::STANDARD
            .decode(file_bytes_b64)
            .map_err(|error| format!("invalid file payload: {error}"))?;
        if file_bytes.len() > MAX_UPLOAD_BYTES {
            return Err(format!("file exceeds the {limit_mib} MiB upload limit"));
        }
        let (status, bytes, content_type, response_headers) = self
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
            status,
            body_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
            content_type,
            response_headers,
        })
    }

    pub async fn refresh_now(&self, app_data: &Path) -> Result<RemoteSessionStatus, String> {
        let enrollment = load_enrollment(app_data).ok_or_else(|| "not enrolled".to_string())?;
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
        RemoteSessionStatus {
            enrolled: true,
            connected,
            auth_expired: !connected && refresh_stored,
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
        let enrollment = load_enrollment(app_data).ok_or_else(|| "not enrolled".to_string())?;
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
            if let Ok((status, _, _, _)) = self
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
                revoked = status >= 200 && status < 300;
            }
        }
        let _ = self
            .store
            .delete_refresh(&enrollment.server_instance_id, &enrollment.device_id);
        *self.state.pending_refresh.lock().await = None;
        self.clear_session().await;
        clear_enrollment(app_data);
        Ok(RemoteLogoutResult {
            logged_out: true,
            revoked,
        })
    }
}

/// Parsed public metadata shared by both probe endpoints.
struct ParsedMetadata {
    product: String,
    server_version: String,
    api_version: String,
    min_client_version: String,
    server_instance_id: String,
    server_display_name: String,
    auth_mode: String,
    auth_enabled: bool,
    owner_configured: bool,
    online_first: bool,
    offline_sync: bool,
    runtime_modes: Vec<String>,
    tls: bool,
}

// ------------------------------------------------------------- commands

/// Probe a candidate self-hosted server. Returns normalized origin + verified
/// server metadata so the renderer can present the compatibility result. The
/// probe is stored as a short-lived pending enrollment that gates login and
/// bootstrap (P6).
#[tauri::command]
pub async fn remote_probe_server(app: AppHandle, origin: String) -> Result<RemoteProbeResult, String> {
    let normalized = normalize_enrollment_origin(&origin)?;
    let broker = app.state::<DesktopState>().broker.clone();
    // Fail-closed: an incompatible server never becomes a pending enrollment.
    let result = broker.probe_desktop_remote(&normalized).await?;
    *broker.state.pending_enrollment.lock().await = Some(PendingEnrollment {
        origin: normalized,
        server: result.server.clone(),
        probed_at: now_unix(),
    });
    Ok(result)
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

/// Explicitly refresh the session (used by the connection-status UX).
#[tauri::command]
pub async fn remote_refresh_now(app: AppHandle) -> Result<RemoteSessionStatus, String> {
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    broker.refresh_now(&app_data).await
}

#[tauri::command]
pub async fn remote_session_status(app: AppHandle) -> RemoteSessionStatus {
    let app_data = app.path().app_data_dir().unwrap_or_default();
    let broker = app.state::<DesktopState>().broker.clone();
    broker.session_status(&app_data).await
}

/// Re-probe the enrolled server and compare its instance identity. A mismatch
/// means the server behind the same URL was replaced (Gate C §6.5): the
/// renderer must surface IdentityChanged and require explicit re-enrollment.
#[tauri::command]
pub async fn remote_verify_identity(app: AppHandle) -> Result<serde_json::Value, String> {
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    broker.verify_identity(&app_data).await
}

/// Log out. `revoke` asks the server to revoke this device; local keyring and
/// enrollment are always cleared regardless of network outcome.
#[tauri::command]
pub async fn remote_logout(app: AppHandle, revoke: bool) -> Result<RemoteLogoutResult, String> {
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let broker = app.state::<DesktopState>().broker.clone();
    broker.logout(&app_data, revoke).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::sync::Mutex as StdMutex;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::{TcpListener, TcpStream};

    // --------------------------------------------------------- test fakes

    #[derive(Clone, Default)]
    struct MemoryStore {
        values: Arc<StdMutex<HashMap<String, String>>>,
        write_fail: Arc<AtomicBool>,
    }

    impl MemoryStore {
        fn new() -> Self {
            Self::default()
        }
        fn set_write_fail(&self, fail: bool) {
            self.write_fail.store(fail, Ordering::SeqCst);
        }
    }

    impl CredentialStore for MemoryStore {
        fn read_refresh(&self, server_instance_id: &str, device_id: &str) -> Option<String> {
            self.values
                .lock()
                .unwrap()
                .get(&remote_refresh_username(server_instance_id, device_id))
                .cloned()
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
        fn delete_refresh(&self, server_instance_id: &str, device_id: &str) -> Result<(), String> {
            self.values
                .lock()
                .unwrap()
                .remove(&remote_refresh_username(server_instance_id, device_id));
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
            "offline_sync": false
        });
        for (key, val) in overrides {
            if *key == "auth.enabled" {
                value["auth"]["enabled"] = serde_json::json!(*val == "true");
            } else if *key == "auth.mode" {
                value["auth"]["mode"] = serde_json::json!(val);
            } else {
                value[*key] = serde_json::json!(val);
            }
        }
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
        assert_eq!(compare_versions("0.7.0", "0.7.0"), std::cmp::Ordering::Equal);
        assert_eq!(compare_versions("0.7.0", "0.10.0"), std::cmp::Ordering::Less);
        assert_eq!(compare_versions("0.10.0", "0.7.0"), std::cmp::Ordering::Greater);
        assert_eq!(compare_versions("1.2", "1.2.0"), std::cmp::Ordering::Equal);
        assert_eq!(compare_versions("0.6.0", "0.7.0"), std::cmp::Ordering::Less);
    }

    fn broker_with(store: Arc<dyn CredentialStore>) -> RemoteBroker {
        RemoteBroker::new(store).unwrap()
    }

    // ---------------------------------------------------- P1 redirect tests

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
                    TestResponse::json(200, &caps_with(&[("auth.owner_configured", "false")]).replace("\"runtime_modes\": [\"desktop-local\", \"desktop-remote\", \"android-remote\", \"browser-remote\"],", ""))
                }
                "/api/auth/owner/bootstrap" => TestResponse::redirect(302, "/api/auth/owner/bootstrap/evil"),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let result = broker
            .bootstrap_owner(server.url(), "correct-horse", "bootstrap-secret")
            .await;
        assert!(result.is_err());
        let paths = server.paths();
        assert!(!paths.iter().any(|path| path.contains("evil")));
        for request in server.requests() {
            if request.path == "/api/auth/owner/bootstrap" {
                assert!(
                    !request
                        .headers
                        .iter()
                        .any(|(key, value)| key == "x-pg-owner-bootstrap-token"
                            && value == "bootstrap-secret"),
                    "bootstrap secret must not reach a redirect target"
                );
            }
        }
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
            "online_first":true,"offline_sync":false}"#;
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
                // the auth-recovery path; refresh must still happen exactly once.
                "/api/test/data" => TestResponse::json(401, r#"{"detail":"unauthorized"}"#),
                _ => TestResponse::json(404, "{}"),
            }
        })
        .await;
        let app_data = TempDir::new("single-flight");
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let headers = HashMap::new();
        let mut tasks = Vec::new();
        for _ in 0..20 {
            let broker = broker.clone();
            let app_data = app_data.0.clone();
            let enrollment = enrollment.clone();
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
        // Every caller must converge: refresh happened once, and the second 401
        // after refresh surfaces as LoginExpired (no infinite loop).
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
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
        let refresh_count = Arc::new(AtomicUsize::new(0));
        // The refresh handler is not count-gated here; instead we assert the
        // outcome: the request surfaced LoginExpired after a single refresh.
        let result = broker
            .api_request(&app_data.0, "/api/test/data", "GET", None, &HashMap::new())
            .await;
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("session expired"));
        // refresh must be called at most once per request (no retry loop).
        let refresh_count = server
            .requests()
            .iter()
            .filter(|request| request.path == "/api/auth/device/refresh")
            .count();
        assert_eq!(refresh_count, 1);
    }

    // ------------------------------------------------------- P8 persistence

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
        // The rotated credential is staged in memory, not lost.
        assert_eq!(
            broker.state.pending_refresh.lock().await.as_deref(),
            Some("refresh-rotated-2")
        );
        // A second refresh reuses the still-valid access credential and must
        // keep the staged replacement (old keyring refresh is already consumed).
        let second = broker.refresh_session_token(&enrollment).await;
        assert_eq!(second.unwrap(), "access-refreshed");
        assert_eq!(
            broker.state.pending_refresh.lock().await.as_deref(),
            Some("refresh-rotated-2")
        );
        // Once the store recovers, the next real refresh persists the
        // replacement and clears the pending slot.
        store.set_write_fail(false);
        broker.set_session("", 0); // force a real refresh instead of reusing access
        let _ = broker.refresh_session_token(&enrollment).await;
        assert!(broker.state.pending_refresh.lock().await.is_none());
        assert_eq!(
            store.read_refresh("instance-A", "device-1").as_deref(),
            Some("refresh-rotated-2")
        );
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
        assert_eq!(store.read_refresh("instance-A", "device-1"), None);
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
        let enrollment = seed_enrollment(&app_data.0, server.url(), "instance-A", "device-1", store.as_ref());
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
        assert_eq!(store.read_refresh("instance-A", "device-1"), None);
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
