"use client";

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Icon from '../components/Icon';
import { WorkspaceBoard, useWorkspaceData } from '../components/WorkspaceWidgets';
import { useRuntimeCopy } from '../components/useRuntimeCopy';
import { api } from '../lib/api';

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
    } catch (err) { setMessage(err.message); }
    finally { setBusy(false); }
  }
  return <div className="homePage">
    <section className="homeHero">
      <h1>今天想把哪个兴趣往前推一点？</h1>
      <p>把想知道的记下来。你可以探索、练习、整理，也可以先停在这里。</p>
      <div className="outputPromise"><Icon name="lightbulb"/><span>探索、练习和整理的结果会沉淀为学习成果</span></div>
      <div className="questionComposer">
        <Icon name="pencil" size={24}/>
        <textarea value={question} onChange={event => setQuestion(event.target.value)} placeholder="记下一个问题" aria-label="记下一个问题" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); } }}/>
        <button onClick={submit} disabled={!question.trim() || busy} aria-label="提交问题"><Icon name="arrowUp" size={24}/></button>
      </div>
      <div className="composerHint"><kbd>↵</kbd><span>Enter 提交</span><span>Shift + Enter 换行</span></div>
      {message && <p className="inlineError"><Icon name="warning"/>{message}</p>}
    </section>
    {error && <div className="serviceNotice"><Icon name="warning"/><span>{error}</span><button onClick={reload}>重试</button></div>}
    <WorkspaceBoard pageId="home" data={data} loading={loading} compact title="今日工作台"/>
    <footer className="localFooter"><Icon name="status"/><span>{runtimeCopy.dataFooter}</span></footer>
  </div>;
}
