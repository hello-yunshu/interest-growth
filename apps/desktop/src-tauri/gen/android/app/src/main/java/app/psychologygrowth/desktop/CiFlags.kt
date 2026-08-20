// Phase 4c — build-time CI capability flag for the x86_64 RELEASE-test APK.
//
// This is a SOURCE flag, read by MainActivity. It is compiled into the APK, so
// it is NOT subject to `tauri android build` regeneration of gradle/build files.
//
//   * The committed default is `false`: the published production APK (arm64
//     release) and normal builds never enable WebView remote debugging.
//   * CI writes `true` here ONLY when producing the x86_64 release-test APK
//     used by the upgrade-in-place emulator job (see release.yml). That APK:
//       - stays NON-debuggable (android:debuggable=false, checked by
//         verify_upgrade_apk_pair.sh),
//       - is an INTERNAL TEST ARTIFACT — never published, never in the formal
//         final SHA256SUMS,
//       - enables WebView remote debugging purely so a black-box CDP driver can
//         drive the real Renderer -> ClientRuntime -> Tauri invoke -> Rust
//         RemoteBroker enrollment path instead of `run-as` config injection
//         (prompt §11 — display DebuggingEnabled risk is confined to this
//         throwaway artifact).
object CiFlags {
  const val ENABLE_WEBVIEW_REMOTE_DEBUGGING: Boolean = true
}