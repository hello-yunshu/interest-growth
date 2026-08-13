from __future__ import annotations


def _topic(client):
    q = client.post('/api/questions', json={'question': 'How should I build my own psychology knowledge?'}).json()
    return client.post(f"/api/questions/{q['id']}/promote").json()


def test_local_living_book_compiles_from_owned_learning_assets_and_tracks_staleness(client):
    topic = _topic(client)
    concept = client.post('/api/concepts', json={
        'topic_id': topic['id'], 'name': 'Intrinsic motivation',
        'definition': 'Engaging for inherent satisfaction.',
        'examples': ['reading from curiosity'], 'counterexamples': [], 'confused_with': [],
        'related_claims': [], 'related_sources': []
    }).json()['concept']
    note = client.post('/api/notes', json={
        'topic_id': topic['id'], 'concept_id': concept['id'], 'title': 'My note',
        'body_markdown': 'Autonomy feels central to my understanding.'
    })
    assert note.status_code == 200
    practice = client.post('/api/practice', json={
        'topic_id': topic['id'], 'concept_id': concept['id'], 'prompt': 'Give a counterexample.'
    })
    assert practice.status_code == 200

    # verified claim with evidence so the book has versioned claim/source refs
    src = client.post('/api/sources', json={'topic_id': topic['id'], 'title': 'source', 'source_type': 'paper'}).json()
    client.post(f"/api/sources/{src['id']}/verify")
    ev = client.post('/api/evidence', json={
        'source_id': src['id'], 'excerpt_or_summary': 'Autonomy support is associated with motivation.',
        'verification_state': 'human_verified', 'limitations': 'Context dependent.'
    }).json()
    claim = client.post('/api/claims', json={
        'topic_id': topic['id'], 'statement': 'Autonomy support can matter for motivation.',
        'supporting_evidence': [ev['id']], 'contradicting_evidence': [],
        'limitations': 'Not a universal causal rule.', 'publishability': 'supported_with_caution'
    }).json()['claim']
    # attach claim to concept so chapter provenance is exact
    client.put(f"/api/concepts/{concept['id']}", json={'related_claims': [claim['id']]})

    book = client.post('/api/living-books', json={
        'topic_id': topic['id'], 'title': 'My Psychology', 'intent': 'Build a revisable learning book.'
    }).json()
    compiled = client.post(f"/api/living-books/{book['id']}/compile")
    assert compiled.status_code == 200
    chapters = compiled.json()['chapters']
    assert len(chapters) == 1
    chapter = chapters[0]
    assert 'Intrinsic motivation' in chapter['content_markdown']
    assert 'Autonomy feels central' in chapter['content_markdown']
    assert claim['id'] in chapter['source_refs']['claims']
    assert src['id'] in chapter['source_refs']['sources']
    first_fingerprint = chapter['source_fingerprint']
    assert len(first_fingerprint) == 64

    current = client.get(f"/api/claims?topic_id={topic['id']}").json()['claims'][0]
    revised = client.post(f"/api/claims/{claim['id']}/revisions", json={
        'statement': current['current_version']['statement'] + ' Revised.',
        'supporting_evidence': current['current_version']['supporting_evidence'],
        'contradicting_evidence': current['current_version']['contradicting_evidence'],
        'limitations': current['current_version']['limitations'],
        'reason_for_revision': 'book drift test', 'publishability': 'supported_with_caution'
    })
    assert revised.status_code == 200
    stale = client.get(f"/api/living-books/{book['id']}").json()['chapters'][0]
    assert stale['status'] == 'stale'
    assert stale['stale_reason'] == 'claim.revised'
    recompiled = client.post(f"/api/living-books/{book['id']}/compile").json()['chapters'][0]
    assert recompiled['status'] == 'current'
    assert recompiled['source_fingerprint'] != first_fingerprint


def test_native_book_proposal_is_review_gated_at_proposal_and_spine(client):
    topic = _topic(client)
    book = client.post('/api/living-books', json={
        'topic_id': topic['id'], 'title': 'Native Proposed Book'
    }).json()

    proposed = client.post(f"/api/living-books/{book['id']}/project")
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()['projection_status'] == 'proposal_pending_review'
    assert proposed.json()['proposal_json']['status'] == 'proposal'

    proposal = client.post(f"/api/living-books/{book['id']}/confirm-proposal", json={})
    assert proposal.status_code == 200
    assert proposal.json()['projection_status'] == 'spine_pending_review'
    assert proposal.json()['spine_json']['review_required'] is True

    spine = client.post(f"/api/living-books/{book['id']}/confirm-spine", json={'auto_compile': False})
    assert spine.status_code == 200
    assert spine.json()['book']['projection_status'] == 'accepted'
    assert spine.json()['upstream']['provider'] == 'native.interest-growth'
