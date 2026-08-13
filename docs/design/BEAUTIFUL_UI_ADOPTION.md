# Beautiful UI Adoption · Psychology Growth v0.4.1

## 1. Purpose

Psychology Growth v0.4.1 adopts the interaction language demonstrated by **Beautiful UI — Crafted primitives for AI-native interfaces** as a design reference, while preserving Psychology Growth's own product identity, domain model, safety rules and implementation.

This is **not** a vendored UI library, copied source tree, fork or runtime dependency. The reference site exposes interaction concepts and visual examples; Psychology Growth implements its own React components, CSS tokens and product-specific semantics.

The design goal is not "make every card look similar." The goal is to make AI work legible:

- what is running;
- what source/context was used;
- what is merely a recommendation;
- what requires the user's decision;
- what changed between two versions;
- what is product-owned evidence versus retrieved context;
- what failed and what can be retried;
- when the system is waiting for the user rather than silently continuing.

## 2. Reference primitives and product mapping

| Beautiful UI reference primitive | Psychology Growth implementation | Primary product surfaces | Product-specific rule |
|---|---|---|---|
| Loading State | `PixelLoader` | Tutor, Research, Knowledge | Represents real active work; never fake-completes a task. |
| Thinking | `ActivityTrace` | Tutor / agent runtime | **Public activity only.** Never renders hidden/private chain-of-thought or reasoning tokens. |
| Streaming Text | `StreamingText` | Tutor, Research | Streams answer content separately from tools/progress/sources. |
| Approval Card | `ApprovalCard` | Tutor `wait_for_input`, Source invalidation, Practice review, Living Book, Publish Guard, Career review | Human-in-the-loop actions remain explicit and cancellable. |
| Tool Chips | `ToolChips` | Tutor, Knowledge, System | Shows tool identity/status, not hidden reasoning. |
| Task Rows | `TaskRows` | Home, Knowledge ingestion, Living Book | Uses real running/failed/completed product states. |
| Chat | `ChatPanel` | Tutor | Persistent product session, not stateless chat decoration. |
| Prompt Bar | `PromptBar` | Curiosity, Tutor, Research, Knowledge, Writing | Compact composer for intentional user requests/context. |
| Recommendation Card | `RecommendationCard` | Home, Curiosity, Research, Growth | Recommendation remains suggestion; confidence is not evidence strength. |
| Context Cards | `ContextCards` | Knowledge/RAG, Living Book | Retrieved context remains `candidate_not_evidence` until explicit Evidence workflow. |
| Diff Table | `DiffTable` | Co-Writer | AI proposal does not overwrite canonical text until Accept. |
| Records Table | `RecordsTable` | Curiosity, Career, Content, System | Dense desktop records with status/action semantics. |
| Filter Table | `FilterTabs` + filtered records | Research, Learning, Career, System | Filters reorganize known data; they do not change truth state. |
| Sidebar Nav | grouped `DesktopShell` navigation | Entire desktop app | Product workspaces are grouped by user intent, not by backend module names. |
| Search | keyboard Command Palette | Entire desktop app | `⌘K / Ctrl+K`, live filtering, arrows, Enter, Escape and empty state. |
| Insight Cards | `InsightCards` | Home, Growth, Career, System | Insight is a surfaced observation, never automatic diagnosis or mastery judgment. |
| Code Block | `CodeBlock` | Content, Growth, System diagnostics | Used for transparent artifacts/diagnostics, not hidden model reasoning. |
| Fine-tune Card | `FineTunePanel` | System / Provider settings | Adjusts explicit settings; secrets remain in native credential store. |
| Selection Actions | `SelectionActions` | Writing, Learning | Acts on explicit user-selected content; Co-Writer output remains a revision proposal. |

`SafeSvgPreview` is an additional Psychology Growth primitive. It replaces privileged-renderer raw HTML/SVG insertion with an image preview.

## 3. Visual language

### 3.1 Surfaces

- Quiet warm-neutral base surfaces rather than saturated dashboard panels.
- Native desktop material remains visible where the OS supplies it: macOS semantic sidebar / Windows 11 Mica.
- Thin borders and restrained shadows establish hierarchy without card-wall clutter.
- Elevated AI work surfaces are used only for active reasoning **status**, review, provenance or proposed changes.

### 3.2 Accent and state

The primary accent is a restrained sage/green family. State color is semantic, not decorative:

- neutral: idle / informational;
- accent: running / selected / provider-active;
- success: completed / human-verified state where appropriate;
- warning: waiting for input / review required;
- danger: failed / invalidated / blocked.

Confidence UI must not visually impersonate Evidence verification. A high model confidence remains a recommendation signal only.

### 3.3 Density

Desktop density is intentionally higher than a mobile/web landing page:

- compact tables;
- narrow status chips;
- small tool/action rails;
- persistent workspace navigation;
- optional context inspector;
- keyboard-first actions.

Large hero cards are reserved for the current task, not repeated on every section.

### 3.4 Motion

Animation should reveal state, not entertain:

- pixel shimmer for active work;
- subtle stream cursor/progress;
- status pulse only while genuinely active;
- short transitions for panels and command search.

`prefers-reduced-motion` must suppress nonessential animation.

## 4. AI interaction laws

### 4.1 Public Activity Trace, not chain-of-thought

The source reference calls one primitive “Thinking.” Psychology Growth intentionally narrows this to **Public Activity Trace**.

