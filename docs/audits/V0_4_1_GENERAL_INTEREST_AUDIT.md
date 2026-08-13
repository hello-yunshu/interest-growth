# v0.4.1 全代码审计：从 Psychology Growth 迁移到 General Interest Core + Psychology Default Pack

审计对象：`psychology-growth-v0.4.1-beautiful-ai-interface.zip`
审计日期：2026-08-12

## 1. 结论

v0.4.1 已经是独立于 DeepTutor 的产品，但**仍然不是一个真正通用的兴趣培养系统**。它目前更准确的定义是：

> 通用能力基础设施 + 心理学写死的产品语义层。

因此下一阶段不应继续在现有结构上增加“领域下拉框”，而应明确拆成四条正交轴：

1. **General Interest Core**：问题、主题、兴趣强度、暂停/返回、学习事件、笔记、资料、表达、成长记录等通用能力；
2. **Capability Plugins**：Research、RAG、Practice、Mastery、Writing、Book、Content 等“做什么”的能力；
3. **Domain Packs**：心理学、绘画、编程等“这个兴趣如何默认使用这些能力”的配置/策略包；
4. **Capability Providers**：DeepSeek、DeepTutor 等“由谁执行 AI 能力”的可替换 Provider。

心理学应成为默认 `domains/psychology`，而不是 Core 命名空间。

---

## 2. 基线验证

对最终 v0.4.1 ZIP 全新解压后重新执行：

- pytest：**89/89 PASS**
- compileall：PASS
- `scripts/self_audit.py`：PASS
- JSON/YAML/TOML/plist：全部可解析
- 当前 33 张业务/基础设施表正常加载

因此本审计不是建立在已损坏的代码上。

但这些测试证明的是“Psychology Growth v0.4.1 当前行为没有回归”，**并没有证明多兴趣/多领域能力**。

当前：

- 0 个 `InterestArea` / `DomainPack` / `DomainProfile` 数据实体；
- 0 个领域切换 UI；
- 0 个多领域隔离测试；
- 19 个插件中 **18 个使用 `psychology.*` 稳定 ID**；
- 8 个 bundled Skills 中 **8 个包含心理学专用语义**；
- 4 个 builtin Personas 中 **4 个都是心理学 Persona**；
- 排除历史 Release Notes / audits / baseline 后，仍有约 **456 处 psychology/心理学相关引用**进入当前代码与现行文档。

---

# 3. P0 架构问题

## P0-1 没有一等 Interest Area / Domain Pack

核心数据库有 Question、Topic、Source、Evidence、Claim、Concept、Mastery、Practice、Note、TutorSession、Writing、Book、GrowthMemory 等，但没有任何表能回答：

> “这个对象属于心理学、绘画、编程、摄影还是一个自定义兴趣？”

`TopicModel` 只有：

- question_id
- title
- description
- status
- interest_boundary
- competence_boundary

没有 area/domain scope。

这意味着新增第二个兴趣后：

- Dashboard 无法按兴趣隔离；
- Growth Memory 会把不同兴趣混合聚合；
- Reflection 没有兴趣作用域；
- Knowledge Base 没有领域作用域；
- 无 Topic 的 Writing/Tutor/Artifact 也无法可靠确定领域；
- Persona/Skill 无法依据当前兴趣选择。

### 推荐

增加：

- `InterestArea`
- `DomainPack`
- `InterestAreaProfile`（或 Area → DomainPack binding）
- scope/binding 模型

干净安装默认创建：

`psychology` Interest Area → `psychology` Domain Pack。

用户随后可以增加其他 Area。

---

## P0-2 插件命名空间与依赖图本身是 Psychology-first

19 个插件里 18 个是：

`psychology.*`

例如：

- psychology.curiosity
- psychology.research-evidence
- psychology.knowledge-rag
- psychology.flexible-mastery
- psychology.practice
- psychology.learning-notebook
- psychology.tutor-runtime
- psychology.content-studio
- psychology.growth-feedback

更深的问题不是前缀，而是依赖结构：

- Knowledge & RAG → Research & Evidence
- Co-Writer → Research & Evidence
- Content Studio → Research & Evidence
- Growth Feedback → Flexible Mastery
- Living Book → Flexible Mastery + Notebook + Practice

