# FRAMEFLOW 第二轮整改：DeepSeek 本地执行总指挥计划

> 本文件是可直接交给本地部署 DeepSeek Agent 执行的工程任务书。
>
> DeepSeek 的职责是实际检查、修改、测试和浏览器验收；不得只返回建议或重新制定计划。
>
> 用户要求：重做项目管理、移除所有旧计划并导入《解毒者》、优化生产流水线横向操作、升级 Agent 任务编排区域。

---

## 0. 执行身份与工作边界

你是本项目的执行工程师。请直接在以下项目根目录工作：

```text
D:\11067\Codex\2026-08-13\video-2
```

《解毒者》源资料目录：

```text
C:\Users\11067\Desktop\AIGC\AIGC—video\jiedu
```

必须先完整阅读：

```text
D:\11067\CodexHome\skills\video-asset-regulator\SKILL.md
D:\11067\CodexHome\skills\video-asset-regulator\references\video-production-handoff-contract.md
D:\11067\Codex\2026-08-13\video-2\FRAMEFLOW_WORKBENCH_UX_REFACTOR_TASK.md
C:\Users\11067\Desktop\AIGC\AIGC—video\jiedu\解毒者_整合制作文档_v1_当前资产整理版.md
```

需要重点检查的当前代码：

```text
app.js
project-manager.js
workflow-state.js
asset-workspace.js
task-packages.js
assistant.js
api.js
index.html
styles.css
server.py
frameflow/schemas.py
frameflow/database.py
frameflow/workflows.py
tests/
```

### 严格限制

1. 不得执行 `git reset --hard`、`git checkout --` 或其他回退用户修改的操作。
2. 不得批量或递归删除目录。
3. 禁止使用：`del /s`、`rd /s`、`rmdir /s`、`Remove-Item -Recurse`、`rm -rf`。
4. 删除项目记录不等于删除素材文件。第一版必须保留项目素材目录。
5. 不得删除 API 凭据、供应商配置或能力绑定。
6. 不得把 API Key 写入 SQLite、浏览器、日志、导出包或本任务文件。
7. 不得伪造 Prompt QA、Generated Image QA、资产登记、镜头导演或 Seedance 完成状态。
8. 不得因为已有 PNG 就自动假设它可以作为正式 Seedance 引用；必须读取对应 QA/注册文档。
9. 工作流阶段顺序由 `video-asset-regulator` 决定，用户不能拖动改变业务顺序。
10. 每完成一个阶段都必须运行相关测试，不要把所有验证拖到最后。

---

## 1. 已确认的当前事实

开始实施前请自行重新核验，不要直接相信本节；本节仅作为对照。

### 1.1 当前工作台

- 当前为原生 ES Modules + FastAPI + SQLite。
- 项目管理入口为 `button#manageProjectsBtn`。
- 项目管理主体位于 `project-manager.js`。
- 当前项目管理已有切换、上移、下移、重命名和删除的初步代码，但用户反馈实际不可使用。
- 当前生产状态推导位于 `workflow-state.js`。
- 当前 Agent 编排区位于 `app.js` 的 `agentOrchestrator()`。
- 当前数据库 `data/frameflow.db` 中已观察到 9 个重复旧项目。
- 当前没有后台任务记录，但删除前必须再次查询。
- 前端仍可能从 `localStorage['frameflow-state']` 恢复旧项目，因此只清 SQLite 不足以完成清理。

### 1.2 《解毒者》源资料

主项目规格：

```text
项目：解毒者
类型：都市悬疑、刑侦医疗、人物成长
首个验证目标：90 秒概念预告
画幅：16:9
目标风格：写实电影感
视觉系统：现代东海冷灰毒理刑侦 + 湘西青绿潮湿历史悬疑
目标生成器：Seedance 2.5
```

主整合文档包含：

- 第一季故事总纲。
- 角色清单与角色资产。
- 第一集场景剧本。
- 20 个稳定镜头的 90 秒概念预告分镜（SH001–SH020）。
- 高风险镜头拆分建议。
- 可信性与内容安全边界。
- 角色、场景和道具实物盘点。
- QA、注册、失败版本和版本优先规则。
- 镜头—资产依赖。
- 当前生产队列。
- 下一次生成选择门。

源目录当前包含：

- 14 张规范命名角色 PNG，覆盖 C001–C005。
- S001、S002 的主场景、top-down、机位规划和独立机位 PNG。
- P001 旧钢笔 PNG。
- 一张通用文件名图片，身份和用途未确认，不能正式注册。
- 多份外部 ChatGPT 生成包、Prompt QA、图片 QA 和资产注册 Markdown。
- 一个原始 DOCX。
- 没有音频文件，音频状态应为 `externally-pending`。

