// Gate R2 §10.3 / R4 §10 layer-2 — Desktop A native broker harness for the
// true Native cross-device gate.
//
// The cross-device job in release.yml runs, on ONE clean Docker server, BOTH
// a real native desktop-remote broker (this harness) AND a real Android
// emulator native android-remote broker (emulator_e2e.rs). Together they
// prove, with real native brokers (no raw HTTP clients):
//
//   1. Desktop A login/enroll (desktop-remote);
//   2. Android B login/enroll (android-remote);
//   3. A create -> B read exact object (B's expectAQuestion slice);
//   4. B create -> A read exact object (A's expectBQuestion check here);
//   5. device list sees both A and B;
//   6. A revokes B;
//   7. B's refresh / next authenticated mutation is denied (B's
//      expectRevoked slice);
//   8. A unaffected after revoking B;
//   9. B re-enrolls and re-reads A's marker (recovery, B's slice).
//
// Compile-time isolation: this module is `#[cfg(feature =
// "desktop-native-harness")]`-gated and is never part of a default build, so
// it is inert in the shipped desktop and Android release binaries. The binary
// target (`desktop_native_harness`) is likewise `required-features`-gated and
// only built by the CI cross-device job.
#![cfg(feature = "desktop-native-harness")]

use std::path::Path;
use std::sync::Arc;

use base64::Engine;
use serde::Deserialize;
use serde_json::json;

use crate::remote::{
    remote_error, FileCredentialStore, RemoteApiResponse, RemoteBroker, ERR_PROTOCOL,
};

/// The exact runtime this harness runs. The server must advertise
/// `desktop-remote` (Gate R0.3); the Android shell must never borrow it.
const RUNTIME_DESKTOP_REMOTE: &str = "desktop-remote";

/// Default Desktop A device name (serde `default =` path, not a literal).
fn default_device_name() -> String {
    "desktop-native-A".to_string()
}

/// Default Android B device name as enrolled.
fn default_expect_b_device_name() -> String {
    "android-emulator-cross-b".to_string()
}

/// Default enrollment persistence directory (kept stable across phases).
fn default_app_data_dir() -> String {
    "/tmp/ig_harness_app".to_string()
}

/// Default FileCredentialStore path (kept stable across phases).
fn default_store_file() -> String {
    "/tmp/ig_harness_store.json".to_string()
}

#[derive(Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct HarnessConfig {
    /// `a_create` — Desktop A login/enroll + create its marker.
    /// `b_revoke` — A reads B's marker (B->A), device list, revoke B, A
    /// unaffected. Reuses the enrollment + refresh credential persisted by
    /// `a_create` (same appDataDir/storeFile).
    pub phase: String,
    pub origin: String,
    #[serde(rename = "ownerPassword")]
    pub owner_password: String,
    #[serde(rename = "bootstrapToken")]
    pub bootstrap_token: String,
    #[serde(rename = "deviceName", default = "default_device_name")]
    pub device_name: String,
    /// Desktop A's own marker question text (created in `a_create`; asserted
    /// by Android B's expectAQuestion slice).
    #[serde(rename = "createMarker", default)]
    pub create_marker: Option<String>,
    /// Android B's marker question text — A must find it EXACTLY in
    /// `b_revoke` (B->A exact-content cross-read).
    #[serde(rename = "expectBQuestion", default)]
    pub expect_b_question: Option<String>,
    /// Android B's device name as enrolled — used to locate B's device id in
    /// the device list before A revokes it.
    #[serde(rename = "expectBDeviceName", default = "default_expect_b_device_name")]
    pub expect_b_device_name: String,
    /// Directory where the broker persists its (non-secret) enrollment file.
    /// Kept stable across phases so `b_revoke` reuses A's session.
    #[serde(rename = "appDataDir", default = "default_app_data_dir")]
    pub app_data_dir: String,
    /// Path of the FileCredentialStore (refresh credential). Kept stable
    /// across phases so `b_revoke` reuses A's stored refresh credential.
    #[serde(rename = "storeFile", default = "default_store_file")]
    pub store_file: String,
}

/// Run the configured Desktop A phase. `Ok` carries the structured report
/// (steps + result) for CI to print; `Err` carries a coded failure.
pub(crate) async fn run_harness(config: HarnessConfig) -> Result<serde_json::Value, String> {
    let store = FileCredentialStore::new(&config.store_file);
    let broker = RemoteBroker::with_expected_runtime(Arc::new(store), RUNTIME_DESKTOP_REMOTE)
        .map_err(|error| format!("cannot build desktop native broker: {error}"))?;
    let app_data = Path::new(&config.app_data_dir);
    match config.phase.as_str() {
        "a_create" => run_a_create(&broker, app_data, &config).await,
        "b_revoke" => run_b_revoke(&broker, app_data, &config).await,
        other => Err(remote_error(
            ERR_PROTOCOL,
            format!("unknown harness phase: {other}"),
        )),
    }
}

