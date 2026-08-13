import { api } from './api';

const TYPE_META = {
  note: { label: '学习笔记', icon: 'pen', href: '/learning', color: '#d97735' },
  practice: { label: '练习记录', icon: 'target', href: '/learning', color: '#6f8f72' },
  activity: { label: '学习活动', icon: 'activity', href: '/learning', color: '#8b7bb5' },
  mastery: { label: '掌握证据', icon: 'check', href: '/learning', color: '#397a63' },
  research: { label: '研究结论', icon: 'search', href: '/research', color: '#5d83a6' },
  artifact: { label: '表达作品', icon: 'spark', href: '/content', color: '#a56b72' },
  writing: { label: '写作草稿', icon: 'file', href: '/writing', color: '#8c7357' },
  book: { label: '书稿', icon: 'book', href: '/book', color: '#6b759b' },
};

const safeArray = value => Array.isArray(value) ? value : [];
const asDate = row => row?.updated_at || row?.created_at || null;

function output(type, row, title, detail = '') {
  const meta = TYPE_META[type];
  return {
    id: `${type}:${row.id}`,
    recordId: row.id,
    type,
    ...meta,
    title: title || meta.label,
    detail,
    date: asDate(row),
    raw: row,
  };
}

export function normalizeClaimRecord(row = {}) {
  const claim = row.claim || row;
  const version = row.current_version || {};
  return {
    ...claim,
    id: claim.id || version.claim_id || row.id,
    statement: version.statement || row.current_statement || row.statement || '',
    limitations: version.limitations ?? row.limitations ?? '',
    updated_at: claim.updated_at || version.created_at || row.updated_at,
    created_at: claim.created_at || version.created_at || row.created_at,
    current_version: version,
  };
}

export async function loadWorkspaceData() {
  const requests = {
    dashboard: api('/dashboard'),
    notes: api('/notes'),
    practice: api('/practice'),
    activities: api('/activities'),
    mastery: api('/mastery-evidence'),
    claims: api('/claims'),
    sources: api('/sources'),
    artifacts: api('/artifacts'),
    writing: api('/writing/documents'),
    books: api('/living-books'),
    growth: api('/growth/events?limit=300'),
    sessions: api('/tutor/sessions'),
    topics: api('/topics'),
  };
  const entries = await Promise.all(Object.entries(requests).map(async ([key, promise]) => {
    try { return [key, await promise, null]; }
    catch (error) { return [key, null, error]; }
  }));
  const data = Object.fromEntries(entries.map(([key, value]) => [key, value || {}]));
  const errors = entries.filter(([, , error]) => error);
  const outputs = [
    ...safeArray(data.notes.notes).map(row => output('note', row, row.title, cleanExcerpt(row.body_markdown))),
    ...safeArray(data.practice.practice).flatMap(bundle => safeArray(bundle.attempts).map(row => output('practice', row, bundle.item?.prompt, row.feedback || cleanExcerpt(row.answer)))),
    ...safeArray(data.activities.activities).filter(row => row.status === 'completed').map(row => output('activity', row, row.objective || activityName(row.activity_type), row.observation || row.self_assessment || row.feedback)),
    ...safeArray(data.mastery.evidence).map(row => output('mastery', row, '一条掌握证据', row.note)),
    ...safeArray(data.claims.claims).map(row => {
      const claim = normalizeClaimRecord(row);
      return output('research', claim, claim.statement || '研究结论', claim.limitations);
    }),
    ...safeArray(data.artifacts.artifacts).map(row => output('artifact', row, row.title, row.approved_at ? '已经人工确认' : '等待你确认')),
    ...safeArray(data.writing.documents).map(row => output('writing', row, row.title, cleanExcerpt(row.content_markdown))),
    ...safeArray(data.books.books).map(row => output('book', row, row.title, row.intent)),
  ].sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));

  const timeline = [
    ...outputs.map(item => ({ date: item.date, kind: item.type, weight: 1 })),
    ...safeArray(data.growth.events).map(row => ({ date: row.created_at, kind: 'growth', weight: 1 })),
  ].filter(item => item.date);

  return {
    ...data,
    outputs,
    timeline,
    errors,
    offline: errors.length === Object.keys(requests).length,
  };
}

export function outputTypeMeta(type) { return TYPE_META[type] || TYPE_META.activity; }

export function activityName(type = '') {
  return ({ practice: '完成一次练习', observation: '记录一次观察', project: '推进一个项目', reading: '完成一次阅读', creation: '完成一次创作' })[type] || '完成一次学习活动';
}

export function cleanExcerpt(value = '', limit = 86) {
  const text = String(value || '').replace(/[#*_>`\[\]()~-]/g, ' ').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

export function formatRelativeDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.round((today - target) / 86400000);
  const time = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
  if (days === 0) return `今天 ${time}`;
  if (days === 1) return `昨天 ${time}`;
  if (days > 1 && days < 7) return `${days} 天前`;
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date);
}

export function buildHeatmap(timeline, weeks = 26) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const end = new Date(today);
  end.setDate(end.getDate() + (6 - end.getDay()));
  const start = new Date(end);
  start.setDate(start.getDate() - (weeks * 7 - 1));
  const counts = new Map();
  timeline.forEach(item => {
    const date = new Date(item.date);
    if (Number.isNaN(date.getTime())) return;
    const key = localDateKey(date);
    counts.set(key, (counts.get(key) || 0) + (item.weight || 1));
  });
  const days = [];
  for (let cursor = new Date(start); cursor <= end; cursor.setDate(cursor.getDate() + 1)) {
    const date = new Date(cursor);
    const count = counts.get(localDateKey(date)) || 0;
    days.push({ date, key: localDateKey(date), count, level: count === 0 ? 0 : count === 1 ? 1 : count <= 3 ? 2 : count <= 5 ? 3 : 4 });
  }
  return Array.from({ length: weeks }, (_, index) => days.slice(index * 7, index * 7 + 7));
}

export function buildWeeklyTrend(timeline, weeks = 10) {
  const heatmap = buildHeatmap(timeline, weeks);
  return heatmap.map((week, index) => ({
    name: index === heatmap.length - 1 ? '本周' : `${heatmap.length - index - 1} 周前`,
    count: week.reduce((sum, day) => sum + day.count, 0),
  }));
}

export function buildOutputDistribution(outputs) {
  return Object.entries(outputs.reduce((map, item) => ({ ...map, [item.type]: (map[item.type] || 0) + 1 }), {}))
    .map(([type, value]) => ({ name: outputTypeMeta(type).label, type, value, color: outputTypeMeta(type).color }));
}

function localDateKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}