---

## 2. 总体交付目标

完成后，工作台必须达到以下状态：

1. 顶部项目区不再只是一个难用的原生下拉框；用户可以打开完整项目中心。
2. 项目中心支持选择、搜索、排序、重命名、复制为模板、导入、导出、删除和查看项目摘要。
3. 所有旧的“零号计划 · 雨夜来信”项目都从浏览器状态和 SQLite 项目列表中移除。
4. 工作台中只保留并默认选中一个正确导入的《解毒者》项目。
5. 《解毒者》的项目规格、20 个镜头、逻辑资产、实物文件、QA/注册状态、缺失资产、依赖关系和下一步队列均可追溯。
6. 流水线不显示原生横向滚动条，但支持鼠标拖动、触控滑动、触控板横向滚动、Shift+滚轮和键盘导航。
7. 点击流水线节点进入对应工作区；节点状态仍由真实数据推导，用户不得直接手工改成完成。
8. Agent 编排区升级为可理解、可预览、可执行、可追踪、可复用的任务控制台。
9. DeepSeek、OpenAI 等 Agent 仍可以按设置切换；失败时不静默切换模型。
10. 所有修改通过单元测试、后端测试、JavaScript 检查和浏览器验收。

---

## 3. 实施阶段 A：基线、备份与故障定位

### A1. 检查工作区

执行并记录：

```powershell
git status --short
python -m pytest -q
npm test
```

如果 `npm test` 不存在，读取 `package.json` 后使用其中真实脚本，不要猜命令。

检查浏览器控制台，重点确认点击“管理项目”时是否存在：

- 模块导入失败。
- `projectManager` 尚未初始化。
- 对话框 `showModal()` 异常。
- 事件被透明元素覆盖。
- CSS `z-index` 或 `pointer-events` 问题。
- `dialog` 插入 DOM 后未获得正确布局。
- 旧缓存仍加载 `app.js?v=2.5.3`。

### A2. 建立可恢复备份

在项目根目录新建单一明确备份文件，不要复制或删除整个目录：

```text
data/frameflow.before-jiedu-YYYYMMDD-HHMMSS.db
```

使用 `Copy-Item -LiteralPath` 复制 `data/frameflow.db`。如果 WAL 正在使用，应先通过 SQLite backup API 或短暂停止本地服务，再复制数据库、`-wal` 和 `-shm` 对应状态；优先使用 SQLite 自带 backup API 生成一致性备份。

同时通过浏览器开发者工具或临时只读脚本导出：

```text
localStorage['frameflow-state']
```

保存为单一备份 JSON：

```text
data/frameflow-localstorage-before-jiedu-YYYYMMDD-HHMMSS.json
```

不要把备份文件加入 Git。

### A3. 记录当前项目清单

读取 SQLite 和 localStorage 的项目 ID、名称、版本、更新时间。确认是否全部为旧的“零号计划 · 雨夜来信”或其乱码副本。

如果发现任何不是旧计划的项目，停止项目清理并向用户报告，因为“删除所有计划”可能误删额外项目。

当前阶段禁止删除任何内容。

### A 阶段验收

- 基线测试结果已记录。
- 数据库和 localStorage 都有可恢复备份。
- 已确认旧项目清单。
- 已定位“管理项目不可使用”的具体错误，而不是只调整 CSS。

---

## 4. 实施阶段 B：重做顶部项目区与项目中心

### B1. 顶部入口重构

不要继续把原生 `<select>` 作为主要项目入口。改为：

```text
[状态点] [当前项目名称 ▾] [项目中心]
```

建议结构：

```html
<div class="project-switcher">
  <span class="project-dot"></span>
  <button id="projectQuickSwitch" class="project-current">当前项目名称 <span>⌄</span></button>
  <button id="manageProjectsBtn" class="mini-button">项目中心</button>
  <span id="saveState"></span>
</div>
```

`projectQuickSwitch` 打开轻量下拉面板，只负责：

- 搜索项目。
- 最近项目。
- 一键切换。
- “进入项目中心”。

完整管理操作全部放入项目中心，避免顶部拥挤。

可以保留隐藏的 `select#projectSelect` 作为兼容层，但不能再是用户主要操作入口。

### B2. 项目中心布局

将当前简单列表对话框重构为双栏项目中心：

```text
┌──────────────────────────────────────────────────────┐
│ 项目中心        [搜索] [导入] [新建]                │
├───────────────────────┬──────────────────────────────┤
│ 项目列表              │ 当前选中项目详情             │
│                       │ 名称 / ID / 阶段 / 时间       │
│ ● 解毒者              │ 资产/镜头/阻塞摘要            │
│                       │                               │
│                       │ [打开] [重命名] [复制为模板]  │
│                       │ [导出] [上移] [下移] [删除]  │
└───────────────────────┴──────────────────────────────┘
```

