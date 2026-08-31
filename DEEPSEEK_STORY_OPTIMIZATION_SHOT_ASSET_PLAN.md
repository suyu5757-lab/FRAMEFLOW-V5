# FRAMEFLOW：脚本优化与逐镜头资产联动执行计划

> 本文件可直接交给本地部署的 DeepSeek Agent 执行。
>
> DeepSeek 的职责是检查现有代码、实现功能、补充测试并完成浏览器验收。不得只输出分析或再次编写计划。
>
> 本计划是 `DEEPSEEK_COMMANDER_PLAN_JIEDU_UX_V2.md` 的增补任务。若两个计划一起执行，应先完成项目数据导入和状态模型稳定化，再执行本计划。

---

## 1. 项目地址与必读文件

项目根目录：

```text
D:\11067\Codex\2026-08-13\video-2
```

开始修改前必须完整阅读：

```text
D:\11067\CodexHome\skills\video-script-storyboard\SKILL.md
D:\11067\CodexHome\skills\video-asset-regulator\SKILL.md
D:\11067\CodexHome\skills\video-asset-regulator\references\video-production-handoff-contract.md
D:\11067\Codex\2026-08-13\video-2\DEEPSEEK_COMMANDER_PLAN_JIEDU_UX_V2.md
```

重点检查：

```text
app.js
assistant.js
workflow-state.js
asset-workspace.js
task-packages.js
api.js
server.py
frameflow/schemas.py
frameflow/workflows.py
frameflow/providers.py
frameflow/database.py
styles.css
index.html
tests/
package.json
```

### 禁止事项

- 不得覆盖或回退用户已有修改。
- 不得运行 `git reset --hard` 或 `git checkout --`。
- 不得批量、递归删除文件或目录。
- 不得让 Agent 结果直接覆盖当前已批准脚本、分镜或资产。
- 不得把 Prompt QA Approved 当作媒体生成授权。
- 不得把已有文件或漂亮图片自动判定为资产 Ready。
- 不得让 `video-asset-regulator` 代替角色、场景、道具或融合领域 Skill 制作最终 Prompt。
- 不得从分镜页绕过 Prompt QA、生成选择、Generated Image QA 和资产总控登记直接生成正式资产。
- 不得让镜头资产进度替代分镜审批状态、视频生成状态或视频 QA 状态。

---

## 2. 产品目标

整改“故事与分镜”页面，使它成为真正可执行的前期生产入口：

1. 在“可视化脚本”区域增加醒目的“脚本优化”按钮。
2. 按顺序调用：

```text
video-script-storyboard
→ 用户审阅并接受新的脚本/分镜版本
→ video-asset-regulator
→ 用户审阅并接受资产清单与镜头依赖版本
```

3. 每个分镜卡片显示该镜头需要的角色、场景、道具、融合、声音和后期依赖。
4. 每个镜头显示资产准备进度和阻塞原因。
5. 点击未完成资产名称，直接进入“资产生产”页并定位该资产的当前可执行步骤。
6. 点击资产名称只能进入正确生产流程，不能直接发起付费生成。
7. 所有状态从真实资产、QA、登记和依赖数据实时推导，禁止保存容易过期的“完成百分比快照”。

---

## 3. 当前实现问题

当前 `app.js` 的故事页主要由以下函数组成：

```js
renderStory(p)
shotCard(s, i)
```

已知问题：

- `renderStory()` 是单行模板，职责过多，不利于继续扩展。
- 脚本区只有 textarea，没有运行、版本、审阅或撤销入口。
- 页面右上“复制分镜技能任务”只复制文字，不能在工作台内执行 Skill。
- 分镜卡只显示目的、动作、景别、时长和一个含义模糊的状态。
- 镜头和资产之间没有稳定、可追溯的依赖结构。
- 点击分镜卡会直接进入镜头导演页，用户在前期看不到该镜头缺哪些资产。
- 现有 `shot.status === ready` 容易被误解为镜头已经可以生成或视频 QA 已通过。

