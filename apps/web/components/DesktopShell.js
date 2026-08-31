"use client";

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { api, getDesktopRuntime, refreshDesktopRuntime, getInterestAreaSelector, setInterestAreaSelector } from '../lib/api';
import Icon from './Icon';
import { useRuntimeCopy } from './useRuntimeCopy';
import { maybeRunUiIpcE2e } from '../lib/runtime/ui-ipc-e2e';
import { domainLabel, sourceTypeLabel, toUserMessage } from '../lib/presentation.js';

const NAV = [
  { href: '/', label: '今日', icon: 'home', group: 'focus', keywords: 'home dashboard today 首页' },
  { href: '/curiosity', label: '好奇心', icon: 'spark', group: 'focus', keywords: 'question curiosity 问题' },
  { href: '/research', label: '研究', icon: 'search', group: 'learn', keywords: 'research evidence source claim 证据 资料 结论' },
  { href: '/knowledge', label: '资料库', icon: 'library', group: 'learn', keywords: 'knowledge rag pdf source library 文件' },
  { href: '/learning', label: '学习', icon: 'learn', group: 'learn', keywords: 'concept mastery practice note 概念 练习 笔记' },
  { href: '/tutor', label: '导师', icon: 'tutor', group: 'learn', keywords: 'tutor session chat 对话' },
  { href: '/outputs', label: '学习成果', icon: 'outputs', group: 'learn', keywords: 'outputs results artifacts 成果 产出' },
  { href: '/writing', label: '共写', icon: 'pen', group: 'create', keywords: 'writing rewrite draft 草稿' },
  { href: '/book', label: '我的书', icon: 'book', group: 'create', keywords: 'book chapter living 章节' },
  { href: '/content', label: '表达', icon: 'send', group: 'create', keywords: 'content publish export 作品' },
  { href: '/growth', label: '成长回顾', icon: 'growth', group: 'reflect', keywords: 'reflection growth memory heatmap 成长 热力图' },
  { href: '/career', label: '职业实验', icon: 'briefcase', group: 'reflect', keywords: 'career experiment 职业' },
  { href: '/system', label: '设置', icon: 'settings', group: 'system', keywords: 'settings providers plugins system 设置' },
];

const GROUPS = [['focus', '关注'], ['learn', '学习'], ['create', '创建'], ['reflect', '回顾']];

function normalizePath(path) {
  const value = String(path || '/');
  return value.length > 1 ? value.replace(/\/+$/, '') : '/';
}

