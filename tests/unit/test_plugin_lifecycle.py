from __future__ import annotations

from pathlib import Path

from pg_plugin_runtime import PluginRuntime, PluginStateRecord


def _write_manifest(root: Path, version: str) -> None:
    folder = root / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.yaml").write_text(
        f"""id: psychology.demo
name: Demo
version: {version}
level: 3
default_enabled: true
requires:
  core: '>=0.1,<0.2'
  plugins: []
""",
        "utf-8",
    )


def test_full_deploy_driven_plugin_lifecycle(tmp_path: Path):
    manifests = tmp_path / "plugins"
    states: dict[str, PluginStateRecord] = {}
    _write_manifest(manifests, "0.1.0")
    runtime = PluginRuntime(manifests, states.get, lambda state: states.__setitem__(state.plugin_id, state))
    runtime.discover()
    runtime.install_defaults()
    assert runtime.list_status()[0]["lifecycle_state"] == "enabled"

    runtime.disable("psychology.demo")
    assert runtime.list_status()[0]["lifecycle_state"] == "disabled"
    runtime.uninstall("psychology.demo")
    assert runtime.list_status()[0]["lifecycle_state"] == "uninstalled"
    assert states["psychology.demo"].installed_version == "0.1.0"

    runtime.install("psychology.demo")
    assert runtime.list_status()[0]["lifecycle_state"] == "installed"
    runtime.enable("psychology.demo")
    assert runtime.list_status()[0]["lifecycle_state"] == "enabled"

    # A new trusted deployment bundle changes the manifest. Runtime surfaces
    # Update Available before the operator acknowledges the bundled update.
    _write_manifest(manifests, "0.2.0")
    runtime.discover()
    status = runtime.list_status()[0]
    assert status["lifecycle_state"] == "update_available"
    assert status["available_version"] == "0.2.0"

    runtime.update("psychology.demo")
    status = runtime.list_status()[0]
    assert status["lifecycle_state"] == "rollback_available"
    assert status["installed_version"] == "0.2.0"
    assert status["previous_version"] == "0.1.0"

    # Runtime refuses to fake a source-code rollback. The previous bundle must
    # actually be redeployed first, then rollback can be confirmed safely.
    try:
        runtime.rollback("psychology.demo")
        raise AssertionError("rollback should require the previous code bundle")
    except ValueError as exc:
        assert "deploy the previous" in str(exc)

    _write_manifest(manifests, "0.1.0")
    runtime.discover()
    runtime.rollback("psychology.demo")
    status = runtime.list_status()[0]
    assert status["installed_version"] == "0.1.0"
    assert status["lifecycle_state"] == "enabled"