必须先把故事页从 `app.js` 拆分出来，不要继续向单行 HTML 字符串叠加逻辑。

---

## 4. 推荐代码拆分

新增：

```text
story-workspace.js
story-workflow.js
shot-assets.js
```

职责：

### `story-workspace.js`

- 渲染故事与分镜页面。
- 脚本版本选择和差异审阅。
- 脚本优化按钮及状态面板。
- 分镜卡、镜头详情和资产目录。
- 页面事件绑定。

### `story-workflow.js`

- 构建 `video-script-storyboard` 输入包。
- 管理脚本优化的两阶段运行状态。
- 构建 `video-asset-regulator` 输入包。
- 解析并校验两个 Skill 的结构化输出。
- 生成项目补丁但不直接应用。

### `shot-assets.js`

- 正规化镜头资产依赖。
- 从实时资产记录推导逐镜头资产状态。
- 计算资产进度。
- 生成镜头下一步动作。
- 提供不依赖 DOM 的纯函数，便于 Node 测试。

更新 `server.py` 的静态文件白名单，确保新模块可加载。

---

## 5. 功能一：“脚本优化”双阶段工作流

### 5.1 页面入口

在“可视化脚本”面板标题右侧增加：

```text
[历史版本] [脚本优化 ✦]
```

移动端可收进更多菜单，但“脚本优化”必须始终可发现。

按钮语义：

> 使用当前输入作为源版本，先由 Storyboard Skill 形成可执行分镜建议；接受后，再由 Asset Regulator 建立资产清单和逐镜头依赖。不会自动生成图片或视频。

### 5.2 点击后的正确行为

点击“脚本优化”不得立刻覆盖内容，也不得立刻执行两个 Agent 调用。应执行：

1. 立即保存当前 textarea 到项目本地草稿。
2. 创建不可变源版本快照。
3. 打开“脚本优化”侧栏或对话框。
4. 显示当前 Agent、模型和连接状态。
5. 显示本次运行范围和默认参数。
6. 用户点击“开始优化”后，运行第一阶段。

这满足“直接连接 Skill 执行”，同时避免误触后覆盖文本。

### 5.3 优化设置

提供最少且不容易选错的预设，禁止让用户输入模型名称：

```text
优化目标：
- 完整前期包（推荐）
- 只优化脚本
- 脚本 + 分镜
- 重新审计现有分镜

改动强度：
- 保守：保持剧情，只做可视化与风险修订
- 平衡：允许压缩、补过渡和拆镜
- 重构：允许重排结构，但必须保留核心意图

时长：读取项目设置，可调整
画幅：读取项目设置，可调整
目标生成器：读取项目设置，只允许已有选项
```

默认使用“完整前期包 + 保守/平衡”，具体默认可根据输入完整度决定：

- 只有一句想法：完整前期包 + 平衡。
- 已有脚本：完整前期包 + 保守。
- 已有稳定镜头和资产：重新审计现有分镜 + 保守。

### 5.4 第一阶段：`video-script-storyboard`

必须携带真实 `skill_id`：

```text
video-script-storyboard
```

输入必须包含：

```text
Project ID
Project name
Source script version ID
Current script/idea
Project brief
Duration
Aspect ratio
Target generator
Existing stable character/scene/prop IDs
Existing shot IDs
Optimization goal
Change strength
Must preserve
Must avoid
Content safety constraints
```

要求模型按 Skill 的完整结构返回：

```text
1. Input Type Judgment
2. Initial Script or Organized Script
3. Cinematic Feasibility Judgment
4. Visualized Script
5. Basic Production Elements
6. Scene Breakdown
7. Storyboard Outline
8. Detailed Storyboard Table
9. AI Generation Risks and Optimization Advice
10. Next-Step Production Checklist
11. Asset Handoff Package
```

必须返回结构化 JSON，同时生成适合人类阅读的 Markdown 摘要。JSON 至少包含：

