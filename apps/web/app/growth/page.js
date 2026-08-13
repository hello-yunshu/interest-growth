"use client";

import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { CodeBlock, InsightCards, StatusChip } from '../../components/BeautifulUI';
import { WorkspaceBoard, useWorkspaceData } from '../../components/WorkspaceWidgets';

export default function GrowthPage() {
  const workspace = useWorkspaceData();
  const [narrative, setNarrative] = useState(null);
  const [memory, setMemory] = useState([]);
  const [graph, setGraph] = useState(null);
  const [message, setMessage] = useState('');
  const [form, setForm] = useState({ attracted_question: '', interest_drain: '', understanding_change: '', continue_topic: '', next_energy_mode: 'normal' });
  async function load() { const [nextNarrative, nextMemory] = await Promise.all([api('/growth/narrative'), api('/growth/memory')]); setNarrative(nextNarrative); setMemory(nextMemory.memory || []); }
  useEffect(() => { load().catch(error => setMessage(error.message)); }, []);
  async function save(event) { event.preventDefault(); try { await api('/reflections', { method: 'POST', body: JSON.stringify(form) }); await load(); workspace.reload(); setMessage('这次回顾已经保存在本机。'); } catch (error) { setMessage(error.message); } }
  async function openMemoryGraph() { try { setGraph(await api('/memory/graph')); } catch (error) { setMessage(error.message); } }
  const hasLongTerm = memory.some(item => item.layer === 'g3_long_term');
  return <div className="stack growthPage">
    <section className="pageLead"><div><div className="eyebrow">成长回顾</div><h1>看见理解怎样变化，不计算连续天数。</h1><p className="muted">{narrative?.narrative || '还没有足够记录形成长期回顾。先留下一个真实问题就好。'}</p></div><StatusChip tone="success">没有打卡压力</StatusChip></section>
    {message && <p className="notice">{message}</p>}
    <WorkspaceBoard pageId="growth" data={workspace.data} loading={workspace.loading} title="成长概览"/>
    <InsightCards items={[
      { id: 'memory', label: '理解线索', title: hasLongTerm ? '已经形成可回看的长期变化' : '长期变化还在积累材料', detail: hasLongTerm ? '它会继续被新的问题、练习和证据修正。' : '系统不会为了制造成长感而过早下结论。', tone: hasLongTerm ? 'success' : 'neutral' },
      { id: 'reflection', label: '回顾材料', title: memory.length ? `当前保留了 ${memory.length} 条成长记忆` : '还没有需要总结的成长记忆', detail: '这些记录只帮助你重遇理解变化，不会变成连续打卡压力。', tone: 'accent' },
    ]}/>
    <div className="grid two">
      <section className="card reflectionIntro"><div className="eyebrow">长期记忆</div><h2>{hasLongTerm ? '已经出现一条长期变化线索' : '让总结等到材料足够时再发生'}</h2><p className="muted">{hasLongTerm ? '这不是给你贴标签，而是一份仍会被新经验修正的回顾。' : '系统不会为了制造成长感而强行总结。真实记录会慢慢形成可以回看的线索。'}</p><button className="secondary" onClick={openMemoryGraph}>查看记录如何连接</button></section>
      <section className="card"><div className="eyebrow">一次轻量回顾</div><h2>最近什么发生了变化？</h2><form className="stack" onSubmit={save}><textarea placeholder="哪个问题最吸引我？" value={form.attracted_question} onChange={event => setForm({ ...form, attracted_question: event.target.value })}/><textarea placeholder="什么在消耗兴趣？" value={form.interest_drain} onChange={event => setForm({ ...form, interest_drain: event.target.value })}/><textarea placeholder="哪个理解发生了变化？" value={form.understanding_change} onChange={event => setForm({ ...form, understanding_change: event.target.value })}/><input placeholder="下次想继续哪个主题？" value={form.continue_topic} onChange={event => setForm({ ...form, continue_topic: event.target.value })}/><label className="fieldGroup"><span>下次的投入强度</span><select value={form.next_energy_mode} onChange={event => setForm({ ...form, next_energy_mode: event.target.value })}><option value="light">轻量看看</option><option value="normal">正常推进</option><option value="deep">深入投入</option></select></label><button>保存这次回顾</button></form></section>
    </div>
    {graph && <section className="grid two"><CodeBlock filename="本地成长记录.json" language="json" code={JSON.stringify(graph.local_growth_memory, null, 2)}/><CodeBlock filename="辅助执行记录.json" language="json" code={JSON.stringify(graph.native_auxiliary, null, 2)}/></section>}
  </div>;
}
