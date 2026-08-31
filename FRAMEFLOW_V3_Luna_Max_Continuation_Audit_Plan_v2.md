# FRAMEFLOW V3 · AI VIDEO OS
# 下一阶段审计整改与接续执行任务书
## 执行模型：GPT-5.6 Luna Max
## 工作台：`http://127.0.0.1:8787/`
## 当前主阶段：Phase 9.2 → Phase 9.3
## 文档类型：Continuation / Verification / Re-Audit Preparation

---

# 0. 文档目的

本文件不是从零开始的开发计划。

这是 FRAMEFLOW V3 在已经完成大量 P0/P1/P2 整改后的**接续执行任务书**。

你需要继承现有成果，在不重复已完成工作的前提下：

1. 以正式审计记录为第一事实源；
2. 以当前代码和测试为第二事实源；
3. 以正在运行的工作台 `http://127.0.0.1:8787/` 的真实行为为第三事实源；
4. 先确认当前系统究竟已经完成到什么程度；
5. 只对“审计要求、代码实现、测试结果、工作台行为”之间仍存在的不一致进行修复；
6. 优先完成 `FF-P2-011` 的真实验证闭环；
7. 然后重新盘点剩余 P2；
8. 不重复处理已经 VERIFIED 的项目；
9. 不因单项通过而提前声明 `RE-AUDIT READY` 或 `GO`。

核心目标：

> **减少返工、保护已经通过的整改结果、补齐尚未运行验证的部分，并把 FRAMEFLOW V3 稳定推进到下一审计阶段。**

---

# 1. 当前工作台地址

当前实际工作台：

```text
FRAMEFLOW V3 · AI VIDEO OS
http://127.0.0.1:8787/
```

执行 Agent 位于用户本地开发环境时，应将这个正在运行的工作台视为**Live Runtime Baseline**。

注意：

> 不允许仅根据源代码推测工作台状态。

如果工作台能够打开，应实际检查：

```text
页面是否能启动
Dashboard 是否正常
项目是否能加载
Asset Library 是否正常
核心导航是否正常
浏览器 console 是否存在错误
关键 API 是否返回异常
核心操作是否产生正确持久化结果
```

但是：

> 不要为了“完整测试所有功能”而重新做一轮无边界的全面 QA。

本轮 Live Workbench 检查只服务于：

```text
FF-P2-011 verification
+
已完成整改的非回归确认
+
剩余 P2 盘点
```

---

# 2. 当前已经完成的情况

以下内容视为本轮任务开始时的已知事实。

---

## 2.1 Severity 状态

```text
P0 = 0
P1 = 0
```

当前 P0/P1 已全部清零。

因此：

### 不要重新开启 P0/P1 整改

除非本轮实际测试发现：

```text
新的 P0/P1 regression
```

否则不得重新做已经 VERIFIED 的 P0/P1 项目。

---

# 3. 已完成：`FF-P1-009`

状态：

```text
FF-P1-009 = VERIFIED
```

该 finding 是 FRAMEFLOW V3 的性能整改项。

---

## 3.1 原始审计性能基线

| Measure | Audit baseline |
|---|---:|
| Asset Library API | 9,012 ms |
| Dashboard API | 8,851 ms |
| Asset Library UI | about 46 s / 1,000 mounted items |

---

## 3.2 已完成整改

现有报告确认已经完成：

- 将 per-asset relation / Prompt reads 替换为 bounded batch projections；
- 将完整 hash integrity 移至显式 `/integrity` 请求；
- 普通 Asset Library 读取不再伪装成完整 integrity audit；
- 增加 server query contract：

```text
page
page_size
q
asset_type
status
sort
```

- 增加 v13 / v14 project projection indexes；
- 使用 `EXPLAIN QUERY PLAN` 验证 query/index 行为；
- 增加 `VirtualAssetList`；
- 1,000 item 场景下 rendered slice `< 30 rows`。

---

## 3.3 已验证性能结果

| Measure | Verified result | Threshold |
|---|---:|---:|
| Asset Library HTTP p95 | 76.10 ms | < 1,000 ms |
| Dashboard HTTP p95 | 107.57 ms | < 1,000 ms |
| Library response | 100 / 1,000 | server pagination |
| Virtual list window | < 30 rows | non-linear DOM growth |

已有历史证据：

```text
tests/test_v3_performance.py
web/src/components/VirtualAssetList.test.ts

Python: 110/110 PASS
Vitest: 33/33 PASS
```

---

## 3.4 本轮对 `FF-P1-009` 的处理规则

