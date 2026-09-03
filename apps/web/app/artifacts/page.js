'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '../../lib/api';
import { RecordsTable, StatusChip } from '../../components/BeautifulUI';
import { statusLabel, toUserMessage } from '../../lib/presentation.js';

export default function ArtifactsPage() {
  const [rows, setRows] = useState([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    const result = await api('/artifacts');
    setRows(result.artifacts || []);
  }

  useEffect(() => { load().catch(error => setMessage(toUserMessage(error))); }, []);

  async function archive(id) {
    if (busy) return;
    setBusy(true);
    try { await api(`/artifacts/${id}/archive`, { method: 'POST' }); await load(); }
    catch (error) { setMessage(toUserMessage(error)); }
    finally { setBusy(false); }
  }

  return <div className="stack">
    <section className="pageLead"><div><div className="eyebrow">表达成果</div><h1>每一份作品，都保留它的依据和审核状态。</h1><p className="muted">详情页只展示本地保存的内容；批准、导出和归档都是明确的人工动作。</p></div><StatusChip tone="success">本地事实来源</StatusChip></section>
    {message && <p className="notice">{message}</p>}
    <section className="card"><RecordsTable columns={[
      { key: 'title', label: '作品', render: row => <Link className="tableLink" href={`/artifacts/detail?id=${encodeURIComponent(row.id)}`}>{row.title || '未命名作品'}</Link> },
      { key: 'kind', label: '类型' },
      { key: 'status', label: '状态', render: row => <StatusChip tone={row.approved_at ? 'success' : 'warning'}>{row.approved_at ? '已批准' : statusLabel(row.status)}</StatusChip> },
      { key: 'action', label: '操作', render: row => <button className="tableLink" disabled={busy} onClick={() => archive(row.id)}>归档</button> },
    ]} rows={rows} empty="还没有表达作品。先在表达页生成一个待审核发布包。" /></section>
  </div>;
}
