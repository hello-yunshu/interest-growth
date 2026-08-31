"use client";

import { useEffect, useMemo, useState } from 'react';
import Icon from './Icon';
import { activityLabel, statusLabel } from '../lib/presentation.js';

export function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!query) return undefined;
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, []);
  return reduced;
}

export function StatusChip({ children, tone = 'neutral', pulse = false }) {
  return <span className={`buiChip buiChip--${tone} ${pulse ? 'buiChip--pulse' : ''}`}>{children}</span>;
}

export function PixelLoader({ label = '正在处理', active = true, startedAt = null, detail = '' }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!active) return undefined;
    const started = startedAt || Date.now();
    const tick = () => setElapsed(Math.max(0, (Date.now() - started) / 1000));
    tick();
    const id = setInterval(tick, 100);
    return () => clearInterval(id);
  }, [active, startedAt]);
  const reducedMotion = useReducedMotion();
  return <div className={`buiLoader ${active ? 'is-active' : 'is-done'} ${reducedMotion ? 'is-reduced-motion' : ''}`} role="status" aria-live="polite">
    <div className="buiPixelGrid" aria-hidden="true">{Array.from({ length: 15 }, (_, i) => <i key={i} style={{ '--i': i }} />)}</div>
    <div className="buiLoaderCopy"><strong>{label}</strong><span>{active ? `${elapsed.toFixed(1)} 秒` : '已完成'}{detail ? ` · ${detail}` : ''}</span></div>
  </div>;
}

function eventLabel(event) {
  const category = event?.category || event?.type || 'activity';
  if (category === 'answer_delta') return '回答';
  if (category === 'tool_call') return event?.metadata?.tool_name ? `调用：${event.metadata.tool_name}` : '调用工具';
  if (category === 'tool_result') return event?.metadata?.tool_name ? `完成：${event.metadata.tool_name}` : '工具结果';
  if (category === 'sources') return '来源';
  if (category === 'progress') return '进展';
  if (category === 'wait_for_input') return '等待你的输入';
  if (category === 'stage_start') return '开始处理';
  if (category === 'stage_end') return '处理完成';
  if (category === 'error') return '出错了';
  if (category === 'done') return '已完成';
  return activityLabel(category);
}

function eventTone(event) {
  const category = event?.category || event?.type || '';
  if (category === 'error') return 'danger';
  if (category === 'done' || event?.terminal) return 'success';
  if (category === 'wait_for_input') return 'warning';
  if (category === 'tool_call' || category === 'tool_result') return 'accent';
  return 'neutral';
}

/**
 * Public activity trace only. Never render hidden/private model chain-of-thought.
 * Inputs should be normalized tool/progress/source/stage events from the product runtime.
 */
const PRIVATE_TRACE_CATEGORIES = new Set(['answer_delta', 'thinking', 'reasoning', 'chain_of_thought', 'cot', 'internal_thought']);
const PUBLIC_TRACE_CATEGORIES = new Set(['stage_start', 'stage_end', 'progress', 'tool_call', 'tool_result', 'sources', 'wait_for_input', 'error', 'done', 'session', 'session_meta', 'activity']);

function publicEventDetail(event) {
  const category = String(event?.category || event?.type || '').toLowerCase();
  if (category === 'error') return '执行未完成，请检查设置或稍后重试。';
  if (category === 'tool_call') return '已经请求调用工具';
  if (category === 'tool_result') return event?.metadata?.status ? `工具已完成（${statusLabel(event.metadata.status)}）` : '工具已经完成';
  if (category === 'sources') {
    const count = event?.metadata?.count ?? event?.sources?.length;
    return count !== undefined ? `找到 ${count} 个可用来源` : '已有可用来源';
  }
  if (category === 'done') return '本轮已经完成';
  return String(event?.detail || event?.metadata?.message || event?.content || '').slice(0, 420) || '运行记录';
}

