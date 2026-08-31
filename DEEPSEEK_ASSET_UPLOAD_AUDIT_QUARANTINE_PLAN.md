# FRAMEFLOW：资产上传、自动审计与不合格资产闭环执行计划

> 本文件可直接交给本地部署的 DeepSeek Agent 执行。
>
> DeepSeek 必须实际检查代码、完成实现、补充测试并进行浏览器验收，不得只输出分析或重新规划。
>
> 本计划与以下任务书配套：
>
> - `DEEPSEEK_COMMANDER_PLAN_JIEDU_UX_V2.md`
> - `DEEPSEEK_STORY_OPTIMIZATION_SHOT_ASSET_PLAN.md`

---

## 1. 项目路径与必读规则

项目根目录：

```text
D:\11067\Codex\2026-08-13\video-2
```

开始修改前完整阅读：

```text
D:\11067\CodexHome\skills\video-asset-regulator\SKILL.md
D:\11067\CodexHome\skills\video-asset-regulator\references\video-production-handoff-contract.md
D:\11067\Codex\2026-08-13\video-2\asset-workspace.js
D:\11067\Codex\2026-08-13\video-2\workflow-state.js
D:\11067\Codex\2026-08-13\video-2\server.py
D:\11067\Codex\2026-08-13\video-2\frameflow\database.py
D:\11067\Codex\2026-08-13\video-2\frameflow\schemas.py
D:\11067\Codex\2026-08-13\video-2\frameflow\workflows.py
```

### 严格限制

- 不得批量或递归删除任何文件或目录。
- 不得执行 `git reset --hard`、`git checkout --` 或回退已有修改。
- 上传失败或 QA 不通过的资产不得自动删除。
- 不得覆盖已经批准的旧资产版本。
- 不得把上传成功等同于资产合格。
- 不得把 Prompt QA Approved 等同于生成授权。
- 不得让语言模型直接写入 `ready`、`approved` 或 `regulatorRegistered=true`。
- 不得在用户未确认时将敏感图片发送给外部供应商。
- 不得在供应商失败时静默切换 Agent、模型或 QA 方式。
- 不得让 `video-asset-regulator` 代替角色、场景、道具或融合领域 Skill 做 Generated Image QA。

---

## 2. 业务边界：界面合并，职责不能混淆

用户希望把“资产总控”融合到资产上传界面。这是正确的交互方向，但内部职责必须保持：

```text
上传文件
→ 技术校验
→ 映射到稳定资产 ID / 版本 / 角色
→ video-asset-regulator 识别、分级、检查依赖并路由
→ 对应领域 Skill 执行 Generated Image QA
→ QA 决策
→ video-asset-regulator 登记或归入不合格资产
→ 若失败，询问用户下一步
```

QA Owner 必须按类型路由：

| 上传资产类型 | Generated Image QA Owner |
|---|---|
| 角色 | `video-character-design-director` |
| 场景 | `video-scene-design-director` |
| 道具 | `video-prop-design-director` |
| 融合/关键帧/首尾帧 | `video-fusion-production-director` |
| 视频 | `video-shot-director` |
| 音频 | `voice-controller` |
| 无法识别 | 先由 `video-asset-regulator` 要求用户完成映射，不进入正式 QA |

`video-asset-regulator` 负责：

- 核对稳定 ID。
- 核对资产类型、等级、用途和关联镜头。
- 确定 QA Owner。
- 建立下游 QA 任务包。
- 接收领域 QA 决策。
- 只有通过后登记生产用途。
- 更新项目缺口和镜头依赖状态。

---

## 3. 当前实现的已知缺陷

当前上传接口：

```http
POST /api/assets/upload?project_id=...
```

当前行为：

- 校验部分扩展名和 PNG/JPEG 文件签名。
- 把文件保存到项目 uploads 目录。
- 立即创建 artifact。
- artifact 默认状态直接设为 `generated_pending_qa`。
- 前端直接把返回 artifactId 写进逻辑资产。

当前不足：

