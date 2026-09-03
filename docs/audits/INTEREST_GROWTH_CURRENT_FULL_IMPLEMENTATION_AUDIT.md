# Interest Growth 当前全仓库实现审计

审计日期：2026-09-04
审计实现 SHA：`1b02417c2cf7b23ad2e7acfa6f88d12ea8b86fdf`
审计文档闭环 SHA：`ab609876bfff86a6f3c2176c48f495b991a1be20`
分支：`main`，与 `origin/main` 一致
产品版本：`1.0.20`

## 结论

本轮针对最新 `main` 完成了全仓库代码审计、当前可复现缺陷修复、锁文件/安全说明收口，并已推送。P0 的 HTTP 错误契约、批准计划快照、CapabilityRun 状态、独立能力门禁、掌握证据保留和 Curiosity 状态机在源码与测试中保持闭环；本轮另外修复了真实关系图占位、Curiosity 状态动作显示、UI 中文文案断言和可选 RAG 安全扫描阻断。

这不是一次新的产品发布：远端 `v1.0.20` 已于 2026-08-30 发布，注释 tag 最终指向 `d6290b44616cb66c288bf3468904e86bf43365d9`。本 SHA 是其后的 `main` 源码审计提交；若要把本轮修改作为新版本发布，仍需重新走版本化 Candidate/Promotion/Tag/Release 流程。

## P0 / P1 / P2 特性矩阵

| 能力 | 当前实现链路与判断 |
| --- | --- |
| 系统错误契约 | System → typed API error → UI 用户文案；未知插件、能力和冲突不伪装成功。✅ |
| Research 计划快照 | 先完成 Area/Feature/Plugin/Permission/Domain/KB gate，再创建 RUNNING；执行消费同一份 approved snapshot，失败显式 FAILED。✅ |
| CapabilityRun | 创建前完成 gate；异常路径 terminalize，不留下孤儿 RUNNING。✅ |
| Curiosity | `captured → exploring → returned/paused → active_topic/closed` 由服务端状态机控制；UI 按状态显示 Explore/Pause/Return/Promote/Close。✅ |
| 掌握证据 | 更新 mastery state 不覆盖 `evidence_note`；Practice promotion 与显式失效保留来源和原因。✅ |
| 学习能力门禁 | mastery、visualize、concept graph、knowledge/RAG 分别读取 Feature + Plugin + Area capability；loading/error/unavailable 时 fail-closed。✅ |
| 多兴趣与 Domain Pack | EntityAreaBinding + current Area 过滤；General 与 Psychology 的实体、规则、掌握标准隔离。✅ |
| Energy mode | Question/Reflection 持久化 `light/normal/deep`，前端不再硬编码 normal。✅ |
| Source / Evidence / Claim | 来源核验、失效传播、主张版本和再核验队列保留；候选检索结果不能直接成为 Evidence。✅ |
| Knowledge Base / RAG | Native provider 与 reviewed exact adapter 分开；无 adapter 时返回 requires_review，禁止静默 fallback；unlink/delete 保留原始 Source 文件并清理投影。✅ |
| Learning / Practice / Note | 概念、练习、作答、笔记与 mastery evidence 均有持久化路径和依赖检查。✅ |
| Graph / Visualize | GraphView 已为真实 SVG 关系查看器：类型筛选、搜索、缩放、平移、节点选择、邻居聚焦；Visualize 复用同一 viewer，不再是卡片/列表占位。✅ |
| Tutor | Session/Turn/replay/resume/cancel/archive/restore/delete 由 Host 持有；能力、权限和恢复失败均显式反馈。✅ |
| CoWriter | 选择区、base/current 校验、Diff、Accept/Reject 和 stale-base 保护存在；正文不会被 AI 自动覆盖。✅ |
| Living Book | 本地 compile、proposal/spine review、confirm、章节来源指纹及 archive/restore/delete 存在；提案不是事实。✅ |
| Artifact / Content | 生成包、依据、人工批准、导出、archive/restore/delete 分离；批准不代表外部发布。✅ |
| Growth / Memory | Growth Memory 是权威；Native auxiliary memory 可独立清除，不冒充用户成长事实。✅ |
| Career Experiment | 实验、结果、证据、反思、置信度和生命周期路径存在，不替用户作职业决定。✅ |

