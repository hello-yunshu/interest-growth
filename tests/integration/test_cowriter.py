from __future__ import annotations

from types import SimpleNamespace


def test_cowriter_revision_requires_explicit_accept_and_preserves_rejection_history(client, monkeypatch):
    from pg_api import cowriter as service

    class FakeCoWriter:
        def propose_selection_edit(self, _context, **kwargs):
            assert kwargs['current_document_text'][kwargs['selection_start']:kwargs['selection_end']] == '心理学证明奖励会降低内在动机。'
            return SimpleNamespace(proposed='一些研究发现，在特定条件下，奖励可能与内在动机下降相关。')
    monkeypatch.setattr(service, 'get_native_bundle', lambda: SimpleNamespace(cowriter=FakeCoWriter()))

    doc = client.post('/api/writing/documents', json={
        'title': 'draft', 'content_markdown': '开头。\n\n心理学证明奖励会降低内在动机。\n\n结尾。'
    }).json()
    revision = client.post(f"/api/writing/documents/{doc['id']}/revisions", json={
        'selected_text': '心理学证明奖励会降低内在动机。',
        'instruction': '改得更符合证据边界', 'mode': 'rewrite', 'tools': []
    })
    assert revision.status_code == 200
    proposed = revision.json()
    # proposal is not silently applied
    current = client.get(f"/api/writing/documents/{doc['id']}").json()['document']
    assert '心理学证明' in current['content_markdown']

    accepted = client.post(f"/api/writing/revisions/{proposed['id']}/decide", json={'accept': True})
    assert accepted.status_code == 200
    assert accepted.json()['revision']['status'] == 'accepted'
    assert '一些研究发现' in accepted.json()['document']['content_markdown']
    assert '心理学证明' not in accepted.json()['document']['content_markdown']

    class FakeCoWriter2:
        def propose_selection_edit(self, _context, **kwargs):
            return SimpleNamespace(proposed='删除结尾。')
    monkeypatch.setattr(service, 'get_native_bundle', lambda: SimpleNamespace(cowriter=FakeCoWriter2()))
    second = client.post(f"/api/writing/documents/{doc['id']}/revisions", json={
        'selected_text': '结尾。', 'instruction': '换一种说法', 'mode': 'rewrite'
    }).json()
    rejected = client.post(f"/api/writing/revisions/{second['id']}/decide", json={'accept': False})
    assert rejected.json()['revision']['status'] == 'rejected'
    assert rejected.json()['document']['content_markdown'].endswith('结尾。')


def test_cowriter_rejects_stale_revision_after_document_changes(client, monkeypatch):
    from pg_api import cowriter as service

    class FakeCoWriter:
        def propose_selection_edit(self, _context, **kwargs):
            return SimpleNamespace(proposed='新段落')
    monkeypatch.setattr(service, 'get_native_bundle', lambda: SimpleNamespace(cowriter=FakeCoWriter()))
    doc = client.post('/api/writing/documents', json={'title': 'stale', 'content_markdown': '旧段落'}).json()
    revision = client.post(f"/api/writing/documents/{doc['id']}/revisions", json={
        'selected_text': '旧段落', 'instruction': 'rewrite'
    }).json()
    client.put(f"/api/writing/documents/{doc['id']}", json={'content_markdown': '用户手动改过的内容'})
    decision = client.post(f"/api/writing/revisions/{revision['id']}/decide", json={'accept': True})
    assert decision.status_code == 409
    current = client.get(f"/api/writing/documents/{doc['id']}").json()['document']
    assert current['content_markdown'] == '用户手动改过的内容'
