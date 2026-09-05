'use strict';

const { test, expect } = require('@playwright/test');
const API_BASE = process.env.E2E_API_URL || 'http://127.0.0.1:8000';

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

test('Energy Mode is selected, persisted and visible after reload', async ({ page }) => {
  let requestBody = null;
  await page.route('**/api/questions', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    requestBody = route.request().postDataJSON();
    return route.continue();
  });
  await ready(page, '/curiosity');
  await page.getByRole('button', { name: '轻量看看' }).click();
  const input = page.locator('textarea[aria-label="记录一个真实问题"]');
  await input.fill('验证轻量投入 ' + Date.now());
  const questionResponse = page.waitForResponse(response => response.url().includes('/api/questions') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '记录问题' }).click();
  await expect.poll(() => requestBody && requestBody.energy_mode).toBe('light');
  const questionResult = await questionResponse;
  expect(questionResult.status(), await questionResult.text()).toBe(200);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => Boolean(document.querySelector('main.workspace') && !document.querySelector('.workspaceBoot')));
  await expect(page.locator('tbody tr').filter({ hasText: '轻量' }).first()).toBeVisible();
});

test('Living Book proposal and spine reviews persist edited titles', async ({ page }) => {
  const topic = await (await page.request.post(API_BASE + '/api/topics', { data: { title: '书籍回归主题 ' + Date.now() } })).json();
  const book = await (await page.request.post(API_BASE + '/api/living-books', { data: { topic_id: topic.id, title: '行为书 ' + Date.now(), intent: '行为级回归' } })).json();
  const proposal = { title: '行为书', purpose: '确认提案', chapters: [{ title: '第一章', purpose: '基础' }, { title: '第二章', purpose: '进阶' }] };
  let spine = { title: '行为书', purpose: '确认结构', chapters: [{ title: '第一章', purpose: '基础' }, { title: '第二章', purpose: '进阶' }] };
  let projectionStatus = 'proposal_pending_review';
  let confirmedProposal = null;
  let confirmedSpine = null;
  await page.route('**/api/living-books/' + book.id, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ book: { ...book, projection_status: projectionStatus, proposal_json: proposal, spine_json: spine }, chapters: [] }) }));
  await page.route('**/api/living-books/' + book.id + '/project', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }));
  await page.route('**/api/living-books/' + book.id + '/confirm-proposal', async route => { confirmedProposal = route.request().postDataJSON(); spine = { ...confirmedProposal.proposal, chapters: confirmedProposal.proposal.chapters }; projectionStatus = 'spine_pending_review'; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }); });
  await page.route('**/api/living-books/' + book.id + '/confirm-spine', async route => { confirmedSpine = route.request().postDataJSON(); projectionStatus = 'confirmed'; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }); });
  await ready(page, '/book');
  await page.getByLabel('选择学习书').selectOption(book.id);
  await page.getByRole('button', { name: '生成章节提案' }).click();
  await page.getByRole('button', { name: '审阅书籍提案' }).click();
  await page.getByLabel('第 1 章标题').fill('已编辑第一章');
  await page.getByRole('button', { name: '增加章节' }).click();
  await page.getByRole('button', { name: '下移' }).first().click();
  await page.getByRole('button', { name: '确认并生成章节结构' }).click();
  await expect.poll(() => confirmedProposal && confirmedProposal.proposal && confirmedProposal.proposal.chapters.some(chapter => chapter.title === '已编辑第一章')).toBe(true);
  await page.getByRole('button', { name: '审阅章节结构' }).click();
  await page.getByLabel('编辑第 1 章标题').fill('已确认第一章');
  await page.getByRole('button', { name: '确认章节结构' }).click();
  await expect.poll(() => confirmedSpine && confirmedSpine.spine && confirmedSpine.spine.chapters[0].title).toBe('已确认第一章');
});

test('Visual Artifact can be reopened and renders its persisted explanation', async ({ page }) => {
  const topic = await (await page.request.post(API_BASE + '/api/topics', { data: { title: '可视化回归主题 ' + Date.now() } })).json();
  const createdConcept = await (await page.request.post(API_BASE + '/api/concepts', { data: { topic_id: topic.id, name: '可视化回归概念 ' + Date.now(), definition: '一个可重新打开的概念' } })).json();
  const concept = createdConcept.concept;
  const artifactId = 'e2e-visual-' + Date.now();
  const artifact = { id: artifactId, topic_id: topic.id, kind: 'visual_explanation', title: '可重新打开的可视化', status: 'active', approved_at: null, metadata_json: { provider: 'native.interest-growth', capability: 'visualize' } };
  const manifest = { title: '可重新打开的可视化', nodes: [{ id: 'n1', label: '概念节点', type: 'concept' }], edges: [], annotations: ['重新打开后仍保留结构。'] };
  await page.route('**/api/concepts/' + concept.id + '/visualize', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ artifact, result: manifest }) }));
  await page.route('**/api/visual-artifacts/' + artifactId + '/preview', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ artifact, manifest }) }));
  await page.route('**/api/artifacts/' + artifactId, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ artifact, content: null, grounding_refs: [] }) }));
  await ready(page, '/learning');
  await page.locator('.buiInlineEditor').filter({ hasText: concept.name }).first().getByRole('button', { name: '画图理解' }).click();
  await expect(page.getByRole('region', { name: '可视化解释' })).toBeVisible();
  await page.goto('/artifacts/detail?id=' + artifactId);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('region', { name: '可视化解释' })).toBeVisible();
  await expect(page.getByText('重新打开后仍保留结构。')).toBeVisible();
});