项目列表必须支持：

- 项目名称搜索。
- 当前项目标记。
- 真实阶段与阻塞数。
- 最后更新时间。
- 单击选择、双击打开。
- 上移/下移或拖动排序。
- 键盘上下选择和 Enter 打开。

### B3. 必要功能定义

#### 选择/打开

- 更新 `state.currentId`。
- 更新顶部项目名称。
- 清空不属于新项目的 `selectedShot`、资产筛选和临时 Agent 输出。
- 同步 localStorage。
- 加载该项目任务。
- 渲染总览。

#### 重命名

- 名称去除首尾空格，不能为空，最多 100 字符。
- 不修改项目 ID。
- 保存到 SQLite 并处理 409 revision 冲突。

#### 排序

- 使用 `sortOrder`。
- 前端和后端列表统一按 `sortOrder ASC, updated_at DESC`。
- 拖动排序只是项目显示顺序，不改变项目内容。

#### 复制为模板

不要直接复制 artifactId、任务、审批或已批准状态。复制为模板时：

- 新建 UUID。
- 名称默认添加“副本”。
- 保留故事、脚本、镜头结构、Prompt 和制作规格。
- 清空 `tasks`、`generations`、`seedancePackages`、`provider_task_id`。
- 资产文件只作为来源说明，不得把旧项目 artifactId 伪装成新项目所有。
- QA、登记和 Ready 状态重置为待确认。
- 在确认对话框中明确说明“复制的是制作模板，不复制已批准产物所有权”。

#### 导出

提供：

- 导出当前项目 JSON。
- 导出当前项目制作报告 Markdown。
- 导出全部项目索引 JSON（只含项目文档与引用清单，不含 API Key）。
- 大型媒体不直接塞入 JSON。

#### 导入

- 支持 `.json` 和 `.frameflow.json`。
- 先调用迁移预览。
- 显示冲突、资产数、镜头数和来源版本。
- 用户确认后才导入。

#### 删除

- 显示项目名称、项目 ID、任务数量和素材保留说明。
- 存在 `queued/running/awaiting_confirmation` 任务时后端返回 409。
- 删除数据库关联记录，但保留素材目录。
- 禁止删除最后一个项目，除非“原子替换项目”流程已经验证新项目存在。

### B4. 修复当前不可用问题

必须先写出根因再修改。至少验证：

1. `initProjectManager(ctx)` 是否在 `bindShell()` 给按钮绑定之前完成。
2. 当前代码中 `bindShell()` 先执行，而 `projectManager = initProjectManager(ctx)` 后执行；虽然点击发生在初始化之后通常可用，但应消除时序脆弱性。
3. 推荐顺序：先创建 `projectManager`，再绑定 shell，或在点击时惰性获取且做空值保护。
4. `dialog` 应有明确 `id`、`aria-labelledby`、表单或按钮类型。
5. 打开前关闭其他已打开 dialog，避免 `showModal()` 状态异常。
6. 给失败显示可见错误，不能让按钮无反应。

建议初始化：

```js
function init() {
  syncProjectSelect();
  const ctx = createAppContext();
  assetWorkspace = initAssetWorkspace(ctx);
  projectManager = initProjectManager(ctx);
  bindShell();
  render();
  // ...
}
```

### B 阶段验收

- “项目中心”按钮每次都能打开。
- 项目选择和详情同步。
- 搜索、切换、重命名、排序、复制为模板、导入、导出、删除均可用。
- 所有失败有当前页面可见反馈。
- 关闭项目中心不触发表单校验。
- 刷新页面后当前项目和顺序保持。

---

## 5. 实施阶段 C：《解毒者》安全导入与旧项目原子替换

### C1. 不得先删除旧项目

正确顺序：

```text
读取源资料
→ 构建候选 ProjectDocument
→ 校验文件与哈希
→ 导入候选项目
→ 重新读取并验证候选项目
→ 将前端切换到候选项目
→ 删除所有确认过的旧项目
→ 清理 localStorage 旧项目条目
→ 最终重启与验收
```

若任何一步失败，旧项目必须仍可恢复。

### C2. 创建一次性导入器

建议新增：

```text
scripts/import_jiedu_project.py
tests/test_jiedu_import.py
```

导入器必须：