1. 上传前没有选择或确认资产 ID、资产类型、目标版本和用途。
2. 无法区分“外部生成结果”“用户参考图”“设计资产”“融合图”“视频”“音频”。
3. 没有待映射队列。
4. 没有真正的领域 QA 运行记录。
5. 前端存在直接点击“Generated Image QA：通过”的按钮，用户可以无证据改状态。
6. 前端存在直接点击“由资产总控登记”的按钮，没有服务端审批记录。
7. QA 失败后只有 `revision-required`，没有不合格资产库、失败原因和 Prompt 重建闭环。
8. 新文件直接覆盖逻辑资产当前 artifactId，可能使已批准版本丢失可追溯性。
9. `register_artifact()` 把状态硬编码为 `generated_pending_qa`，不适合所有上传来源。
10. 上传行为、审计行为和全项目资产总控卡彼此割裂。

实施时必须先修正这些数据边界，再调整视觉布局。

---

## 4. 最终交互目标

将当前独立“资产总控”卡片和上传入口重构为统一的“资产导入与审计中心”：

```text
┌──────────────────────────────────────────────────────────┐
│ 资产导入与审计中心                                      │
│ [上传资产] [批量上传] [运行项目总控审计]                │
├──────────────────────────────────────────────────────────┤
│ 待映射 2 │ 待审计 3 │ 审计中 1 │ 合格 8 │ 未合格 4     │
├──────────────────────────────────────────────────────────┤
│ 上传/审计队列                                           │
│ 文件缩略图 │ 目标资产 │ 类型/用途 │ 技术校验 │ 领域 QA  │
│            │          │           │          │ 下一步    │
└──────────────────────────────────────────────────────────┘
```

页面下方继续保留逻辑资产卡片，但资产总控状态、上传、QA 和登记都从统一中心进入，不再单独放一张说明卡。

---

## 5. 上传流程详细设计

### 5.1 上传入口

提供：

- 拖放区域。
- 单文件选择。
- 多文件批量选择。
- 从某个逻辑资产检查器打开时，自动预选资产 ID。
- 从某个镜头资产目录进入时，自动带上 `fromShotId` 和目标资产 ID。

不要让用户通过浏览器 `prompt()` 输入资产类型或名称。使用明确表单和受控下拉框。

### 5.2 上传前映射表单

字段：

```text
项目：只读
上传来源：外部 ChatGPT / 工作台生成返回 / 用户参考图 / 已有制作资产 / 其他
目标资产：从当前项目稳定资产 ID 下拉选择
资产类型：由目标资产自动确定，只读；未映射时可选择候选类型
目标角色：DES / FACE / EXPR / COSTUME / DETAIL / REF / SCENE_MAIN / TOPDOWN / CAM / PROP_MASTER / FUSION / KEY / FIRST / LAST / AUDIO / VIDEO
关联镜头：多选现有 SH ID
Prompt 版本：可选已有版本，不允许自由伪造 Approved
Generation ID：如有则选择或填入受控格式
尝试次数：自动计算
备注：可选
是否立即进入审计：默认开启
```

若从逻辑资产卡发起上传，目标资产必须锁定为该资产，除非用户明确点击“重新映射”。

### 5.3 技术校验

上传时自动执行，不调用 Agent：

- 文件不能为空。
- 文件大小限制。
- 扩展名白名单。
- MIME 和文件签名一致。
- 图片可解码。
- 图片宽高、色彩模式和分辨率可读取。
- 视频可通过 ffprobe 读取。
- 音频可读取时长、采样率和声道。
- SHA-256。
- 同项目重复哈希检查。
- 文件名安全化。
- 路径必须位于项目目录。

技术校验失败时：

- 不进入领域 QA。
- 显示具体错误。
- 询问“重新选择文件”，不要询问重建 Prompt，因为损坏文件与 Prompt 无关。
- 不保存空文件或伪装 MIME 文件。

### 5.4 待映射状态

如果无法确定以下任一项：

- 项目。
- 稳定资产 ID。
- 资产类型。
- 资产角色。
- Prompt 版本或来源用途。

则进入：

```text
intake_mapping_required
```

不得进入 Generated Image QA，也不得更新逻辑资产当前版本。

### 5.5 上传完成不是 Ready

完成上传并映射后，状态应为：

```text
generated_pending_qa
```

或对于纯参考素材：

```text
reference_pending_review
```

任何上传返回都不能直接设置：