不要重新整改 `FF-P1-009`。

默认：

```text
FF-P1-009 = VERIFIED
```

只有以下情况才重新运行 performance regression：

```text
本轮修改了 Asset Library
本轮修改了 Dashboard data loading
本轮修改了 project projection
本轮修改了 asset relation loading
本轮修改了 integrity request path
本轮修改了 pagination/filter/search contract
本轮修改了 VirtualAssetList
本轮修改了公共 query middleware
```

如果本轮修改与这些模块无关：

```text
Do not repeat the full FF-P1-009 benchmark.
```

这条规则用于减少返工。

---

# 4. 已完成：Phase 9.1 / `FF-P2-010`

状态：

```text
FF-P2-010 = VERIFIED
```

已完成内容：

```text
Database FK / integrity constraints
```

即 Phase 9.1 已经完成。

---

## 4.1 本轮对 `FF-P2-010` 的处理规则

不要重新实现数据库 FK。

不要重新设计 schema。

不要重新开始 Phase 9.1。

本轮只需要在最后相关 regression 中确认：

```text
foreign_key_check
integrity_check
no orphan regression
migration remains valid
```

如果已有正式测试可以覆盖：

> 直接运行已有测试。

不要新增重复数据库机制。

---

# 5. 当前未闭环：`FF-P2-011`

当前状态：

```text
FF-P2-011
IMPLEMENTATION = WRITTEN
REGRESSION TESTS = WRITTEN
RUNTIME VERIFICATION = NOT YET EXECUTED
STATUS = NOT VERIFIED
```

这是当前下一步的第一优先级。

---

# 6. 当前全局状态

任务开始时必须锁定为：

```text
FRAMEFLOW V3 STATUS

P0 = 0
P1 = 0

FF-P1-009 = VERIFIED
FF-P2-010 = VERIFIED
FF-P2-011 = IMPLEMENTED / NOT VERIFIED

GLOBAL STATUS = NOT READY

RE-AUDIT READY = NO
GO = NO
```

禁止为了显示进度将其提前升级。

---

# 7. 为什么本轮计划要与之前不同

FRAMEFLOW V3 已经不是早期整改阶段。

之前适合的方式是：

```text
Finding
→ Fix
→ Test
```

现在继续使用这种模式容易产生：

```text
重复修改已经正确的代码
重复增加测试
重复跑昂贵 benchmark
为了“完成任务”制造无意义 diff
破坏已经 VERIFIED 的模块
引入新 regression
```

因此从本轮开始改为：

```text
AUDIT FACT
    ↓
CURRENT CODE
    ↓
CURRENT TEST
    ↓
LIVE WORKBENCH
    ↓
COMPARE
    ↓
ONLY FIX THE GAP
```

原则：

> **No discrepancy = No code change.**

---

# 8. 三层事实源

所有判断按照以下优先级执行。

---

## Source 1 — Authoritative Audit

查找：

```text
audit
audit report
finding
remediation
ledger
security review
re-audit
FF-P2-011
P2-011
```

这是：

```text
“系统应该满足什么”
```

的事实来源。

---

## Source 2 — Code + Tests

检查：

```text
当前实现
现有 regression
已有 integration tests
相关 API
DB constraints
frontend behavior
```

这是：

```text
“代码声称已经实现什么”
```

的事实来源。

---

## Source 3 — Live Workbench

打开：

```text
http://127.0.0.1:8787/
```

这是：

```text
“用户实际上现在得到什么”
```

的事实来源。

---

# 9. 三层一致性判定

---

## 情况 A

```text
Audit requirement
=
Current implementation
=
Tests
=
Live behavior
```

处理：

```text
NO CODE CHANGE
```

直接进入验证证据和 full regression。

---

## 情况 B

```text
Code correct
Tests PASS
Live workbench FAIL
```

说明可能存在：

```text
integration gap
runtime config gap
frontend/backend mismatch
uncovered path
stale build
state/persistence issue
```

此时不要继续给 unit test 加无意义 assertion。

优先排查真实运行路径。

---

## 情况 C

```text
Code appears correct
Tests FAIL
```

先判断：

```text
implementation bug
test bug
fixture issue
environment issue
```

不得默认改测试。

---

## 情况 D

```text
Tests PASS
but do not reproduce original finding
```

视为：

```text
INSUFFICIENT VERIFICATION
```

补最小 regression。

---

## 情况 E

```text
Live behavior correct
but no evidence / no regression
```

不能直接 VERIFIED。

