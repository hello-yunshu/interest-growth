import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("rust")
}

val tauriProperties = Properties().apply {
    val propFile = file("tauri.properties")
    if (propFile.exists()) {
        propFile.inputStream().use { load(it) }
    }
}

// Gate F §8.2 — release signing credentials are NEVER hardcoded in tracked
// source. They come from (in priority order):
//   1. a gitignored `keystore.properties` next to this file, or
//   2. environment variables (storeFile/storePassword/keyAlias/keyPassword).
// Formal release assembly (PG_RELEASE_BUILD=1, set by the release workflow)
// is FAIL-CLOSED at the Gradle layer: if any signing field is missing the
// build aborts rather than silently falling back to the debug keystore.
// Local/debug development (PG_RELEASE_BUILD unset) may build unsigned and
// rely on the later apksigner/verify checks — the debug keystore is never a
// release cert.
val keystoreProps = Properties().apply {
    val propFile = file("keystore.properties")
    if (propFile.exists()) {
        propFile.inputStream().use { load(it) }
    }
}
val releaseStoreFile = (keystoreProps.getProperty("storeFile") ?: System.getenv("PG_ANDROID_STORE_FILE"))
    ?.takeIf { it.isNotBlank() }
val releaseStorePassword = (keystoreProps.getProperty("storePassword") ?: System.getenv("PG_ANDROID_STORE_PASSWORD"))
    ?.takeIf { it.isNotBlank() }
val releaseKeyAlias = (keystoreProps.getProperty("keyAlias") ?: System.getenv("PG_ANDROID_KEY_ALIAS"))
    ?.takeIf { it.isNotBlank() }
val releaseKeyPassword = (keystoreProps.getProperty("keyPassword") ?: System.getenv("PG_ANDROID_KEY_PASSWORD"))
    ?.takeIf { it.isNotBlank() }

android {
    compileSdk = 36
    namespace = "app.psychologygrowth.desktop"
    defaultConfig {
        applicationId = "app.psychologygrowth.desktop"
        minSdk = 24
        targetSdk = 36
        versionCode = tauriProperties.getProperty("tauri.android.versionCode", "1").toInt()
        versionName = tauriProperties.getProperty("tauri.android.versionName", "1.0")
    }
    signingConfigs {
        if (releaseStoreFile != null && releaseStorePassword != null &&
            releaseKeyAlias != null && releaseKeyPassword != null
        ) {
            create("release") {
                storeFile = file(releaseStoreFile)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }
    buildTypes {
        getByName("debug") {
            isDebuggable = true
            isJniDebuggable = true
            isMinifyEnabled = false
            packaging {                jniLibs.keepDebugSymbols.add("*/arm64-v8a/*.so")
                jniLibs.keepDebugSymbols.add("*/armeabi-v7a/*.so")
                jniLibs.keepDebugSymbols.add("*/x86/*.so")
                jniLibs.keepDebugSymbols.add("*/x86_64/*.so")
            }
        }
        getByName("release") {
            // The signed arm64 release remains minified and keeps its explicit
            // plugin/InvokeArg rules below. The emulator uses the separate
            // debug profile and is never published.
            isMinifyEnabled = true
            proguardFiles(
                *fileTree(".") { include("**/*.pro") }
                    .plus(getDefaultProguardFile("proguard-android-optimize.txt"))
                    .toList().toTypedArray()
            )
            // Gate F §18 — formal release assembly fails closed at the Gradle
            // layer. PG_RELEASE_BUILD=1 is set only by the release workflow on
            // the signed arm64 build; a missing signing field there is a hard
            // abort, never a silent fallback to the debug keystore.
            if (System.getenv("PG_RELEASE_BUILD") == "1") {
                val allSigningFieldsPresent = releaseStoreFile != null &&
                    releaseStorePassword != null &&
                    releaseKeyAlias != null &&
                    releaseKeyPassword != null
                check(allSigningFieldsPresent) {
                    "PG_RELEASE_BUILD=1 (formal release) but release signing " +
                        "fields are missing; a release MUST NOT fall back to the " +
                        "debug keystore. Provide PG_ANDROID_STORE_FILE/PASSWORD/" +
                        "KEY_ALIAS/KEY_PASSWORD (or gitignored keystore.properties)."
                }
                signingConfig = signingConfigs.getByName("release")
            } else if (releaseStoreFile != null && releaseStorePassword != null &&
                releaseKeyAlias != null && releaseKeyPassword != null
            ) {
                // Local/dev: sign when credentials are available, otherwise
                // leave unsigned for later apksigner/verify checks.
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
    // Gate F §8.5 — `tauri android build` re-triggers the CLI's jniLib symlink via the
    // gradle rust build; when the canonical .so already exists the CLI creates numbered
    // duplicates ("lib... 2.so", "lib... 3.so") that would bloat the APK. Strip every
    // space-suffixed copy and keep exactly one canonical lib per ABI.
    packaging {
        jniLibs.excludes += "**/libinterest_growth_desktop_lib *.so"
    }
    kotlinOptions {
        jvmTarget = "1.8"
    }
    buildFeatures {
        buildConfig = true
    }
}

rust {
    rootDirRel = "../../../"
}

dependencies {
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-process:2.10.0")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.4")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.0")
}

apply(from = "tauri.build.gradle.kts")
