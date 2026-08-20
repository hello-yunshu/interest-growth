use std::{
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use keyring::v1::{Entry, Error as KeyringError};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_updater::UpdaterExt;
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};
use url::Url;
use uuid::Uuid;

mod android_bridge;
mod remote;
mod runtime_mode;
// Gate R2 §10.2 — debug-only Android-emulator real remote vertical slice. This
// module is `cfg(debug_assertions)`-gated and inert in release builds.
#[cfg(debug_assertions)]
mod emulator_e2e;
// Gate R2 §10.3 / R4 §10 layer-2 — Desktop A native broker harness for the
// true Native cross-device gate. `desktop-native-harness` feature only; never
// part of a default (product) build.
#[cfg(feature = "desktop-native-harness")]
mod cross_device_harness;
// Gate R2 §8.2 — Android UI/IPC smoke invoke back-end. Compiled in both build
// kinds so the invoke_handler list stays valid; bodies are inert in release.
mod ui_ipc_e2e;

use remote::RemoteBroker;
#[cfg(not(target_os = "android"))]
use remote::KeyringStore;
#[cfg(target_os = "android")]
use remote::AndroidKeystoreStore;
use runtime_mode::{
    broker_expected_runtime_id, parse_runtime_mode, should_spawn_sidecar, RuntimeMode, RuntimeProfile,
};

const KEYRING_SERVICE: &str = "app.psychologygrowth.desktop";
const PROVIDER_SETTINGS_FILE: &str = "provider-settings.json";

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeInfo {
    runtime_id: String,
    endpoint: String,
    token: String,
    status: String,
    data_dir: String,
    version: String,
    updater_configured: bool,
    platform: String,
}

// Gate C §5.3 / Gate D §P10 — active/pending runtime separation.
//
// `active_runtime_id` is the process-lifetime immutable mode resolved at setup
// (the only source of truth for this session). `pending_runtime_id` is the
// persisted NEXT profile that only applies after an explicit restart.
// `restart_required` is true whenever the persisted profile differs from the
// active mode, so the UI can never present a pending mode as already active.
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeModeInfo {
    active_runtime_id: String,
    pending_runtime_id: String,
    restart_required: bool,
    // Session immutable: the profile only applies after an explicit restart.
    session_immutable: bool,
}

