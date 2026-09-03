'use strict';

const { test, expect } = require('@playwright/test');

const PAGES = ['/', '/curiosity', '/research', '/knowledge', '/learning', '/tutor', '/outputs', '/writing', '/book', '/content', '/growth', '/career', '/system'];
const FORBIDDEN_UI = [
  'Curiosity', 'Topic', 'Claim/Evidence', 'Research 正在', 'Renderer DOM', 'image data URI',
  'rewrite', 'shorten', 'expand',
  'candidate ready', 'human_verified', 'source_identified', 'supported_with_caution', 'internal_only',
  'not_publishable', 'Session setup', 'Activity trace', 'Tutor answer', 'Knowledge Bases', 'Domain Skills',
  'Claim Ledger', 'Evidence boundary', 'Native research context', 'Interest before', 'Interest after',
  'Ingestion runs', 'Publish Guard', 'Final human review', 'This device', 'Self-hosted server',
];

function initScript() {
  window.__TAURI_INTERNALS__ = {
    transformCallback() { return 0; }, unregisterCallback() {}, convertFileSrc() { return ''; },
    async invoke(cmd, args = {}) {
      if (cmd === 'desktop_runtime') return { runtimeId: 'desktop-local', status: 'ok', version: '1.0.0', platform: 'linux', endpoint: '' };
      if (cmd === 'desktop_runtime_mode') return { runtimeId: 'desktop-local', activeRuntimeId: 'desktop-local', pendingRuntimeId: 'desktop-local' };
      if (cmd === 'restart_desktop_core') {
        window.__E2E_RESTART_CALLS = (window.__E2E_RESTART_CALLS || 0) + 1;
        if (window.__E2E_DELAY_RESTART__) await new Promise(resolve => setTimeout(resolve, 500));
        if (window.__E2E_REJECT_RESTART__) throw { code: 'LOCAL_SERVICE_UNAVAILABLE' };
        return { status: 'ok', version: '1.0.0' };
      }
      if (args.kind && /secret|provider/i.test(cmd)) return { kind: args.kind, configured: false, secureStoreAvailable: false };
      return {};
    },
  };
}

async function ready(page, path) {
  await page.goto(path, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.waitForFunction(() => Boolean(document.querySelector('main.workspace') && !document.querySelector('.workspaceBoot')), { timeout: 45_000 });
  await page.waitForTimeout(250);
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(initScript);
});

test('主页面不泄漏内部英文状态或架构词', async ({ page }) => {
  for (const path of PAGES) {
    await ready(page, path);
    const text = await page.locator('body').innerText();
    for (const phrase of FORBIDDEN_UI) expect(text, `${path} leaked ${phrase}`).not.toContain(phrase);
  }
});

test('overlays, activity trace and reduced motion have functional fallbacks', async ({ page }) => {
  await ready(page, '/tutor');
  const search = page.locator('button.globalSearch');
  await search.focus();
  await search.click();
  const commandDialog = page.locator('[role="dialog"][aria-label="快速跳转"]');
  await expect(commandDialog).toBeVisible();
  await expect(commandDialog.locator('input')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(commandDialog).toContainText('快速跳转');
  expect(await commandDialog.evaluate(dialog => dialog.contains(document.activeElement))).toBeTruthy();
  await page.keyboard.press('Shift+Tab');
  await expect(commandDialog.locator('input')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.locator('.commandBackdrop')).toHaveCount(0, { timeout: 1_000 });
  await expect(search).toBeFocused();

  const trace = page.locator('.buiTraceHeader');
  await expect(trace).toHaveCount(1);
  const before = await trace.getAttribute('aria-expanded');
  await trace.click();
  expect(await trace.getAttribute('aria-expanded')).not.toBe(before);
  await expect(page.locator('.buiTraceBody')).not.toHaveClass(/is-open/);
  await trace.click();
  await expect(page.locator('.buiTraceBody')).toHaveClass(/is-open/);

  const area = page.locator('.areaSelectButton');
  await area.click();
  await expect(page.locator('.areaMenu[data-state="open"]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.areaMenu[data-state="closing"]')).toHaveCount(1);
  await expect(page.locator('.areaMenu')).toHaveCount(0, { timeout: 1_000 });
  await expect(area).toBeFocused();

  const editWorkspace = page.getByRole('button', { name: '调整工作台' });
  await editWorkspace.click();
  const cards = page.locator('.widgetCard');
  const firstMoveBack = cards.first().getByRole('button', { name: /向后移动/ });
  await expect(firstMoveBack).toBeEnabled();
  await firstMoveBack.click();
  await expect(cards.first()).toHaveAttribute('data-widget-id', 'questions');
  const addWidget = page.locator('.addWidgetCard');
  await addWidget.click();
  await expect(page.locator('[role="dialog"][aria-labelledby="widget-picker-title"]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.widgetPickerBackdrop.is-closing')).toHaveCount(1);
  await expect(page.locator('.widgetPickerBackdrop')).toHaveCount(0, { timeout: 1_000 });
  await expect(addWidget).toBeFocused();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.mobileMenuButton').click();
  await expect(page.locator('.desktopSidebar')).toHaveClass(/is-open/);
  await expect(page.locator('.mobileNavBackdrop')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.desktopSidebar')).not.toHaveClass(/is-open/);
  await expect(page.locator('.mobileNavBackdrop.is-closing')).toHaveCount(1);
  await expect(page.locator('.mobileNavBackdrop')).toHaveCount(0, { timeout: 1_000 });

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await search.click();
  const durations = await page.locator('.commandBackdrop, .commandPalette').evaluateAll(nodes => nodes.flatMap(node => [getComputedStyle(node).transitionDuration, getComputedStyle(node).animationDuration]));
  expect(durations.every(value => value === '0s' || value === '0.01ms')).toBeTruthy();
});

test('Curiosity write action is busy, disabled and not duplicated', async ({ page }) => {
  let writes = 0;
  await page.route('**/questions', async route => {
    if (route.request().method() !== 'POST') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ questions: [] }) });
    writes += 1;
    await new Promise(resolve => setTimeout(resolve, 500));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'busy-test' }) });
  });
  await ready(page, '/curiosity');
  const input = page.locator('textarea[aria-label="记录一个真实问题"]');
  await input.fill('验证重复提交保护');
  const submit = page.locator('button[aria-label="记录问题"]');
  await submit.click();
  await expect(submit).toBeDisabled();
  await submit.click({ force: true });
  await expect.poll(() => writes).toBe(1);
  await expect(submit).toHaveAttribute('aria-label', '记录问题', { timeout: 2_000 });
  await input.fill('确认忙碌态已经结束');
  await expect(submit).toBeEnabled({ timeout: 2_000 });
});

