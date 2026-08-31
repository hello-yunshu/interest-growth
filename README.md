# Interest Growth · 多兴趣培养、学习、研究与表达系统

Interest Growth 是一个 **local-first、multi-interest** 的 Windows/macOS 桌面产品。它把真实好奇心、学习、练习、研究、资料库、成长反馈、写作和长期作品放在同一个可暂停、可返回的循环里。

**心理学仍然是默认培养领域，但不再是产品 Core。** 新用户默认获得 Psychology Interest Area；也可以新增水彩、编程、摄影、历史、音乐等 General Interest Area。不同 Area 可以选择不同能力组合、Persona、Skill、Mastery Profile 和表达规则。

所有产品能力都由 Interest Growth 的 **Native Core** 实现。DeepSeek 只作为可选模型传输层，为已获授权的原生能力提供模型推理；它不持有产品身份、流程或数据。数据库、Source/Artifact、Evidence/Claim、Practice、Note、Growth Memory、Writing、Living Book 与人工审核状态均由本地 Host 持有。

## 当前 1X 产品契约（全量审计基线）

- 当前实现只支持 `CURRENT_SCHEMA_VERSION` 的全新 Host 数据库；旧数据库不会自动迁移，也不承诺兼容。schema 不兼容时必须 fail-closed。备份与恢复只接受同一当前 schema，恢复前保留可回退的现有数据。
- General 与 Psychology 都由后端返回各自的 Mastery Profile；前端不得硬编码另一领域的状态、标签或证据规则。
- 每次可执行能力都同时经过 Feature、Plugin 安装/启用、Area capability、PermissionBroker、Domain scope 与 provider 边界。只有 provider 不可用或 provider 执行失败可以进入显式降级；gate 失败不会伪装成 provider 降级。
- Tutor 恢复同一个已持久化 turn；Research 必须执行用户确认的同一份计划快照；Visualize、Concept Graph 与 Memory Graph 使用结构化可读视图；写作、Living Book、内容与来源仍保留人工审核边界。

本节描述当前产品契约。下方带有旧版本号的章节是历史实现记录，不能单独作为当前发布或兼容性证明；当前 commit、Actions 与发布边界以 `docs/audits/INTEREST_GROWTH_1X_FULL_IMPLEMENTATION_AUDIT.md` 及对应 exact-SHA 证据为准。

## v0.6 原生执行产品

v0.6 把原生执行核心接入真实 Host，而不是把两个源码包并排放置：

- 默认 Knowledge/RAG 为 `native-lexical`，另有 LightGraph、Concept Graph、Heading 三种本地引擎；
- Source 原件仍由 Host 持有，原生解析支持文本、PDF 与常见 OOXML 文档；
- Tutor 页面通过 Host REST API 使用原生 checkpoint、事件序列、等待/继续、取消与重放；
- Host `TutorSession` / `TutorTurn`、`KnowledgeIngestionRun`、`RetrievalCandidate` 仍是产品事实；
- DomainPolicy 来自当前 Area 的 Domain Pack，Capability 和 PermissionScope 来自 Host 插件生命周期与权限声明；
- `llamaindex`、`lightrag`、`graphrag`、`pageindex` 只调用显式注册的 reviewed exact adapter；未配置时返回 `requires_review`，绝不静默换成原生算法；
- 未配置 LLM 时，本地检索、可视化规划、Notebook proposal 等本地能力可用；AI Tutor/Research 会明确显示降级状态。

## 四层模型

- **Interest Area**：用户正在培养什么。
- **Capability Plugin**：系统能做什么。
- **Domain Pack**：这个兴趣应该怎样使用这些能力。
- **Model Transport**：可选地为原生能力提供模型推理，不承载产品流程。

> Plugin = what · Domain Pack = how · Native Core = execution · Interest Area = what you cultivate

## 默认 Domain Packs

### Psychology（默认）

保留原项目最严格的心理学路径：

- Psychology Personas / Skills；
- 诊断与治疗边界；
- 高质量综述、元分析、原始研究等 Research 偏好；
- Conceptual + Evidence Mastery Profile；
- 心理学事实型公开表达必须经过本地 Claim/Evidence + 人工核验；
- Source 失效 / Claim 修订继续触发重新审核。

### General Interest

适合绘画、摄影、编程、音乐、历史、手工、项目学习等不需要心理学专属策略的兴趣：

- neutral Quick Explore / Tutor / Research；
- practical demonstration / worked example / project practice 都可成为学习输入；
- Adaptive Mastery：understand → practice → apply → reflect → transfer → self_directed；
- Learning Activity 可记录作品、练习、项目、观察；
- Content 可以用 Note / Activity / Practice / Source / Artifact / Book Chapter 做 Grounding；
- 个人练习记录会明确标为个人/实践记录，不会自动升级成普遍事实或 Evidence。

