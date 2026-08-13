# v0.3.1 Independent Product / Provider Boundary Audit

**Audit target:** the exact v0.3.0 release ZIP generated in the previous cycle, followed by the v0.3.1 corrective working copy.
**Primary question:** Is Psychology Growth an independent product that integrates DeepTutor as an optional capability provider, or has the code/documentation drifted into a DeepTutor fork/branch/distribution architecture?

## Executive conclusion

After correction, the answer is **independent product + optional provider**.

The original v0.3.0 release was already **not a source-code fork**: it had independent package/product names, no vendored DeepTutor source tree, no submodule, no direct upstream `import deeptutor`, separate product database/domain models, and a separately deployed sidecar that installed the published DeepTutor package.

However, the audit found three material architecture/identity defects that weakened that boundary:

1. **Product identity defect — fixed.** Current branding over-centered DeepTutor (`DeepTutor-Powered`, `DeepTutor Native Learning Runtime`).
2. **Plugin graph defect — fixed.** Multiple local product plugins hard-depended on `integration.deeptutor`, which made an external provider a parent node of local functionality.
3. **Lifecycle enforcement defect — fixed.** Disabling `integration.deeptutor` did not consistently gate provider execution if deployment configuration still enabled it.

v0.3.1 fixes all three and adds regression enforcement.

## 1. Fork / source provenance audit

### PASS — independent product identity in code

- Root Python project: `psychology-growth`.
- Web project: `psychology-growth-web`.
- API title: `Psychology Growth API`.
- Domain/database models use Psychology Growth concepts and generic upstream reference fields.

### PASS — no vendored upstream code

The release tree contains no top-level `deeptutor/` upstream source tree and no `.gitmodules` entry. `infra/deeptutor/Dockerfile` installs a pinned published package in an external sidecar rather than cloning/copying upstream source.

### PASS — no direct upstream Python imports

Static scan of `apps/`, `packages/`, and `adapters/` finds no `import deeptutor` / `from deeptutor ...`. Product code imports its own adapter package `pg_deeptutor`; only the sidecar runtime installs the upstream package.

### PASS — repository/product data ownership is independent

Psychology Growth owns canonical data for questions, sources, evidence, claims, concepts, mastery, growth memory, notes, practice, writing, books and review/approval state. Upstream IDs are projections/references, not primary keys for product ownership.

## 2. Provider boundary audit

### FINDING PB-01 · High · Product plugins hard-depended on DeepTutor — FIXED

**Affected v0.3.0 manifests included:** Knowledge/RAG, Learning Notebook, Memory Graph, Practice, Tutor Persona and Tutor Runtime.

Because Plugin Runtime enforces dependency lifecycle, those hard dependencies contradicted the own-data-first promise: a user could not cleanly regard DeepTutor as a removable provider while local Psychology Growth functionality remained independently enabled.

**Correction:** every Psychology Growth product plugin is now provider-independent. `integration.deeptutor` is a leaf integration/provider plugin rather than a parent product plugin.

**Regression test:** `test_product_plugins_do_not_hard_depend_on_deeptutor_provider`.

### FINDING PB-02 · High · Plugin disable did not reliably disable provider execution — FIXED

v0.3.0 primarily checked `DEEPTUTOR_ENABLED`; plugin lifecycle state could say disabled while business code still attempted provider calls.

**Correction:** `apps/api/pg_api/capability_providers.py` is the single provider gate. DeepTutor execution requires:

```text
DEEPTUTOR_ENABLED=true
AND
integration.deeptutor plugin enabled
```

Disabling either side removes only provider execution/projection paths.

**Regression test:** with deployment env enabled and provider plugin explicitly disabled, local Knowledge Base, Practice, Learning Note and Tutor Session creation still succeed while DeepTutor capability calls are unavailable.

### FINDING PB-03 · Medium · Provider gate lived in Knowledge service — FIXED

During the first corrective pass, the gate was placed in `knowledge.py`. That still made unrelated capabilities indirectly depend on a product business module for provider access.

**Correction:** moved to dedicated `capability_providers.py`; Research, Knowledge, Tutor, Co-Writer, Living Book, Learning Assets and Memory Graph share that provider boundary.

### FINDING PB-04 · Medium · Current branding looked like a DeepTutor edition — FIXED

The terms `DeepTutor-Powered` and `DeepTutor Native Learning Runtime` were technically descriptive but product-identity hostile.

**Correction:** current release line is **Psychology Growth v0.3.1 Independent Learning Runtime**. DeepTutor appears only where identifying the optional third-party integration is necessary. Historical baseline/release documents remain immutable historical records rather than being rewritten.

## 3. Canonical-data and deletion/replacement behavior

### PASS — disabling provider preserves local product workflows

Architecture tests demonstrate that provider disable does not remove/disable local Knowledge/RAG library metadata, Practice, Learning Notes, Personas, Memory Graph, Tutor Runtime or Living Book plugins. Local object creation still succeeds.

### PASS — DeepTutor projections are not canonical facts

- RAG indexes are rebuildable from locally-owned Source files/mappings.
- Retrieval candidates are not Evidence.
- Question Notebook results do not auto-upgrade Mastery.
- DeepTutor Notebook does not replace Learning Notes.
- DeepTutor Memory is auxiliary; Growth Memory remains authoritative.
- DeepTutor Book projection does not replace local Living Book/chapter fingerprints.
- Visual output requires review and does not become a verified Claim automatically.

## 4. Security and privacy audit

### PASS — loopback-first deployment defaults

