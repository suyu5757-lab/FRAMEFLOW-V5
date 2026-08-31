# FRAMEFLOW V3 · Codex 全面整改与上线准备执行指令

> 适用对象：Codex  
> 项目：FRAMEFLOW V3 · AI VIDEO OS  
> 依据：`FRAMEFLOW V3 INITIAL AUDIT REPORT`  
> 当前审计结论：`NO-GO`  
> 当前 P0：0  
> 当前 P1：9  
> 本轮目标：完成 P1 清零并达到 `RE-AUDIT READY`

---

# 0. 你的角色

你现在不是代码建议助手，而是 **FRAMEFLOW V3 的 Principal Engineer + QA Lead + Release Engineer**。

你的任务是：

> 根据当前 FRAMEFLOW V3 审计结果，对现有代码库实施一轮以“生产安全、数据权威、完整工作流、性能和上线可靠性”为目标的系统性整改。

本轮工作不是重新设计产品，也不是进行表面 UI 美化。

核心目标只有一个：

# 将 FRAMEFLOW V3 从当前 `NO-GO` 状态推进到可重新执行正式上线审计的状态。

---

# 1. 当前已确认状态

当前审计结果：

- Final Decision：`NO-GO`
- P0：0
- P1：9
- 总评分：41/100
- 当前版本不得进入真实影视项目正式生产。

已经通过：

- Python regression：83/83 PASS
- Vitest：32/32 PASS
- TypeScript + Vite Production Build：PASS
- Playwright Chromium：8/8 PASS
- npm audit：0 vulnerability
- pip check：PASS
- FFmpeg / FFprobe：基本可用
- SQLite：WAL
- 基础 XSS / Credential masking / upload validation：基本通过

因此：

**不要重新实现已经稳定的基础能力。**

整改重点必须集中在审计失败项。

---

# 2. 最高执行原则

## 2.1 优先级

严格按照以下顺序执行：

```text
数据安全
→ 生产 Gate
→ Prompt Authority
→ Generation 幂等
→ 数据库/媒体一致性
→ Recovery
→ 人工生产闭环
→ Reference Authority
→ 性能
→ P2
→ P3
→ 全量 Regression
→ Release Audit
```

禁止为了重构、美化或者代码洁癖，延迟 P1 修复。

原则：

```text
Correctness
> Data Safety
> Production Authority
> Recoverability
> Performance
> UX
> Refactoring
```

---

# 3. 修改代码前必须执行

首先检查：

```text
git status
git branch
当前数据库路径
项目媒体目录
当前 migration version
Python test 状态
Vitest 状态
Playwright 状态
Production build 状态
```

建立：

```text
FRAMEFLOW_REMEDIATION_PROGRESS.md
```

记录所有整改项目：

```text
ID
Severity
Problem
Root Cause
Files
Fix Plan
Status
Tests
Regression Result
Remaining Risk
```

状态只允许：

```text
TODO
IN_PROGRESS
FIXED
VERIFIED
BLOCKED
DEFERRED
```

第一轮只做结构分析、风险确认和整改 Ledger，随后立即开始 P1 修复。

---

# 4. 正式数据保护

这是绝对要求。

在任何数据库 migration、恢复机制或者数据修复发生以前：

1. 备份正式 SQLite DB；
2. 执行 WAL checkpoint；
3. 输出数据库 SHA256；
4. 输出项目媒体目录 manifest；
5. 不自动删除任何 orphan directory；
6. 不自动修复未知正式项目；
7. Recovery 默认 `dry-run`；
8. 所有 destructive operation 必须具有明确 preview。

特别保护：

```text
PRJ_F3843DF0760F
PRJ_32B543F4B566
```

不得因为整改过程而删除、覆盖或者错误登记其媒体。

测试优先使用：

```text
独立临时 DB
临时 project
临时 media directory
synthetic test assets
```

禁止在正式数据库中执行破坏性测试。

---

# 5. PHASE 1 —— 修复最终生产 Gate

对应：

```text
FF-P1-001
```

这是整个整改的最高优先级。

当前严重漏洞：

```text
Pending / generated_pending_qa artifact
↓
Shot directorApproved=true
↓
Timeline
↓
Preflight
↓
Render
↓
Delivery
```

未经正式 QA 和登记的素材可以最终生成交付物。

必须建立唯一服务端：

```text
production_artifact_gate()
```