function CommandPalette({ open, onClose, runtimeCopy }) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [contentRows, setContentRows] = useState([]);
  const [searching, setSearching] = useState(false);
  const previousFocus = useRef(null);
  const [mounted, setMounted] = useState(open);
  const [visible, setVisible] = useState(open);
  const router = useRouter();
  useEffect(() => {
    if (open) {
      previousFocus.current = document.activeElement;
      setMounted(true);
      requestAnimationFrame(() => setVisible(true));
      setQuery(''); setActive(0); setContentRows([]);
    } else if (mounted) {
      setVisible(false);
      const timer = window.setTimeout(() => setMounted(false), 180);
      previousFocus.current?.focus?.();
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [open]);
  const navigationRows = useMemo(() => {
    const value = query.trim().toLowerCase();
    return NAV.filter(item => !value || `${item.label} ${item.keywords}`.toLowerCase().includes(value)).map(item => ({ ...item, id: `nav:${item.href}`, kind: '页面' }));
  }, [query]);
  useEffect(() => {
    const value = query.trim().toLowerCase();
    if (!open || !value) { setContentRows([]); setSearching(false); return; }
    let cancelled = false;
    setSearching(true);
    const timer = window.setTimeout(async () => {
      const results = await Promise.allSettled([api('/questions?limit=100'), api('/notes'), api('/sources')]);
      if (cancelled) return;
      const [questions, notes, sources] = results.map(result => result.status === 'fulfilled' ? result.value : {});
      const contains = text => String(text || '').toLowerCase().includes(value);
      setContentRows([
        ...(questions.questions || []).filter(row => contains(row.question)).map(row => ({ id: `question:${row.id}`, label: row.question, detail: '保留的问题', kind: '问题', icon: 'question', href: '/curiosity' })),
        ...(notes.notes || []).filter(row => contains(`${row.title} ${row.body_markdown}`)).map(row => ({ id: `note:${row.id}`, label: row.title || '未命名笔记', detail: excerpt(row.body_markdown), kind: '笔记', icon: 'pen', href: '/learning' })),
        ...(sources.sources || []).filter(row => contains(`${row.title} ${row.original_filename} ${row.source_type}`)).map(row => ({ id: `source:${row.id}`, label: row.title || row.original_filename || '未命名资料', detail: row.original_filename || sourceTypeLabel(row.source_type), kind: '资料', icon: 'source', href: '/knowledge' })),
      ].slice(0, 30));
      setSearching(false);
    }, 180);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [open, query]);
  const rows = useMemo(() => [...navigationRows, ...contentRows], [navigationRows, contentRows]);
  useEffect(() => { setActive(value => Math.min(value, Math.max(0, rows.length - 1))); }, [rows.length]);
  function choose(item) { if (!item) return; router.push(item.href); onClose(); }
  if (!mounted) return null;
  return <div className={`commandBackdrop ${visible ? 'is-visible' : 'is-closing'}`} onMouseDown={onClose}>
    <div className="commandPalette" onMouseDown={event => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="快速跳转">
      <div className="commandInputRow"><Icon name="search"/><input autoFocus value={query} onChange={event => { setQuery(event.target.value); setActive(0); }} placeholder="搜索页面、问题、笔记或资料" onKeyDown={event => { if (event.key === 'Escape') onClose(); if (event.key === 'ArrowDown') { event.preventDefault(); setActive(value => Math.min(rows.length - 1, value + 1)); } if (event.key === 'ArrowUp') { event.preventDefault(); setActive(value => Math.max(0, value - 1)); } if (event.key === 'Enter') { event.preventDefault(); choose(rows[active]); } }}/><kbd>ESC</kbd></div>
      <div className="commandResults" aria-live="polite">{rows.map((item, index) => <button key={item.id} className={`commandItem ${index === active ? 'is-active' : ''}`} onMouseEnter={() => setActive(index)} onClick={() => choose(item)}><span className="commandIcon"><Icon name={item.icon}/></span><span><strong>{item.label}</strong><small>{item.detail || item.kind}</small></span>{index === active && <kbd>↵</kbd>}</button>)}{!rows.length && <div className="commandEmpty"><Icon name="search"/><strong>{searching ? runtimeCopy.searchEmptyTitle : '没有找到匹配内容'}</strong><span>{searching ? runtimeCopy.searchEmptyHint : '换一个更短的关键词试试。'}</span></div>}</div>
      <div className="commandFooter"><span>{query.trim() ? '当前兴趣中的页面与内容' : '快速跳转'}</span><span><kbd>↑↓</kbd> 选择 <kbd>↵</kbd> 打开</span></div>
    </div>
  </div>;
}

function excerpt(value = '') {
  const text = String(value).replace(/[#*_>`\[\]()~-]/g, ' ').replace(/\s+/g, ' ').trim();
  return text.length > 54 ? `${text.slice(0, 54)}…` : text || '学习笔记';
}

function AreaSwitcher({ areas, current, onSwitch, onCreated, busy = false }) {
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [menuMounted, setMenuMounted] = useState(false);
  const [menuVisible, setMenuVisible] = useState(false);
  const [form, setForm] = useState({ name: '', slug: '', domain_pack_id: 'general' });
  const [error, setError] = useState('');
  const menuRef = useRef(null);
  const triggerRef = useRef(null);
  const closeTimer = useRef(null);
  function openMenu() {
    clearTimeout(closeTimer.current);
    setCreating(true); setMenuMounted(true); setMenuVisible(false);
    requestAnimationFrame(() => setMenuVisible(true));
  }
  function closeMenu({ restoreFocus = true } = {}) {
    clearTimeout(closeTimer.current);
    setCreating(false); setMenuVisible(false);
    if (!menuMounted) return;
    closeTimer.current = window.setTimeout(() => setMenuMounted(false), 180);
    if (restoreFocus) triggerRef.current?.focus?.();
  }
  useEffect(() => () => clearTimeout(closeTimer.current), []);
  useEffect(() => {
    if (!menuMounted) return undefined;
    const handlePointerDown = event => { if (!menuRef.current?.contains(event.target) && !triggerRef.current?.contains(event.target)) closeMenu({ restoreFocus: false }); };
    const handleKeyDown = event => { if (event.key === 'Escape') { event.preventDefault(); closeMenu(); } };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => { document.removeEventListener('mousedown', handlePointerDown); document.removeEventListener('keydown', handleKeyDown); };
  }, [menuMounted]);
  async function create(event) {
    event.preventDefault(); if (saving) return; setSaving(true); setError('');
    try {
      const row = await api('/areas', { method: 'POST', body: JSON.stringify(form) });
      closeMenu(); setForm({ name: '', slug: '', domain_pack_id: 'general' }); await onCreated(row);
    } catch (err) { setError(toUserMessage(err)); } finally { setSaving(false); }
  }
  return <div className="topAreaSwitcher">
    <span>当前兴趣</span>
    <button ref={triggerRef} className="areaSelectButton" onClick={() => (menuMounted && creating ? closeMenu() : openMenu())} aria-expanded={menuMounted && creating}><strong>{current?.name || '选择兴趣'}</strong><Icon name="chevronDown" size={14}/></button>
    {menuMounted && <div ref={menuRef} className={`areaMenu ${menuVisible ? 'is-visible' : 'is-closing'}`} data-state={menuVisible ? 'open' : 'closing'}>
      <div className="areaMenuList">{(areas || []).map(area => <button key={area.id} className={area.id === current?.id ? 'active' : ''} disabled={busy || saving} onClick={() => { onSwitch(area.id); closeMenu({ restoreFocus: false }); }}><span>{area.name.slice(0, 1).toUpperCase()}</span><div><strong>{area.name}</strong><small>{area.domain_name || domainLabel(area.domain_pack_id)}</small></div>{area.id === current?.id && <Icon name="check"/>}</button>)}</div>
      <form className="areaCreateForm" onSubmit={create}><strong>新建兴趣</strong><input value={form.name} onChange={event => setForm({ ...form, name: event.target.value, slug: event.target.value.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-').replace(/[\u4e00-\u9fa5]/g, '') || `interest-${Date.now()}` })} placeholder="例如：城市摄影" required disabled={busy || saving}/><select value={form.domain_pack_id} onChange={event => setForm({ ...form, domain_pack_id: event.target.value })} disabled={busy || saving}><option value="general">通用兴趣</option><option value="psychology">心理学</option></select>{error && <p className="formError">{error}</p>}<button type="submit" className="compactPrimary" disabled={busy || saving}><Icon name="plus"/>{saving ? '正在创建…' : '创建兴趣'}</button></form>
    </div>}
  </div>;
}

function WindowsControls({ visible }) {
  if (!visible) return null;
  async function act(action) {
    const { getCurrentWindow } = await import('@tauri-apps/api/window'); const win = getCurrentWindow();
    if (action === 'minimize') await win.minimize(); if (action === 'maximize') await win.toggleMaximize(); if (action === 'close') await win.close();
  }
  return <div className="windowsControls"><button aria-label="最小化" onClick={() => act('minimize')}><span className="winMin"/></button><button aria-label="最大化" onClick={() => act('maximize')}><span className="winMax"/></button><button className="winClose" aria-label="关闭" onClick={() => act('close')}><span>×</span></button></div>;
}

export default function DesktopShell({ children }) {
  const pathname = usePathname();
  const currentPath = normalizePath(pathname);
  const [palette, setPalette] = useState(false);
  const [runtime, setRuntime] = useState(null);
  const [areas, setAreas] = useState([]);
  const [currentArea, setCurrentArea] = useState(null);
  const [areaReady, setAreaReady] = useState(false);
  const [areaSwitchBusy, setAreaSwitchBusy] = useState(false);
  const [theme, setTheme] = useState('light');
  const [mobileNav, setMobileNav] = useState(false);
  const [mobileNavMounted, setMobileNavMounted] = useState(false);
  const [mobileNavVisible, setMobileNavVisible] = useState(false);
  const mobileNavCloseTimer = useRef(null);
  const runtimeCopy = useRuntimeCopy();
  useEffect(() => {
    let unlisten = null; let active = true;
    setTheme(window.localStorage.getItem('interest-growth.theme') || 'light');
    getDesktopRuntime().then(value => { if (active) setRuntime(value); }).catch(() => setRuntime({ desktop: false, status: 'web' }));
    api('/areas').then(async list => {
      if (!active) return;
      const nextAreas = list.areas || [];
      setAreas(nextAreas);
      const stored = getInterestAreaSelector();
      if (nextAreas.length && !nextAreas.some(area => area.id === stored)) {
        setInterestAreaSelector(nextAreas.find(area => area.is_default)?.id || nextAreas[0].id);
        window.location.reload();
        return;
      }
      const selected = await api('/areas/current');
      if (active) { setCurrentArea(selected.area || null); setAreaReady(true); }
    }).catch(() => { if (active) setAreaReady(true); });
    if (isTauri()) import('@tauri-apps/api/event').then(({ listen }) => listen('core-terminated', async () => { try { const value = await refreshDesktopRuntime(); if (active) setRuntime(value); } catch { if (active) setRuntime(current => ({ ...current, status: 'error' })); } })).then(fn => { unlisten = fn; }).catch(() => {});
    maybeRunUiIpcE2e().catch(console.error);
    return () => { active = false; if (unlisten) unlisten(); };
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; window.localStorage.setItem('interest-growth.theme', theme); }, [theme]);
  useEffect(() => () => clearTimeout(mobileNavCloseTimer.current), []);
  function openMobileNav() {
    clearTimeout(mobileNavCloseTimer.current);
    setMobileNav(true); setMobileNavMounted(true); setMobileNavVisible(false);
    requestAnimationFrame(() => setMobileNavVisible(true));
  }
  function closeMobileNav() {
    clearTimeout(mobileNavCloseTimer.current);
    setMobileNav(false); setMobileNavVisible(false);
    if (mobileNavMounted) mobileNavCloseTimer.current = window.setTimeout(() => setMobileNavMounted(false), 180);
  }
  function toggleMobileNav() { if (mobileNavMounted && mobileNav) closeMobileNav(); else openMobileNav(); }
  useEffect(() => { const handler = event => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setPalette(value => !value); } if (event.key === 'Escape') { setPalette(false); closeMobileNav(); } }; window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler); }, [mobileNavMounted, mobileNav]);
  async function switchArea(id) { if (areaSwitchBusy) return; setAreaSwitchBusy(true); try { setInterestAreaSelector(id); const [list, selected] = await Promise.all([api('/areas'), api('/areas/current')]); setAreas(list.areas || []); setCurrentArea(selected.area || null); window.location.reload(); } catch (error) { console.error('兴趣切换失败', error); setAreaSwitchBusy(false); } }
  async function areaCreated(row) { setAreas(value => [...value.filter(item => item.id !== row.id), row]); await switchArea(row.id); }
  const date = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()).replaceAll('/', '-');
  return <div className="desktopApp">
    <header className="desktopTopbar" data-tauri-drag-region>
      <button className="mobileMenuButton" onClick={toggleMobileNav} aria-label={mobileNav ? '关闭导航' : '打开导航'} aria-expanded={mobileNav} aria-controls="primary-navigation"><Icon name={mobileNav ? 'close' : 'rows'}/></button>
      <AreaSwitcher areas={areas} current={currentArea} onSwitch={switchArea} onCreated={areaCreated} busy={areaSwitchBusy}/>
      <button className="globalSearch" onClick={() => setPalette(true)}><Icon name="search"/><span>搜索问题、笔记、资料</span><kbd>⌘K</kbd></button>
      <div className="topbarEnd"><time>{date}</time><button className="themeButton" onClick={() => setTheme(value => value === 'light' ? 'dark' : 'light')} aria-label="切换明暗主题"><Icon name={theme === 'light' ? 'sun' : 'moon'}/></button><WindowsControls visible={runtime?.desktop && runtime?.platform === 'windows'}/></div>
    </header>
    <div className="desktopBody">
      <aside className={`desktopSidebar ${mobileNavVisible ? 'is-open' : ''}`}>
        <Link href="/" className="desktopBrand" onClick={closeMobileNav}><span className="brandMark">IG</span><span><strong>Interest Growth</strong><small><i className={`statusDot ${runtimeCopy.dataLocation === 'self-hosted-server' ? 'remote' : 'ok'}`}/> {runtimeCopy.dataStatusLabel}</small></span></Link>
        <nav id="primary-navigation" className="sideNav" aria-label="主导航">{GROUPS.map(([group, label]) => <div className="sideNavGroup" key={group}><div className="sideNavLabel">{label}</div>{NAV.filter(item => item.group === group).map(item => { const active = currentPath === normalizePath(item.href); return <Link key={item.href} href={item.href} onClick={closeMobileNav} className={`sideNavItem ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined}><Icon name={item.icon}/><span>{item.label}</span></Link>; })}</div>)}</nav>
        <div className="sidebarBottom"><button className="commandShortcut" onClick={() => setPalette(true)}><Icon name="search"/><span>快速跳转</span><kbd>⌘K</kbd></button>{(() => { const active = currentPath === '/system'; return <Link href="/system" className={`sideNavItem ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined}><Icon name="settings"/><span>设置</span></Link>; })()}</div>
      </aside>
      {mobileNavMounted && <button className={`mobileNavBackdrop ${mobileNavVisible ? 'is-visible' : 'is-closing'}`} aria-label="关闭导航菜单" onClick={closeMobileNav}/>}
      <main className="workspace"><div className="workspaceInner">{areaReady ? children : <div className="workspaceBoot"><span className="brandMark">IG</span><strong>正在打开你的兴趣空间</strong><small>{runtimeCopy.bootCopy}</small></div>}</div></main>
    </div>
    <CommandPalette open={palette} onClose={() => setPalette(false)} runtimeCopy={runtimeCopy}/>
  </div>;
}