test('External RAG creation stays blocked until egress consent is checked', async ({ page }) => {
  let writes = 0;
  await page.route('**/api/knowledge/providers', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ providers: [{ id: 'pageindex', name: 'PageIndex', native: false, ingestion_supported: true, configured: true }] }) }));
  await page.route('**/api/knowledge/bases', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    writes += 1;
    const body = route.request().postDataJSON();
    if (!body.external_data_egress_confirmed) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'external_data_egress_confirmation_required', message: '需要确认资料外发。' } }) });
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'e2e-kb-' + Date.now(), name: body.name, status: 'local_only' }) });
  });
  await ready(page, '/knowledge');
  await page.getByLabel('资料库名称').fill('外发同意回归 ' + Date.now());
  await page.getByLabel('检索引擎（RAG）').selectOption('pageindex');
  await page.getByRole('button', { name: '创建资料库' }).click();
  await expect(page.locator('.notice')).toContainText('该检索引擎需要把资料发送到第三方服务处理');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: '创建资料库' }).click();
  await expect.poll(() => writes).toBe(2);
});

test('Topic lifecycle is operable from the curiosity page', async ({ page }) => {
  const title = '主题生命周期 ' + Date.now();
  await ready(page, '/curiosity');
  const management = page.getByRole('region', { name: '主题管理' });
  await management.getByLabel('主题标题').fill(title);
  const topicResponse = page.waitForResponse(response => response.url().includes('/api/topics') && response.request().method() === 'POST');
  await management.getByRole('button', { name: '创建主题' }).click();
  const topicResult = await topicResponse;
  expect(topicResult.status(), await topicResult.text()).toBe(200);
  const row = management.locator('.cleanRow').filter({ hasText: title });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: '编辑' }).click();
  await management.getByLabel('主题标题').fill(title + ' 已编辑');
  await management.getByRole('button', { name: '保存主题修改' }).click();
  const edited = management.locator('.cleanRow').filter({ hasText: title + ' 已编辑' });
  await edited.getByRole('button', { name: '归档' }).click();
  await page.getByRole('button', { name: '确认归档主题' }).click();
  await management.getByRole('tab', { name: /已归档/ }).click();
  await expect(management.locator('.cleanRow').filter({ hasText: title + ' 已编辑' })).toBeVisible();
  await management.locator('.cleanRow').filter({ hasText: title + ' 已编辑' }).getByRole('button', { name: '恢复' }).click();
  await management.getByRole('tab', { name: /当前主题/ }).click();
  await expect(management.locator('.cleanRow').filter({ hasText: title + ' 已编辑' })).toBeVisible();
});

test('Interest Area lifecycle is operable and default archive stays disabled', async ({ page }) => {
  const name = '生命周期兴趣 ' + Date.now();
  await ready(page, '/system');
  await page.getByRole('tab', { name: /兴趣管理/ }).click();
  const management = page.locator('section.card').filter({ hasText: '兴趣生命周期' }).first();
  await expect(management.getByRole('button', { name: '请先切换' })).toBeDisabled();
  await management.getByLabel('兴趣名称').fill(name);
  const areaResponse = page.waitForResponse(response => response.url().includes('/api/areas') && response.request().method() === 'POST');
  await management.getByRole('button', { name: '创建兴趣' }).click();
  const areaResult = await areaResponse;
  expect(areaResult.status(), await areaResult.text()).toBe(200);
  const row = management.locator('.cleanRow').filter({ hasText: name });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: '编辑' }).click();
  await management.getByLabel('兴趣名称').fill(name + ' 已编辑');
  await management.getByRole('button', { name: '保存兴趣修改' }).click();
  const edited = management.locator('.cleanRow').filter({ hasText: name + ' 已编辑' });
  await edited.getByRole('button', { name: '归档' }).click();
  await page.getByRole('button', { name: '确认归档兴趣' }).click();
  await management.getByRole('tab', { name: /已归档/ }).click();
  await expect(management.locator('.cleanRow').filter({ hasText: name + ' 已编辑' })).toBeVisible();
  await management.locator('.cleanRow').filter({ hasText: name + ' 已编辑' }).getByRole('button', { name: '恢复' }).click();
  await management.getByRole('tab', { name: /当前兴趣/ }).click();
  await expect(management.locator('.cleanRow').filter({ hasText: name + ' 已编辑' })).toBeVisible();
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
