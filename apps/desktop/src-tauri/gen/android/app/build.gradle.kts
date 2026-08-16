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
// If none are present the release build type simply has no explicit signing
// config and Android falls back to the debug keystore (NOT a release cert) —
// the CI/verify steps detect that and never claim a signed release.
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
            isMinifyEnabled = true
            proguardFiles(
                *fileTree(".") { include("**/*.pro") }
                    .plus(getDefaultProguardFile("proguard-android-optimize.txt"))
                    .toList().toTypedArray()
            )
            if (releaseStoreFile != null && releaseStorePassword != null &&
                releaseKeyAlias != null && releaseKeyPassword != null
            ) {
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