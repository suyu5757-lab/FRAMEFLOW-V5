# FRAMEFLOW 工作台流程与交互整改任务书

## 1. 任务目标

对 FRAMEFLOW 当前工作台进行一次以“真实可执行生产流程”为中心的交互整改。重点不是调整视觉样式，而是解决以下问题：

1. 项目只能切换，不能重命名、删除、移动或排序。
2. 主导航没有表达 `video-asset-regulator` 控制下的完整资产生产路径，用户找不到角色、场景、道具、融合资产及其提示词的制作入口。
3. 总览页生产流水线使用阶段序号和单一 `stageIndex` 推断完成情况，可能在真实门禁没有完成时显示错误的“已完成”状态。
4. “导演指令”用途不明确，生成的任务包缺少可见预览、复制、交给工作台 Agent 或外部 ChatGPT 的明确出口。
5. “项目就绪门”与生产流水线重复展示，应合并为一个真实状态面板。
6. “下一步任务”目前只能复制 Skill 任务，不能直接把用户带到对应执行位置。

最终目标：用户打开项目后，应一眼看到当前处于哪一步、为什么未完成、下一项应做什么，并能通过一次点击进入正确工作区执行。

---

## 2. 项目现状与技术边界

当前项目是本地优先的原生前端 + FastAPI 后端：

- 前端入口：`index.html`
- 前端主逻辑：`app.js`
- 助手逻辑：`assistant.js`
- API 客户端：`api.js`
- 样式：`styles.css`
- FastAPI：`server.py`
- 数据模型：`frameflow/schemas.py`
- SQLite：`frameflow/database.py`
- 工作流门禁：`frameflow/workflows.py`
- 测试：`tests/test_server.py`
- 启动入口：`启动工作台.bat`

实施约束：

- 保留原生 ES Modules，不引入 React/Vue 等框架。
- 不覆盖或回退工作区已有改动。
- 所有项目状态必须由项目数据、资产文件、QA、注册、审批和任务状态推导，不能依赖手工维护的 `p.stage`。
- 保持 `PRJ/C/S/P/BLEND/SH/PROMPT/GEN/DIR_SH` 稳定 ID。
- A/A+ 资产不可仅凭 `status: ready` 判定为生产就绪。
- 付费生成前必须人工确认。
- 不允许失败后静默切换供应商或模型。
- Seedance 2.5 保持默认，2.0/2.0 Fast 保持兼容且不自动迁移。

---

## 3. 必须遵守的资产总控业务顺序

资产生产必须按照 `video-asset-regulator` 的控制顺序实现：

```text
故事与分镜
  → 资产总控：读取分镜、提取资产、分级、依赖审计、下游路由
  → 角色 / 场景 / 道具设计与 Prompt QA
  → 用户生成方式确认
  → 工作台生成或外部 ChatGPT 生成
  → Generated Image QA
  → 资产总控登记
  → 基础资产完整性门禁
  → 融合生产与融合 QA
  → 镜头导演
  → Seedance 打包
  → 视频生成与视频 QA
  → 声音与时间线
  → 最终交付
```

`video-asset-regulator` 只负责审计、分级、门控、登记与路由，不直接替代以下执行技能：

| 生产内容 | 负责 Skill |
|---|---|
| 剧本与分镜 | `video-script-storyboard` |
| 资产提取、分级、缺口、门禁、登记 | `video-asset-regulator` |
| 角色规格、角色提示词与角色图片 QA | `video-character-design-director` |
| 场景规格、场景提示词与场景图片 QA | `video-scene-design-director` |
| 道具规格、道具提示词与道具图片 QA | `video-prop-design-director` |
| 角色/场景/道具关系融合 | `video-fusion-production-director` |
| 镜头语言、连续性和视频 QA | `video-shot-director` |
| Seedance 执行包 | `seedance-shot-packager` |
| 对白、配音、音乐、音效和授权 | `voice-controller` |

不得让用户从“资产总控”直接跳过角色/场景/道具 Prompt QA 进入图片生成，也不得从资产就绪直接跳过镜头导演进入 Seedance 打包。

