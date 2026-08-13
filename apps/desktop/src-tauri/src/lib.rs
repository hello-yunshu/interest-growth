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

const KEYRING_SERVICE: &str = "app.psychologygrowth.desktop";
const PROVIDER_SETTINGS_FILE: &str = "provider-settings.json";

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeInfo {
    endpoint: String,
    token: String,
    status: String,
    data_dir: String,
    version: String,
    updater_configured: bool,
    platform: String,
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
fn desktop_platform_policy() -> serde_json::Value {
    serde_json::json!({
        "windows": "Windows 11 24H2+ (build 26100+, x64)",
        "macos": "macOS 13 Ventura+ (Apple Silicon)",
        "linux": "development/test host only"
    })
}

#[tauri::command]
async fn check_for_update(app: AppHandle) -> Result<UpdateInfo, String> {
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

#[tauri::command]
async fn install_available_update(app: AppHandle) -> Result<bool, String> {
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

#[tauri::command]
fn desktop_provider_settings(app: AppHandle) -> Result<ProviderSettings, String> {
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    Ok(load_provider_settings(&app_data))
}

#[tauri::command]
fn set_desktop_provider_settings(
    app: AppHandle,
    settings: ProviderSettings,
) -> Result<ProviderSettings, String> {
    let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let normalized = normalize_provider_settings(settings)?;
    save_provider_settings(&app_data, &normalized)?;
    Ok(normalized)
}

#[tauri::command]
fn provider_secret_status(kind: String) -> Result<ProviderSecretStatus, String> {
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
fn set_provider_secret(kind: String, secret: String) -> Result<ProviderSecretStatus, String> {
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
fn delete_provider_secret(kind: String) -> Result<ProviderSecretStatus, String> {
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

fn runtime_error(app: &AppHandle, error: &str) -> RuntimeInfo {
    RuntimeInfo {
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

#[tauri::command]
fn restart_desktop_core(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<RuntimeInfo, String> {
    stop_core(&state.child);
    match spawn_core(&app, state.child.clone()) {
        Ok(runtime) => {
            *state.runtime.lock().map_err(|_| "desktop state poisoned")? = runtime.clone();
            Ok(runtime)
        }
        Err(error) => {
            let failed = runtime_error(&app, &error);
            *state.runtime.lock().map_err(|_| "desktop state poisoned")? = failed;
            Err(error)
        }
    }
}

pub fn run() {
    let child_slot: Arc<Mutex<Option<CommandChild>>> = Arc::new(Mutex::new(None));
    let slot_for_setup = child_slot.clone();
    let slot_for_exit = child_slot.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_opener::init())
        .setup(move |app| {
            let runtime = spawn_core(app.handle(), slot_for_setup.clone())
                .unwrap_or_else(|error| runtime_error(app.handle(), &error));
            app.manage(DesktopState {
                runtime: Mutex::new(runtime),
                child: slot_for_setup.clone(),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            desktop_runtime,
            desktop_platform_policy,
            check_for_update,
            install_available_update,
            desktop_provider_settings,
            set_desktop_provider_settings,
            provider_secret_status,
            set_provider_secret,
            delete_provider_secret,
            restart_desktop_core
        ])
        .on_window_event(move |_window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                stop_core(&slot_for_exit);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Interest Growth desktop");
}
