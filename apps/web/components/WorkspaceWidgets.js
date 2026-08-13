"use client";

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import Icon from './Icon';
import { buildHeatmap, buildOutputDistribution, buildWeeklyTrend, formatRelativeDate, loadWorkspaceData, normalizeClaimRecord, outputTypeMeta } from '../lib/workspaceData';
import { readLayout, resetLayout, saveLayout } from '../lib/workspaceLayout';

export const PAGE_WIDGETS = {
  home: ['recent-outputs', 'focus', 'heatmap', 'questions', 'old-note', 'weekly-trend', 'output-distribution'],
  research: ['research-check', 'recent-sources', 'research-outputs', 'weekly-trend'],
  learning: ['learning-resume', 'review-queue', 'mastery-evidence', 'heatmap', 'old-note'],
  tutor: ['tutor-resume', 'questions', 'learning-resume', 'old-note'],
  outputs: ['recent-outputs', 'output-distribution', 'heatmap', 'weekly-trend', 'needs-shaping'],
  writing: ['drafts', 'research-outputs', 'recent-outputs', 'old-note'],
  content: ['recent-outputs', 'research-outputs', 'drafts', 'output-distribution'],
  book: ['recent-outputs', 'research-outputs', 'old-note', 'drafts'],
  knowledge: ['recent-sources', 'research-check', 'old-note', 'weekly-trend'],
  growth: ['heatmap', 'weekly-trend', 'output-distribution', 'mastery-evidence'],
};

export const PAGE_DEFAULTS = {
  home: [{ id: 'recent-outputs', span: 2 }, { id: 'focus', span: 1 }],
  research: [{ id: 'research-check', span: 1 }, { id: 'recent-sources', span: 1 }],
  learning: [{ id: 'learning-resume', span: 1 }, { id: 'review-queue', span: 1 }, { id: 'mastery-evidence', span: 1 }],
  tutor: [{ id: 'tutor-resume', span: 1 }, { id: 'questions', span: 1 }],
  outputs: [{ id: 'output-distribution', span: 1 }, { id: 'heatmap', span: 2 }],
  writing: [{ id: 'drafts', span: 1 }, { id: 'research-outputs', span: 1 }],
  content: [{ id: 'research-outputs', span: 1 }, { id: 'drafts', span: 1 }],
  book: [{ id: 'recent-outputs', span: 2 }, { id: 'old-note', span: 1 }],
  knowledge: [{ id: 'recent-sources', span: 1 }, { id: 'research-check', span: 1 }],
  growth: [{ id: 'heatmap', span: 2 }, { id: 'weekly-trend', span: 1 }],
};

const META = {
  'recent-outputs': { title: '最近产出', description: '最近沉淀下来的笔记、练习、研究与作品。', icon: 'outputs' },
  focus: { title: '此刻的焦点', description: '在继续学习和下一步之间切换。', icon: 'target' },
  heatmap: { title: '学习节奏', description: '真实活动分布，没有连续打卡要求。', icon: 'heatmap' },
  questions: { title: '待回答的问题', description: '仍值得回来的好奇心。', icon: 'question' },
  'old-note': { title: '重遇一条笔记', description: '从旧记录里重新发现线索。', icon: 'quote' },
  'weekly-trend': { title: '近期投入', description: '近十周留下的学习记录变化。', icon: 'activity' },
  'output-distribution': { title: '成果构成', description: '不同类型的学习产出分布。', icon: 'dashboard' },
  'research-check': { title: '待验证结论', description: '需要补证据或重新确认的结论。', icon: 'check' },
  'recent-sources': { title: '最近资料', description: '刚加入当前兴趣领域的资料。', icon: 'library' },
  'research-outputs': { title: '研究产出', description: '已经形成版本记录的研究结论。', icon: 'search' },
  'learning-resume': { title: '继续学习', description: '从最近的问题、练习或主题接着走。', icon: 'learn' },
  'review-queue': { title: '待复习内容', description: '还没有完成或值得再看的练习。', icon: 'list' },
  'mastery-evidence': { title: '掌握证据', description: '只统计你明确保留的学习证据。', icon: 'status' },
  'tutor-resume': { title: '继续导师对话', description: '回到最近一次仍在进行的会话。', icon: 'tutor' },
  drafts: { title: '继续草稿', description: '继续打磨尚未完成的表达。', icon: 'pen' },
  'needs-shaping': { title: '待整理内容', description: '可以继续梳理的学习记录与草稿。', icon: 'stack' },
};