```js
{
  sourceScriptVersionId,
  proposedScript,
  feasibility,
  productionElements,
  scenes,
  shots,
  risks,
  assetHandoff,
  assumptions,
  warnings
}
```

### 5.5 第一阶段审阅

第一阶段返回后进入：

```text
storyboard_review_required
```

界面显示：

- 原脚本与优化脚本并排或切换对比。
- 字数、时长、角色数、场景数、镜头数变化。
- 新增、修改、删除的镜头。
- 稳定 ID 变化警告。
- 高风险动作变化。
- 假设与不确定内容。

用户可以：

- 接受整个建议版本。
- 只接受脚本。
- 只接受选中的镜头变化。
- 保存为候选版本但不启用。
- 拒绝。

禁止模型输出直接写进当前项目。

### 5.6 稳定 ID 合并规则

- 已存在 SH/C/S/P ID 时必须尽量保留。
- 内容更新产生新版本，不重命名稳定目标。
- 新角色、场景、道具由服务端 ID 分配器生成，不能信任模型随意创建的重复 ID。
- 删除已有镜头默认标记为 `deprecated`，不要立即从历史版本物理删除。
- 如果镜头目的发生根本变化，应创建新镜头 ID并保留旧镜头历史。
- 提交前检查 ID 唯一性和引用完整性。

### 5.7 第二阶段：`video-asset-regulator`

只有第一阶段结果被用户接受为活动 storyboard 版本后，才能运行资产总控。

输入必须是已接受的 `Asset Handoff Package`，至少包含：

```text
Project Summary
Visualized Script
Character List
Scene List
Prop / Item List
Storyboard Outline
Detailed Storyboard Table
Shot Risk Table
Asset Dependency Draft
Stable Shot IDs
Existing Asset Inventory
Existing QA/registration evidence
```

资产总控输出必须包含：

```text
Input Recognition
Upstream Handoff Summary
Existing Asset Inventory
Asset Extraction Master Table
Asset Priority Classification
Missing Asset Register
Asset Dependency Table
Downstream Routing Plan
Production Task Queue
Seedance Packaging Readiness
Asset Completeness Gate
Next Action Recommendation
```

Regulator 只建立资产清单、优先级、依赖、门禁和路由，不生成角色/场景/道具最终 Prompt。

### 5.8 第二阶段审阅

资产总控结果进入：

```text
regulator_review_required
```

界面显示：

- 新增资产。
- 修改的资产等级。
- 每个镜头的新增/删除依赖。
- A/A+ 缺口。
- 被阻塞的镜头。
- 建议生产队列。

用户接受后才更新：

- 项目资产清单。
- `assetRegulator` 版本。
- 镜头资产依赖。
- 下一步任务。

### 5.9 工作流状态机

统一状态：

```text
draft
validated
running_storyboard
storyboard_review_required
storyboard_rejected
running_regulator
regulator_review_required
regulator_rejected
succeeded
blocked
failed
canceled
```

每次运行记录父子关系：

```js
{
  chainRunId,
  projectId,
  sourceScriptVersionId,
  storyboardRunId,
  regulatorRunId,
  activeStep,
  status,
  providerProfileId,
  model,
  createdAt,
  updatedAt
}
```

服务重启后能够继续显示待审阅状态，不重复调用 Agent。

### 5.10 版本与撤销

建议项目增加：

```js
scriptVersions: [
  {
    id: 'SCRIPT_v001',
    parentId: null,
    status: 'active|candidate|rejected|superseded',
    text: '',
    source: 'user|agent',
    skillId: null,
    providerProfileId: null,
    model: null,
    createdAt: '',
    acceptedAt: null
  }
],
storyboardVersions: [
  {
    id: 'STORYBOARD_v001',
    parentId: null,
    scriptVersionId: 'SCRIPT_v001',
    status: 'active|candidate|rejected|superseded',
    shotIds: [],
    package: {},
    createdAt: '',
    acceptedAt: null
  }
]
```