---

## 4. 项目管理整改

### 4.1 入口

在顶部 `select#projectSelect` 右侧增加清晰的“管理项目”按钮，不要把管理行为塞进原生 `<select>`。

点击后打开项目管理对话框，列出所有项目。每一行至少显示：

- 项目名称
- 项目 ID（短格式即可）
- 创建时间或最后更新时间
- 当前真实阶段
- 当前项目标记
- 上移
- 下移
- 重命名
- 删除
- 切换到此项目

### 4.2 排序与移动

- 使用 `state.projects` 数组顺序作为本地显示顺序。
- 上移/下移后立即更新项目选择器并保存。
- 当前项目移动后仍保持选中。
- 第一项的“上移”和最后一项的“下移”应禁用。
- 后续如需跨设备保持顺序，可在项目文档增加 `sortOrder`，但第一版不得因服务端缺失排序字段而阻塞本地功能。

### 4.3 重命名

- 支持行内编辑或单独确认对话框。
- 名称去除首尾空格，不能为空，最长 100 字符。
- 修改后同步更新 `projectSelect`、总览标题、本地存储和 SQLite 项目文档。
- 不修改项目稳定 ID。

### 4.4 删除

- 不允许删除最后一个项目；至少保留一个项目，或删除后自动创建一个明确标识的空白项目。
- 删除前显示项目名称和不可撤销影响。
- 删除当前项目后，自动切换到相邻项目并重新渲染。
- 增加后端 `DELETE /api/projects/{project_id}`，只删除数据库中的项目记录和与其明确关联的数据库记录。
- 第一版不要自动递归删除项目素材目录。若素材目录仍存在，应返回或记录“素材保留，可人工清理”，避免不可恢复误删。
- 删除接口应处理任务、任务事件、对话、消息、工作流运行、审批和项目记录之间的引用顺序。
- 删除前如果存在 `queued/running/awaiting_confirmation` 任务，返回 409，要求先取消任务。

### 4.5 API 客户端

在 `api.js` 增加：

```js
deleteProject: id => api(`/api/projects/${encodeURIComponent(id)}`, {
  method: 'DELETE'
})
```

---

## 5. 导航与资产生产入口整改

### 5.1 主导航应表达生产顺序

保留主导航的精简结构，但调整标签和辅助说明，使用户能理解入口职责：

```text
总览

前期
  故事与分镜
  资产生产

制作
  镜头导演
  配音与声音
  生成工作台

后期
  质检与交付
```

将“资产工坊”改为“资产生产”或“资产与提示词”，并增加未完成数量。进入该页后必须明确出现以下子流程，而不是只显示资产卡片：

1. 资产总控
2. 角色设计
3. 场景设计
4. 道具设计
5. Prompt QA
6. 生成方式选择
7. Generated Image QA
8. 资产登记
9. 融合生产

### 5.2 资产生产页信息架构

资产页建议拆为三层：

#### A. 顶部：资产生产导航条

显示角色、场景、道具、融合的真实状态和数量。点击某一阶段后自动过滤对应资产，并滚动到任务列表。

#### B. 中部：下一项可执行动作

用一个明确行动卡展示：

- 当前应执行的 Skill
- 为什么现在应执行它
- 输入来源
- 预期输出
- 被哪些门禁阻塞
- “在工作台 Agent 中执行”
- “复制任务指令”

#### C. 下部：资产卡片与资产检查器

每张资产卡片必须显示：

- 稳定 ID、名称、类型、等级和版本
- 当前状态
- Prompt 状态
- 文件状态
- Generated Image QA 状态
- 资产总控登记状态
- 依赖与关联镜头
- 当前唯一推荐动作

点击资产卡片后打开检查器，不要通过连续 `confirm()` 让用户猜流程。

### 5.3 每个资产的生产动作

根据状态只展示当前可执行动作：

