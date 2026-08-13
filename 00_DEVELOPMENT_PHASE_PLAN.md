# 心理学成长与表达系统：开发阶段计划 v0.1

> 对应蓝图：《心理学成长与表达系统：开发蓝图 v0.3》
> 原则：每一阶段**先实现 → 自测 → 审计 → 再进入下一阶段**。
> 不以“功能数量”作为阶段完成标准。

---

# 0. 总体推进策略

开发采用：

```text
Architecture First
→ Thin Vertical Slice
→ Contract Tests
→ Product Loop
→ Advanced Capabilities
```

第一轮目标不是“做成最终产品”，而是证明五件事：

1. 独立项目能够在没有 DeepTutor 时正常存在；
2. DeepTutor 能作为可插拔引擎接入；
3. 插件能独立启停且不破坏 Core；
4. Question → Research → Claim/Evidence → Growth 的核心数据链可持续；
5. 内容生产只是可选出口，不会反向绑架学习流程。

---

# P0 — Architecture Foundation

## 目标

搭好以后 2–3 年仍可演进的最小工程底座。

## 必做

- 创建独立 GitHub 仓库；
- README；
- Architecture Decision Records；
- `apps/web`；
- `apps/api`；
- `packages/domain`；
- `packages/plugin-runtime`；
- `packages/engine-contracts`；
- Event Bus；
- Feature Flag；
- Plugin Manifest v0.1；
- Plugin lifecycle；
- Artifact 抽象；
- Database + migration；
- DeepSeek Provider skeleton；
- DeepTutor Adapter skeleton；
- Docker Compose；
- Core health check；
- DeepTutor health check；
- CI 基础测试。

## 暂不做

- Deep Research UI；
- Growth Feedback；
- Content Studio；
- 图片渲染；
- Career；
- 社交平台发布；
- Plugin Store。

## 验收

### A. Core independence

关闭 DeepTutor：

```text
Web ✅
API ✅
DB ✅
Plugin Runtime ✅
基本 CRUD ✅
```

### B. Plugin isolation

安装一个 demo plugin：

```text
Enable → 页面/API生效
Disable → Core仍正常
Enable again → 数据仍在
```

### C. Engine contract

DeepTutor Adapter 与 DeepSeek Adapter 不得被 Domain 直接 import。

### D. Audit

生成：

```text
docs/audits/P0_AUDIT.md
```

只有 P0 审计通过才进入 P1。

---

# P1 — Curiosity & Interest Loop

## 目标

先证明这个网站真的能帮助“产生、保存、恢复兴趣”，而不是先做 AI 大功能。

## 插件

- `psychology-growth-core`
- `psychology-curiosity`

## 必做

### Curiosity Inbox

字段至少：

- question；
- created_at；
- source/context；
- interest_level；
- state；
- energy_mode；
- active/paused；
- returned_count；
- optional notes。

### 状态

```text
Captured
Exploring
Active Topic
Paused
Closed
Returned
```

### Energy Mode

```text
Light
Normal
Deep
```

### Dashboard v1

只显示：

- 最近想继续的问题；
- 1–3 个 Active Topics；
- 微进展；
- 快速记录；
- Energy Mode。

## 关键产品约束

- 新建问题后允许直接结束；
- 不自动启动 Deep Research；
- 暂停不是失败；
- Returned 应被记作正向事件。

## 验收旅程

```text
记录问题
→ 快速看一下
→ 暂停
→ 3天后重新打开
→ 标记 Returned
→ 继续探索
```

全过程不需要发布内容。

---

# P2 — DeepTutor Integration & Research Evidence

## 目标

开始真正利用 DeepTutor 的优质能力，但把数据留在自己的系统。

## 插件

- `research-evidence`
- DeepTutor engine adapter
- psychology research skills

## 必做

### DeepTutor Client

至少支持：

- health；
- capability list；
- capability execution；
- stream consumption；
- error mapping；
- timeout；
- version info；
- capability availability。

### ResearchEngine Contract

```text
create_plan()
run()
stream()
cancel()
normalize_result()
```

业务层只看自己的 ResearchResult。

### Research Pipeline

```text
Question
→ Research Brief
→ Subquestions
→ DeepTutor Research
→ Candidate Sources
→ Evidence Candidates
→ Claims
→ Skeptic Pass
→ Human Review
```

### Claim Ledger

每个 Claim 至少有：

- statement；
- evidence_ids；
- contradicting_evidence_ids；
- confidence；
- limitations；
- publishability；
- verification state。

### Source / Evidence

自己的 DB 是事实源。

DeepTutor RAG index 必须被视为可重建数据。

## DeepTutor Skills 第一批

- `psychology-research`
- `psychology-evidence-review`
- `psychology-claim-check`
- `psychology-skeptic`

## Fallback

DeepTutor 不可用时：

```text
ResearchEngine
→ DeepSeek limited research / manual workspace
```

明确显示能力降级，不伪装为完整 Deep Research。

## 验收

给一个心理学问题：

1. 产生 Research Plan；
2. 调用 DeepTutor；
3. 形成 Source；
4. 形成至少一个 Claim；
5. 显示支持与限制；
6. 人工修改 Claim；
7. 保存 ClaimVersion；
8. 删除 DeepTutor index 后本项目记录仍存在。

---

# P3 — Learning, Mastery & Growth Feedback

## 目标

让系统开始产生真实的内部正反馈。

## 插件

- `flexible-mastery`
- `growth-feedback`
- `reflection`

## 必做

### Concept Card

至少：

- definition；
- examples；
- counterexamples；
- confused_with；
- related_claims；
- related_sources；
- mastery state。

### Flexible Mastery

```text
陌生
→ 有印象
→ 能解释
→ 能举例
→ 能区分
→ 能迁移
→ 能判断证据
→ 能稳定表达
```

