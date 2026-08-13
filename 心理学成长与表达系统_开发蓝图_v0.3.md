# 心理学成长与表达系统：开发蓝图 v0.3

> 状态：开发基线（Architecture Baseline）
> 日期：2026-08-11
> 目标：在**不 Fork DeepTutor**的前提下，独立开发一套长期可演进的心理学成长与表达系统；尽量复用 DeepTutor 的成熟能力，同时确保核心数据、产品逻辑、插件体系、UI 与未来方向不受其限制。

---

## 0. 一句话定义

这是一个以**兴趣培养与长期成长**为第一目标、以**可靠学习与证据意识**为方法、以**内容表达与职业探索**为自然出口的个人心理学系统。

核心循环：

```text
真实问题
  ↓
快速探索 / 学习 / 深度研究
  ↓
概念、证据、Claim 与理解沉淀
  ↓
可选：内容表达 / 图片提示词 / 视频提示词 / 发布包
  ↓
人工审核与发布
  ↓
反馈与新问题
  ↓
回流到兴趣与学习
```

任何环节都允许自然结束，不强制每个问题最终变成内容。

---

# 1. 产品目标

## 1.1 第一目标：保护与培养兴趣

系统必须降低“开始学习”的心理成本，而不是制造新的任务压力。

需要做到：

- 允许只记录一个问题就结束；
- 允许只快速了解，不做完整研究；
- 允许学到一半暂停，未来无损恢复；
- 允许一个专题永远不公开发表；
- 允许状态不好时自动降级工作量；
- 不以连续打卡、发文数量、阅读页数作为核心成功指标；
- 优先鼓励“主动产生问题”“主动回来继续”“理解发生变化”。

## 1.2 第二目标：形成可靠的心理学知识结构

系统不仅保存笔记，而要帮助用户逐渐形成：

- 概念网络；
- 理论关系；
- Evidence Library；
- Claim Ledger；
- 支持证据 / 相反证据；
- 研究限制；
- 可信度与表达边界；
- 观点的版本演化。

## 1.3 第三目标：把学习自然转化为表达

不是为了“生产内容而学习”，而是：

> 当一个问题已经理解到适合表达的程度时，系统帮助把它低摩擦地转化为图文、长文、视频脚本或其他内容。

## 1.4 第四目标：长期验证职业方向

系统逐渐记录：

- 持续兴趣主题；
- 能力增长；
- 对心理咨询、教育心理、心理科普、研究等方向的兴趣变化；
- 当前能力边界；
- 可公开表达范围；
- 未来培训 / 学习 / 职业尝试。

职业探索是长期结果，不是初期 KPI。

---

# 2. 不做什么

第一阶段明确不做：

- 不做心理诊断系统；
- 不做自动心理咨询决策；
- 不让 AI 自动输出个体诊断结论；
- 不做自动治疗建议；
- 不追求“一键自动发布”；
- 不追求复杂社交媒体矩阵；
- 不做通用 AI 平台；
- 不重写 DeepTutor 已经成熟的通用基础设施；
- 不把 DeepTutor 内部数据库当作本项目的唯一事实来源；
- 不依赖 DeepTutor 未成熟的 Plugin Loader 作为本项目插件体系的根基；
- 不为了“未来可能用到”而一次实现全部功能。

---

# 3. 总体架构原则

正式确定以下架构原则：

```text
Independent Product
Plugin-First
DeepTutor-Powered
Adapter-Isolated
Own-Data-First
Fallback-Ready
Human-Review-Gated
Upstream-Audited
Feature-Flagged
Versioned-Knowledge
```

含义：

1. **Independent Product**：项目有自己的仓库、UI、数据库、产品逻辑。
2. **Plugin-First**：新增领域功能优先做插件，而不是持续膨胀 Core。
3. **DeepTutor-Powered**：优先复用 DeepTutor 的优质能力。
4. **Adapter-Isolated**：所有 DeepTutor 调用集中在 Adapter，不向业务层泄漏内部接口。
5. **Own-Data-First**：Question、Claim、Evidence、Growth 等核心数据由自己掌握。
6. **Fallback-Ready**：DeepTutor 不可用时，核心产品仍然可使用。
7. **Human-Review-Gated**：公开表达与发布始终保留人工审核。
8. **Upstream-Audited**：DeepTutor 更新必须经过兼容性与差异审计。
9. **Feature-Flagged**：新功能可独立开关、灰度、回滚。
10. **Versioned-Knowledge**：知识与观点允许被修正，不覆盖历史。

---

# 4. 与 DeepTutor 的关系

## 4.1 不 Fork