这等于把心理学当前最适合的“证据驱动 + 概念掌握 + 问答练习”路径变成全产品的结构依赖。

对绘画、音乐、摄影、烹饪、编程项目学习等兴趣，这种依赖并不成立。

### 推荐

Capability Plugin 改成中性 ID，例如：

- `core.interest-growth`
- `capability.curiosity`
- `capability.research-evidence`
- `capability.knowledge`
- `capability.mastery`
- `capability.practice`
- `capability.writer`
- `capability.content`

而“心理学默认开启哪些能力、如何组合”由 Psychology Domain Pack 决定。

**不能直接暴力改 ID。** 当前 `plugin_states` 已持久化 `psychology.*`。需要 `legacy_ids`/alias migration，保证旧用户插件状态不丢失。

---

## P0-3 Psychology Prompt 已进入 Provider Adapter / Core service，而不是 Domain Pack

硬编码位置包括：

- `adapters/deepseek/pg_deepseek/research.py`
- `adapters/deeptutor/pg_deeptutor/research.py`
- `apps/api/pg_api/engines.py`
- `apps/api/pg_api/cowriter.py`
- `apps/api/pg_api/living_book.py`
- `apps/api/pg_api/content.py`

这是严重的层次反转：Adapter 应该只负责 Provider protocol，不能决定用户学的是心理学。

### 实际行为反证

在 DeepSeek/DeepTutor 均关闭时执行：

`我想学习水彩画，如何开始建立色彩感觉？`

当前 Quick Explore 输出仍然要求：

> “这个问题里最核心的心理学概念分别是什么？”

Manual Research 仍默认：

- systematic review
- meta-analysis
- primary research

这证明当前系统不能通过单纯“增加一个绘画 Topic”实现通用化。

### 推荐

ResearchEngine / Quick Explore / Writer / Book 接收中性的 `DomainContext`：

- domain_name
- research_policy
- safety_policy
- source_preferences
- terminology
- skill_names
- persona defaults

心理学规则由 `domains/psychology` 注入。

---

## P0-4 bundled Skills 全部是 Psychology Pack 内容，但目前处于全局技能目录

8/8 Skills 都包含心理学语义：

- psychology-research
- psychology-evidence-review
- psychology-claim-check
- psychology-skeptic
- psychology-writing
- image-prompt（内容实际是 psychology editorial）
- video-prompt（内容实际是 psychology video）
- xhs-writing（内容实际是 psychology XHS）

即使后三个名称看起来通用，内容也不是通用技能。

### 推荐目录

```text
skills/common/
  generic-research/
  generic-writing/
  image-prompt/
  video-prompt/

domains/psychology/
  skills/
    psychology-research/
    psychology-evidence-review/
    psychology-claim-check/
    psychology-skeptic/
    psychology-writing/
    psychology-xhs-writing/
```

DeepTutor Skill Bridge 应同步“当前 Area 对应 Domain Pack + common”而不是扫描一个全球 psychology skills 目录。

---

## P0-5 Personas 被作为全局系统默认值 Seed，但 4/4 都是 Psychology Persona

`apps/api/pg_api/learning_assets.py` 当前启动时全局 seed：

- psychology-peer
- psychology-socratic-tutor
- psychology-research-assistant
- psychology-evidence-reviewer

这导致任何新领域默认也看到/使用心理学 Persona。

### 推荐

Persona 增加 scope：

- global/common
- domain-pack
- interest-area
- user-custom

Psychology Persona 移到 `domains/psychology/personas/`。

Core 只 seed 非领域化的基础 Persona，或不 seed Persona。

---

## P0-6 Growth Memory / Reflection 是全局聚合，新增兴趣会互相污染

`refresh_growth_memory_records()` 当前遍历全库：

- 所有 mastery
- 所有 returned questions
- 所有 claim revisions
- 所有 reflections
- 所有 research events

然后生成：

- `g1:trace-summary`
- `g3:long-term-growth-model`

因此未来绘画与心理学会进入同一长期成长模型。

### 推荐

Growth Memory 至少支持：

- `scope_type = global | area | topic`
- `scope_id`

同时保留一个真正的 cross-interest global synthesis，但不能把它和某一兴趣自己的成长模型混为一谈。