/// Accumulator that mirrors emulator_e2e.rs's result-file contract: every step
/// is a JSON entry and the final result is PASS only when all steps are OK.
struct HarnessRun {
    steps: Vec<serde_json::Value>,
}

impl HarnessRun {
    fn new() -> Self {
        Self { steps: Vec::new() }
    }

    fn record(&mut self, step: &str, ok: bool, detail: impl AsRef<str>) {
        self.steps.push(json!({
            "step": step,
            "ok": ok,
            "detail": detail.as_ref(),
        }));
    }

    fn record_result(&mut self, step: &str, res: Result<(), String>) {
        match res {
            Ok(()) => self.record(step, true, "ok"),
            Err(e) => self.record(step, false, e),
        }
    }

    fn finish(self) -> serde_json::Value {
        let all_ok = self.steps.iter().all(|e| e["ok"] == json!(true));
        json!({
            "steps": self.steps,
            "result": if all_ok { "PASS" } else { "FAIL" },
        })
    }
}

fn decode_body(resp: &RemoteApiResponse) -> serde_json::Value {
    base64::engine::general_purpose::STANDARD
        .decode(&resp.body_base64)
        .ok()
        .and_then(|bytes| String::from_utf8(bytes).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

/// Find a question object whose `question` field equals EXACTLY `expected`.
/// `GET /api/questions` returns `{"questions": [...]}` (frozen contract); a
/// fuzzy substring match is never accepted for the cross-device proof.
fn find_question_by_text(payload: &serde_json::Value, expected: &str) -> Option<serde_json::Value> {
    let items = payload.get("questions").and_then(|value| value.as_array())?;
    items
        .iter()
        .find(|item| item.get("question").and_then(|value| value.as_str()) == Some(expected))
        .cloned()
}

/// Phase `a_create`: probe -> bootstrap (if fresh) -> login/enroll -> create
/// Desktop A's marker. Persists enrollment + refresh credential for the later
/// `b_revoke` phase.
async fn run_a_create(
    broker: &RemoteBroker,
    app_data: &Path,
    config: &HarnessConfig,
) -> Result<serde_json::Value, String> {
    let mut run = HarnessRun::new();

    // 1. Real probe for the EXACT runtime this native broker runs.
    let probe = broker
        .probe_for_runtime(&config.origin, RUNTIME_DESKTOP_REMOTE)
        .await
        .map_err(|e| format!("probe failed: {e}"))?;
    run.record(
        "probe",
        true,
        format!("runtime=desktop-remote origin={}", probe.normalized_origin),
    );

    // 2. Bootstrap a fresh owner only when the server has none.
    if probe.server.owner_configured {
        run.record("bootstrap_owner", true, "owner already configured; using existing owner");
    } else {
        run.record_result(
            "bootstrap_owner",
            broker
                .bootstrap_owner(&config.origin, &config.owner_password, &config.bootstrap_token)
                .await
                .map(|_| ()),
        );
    }

    // 3. Login/enroll as Desktop A (writes refresh credential to the
    //    FileCredentialStore and persists the enrollment file).
    let login = broker
        .login(
            app_data,
            &config.origin,
            &config.owner_password,
            &config.device_name,
            "desktop",
            "",
        )
        .await
        .map_err(|e| format!("login failed: {e}"))?;
    run.record(
        "login",
        true,
        format!(
            "device={} server={} api={} refresh_stored={}",
            login.device_id, login.server_instance_id, login.api_version, login.refresh_stored
        ),
    );

    // 4. Create Desktop A's marker question — the object Android B must read
    //    by exact content in its expectAQuestion slice.
    let marker = config
        .create_marker
        .clone()
        .unwrap_or_else(|| "desktop-native-A authored".to_string());
    let create = broker
        .api_request(
            app_data,
            "/api/questions",
            "POST",
            Some((
                "application/json".to_string(),
                json!({ "question": marker, "interest_level": 3 })
                    .to_string()
                    .into_bytes(),
            )),
            &Default::default(),
        )
        .await?;
    if create.status != 200 && create.status != 201 {
        return Err(remote_error(
            ERR_PROTOCOL,
            format!("create marker returned status {}", create.status),
        ));
    }
    let created_id = decode_body(&create)
        .get("id")
        .cloned()
        .unwrap_or_else(|| json!("?"));
    run.record(
        "api_post_question",
        true,
        format!("status={} id={created_id} marker={marker:?}", create.status),
    );

    Ok(run.finish())
}

/// Phase `b_revoke`: reuses Desktop A's persisted enrollment + refresh
/// credential (no re-login) to:
///   1. read Android B's marker by EXACT content (B->A cross-read);
///   2. list devices and assert both A and B are present;
///   3. revoke B;
///   4. confirm A is unaffected (still reads canonical state);
///   5. confirm the server records B as revoked.
async fn run_b_revoke(
    broker: &RemoteBroker,
    app_data: &Path,
    config: &HarnessConfig,
) -> Result<serde_json::Value, String> {
    let mut run = HarnessRun::new();

    // 1. B -> A exact-content cross-read.
    let expected = config
        .expect_b_question
        .clone()
        .ok_or_else(|| remote_error(ERR_PROTOCOL, "b_revoke requires expectBQuestion"))?;
    let read = broker
        .api_request(app_data, "/api/questions", "GET", None, &Default::default())
        .await
        .map_err(|e| format!("GET /api/questions failed: {e}"))?;
    if read.status != 200 {
        return Err(remote_error(
            ERR_PROTOCOL,
            format!("GET /api/questions returned status {}", read.status),
        ));
    }
    let payload = decode_body(&read);
    match find_question_by_text(&payload, &expected) {
        Some(found) => {
            let id = found.get("id").cloned().unwrap_or_else(|| json!("?"));
            run.record("cross_read_b_question", true, format!("found id={id} question={expected:?}"));
        }
        None => {
            return Err(remote_error(
                ERR_PROTOCOL,
                format!("A cannot read B's exact question {expected:?}; payload={payload}"),
            ));
        }
    }

    // 2. Device list: both A and B present; capture B's device id.
    let devs = broker
        .api_request(app_data, "/api/auth/devices", "GET", None, &Default::default())
        .await
        .map_err(|e| format!("GET /api/auth/devices failed: {e}"))?;
    if devs.status != 200 {
        return Err(remote_error(
            ERR_PROTOCOL,
            format!("GET /api/auth/devices returned status {}", devs.status),
        ));
    }
    let dev_payload = decode_body(&devs);
    let devices = dev_payload
        .get("devices")
        .and_then(|value| value.as_array())
        .ok_or_else(|| remote_error(ERR_PROTOCOL, "device list has no `devices` array"))?;
    let has_a = devices
        .iter()
        .any(|d| d.get("name").and_then(|v| v.as_str()) == Some(config.device_name.as_str()));
    let device_b = devices
        .iter()
        .find(|d| d.get("name").and_then(|v| v.as_str()) == Some(config.expect_b_device_name.as_str()))
        .cloned();
    if !has_a {
        return Err(remote_error(
            ERR_PROTOCOL,
            format!("device list does not contain Desktop A {}", config.device_name),
        ));
    }
    let device_b = device_b.ok_or_else(|| {
        remote_error(
            ERR_PROTOCOL,
            format!("device list does not contain Android B {}", config.expect_b_device_name),
        )
    })?;
    let b_id = device_b
        .get("id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| remote_error(ERR_PROTOCOL, "Android B device has no id"))?
        .to_string();
    run.record(
        "device_list_both_present",
        true,
        format!("A={} B={} (id={b_id})", config.device_name, config.expect_b_device_name),
    );

    // 3. A revokes B (different device -> owner password required by the
    //    server; the real owner password is supplied).
    let revoke = broker
        .api_request(
            app_data,
            "/api/auth/device/revoke",
            "POST",
            Some((
                "application/json".to_string(),
                json!({ "device_id": b_id, "owner_password": config.owner_password })
                    .to_string()
                    .into_bytes(),
            )),
            &Default::default(),
        )
        .await
        .map_err(|e| format!("revoke B failed: {e}"))?;
    if revoke.status != 200 {
        return Err(remote_error(
            ERR_PROTOCOL,
            format!("revoke B returned status {}", revoke.status),
        ));
    }
    run.record("revoke_b", true, format!("device={b_id}"));

    // 4. A unaffected: A still reads canonical state after revoking B.
    let after = broker
        .api_request(app_data, "/api/questions", "GET", None, &Default::default())
        .await
        .map_err(|e| format!("A re-read after revoke failed: {e}"))?;
    if after.status != 200 {
        return Err(remote_error(
            ERR_PROTOCOL,
            format!("A affected by revoking B: status {}", after.status),
        ));
    }
    run.record("a_unaffected", true, "A still reads canonical state after revoking B");

    // 5. Server-side proof: B is recorded as revoked in the device list.
    let devs2 = broker
        .api_request(app_data, "/api/auth/devices", "GET", None, &Default::default())
        .await
        .map_err(|e| format!("re-read device list failed: {e}"))?;
    let dev2 = decode_body(&devs2);
    let b_revoked = dev2
        .get("devices")
        .and_then(|value| value.as_array())
        .and_then(|items| {
            items
                .iter()
                .find(|d| d.get("id").and_then(|v| v.as_str()) == Some(b_id.as_str()))
        })
        .and_then(|d| d.get("revoked_at"))
        .map(|v| !v.is_null())
        .unwrap_or(false);
    if !b_revoked {
        return Err(remote_error(
            ERR_PROTOCOL,
            format!("server did not record B ({b_id}) as revoked"),
        ));
    }
    run.record("b_revoked_server_side", true, format!("device={b_id}"));

    Ok(run.finish())
}
