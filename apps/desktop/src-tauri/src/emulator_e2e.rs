// Gate R2 §10.2 — Android-emulator real remote vertical slice.
//
// This module is compiled in ONLY for debug builds (`cfg(debug_assertions)`)
// and is inert in release artifacts. It lets the remote GitHub-hosted Android
// emulator drive the REAL native remote broker end-to-end against a real
// self-hosted server that the emulator job boots and reaches via `adb reverse`
// (so the enrollment origin stays a loopback URL, matching the contract).
//
// Trigger contract (no WebView / JS / IPC involved):
//   1. CI writes a config file into the app-private `files/` dir:
//        adb shell run-as <pkg> sh -c 'cat > files/ig_e2e_config.json'
//      The file is JSON:
//        {
//          "origin":         "http://127.0.0.1:18080",
//          "ownerPassword":  "...",
//          "bootstrapToken": "...",
//          "deviceName":     "android-emulator-ci"
//        }
//   2. CI launches MainActivity (`am start`). On setup this module reads the
//      config (if present) and spawns a background task that runs the slice.
//   3. Every step writes an entry to the result file `files/ig_e2e_result.json`
//      and the final line records PASS/FAIL. CI polls that file via
//      `adb shell run-as <pkg> cat files/ig_e2e_result.json`.
//
// The slice exercises the same broker methods the production commands call:
// probe → bootstrap owner → login → authenticated GET → mutation (create a
// question) → forced refresh → logout(revoke). All of it goes over real HTTP
// to the emulator-host loopback server, so it is a genuine remote vertical
// slice, not a mock.
//
// Compile-time isolation: the `#[cfg(debug_assertions)]` gate means the
// trigger file is never read in a release build, and the module is not part
// of the release crate graph. No authorization bypass is exposed.
#![cfg(debug_assertions)]

use std::path::Path;

use serde::Deserialize;
use serde_json::json;
use base64::Engine;

use crate::remote::{RemoteBroker, RemoteApiResponse};

/// Loopback-only marker path inside the app-private files dir. The CI emulator
/// job writes the config here with `adb shell run-as`; the app reads the same
/// absolute path. Only meaningful in debug builds.
fn config_path() -> std::path::PathBuf {
    Path::new("/data/user/0/app.psychologygrowth.desktop/files/ig_e2e_config.json").to_path_buf()
}

fn result_path() -> std::path::PathBuf {
    Path::new("/data/user/0/app.psychologygrowth.desktop/files/ig_e2e_result.json").to_path_buf()
}

#[derive(Deserialize, Clone)]
struct EmulatorE2EConfig {
    origin: String,
    #[serde(rename = "ownerPassword")]
    owner_password: String,
    #[serde(rename = "bootstrapToken")]
    bootstrap_token: String,
    #[serde(rename = "deviceName", default = "default_device")]
    device_name: String,
    // ---- R4 §10 layer-2 cross-device extension (all optional) ----
    /// When set, the slice asserts (after login) that GET /questions returns
    /// an object whose `question` equals this EXACT text — the object Desktop
    /// A (native desktop-remote broker) created on the same server. Proves the
    /// A -> B cross-device read with the real Android native broker, by exact
    /// content (id comes from the meta record below).
    #[serde(rename = "expectAQuestion", default)]
    expect_a_question: Option<String>,
    /// The slice's own create marker. Recorded in the result meta so Desktop A
    /// can assert B -> A by exact id.
    #[serde(rename = "createMarker", default)]
    create_marker: Option<String>,
    /// When true the final self logout/revoke is skipped so the device stays
    /// active — required for the "A revokes B, B denied" isolation proof.
    #[serde(rename = "keepDevice", default)]
    keep_device: bool,
    /// When true the slice does NOT re-login; it attempts an authenticated
    /// mutation with the stored enrollment + stored refresh credential and
    /// asserts the server DENIES it (A already revoked this device).
    #[serde(rename = "expectRevoked", default)]
    expect_revoked: bool,
}

fn default_device() -> String {
    "android-emulator-ci".to_string()
}

/// Read the trigger config if present. Returns None when the marker file does
/// not exist (the normal case) — callers must not treat that as a failure.
fn read_config() -> Option<EmulatorE2EConfig> {
    let raw = std::fs::read_to_string(config_path()).ok()?;
    serde_json::from_str(&raw).ok()
}

