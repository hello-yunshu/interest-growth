"use client";

// Gate C §18 — runtime-aware user copy hook.
//
// Feature pages consume copy from here instead of hardcoding "本地保存 / 本机 /
// 设备上". Labels are derived from the ClientRuntime descriptor so that when a
// future remote runtime is active the same copy follows the real data location.
import { useEffect, useState } from 'react';
import { getRuntimeLabels } from '../lib/runtime/client-runtime.js';

const LOCAL_DEFAULT = {
  dataLocation: 'local-device',
  dataStatusLabel: '本地保存',
  bootCopy: '内容仍保存在本机',
  searchEmptyTitle: '正在搜索本机内容',
  searchEmptyHint: '问题、笔记和资料仍保存在本机。',
  savedCopy: '这次回顾已保存在本机。',
  noteSavedCopy: '学习笔记已保存在本机。',
  providerCopy: '你的内容由本地服务保存',
  offlineCopy: '暂时连接不到本地服务。你的内容仍安全保存在设备上，请稍后重试。',
  dataFooter: '本地保存 · 数据仅保存在你的设备上',
  knowledgeHeadline: '原始资料留在本机，检索索引可随时重建。',
  systemTitle: '本地服务、能力开关与模型通道。',
  systemBadge: '本地优先',
};

export function useRuntimeCopy() {
  const [labels, setLabels] = useState(LOCAL_DEFAULT);
  useEffect(() => {
    let active = true;
    getRuntimeLabels()
      .then((value) => { if (active) setLabels(value); })
      .catch(() => { if (active) setLabels(LOCAL_DEFAULT); });
    return () => { active = false; };
  }, []);
  return labels;
}
