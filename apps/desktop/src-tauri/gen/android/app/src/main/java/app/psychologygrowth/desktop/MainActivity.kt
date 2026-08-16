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
    // Gate E §6.4 — install the NDK application context BEFORE
    // super.onCreate(): TauriActivity's native create() spawns the Rust
    // thread that runs setup(), where the Android Keystore store is opened.
    // It must see an initialized ndk-context or the store crate panics.
    Keyring.initializeNdkContext(applicationContext)
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
  }
}