| 条件 | 推荐动作 |
|---|---|
| 尚无设计规格/Prompt | 使用对应设计 Skill 制作 Prompt |
| Prompt 待 QA | 运行 Prompt QA |
| Prompt QA 不通过 | 修订 Prompt，不允许使用旧 Prompt 生成 |
| Prompt QA 已批准、未选择生成方式 | 选择生成方式 |
| 选择工作台生成 | 进入生成工作台并预填资产、Prompt、数量 |
| 选择外部 ChatGPT | 复制外部生成包，可同时打开 ChatGPT 网页 |
| 选择暂不生成 | 保存批准 Prompt，但资产保持未就绪 |
| 图片已返回 | 运行对应领域 Generated Image QA |
| QA 通过但未登记 | 由资产总控登记 |
| 文件 + QA + 登记完整 | 标记生产就绪 |

### 5.4 外部 ChatGPT 生成包

增加明确按钮：

- `复制 Prompt`
- `复制完整生成包`
- `复制并打开 ChatGPT`

完整生成包至少包含：

```text
项目：
资产 ID：
资产类型：
Prompt 版本：
生成目标：
引用图片角色：
最终 Prompt：
Must preserve：
Must avoid：
数量：
画幅 / 尺寸：
返回文件命名：
返回后状态：generated-pending-qa
```

打开地址使用 `https://chatgpt.com/`。由于不能可靠地把长 Prompt 自动注入外部页面，必须先复制到剪贴板，再打开新标签，并提示“已复制，请在 ChatGPT 粘贴”。如果浏览器阻止弹窗，仍需保留复制成功结果。

### 5.5 工作台 Agent 执行

为 `assistant.js` 增加可调用的公开方法，例如：

```js
openAssistantWithPrompt(text, skillId)
```

点击“在工作台 Agent 中执行”时：

- 打开助手侧栏。
- 把任务内容预填到输入框。
- 将对应 `skill_id` 传给 `/api/assistant/stream`，不能永远传 `null`。
- 不自动发送，用户确认后再发送。
- 助手返回结构化补丁时仍需用户接受后才写入项目。

---

## 6. 生产流水线真实状态模型

### 6.1 禁止继续使用的逻辑

不得使用以下简化逻辑判断完成：

```js
i < stageIndex(project)
```

它只能表达单一当前位置，不能证明前一步真实通过，也无法表示未开始、进行中、阻塞和无需执行。

### 6.2 统一阶段状态

增加纯函数：

```js
deriveWorkflowStages(project, tasks)
```

每个阶段返回：

```js
{
  id: 'character',
  state: 'not_started' | 'in_progress' | 'completed' | 'blocked' | 'not_required',
  label: '角色设计',
  reason: 'C001 缺 FACE_neutral，Prompt QA 尚未通过',
  completed: 2,
  total: 5,
  routeView: 'assets',
  routeFilter: '角色',
  skillId: 'video-character-design-director'
}
```

视觉规则：

- `completed`：青绿色对号。
- `in_progress`：黄色圆点或半圆进度标记。
- `not_started`：红色空心圆或红点。
- `blocked`：红色锁或感叹号，并显示阻塞原因。
- `not_required`：灰色横线，不参与完成率。

颜色之外必须有图形和文字，避免只依赖颜色传达状态。

### 6.3 各阶段确定性规则

#### 故事与分镜

- `completed`：`script` 非空、存在镜头、所有镜头具备稳定 `SHxxx`、目的、动作、景别、摄影机和时长。
- `in_progress`：脚本或镜头已有部分内容，但上述字段不完整。
- `not_started`：脚本为空且镜头为空。

#### 资产总控

- `completed`：分镜已完成；已经提取资产；所有资产具备稳定 ID、类型、等级、负责 Skill 和依赖信息；A/A+ 缺口已明确登记。
- `in_progress`：已有部分资产，但缺等级、路由或依赖。
- `blocked`：分镜未完成。
- 不得因为 `assets.length > 0` 就直接完成。

建议在项目中增加：

```js
assetRegulator: {
  version: 1,
  status: 'draft|approved|revision_required',
  auditedAt: null,
  missingA: [],
  dependencyVersion: 'v01'
}
```

#### 角色 / 场景 / 道具

