# Interest Growth 当前全仓库实现审计

审计日期：2026-09-04
审计基线：本轮提交（基于远端 `main` `11d3a6c64f252ff3868c8b611644722efcf313f6`）
产品版本：1.0.20

## 结论

本轮已完成 P0，并完成 P1/P2 中与当前产品声明直接相关的真实闭环：Native Core 仍是唯一执行核心；Research 使用同一份用户批准快照；Curiosity 只能通过显式状态机推进；学习辅助能力按独立 Feature/Plugin/Area gate 判定；Evidence、Source、Concept、Practice、Note、Artifact、Writing、Living Book、Tutor、Reflection 与 Career Experiment 均有可持久化的生命周期路径。

代码与 Web 验证为 `PASS`。当前没有把静态检查替代成发布证据：exact-SHA CI、构建产物签名/发布、Windows/macOS/Android 真机和公共 TLS 仍需在对应环境重新取得证据。

## P0/P1/P2 实现矩阵

| 能力 | Frontend → API → Gate → Backend/Native → DB/Storage → UI/Recovery/Lifecycle | 判定 |
| --- | --- | --- |
| 系统错误契约 | System 页面 → `/plugins/*`、`/features/*`、Area capability API → unknown plugin/feature 与冲突均为 typed 404/409 → PluginRuntime → Feature/Area 状态持久化 → UI 显示错误并可重试 | ✅ 完整实现 |
| Research 计划快照 | Research Plan/ApprovalCard → `/research/plan`、`/research/run` → Feature、Plugin、Area、Permission、Domain/KB gate 在创建 RUNNING 前完成 → Native Research 或显式 provider degraded fallback 均消费 approved snapshot → CapabilityRun/Source/Evidence/Claim → reload 可查看同一计划；失败为 FAILED | ✅ 完整实现 |
| Research gate 顺序 | 研究入口 → `resolve_native_context` → Area/Feature/Plugin/Area capability/Permission/Domain/KB → 最后创建 RUNNING → Native/provider → CapabilityRun 状态 | ✅ 完整实现 |
| Curiosity 状态机 | Home/Curiosity → `/questions/{id}/explore|pause|return|promote|close` → capability gate + `QuestionTransitionService` → QuestionModel 与 GrowthEvent → UI 按状态呈现 → 非法转移 409；generic PATCH 不可改 state/active/returned_count | ✅ 完整实现 |
| Mastery Evidence | Learning → `/concepts/{id}/mastery` 与 `/mastery-evidence/{id}/invalidate` → Practice/Area/Permission gate → MasteryRecord/MasteryEvidence → evidence note 在只更新 state 时保留 → 可显式失效且保留原因 | ✅ 完整实现 |
| Learning 独立门禁 | Learning → mastery assist / visualize / concept graph / knowledge 各自读取 capability state → Feature + Plugin installed/enabled + Area enabled → 对应 Native capability → UI 独立禁用与错误态；能力状态支持 loading/available/unavailable/error | ✅ 完整实现 |
| Interest Area | System/Area → `/areas`、`/areas/{id}`、capability API → current Area scope → Domain Pack/Profile 与 EntityAreaBinding → General 不读取 Psychology 专属状态；变更后前端可 refresh | ✅ 完整实现 |
| Energy mode | Home/Curiosity/Reflection → Question/Reflection API → enum 校验 → Question/Reflection 持久化 → UI 使用用户选择的 light/normal/deep，不再硬编码 normal | ✅ 完整实现 |
| Source/Evidence/Claim | Research/Knowledge → Source、Evidence、Claim、reverification API → Area/Permission/verification gates → Host DB + source vault → source 删除会标记依赖 Claim/Artifact/Book 需要复核/过期，不静默保留失效依据 | ✅ 完整实现 |
| Knowledge Base | Knowledge → KB create/update/link/unlink/delete/sync/rebuild → Feature/Plugin/Area/Permission → Native retrieval/index + Host mapping → 原始 Source 文件保留，KB 删除/解除映射不制造孤儿候选 | ✅ 完整实现 |
| Concept/Practice/Note | Learning → edit/archive/restore/delete endpoints → scoped selectors + dependency checks → Host DB → Concept 删除有依赖时阻断或显式 force；Practice attempt 与 Note mapping 清理 | ✅ 完整实现 |
| Tutor | Tutor → session/update/native turn/replay/resume/cancel/archive/restore/delete → Feature/Plugin/Area/Permission/Native operation → Host Session/Turn + Native checkpoint/events/aux memory → reload 恢复同一 turn；辅助 memory 可单独清空且不触碰 Growth Memory | ✅ 完整实现 |
| Co-Writer | Writing textarea selection → `/writing/documents/{id}/revisions` → Feature/Plugin/Native gate → WritingRevision + document update → selectionStart/End 校验 current document/base SHA → Diff Accept/Reject 与 stale-base 保护 | ✅ 完整实现 |
| Living Book | Book → local compile/project/confirm proposal/confirm spine + archive/restore/delete → Feature/Plugin/Area/Permission → Host Book/Chapter，Native 仅生成 proposal → 审阅 UI 展示真实 proposal/spine JSON、章节来源与 stale 状态 | ✅ 完整实现 |
| Artifact | Content/Learning → `/artifacts`、详情、approve/export/archive/restore/delete → Content/Graph/Permission/Human Review gate → Artifact storage + GroundingRef → `/artifacts/detail?id=` 可用于 static export，`/artifacts/[id]` 保留语义路由；批准不等于外部发布 | ✅ 完整实现 |
| Growth/Reflection | Growth → `/growth/*`、`/reflections`、archive/restore/delete → Growth capability/Feature → Growth Memory authoritative；Native auxiliary read-only/可清空 → UI 分开展示两类记忆，不伪装为同一事实 | ✅ 完整实现 |
| Career Experiment | Career → create/update/complete/archive/restore/delete → Career Feature/Plugin/Area → CareerExperiment + summary basis/confidence/sample/ties → UI 明示低置信度与不替用户决策 | ✅ 完整实现 |
| General/Psychology 边界 | Area selector → 所有 direct-ID API 验证 EntityAreaBinding → Domain Pack 提供 rules/profile/skills/personas → Host DB → General 页面不出现 Psychology mastery/提示词/专属证据规则 | ✅ 完整实现 |