## 主要能力

- **Curiosity**：问题收集、Light/Normal/Deep、pause/return、Topic promotion。
- **Research & Evidence**：可选研究计划、Source/Evidence/Claim/ClaimVersion、Skeptic Review、re-verification。
- **Knowledge & RAG**：本地 Source 为事实源，外部索引可重建；retrieval 只产生 `candidate_not_evidence`。
- **Mastery / Practice / Activity**：Domain-profiled Mastery、Quiz Practice、Mastery Evidence、Creative/Project LearningActivity。
- **Notebook / Persona / Tutor**：Area-scoped Note、Persona、Skills 和持续 Tutor Session。
- **Co-Writer**：selection edit、Diff、Accept/Reject、stale-base protection。
- **Living Book**：从当前 Area 的 Concept/Claim/Note/Practice/Activity 编译本地长期书；原生 proposal 仍需人工确认。
- **Content Studio**：Domain Pack 决定 Grounding/风险规则；Human Review 后才能 Export，Export ≠ 自动发布。
- **Growth / Reflection / Career**：Area-scoped Growth Memory、Reflection 与可逆实践/职业实验。

## 精确第三方 RAG

四个第三方 ID 已有独立的可选精确适配器：LlamaIndex 调用
`VectorStoreIndex`，LightRAG 调用结构化 `aquery_data`，Microsoft GraphRAG
调用 `build_index` 与 `local_search`，PageIndex 调用官方文档上传与检索
SDK。它们接收整个 KB 的 Host Source 快照，并把结果严格映射回本地 Source
ID、原始文件名、fingerprint 与 locator；无法映射的结果会被拒绝。

这些重型/联网依赖默认不安装、不启用。第三方索引只是可重建投影，Host
`KnowledgeIngestionRun` 仍是全 KB ingestion 的权威记录，检索结果仍为
`candidate_not_evidence`。版本、许可、体积、安全、维护与离线影响见
[`docs/architecture/EXACT_RAG_ADAPTERS.md`](docs/architecture/EXACT_RAG_ADAPTERS.md)。

## 多兴趣隔离

HTTP 使用 `X-PG-Interest-Area`，Tutor WebSocket 使用 Area query context。列表、直接 ID 操作、Evidence/Claim 引用、Practice↔Tutor、Persona/Skill、Source invalidation、Tutor Turn 等都经过当前 Area 边界。

v0.5 采用 `EntityAreaBinding` 给 v0.4.1 旧模型做 additive scope，而不是一次性给 30 多张旧表做 destructive ALTER。新建旧模型对象由 SQLAlchemy hook 自动绑定当前 Area。v0.6 沿用这些边界，并把 Area ID 直接编译进每次原生执行上下文。

## Area capability composition

每个 Domain Pack 提供默认 Capability 组合。System → **Area capabilities** 可以针对当前兴趣单独开启/关闭 `capability.*`，例如某个绘画 Area 不需要 Research & Evidence，可以关闭；Psychology Area 仍可保持完整证据路径。

Area capability 开关只控制当前 Area 的产品能力，不改变 `core.interest-growth` 生命周期，也不把模型传输配置误当成产品插件生命周期。

## Plugin 权限

Capability routes 通过 `PermissionBroker` 检查 manifest 声明的 read/write 和 network/LLM 等高风险能力。测试会动态移除 manifest 权限并要求 API 返回 403。

这仍然是 **trusted first-party enforcement**，不是 hostile third-party Python sandbox。v0.5 不支持运行任意下载的插件代码。

## Desktop Runtime

桌面架构延续 v0.4：

```text
Tauri 2
├── static Next.js / React UI
├── native window / dialog / updater / credential store
└── Psychology-era compatible Python sidecar filename
    └── Interest Growth FastAPI Core
```

正式支持：

- **Windows 11 24H2+ x64**；
- **macOS 13+ Apple Silicon**。

桌面 Core：

- 随机 `127.0.0.1` 端口；
- 每次启动/重启随机 desktop token；
- HTTP `X-PG-Desktop-Token` + Tutor WS token；
- OS App Data 保存 DB/Source/Artifact；
- macOS Keychain / Windows Credential Manager 保存可选模型密钥；
- renderer 不允许直接访问模型服务；
- 单实例；
- native Save dialog；
- signed updater architecture。

## Planned v0.7 self-hosted cross-device mode

The approved next direction is an additive self-hosted mode rather than a replacement for the existing local desktop runtime:

