// Gate C §5 — Runtime mode decision is separate from "is Tauri".
//
// load runtime profile → resolve explicit RuntimeMode → desktop-local ?
// spawn sidecar : never spawn. An existing install without a profile
// defaults to desktop-local so v0.6 behavior (App Data, DB, keyring,
// sidecar, provider settings) is preserved exactly.
//
// The mode is session-immutable: switching the profile only persists the
// NEXT profile and requires an explicit restart. A remote mode must never
// silently fall back to a local Core, because that would present a
// completely different dataset.

use serde::{Deserialize, Serialize};

pub const RUNTIME_PROFILE_FILE: &str = "runtime-profile.json";

pub const RUNTIME_ID_DESKTOP_LOCAL: &str = "desktop-local";
pub const RUNTIME_ID_DESKTOP_REMOTE: &str = "desktop-remote";
pub const RUNTIME_ID_ANDROID_REMOTE: &str = "android-remote";

// Gate E §6.3 — the modes a shell can express. A Tauri desktop shell may be
// desktop-local / desktop-remote. The Android shell only ever expresses
// android-remote (no local Core, no desktop keyring, no sidecar). browser-remote
// is reserved for a future web shell.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RuntimeMode {
    DesktopLocal,
    DesktopRemote,
    AndroidRemote,
}

impl RuntimeMode {
    pub fn as_str(self) -> &'static str {
        match self {
            RuntimeMode::DesktopLocal => RUNTIME_ID_DESKTOP_LOCAL,
            RuntimeMode::DesktopRemote => RUNTIME_ID_DESKTOP_REMOTE,
            RuntimeMode::AndroidRemote => RUNTIME_ID_ANDROID_REMOTE,
        }
    }
}

// Persisted non-secret profile (Gate C §5.2). It only records the intended
// runtime id; it never stores credentials.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeProfile {
    pub runtime_id: String,
}

pub fn is_desktop_runtime_id(value: &str) -> bool {
    value == RUNTIME_ID_DESKTOP_LOCAL || value == RUNTIME_ID_DESKTOP_REMOTE
}

// Existing install without a profile → desktop-local (v0.6 compatibility).
// An explicit desktop-local profile is honored. Anything else (including an
// unrecognized value) resolves to desktop-local and NEVER switches to another
// canonical store.
pub fn parse_runtime_mode(profile: Option<&RuntimeProfile>) -> RuntimeMode {
    match profile {
        None => RuntimeMode::DesktopLocal,
        Some(profile) => match profile.runtime_id.as_str() {
            RUNTIME_ID_DESKTOP_REMOTE => RuntimeMode::DesktopRemote,
            _ => RuntimeMode::DesktopLocal,
        },
    }
}

pub fn should_spawn_sidecar(mode: RuntimeMode) -> bool {
    mode == RuntimeMode::DesktopLocal
}

// Gate R0 §4 — the remote broker's expected runtime, resolved independently of
// local mode. A desktop-local session still owns a RemoteBroker object, but it
// is never reachable while local mode is active (every remote command is gated
// by ensure_remote_mode). So desktop-local uses a default remote runtime that
// is never reachable during the session; only a genuinely remote mode binds
// the broker to its own runtime id.
pub fn broker_expected_runtime_id(mode: RuntimeMode) -> &'static str {
    match mode {
        RuntimeMode::DesktopLocal => RUNTIME_ID_DESKTOP_REMOTE,
        RuntimeMode::DesktopRemote => RUNTIME_ID_DESKTOP_REMOTE,
        RuntimeMode::AndroidRemote => RUNTIME_ID_ANDROID_REMOTE,
    }
}

// Gate E §6.3 — the Android shell is always android-remote: it never spawns a
// Python sidecar, never reads a desktop keyring / local vaults, and never has
// a canonical local DB. This is the only mode the Android host can express.
#[cfg(target_os = "android")]
pub fn android_remote_mode() -> RuntimeMode {
    RuntimeMode::AndroidRemote
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_existing_install_is_desktop_local() {
        assert_eq!(parse_runtime_mode(None), RuntimeMode::DesktopLocal);
        assert!(should_spawn_sidecar(RuntimeMode::DesktopLocal));
    }

    #[test]
    fn explicit_desktop_local_spawns_sidecar() {
        let profile = RuntimeProfile {
            runtime_id: RUNTIME_ID_DESKTOP_LOCAL.into(),
        };
        assert_eq!(parse_runtime_mode(Some(&profile)), RuntimeMode::DesktopLocal);
        assert!(should_spawn_sidecar(RuntimeMode::DesktopLocal));
    }

    #[test]
    fn desktop_remote_never_spawns_sidecar() {
        let profile = RuntimeProfile {
            runtime_id: RUNTIME_ID_DESKTOP_REMOTE.into(),
        };
        assert_eq!(parse_runtime_mode(Some(&profile)), RuntimeMode::DesktopRemote);
        assert!(!should_spawn_sidecar(RuntimeMode::DesktopRemote));
    }

    #[test]
    fn invalid_profile_does_not_silently_switch_store() {
        // Unrecognized / empty values must resolve to the local default and
        // never to a remote canonical store.
        for value in ["", "android-remote", "browser-remote", "garbage", "desktop-remote-extra"] {
            let profile = RuntimeProfile {
                runtime_id: value.into(),
            };
            assert_eq!(parse_runtime_mode(Some(&profile)), RuntimeMode::DesktopLocal);
            assert!(should_spawn_sidecar(RuntimeMode::DesktopLocal));
        }
    }

    #[test]
    fn desktop_runtime_id_validation() {
        assert!(is_desktop_runtime_id(RUNTIME_ID_DESKTOP_LOCAL));
        assert!(is_desktop_runtime_id(RUNTIME_ID_DESKTOP_REMOTE));
        assert!(!is_desktop_runtime_id("android-remote"));
        assert!(!is_desktop_runtime_id("browser-remote"));
        assert!(!is_desktop_runtime_id(""));
    }

    #[test]
    fn android_remote_never_spawns_sidecar() {
        assert_eq!(
            RuntimeMode::AndroidRemote.as_str(),
            RUNTIME_ID_ANDROID_REMOTE
        );
        assert!(!should_spawn_sidecar(RuntimeMode::AndroidRemote));
    }

    // Gate R0 §4 — broker construction must succeed even on a clean default
    // desktop-local startup, while credential-bearing remote commands stay
    // denied. The broker's expected runtime is resolved independently of local
    // mode.
    #[test]
    fn desktop_local_broker_expected_runtime_is_a_remote_runtime() {
        // desktop-local must still yield a valid remote runtime id so
        // RemoteBroker::with_expected_runtime succeeds at setup.
        assert!(crate::remote::is_remote_runtime_id(broker_expected_runtime_id(
            RuntimeMode::DesktopLocal
        )));
        assert_eq!(
            broker_expected_runtime_id(RuntimeMode::DesktopLocal),
            RUNTIME_ID_DESKTOP_REMOTE
        );
    }

    #[test]
    fn desktop_remote_broker_expected_runtime_is_desktop_remote() {
        assert_eq!(
            broker_expected_runtime_id(RuntimeMode::DesktopRemote),
            RUNTIME_ID_DESKTOP_REMOTE
        );
    }

    #[test]
    fn android_remote_broker_expected_runtime_is_android_remote() {
        assert_eq!(
            broker_expected_runtime_id(RuntimeMode::AndroidRemote),
            RUNTIME_ID_ANDROID_REMOTE
        );
    }
}
