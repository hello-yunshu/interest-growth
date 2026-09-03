'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { api, downloadArtifact } from '../../lib/api';
import { CodeBlock, SafeSvgPreview, StatusChip } from '../../components/BeautifulUI';
import { statusLabel, toUserMessage } from '../../lib/presentation.js';

export default function ArtifactDetailClient({ usePathParams = false, artifactId = '' }) {
  const params = useParams(); const router = useRouter(); const id = usePathParams ? params?.id : artifactId;
  const [bundle, setBundle] = useState(null); const [message, setMessage] = useState(''); const [busy, setBusy] = useState(false);
  async function load() { if (id) setBundle(await api(`/artifacts/${id}`)); }
  useEffect(() => { load().catch(error => setMessage(toUserMessage(error))); }, [id]);
  async function action(path) { if (busy) return; setBusy(true); try { await api(`/artifacts/${id}/${path}`, { method: 'POST' }); await load(); setMessage('已保存。'); } catch (error) { setMessage(toUserMessage(error)); } finally { setBusy(false); } }
  async function remove() { if (busy) return; setBusy(true); try { await api(`/artifacts/${id}`, { method: 'DELETE' }); router.push('/artifacts'); } catch (error) { setMessage(toUserMessage(error)); setBusy(false); } }
  if (!id) return <div className="card"><p className="muted">缺少作品 ID。</p></div>;
  if (!bundle) return <div className="card"><p className="muted">{message || '正在读取作品…'}</p></div>;
  const artifact = bundle.artifact; const svg = artifact.metadata_json?.mime_type === 'image/svg+xml' && bundle.content;
  return <div className="stack"><section className="pageLead"><div><div className="eyebrow">作品详情 · {artifact.kind}</div><h1>{artifact.title || '未命名作品'}</h1><p className="muted">状态：{artifact.approved_at ? '已批准' : statusLabel(artifact.status)} · 依据和风险仍需人工检查。</p></div><StatusChip tone={artifact.approved_at ? 'success' : 'warning'}>{artifact.approved_at ? '已批准' : '待审核'}</StatusChip></section>{message && <p className="notice">{message}</p>}<section className="card">{svg ? <SafeSvgPreview svg={svg}/> : <CodeBlock language="markdown" filename={`${artifact.kind}.md`} code={bundle.content || '该作品没有可直接预览的文本内容。'}/>}</section><section className="card"><h2>来源与审核</h2><p className="muted">{bundle.grounding_refs?.length || 0} 条本地依据引用。批准不会触发外部发布。</p><div className="row"><button onClick={() => action('approve')} disabled={busy || Boolean(artifact.approved_at)}>批准</button><button className="secondary" onClick={() => downloadArtifact(id)} disabled={busy}>导出 ZIP</button><button className="ghost" onClick={() => action(artifact.status === 'archived' ? 'restore' : 'archive')} disabled={busy}>{artifact.status === 'archived' ? '恢复' : '归档'}</button><button className="ghost" onClick={remove} disabled={busy}>删除</button></div></section></div>;
}