- 只检查对应类型的必需资产。
- `completed`：该阶段所有必需 A/A+ 资产均满足 `assetProductionReady()`。
- `in_progress`：存在规格、Prompt、计划、文件或 QA 中间产物，但尚未全部 Ready。
- `not_started`：存在此类必需资产，但所有生产字段均为空。
- `not_required`：资产总控明确记录该项目不需要此类资产；不能仅根据数组为空自行假设。

#### 融合生产

- 基础角色、场景、道具未就绪时为 `blocked`。
- 资产总控明确不需要融合时为 `not_required`。
- 需要融合时，只有融合文件存在、Fusion Generated Image QA 通过且已登记才 `completed`。
- Prompt 包完成不能等同融合资产完成。

#### 镜头导演

- 所有必需资产门禁通过后才可开始。
- 每个镜头需要独立的 `DIR_SHxxx` 包或 `directorPackage` 登记。
- 仅将镜头 `status` 手工改为 `ready` 不能证明镜头导演阶段完成。
- 所有目标镜头均有已批准导演包后才 `completed`。

#### 声音控制

- 使用现有 `audioSummary(project)`，但必须检查声音是否 `not-required`、已提供或已批准。
- 需要声音而没有制作来源时必须 `blocked`，不能静默 Ready。

#### Seedance 打包

- 必须已有对应镜头导演包。
- 必须已有按镜头关联的 Seedance 包版本。
- 2.5 与 2.0 包分别计算，旧项目保持原模型版本。
- 包建立不等于视频 QA 已通过；生成与 QA 可作为节点内子状态展示。

### 6.4 A/A+ 资产生产就绪条件

必须同时满足：

```js
function assetProductionReady(asset) {
  return Boolean(
    ['ready', 'approved'].includes(asset.status) &&
    (asset.filePath || asset.artifactId) &&
    asset.qaDecision === 'Approved' &&
    asset.regulatorRegistered === true
  );
}
```

对于 B/C 资产也不得只显示误导性的“已批准”，应区分规划就绪和文件就绪。

---

## 7. 总览页重排

### 7.1 合并生产流水线与项目就绪门

删除独立的“项目就绪门”卡片，把以下信息合并到生产流水线：

- 总完成率，仅统计非 `not_required` 阶段。
- 每个阶段的真实状态图标。
- `完成项 / 总项`。
- 未完成原因。
- 点击后的跳转目标。
- 当前阻塞摘要。

生产流水线头部可显示：

```text
整体 22% · 2 个阶段完成 · 1 个阻塞 · 当前建议：完善 C001 角色资产
```

不要再显示一个与流水线重复的圆环卡片。

### 7.2 流水线节点交互

点击节点后的默认行为必须是“进入执行位置”，不能只在后台复制文本：

| 节点 | 跳转 |
|---|---|
| 故事与分镜 | `story` |
| 资产总控 | `assets`，定位资产总控卡 |
| 角色设计 | `assets`，过滤角色 |
| 场景设计 | `assets`，过滤场景 |
| 道具设计 | `assets`，过滤道具 |
| 融合生产 | `assets`，过滤融合 |
| 镜头导演 | `shots` |
| 声音控制 | `audio` |
| Seedance 打包 | `generate` |

节点内部再提供“复制 Skill 任务”次级按钮或执行面板。

### 7.3 “导演指令”改名与明确用途

将“导演指令”改为“Agent 任务编排”或“创作任务指令”。说明文字必须写清：

> 根据当前项目和所选 Video Skill 生成任务指令。可以交给工作台 Agent 执行，也可以复制到外部 ChatGPT；它不会直接产生图片或视频。

输出不应只用 Toast 表示“已复制”。增加可见结果区，显示：

- 目标 Skill
- 完整任务指令（只读 textarea 或可编辑 textarea）
- 复制任务指令
- 在工作台 Agent 中执行
- 复制并打开 ChatGPT

模板按钮应明确映射：

- 优化故事 → `video-script-storyboard`
- 资产体检 → `video-asset-regulator`
- 角色提示词 → `video-character-design-director`
- 场景提示词 → `video-scene-design-director`
- 道具提示词 → `video-prop-design-director`
- 镜头导演 → `video-shot-director`
- Seedance 打包 → `seedance-shot-packager`

