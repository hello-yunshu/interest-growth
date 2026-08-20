package app.psychologygrowth.desktop

import android.os.Bundle
import androidx.activity.enableEdgeToEdge
import io.crates.keyring.Keyring

class MainActivity : TauriActivity() {
  // Gate R0.4 §R0.4 — enable system Back so WebView history navigates when a
  // page has history, the root falls through to the default activity behavior
  // (move to background), and there is no back-loop. TauriActivity sets this
  // to false by default, which would otherwise disable all Back handling.
  override val handleBackNavigation: Boolean = true

  override fun onCreate(savedInstanceState: Bundle?) {
    // Phase 4c — the CI-only x86_64 RELEASE-test APK enables WebView CDP
    // remote debugging (flag sourced from CiFlags, committed default false).
    // This MUST happen before super.onCreate(): the Tauri WebView is created
    // during native create(), and setWebContentsDebuggingEnabled() only has
    // effect when called before a WebView instance exists. It does NOT set the
    // `android:debuggable` manifest flag, so verify_upgrade_apk_pair.sh still
    // proves the release-test APK is non-debuggable; the flag is inert in
    // production because CiFlags is only set true by the CI build step.
    if (CiFlags.ENABLE_WEBVIEW_REMOTE_DEBUGGING) {
      android.webkit.WebView.setWebContentsDebuggingEnabled(true)
    }
    // Gate E §6.4 — install the NDK application context BEFORE
    // super.onCreate(): TauriActivity's native create() spawns the Rust
    // thread that runs setup(), where the Android Keystore store is opened.
    // It must see an initialized ndk-context or the store crate panics.
    Keyring.initializeNdkContext(applicationContext)
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
  }
}