- 默认只做 dry-run。
- `--apply` 才实际写入。
- 固定项目 ID，例如 `PRJ001_JIEDU`；如现有 Schema 限制，可使用 UUID，但文档内保留 `projectCode: PRJ001`。
- 支持 `--source` 指定源目录。
- 支持 `--database` 指定数据库。
- 拒绝源目录不存在、主文档不存在或文件签名异常。
- 只读取源目录顶层明确支持的 `.md/.docx/.png` 文件。
- 忽略 `.audit_*`、`.tmp_*` 等临时目录。
- 计算 SHA-256。
- 生成导入预览，包括将创建的项目、资产、文件、缺口和警告。
- 不删除源目录文件。
- 不覆盖同名目标文件；冲突时比较哈希并版本化。

### C3. 项目文档映射

建立项目：

```json
{
  "id": "PRJ001_JIEDU",
  "name": "解毒者 · 90秒概念预告",
  "ratio": "16:9",
  "duration": 90,
  "generator": "Seedance 2.5",
  "brief": "从整合文档的一句话故事读取，不自行改写事实",
  "script": "保留90秒概念预告的叙事说明与安全边界",
  "projectCode": "PRJ001",
  "sourceRoot": "仅供本地审计，不进入公开导出",
  "contentSafety": {
    "noActionablePoisonInstructions": true
  }
}
```

如果 `ProjectDocument` 不允许新字段，更新 `frameflow/schemas.py`，但保持旧项目兼容。

### C4. 镜头映射

从主整合文档第 6 节导入 SH001–SH020：

- 保留镜头 ID。
- 保留时长。
- 将“画面”映射到 `action`。
- 将“声音”映射到镜头音频意图字段，例如 `audioIntent`。
- 给镜头增加 `sourceSection`。
- 高风险镜头 SH005、SH006、SH007、SH008、SH018 增加 `risk` 和 `riskMitigation`。
- 不得自行编造主文档没有明确给出的摄影机、景别或演员动作。
- 缺失字段设置为空或 `needs-director-review`，并让故事/镜头阶段准确显示待完善。
- 所有镜头初始不得标记视频 QA Ready。
- 所有镜头初始不得拥有虚构的导演包。

### C5. 逻辑资产映射

#### 角色

导入 C001–C008：

- C001–C005：根据 QA/注册文档逐项核实 DES/FACE/EXPR 文件。
- C006 小林：B，missing。
- C007 死者：B，missing。
- C008 金白：A，missing，阻塞 SH020。

对于 C001–C005，只有当以下条件都能从文件和 QA 文档证明时才设置 Ready：

- 对应文件真实存在。
- 文件名版本符合注册文档。
- 对应领域 QA 为 Approved。
- 资产总控注册记录存在。
- 文件哈希已登记。

#### 场景

- S001 于村祠堂雨夜：覆盖 SH001–SH005。
- S002 湘西山路：覆盖 SH006–SH009。
- S003 继业实验室：A+，missing。
- S004 死者住宅：A，missing。
- S005 法医中心：A，missing。
- S006 公安局简报/签约空间：A，missing。
- S007 空仓库：A，missing。
- S008 金白监控空间：A，missing。

S001/S002 的 grid 只能登记为规划角色；独立 panel 才能按注册文档用于对应机位。失败或被替代版本不得进入正式引用。

#### 道具

- P001 旧钢笔：核实 `P001_DES_master_v02.png` 和注册文档后登记。
- P002《百物录》：A，missing。
- P003 白色封签：A，missing。
- P004 物证袋/样本箱系统：A，missing。

#### 融合

创建逻辑待办：

```text
BLEND_SH004
BLEND_SH006
BLEND_SH007
BLEND_SH008
BLEND_SH009
BLEND_SH018
```

初始必须为 `blocked` 或 `missing`，不能因为基础资产存在就 Ready。依赖从主文档第 10.2 节导入。

#### 音频

- 不存在音频实物。
- 创建音频生产依赖或项目级音频状态。
- 状态为 `externally-pending`。
- 不能显示声音 Ready。

### C6. 文件登记

不要只在项目 JSON 中保存 Windows 源路径。正式导入时将顶层受支持文件复制到：

```text
data/projects/PRJ001_JIEDU/imported/
```

按类别整理但不要递归删除或覆盖：

```text
imported/source-documents/
imported/characters/
imported/scenes/
imported/props/
imported/qa-records/
imported/generation-packages/
imported/unclassified/
```

如创建目录可使用 `mkdir(parents=True, exist_ok=True)`。删除任何文件必须一次一个明确路径，并且本任务不要求删除源文件。

每个正式文件登记到 artifacts 表，至少包含：

- project_id
- artifact_type
- role
- version
- local_path
- sha256
- mime_type
- metadata
- qa_owner
- qa_decision
- status
- source filename
- source document reference

通用文件名：

```text
ChatGPT Image Aug 1, 2026, 12_09_12 PM.png
```

必须进入 `unclassified`，状态为待确认，不得成为正式角色/场景/Seedance 引用。

### C7. 资产总控状态

