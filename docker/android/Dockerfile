# Interest Growth — Android build environment (Gate E)
#
# Provides a self-contained toolchain to initialize and build the Tauri 2
# Android target without installing anything on the host:
#   JDK 17 + Android SDK + NDK + Rust (android targets) + cargo-ndk + Node.
#
# NOTE: This image intentionally does NOT install Linux desktop GUI libraries
# (webkit2gtk, librsvg, etc.). Those are only needed to build the Linux desktop
# target. Android compiles for android-* Rust targets via cargo-ndk + Gradle,
# so they are unnecessary and would only slow the build down.
#
# Build:  docker build --platform linux/amd64 -f docker/android/Dockerfile -t interest-growth-android .
# Run:    docker run --rm -v "$PWD":/work -w /work interest-growth-android <cmd>
#
# NOTE: The Android NDK only ships linux-x86_64 host toolchains, so this image
# must be built for linux/amd64 (QEMU emulation on arm64 hosts). The Rust
# Android targets are cross-compiled from the amd64 host under emulation.

FROM eclipse-temurin:17-jdk

# NDK r27 (Linux x86_64 host) — must be declared before the ENV that uses it.
ARG ANDROID_NDK_VERSION=27.1.12297006

ENV DEBIAN_FRONTEND=noninteractive
ENV ANDROID_HOME=/opt/android-sdk
ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV ANDROID_NDK_HOME=${ANDROID_HOME}/ndk/${ANDROID_NDK_VERSION}
ENV CARGO_HOME=/usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup
# Use a Rust mirror for reliable downloads (static.rust-lang.org is frequently
# slow/unreachable from some regions). Points both rustup-init and toolchain
# downloads at rsproxy.cn. Overridable at build time via --build-arg.
ARG RUSTUP_DIST_SERVER=https://rsproxy.cn
ARG RUSTUP_UPDATE_ROOT=https://rsproxy.cn/rustup
ENV RUSTUP_DIST_SERVER=${RUSTUP_DIST_SERVER}
ENV RUSTUP_UPDATE_ROOT=${RUSTUP_UPDATE_ROOT}
ENV PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${ANDROID_NDK_HOME}/toolchains/llvm/prebuilt/linux-x86_64/bin:${CARGO_HOME}/bin:${PATH}"

# Minimal host build tools + Node.js (for the Next.js web build and @tauri-apps/cli).
# No GUI/GTK packages: see note above.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl unzip python3 make g++ \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Rust stable + Android targets + cargo-ndk
# Use a cargo registry mirror (crates.io is slow/unreachable from some regions).
RUN mkdir -p "${CARGO_HOME}" \
    && printf '[source.crates-io]\nreplace-with = "rsproxy-sparse"\n\n[source.rsproxy-sparse]\nregistry = "sparse+https://rsproxy.cn/index/"\n\n[net]\ngit-fetch-with-cli = true\n' > "${CARGO_HOME}/config.toml" \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable \
    && rustup target add aarch64-linux-android armv7-linux-androideabi \
                            x86_64-linux-android i686-linux-android \
    && cargo install cargo-ndk --locked

# Android SDK components. dl.google.com is unreliable/slow from some regions, so
# everything is fetched from the Tencent Android SDK mirror (fast, verified).
# Each component is its own RUN so a later change only re-does that one layer.
ARG SDK_MIRROR=https://mirrors.cloud.tencent.com/AndroidSDK

# command-line tools
RUN mkdir -p "${ANDROID_HOME}/cmdline-tools" \
    && curl -fSL -o /tmp/cmdline-tools.zip "${SDK_MIRROR}/commandlinetools-linux-11076708_latest.zip" \
    && unzip -q /tmp/cmdline-tools.zip -d "${ANDROID_HOME}/cmdline-tools" \
    && mv "${ANDROID_HOME}/cmdline-tools/cmdline-tools" "${ANDROID_HOME}/cmdline-tools/latest" \
    && rm -f /tmp/cmdline-tools.zip

# platform-tools (zip already contains a top-level platform-tools/ dir)
RUN curl -fSL -o /tmp/platform-tools.zip "${SDK_MIRROR}/platform-tools-latest-linux.zip" \
    && unzip -qo /tmp/platform-tools.zip -d "${ANDROID_HOME}" \
    && rm -f /tmp/platform-tools.zip

# build-tools 35.0.0 (mirror zip wraps content in a top-level android-15/ dir)
RUN curl -fSL -o /tmp/build-tools.zip "${SDK_MIRROR}/build-tools_r35_linux.zip" \
    && unzip -qo /tmp/build-tools.zip -d /tmp/bt \
    && mkdir -p "${ANDROID_HOME}/build-tools/35.0.0" \
    && cp -a /tmp/bt/*/. "${ANDROID_HOME}/build-tools/35.0.0/" \
    && rm -rf /tmp/bt /tmp/build-tools.zip

# platform android-35 (mirror zip wraps content in a top-level android-35/ dir)
RUN curl -fSL -o /tmp/platform-35.zip "${SDK_MIRROR}/platform-35_r02.zip" \
    && unzip -qo /tmp/platform-35.zip -d /tmp/p35 \
    && mkdir -p "${ANDROID_HOME}/platforms/android-35" \
    && cp -a /tmp/p35/*/. "${ANDROID_HOME}/platforms/android-35/" \
    && rm -rf /tmp/p35 /tmp/platform-35.zip

# platform android-36 (compileSdk/targetSdk for the generated gen/android project)
RUN curl -fSL -o /tmp/platform-36.zip "${SDK_MIRROR}/platform-36_r02.zip" \
    && unzip -qo /tmp/platform-36.zip -d /tmp/p36 \
    && mkdir -p "${ANDROID_HOME}/platforms/android-36" \
    && cp -a /tmp/p36/*/. "${ANDROID_HOME}/platforms/android-36/" \
    && rm -rf /tmp/p36 /tmp/platform-36.zip

# NDK r27c
RUN curl -fSL -o /tmp/ndk.zip "${SDK_MIRROR}/android-ndk-r27c-linux.zip" \
    && unzip -q /tmp/ndk.zip -d "${ANDROID_HOME}/ndk" \
    && mv "${ANDROID_HOME}/ndk/android-ndk-r27c" "${ANDROID_HOME}/ndk/${ANDROID_NDK_VERSION}" \
    && rm -f /tmp/ndk.zip

# Accept SDK licenses so later Gradle/cargo-ndk runs do not block on them.
RUN yes | sdkmanager --sdk_root="${ANDROID_HOME}" --licenses >/dev/null 2>&1 || true

# Tauri CLI for android init/build (npm latest is 2.11.4, compatible with the
# repo's tauri 2.11.x Rust crate).
ARG TAURI_CLI_VERSION=2.11.4
RUN npm install -g "@tauri-apps/cli@${TAURI_CLI_VERSION}" --registry=https://registry.npmmirror.com

WORKDIR /work