Reflection 也应支持 Area scope。

---

## P0-7 v0.4.1 的 schema migration 机制不足以支撑这次重构

`init_db()` 当前仍然是：

`Base.metadata.create_all()` + 把 1–7 写入 `schema_migrations`。

并不存在对应的 ALTER/data migration runner。

过去版本主要新增表，因此尚可工作；但通用化需要：

- 新领域实体；
- 为旧数据建立 psychology 默认绑定；
- plugin ID alias/state migration；
- 可能增加 scope；
- Persona/Skill ownership migration。

这些已经不是“create_all 即可”的升级。

### 推荐

v0.5 在做业务改造前先建立真正的 migration runner（或 Alembic）。

必须有真实升级测试：

`v0.4.1 DB → v0.5 DB`

并验证所有旧 Question/Topic/Source/Claim/Note/Book 等自动归入 Psychology Area。

---

# 4. P1 产品模型问题

## P1-1 Mastery 模型过度偏向“概念知识”

当前 MasteryState 固定：

- unfamiliar
- familiar
- explain
- example
- distinguish
- transfer
- evidence_boundary
- stable_expression

对心理学概念非常合理。

但对：

- 水彩技法
- 吉他演奏
- 摄影构图
- 编程项目
- 烹饪

并不完整。

### 推荐

引入 `MasteryProfile`：

- conceptual-evidence（Psychology 默认，可复用现有状态）
- procedural
- creative/practice
- project-based
- custom

数据库的 `state` 已经是 String，可保留；真正硬编码的是 Domain enum、API validation、UI selector。

---

## P1-2 Practice 是 Quiz-first，不足以表示一般兴趣练习

当前 PracticeItem 强依赖：

- prompt
- question_type
- options
- reference_answer
- explanation
- is_correct

适合 Quiz / Question Bank，但不能自然表达：

- 今天画了一张湿画法练习
- 做了一个 React 小项目
- 录了一段吉他练习
- 做了一次摄影外拍

### 推荐

保留现有 PracticeItem 作为 `question_practice` 类型，同时新增通用：

`PracticeSession / LearningActivity`

支持：

- objective
- activity_type
- artifact_refs
- self_assessment
- feedback
- observation
- evidence refs
- duration optional（不能变 KPI）

---

## P1-3 Content Studio 与 Co-Writer 被强制绑定 Claim/Evidence

Psychology factual content 应该如此严格。

但通用内容可能来自：

- Note
- Project
- Practice artifact
- Book chapter
- Reflection

而不是一定来自 verified Claim。

### 推荐

引入通用 `GroundingRef`：

- claim
- source
- note
- practice/project
- book chapter
- artifact

Psychology Domain Policy 可以要求“涉及心理学事实时必须使用 verified Claim/Evidence”，而 Core Content Studio 不应全局强制这一要求。

---

## P1-4 Source / Research 默认仍偏学术与生物医学

`SourceModel` 固定提供：

- doi
- pmid
- isbn

不是错误，但 general core 更适合：

`identifiers: {type -> value}`

以支持：

- arXiv
- standard
- patent
- museum catalog
- repository commit
- course URL
- custom identifier

DOI/PMID/ISBN 可以保留兼容字段。

---

## P1-5 公共 API 泄漏 Psychology 语义

`ResearchRequest` 当前公开：

`use_psychology_skills: bool = True`

`ContentPackRequest` 默认：

`target_audience = 对心理学感兴趣的普通读者`

这是直接的 API contract coupling。

### 推荐

新 contract：

- `area_id`
- `use_domain_skills`
- optional explicit `skill_names`
- audience/template 由 Area/Domain defaults 决定

旧 `use_psychology_skills` 在一个兼容窗口内可作为 deprecated alias。

---

## P1-6 PermissionBroker 目前是“部分执行”，不是全插件权限执行

当前 11 个使用 `require_plugin()` 的 route 模块中：

有 PermissionBroker enforcement：

- cowriter
- learning_assets
- living_book
- tutor

没有 resource/risk broker enforcement：

- career
- content
- growth
- knowledge
- learning
- questions
- research

所以插件 manifest 中 permissions/risk 对旧能力仍有不少属于声明性 metadata。