需要把真实行为固化成测试证据。

---

# 10. 本轮目标调整

本轮不再要求 Luna Max 先做大量静态检查然后全面重测。

调整后的顺序：

```text
Stage A
接续基线确认

Stage B
定位 FF-P2-011 authoritative finding

Stage C
运行已有 FF-P2-011 tests

Stage D
只针对 finding 做 Live Workbench 验证

Stage E
如果存在 gap → 最小修复

Stage F
相关 regression

Stage G
full backend/frontend regression

Stage H
更新 ledger

Stage I
重新盘点剩余 P2
```

---

# 11. Stage A — 接续基线确认

首先确认当前 repo：

```bash
git status
git branch --show-current
git rev-parse HEAD
```

同时记录：

```text
repository root
branch
commit
dirty files
```

---

## 11.1 保护已有工作

如果存在 dirty files：

不要执行：

```bash
git reset --hard
git clean -fd
```

不要覆盖用户已有修改。

先分类：

```text
previous remediation
current uncommitted work
generated files
unrelated user work
```

---

# 12. Stage A.2 — 工作台启动状态确认

检查：

```text
http://127.0.0.1:8787/
```

目标不是测试全部功能。

只记录：

```text
Workbench reachable: YES/NO
Main shell renders: YES/NO
Fatal startup error: YES/NO
Visible critical console error: YES/NO
Visible critical network 5xx: YES/NO
```

---

## 12.1 如果工作台当前未运行

先根据项目现有启动方式启动。

不得为了启动而：

```text
升级框架
改依赖版本
重装整个项目
删除数据库
重建用户数据
```

---

# 13. Stage A.3 — 实际导航盘点

从正在运行的工作台识别当前实际存在的模块。

记录真实 UI，不要根据旧文档猜。

例如可能包括：

```text
Dashboard
Projects
Scenes
Shots
Assets
Asset Library
Prompts
Media
Providers
Generation
Settings
```

这里只记录**实际上存在的模块**。

如果名称不同，以当前工作台为准。

---

# 14. Stage A.4 — 建立 Workbench Snapshot

建议输出：

```text
Workbench Snapshot

URL:
Build/runtime:
Main navigation:
Project loaded:
Current database:
Provider status:
Visible errors:
Critical API errors:
```

如果能够通过浏览器 DevTools / network / local API 检查，则记录。

不要截获或输出秘密：

```text
API keys
tokens
passwords
credentials
```

---

# 15. Stage B — 定位 `FF-P2-011`

在仓库中查找：

```text
FF-P2-011
P2-011
```

优先查：

```text
audit ledger
formal audit
remediation plan
security report
re-audit document
```

---

# 16. 不允许猜 `FF-P2-011`

当前接续信息只能确认：

```text
安全边界代码已写
regression tests 已写
尚未运行验证
```

但并不能替代原始 finding。

因此必须从项目文件确认：

```text
Title
Original defect
Threat/risk
Affected component
Reproduction
Expected behavior
Acceptance criteria
```

找不到：

```text
FF-P2-011 = NOT VERIFIED
```

不得自行创造 finding。

---

# 17. Stage B.2 — Finding Contract

形成：

```text
FF-P2-011 FINDING CONTRACT

ID:
Title:
Severity:
Source:
Affected module:
Original defect:
Security boundary:
Reproduction:
Expected secure behavior:
Acceptance criteria:
Existing remediation:
Existing test:
```

只有这个 contract 建立后才进入验证。

---

# 18. Stage C — 先运行已有专项测试

这是减少返工的关键。

既然：

```text
P2-011 code 已写
P2-011 regression test 已写
```

第一动作不是重新审查整个安全架构。

而是：

> **直接运行已有 P2-011 targeted tests。**

记录：

```text
Exact command
Collected
Passed
Failed
Skipped
Exit code
Duration
```

---

# 19. Stage C Decision Tree

---

## C1 — Existing test PASS

不要立刻改代码。

继续：

```text
Verify test relevance
→ Live boundary verification
→ relevant regression
```

---

## C2 — Existing test FAIL

定位：

```text
implementation
fixture
environment
test assumption
```

做最小修复。

---

## C3 — Test cannot run

先解决最小环境问题。

不要：

```text
skip test
delete test
mark expected failure
```

除非正式 finding 明确允许。

---

# 20. Stage D — 只做 `FF-P2-011` 定向工作台验证

这一步非常重要。

不要进行无边界 UI QA。

根据 finding 所在模块，只打开相关路径。

---

## 示例