旧项目迁移：

- 当前 `script` 迁移为第一个 active script version。
- 当前 `shots` 迁移为第一个 active storyboard version。
- 不覆盖原字段，第一版仍同步维护 `script` 和 `shots` 以兼容现有页面。

---

## 6. 功能二：分镜卡的资产目录与实时进度

### 6.1 镜头资产依赖数据结构

为每个镜头增加：

```js
assetRequirements: [
  {
    assetId: 'C001',
    assetClass: 'character',
    role: '主角身份与服装连续性',
    priority: 'A',
    required: true,
    requiredReadiness: 'production',
    source: 'video-asset-regulator',
    regulatorVersion: 'v02'
  },
  {
    assetId: 'S001',
    assetClass: 'scene',
    role: '卧室空间布局与雨夜侧光',
    priority: 'A+',
    required: true,
    requiredReadiness: 'production',
    source: 'video-asset-regulator',
    regulatorVersion: 'v02'
  }
]
```

允许的 `assetClass`：

```text
character
scene
prop
fusion
audio
post
```

允许的 `requiredReadiness`：

```text
production     # 必须有文件 + 领域 QA + 总控登记
planning       # B 级可用明确规格/参考满足
prompt-only    # C 级仅需 Prompt/文字规格
not-required
```

不要把 `ready`、`progress` 或百分比保存在此结构中。它们必须从当前资产记录实时推导，避免过期。

### 6.2 资产状态推导

在 `shot-assets.js` 增加纯函数：

```js
deriveShotAssetStatus(shot, assets)
deriveShotAssetProgress(shot, assets)
deriveShotBlockingReasons(shot, assets)
nextAssetAction(asset, requirement)
```

生产级依赖使用现有严格规则：

```js
assetProductionReady(asset)
```

A/A+ 只有同时满足以下条件才能算就绪：

- `status` 是 `ready` 或 `approved`。
- `artifactId` 或 `filePath` 存在。
- `qaDecision === 'Approved'`。
- `regulatorRegistered === true`。

规划级 B 资产可以由明确规格或清晰参考满足，但必须在资产记录中有证据字段；不能只因为资产 ID 存在就完成。

C 级 prompt-only 资产只在 `prompt` 存在且 Prompt QA 通过时完成规划要求，但不得作为 A 级生产引用。

### 6.3 状态分类

逐项显示：

```text
ready                  绿色对号
in_progress            黄色半圆
missing                红色空心圆
blocked                红色锁
generated_pending_qa   黄色“待图片 QA”
prompt_qa_pending      黄色“待 Prompt QA”
registration_pending   黄色“待总控登记”
external_pending       黄色“待外部返回”
not_required           灰色横线
```

颜色之外必须有图标和文字。

### 6.4 镜头卡片布局

分镜卡建议改为：

```text
┌──────────────────────────────┐
│ SH001              分镜已批准 │
│ [预览区域]                    │
│ 建立雨夜空间                  │
│ 4s · 全景 · 风险低            │
├──────────────────────────────┤
│ 资产准备 2/4   █████░░ 50%    │
│ ✓ S001 雨夜卧室               │
│ ◐ C001 林夏 · 待图片 QA       │
│ ○ P001 手机 · 缺失            │
│ 🔒 BLEND_SH001 · 基础资产阻塞 │
│ [查看全部资产 →]              │
└──────────────────────────────┘
```

卡片上必须区分：

- `分镜状态`：脚本/分镜是否批准。
- `资产准备状态`：该镜头所需生产资产是否齐全。
- `导演状态`：是否存在批准的 `DIR_SH...` 包。
- `视频状态`：尚未生成、生成中、待视频 QA、已批准。

不要继续用一个“已批准”覆盖四种不同含义。

### 6.5 资产目录显示规则