export function useWorkspaceData() {
  const [state, setState] = useState({ loading: true, data: null, error: '' });
  const reload = () => {
    setState(current => ({ ...current, loading: true, error: '' }));
    loadWorkspaceData().then(data => setState({ loading: false, data, error: data.offline ? '暂时连接不到本地服务。你的内容仍安全保存在设备上。' : '' }))
      .catch(error => setState({ loading: false, data: null, error: error.message }));
  };
  useEffect(reload, []);
  return { ...state, reload };
}

export function WorkspaceBoard({ pageId, data, loading = false, compact = false, title = '你的工作台' }) {
  const defaults = PAGE_DEFAULTS[pageId] || [];
  const available = PAGE_WIDGETS[pageId] || [];
  const [layout, setLayout] = useState(defaults);
  const [editing, setEditing] = useState(false);
  const [picker, setPicker] = useState(null);
  const [dragged, setDragged] = useState(null);
  const closePicker = useCallback(() => setPicker(null), []);
  useEffect(() => setLayout(readLayout(pageId, defaults)), [pageId]);
  function commit(next) { setLayout(next); saveLayout(pageId, next); }
  function move(from, to) {
    if (from === to || from == null || to == null) return;
    const next = [...layout]; const [item] = next.splice(from, 1); next.splice(to, 0, item); commit(next);
  }
  function moveBy(index, offset) { move(index, Math.max(0, Math.min(layout.length - 1, index + offset))); }
  function replace(index, id) { const next = [...layout]; next[index] = { ...next[index], id }; commit(next); setPicker(null); }
  function remove(index) { commit(layout.filter((_, i) => i !== index)); }
  function add(id) { commit([...layout, { id, span: id === 'heatmap' || id === 'recent-outputs' ? 2 : 1 }]); setPicker(null); }
  function resize(index) { const next = [...layout]; next[index] = { ...next[index], span: next[index].span === 2 ? 1 : 2 }; commit(next); }
  function reset() { resetLayout(pageId); setLayout(defaults); setEditing(false); }
  const unused = available.filter(id => !layout.some(item => item.id === id));
  return <section className={`workspaceBoard ${compact ? 'is-compact' : ''}`} aria-label={title}>
    <div className="boardTopline">
      <div><span className="sectionKicker">可按你的方式安排</span>{!compact && <h2>{title}</h2>}</div>
      <div className="boardActions">
        {editing && <button className="quietButton" onClick={reset}><Icon name="refresh"/>恢复默认</button>}
        <button className={`quietButton ${editing ? 'is-active' : ''}`} onClick={() => { setEditing(value => !value); setPicker(null); }}><Icon name={editing ? 'check' : 'settings'}/>{editing ? '完成调整' : '调整工作台'}</button>
      </div>
    </div>
    {editing && <div className="layoutNotice"><Icon name="drag"/><span>拖动组件改变顺序，也可以替换、隐藏或调整宽度。排布只保存在这台设备上。</span></div>}
    <div className="widgetGrid">
      {layout.map((item, index) => <article
        key={`${item.id}-${index}`}
        className={`widgetCard span-${item.span || 1} ${editing ? 'is-editing' : ''}`}
        draggable={editing}
        onDragStart={() => setDragged(index)}
        onDragOver={event => { if (editing) event.preventDefault(); }}
        onDrop={() => { move(dragged, index); setDragged(null); }}
      >
        {editing && <div className="widgetEditBar">
          <span className="dragHandle"><Icon name="drag"/>拖动</span>
          <button onClick={() => moveBy(index, -1)} disabled={index === 0} aria-label={`将${META[item.id]?.title || '组件'}向前移动`} title="向前移动"><Icon name="arrowUp"/></button>
          <button onClick={() => moveBy(index, 1)} disabled={index === layout.length - 1} aria-label={`将${META[item.id]?.title || '组件'}向后移动`} title="向后移动"><Icon name="arrowDown"/></button>
          <button onClick={() => resize(index)} aria-label={`调整${META[item.id]?.title || '组件'}宽度`} title="调整宽度"><Icon name="reorder"/></button>
          <button onClick={() => setPicker({ mode: 'replace', index })}>替换</button>
          <button onClick={() => remove(index)} aria-label={`隐藏${META[item.id]?.title || '组件'}`} title="隐藏"><Icon name="close"/></button>
        </div>}
        <Widget id={item.id} data={data} loading={loading}/>
      </article>)}
      {editing && unused.length > 0 && <button className="addWidgetCard" onClick={() => setPicker({ mode: 'add' })}><Icon name="plus" size={22}/><strong>添加组件</strong><span>选择一个对这里有用的入口或统计</span></button>}
    </div>
    {picker && <WidgetPicker ids={picker.mode === 'replace' ? available.filter(id => id !== layout[picker.index]?.id) : unused} onChoose={id => picker.mode === 'replace' ? replace(picker.index, id) : add(id)} onClose={closePicker}/>}
  </section>;
}