或语义等价的统一服务。

它必须验证：

```text
artifact 存在
artifact 属于当前 project
physical file 存在
hash 有效
QA decision == Approved
asset version 已 registered
asset version == active version
logical asset 状态允许生产
artifact 未 superseded
artifact 未 revoked
```

禁止依赖：

```text
shot.status
directorApproved
generated_pending_qa
前端状态
客户端提交的 ready 字段
```

作为最终权威。

## Gate 必须覆盖全部入口

至少覆盖：

```text
Timeline Assemble
Timeline Preflight
Preview Render
Render Estimate
Render Create
Render Approve
Render Worker Start
Final Delivery
Delivery Package
```

必须遵循：

> 越靠近最终输出，越必须重新验证 Gate。

不能因为前一个接口检查过，Worker 就默认安全。

## 强制 Regression

新增：

```text
pending artifact -> approved shot -> assemble
```

必须：

```text
409
```

新增：

```text
pending artifact -> render estimate
pending artifact -> render create
pending artifact -> render approve
pending artifact -> worker
```

全部必须失败。

新增：

```text
unregistered artifact
superseded artifact
wrong project artifact
missing physical file
hash mismatch
```

全部必须阻断。

必须修复：

```text
delivery_set=single
```

绕过 preflight blocking 的可能性。

---

# 6. PHASE 2 —— 建立 Prompt 唯一权威

对应：

```text
FF-P1-002
FF-P1-003
```

必须建立规则：

# 每一个 Logical Asset 在任意时刻最多只能存在一个 Current Approved Prompt。

状态建议至少明确：

```text
draft
pending_qa
approved
superseded
rejected
```

当：

```text
Prompt v02 -> Approved
```

同一事务内必须执行：

```text
v02 = current-approved
v01 = superseded
```

数据库层必须尽量提供约束。

不要仅依赖业务代码。

---

# 7. Generation 不允许信任客户端 Prompt 正文

当前存在风险：

```text
prompt_version = approved version
prompt = 被篡改正文
```

服务端仍可能采用客户端正文。

这是不可接受的。

修改为：

客户端最多提交：

```text
prompt_version_id
```

服务端必须：

```text
SELECT approved prompt version
↓
读取 canonical prompt body
↓
计算 hash
↓
生成 frozen generation snapshot
↓
送 Provider
```

客户端提交的 Prompt 正文不得成为生产权威。

Generation snapshot 至少保存：

```text
prompt_version_id
prompt_hash
prompt_body snapshot
reference snapshot
provider
model
parameters
timestamp
project_id
asset_id
```

Regression：

```text
Approved Prompt ID + tampered prompt body
```

必须：

```text
409
```

或者服务端完全忽略 tampered body，并通过测试证明真正送往 Provider 的仍是 Approved canonical body。

---

# 8. PHASE 3 —— Generation / Render 幂等

对应：

```text
FF-P1-004
```

设计：

```text
idempotency_fingerprint
```

至少包含：

```text
project_id
graph_revision
selected_nodes
generation_parameters
prompt_version
reference_snapshot
actor
operation_type
```

canonical serialization 后计算 hash。

数据库建立唯一约束或等价强保证。

对于相同：

```text
project
revision
nodes
parameters
```

在任务：

```text
queued
awaiting_confirmation
running
```

期间再次请求：

不得建立第二个 Run。

必须返回已有：

```text
run_id
```

同时：

- Approval token 一次性使用；
- Confirm 重复请求不得重复扣费；
- Worker 重启不得重复执行完成任务；
- Render Create 同样考虑幂等。

Regression：

并发 Generate ×10。

预期：

```text
1 unique run_id
1 approval gate
1 billable execution
```

---

# 9. PHASE 4 —— 修复 Data Audit 假绿灯

对应：

```text
FF-P1-006
```

当前已经发现：

```text
storage integrity = false
system data-audit = true
```

这种情况以后绝对禁止出现。

建立统一：

```text
data_integrity_service
```

检查：

```text
DB project -> project directory
project directory -> DB project
artifact DB row -> physical file
physical file -> registered artifact
asset_version -> artifact
QA -> artifact/version
reference -> project/asset/artifact
lineage -> existing objects
```

最终：

```text
system data-audit ok
```

必须涵盖：

```text
missing_project_directory
unregistered_project_directory
orphan artifact
missing media
broken ownership
hash mismatch
invalid active version
```