Allowed examples:

- stage start/end;
- progress;
- tool call/tool result labels;
- source availability;
- wait-for-input;
- done/error.

Activity uses an explicit public-event allowlist. Unknown categories are not rendered by default. Tool call/result rows expose tool identity/status but not raw tool-result bodies.

Blocked categories include:

- `thinking`;
- `reasoning`;
- `chain_of_thought`;
- `cot`;
- `internal_thought`;
- answer deltas (shown in `StreamingText` instead).

The UI must never expose a model's private chain-of-thought merely to imitate the reference site.

### 4.2 Human approval is first-class

Browser-native `prompt`, `confirm` and `alert` are forbidden in product flows. Decisions that change knowledge/evidence/mastery/content/career records use reviewable in-app controls.

Examples:

- invalidate a Source → reason + explicit confirm;
- submit Practice → answer/correctness + optional “keep as mastery evidence”;
- complete Career Experiment → evidence/interest/reflection review;
- Living Book proposal/spine → explicit confirmation;
- Co-Writer → Diff → Accept/Reject;
- Publish Pack → Publish Guard → Human Review.

### 4.3 Context is not evidence

`ContextCards` are provenance/navigation UI. A retrieved chunk, model summary or RAG citation is not automatically a verified Evidence record.

### 4.4 Recommendations do not execute themselves

`RecommendationCard` can surface alternatives and confidence, but cannot silently:

- publish content;
- promote Mastery;
- verify a Claim;
- invalidate a Source;
- complete a career decision;
- start a destructive provider action.

### 4.5 Proposed edits remain proposals

`DiffTable` is a review boundary. Canonical Writing Document text changes only after an explicit Accept action and baseline hash validation.

## 5. Desktop shell

The desktop shell combines two source concepts — Sidebar Nav and Search — with native desktop window behavior.

### Navigation groups

- Focus
- Learn
- Create
- Reflect
- System

The navigation names user workspaces, not microservices or provider internals.

### Command Palette

- `⌘K` on macOS / `Ctrl+K` on Windows;
- live search;
- Arrow Up/Down selection;
- Enter to navigate;
- Escape to close;
- explicit empty state.

The palette remains local navigation/search in v0.4.1; arbitrary command execution is not enabled. Prompt Bar does not display fake `@` or `/` buttons unless the product supplies real handlers.

## 6. Security-specific UI rules

- No `dangerouslySetInnerHTML` in the privileged desktop renderer.
- Generated SVG is previewed as a data-image (`SafeSvgPreview`), not injected markup.
- External source links only become clickable for `http:` or `https:` URLs; desktop mode delegates them to the OS default browser through the scoped Tauri Opener plugin rather than loading them into the privileged main WebView.
- Renderer CSP remains unable to connect directly to DeepSeek/DeepTutor/provider HTTPS endpoints.
- Provider secrets remain set/delete/status-only from JS; no secret read-back.
- Tauri native Save flow keeps user-selected path scoping; no broad `fs:write-all` permission.

## 7. Product surface composition

### Home
`InsightCards + RecommendationCard + TaskRows` provide a calm “what changed / what matters / what next” view rather than vanity metrics or streak pressure.

### Curiosity
`PromptBar + FilterTabs + RecordsTable + RecommendationCard` keeps Quick Explore lightweight and visibly `not_evidence`.

### Tutor
`ChatPanel + PromptBar + StreamingText + ActivityTrace + ToolChips + ApprovalCard` separates answer, public runtime activity, tools and human interaction.

### Research
`PromptBar + StreamingText + ToolChips + ApprovalCard + filters` makes source verification/revocation auditable and keeps candidate research separate from Evidence.

### Knowledge
`ContextCards + TaskRows + RecordsTable` represents ingestion and RAG provenance instead of pretending each Source has an independent provider task.

### Learning
`InsightCards + RecordsTable + SelectionActions + ApprovalCard` makes Practice and Mastery Evidence separate decisions.

### Writing
`SelectionActions + DiffTable + RecordsTable` makes AI editing surgical and reversible.

### Living Book
`ContextCards + TaskRows + ApprovalCard` keeps local source fingerprints/staleness visible while external book generation remains a projection.

### Content
`ApprovalCard + SafeSvgPreview + CodeBlock + RecordsTable` preserves Publish Guard and avoids raw SVG insertion.

### Career
`InsightCards + RecordsTable + ApprovalCard` preserves reversible experiments rather than AI career matching.

### System
`FineTunePanel + RecordsTable + ToolChips + CodeBlock` surfaces Provider/runtime configuration without exposing secrets or provider internals as product identity.

## 8. Accessibility and maintenance

- status updates use accessible text in addition to color;
- interactive tabs expose tab roles/selected state;
- loading uses `role=status` / `aria-live`;
- buttons remain native keyboard-focusable;
- reduced-motion is respected;
- design primitives are centralized in `apps/web/components/BeautifulUI.js` and `apps/web/app/globals.css`;
- pages should compose primitives instead of adding one-off “AI-looking” effects.

## 9. Non-goals

v0.4.1 does not:

- copy Beautiful UI source code or turn the reference into a runtime dependency;
- expose private chain-of-thought;
- add decorative fake tool calls/progress;
- replace Psychology Growth domain language with generic agent terminology;
- make Recommendations or retrieval results authoritative;
- weaken Tauri/Provider permission boundaries for visual convenience.