function WidgetPicker({ ids, onChoose, onClose }) {
  const dialogRef = useRef(null);
  const returnFocusRef = useRef(null);
  useEffect(() => {
    returnFocusRef.current = document.activeElement;
    const dialog = dialogRef.current;
    const controls = () => [...(dialog?.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])') || [])].filter(node => !node.disabled);
    controls()[0]?.focus();
    const handleKeyDown = event => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); return; }
      if (event.key !== 'Tab') return;
      const items = controls();
      if (!items.length) return;
      const first = items[0]; const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    dialog?.addEventListener('keydown', handleKeyDown);
    return () => { dialog?.removeEventListener('keydown', handleKeyDown); returnFocusRef.current?.focus?.(); };
  }, [onClose]);
  return <div className="widgetPickerBackdrop" onMouseDown={onClose}>
    <div ref={dialogRef} className="widgetPicker" role="dialog" aria-modal="true" aria-labelledby="widget-picker-title" onMouseDown={event => event.stopPropagation()}>
      <div className="pickerHeader"><div><span className="sectionKicker">组件目录</span><h3 id="widget-picker-title">这里放什么？</h3></div><button onClick={onClose} aria-label="关闭组件目录"><Icon name="close"/></button></div>
      <div className="pickerGrid">{ids.map(id => <button key={id} onClick={() => onChoose(id)}><span className="pickerIcon"><Icon name={META[id]?.icon}/></span><span><strong>{META[id]?.title}</strong><small>{META[id]?.description}</small></span><Icon name="arrowRight"/></button>)}</div>
    </div>
  </div>;
}

function Widget({ id, data, loading }) {
  if (loading || !data) return <WidgetFrame id={id}><WidgetSkeleton/></WidgetFrame>;
  const components = {
    'recent-outputs': RecentOutputs,
    focus: FocusWidget,
    heatmap: HeatmapWidget,
    questions: QuestionsWidget,
    'old-note': OldNoteWidget,
    'weekly-trend': WeeklyTrendWidget,
    'output-distribution': OutputDistributionWidget,
    'research-check': ResearchCheckWidget,
    'recent-sources': RecentSourcesWidget,
    'research-outputs': ResearchOutputsWidget,
    'learning-resume': LearningResumeWidget,
    'review-queue': ReviewQueueWidget,
    'mastery-evidence': MasteryEvidenceWidget,
    'tutor-resume': TutorResumeWidget,
    drafts: DraftsWidget,
    'needs-shaping': NeedsShapingWidget,
  };
  const Component = components[id] || RecentOutputs;
  return <WidgetFrame id={id}><Component data={data}/></WidgetFrame>;
}

function WidgetFrame({ id, children }) {
  const meta = META[id] || META['recent-outputs'];
  return <><header className="widgetHeader"><span className="widgetTitleIcon"><Icon name={meta.icon}/></span><div><h3>{meta.title}</h3><p>{meta.description}</p></div></header><div className="widgetBody">{children}</div></>;
}

