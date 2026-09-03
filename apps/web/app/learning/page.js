'use client';

import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import { ApprovalCard, FilterTabs, GraphView, InsightCards, RecommendationCard, RecordsTable, SelectionActions, StatusChip, TaskRows, VisualExplanation } from '../../components/BeautifulUI';
import { WorkspaceBoard, useWorkspaceData } from '../../components/WorkspaceWidgets';
import { useRuntimeCopy } from '../../components/useRuntimeCopy';
import { masteryLabel, statusLabel, toUserMessage } from '../../lib/presentation.js';
import { useCapabilityAvailability } from '../../lib/capabilities';

const emptyConcept = { name: '', definition: '', examples: '', counterexamples: '', confused_with: '' };

export default function LearningPage() {
  const workspace = useWorkspaceData();
  const runtimeCopy = useRuntimeCopy();
  const capability = useCapabilityAvailability();
  const [topics, setTopics] = useState([]), [topic, setTopic] = useState('');
  const [concepts, setConcepts] = useState([]), [notes, setNotes] = useState([]), [practice, setPractice] = useState([]);
  const [bases, setBases] = useState([]), [selectedKb, setSelectedKb] = useState([]);
  const [area, setArea] = useState(null), [claims, setClaims] = useState([]), [sources, setSources] = useState([]);
  const [graph, setGraph] = useState(null), [visual, setVisual] = useState(null);
  const [msg, setMsg] = useState(''), [tab, setTab] = useState('concepts'), [busy, setBusy] = useState(false);
  const [form, setForm] = useState(emptyConcept), [editing, setEditing] = useState('');
  const [editForm, setEditForm] = useState(emptyConcept), [editRelated, setEditRelated] = useState({ claims: [], sources: [] });
  const [note, setNote] = useState({ title: '', body_markdown: '', concept_id: '' });
  const [question, setQuestion] = useState({ prompt: '', concept_id: '' }), [attemptDraft, setAttemptDraft] = useState(null);

  const profileStates = area?.mastery_profile?.states || [];
  const stateLabel = state => profileStates.find(item => item.id === state)?.label || masteryLabel(state) || state;
  const highestState = profileStates.at(-1)?.id;
  const splitLines = value => String(value || '').split('\n').map(item => item.trim()).filter(Boolean);
  const listFields = value => ({ examples: splitLines(value.examples), counterexamples: splitLines(value.counterexamples), confused_with: splitLines(value.confused_with), related_claims: [], related_sources: [] });

  async function load() {
    const [t, k, a] = await Promise.all([api('/topics'), api('/knowledge/bases').catch(() => ({ knowledge_bases: [] })), api('/areas/current')]);
    setTopics(t.topics || []); setBases(k.knowledge_bases || []); setArea(a);
    if (!topic && t.topics?.length) setTopic(t.topics[0].id);
  }
  async function loadTopic(id = topic) {
    const query = id ? `?topic_id=${id}` : '';
    const [c, n, q, cl, s] = await Promise.all([api(`/concepts${query}`), api(`/notes${query}`), api(`/practice${query}`), api(`/claims${query}`), api(`/sources${query}`)]);
    setConcepts(c.concepts || []); setNotes(n.notes || []); setPractice(q.practice || []); setClaims(cl.claims || []); setSources(s.sources || []);
  }
  useEffect(() => { load().catch(error => setMsg(toUserMessage(error))); }, []);
  useEffect(() => { loadTopic().catch(error => setMsg(toUserMessage(error))); setAttemptDraft(null); setEditing(''); }, [topic]);

  async function createConcept(event) {
    event.preventDefault(); if (busy) return; setBusy(true);
    try { await api('/concepts', { method: 'POST', body: JSON.stringify({ topic_id: topic || null, ...listFields(form), name: form.name, definition: form.definition }) }); setForm(emptyConcept); await loadTopic(); setMsg('概念已保存；掌握状态由当前领域的 Profile 驱动。'); }
    catch (error) { setMsg(toUserMessage(error)); } finally { setBusy(false); }
  }
  function beginEdit(item) { const c = item.concept; setEditing(c.id); setEditForm({ name: c.name || '', definition: c.definition || '', examples: (c.examples || []).join('\n'), counterexamples: (c.counterexamples || []).join('\n'), confused_with: (c.confused_with || []).join('\n') }); setEditRelated({ claims: c.related_claims || [], sources: c.related_sources || [] }); }
  async function saveEdit(event) {
    event.preventDefault(); if (busy || !editing) return; setBusy(true);
    try { await api(`/concepts/${editing}`, { method: 'PUT', body: JSON.stringify({ ...listFields(editForm), name: editForm.name, definition: editForm.definition, related_claims: editRelated.claims, related_sources: editRelated.sources }) }); setEditing(''); await loadTopic(); setMsg('概念卡已更新，知识关系会随之刷新。'); }
    catch (error) { setMsg(toUserMessage(error)); } finally { setBusy(false); }
  }
  async function mastery(id, state) { if (busy) return; setBusy(true); try { await api(`/concepts/${id}/mastery`, { method: 'PUT', body: JSON.stringify({ state }) }); await loadTopic(); } catch (error) { setMsg(toUserMessage(error)); } finally { setBusy(false); } }
  async function assist(id, type) {
    if (busy) return; setBusy(true);
    try { const result = await api(`/concepts/${id}/${type}`, { method: 'POST', body: JSON.stringify({ knowledge_base_ids: selectedKb, focus: '' }) }); if (type === 'visualize') { const preview = await api(`/visual-artifacts/${result.artifact.id}/preview`); setVisual(preview); setMsg('可视化已保存，可在当前页面重新查看；它仍需要人工审核。'); } else setMsg((result.result?.text || '学习辅助已生成。').slice(0, 700)); }
    catch (error) { setMsg(toUserMessage(error)); } finally { setBusy(false); }
  }
  async function openGraph() { if (busy) return; setBusy(true); try { setGraph(await api(`/graph${topic ? `?topic_id=${topic}` : ''}`)); setTab('graph'); } catch (error) { setMsg(toUserMessage(error)); } finally { setBusy(false); } }
  async function addNote(event) { event.preventDefault(); if (busy) return; setBusy(true); try { await api('/notes', { method: 'POST', body: JSON.stringify({ topic_id: topic || null, ...note }) }); setNote({ title: '', body_markdown: '', concept_id: '' }); await loadTopic(); setMsg(runtimeCopy.noteSavedCopy); } catch (error) { setMsg(toUserMessage(error)); } finally { setBusy(false); } }
  async function addPractice(event) { event.preventDefault(); if (busy) return; setBusy(true); try { await api('/practice', { method: 'POST', body: JSON.stringify({ topic_id: topic || null, ...question, question_type: 'open' }) }); setQuestion({ prompt: '', concept_id: '' }); await loadTopic(); setMsg('练习已加入；答对不会自动改变掌握状态。'); } catch (error) { setMsg(toUserMessage(error)); } finally { setBusy(false); } }
  async function submitAttempt(promote = false) { if (busy || !attemptDraft?.answer?.trim()) return; setBusy(true); try { const a = await api(`/practice/${attemptDraft.item.id}/attempts`, { method: 'POST', body: JSON.stringify({ answer: attemptDraft.answer, is_correct: attemptDraft.correct, feedback: attemptDraft.feedback || '' }) }); if (promote) await api(`/practice/attempts/${a.id}/promote-evidence`, { method: 'POST', body: JSON.stringify({ note: '用户明确选择保留这次作答作为掌握证据。' }) }); setAttemptDraft(null); await loadTopic(); setMsg(promote ? '作答已保存并保留为证据；掌握等级仍不会自动改变。' : '作答已保存。'); } catch (error) { setMsg(toUserMessage(error)); } finally { setBusy(false); } }
  function toggle(setter, list, id) { setter(list.includes(id) ? list.filter(item => item !== id) : [...list, id]); }

  const masteryTasks = useMemo(() => concepts.map(item => ({ id: item.concept.id, title: item.concept.name, detail: item.concept.definition, status: item.mastery?.state === highestState ? 'completed' : 'running', metaLabel: stateLabel(item.mastery?.state || profileStates[0]?.id || 'unfamiliar') })), [concepts, highestState, profileStates]);
  const masteryAssistAvailable = capability.available('FEATURE_FLEXIBLE_MASTERY', 'capability.mastery');
  const visualizeAvailable = capability.available('FEATURE_VISUALIZE', 'capability.concept-graph');
  const conceptGraphAvailable = capability.available('FEATURE_CONCEPT_GRAPH', 'capability.concept-graph');
  const knowledgeAvailable = capability.available('FEATURE_KNOWLEDGE_RAG', 'capability.knowledge');
  return <div className="stack">
    <section className="pageLead"><div><div className="eyebrow">学习 · {area?.area?.name || '当前兴趣'}</div><h1>用自己的话理解，用真实练习留下证据。</h1><p className="muted">掌握状态来自当前 Domain Pack 的 Mastery Profile，不由通用前端猜测，也不会由 AI 自动宣布。</p></div><StatusChip tone="success">{area?.mastery_profile?.name || runtimeCopy.dataStatusLabel}</StatusChip></section>
    {msg && <p className="notice">{msg}</p>}
    <WorkspaceBoard pageId="learning" data={workspace.data} loading={workspace.loading} compact title="学习工作台"/>
    <section className="card"><div className="cardHeader"><div><div className="eyebrow">当前范围</div><h2>学习主题</h2></div><select aria-label="学习主题" className="compactSelect" value={topic} onChange={event => setTopic(event.target.value)} disabled={busy}><option value="">不限主题</option>{topics.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></div><p className="muted">{capability.status === 'loading' ? '正在确认当前兴趣的能力权限…' : capability.status === 'error' ? '能力状态暂时无法确认，辅助操作已安全停用。' : masteryAssistAvailable || visualizeAvailable || conceptGraphAvailable || knowledgeAvailable ? '不同学习辅助会分别依据当前 Feature、插件与 Area 权限开放。' : '学习辅助当前不可用；基础概念、笔记与练习仍可继续。'}</p><FilterTabs value={tab} onChange={setTab} items={[{ value: 'concepts', label: '概念', count: concepts.length }, { value: 'notes', label: '笔记', count: notes.length }, { value: 'practice', label: '练习', count: practice.length }, { value: 'context', label: '学习上下文', count: bases.length }, { value: 'graph', label: '知识关系' }]} /></section>
    {tab === 'concepts' && <><div className="grid two"><section className="card"><h2>建立一个概念</h2><form className="stack" onSubmit={createConcept}><input value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} placeholder="概念名称" required disabled={busy}/><textarea value={form.definition} onChange={event => setForm({ ...form, definition: event.target.value })} placeholder="先用你自己的话解释它" disabled={busy}/><textarea value={form.examples} onChange={event => setForm({ ...form, examples: event.target.value })} placeholder="例子（每行一个，可选）" disabled={busy}/><textarea value={form.counterexamples} onChange={event => setForm({ ...form, counterexamples: event.target.value })} placeholder="反例或边界（每行一个，可选）" disabled={busy}/><textarea value={form.confused_with} onChange={event => setForm({ ...form, confused_with: event.target.value })} placeholder="易混淆对象（每行一个，可选）" disabled={busy}/><button disabled={busy}>{busy ? '正在保存…' : '保存概念卡'}</button></form></section><RecommendationCard eyebrow="掌握方式" title={area?.mastery_profile?.name || '当前领域掌握 Profile'} description={area?.mastery_profile?.description || '先保存一条自己的理解，再决定下一步。'} alternatives={[{ title: '先记一条笔记', meta: '低能量也有效' }, { title: '先做一次练习', meta: '观察自己的解释' }]}/></div><section className="card"><div className="cardHeader"><h2>概念与理解</h2><div className="row"><StatusChip>{concepts.length} 个概念</StatusChip><button className="secondary small" onClick={openGraph} disabled={busy || !conceptGraphAvailable}>查看知识关系</button></div></div><TaskRows tasks={masteryTasks}/>{concepts.map(item => <div className="buiInlineEditor" key={item.concept.id}><div><strong>{item.concept.name}</strong><p>{item.concept.definition || '待完善'}</p><small className="muted">例子 {item.concept.examples?.length || 0} · 反例 {item.concept.counterexamples?.length || 0} · 关系 {(item.concept.related_claims?.length || 0) + (item.concept.related_sources?.length || 0)}</small></div><select aria-label={`概念掌握状态：${item.concept.name}`} value={item.mastery?.state || profileStates[0]?.id || ''} onChange={event => mastery(item.concept.id, event.target.value)} disabled={busy}>{profileStates.map(state => <option key={state.id} value={state.id}>{state.label || state.id}</option>)}</select><SelectionActions label="针对这个概念" actions={[{ label: '编辑概念卡', onClick: () => beginEdit(item), disabled: busy }, { label: '生成学习路径', onClick: () => assist(item.concept.id, 'guided-path'), primary: true, disabled: busy || !masteryAssistAvailable }, { label: '深入提问', onClick: () => assist(item.concept.id, 'deep-question'), disabled: busy || !masteryAssistAvailable }, { label: '画图理解', onClick: () => assist(item.concept.id, 'visualize'), disabled: busy || !visualizeAvailable }]} />{editing === item.concept.id && <ConceptEditor form={editForm} setForm={setEditForm} claims={claims} sources={sources} related={editRelated} setRelated={setEditRelated} onSubmit={saveEdit} busy={busy} onCancel={() => setEditing('')}/>}</div>)}</section>{visual && <VisualExplanation manifest={visual.manifest} />}</>}
    {tab === 'graph' && <section className="card">{graph ? <GraphView graph={graph} title="当前兴趣的知识关系"/> : <div className="row"><p className="muted">加载当前范围的概念、主张、证据与来源关系。</p><button onClick={openGraph} disabled={busy || !conceptGraphAvailable}>加载关系</button></div>}</section>}
    {tab === 'notes' && <section className="grid two"><div className="card"><h2>写一条学习笔记</h2><form className="stack" onSubmit={addNote}><select aria-label="选择笔记概念" value={note.concept_id} onChange={event => setNote({ ...note, concept_id: event.target.value })}><option value="">不绑定概念</option>{concepts.map(item => <option key={item.concept.id} value={item.concept.id}>{item.concept.name}</option>)}</select><input value={note.title} onChange={event => setNote({ ...note, title: event.target.value })} placeholder="笔记标题" required/><textarea value={note.body_markdown} onChange={event => setNote({ ...note, body_markdown: event.target.value })} placeholder="自己的解释、疑问或灵感"/><button disabled={busy}>保存笔记</button></form></div><div className="card"><RecordsTable columns={[{ key: 'title', label: '笔记' }, { key: 'status', label: '状态', render: row => statusLabel(row.status) }, { key: 'body_markdown', label: '内容预览', render: row => <span>{row.body_markdown?.slice(0, 90) || '—'}</span> }]} rows={notes.slice(0, 20)}/></div></section>}
    {tab === 'practice' && <section className="grid two"><div className="card"><h2>新增一道练习</h2><form className="stack" onSubmit={addPractice}><select aria-label="选择练习概念" value={question.concept_id} onChange={event => setQuestion({ ...question, concept_id: event.target.value })}><option value="">不绑定概念</option>{concepts.map(item => <option key={item.concept.id} value={item.concept.id}>{item.concept.name}</option>)}</select><textarea value={question.prompt} onChange={event => setQuestion({ ...question, prompt: event.target.value })} placeholder="用什么问题检验理解？" required/><button disabled={busy}>加入练习</button></form></div><div className="card"><RecordsTable columns={[{ key: 'item', label: '问题', render: row => <strong>{row.item.prompt}</strong> }, { key: 'attempts', label: '作答次数', render: row => row.attempts.length }, { key: 'action', label: '回顾', render: row => <button className="tableLink" onClick={() => setAttemptDraft({ item: row.item, answer: '', correct: false, feedback: '' })}>回答一次</button> }]} rows={practice.slice(0, 20)}/></div></section>}
    {attemptDraft && <ApprovalCard eyebrow="回顾这次练习" title={attemptDraft.item.prompt} description="保存回答与保留为证据是两个明确动作；都不会自动改变掌握等级。" tone="warning" onCancel={() => setAttemptDraft(null)} actions={<><button className="secondary" onClick={() => submitAttempt(false)} disabled={busy}>只保存作答</button><button onClick={() => submitAttempt(true)} disabled={busy}>保存并保留为证据</button></>}><textarea value={attemptDraft.answer} onChange={event => setAttemptDraft({ ...attemptDraft, answer: event.target.value })} placeholder="你的回答" autoFocus/><label className="check"><input type="checkbox" checked={attemptDraft.correct} onChange={event => setAttemptDraft({ ...attemptDraft, correct: event.target.checked })}/><span>我愿意把这次回答标记为“答对 / 基本成立”</span></label><textarea value={attemptDraft.feedback} onChange={event => setAttemptDraft({ ...attemptDraft, feedback: event.target.value })} placeholder="可选：为什么这样判断？"/></ApprovalCard>}
    {tab === 'context' && <div className="grid two"><section className="card"><h2>可参考的资料库</h2>{bases.map(item => <label className="check" key={item.id}><input type="checkbox" checked={selectedKb.includes(item.id)} onChange={() => toggle(setSelectedKb, selectedKb, item.id)}/><span>{item.name} · {statusLabel(item.status)}</span></label>)}</section><section className="card"><h2>可维护的关系范围</h2><InsightCards items={[{ label: '当前 Profile', title: area?.mastery_profile?.id || '—', detail: '页面只使用后端返回的当前领域 Profile。' }, { label: '可选主张', title: String(claims.length), detail: '编辑概念卡时只能选择当前 Area 可访问的实体。' }, { label: '可选来源', title: String(sources.length), detail: '关系字段通过 selector 写入，不用自由字符串伪造 ID。' }]}/></section></div>}
  </div>;
}