- 默认显示前 3–4 个必需资产。
- “查看全部资产”展开完整目录或打开镜头详情抽屉。
- 先按阻塞程度排序，再按角色 → 场景 → 道具 → 融合 → 音频 → 后期排序。
- 可选 C 级内容折叠到“可选/后期”。
- 每项显示资产 ID、名称、角色、当前状态和下一动作。
- 如果资产 ID 未在项目资产表中找到，显示“总控登记缺失”，不要静默创建 Ready 资产。

### 6.6 点击资产后的跳转

点击资产名称执行：

```js
navigate('assets', {
  filter: asset.type,
  assetId: asset.id,
  action: derivedNextAction,
  fromShotId: shot.id,
  scrollTarget: '#asset-workspace'
})
```

进入资产页后：

1. 应用资产类型筛选。
2. 定位并高亮资产卡片。
3. 自动打开资产检查器。
4. 显示来源镜头。
5. 聚焦唯一推荐动作。

推荐动作根据真实状态决定：

| 当前状态 | 推荐动作 |
|---|---|
| 资产记录不存在 | 运行资产总控或登记缺失资产 |
| 无设计规格/Prompt | 运行对应领域设计 Skill |
| Prompt 待 QA | 运行 Prompt QA |
| Prompt Needs revision | 修订并重新 QA，旧 Prompt 禁止生成 |
| Prompt Approved、未选择生成方式 | 显示三种生成选择 |
| external-generation-pending | 上传或登记外部返回图 |
| generated-pending-qa | 运行对应领域 Generated Image QA |
| QA Approved、未登记 | 由资产总控登记 |
| 生产 Ready | 查看版本和批准用途 |
| 融合依赖未就绪 | 返回基础资产阻塞清单 |

### 6.7 生成选择门

从分镜页进入资产页后，仍必须遵循：

```text
1. 使用工作台图片生成
2. 输出外部 ChatGPT 网页版生成包
3. 暂不生成，仅保留已批准 Prompt
```

只有 Prompt QA Approved 后才显示选择。点击资产名称绝不能自动调用图片 API。

### 6.8 资产变更对镜头的影响

资产状态变化后：

- 所有关联镜头的资产进度实时更新。
- 不修改分镜审批状态。
- 如果已批准资产的新版本进入 QA，旧批准版本仍可使用，除非被明确废弃。
- 如果资产被拒绝且没有可用批准版本，关联镜头立即显示阻塞。
- 不要通过保存冗余百分比更新所有镜头。

### 6.9 镜头级聚合状态

增加：

```js
{
  total,
  ready,
  inProgress,
  missing,
  blocked,
  percent,
  productionReady,
  blockingAssetIds,
  nextAssetId
}
```

计算规则：

- `not_required` 不计入分母。
- 必需资产权重一致，不使用等级虚构百分比。
- 任一 required production 资产 blocked/missing，则镜头 `productionReady=false`。
- 进度 100% 只代表资产依赖完成，不代表镜头导演、Seedance 或视频 QA 完成。

---

## 7. 后端与持久化设计

### 7.1 Schema 扩展

在 `ProjectDocument` 中增加兼容字段：

```python
scriptVersions: list[dict[str, Any]] = Field(default_factory=list)
storyboardVersions: list[dict[str, Any]] = Field(default_factory=list)
storyWorkflowRuns: list[dict[str, Any]] = Field(default_factory=list)
```

`shots` 仍可保持 `list[dict]`，但必须在正规化函数中补 `assetRequirements: []`。

### 7.2 建议数据库表

不要把大段候选输出全部塞进 `undoStack`。建议迁移新增：

```sql
story_workflow_chains
story_versions
storyboard_versions
```

最小字段：

```text
id
project_id
parent_id / source_version_id
status
provider_profile_id
model
content_json
created_at
accepted_at
```

迁移必须版本化，不得修改已有迁移记录。

### 7.3 API

建议新增：