如果 finding 发生于：

```text
Asset Library
```

只验证相关 asset 行为。

如果发生于：

```text
Project isolation
```

只验证跨 project boundary。

如果发生于：

```text
filesystem
```

只验证对应导入/保存路径。

如果发生于：

```text
Provider
```

只验证 provider security boundary。

---

# 21. Live Verification 最低要求

必须验证：

## Negative Path

原始非法输入 / 风险路径：

```text
必须被拒绝
```

并确认：

```text
没有错误持久化
没有越权副作用
没有部分写入
没有异常数据残留
```

---

## Positive Path

对应合法操作：

```text
必须仍然正常工作
```

避免出现：

```text
security fix blocks valid workflow
```

---

# 22. 浏览器层检查

在执行相关操作时检查：

```text
browser console
network requests
HTTP status
API response
UI error state
```

重点关注：

```text
unexpected 500
uncaught exception
silent failure
incorrect success toast
frontend says success but backend failed
backend succeeds but UI remains stale
```

---

# 23. 不把环境能力缺失误判为应用 bug

如果某一操作依赖：

```text
外部 Provider
模型权重
第三方 API
GPU runtime
外部 credential
```

应区分：

```text
application defect
vs
environment capability unavailable
```

本轮安全 finding 的验证重点是：

```text
boundary behavior
validation
state integrity
error handling
```

而不是强行要求所有外部生成能力都可用。

如果环境能力不完整：

```text
记录 ENVIRONMENT LIMITATION
```

不要为了“跑通生成”随意改 Provider 或下载大型依赖。

---

# 24. Stage E — 只有出现真实 gap 才修改

允许修改代码的触发条件：

```text
targeted test FAIL
live workbench violates finding
test missing original attack case
positive path regression
persistent side effect exists
```

如果不存在这些情况：

```text
NO CODE CHANGE
```

---

# 25. 修复纪律

修复必须：

```text
minimal
finding-specific
testable
reversible
```

禁止：

```text
large refactor
new architecture
unrelated cleanup
dependency upgrade
UI redesign
schema redesign
```

除非原 finding 无法通过最小修复解决。

---

# 26. Stage F — 相关 Regression

不要每修改一行就跑完整 suite。

采用：

```text
targeted test
    ↓
related module regression
    ↓
stabilize
    ↓
full regression once
```

这样减少时间和无意义重复。

---

# 27. Related Regression 选择原则

只选择与代码改动直接相关的测试。

例如：

```text
security tests
asset tests
project tests
database tests
provider tests
media tests
workflow tests
```

不要全部无差别重复运行。

---

# 28. Stage G — Full Backend Regression

在 targeted + related regression 稳定后：

运行当前正式 Python suite。

历史结果：

```text
110/110 PASS
```

只能作为历史参考。

本轮必须记录真实新结果：

```text
Command
Total
Passed
Failed
Skipped
Duration
```

要求：

```text
Unexpected FAIL = 0
```

---

# 29. Stage G.2 — Full Frontend Regression

运行当前正式 frontend / Vitest suite。

历史结果：

```text
33/33 PASS
```

只能作为历史参考。

记录真实本轮：

```text
Files
Tests
Passed
Failed
Skipped
Duration
```

---

# 30. Build / Typecheck / Lint

如果项目本身已有：

```text
build
typecheck
lint
```

作为正式 gate：

运行。

如果不存在：

不要为了本任务新增 gate 或工具链。

---

# 31. DB 非回归

因为：

```text
FF-P2-010 = VERIFIED
```

最终相关 regression 至少确认已有 DB integrity gate 仍然通过。

使用项目已有方式。

可能包括：

```text
PRAGMA foreign_key_check
PRAGMA integrity_check
migration tests
orphan regression tests
```

不要重新设计 database integrity。

---

# 32. Performance 非回归优化

`FF-P1-009` 已 VERIFIED。

因此使用变更影响判断：

```text
IF P2-011 touched performance-sensitive path:
    run relevant performance regression
ELSE:
    do not repeat full performance audit
```

目标是减少返工。

---

# 33. 当前工作台 Smoke Test

在 `FF-P2-011` 完成后，可以做一轮非常短的 smoke test。

不是 full QA。

建议：

| Area | Check |
|---|---|
| App | 主界面正常打开 |
| Dashboard | 能正常显示，无 fatal error |
| Project | 当前项目可以打开 |
| Asset Library | 列表可以加载 |
| Search/Filter | 基础查询不出现 500 |
| Asset | 可以正常查看合法 asset |
| Persistence | 本轮相关合法写入可持久化 |
| Error handling | 非法操作有明确失败 |
| Console | 无新增 fatal error |