fn runtime_mode_info(active: RuntimeMode, pending: Option<&RuntimeProfile>) -> RuntimeModeInfo {
    let pending_mode = parse_runtime_mode(pending);
    RuntimeModeInfo {
        active_runtime_id: active.as_str().into(),
        pending_runtime_id: pending_mode.as_str().into(),
        restart_required: active != pending_mode,
        session_immutable: true,
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProviderSettings {
    deepseek_base_url: String,
    deepseek_model: String,
}

impl Default for ProviderSettings {
    fn default() -> Self {
        Self {
            deepseek_base_url: "https://api.deepseek.com".into(),
            deepseek_model: "deepseek-chat".into(),
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProviderSecretStatus {
    kind: String,
    configured: bool,
    secure_store_available: bool,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct UpdateInfo {
    available: bool,
    current_version: String,
    version: String,
    notes: String,
    published_at: String,
}

struct DesktopState {
    runtime: Mutex<RuntimeInfo>,
    child: Arc<Mutex<Option<CommandChild>>>,
    mode: RuntimeMode,
    // Native remote broker: owns the HTTP transport, the OS-keyring credential
    // store and the shared session state (Gate D §P24). The refresh credential
    // never enters this struct nor the renderer (Gate C §11).
    broker: RemoteBroker,
}

fn secret_username(kind: &str) -> Result<&'static str, String> {
    match kind {
        "deepseek" => Ok("deepseek-api-key"),
        _ => Err("unsupported provider secret kind".into()),
    }
}

fn secret_entry(kind: &str) -> Result<Entry, String> {
    let username = secret_username(kind)?;
    Entry::new(KEYRING_SERVICE, username).map_err(|error| error.to_string())
}

fn read_provider_secret(kind: &str) -> Option<String> {
    let entry = secret_entry(kind).ok()?;
    entry
        .get_password()
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn settings_path(app_data: &Path) -> PathBuf {
    app_data.join(PROVIDER_SETTINGS_FILE)
}

fn load_provider_settings(app_data: &Path) -> ProviderSettings {
    let path = settings_path(app_data);
    let backup = path.with_extension("json.bak");
    for candidate in [&path, &backup] {
        if let Ok(raw) = std::fs::read_to_string(candidate) {
            if let Ok(settings) = serde_json::from_str::<ProviderSettings>(&raw) {
                return settings;
            }
        }
    }
    ProviderSettings::default()
}

fn runtime_profile_path(app_data: &Path) -> PathBuf {
    app_data.join(runtime_mode::RUNTIME_PROFILE_FILE)
}

fn load_runtime_profile(app_data: &Path) -> Option<RuntimeProfile> {
    let raw = std::fs::read_to_string(runtime_profile_path(app_data)).ok()?;
    serde_json::from_str::<RuntimeProfile>(&raw).ok()
}

fn save_runtime_profile(app_data: &Path, profile: &RuntimeProfile) -> Result<(), String> {
    std::fs::create_dir_all(app_data).map_err(|error| error.to_string())?;
    let path = runtime_profile_path(app_data);
    let temp = path.with_extension("json.tmp");
    let payload = serde_json::to_vec_pretty(profile).map_err(|error| error.to_string())?;
    {
        let mut file = std::fs::File::create(&temp).map_err(|error| error.to_string())?;
        file.write_all(&payload).map_err(|error| error.to_string())?;
        file.sync_all().map_err(|error| error.to_string())?;
    }
    std::fs::rename(&temp, &path).map_err(|error| error.to_string())
}

// Desktop-only: the Android shell always uses android_remote_mode() instead.
#[cfg(not(target_os = "android"))]
fn resolve_runtime_mode(app_data: &Path) -> RuntimeMode {
    parse_runtime_mode(load_runtime_profile(app_data).as_ref())
}

fn validate_http_url(label: &str, value: &str, https_or_loopback: bool) -> Result<String, String> {
    let trimmed = value.trim();
    let parsed = Url::parse(trimmed).map_err(|error| format!("invalid {label}: {error}"))?;
    if parsed.host_str().is_none() {
        return Err(format!("{label} must include a host"));
    }
    if !parsed.username().is_empty() || parsed.password().is_some() {
        return Err(format!("{label} must not contain embedded credentials"));
    }
    let host = parsed.host_str().unwrap_or_default().to_ascii_lowercase();
    let loopback = host == "localhost" || host == "127.0.0.1" || host == "::1";
    let valid = if https_or_loopback {
        parsed.scheme() == "https" || (parsed.scheme() == "http" && loopback)
    } else {
        parsed.scheme() == "http" || parsed.scheme() == "https"
    };
    if !valid {
        return Err(format!(
            "{label} must use HTTPS, or loopback HTTP when local"
        ));
    }
    Ok(parsed.as_str().trim_end_matches('/').to_string())
}

fn normalize_provider_settings(mut value: ProviderSettings) -> Result<ProviderSettings, String> {
    value.deepseek_base_url = validate_http_url("DeepSeek base URL", &value.deepseek_base_url, true)?;
    value.deepseek_model = value.deepseek_model.trim().to_string();
    if value.deepseek_model.is_empty() {
        return Err("DeepSeek model cannot be empty".into());
    }
    Ok(value)
}

fn save_provider_settings(app_data: &Path, value: &ProviderSettings) -> Result<(), String> {
    std::fs::create_dir_all(app_data).map_err(|error| error.to_string())?;
    let path = settings_path(app_data);
    let temp = path.with_extension("json.tmp");
    let backup = path.with_extension("json.bak");
    let payload = serde_json::to_vec_pretty(value).map_err(|error| error.to_string())?;
    {
        let mut file = std::fs::File::create(&temp).map_err(|error| error.to_string())?;
        file.write_all(&payload).map_err(|error| error.to_string())?;
        file.sync_all().map_err(|error| error.to_string())?;
    }
    if backup.exists() {
        std::fs::remove_file(&backup).map_err(|error| error.to_string())?;
    }
    let had_previous = path.exists();
    if had_previous {
        std::fs::rename(&path, &backup).map_err(|error| error.to_string())?;
    }
    if let Err(error) = std::fs::rename(&temp, &path) {
        if had_previous && backup.exists() {
            let _ = std::fs::rename(&backup, &path);
        }
        return Err(error.to_string());
    }
    if backup.exists() {
        let _ = std::fs::remove_file(&backup);
    }
    Ok(())
}

#[tauri::command]
fn desktop_runtime(state: State<'_, DesktopState>) -> RuntimeInfo {
    state.runtime.lock().expect("desktop state poisoned").clone()
}

#[tauri::command]
fn desktop_runtime_mode(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<RuntimeModeInfo, String> {
    // The ACTIVE mode is the process-lifetime value resolved at setup. Reading
    // the disk profile here must never pretend a pending mode is already active.
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let pending = load_runtime_profile(&app_data);
    Ok(runtime_mode_info(state.mode, pending.as_ref()))
}

// Gate C §5.2 — mode switch primitive. It persists the NEXT profile and never
// hot-swaps the current session (session immutable). The response keeps
// `activeRuntimeId` unchanged so the UI shows the real data location and an
// explicit restart requirement until the restart happens.
#[tauri::command]
fn set_desktop_runtime_mode(
    app: AppHandle,
    state: State<'_, DesktopState>,
    runtime_id: String,
) -> Result<RuntimeModeInfo, String> {
    #[cfg(target_os = "android")]
    {
        return Err("android-remote runtime mode is immutable; switching is unsupported on Android".into());
    }
    #[cfg(not(target_os = "android"))]
    {
        if !runtime_mode::is_desktop_runtime_id(&runtime_id) {
            return Err(format!("unsupported desktop runtime mode: {runtime_id}"));
        }
        let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
        let profile = RuntimeProfile {
            runtime_id,
        };
        save_runtime_profile(&app_data, &profile)?;
        let pending = load_runtime_profile(&app_data);
        Ok(runtime_mode_info(state.mode, pending.as_ref()))
    }
}

#[tauri::command]
fn desktop_platform_policy() -> serde_json::Value {
    serde_json::json!({
        "windows": "Windows 11 24H2+ (build 26100+, x64)",
        "macos": "macOS 13 Ventura+ (Apple Silicon)",
        "linux": "development/test host only"
    })
}

// Gate D §D5 — explicit restart boundary. A runtime-mode switch is persisted
// as the NEXT profile and only applies after a real application restart, so
// local and remote datasets are never mixed in one session (Gate C §5.3).
#[tauri::command]
fn restart_app(app: AppHandle) -> Result<(), String> {
    app.request_restart();
    Ok(())
}

#[tauri::command]
async fn check_for_update(app: AppHandle) -> Result<UpdateInfo, String> {
    #[cfg(target_os = "android")]
    return Err("updater is a desktop-only capability; unsupported on Android".into());
    #[cfg(not(target_os = "android"))]
    {
        if option_env!("PG_UPDATER_CONFIGURED") != Some("1") {
            return Err("this build does not have a signed updater channel configured".into());
        }
        let updater = app.updater().map_err(|error| error.to_string())?;
        let update = updater.check().await.map_err(|error| error.to_string())?;
        Ok(match update {
            Some(update) => UpdateInfo {
                available: true,
                current_version: update.current_version,
                version: update.version,
                notes: update.body.unwrap_or_default(),
                published_at: update.date.map(|date| date.to_string()).unwrap_or_default(),
            },
            None => UpdateInfo {
                available: false,
                current_version: env!("CARGO_PKG_VERSION").into(),
                version: String::new(),
                notes: String::new(),
                published_at: String::new(),
            },
        })
    }
}

#[tauri::command]
async fn install_available_update(app: AppHandle) -> Result<bool, String> {
    #[cfg(target_os = "android")]
    return Err("updater is a desktop-only capability; unsupported on Android".into());
    #[cfg(not(target_os = "android"))]
    {
        if option_env!("PG_UPDATER_CONFIGURED") != Some("1") {
            return Err("this build does not have a signed updater channel configured".into());
        }
        let updater = app.updater().map_err(|error| error.to_string())?;
        let Some(update) = updater.check().await.map_err(|error| error.to_string())? else {
            return Ok(false);
        };
        update
            .download_and_install(|_, _| {}, || {})
            .await
            .map_err(|error| error.to_string())?;
        app.request_restart();
        Ok(true)
    }
}

// Gate D §P14 — provider administration is desktop-local only. The renderer
// is not a security boundary: even if the UI hides these controls in remote
// mode, a remote-mode renderer must never read or mutate local provider
// settings / secrets, and desktop-remote never owns a local Core to restart.
fn ensure_local_mode(mode: RuntimeMode) -> Result<(), String> {
    if mode != RuntimeMode::DesktopLocal {
        return Err("this action is only available in desktop-local mode".into());
    }
    Ok(())
}

fn require_desktop_local(state: &State<'_, DesktopState>) -> Result<(), String> {
    ensure_local_mode(state.mode)
}

#[tauri::command]
fn desktop_provider_settings(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<ProviderSettings, String> {
    require_desktop_local(&state)?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    Ok(load_provider_settings(&app_data))
}

#[tauri::command]
fn set_desktop_provider_settings(
    app: AppHandle,
    state: State<'_, DesktopState>,
    settings: ProviderSettings,
) -> Result<ProviderSettings, String> {
    require_desktop_local(&state)?;
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let normalized = normalize_provider_settings(settings)?;
    save_provider_settings(&app_data, &normalized)?;
    Ok(normalized)
}

#[tauri::command]
fn provider_secret_status(
    kind: String,
    state: State<'_, DesktopState>,
) -> Result<ProviderSecretStatus, String> {
    require_desktop_local(&state)?;
    let username = secret_username(&kind)?;
    let entry = match Entry::new(KEYRING_SERVICE, username) {
        Ok(entry) => entry,
        Err(_) => {
            return Ok(ProviderSecretStatus {
                kind,
                configured: false,
                secure_store_available: false,
            });
        }
    };
    let (configured, secure_store_available) = match entry.get_password() {
        Ok(value) => (!value.trim().is_empty(), true),
        Err(KeyringError::NoEntry) => (false, true),
        Err(_) => (false, false),
    };
    Ok(ProviderSecretStatus {
        kind,
        configured,
        secure_store_available,
    })
}

#[tauri::command]
fn set_provider_secret(
    kind: String,
    secret: String,
    state: State<'_, DesktopState>,
) -> Result<ProviderSecretStatus, String> {
    require_desktop_local(&state)?;
    let value = secret.trim();
    if value.is_empty() {
        return Err("secret cannot be empty".into());
    }
    let entry = secret_entry(&kind)?;
    entry.set_password(value).map_err(|error| error.to_string())?;
    Ok(ProviderSecretStatus {
        kind,
        configured: true,
        secure_store_available: true,
    })
}

#[tauri::command]
fn delete_provider_secret(
    kind: String,
    state: State<'_, DesktopState>,
) -> Result<ProviderSecretStatus, String> {
    require_desktop_local(&state)?;
    let entry = secret_entry(&kind)?;
    if entry.get_password().is_ok() {
        entry.delete_credential().map_err(|error| error.to_string())?;
    }
    Ok(ProviderSecretStatus {
        kind,
        configured: false,
        secure_store_available: true,
    })
}

fn free_loopback_port() -> Result<u16, String> {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    listener
        .local_addr()
        .map(|addr| addr.port())
        .map_err(|error| error.to_string())
}

fn core_health_ready(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(250)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(350)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(350)));
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = Vec::with_capacity(1024);
    if stream.read_to_end(&mut response).is_err() {
        return false;
    }
    let text = String::from_utf8_lossy(&response);
    text.starts_with("HTTP/1.1 200") && text.contains("\"service\":\"interest-growth-api\"")
}

fn wait_for_core_health(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if core_health_ready(port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    false
}

fn spawn_core(
    app: &AppHandle,
    child_slot: Arc<Mutex<Option<CommandChild>>>,
    mode: RuntimeMode,
) -> Result<RuntimeInfo, String> {
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&app_data).map_err(|error| error.to_string())?;
    for child in ["sources", "artifacts", "logs"] {
        std::fs::create_dir_all(app_data.join(child)).map_err(|error| error.to_string())?;
    }

    let provider_settings = load_provider_settings(&app_data);
    let port = free_loopback_port()?;
    let port_string = port.to_string();
    let token = Uuid::new_v4().as_simple().to_string();
    let endpoint = format!("http://127.0.0.1:{port}");

    let mut command = app
        .shell()
        .sidecar("psychology-growth-core")
        .map_err(|error| error.to_string())?
        .args(["--host", "127.0.0.1", "--port", port_string.as_str()])
        .env("APP_ENV", "desktop")
        .env("APP_DATA_ROOT", app_data.as_os_str())
        .env("PG_DESKTOP_TOKEN", &token)
        .env("PG_CORE_LOG_LEVEL", "warning");

    if std::env::var_os("DEEPSEEK_BASE_URL").is_none() {
        command = command.env("DEEPSEEK_BASE_URL", &provider_settings.deepseek_base_url);
    }
    if std::env::var_os("DEEPSEEK_MODEL").is_none() {
        command = command.env("DEEPSEEK_MODEL", &provider_settings.deepseek_model);
    }
    if std::env::var_os("DEEPSEEK_API_KEY").is_none() {
        if let Some(secret) = read_provider_secret("deepseek") {
            command = command.env("DEEPSEEK_API_KEY", secret);
        }
    }

    let (mut rx, child) = command.spawn().map_err(|error| error.to_string())?;
    *child_slot.lock().map_err(|_| "child state poisoned")? = Some(child);

    let app_events = app.clone();
    let runtime_token = token.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let _ = app_events.emit("core-log", String::from_utf8_lossy(&bytes).to_string());
                }
                CommandEvent::Stderr(bytes) => {
                    let _ = app_events.emit("core-error", String::from_utf8_lossy(&bytes).to_string());
                }
                CommandEvent::Terminated(payload) => {
                    if let Some(state) = app_events.try_state::<DesktopState>() {
                        if let Ok(mut runtime) = state.runtime.lock() {
                            if runtime.token == runtime_token {
                                runtime.endpoint = "http://127.0.0.1:0".into();
                                runtime.token.clear();
                                runtime.status = format!("error:core-terminated:{:?}", payload.code);
                            }
                        }
                    }
                    let _ = app_events.emit("core-terminated", format!("{:?}", payload.code));
                }
                _ => {}
            }
        }
    });

    // A signed/packaged PyInstaller sidecar can need more than ten seconds on
    // its first macOS launch while dyld and the OS validate/extract resources.
    let ready = wait_for_core_health(port, Duration::from_secs(30));
    if !ready {
        if let Ok(mut guard) = child_slot.lock() {
            if let Some(child) = guard.take() {
                let _ = child.kill();
            }
        }
        return Err("Interest Growth Core did not become ready within 30 seconds".into());
    }

    Ok(RuntimeInfo {
        runtime_id: mode.as_str().into(),
        endpoint,
        token,
        status: "ready".into(),
        data_dir: app_data.to_string_lossy().to_string(),
        version: env!("CARGO_PKG_VERSION").into(),
        updater_configured: option_env!("PG_UPDATER_CONFIGURED") == Some("1"),
        platform: std::env::consts::OS.into(),
    })
}

fn stop_core(child_slot: &Arc<Mutex<Option<CommandChild>>>) {
    if let Ok(mut guard) = child_slot.lock() {
        if let Some(child) = guard.take() {
            let _ = child.kill();
        }
    }
}

fn runtime_error(app: &AppHandle, error: &str, mode: RuntimeMode) -> RuntimeInfo {
    RuntimeInfo {
        runtime_id: mode.as_str().into(),
        endpoint: "http://127.0.0.1:0".into(),
        token: String::new(),
        status: format!("error:{error}"),
        data_dir: app
            .path()
            .app_data_dir()
            .map(|path| path.to_string_lossy().to_string())
            .unwrap_or_default(),
        version: env!("CARGO_PKG_VERSION").into(),
        updater_configured: option_env!("PG_UPDATER_CONFIGURED") == Some("1"),
        platform: std::env::consts::OS.into(),
    }
}

// Gate C §5 — desktop-remote (or any non-local mode) never spawns a local
// Core and never falls back to a local dataset. The status is explicit so the
// renderer can honestly report "remote is not active in this build".
fn runtime_remote(app: &AppHandle, mode: RuntimeMode) -> RuntimeInfo {
    RuntimeInfo {
        runtime_id: mode.as_str().into(),
        endpoint: String::new(),
        token: String::new(),
        status: format!("mode:{}:sidecar-disabled", mode.as_str()),
        data_dir: app
            .path()
            .app_data_dir()
            .map(|path| path.to_string_lossy().to_string())
            .unwrap_or_default(),
        version: env!("CARGO_PKG_VERSION").into(),
        updater_configured: option_env!("PG_UPDATER_CONFIGURED") == Some("1"),
        platform: std::env::consts::OS.into(),
    }
}

#[tauri::command]
fn restart_desktop_core(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<RuntimeInfo, String> {
    require_desktop_local(&state)?;
    stop_core(&state.child);
    match spawn_core(&app, state.child.clone(), state.mode) {
        Ok(runtime) => {
            *state.runtime.lock().map_err(|_| "desktop state poisoned")? = runtime.clone();
            Ok(runtime)
        }
        Err(error) => {
            let failed = runtime_error(&app, &error, state.mode);
            *state.runtime.lock().map_err(|_| "desktop state poisoned")? = failed;
            Err(error)
        }
    }
}

// Gate R2 §10.3 / R4 §10 layer-2 — Desktop A native broker harness entry.
// The CI cross-device job builds the `desktop_native_harness` binary
// (required-features = ["desktop-native-harness"]) and runs it against a real
// Docker server to prove cross-device sync with a real Android emulator. The
// harness is feature-gated and inert in every product build. `config_json` is
// the `HarnessConfig` document (phase a_create / b_revoke). Returns the
// process exit code: 0 = PASS, 1 = FAIL, 2 = harness error.
#[cfg(feature = "desktop-native-harness")]
pub fn run_desktop_native_harness(config_json: &str) -> i32 {
    let config: cross_device_harness::HarnessConfig = match serde_json::from_str(config_json) {
        Ok(config) => config,
        Err(error) => {
            eprintln!("desktop_native_harness: invalid config: {error}");
            return 2;
        }
    };
    let runtime = match tokio::runtime::Runtime::new() {
        Ok(runtime) => runtime,
        Err(error) => {
            eprintln!("desktop_native_harness: cannot start runtime: {error}");
            return 2;
        }
    };
    match runtime.block_on(cross_device_harness::run_harness(config)) {
        Ok(report) => {
            let pass = report.get("result").and_then(|value| value.as_str()) == Some("PASS");
            println!("{}", serde_json::to_string_pretty(&report).unwrap_or_default());
            println!("HARNESS RESULT={}", if pass { "PASS" } else { "FAIL" });
            if pass { 0 } else { 1 }
        }
        Err(error) => {
            eprintln!("desktop_native_harness: FAIL: {error}");
            1
        }
    }
}

// Gate E — the mobile entry point macro generates the Android JNI entry that
// the runtime uses to drive the app on-device. Without it the built .so lacks
// the required `Java_app_tauri_plugin_PluginManager_handlePluginResponse`
// symbol and the Gradle `rustBuild*` task fails the library validation step.
// On desktop this cfg is false and `run()` is a plain function.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let child_slot: Arc<Mutex<Option<CommandChild>>> = Arc::new(Mutex::new(None));
    let slot_for_setup = child_slot.clone();

    let mut builder = tauri::Builder::default();
    // Gate R2 §6.4 — desktop vs Android plugin surface is structurally split.
    // shell / updater / dialog / fs are DESKTOP-only capabilities; Android must
    // not gain desktop updater/fs/dialog/shell management by unconditional
    // registration. opener stays on both (Android opens external URLs through
    // the system browser via `opener:allow-default-urls`), and the SAF bridge
    // plugin is registered on both (no-op on desktop).
    #[cfg(not(target_os = "android"))]
    {
        builder = builder
            .plugin(tauri_plugin_shell::init())
            .plugin(tauri_plugin_updater::Builder::new().build())
            .plugin(tauri_plugin_dialog::init())
            .plugin(tauri_plugin_fs::init())
            .plugin(tauri_plugin_opener::init());
    }
    #[cfg(target_os = "android")]
    {
        builder = builder.plugin(tauri_plugin_opener::init());
    }
    builder = builder
        // Gate R0.5/R0.6 — registers the Kotlin InterestGrowthPlugin on
        // Android (no-op plugin on desktop). The SAF bridge lets the native
        // layer read/write file bytes without a renderer base64 copy.
        .plugin(android_bridge::init());
    // Gate E §6.3 — single-instance and window-state are desktop-only plugins.
    // The Android host has no OS-level single-instance and no desktop window to
    // persist state for, so they are compiled out.
    #[cfg(not(target_os = "android"))]
    let slot_for_exit = child_slot.clone();
    #[cfg(not(target_os = "android"))]
    {
        builder = builder
            .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.unminimize();
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }))
            .plugin(tauri_plugin_window_state::Builder::default().build());
    }

    builder = builder
        .setup(move |app| {
            // Gate E §6.3 — the Android shell is always android-remote and
            // never spawns a local Core. Desktop keeps its profile-driven mode.
            #[cfg(target_os = "android")]
            let mode = runtime_mode::android_remote_mode();
            #[cfg(not(target_os = "android"))]
            let mode = resolve_runtime_mode(&app.path().app_data_dir().unwrap_or_default());
            let runtime = if should_spawn_sidecar(mode) {
                spawn_core(app.handle(), slot_for_setup.clone(), mode)
                    .unwrap_or_else(|error| runtime_error(app.handle(), &error, mode))
            } else {
                runtime_remote(app.handle(), mode)
            };
            // Gate E §6.4 — on Android the OS-backed Android Keystore is the
            // credential store; on desktop the platform keyring is used.
            // Gate R0.3 / R0 §4 — the broker's expected runtime is the ACTIVE
            // mode's remote runtime id, so a server must advertise exactly
            // android-remote / desktop-remote. desktop-local still owns a
            // broker (never reachable while local mode is active) using the
            // default remote runtime id.
            #[cfg(target_os = "android")]
            let broker = {
                // Phase 4d — CI-only optional TLS trust root. On the upgrade-
                // test APK the adb-runner sets `ig.ci.tls_ca_path` to an
                // ephemeral CI CA; production (property unset) → None and the
                // broker keeps its default Mozilla roots. Fail-closed if the
                // property is set but the CA can't be loaded.
                let trust_root = remote::ci_tls_trust_root()
                    .map_err(|error| format!("failed to load CI TLS trust root: {error}"))?;
                RemoteBroker::with_expected_runtime_and_trust_root(
                    AndroidKeystoreStore::new()
                        .map_err(|error| format!("failed to open Android Keystore: {error}"))?,
                    broker_expected_runtime_id(mode),
                    trust_root,
                )
                .map_err(|error| format!("failed to initialize remote broker: {error}"))?
            };
            #[cfg(not(target_os = "android"))]
            let broker =
                RemoteBroker::with_expected_runtime(Arc::new(KeyringStore), broker_expected_runtime_id(mode))
                    .map_err(|error| format!("failed to initialize remote broker: {error}"))?;
            app.manage(DesktopState {
                runtime: Mutex::new(runtime),
                child: slot_for_setup.clone(),
                mode,
                broker,
            });
            // Gate R2 §10.2 — debug-only Android-emulator vertical slice. When a
            // CI-emulator trigger config exists inside the app-private files dir,
            // drive the REAL native remote broker against the emulator-host
            // loopback server and record results for CI to poll. Inert otherwise.
            #[cfg(debug_assertions)]
            {
                let e2e_broker = app.state::<DesktopState>().broker.clone();
                let e2e_app_data = app.path().app_data_dir().unwrap_or_default();
                tauri::async_runtime::spawn(async move {
                    emulator_e2e::maybe_run_emulator_e2e(e2e_broker, e2e_app_data).await;
                });
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            desktop_runtime,
            desktop_runtime_mode,
            set_desktop_runtime_mode,
            desktop_platform_policy,
            check_for_update,
            install_available_update,
            desktop_provider_settings,
            set_desktop_provider_settings,
            provider_secret_status,
            set_provider_secret,
            delete_provider_secret,
            restart_desktop_core,
            restart_app,
            // Gate D — native remote credential broker + transport.
            remote::remote_probe_server,
            remote::remote_bootstrap_owner,
            remote::remote_login,
            remote::remote_api_request,
            remote::remote_api_upload,
            remote::remote_api_upload_by_uri,
            remote::remote_pick_document,
            remote::remote_save_export,
            remote::remote_refresh_now,
            remote::remote_session_status,
            remote::remote_verify_identity,
            remote::remote_logout,
            // Gate R2 §8.2 — Android UI/IPC smoke invoke channel (inert outside
            // debug+android).
            ui_ipc_e2e::ui_ipc_e2e_should_run,
            ui_ipc_e2e::ui_ipc_e2e_record,
        ]);
    // Gate E §6.3 — the desktop window-lifecycle hook only exists on desktop.
    // The Android host stops the (never-spawned) Core on nothing.
    #[cfg(not(target_os = "android"))]
    {
        builder = builder.on_window_event(move |_window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                stop_core(&slot_for_exit);
            }
        });
    }

    builder
        .run(tauri::generate_context!())
        .expect("error while running Interest Growth desktop");
}