```http
POST /api/projects/{project_id}/story-optimization-runs
GET  /api/projects/{project_id}/story-optimization-runs
GET  /api/story-optimization-runs/{run_id}
POST /api/story-optimization-runs/{run_id}/start
POST /api/story-optimization-runs/{run_id}/accept-storyboard
POST /api/story-optimization-runs/{run_id}/reject-storyboard
POST /api/story-optimization-runs/{run_id}/accept-regulator
POST /api/story-optimization-runs/{run_id}/reject-regulator
POST /api/story-optimization-runs/{run_id}/cancel
```

也可以复用 `/api/workflow-runs`，但必须增加：

- parent/chain run ID。
- step。
- output_json。
- review status。
- accepted version ID。

不能只在浏览器内临时保存 Agent 返回内容。

### 7.4 SSE

复用 `/api/assistant/stream` 时，每一步必须传真实 `skill_id`：

```text
video-script-storyboard
video-asset-regulator
```

SSE 事件建议：

```text
meta
step_started
text_delta
structured_result
review_required
step_finished
error
```

当前 `/api/assistant/stream` 只返回一次 `result`，允许先以两次独立 SSE 请求实现，但运行链状态必须落库。

### 7.5 服务端校验

Storyboarding 输出校验：

- 镜头 ID 唯一。
- 资产 ID 唯一。
- 时长合计与项目目标差异有明确警告。
- 镜头引用的场景/角色/道具存在或列为待建。
- 必填分镜字段完整性。
- 风险字段存在。
- Asset Handoff Package 存在。

Regulator 输出校验：

- 所有依赖引用稳定 ID。
- 每个必需资产有等级、负责 Skill 和状态。
- A/A+ 缺口没有被误判 Ready。
- 融合依赖只在基础资产之后。
- Seedance 路由没有绕过镜头导演。

---

## 8. 页面交互细节

### 8.1 脚本区

建议布局：

```text
可视化脚本                   版本 v03 · 已保存
[历史版本] [脚本优化 ✦]
┌────────────────────────────────────┐
│ textarea                           │
└────────────────────────────────────┘
上次优化：DeepSeek · 8 秒 · 待审阅/已接受
```

运行中按钮显示：

```text
正在优化脚本…
```

不可重复点击。允许取消文本任务，但不能误删已有候选版本。

### 8.2 分镜区域

顶部增加汇总：

```text
20 镜头 · 90 秒
分镜完整 20/20
资产就绪 6/20 镜头
阻塞 14 镜头
[只看阻塞] [按场景分组] [全部展开]
```

筛选只影响显示，不改变项目数据。

### 8.3 镜头详情抽屉

点击卡片主体打开故事页内的镜头详情，不应立刻把用户送到镜头导演页。详情包含：

- 分镜字段。
- 风险和优化建议。
- 连续性字段。
- 完整资产目录。
- 资产阻塞链。
- 当前最小下一步。
- “进入镜头导演”按钮；只有资产门禁满足时启用。

点击卡片中的资产名称时，则进入资产生产页。

### 8.4 无障碍与事件冲突

- 分镜卡和内部资产按钮不能共享同一个 click 行为。
- 资产按钮处理后必须 `stopPropagation()`。
- 卡片使用可聚焦元素或 `tabindex=0`。
- Enter 打开镜头详情。
- 资产按钮 Enter 进入资产页。
- 状态不能只依赖颜色。

---

## 9. 与现有功能的集成

### 9.1 `asset-workspace.js`

增加公开入口：

```js
openAsset(assetId, options)
```

至少支持：

```js
{
  fromShotId,
  action,
  focus: true
}
```

不要依赖 `setTimeout + querySelector` 猜测渲染完成；使用明确的 pending navigation state。

### 9.2 `assistant.js`

确保 `openWithPrompt(text, skillId)`：

- 将 Skill ID 保存到本次请求上下文。
- 请求时传入真实 Skill ID。
- 页面显示当前 Skill。
- 切换项目后清理不相关上下文。

### 9.3 `workflow-state.js`

