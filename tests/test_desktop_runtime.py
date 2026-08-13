from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pg_shared import get_settings


def test_desktop_data_root_derives_mutable_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    monkeypatch.delenv("SOURCE_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("ARTIFACT_STORAGE_ROOT", raising=False)
    settings = get_settings()
    assert settings.database_url.endswith("psychology_growth.db")
    assert Path(settings.source_storage_root) == tmp_path / "sources"
    assert Path(settings.artifact_storage_root) == tmp_path / "artifacts"


def test_desktop_http_token_gate(monkeypatch):
    monkeypatch.setenv("PG_DESKTOP_TOKEN", "correct-token")
    from pg_api.main import app
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        denied = client.get("/api/dashboard")
        assert denied.status_code == 401
        allowed = client.get("/api/dashboard", headers={"X-PG-Desktop-Token": "correct-token"})
        assert allowed.status_code == 200


def test_renderer_uses_official_tauri_environment_detection(project_root):
    api_js = (project_root / "apps/web/lib/api.js").read_text(encoding="utf-8")
    shell_js = (project_root / "apps/web/components/DesktopShell.js").read_text(encoding="utf-8")
    assert "isTauri as tauriIsTauri" in api_js
    assert "import { isTauri } from '@tauri-apps/api/core'" in shell_js
    assert "__TAURI_INTERNALS__" not in api_js
    assert "__TAURI_INTERNALS__" not in shell_js


def test_desktop_runtime_files_and_static_export_config_exist(project_root):
    tauri = project_root / "apps/desktop/src-tauri/tauri.conf.json"
    assert tauri.exists()
    text = tauri.read_text(encoding="utf-8")
    assert '"frontendDist": "../../web/out"' in text
    assert '"minimumSystemVersion": "13.0"' in text
    assert 'binaries/psychology-growth-core' in text
    next_config = (project_root / "apps/web/next.config.js").read_text(encoding="utf-8")
    assert "output: 'export'" in next_config


def test_no_updater_private_key_in_repository(project_root):
    needles = ("TAURI_SIGNING_" + "PRIVATE_KEY=", "-----BEGIN " + "PRIVATE KEY-----")
    for path in project_root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix.lower() not in {".md", ".json", ".toml", ".py", ".yml", ".yaml", ".js", ".rs", ".example"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not any(n in text for n in needles), path


def test_validation_desktop_config_initializes_disabled_updater_without_null_config(project_root):
    config = json.loads(
        (project_root / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )
    assert config["plugins"]["updater"] == {"pubkey": ""}


def test_desktop_allows_packaged_sidecar_first_launch_validation_time(project_root):
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    assert "wait_for_core_health(port, Duration::from_secs(30))" in rust


def test_desktop_cors_preflight_does_not_require_runtime_token(monkeypatch):
    monkeypatch.setenv("PG_DESKTOP_TOKEN", "correct-token")
    from pg_api.main import app
    with TestClient(app) as client:
        response = client.options(
            "/api/dashboard",
            headers={
                "Origin": "tauri://localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-PG-Desktop-Token",
            },
        )
        assert response.status_code == 200


def test_desktop_runtime_info_requires_token(monkeypatch):
    monkeypatch.setenv("PG_DESKTOP_TOKEN", "correct-token")
    from pg_api.main import app
    with TestClient(app) as client:
        assert client.get("/api/system/desktop-runtime").status_code == 401
        assert client.get("/api/system/desktop-runtime", headers={"X-PG-Desktop-Token": "correct-token"}).status_code == 200


def test_desktop_secure_provider_credentials_use_native_keyring(project_root):
    cargo = (project_root / "apps/desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    web = (project_root / "apps/web/lib/api.js").read_text(encoding="utf-8")
    assert 'keyring = { version = "4.1"' in cargo
    assert "Entry::store_status" not in rust, "keyring v1::Entry has no store_status API"
    assert "KeyringError::NoEntry" in rust
    assert 'const KEYRING_SERVICE: &str = "app.psychologygrowth.desktop"' in rust
    assert '"deepseek-api-key"' in rust
    assert '"deepseek-api-key"' in rust
    assert "provider_secret_status" in rust
    assert "set_provider_secret" in rust
    assert "delete_provider_secret" in rust
    assert "get_provider_secret" not in rust
    assert "get_provider_secret" not in web


def test_desktop_provider_settings_are_nonsecret_and_restartable(project_root):
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    api_js = (project_root / "apps/web/lib/api.js").read_text(encoding="utf-8")
    provider_struct = rust.split("struct ProviderSettings", 1)[1].split("impl Default", 1)[0]
    assert "api_key" not in provider_struct.lower()
    assert "auth_token" not in provider_struct.lower()
    assert "restart_desktop_core" in rust
    assert "restartDesktopCore" in api_js
    assert "provider-settings.json" in rust


def test_desktop_release_policy_matches_build_matrix(project_root):
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    workflow = (project_root / ".github/workflows/desktop-build.yml").read_text(encoding="utf-8")
    core = (project_root / "scripts/desktop_core.py").read_text(encoding="utf-8")
    assert "Windows 11 24H2+ (build 26100+, x64)" in rust
    assert "x86_64-pc-windows-msvc" in workflow
    assert "aarch64-apple-darwin" in workflow
    assert "requires Windows 11 24H2+ (26100+) x64" in core
    windows_conf = (project_root / "apps/desktop/src-tauri/tauri.windows.conf.json").read_text(encoding="utf-8")
    base_conf = (project_root / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    installer_hook = (project_root / "apps/desktop/src-tauri/windows/hooks.nsh").read_text(encoding="utf-8")
    assert '"targets": [\n      "nsis"' in windows_conf
    assert '"installerHooks": "./windows/hooks.nsh"' in base_conf
    assert "CurrentBuildNumber" in installer_hook
    assert "IntCmp $0 26100" in installer_hook
    assert "Abort" in installer_hook


def test_macos_uses_native_sidebar_material_with_explicit_private_api(project_root):
    import json
    mac = json.loads((project_root / "apps/desktop/src-tauri/tauri.macos.conf.json").read_text(encoding="utf-8"))
    main = mac["app"]["windows"][0]
    assert main["decorations"] is True
    assert main["titleBarStyle"] == "Overlay"
    assert main["transparent"] is True
    assert main["windowEffects"]["effects"] == ["sidebar"]
    assert mac["app"]["macOSPrivateApi"] is True


def test_windows_uses_native_mica_with_custom_window_controls(project_root):
    import json
    windows = json.loads((project_root / "apps/desktop/src-tauri/tauri.windows.conf.json").read_text(encoding="utf-8"))
    main = windows["app"]["windows"][0]
    assert main["decorations"] is False
    assert "mica" in main["windowEffects"]["effects"]
    capability = json.loads((project_root / "apps/desktop/src-tauri/capabilities/default.json").read_text(encoding="utf-8"))
    for permission in [
        "core:window:allow-close",
        "core:window:allow-minimize",
        "core:window:allow-toggle-maximize",
        "core:window:allow-start-dragging",
    ]:
        assert permission in capability["permissions"]
    shell = (project_root / "apps/web/components/DesktopShell.js").read_text(encoding="utf-8")
    assert "getCurrentWindow" in shell
    assert "WindowsControls" in shell


def test_release_updater_config_is_merge_patch_delta(project_root, monkeypatch, tmp_path):
    import json
    import runpy
    import sys
    monkeypatch.setenv("TAURI_UPDATER_ENDPOINT", "https://updates.example.com/{{target}}/{{current_version}}")
    monkeypatch.setenv("TAURI_UPDATER_PUBLIC_KEY", "public-key")
    script = project_root / "scripts/prepare_desktop_release_config.py"
    old_argv = sys.argv
    try:
        sys.argv = [str(script)]
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = old_argv
    generated = json.loads((project_root / "apps/desktop/src-tauri/tauri.release.conf.json").read_text(encoding="utf-8"))
    assert set(generated) == {"plugins", "bundle"}
    assert generated["bundle"] == {"createUpdaterArtifacts": True}
    assert "windows" not in generated["bundle"]
    (project_root / "apps/desktop/src-tauri/tauri.release.conf.json").unlink(missing_ok=True)


def test_desktop_export_uses_native_save_dialog_with_runtime_scoped_write(project_root):
    import json
    cargo = (project_root / "apps/desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    web_package = json.loads((project_root / "apps/web/package.json").read_text(encoding="utf-8"))
    api_js = (project_root / "apps/web/lib/api.js").read_text(encoding="utf-8")
    capability = json.loads((project_root / "apps/desktop/src-tauri/capabilities/default.json").read_text(encoding="utf-8"))
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    assert 'tauri-plugin-dialog = "2"' in cargo
    assert 'tauri-plugin-fs = "2"' in cargo
    assert "@tauri-apps/plugin-dialog" in web_package["dependencies"]
    assert "@tauri-apps/plugin-fs" in web_package["dependencies"]
    assert "import('@tauri-apps/plugin-dialog')" in api_js
    assert "import('@tauri-apps/plugin-fs')" in api_js
    assert "writeFile(destination" in api_js
    assert "dialog:allow-save" in capability["permissions"]
    assert "fs:allow-write-file" in capability["permissions"]
    assert "tauri_plugin_dialog::init()" in rust
    assert "tauri_plugin_fs::init()" in rust


def test_desktop_core_readiness_is_real_http_health_probe(project_root):
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    assert "GET /api/health HTTP/1.1" in rust
    assert "interest-growth-api" in rust
    assert "wait_for_core_health" in rust
    assert "wait_for_port" not in rust


def test_desktop_is_single_instance_to_protect_shared_app_data(project_root):
    cargo = (project_root / "apps/desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    assert 'tauri-plugin-single-instance = "2"' in cargo
    assert "tauri_plugin_single_instance::init" in rust
    assert 'get_webview_window("main")' in rust
    assert ".set_focus()" in rust


def test_failed_desktop_core_restart_updates_runtime_error_state(project_root):
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    web = (project_root / "apps/web/lib/api.js").read_text(encoding="utf-8")
    assert "fn runtime_error(" in rust
    assert "let failed = runtime_error(&app, &error);" in rust
    assert "runtimePromise = null" in web


def test_pyinstaller_sidecar_has_static_fastapi_import_graph(project_root):
    core = (project_root / "scripts/desktop_core.py").read_text(encoding="utf-8")
    assert "from pg_api.main import app" in core
    assert '"pg_api.main:app"' not in core
    assert "uvicorn.run(\n        app," in core


def test_desktop_renderer_csp_cannot_connect_directly_to_ai_providers(project_root):
    import json
    conf = json.loads((project_root / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    csp = conf["app"]["security"]["csp"]
    connect = csp.split("connect-src", 1)[1].split(";", 1)[0]
    assert "127.0.0.1:*" in connect
    assert "ipc:" in connect
    assert "deepseek" not in connect.lower()
    assert ("deep" + "tutor") not in connect.lower()
    assert "https://" not in connect


def test_unexpected_core_termination_invalidates_only_matching_runtime_token(project_root):
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    shell = (project_root / "apps/web/components/DesktopShell.js").read_text(encoding="utf-8")
    api_js = (project_root / "apps/web/lib/api.js").read_text(encoding="utf-8")
    assert "let runtime_token = token.clone();" in rust
    assert "if runtime.token == runtime_token" in rust
    assert "error:core-terminated" in rust
    assert "listen('core-terminated'" in shell
    assert "refreshDesktopRuntime" in shell
    assert "runtimePromise = null" in api_js


def test_native_ci_smokes_packaged_sidecar_before_tauri_bundle(project_root):
    workflow = (project_root / ".github/workflows/desktop-build.yml").read_text(encoding="utf-8")
    smoke = (project_root / "scripts/smoke_desktop_sidecar.py").read_text(encoding="utf-8")
    assert "python scripts/smoke_desktop_sidecar.py --target ${{ matrix.target }}" in workflow
    assert "/api/health" in smoke
    assert "/api/system/desktop-runtime" in smoke
    assert "expected 401 without token" in smoke
    assert "PG_DESKTOP_TOKEN" in smoke
