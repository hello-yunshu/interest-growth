'use strict';

const { test, expect } = require('@playwright/test');

const PAGES = ['/', '/curiosity', '/research', '/knowledge', '/learning', '/tutor', '/outputs', '/writing', '/book', '/content', '/growth', '/career', '/system'];
const FORBIDDEN_UI = [
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
  await expect(page.locator('[role="dialog"][aria-label="快速跳转"]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.commandBackdrop')).toHaveCount(0, { timeout: 1_000 });
  await expect(search).toBeFocused();

  const trace = page.locator('.buiTraceHeader');
  if (await trace.count()) {
    const before = await trace.getAttribute('aria-expanded');
    await trace.click();
    expect(await trace.getAttribute('aria-expanded')).not.toBe(before);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.mobileMenuButton').click();
  await expect(page.locator('.desktopSidebar')).toHaveClass(/is-open/);
  await expect(page.locator('.mobileNavBackdrop')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.desktopSidebar')).not.toHaveClass(/is-open/);

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await search.click();
  const durations = await page.locator('.commandBackdrop, .commandPalette').evaluateAll(nodes => nodes.map(node => getComputedStyle(node).transitionDuration));
  expect(durations.every(value => value === '0s' || value === '0.01ms')).toBeTruthy();
});