任意 Critical integrity error：

```text
ok=false
```

---

# 10. 项目创建必须原子化

新建 Project 必须同时保证：

```text
DB Project row
+
Project media directory
```

要么一起成功，要么一起 rollback。

不得再出现：

```text
有 DB 项目但没有目录
```

为此需要新增对应测试。

---

# 11. PHASE 5 —— Backup / Export / Import / Recovery

对应：

```text
FF-P1-007
```

实现 V3 原生能力，不恢复旧 V1/V2 API。

至少建立语义等价的 V3 能力：

```text
backup
export
recovery preview
recovery apply
```

具体 API URL 根据现有 V3 architecture 决定。

## Backup

包括：

```text
SQLite backup
WAL checkpoint
media manifest
hash manifest
schema version
project metadata
timestamp
```

## Export

导出必须可验证。

manifest 至少包含：

```text
project_id
schema_version
artifacts
asset_versions
QA
prompt versions
references
lineage
timeline
graphs
file paths
file hashes
MIME
sizes
```

## Recovery

必须采用：

```text
SCAN
↓
PREVIEW
↓
CONFLICT REPORT
↓
DRY RUN
↓
APPLY
↓
VERIFY
```

绝对不要：

```text
发现 orphan directory
→ 自动 import
```

必须先提供只读恢复预览。

---

# 12. PHASE 6 —— 无 Provider 环境下完整人工工作流

对应：

```text
FF-P1-005
```

必须让一个完全没有 AI Provider 的用户通过 UI 完成：

```text
Project
↓
Story
↓
Scene
↓
Shot
↓
Logical Asset
↓
Artifact Upload
↓
QA
↓
Register
↓
Timeline
↓
Render
```

## Story / Shot UI

实现：

```text
Add Shot
Duplicate Shot
Delete Shot
Reorder Shot
Split Shot
```

Shot ID 必须保持稳定。

删除：

```text
SH002
```

不能造成：

```text
SH003 -> SH002
```

## Asset UI

至少允许创建：

```text
Character
Scene
Prop
Fusion
Audio
```

如现有模型支持，再加入：

```text
Camera
Environment
Reference
```

至少实现：

```text
Create
Edit
Duplicate
Archive/Delete
Upload Candidate
QA
Register
Return
Retry
```

AI 只是效率工具。

**AI 不得是建立项目生产数据的唯一入口。**

---

# 13. PHASE 7 —— Reference Authority

对应：

```text
FF-P1-008
```

扩展现有 reference model。

至少新增：

```text
priority
scope
authority
conflict_group
effective_version
```

## priority

```text
1
2
3
...
```

决定 Prompt Packaging 顺序。

## scope

例如：

```text
identity
face
costume
pose
camera
lighting
environment
geometry
material
composition
```

## authority

建议：

```text
absolute
primary
secondary
supporting
negative
```

## conflict_group

描述多个 Reference 控制同一个属性时的冲突关系。

## effective_version

保证历史 generation 能知道：

> 当时真正使用的是哪一个 Reference Version。

---

# 14. Reference Frozen Snapshot

每一次 Generation 必须冻结：

```text
reference_id
artifact/version
priority
scope
authority
conflict_group
hash
order
```

历史生成不得因为后来修改 Reference 而失去可重现性。

---

# 15. PHASE 8 —— 性能整改

对应：

```text
FF-P1-009
```

目标规模：

```text
1000 assets
300 shots
```

当前已知问题：

```text
Asset Library API ≈ 9s
Dashboard API ≈ 8.9s
UI Asset Library ≈ 46s
```

整改目标：

```text
Asset Library API p95 < 1s
Dashboard API p95 < 1s
UI usable < 3s
```

## Backend

禁止：

```text
Dashboard endpoint
→ load entire Asset Library
→ Python full aggregation
```

改成：

```text
SQL COUNT
SQL GROUP BY
indexed projection
summary query
pagination
```

检查并建立合理索引。

重点检查：

```text
project_id
asset_id
artifact_id
status
qa_decision
asset_type
created_at
updated_at
active_version
shot_id
```

不要盲目创建索引。

使用：

```text
EXPLAIN QUERY PLAN
```

验证。

## Asset Library

实现 server-side：

```text
pagination
filter
search
sorting
```

例如：

```text
?page=
&page_size=
&type=
&status=
&q=
&sort=
```