function RecentOutputs({ data }) {
  const rows = data.outputs.slice(0, 4);
  return <>{rows.length ? <div className="cleanRows">{rows.map(item => <Link href={item.href} key={item.id} className="cleanRow"><span className="rowIcon"><Icon name={item.icon}/></span><span className="rowMain"><strong>{item.title}</strong><small><i style={{ '--tag-color': item.color }}>{item.label}</i>{item.detail}</small></span><time>{formatRelativeDate(item.date)}</time></Link>)}</div> : <EmptyWidget icon="outputs" text="还没有学习成果。完成一次探索、练习或整理后，它会出现在这里。" href="/learning" action="开始学习"/>}<Link href="/outputs" className="widgetTextLink">查看全部学习成果 <Icon name="arrowRight"/></Link></>;
}

function FocusWidget({ data }) {
  const [mode, setMode] = useState('next');
  useEffect(() => setMode(window.localStorage.getItem('interest-growth.focus-widget') || 'next'), []);
  function choose(value) { setMode(value); window.localStorage.setItem('interest-growth.focus-widget', value); }
  const topic = data.dashboard?.active_topics?.[0];
  const question = data.dashboard?.recent_questions?.[0];
  const session = data.sessions?.sessions?.find(item => item.status !== 'closed');
  return <div className="focusWidget">
    <div className="segmentSwitch" aria-label="焦点类型"><button aria-pressed={mode === 'continue'} className={mode === 'continue' ? 'active' : ''} onClick={() => choose('continue')}>继续学习</button><button aria-pressed={mode === 'next'} className={mode === 'next' ? 'active' : ''} onClick={() => choose('next')}>下一步</button></div>
    {mode === 'next' ? <div className="focusRecommendation"><span className="focusTarget"><Icon name="target"/></span><div><strong>{topic ? `围绕「${topic.title}」做一次小验证` : '从一个小问题开始'}</strong><p>{topic ? '用 20 分钟找一条资料、做一次练习或留下观察。' : '写下此刻最想弄清楚的事，之后再决定要走多深。'}</p><Link href={topic ? '/learning' : '/curiosity'} className="compactPrimary">开始这一步</Link></div></div> : <div className="focusRecommendation"><span className="focusTarget"><Icon name="clock"/></span><div><strong>{session?.title || question?.question || '还没有进行中的学习'}</strong><p>{session ? '最近一次导师会话仍可继续。' : question ? '回到这个问题，不用从头开始。' : '先记录一个问题，系统会帮你保留返回的入口。'}</p><Link href={session ? '/tutor' : '/curiosity'} className="compactPrimary">{session ? '继续对话' : question ? '回到问题' : '记录问题'}</Link></div></div>}
    <div className="focusAlternatives"><Link href="/curiosity"><Icon name="question"/>继续问一个问题<Icon name="arrowRight"/></Link><Link href="/learning"><Icon name="learn"/>回到学习<Icon name="arrowRight"/></Link></div>
    <small className="memoryHint">下次会记住你的选择</small>
  </div>;
}

function HeatmapWidget({ data }) {
  const weeks = buildHeatmap(data.timeline, 52);
  const total = weeks.flat().reduce((sum, day) => sum + day.count, 0);
  return <div className="heatmapWrap"><div className="heatmapSummary"><strong>{total}</strong><span>过去一年留下的学习记录</span></div><div className="heatmapChart" role="img" aria-label={`过去 52 周共留下 ${total} 条学习记录；空白不代表中断。`}><div className="heatmapDays" aria-hidden="true"><span>一</span><span>三</span><span>五</span></div><div className="heatmapWeeks" aria-hidden="true">{weeks.map((week, index) => <div className="heatmapWeek" key={index}>{week.map(day => <span key={day.key} className={`heatCell level-${day.level}`} title={`${day.key} · ${day.count ? `${day.count} 条记录` : '没有记录'}`}/>)}</div>)}</div></div><div className="heatLegend" aria-hidden="true"><span>空白不代表中断</span><div><i className="level-0"/><i className="level-1"/><i className="level-2"/><i className="level-3"/><i className="level-4"/></div><span>记录更多</span></div></div>;
}