- 故事阶段应以 active storyboard version 为依据。
- Regulator 阶段应以已接受的监管版本为依据。
- 脚本优化候选未接受时，不改变生产流水线状态。
- 资产依赖变化后，镜头资产进度实时变化。

### 9.4 导出

项目导出应包括：

- 活动脚本版本。
- 活动分镜版本。
- 历史版本索引。
- 镜头资产依赖。
- 监管版本。

默认不把全部 Agent 对话和大体积候选输出塞进轻量项目 JSON，可提供单独完整备份。

---

## 10. 实施顺序

严格按以下顺序执行：

### 阶段 1：基线

1. 运行现有 Python 和 JavaScript 测试。
2. 浏览器记录现有故事页行为与控制台错误。
3. 记录当前项目 JSON 结构。

### 阶段 2：纯状态函数

1. 新建 `shot-assets.js`。
2. 实现正规化和状态推导。
3. 编写单元测试。
4. 不修改 UI，先确保数据规则正确。

### 阶段 3：故事页拆分

1. 新建 `story-workspace.js`。
2. 迁移 `renderStory`、`shotCard` 和事件绑定。
3. 确保旧功能不回退。

### 阶段 4：分镜资产目录

1. 在卡片显示实时进度。
2. 增加镜头详情抽屉。
3. 实现资产点击跳转。
4. 与 `asset-workspace.openAsset()` 对接。

### 阶段 5：版本模型

1. 增加 script/storyboard 版本正规化。
2. 增加数据库迁移。
3. 增加版本 API。
4. 迁移旧项目但不覆盖原字段。

### 阶段 6：脚本优化第一阶段

1. 增加脚本优化面板。
2. 调用 `video-script-storyboard`。
3. 实现候选版本和差异审阅。
4. 实现接受/拒绝。

### 阶段 7：资产总控第二阶段

1. 接受 storyboard 后建立 regulator run。
2. 调用 `video-asset-regulator`。
3. 实现资产和依赖差异审阅。
4. 接受后更新活动监管版本。

### 阶段 8：恢复与历史

1. 重启恢复待审阅状态。
2. 运行历史列表。
3. 版本切换和撤销。

### 阶段 9：浏览器验收

逐条执行第 12 节。

---

## 11. 自动化测试要求

### 11.1 `shot-assets.js`

- 无依赖镜头显示“等待资产总控”，不能显示 100%。
- A 级资产只有 status ready 但无文件时不完成。
- 有文件但图片 QA Pending 时不完成。
- 图片 QA Approved 但未登记时不完成。
- 文件 + QA + 登记完整时完成。
- B 级 planning 依赖由明确规格满足。
- C 级 prompt-only 只满足规划，不变成正式引用。
- not_required 不进入分母。
- 融合基础资产未齐时显示 blocked。
- 资产新版本 QA 中但旧批准版本存在时仍可按批准版本就绪。

### 11.2 脚本版本

- 当前旧脚本可迁移为 v001。
- 候选版本不改变当前脚本。
- 接受候选后活动版本切换。
- 拒绝候选后当前版本不变。
- 稳定 ID 冲突被拒绝。
- 删除镜头被转换为 deprecated 或进入明确变更集。

### 11.3 双阶段链路

- Storyboard 未接受时 Regulator 不运行。
- Storyboard 接受后才允许 Regulator。
- Regulator 候选未接受时资产依赖不改变。
- 重启后不会重复调用已完成第一阶段。
- DeepSeek/OpenAI 失败不会静默切换。
- SSE 中断后显示可恢复失败，不覆盖项目。
- 文本工作流不会创建图片、TTS 或 Seedance 付费任务。

### 11.4 跳转

- 点击镜头卡主体打开镜头详情。
- 点击内部资产按钮不会触发卡片主体事件。
- 点击角色进入角色资产检查器。
- 点击场景进入场景资产检查器。
- 点击道具进入道具资产检查器。
- 点击融合进入融合检查器并显示基础资产门禁。
- 点击音频进入声音页。
- 缺失资产记录进入总控登记动作。

