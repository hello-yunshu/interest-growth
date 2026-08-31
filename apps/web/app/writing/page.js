'use client';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import { DiffTable, PromptBar, RecordsTable, SelectionActions, StatusChip, ToolChips } from '../../components/BeautifulUI';
import { WorkspaceBoard, useWorkspaceData } from '../../components/WorkspaceWidgets';
import { useRuntimeCopy } from '../../components/useRuntimeCopy';
import { engineLabel, revisionModeLabel, statusLabel, toUserMessage } from '../../lib/presentation.js';

export default function WritingPage(){
 const workspace=useWorkspaceData();
 const runtimeCopy=useRuntimeCopy();
 const [docs,setDocs]=useState([]),[id,setId]=useState(''),[bundle,setBundle]=useState(null),[msg,setMsg]=useState('');
 const [newDoc,setNewDoc]=useState({title:'学习草稿',content_markdown:''}); const [edit,setEdit]=useState({selected_text:'',instruction:'更谨慎、更通俗，但不要扩大证据范围',mode:'rewrite'}); const [busy,setBusy]=useState(false);
 async function load(){const x=await api('/writing/documents');setDocs(x.documents||[]);if(!id&&x.documents?.length)setId(x.documents[0].id)} async function detail(x=id){if(x)setBundle(await api(`/writing/documents/${x}`))}
 useEffect(()=>{load().catch(e=>setMsg(toUserMessage(e)))},[]);useEffect(()=>{detail(id).catch(e=>setMsg(toUserMessage(e)))},[id]);
 async function create(e){e.preventDefault();if(busy)return;setBusy(true);try{const x=await api('/writing/documents',{method:'POST',body:JSON.stringify(newDoc)});await load();setId(x.id);setMsg('草稿已保存。')}catch(e){setMsg(toUserMessage(e))}finally{setBusy(false)}}
 async function save(){if(busy||!id||!bundle)return;setBusy(true);try{const x=await api(`/writing/documents/${id}`,{method:'PUT',body:JSON.stringify({content_markdown:bundle.document.content_markdown,title:bundle.document.title})});setBundle(current=>({...current,document:{...x,title:current.document.title,content_markdown:current.document.content_markdown}}));setMsg('正文已保存。')}catch(e){setMsg(toUserMessage(e))}finally{setBusy(false)}}
 async function propose(mode=edit.mode){if(busy||!id||!edit.selected_text.trim())return;setBusy(true);try{const r=await api(`/writing/documents/${id}/revisions`,{method:'POST',body:JSON.stringify({...edit,mode,tools:[]})});await detail();setEdit(v=>({...v,mode}));setMsg(`修改提案已提出：${engineLabel(r.engine)}。不会自动覆盖正文。`)}catch(e){setMsg(toUserMessage(e))}finally{setBusy(false)}}
 async function decide(r,accept){if(busy)return;setBusy(true);try{await api(`/writing/revisions/${r.id}/decide`,{method:'POST',body:JSON.stringify({accept})});await detail();setMsg(accept?'已接受修改提案。':'已拒绝修改提案，正文未变。')}catch(e){setMsg(toUserMessage(e))}finally{setBusy(false)}}
 const pending=useMemo(()=>bundle?.revisions?.find(r=>r.status==='proposed')||null,[bundle]);
 const docRows=docs.map(d=>({...d,status:d.id===id?'open':'saved'}));
 return <div className="stack">
   <section className="pageLead"><div><div className="eyebrow">共写</div><h1>先写出自己的意思，再一起把它说清楚。</h1><p className="muted">选择一段文字，提出改写、缩短或展开。每次修改都先给你对照，不会直接覆盖正文。</p></div><StatusChip tone={pending?'warning':'success'}>{pending?'有修改待确认':'正文已保存'}</StatusChip></section>
   {msg&&<p className="notice">{msg}</p>}
   <WorkspaceBoard pageId="writing" data={workspace.data} loading={workspace.loading} compact title="写作工作台"/>
   <div className="grid two"><section className="card"><div className="cardHeader"><h2>文档</h2><StatusChip>{docs.length}</StatusChip></div><form className="stack" onSubmit={create}><input aria-label="草稿标题" value={newDoc.title} onChange={e=>setNewDoc({...newDoc,title:e.target.value})}/><textarea aria-label="草稿正文" value={newDoc.content_markdown} onChange={e=>setNewDoc({...newDoc,content_markdown:e.target.value})} placeholder="初稿"/><button disabled={busy}>{busy?'正在保存…':'建立草稿'}</button></form><div className="sectionTop"><RecordsTable columns={[{key:'title',label:'文档'},{key:'status',label:'状态',render:r=><button className="tableLink" onClick={()=>setId(r.id)}>{statusLabel(r.status)}</button>}]} rows={docRows}/></div></section>
   <section className="card"><div className="cardHeader"><h2>修改选中段落</h2><ToolChips tools={[{name:'主草稿',status:'done'},{name:'修改提案',status:pending?'running':'available'}]}/></div><textarea value={edit.selected_text} onChange={e=>setEdit({...edit,selected_text:e.target.value})} placeholder="粘贴需要修改的一段"/><PromptBar value={edit.instruction} onChange={v=>setEdit({...edit,instruction:v})} onSubmit={()=>propose(edit.mode)} disabled={busy||!id||!edit.selected_text.trim()} placeholder="说明想怎么改…" model={revisionModeLabel(edit.mode)} commands={false}/><SelectionActions label="想怎么处理" actions={['rewrite','shorten','expand'].map(mode=>({label:revisionModeLabel(mode),onClick:()=>propose(mode),primary:mode===edit.mode,disabled:busy||!id||!edit.selected_text.trim()}))}/></section></div>
   {bundle&&<section className="card"><div className="cardHeader"><div><div className="eyebrow">当前正文</div><h2>{bundle.document.title}</h2></div><button className="secondary small" onClick={save} disabled={busy}>{busy?'正在保存…':'保存手动修改'}</button></div><input aria-label="当前文档标题" value={bundle.document.title} onChange={e=>setBundle({...bundle,document:{...bundle.document,title:e.target.value}})}/><textarea aria-label="当前文档正文" className="documentEditor" value={bundle.document.content_markdown} onChange={e=>setBundle({...bundle,document:{...bundle.document,content_markdown:e.target.value}})}/></section>}
   {bundle?.revisions?.length>0&&<section className="stack"><div className="sectionTitle"><div><div className="eyebrow">修改记录</div><h2>每次 AI 修改都有决策记录</h2></div></div>{bundle.revisions.map(r=><DiffTable key={r.id} before={r.selected_text} after={r.replacement_text} title={`${revisionModeLabel(r.mode)} · ${statusLabel(r.status)}`} meta={engineLabel(r.engine)} actions={r.status==='proposed'?<><button onClick={()=>decide(r,true)} disabled={busy}>{busy?'处理中…':'接受修改'}</button><button className="ghost" onClick={()=>decide(r,false)} disabled={busy}>{busy?'处理中…':'拒绝修改'}</button></>:<StatusChip tone={r.status==='accepted'?'success':'neutral'}>{statusLabel(r.status)}</StatusChip>}/>)}</section>}
 </div>
}