## P3 与明确边界

| 项目 | 审计结论 |
| --- | --- |
| Native Core root/package mirror | `scripts/verify_native_core_sync.py` 通过；本轮修改后已同步镜像。保留双目录作为发布镜像，不再允许内容漂移。 |
| Browser remote | API 的正式支持列表为 `desktop-local`、`desktop-remote`、`android-remote`；`browser-remote` 在 capability response 和 v0.7 历史文档中明确为 experimental，不作为正式 release claim。 |
| RAG 层次 | Native lexical/lightgraph/concept-graph/heading 与 reviewed exact adapters 保留；retrieval candidate 仍不是 Evidence，外部索引仍是可重建投影。 |
| 历史文档 | README、Development Contract、v0.7 runtime contract 已标注 current/historical 边界；旧版本号文档不再被当作当前发布证据。 |
| 未来外部集成 | 本轮未新增未经闭环验证的第三方集成；优先保证 Host/Native/Area/Permission/Review contracts。 |

## 验证记录

| Gate | 结果 | 证据 |
| --- | --- | --- |
| Python compileall | PASS | `PYTHONPYCACHEPREFIX=/private/tmp/interest-growth-pycache python3 -m compileall -q apps packages adapters scripts tests` |
| Python full test | PASS | `./.venv/bin/pytest -q`，本轮最终全量通过 |
| Web lint | PASS | `npm run lint` |
| Web unit | PASS | `npm run test:web-unit`，103 passed |
| Web production build | PASS | `npm run build`，Next static export completed |
| Browser responsive/a11y/localization | PASS | Playwright 58/58 passed；4 个 Home 视口修复后专项 4/4 passed；覆盖 360/390/768/1440 |
| Native Core sync | PASS | `python3 scripts/verify_native_core_sync.py` |
| Source manifest | PASS | `python3 scripts/generate_source_manifest.py --check`，477 entries |
| self audit | PASS | `PYTHONPYCACHEPREFIX=/private/tmp/interest-growth-pycache python3 scripts/self_audit.py` |
| Rust desktop check | PASS | `cargo check --locked`；仅有既有 dead-code warnings |
| exact-SHA GitHub Actions | ❓ 需要真实环境验证 | 本地尚未取得本轮工作树对应 commit 的新 Actions run |
| Windows/macOS/Android 真机、签名与公开 TLS | ❓ 需要真实环境验证 | 本机没有对应硬件/发布证据；不能用本地 green tests 替代 |

## 变更后的交付边界

本轮源代码已达到当前产品契约的实现闭环，发布状态仍应写作：`CODE COMPLETE / RELEASE EVIDENCE PENDING`，直到变更提交后的 exact-SHA CI、Artifacts、签名和真实设备证据全部取得。任何 72h/7d soak 若按用户批准跳过，都应记录为 `SKIPPED (user-approved)`，不得写成 PASS。