### 11.5 回归

- 项目管理仍可用。
- 总览流水线仍正常。
- API 设置、Agent 切换和延迟显示不回退。
- Seedance 2.5/2.0 不回退。
- 所有既有 Python 测试通过。
- 所有 JS 测试通过。

---

## 12. 浏览器验收脚本

在：

```text
http://127.0.0.1:8787/
```

执行：

1. 打开“故事与分镜”。
2. 确认脚本面板出现“历史版本”和“脚本优化”。
3. 在脚本尾部输入一个测试句，确认自动保存。
4. 点击“脚本优化”。
5. 确认显示当前 Agent、模型、项目时长、画幅和改动强度。
6. 选择“完整前期包”。
7. 开始优化。
8. 确认页面显示 `video-script-storyboard` 正在运行。
9. 确认运行过程中可看到状态且按钮不可重复提交。
10. 返回后确认出现原文/建议版本差异。
11. 在未接受建议前刷新，确认当前脚本未被覆盖。
12. 重新进入待审阅结果，接受建议版本。
13. 确认随后才出现或运行 `video-asset-regulator` 阶段。
14. 确认资产总控返回资产、等级、依赖和缺口差异。
15. 在未接受监管结果前检查分镜卡，资产目录不得偷偷变化。
16. 接受监管结果。
17. 检查每个分镜卡出现资产准备进度。
18. 检查分镜状态和资产状态分开显示。
19. 选择一个缺失资产的镜头。
20. 展开完整资产目录。
21. 点击缺失角色，确认进入角色资产检查器并聚焦正确动作。
22. 返回故事页，点击缺失场景，确认进入场景资产检查器。
23. 返回故事页，点击缺失道具，确认进入道具资产检查器。
24. 点击被阻塞融合，确认显示基础资产缺口而不是生成按钮。
25. 将一个测试资产推进到 Prompt Approved，确认出现三种生成选择。
26. 不选择生成，确认不会调用图片 API。
27. 模拟 generated-pending-qa，确认镜头资产进度仍未完成。
28. 模拟 QA Approved 但未登记，确认显示“待总控登记”。
29. 完成登记后确认所有关联镜头实时更新。
30. 检查浏览器控制台无异常。

测试中不得真实发起付费媒体生成；使用 fixture 或测试项目状态。

---

## 13. 完成标准

只有以下全部满足才可交付：

- “脚本优化”入口清晰可见。
- 它真实连接 `video-script-storyboard`，并在接受后连接 `video-asset-regulator`。
- 两阶段均有独立运行记录、错误状态和人工审阅。
- Agent 结果不会直接覆盖当前项目。
- 脚本、分镜和监管结果全部版本化。
- 分镜卡显示真实资产目录和实时进度。
- 分镜审批、资产准备、导演包和视频状态含义分离。
- 未完成资产可以一键进入正确资产生产检查器。
- 跳转后显示当前唯一推荐动作。
- Prompt QA 前不显示媒体生成选择。
- Prompt QA 后仍需用户选择生成方式。
- Generated Image QA 和资产总控登记完成前，A/A+ 资产不算 Ready。
- 融合工作不会在基础资产未齐时解锁。
- 镜头导演仍是 Seedance 打包前不可绕过的门禁。
- 所有自动化测试和 30 步浏览器验收通过。

---

## 14. DeepSeek 交付报告格式

完成后按以下格式报告：

```text
1. 当前问题根因
2. 修改文件及职责
3. 新增数据结构和数据库迁移
4. 脚本优化两阶段链路实现
5. 版本和审阅机制
6. 分镜资产目录与状态推导
7. 资产页跳转和生成门禁
8. 自动化测试命令与结果
9. 30 步浏览器验收结果
10. 未完成项、风险和需要用户配置的内容
```

若任何状态缺少证据，应保持 Pending、Missing 或 Blocked，并在报告中说明；不得为了让进度好看而标记完成。
