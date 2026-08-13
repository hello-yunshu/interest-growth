import { getInterestAreaSelector } from './api';

const STORAGE_PREFIX = 'interest-growth.workspace-layout.v1';

export function layoutStorageKey(pageId) {
  const area = getInterestAreaSelector() || 'default-area';
  return `${STORAGE_PREFIX}:${area}:${pageId}`;
}

export function readLayout(pageId, defaults) {
  if (typeof window === 'undefined') return defaults;
  try {
    const value = JSON.parse(window.localStorage.getItem(layoutStorageKey(pageId)) || 'null');
    return Array.isArray(value) ? value : defaults;
  } catch { return defaults; }
}

export function saveLayout(pageId, layout) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(layoutStorageKey(pageId), JSON.stringify(layout));
}

export function resetLayout(pageId) {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(layoutStorageKey(pageId));
}