不要一次返回 1000+ 完整对象。

## Frontend

Asset Library 必须使用：

```text
virtualization / windowing
```

禁止：

```text
1000 assets
→ 1000 DOM rows 全部 mount
```

React Flow 同样评估：

```text
visible node rendering
lazy loading
group collapse
viewport culling
```

## Dashboard 请求去重

解决页面切换时重复 Dashboard GET。

至少采用：

```text
request cache
AbortController
request deduplication
ETag / revision cache
```

选择适合当前 architecture 的实现。

---

# 16. PHASE 9 —— P2 问题

所有 P1 完成后继续。

## 16.1 Database FK

针对：

```text
artifacts
asset_versions
prompt_versions
QA
reference
lineage
```

评估并增加真正的数据库：

```text
FOREIGN KEY
UNIQUE
CHECK
```

不要只依赖应用逻辑。

Migration 必须：

```text
backward safe
backup first
validate existing data
report conflicts
```

---

## 16.2 Security

虽然当前是：

```text
127.0.0.1
single-user
```

仍增加合理的：

```text
TrustedHost
Origin validation
CSRF strategy if applicable
Content-Security-Policy
X-Content-Type-Options
frame-ancestors / X-Frame-Options
Referrer-Policy
```

不要为了安全整改破坏本地 Provider 和媒体预览。

---

## 16.3 Upload

禁止：

```python
await file.read(MAX_UPLOAD + 1)
```

处理最大 1GB 上传。

修改成：

```text
streamed upload
chunk size limit
running size counter
hash streaming
temporary file
atomic move
```

超过限制立即停止。

---

## 16.4 Audit Trail

统一：

```text
actor
reason
before
after
timestamp
entity
operation
```

不要继续把：

```text
studio-user
```

当真正 actor。

单用户模式可以使用：

```text
local-user
```

但 schema 应支持未来身份系统。

---

## 16.5 Accessibility

修复：

```text
hidden Drawer focusable elements
low contrast
missing id/name
keyboard focus
aria
```

目标：

```text
Lighthouse Accessibility >= 95
```

尽量达到：

```text
100
```

---

# 17. PHASE 10 —— Camera / Scene Spatial Authority

当前 Camera Board 属于缺失能力。

不要在 P1 修完前做大型 Camera 系统。

P1 清零以后，建立最小正式模型：

```text
Camera
Camera Panel
Scene Spatial Authority
```

Camera 至少包含：

```text
camera_id
scene_id
position
orientation
lens
height
movement
screen_direction
shot_size
version
QA status
```

Scene Spatial Authority 至少支持：

```text
orientation
entrances/exits
action zones
landmarks
screen direction
relative positions
```

必须支持：

```text
version
QA
```

不要把这些数据永远只放在 Prompt 文本中。

---

# 18. PHASE 11 —— P3

## Path Traversal

编码路径穿越：

不能：

```text
ValueError -> 500
```

应：

```text
400 / 403 / 404
```

并且不能泄露服务器路径。

## favicon

补充 favicon 或停止无效请求。

## Duplicate Project Name

可以选择：

```text
A. 禁止重名
```

或者：

```text
B. 明确允许，但 UI 显示提示并强化 ID/metadata 区分
```

不要继续静默创建。

---

# 19. 代码结构整改原则

当前：

```text
server.py ≈ 5072 lines
App.tsx ≈ 4536 lines
```

不要在本轮一开始大规模重写。

采用：

```text
Fix while extracting
```

当修改某一领域时再逐步抽离。

Backend 建议逐渐形成：

```text
services/
    production_gate.py
    prompt_authority.py
    data_integrity.py
    recovery.py
    generation.py

repositories/
routers/
schemas/
```

Frontend 建议逐渐形成：

```text
features/
    story/
    assets/
    timeline/
    provider/
    project/
```

禁止为了减少文件行数进行纯机械拆文件。

---

# 20. 每完成一个 Phase 的固定流程

严格执行：

```text
1. 修改代码
2. 新增 regression test
3. 运行相关单元测试
4. 运行 integration test
5. 更新 remediation ledger
6. 检查 git diff
7. 检查数据库 migration
8. 检查 backward compatibility
```

如果存在 Git：

建议每一个逻辑 Phase 使用独立 commit，例如：

