from __future__ import annotations

from dataclasses import dataclass

from .runtime import PluginRuntime


class PluginPermissionDenied(PermissionError):
    pass


@dataclass(slots=True)
class PermissionDecision:
    plugin_id: str
    allowed: bool
    kind: str
    target: str
    reason: str = ''


class PermissionBroker:
    """Enforce declared permissions for trusted first-party product plugins.

    This is a capability boundary, not an OS/process sandbox. It prevents product
    code from using an undeclared domain/risk capability when routed through the
    broker, but it does not make arbitrary hostile Python safe to execute.
    """

    def __init__(self, runtime: PluginRuntime):
        self.runtime = runtime

    def _manifest(self, plugin_id: str):
        if plugin_id not in self.runtime.manifests:
            raise PluginPermissionDenied(f'unknown plugin: {plugin_id}')
        if not self.runtime.is_enabled(plugin_id):
            raise PluginPermissionDenied(f'plugin disabled: {plugin_id}')
        return self.runtime.manifests[plugin_id]

    def require_resource(self, plugin_id: str, operation: str, resource: str) -> PermissionDecision:
        if operation not in {'read', 'write'}:
            raise ValueError('operation must be read or write')
        manifest = self._manifest(plugin_id)
        declared = getattr(manifest.permissions, operation)
        if resource not in declared and '*' not in declared:
            raise PluginPermissionDenied(f'{plugin_id} did not declare {operation}:{resource}')
        return PermissionDecision(plugin_id, True, operation, resource)

    def require_risk(self, plugin_id: str, capability: str) -> PermissionDecision:
        if capability not in {'network', 'shell', 'llm', 'destructive_data'}:
            raise ValueError(f'unknown risk capability: {capability}')
        manifest = self._manifest(plugin_id)
        if not bool(getattr(manifest.risk, capability)):
            raise PluginPermissionDenied(f'{plugin_id} did not declare risk capability: {capability}')
        return PermissionDecision(plugin_id, True, 'risk', capability)
