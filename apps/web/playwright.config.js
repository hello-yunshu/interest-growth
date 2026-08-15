// Gate R1 "Web/UX closure" Playwright runner.
//
// Runs the responsive + accessibility + rendering-state checks on the core
// pages of the Interest Growth web app. The web app expects a running Python
// host Core (see scripts/ci/web_e2e_server.sh) reached through the
// NEXT_PUBLIC_API_BASE the dev/start server was booted with.
'use strict';

const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './e2e',
  // One browser thread; the fixture against a single loopback Core is cheap and
  // keeps the checks deterministic.
  workers: 1,
  fullyParallel: false,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  retries: 0,
  reporter: [['list']],
  use: {
    // The web app is a client-side app; the fixture boots the Next dev server on
    // 127.0.0.1:3000 (see scripts/ci/web_e2e_server.sh), which is the loopback
    // origin the Core's CORS allow-list permits. Override with E2E_WEB_URL if needed.
    baseURL: process.env.E2E_WEB_URL || 'http://127.0.0.1:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    colorScheme: 'light',
  },
});