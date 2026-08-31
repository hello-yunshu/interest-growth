import test from 'node:test';
import assert from 'node:assert/strict';

import { getDesktopRuntimeMode } from '../platforms/browser.js';

test('browser runtime mode uses the MODE_LOADED contract', async () => {
  assert.deepEqual(await getDesktopRuntimeMode(), {
    activeRuntimeId: 'desktop-local',
    pendingRuntimeId: 'desktop-local',
    sidecarLaunch: false,
    sessionImmutable: true,
  });
});