本项目**不 Fork DeepTutor**，也不复制其完整源码成为项目主体。

推荐关系：

```text
Psychology Growth Product
        │
        ├── DeepTutor Adapter ────> DeepTutor Runtime
        ├── DeepSeek Adapter  ────> DeepSeek API
        ├── Local Services
        └── Future Adapters
```

DeepTutor 作为独立服务运行，可通过 Docker / 本地服务 / 内部 HTTP API 连接。

## 4.2 DeepTutor 的角色

DeepTutor 主要承担通用智能能力：

- Capability Runtime；
- Deep Research；
- Knowledge Center / RAG；
- 文档解析；
- Skills；
- Guided Learning；
- Mastery；
- Agent Memory；
- Visualize；
- Tools；
- 未来新增的优秀通用能力。

本项目负责：

- 兴趣；
- 好奇心；
- 心理学领域模型；
- Claim / Evidence；
- 边界；
- 正反馈；
- Growth Memory；
- 内容生产；
- 职业探索；
- 用户自己的长期产品体验。

## 4.3 DeepTutor 当前可直接利用的基础

当前 DeepTutor 已具备：

- Skills：`SKILL.md + references/ + optional scripts`，支持按需读取；
- Capability Registry；
- Capability 执行 API 与 SSE 流；
- Knowledge / RAG 与多种解析器；
- Deep Research；
- Guided Learning / Mastery；
- Memory；
- 多模型与工具基础设施。

同时，其代码已有 Plugin Registry / Plugin API 设计痕迹，但当前完整 Plugin Loader 并不是本项目必须依赖的稳定基础。

因此：

> **DeepTutor Skills 可以直接使用；DeepTutor Capability API 可以作为主要运行接口；本项目自己的产品插件体系独立实现。**

---

# 5. 系统分层

```text
┌───────────────────────────────────────┐
│            Psychology Growth UI       │
├───────────────────────────────────────┤
│              Product Plugins          │
│ Curiosity / Research / Feedback / ... │
├───────────────────────────────────────┤
│                Domain Core            │
│ Question / Claim / Evidence / Growth  │
├───────────────────────────────────────┤
│              Engine Contracts         │
│ Research / Memory / Knowledge / LLM   │
├───────────────────────────────────────┤
│                  Adapters             │
│ DeepTutor / DeepSeek / Local / Future │
├───────────────────────────────────────┤
│          External / Local Engines     │
│ DeepTutor / DeepSeek / Future APIs    │
└───────────────────────────────────────┘
```

---

# 6. 自己的插件体系

## 6.1 为什么必须插件化

插件的目标不是“炫技”，而是解决：

- 一个功能出问题不拖累整个系统；
- 可以单独升级；
- 可以单独禁用；
- 可以单独回滚；
- 未来新增能力不需要频繁修改 Core；
- 用户可以只启用自己真正需要的模块。

## 6.2 插件等级

### Level 1 — Skill / Prompt Plugin

用于：

- 心理学文献阅读规则；
- Claim 审查；
- 证据审查；
- Skeptic；
- 小红书写作；
- 图片 Prompt；
- 视频 Prompt。

其中适合 DeepTutor Agent 的部分优先使用 DeepTutor Skill 格式。

### Level 2 — Capability Plugin

拥有业务逻辑，可调用 Engine：

- Psychology Research；
- Evidence Review；
- Flexible Mastery。

### Level 3 — Product Feature Plugin

可拥有：

- 页面；
- API；
- 自己的数据；
- Event Subscription；
- Dashboard Widget；
- Settings；
- Migration。

例如 Growth Feedback。

### Level 4 — Integration Plugin

连接外部系统：

- DeepTutor；
- DeepSeek；
- Zotero；
- Crossref；
- PubMed；
- 图片 API；
- 视频 API；
- Obsidian；
- 社交平台。

## 6.3 插件生命周期

插件必须支持：

```text
Installed
Enabled
Disabled
Update Available
Updating
Rollback Available
Uninstalled
```

禁用插件：保留数据。
卸载插件：默认保留数据。
删除插件数据：必须独立确认。

## 6.4 插件 Manifest 建议

```yaml
id: psychology.growth-feedback
name: Growth Feedback
version: 0.1.0

requires:
  core: ">=0.3,<0.4"
  plugins:
    - psychology.growth-core

provides:
  pages:
    - /growth/feedback
  capabilities:
    - growth-feedback
  widgets:
    - weekly-growth

subscribes:
  - research.completed
  - mastery.updated
  - claim.revised
  - topic.returned

permissions:
  read:
    - mastery
    - research
  write:
    - growth_feedback

risk:
  network: false
  shell: false
  llm: true
  destructive_data: false
```

