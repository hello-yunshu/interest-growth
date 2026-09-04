'use client';

import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import { ApprovalCard, ContextCards, FilterTabs, StatusChip, TaskRows } from '../../components/BeautifulUI';
import { WorkspaceBoard, useWorkspaceData } from '../../components/WorkspaceWidgets';
import { statusLabel, toUserMessage } from '../../lib/presentation.js';

const projectionLabel = {
  proposal_pending_review: '书籍提案待确认',
  spine_pending_review: '章节结构待确认',
  local_only: '仅保存在本地',
};

export default function BookPage() {
  const workspace = useWorkspaceData();
  const [topics, setTopics] = useState([]);
  const [books, setBooks] = useState([]);
  const [id, setId] = useState('');
  const [bundle, setBundle] = useState(null);
  const [msg, setMsg] = useState('');
  const [tab, setTab] = useState('chapters');
  const [review, setReview] = useState(null);
  const [proposalDraft, setProposalDraft] = useState(null);
  const [spineDraft, setSpineDraft] = useState(null);
  const [busyAction, setBusyAction] = useState('');
  const busy = Boolean(busyAction);
  const [form, setForm] = useState({ topic_id: '', title: '我的学习书', intent: '把我真正理解、练习、核验或反思过的内容整理成可持续修订的个人学习书。' });

  async function load() {
    const [topicResult, bookResult] = await Promise.all([api('/topics'), api('/living-books')]);
    setTopics(topicResult.topics || []);
    setBooks(bookResult.books || []);
    if (!form.topic_id && topicResult.topics?.length) setForm(current => ({ ...current, topic_id: topicResult.topics[0].id }));
    if (!id && bookResult.books?.length) setId(bookResult.books[0].id);
  }

  async function detail(nextId = id) {
    if (nextId) {
      const next = await api(`/living-books/${nextId}`);
      setBundle(next);
      setProposalDraft(next.book.proposal_json || null);
      setSpineDraft(next.book.spine_json || null);
    }
  }

  useEffect(() => { load().catch(error => setMsg(toUserMessage(error))); }, []);
  useEffect(() => { detail(id).catch(error => setMsg(toUserMessage(error))); setReview(null); }, [id]);

  async function create(event) {
    event.preventDefault();
    if (busy) return;
    setBusyAction('create');
    try {
      const created = await api('/living-books', { method: 'POST', body: JSON.stringify(form) });
      await load();
      setId(created.id);
      setMsg('学习书已创建。可先在本地编译，再决定是否生成章节提案。');
    } catch (error) { setMsg(toUserMessage(error)); } finally { setBusyAction(''); }
  }

  async function action(name, body = {}) {
    if (busy || !id) return null;
    setBusyAction(name);
    try {
      const result = await api(`/living-books/${id}/${name}`, { method: 'POST', body: JSON.stringify(body) });
      await detail();
      setMsg('处理完成，新版本已保存在本地。');
      setReview(null);
      return result;
    } catch (error) { setMsg(toUserMessage(error)); return null; } finally { setBusyAction(''); }
  }

  async function archiveBook() {
    if (busy || !id) return;
    setBusyAction('archive');
    try { await api(`/living-books/${id}/archive`, { method: 'POST' }); await load(); setId(''); setBundle(null); setMsg('学习书已归档，可从历史记录中重新载入。'); }
    catch (error) { setMsg(toUserMessage(error)); } finally { setBusyAction(''); }
  }

  function beginReview(kind) {
    if (kind === 'proposal') setProposalDraft(JSON.parse(JSON.stringify(bundle?.book?.proposal_json || {})));
    if (kind === 'spine') setSpineDraft(JSON.parse(JSON.stringify(bundle?.book?.spine_json || {})));
    setReview(kind);
  }

  function updateChapter(setter, index, key, value) {
    setter(current => ({ ...current, chapters: (current?.chapters || []).map((chapter, i) => i === index ? { ...chapter, [key]: value } : chapter) }));
  }

  function addChapter(setter) {
    setter(current => ({ ...current, chapters: [...(current?.chapters || []), { title: '新章节', purpose: '' }] }));
  }

  function removeChapter(setter, index) {
    setter(current => ({ ...current, chapters: (current?.chapters || []).filter((_, i) => i !== index) }));
  }

  function moveChapter(setter, index, delta) {
    setter(current => {
      const chapters = [...(current?.chapters || [])]; const next = index + delta;
      if (next < 0 || next >= chapters.length) return current;
      [chapters[index], chapters[next]] = [chapters[next], chapters[index]];
      return { ...current, chapters };
    });
  }

  const tasks = useMemo(() => bundle?.chapters?.map(chapter => ({
    id: chapter.id,
    title: `${chapter.order_index}. ${chapter.title}`,
    detail: chapter.stale_reason || chapter.content_markdown?.slice(0, 100) || '',
    status: chapter.status === 'stale' ? 'failed' : chapter.status === 'ready' ? 'completed' : 'running',
    metaLabel: chapter.status === 'ready' ? '已就绪' : chapter.status === 'stale' ? '需要更新' : statusLabel(chapter.status),
  })) || [], [bundle]);

  const context = useMemo(() => bundle?.chapters?.flatMap(chapter => Object.entries(chapter.source_refs || {}).flatMap(([kind, refs]) => (Array.isArray(refs) ? refs : []).slice(0, 4).map((ref, index) => ({
    id: `${chapter.id}-${kind}-${index}`,
    title: chapter.title,
    text: typeof ref === 'string' ? ref : JSON.stringify(ref),
    source: `本地章节引用 · ${kind}`,
    location: chapter.source_fingerprint?.slice(0, 16),
  })))) || [], [bundle]);

  return <div className="stack">
    <section className="pageLead"><div><div className="eyebrow">我的书</div><h1>把学过的东西，写成会随理解一起生长的书。</h1><p className="muted">章节会引用本地的概念、主张、资料、笔记和练习。AI 生成的结构都要经过你确认，才会继续。</p></div><StatusChip tone="success">以本地版本为准</StatusChip></section>
    {msg && <p className="notice">{msg}</p>}
    <WorkspaceBoard pageId="book" data={workspace.data} loading={workspace.loading} compact title="书籍工作台" />
    <div className="grid two">
      <section className="card"><h2>新建一本书</h2><form className="stack" onSubmit={create}><select aria-label="绑定学习主题" value={form.topic_id} onChange={event => setForm({ ...form, topic_id: event.target.value })} disabled={busy}>{topics.map(topic => <option key={topic.id} value={topic.id}>{topic.title}</option>)}</select><input value={form.title} onChange={event => setForm({ ...form, title: event.target.value })} aria-label="书名" disabled={busy}/><textarea value={form.intent} onChange={event => setForm({ ...form, intent: event.target.value })} aria-label="写作意图" disabled={busy}/><button disabled={busy}>{busyAction === 'create' ? '正在保存…' : '创建学习书'}</button></form></section>
      <section className="card"><div className="cardHeader"><h2>我的书架</h2><StatusChip>{books.length} 本</StatusChip></div><select aria-label="选择学习书" value={id} onChange={event => setId(event.target.value)} disabled={busy}><option value="">选择一本书</option>{books.map(book => <option key={book.id} value={book.id}>{book.title}</option>)}</select>{bundle && <div className="sectionTop"><div className="providerHeroRow"><span>章节提案</span><StatusChip tone={bundle.book.projection_status?.includes('pending') ? 'warning' : 'neutral'}>{projectionLabel[bundle.book.projection_status] || statusLabel(bundle.book.projection_status)}</StatusChip></div><div className="row sectionTop"><button onClick={() => action('compile')} disabled={busy}>{busyAction === 'compile' ? '正在整理…' : '重新整理本地章节'}</button><button className="secondary" onClick={() => action('project')} disabled={busy}>{busyAction === 'project' ? '正在生成…' : '生成章节提案'}</button></div>{bundle.book.projection_status === 'proposal_pending_review' && <button className="sectionTop" onClick={() => setReview('proposal')} disabled={busy}>审阅书籍提案</button>}{bundle.book.projection_status === 'spine_pending_review' && <button className="sectionTop" onClick={() => setReview('spine')} disabled={busy}>审阅章节结构</button>}</div>}</section>
    </div>
    {bundle && <section className="card"><FilterTabs value={tab} onChange={setTab} items={[{ value: 'chapters', label: '章节', count: bundle.chapters.length }, { value: 'sources', label: '来源指纹', count: context.length }]}/>{tab === 'chapters' ? <TaskRows tasks={tasks}/> : <ContextCards items={context} countLabel={`${context.length} 条本地引用`}/>}<div className="row sectionTop"><button className="ghost" onClick={archiveBook} disabled={busy}>{busyAction === 'archive' ? '正在归档…' : '归档这本书'}</button></div></section>}
    {review === 'proposal' && <ApprovalCard eyebrow="书籍提案待确认" title="先编辑，再确认书籍提案" description="确认后只会进入章节结构生成。你的本地学习书仍然是唯一事实来源。" tone="warning" onCancel={() => setReview(null)} actions={<button disabled={busy} onClick={() => action('confirm-proposal', { proposal: proposalDraft })}>{busyAction === 'confirm-proposal' ? '正在确认…' : '确认并生成章节结构'}</button>}><div className="stack"><label>书名<input value={proposalDraft?.title || ''} onChange={e => setProposalDraft({ ...proposalDraft, title: e.target.value })}/></label><label>目的与范围<textarea value={proposalDraft?.purpose || proposalDraft?.intent || ''} onChange={e => setProposalDraft({ ...proposalDraft, purpose: e.target.value })}/></label><div className="stack"><strong>章节草案</strong>{(proposalDraft?.chapters || []).map((chapter, index) => <div className="buiInlineEditor" key={index}><input aria-label={`第 ${index + 1} 章标题`} value={chapter.title || ''} onChange={e => updateChapter(setProposalDraft, index, 'title', e.target.value)}/><textarea aria-label={`第 ${index + 1} 章目的`} value={chapter.purpose || chapter.summary || ''} onChange={e => updateChapter(setProposalDraft, index, 'purpose', e.target.value)}/><div className="row"><button type="button" className="tableLink" onClick={() => moveChapter(setProposalDraft, index, -1)}>上移</button><button type="button" className="tableLink" onClick={() => moveChapter(setProposalDraft, index, 1)}>下移</button><button type="button" className="tableLink quiet" onClick={() => removeChapter(setProposalDraft, index)}>删除</button></div></div>)}<button type="button" className="secondary" onClick={() => addChapter(setProposalDraft)}>增加章节</button></div></div></ApprovalCard>}
    {review === 'spine' && <ApprovalCard eyebrow="章节结构待确认" title="编辑并确认章节结构" description="本次确认不会自动批量编译页面，后续内容仍由你控制。" tone="warning" onCancel={() => setReview(null)} actions={<button disabled={busy} onClick={() => action('confirm-spine', { spine: spineDraft, auto_compile: false })}>{busyAction === 'confirm-spine' ? '正在确认…' : '确认章节结构'}</button>}><div className="stack"><label>书名<input value={spineDraft?.title || ''} onChange={e => setSpineDraft({ ...spineDraft, title: e.target.value })}/></label><label>章节目的<textarea value={spineDraft?.purpose || ''} onChange={e => setSpineDraft({ ...spineDraft, purpose: e.target.value })}/></label>{(spineDraft?.chapters || []).map((chapter, index) => <div className="buiInlineEditor" key={index}><input aria-label={`编辑第 ${index + 1} 章标题`} value={chapter.title || ''} onChange={e => updateChapter(setSpineDraft, index, 'title', e.target.value)}/><textarea aria-label={`编辑第 ${index + 1} 章目的`} value={chapter.purpose || chapter.summary || ''} onChange={e => updateChapter(setSpineDraft, index, 'purpose', e.target.value)}/><div className="row"><button type="button" className="tableLink" onClick={() => moveChapter(setSpineDraft, index, -1)}>上移</button><button type="button" className="tableLink" onClick={() => moveChapter(setSpineDraft, index, 1)}>下移</button><button type="button" className="tableLink quiet" onClick={() => removeChapter(setSpineDraft, index)}>删除</button></div></div>)}<button type="button" className="secondary" onClick={() => addChapter(setSpineDraft)}>增加章节</button></div></ApprovalCard>}
  </div>;
}