### 7.4 下一步任务可执行跳转

任务行整体可点击，并显示“进入执行 →”。点击后：

- 切换 `activeView`。
- 更新左侧导航选中状态。
- 应用对应资产类型筛选。
- 选中具体资产或镜头。
- 滚动到执行面板。
- 不自动复制，不自动调用 API，不自动产生费用。

任务对象建议统一为：

```js
{
  id: 'NEXT_C001_PROMPT',
  title: '完善 C001 角色提示词',
  reason: '缺 FACE_neutral，Prompt QA 尚未完成',
  priority: 'blocking|high|normal',
  view: 'assets',
  assetId: 'C001',
  filter: '角色',
  skillId: 'video-character-design-director',
  action: 'prepare_prompt'
}
```

增加纯函数 `deriveNextTasks(project, tasks)`，按以下优先级输出：

1. 上游阻塞。
2. 缺失 A/A+ 资产。
3. Prompt QA 或 Generated Image QA。
4. 待资产总控登记。
5. 融合依赖。
6. 镜头导演包。
7. Seedance 包或生成任务。
8. 声音授权与 QA。
9. 最终交付。

---

## 8. 建议数据结构扩展

在兼容旧项目的前提下，为资产补充可选字段：

```js
{
  id: 'C001',
  name: '角色名称',
  type: '角色',
  grade: 'A',
  required: true,
  status: 'missing',
  skill: 'character',
  version: 1,
  dependencies: ['SH003'],
  prompt: '',
  promptVersion: 'v01',
  promptQaDecision: 'Pending',
  generationChoice: 'user-confirmation-required',
  generationSource: null,
  artifactId: null,
  filePath: null,
  qaOwner: 'video-character-design-director',
  qaDecision: 'Pending',
  regulatorRegistered: false,
  approvalId: null
}
```

允许的 `generationChoice`：

```text
user-confirmation-required
codex-imagegen-approved
external-chatgpt-selected
generation-deferred
```

旧项目迁移原则：

- 缺失字段补默认值，不覆盖原字段。
- 旧 `status: ready` 的 A/A+ 资产如果缺少文件、QA 或登记，界面应显示“历史 Ready / 门禁未通过”，真实流水线不得判为完成。
- 不自动伪造 `qaDecision: Approved` 或 `regulatorRegistered: true`。

需要同步更新 `frameflow/schemas.py`。由于 `assets` 当前是 `list[dict]`，可以先保持兼容，但应增加前端正规化函数 `normalizeProject()` / `normalizeAsset()`。

---

## 9. 推荐代码拆分

当前 `app.js` 已较大，避免继续把所有逻辑塞进单行函数。建议新增：

```text
workflow-state.js    # deriveWorkflowStages / deriveNextTasks / 门禁解释
project-manager.js   # 项目管理对话框和操作
asset-workspace.js   # 资产生产页、筛选、检查器、生成选择
task-packages.js     # Skill 任务包和外部 ChatGPT 生成包
```

最低限度也应把以下现有函数改为多行、可测试形式：

- `stageIndex`
- `pipeline`
- `copySkillTask`
- `renderOverview`
- `renderAssets`
- `bindPipeline`
- `bindView`

不要继续使用大量内联 `onclick` 或依赖 DOM 顺序定位元素。

---

## 10. 后端与持久化要求

### 10.1 项目删除

新增：

```http
DELETE /api/projects/{project_id}
```

响应示例：

```json
{
  "ok": true,
  "project_id": "...",
  "project_files_preserved": true
}
```

### 10.2 项目版本冲突

重命名、排序或资产状态修改仍通过现有项目 PUT 与 `expected_revision` 机制保存。409 冲突不得被静默覆盖。

### 10.3 工作流运行

“在工作台 Agent 中执行”应尽量使用现有：

```http
POST /api/workflow-runs
POST /api/assistant/stream
```

助手请求必须携带真实 `skill_id`。后端继续运行确定性门禁，模型输出不得直接绕过门禁写入项目。