---

# 7. 第一批产品插件

## 7.1 `psychology-growth-core`

最小公共领域层。

提供：

- InterestSignal；
- GrowthEvent；
- Boundary；
- EnergyMode；
- Reflection；
- FeedbackSignal；
- Growth Timeline 基础接口。

禁止塞入过多具体页面与工作流。

## 7.2 `psychology-curiosity`

功能：

- Curiosity Inbox；
- 快速记录问题；
- 问题来源；
- 兴趣强度；
- 状态；
- 是否主动产生；
- 暂停；
- 回归；
- 转 Topic；
- 只记录不研究。

## 7.3 `psychology-research-evidence`

功能：

```text
Question
→ Research Plan
→ DeepTutor Deep Research
→ Source Candidates
→ Evidence
→ Claim
→ Counter Evidence
→ Limitations
→ Boundary
```

系统必须区分：

- 检索命中；
- AI 摘要；
- 原文；
- 人工核验；
- 研究支持；
- 可公开表达。

## 7.4 `psychology-flexible-mastery`

掌握度不等于做题正确率。

建议阶段：

```text
0 陌生
1 有印象
2 能解释
3 能举例
4 能区分
5 能迁移
6 能判断证据边界
7 能稳定公开表达
```

任何概念不要求强制达到 7。

## 7.5 `psychology-growth-feedback`

这是核心差异化插件之一。

正反馈来源：

- 过程；
- 能力；
- 闭环；
- 回归；
- 高质量社会反馈；
- 自我叙事。

避免：

- 单纯连续打卡；
- 单纯发文数量；
- 单纯点赞量；
- 过度游戏化。

系统应能发现：

- 以前不会，现在会了；
- 以前说得绝对，现在会表达边界；
- 一个中断很久的主题重新被主动拾起；
- 用户主动问题比例提升；
- 用户逐渐不依赖 AI 给结论。

## 7.6 `psychology-reflection`

负责：

- Weekly Review；
- 兴趣变化；
- 精力；
- 外界评价影响；
- 哪些主题真的想继续；
- 什么在消耗兴趣；
- 下周是否继续。

## 7.7 `psychology-concept-graph`

节点：

- Question；
- Concept；
- Theory；
- Claim；
- Evidence；
- Source；
- Content。

关系：

- supports；
- contradicts；
- explains；
- prerequisite；
- confused_with；
- similar_to；
- applied_to；
- cited_by。

## 7.8 `psychology-content-studio`

输入不必只有“已经完成的研究”，也可从 Topic / Concept / Feedback 进入。

输出：

- 标题候选；
- 正文；
- 长文；
- 小红书图文结构；
- 视频结构；
- Claim 引用关系；
- 风险提醒；
- Publish Pack。

默认不自动发布。

## 7.9 `psychology-media-prompt`

当前阶段：

- 生成 ChatGPT 图片 Prompt；
- 生成视频 Prompt；
- 生成分镜；
- 提供构图 / 风格 / 留白 / 禁止元素；
- 用户手动生成后上传回来。

未来只需增加 Image / Video Provider 插件即可自动生成。

## 7.10 `psychology-career`

后期插件。

负责：

- 长期兴趣方向；
- 能力边界；
- 培训路线；
- 心理科普 / 教育心理 / 心理咨询 / 研究等方向比较；
- 可公开表达范围；
- 职业实验记录。

---

# 8. 弹性系统

## 8.1 Energy Mode

### Light

只要求最轻动作：

- 记一个问题；
- 收藏一个来源；
- 看一个概念解释；
- 写一句感想。

### Normal

典型：

```text
一个问题
→ 几个来源
→ 形成理解
→ 可选知识沉淀
```

### Deep

典型：

```text
Deep Research
→ 多来源
→ 理论比较
→ Claim Ledger
→ Counter Evidence
→ Concept Graph
→ 可选内容表达
```

三个模式没有价值等级。

## 8.2 半闭环原则

合法结束点：

```text
Question → END
Question → Quick Explore → END
Question → Concept → END
Question → Research → END
Question → Content Draft → END
Question → Publish Pack → Human Review
```

系统不得暗示只有发出去才算完成。

## 8.3 自动降级

如果：

- DeepTutor 不可用；
- 精力不足；
- 来源不足；
- 图片未准备；

系统应允许：

```text
Deep Research → Quick Explore
Publish Pack → Text Pack
Video Pack → Outline
AI Image → Prompt Only
```

---

# 9. 边界系统

每个 Topic / Claim 都可拥有以下边界：

## 9.1 兴趣边界