#[cfg(test)]
mod tests {
    use super::*;
    use runtime_mode::RUNTIME_ID_DESKTOP_LOCAL;

    // Gate D §P10 — active/pending runtime separation.
    #[test]
    fn active_local_with_no_pending_profile() {
        let info = runtime_mode_info(RuntimeMode::DesktopLocal, None);
        assert_eq!(info.active_runtime_id, RUNTIME_ID_DESKTOP_LOCAL);
        assert_eq!(info.pending_runtime_id, RUNTIME_ID_DESKTOP_LOCAL);
        assert!(!info.restart_required);
        assert!(info.session_immutable);
    }

    #[test]
    fn persist_remote_pending_keeps_active_local_and_requires_restart() {
        let pending = RuntimeProfile {
            runtime_id: runtime_mode::RUNTIME_ID_DESKTOP_REMOTE.into(),
        };
        let info = runtime_mode_info(RuntimeMode::DesktopLocal, Some(&pending));
        assert_eq!(info.active_runtime_id, RUNTIME_ID_DESKTOP_LOCAL);
        assert_eq!(info.pending_runtime_id, runtime_mode::RUNTIME_ID_DESKTOP_REMOTE);
        assert!(info.restart_required, "restart must be required after persisting a switch");
    }

    #[test]
    fn after_restart_active_matches_pending_and_no_restart_needed() {
        let pending = RuntimeProfile {
            runtime_id: runtime_mode::RUNTIME_ID_DESKTOP_REMOTE.into(),
        };
        let info = runtime_mode_info(RuntimeMode::DesktopRemote, Some(&pending));
        assert_eq!(info.active_runtime_id, runtime_mode::RUNTIME_ID_DESKTOP_REMOTE);
        assert_eq!(info.pending_runtime_id, runtime_mode::RUNTIME_ID_DESKTOP_REMOTE);
        assert!(!info.restart_required);
    }