function WeeklyTrendWidget({ data }) {
  const rows = buildWeeklyTrend(data.timeline, 10);
  return <div className="chartBlock"><ResponsiveContainer width="100%" height={190}><AreaChart data={rows} margin={{ top: 10, right: 8, left: -24, bottom: 0 }}><CartesianGrid vertical={false} stroke="#e9e5dd"/><XAxis dataKey="name" tick={{ fontSize: 10, fill: '#85837e' }} axisLine={false} tickLine={false} interval={2}/><YAxis allowDecimals={false} tick={{ fontSize: 10, fill: '#85837e' }} axisLine={false} tickLine={false}/><Tooltip content={<QuietTooltip suffix=" 条记录"/>}/><Area type="monotone" dataKey="count" stroke="#4e775e" strokeWidth={2} fill="#dfe9df" fillOpacity={0.7}/></AreaChart></ResponsiveContainer><p className="chartFootnote">这里只呈现投入节奏，不评价连续性。</p></div>;
}

function OutputDistributionWidget({ data }) {
  const rows = buildOutputDistribution(data.outputs);
  const total = rows.reduce((sum, item) => sum + item.value, 0);
  if (!rows.length) return <EmptyWidget icon="dashboard" text="有了学习成果后，这里会展示它们的类型构成。" href="/learning" action="开始学习"/>;
  return <div className="distribution"><div className="donut"><ResponsiveContainer width="100%" height={178}><PieChart><Pie data={rows} dataKey="value" nameKey="name" innerRadius={52} outerRadius={72} paddingAngle={2}>{rows.map(item => <Cell key={item.type} fill={item.color}/>)}</Pie><Tooltip content={<QuietTooltip suffix=" 条"/>}/></PieChart></ResponsiveContainer><div className="donutCenter"><strong>{total}</strong><span>项成果</span></div></div><div className="distributionLegend">{rows.slice(0, 6).map(item => <div key={item.type}><i style={{ background: item.color }}/><span>{item.name}</span><strong>{item.value}</strong></div>)}</div></div>;
}

function QuestionsWidget({ data }) { const rows = data.dashboard?.recent_questions || []; return rows.length ? <div className="linkRows">{rows.slice(0, 4).map(row => <Link href="/curiosity" key={row.id}><Icon name="question"/><span><strong>{row.question}</strong><small>{energyLabel(row.energy_mode)} · 回来过 {row.returned_count || 0} 次</small></span><Icon name="arrowRight"/></Link>)}</div> : <EmptyWidget icon="question" text="还没有悬而未决的问题。" href="/curiosity" action="记下一个问题"/>; }

function OldNoteWidget({ data }) { const notes = data.notes?.notes || []; const note = notes.length > 2 ? notes[notes.length - 1] : notes[0]; return note ? <div className="oldNote"><Icon name="quote" size={28}/><blockquote>{note.body_markdown || note.title}</blockquote><strong>{note.title}</strong><Link href="/learning">重新打开 <Icon name="arrowRight"/></Link></div> : <EmptyWidget icon="pen" text="写下第一条笔记，未来的你会在这里重新遇见它。" href="/learning" action="写一条笔记"/>; }