Compose maps API/Web/DeepTutor ports through `${HOST_BIND:-127.0.0.1}`. The local Makefile development server is corrected to bind `127.0.0.1` by default. The API container itself listens on `0.0.0.0` only inside the container, which is required for container port routing while host exposure stays loopback-scoped.

### PASS — local source path boundary

Local Source files are stored under a dedicated `LocalFilesystemStorage` root with path traversal protection; public Source creation cannot inject arbitrary absolute server paths. Download resolves only locally-owned Source keys.

### PASS — no product code-execution surface detected

Static scan found no `eval`, Python `exec`, `os.system`, `subprocess`, `shell=True`, or arbitrary executable-plugin route in product code.

### LIMITATION S-01 · High if exposed remotely · No native app authentication

v0.3.1 is explicitly a trusted single-user/local-private product. CORS is not authentication. Exposing API/Web ports directly to an untrusted network would make sensitive psychology/learning data accessible. Keep loopback/private-network deployment or add a trusted authenticated reverse proxy until native auth is designed.

### LIMITATION S-02 · Medium · PermissionBroker is not a hostile-code sandbox

It enforces first-party manifest capability declarations; it does not isolate arbitrary Python. Third-party executable plugin ecosystems require signing/review/process isolation before being supported.

## 5. Replaceability / abstraction audit

### PASS — canonical product contracts remain provider-neutral

`packages/engine-contracts` defines Research, Knowledge, Parsing, Retrieval, Learning, Memory, Visualization and Skill contracts without importing provider adapters.

### DEBT A-01 · Medium · orchestration still names DeepTutor-specific bridge classes

Application services for Book, Notebook/Persona/Question Notebook, Memory/Visualize and some Tutor paths construct `pg_deeptutor` bridge classes after the provider gate. This does **not** make the project a fork and it does not affect canonical ownership, but a future second provider for the same capability would require a provider registry/factory to avoid editing orchestration modules.

**Recommendation:** add a capability-provider registry only when a second concrete provider exists; do not create speculative abstractions that add complexity without an implementation.

### DEBT A-02 · Low/Medium · adapter code ships with the product build

Disabling DeepTutor is a supported runtime state; physically deleting `adapters/deeptutor` from the application source is not. This is a normal compiled-in optional integration pattern, not dynamic plugin-package isolation. If true uninstallable provider packages become a goal, package adapters as optional distributions later.

### DEBT A-03 · Medium · RAG engine IDs are provider-family specific

Knowledge Base `rag_provider` currently uses values such as `llamaindex`, `lightrag`, `graphrag`, and `pageindex`. They are local configuration, not product identity, but a future non-DeepTutor RAG implementation may need namespaced provider/engine fields instead of assuming these IDs are universal.

## 6. Reliability / release engineering audit

### PASS — previous functional suite preserved

The v0.3.0 exact release ZIP passed its existing 53 tests before corrective changes. After the v0.3.1 boundary changes, the suite is 56 tests and all pass.

### LIMITATION R-01 · Medium · additive schema bootstrap, not general migrations

The schema ledger plus SQLAlchemy `create_all()` is sufficient for the current additive history but is not a complete migration system. Future changes to existing table columns/constraints require explicit migrations before release.

### LIMITATION R-02 · Medium · no committed npm lockfile

The Web project has no package lock in the release tree. This does not affect Python/provider independence, but it reduces reproducibility of production JS dependency resolution. Add and maintain the lockfile when a package-manager install is available in the deployment/CI environment.

### LIMITATION R-03 · Environment-dependent live verification

A source/mock contract suite cannot substitute for:

- real Docker/Compose startup;
- live DeepTutor v1.5.11 sidecar calls;
- real DeepSeek calls with user credentials;
- production Next.js install/build/browser E2E.

These must remain explicit deployment-host acceptance gates unless actually executed.

## 7. Licensing / third-party identity

DeepTutor v1.5.11 is consumed as a separately installed third-party package in the optional sidecar. `THIRD_PARTY_NOTICES.md` records the compatibility baseline and attribution. Psychology Growth does not claim to be an official DeepTutor distribution, fork, branch, or endorsed downstream product.

## 8. Verification gates added by v0.3.1

The release must fail if any of the following regress:

1. A top-level vendored `deeptutor/` source tree or DeepTutor submodule appears.
2. Product/application source directly imports the upstream `deeptutor` Python package.
3. Any Psychology Growth plugin hard-depends on `integration.deeptutor`.
4. Current product identity reintroduces `DeepTutor-Powered` or `DeepTutor Native Learning Runtime`.
5. Provider execution ignores either environment configuration or plugin lifecycle state.
6. Disabling DeepTutor prevents local canonical Knowledge/Practice/Note/Tutor Session workflows.

## Final classification

**PASS WITH EXPLICIT NON-BLOCKING DEBTS.**

Psychology Growth v0.3.1 is architecturally an independent product. DeepTutor is an optional, adapter-isolated external capability provider. The high-severity provider-boundary defects found in v0.3.0 are corrected and regression-tested. Remaining items concern future provider-registry ergonomics, authentication for remote deployment, mature migration tooling, JS lockfile reproducibility, and live deployment verification—not fork identity or canonical product ownership.

## 9. Project licensing housekeeping

### LIMITATION L-01 · Low/Medium for public distribution · no Psychology Growth LICENSE selected

The release tree contains `THIRD_PARTY_NOTICES.md` but no license file declaring terms for Psychology Growth's own source. This is not a runtime defect and no license should be invented by the implementation. Before publishing the repository as reusable open source, the owner should deliberately choose and add a project license; until then, treat the code as a private project rather than assuming open-source redistribution rights.