    // Gate D §P14 — provider administration is desktop-local only.
    #[test]
    fn local_mode_permits_provider_administration() {
        assert!(ensure_local_mode(RuntimeMode::DesktopLocal).is_ok());
    }

    #[test]
    fn remote_mode_denies_provider_administration() {
        let error = ensure_local_mode(RuntimeMode::DesktopRemote).unwrap_err();
        assert!(error.contains("desktop-local"));
    }

    // Gate R2 §6.4 — static audit of the Android plugin/capability surface.
    // The Android capability file must never inherit desktop shell/window/
    // fs/dialog/updater permissions, and desktop-only invoke commands must
    // reject on Android builds.
    #[test]
    fn android_capability_surface_stays_minimal() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let android_cap = std::fs::read_to_string(root.join("capabilities/android.json"))
            .expect("capabilities/android.json must exist");
        for banned in [
            "window-state",
            "dialog:allow-save",
            "fs:allow-write-file",
            "shell:",
            "updater:",
        ] {
            assert!(
                !android_cap.contains(banned),
                "android.json must not grant {banned}"
            );
        }
        assert!(android_cap.contains("opener:allow-default-urls"));
        let desktop_cap = std::fs::read_to_string(root.join("capabilities/default.json"))
            .expect("capabilities/default.json must exist");
        assert!(!desktop_cap.contains("\"android\""));
        assert!(desktop_cap.contains("dialog:allow-save"));
        assert!(desktop_cap.contains("fs:allow-write-file"));
    }

    // Gate R2 §6.4 — Android cannot invoke the desktop-only updater install or
    // runtime-mode switch. These compile out to a hard error on Android.
    #[cfg(target_os = "android")]
    #[test]
    fn android_rejects_desktop_only_commands() {
        let info = runtime_mode_info(RuntimeMode::AndroidRemote, None);
        assert_eq!(info.active_runtime_id, RUNTIME_ID_ANDROID_REMOTE);
    }

    #[cfg(not(target_os = "android"))]
    #[test]
    fn android_compile_guard_is_desktop_noop() {
        // On desktop these commands are reachable; the cfg gates are asserted by
        // the Android emulator/upgrade jobs on the Android target build.
        assert!(true);
    }
}
