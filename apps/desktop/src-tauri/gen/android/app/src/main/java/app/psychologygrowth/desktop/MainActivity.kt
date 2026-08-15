package app.psychologygrowth.desktop

import android.os.Bundle
import androidx.activity.enableEdgeToEdge

class MainActivity : TauriActivity() {
  // Gate R0.4 §R0.4 — enable system Back so WebView history navigates when a
  // page has history, the root falls through to the default activity behavior
  // (move to background), and there is no back-loop. TauriActivity sets this
  // to false by default, which would otherwise disable all Back handling.
  override val handleBackNavigation: Boolean = true

  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
  }
}
