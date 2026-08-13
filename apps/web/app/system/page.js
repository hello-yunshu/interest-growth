'use client';
import { useEffect, useMemo, useState } from 'react';
import { api, deleteProviderSecret, getDesktopProviderSettings, getDesktopRuntime, getProviderSecretStatus, restartDesktopCore, setDesktopProviderSettings, setProviderSecret } from '../../lib/api';
import { FilterTabs, FineTunePanel, InsightCards, RecordsTable, StatusChip, TaskRows } from '../../components/BeautifulUI';
import RuntimeConnect from '../../components/RuntimeConnect';
import { useRuntimeCopy } from '../../components/useRuntimeCopy';

const DEFAULT_SETTINGS={deepseekBaseUrl:'https://api.deepseek.com',deepseekModel:'deepseek-chat'};
const isLocalDesktop=(desktop)=>Boolean(desktop?.desktop && desktop?.runtimeId==='desktop-local');

export default function SystemPage(){
  const runtimeCopy=useRuntimeCopy();
  const [integrations,setIntegrations]=useState(null),[plugins,setPlugins]=useState([]),[features,setFeatures]=useState([]),[desktop,setDesktop]=useState(null),[providerSettings,setProviderSettings]=useState(DEFAULT_SETTINGS),[secretStatus,setSecretStatus]=useState(null),[deepseekSecret,setDeepseekSecret]=useState(''),[saving,setSaving]=useState(false),[msg,setMsg]=useState(''),[tab,setTab]=useState('runtime'),[area,setArea]=useState(null),[areaCapabilities,setAreaCapabilities]=useState([]);

  async function load(){
    const [i,p,f,a,r]=await Promise.all([api('/system/integrations'),api('/plugins'),api('/features'),api('/areas/current'),getDesktopRuntime()]);
    setIntegrations(i);setPlugins(p.plugins||[]);setFeatures(f.features||[]);setArea(a.area||null);setDesktop(r);
    if(a.area?.id){const caps=await api(`/areas/${a.area.id}/capabilities`);setAreaCapabilities(caps.capabilities||[])}
    if(isLocalDesktop(r)){
      const [settings,secret]=await Promise.all([getDesktopProviderSettings(),getProviderSecretStatus('deepseek')]);
      if(settings)setProviderSettings(settings);setSecretStatus(secret);
    } else {
      setSecretStatus(null);
    }
  }
  useEffect(()=>{load().catch(e=>setMsg(e.message))},[]);

  async function saveProvider(){setSaving(true);setMsg('');try{await setDesktopProviderSettings(providerSettings);if(deepseekSecret.trim())await setProviderSecret('deepseek',deepseekSecret);setDeepseekSecret('');setDesktop(await restartDesktopCore());await load();setMsg('模型通道设置已保存，Native Core 已重启。')}catch(e){setMsg(e.message)}finally{setSaving(false)}}
  async function removeSecret(){setSaving(true);try{await deleteProviderSecret('deepseek');setDesktop(await restartDesktopCore());await load();setMsg('DeepSeek API Key 已从安全凭据库删除。')}catch(e){setMsg(e.message)}finally{setSaving(false)}}
  async function toggleFeature(row){await api(`/features/${row.name}`,{method:'PUT',body:JSON.stringify({enabled:!row.enabled})});await load()}
  async function togglePlugin(row){const id=row.manifest.id;const action=row.enabled?'disable':'enable';await api(`/plugins/${id}/${action}`,{method:'POST'});await load()}
  async function toggleAreaCapability(row){if(!area)return;await api(`/areas/${area.id}/capabilities/${row.plugin_id}`,{method:'PUT',body:JSON.stringify({enabled:!row.enabled})});await load()}

  const remote=desktop?.runtimeId==='desktop-remote';
  const health=useMemo(()=>[
    {label:remote?'数据源':'Core',title:remote?'自托管服务器':desktop?.desktop?(desktop.status||'unknown'):'web dev',detail:remote?(desktop?.dataLocation==='self-hosted-server'?'远程服务 · 本机不复制数据':'等待连接'):desktop?.desktop?`v${desktop.version||'0.7.0'}`:'Browser development mode'},
    {label:'Native execution',title:integrations?.native_execution?.provider?'ready':'loading',detail:integrations?.native_execution?.llm_available?'Native Core + configured model':'Native local capabilities ready · model optional'},
    {label:'DeepSeek',title:remote?'remote':(secretStatus?.configured?'configured':'optional'),detail:remote?'模型通道由服务器侧配置，不在本机管理。':'仅作为可替换模型通道，不拥有产品状态。'},
    {label:'Interest Area',title:area?.name||'loading',detail:area?.domain_name||''},
  ],[desktop,integrations,secretStatus,area,remote]);

  const runtimeTasks=[
    {title:'Native execution core',status:integrations?.native_execution?.provider?'completed':'running',meta:integrations?.native_execution?.provider||'loading',detail:'唯一产品执行与编排层。'},
    {title:'DeepSeek model transport',status:secretStatus?.configured?'completed':'todo',meta:secretStatus?.configured?'configured':'optional',detail:'可关闭、可替换；不拥有任何 Canonical 数据。'},
  ];

  return <div className="stack">
    <section className="pageLead"><div><div className="eyebrow">设置</div><h1>{runtimeCopy.systemTitle}</h1><p className="muted">{runtimeCopy.providerCopy}。模型只负责可替换的生成能力，不拥有产品数据。</p></div><StatusChip tone="success">{runtimeCopy.systemBadge}</StatusChip></section>
    {msg&&<p className="notice">{msg}</p>}
    <InsightCards items={health}/>
    <FilterTabs value={tab} onChange={setTab} items={[{value:'connection',label:'连接'},{value:'runtime',label:'运行状态'},{value:'plugins',label:'能力组件',count:plugins.length},{value:'features',label:'功能开关',count:features.length},{value:'area',label:'当前兴趣',count:areaCapabilities.length}]}/>
    {tab==='connection'&&<RuntimeConnect onRuntimeChanged={()=>load().catch(e=>setMsg(e.message))}/>}
    {tab==='runtime'&&<><section className="card"><TaskRows tasks={runtimeTasks}/></section>{isLocalDesktop(desktop)?<><FineTunePanel title="DeepSeek · optional model transport" fields={[{label:'Base URL',node:<input value={providerSettings.deepseekBaseUrl||''} onChange={e=>setProviderSettings({...providerSettings,deepseekBaseUrl:e.target.value})}/>},{label:'Model',node:<input value={providerSettings.deepseekModel||''} onChange={e=>setProviderSettings({...providerSettings,deepseekModel:e.target.value})}/>},{label:'API Key',node:<input type="password" autoComplete="new-password" placeholder={secretStatus?.configured?'已安全保存；留空保持不变':'输入 API Key'} value={deepseekSecret} onChange={e=>setDeepseekSecret(e.target.value)}/>}]} actions={<div className="row"><StatusChip tone={secretStatus?.configured?'success':'neutral'}>{secretStatus?.configured?'Key saved':'no key'}</StatusChip>{secretStatus?.configured&&<button className="ghost danger" disabled={saving} onClick={removeSecret}>删除 Key</button>}</div>}/><div className="row"><button className="secondary" disabled={saving} onClick={async()=>setDesktop(await restartDesktopCore())}>重启 Core</button><button disabled={saving} onClick={saveProvider}>{saving?'保存中…':'保存并重启 Core'}</button></div></>:desktop?.desktop?<p className="notice warning">当前处于自托管服务器模式。模型通道由服务器侧配置，本机不再显示本地凭据管理。切换到本机模式可管理本机模型通道。</p>:<p className="notice">安全凭据管理仅在桌面运行时显示。</p>}</>}
    {tab==='plugins'&&<RecordsTable columns={[{key:'manifest',label:'Plugin',render:r=><strong>{r.manifest.name}</strong>},{key:'enabled',label:'State',render:r=><StatusChip tone={r.enabled?'success':'neutral'}>{r.enabled?'enabled':'disabled'}</StatusChip>},{key:'action',label:'Action',render:r=><button className="tableLink" onClick={()=>togglePlugin(r)}>{r.enabled?'停用':'启用'}</button>}]} rows={plugins}/>}
    {tab==='features'&&<RecordsTable columns={[{key:'name',label:'Feature'},{key:'enabled',label:'State',render:r=><StatusChip tone={r.enabled?'success':'neutral'}>{r.enabled?'on':'off'}</StatusChip>},{key:'action',label:'Action',render:r=><button className="tableLink" onClick={()=>toggleFeature(r)}>切换</button>}]} rows={features}/>}
    {tab==='area'&&<RecordsTable columns={[{key:'plugin_id',label:'Capability'},{key:'enabled',label:'Area state',render:r=><StatusChip tone={r.enabled?'success':'neutral'}>{r.enabled?'enabled':'disabled'}</StatusChip>},{key:'action',label:'Action',render:r=><button className="tableLink" onClick={()=>toggleAreaCapability(r)}>切换</button>}]} rows={areaCapabilities}/>}
  </div>
}