## 本轮源码修复

- 将 `VisualExplanation` 与 `GraphView` 接入真实可交互关系图，并加入键盘可达性、节点搜索、缩放、平移和邻居聚焦。
- Curiosity 页面按服务端状态只显示合法动作，避免状态与动作错配。
- 修复 activity trace 的真实用户文案断言：`工具已经完成`。
- 将可选 GraphRAG 的 NLTK 下限和 `uv.lock` 统一到 `3.10.3`；CI 的 `PYSEC-2026-3740` 例外仅限可选 RAG scanner metadata mismatch，并在 `SECURITY.md` 留下 review 条件，不放宽旧版本。
- 更新 `CHANGELOG.md` / `PROJECT_STATUS.md`，把已发布的 `v1.0.20` 与当前 post-release main audit 分离。
- 保持 Native Core 镜像目录：`verify_native_core_sync.py` 通过，镜像漂移由脚本和 CI 约束；没有证据证明可安全删除任一发布镜像。

## 验证记录

| Gate | 结果 | 证据 |
| --- | --- | --- |
| Python full test | PASS | `./.venv/bin/pytest -q -p no:cacheprovider`：全量通过 |
| UI adoption tests | PASS | `tests/test_beautiful_ui_adoption.py`：13 passed |
| Web unit | PASS | `npm run test:web-unit`：103 passed |
| Web lint | PASS | `npm run lint` |
| Web production build | PASS | `npm run build` |
| Native Core sync | PASS | `python3 scripts/verify_native_core_sync.py` |
| Source manifest | PASS | `python3 scripts/generate_source_manifest.py --check` |
| Self audit | PASS | `PYTHONPYCACHEPREFIX=/private/tmp/interest-growth-pycache python3 scripts/self_audit.py` |
| Rust source | PASS locally | `cargo check --locked`；仅既有 dead-code warnings |
| Current-SHA GitHub Actions | PASS | CI `33807240181`、Web E2E `33807240178`、Build Artifacts `33807240174` 均绑定审计文档闭环 SHA；CI/Web E2E/三平台制品全部 `success` |

## 发布、设备与环境边界

- 已发布稳定版本：`v1.0.20`；GitHub release assets 包含 Android arm64 APK、macOS arm64 app、Windows x64 installer、server bundle、SBOM、checksum 和 release verification 文档。
- 本轮不是新 Stable 发布，也没有把当前 SHA 的 CI/Artifacts 运行中状态写成 release PASS。
- Android emulator、Android physical device、Windows/macOS packaged runtime、代码签名、公开 TLS、自托管跨设备和 72h/7d soak 未在本机重新取得本轮完整证据；它们应写作 `NOT RUN` 或 `SKIPPED (user-approved)`，不能由本地测试推断通过。
- Browser remote 仍是 experimental；正式 runtime claim 仅覆盖已声明的 desktop-local、desktop-remote、android-remote 路径。

## 当前剩余限制与后续建议

1. 当前审计 SHA 的 CI、Web E2E 和三平台制品矩阵已完成；后续代码变更必须重新绑定新的 exact SHA 验证。
2. 若要发布本轮代码，先生成新版本，再执行 exact-SHA Candidate → Promotion → immutable tag → exact-tag Release matrix。
3. 继续补齐缺少真实硬件/公网环境的设备、签名、TLS、跨设备和长期 soak 证据；不得用 waiver 冒充 PASS。
4. 后续 UI 迭代应优先把已存在的后端 archive/restore/delete 能力逐页补到 Learning/Research/Knowledge 等列表操作，并为这些生命周期动作增加浏览器级覆盖。

## 最终判定

当前判定：`SOURCE / LOCAL TESTS PASS; CURRENT-SHA CI + WEB E2E + ARTIFACTS PASS; RELEASE/DEVICE EVIDENCE NOT CLAIMED`。本轮提交仍不是新的 Stable release；物理设备、公开 TLS 与长期 soak 仍保持明确边界。
