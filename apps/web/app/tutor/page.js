'use client';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import { ActivityTrace, ApprovalCard, ChatPanel, PixelLoader, PromptBar, StatusChip, StreamingText, ToolChips } from '../../components/BeautifulUI';
import { WorkspaceBoard, useWorkspaceData } from '../../components/WorkspaceWidgets';
import { capabilityLabel, domainDisplayName, statusLabel, toUserMessage } from '../../lib/presentation.js';
import { useCapabilityAvailability } from '../../lib/capabilities.js';

export default function TutorPage(){
  const workspace=useWorkspaceData();
  const availability=useCapabilityAvailability();
  const [topics,setTopics]=useState([]), [concepts,setConcepts]=useState([]), [bases,setBases]=useState([]), [personas,setPersonas]=useState([]), [sessions,setSessions]=useState([]);
  const [domain,setDomain]=useState(null), [sessionId,setSessionId]=useState(''), [turns,setTurns]=useState([]), [events,setEvents]=useState([]), [pending,setPending]=useState(null), [msg,setMsg]=useState('');
  const [form,setForm]=useState({title:'兴趣学习会话',topic_id:'',concept_id:'',persona_name:'',knowledge_base_ids:[],skill_names:[]});
  const [content,setContent]=useState(''), [capability,setCapability]=useState('chat'), [reply,setReply]=useState('');
  const [connected,setConnected]=useState(false), [running,setRunning]=useState(false), [activeTurnId,setActiveTurnId]=useState(''), [busyAction,setBusyAction]=useState('');

  async function load(){
    const [t,c,k,p,s,a]=await Promise.all([api('/topics'),api('/concepts'),api('/knowledge/bases'),api('/personas'),api('/tutor/sessions'),api('/areas/current')]);
    const nextPersonas=p.personas||[]; const skills=a.domain?.skills||[];
    setTopics(t.topics||[]);setConcepts(c.concepts||[]);setBases(k.knowledge_bases||[]);setPersonas(nextPersonas);setSessions(s.sessions||[]);setDomain(a);setSessionId(old=>old||s.sessions?.[0]?.id||'');
    setForm(old=>({
      ...old,
      title: old.title || '兴趣学习会话',
      persona_name: nextPersonas.some(x=>x.name===old.persona_name) ? old.persona_name : (nextPersonas[0]?.name||''),
      skill_names: (old.skill_names||[]).filter(name=>skills.includes(name)),
    }));
  }
  async function loadTurns(id=sessionId){
    if(!id){setTurns([]);setActiveTurnId('');setEvents([]);setPending(null);return;}
    const x=await api(`/tutor/sessions/${id}/turns`);const next=x.turns||[];setTurns(next);
    const candidate=[...next].reverse().find(turn=>turn.upstream_turn_id&&['running','awaiting_input'].includes(turn.status));
    if(!candidate){setActiveTurnId('');setEvents([]);setPending(null);return;}
    try {
      const replay=await api(`/tutor/sessions/${id}/native-turns/${candidate.id}/events`);
      const replayEvents=replay.events||[];
      const waitEvent=replayEvents.find(event=>event.category==='wait_for_input');
      const persistedPending=candidate.pending_input_json?.content?candidate.pending_input_json:null;
      setActiveTurnId(candidate.id);setEvents(replayEvents);setPending(waitEvent||persistedPending);setRunning(false);
    } catch(error) { setMsg(toUserMessage(error)); }
  }
  useEffect(()=>{load().catch(e=>setMsg(toUserMessage(e)));},[]);
  useEffect(()=>{loadTurns(sessionId).catch(e=>setMsg(toUserMessage(e)));},[sessionId]);
  function toggleKb(id){setForm(f=>({...f,knowledge_base_ids:f.knowledge_base_ids.includes(id)?f.knowledge_base_ids.filter(x=>x!==id):[...f.knowledge_base_ids,id]}))}
  function toggleSkill(name){setForm(f=>({...f,skill_names:f.skill_names.includes(name)?f.skill_names.filter(x=>x!==name):[...f.skill_names,name]}))}
  async function createSession(e){e.preventDefault();if(busyAction)return;setBusyAction('create');try{const x=await api('/tutor/sessions',{method:'POST',body:JSON.stringify({...form,topic_id:form.topic_id||null,concept_id:form.concept_id||null})});await load();setSessionId(x.id);setMsg('会话已保存在当前兴趣，并由本地服务执行。');}catch(e){setMsg(toUserMessage(e))}finally{setBusyAction('')}}
  async function connect(){if(!sessionId||busyAction)return;setBusyAction('connect');try{const health=await api('/native-execution/health');setConnected(true);setMsg(health.llm_available?'本地导师服务已就绪。':'本地执行服务已连接；请在设置中配置 DeepSeek API Key 以启用 AI 导师。')}catch(e){setConnected(false);setMsg(toUserMessage(e))}finally{setBusyAction('')}}
  async function sendTurn(){if(running)return;if(!connected){setMsg('请先连接本地导师服务。');return;}if(!content.trim())return;const input=content.trim();setEvents([]);setPending(null);setRunning(true);setContent('');try{const x=await api(`/tutor/sessions/${sessionId}/native-turns`,{method:'POST',headers:{'X-PG-Native-Session':sessionId},body:JSON.stringify({capability,content:input})});setActiveTurnId(x.turn?.id||'');setEvents(x.events||[]);const wait=(x.events||[]).find(e=>e.category==='wait_for_input');setPending(wait||null);if((x.events||[]).some(e=>e.category==='error'))setMsg('本地导师服务执行失败，请检查模型配置。');await loadTurns()}catch(e){setMsg(toUserMessage(e))}finally{setRunning(false)}}
  async function answer(){if(running||!pending||!activeTurnId||!reply.trim())return;const questions=pending.metadata?.questions||[];const answers=questions.length?[{questionId:questions[0]?.id||'q1',text:reply}]:[];setRunning(true);try{const x=await api(`/tutor/sessions/${sessionId}/native-turns/${activeTurnId}/resume`,{method:'POST',headers:{'X-PG-Native-Session':sessionId},body:JSON.stringify({text:reply,answers})});setEvents(old=>[...old,...(x.events||[])]);const wait=(x.events||[]).find(e=>e.category==='wait_for_input');setPending(wait||null);setReply('');await loadTurns()}catch(e){setMsg(toUserMessage(e))}finally{setRunning(false)}}
  async function cancel(){if(running||!activeTurnId)return;setRunning(true);try{await api(`/tutor/sessions/${sessionId}/native-turns/${activeTurnId}/cancel`,{method:'POST',headers:{'X-PG-Native-Session':sessionId}});setPending(null);await loadTurns()}catch(e){setMsg(toUserMessage(e))}finally{setRunning(false)}}
  const answerText=events.filter(x=>x.category==='answer_delta').map(x=>x.content||'').join('');
  const sourceEvents=events.filter(x=>x.category==='sources').flatMap(x=>x.metadata?.sources||x.sources||[]);
  const messages=useMemo(()=>turns.slice(-8).flatMap(t=>[{id:`${t.id}-q`,role:'user',content:t.prompt_text||t.input_text||t.user_text||`${capabilityLabel(t.capability)}内容`,meta:statusLabel(t.status)},{id:`${t.id}-a`,role:'assistant',content:t.answer_text||'—',meta:capabilityLabel(t.capability)}]),[turns]);
  const availableSkills=domain?.domain?.skills||[];
  const areaName=domain?.area?.name||'当前兴趣';
  const modeAvailability={
    chat: availability.available('FEATURE_TUTOR_RUNTIME','capability.tutor-runtime'),
    deep_question: availability.available('FEATURE_FLEXIBLE_MASTERY','capability.mastery'),
    mastery_path: availability.available('FEATURE_FLEXIBLE_MASTERY','capability.mastery'),
    deep_research: availability.available('FEATURE_DEEP_RESEARCH','capability.research-evidence'),
    visualize: availability.available('FEATURE_VISUALIZE','capability.concept-graph'),
  };
  return <div className="stack">
    <section className="pageLead"><div><div className="eyebrow">导师 · {areaName}</div><h1>带着一个具体问题，继续上次的思路。</h1><p className="muted">导师会结合当前兴趣的学习方式和你选中的资料。界面只呈现可检查的活动、工具与来源。</p></div><div className="pageLeadStatus"><StatusChip tone={connected?'success':'neutral'} pulse={running}>{connected?'已经连接':'尚未连接'}</StatusChip></div></section>
    {msg&&<p className="notice">{msg}</p>}
    <WorkspaceBoard pageId="tutor" data={workspace.data} loading={workspace.loading} compact title="导师工作台"/>

    <div className="grid two">
      <section className="card"><div className="cardHeader"><div><div className="eyebrow">会话设置 · {domainDisplayName(domain?.area)}</div><h2>建立学习会话</h2></div><StatusChip>{sessions.length} 个已保存会话</StatusChip></div><form className="stack" onSubmit={createSession}><input aria-label="学习会话标题" value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/><select aria-label="学习主题" value={form.topic_id} onChange={e=>setForm({...form,topic_id:e.target.value})}><option value="">不限主题</option>{topics.map(x=><option key={x.id} value={x.id}>{x.title}</option>)}</select><select aria-label="学习概念" value={form.concept_id} onChange={e=>setForm({...form,concept_id:e.target.value})}><option value="">不限概念</option>{concepts.filter(x=>!form.topic_id||x.concept.topic_id===form.topic_id).map(x=><option key={x.concept.id} value={x.concept.id}>{x.concept.name}</option>)}</select><select aria-label="导师风格" value={form.persona_name} onChange={e=>setForm({...form,persona_name:e.target.value})}><option value="">不使用特定导师风格</option>{personas.map(x=><option key={x.id} value={x.name}>{x.name}</option>)}</select>
        {availableSkills.length>0&&<div><div className="fieldLabel">领域能力（可选）</div><div className="checkGrid">{availableSkills.map(name=><label className="check" key={name}><input type="checkbox" checked={form.skill_names.includes(name)} onChange={()=>toggleSkill(name)}/><span>{name}</span></label>)}</div></div>}
        {bases.length>0&&<div><div className="fieldLabel">参考资料库（可选）</div><div className="checkGrid">{bases.map(k=><label className="check" key={k.id}><input type="checkbox" checked={form.knowledge_base_ids.includes(k.id)} onChange={()=>toggleKb(k.id)}/><span>{k.name} · {statusLabel(k.status)}</span></label>)}</div></div>}
        <div className="row" style={{justifyContent:'flex-end',marginTop:4}}><button className="buiButton--secondary" disabled={Boolean(busyAction)}>{busyAction==='create'?'正在保存…':'保存本地学习会话'}</button></div></form></section>
      <section className="card"><div className="cardHeader"><div><div className="eyebrow">继续会话</div><h2>已有学习会话</h2></div></div><select aria-label="选择学习会话" value={sessionId} onChange={e=>{setSessionId(e.target.value);setConnected(false);setActiveTurnId('')}} disabled={Boolean(busyAction)}><option value="">选择学习会话</option>{sessions.map(s=><option key={s.id} value={s.id}>{s.title||s.id} · {statusLabel(s.status)}</option>)}</select><div className="row sectionTop"><button onClick={connect} disabled={!sessionId||Boolean(busyAction)}>{busyAction==='connect'?'正在连接…':'连接本地执行服务'}</button><button className="ghost" onClick={cancel} disabled={!activeTurnId||running}>{running?'正在取消…':'取消当前对话'}</button></div><ChatPanel messages={messages} empty="这个学习会话还没有历史对话。"/></section>
    </div>

    <section className="card aiWorkSurface"><div className="cardHeader"><div><div className="eyebrow">互动学习</div><h2>和当前兴趣上下文一起学习</h2></div><label className="fieldGroup"><span>导师模式</span><select aria-label="导师模式" value={capability} onChange={e=>setCapability(e.target.value)} disabled={availability.status!=='available'||running}>{[['chat','自由对话'],['deep_question','深入提问'],['mastery_path','学习路径'],['deep_research','深入研究'],['visualize','可视化理解']].map(([value,label])=><option key={value} value={value} disabled={!modeAvailability[value]}>{label}{modeAvailability[value]?'':'（当前不可用）'}</option>)}</select></label></div>
      <PromptBar value={content} onChange={setContent} onSubmit={sendTurn} disabled={!connected||running} placeholder={`例如：不要直接给结论，先检查我对「${areaName}」当前理解或练习计划中的漏洞。`} model={{chat:'对话',deep_question:'深入提问',mastery_path:'学习路径',deep_research:'深入研究',visualize:'可视化'}[capability]||capability} context={[...form.skill_names,...form.knowledge_base_ids.map(id=>bases.find(b=>b.id===id)?.name).filter(Boolean)]}/>
      {running&&<PixelLoader label="导师正在整理回答" detail={capabilityLabel(capability)}/>}<ToolChips events={events}/>
      <div className="stack sectionTop"><StreamingText title="导师回答" text={answerText} sources={sourceEvents} streaming={false}/><ActivityTrace events={events} title="活动记录"/></div>
      {pending&&<ApprovalCard eyebrow="导师需要你的输入" title="继续当前这轮对话" description={pending.content||pending.metadata?.questions?.[0]?.prompt||'请回答后继续。'} tone="warning" actions={<button onClick={answer} disabled={running||!reply.trim()}>{running?'正在提交…':'提交并继续'}</button>} onCancel={()=>setPending(null)}><textarea value={reply} onChange={e=>setReply(e.target.value)} placeholder="你的回答" autoFocus/></ApprovalCard>}
    </section>
  </div>
}