export function ActivityTrace({ events = [], title = '活动记录', defaultOpen = true, empty = '还没有可展示的活动。' }) {
  const [open, setOpen] = useState(defaultOpen);
  const publicEvents = useMemo(() => events.filter(event => { const category = String(event?.category || event?.type || '').toLowerCase(); return PUBLIC_TRACE_CATEGORIES.has(category) && !PRIVATE_TRACE_CATEGORIES.has(category); }).slice(-50), [events]);
  return <section className="buiTrace">
    <button className="buiTraceHeader" type="button" onClick={() => setOpen(v => !v)} aria-expanded={open}>
      <span className="buiTraceTitle"><span className="buiActivityDot" />{title}</span>
      <span className="buiTraceMeta">{publicEvents.length} 条 <span className={`buiChevron ${open ? 'is-open' : ''}`}>›</span></span>
    </button>
    <div className={`buiTraceBody ${open ? 'is-open' : ''}`} aria-hidden={!open}>
      {!publicEvents.length && <div className="buiTraceEmpty">{empty}</div>}
      {publicEvents.map((event, index) => <div className="buiTraceRow" key={`${event?.seq ?? index}-${index}`}>
        <span className={`buiTraceNode buiTraceNode--${eventTone(event)}`} />
        <div><strong>{eventLabel(event)}</strong><p>{publicEventDetail(event)}</p></div>
        {event?.seq !== undefined && <span className="buiTraceSeq">#{event.seq}</span>}
      </div>)}
    </div>
  </section>;
}

export function StreamingText({ text = '', sources = [], followUps = [], streaming = false, title = '回答', actions = null }) {
  const reducedMotion = useReducedMotion();
  return <section className="buiStream">
    <div className="buiStreamTop"><span>{title}</span>{streaming && <StatusChip tone="accent" pulse>正在生成</StatusChip>}</div>
    <div className={`buiStreamText ${streaming && !reducedMotion ? 'is-streaming' : ''}`}>{text || <span className="buiPlaceholder">回答会在这里出现。</span>}</div>
    {!!sources.length && <div className="buiSourceRail"><span className="buiRailLabel">{sources.length} 个来源</span>{sources.slice(0, 8).map((source, i) => <span className="buiSourcePill" key={source.id || `${source.title}-${i}`}><Icon name="source" size={13}/>{source.title || source.name || source.source || `来源 ${i + 1}`}</span>)}</div>}
    {!!followUps.length && <div className="buiFollowUps"><span className="buiRailLabel">可以继续追问</span>{followUps.map((x, i) => <button type="button" className="buiFollowButton" key={`${x}-${i}`}>{x}</button>)}</div>}
    {actions && <div className="buiStreamActions">{actions}</div>}
  </section>;
}

export function ApprovalCard({ eyebrow = '需要你确认', title, description, tone = 'neutral', children, actions, onCancel }) {
  return <section className={`buiApproval buiApproval--${tone}`}>
    <div className="buiApprovalMark"><Icon name="approval" size={18}/></div>
    <div className="buiApprovalBody"><div className="buiKicker">{eyebrow}</div><h3>{title}</h3>{description && <p>{description}</p>}{children && <div className="buiApprovalContent">{children}</div>}
      {(actions || onCancel) && <div className="buiApprovalActions">{onCancel && <button type="button" className="buiButton buiButton--quiet" onClick={onCancel}>取消</button>}{actions}</div>}
    </div>
  </section>;
}

export function ToolChips({ events = [], tools = [], label = '使用的工具' }) {
  const rows = useMemo(() => {
    if (tools.length) return tools.map((tool, i) => typeof tool === 'string' ? { name: tool, status: 'available', id: `${tool}-${i}` } : tool);
    return events.filter(event => ['tool_call', 'tool_result'].includes(event?.category || event?.type)).map((event, i) => ({
      id: `${event?.seq ?? i}-${i}`,
      name: event?.metadata?.tool_name || event?.tool_name || eventLabel(event),
      status: (event?.category || event?.type) === 'tool_result' ? 'done' : 'running',
    }));
  }, [events, tools]);
  if (!rows.length) return null;
  return <div className="buiToolRail"><span className="buiRailLabel">{label}</span>{rows.slice(-12).map(row => <span className={`buiToolChip is-${row.status || 'idle'}`} key={row.id || row.name}><span className="buiToolGlyph"><Icon name="tool" size={12}/></span>{row.name}<i /></span>)}</div>;
}

export function TaskRows({ tasks = [], empty = '没有进行中的任务。' }) {
  return <div className="buiTasks">{!tasks.length && <div className="buiEmptyRow"><Icon name="check" size={16}/><span>{empty}</span></div>}{tasks.map((task, index) => {
    const status = task.status || 'todo';
    const isDone = status === 'completed' || status === 'done';
    return <div className="buiTask" key={task.id || `${task.title}-${index}`}>
      <span className={`buiTaskIndex is-${status}`}>{isDone ? '✓' : index + 1}</span>
      <div className="buiTaskCopy"><strong>{task.title}</strong>{task.detail && <p>{task.detail}</p>}{task.metaLabel && !isDone && <div className="buiTaskMeta">{task.metaLabel}</div>}{typeof task.progress === 'number' && <div className="buiProgress"><i className={status === 'running' ? 'is-running' : ''} style={{ width: `${Math.max(0, Math.min(100, task.progress))}%` }} /></div>}</div>
      <StatusChip tone={status === 'failed' ? 'danger' : status === 'running' ? 'accent' : isDone ? 'success' : 'neutral'}>{task.metaLabel || statusLabel(status)}</StatusChip>
    </div>;
  })}</div>;
}

export function ChatPanel({ messages = [], empty = '开始一段有上下文的对话。', footer = null }) {
  return <section className="buiChat">
    <div className="buiChatMessages">{!messages.length && <div className="buiChatEmpty"><Icon name="tutor" size={28}/><span>{empty}</span></div>}{messages.map((message, index) => <div className={`buiMessage is-${message.role || 'assistant'}`} key={message.id || index}>
      <div className="buiMessageMeta"><span>{message.role === 'user' ? '你' : message.label || '导师'}</span>{message.meta && <small>{message.meta}</small>}</div>
      <div className="buiMessageBody">{message.content}</div>
    </div>)}</div>
    {footer && <div className="buiChatFooter">{footer}</div>}
  </section>;
}

export function PromptBar({ value, onChange, onSubmit, placeholder = '输入你的问题…', ariaLabel = '', disabled = false, model = '', context = [], commands = false, onMention = null, onCommand = null, hint = '', leadingIcon = '', shortcutHint = false, className = '', sendLabel = '发送', children }) {
  function keyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); onSubmit?.(); }
  }
  const canSend = !disabled && !!String(value || '').trim();
  return <div className={`buiPrompt ${className} ${disabled ? 'is-disabled' : ''}`.trim()}>
    {!!context.length && <div className="buiPromptContext">{context.map((item, i) => <span key={`${item}-${i}`}>@ {item}</span>)}</div>}
    <div className={`buiPromptEditor ${leadingIcon ? 'has-leading-icon' : ''}`}>
      {leadingIcon && <Icon name={leadingIcon} size={21}/>}<textarea rows={2} value={value} onChange={event => onChange?.(event.target.value)} onKeyDown={keyDown} placeholder={placeholder} aria-label={ariaLabel || placeholder} disabled={disabled}/>
    </div>
    <div className="buiPromptBottom"><div className="buiPromptTools">{shortcutHint && <div className="buiPromptShortcut"><kbd>↵</kbd><span>Enter 提交</span><span>Shift + Enter 换行</span></div>}{onMention && <button type="button" className="buiMiniAction" onClick={onMention} disabled={disabled} aria-label="添加来源上下文">@</button>}{onCommand && <button type="button" className="buiMiniAction" onClick={onCommand} disabled={disabled} aria-label="打开快捷指令">/</button>}{model && <span className="buiModelPill" title="当前模式">{model}<Icon name="chevron" size={10}/></span>}{commands && !onMention && !onCommand && !model && !shortcutHint && <span className="buiPromptHint">{hint || '会结合当前上下文'}</span>}{!commands && !onMention && !onCommand && !model && !shortcutHint && hint && <span className="buiPromptHint">{hint}</span>}{children}</div><button type="button" className="buiSend" onClick={onSubmit} disabled={!canSend} aria-label={sendLabel}><Icon name="arrowUp" size={18}/></button></div>
  </div>;
}

