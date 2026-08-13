// Gate C §10 / §21.5 — retry safety contract.
//
// Safe retry: GET, HEAD, OPTIONS, PUT, DELETE are idempotent and can be
// retried on transient failure. POST with ambiguous transport failure must
// NOT auto-retry because the server may have already committed. The only
// exception is POST after a 401 refresh: the original request never reached
// the business path, so a single retry is safe.
//
// The refresh itself must not enter recursion; a refresh attempt that fails
// is terminal (LoginExpired) and does not trigger another refresh.

const IDEMPOTENT_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE']);

export function isIdempotentMethod(method) {
  return IDEMPOTENT_METHODS.has((method || '').toUpperCase());
}

export class RetryPolicy {
  constructor({ maxRetries = 3 } = {}) {
    this.maxRetries = maxRetries;
  }

  // Whether a request with the given method and context MAY be retried.
  canRetry(method, { isTransient, afterRefresh } = {}) {
    const m = (method || 'GET').toUpperCase();
    // Only transient (network) failures qualify for retry.
    if (!isTransient) return false;
    if (isIdempotentMethod(m)) return true;
    // POST after a successful 401 refresh: the original request never reached
    // the business path, so one retry is safe.
    if (m === 'POST' && afterRefresh) return true;
    // POST/PATCH with ambiguous failure must NOT auto-retry.
    return false;
  }

  // The number of retries allowed for a given method. Bounded.
  allowedRetries(method, { afterRefresh } = {}) {
    const m = (method || 'GET').toUpperCase();
    if (isIdempotentMethod(m)) return this.maxRetries;
    if (m === 'POST' && afterRefresh) return 1;
    return 0;
  }
}