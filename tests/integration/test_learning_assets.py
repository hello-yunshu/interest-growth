from __future__ import annotations

import pytest
from types import SimpleNamespace


def _topic_and_concept(client):
    topic = client.post('/api/topics', json={'title': 'Learning evidence', 'description': ''}).json()
    bundle = client.post('/api/concepts', json={
        'topic_id': topic['id'],
        'name': 'Cognitive dissonance',
        'definition': 'Tension from inconsistent cognitions or behavior.',
        'examples': [], 'counterexamples': [], 'confused_with': [],
        'related_claims': [], 'related_sources': [],
    }).json()
    return topic, bundle['concept'], bundle['mastery']


def test_bundled_personas_are_local_and_selectable_as_sticky_tutor_context(client):
    personas = client.get('/api/personas')
    assert personas.status_code == 200
    names = {x['name'] for x in personas.json()['personas']}
    assert {'psychology-peer', 'psychology-socratic-tutor', 'psychology-research-assistant', 'psychology-evidence-reviewer'} <= names
    topic, concept, _ = _topic_and_concept(client)
    created = client.post('/api/tutor/sessions', json={
        'title': 'Socratic session',
        'topic_id': topic['id'],
        'concept_id': concept['id'],
        'knowledge_base_ids': [],
        'skill_names': [],
        'persona_name': 'psychology-socratic-tutor',
    })
    assert created.status_code == 200
    assert created.json()['persona_name'] == 'psychology-socratic-tutor'
    missing = client.post('/api/tutor/sessions', json={
        'title': 'bad', 'topic_id': topic['id'], 'concept_id': concept['id'],
        'knowledge_base_ids': [], 'skill_names': [], 'persona_name': 'invented-persona'
    })
    assert missing.status_code == 400


def test_practice_attempt_can_be_promoted_as_evidence_without_changing_mastery(client):
    topic, concept, mastery = _topic_and_concept(client)
    assert mastery['state'] == 'unfamiliar'
    item = client.post('/api/practice', json={
        'topic_id': topic['id'], 'concept_id': concept['id'],
        'prompt': 'Give one example of cognitive dissonance.',
        'question_type': 'open', 'reference_answer': 'A person acts against a belief and feels tension.'
    })
    assert item.status_code == 200
    attempt = client.post(f"/api/practice/{item.json()['id']}/attempts", json={
        'answer': 'I value health but keep smoking and rationalize it.',
        'is_correct': True,
        'feedback': 'Plausible example with belief-behavior conflict.'
    })
    assert attempt.status_code == 200
    promoted = client.post(f"/api/practice/attempts/{attempt.json()['id']}/promote-evidence", json={
        'note': 'User chose to retain this answer as one mastery evidence point.'
    })
    assert promoted.status_code == 200
    assert promoted.json()['mastery_changed'] is False
    concepts = client.get(f"/api/concepts?topic_id={topic['id']}").json()['concepts']
    assert concepts[0]['mastery']['state'] == 'unfamiliar'
    evidence = client.get(f"/api/mastery-evidence?concept_id={concept['id']}").json()['evidence']
    assert len(evidence) == 1
    assert evidence[0]['reference_id'] == attempt.json()['id']


def test_native_practice_proposal_is_reviewable_and_does_not_change_mastery(client, monkeypatch):
    from pg_api.routes import learning_assets as routes

    topic, concept, _ = _topic_and_concept(client)
    proposal = SimpleNamespace(
        prompt='Which case shows conflicting cognitions?', question_type='open_response',
        options=(), expected_answer='A belief-behavior conflict.',
        answer_guide='Explain the conflict.',
    )
    fake = SimpleNamespace(practice=SimpleNamespace(propose=lambda *_args, **_kwargs: (proposal,)))
    monkeypatch.setattr(routes, 'get_native_bundle', lambda: fake)
    response = client.post('/api/practice/propose', json={
        'topic_id': topic['id'], 'concept_id': concept['id'],
        'topic': 'Cognitive dissonance', 'material': 'Conflict between belief and behavior.', 'count': 1,
    })
    assert response.status_code == 200, response.text
    assert response.json()['review_required'] is True
    assert response.json()['proposals'][0]['origin'] == 'native-proposal'
    current = client.get(f"/api/concepts?topic_id={topic['id']}").json()['concepts'][0]
    assert current['mastery']['state'] == 'unfamiliar'


def test_learning_note_remains_host_owned(client):
    topic, concept, _ = _topic_and_concept(client)
    note = client.post('/api/notes', json={
        'topic_id': topic['id'], 'concept_id': concept['id'],
        'title': 'My own explanation', 'body_markdown': 'Conflict is not simple disagreement.'
    })
    assert note.status_code == 200
    edited = client.put(f"/api/notes/{note.json()['id']}", json={'body_markdown': 'Revised locally.'})
    assert edited.status_code == 200
    assert edited.json()['body_markdown'] == 'Revised locally.'


def test_tutor_tool_and_skill_allowlists_are_product_scoped():
    from pg_api.tutor import normalize_tutor_skills, normalize_tutor_tools

    assert normalize_tutor_tools(["paper_search", "reason", "paper_search"]) == ["paper_search", "reason"]
    with pytest.raises(ValueError, match="unsupported tutor tool"):
        normalize_tutor_tools(["exec"])
    # Contract-level validation remains pure before DB/app lifespan exists.
    skills = normalize_tutor_skills(["psychology-evidence-review", "psychology-skeptic"])
    assert skills == ["psychology-evidence-review", "psychology-skeptic"]
    assert normalize_tutor_skills(["generic-research"], domain_pack_id="general") == ["generic-research"]
    with pytest.raises(ValueError, match="unknown bundled tutor skill"):
        normalize_tutor_skills(["psychology-socratic-tutor"])
    with pytest.raises(ValueError, match="unknown bundled tutor skill"):
        normalize_tutor_skills(["psychology-skeptic"], domain_pack_id="general")
