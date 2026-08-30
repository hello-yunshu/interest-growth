from __future__ import annotations

from sqlalchemy import inspect, select


def _create_area(client, *, name='水彩画', slug='watercolor', pack='general'):
    r = client.post('/api/areas', json={
        'name': name, 'slug': slug, 'description': '练习色彩、构图与观察。', 'domain_pack_id': pack,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _h(area):
    return {'X-PG-Interest-Area': area['id'] if isinstance(area, dict) else area}


def test_fresh_install_has_domain_packs_area_and_real_migration(client):
    from pg_api.db import (
        InterestAreaModel, DomainPackModel, PersonaScopeModel,
        get_engine, get_session_factory,
    )

    assert len(inspect(get_engine()).get_table_names()) == 50
    with get_session_factory()() as db:
        assert {x.id for x in db.scalars(select(DomainPackModel)).all()} == {'general', 'psychology'}
        areas = db.scalars(select(InterestAreaModel)).all()
        assert len(areas) == 1
        assert areas[0].slug == 'psychology'
        assert areas[0].domain_pack_id == 'psychology'
        assert areas[0].is_default is True
        from pg_api.db import SchemaMigration
        assert set(db.scalars(select(SchemaMigration.version)).all()) == {15}
        # 2 general + 4 psychology builtin personas are scoped by pack.
        assert len(db.scalars(select(PersonaScopeModel)).all()) == 6


def test_general_area_quick_explore_and_research_do_not_leak_psychology(client):
    area = _create_area(client)
    headers = _h(area)
    q = client.post('/api/questions', headers=headers, json={
        'question': '我想学习水彩画，如何开始建立色彩感觉？', 'interest_level': 5,
    }).json()
    quick = client.post(f"/api/questions/{q['id']}/quick-explore", headers=headers, json={}).json()
    text = quick['exploration']['content']
    assert '心理学' not in text
    assert 'psychology' not in text.lower()
    assert '10-30' in text or '10–30' in text or '分钟' in text

    plan = client.post('/api/research/plan', headers=headers, json={
        'question': '如何建立水彩色彩感觉？', 'depth': 'normal', 'persist_sources': False,
    })
    assert plan.status_code == 200, plan.text
    joined = str(plan.json()).lower()
    for forbidden in ('systematic review', 'meta-analysis', '心理学'):
        assert forbidden not in joined
    assert 'practical demonstration' in joined or 'worked example' in joined


def test_area_lists_and_direct_ids_are_isolated(client):
    psych = client.get('/api/areas/current').json()['area']
    drawing = _create_area(client)

    pq = client.post('/api/questions', headers=_h(psych), json={'question': '什么是认知失调？'}).json()
    dq = client.post('/api/questions', headers=_h(drawing), json={'question': '湿画法如何控制水分？'}).json()

    assert [x['id'] for x in client.get('/api/questions', headers=_h(psych)).json()['questions']] == [pq['id']]
    assert [x['id'] for x in client.get('/api/questions', headers=_h(drawing)).json()['questions']] == [dq['id']]
    assert client.get(f"/api/questions/{pq['id']}", headers=_h(drawing)).status_code == 404
    assert client.get(f"/api/questions/{dq['id']}", headers=_h(psych)).status_code == 404

    ptopic = client.post('/api/topics', headers=_h(psych), json={'title':'认知失调'}).json()
    dtopic = client.post('/api/topics', headers=_h(drawing), json={'title':'水彩水分控制'}).json()
    pnote = client.post('/api/notes', headers=_h(psych), json={'topic_id':ptopic['id'], 'title':'心理学笔记'}).json()
    dnote = client.post('/api/notes', headers=_h(drawing), json={'topic_id':dtopic['id'], 'title':'水彩笔记'}).json()
    assert [x['id'] for x in client.get('/api/notes', headers=_h(psych)).json()['notes']] == [pnote['id']]
    assert [x['id'] for x in client.get('/api/notes', headers=_h(drawing)).json()['notes']] == [dnote['id']]
    assert client.put(f"/api/notes/{pnote['id']}", headers=_h(drawing), json={'title':'越权'}).status_code == 404


def test_cross_area_evidence_and_claim_references_are_rejected(client):
    psych = client.get('/api/areas/current').json()['area']
    drawing = _create_area(client)
    pt = client.post('/api/topics', headers=_h(psych), json={'title':'心理主题'}).json()
    dt = client.post('/api/topics', headers=_h(drawing), json={'title':'水彩主题'}).json()
    src = client.post('/api/sources', headers=_h(psych), json={'topic_id':pt['id'], 'title':'Psych source'}).json()
    ev = client.post('/api/evidence', headers=_h(psych), json={
        'source_id':src['id'], 'excerpt_or_summary':'心理学证据摘要', 'verification_state':'unverified'
    }).json()
    # A Drawing claim cannot pull a Psychology Evidence id across the area boundary.
    r = client.post('/api/claims', headers=_h(drawing), json={
        'topic_id':dt['id'], 'statement':'绘画结论', 'supporting_evidence':[ev['id']],
    })
    assert r.status_code in {400,409}, r.text


def test_general_content_can_use_learning_activity_but_psychology_requires_claim_chain(client):
    drawing = _create_area(client)
    dheaders = _h(drawing)
    dt = client.post('/api/topics', headers=dheaders, json={'title':'水彩色彩练习'}).json()
    activity = client.post('/api/activities', headers=dheaders, json={
        'topic_id':dt['id'], 'activity_type':'creative_practice',
        'objective':'用三组互补色做小色稿', 'observation':'第二组灰度关系更稳定',
        'self_assessment':'仍需要控制饱和度', 'duration_minutes':25,
    })
    assert activity.status_code == 200, activity.text
    activity = activity.json()
    pack = client.post('/api/content/packs', headers=dheaders, json={
        'topic_id':dt['id'], 'grounding_refs':[{'ref_type':'activity','ref_id':activity['id']}],
    })
    assert pack.status_code == 200, pack.text
    payload = pack.json()['pack']
    assert payload['claims'] == []
    assert payload['grounding_refs'][0]['grounding_status'] == 'personal_or_practice_record'
    assert payload['ready_for_publication'] is True
    assert '普遍结论' in payload['body'] or '过程' in payload['body']

    psych = client.get('/api/areas/current').json()['area']
    pt = client.post('/api/topics', headers=_h(psych), json={'title':'心理学学习记录'}).json()
    note = client.post('/api/notes', headers=_h(psych), json={'topic_id':pt['id'], 'title':'只是一条笔记', 'body_markdown':'个人理解'}).json()
    blocked = client.post('/api/content/packs', headers=_h(psych), json={
        'topic_id':pt['id'], 'grounding_refs':[{'ref_type':'note','ref_id':note['id']}],
    })
    assert blocked.status_code == 400
    assert 'Claim/Evidence' in blocked.text


def test_general_mastery_profile_and_activity_do_not_require_claim_or_concept(client):
    drawing = _create_area(client)
    h = _h(drawing)
    topic = client.post('/api/topics', headers=h, json={'title':'构图练习'}).json()
    concept = client.post('/api/concepts', headers=h, json={'topic_id':topic['id'], 'name':'视觉重心'}).json()
    assert concept['mastery']['state'] == 'unfamiliar'
    assert client.put(f"/api/concepts/{concept['concept']['id']}/mastery", headers=h, json={'state':'practice'}).status_code == 200
    bad = client.put(f"/api/concepts/{concept['concept']['id']}/mastery", headers=h, json={'state':'evidence_boundary'})
    assert bad.status_code == 400

    activity = client.post('/api/activities', headers=h, json={
        'activity_type':'project', 'objective':'临摹一张小幅静物', 'status':'completed'
    })
    assert activity.status_code == 200
    assert activity.json()['topic_id'] is None


def test_personas_skills_and_area_capability_are_area_scoped(client):
    psych = client.get('/api/areas/current').json()['area']
    drawing = _create_area(client)
    pctx = client.get('/api/areas/current', headers=_h(psych)).json()
    dctx = client.get('/api/areas/current', headers=_h(drawing)).json()
    assert 'psychology-socratic-tutor' in pctx['domain']['personas']
    assert 'psychology-socratic-tutor' not in dctx['domain']['personas']
    assert 'generic-research' in dctx['domain']['skills']
    assert not any(x.startswith('psychology-') for x in dctx['domain']['skills'])

    dpersonas = client.get('/api/personas', headers=_h(drawing)).json()['personas']
    ppersonas = client.get('/api/personas', headers=_h(psych)).json()['personas']
    assert {x['name'] for x in dpersonas} >= {'curious-peer','socratic-guide'}
    assert 'psychology-socratic-tutor' not in {x['name'] for x in dpersonas}
    assert 'psychology-socratic-tutor' in {x['name'] for x in ppersonas}

    off = client.put(f"/api/areas/{drawing['id']}/capabilities/capability.curiosity", json={'enabled':False})
    assert off.status_code == 200
    assert client.get('/api/questions', headers=_h(drawing)).status_code == 503
    assert client.get('/api/questions', headers=_h(psych)).status_code == 200


def test_generic_area_rejects_psychology_only_tutor_context(client):
    drawing = _create_area(client)
    h = _h(drawing)
    topic = client.post('/api/topics', headers=h, json={'title':'水彩'}).json()
    r = client.post('/api/tutor/sessions', headers=h, json={
        'title':'水彩辅导', 'topic_id':topic['id'], 'persona_name':'psychology-socratic-tutor',
        'skill_names':['psychology-evidence-review'],
    })
    assert r.status_code in {400,409}, r.text

def test_web_area_context_and_curiosity_state_contract(project_root):
    api_js = (project_root / 'apps/web/lib/api.js').read_text('utf-8')
    socket = (project_root / 'apps/web/lib/runtime/transports/socket.js').read_text('utf-8')
    curiosity = (project_root / 'apps/web/app/curiosity/page.js').read_text('utf-8')
    shell = (project_root / 'apps/web/components/DesktopShell.js').read_text('utf-8')
    tutor = (project_root / 'apps/web/app/tutor/page.js').read_text('utf-8')
    content = (project_root / 'apps/web/app/content/page.js').read_text('utf-8')
    assert 'X-PG-Interest-Area' in api_js
    assert "params.set('area'" in socket
    assert "state==='active_topic'" in curiosity
    assert "state==='promoted'" not in curiosity
    assert 'AreaSwitcher' in shell
    assert "persona_name:'psychology-socratic-tutor'" not in tutor
    assert "skill_names:['psychology" not in tutor
    assert "api('/areas/current')" in tutor
    assert 'grounding_refs:refs' in content


def test_cross_area_direct_invalidation_and_practice_tutor_link_are_blocked(client):
    psych = client.get('/api/areas/current').json()['area']
    drawing = _create_area(client)
    pt = client.post('/api/topics', headers=_h(psych), json={'title':'心理来源'}).json()
    src = client.post('/api/sources', headers=_h(psych), json={'topic_id':pt['id'], 'title':'Private psych source'}).json()
    assert client.post(f"/api/sources/{src['id']}/invalidate", headers=_h(drawing), json={'reason':'cross area'}).status_code == 404

    dt = client.post('/api/topics', headers=_h(drawing), json={'title':'水彩练习'}).json()
    item = client.post('/api/practice', headers=_h(drawing), json={'topic_id':dt['id'], 'prompt':'画一组三色阶'}).json()
    ps = client.post('/api/tutor/sessions', headers=_h(psych), json={'title':'心理 session'}).json()
    cross = client.post(f"/api/practice/{item['id']}/attempts", headers=_h(drawing), json={'answer':'done','tutor_session_id':ps['id']})
    assert cross.status_code == 404

def test_tutor_context_update_and_card_render_cannot_cross_areas(client):
    psych = client.get('/api/areas/current').json()['area']
    drawing = _create_area(client)
    ph = _h(psych); dh = _h(drawing)
    ps = client.post('/api/tutor/sessions', headers=ph, json={'title':'psych'}).json()
    # Current-area session cannot be changed to a persona outside its domain scope.
    assert client.patch(f"/api/tutor/sessions/{ps['id']}", headers=ph, json={'persona_name':'curious-peer'}).status_code == 400
    # A drawing session likewise cannot receive a Psychology persona.
    ds = client.post('/api/tutor/sessions', headers=dh, json={'title':'drawing'}).json()
    assert client.patch(f"/api/tutor/sessions/{ds['id']}", headers=dh, json={'persona_name':'psychology-peer'}).status_code == 400

    ptopic = client.post('/api/topics', headers=ph, json={'title':'心理主题卡'}).json()
    cross = client.post('/api/content/cards/render', headers=dh, json={'topic_id':ptopic['id'],'title':'越权卡片','points':['x']})
    assert cross.status_code == 409


def test_area_capability_override_rejects_core_provider_and_unknown_plugins(client):
    area = _create_area(client, name='摄影', slug='photography')
    ok = client.put(f"/api/areas/{area['id']}/capabilities/capability.curiosity", json={'enabled': False})
    assert ok.status_code == 200
    assert ok.json()['plugin_id'] == 'capability.curiosity'

    retired_provider = "integration." + "deep" + "tutor"
    provider = client.put(f"/api/areas/{area['id']}/capabilities/{retired_provider}", json={'enabled': False})
    assert provider.status_code == 404
    assert provider.json()['detail']['code'] == 'unknown_plugin'

    core = client.put(f"/api/areas/{area['id']}/capabilities/core.interest-growth", json={'enabled': False})
    assert core.status_code == 400
    unknown = client.put(f"/api/areas/{area['id']}/capabilities/capability.not-real", json={'enabled': False})
    assert unknown.status_code == 404


def test_route_layer_permission_broker_blocks_manifest_boundary_regressions(client):
    from pg_api.plugins import get_plugin_runtime

    runtime = get_plugin_runtime()
    manifest = runtime.manifests['capability.curiosity']
    original_write = list(manifest.permissions.write)
    original_llm = manifest.risk.llm
    try:
        manifest.permissions.write = [x for x in original_write if x != 'question']
        denied = client.post('/api/questions', json={'question': 'permission boundary probe'})
        assert denied.status_code == 403
        assert denied.json()['detail']['code'] == 'plugin_permission_denied'
    finally:
        manifest.permissions.write = original_write

    question = client.post('/api/questions', json={'question': 'risk boundary probe'}).json()
    try:
        manifest.risk.llm = False
        denied = client.post(f"/api/questions/{question['id']}/quick-explore", json={})
        assert denied.status_code == 403
        assert denied.json()['detail']['code'] == 'plugin_permission_denied'
    finally:
        manifest.risk.llm = original_llm


def test_tutor_browser_turn_ids_are_bound_to_current_area_and_session(client):
    from pg_api.area_context import set_area_selector, reset_area_selector
    from pg_api.db import get_session_factory
    from pg_api.routes.tutor import _turn_for_current_session
    from pg_api.tutor import create_tutor_session, create_tutor_turn

    psych = client.get('/api/areas/current').json()['area']
    drawing = _create_area(client, name='素描', slug='sketching')

    token = set_area_selector(psych['id'])
    try:
        p_session = create_tutor_session(title='psych')
        p_turn = create_tutor_turn(p_session.id, 'chat', {'content':'p'})
    finally:
        reset_area_selector(token)

    token = set_area_selector(drawing['id'])
    try:
        d_session = create_tutor_session(title='drawing')
        d_turn = create_tutor_turn(d_session.id, 'chat', {'content':'d'})
        with get_session_factory()() as db:
            assert _turn_for_current_session(db, d_turn.id, d_session.id).id == d_turn.id
            assert _turn_for_current_session(db, p_turn.id, d_session.id) is None
            assert _turn_for_current_session(db, d_turn.id, 'not-the-current-session') is None
    finally:
        reset_area_selector(token)
