from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from .manifest import PluginManifest

LIFECYCLE_STATES = {
    "installed",
    "enabled",
    "disabled",
    "update_available",
    "updating",
    "rollback_available",
    "uninstalled",
}


@dataclass(slots=True)
class PluginStateRecord:
    plugin_id: str
    enabled: bool
    installed_version: str
    lifecycle_state: str = "enabled"
    previous_version: str | None = None


class PluginRuntime:
    """Manifest-driven product runtime with deploy-driven plugin lifecycle.

    v0.1 deliberately does not execute arbitrary downloaded plugin code. A new plugin
    version arrives with a trusted application/deployment bundle; the runtime detects
    the manifest version change and records update/rollback state. This gives product
    plugins independent enable/disable/install/uninstall/update bookkeeping without
    pretending to provide a third-party code sandbox.
    """

    def __init__(
        self,
        manifests_dir: Path,
        get_state: Callable[[str], PluginStateRecord | None],
        set_state: Callable[[PluginStateRecord], None],
    ) -> None:
        self.manifests_dir = manifests_dir
        self.get_state = get_state
        self.set_state = set_state
        self.manifests: dict[str, PluginManifest] = {}

    def discover(self) -> dict[str, PluginManifest]:
        found: dict[str, PluginManifest] = {}
        for path in sorted(self.manifests_dir.glob("*/plugin.yaml")):
            manifest = PluginManifest.model_validate(yaml.safe_load(path.read_text("utf-8")))
            if manifest.id in found:
                raise ValueError(f"duplicate plugin id: {manifest.id}")
            found[manifest.id] = manifest
        self.manifests = found
        self._validate_dependencies()
        return found

    def _validate_dependencies(self) -> None:
        for manifest in self.manifests.values():
            missing = [p for p in manifest.requires.plugins if p not in self.manifests]
            if missing:
                raise ValueError(f"{manifest.id} missing plugin dependencies: {missing}")

    def install_defaults(self) -> None:
        for manifest in self.manifests.values():
            if self.get_state(manifest.id) is None:
                enabled = manifest.default_enabled
                self.set_state(
                    PluginStateRecord(
                        manifest.id,
                        enabled,
                        manifest.version,
                        "enabled" if enabled else "disabled",
                    )
                )

    def _require_manifest(self, plugin_id: str) -> PluginManifest:
        if plugin_id not in self.manifests:
            raise KeyError(plugin_id)
        return self.manifests[plugin_id]

    def _require_installed(self, plugin_id: str) -> tuple[PluginManifest, PluginStateRecord]:
        manifest = self._require_manifest(plugin_id)
        state = self.get_state(plugin_id)
        if state is None or state.lifecycle_state == "uninstalled":
            raise ValueError(f"plugin is not installed: {plugin_id}")
        return manifest, state

    def is_enabled(self, plugin_id: str) -> bool:
        state = self.get_state(plugin_id)
        return bool(
            state
            and state.enabled
            and state.lifecycle_state not in {"uninstalled", "installed", "updating"}
        )

    def install(self, plugin_id: str) -> None:
        manifest = self._require_manifest(plugin_id)
        current = self.get_state(plugin_id)
        if current and current.lifecycle_state != "uninstalled":
            raise ValueError(f"plugin already installed: {plugin_id}")
        self.set_state(
            PluginStateRecord(
                plugin_id=plugin_id,
                enabled=False,
                installed_version=manifest.version,
                lifecycle_state="installed",
                previous_version=current.installed_version if current else None,
            )
        )

    def enable(self, plugin_id: str) -> None:
        manifest, current = self._require_installed(plugin_id)
        for dep in manifest.requires.plugins:
            if not self.is_enabled(dep):
                raise ValueError(f"dependency disabled: {dep}")
        self.set_state(
            PluginStateRecord(
                plugin_id,
                True,
                current.installed_version,
                "enabled",
                current.previous_version,
            )
        )

    def _enabled_dependants(self, plugin_id: str) -> list[str]:
        return [
            p.id
            for p in self.manifests.values()
            if plugin_id in p.requires.plugins and self.is_enabled(p.id)
        ]

    def disable(self, plugin_id: str) -> None:
        _, current = self._require_installed(plugin_id)
        dependants = self._enabled_dependants(plugin_id)
        if dependants:
            raise ValueError(f"enabled dependants require {plugin_id}: {dependants}")
        self.set_state(
            PluginStateRecord(
                plugin_id,
                False,
                current.installed_version,
                "disabled",
                current.previous_version,
            )
        )

    def uninstall(self, plugin_id: str) -> None:
        _, current = self._require_installed(plugin_id)
        dependants = self._enabled_dependants(plugin_id)
        if dependants:
            raise ValueError(f"enabled dependants require {plugin_id}: {dependants}")
        # State row remains so product data and version history are preserved. There
        # is intentionally no plugin-data deletion action in Personal Alpha.
        self.set_state(
            PluginStateRecord(
                plugin_id,
                False,
                current.installed_version,
                "uninstalled",
                current.previous_version,
            )
        )

    def update(self, plugin_id: str) -> None:
        """Acknowledge the plugin version already present in the deployment bundle.

        Discovery detects `manifest.version != installed_version` as Update Available.
        Calling update first persists `updating`, then adopts that manifest version and
        records the old version as rollback target. Code downloading is intentionally
        outside this first-party runtime.
        """
        manifest, current = self._require_installed(plugin_id)
        if manifest.version == current.installed_version:
            raise ValueError(f"no bundled update available for {plugin_id}")
        was_enabled = current.enabled
        self.set_state(
            PluginStateRecord(
                plugin_id,
                was_enabled,
                current.installed_version,
                "updating",
                current.previous_version,
            )
        )
        self.set_state(
            PluginStateRecord(
                plugin_id,
                was_enabled,
                manifest.version,
                "rollback_available",
                current.installed_version,
            )
        )

    def rollback(self, plugin_id: str) -> None:
        """Adopt a previously recorded version after that code bundle is redeployed."""
        manifest, current = self._require_installed(plugin_id)
        if not current.previous_version:
            raise ValueError(f"no rollback version recorded for {plugin_id}")
        if manifest.version != current.previous_version:
            raise ValueError(
                "rollback code bundle is not active; deploy the previous plugin/app bundle "
                f"({current.previous_version}) before confirming rollback"
            )
        old_current = current.installed_version
        self.set_state(
            PluginStateRecord(
                plugin_id,
                current.enabled,
                manifest.version,
                "enabled" if current.enabled else "disabled",
                old_current,
            )
        )

    def list_status(self) -> list[dict]:
        result = []
        for pid, manifest in self.manifests.items():
            state = self.get_state(pid)
            installed = bool(state and state.lifecycle_state != "uninstalled")
            lifecycle = state.lifecycle_state if state else "uninstalled"
            update_version = None
            if installed and state and manifest.version != state.installed_version:
                lifecycle = "update_available"
                update_version = manifest.version
            result.append({
                "manifest": manifest.model_dump(),
                "installed": installed,
                "enabled": self.is_enabled(pid),
                "lifecycle_state": lifecycle,
                "installed_version": state.installed_version if state else None,
                "available_version": update_version,
                "previous_version": state.previous_version if state else None,
            })
        return result