function ResearchCheckWidget({ data }) { const claims = (data.claims?.claims || []).map(normalizeClaimRecord); const pending = claims.filter(row => row.verification_state !== 'human_verified'); return <MetricList value={pending.length} label="条结论等待确认" rows={pending.slice(0, 3).map(row => row.statement || '尚未写下结论')} href="/research" empty="目前没有等待确认的结论。"/>; }
function RecentSourcesWidget({ data }) { const rows = data.sources?.sources || []; return rows.length ? <div className="cleanRows compact">{rows.slice(0, 4).map(row => <Link href="/research" className="cleanRow" key={row.id}><span className="rowIcon"><Icon name="source"/></span><span className="rowMain"><strong>{row.title}</strong><small>{sourceState(row.verification_state)}</small></span><time>{formatRelativeDate(row.created_at)}</time></Link>)}</div> : <EmptyWidget icon="library" text="当前兴趣还没有加入资料。" href="/research" action="添加资料"/>; }
function ResearchOutputsWidget({ data }) { const rows = data.outputs.filter(item => item.type === 'research'); return <SimpleOutputRows rows={rows} empty="还没有形成研究结论。" href="/research"/>; }
function LearningResumeWidget({ data }) { const item = data.practice?.practice?.find(row => !row.attempts?.length)?.item; const question = data.dashboard?.recent_questions?.[0]; const topic = data.dashboard?.active_topics?.[0]; return <div className="primaryEntry"><span><Icon name="learn" size={24}/></span><strong>{item?.prompt || question?.question || topic?.title || '开始一次轻量学习'}</strong><p>{item ? '这道练习还没有作答。' : question ? '这个问题仍值得继续。' : topic ? '从这个主题挑一个小问题。' : '不需要计划完整路径，先走一步就好。'}</p><Link href="/learning">继续学习 <Icon name="arrowRight"/></Link></div>; }
function ReviewQueueWidget({ data }) { const rows = data.practice?.practice?.filter(bundle => !bundle.attempts?.length) || []; return <MetricList value={rows.length} label="项内容可以复习" rows={rows.slice(0, 3).map(row => row.item?.prompt)} href="/learning" empty="目前没有待复习内容。"/>; }
function MasteryEvidenceWidget({ data }) { const rows = data.mastery?.evidence || []; return <MetricList value={rows.length} label="条明确保留的证据" rows={rows.slice(0, 3).map(row => row.note || '练习作答证据')} href="/learning" empty="还没有明确保留的掌握证据。"/>; }
function TutorResumeWidget({ data }) { const session = data.sessions?.sessions?.find(row => row.status !== 'closed') || data.sessions?.sessions?.[0]; return session ? <div className="primaryEntry"><span><Icon name="tutor" size={24}/></span><strong>{session.title}</strong><p>{session.status === 'closed' ? '这段对话已经结束，也可以作为新问题的起点。' : '这段导师对话仍在进行中。'}</p><Link href="/tutor">打开对话 <Icon name="arrowRight"/></Link></div> : <EmptyWidget icon="tutor" text="还没有导师会话。可以带着一个具体问题开始。" href="/tutor" action="开始对话"/>; }
function DraftsWidget({ data }) { const rows = data.writing?.documents || []; return rows.length ? <div className="cleanRows compact">{rows.slice(0, 4).map(row => <Link href="/writing" className="cleanRow" key={row.id}><span className="rowIcon"><Icon name="pen"/></span><span className="rowMain"><strong>{row.title}</strong><small>{row.status === 'draft' ? '草稿' : row.status}</small></span><time>{formatRelativeDate(row.updated_at)}</time></Link>)}</div> : <EmptyWidget icon="pen" text="还没有草稿。研究结论或学习笔记都可以成为开头。" href="/writing" action="新建草稿"/>; }
function NeedsShapingWidget({ data }) { const rows = data.outputs.filter(item => ['note', 'writing', 'activity'].includes(item.type) && !item.raw?.approved_at); return <SimpleOutputRows rows={rows} empty="目前没有需要整理的内容。" href="/outputs"/>; }

function SimpleOutputRows({ rows, empty, href }) { return rows.length ? <div className="cleanRows compact">{rows.slice(0, 4).map(item => <Link href={item.href} className="cleanRow" key={item.id}><span className="rowIcon"><Icon name={item.icon}/></span><span className="rowMain"><strong>{item.title}</strong><small>{item.label}</small></span><time>{formatRelativeDate(item.date)}</time></Link>)}</div> : <EmptyWidget icon="outputs" text={empty} href={href} action="前往查看"/>; }
function MetricList({ value, label, rows, href, empty }) { return <div className="metricList"><div className="metricHero"><strong>{value}</strong><span>{value ? label : empty}</span></div>{rows.length > 0 && <ul>{rows.map((row, index) => <li key={index}>{row}</li>)}</ul>}<Link href={href}>查看详情 <Icon name="arrowRight"/></Link></div>; }
function EmptyWidget({ icon, text, href, action }) { return <div className="emptyWidget"><span><Icon name={icon}/></span><p>{text}</p>{href && <Link href={href}>{action}<Icon name="arrowRight"/></Link>}</div>; }
function WidgetSkeleton() { return <div className="widgetSkeleton"><span/><span/><span/></div>; }
function QuietTooltip({ active, payload, label, suffix = '' }) { if (!active || !payload?.length) return null; return <div className="quietTooltip"><strong>{label || payload[0]?.name}</strong><span>{payload[0]?.value}{suffix}</span></div>; }
function energyLabel(value) { return ({ light: '轻量', normal: '适中', deep: '深入' })[value] || '适中'; }
function sourceState(value) { return String(value || '').includes('verified') ? '已经人工确认' : '等待确认'; }