```text
ready
approved
regulatorRegistered=true
```

---

## 6. 上传后自动审计流程

### 6.1 审计前预检查

`video-asset-regulator` 先确定：

- 稳定资产 ID 是否存在。
- 文件版本是否会覆盖批准版本。
- 资产等级。
- 资产类型与文件角色是否相符。
- 关联镜头。
- 当前 Prompt 版本。
- QA Owner。
- 是否满足进入领域 QA 的必要上下文。
- 是否需要用户确认敏感素材上传到 Agent 供应商。

若不完整，则进入 `audit_blocked`，显示缺失字段。

### 6.2 能力探测

自动审计图片前检查当前 Agent 是否支持视觉输入：

- 支持视觉：显示供应商、模型、将发送的图片和文本范围。
- 不支持视觉：不得假装完成 QA；显示“当前 DeepSeek 接入不支持图片审计”，允许用户：
  - 切换到支持视觉的已配置 Agent。
  - 输出外部 ChatGPT QA 包。
  - 暂存待人工 QA。

不允许静默切换 Agent。

### 6.3 敏感素材确认

人物肖像、真人声音、身份证明或其他敏感素材，在发送给外部 API 前必须显示：

- 供应商。
- 模型。
- 文件名和缩略图。
- 用途。
- 授权状态。
- 数据发送确认。

没有授权材料时进入 `blocked`。

### 6.4 领域 QA 任务包

任务包至少包含：

```text
Target skill:
Project ID:
Asset ID:
Asset class:
Asset role:
Asset priority:
Generated file:
Generation ID:
Source prompt version:
Generation source:
Attempt number:
Reference assets used:
Relevant shots:
Design/identity/scene/prop/fusion locks:
Must preserve:
Must avoid:
Known previous failures:
Required QA decision:
Return expected: video-asset-regulator
```

只允许领域 QA 返回：

```text
Decision: Approved
Decision: Needs revision
Decision: Reject and rebuild prompt
```

必须同时返回：

- 观察到的问题。
- 影响镜头。
- 可批准用途。
- 禁止用途。
- 是否可以通过图片编辑修复。
- 是否必须重建 Prompt。

### 6.5 QA 结果必须结构化校验

服务端校验：

- 决策枚举有效。
- Asset ID 与上传映射一致。
- QA Owner 与类型一致。
- Prompt 版本存在或明确为 reference-only。
- QA 报告不是空文本。
- 不得由模型直接设 `regulatorRegistered`。

---

## 7. 合格资产登记流程

当领域 QA 返回 `Approved`：

```text
generated_pending_qa
→ approved_pending_registration
→ video-asset-regulator registration
→ ready
```

资产总控登记必须生成：

```text
Asset ID
Asset class
Version
Project path
Source generation ID
Source prompt version
Generation source
QA owner
QA decision
Approved reference roles
Relevant shots
Continuity locks
Restrictions
Readiness
Registered by: video-asset-regulator
```

A/A+ 资产只有同时满足：

- 文件存在。
- 哈希存在。
- 领域 Generated Image QA Approved。
- 资产总控登记存在。
- 状态是 ready/approved。

才能更新为生产就绪。

如果逻辑资产已有批准版本：

- 新版本先作为 candidate。
- 旧批准版本保持 active。
- 用户确认替换后新版本才成为 active。
- 旧版本变为 superseded，但仍可追溯。

---

## 8. 不合格资产库

### 8.1 逻辑归档，不物理删除

QA 不通过时，把 artifact 归入：

```text
collection = unqualified
```

不要立即移动或删除物理文件，以免破坏哈希、路径和审计记录。界面通过数据库状态形成“不合格资产库”。

如未来需要物理隔离，应单独设计事务化迁移，本次不做。

### 8.2 状态

```text
revision_required
rejected
technical_rejected
mapping_required
audit_blocked
```

其中：

- `revision_required`：图像可能通过编辑或小范围修订恢复。
- `rejected`：当前图像不能进入生产。
- `technical_rejected`：文件格式或完整性失败。
- `mapping_required`：无法确定所属资产。
- `audit_blocked`：缺上下文、授权或视觉能力。

### 8.3 不合格资产卡片

必须显示：

