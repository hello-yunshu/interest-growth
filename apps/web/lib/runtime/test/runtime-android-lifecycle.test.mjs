// Gate R0.4 §R0.4 — Android Back + suspend/resume lifecycle adapter tests.
//
// Run with: node --test apps/web/lib/runtime/test/runtime-android-lifecycle.test.mjs
//
// The tauri-android adapter exposes `handleBack` and `onSuspendResume`. These
// tests prove Back falls back to WebView history / root behavior and that
// `onSuspendResume` fires the callback only when the page returns to the
// foreground (resume != Connected — the caller re-evaluates the session).
import test from 'node:test';
import assert from 'node:assert/strict';

import * as tauriAndroid from '../platforms/tauri-android.js';

// ---- helpers ------------------------------------------------------------
function installDom({ visible = true, historyLength = 1 } = {}) {
  const listeners = new Map();
  const document = {
    visibilityState: visible ? 'visible' : 'hidden',
    addEventListener(type, fn) {
      listeners.set(type, fn);
    },
    removeEventListener(type, fn) {
      if (listeners.get(type) === fn) listeners.delete(type);
    },
  };
  const window = {
    history: {
      length: historyLength,
      back() {
        this._backCalled = true;
      },
    },
    _backCalled: false,
    historyBack() {
      this._backCalled = true;
    },
  };
  const originalDocument = globalThis.document;
  const originalWindow = globalThis.window;
  globalThis.document = document;
  globalThis.window = window;
  return {
    document,
    listeners,
    simulate(type) {
      const fn = listeners.get(type);
      if (fn) fn();
    },
    restore() {
      if (originalDocument === undefined) delete globalThis.document;
      else globalThis.document = originalDocument;
      if (originalWindow === undefined) delete globalThis.window;
      else globalThis.window = originalWindow;
    },
  };
}

// ---- §1 Back -------------------------------------------------------------
test('handleBack navigates WebView history when history exists', async () => {
  const dom = installDom({ historyLength: 3 });
  try {
    const handled = await tauriAndroid.handleBack();
    assert.equal(handled, true);
  } finally {
    dom.restore();
  }
});

test('handleBack returns false at root (no history to pop)', async () => {
  const dom = installDom({ historyLength: 1 });
  try {
    const handled = await tauriAndroid.handleBack();
    assert.equal(handled, false);
  } finally {
    dom.restore();
  }
});

// ---- §2 suspend/resume -----------------------------------------------------
test('onSuspendResume fires callback only on return to foreground', async () => {
  const dom = installDom({ visible: false }); // app starts backgrounded
  try {
    let calls = 0;
    const unsubscribe = tauriAndroid.onSuspendResume(() => { calls += 1; });

    // Still hidden → no callback.
    dom.simulate('visibilitychange');
    assert.equal(calls, 0, 'must not fire while the page is still hidden');

    // Return to foreground → callback fires.
    dom.document.visibilityState = 'visible';
    dom.simulate('visibilitychange');
    assert.equal(calls, 1, 'must fire exactly once on resume');

    // Background again → no callback.
    dom.document.visibilityState = 'hidden';
    dom.simulate('visibilitychange');
    assert.equal(calls, 1);

    // Unsubscribe stops all future callbacks.
    unsubscribe();
    dom.document.visibilityState = 'visible';
    dom.simulate('visibilitychange');
    assert.equal(calls, 1, 'unsubscribe must stop callbacks');
  } finally {
    dom.restore();
  }
});

test('onSuspendResume is a no-op without a document (SSR-safe)', () => {
  const originalDocument = globalThis.document;
  delete globalThis.document;
  try {
    let calls = 0;
    const unsubscribe = tauriAndroid.onSuspendResume(() => { calls += 1; });
    unsubscribe();
    assert.equal(calls, 0);
  } finally {
    if (originalDocument !== undefined) globalThis.document = originalDocument;
  }
});