如果 P2-011 与某区域完全无关：

不需要深入测试该区域。

---

# 34. 不重新测试整个产品的原因

当前目标不是：

```text
重新对 FRAMEFLOW 做第一次 QA
```

而是：

```text
对已整改版本进行增量验证
```

因此：

### 已 VERIFIED + 未被修改

保留已有状态。

### 当前 finding 相关路径

深入验证。

### 被本轮 diff 影响的路径

做 regression。

### 其余路径

只做最小 smoke。

---

# 35. `FF-P2-011` VERIFIED Gate

只有满足：

```text
Authoritative finding located
+
Acceptance criteria confirmed
+
Existing remediation reviewed
+
Existing targeted regression executed
+
Original negative path verified
+
Valid positive path verified
+
Relevant regression PASS
+
Full backend PASS
+
Full frontend PASS
+
No unresolved contradictory evidence
+
Evidence report written
```

才可以：

```text
FF-P2-011 = VERIFIED
```

---

# 36. 如果所有已有实现第一次就 PASS

这是理想结果。

此时：

不要制造代码 diff。

流程：

```text
existing targeted test PASS
→ live boundary PASS
→ related regression PASS
→ full suites PASS
→ evidence
→ VERIFIED
```

并明确写：

```text
No additional remediation code was required.
The previously implemented fix was validated successfully.
```

这就是减少返工的正确方式。

---

# 37. 如果 targeted PASS，但 Live FAIL

这类情况优先级很高。

说明：

```text
test does not represent real runtime
or
integration path bypasses secure implementation
```

处理：

```text
reproduce
→ locate runtime path
→ minimal fix
→ add regression reproducing live failure
```

---

# 38. 如果 Live PASS，但 test FAIL

调查：

```text
fixture
old test assumption
stale API contract
test environment
```

只有能证明测试本身错误，才改测试。

---

# 39. 如果无法启动工作台

不要直接 BLOCKED。

先检查：

```text
existing dev command
backend process
frontend process
port 8787
runtime log
existing project docs
```

如果仍无法启动：

记录：

```text
WORKBENCH VERIFICATION = BLOCKED
```

并继续执行能够完成的：

```text
static review
targeted tests
related regression
```

但是如果 Live Runtime 是 finding acceptance 的必要条件：

```text
FF-P2-011 remains NOT VERIFIED
```

---

# 40. Phase 9.2 完成后的状态

如果 `FF-P2-011 = VERIFIED`：

仍然：

```text
GLOBAL STATUS = NOT READY
```

然后进入：

```text
P2 inventory reconciliation
```

---

# 41. Stage H — 更新 Audit Ledger

找到 authoritative ledger。

只更新真实完成项。

例如：

```text
FF-P2-011
Previous: IMPLEMENTED_NOT_VERIFIED
Current: VERIFIED
Evidence: ...
```

不要修改其他 finding 状态，除非本轮有直接证据。

---

# 42. Stage I — 剩余 P2 盘点

完成 P2-011 后：

全量扫描：

```text
FF-P2-*
```

建立：

| Finding | Title | Current state | Evidence | Next action |
|---|---|---|---|---|

状态统一使用：

```text
VERIFIED
IMPLEMENTED_NOT_VERIFIED
OPEN
BLOCKED
NOT_APPLICABLE
```

---

# 43. P2 盘点不等于继续全部修复

本轮 Phase 9.2 的任务边界：

```text
P2-011 close
+
P2 inventory
```

不要在没有必要时连续修改多个 finding。

---

# 44. 下一 Finding 排序原则

剩余 P2 优先级：

```text
1. Security / data integrity
2. Data loss / project corruption
3. Core workflow blocking
4. Cross-module correctness
5. Provider / media boundary
6. Lower-impact P2
```

如果 authoritative audit 已经规定顺序：

遵守 audit 顺序。

---

# 45. Phase 9.3 建议执行方式

接下来每个 P2 使用相同增量方式：

```text
READ
→ RUN EXISTING TEST
→ VERIFY LIVE
→ FIX GAP ONLY
→ REGRESSION
→ EVIDENCE
```

避免再次进入：

```text
全面重新审查整个仓库
```

---

# 46. P3 处理条件

只有：

```text
P0 = 0
P1 = 0
P2 = 0
```

再正式进入 P3。

---

# 47. P3 状态

允许：

