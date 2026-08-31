# Interest Growth 1X 全量重新审计与完整实现

**审计对象：** 当前 `main` 工作树与 Native Core 产品路径
**审计原则：** 先确认当前源代码与运行路径，再以 exact SHA、远程 Actions 和发布产物分别判定；静态 grep 不替代行为验证。

## 结论

本轮已完成当前产品契约所要求的 P0/P1/P2 实现收口。实现层的结论为 `PASS`：General/Psychology 使用后端 Domain Pack 的 Mastery Profile；Native capability 入口统一执行 Feature、Plugin、Area、PermissionBroker、Domain scope 和 provider 边界；Tutor reload/replay 恢复同一 turn；Research 先确认计划并以同一快照执行；Concept Card、Concept Graph、Visualize、Career signal、Plugin lifecycle 和 Memory Graph 均有真实 Host/API/UI 路径。

发布层不能由本文件自行宣称通过。提交后的 exact SHA 必须重新运行普通 CI、Web E2E、Build Artifacts 及项目当前 release workflow；任何未运行或外部设备边界都保持 `NOT_RUN` / `NOT_EVALUATED`，不得继承历史 run 作为新 SHA 证据。

## 契约与实现矩阵

| 领域 | 当前实现与证据路径 | 状态 |
| --- | --- | --- |
| Native-only | `packages/native-execution-core` + `apps/api/pg_api/native_execution.py`；退休外部 Tutor 只保留历史文档 | PASS |
| Domain Pack | `/api/areas/current` 返回 `mastery_profile`；Learning 页面按返回 states 渲染，General 不读取 Psychology 专属状态 | PASS |
| 统一能力门 | `require_capability_operation` 统一 Feature → Plugin/Area → PermissionBroker；`resolve_native_context` 为 Native 操作入口 | PASS |
| 错误契约 | Feature、未安装/禁用 Plugin、Area capability、权限和 provider 错误保持 typed code；仅 provider unavailable/execution failure 允许显式降级 | PASS |
| 当前 schema | `init_db` 只接受 fresh `CURRENT_SCHEMA_VERSION`；不兼容数据库 fail-closed；backup/restore 校验同一 current schema 并保留 pre-restore 状态 | PASS |
| Host canonical truth | Host DB 持有 Source/Evidence/Claim/Practice/Mastery/Note/Writing/Book/Growth；Native 仅持 execution/checkpoint/auxiliary memory | PASS |
| Evidence boundary | retrieval candidate、AI summary、practice output 均不自动变成 Evidence/Mastery；Source、Claim、Content 保持人工核验/审核 | PASS |
| Tutor recovery | 持久化 turn/events；reload 后 replay events，恢复 pending input 与 running turn；resume/cancel 使用同一 turn | PASS |
| Plugin lifecycle | System 页面提供 install/enable/disable/update/rollback/uninstall；API 检查依赖/冲突，状态与数据保留；仅 trusted bundle | PASS |
| Research Plan | `/research/plan` 生成候选计划；ApprovalCard 编辑/确认；`approved_plan` 转为同一 native subtopic snapshot 执行 | PASS |
| Visualize | visual artifact manifest 结构化保存并由 `VisualExplanation` 显示节点、关系、注释和审核状态 | PASS |
| Concept Graph | Learning 页面使用真实 `/graph` 节点/边视图和类型过滤，不显示 JSON 替代品 | PASS |
| Concept Card | 创建/编辑名称、定义、例子、反例、易混淆项及 scoped Claim/Source selectors；API 再次检查 Area scope | PASS |
| Career | summary 返回 direction/confidence/basis/sample/ties signal，UI 显示依据与低置信度边界 | PASS |
| Memory Graph | Growth 页面分别显示 authoritative Growth Memory 与 read-only auxiliary graph；不把辅助记忆伪装成成长事实 | PASS |
| UI capability state | `/api/system/capability-state` 提供 Feature/Plugin/Area 状态；Learning/Research 对不可用操作显式禁用并保留错误信息 | PASS |
| KPI/social boundary | 未新增连续打卡、排行榜、用户画像 KPI 或自动社交发布 | PASS |

## 已执行的本地验证

以下命令在本轮实现后执行；`uv` 使用任务专属缓存目录以避免环境缓存权限干扰：

```text
web unit: 103 passed
web lint: PASS
Python compileall: PASS
targeted native/Host integration tests: PASS
```

全量 Python 测试必须在最终工作树再次执行。当前沙箱对 loopback listener 有权限限制时，相关失败只能标为 `BLOCKED`（环境限制），不能改写为产品 PASS/FAIL；应使用终端 Actions 的真实运行结果作为远程 gate 证据。

## 远程与发布证据边界

| Gate | 判定 |
| --- | --- |
| exact-SHA ordinary CI | 提交推送后重新运行；未取得新 SHA run 前为 NOT_RUN |
| exact-SHA Web E2E | 提交推送后重新运行；未取得新 SHA run 前为 NOT_RUN |
| exact-SHA Build Artifacts | 提交推送后重新运行；未取得新 SHA run 前为 NOT_RUN |
| Stable Candidate / Release | 不由历史版本或静态版本检查替代；当前 run 未闭环前为 NOT_EVALUATED |
| Windows/macOS/Android 真实设备与签名 | 取决于对应 Actions/设备产物；本地没有证据时为 NOT_EVALUATED |

最终交付必须补入：最终 exact SHA、每个新 run ID/结论、失败日志与修复轮次、是否创建 Candidate/Stable、产物校验结果，以及仍未覆盖的真实设备或公共 TLS 边界。