- 缩略图。
- 文件名。
- artifactId。
- 目标 Asset ID。
- Prompt 版本。
- 尝试次数。
- QA Owner。
- QA 决策。
- 失败原因。
- 影响镜头。
- 是否替代旧批准版本。
- 下一步建议。

支持筛选：

- 角色。
- 场景。
- 道具。
- 融合。
- 技术失败。
- QA 需修订。
- 必须重建 Prompt。
- 待映射。

---

## 9. QA 不通过后的询问窗口

### 9.1 弹出时机

领域 QA 返回以下任一结果后弹出：

```text
Needs revision
Reject and rebuild prompt
```

技术校验失败不显示 Prompt 重建选项，只显示重新上传。

### 9.2 窗口内容

标题：

```text
[Asset ID] 未通过资产审计
```

显示：

- 当前图片。
- 决策。
- 具体问题。
- Must preserve 违反项。
- Must avoid 违反项。
- 影响镜头。
- 当前 Prompt 版本。
- 当前尝试次数。
- 推荐修复方式。

按钮根据 QA 决策动态显示：

```text
1. 修订当前 Prompt
2. 重建 Prompt
3. 尝试图片编辑
4. 上传替代文件
5. 保留到不合格资产库
6. 暂不处理
```

不要一律只问“是否重新生成 Prompt”。

### 9.3 决策路由表

| 失败类型 | 默认建议 | 可选动作 |
|---|---|---|
| 文件损坏/MIME 不符 | 重新上传 | 上传替代文件 |
| 轻微构图、背景或色彩问题 | 尝试图片编辑 | 修订 Prompt、暂存 |
| 身份、结构、空间几何、道具比例错误 | 重建 Prompt | 上传替代文件、暂存 |
| Prompt 与结果偏差但 Prompt 本身仍有效 | 新生成尝试 | 重新选择生成方式 |
| Prompt QA 规则本身缺失或模糊 | 修订 Prompt 并重新 Prompt QA | 暂存 |
| 同一融合目标失败两次 | 强制从源锁重建 Prompt | 不允许继续旧 Prompt 重试 |
| 无法映射 Asset ID/Prompt 版本 | 完成映射 | 暂存未映射区 |
| 当前 Agent 无视觉能力 | 切换视觉 Agent或外部 QA | 暂存 |

### 9.4 Prompt 修订和重建的区别

#### 修订当前 Prompt

适用于局部问题：

- 创建新 Prompt 版本。
- 保留原 Prompt。
- 把 QA 观察作为修订输入。
- 路由到对应领域 Skill。
- 新 Prompt 必须重新经过 Prompt QA。

#### 重建 Prompt

适用于根本性失败：

- 不从失败 Prompt 继续微调。
- 从资产 Bible、身份锁、场景 DNA、道具结构锁或融合源资产重新构建。
- 创建新的 Prompt 主版本。
- 记录 `rebuiltFromFailureIds`。
- 必须重新 Prompt QA。
- 必须重新经过用户生成选择门。

### 9.5 重新生成仍需确认

Prompt 修订或重建完成并通过 Prompt QA 后，只进入：

```text
user-confirmation-required
```

再次显示：

```text
1. 使用工作台图片生成
2. 输出外部 ChatGPT 网页版生成包
3. 暂不生成
```

不得因为用户之前批准过旧 Prompt 的生成，就自动批准新版本。

---

## 10. 统一页面设计

### 10.1 移除独立资产总控说明卡

把当前 `regulatorCard(p)` 的内容并入“资产导入与审计中心”的状态栏：

```text
总控版本 v02
最后审计时间
A/A+ 缺口
待映射
待 QA
未合格
待登记
```

保留“运行项目总控审计”，但它负责全局资产和依赖复核；单个上传后的审计由上传队列触发。

### 10.2 标签页

```text
待处理
审计中
合格资产
未合格资产
全部记录
```

“待处理”合并：待映射、待 QA、待登记和被阻塞项。

### 10.3 上传队列

每行：

```text
缩略图 | 文件/哈希 | 目标资产 | 用途 | 状态 | QA Owner | 失败原因/下一步 | 操作
```

行点击打开审计详情；不得再用连续 `confirm()` 和 `prompt()` 完成复杂流程。