- fleeting；
- explore；
- topic；
- deep_research；
- expression；
- pause。

## 9.2 证据边界

- stable；
- supported_with_caution；
- limited；
- controversial；
- internal_only；
- not_publishable。

## 9.3 能力边界

- inside_current_competence；
- cautious_expression；
- learning_only；
- outside_scope。

## 9.4 内容边界

- internal_note；
- article；
- xhs；
- video；
- longform；
- hold。

## 9.5 AI 权限边界

AI 可以：

- 帮助搜索；
- 帮助拆问题；
- 帮助结构化；
- 帮助生成草稿；
- 帮助发现逻辑漏洞；
- 帮助生成图片/视频提示词。

AI 不得自动成为：

- 最终文献真伪确认者；
- 个体诊断者；
- 治疗建议决策者；
- 最终心理学结论审批者；
- 自动公开发布者。

---

# 10. 核心数据模型

核心实体尽量保持少而稳定。

```text
User
Question
Topic
Concept
Source
Evidence
Claim
ClaimVersion
Memory
MasteryRecord
GrowthEvent
Reflection
Feedback
Artifact
CapabilityRun
PluginState
```

## 10.1 Source

建议字段：

```text
id
source_type
title
authors
year
publisher
DOI
PMID
ISBN
canonical_url
local_file
full_text_available
ai_summary_only
verified
verified_at
notes
```

## 10.2 Evidence

```text
id
source_id
evidence_type
excerpt_or_summary
location
supports_claim
strength
limitations
verified
```

## 10.3 Claim

```text
id
topic_id
current_version_id
status
confidence
source_level
publishability
last_verified_at
```

## 10.4 ClaimVersion

不要覆盖旧观点。

```text
claim_id
version
statement
supporting_evidence
contradicting_evidence
limitations
reason_for_revision
created_at
```

## 10.5 Artifact

所有产物统一抽象：

```text
note
research_report
concept_card
article
xhs_pack
image_prompt
image
video_prompt
video
concept_map
review
export
```

这样以后新媒体类型不需要疯狂增加新表。

---

# 11. Memory 设计

## 11.1 DeepTutor Memory

定位：Agent / 学习过程工作记忆。

不是唯一事实源。

## 11.2 Growth Memory

属于本项目。

记录长期稳定事实：

- recurring interests；
- recurring confusions；
- mastered concepts；
- preferred learning modes；
- views under validation；
- career interest changes；
- current competence boundaries。

不存大量短期情绪噪声。

## 11.3 三层 Growth Memory

### G1 Raw Growth Trace

问题、反思、行为、回归、反馈。

### G2 Structured Growth Record

概念掌握、误区、兴趣主题、能力变化。

### G3 Long-term Growth Model

长期稳定趋势与成长叙事。

---

# 12. DeepTutor Capability Map

建立长期维护文件：

`compat/deeptutor/CAPABILITY_MAP.md`

建议初版：

| DeepTutor 能力 | 策略 | 本项目接口 |
|---|---|---|
| Capability Runtime | 采用 | DeepTutorClient |
| Deep Research | 采用 | ResearchEngine |
| Knowledge Center | 采用 | KnowledgeEngine |
| RAG | 采用 | RetrievalEngine |
| Skills | 采用 | SkillBridge |
| Memory | 部分采用 | AgentMemoryEngine |
| Guided Learning | 部分采用 | LearningEngine |
| Mastery | 部分采用 | AssessmentEngine |
| Visualize | 预留 | VisualizationEngine |
| Question Bank | 预留 | PracticeEngine |
| Document Parsing | 采用/预留 | ParsingEngine |
| Tools | 采用 | ToolEngine |
| MCP | 预留 | IntegrationEngine |
| Partners | 观察 | FutureAgentIntegration |
| Plugin API | 观察 | 不作为自身插件根基 |
| Multi-user | 暂缓 | Future |

每次 DeepTutor 升级必须复核此表。

---

# 13. Engine Contracts

业务层只依赖自己的接口。

## 13.1 ResearchEngine

实现：

```text
DeepTutorResearchEngine
DeepSeekResearchEngine
ManualResearchEngine
```

## 13.2 KnowledgeEngine

```text
DeepTutorKnowledgeEngine
LocalKnowledgeEngine
```

## 13.3 MemoryEngine

```text
DeepTutorAgentMemory
GrowthMemory
```

## 13.4 LLMProvider

```text
DeepSeekProvider
FutureOpenAIProvider
FutureClaudeProvider
FutureGeminiProvider
LocalProvider
```

第一阶段只正式实现 DeepSeek。

## 13.5 ImageProvider

```text
ManualPromptWorkflow
LocalCardRenderer
FutureImageAPIProvider
```