```text
VERIFIED
ACCEPTED_DEBT
NOT_APPLICABLE
```

每种都必须有证据。

---

# 48. Final Release Candidate Regression

未来只有在所有 required findings 收口后才执行。

覆盖：

```text
Database
Security
Backend
Frontend
API
Asset Library
Performance
Project lifecycle
Shot / Scene workflow
Media
Provider boundary
Generation boundary
Persistence
Error handling
```

这才是全面测试阶段。

不是现在。

---

# 49. 工作台最终 RC 流程建议

最终 re-audit 前可以按实际工作台执行：

```text
Launch app
→ open/create project
→ load dashboard
→ use asset library
→ create/edit relevant workflow data
→ validate persistence
→ run valid provider/generation path where environment supports it
→ run failure path where provider unavailable
→ restart app
→ confirm persistence
→ run integrity
→ run full test suites
```

---

# 50. 状态机

严格使用：

```text
NOT READY
    ↓
FF-P2-011 VERIFIED
    ↓
Remaining P2 inventory
    ↓
P2 = 0
    ↓
P3 resolved / accepted
    ↓
Final RC regression PASS
    ↓
RE-AUDIT READY
    ↓
Independent Re-Audit
    ├── FAIL → NOT READY
    └── PASS → GO
```

---

# 51. 不允许的快捷状态

禁止：

```text
P2-011 PASS → GO
```

禁止：

```text
P0/P1 = 0 → READY
```

禁止：

```text
All tests green → GO
```

因为：

```text
test suite
≠
independent re-audit
```

---

# 52. Workbench Reality Overrides Assumptions

如果文档描述和当前工作台不一致：

先确认：

```text
是否是旧文档
是否是新实现
是否是 regression
```

不得盲目按照旧名称改当前系统。

例如：

```text
旧文档叫 Asset 页面
当前工作台已经合并为 Asset Library
```

先确认实际 contract。

---

# 53. 不要重新实现已经存在的功能

如果 Live Workbench 已经存在符合要求的：

```text
pagination
search
filter
virtualization
integrity
project isolation
error handling
```

不要再创建第二套实现。

优先：

```text
verify existing implementation
```

---

# 54. API Contract 保护

如果当前 API 已经被前端使用：

不要随意修改：

```text
request schema
response shape
route names
status codes
pagination contract
```

除非原 finding 要求。

任何必要 contract change 必须同步：

```text
backend
frontend
tests
```

---

# 55. Data Safety

不要：

```text
删除用户正式项目
清空当前数据库
重建工作区
清除媒体
改写正式资源
```

安全测试优先使用：

```text
isolated test DB
temporary project
temporary asset
test fixture
```

---

# 56. Live Test 数据隔离

在工作台进行验证时：

如果必须创建数据：

使用明确 test naming，例如：

```text
AUDIT_TEST_P2_011
SECURITY_TEST_TEMP
```

完成后按项目现有安全流程清理。

不要误删正式数据。

---

# 57. Provider / Generation 测试原则

当前任务核心不是验证所有模型实际生成质量。

如果 finding 与 Provider / Generation 有关：

优先检查：

```text
provider selection
parameter validation
credential boundary
request construction
error propagation
state transition
failed generation cleanup
```

实际模型输出只在 acceptance criteria 明确要求时成为 gate。

---

# 58. 浏览器错误分类

Live Workbench 检查到错误时分类：

```text
A. Current finding related
B. Existing unrelated defect
C. Environment issue
D. Expected controlled error
E. Dev-only warning
```

不要把所有 console warning 当审计失败。

---

# 59. Unexpected New Finding

如果执行过程中发现新的高严重度问题：

不要假装没看到。

记录：

```text
NEW FINDING CANDIDATE
```

包含：

```text
description
reproduction
impact
evidence
```

但不要未经正式审计流程随意重编号已有 finding。

---

# 60. 测试效率策略

为了减少重复：

## 每次小改后

只运行：

```text
targeted test
```

## 找到稳定修复后

运行：

```text
related regression
```

## finding 准备关闭时

运行：

```text
full backend
full frontend
```

## release candidate

才运行：

```text
full product regression
full performance
final audit
```

---

# 61. 日志与证据

不要粘贴巨大日志。

保存：

```text
exact command
exit code
pass/fail count
meaningful failure
relevant stack trace
```

完整日志可放文件。

---

# 62. 本轮建议报告路径

优先沿用项目现有 audit 目录。

如果已有：

```text
docs/audit/
```

可以创建：

```text
docs/audit/FF-P2-011-verification-report.md
```