### 10.4 审计详情抽屉

分区：

1. 文件技术信息。
2. 资产映射。
3. Prompt/Generation 来源。
4. 领域 QA 报告。
5. 总控登记。
6. 版本与历史。
7. 关联镜头。
8. 下一步动作。

### 10.5 批量上传

批量上传必须先显示表格预览：

- 文件数量。
- 推测资产 ID。
- 重复哈希。
- 未映射数量。
- 将触发的 QA 次数。
- 将发送给外部 Agent 的文件数量。

用户确认批次后上传。批量 QA 可排队，但不得批量自动批准。

---

## 11. 数据库与数据结构

### 11.1 不要只修改项目 JSON

上传、QA、失败和登记是审计记录，应主要落在 SQLite；项目 JSON 保存当前逻辑资产摘要和 active 版本引用。

### 11.2 artifacts 表迁移

建议增加：

```text
logical_asset_id
asset_class
asset_role
collection
intake_status
source_type
generation_id
prompt_version
attempt_number
qa_report_json
rejection_reason
supersedes_artifact_id
updated_at
```

`collection`：

```text
intake
qualified
unqualified
reference
archived
```

### 11.3 新增 QA 表

```sql
CREATE TABLE asset_qa_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  logical_asset_id TEXT NOT NULL,
  qa_owner TEXT NOT NULL,
  status TEXT NOT NULL,
  decision TEXT,
  report_json TEXT NOT NULL DEFAULT '{}',
  provider_profile_id TEXT,
  provider_model TEXT,
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT NOT NULL
);
```

### 11.4 新增资产版本表（推荐）

```sql
CREATE TABLE asset_versions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  logical_asset_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  artifact_id TEXT NOT NULL,
  prompt_version TEXT,
  status TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 0,
  registration_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  approved_at TEXT
);
```

旧项目兼容：项目资产仍保留 `artifactId/filePath/version/status` 摘要，由服务端根据 active asset version 同步。

### 11.5 失败计数

同一逻辑资产、同一目标、同一 Prompt 主版本的失败次数必须可计算。融合目标失败两次后：

- 禁止继续用旧 Prompt 重试。
- 强制重建 Prompt。
- UI 显示“已达到重建阈值”。

---

## 12. API 设计

### 12.1 新上传入口

推荐新增并逐步替代旧接口：

```http
POST /api/assets/intake
```

multipart 字段：

```text
project_id
file
logical_asset_id
asset_role
source_type
generation_id
prompt_version
relevant_shots_json
run_audit
```

响应：

```json
{
  "artifact": {},
  "technical_validation": {},
  "mapping": {},
  "next_status": "generated_pending_qa",
  "audit_allowed": true,
  "warnings": []
}
```

保留旧 `/api/assets/upload` 一段时间，但内部调用同一 intake service。

### 12.2 查询

```http
GET /api/assets/intake?project_id=...&collection=...
GET /api/assets/artifacts/{artifact_id}
GET /api/assets/{logical_asset_id}/versions?project_id=...
```

### 12.3 映射

```http
POST /api/assets/artifacts/{artifact_id}/map
```

只允许映射到当前项目资产。

### 12.4 QA

```http
POST /api/assets/artifacts/{artifact_id}/qa-runs
GET  /api/assets/qa-runs/{qa_run_id}
POST /api/assets/qa-runs/{qa_run_id}/cancel
```

创建前执行能力、授权和上下文门禁。

### 12.5 登记

```http
POST /api/assets/artifacts/{artifact_id}/register
```

后端重新检查文件、QA 决策和 QA Owner，不接受前端直接传 `ready=true`。

### 12.6 失败处置

```http
POST /api/assets/artifacts/{artifact_id}/resolution
```

请求枚举：

```text
revise_prompt
rebuild_prompt
image_edit
upload_replacement
keep_unqualified
defer
```

`revise_prompt/rebuild_prompt` 创建对应领域 workflow run，而不是由 regulator 自己写 Prompt。

---

## 13. 服务端状态机

```text
selected_local
→ uploading
→ technical_validation
→ mapping_required / technical_rejected / mapped
→ audit_queued
→ audit_running
→ approved_pending_registration / revision_required / rejected / audit_blocked
→ ready / unqualified / deferred
```

