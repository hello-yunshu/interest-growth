from __future__ import annotations


def test_memory_graph_keeps_growth_memory_authoritative_and_native_auxiliary(client):
    q = client.post('/api/questions', json={'question': 'What am I returning to?'}).json()
    client.post(f"/api/questions/{q['id']}/pause")
    client.post(f"/api/questions/{q['id']}/return")

    graph = client.get('/api/memory/graph')
    assert graph.status_code == 200
    payload = graph.json()
    assert 'authoritative' in payload['ownership']
    assert payload['native_auxiliary']['available'] is True
    assert payload['native_auxiliary']['authoritative_growth_memory'] is False
    assert payload['local_growth_memory']['area']['id']


def test_visualize_persists_reviewable_native_manifest(client):
    topic = client.post('/api/topics', json={'title': 'Visual learning', 'description': ''}).json()
    concept = client.post('/api/concepts', json={
        'topic_id': topic['id'], 'name': 'Operant conditioning',
        'definition': 'Behavior shaped by consequences.',
        'examples': [], 'counterexamples': [], 'confused_with': [],
        'related_claims': [], 'related_sources': []
    }).json()['concept']

    response = client.post(f"/api/concepts/{concept['id']}/visualize", json={})
    assert response.status_code == 200, response.text
    artifact = response.json()['artifact']
    assert artifact['kind'] == 'visual_explanation'
    assert artifact['metadata_json']['provider'] == 'native.interest-growth'

    preview = client.get(f"/api/visual-artifacts/{artifact['id']}/preview")
    assert preview.status_code == 200
    manifest = preview.json()['manifest']
    assert manifest['schema'] == 'interest.visual.v1'
    assert manifest['provider'] == 'native.interest-growth'
    assert manifest['review_required'] is True
