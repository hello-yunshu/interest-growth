"use client";

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Icon from '../components/Icon';
import { PromptBar } from '../components/BeautifulUI';
import { WorkspaceBoard, useWorkspaceData } from '../components/WorkspaceWidgets';
import { useRuntimeCopy } from '../components/useRuntimeCopy';
import { api } from '../lib/api';
import { toUserMessage } from '../lib/presentation.js';

export default function Home() {
  const router = useRouter();
  const runtimeCopy = useRuntimeCopy();
  const { data, loading, error, reload } = useWorkspaceData();
  const [question, setQuestion] = useState('');
  const [energy, setEnergy] = useState('normal');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function submit() {
    if (!question.trim() || busy) return;
    setBusy(true); setMessage('');
    try {
      await api('/questions', { method: 'POST', body: JSON.stringify({ question: question.trim(), energy_mode: energy }) });
      setQuestion(''); router.push('/curiosity');
    } catch (err) { setMessage(toUserMessage(err)); }
    finally { setBusy(false); }
  }
  return <div className="homePage">
    <section className="homeHero">
      <div className="homeHeroIntro">
        <div className="homeHeroCopy">
          <h1>今天想把哪个兴趣往前推一点？</h1>
          <p>把想知道的事记下来。可以探索、练习或整理，也可以先停在这里。</p>
        </div>
        <aside className="homeHeroAside" aria-label="开始提示">
          <span className="homeHeroAsideIcon"><Icon name="spark" size={17}/></span>
          <div><span>今天的开始不必很大</span><strong>写下一个你愿意继续的问题。</strong></div>
        </aside>
      </div>
      <div className="homeCapture">
        <div className="homeCaptureHeader">
          <div className="homeCaptureTitle"><strong>从一个小问题开始</strong><span>探索、练习和整理的结果会沉淀为学习成果。</span></div>
          <label className="energyPicker"><span>投入程度</span><select aria-label="这次的投入程度" value={energy} onChange={event => setEnergy(event.target.value)} disabled={busy}><option value="light">轻量</option><option value="normal">标准</option><option value="deep">深入</option></select></label>
        </div>
        <PromptBar className="capturePrompt questionComposer" value={question} onChange={setQuestion} onSubmit={submit} placeholder="记下一个问题" ariaLabel="记下一个问题" disabled={busy} leadingIcon="pencil" shortcutHint commands={false} sendLabel="记录问题"/>
        {message && <p className="inlineError" role="alert"><Icon name="warning"/>{message}</p>}
      </div>
    </section>
    {error && <div className="serviceNotice"><Icon name="warning"/><span>{error}</span><button onClick={reload}>重试</button></div>}
    <WorkspaceBoard pageId="home" data={data} loading={loading} compact title="今天的工作台"/>
    <footer className="localFooter"><Icon name="status"/><span>{runtimeCopy.dataFooter}</span></footer>
  </div>;
}
