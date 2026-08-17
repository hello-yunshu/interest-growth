package io.crates.keyring

import android.content.Context

/**
 * Initializes the `ndk-context` global for the android-native-keyring-store
 * crate (Gate E §6.4). tao 0.35's vendored Android glue keeps its activity
 * context in its own static and never calls
 * `ndk_context::initialize_android_context`, so the store crate would panic
 * with "android context was not initialized" when opened from the Rust
 * broker. This JNI hook (documented in the crate's README) installs the
 * application context before the native app thread runs `setup()`.
 *
 * The store crate is compiled INTO libinterest_growth_desktop_lib.so (there is
 * no standalone libandroid_native_keyring_store.so), so the init block loads
 * the main app library to make the JNI symbol resolvable. Loading an already
 * loaded library is a no-op, so ordering vs. the generated `Rust` object is
 * irrelevant.
 */
class Keyring {
    companion object {
        init {
            System.loadLibrary("interest_growth_desktop_lib")
        }

        external fun initializeNdkContext(context: Context)
    }
}
