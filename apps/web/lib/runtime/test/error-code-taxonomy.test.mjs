// Gate R2 §15 — frozen remote error-code taxonomy.
//
// The remote error codes are a user-facing contract (see
// docs/releases/V1_0_RELEASE_CRITERIA.md §15). The renderer must NEVER guess
// state from fuzzy message text; it classifies only exact frozen codes. This
// file freezes the vocabulary and the stable user-facing retry guidance
// (which connection event each code drives) so a refactor cannot silently
// rename a code or flip a terminal verdict.
//
// The 10 user-facing codes below are normative. `INTERNAL_ERROR` is a
// catch-all and is intentionally NOT part of the user-facing taxonomy: it
// must always behave as a retryable transport failure, never as a terminal
// server verdict.
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  REMOTE_ERROR_CODES,
  parseRemoteErrorCode,
  remoteErrorEvent,
} from '../transports/remote.js';

// Normative vocabulary — must match docs/releases/V1_0_RELEASE_CRITERIA.md §15.
// Do not reorder or rename. Adding a NEW code is a release-criteria change.
const FROZEN_USER_FACING_CODES = Object.freeze([
  'NETWORK_UNAVAILABLE',
  'SERVER_UNAVAILABLE',
  'RATE_LIMITED',
  'LOGIN_EXPIRED',
  'IDENTITY_CHANGED',
  'UPDATE_REQUIRED',
  'UNSUPPORTED_SERVER',
  'CREDENTIAL_PERSISTENCE_FAILURE',
  'PROTOCOL_ERROR',
  'RUNTIME_MODE_DENIED',
]);

const INTERNAL_CATCH_ALL = 'INTERNAL_ERROR';

// Expected stable user-facing retry guidance. Terminal classifications only
// for honest server verdicts; anything ambiguous stays NETWORK_FAIL so the
// connection state machine can retry with bounds.
const EVENT_BY_CODE = {
  NETWORK_UNAVAILABLE: 'NETWORK_FAIL',
  SERVER_UNAVAILABLE: 'NETWORK_FAIL',
  RATE_LIMITED: 'NETWORK_FAIL',
  LOGIN_EXPIRED: 'REFRESH_FAIL',
  IDENTITY_CHANGED: 'IDENTITY_MISMATCH',
  UPDATE_REQUIRED: 'INCOMPATIBLE',
  UNSUPPORTED_SERVER: 'UNSUPPORTED_SERVER',
  CREDENTIAL_PERSISTENCE_FAILURE: 'NETWORK_FAIL',
  PROTOCOL_ERROR: 'UNSUPPORTED_SERVER',
  RUNTIME_MODE_DENIED: 'NETWORK_FAIL',
};

test('§15 frozen vocabulary: the 10 user-facing codes are exactly the contract', () => {
  const exported = Object.values(REMOTE_ERROR_CODES);
  const frozen = [...FROZEN_USER_FACING_CODES, INTERNAL_CATCH_ALL];
  assert.deepEqual(
    [...exported].sort(),
    [...frozen].sort(),
    'REMOTE_ERROR_CODES drifted from the frozen §15 vocabulary',
  );
  // Every frozen code must actually be exported (values are the contract).
  for (const code of FROZEN_USER_FACING_CODES) {
    assert.equal(REMOTE_ERROR_CODES[code], code, `code ${code} must self-reference its value`);
  }
  assert.equal(REMOTE_ERROR_CODES[INTERNAL_CATCH_ALL], INTERNAL_CATCH_ALL);
});

test('§15 stable retry guidance: each frozen code maps to its connection event', () => {
  for (const [code, expectedEvent] of Object.entries(EVENT_BY_CODE)) {
    const payload = `{"code":"${code}","message":"anything"}`;
    assert.equal(parseRemoteErrorCode({ message: payload }), code, `parse failed for ${code}`);
    assert.equal(remoteErrorEvent({ message: payload }), expectedEvent, `event mismatch for ${code}`);
  }
});

test('§15 INTERNAL_ERROR is a catch-all and never a terminal verdict', () => {
  const payload = `{"code":"${INTERNAL_CATCH_ALL}","message":"oops"}`;
  assert.equal(parseRemoteErrorCode({ message: payload }), INTERNAL_CATCH_ALL);
  // NETWORK_FAIL is the retryable bucket, never REFRESH_FAIL / INCOMPATIBLE /
  // UNSUPPORTED_SERVER / IDENTITY_MISMATCH.
  assert.equal(remoteErrorEvent({ message: payload }), 'NETWORK_FAIL');
});

test('§15 unknown or fuzzy codes are transport failures, never guessed state', () => {
  // Unknown code string in a coded payload: must NOT map to a terminal verdict.
  assert.equal(parseRemoteErrorCode({ message: '{"code":"AUTH_REQUIRED","message":"x"}' }), 'AUTH_REQUIRED');
  assert.equal(remoteErrorEvent({ message: '{"code":"AUTH_REQUIRED","message":"x"}' }), 'NETWORK_FAIL');
  // Non-JSON human text (e.g. a raw proxy error body) must never classify.
  assert.equal(parseRemoteErrorCode(new Error('socket hang up')), null);
  assert.equal(parseRemoteErrorCode(new Error('401 Unauthorized')), null);
  assert.equal(parseRemoteErrorCode('upstream connection reset'), null);
  assert.equal(parseRemoteErrorCode(undefined), null);
  // Coded payload but with a non-string code: unclassified.
  assert.equal(parseRemoteErrorCode({ message: '{"code":123,"message":"x"}' }), null);
  // Coded payload but missing the code field: unclassified.
  assert.equal(parseRemoteErrorCode({ message: '{"message":"x"}' }), null);
  // A code value without the JSON envelope stays unclassified too.
  assert.equal(parseRemoteErrorCode(new Error('LOGIN_EXPIRED')), null);
});