当前系统明确只运行受信任 first-party plugin，因此这不是远程代码执行漏洞；但如果下一阶段把 Domain Pack / capabilities 做成更强的可组合系统，这个缺口应补齐。

---

## P1-7 当前缺少任何前端行为测试，已经实际漏掉一个 UI 状态 Bug

后端 89 tests 全绿，但 `apps/web` 没有 Playwright/Vitest/Jest 测试。

实际发现：

Domain enum 使用：

`active_topic`

但 Curiosity UI 使用：

`promoted`

作为 filter/count/success state。

所以已经 Promotion 的 Question 会进入后端 `active_topic`，但前端 “Topics” filter 的数量/筛选不匹配。

这是一个真实 v0.4.1 UI bug，也是“后端测试绿并不代表桌面 UI 正确”的直接证据。

建议 v0.5 至少加入：

- Vitest/React Testing Library：状态映射和组件行为；
- Playwright/Tauri Web-level E2E：Area 切换、Question→Topic、Research、Learning、Writing、Export 关键链。

---

## P1-8 多领域数据隔离规则当前不存在

例如 Claim 只验证 Evidence ID 存在，并不验证它属于当前 Topic/Area。

当前单领域产品可以允许跨 Topic 复用证据；但加入 Area 后必须显式定义：

- 同 Area 可复用；
- 跨 Area 是否允许；
- 如果允许，是否必须显式 `shared/global`；
- Knowledge Base 是否 Area-private 或 shared。

不能依赖“用户不会混用”。

---

# 5. P2 / 迁移与工程问题

## P2-1 Product / OS identity 全部 Psychology-coded，但不能直接全量 rename

包括：

- package: `psychology-growth`
- web: `psychology-growth-web`
- desktop crate: `psychology-growth-desktop`
- Tauri `productName = Psychology Growth`
- bundle identifier: `app.psychologygrowth.desktop`
- Keyring service: `app.psychologygrowth.desktop`
- sidecar: `psychology-growth-core`
- DB filename: `psychology_growth.db`
- export filename: `psychology-growth-*.zip`

产品希望脱离 Psychology 后，这些名称最终需要重新审视。

但**不能和 Domain 重构一起暴力重命名**。

bundle identifier / credential service / App Data / updater identity 是稳定 OS-facing identity。直接修改可能造成旧数据或凭据看似“消失”。

建议 v0.5 先完成领域层分离，保留 legacy technical IDs；品牌/OS identifier migration 单独作为后续受控迁移。

`pg_*` Python namespace 也不值得为了视觉上的“去心理学”立即重写。可以保留为兼容技术命名，等公共品牌确定后再决定。

---

## P2-2 当前无 npm/Cargo lockfiles，构建不是 dependency-reproducible

没有：

- apps/web/package-lock.json
- apps/desktop/package-lock.json
- Cargo.lock

CI 使用 `npm install` 而不是 `npm ci`。

这已在 v0.4.1 中如实记录为原生发布门，仍未解决。

在真正发布 Win/mac 二进制前应完成。

---

## P2-3 `Nav.js` 已经成为明显 dead component

当前 layout 使用 `DesktopShell`，没有任何地方 import `components/Nav.js`。

它仍带 Psychology Growth brand 和旧导航，属于维护噪音，应删除或测试证明用途。

---

# 6. 哪些部分可以保留，不应推倒重来

以下层已经具有明显通用价值：

- Tauri Desktop runtime / single instance / random port + launch token；
- Keychain / Windows Credential Manager；
- static React/Next desktop renderer；
- Beautiful UI AI-native primitives；
- Provider isolation：DeepSeek / DeepTutor adapters；
- Engine Contracts；
- Event Bus 基础设施；
- Source Vault / Artifact Vault；
- Question pause / return / energy mode；
- Source → Evidence → Claim ledger（作为可选能力）；
- Knowledge/RAG projection model；
- Learning Note；
- Writing revision accept/reject；
- Living Book fingerprints；
- Human Review / Publish Guard 架构；
- local-first / own-data-first / no auto-publish 原则。

因此**不需要重写桌面壳、Provider 或 Beautiful UI**。

---

# 7. 推荐 v0.5 目标架构

