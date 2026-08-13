# Third-Party Notices

Interest Growth is an independent product. Third-party Python, JavaScript and Rust dependencies retain their own licenses and terms. This notice does not assign a license to Interest Growth itself.

## Optional exact RAG adapters

- `llama-index-core` (LlamaIndex), `lightrag-hku` (HKUDS LightRAG), Microsoft
  `graphrag`, and Vectify AI `pageindex` are optional, default-off integrations.
- Their reviewed upstream repositories declare MIT licenses. They are not
  vendored and retain their own copyright, license, dependency and service
  terms.
- Installing or configuring them can materially increase runtime/image size,
  model and indexing resource use, data-egress exposure, and transitive
  dependency surface. PageIndex uses an external API and is not offline/local.
- See `docs/architecture/EXACT_RAG_ADAPTERS.md` for the reviewed API lines and
  operational boundaries.

## Desktop credential storage

- `keyring-rs` is used by the Tauri desktop runtime to access the operating system credential store.
- macOS provider secrets are stored through Keychain Services; Windows provider secrets are stored through Windows Credential Manager.
- `keyring-rs` is distributed under MIT OR Apache-2.0 terms.
- Psychology Growth does not implement a custom encrypted secret file as a replacement for the OS credential store.

## Desktop shell

- Tauri 2 and its official Shell, Updater, Window State, Dialog, File System, Opener and Single Instance plugins provide the desktop shell/runtime boundary.
- Tauri and the official plugins retain their upstream license terms; they are dependencies, not Psychology Growth product identity.
- Next.js/React provide the static renderer and retain their upstream license terms.
- No third-party signing credential or updater private key is redistributed in this source package.

## Design reference

- Beautiful UI (`beautiful-ui-five.vercel.app`) was studied as a visual/interaction reference for AI-native interface concepts.
- Psychology Growth implements its own React/CSS primitives and product semantics; the reference site is not a vendored runtime dependency and its source code/assets are not redistributed in this package.
- The reference “Thinking” concept is intentionally implemented only as Psychology Growth Public Activity Trace, not private model chain-of-thought.
