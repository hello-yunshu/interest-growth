// Gate D §D3/D4 — native remote credential broker + HTTP transport.
//
// The refresh credential never leaves this process: it is stored in the OS
// keyring (keyed server_instance_id:device_id) and only ever read here. The
// renderer submits RELATIVE API paths only; the base origin comes from the
// verified enrollment profile, never from arbitrary renderer input. On a
// clear 401 the broker refreshes once and retries the original request once,
// guarding against refresh loops and duplicate mutations.
//
// Security properties (Gate C §7/§10/§11/§12):
// - No `get_refresh_token() → JS` readback. The renderer never receives the
//   refresh credential and does not even receive the access token: all HTTP
//   is performed here with the Bearer header attached natively.
// - Enrollment origin is normalized and HTTPS (loopback HTTP only for
//   development/test). No username/password, query, fragment or path.
// - The access credential lives in memory only (`DesktopState.remote`), never
//   persisted, and never placed in a URL query.
// - Identity binding: login must return the same server_instance_id that was
//   probed; any mismatch is rejected instead of silently switching servers.

use std::{
    collections::HashMap,
    path::{Path, PathBuf},
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

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteServerInfo {
    pub product: String,
    pub server_version: String,
    pub api_version: String,
    pub min_client_version: String,
    pub server_instance_id: String,
    pub server_display_name: String,
    pub auth_mode: String,
    pub auth_enabled: bool,
    pub owner_configured: bool,
    pub tls: bool,
    pub online_first: bool,
    pub offline_sync: bool,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteProbeResult {
    pub normalized_origin: String,
    pub server: RemoteServerInfo,
}

#[derive(Clone, Serialize)]
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

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteApiResponse {
    pub status: u16,
    pub body_base64: String,
    pub content_type: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteLogoutResult {
    pub logged_out: bool,
    pub revoked: bool,
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

fn refresh_entry(enrollment: &RemoteEnrollment) -> Result<Entry, String> {
    Entry::new(
        KEYRING_SERVICE,
        &remote_refresh_username(&enrollment.server_instance_id, &enrollment.device_id),
    )
    .map_err(|error| error.to_string())
}

fn read_refresh_token(enrollment: &RemoteEnrollment) -> Option<String> {
    let entry = refresh_entry(enrollment).ok()?;
    entry
        .get_password()
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn write_refresh_token(enrollment: &RemoteEnrollment, token: &str) -> Result<(), String> {
    refresh_entry(enrollment)?.set_password(token).map_err(|error| error.to_string())
}

fn delete_refresh_token(enrollment: &RemoteEnrollment) -> Result<(), String> {
    let entry = refresh_entry(enrollment)?;
    if entry.get_password().is_ok() {
        entry.delete_credential().map_err(|error| error.to_string())?;
    }
    Ok(())
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

fn http_client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(REQUEST_TIMEOUT)
        .connect_timeout(CONNECT_TIMEOUT)
        .user_agent(format!("interest-growth-desktop/{CLIENT_APP_VERSION}"))
        .build()
        .map_err(|error| error.to_string())
}

fn set_session_token(app: &AppHandle, access_token: &str, expires_in: u64) -> Result<(), String> {
    let state = app.state::<DesktopState>();
    let mut session = state
        .remote
        .lock()
        .map_err(|_| "remote session state poisoned".to_string())?;
    *session = Some(RemoteSession {
        access_token: access_token.to_string(),
        expires_at_unix: now_unix() + expires_in as i64,
    });
    Ok(())
}

fn clear_session(app: &AppHandle) {
    if let Some(state) = app.try_state::<DesktopState>() {
        if let Ok(mut session) = state.remote.lock() {
            *session = None;
        }
    }
}

/// Return the in-memory access credential, refreshing first if it is missing
/// or expired (with a grace period so short bursts never cascade refreshes).
async fn get_session_token(app: &AppHandle, enrollment: &RemoteEnrollment) -> Result<String, String> {
    let state = app.state::<DesktopState>();
    let session = state
        .remote
        .lock()
        .map_err(|_| "remote session state poisoned".to_string())?
        .clone();
    if let Some(current) = session.as_ref() {
        if !current.access_token.is_empty()
            && current.expires_at_unix > now_unix() + ACCESS_TOKEN_GRACE_SECS
        {
            return Ok(current.access_token.clone());
        }
    }
    refresh_session_token(app, enrollment).await
}

/// Consume the stored refresh credential once and rotate it. The access token
/// stays in memory; the replacement refresh credential goes straight to the
/// keyring and is never exposed to the renderer.
async fn refresh_session_token(
    app: &AppHandle,
    enrollment: &RemoteEnrollment,
) -> Result<String, String> {
    let refresh_token = read_refresh_token(enrollment)
        .ok_or_else(|| "no remote refresh credential stored; please log in again".to_string())?;
    let client = http_client()?;
    let body = serde_json::json!({
        "device_id": enrollment.device_id,
        "refresh_token": refresh_token,
    });
    let response = client
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
        write_refresh_token(enrollment, next_refresh)?;
    }
    set_session_token(app, &access, expires_in)?;
    Ok(access)
}

async fn send_once(
    app: &AppHandle,
    enrollment: &RemoteEnrollment,
    method: &str,
    path: &str,
    extra_headers: &HashMap<String, String>,
    body: Option<(String, Vec<u8>)>,
) -> Result<(u16, Vec<u8>, String), String> {
    let access = get_session_token(app, enrollment).await?;
    let url = format!("{}{}", enrollment.normalized_origin, path);
    let parsed_method = reqwest::Method::from_bytes(method.as_bytes())
        .map_err(|error| format!("unsupported HTTP method {method}: {error}"))?;
    let mut builder = http_client()?.request(parsed_method, &url).bearer_auth(&access);
    if let Some((content_type, bytes)) = &body {
        builder = builder
            .header(reqwest::header::CONTENT_TYPE, content_type)
            .body(bytes.clone());
    }
    // Caller-supplied headers may carry scoping hints (e.g. X-PG-Interest-Area)
    // but can never override the native Bearer or Content-Type.
    for (key, value) in extra_headers {
        if !key.eq_ignore_ascii_case("authorization") && !key.eq_ignore_ascii_case("content-type") {
            builder = builder.header(key, value);
        }
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
    let bytes = response
        .bytes()
        .await
        .map_err(|error| format!("failed reading remote response: {error}"))?
        .to_vec();
    Ok((status, bytes, content_type))
}

/// Gate C §10.3 — a clear 401 means the request never entered the business
/// path, so refresh once and retry the original request exactly once. Never
/// retried on ambiguous transport failures; mutations are never auto-retried
/// beyond this single auth recovery.
async fn send_with_auth(
    app: &AppHandle,
    enrollment: &RemoteEnrollment,
    method: &str,
    path: &str,
    extra_headers: &HashMap<String, String>,
    body: Option<(String, Vec<u8>)>,
) -> Result<(u16, Vec<u8>, String), String> {
    let mut attempt = send_once(app, enrollment, method, path, extra_headers, body.clone()).await?;
    if attempt.0 == 401 {
        refresh_session_token(app, enrollment).await?;
        attempt = send_once(app, enrollment, method, path, extra_headers, body).await?;
    }
    Ok(attempt)
}

async fn send_multipart_once(
    app: &AppHandle,
    enrollment: &RemoteEnrollment,
    path: &str,
    file_field: &str,
    file_name: &str,
    file_content_type: &str,
    file_bytes: &[u8],
    fields: &HashMap<String, String>,
) -> Result<(u16, Vec<u8>, String), String> {
    let access = get_session_token(app, enrollment).await?;
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
    let response = http_client()?
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
    let bytes = response
        .bytes()
        .await
        .map_err(|error| error.to_string())?
        .to_vec();
    Ok((status, bytes, content_type))
}

async fn send_multipart_with_auth(
    app: &AppHandle,
    enrollment: &RemoteEnrollment,
    path: &str,
    file_field: &str,
    file_name: &str,
    file_content_type: &str,
    file_bytes: &[u8],
    fields: &HashMap<String, String>,
) -> Result<(u16, Vec<u8>, String), String> {
    let mut attempt = send_multipart_once(
        app,
        enrollment,
        path,
        file_field,
        file_name,
        file_content_type,
        file_bytes,
        fields,
    )
    .await?;
    if attempt.0 == 401 {
        refresh_session_token(app, enrollment).await?;
        attempt = send_multipart_once(
            app,
            enrollment,
            path,
            file_field,
            file_name,
            file_content_type,
            file_bytes,
            fields,
        )
        .await?;
    }
    Ok(attempt)
}

async fn probe_server_inner(origin: &str) -> Result<RemoteProbeResult, String> {
    let client = http_client()?;
    let response = client
        .get(format!("{origin}/api/auth/server-info"))
        .send()
        .await
        .map_err(|error| format!("cannot reach server: {error}"))?;
    let status = response.status().as_u16();
    if status != 200 {
        return Err(format!("server-info returned HTTP {status}"));
    }
    let payload: serde_json::Value = response
        .json()
        .await
        .map_err(|error| format!("invalid server-info response: {error}"))?;
    let server = RemoteServerInfo {
        product: payload
            .get("product")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        server_version: payload
            .get("server_version")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        api_version: payload
            .get("api_version")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        min_client_version: payload
            .get("min_client_version")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        server_instance_id: payload
            .get("server_instance_id")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        server_display_name: payload
            .get("server_display_name")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        auth_mode: payload
            .pointer("/auth/mode")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        auth_enabled: payload
            .pointer("/auth/enabled")
            .and_then(|value| value.as_bool())
            .unwrap_or(false),
        owner_configured: payload
            .pointer("/auth/owner_configured")
            .and_then(|value| value.as_bool())
            .unwrap_or(false),
        tls: payload
            .get("tls")
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
    };
    Ok(RemoteProbeResult {
        normalized_origin: origin.to_string(),
        server,
    })
}

// ------------------------------------------------------------- commands

/// Probe a candidate self-hosted server. Returns normalized origin + server
/// metadata so the renderer can run the compatibility checker before enrolling.
#[tauri::command]
pub async fn remote_probe_server(origin: String) -> Result<RemoteProbeResult, String> {
    let normalized = normalize_enrollment_origin(&origin)?;
    probe_server_inner(&normalized).await
}

/// Bootstrap a fresh server owner. Only valid when the server reports
/// `owner_configured == false`. Requires the server-side bootstrap token.
#[tauri::command]
pub async fn remote_bootstrap_owner(
    origin: String,
    owner_password: String,
    bootstrap_token: String,
) -> Result<serde_json::Value, String> {
    let normalized = normalize_enrollment_origin(&origin)?;
    let client = http_client()?;
    let response = client
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

/// Login as the owner on the enrolled-origin server. The refresh credential is
/// written to the OS keyring (server_instance_id:device_id namespace) and the
/// access credential stays in memory; neither reaches the renderer.
#[tauri::command]
pub async fn remote_login(
    app: AppHandle,
    origin: String,
    owner_password: String,
    device_name: String,
    platform: String,
    app_version: String,
    expected_server_instance_id: String,
) -> Result<RemoteLoginResult, String> {
    let normalized = normalize_enrollment_origin(&origin)?;
    let client = http_client()?;
    let payload = serde_json::json!({
        "owner_password": owner_password,
        "device_name": device_name,
        "platform": platform,
        "app_version": if app_version.is_empty() { CLIENT_APP_VERSION } else { app_version.as_str() },
    });
    let response = client
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
    let server = body.get("server").cloned().unwrap_or_default();
    let tokens = body.get("tokens").cloned().unwrap_or_default();

    let server_instance_id = server
        .get("server_instance_id")
        .and_then(|value| value.as_str())
        .unwrap_or_default()
        .to_string();
    // Identity binding (Gate C §6.5): the login must come from the very server
    // that was probed. A replaced server behind the same URL is rejected.
    if !expected_server_instance_id.is_empty() && server_instance_id != expected_server_instance_id {
        return Err(
            "server identity changed during login; re-verify the server before enrolling".into(),
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

    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let enrollment = RemoteEnrollment {
        normalized_origin: normalized,
        server_instance_id: server_instance_id.clone(),
        server_display_name: server
            .get("server_display_name")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        product: server
            .get("product")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        api_version: server
            .get("api_version")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        server_version: server
            .get("server_version")
            .and_then(|value| value.as_str())
            .unwrap_or_default()
            .to_string(),
        min_client_version: server
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
            app_version
        },
        last_verified_at: now_unix().to_string(),
    };
    write_refresh_token(&enrollment, &refresh_token)?;
    save_enrollment(&app_data, &enrollment)?;
    set_session_token(&app, &access_token, expires_in)?;

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
    let enrollment = load_enrollment(&app_data).ok_or_else(|| "not enrolled to a server".to_string())?;
    assert_relative_path(&path)?;
    let method = method.unwrap_or_else(|| "GET".into()).to_uppercase();
    let body_bytes = body.map(|value| value.into_bytes());
    let body_spec = body_bytes.map(|bytes| {
        (
            content_type.clone().unwrap_or_else(|| "application/json".into()),
            bytes,
        )
    });
    let (status, bytes, resolved_content_type) =
        send_with_auth(&app, &enrollment, &method, &path, &headers.unwrap_or_default(), body_spec).await?;
    Ok(RemoteApiResponse {
        status,
        body_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
        content_type: resolved_content_type,
    })
}

/// Multipart upload (e.g. knowledge source files) through the native broker.
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
    let enrollment = load_enrollment(&app_data).ok_or_else(|| "not enrolled to a server".to_string())?;
    assert_relative_path(&path)?;
    let file_bytes = base64::engine::general_purpose::STANDARD
        .decode(file_bytes_b64)
        .map_err(|error| format!("invalid file payload: {error}"))?;
    let file_field = file_field.unwrap_or_else(|| "file".into());
    let file_content_type = file_content_type.unwrap_or_else(|| "application/octet-stream".into());
    let (status, bytes, resolved_content_type) = send_multipart_with_auth(
        &app,
        &enrollment,
        &path,
        &file_field,
        &file_name,
        &file_content_type,
        &file_bytes,
        &fields.unwrap_or_default(),
    )
    .await?;
    Ok(RemoteApiResponse {
        status,
        body_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
        content_type: resolved_content_type,
    })
}

/// Explicitly refresh the session (used by the connection-status UX).
#[tauri::command]
pub async fn remote_refresh_now(app: AppHandle) -> Result<RemoteSessionStatus, String> {
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let enrollment = load_enrollment(&app_data).ok_or_else(|| "not enrolled".to_string())?;
    refresh_session_token(&app, &enrollment).await?;
    Ok(session_status(&app, &enrollment))
}

#[tauri::command]
pub fn remote_session_status(app: AppHandle) -> RemoteSessionStatus {
    let app_data = app.path().app_data_dir().unwrap_or_default();
    match load_enrollment(&app_data) {
        Some(enrollment) => session_status(&app, &enrollment),
        None => RemoteSessionStatus {
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
        },
    }
}

fn session_status(app: &AppHandle, enrollment: &RemoteEnrollment) -> RemoteSessionStatus {
    let session = app
        .state::<DesktopState>()
        .remote
        .lock()
        .map(|value| value.clone())
        .unwrap_or(None);
    let connected = session
        .as_ref()
        .map(|session| !session.access_token.is_empty() && session.expires_at_unix > now_unix())
        .unwrap_or(false);
    let refresh_stored = read_refresh_token(enrollment).is_some();
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

/// Re-probe the enrolled server and compare its instance identity. A mismatch
/// means the server behind the same URL was replaced (Gate C §6.5): the
/// renderer must surface IdentityChanged and require explicit re-enrollment.
#[tauri::command]
pub async fn remote_verify_identity(app: AppHandle) -> Result<serde_json::Value, String> {
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let enrollment = load_enrollment(&app_data).ok_or_else(|| "not enrolled".to_string())?;
    let probe = probe_server_inner(&enrollment.normalized_origin).await?;
    let identity_changed = probe.server.server_instance_id != enrollment.server_instance_id;
    Ok(serde_json::json!({
        "identityChanged": identity_changed,
        "server": probe.server,
    }))
}

/// Log out. `revoke` asks the server to revoke this device; local keyring and
/// enrollment are always cleared regardless of network outcome.
#[tauri::command]
pub async fn remote_logout(app: AppHandle, revoke: bool) -> Result<RemoteLogoutResult, String> {
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let Some(enrollment) = load_enrollment(&app_data) else {
        return Ok(RemoteLogoutResult {
            logged_out: true,
            revoked: false,
        });
    };
    let mut revoked = false;
    if revoke {
        let body = serde_json::json!({ "device_id": enrollment.device_id });
        if let Ok((status, _, _)) = send_with_auth(
            &app,
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
    let _ = delete_refresh_token(&enrollment);
    clear_session(&app);
    clear_enrollment(&app_data);
    Ok(RemoteLogoutResult {
        logged_out: true,
        revoked,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
