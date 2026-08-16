'use client';
import { useEffect, useMemo, useState } from 'react';
import { api, openExternalUrl } from '../../lib/api';
import { ApprovalCard, FilterTabs, PixelLoader, PromptBar, RecommendationCard, StatusChip, StreamingText, ToolChips } from '../../components/BeautifulUI';
import { WorkspaceBoard, useWorkspaceData } from '../../components/WorkspaceWidgets';

export default function ResearchPage() {
  const workspace = useWorkspaceData();
  const [topics, setTopics] = useState([]);
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [selectedKbIds, setSelectedKbIds] = useState([]);
  const [useSkills, setUseSkills] = useState(true);
  const [topicId, setTopicId] = useState('');
  const [question, setQuestion] = useState('');
  const [depth, setDepth] = useState('normal');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sources, setSources] = useState([]);
  const [evidence, setEvidence] = useState([]);
  const [claims, setClaims] = useState([]);
  const [skepticReviews, setSkepticReviews] = useState({});
  const [sourceForm, setSourceForm] = useState({ title:'', canonical_url:'', source_type:'paper' });
  const [evidenceForm, setEvidenceForm] = useState({ source_id:'', excerpt_or_summary:'', limitations:'', supports_claim:true, verification_state:'unverified' });
  const [claimForm, setClaimForm] = useState({ statement:'', limitations:'', confidence:0.5, publishability:'internal_only' });
  const [supportIds, setSupportIds] = useState([]);
  const [counterIds, setCounterIds] = useState([]);
  const [revision, setRevision] = useState({ claim_id:'', statement:'', limitations:'', reason_for_revision:'', publishability:'supported_with_caution' });
  const [message, setMessage] = useState('');
  const [reverification, setReverification] = useState([]);
  const [invalidateDraft, setInvalidateDraft] = useState(null);
  const [ledgerTab, setLedgerTab] = useState('all');

  async function loadTopics() {
    const t = await api('/topics'); setTopics(t.topics || []);
    if (!topicId && t.topics?.length) setTopicId(t.topics[0].id);
  }
  async function loadWorkspace(id=topicId) {
    if (!id) return;
    const [s,e,c] = await Promise.all([api(`/sources?topic_id=${id}`), api('/evidence'), api(`/claims?topic_id=${id}`)]);
    setSources(s.sources || []);
    const sourceIds = new Set((s.sources || []).map(x=>x.id));
    setEvidence((e.evidence || []).filter(x=>sourceIds.has(x.source_id)));
    setClaims(c.claims || []);
  }
  useEffect(()=>{loadTopics().catch(()=>{});api('/knowledge/bases').then(x=>setKnowledgeBases(x.knowledge_bases||[])).catch(()=>{});},[]);
  useEffect(()=>{loadWorkspace(topicId).catch(()=>{});},[topicId]);
  useEffect(()=>{api('/claims/reverification?stale_days=180').then(x=>setReverification(x.claims||[])).catch(()=>{});},[claims.length]);

  const selectedTopic = useMemo(()=>topics.find(t=>t.id===topicId),[topics,topicId]);

  async function run(e) {
    e?.preventDefault?.(); setBusy(true); setMessage('');
    try { setResult(await api('/research/run', { method:'POST', body:JSON.stringify({topic_id: topicId || null, question, depth, knowledge_base_ids:selectedKbIds, use_domain_skills:useSkills}) })); await loadWorkspace(); }
    catch (err) { setMessage(err.message); }
    finally { setBusy(false); }
  }
  async function addSource(e) {
    e.preventDefault();
    await api('/sources',{method:'POST',body:JSON.stringify({...sourceForm,topic_id:topicId || null})});
    setSourceForm({title:'',canonical_url:'',source_type:'paper'}); setMessage('来源已加入，需人工打开原文核验后再标记 verified。'); await loadWorkspace();
  }
  async function verifySource(id) { await api(`/sources/${id}/verify`,{method:'POST'}); setMessage('已记录人工核验来源。'); await loadWorkspace(); }
  async function invalidateSource() {
    if (!invalidateDraft?.reason?.trim()) return;
    try {
      const data = await api(`/sources/${invalidateDraft.id}/invalidate`, {method:'POST', body:JSON.stringify({reason:invalidateDraft.reason})});
      setMessage(`已撤销来源核验；${data.affected_claim_ids?.length||0} 条 Claim 已进入再核验。`);
      setInvalidateDraft(null);
      await loadWorkspace();
      const queue = await api('/claims/reverification?stale_days=180'); setReverification(queue.claims||[]);
    } catch(err) { setMessage(err.message); }
  }
  async function addEvidence(e) {
    e.preventDefault();
    try { await api('/evidence',{method:'POST',body:JSON.stringify(evidenceForm)}); setEvidenceForm({...evidenceForm,excerpt_or_summary:'',limitations:''}); setMessage('Evidence 已保存。'); await loadWorkspace(); }
    catch(err){setMessage(err.message);}
  }
  function toggle(id, list, setter) { setter(list.includes(id) ? list.filter(x=>x!==id) : [...list,id]); }
  function toggleKb(id){setSelectedKbIds(selectedKbIds.includes(id)?selectedKbIds.filter(x=>x!==id):[...selectedKbIds,id]);}
  async function addClaim(e) {
    e.preventDefault();
    await api('/claims',{method:'POST',body:JSON.stringify({...claimForm,topic_id:topicId,supporting_evidence:supportIds,contradicting_evidence:counterIds})});
    setClaimForm({statement:'',limitations:'',confidence:0.5,publishability:'internal_only'}); setSupportIds([]); setCounterIds([]); setMessage('Claim v1 已建立。'); await loadWorkspace();
  }
  async function skepticPass(id){ try {const data=await api(`/claims/${id}/skeptic-pass`,{method:'POST'});setSkepticReviews(prev=>({...prev,[id]:data.review}));setMessage(`Skeptic Pass：${data.review.status}。它不会替代人工核验。`);}catch(err){setMessage(err.message);} }
  async function verifyClaim(id){ try {await api(`/claims/${id}/verify`,{method:'POST'});setMessage('Claim 已记录为 human_verified。');await loadWorkspace();}catch(err){setMessage(err.message);} }
  function startRevision(item){setRevision({claim_id:item.claim.id,statement:item.current_version?.statement||'',limitations:item.current_version?.limitations||'',reason_for_revision:'',publishability:item.claim.publishability||'supported_with_caution'});setSupportIds(item.current_version?.supporting_evidence||[]);setCounterIds(item.current_version?.contradicting_evidence||[]);}
  async function reviseClaim(e){e.preventDefault();await api(`/claims/${revision.claim_id}/revisions`,{method:'POST',body:JSON.stringify({statement:revision.statement,limitations:revision.limitations,reason_for_revision:revision.reason_for_revision,publishability:revision.publishability,supporting_evidence:supportIds,contradicting_evidence:counterIds})});setMessage('新 ClaimVersion 已保存，旧版本仍保留；上一版本的核验状态已失效，请重新运行 Skeptic Pass 并人工核验。');setRevision({...revision,claim_id:'',statement:'',limitations:'',reason_for_revision:''});setSupportIds([]);setCounterIds([]);await loadWorkspace();}

  return <div className="stack">
    <section className="pageLead"><div><div className="eyebrow">研究</div><h1>把“我听说过”，慢慢变成有依据的理解。</h1><p className="muted">研究结果只是候选理解。核对来源、摘出证据，再决定自己愿意承担怎样的结论。</p></div><StatusChip tone={busy?'accent':'neutral'} pulse={busy}>{busy?'正在研究':'由你确认'}</StatusChip></section>
    <WorkspaceBoard pageId="research" data={workspace.data} loading={workspace.loading} compact title="研究工作台"/>
    <div className="card">
      <div className="fieldGroup">
        <label>当前 Topic</label>
        <select aria-label="当前 Topic" value={topicId} onChange={e=>setTopicId(e.target.value)}><option value="">不绑定 Topic</option>{topics.map(t=><option key={t.id} value={t.id}>{t.title}</option>)}</select>
        {!topics.length && <p className="help">先在 Curiosity 把一个问题转为 Topic，再建立长期 Claim/Evidence。</p>}
      </div>
      <div className="subcard sectionTop">
        <strong>Native research context</strong>
        <ToolChips tools={[...selectedKbIds.map(id=>({id,name:knowledgeBases.find(k=>k.id===id)?.name||id,status:'available'})), ...(useSkills?[{name:'current domain skills',status:'available'}]:[])]}/>
        <p className="muted">选择知识库后，Deep Research 优先检索本地可重建索引；当前 Domain Skills 由 Native Core 直接装配。</p>
        <div className="fieldRow" style={{marginTop:8}}>
          <div><div className="fieldLabel">Knowledge Bases</div><div className="checkGrid">{knowledgeBases.map(k=><label className="check" key={k.id}><input type="checkbox" checked={selectedKbIds.includes(k.id)} onChange={()=>toggleKb(k.id)}/><span>{k.name}</span></label>)}</div></div>
          <div><div className="fieldLabel">Domain Skills</div><label className="check"><input type="checkbox" checked={useSkills} onChange={e=>setUseSkills(e.target.checked)}/><span>使用当前 Interest Area 已配置的 Domain Skills</span></label></div>
        </div>
      </div>
      <div className="stack sectionTop"><div className="row"><select aria-label="研究深度" className="compactSelect" value={depth} onChange={e=>setDepth(e.target.value)}><option value="light">Light</option><option value="normal">Normal</option><option value="deep">Deep</option></select><span className="muted">先生成候选理解，再进入人工证据链。</span></div><PromptBar value={question} onChange={setQuestion} onSubmit={run} disabled={busy} placeholder="输入需要研究的问题…" model={depth.charAt(0).toUpperCase()+depth.slice(1)} context={selectedKbIds.map(id=>knowledgeBases.find(k=>k.id===id)?.name).filter(Boolean)}/></div>
      {message && <p className="notice">{message}</p>}
    </div>

    {busy && <PixelLoader label="Research 正在建立候选理解" detail={depth}/>}
    {result && <div className="grid two"><StreamingText title={result.engine_status?.engine||'Research result'} text={result.result?.report||''} sources={result.result?.sources||result.result?.citations||[]} streaming={false} actions={result.engine_status?.degraded?<StatusChip tone="warning">degraded · {result.engine_status.reason}</StatusChip>:<StatusChip tone="success">candidate ready</StatusChip>}/><RecommendationCard eyebrow="Evidence boundary" title="Research 结果不能直接成为 Evidence" description="先定位原始 Source，再摘录/总结为 Evidence，最后把 Claim 与支持/相反证据显式关联。" confidence={0.96} alternatives={(result.result?.limitations||[]).slice(0,4).map(x=>({title:x}))}/></div>}

    <section className="card"><div className="cardHeader"><div><div className="eyebrow">证据账本</div><h2>人工维护的研究事实链</h2></div></div><FilterTabs value={ledgerTab} onChange={setLedgerTab} items={[{value:'all',label:'全部'},{value:'sources',label:'来源',count:sources.length},{value:'evidence',label:'证据',count:evidence.length},{value:'claims',label:'主张',count:claims.length},{value:'reverify',label:'待复核',count:reverification.length}]}/></section>
    <div className="grid two">
      <div className="card" hidden={ledgerTab!=='all'&&ledgerTab!=='sources'}><h2>1 · Source</h2><p className="muted">AI 找到的只是 candidate。只有你核对原文后，才点“人工核验”。</p><form className="stack" onSubmit={addSource}><input value={sourceForm.title} onChange={e=>setSourceForm({...sourceForm,title:e.target.value})} placeholder="来源标题" required/><input value={sourceForm.canonical_url} onChange={e=>setSourceForm({...sourceForm,canonical_url:e.target.value})} placeholder="DOI / URL"/><select aria-label="来源类型" value={sourceForm.source_type} onChange={e=>setSourceForm({...sourceForm,source_type:e.target.value})}><option value="paper">论文</option><option value="book">书籍</option><option value="web">网页</option><option value="report">报告</option></select><button>加入来源</button></form><div className="list sectionTop">{sources.map(s=><div className="item" key={s.id}><strong>{s.title}</strong><div className="muted">{s.source_type} · {s.verified?'human verified':'待核验'}</div>{s.canonical_url && <SourceLink value={s.canonical_url}/>}<div className="row">{!s.verified && <button className="secondary small" onClick={()=>verifySource(s.id)}>我已核对原文</button>}{s.verified && <button className="ghost small" onClick={()=>setInvalidateDraft({id:s.id,title:s.title,reason:'来源被替换、撤回或需要重新核对原文'})}>撤销核验</button>}</div></div>)}</div></div>

      <div className="card" hidden={ledgerTab!=='all'&&ledgerTab!=='evidence'}><h2>2 · Evidence</h2><p className="muted">Evidence 必须绑定 Source；未核验 Source 不能直接升级为 human_verified。</p><form className="stack" onSubmit={addEvidence}><select aria-label="选择证据来源" value={evidenceForm.source_id} onChange={e=>setEvidenceForm({...evidenceForm,source_id:e.target.value})} required><option value="">选择来源</option>{sources.map(s=><option key={s.id} value={s.id}>{s.verified?'✓ ':''}{s.title}</option>)}</select><textarea value={evidenceForm.excerpt_or_summary} onChange={e=>setEvidenceForm({...evidenceForm,excerpt_or_summary:e.target.value})} placeholder="摘录或你核对后的证据摘要" required/><textarea value={evidenceForm.limitations} onChange={e=>setEvidenceForm({...evidenceForm,limitations:e.target.value})} placeholder="限制 / 适用边界"/><select aria-label="证据核验状态" value={evidenceForm.verification_state} onChange={e=>setEvidenceForm({...evidenceForm,verification_state:e.target.value})}><option value="unverified">未核验</option><option value="source_identified">已定位原始来源</option><option value="human_verified">我已人工核验</option></select><label className="check"><input type="checkbox" checked={evidenceForm.supports_claim} onChange={e=>setEvidenceForm({...evidenceForm,supports_claim:e.target.checked})}/> 默认作为支持证据</label><button>保存 Evidence</button></form><div className="list sectionTop">{evidence.map(ev=><div className="item" key={ev.id}><span className="pill">{ev.verification_state}</span><p>{ev.excerpt_or_summary}</p>{ev.limitations && <div className="muted">边界：{ev.limitations}</div>}</div>)}</div></div>
    </div>

    {reverification.length > 0 && (ledgerTab==='all'||ledgerTab==='reverify') && <div className="card"><h2>再核验队列</h2><p className="muted">这里不是说 Claim 已经“错误”，而是当前证据链或核验时间要求你重新查看。Source 撤销核验会自动传播到这里。</p><div className="list">{reverification.filter(x=>!topicId || x.claim.topic_id===topicId).map(x=><div className="item" key={x.claim.id}><strong>{x.current_version?.statement||'缺少当前版本'}</strong><div className="row sectionTop">{x.reasons.map(r=><span className="pill" key={r}>{r}</span>)}</div></div>)}</div></div>}

    <div className="card" hidden={ledgerTab!=='all'&&ledgerTab!=='claims'}><h2>3 · Claim Ledger</h2><p className="muted">选择支持与相反 Evidence，再写你目前愿意承担的表述。Claim 修订不会覆盖旧版本。</p>
      {topicId ? <form className="stack" onSubmit={addClaim}><textarea value={claimForm.statement} onChange={e=>setClaimForm({...claimForm,statement:e.target.value})} placeholder="当前 Claim" required/><textarea value={claimForm.limitations} onChange={e=>setClaimForm({...claimForm,limitations:e.target.value})} placeholder="必须同时说出的限制"/><div className="grid two"><EvidencePicker title="支持证据" evidence={evidence} selected={supportIds} toggle={id=>toggle(id,supportIds,setSupportIds)}/><EvidencePicker title="相反 / 边界证据" evidence={evidence} selected={counterIds} toggle={id=>toggle(id,counterIds,setCounterIds)}/></div><div className="row"><select aria-label="可发布性" style={{maxWidth:260}} value={claimForm.publishability} onChange={e=>setClaimForm({...claimForm,publishability:e.target.value})}><option value="internal_only">仅内部学习</option><option value="limited">证据有限</option><option value="supported_with_caution">可谨慎表达</option><option value="stable">相对稳定</option><option value="controversial">有争议</option><option value="not_publishable">不可公开</option></select><button>建立 Claim v1</button></div></form> : <div className="notice">Claim 必须属于一个 Topic。</div>}
      <div className="list sectionTop">{claims.map(item=><div className="item" key={item.claim.id}><div className="row"><span className="pill">{item.claim.verification_state}</span><span className="pill">{item.claim.publishability}</span><span className="muted">v{item.current_version?.version}</span></div><h3>{item.current_version?.statement}</h3>{item.current_version?.limitations && <p className="muted">边界：{item.current_version.limitations}</p>}<div className="row"><button className="secondary small" onClick={()=>startRevision(item)}>修订 Claim</button><button className="ghost small" onClick={()=>skepticPass(item.claim.id)}>Skeptic Pass</button><button className="ghost small" onClick={()=>verifyClaim(item.claim.id)}>核验当前版本</button></div>{skepticReviews[item.claim.id] && <div className="notice sectionTop"><strong>Skeptic Pass · {skepticReviews[item.claim.id].status}</strong>{!skepticReviews[item.claim.id].issues?.length && <p>未发现结构性警告；仍需人工核对原文与当前版本。</p>}<ul>{(skepticReviews[item.claim.id].issues||[]).map((issue,i)=><li key={i}><strong>{issue.severity}</strong> · {issue.message}</li>)}</ul></div>}</div>)}</div>
    </div>

    {invalidateDraft && <ApprovalCard eyebrow="Source verification" title={`撤销核验：${invalidateDraft.title}`} description="这会把受影响 Claim 推入再核验队列，不代表 Claim 自动变成错误。请留下可审计的原因。" tone="warning" onCancel={()=>setInvalidateDraft(null)} actions={<button onClick={invalidateSource} disabled={!invalidateDraft.reason.trim()}>确认撤销核验</button>}><textarea value={invalidateDraft.reason} onChange={e=>setInvalidateDraft({...invalidateDraft,reason:e.target.value})}/></ApprovalCard>}

    {revision.claim_id && <div className="card"><h2>修订 Claim</h2><p className="muted">正在建立新版本；旧版本和修订原因会永久保留。</p><form className="stack" onSubmit={reviseClaim}><textarea value={revision.statement} onChange={e=>setRevision({...revision,statement:e.target.value})} required/><textarea value={revision.limitations} onChange={e=>setRevision({...revision,limitations:e.target.value})} placeholder="限制"/><input value={revision.reason_for_revision} onChange={e=>setRevision({...revision,reason_for_revision:e.target.value})} placeholder="为什么修订？" required/><div className="grid two"><EvidencePicker title="支持证据" evidence={evidence} selected={supportIds} toggle={id=>toggle(id,supportIds,setSupportIds)}/><EvidencePicker title="相反 / 边界证据" evidence={evidence} selected={counterIds} toggle={id=>toggle(id,counterIds,setCounterIds)}/></div><div className="row"><button>保存新版本</button><button type="button" className="ghost" onClick={()=>setRevision({...revision,claim_id:''})}>取消</button></div></form></div>}
  </div>;
}

function EvidencePicker({title,evidence,selected,toggle}){
  return <div className="subcard"><strong>{title}</strong>{!evidence.length && <p className="muted">还没有 Evidence。</p>}{evidence.map(ev=><label className="check" key={ev.id}><input type="checkbox" checked={selected.includes(ev.id)} onChange={()=>toggle(ev.id)}/><span>{ev.excerpt_or_summary.slice(0,90)}{ev.excerpt_or_summary.length>90?'…':''} <small>({ev.verification_state})</small></span></label>)}</div>;
}

function SourceLink({value}){
  let safe='';
  try { const url=new URL(value); if(['http:','https:'].includes(url.protocol)) safe=url.toString(); } catch {}
  return safe ? <button type="button" className="textLink linkButton" onClick={()=>openExternalUrl(safe)}>打开原始链接 ↗</button> : <span className="muted">{value}</span>;
}