/// Append a structured result entry and persist it. The CI job reads this file
/// to decide PASS/FAIL, so each entry is atomic-enough (rewrite wholly).
fn record<S: AsRef<str>>(step: &str, ok: bool, detail: S) {
    let mut events: Vec<serde_json::Value> = Vec::new();
    if let Ok(raw) = std::fs::read_to_string(result_path()) {
        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&raw) {
            if let Some(arr) = parsed.get("steps").and_then(|v| v.as_array()) {
                events = arr.clone();
            }
        }
    }
    events.push(json!({
        "step": step,
        "ok": ok,
        "detail": detail.as_ref(),
    }));
    let all_ok = events.iter().all(|e| e["ok"] == json!(true));
    let payload = json!({
        "steps": events,
        "result": if all_ok { "PASS" } else { "FAIL" },
    });
    let _ = std::fs::write(result_path(), serde_json::to_string_pretty(&payload).unwrap_or_default());
    // Also mirror to stdout so `adb logcat` / `adb shell` can observe progress.
    println!("[ig-e2e] step={step} ok={ok} result={} detail={}", if all_ok { "PASS" } else { "FAIL" }, detail.as_ref());
}

/// Decode a broker response body (base64) into a JSON value. A body that is
/// not valid JSON degrades to `Value::Null` — callers then fail their step.
fn decode_body(resp: &RemoteApiResponse) -> serde_json::Value {
    base64::engine::general_purpose::STANDARD
        .decode(&resp.body_base64)
        .ok()
        .and_then(|bytes| String::from_utf8(bytes).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

/// Find a question object whose `question` field equals EXACTLY `expected`.
/// `GET /questions` returns `{"questions": [...]}` (frozen contract). A fuzzy
/// substring match is never accepted: the cross-device proof must be exact.
fn find_question_by_text(payload: &serde_json::Value, expected: &str) -> Option<serde_json::Value> {
    let items = payload.get("questions").and_then(|value| value.as_array())?;
    items
        .iter()
        .find(|item| item.get("question").and_then(|value| value.as_str()) == Some(expected))
        .cloned()
}

/// Run the vertical slice against the real broker. Returns WITHOUT error when
/// there is no trigger config (normal app boot). Panics/errors are converted
/// into a FAIL result entry so CI sees a deterministic outcome.
pub async fn maybe_run_emulator_e2e(broker: RemoteBroker, app_data: std::path::PathBuf) {
    let Some(config) = read_config() else {
        // No trigger file — this is a normal app boot. Nothing to do.
        return;
    };

    // Reset any previous result file for a clean run.
    let _ = std::fs::remove_file(result_path());

    let verify = |step: &str, res: Result<(), String>| {
        match res {
            Ok(()) => record(step, true, "ok"),
            Err(e) => record(step, false, e),
        }
    };

    // R4 §10 layer-2 — the revoke-isolation slice. This runs as a SECOND app
    // launch after Desktop A already revoked this device: the persisted
    // enrollment + stored refresh credential must be DENIED on an
    // authenticated mutation (no re-login). The slice then proves recovery by
    // re-enrolling (fresh login) and re-reading Desktop A's marker.
    if config.expect_revoked {
        run_expect_revoked_slice(&broker, &app_data, &config, &verify).await;
        let raw = std::fs::read_to_string(result_path()).unwrap_or_default();
        let pass = raw.contains("\"result\": \"PASS\"");
        println!("[ig-e2e] FINAL RESULT={}", if pass { "PASS" } else { "FAIL" });
        return;
    }

    // 1. Probe for the EXACT runtime the Android client runs (android-remote).
    let probe = broker.probe_for_runtime(&config.origin, "android-remote").await;
    let server = match probe {
        Ok(p) => {
            record("probe", true, format!("runtime=android-remote origin={}", p.normalized_origin));
            p.server
        }
        Err(e) => {
            record("probe", false, e);
            return;
        }
    };

    // 2. Bootstrap a fresh owner (only valid when the server has no owner).
    if !server.owner_configured {
        verify(
            "bootstrap_owner",
            broker
                .bootstrap_owner(&config.origin, &config.owner_password, &config.bootstrap_token)
                .await
                .map(|_| ()),
        );
    } else {
        record("bootstrap_owner", true, "owner already configured; using existing owner");
    }

    // 3. Login as the owner (writes the refresh credential to the OS keyring).
    let login = broker
        .login(
            &app_data,
            &config.origin,
            &config.owner_password,
            &config.device_name,
            "android",
            "",
        )
        .await;
    match login {
        Ok(l) => record(
            "login",
            true,
            format!(
                "device={} server={} api={} refresh_stored={}",
                l.device_id, l.server_instance_id, l.api_version, l.refresh_stored
            ),
        ),
        Err(e) => {
            record("login", false, e);
            return;
        }
    }

    // 4. Authenticated GET (dashboard/capabilities) through the native broker.
    let get = broker
        .api_request(&app_data, "/api/system/capabilities", "GET", None, &Default::default())
        .await;
    match get {
        Ok(RemoteApiResponse { status, .. }) if status == 200 => {
            record("api_get", true, format!("status={status}"))
        }
        Ok(RemoteApiResponse { status, .. }) => {
            record("api_get", false, format!("unexpected status={status}"));
            return;
        }
        Err(e) => {
            record("api_get", false, e);
            return;
        }
    }

    // 5. Mutation through the native broker — create a representative object
    //    (a question) so the slice proves authenticated writes, not just reads.
    //    R4 §10 layer-2: when `createMarker` is set, the created object uses
    //    that EXACT text so Desktop A (native desktop-remote broker) can find
    //    this device's object by exact content on the same server.
    let marker = config
        .create_marker
        .clone()
        .unwrap_or_else(|| "emulator e2e hole".to_string());
    let create = broker
        .api_request(
            &app_data,
            "/api/questions",
            "POST",
            Some((
                "application/json".to_string(),
                json!({ "question": marker, "interest_level": 3 }).to_string().into_bytes(),
            )),
            &Default::default(),
        )
        .await;
    match create {
        Ok(RemoteApiResponse { status, body_base64, .. }) if status == 200 || status == 201 => {
            let body = base64::engine::general_purpose::STANDARD
                .decode(&body_base64)
                .ok()
                .and_then(|b| String::from_utf8(b).ok())
                .unwrap_or_default();
            let created_id = serde_json::from_str::<serde_json::Value>(&body)
                .ok()
                .and_then(|v| v.get("id").cloned())
                .unwrap_or_else(|| json!("?"));
            record(
                "api_post_question",
                true,
                format!("status={status} id={created_id} marker={marker:?}"),
            );
        }
        Ok(RemoteApiResponse { status, .. }) => {
            record("api_post_question", false, format!("unexpected status={status}"));
            return;
        }
        Err(e) => {
            record("api_post_question", false, e);
            return;
        }
    }

    // 5.5. R4 §10 layer-2 — when `expectAQuestion` is set, assert that GET
    //      /questions returns the EXACT object that Desktop A created on this
    //      same server (native desktop-remote broker -> native Android broker
    //      cross-device read, by exact content).
    if let Some(expected) = config.expect_a_question.as_deref() {
        let read = broker
            .api_request(&app_data, "/api/questions", "GET", None, &Default::default())
            .await;
        let payload = match &read {
            Ok(resp) if resp.status == 200 => decode_body(resp),
            Ok(resp) => {
                record("expect_a_question", false, format!("unexpected status={}", resp.status));
                return;
            }
            Err(e) => {
                record("expect_a_question", false, e);
                return;
            }
        };
        match find_question_by_text(&payload, expected) {
            Some(found) => {
                let id = found.get("id").cloned().unwrap_or_else(|| json!("?"));
                record("expect_a_question", true, format!("found id={id} question={expected:?}"));
            }
            None => {
                record(
                    "expect_a_question",
                    false,
                    format!("GET /questions lacks exact question {expected:?}; payload={payload}"),
                );
                return;
            }
        }
    }

    // 6. Forced refresh cycle (proves the refresh credential round-trips).
    verify("refresh", broker.refresh_now(&app_data).await.map(|_| ()));

    // 7. Logout with revoke — the server-side device is revoked. R4 §10
    //    layer-2: `keepDevice` keeps the device ACTIVE (no self-revoke) so a
    //    LATER slice can prove that Desktop A's revoke of THIS device is what
    //    denies its next mutation (isolation proof), instead of the device
    //    having revoked itself.
    if config.keep_device {
        record("logout_revoke", true, "skipped (keepDevice): device stays active for revoke-isolation");
    } else {
        verify("logout_revoke", broker.logout(&app_data, true).await.map(|_| ()));
    }

    // Final summary line echoed for CI.
    let raw = std::fs::read_to_string(result_path()).unwrap_or_default();
    let pass = raw.contains("\"result\": \"PASS\"");
    println!("[ig-e2e] FINAL RESULT={}", if pass { "PASS" } else { "FAIL" });
}

/// R4 §10 layer-2 — revoke-isolation + recovery slice. Runs as a SECOND app
/// launch AFTER Desktop A (native desktop-remote broker) has revoked this
/// device. The slice:
///   1. attempts an authenticated mutation using ONLY the persisted enrollment
///      + stored refresh credential (no re-login, no fresh probe) and asserts
///      the server DENIES it — the device was revoked, not logged out by self;
///   2. re-enrolls with a fresh login (recovery path);
///   3. re-reads Desktop A's marker question by exact content (cross-read after
///      recovery).
async fn run_expect_revoked_slice(
    broker: &RemoteBroker,
    app_data: &std::path::Path,
    config: &EmulatorE2EConfig,
    verify: &(dyn Fn(&str, Result<(), String>) + Sync),
) {
    // 1. Authenticated mutation with stored credentials — must be DENIED.
    //    The broker performs the refresh with the stored credential and the
    //    server (A already revoked this device) must refuse it. A hard Err is
    //    the denial; an Ok(401/403) is also a denial; any 2xx is a FAIL.
    let denied = broker
        .api_request(
            app_data,
            "/api/questions",
            "POST",
            Some((
                "application/json".to_string(),
                json!({ "question": "should never persist", "interest_level": 3 })
                    .to_string()
                    .into_bytes(),
            )),
            &Default::default(),
        )
        .await;
    match denied {
        Err(e) => record("revoked_mutation_denied", true, format!("denied: {e}")),
        Ok(RemoteApiResponse { status, .. }) if status == 401 || status == 403 => {
            record("revoked_mutation_denied", true, format!("denied: status={status}"))
        }
        Ok(RemoteApiResponse { status, .. }) => {
            record(
                "revoked_mutation_denied",
                false,
                format!("revoked device mutation was ACCEPTED (status={status})"),
            );
            return;
        }
    }

    // 2. Recovery: re-enroll with a fresh login. The revoked device identity
    //    may be replaced by the server; the slice accepts a fresh device.
    let login = broker
        .login(
            app_data,
            &config.origin,
            &config.owner_password,
            &config.device_name,
            "android",
            "",
        )
        .await;
    match login {
        Ok(l) => record(
            "re_enroll",
            true,
            format!("device={} server={} api={}", l.device_id, l.server_instance_id, l.api_version),
        ),
        Err(e) => {
            record("re_enroll", false, e);
            return;
        }
    }

    // 3. Re-read Desktop A's marker by EXACT content (cross-read after
    //    recovery). This also proves the server canonical state survived A's
    //    revoke of the previous device identity.
    if let Some(expected) = config.expect_a_question.as_deref() {
        let read = broker
            .api_request(app_data, "/api/questions", "GET", None, &Default::default())
            .await;
        let payload = match &read {
            Ok(resp) if resp.status == 200 => decode_body(resp),
            Ok(resp) => {
                record("expect_a_question_after_recover", false, format!("unexpected status={}", resp.status));
                return;
            }
            Err(e) => {
                record("expect_a_question_after_recover", false, e);
                return;
            }
        };
        match find_question_by_text(&payload, expected) {
            Some(found) => {
                let id = found.get("id").cloned().unwrap_or_else(|| json!("?"));
                record(
                    "expect_a_question_after_recover",
                    true,
                    format!("found id={id} question={expected:?}"),
                );
            }
            None => {
                record(
                    "expect_a_question_after_recover",
                    false,
                    format!("recovered read lacks exact question {expected:?}; payload={payload}"),
                );
            }
        }
    } else {
        record("expect_a_question_after_recover", true, "no expectAQuestion configured");
    }

    let _ = verify;
}