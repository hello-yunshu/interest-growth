// Gate C §3 — single import point for the ClientRuntime vocabulary.
//
// Feature pages import from here (or from api.js), never from platform.js or
// the tauri packages directly.
export * from './contract.js';
export * from './descriptors.js';