## 13.6 VideoProvider

```text
ManualVideoPromptWorkflow
FutureVideoAPIProvider
```

---

# 14. DeepSeek 使用策略

DeepSeek 负责主要语言模型调用。

用途：

- 问题分类；
- Research brief；
- Claim 草拟；
- 信息结构化；
- Concept Card；
- 内容草稿；
- 图文结构；
- 图片 Prompt；
- 视频 Prompt；
- 反方审查；
- Weekly Review 草稿。

所有重要结构输出优先采用 JSON Schema。

标准流程：

```text
LLM Output
→ schema validation
→ auto repair once
→ still invalid
→ human editable state
```

禁止静默吞错继续。

---

# 15. 内容系统

## 15.1 Publish Pack，而非自动发布

一个内容包建议包含：

```text
01-title-candidates.md
02-post.md
03-longform.md
04-claims.md
05-sources.md
06-risk-review.md
07-card-plan.md
08-image-prompts.md
09-video-script.md
10-video-prompts.md
assets/
publish.json
```

## 15.2 图文模式

### Local Card

适合：

- 概念；
- 三点总结；
- 对比；
- 时间线；
- Evidence Card；
- Checklist；
- Concept Map。

可用 HTML/CSS/SVG + Playwright 本地渲染 PNG。

### Manual AI Illustration

系统生成完整 Prompt，用户用 ChatGPT 等工具生成图片，再导入。

### User Asset

用户图片、截图、书摘、图表优先可用。

## 15.3 Style × Layout × Palette

视觉系统从一开始分离：

### Style

- Psychology Editorial；
- Research Paper；
- Study Notes；
- Minimal；
- Warm Illustration。

### Layout

- Cover；
- Problem；
- Mechanism；
- Comparison；
- Three Points；
- Timeline；
- Evidence；
- Concept Map；
- Checklist；
- Closing。

### Palette

独立配置，不与 Style 强绑定。

---

# 16. Publish Guard

发布前自动检查，但不替用户做最后决定。

## 16.1 心理学表达

检查：

- unsupported causality；
- correlation → causation；
- “心理学证明”；
- 过度绝对化；
- 诊断式语言；
- 治疗承诺；
- 将群体研究直接套到个体；
- 缺少研究限制。

## 16.2 Evidence

检查：

- Claim 是否有 Evidence；
- Evidence 是否来自可识别 Source；
- 是否只有 AI 摘要；
- 是否存在相反证据；
- 是否过期；
- 是否经过人工核验。

## 16.3 内容

检查：

- 标题是否过度夸张；
- 卡片是否信息过载；
- 引用是否对应；
- 图片 Prompt 是否泄漏敏感内容；
- 是否明确边界。

---

# 17. 正反馈引擎

不做“签到型激励系统”。

## 17.1 Process Feedback

例如：

- 今天记录了一个真实问题；
- 今天核验了一条 Claim；
- 今天区分了两个概念。

## 17.2 Capability Feedback

例如：

- 从“看懂”到“能解释”；
- 从“能解释”到“能判断证据”；
- 某概念已经能够稳定迁移。

## 17.3 Loop Feedback

完成一次自然闭环即为成果，不要求发布。

## 17.4 Return Feedback

特别记录：

> 暂停之后重新主动回来。

这比连续打卡更重要。

## 17.5 Social Quality Feedback

收藏：

- 高质量评论；
- 真正理解的反馈；
- 带来新问题的互动。

不把点赞数等同于学习质量。

## 17.6 Narrative Feedback

系统周期性生成：

> “过去一段时间你的理解发生了什么变化？”

帮助建立长期自我叙事。

---

# 18. 首页设计原则

首页必须安静。

建议只突出：

1. 最近想继续的问题；
2. 当前 1–3 个 Active Topics；
3. 今日/本周微进展；
4. 快速记录问题；
5. 当前 Energy Mode。

不展示大量 KPI。

不默认显示：

- 发文数量排行榜；
- 连续天数；
- Token 花费大图；
- 任务红点轰炸。

这些可在设置或高级页面查看。

---

# 19. 事件系统

插件之间尽量使用事件，而不是互相直接调用内部函数。

建议事件：

```text
question.created
question.returned
topic.activated
topic.paused
research.started
research.completed
claim.created
claim.revised
claim.verified
mastery.updated
reflection.completed
content.created
content.approved
artifact.created
feedback.received
plugin.enabled
plugin.disabled
```

例如：

```text
claim.revised
     ├─ Growth Feedback 发现“观点修正”
     ├─ Content Studio 标记旧内容需复核
     └─ Concept Graph 更新关系
```