媒体生成返回的标准路径：

```text
generated_pending_qa
→ audit_queued
→ audit_running
→ approved_pending_registration
→ ready
```

失败重建路径：

```text
revision_required or rejected
→ unqualified
→ user_resolution_required
→ prompt_revision or prompt_rebuild
→ Prompt QA
→ user-confirmation-required
→ new generation attempt
```

所有状态转换写入事件表，禁止只改最终状态而没有历史。

---

## 14. 需要修复的现有直接审批行为

当前 `asset-workspace.js` 中以下行为不能作为正式生产流程保留：

- 点击按钮直接 `promptQaDecision = 'Approved'`。
- 点击按钮直接 `qaDecision = 'Approved'`。
- 点击按钮直接 `regulatorRegistered = true` 和 `status = 'ready'`。

改为：

- “运行 Prompt QA”创建 workflow run。
- “运行 Generated Image QA”创建 asset QA run。
- “由资产总控登记”调用服务端登记接口。
- 手工覆盖只对管理员/本地用户开放，并要求输入原因、责任人和审批记录；默认界面不提供一键假批准。

测试 fixture 可以直接构造状态，但正式 UI 不能。

---

## 15. 实施顺序

### 阶段 1：基线与数据备份

1. 运行现有 Python/JS 测试。
2. 备份 SQLite。
3. 浏览器记录当前上传、QA 和登记行为。

### 阶段 2：状态机和纯函数

1. 新建 `asset-intake-state.js`。
2. 定义状态、决策和路由纯函数。
3. 编写单元测试。

### 阶段 3：数据库迁移

1. 升级 schema version。
2. 扩展 artifacts。
3. 新增 QA 和 asset versions 表。
4. 迁移旧 artifacts，默认不得把历史 Pending 升级为 Approved。

### 阶段 4：后端 intake service

1. 抽离技术校验。
2. 实现映射、重复哈希和版本逻辑。
3. 实现新 API。
4. 保持旧上传接口兼容。

### 阶段 5：领域 QA 编排

1. 根据资产类型确定 QA Owner。
2. 实现视觉能力和敏感素材门禁。
3. 创建 QA run。
4. 校验结构化 QA 结果。

### 阶段 6：登记和不合格库

1. 实现服务端登记。
2. 实现 qualified/unqualified collection。
3. 实现失败计数和融合两次失败规则。

### 阶段 7：前端统一中心

1. 移除独立 regulator card。
2. 增加上传/审计中心和标签页。
3. 增加队列、详情和批量预览。
4. 替换直接 QA/登记按钮。

### 阶段 8：失败询问和 Prompt 重建

1. 实现动态处理窗口。
2. 路由到对应领域 Skill。
3. 保证新 Prompt 重走 QA 和生成选择门。

### 阶段 9：联动

1. 更新镜头资产进度。
2. 更新总览流水线。
3. 更新下一步任务。
4. 确保旧批准版本不被候选版本覆盖。

### 阶段 10：浏览器验收

执行第 17 节全部步骤。

---

## 16. 自动化测试要求

### 技术校验

- 空文件拒绝。
- 扩展名伪装拒绝。
- PNG/JPEG 签名不符拒绝。
- 路径穿越拒绝。
- 重复哈希被识别。
- 不支持格式不落盘。
- 大文件限制有效。

### 映射

- 未指定资产 ID 进入 mapping_required。
- 不能映射到其他项目资产。
- 资产类型冲突需要确认。
- stable ID 保持不变。

### QA 路由

- 角色路由 character director。
- 场景路由 scene director。
- 道具路由 prop director。
- 融合路由 fusion director。
- 无视觉能力时 blocked，不能 Approved。
- 未授权敏感素材 blocked。
- 模型失败不静默切换。

### QA 决策

- Approved 只能进入 approved_pending_registration。
- Needs revision 进入 unqualified/revision_required。
- Reject and rebuild 进入 unqualified/rejected。
- 空 QA 报告不能接受。
- QA Owner 错误不能接受。

### 登记

- A 级无文件不能 Ready。
- A 级无 QA Approved 不能 Ready。
- A 级无总控登记不能 Ready。
- 正式登记生成 registration record。
- 新候选版本不覆盖旧 active 版本。

