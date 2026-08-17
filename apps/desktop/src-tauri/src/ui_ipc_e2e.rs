// Gate R2 §8.2 — Android-emulator UI/IPC smoke (Rust side).
//
// The §10.2 vertical slice (`emulator_e2e`) proves the native remote broker →
// server leg but deliberately runs WITHOUT a WebView (no JS / Tauri invoke /
// IPC). §8.2 requires the missing half of the chain:
//
//   WebView/Renderer → ClientRuntime → Tauri invoke → native broker → server
//
// This module is that chain's INVOKE back-end. It exposes two debug-only Tauri
// commands that the renderer driver (`apps/web/lib/runtime/ui-ipc-e2e.js`) uses
// while running INSIDE the real Android WebView:
//
//   * `ui_ipc_e2e_should_run` — returns the CI-injected trigger config when the
//     emulator job has written `files/ig_uiipc_config.json`, else None.
//   * `ui_ipc_e2e_record`     — persists each step (and the final PASS/FAIL)
//     to `files/ig_uiipc_result.json` for CI to poll.
//
// The commands are compiled in BOTH build kinds so the `invoke_handler` list
// stays valid, but their bodies are inert except under
// `cfg!(all(debug_assertions, target_os = "android"))`. In a release APK (or on
// desktop) neither reads the trigger file nor writes any result, so no
// authorization bypass / test surface is exposed in shipped artifacts.
use serde::{Deserialize, Serialize};
use serde_json::json;
use tauri::State;

use crate::DesktopState;

/// Loopback-only marker paths inside the app-private files dir. The CI emulator
/// job writes the config here with `adb shell run-as`; the renderer reads it
/// through `ui_ipc_e2e_should_run` and writes results through `ui_ipc_e2e_record`.
const CONFIG_PATH: &str = "/data/user/0/app.psychologygrowth.desktop/files/ig_uiipc_config.json";
const RESULT_PATH: &str = "/data/user/0/app.psychologygrowth.desktop/files/ig_uiipc_result.json";

fn active() -> bool {
    cfg!(all(debug_assertions, target_os = "android"))
}

#[derive(Deserialize, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct UiIpcE2eConfig {
    pub origin: String,
    pub owner_password: String,
    pub bootstrap_token: String,
    /// sentinel in case CI omits it; driver does not require a stable name
    #[serde(default = "default_device_name")]
    pub device_name: String,
}

fn default_device_name() -> String {
    "android-emulator-uiipc-ci".to_string()
}

/// Called by the WebView renderer on startup. Returns the injected trigger
/// config when the CI emulator job has written it, else None (normal boot).
#[tauri::command]
pub fn ui_ipc_e2e_should_run() -> Result<serde_json::Value, String> {
    if !active() {
        return Ok(serde_json::Value::Null);
    }
    let raw = std::fs::read_to_string(CONFIG_PATH).map_err(|e| format!("read ui-ipc config: {e}"))?;
    let config: UiIpcE2eConfig =
        serde_json::from_str(&raw).map_err(|e| format!("parse ui-ipc config: {e}"))?;
    serde_json::to_value(config).map_err(|e| format!("serialize ui-ipc config: {e}"))
}

/// Append a UI/IPC step result and persist the whole file. The final step uses
/// `step == "final"`; the persisted `result` is PASS iff every step is ok.
#[tauri::command]
pub fn ui_ipc_e2e_record(
    _app: tauri::AppHandle,
    _state: State<'_, DesktopState>,
    step: String,
    ok: bool,
    detail: String,
) -> Result<(), String> {
    if !active() {
        return Ok(());
    }
    let mut events: Vec<serde_json::Value> = Vec::new();
    if let Ok(raw) = std::fs::read_to_string(RESULT_PATH) {
        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&raw) {
            if let Some(arr) = parsed.get("steps").and_then(|v| v.as_array()) {
                events = arr.clone();
            }
        }
    }
    events.push(json!({
        "step": step,
        "ok": ok,
        "detail": detail,
    }));
    let all_ok = events.iter().all(|e| e["ok"] == json!(true));
    let payload = json!({
        "steps": events,
        "result": if all_ok { "PASS" } else { "FAIL" },
    });
    let text = serde_json::to_string_pretty(&payload).unwrap_or_default();
    std::fs::write(RESULT_PATH, text).map_err(|e| format!("write ui-ipc result: {e}"))
}