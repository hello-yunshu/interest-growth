// Gate R0.5 / R0.6 — native SAF bridge between Rust and the Android
// `InterestGrowthPlugin` (Kotlin).
//
// The renderer only passes a content URI, filename, MIME type and size; the
// actual file BYTES never cross the renderer. Gate R0.5/R0.6 make the native
// path genuinely bounded/streaming by staging through a bounded app-private
// temp file instead of a full base64 String:
//
//   * upload  — Kotlin streams the SAF content URI into a bounded app-private
//               cache file (enforcing the product limit during the copy),
//               Rust streams that file as the multipart body, then the temp
//               file is cleaned up. The whole file never exists as a Kotlin
//               ByteArray + base64 String + Rust Vec simultaneously.
//   * export  — Rust streams the HTTP response into a bounded app-private temp
//               file, Kotlin copies that file into the SAF ACTION_CREATE_DOCUMENT
//               output stream, then the temp file is cleaned up.
//
// The Kotlin plugin is registered from Rust via `register_android_plugin`
// during app setup and its handle is kept in Tauri state. Every command is
// dispatched through `run_mobile_plugin_async` — the renderer never talks to
// Kotlin directly and never receives the raw file bytes.
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Runtime};

#[cfg(target_os = "android")]
use tauri::{plugin::PluginHandle, Manager};

/// A bounded app-private temp file staged from a SAF content URI. Only the
/// path + metadata reach Rust; the bytes live on disk, not in memory.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StagedUpload {
    pub path: String,
    pub name: String,
    pub size: i64,
    pub mime_type: String,
}

/// Result of the SAF document picker: only a content URI and metadata, never
/// file bytes.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PickedDocument {
    pub uri: String,
    pub name: String,
    pub size: i64,
    pub mime_type: String,
}

/// Result of writing a document through SAF (user-selected location).
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SavedDocument {
    pub uri: String,
    pub size: i64,
}

/// Holds the registered Android plugin handle so native commands can invoke
/// Kotlin (SAF) without re-resolving the plugin per call.
#[cfg(target_os = "android")]
#[derive(Clone)]
pub struct AndroidBridge(pub PluginHandle<tauri::Wry>);

/// Registers the InterestGrowthPlugin on Android. On desktop this is a no-op
/// plugin so the crate compiles everywhere while keeping the mobile entry
/// point's plugin wiring identical.
///
/// Note: this is deliberately NOT generic on Android. `register_android_plugin`
/// drives `run_on_android_context`, which only exists on the concrete Wry
/// mobile runtime, so `R` is pinned to `tauri::Wry` and the returned plugin is
/// `TauriPlugin<tauri::Wry>` — not the generic `TauriPlugin<R>`.
#[cfg(target_os = "android")]
pub fn init() -> tauri::plugin::TauriPlugin<tauri::Wry> {
    tauri::plugin::Builder::new("interest-growth-plugin")
        .setup(|app, api| {
            let handle = api.register_android_plugin(
                "app.psychologygrowth.desktop",
                "InterestGrowthPlugin",
            )?;
            app.manage(AndroidBridge(handle));
            Ok(())
        })
        .build()
}

#[cfg(not(target_os = "android"))]
pub fn init<R: Runtime>() -> tauri::plugin::TauriPlugin<R> {
    tauri::plugin::Builder::new("interest-growth-plugin").build()
}

#[cfg(target_os = "android")]
async fn invoke_android<T: serde::de::DeserializeOwned>(
    app: &AppHandle,
    command: &str,
    payload: serde_json::Value,
) -> Result<T, String> {
    let bridge = app.state::<AndroidBridge>();
    bridge
        .0
        .run_mobile_plugin_async(command, payload)
        .await
        .map_err(|error| format!("android {command} failed: {error}"))
}

/// Stage a SAF content URI into a bounded app-private cache file (Kotlin).
/// The copy is aborted if `max_bytes` is exceeded, so the file is never read
/// into memory unbounded. Returns the staged file path + metadata (Gate R0.5).
#[cfg(target_os = "android")]
pub async fn stage_upload(
    app: &AppHandle,
    uri: &str,
    max_bytes: u64,
) -> Result<StagedUpload, String> {
    invoke_android(
        app,
        "stageContentUri",
        serde_json::json!({ "uri": uri, "maxBytes": max_bytes }),
    )
    .await
}

/// Open the SAF ACTION_OPEN_DOCUMENT picker and return the selected content
/// URI plus metadata (Gate R0.5).
#[cfg(target_os = "android")]
pub async fn pick_document(
    app: &AppHandle,
    mime_type: Option<String>,
) -> Result<PickedDocument, String> {
    invoke_android(app, "pickDocument", serde_json::json!({ "mimeType": mime_type })).await
}

/// Open the SAF ACTION_CREATE_DOCUMENT picker and copy a bounded app-private
/// temp file into the user-selected location (Gate R0.6). The source file is
/// read in bounded chunks and written to the output stream; it is never
/// materialised as a base64 payload on the plugin.
#[cfg(target_os = "android")]
pub async fn save_document_from_file(
    app: &AppHandle,
    source_path: &str,
    filename: &str,
    mime_type: &str,
) -> Result<SavedDocument, String> {
    invoke_android(
        app,
        "saveDocumentFromFile",
        serde_json::json!({
            "sourcePath": source_path,
            "filename": filename,
            "mimeType": mime_type,
        }),
    )
    .await
}

// Desktop stubs — the SAF bridge is Android-only. The commands stay
// registered on every platform (the invoke_handler is shared) but they reject
// cleanly instead of pretending to exist on desktop, which keeps the desktop
// export path (native save dialog) the only desktop export surface.
#[cfg(not(target_os = "android"))]
pub async fn stage_upload(
    _app: &AppHandle,
    _uri: &str,
    _max_bytes: u64,
) -> Result<StagedUpload, String> {
    Err("SAF content URI staging is only available on the Android build".into())
}

#[cfg(not(target_os = "android"))]
pub async fn pick_document(
    _app: &AppHandle,
    _mime_type: Option<String>,
) -> Result<PickedDocument, String> {
    Err("the SAF document picker is only available on the Android build".into())
}

#[cfg(not(target_os = "android"))]
pub async fn save_document_from_file(
    _app: &AppHandle,
    _source_path: &str,
    _filename: &str,
    _mime_type: &str,
) -> Result<SavedDocument, String> {
    Err("SAF document writes are only available on the Android build".into())
}