主文档已经包含截至 2026-08-02 的总控审计，因此可登记：

```js
assetRegulator: {
  version: 2,
  status: 'approved-with-gaps',
  auditedAt: '从源文档版本日期记录',
  dependencyVersion: 'v02',
  missingA: [
    'C008',
    'S003', 'S004', 'S005', 'S006', 'S007', 'S008',
    'P002', 'P003', 'P004',
    'BLEND_SH004', 'BLEND_SH006', 'BLEND_SH007',
    'BLEND_SH008', 'BLEND_SH009', 'BLEND_SH018'
  ]
}
```

C006/C007 是 B 级缺口，应进入缺失资产清单，但不要误放进 `missingA`。

### C8. 下一步队列

导入项目后，下一步任务至少能够反映：

```text
P0：BLEND_SH006–SH009 路由融合生产，但仅在依赖资产满足时执行
P0：P004 进入道具设计与 Prompt QA
P1：S003 → S006 → S004 → S005
P1：并行 P002、P003
P1：C006、C007 最小 B 级方案
P2：C008、S007、S008
P3：资产完整后才进入镜头导演，再进入 Seedance 打包
```

注意：原文把 BLEND_SH006–SH009 列为优先任务，但实际工作台必须再次运行基础资产门禁；若所需基础资产未全部生产就绪，显示“已规划、被依赖阻塞”，不能允许生成。

### C9. 原子替换旧项目

只有候选《解毒者》项目完成以下验证后才删除旧项目：

- 后端可读取。
- 浏览器可切换并渲染。
- 20 个镜头存在。
- 资产清单存在。
- 正式 PNG 数量与导入报告一致。
- 缺失资产没有被误标 Ready。
- 数据库备份存在。

然后：

1. 将 `state.currentId` 切换为《解毒者》。
2. 逐个调用现有 `DELETE /api/projects/{project_id}` 删除确认过的旧项目。
3. 不要使用一条无条件 SQL `DELETE FROM projects`。
4. 不要删除 `data/projects/<old-id>` 素材目录。
5. 将 localStorage 的 `projects` 替换为服务端最终项目集合。
6. 保存后刷新。
7. 再次确认 SQLite 和 localStorage 都只包含《解毒者》。

### C 阶段验收

- 项目中心只显示《解毒者 · 90秒概念预告》。
- 顶部默认选中《解毒者》。
- SQLite 和 localStorage 不再包含旧计划。
- 20 个镜头和资产依赖正确。
- 已注册资产有真实文件、哈希、QA 和登记证据。
- 缺失资产保持 Missing/Blocked。
- 音频保持 externally-pending。
- 旧素材目录没有被递归删除。

---

## 6. 实施阶段 D：生产流水线交互升级

### D1. 移除可见横向滚动条

用户要求移除流水线下方原生横向滑杆。保留容器 `overflow-x: auto`，但隐藏滚动条：

```css
.pipeline {
  overflow-x: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
  overscroll-behavior-x: contain;
  scroll-snap-type: x proximity;
  cursor: grab;
}
.pipeline::-webkit-scrollbar { display: none; }
.pipeline.is-dragging { cursor: grabbing; user-select: none; }
.pipe-node { scroll-snap-align: start; }
```

不要用 `overflow-x: hidden`，否则小屏幕无法访问后续节点。

### D2. 支持直接拖动/滑动

新增独立的通用模块或函数，例如：

```text
horizontal-pan.js
bindHorizontalPan(element)
```

支持：

- 鼠标按住空白区域拖动。
- 触控 Pointer Events 滑动。
- 触控板原生横向滚动。
- Shift + 鼠标滚轮横向移动。
- 普通垂直滚轮仍优先滚动页面，不要劫持所有 wheel。
- 拖动距离超过阈值后不得触发节点点击。
- Home/End 跳到首尾。
- 左右方向键切换焦点节点。
- 节点获得焦点时自动滚入视区。

### D3. 节点不能直接手改“完成”

“滑动编辑”解释为：

- 滑动浏览流水线。
- 点击节点打开阶段详情/进入执行区。
- 在详情中修改阶段对应的真实业务数据。

不得提供“把阶段直接设为完成”的按钮。状态仍由 `deriveWorkflowStages()` 推导。

### D4. 阶段详情抽屉

点击流水线节点后显示阶段详情，至少包含：

- 阶段状态。
- 完成数/总数。
- 判断依据。
- 阻塞原因。
- 输入资产。
- 缺失产物。
- 负责 Skill。
- “进入执行区”。
- “生成 Agent 任务”。
- “复制任务包”。

对于完成阶段，仍允许查看证据和版本，但不要默认重新执行。

### D5. 自适应显示