export function RecommendationCard({ title, description, confidence = null, alternatives = [], actions, eyebrow = '建议' }) {
  const pct = confidence == null ? null : Math.round(Math.max(0, Math.min(1, Number(confidence))) * 100);
  return <section className="buiRecommendation"><div className="buiKicker">{eyebrow}</div><h3>{title}</h3>{description && <p>{description}</p>}{pct !== null && <div className="buiConfidence"><div><span>建议强度</span><strong>{pct}%</strong></div><div className="buiConfidenceTrack"><i style={{ width: `${pct}%` }} /></div></div>}{!!alternatives.length && <div className="buiAlternatives"><span className="buiRailLabel">也可以这样做</span>{alternatives.map((item, i) => <div key={`${item.title || item}-${i}`}><strong>{item.title || item}</strong>{item.meta && <span>{item.meta}</span>}</div>)}</div>}{actions && <div className="buiRecommendationActions">{actions}</div>}</section>;
}

export function ContextCards({ items = [], countLabel = '', empty = '暂无上下文片段。' }) {
  return <section className="buiContext"><div className="buiContextHead"><strong>参考上下文</strong><span>{countLabel || `${items.length} 个片段`}</span></div>{!items.length && <div className="buiEmptyRow"><Icon name="file" size={18}/><span>{empty}</span></div>}{items.map((item, i) => <article className="buiContextCard" key={item.id || i}><div className="buiContextTitle"><strong>{item.title || item.label || `上下文 ${i + 1}`}</strong>{item.length && <span>{item.length}</span>}</div><p>{item.text || item.excerpt || item.content || '—'}</p><div className="buiContextSource"><Icon name="file" size={13}/><span>{item.source || item.filename || item.upstream_file_name || '本地来源'}</span>{item.location && <small>{item.location}</small>}</div></article>)}</section>;
}

