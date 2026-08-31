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
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function submit() {
    if (!question.trim() || busy) return;
    setBusy(true); setMessage('');
    try {
      await api('/questions', { method: 'POST', body: JSON.stringify({ question: question.trim(), energy_mode: 'normal' }) });
      setQuestion(''); router.push('/curiosity');
    } catch (err) { setMessage(toUserMessage(err)); }
    finally { setBusy(false); }
  }
  return <div className="homePage">
    <section className="homeHero">
      <h1>今天想把哪个兴趣往前推一点？</h1>
      <p>把想知道的记下来。你可以探索、练习、整理，也可以先停在这里。</p>
      <div className="outputPromise"><Icon name="lightbulb"/><span>探索、练习和整理的结果会沉淀为学习成果</span></div>
      <PromptBar className="capturePrompt questionComposer" value={question} onChange={setQuestion} onSubmit={submit} placeholder="记下一个问题" ariaLabel="记下一个问题" disabled={busy} leadingIcon="pencil" shortcutHint commands={false} sendLabel="提交问题"/>
      {message && <p className="inlineError"><Icon name="warning"/>{message}</p>}
    </section>
    {error && <div className="serviceNotice"><Icon name="warning"/><span>{error}</span><button onClick={reload}>重试</button></div>}
    <WorkspaceBoard pageId="home" data={data} loading={loading} compact title="今日工作台"/>
    <footer className="localFooter"><Icon name="status"/><span>{runtimeCopy.dataFooter}</span></footer>
  </div>;
}