function ConceptEditor({ form, setForm, claims, sources, related, setRelated, onSubmit, onCancel, busy }) {
  return <form className="subcard stack sectionTop" onSubmit={onSubmit}><strong>编辑完整 Concept Card</strong><input value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} placeholder="名称" required/><textarea value={form.definition} onChange={event => setForm({ ...form, definition: event.target.value })} placeholder="定义"/><textarea value={form.examples} onChange={event => setForm({ ...form, examples: event.target.value })} placeholder="例子，每行一个"/><textarea value={form.counterexamples} onChange={event => setForm({ ...form, counterexamples: event.target.value })} placeholder="反例或边界，每行一个"/><textarea value={form.confused_with} onChange={event => setForm({ ...form, confused_with: event.target.value })} placeholder="易混淆对象，每行一个"/><RelationSelector title="关联主张" rows={claims.map(item => ({ id: item.claim.id, label: item.current_version?.statement || item.claim.id }))} selected={related.claims} onToggle={id => setRelated({ ...related, claims: related.claims.includes(id) ? related.claims.filter(item => item !== id) : [...related.claims, id] })}/><RelationSelector title="关联来源" rows={sources.map(item => ({ id: item.id, label: item.title }))} selected={related.sources} onToggle={id => setRelated({ ...related, sources: related.sources.includes(id) ? related.sources.filter(item => item !== id) : [...related.sources, id] })}/><div className="row"><button disabled={busy}>保存完整卡片</button><button type="button" className="ghost" onClick={onCancel}>取消</button></div></form>;
}

function RelationSelector({ title, rows, selected, onToggle }) {
  return <div><div className="fieldLabel">{title}</div>{!rows.length && <p className="muted">当前范围还没有可选项。</p>}{rows.map(row => <label className="check" key={row.id}><input type="checkbox" checked={selected.includes(row.id)} onChange={() => onToggle(row.id)}/><span>{row.label}</span></label>)}</div>;
}
