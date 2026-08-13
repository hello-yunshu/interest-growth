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

// The only modes a Tauri desktop shell can express in Gate C. android-remote
// / browser-remote are future runtimes for other shells and are not
// expressible here.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RuntimeMode {
    DesktopLocal,
    DesktopRemote,
}

impl RuntimeMode {
    pub fn as_str(self) -> &'static str {
        match self {
            RuntimeMode::DesktopLocal => RUNTIME_ID_DESKTOP_LOCAL,
            RuntimeMode::DesktopRemote => RUNTIME_ID_DESKTOP_REMOTE,
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
}