test('Learning sections are unique and concept save is busy-safe', async ({ page }) => {
  let writes = 0;
  await page.route(/\/api\/concepts(?:\?.*)?$/, async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== 'POST' || !url.pathname.endsWith('/concepts')) return route.continue();
    writes += 1;
    await new Promise(resolve => setTimeout(resolve, 500));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'learning-busy-test' }) });
  });
  await ready(page, '/learning');
  await expect(page.getByRole('heading', { name: '创建概念', exact: true })).toHaveCount(1);
  await expect(page.getByRole('heading', { name: '概念与理解', exact: true })).toHaveCount(1);

  await page.getByRole('tab', { name: /笔记/ }).click();
  await expect(page.getByRole('heading', { name: '写一条学习笔记', exact: true })).toHaveCount(1);
  await page.getByRole('tab', { name: /练习/ }).click();
  await expect(page.getByRole('heading', { name: '新增一道练习', exact: true })).toHaveCount(1);

  await page.getByRole('tab', { name: /概念/ }).click();
  const conceptCard = page.locator('section.card').filter({ hasText: '创建概念' }).first();
  await conceptCard.locator('input').fill('忙碌态测试概念');
  const save = conceptCard.locator('button').first();
  await save.click();
  await expect(save).toBeDisabled();
  await expect(save).toHaveText('正在保存…');
  await save.click({ force: true });
  await expect.poll(() => writes).toBe(1);
  await expect(save).toBeEnabled({ timeout: 2_000 });
});

test('System feature write is busy-safe and handles failure in user copy', async ({ page }) => {
  let writes = 0;
  await page.route(/\/api\/features\/[^/]+$/, async route => {
    const request = route.request();
    if (request.method() !== 'PUT') return route.continue();
    writes += 1;
    await new Promise(resolve => setTimeout(resolve, 500));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
  await ready(page, '/system');
  await page.getByRole('tab', { name: /功能开关/ }).click();
  const toggle = page.locator('tbody tr').first().locator('button').first();
  await toggle.click();
  await expect(toggle).toBeDisabled();
  await expect(toggle).toHaveText('处理中…');
  await toggle.click({ force: true });
  await expect.poll(() => writes).toBe(1);
  await expect(toggle).toBeEnabled({ timeout: 2_000 });

  await page.unroute(/\/api\/features\/[^/]+$/);
  await page.route(/\/api\/features\/[^/]+$/, async route => {
    if (route.request().method() !== 'PUT') return route.continue();
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'internal feature failure' }) });
  });
  await toggle.click();
  await expect(page.locator('.notice')).toContainText('本地服务');
});

test('Workspace replace picker preserves unique widget identity', async ({ page }) => {
  await ready(page, '/learning');
  await page.getByRole('button', { name: '调整工作台' }).click();
  const cards = page.locator('.widgetCard');
  const otherWidgetId = await cards.nth(1).getAttribute('data-widget-id');
  await cards.first().getByRole('button', { name: '替换' }).click();
  const picker = page.locator('[role="dialog"][aria-labelledby="widget-picker-title"]');
  await expect(picker).toBeVisible();
  const otherTitle = { 'review-queue': '待复习内容', 'questions': '待回答的问题', 'recent-outputs': '最近产出' }[otherWidgetId] || '待复习内容';
  await expect(picker.getByRole('button', { name: new RegExp(otherTitle) })).toHaveCount(0);
  await picker.getByRole('button', { name: /学习节奏/ }).click();
  const ids = await page.locator('.widgetCard').evaluateAll(nodes => nodes.map(node => node.dataset.widgetId));
  expect(new Set(ids).size).toBe(ids.length);
});