### Growth Events

监听：

- returned；
- claim revised；
- mastery increased；
- misconception resolved；
- research completed；
- reflection completed。

### Growth Feedback

输出强调：

- 能力变化；
- 理解变化；
- 主动问题；
- 回归；
- 边界意识。

### Weekly Review

不要求完成任务清单，只回答：

- 什么问题最吸引我？
- 什么在消耗兴趣？
- 哪个理解发生变化？
- 哪个专题值得继续？
- 下周选择 Light / Normal / Deep 哪种节奏？

## 验收

系统必须能生成一个类似：

> “一个月前你只是知道自我决定理论；现在已经可以区分自主性、胜任感与关系需要，并能指出奖励效应不能脱离情境直接下结论。”

而不是：

> “你连续学习了 14 天。”

---

# P4 — Content Studio & Publish Pack

## 目标

把可靠理解低摩擦地转成内容，但不自动公开发布。

## 插件

- `content-studio`
- `media-prompt`
- `local-card-renderer`

## 必做

### Content Draft

输入：

- Topic；
- Claims；
- Evidence；
- target audience；
- platform / format。

### XHS Pack

输出：

- title candidates；
- body；
- tag suggestions；
- card outline；
- evidence notes；
- risk review。

### Image Prompt Pack

每页：

- purpose；
- composition；
- subject；
- style；
- palette；
- text-safe-zone；
- forbidden elements；
- aspect ratio。

### Video Pack

- hook；
- timeline；
- narration；
- shot list；
- visual prompt；
- transitions；
- subtitle keywords；
- cover prompt。

### Local Card Renderer

第一版只做信息卡：

- Cover；
- Three Points；
- Comparison；
- Evidence；
- Checklist；
- Closing。

不追求复杂 AI 艺术图。

### Publish Guard

自动提示问题但不自动“批准”。

## 验收

```text
Research Topic
→ Select Claims
→ Generate Content Draft
→ Generate XHS Pack
→ Generate Image Prompts
→ optional local cards
→ Human Review
→ Export
```

没有“自动发布”也是完整成功路径。

---

# P5 — Knowledge Graph & Advanced DeepTutor Use

## 目标

逐步吸收 DeepTutor 现有及未来成熟能力。

## 候选

- Knowledge Center 深度同步；
- DeepTutor Memory bridge；
- Guided Learning 深度结合；
- Mastery Question Bank；
- Visualize；
- Concept Graph；
- 文档解析增强；
- 外部论文数据库；
- Citation refresh；
- Claim re-verification。

每个能力先经过：

```text
Capability Map Review
→ Value
→ Coupling Risk
→ Adapter Feasibility
→ MVP Need
```

不因为 DeepTutor 有功能就全部启用。

---

# P6 — Career & Ecosystem

## 候选插件

- Career Exploration；
- Zotero；
- Obsidian；
- PubMed；
- Crossref；
- Semantic Scholar；
- Image API；
- Video API；
- Speech；
- Mobile；
- NAS / S3；
- optional social publishing；
- DeepTutor Watcher；
- Plugin Hub。

这些不得阻塞 P0–P4。

---

# DeepTutor 联合审计计划

每次升级 DeepTutor：

## Step 1 — Baseline

记录：

```text
old version
old commit
new version
new commit
```

## Step 2 — Upstream Diff

归类：

- Runtime；
- Capability；
- Research；
- Memory；
- Knowledge；
- Skills；
- Parsing；
- UI；
- Partners；
- Security。

## Step 3 — Capability Map

判断：

- 新功能值得接入？
- 当前接口受影响？
- 是否需要 Adapter 修改？

## Step 4 — Contract Tests

跑：

- health；
- capability list；
- capability execute；
- streaming；
- skills；
- research；
- knowledge；
- relevant memory/mastery tests。

## Step 5 — Impact-based Plugin Tests

只重点测试受影响插件。

## Step 6 — Report

生成：

```text
compat/deeptutor/UPGRADE_REPORT_<version>.md
```

结论：

```text
SAFE
SAFE_WITH_NOTES
HOLD
REJECT
```

---

# 第一轮开发产物清单

在真正开始 P0 编码前，准备：

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

推荐下一步先完成：

```text
03_PLUGIN_API_v0.1.md
04_DEEPTUTOR_INTEGRATION.md
06_DATABASE_SCHEMA.md
07_EVENT_CONTRACT.md
```

因为这四份一旦稳定，后面绝大多数功能可以独立开发而不反复改底座。

---

# 首轮发布目标

第一个真正可以自己长期使用的版本，不要求 P6。

建议定义为：

## `v0.1 Personal Alpha`

包含：

```text
P0 ✅
P1 ✅
P2 ✅
P3 基础 ✅
P4 基础 ✅
```

能够：

1. 记录真实问题；
2. 选择学习强度；
3. 用 DeepTutor 做深度研究；
4. 建立 Claim/Evidence；
5. 形成 Concept；
6. 看见真实成长反馈；
7. 生成可人工审核的小红书图文/视频发布包；
8. 随时暂停、回归；
9. DeepTutor 故障不会破坏已有数据。

达到这一点后，再决定哪些未来功能真的值得开发。

---

# 开发纪律

任何阶段都避免：

- 为了“完整”提前做未来插件；
- 为了漂亮首页绕过 Core；
- 让 Adapter 类型泄漏到 Domain；
- 把 DeepTutor index 当事实数据；
- 把 DeepSeek 输出直接当已核验证据；
- 自动越过 Human Review；
- 用流量指标替代学习质量；
- 因某个插件失败让整个系统不可启动；
- 不写测试就推进下一阶段。

最终目标不是开发最快，而是建立一个**能长期迭代又不失去原始目的**的系统。
