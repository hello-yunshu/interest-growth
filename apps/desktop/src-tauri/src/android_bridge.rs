// Gate R0.5 / R0.6 — native SAF bridge between Rust and the Android
// `InterestGrowthPlugin` (Kotlin).
//
// The renderer only passes a content URI, filename, MIME type and size; the
// actual file bytes are read (upload) and written (export) in the native
// layer, so a 100 MiB file never becomes a renderer base64 copy (Gate R0.5)
// and an exported artifact is streamed through the native broker into SAF
// (Gate R0.6).
//
// The Kotlin plugin is registered from Rust via `register_android_plugin`
// during app setup and its handle is kept in Tauri state. Every command is
// dispatched through `run_mobile_plugin_async` — the renderer never talks to
// Kotlin directly and never receives the raw file bytes.
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Runtime};

#[cfg(target_os = "android")]
use tauri::{plugin::PluginHandle, Manager};

/// Bytes read from a SAF content URI (base64 so it crosses the JNI boundary
/// as a string), plus the metadata the renderer is allowed to see.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContentUriPayload {
    pub base64: String,
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

/// Read a SAF content URI natively (Kotlin → base64 → Rust). The renderer
/// only ever supplies the URI string (Gate R0.5).
#[cfg(target_os = "android")]
pub async fn read_content_uri(app: &AppHandle, uri: &str) -> Result<ContentUriPayload, String> {
    invoke_android(app, "readContentUri", serde_json::json!({ "uri": uri })).await
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

/// Open the SAF ACTION_CREATE_DOCUMENT picker and write the base64 content to
/// the user-selected location (Gate R0.6).
#[cfg(target_os = "android")]
pub async fn save_document(
    app: &AppHandle,
    filename: &str,
    mime_type: &str,
    content_base64: &str,
) -> Result<SavedDocument, String> {
    invoke_android(
        app,
        "saveDocument",
        serde_json::json!({
            "contentBase64": content_base64,
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
pub async fn read_content_uri(_app: &AppHandle, _uri: &str) -> Result<ContentUriPayload, String> {
    Err("SAF content URI reads are only available on the Android build".into())
}

#[cfg(not(target_os = "android"))]
pub async fn pick_document(
    _app: &AppHandle,
    _mime_type: Option<String>,
) -> Result<PickedDocument, String> {
    Err("the SAF document picker is only available on the Android build".into())
}

#[cfg(not(target_os = "android"))]
pub async fn save_document(
    _app: &AppHandle,
    _filename: &str,
    _mime_type: &str,
    _content_base64: &str,
) -> Result<SavedDocument, String> {
    Err("SAF document writes are only available on the Android build".into())
}
