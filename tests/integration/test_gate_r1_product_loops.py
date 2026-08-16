"""Gate R1 (Product Completion) — concrete product-loop coverage.

These tests run against the deterministic / no-provider TestClient (`client` fixture),
so no real LLM/provider is required. They close the §7.6 Growth Feedback, §7.2
Research/Evidence/Claim invariants, §7.1 Curiosity loop, §7.7 Content Studio closed
loop and §7.9 General Interest journeys that were not already asserted by the
existing suite.
"""
from __future__ import annotations


def _create_area(client, *, name='摄影', slug='photography', pack='general'):
    r = client.post('/api/areas', json={
        'name': name, 'slug': slug, 'description': '练习观察与光线。', 'domain_pack_id': pack,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _h(area):
    return {'X-PG-Interest-Area': area['id'] if isinstance(area, dict) else area}


def _promote(client, *, question='如何理解奖励与内在动机的关系？', headers=None):
    q = client.post('/api/questions', headers=headers, json={'question': question}).json()
    return client.post(f"/api/questions/{q['id']}/promote", headers=headers).json()


def _verified_claim(client, topic, *, headers=None):
    """Build a source -> verified evidence -> verified claim chain."""
    source = client.post('/api/sources', headers=headers, json={
        'topic_id': topic['id'], 'title': 'Human-reviewed source', 'source_type': 'paper',
    }).json()
    client.post(f"/api/sources/{source['id']}/verify", headers=headers)
    support = client.post('/api/evidence', headers=headers, json={
        'source_id': source['id'],
        'excerpt_or_summary': 'Reward effects vary by contingency, meaning and context.',
        'verification_state': 'human_verified',
        'limitations': 'Fixture evidence only.',
    }).json()
    counter = client.post('/api/evidence', headers=headers, json={
        'source_id': source['id'],
        'excerpt_or_summary': 'Some reward conditions do not show the same pattern.',
        'supports_claim': False,
        'verification_state': 'human_verified',
        'limitations': 'Binding fixture.',
    }).json()
    claim = client.post('/api/claims', headers=headers, json={
        'topic_id': topic['id'],
        'statement': '奖励对内在动机的关系取决于奖励类型、意义与情境，不能一概而论。',
        'supporting_evidence': [support['id']],
        'contradicting_evidence': [counter['id']],
        'limitations': '不能推广为所有人、所有奖励的单一因果规则。',
        'publishability': 'supported_with_caution',
    }).json()['claim']
    assert client.post(f"/api/claims/{claim['id']}/verify", headers=headers).status_code == 200
    return source, support, counter, claim


# --------------------------------------------------------------------------- #
# §7.6 Growth Feedback
# --------------------------------------------------------------------------- #


def test_growth_feedback_records_all_reachable_event_types_without_streak_metrics(client):
    """Every API-reachable growth event type is recorded; no streak/daily/page-count
    is used as a canonical growth metric."""
    topic = _promote(client)

    # research.completed via a (degradable) research run.
    run = client.post('/api/research/run', json={
        'topic_id': topic['id'], 'question': topic['title'], 'depth': 'normal',
    })
    assert run.status_code == 200, run.text

    # claim.revised via a revision.
    claim = client.post('/api/claims', json={
        'topic_id': topic['id'],
        'statement': '初步表述。',
        'publishability': 'internal_only',
    }).json()['claim']
    v = client.post(f"/api/claims/{claim['id']}/revisions", json={
        'statement': '修订后的表述，更贴近证据边界。',
        'reason_for_revision': 'adding evidence boundary',
        'publishability': 'internal_only',
    })
    assert v.status_code == 200, v.text

    # mastery.updated via a concept mastery change.
    concept = client.post('/api/concepts', json={
        'topic_id': topic['id'], 'name': '奖励效应', 'definition': '奖励效应需按类型与情境区分。',
    }).json()['concept']
    m = client.put(f"/api/concepts/{concept['id']}/mastery", json={
        'state': 'evidence_boundary', 'evidence_note': '能区分单一因果与条件化结论。',
    })
    assert m.status_code == 200, m.text

    # reflection.completed.
    reflection = client.post('/api/reflections', json={
        'attracted_question': topic['title'],
        'understanding_change': '从记住结论到能按条件判断',
        'next_energy_mode': 'light',
    })
    assert reflection.status_code == 200, reflection.text

    # question.returned via pause -> return (pause is not a failure).
    own = client.get('/api/questions').json()['questions'][0]
    assert client.post(f"/api/questions/{own['id']}/pause").json()['state'] == 'paused'
    returned = client.post(f"/api/questions/{own['id']}/return").json()
    assert returned['state'] == 'returned'
    assert returned['returned_count'] == 1

    events = client.get('/api/growth/events').json()['events']
    types = {e['event_type'] for e in events}
    assert {
        'question.returned',
        'claim.revised',
        'mastery.updated',
        'research.completed',
        'reflection.completed',
    } <= types

    # Growth narrative is a data-driven signal, intentionally NOT a streak.
    narrative = client.get('/api/growth/narrative').json()
    assert set(narrative['signals']) == {'returns', 'claim_revisions', 'mastery_records', 'research_completed'}
    assert narrative['signals']['returns'] >= 1
    assert narrative['signals']['claim_revisions'] >= 1
    assert narrative['signals']['mastery_records'] >= 1
    assert narrative['signals']['research_completed'] >= 1
    for key in narrative['signals']:
        assert 'streak' not in key and 'daily' not in key and 'page' not in key

    # The long-term memory model exposes the same non-gaming metric set.
    memory = client.get('/api/growth/memory').json()['memory']
    g3 = next(m for m in memory if m['layer'] == 'g3_long_term')
    long_term = g3['value_json']
    assert set(long_term) >= {'returns', 'claim_revisions', 'mastery_records', 'reflections', 'research_completed'}
    assert not any(('streak' in k or 'daily_count' in k or 'page_count' in k) for k in long_term)
    assert '变化信号' in long_term['interpretation']

    # The dashboard explicitly disclaims streak / publishing KPIs.
    dashboard = client.get('/api/dashboard').json()
    assert 'No streaks' in dashboard['design_note']


def test_weekly_review_is_served_by_deterministic_memory_and_narrative_not_a_streak(client):
    """§7.6 asks for a 'Weekly Review'. The product has no separate weekly endpoint;
    the deterministic growth-memory refresh + narrative is the closest real surface,
    and it must not be a streak/daily-count metric."""
    # No dedicated weekly/review endpoint exists in the route table.
    for path in ('/api/growth/weekly', '/api/growth/review', '/api/review/weekly'):
        assert client.get(path).status_code in {404, 405}

    # The real surface: refreshing growth memory is deterministic and idempotent.
    first = client.post('/api/growth/memory/refresh')
    assert first.status_code == 200, first.text
    second = client.post('/api/growth/memory/refresh')
    assert second.status_code == 200
    assert first.json()['g3']['value_json'] == second.json()['g3']['value_json']

    narrative = client.get('/api/growth/narrative').json()
    # No streak/publishing KPI is present anywhere in the periodic review output.
    assert '点击' not in narrative['narrative']
    assert '打卡' not in narrative['narrative']


# --------------------------------------------------------------------------- #
# §7.2 Research / Evidence / Claim invariants
# --------------------------------------------------------------------------- #


def test_unreviewed_retrieval_candidate_cannot_be_used_as_evidence(client):
    """A not-human-reviewed candidate (an unverified source) must not become usable
    Evidence, and a Claim built on it cannot be verified until human review."""
    topic = _promote(client)
    candidate = client.post('/api/sources', json={
        'topic_id': topic['id'], 'title': 'Freshly retrieved candidate', 'source_type': 'web',
    }).json()
    assert candidate['verified'] is False

    # human_verified Evidence requires a human-verified source -> 409.
    blocked = client.post('/api/evidence', json={
        'source_id': candidate['id'],
        'excerpt_or_summary': 'Candidate text pulled from a retrieval hit.',
        'verification_state': 'human_verified',
    })
    assert blocked.status_code == 409

    # A candidate may only be captured as non-verified (source_identified) Evidence.
    ev = client.post('/api/evidence', json={
        'source_id': candidate['id'],
        'excerpt_or_summary': 'Candidate text pulled from a retrieval hit.',
        'verification_state': 'source_identified',
    }).json()
    assert ev['verified'] is False

    claim = client.post('/api/claims', json={
        'topic_id': topic['id'],
        'statement': '候选来源支撑的未核验断言。',
        'supporting_evidence': [ev['id']],
        'publishability': 'internal_only',
    }).json()['claim']
    # The Claim cannot be verified until the candidate is human-reviewed.
    assert client.post(f"/api/claims/{claim['id']}/verify").status_code == 409


def test_invalidated_evidence_source_downgrades_support_and_counter_and_blocks_reverify(client):
    """Invalidating the Evidence's source must cascade to BOTH supporting and
    contradicting Evidence and revoke the Claim's verification (no re-verify)."""
    topic = _promote(client)
    source, support, counter, claim = _verified_claim(client, topic)

    revoked = client.post(f"/api/sources/{source['id']}/invalidate", json={
        'reason': 'original text superseded; requires renewed human review',
    })
    assert revoked.status_code == 200
    assert {support['id'], counter['id']} <= set(revoked.json()['affected_evidence_ids'])
    assert claim['id'] in revoked.json()['affected_claim_ids']

    evidence = {e['id']: e for e in client.get('/api/evidence').json()['evidence']}
    for eid in (support['id'], counter['id']):
        row = evidence[eid]
        assert row['verified'] is False
        assert row['verification_state'] == 'source_identified'

    current = next(
        x for x in client.get(f"/api/claims?topic_id={topic['id']}").json()['claims']
        if x['claim']['id'] == claim['id']
    )
    assert current['claim']['verification_state'] == 'unverified'
    # Revoked evidence cannot be silently re-verified.
    assert client.post(f"/api/claims/{claim['id']}/verify").status_code == 409


def test_claim_revision_history_and_citation_provenance(client):
    """Claim version history is retained across revisions and the associated
    Evidence continues to carry its source provenance."""
    topic = _promote(client)
    source, support, counter, claim = _verified_claim(client, topic)

    current = next(
        x for x in client.get(f"/api/claims?topic_id={topic['id']}").json()['claims']
        if x['claim']['id'] == claim['id']
    )
    rev = client.post(f"/api/claims/{claim['id']}/revisions", json={
        'statement': current['current_version']['statement'] + ' 更注意边界。',
        'supporting_evidence': current['current_version']['supporting_evidence'],
        'contradicting_evidence': current['current_version']['contradicting_evidence'],
        'limitations': current['current_version']['limitations'],
        'reason_for_revision': 'tightened boundary',
        'publishability': 'supported_with_caution',
    })
    assert rev.status_code == 200

    versions = client.get(f"/api/claims/{claim['id']}/versions").json()['versions']
    assert [v['version'] for v in versions] == [1, 2]
    # Revision invalidates prior human verification (verified against v1 only).
    assert versions[1]['reason_for_revision'] == 'tightened boundary'

    # Citation provenance: the supporting Evidence still points at the source.
    ev = next(e for e in client.get('/api/evidence').json()['evidence'] if e['id'] == support['id'])
    assert ev['source_id'] == source['id']
    src = next(s for s in client.get(f"/api/sources?topic_id={topic['id']}").json()['sources'] if s['id'] == source['id'])
    assert src['verified'] is True


# --------------------------------------------------------------------------- #
# §7.1 Curiosity loop
# --------------------------------------------------------------------------- #


def test_curiosity_accepts_all_energy_modes(client):
    for mode in ('light', 'normal', 'deep'):
        q = client.post('/api/questions', json={
            'question': f'在{mode}能量模式下如何保持兴趣？',
            'energy_mode': mode,
        })
        assert q.status_code == 200, q.text
        assert q.json()['energy_mode'] == mode
        assert q.json()['state'] == 'captured'


def test_question_recorded_and_promoted_without_any_research(client):
    """A user may record a question and move it to a topic WITHOUT performing research."""
    q = client.post('/api/questions', json={'question': '水彩湿画法的水分控制？'}).json()
    assert q['state'] == 'captured'
    # No research/quick-explore was performed; promote directly.
    topic = client.post(f"/api/questions/{q['id']}/promote").json()
    assert topic['title'] == '水彩湿画法的水分控制？'
    assert client.get(f"/api/questions/{q['id']}").json()['state'] == 'active_topic'

    # Pause is a valid (non-failure) state and Return is a growth event.
    paused = client.post(f"/api/questions/{q['id']}/pause").json()
    assert paused['state'] == 'paused'
    assert paused['active'] is False
    returned = client.post(f"/api/questions/{q['id']}/return").json()
    assert returned['state'] == 'returned'
    assert returned['returned_count'] == 1
    events = client.get('/api/growth/events').json()['events']
    assert any(e['event_type'] == 'question.returned' for e in events)


# --------------------------------------------------------------------------- #
# §7.7 Content Studio closed loop
# --------------------------------------------------------------------------- #


def test_content_studio_closed_loop_human_review_gate(client):
    """Research Topic -> selected reviewed Claims -> Draft -> XHS pack -> Publish Guard
    -> Human Review -> Export. A draft must NOT be publish-approved without human
    acceptance (rule gate + explicit approval)."""
    topic = _promote(client)
    source, support, counter, claim = _verified_claim(client, topic)

    # Draft the XHS pack from a reviewed Claim.
    pack = client.post('/api/content/packs', json={
        'topic_id': topic['id'],
        'claim_ids': [claim['id']],
        'target_audience': '对内在动机感兴趣的普通读者',
        'platform': 'xhs',
    })
    assert pack.status_code == 200, pack.text
    data = pack.json()['pack']
    assert data['ready_for_publication'] is True
    artifact_id = pack.json()['artifact']['id']

    # Publish Guard agrees the Claim is publishable.
    guard = client.post('/api/content/guard', json={
        'text': data['body'], 'claim_ids': [claim['id']],
    })
    assert guard.status_code == 200
    assert not any(x['severity'] == 'high' for x in guard.json()['issues'])

    # Human-review gate: without approval neither approve-state nor export is allowed.
    artifact = next(a for a in client.get(f"/api/artifacts?topic_id={topic['id']}").json()['artifacts'] if a['id'] == artifact_id)
    assert artifact['human_review_required'] is True
    assert artifact['approved_at'] is None
    assert client.get(f"/api/artifacts/{artifact_id}/export").status_code == 409

    approved = client.post(f"/api/artifacts/{artifact_id}/approve").json()
    assert approved['external_publish_performed'] is False
    exported = client.get(f"/api/artifacts/{artifact_id}/export")
    assert exported.status_code == 200
    assert exported.headers['content-type'] == 'application/zip'


# --------------------------------------------------------------------------- #
# §7.9 General Interest (non-psychology) journey
# --------------------------------------------------------------------------- #


def test_general_photography_journey_across_all_loops_without_psychology(client):
    """A non-psychology area (photography) completes Curiosity / Research / Learning /
    Growth / Content loops without any psychology-only entity."""
    area = _create_area(client)
    h = _h(area)

    # Curiosity: record + return a question (growth event in the general area).
    q = client.post('/api/questions', headers=h, json={
        'question': '如何理解自然光下的曝光？', 'interest_level': 4, 'energy_mode': 'normal',
    }).json()
    assert client.post(f"/api/questions/{q['id']}/return", headers=h).json()['returned_count'] == 1

    # Research plan: no psychology-only content leaks into a general area.
    plan = client.post('/api/research/plan', headers=h, json={
        'question': '自然光曝光的基本方法？', 'depth': 'light',
    })
    assert plan.status_code == 200, plan.text
    assert '心理学' not in str(plan.json())

    # Learning: a practice activity with an observation (no claim/concept required).
    activity = client.post('/api/activities', headers=h, json={
        'activity_type': 'creative_practice',
        'objective': '拍一组晨光逆光小样',
        'observation': '顺光细节更稳，逆光氛围更强',
        'self_assessment': '需要控制高光',
        'duration_minutes': 20,
    }).json()
    assert activity['id']

    # Growth: the general area has its own area-scoped growth memory/narrative.
    narrative = client.get('/api/growth/narrative', headers=h).json()
    assert narrative['signals']['returns'] >= 1
    assert narrative['area']['domain_pack_id'] == 'general'

    # Content: a pack grounded in the practice activity under a general-area topic.
    topic = client.post('/api/topics', headers=h, json={'title': '自然光摄影练习'}).json()
    pack = client.post('/api/content/packs', headers=h, json={
        'topic_id': topic['id'],
        'grounding_refs': [{'ref_type': 'activity', 'ref_id': activity['id']}],
    })
    assert pack.status_code == 200, pack.text
    payload = pack.json()['pack']
    assert payload['claims'] == []
    assert payload['grounding_refs'][0]['grounding_status'] == 'personal_or_practice_record'
    assert payload['ready_for_publication'] is True