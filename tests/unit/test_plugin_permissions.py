from __future__ import annotations

from pathlib import Path

import pytest

from pg_plugin_runtime import PermissionBroker, PluginPermissionDenied, PluginRuntime, PluginStateRecord


def test_permission_broker_enforces_declared_first_party_capabilities(tmp_path: Path):
    manifests = tmp_path / 'plugins'
    (manifests / 'one').mkdir(parents=True)
    (manifests / 'one' / 'plugin.yaml').write_text('''
id: test.one
name: One
version: 1.0.0
level: 1
default_enabled: true
permissions:
  read: [source]
  write: [note]
risk:
  network: true
  shell: false
  llm: false
  destructive_data: false
''', 'utf-8')
    states = {}
    runtime = PluginRuntime(manifests, states.get, lambda state: states.__setitem__(state.plugin_id, state))
    runtime.discover(); runtime.install_defaults()
    broker = PermissionBroker(runtime)
    assert broker.require_resource('test.one', 'read', 'source').allowed is True
    assert broker.require_resource('test.one', 'write', 'note').allowed is True
    assert broker.require_risk('test.one', 'network').allowed is True
    with pytest.raises(PluginPermissionDenied): broker.require_resource('test.one', 'write', 'claim')
    with pytest.raises(PluginPermissionDenied): broker.require_risk('test.one', 'shell')
    runtime.disable('test.one')
    with pytest.raises(PluginPermissionDenied): broker.require_resource('test.one', 'read', 'source')