---

## 11. 测试要求

### 11.1 单元测试

至少覆盖：

- 空项目所有阶段均不会误显示完成。
- 只有脚本没有镜头时，故事阶段为进行中。
- A 级资产仅 `status: ready` 但无文件时，角色/场景/道具阶段不完成。
- A 级资产有文件但 QA Pending 时不完成。
- A 级资产有文件且 QA Approved、未登记时不完成。
- A 级资产满足文件 + QA + 登记后才完成。
- 基础资产未完成时融合阶段阻塞。
- 没有导演包时 Seedance 阶段不完成。
- `not_required` 阶段不计入整体完成率。
- 下一步任务优先返回上游 A/A+ 阻塞项。

### 11.2 项目管理测试

- 可重命名当前和非当前项目。
- 可上移、下移，刷新后顺序保持。
- 删除非当前项目后选中项不变。
- 删除当前项目后自动切换。
- 最后一个项目不可被删除或会建立明确空白项目。
- 有运行中/待确认任务的项目删除返回 409。
- 删除项目不递归删除素材目录。

### 11.3 交互验收

手工或浏览器自动化完成：

1. 新建空项目。
2. 总览显示故事阶段红色未开始，不能出现错误对号。
3. 点击故事阶段进入“故事与分镜”。
4. 建立脚本和镜头后，资产总控成为下一项。
5. 点击角色阶段进入资产页并自动过滤角色。
6. 能在角色资产卡中找到“制作提示词”。
7. Prompt QA 通过后出现三种生成选择。
8. “复制并打开 ChatGPT”先复制再打开 `https://chatgpt.com/`。
9. 上传图片后状态为 `generated-pending-qa`，不能直接 Ready。
10. QA 通过且总控登记后，该资产才显示完成。
11. 总览不再单独显示重复的“项目就绪门”。
12. 点击“下一步任务”直接到对应执行区域。

### 11.4 回归测试

- 工作台仍从 `http://127.0.0.1:8787/` 启动。
- 直接打开本地 `index.html` 会跳转到服务地址。
- OpenAI/DeepSeek Agent 配置、模型选择、连接检测和延迟显示不回退。
- DeepSeek 严格结构化工具 Schema 不再出现 `unknown variant object`。
- 新建项目取消不会触发表单必填校验。
- Seedance 2.5 默认和 2.0 兼容设置保持可用。
- 现有后端测试全部通过。

---

## 12. 完成标准

以下条件全部满足才可交付：

- 项目选择器旁可以进入完整项目管理，重命名、排序、移动和删除均可用。
- 用户不需要猜测在哪里制作角色、场景、道具、融合资产和提示词。
- 流水线状态完全由真实项目数据推导，未完成绝不显示对号。
- 未开始、进行中、阻塞、已完成和无需执行有清晰且无障碍的区分。
- 项目就绪门已合并到生产流水线，没有重复展示。
- Agent 任务编排区能预览、复制、交给工作台 Agent 或外部 ChatGPT。
- 下一步任务点击后进入正确执行窗口，不只是复制文本。
- 外部生成返回后必须经过领域 QA 和资产总控登记才能 Ready。
- `video-shot-director` 仍是 Seedance 打包前不可绕过的强制门。
- 所有新增和既有测试通过，浏览器控制台无错误。

---

## 13. 建议实施顺序

1. 先建立 `deriveWorkflowStages()`、`deriveNextTasks()` 及测试。
2. 用真实状态重写生产流水线，合并并移除独立项目就绪门。
3. 实现节点和下一步任务的执行跳转。
4. 重构资产生产页，加入 Prompt、QA、生成选择和登记路径。
5. 改造 Agent 任务编排区及外部 ChatGPT 复制流程。
6. 实现项目管理对话框和后端删除接口。
7. 完成旧项目正规化迁移与回归测试。
8. 使用浏览器逐条执行第 11 节验收流程。

执行过程中若业务数据不足以确定阶段是否完成，应显示“需要确认”或“进行中”，不得乐观地显示已完成。