### 失败闭环

- 技术失败不显示 Prompt 重建。
- Needs revision 显示修订/编辑/替换。
- Reject and rebuild 默认重建 Prompt。
- 融合同一目标失败两次后禁止旧 Prompt 重试。
- 新 Prompt 必须重新 Prompt QA。
- 新 Prompt Approved 后必须重新生成选择确认。

### 回归

- 项目管理、故事优化、分镜资产目录不回退。
- Agent API 设置与延迟显示不回退。
- Seedance 2.5/2.0 不回退。
- 所有现有测试继续通过。

---

## 17. 浏览器验收脚本

在测试项目和 fixture 中执行，不产生真实付费媒体调用：

1. 打开“资产生产”。
2. 确认独立资产总控说明卡已并入“资产导入与审计中心”。
3. 点击上传资产。
4. 确认出现目标资产、来源、用途、关联镜头和审计开关。
5. 上传一个损坏 PNG，确认技术校验失败且只提示重新上传。
6. 上传一个正常但未映射 PNG，确认进入待映射。
7. 将其映射到 C001。
8. 确认角色类型和 QA Owner 自动设置。
9. 确认上传完成仍是 generated-pending-qa，不是 Ready。
10. 当前 Agent 无视觉能力时，确认显示 blocked 和可选解决方案。
11. 使用视觉测试 fixture 运行角色 QA。
12. 模拟 Approved，确认进入待登记而非 Ready。
13. 调用资产总控登记，确认变为 Ready。
14. 检查关联镜头资产进度更新。
15. 再上传 C001 新候选版本。
16. 确认旧批准版本仍 active。
17. 模拟 Needs revision。
18. 确认新文件进入未合格资产库。
19. 确认弹窗显示具体问题和多种处理方式。
20. 点击“修订当前 Prompt”。
21. 确认创建对应领域 Skill 任务，而非 regulator 自写 Prompt。
22. 确认修订 Prompt 产生新版本并重新 Prompt QA。
23. 模拟 Reject and rebuild prompt。
24. 确认默认建议为“重建 Prompt”。
25. 重建后确认需要重新选择生成方式。
26. 模拟同一 BLEND 失败两次。
27. 确认旧 Prompt 重试被禁用。
28. 查看不合格资产详情和完整 QA 历史。
29. 确认未合格物理文件仍存在，未被删除。
30. 批量上传三个 fixture，检查批次预览和映射。
31. 确认批量 QA 不会批量自动批准。
32. 检查浏览器控制台无错误。
33. 重启服务，确认队列、QA 结果和不合格库仍存在。

---

## 18. 完成标准

只有全部满足才可交付：

- 上传与资产总控已整合为统一中心。
- 上传前可明确映射资产、用途、版本和关联镜头。
- 技术校验、总控路由、领域 QA 和总控登记职责分离。
- 上传完成不会自动 Ready。
- QA 不通过资产进入不合格资产库且文件保留。
- 失败后根据原因提供修订、重建、编辑、替代上传或暂存。
- Prompt 修订/重建由对应领域 Skill 执行。
- 新 Prompt 重新通过 Prompt QA 和用户生成选择门。
- 融合同一目标两次失败后强制重建 Prompt。
- 不再存在无证据的一键 QA 通过或一键 Ready。
- 已批准旧版本不会被失败候选覆盖。
- 关联分镜的资产进度实时更新。
- 所有自动化测试和 33 步浏览器验收通过。

---

## 19. DeepSeek 交付报告格式

```text
1. 当前上传/QA/登记问题根因
2. 修改文件及职责
3. 数据库迁移与兼容策略
4. 新上传与映射流程
5. 技术校验规则
6. 领域 QA 路由和能力门禁
7. 合格资产登记
8. 不合格资产库
9. Prompt 修订/重建闭环
10. 版本保护与失败次数规则
11. 自动化测试命令和结果
12. 33 步浏览器验收结果
13. 未完成项和需用户配置内容
```

若缺少 QA、授权、映射或注册证据，必须保持 Pending、Blocked、Revision Required 或 Rejected，不得为了提高进度而标记 Ready。