不建立硬编码流水线。

---

# 20. Feature Flags

从第一版就支持：

```text
FEATURE_DEEP_RESEARCH
FEATURE_GROWTH_FEEDBACK
FEATURE_FLEXIBLE_MASTERY
FEATURE_CONCEPT_GRAPH
FEATURE_CONTENT_STUDIO
FEATURE_MEDIA_PROMPT
FEATURE_LOCAL_CARD_RENDERER
FEATURE_DEEPTUTOR_MEMORY
FEATURE_VISUALIZE
FEATURE_CAREER
```

目的：

- 单独关闭故障功能；
- 阶段性测试；
- 避免一次上线所有复杂模块；
- 上游升级时隔离问题。

---

# 21. 仓库结构建议

```text
psychology-growth/
│
├── apps/
│   ├── web/
│   └── api/
│
├── packages/
│   ├── domain/
│   ├── engine-contracts/
│   ├── plugin-runtime/
│   ├── event-bus/
│   ├── artifacts/
│   └── shared/
│
├── plugins/
│   ├── psychology-growth-core/
│   ├── curiosity/
│   ├── research-evidence/
│   ├── flexible-mastery/
│   ├── growth-feedback/
│   ├── reflection/
│   ├── concept-graph/
│   ├── content-studio/
│   ├── media-prompt/
│   └── career/
│
├── adapters/
│   ├── deeptutor/
│   ├── deepseek/
│   ├── local-search/
│   └── media/
│
├── skills/
│   ├── psychology-evidence-review/
│   ├── psychology-claim-check/
│   ├── psychology-skeptic/
│   ├── psychology-research/
│   ├── psychology-writing/
│   ├── xhs-writing/
│   ├── image-prompt/
│   └── video-prompt/
│
├── compat/
│   └── deeptutor/
│       ├── SUPPORTED_VERSIONS.md
│       ├── CAPABILITY_MAP.md
│       ├── API_CONTRACT.md
│       ├── KNOWN_ISSUES.md
│       └── UPGRADE_REPORT.md
│
├── docs/
│   ├── architecture/
│   ├── decisions/
│   ├── audits/
│   ├── roadmap/
│   └── product/
│
├── infra/
│   ├── docker/
│   └── compose/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contracts/
│   └── e2e/
│
└── README.md
```

---

# 22. 推荐技术栈

## Frontend

- Next.js / React
- TypeScript

## Backend

- Python
- FastAPI

## Database

开发初期：SQLite 可接受。
如果很快加入大量插件与长期数据，优先 PostgreSQL。

建议从数据访问层开始就不要依赖数据库专有语法，以保留迁移空间。

## Object / File Storage

抽象 StorageProvider：

```text
LocalFilesystem
FutureS3
FutureNAS
```

## DeepTutor

独立服务 / Docker 容器，锁定版本。

## LLM

DeepSeek 为当前默认。

---

# 23. 部署拓扑

推荐初期：

```text
Docker Compose

psychology-web
psychology-api
psychology-db
psychology-worker (可后加)
deeptutor
```

DeepTutor 挂掉时：

- Web 可用；
- 数据可用；
- Curiosity 可用；
- Reflection 可用；
- Content 草稿可用；
- DeepSeek 可用；
- Deep Research / DeepTutor KB 显示 unavailable。

---

# 24. DeepTutor 版本与联合审计

## 24.1 锁定版本

禁止长期使用：

```text
deeptutor:latest
```

必须记录：

```text
version
tag
commit
updated_at
```

## 24.2 更新流程

```text
发现新版本
→ 读取 release / compare diff
→ 更新 Capability Map
→ Adapter contract tests
→ Deep Research smoke test
→ Knowledge smoke test
→ Skill smoke test
→ Memory / Mastery affected-area test
→ Psychology integration tests
→ Audit report
→ 人工决定是否升级
```

## 24.3 影响范围审计

如果上游只修改 Partners，则不必重审 Content Studio。

如果修改：

```text
Memory
```

重点检查：

```text
DeepTutor Memory Adapter
Growth Memory bridge
Reflection
Growth Feedback
```

## 24.4 DeepTutor Watcher（后续）

未来插件可定期检查：

- 最新 Release；
- 当前落后版本；
- 新 Capability；
- Breaking Change；
- 可能适合本项目的新功能；
- 是否建议升级。

只建议，不自动升级。

---

# 25. 数据所有权与可迁移性

必须能够回答：

> 如果明天完全删除 DeepTutor，我还剩什么？

答案应该是：

