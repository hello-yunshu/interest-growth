// Gate C §9 — explicit connection state machine.
//
// A single "ready/error" boolean is not allowed. Every transition is guarded:
// remote states never silently fall back to local data, and reconnect is
// bounded so there is no infinite retry.
import { CONNECTION_STATES } from './contract.js';

const TERMINAL_STATES = new Set([
  'Offline',
  'LoginExpired',
  'IdentityChanged',
  'UpdateRequired',
  'UnsupportedServer',
  'LocalCoreError',
]);

export class ConnectionStateMachine {
  constructor({ initialState = 'Initializing', maxReconnectAttempts = 3 } = {}) {
    if (!CONNECTION_STATES.includes(initialState)) {
      throw new Error(`unknown connection state: ${initialState}`);
    }
    this.state = initialState;
    this.maxReconnectAttempts = maxReconnectAttempts;
    this.reconnectAttempts = 0;
  }

  get isConnected() {
    return this.state === 'Connected';
  }

  // Terminal states are blocking and never auto-flip back to Connected.
  get isTerminal() {
    return TERMINAL_STATES.has(this.state);
  }

  // Mutations are only allowed when the connection is honestly Connected.
  get mutationsAllowed() {
    return this.state === 'Connected';
  }

  _set(next) {
    if (!CONNECTION_STATES.includes(next)) throw new Error(`unknown connection state: ${next}`);
    this.state = next;
    return next;
  }

  _enterReconnecting() {
    this.reconnectAttempts += 1;
    return this.reconnectAttempts > this.maxReconnectAttempts
      ? this._set('Offline')
      : this._set('Reconnecting');
  }

  handle(event) {
    switch (event) {
      case 'BOOTSTRAP_OK':
        // auth verified + server identity valid + compatible (checked by caller)
        this.reconnectAttempts = 0;
        return this._set('Connected');
      case 'RECONNECT_OK':
        this.reconnectAttempts = 0;
        return this._set('Connected');
      case 'NETWORK_FAIL':
        return this._enterReconnecting();
      case 'REFRESH_OK':
        return this._set('Connected');
      case 'REFRESH_FAIL':
        return this._set('LoginExpired');
      case 'IDENTITY_MISMATCH':
        // Blocking and never auto-accepted.
        return this._set('IdentityChanged');
      case 'INCOMPATIBLE':
        return this._set('UpdateRequired');
      case 'UNSUPPORTED_SERVER':
        return this._set('UnsupportedServer');
      case 'LOCAL_CORE_ERROR':
        return this._set('LocalCoreError');
      case 'RESET':
        this.reconnectAttempts = 0;
        return this._set('Initializing');
      default:
        throw new Error(`unknown connection event: ${event}`);
    }
  }
}