如果已有其他规范：

遵循现有结构。

不要建立第二套 audit hierarchy。

---

# 63. 接续状态文件

建议同时维护一份非常短的 handoff，例如：

```text
CURRENT_AUDIT_STATUS.md
```

但：

> 只有项目当前不存在等效 authoritative status 文件时才考虑创建。

如果已经存在 ledger：

直接更新 ledger，不新建重复文件。

---

# 64. 报告必须包含“接续前状态”

最终 P2-011 报告开头：

```text
Before this execution:

P0 = 0
P1 = 0

FF-P1-009 = VERIFIED
FF-P2-010 = VERIFIED
FF-P2-011 = IMPLEMENTED / NOT VERIFIED

GLOBAL STATUS = NOT READY
```

这样下一位 Agent 不需要重新推断。

---

# 65. 报告必须包含“本轮完成内容”

例如：

```text
Completed in this execution:

- Located authoritative FF-P2-011 finding
- Executed existing regression
- Verified live negative path
- Verified live valid path
- Fixed ...
- Ran related regression
- Ran full backend
- Ran full frontend
- Updated audit ledger
```

---

# 66. 报告必须包含“未完成内容”

例如：

```text
Not completed:

- Remaining P2 findings
- P3
- Final RC regression
- Independent re-audit
```

这样避免下一轮重复问。

---

# 67. 报告必须包含“不要重复的项目”

明确：

```text
Do not redo:
FF-P1-009
FF-P2-010
```

除非相关路径发生 regression。

---

# 68. 最终 Verification Report 模板

## FRAMEFLOW V3 — FF-P2-011 Verification Report

### A. Handoff State

```text
P0:
P1:
FF-P1-009:
FF-P2-010:
FF-P2-011:
Global status:
```

### B. Repository Baseline

```text
Branch:
Commit:
Working tree:
Runtime:
```

### C. Live Workbench Baseline

```text
URL:
Reachable:
Main shell:
Relevant module:
Console:
Network:
```

### D. Original Finding

```text
Source:
ID:
Title:
Severity:
Risk:
Acceptance criteria:
```

### E. Existing Remediation

```text
Files:
Implementation:
Existing tests:
```

### F. First Targeted Test

```text
Command:
Result:
```

### G. Live Negative Path

```text
Action:
Expected:
Actual:
Persistent side effect:
Result:
```

### H. Live Positive Path

```text
Action:
Expected:
Actual:
Result:
```

### I. Changes

```text
No changes
```

或：

```text
Changed files:
Reason:
```

### J. Related Regression

```text
Command:
PASS:
FAIL:
```

### K. Full Backend

```text
Command:
PASS:
FAIL:
SKIP:
```

### L. Full Frontend

```text
Command:
PASS:
FAIL:
SKIP:
```

### M. DB Integrity

```text
PASS / FAIL / N/A
```

### N. Performance Non-Regression

```text
PASS / FAIL / NOT REQUIRED
```

### O. Finding Decision

```text
FF-P2-011 = ...
```

### P. Updated Inventory

```text
P0 =
P1 =
P2 =
P3 =
```

### Q. Remaining P2

| ID | Status | Next action |
|---|---|---|

### R. Global Decision

```text
GLOBAL STATUS = NOT READY
```

### S. Next Recommended Action

```text
...
```

---

# 69. 控制台最终回报

最终只需：

```text
FRAMEFLOW V3 — Phase 9.2 Result

Workbench:
- 127.0.0.1:8787 reachable: YES/NO
- Relevant workflow verified: YES/NO

FF-P2-011:
- Authoritative finding located: YES/NO
- Existing remediation reviewed: YES/NO
- Existing targeted test: PASS/FAIL
- Live negative path: PASS/FAIL/N/A
- Live positive path: PASS/FAIL/N/A
- Related regression: PASS/FAIL
- Full Python: PASS/FAIL
- Full frontend: PASS/FAIL
- DB integrity: PASS/FAIL/N/A
- Performance regression: PASS/FAIL/NOT REQUIRED

Final:
FF-P2-011 = ...

Current inventory:
P0 = ...
P1 = ...
P2 = ...
P3 = ...

GLOBAL STATUS = NOT READY

Files changed:
...

Evidence report:
...

Next:
...
```

---

# 70. Phase 9.2 Definition of Done

