"use client";

import { useMemo, useState } from 'react';
import Link from 'next/link';
import Icon from '../../components/Icon';
import { WorkspaceBoard, useWorkspaceData } from '../../components/WorkspaceWidgets';
import { formatRelativeDate, outputTypeMeta } from '../../lib/workspaceData';

export default function OutputsPage() {
  const { data, loading, error, reload } = useWorkspaceData();
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const outputs = useMemo(() => (data?.outputs || []).filter(item => (filter === 'all' || item.type === filter) && (!query.trim() || `${item.title} ${item.detail} ${item.label}`.toLowerCase().includes(query.toLowerCase()))), [data, filter, query]);
  const types = useMemo(() => [...new Set((data?.outputs || []).map(item => item.type))], [data]);
  return <div className="outputsPage stack">
    <section className="editorialLead"><span className="sectionKicker">学习成果</span><h1>你留下来的，不只是进度。</h1><p>笔记、练习、研究结论、草稿和作品各自保留原本的含义，也一起构成你在这个兴趣上的积累。</p></section>
    {error && <div className="serviceNotice"><Icon name="warning"/><span>{error}</span><button onClick={reload}>重试</button></div>}
    <WorkspaceBoard pageId="outputs" data={data} loading={loading} title="成果概览"/>
    <section className="outputLibrary">
      <div className="libraryHeader"><div><span className="sectionKicker">全部记录</span><h2>浏览学习成果</h2></div><label className="inlineSearch"><Icon name="search"/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索成果"/></label></div>
      <div className="filterTabs"><button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>全部 <span>{data?.outputs?.length || 0}</span></button>{types.map(type => <button key={type} className={filter === type ? 'active' : ''} onClick={() => setFilter(type)}>{outputTypeMeta(type).label}</button>)}</div>
      {loading ? <div className="outputSkeleton"><span/><span/><span/></div> : outputs.length ? <div className="outputRows">{outputs.map(item => <Link href={item.href} key={item.id}><span className="outputIcon" style={{ '--output-color': item.color }}><Icon name={item.icon}/></span><span className="outputMain"><strong>{item.title}</strong><small>{item.detail || '已保存在当前兴趣中'}</small></span><span className="outputType" style={{ '--output-color': item.color }}>{item.label}</span><time>{formatRelativeDate(item.date)}</time><Icon name="arrowRight"/></Link>)}</div> : <div className="largeEmpty"><Icon name="outputs" size={32}/><h3>这里还没有匹配的成果</h3><p>{query || filter !== 'all' ? '换一个筛选条件试试。' : '完成一次探索、练习或整理，它就会出现在这里。'}</p><Link href="/learning">开始学习 <Icon name="arrowRight"/></Link></div>}
    </section>
  </div>;
}