```text
fix: enforce production artifact gate
fix: enforce single approved prompt authority
fix: add generation idempotency
fix: unify storage data audit
feat: add v3 project recovery
feat: enable manual shot and asset workflow
feat: add reference authority model
perf: virtualize asset library and optimize dashboard
```

不要 rewrite Git history。

---

# 21. 最终自动化验收

以下全部必须新增或验证。

## 21.1 Gate

```text
pending artifact
-> approved shot
-> assemble
= BLOCKED
```

```text
pending artifact
-> preflight
= BLOCKED
```

```text
pending artifact
-> render estimate
= BLOCKED
```

```text
pending artifact
-> render create
= BLOCKED
```

```text
pending artifact
-> render approve
= BLOCKED
```

```text
pending artifact
-> worker
= BLOCKED
```

## 21.2 Prompt

```text
Prompt v1 Approved
Prompt v2 Approved
```

结果：

```text
v1 = superseded
v2 = current approved
```

数据库中：

```text
current-approved <= 1
```

## 21.3 Prompt Tampering

```text
approved prompt_version
+
modified body
```

不得执行修改后的正文。

## 21.4 Idempotency

```text
Generate ×10 concurrent
```

结果：

```text
1 run ID
```

## 21.5 Data Audit

制造：

```text
missing project directory
```

结果：

```text
data-audit ok=false
```

制造：

```text
unregistered project directory
```

结果：

```text
data-audit ok=false
```

## 21.6 Manual Workflow

关闭所有 Provider。

新建项目。

必须可以纯人工完成：

```text
Project
→ Story
→ Scene
→ Shot
→ Asset
→ Upload
→ QA
→ Register
→ Timeline
```

## 21.7 Performance

数据：

```text
1000 assets
300 shots
```

要求：

```text
Asset Library API p95 < 1s
Dashboard API p95 < 1s
UI usable < 3s
```

并验证：

```text
DOM 数量不随 asset 总量近似线性增长
```

---

# 22. 全量最终 Regression

P1 清零后必须执行：

```text
Python tests
Vitest
TypeScript
Production build
Playwright
Chrome smoke
Edge smoke
npm audit
pip check
```

如果可以安全安装：

```text
pip-audit
```

继续执行 Python dependency vulnerability scan。

如果环境无法安装：

标记：

```text
BLOCKED_ENVIRONMENT
```

不要伪造 PASS。

---

# 23. Provider 验收原则

当前：

```text
orchestrator
image
vision
TTS
music
SFX
```

存在未就绪项。

代码整改完成后：

1. 检查 Provider configuration；
2. 检查 capability bindings；
3. 检查 health；
4. 检查 credential masking；
5. 检查 error handling。

未经授权：

**不要主动执行真实付费 Generation。**

付费 Provider 测试属于最终 Release Acceptance 阶段。

---

# 24. 禁止行为

整个整改期间禁止：

```text
删除正式媒体
自动修复未知 orphan project
偷偷降低 QA 标准
把 Pending 改名成 Ready
只在前端增加 disabled button 代替服务端 Gate
删除 failing tests 让 CI 变绿
跳过数据库 migration
将所有异常 catch 后返回 200
为通过性能测试减少测试数据
mock FFmpeg 后宣称真实 Render PASS
mock Provider 后宣称 Provider PASS
```

尤其禁止：

> 修复 UI 表象，而不修复服务端生产权威。

---

# 25. 遇到问题时如何工作

不要因为某个模块受阻而停止整个整改。

如果某任务无法继续：

```text
标记 BLOCKED
记录原因
记录需要的依赖
继续执行其他独立任务
```

例如 Provider 不可用：

不要停止。

继续完成：

```text
Gate
Prompt
Database
Recovery
Manual Workflow
Reference
Performance
Regression
```

---

# 26. 每个阶段必须汇报

每完成一个 Phase，输出：

```markdown
## PHASE X RESULT

### Fixed
- ...

### Files Changed
- ...

### Database Changes
- ...

### Tests Added
- ...

### Tests Passed
- ...

### Remaining Risks
- ...

### Status
VERIFIED / BLOCKED
```

不要只告诉用户：

> 已修复。

必须提供验证证据。

---

# 27. 最终交付物

整改完成后生成：

```text
FRAMEFLOW_REMEDIATION_PROGRESS.md
FRAMEFLOW_REMEDIATION_REPORT.md
FRAMEFLOW_RELEASE_CHECKLIST.md
FRAMEFLOW_DATA_MIGRATION_REPORT.md
FRAMEFLOW_PERFORMANCE_REPORT.md
```