- 宽屏优先在一行内显示全部节点或减少节点最小宽度。
- 中屏允许滑动。
- 手机端改为纵向时间线或两列网格，避免必须横向拖动九个节点。
- 右侧最后节点不能被裁切。
- 当前建议节点打开页面时自动滚入可见区域。

### D 阶段验收

- 不再看到白色原生横向滑杆。
- 鼠标、触控、键盘都能访问所有节点。
- 拖动不会误触节点。
- 点击节点进入正确页面或详情。
- 任何节点状态仍与真实项目数据一致。

---

## 7. 实施阶段 E：Agent 任务编排控制台升级

### E1. 设计目标

当前区域只是 Skill 下拉框 + 文本框 + 生成/复制按钮，缺乏：

- 当前为什么要运行这个 Skill。
- 输入范围和目标对象。
- 执行前门禁。
- 将修改哪些项目字段。
- 使用哪个 Agent/模型。
- 是否会产生费用。
- 运行历史和失败重试。
- Prompt/任务版本。

升级后它应是“受监督制作任务控制台”，而不是普通 Prompt 输入框。

### E2. 可借鉴的高 Star 项目模式

只借鉴交互和状态思想，不复制它们的大型框架：

- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)：异步队列、历史记录、只重跑变化节点、撤销/重做。FRAMEFLOW 应借鉴“任务队列 + 局部重跑 + 历史版本”，不引入自由节点画布。
- [Dify](https://github.com/langgenius/dify)：工作流运行记录、节点级输入/输出、状态、耗时、Token 和费用。FRAMEFLOW 应为每次 Skill 运行保存可观察的运行摘要。
- [n8n](https://github.com/n8n-io/n8n)：多步骤工作流、人工批准、可观察性和供应商灵活切换。FRAMEFLOW 应保留确定性 Gate 和人工确认，不把模型当作最终状态权威。
- [Open WebUI](https://github.com/open-webui/open-webui)：工作区 Prompt、Prompt 历史和模型切换。FRAMEFLOW 应实现版本化任务模板与明确模型来源。

### E3. 推荐三段式布局

桌面端：

```text
┌──────────────┬───────────────────────────┬────────────────────┐
│ 1. 任务选择  │ 2. 上下文与任务编辑       │ 3. 门禁与执行       │
│ 当前建议     │ 目标资产/镜头              │ Agent/模型           │
│ Skill 模板   │ 自动收集的项目上下文       │ Gate 检查             │
│ 最近任务     │ 用户补充指令               │ 费用/数据发送提示      │
│              │ 输出契约预览               │ 运行/复制/外部执行     │
└──────────────┴───────────────────────────┴────────────────────┘
```

小屏幕使用分步 Tab：任务 → 上下文 → 确认。

### E4. 第一段：任务选择

显示：

- “推荐下一项”，来自 `deriveNextTasks()`。
- 按生产阶段分组的 Skill。
- 当前项目相关资产/镜头数量。
- 收藏模板或最近使用。
- 每个 Skill 一句话说明“负责什么/不负责什么”。

选择 Skill 后自动设置默认 scope：

| Skill | 默认 scope |
|---|---|
| video-script-storyboard | 项目/镜头组 |
| video-asset-regulator | 全项目资产审计 |
| character director | 选中的角色资产 |
| scene director | 选中的场景资产 |
| prop director | 选中的道具资产 |
| fusion director | 选中的 BLEND |
| video-shot-director | 选中的镜头或镜头组 |
| voice-controller | 选中的对白/音频 Cue |
| seedance-shot-packager | 已批准导演包对应镜头 |

### E5. 第二段：上下文与任务编辑

用结构化表单替代一个含糊文本框：

- 任务目标。
- 目标对象：项目/资产/镜头/声音。
- 选择的稳定 ID。
- 输入来源清单。
- 必须保留。
- 必须避免。
- 期望输出。
- 用户补充指令。

下方实时生成“任务指令预览”，可编辑但应保留结构：

```text
Target skill:
Task objective:
Source assets:
Relevant shots:
Asset priority:
Required output:
Must preserve:
Must avoid:
Dependencies:
Return expected:
```

每次生成预览建立本地草稿版本，但不调用 Agent。

### E6. 第三段：门禁与执行

执行前显示：

- 当前 Agent：DeepSeek/OpenAI。
- 实际模型：只读显示设置中已选择的模型。
- API 连接状态和最近延迟。
- 将发送的数据范围。
- 是否涉及敏感素材。
- 是否会产生付费媒体调用。
- 确定性 Gate 结果。
- 预计调用次数（如果能确定）。

按钮分层：

```text
主操作：在工作台 Agent 中运行
次操作：复制完整任务指令
次操作：复制并打开 ChatGPT
次操作：保存为草稿
危险/付费操作：必须单独确认，不能与文本编排混为一谈
```

文本 Skill 编排本身不得自动触发图片、TTS 或 Seedance 付费调用。

### E7. 运行状态和历史

每次运行记录：

```js
{
  id,
  projectId,
  skillId,
  scope,
  inputVersion,
  status,
  providerProfileId,
  model,
  startedAt,
  finishedAt,
  latencyMs,
  tokenUsage,
  costEstimate,
  outputSummary,
  patch,
  gateResult,
  errorKind,
  errorMessage
}
```

界面显示：

- 等待。
- 运行中。
- 成功。
- 需要用户接受补丁。
- 被门禁阻塞。
- 失败。
- 已取消。

失败时支持：

- 使用相同版本重试。
- 修改输入后创建新版本。
- 明确切换 Agent/模型后重试。

禁止静默回退。

### E8. 结构化补丁

Agent 返回后不直接改项目。显示差异卡：

- 新增字段。
- 修改字段。
- 删除字段。
- 受影响资产/镜头。
- 门禁变化。

用户选择：

- 接受全部。
- 接受选中项。
- 拒绝。
- 保存结果但不应用。

应用前把旧值写入 `undoStack`，支持撤销。

### E9. DeepSeek 兼容

- 继续通过 OpenAI-compatible 接口调用。
- 工具 Schema 必须转换为 DeepSeek 可接受的基础 JSON Schema。
- 不向 DeepSeek 发送它不支持的嵌套严格函数类型。
- 结构化返回需由服务端再次校验。
- DeepSeek 生成文本不能直接改变 QA、审批、Ready 或 paid task 状态。
- 当前页面显示连接结果、模型和延迟。

### E 阶段验收

- 用户能理解当前为什么运行某个 Skill。
- 能选择目标资产或镜头。
- 能预览完整输入和输出契约。
- 能看到 Agent、模型、连接状态和 Gate。
- 文本任务可以运行、复制或交给外部 ChatGPT。
- 运行历史可查看、失败可明确重试。
- Agent 结果必须经差异确认后应用。
- 文本编排不会直接产生付费媒体调用。

---

## 8. 数据与接口调整建议

### 8.1 项目列表

调整：

```http
GET /api/projects
```

按 `sortOrder ASC, updated_at DESC` 返回，或让响应包含排序字段后由前端统一排序。

### 8.2 项目复制

新增：

```http
POST /api/projects/{project_id}/clone-template
```

请求：

```json
{ "name": "解毒者 · 制作副本" }
```

后端负责清除不应复制的任务、artifact 所有权、审批和 Ready 状态。

### 8.3 项目导出

可复用前端下载，但建议增加：

```http
GET /api/projects/{project_id}/export
GET /api/projects/export-index
```

响应不得包含凭据。

### 8.4 工作流运行历史

补充：

```http
GET /api/workflow-runs?project_id=...
GET /api/workflow-runs/{run_id}
POST /api/workflow-runs/{run_id}/retry
POST /api/workflow-runs/{run_id}/cancel
```

继续使用已有 `POST /api/workflow-runs` 和 `/api/assistant/stream`。

### 8.5 本地目录导入

优先先做一次性受控脚本，不要立即开放任意路径 API。如果确实增加接口，只允许：

- 服务仅监听 127.0.0.1。
- 用户显式选择目录。
- 对路径做 resolve 和白名单检查。
- 不接受远程 URL。
- 不跟随离开源根目录的符号链接。
- 只读取允许的扩展名。

---

## 9. 自动化测试清单

### 9.1 项目中心

- 项目管理初始化顺序测试。
- 项目中心按钮点击可打开。
- 搜索与选择。
- 重命名。
- 排序持久化。
- 模板复制不会继承 artifactId、任务和 Ready。
- 导出不含 API Key。
- 删除活动任务项目返回 409。
- 删除不触碰素材目录。

### 9.2 《解毒者》导入

- dry-run 不写数据库和文件。
- 只读取顶层允许文件。
- 临时目录被忽略。
- 20 个镜头 ID 与时长正确。
- C001–C008、S001–S008、P001–P004、BLEND 清单正确。
- C006/C007 是 B 缺口，不进入 missingA。
- 通用文件名 PNG 未注册为正式引用。
- 失败/被替代版本不能成为正式引用。
- 无音频时保持 externally-pending。
- 导入重复执行具有幂等性或明确冲突预览。
- 正式文件都有 SHA-256。

### 9.3 流水线

- 原生滚动条不可见。
- 内容仍可横向访问。
- pointer drag 正常。
- drag 后不误触 click。
- 键盘可访问。
- 节点不能直接手改 completed。
- 状态推导测试继续通过。

### 9.4 Agent 编排

- 推荐任务来自 `deriveNextTasks()`。
- 切换 Skill 更新 scope 和输出契约。
- DeepSeek/OpenAI 模型显示正确。
- 连接错误在当前面板显示。
- 运行记录包含状态和耗时。
- 结构化补丁未确认前不修改项目。
- 文本编排不会创建图片/TTS/Seedance 任务。
- 外部 ChatGPT 按钮先复制后打开。

### 9.5 回归测试

- 新建项目取消不触发必填校验。
- 设置页 Agent 选择、模型选择、API 检测和延迟仍正常。
- Seedance 2.5 默认，2.0/2.0 Fast 仍存在。
- 旧 2.0 包不被自动迁移。
- 浏览器控制台无错误。
- `python -m pytest -q` 全部通过。
- `npm test` 或项目真实 JS 测试全部通过。

---

## 10. 浏览器最终验收脚本

服务地址：

```text
http://127.0.0.1:8787/
```

严格按顺序执行：

1. 启动工作台并强制刷新。
2. 确认顶部显示《解毒者 · 90秒概念预告》。
3. 打开项目快速切换，确认没有旧计划。
4. 打开项目中心。
5. 搜索“解毒者”。
6. 查看项目详情、镜头数、资产数、当前阶段和阻塞。
7. 重命名后撤回或改回原名。
8. 导出项目 JSON，检查无 API Key。
9. 复制为模板，确认副本不继承 Ready/artifact 所有权；随后仅删除这个明确的测试副本。
10. 返回总览，确认生产流水线没有可见白色横向滑杆。
11. 鼠标拖动到最后一个 Seedance 节点。
12. 用键盘左右键遍历节点。
13. 点击资产总控节点，进入资产生产总控区域。
14. 点击缺失 P004，确认显示道具设计/Prompt QA 的下一动作。
15. 返回总览，打开 Agent 任务编排。
16. 选择 `video-prop-design-director` 和 P004。
17. 查看自动收集上下文、输出契约和门禁。
18. 生成任务预览，但不要发起付费媒体调用。
19. 复制任务指令。
20. 使用已连接 DeepSeek 运行文本任务。
21. 确认页面显示 Agent、模型、延迟和运行状态。
22. 确认返回补丁需要人工接受。
23. 拒绝一次补丁，项目不应改变。
24. 再运行并接受合法补丁，确认可以撤销。
25. 检查浏览器控制台无异常。

---

## 11. 交付报告格式

完成后必须按以下结构报告，不要只说“已完成”：

```text
1. 根因
   - 项目管理不可用的真实原因
   - 旧项目重复来源
   - 流水线滚动条来源
   - Agent 编排当前不足

2. 修改文件
   - 文件路径
   - 修改内容

3. 《解毒者》导入结果
   - 项目 ID
   - 镜头数
   - 逻辑资产数
   - 正式文件数
   - Ready 数
   - Missing/Blocked 数
   - 未分类文件数
   - 音频状态

4. 旧项目清理
   - 删除的项目 ID/名称
   - SQLite 最终项目数
   - localStorage 最终项目数
   - 素材目录是否保留
   - 备份文件路径

5. 项目中心功能
   - 选择、搜索、排序、重命名、复制、导入、导出、删除测试结果

6. 流水线
   - 鼠标、触控、滚轮、键盘测试结果
   - 状态推导测试结果

7. Agent 编排
   - DeepSeek 连接与运行结果
   - Gate、版本、历史、补丁确认结果

8. 自动化测试
   - 命令
   - 通过数
   - 失败数

9. 浏览器验收
   - 25 个步骤的逐项结果

10. 尚未完成或需要用户配置的内容
```

---

## 12. 最终完成判定

只有同时满足以下条件，任务才可标记完成：

- 项目中心真实可操作，不再出现点击无反应。
- 项目中心具备选择、搜索、重命名、排序、复制为模板、导入、导出和安全删除。
- 旧计划已从 SQLite 和 localStorage 移除，但备份仍存在。
- 《解毒者》完整导入并成为唯一默认项目。
- 导入状态有证据，不伪造 QA/注册。
- 流水线原生横向滑杆已隐藏，所有节点仍可访问。
- 流水线业务顺序不可被用户改变。
- Agent 编排区能明确选择任务、上下文、目标对象、模型、Gate 和执行方式。
- DeepSeek 的文本任务能够运行并显示结果、延迟和错误。
- Agent 补丁必须人工确认。
- `video-shot-director` 仍是 Seedance 打包前的强制门。
- 所有自动化测试和浏览器验收通过。

如果遇到不确定的历史 QA 或注册证据，保持 Pending/Missing 并在交付报告列出，不得乐观推断为 Ready。