- 所有 Question；
- 所有 Topic；
- 所有 Source；
- 所有 Evidence；
- 所有 Claim 及历史版本；
- 所有 Concept；
- 所有 Growth Memory；
- 所有 Reflection；
- 所有 Content；
- 所有图片/视频 Prompt；
- 所有 Artifact；
- 所有职业探索记录。

DeepTutor 内部数据只作为：

- 运行缓存；
- RAG index；
- Agent Memory；
- 可重建派生数据。

---

# 26. 隐私与安全

心理学成长数据可能高度私人，第一阶段应：

- 默认单用户；
- 默认本地/私有部署优先；
- Secret 不写入数据库明文；
- API Key 使用环境变量 / Secret Store；
- 插件声明权限；
- 网络、Shell、破坏性数据权限单独分级；
- 高风险插件默认关闭；
- 导出 / 删除个人数据要可审计；
- 日志避免记录完整敏感内容。

---

# 27. 第一阶段 MVP

MVP 不要太大。

## P0：工程底座

必须完成：

- 独立仓库；
- Web + API；
- 数据库；
- Plugin Runtime v0.1；
- Event Bus；
- Feature Flags；
- Artifact abstraction；
- DeepSeek Provider；
- DeepTutor Adapter；
- DeepTutor version lock；
- Contract tests；
- Docker Compose；
- 基础审计文档。

验收：

> DeepTutor 完全关闭时，系统仍可启动、记录问题、保存数据。

## P1：兴趣与问题

开发：

- Dashboard v1；
- Curiosity Inbox；
- Topic Workspace；
- Energy Mode；
- Pause / Return；
- 最小 Growth Event。

验收：

> 一个问题从记录到暂停再到回归完整可用，且不会强制进入研究。

## P2：研究与证据

开发：

- DeepTutor Deep Research Adapter；
- Research Plan；
- Source；
- Evidence；
- Claim；
- Counter Evidence；
- Claim Version；
- Evidence Guard；
- Psychology research skills。

验收：

> 一个 Topic 能形成可追溯的 Claim ↔ Evidence 关系；关闭 DeepTutor 后数据仍完整存在。

## P3：学习与成长

开发：

- Concept Card；
- Flexible Mastery；
- Growth Memory；
- Growth Feedback；
- Weekly Reflection。

验收：

> 系统能够展示“理解发生了什么变化”，而不只是学习次数。

## P4：内容表达

开发：

- Content Studio；
- Publish Pack；
- 小红书图文结构；
- 图片 Prompt；
- 视频 Prompt；
- Publish Guard；
- 本地信息卡渲染 MVP。

验收：

> 从一个已研究 Topic 可生成完整可审核的图文 / 视频素材包，但不会自动发布。

## P5：知识网络与高级能力

开发：

- Concept Graph；
- Visualization；
- Knowledge Center 深度同步；
- 更强 Mastery；
- DeepTutor Memory bridge；
- 外部文献服务。

## P6：职业探索与生态

开发：

- Career Plugin；
- Zotero；
- Obsidian；
- 更多模型；
- 图片 / 视频 API；
- 可选社交平台发布插件；
- DeepTutor Watcher；
- Plugin Hub（有实际需求后再做）。

---

# 28. 开发阶段的强制原则

每次增加功能都必须回答：

1. 它是否保护或增强兴趣？
2. 它是否帮助能力成长，而不是只替用户做更多？
3. 它是否减少机械成本？
4. 它会不会制造额外管理压力？
5. 删除它以后核心循环是否仍成立？
6. 是否应该做 Plugin，而不是写进 Core？
7. 是否已经有 DeepTutor 优质能力可复用？
8. 如果 DeepTutor 未来变化，这个功能是否仍可迁移？

如果不能合理回答，不进入当前迭代。

---

# 29. 测试策略

## Unit

- Domain rules；
- Claim versioning；
- Boundary；
- Plugin lifecycle；
- Feedback rules。

## Contract

尤其重要：

- DeepTutor API Contract；
- DeepSeek JSON Contract；
- Plugin Manifest Contract；
- Storage Contract。

## Integration

- Research → Evidence → Claim；
- Claim revision → Feedback → Content invalidation；
- DeepTutor unavailable fallback；
- Plugin disable/enable；
- Database migrations。

## E2E

至少覆盖：

```text
记录一个问题
→ 快速探索
→ 升级专题
→ Deep Research
→ 建立 Claim
→ 生成人工审核内容包
→ 暂不发布
→ 一周后回归
```

这是核心产品旅程。

---

# 30. 开发完成定义（Definition of Done）

一个功能不能因为“页面看起来能用”就算完成。

每个功能至少满足：