---

# 28. 最终状态判定

最终重新统计：

```text
P0
P1
P2
P3
```

只有：

```text
P0 = 0
P1 = 0
```

才能进入：

```text
RE-AUDIT READY
```

不要自行宣称：

```text
GO
```

因为正式 GO 必须经过第二轮独立审计。

最终只允许：

```text
RE-AUDIT READY
```

或者：

```text
NOT READY
```

---

# 29. 执行起点

现在开始执行。

第一步不要直接修改代码。

首先完成：

```text
1. 阅读现有代码结构
2. 将 9 个 P1 映射到具体代码路径
3. 检查现有测试覆盖
4. 检查 Git 状态
5. 检查数据库 migration
6. 创建整改 Ledger
7. 创建正式数据安全快照
```

然后立即从：

# FF-P1-001 Production Artifact Gate

开始整改。

不要先处理：

```text
favicon
CSS
颜色
页面装饰
大型代码拆分
低优先级重构
```

---

# 30. Codex 自主工作规则

你需要尽可能自主完成工作，不要在每一个普通工程决策上向用户提问。

可以自主决定：

- 文件拆分方式；
- service/repository/router 的具体组织；
- 数据库索引方案；
- 测试 fixture；
- API 内部实现；
- React 组件拆分；
- 性能优化技术选型；
- 非破坏性的 migration 实现细节。

但以下情况不得自行越权：

- 删除或重写正式媒体；
- 对未知 orphan data 自动做 destructive recovery；
- 使用真实付费 Provider；
- 重写 Git history；
- 删除重要正式项目；
- 通过降低 QA 标准让测试通过。

如果遇到需要用户授权的操作：

1. 标记 `BLOCKED_USER_APPROVAL`；
2. 继续执行其他不依赖该授权的任务；
3. 在阶段报告中说明。

不要因为一个受阻事项停止整个整改。

---

# 31. 最终目标

最终目标不是：

> 代码看起来更漂亮。

而是：

# FRAMEFLOW V3 不允许任何未经 QA、未经登记、非当前权威版本的素材进入最终影视交付。

并且系统必须做到：

```text
生产规则有唯一权威
Prompt 可追溯
Reference 可冻结
Generation 幂等
数据库与媒体一致
项目可备份和恢复
无 AI Provider 时仍可人工生产
大规模项目仍保持可用
全部关键行为有 Regression Test
```

完成后，等待第二轮独立审计重新判定是否可以从：

```text
RE-AUDIT READY
```

升级为：

```text
CONDITIONAL GO
```

或：

```text
GO
```

---

# 32. 可直接发送给 Codex 的启动指令

将下面这段话与本文件一起发送给 Codex：

```text
请读取并严格执行项目中的《FRAMEFLOW_V3_CODEX_REMEDIATION_EXECUTION_PLAN.md》。

这不是一次普通的代码优化任务，而是一次基于正式审计结果的上线阻断整改。

请先不要直接大规模重构，也不要先处理 UI 美化、favicon、CSS 或低优先级问题。

第一步先完成：
1. 检查 Git、数据库、migration、正式媒体目录和现有测试状态；
2. 建立 FRAMEFLOW_REMEDIATION_PROGRESS.md；
3. 为正式 SQLite 数据库和媒体目录建立安全快照/manifest；
4. 将审计中的 9 个 P1 映射到具体代码位置和测试；
5. 输出初始整改 Ledger。

完成上述准备后，立即从 FF-P1-001 Production Artifact Gate 开始执行。

整个整改必须严格遵循：
Data Safety > Production Authority > Recoverability > Performance > UX > Refactoring。

每完成一个 Phase，必须运行对应 regression tests，并更新整改报告。不要只修改代码而不验证。

未经我的明确授权，不得：
- 删除正式媒体；
- 自动修复未知 orphan project；
- 调用真实付费 Provider；
- 重写 Git history；
- 降低 QA 标准以让测试通过。

如果某一步因环境或授权阻塞，记录 BLOCKED 并继续处理其他独立任务，不要停止整个整改。

最终只有在 P0=0、P1=0 且关键自动化验收通过后，才允许将状态标记为 RE-AUDIT READY；不得自行宣布 GO。

现在开始执行。
```