export function DiffTable({ before = '', after = '', title = '建议修改', meta = '', actions = null }) {
  const beforeLines = String(before || '').split('\n');
  const afterLines = String(after || '').split('\n');
  const length = Math.max(beforeLines.length, afterLines.length);
  return <section className="buiDiff"><div className="buiDiffHead"><div><div className="buiKicker">修改对照</div><strong>{title}</strong></div>{meta && <span>{meta}</span>}</div><div className="buiDiffGrid"><div className="buiDiffLabel">修改前</div><div className="buiDiffLabel">建议版本</div>{Array.from({ length }, (_, i) => <div className="buiDiffPair" key={i}><div className="buiDiffCell is-before"><span>−</span><pre>{beforeLines[i] ?? ''}</pre></div><div className="buiDiffCell is-after"><span>+</span><pre>{afterLines[i] ?? ''}</pre></div></div>)}</div>{actions && <div className="buiDiffActions">{actions}</div>}</section>;
}

export function RecordsTable({ columns = [], rows = [], empty = '暂无记录。', rowKey = 'id', icon = null }) {
  return <div className="buiTableWrap"><table className="buiTable"><thead><tr>{columns.map(col => <th key={col.key}>{col.label}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={row[rowKey] || i}>{columns.map(col => <td key={col.key}>{col.render ? col.render(row) : row[col.key] ?? '—'}</td>)}</tr>)}{!rows.length && <tr><td colSpan={Math.max(columns.length, 1)} className="buiTableEmpty">{icon && <div><Icon name={icon} size={22}/></div>}<span>{empty}</span></td></tr>}</tbody></table></div>;
}

export function FilterTabs({ items = [], value, onChange }) {
  return <div className="buiFilters" role="tablist">{items.map(item => <button type="button" role="tab" aria-selected={value === item.value} className={value === item.value ? 'is-active' : ''} onClick={event => { event.preventDefault(); event.stopPropagation(); onChange?.(item.value); }} key={item.value}>{item.label}{item.count !== undefined && <span>{item.count}</span>}</button>)}</div>;
}

export function InsightCards({ items = [] }) {
  return <div className="buiInsights">{items.map((item, i) => <article className={`buiInsight ${item.tone ? `is-${item.tone}` : ''}`} key={item.id || i}><div className="buiInsightTop"><span>{item.label || `观察 ${i + 1}`}</span>{item.meta && <small>{item.meta}</small>}</div><strong>{item.title}</strong>{item.detail && <p>{item.detail}</p>}{item.action && <div className="buiInsightAction">{item.action}</div>}</article>)}</div>;
}

export function CodeBlock({ code = '', language = 'JSON', filename = '', compact = false }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try { await navigator.clipboard.writeText(String(code)); setCopied(true); setTimeout(() => setCopied(false), 1200); } catch {}
  }
  return <section className={`buiCode ${compact ? 'is-compact' : ''}`}><div className="buiCodeHead"><span>{filename || language}</span><button type="button" onClick={copy}>{copied ? '已复制' : '复制'}</button></div><pre><code>{String(code)}</code></pre></section>;
}

export function FineTunePanel({ title = '调整', fields = [], children, actions }) {
  return <section className="buiFineTune"><div className="buiFineTuneHead"><div><div className="buiKicker">细节检查</div><strong>{title}</strong></div><StatusChip tone="neutral">可调整</StatusChip></div><div className="buiFineTuneGrid">{fields.map((field, i) => <label key={field.key || i}><span>{field.label}</span>{field.node || <input value={field.value ?? ''} readOnly />}</label>)}</div>{children}{actions && <div className="buiFineTuneActions">{actions}</div>}</section>;
}

export function SelectionActions({ label = '选中内容可以这样处理', actions = [], input = null }) {
  return <div className="buiSelection"><div className="buiSelectionTop"><span>{label}</span>{input}</div><div className="buiSelectionActions">{actions.map((action, i) => <button type="button" onClick={action.onClick} disabled={action.disabled} className={action.primary ? 'is-primary' : ''} key={action.label || i}>{action.label}</button>)}</div></div>;
}

export function SafeSvgPreview({ svg = '', alt = '生成的信息卡' }) {
  const src = useMemo(() => svg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}` : '', [svg]);
  if (!src) return null;
  return <div className="buiSvgPreview"><img src={src} alt={alt}/></div>;
}