- [ ] 已确认 repo / branch / commit / dirty state
- [ ] 已打开或确认当前工作台状态
- [ ] 已记录实际相关 UI / runtime 路径
- [ ] 已找到 authoritative `FF-P2-011`
- [ ] 已建立 finding contract
- [ ] 已检查既有 remediation
- [ ] 已检查既有 regression
- [ ] 已首先运行既有 targeted tests
- [ ] 已验证真实 negative path
- [ ] 已验证真实 positive path
- [ ] 只有出现 gap 时才修改代码
- [ ] 新修改有 targeted regression
- [ ] related regression PASS
- [ ] full backend PASS
- [ ] full frontend PASS
- [ ] `FF-P2-010` DB integrity 无 regression
- [ ] `FF-P1-009` 性能相关路径无 regression（若适用）
- [ ] 已形成 verification report
- [ ] 已更新 audit ledger
- [ ] 已重新统计剩余 P2
- [ ] 未重新做已经 VERIFIED 的整改
- [ ] 未提前声明 `RE-AUDIT READY`
- [ ] 未提前声明 `GO`

---

# 71. 本轮明确禁止事项

禁止：

1. 从零重做所有审计。
2. 重新整改 `FF-P1-009`。
3. 重新实现 `FF-P2-010`。
4. 未执行测试就把 `FF-P2-011` 标记 VERIFIED。
5. 只看代码就宣布安全问题解决。
6. 用旧 PASS 结果代替本轮实际执行。
7. 修改测试降低要求。
8. 跳过 failing security test。
9. 为显示进度制造无意义代码 diff。
10. 大规模重构无关模块。
11. 随意升级依赖。
12. 清空数据库。
13. 删除用户正式项目。
14. 把 Provider/模型环境问题错误判断为 application failure。
15. 把所有 console warning 当 blocker。
16. 在 P2 未清零时宣布 `RE-AUDIT READY`。
17. 未经过 independent re-audit 就宣布 `GO`。

---

# 72. 当前接续摘要

在你开始执行前，必须理解以下事实：

```text
FRAMEFLOW V3 已经完成了主要 P1 整改。

P0 = 0
P1 = 0

FF-P1-009 Performance = VERIFIED

Phase 9.1:
FF-P2-010 Database FK / Integrity = VERIFIED

Phase 9.2:
FF-P2-011 Security Boundary
Implementation = DONE
Regression code = DONE
Execution verification = PENDING

GLOBAL STATUS = NOT READY
```

因此你现在不是来“重新开发”。

你是来：

```text
验证
→ 补 gap
→ 固化证据
→ 继续接续
```

---

# 73. 最优执行路径

严格优先：

```text
1. Read current repo state
2. Open current workbench
3. Locate FF-P2-011
4. Run existing FF-P2-011 tests
5. Compare with live behavior
6. If PASS → do not modify code
7. If gap → minimal fix
8. Run related regression
9. Run full suites
10. Update evidence
11. Mark FF-P2-011 only if justified
12. Inventory remaining P2
13. Stop and report
```

---

# 74. Fail-Closed 原则

如果证据不足：

```text
NOT VERIFIED
```

如果工作台行为与测试冲突：

```text
NOT VERIFIED
```

如果 finding 找不到：

```text
NOT VERIFIED
```

如果 full regression 存在无法解释的失败：

```text
NOT READY
```

原则：

> **宁可暂时保持 NOT READY，也不要制造未经证据支持的绿色状态。**

---

# 75. 成功标准

本轮成功并不要求一定产生代码修改。

最理想的执行结果甚至可能是：

```text
Existing P2-011 implementation is correct.
Existing regression tests pass.
Live workbench security boundary behaves correctly.
No code modification required.
Full regression passes.
FF-P2-011 can be upgraded to VERIFIED.
```

这说明上一轮整改有效，也最大程度避免了返工。

如果发现真实问题：

```text
精确修复
+
最小 regression
```

同样是成功。

---

# 76. 现在开始

不要重新写计划。

不要要求用户重复现状。

直接从：

```text
git status
git branch --show-current
git rev-parse HEAD
```

开始。

然后打开：

```text
http://127.0.0.1:8787/
```

完成 Live Workbench baseline。

随后定位：

```text
FF-P2-011
```

并按照本文件继续执行。

---

# FINAL STATE LOCK

开始执行时：

```text
P0 = 0
P1 = 0

FF-P1-009 = VERIFIED
FF-P2-010 = VERIFIED
FF-P2-011 = IMPLEMENTED / NOT VERIFIED

GLOBAL STATUS = NOT READY
RE-AUDIT READY = NO
GO = NO
```

所有状态升级必须有本轮实际运行证据支持。