- 有明确产品目标；
- 有数据模型；
- 有失败状态；
- 有禁用/降级路径；
- 有权限边界；
- 有测试；
- 有日志；
- 有迁移方案；
- 不破坏其他插件；
- 有文档；
- 若依赖 DeepTutor，有兼容性测试；
- 若产生心理学表达，有边界与人工审核路径。

---

# 31. 首次开发建议顺序

真正开始编码时，建议严格按下面顺序，不先做漂亮页面：

```text
1. Repo + architecture docs
2. Domain Core
3. Plugin Runtime
4. Event Bus
5. Engine Contracts
6. DeepSeek Adapter
7. DeepTutor Adapter + contract tests
8. Database + migration
9. Curiosity Plugin
10. Dashboard v1
11. Research Evidence Plugin
12. Claim/Evidence UI
13. Growth Memory / Feedback
14. Content Studio
15. Media Prompt
16. Local Card Renderer
17. Advanced DeepTutor capabilities
```

这样先保证“以后能长”，再快速补功能。

---

# 32. 未来能力预留清单

当前只预留接口，不实现或不默认启用：

- OpenAI / Claude / Gemini / Local LLM；
- Image API；
- Video API；
- Speech / Podcast；
- 视频课程解析；
- Zotero；
- PubMed；
- Crossref；
- Semantic Scholar；
- Obsidian；
- Web Clipper；
- Mobile App；
- NAS / S3；
- Multi-user；
- Public Knowledge Garden；
- Social Platform Adapters；
- Automation；
- DeepTutor Visualize；
- DeepTutor Question Bank；
- DeepTutor MCP；
- DeepTutor future capabilities；
- 自定义 Research Engine。

预留原则：**定义接口，不提前实现。**

---

# 33. 项目成功标准

这个项目真正成功，不是因为它拥有最多 AI 功能，而是因为长期来看：

- 用户更容易主动提出心理学问题；
- 更愿意回来继续旧问题；
- 更少从头重读；
- 更会区分“知道一个说法”和“证据支持一个 Claim”；
- 更能表达研究边界；
- 对心理学知识形成自己的结构；
- 对流量的依赖下降；
- 内容生产越来越自然；
- 能看到自己能力真实增长；
- 对职业方向的判断越来越基于真实体验而不是想象。

---

# 34. 当前架构决议

截至 v0.3，正式确认：

1. 不 Fork DeepTutor。
2. 不复制 DeepTutor 作为主项目。
3. 创建完全独立的 Psychology Growth 仓库。
4. DeepTutor 作为首选高级学习 / Research / Knowledge 引擎。
5. DeepTutor 通过 Adapter 隔离。
6. 核心数据由本项目拥有。
7. 自己实现产品级 Plugin Runtime。
8. DeepTutor Skills 尽量复用。
9. DeepTutor Capability API 尽量复用。
10. DeepTutor 当前及未来优质功能通过 Capability Map 持续评估。
11. 所有 DeepTutor 更新均版本锁定并联合审计。
12. DeepSeek 作为当前主要 LLM Provider。
13. 图片/视频第一阶段采用 Prompt Pack + 手动生成。
14. 内容生成与公开发布分离。
15. 兴趣、弹性、正反馈、证据边界是产品核心，不是附加功能。

---

# 35. 下一阶段产物

蓝图确认后，开发前应继续生成以下文件：

```text
01_ARCHITECTURE.md
02_DOMAIN_MODEL.md
03_PLUGIN_API_v0.1.md
04_DEEPTUTOR_INTEGRATION.md
05_DEEPTUTOR_CAPABILITY_MAP.md
06_DATABASE_SCHEMA.md
07_EVENT_CONTRACT.md
08_DEEPSEEK_PROVIDER.md
09_MVP_ROADMAP.md
10_ACCEPTANCE_TESTS.md
11_SECURITY_AND_PRIVACY.md
12_CODING_AGENT_MASTER_PROMPT.md
```

其中最优先：

```text
03_PLUGIN_API_v0.1.md
04_DEEPTUTOR_INTEGRATION.md
06_DATABASE_SCHEMA.md
09_MVP_ROADMAP.md
```

完成这些后再正式开始 P0 编码。

---

## 附：设计核心

> DeepTutor 是引擎，不是产品边界。
> 插件是扩展方式，不是新的复杂度来源。
> AI 是降低摩擦的工具，不是替代最终判断的人。
> 内容是学习的自然产物，不是所有学习的终点。
> 正反馈来自真实成长，而不是单一流量。
> 系统必须允许暂停、回归、降级、绕路和重新理解。
> 最终要培养的不是“完成任务的能力”，而是长期主动探索心理学的能力。
