# Third-Party / Upstream Design Notice

Interest Growth v0.6.0 RC2 Native Execution Core was cross-validated against
the public behavior/contracts of:

- HKUDS/DeepTutor
- compatibility baseline: v1.5.11
- reviewed commit: `456f9c24226e008f1ff07a7e3455d7b4d39f6221`
- upstream license: Apache License 2.0

RC2 is an Interest Growth-owned behavioral/product adaptation:
- no `deeptutor` Python module is imported by the runtime;
- no DeepTutor source tree is vendored;
- no DeepTutor database becomes canonical product state;
- no claim is made that native lightweight RAG algorithms are the same
  implementation as LlamaIndex, LightRAG, GraphRAG or PageIndex.

A future **exact adapter** may call a separately installed third-party engine.
If an adapter later incorporates third-party source code rather than using it as
a separate dependency/service, that adapter must preserve all applicable
license, copyright and NOTICE obligations.

DeepTutor remains named in compatibility/audit documentation because it is the
upstream capability baseline being cross-validated, not because it is the
Interest Growth product identity.