- FastAPI Native Core runs in Docker on a Unix host and owns the remote-mode SQLite, Sources and Artifacts;
- Windows/macOS can choose the current local-sidecar mode or connect to the self-hosted server;
- Android connects to the self-hosted server and does not bundle Python or a local canonical database;
- authenticated client-facing HTTPS/WSS device sessions make the same server state available across devices; local Docker and the trusted external-proxy upstream may use loopback HTTP;
- the initial design is online-first and does not claim offline bidirectional sync;
- Android is distributed directly as APK, not through Google Play or AAB.

“No Google Play/official store signing” does not mean an unsigned APK. Android requires APK signing; development uses debug signing, while a controlled release uses a project-owned private signing key kept outside Git. Future upgrades must retain the same application ID and signing identity.

Normative planning documents:

- `docs/development/DEVELOPMENT_CONTRACT.md`
- `docs/architecture/V0_7_SELF_HOSTED_CROSS_DEVICE_BLUEPRINT.md`
- `docs/roadmap/V0_7_SELF_HOSTED_CROSS_DEVICE_PLAN.md`
- `docs/design/V0_7_CROSS_DEVICE_CLIENT_DESIGN.md`
- `docs/audits/V0_7_IMPLEMENTATION_AUDIT.md`
- `docs/operations/V0_7_BACKUP_RESTORE.md`
- `docs/security/11_SECURITY_AND_PRIVACY.md`

## 原生执行边界

- Tutor、Research、Learning、Practice、Co-Writer、Living Book、Memory、Visualize 与 Knowledge 全部走内置 Native Core；
- 模型未配置或不可用时，确定性本地能力继续工作，需要模型的能力明确降级；
- Native Core 只持有 checkpoint、事件和辅助执行状态，Host 数据库始终是唯一产品事实源；
- 模型输出不能自动成为 Evidence、Mastery、已接受写作或 Growth Memory。

## 历史 schema ledger（非当前兼容承诺）

Schema ledger：

- 1–7：v0.4.1 legacy baseline；
- 8：创建 General Interest schema；
- 9：seed `general` + `psychology` Domain Packs、默认 Psychology Area，并 backfill legacy entity scope；
- 10：把已保存的 `psychology.*` plugin state 复制到 neutral capability IDs，旧行保留作兼容历史。
- 11：创建原生 Tutor checkpoint、公开事件序列与辅助执行 memory 表；这些是 execution-only state，不取代 Host 产品模型；
- 12：移除已退休的外部运行时配置，并将旧 Knowledge Base 标记为需要原生重建。

这些条目记录旧版本的开发历史，不构成当前旧数据库迁移承诺。当前初始化只接受新建的 current schema；已有不兼容数据库会直接拒绝启动，必须由用户先完成受支持的同 schema 备份/恢复流程。

## Legacy technical identifiers

为了避免升级后用户感觉数据库、Keychain、App Data 或已安装应用“消失”，v0.5 **有意保留**以下技术标识：

- Tauri/keyring identifier：`app.psychologygrowth.desktop`
- DB filename：`psychology_growth.db`
- sidecar binary basename：`psychology-growth-core`

它们是 **upgrade compatibility anchors**，不是当前产品品牌。未来如果要改，必须做一轮专门的 App Data / credential / updater migration，而不是字符串替换。

## Known v0.5 compatibility limitation

历史 `knowledge_bases.name` 与 Tutor Persona name 仍是全局唯一。它不会造成 Area 数据泄漏，但两个 Area 暂时不能创建完全同名的 Knowledge Base / user Persona。安全移除这些 legacy unique constraints 需要专门的 non-additive migration，因此没有混入本次 additive v0.5 升级。

## 开发运行

```bash
python -m compileall -q apps packages scripts tests
python -m pytest -q
python scripts/self_audit.py
```

本地 Web/API 仍默认 loopback。桌面 native 构建需要目标 OS 上的 Rust、PyInstaller、npm 依赖和 Tauri toolchain。

## 文档入口

- `docs/architecture/V0_5_GENERAL_INTEREST_ARCHITECTURE.md`
- `docs/roadmap/V0_5_GENERAL_INTEREST_PLAN.md`
- `docs/decisions/0004-interest-areas-domain-packs.md`
- `docs/audits/V0_4_1_GENERAL_INTEREST_AUDIT.md`
- `docs/audits/V0_5_GENERAL_INTEREST_AUDIT.md`
- `RELEASE_NOTES_v0.5.0-general-interest-core.md`
- `docs/development/DEVELOPMENT_CONTRACT.md`
- `docs/architecture/V0_7_SELF_HOSTED_CROSS_DEVICE_BLUEPRINT.md`
- `docs/roadmap/V0_7_SELF_HOSTED_CROSS_DEVICE_PLAN.md`
- `docs/design/V0_7_CROSS_DEVICE_CLIENT_DESIGN.md`

原始《心理学成长与表达系统》蓝图/阶段计划继续 byte-for-byte 保留，作为项目历史基线，而不是当前产品身份。