```text
General Interest Desktop Product
│
├── Interest Areas
│   ├── Psychology   ← 默认
│   ├── Drawing
│   ├── Programming
│   └── Custom...
│
├── General Interest Core
│   ├── Curiosity
│   ├── Topic / Learning Unit
│   ├── Growth / Reflection
│   ├── Resource Library
│   └── Artifact / Event / Review
│
├── Capability Plugins
│   ├── Research & Evidence
│   ├── Knowledge / RAG
│   ├── Mastery
│   ├── Practice
│   ├── Tutor
│   ├── Writer
│   ├── Living Book
│   ├── Content
│   └── Career Experiments
│
├── Domain Packs (non-provider semantics)
│   ├── general/
│   └── psychology/  ← default
│       ├── domain.yaml
│       ├── personas/
│       ├── skills/
│       ├── policies/research.yaml
│       ├── policies/content.yaml
│       └── mastery-profiles/
│
└── Capability Providers
    ├── DeepSeek
    ├── DeepTutor
    └── Future Providers
```

关键原则：

> Plugin = 做什么；Domain Pack = 在这个兴趣里如何做；Provider = 谁来执行。

三者不得再次合并。

---

# 8. 推荐实施顺序

1. **先建立真实 migration framework**；
2. 新增 InterestArea / DomainPack / scope；
3. v0.4.1 全量旧数据自动绑定到 Psychology 默认 Area；
4. 新增 `domains/general` 与 `domains/psychology`；
5. 把所有 Psychology Personas / Skills / Prompt / Policy 搬出 Core/Adapter；
6. Research API 从 `use_psychology_skills` → `use_domain_skills`；
7. 将插件稳定 ID generalize，并通过 alias migration 保留旧 plugin_states；
8. 松开 Knowledge/Writer/Content/Growth/LivingBook 的 Psychology-specific hard dependency；
9. 引入 Area switcher，并让所有 workspace 明确当前 Area；
10. Growth/Reflection/Memory 加 Area scope；
11. 增加 MasteryProfile + 通用 PracticeSession；
12. 增加 multi-domain isolation tests；
13. 修复 Curiosity `promoted` vs `active_topic` UI bug；
14. 补前端行为测试；
15. 最后才考虑公共品牌、bundle id、Keyring service、DB 文件名等 OS identity rename。

---

# 9. v0.5 必须通过的核心验收

至少需要证明：

1. 干净安装默认出现 Psychology Area；
2. 可以新增 Drawing/Programming/custom Area；
3. 在 Drawing Area 问水彩问题，不出现 Psychology prompt/persona/skill；
4. Psychology Area 仍保留当前 diagnosis/treatment/evidence safety；
5. Psychology Skills 不会进入其他 Area；
6. Area 间 Dashboard/Growth/Reflection/KB/Tutor context 正确隔离；
7. shared resource 必须显式标记，不能隐式跨 Area；
8. v0.4.1 DB 所有旧数据无损迁移到 Psychology Area；
9. 旧 `psychology.*` plugin state 能迁移/alias 到新 generic ID；
10. 禁用 DeepTutor 后所有本地 Area 仍可用；
11. 非 Evidence-heavy Domain 可以使用 Notes/Practice/Writer/Book，而不被强制创建 Claim；
12. Psychology factual publishing 仍必须经过原来的 Evidence/Claim/Human Review 边界；
13. Quick Explore / Research / Tutor / Content 都由当前 Area 的 DomainContext 驱动；
14. frontend tests 能抓住 `active_topic` 这类 API/UI 状态漂移；
15. Core 当前代码（排除 `domains/psychology`、历史 migration/docs/compat）不再出现 psychology-specific prompt/policy。

---

## 最终判断

当前 v0.4.1 **适合作为通用化的技术基线，但不适合作为已经完成的通用兴趣产品发布**。

最值得保留的是其 local-first desktop、AI-native UI、Provider isolation、evidence/version/review 基础设施。

最需要重构的不是 DeepTutor 或 Tauri，而是：

**Domain ownership + plugin composition + prompt/policy ownership + scope/migration。**

建议下一正式里程碑定义为：

> **v0.5 — General Interest Core + Psychology Default Domain Pack**

而不是继续称“Psychology Growth 加更多兴趣”。
