# DEEPSEEK UI/ASSET 执行验收报告

- 执行日期：2026-08-18
- 执行环境：DeepSeek Harness（DeepSeek-V4-Flash），工作区 D:\11067\Codex\2026-08-13\video-2
- 验收服务：最新代码服务 http://127.0.0.1:8790/（uvicorn，后台任务）
- 真实浏览器：Harness 提供的 CDP 浏览器 http://127.0.0.1:9333/json（HeadlessChrome 151），页面已加载本工作台
- 结论：三类问题（资产媒体不显示、弹窗内容不完整、字体/UI 层级不统一）已全部修复；前端 39 项、后端 37 项自动化测试全部通过；三个视口下代表性弹窗全部通过真实 DOM 测量验收；浏览器控制台无本任务引入的错误。

## 1. 修改摘要

本任务在保留全部用户既有修改的前提下，采用增量修改方式完成三个相互关联问题的修复，并顺带修复了在验收过程中发现的**既有严重缺陷**（styles.css 第 23 行被上一轮会话工具写回时截断污染，导致整个样式表只解析前 44 条规则、应用完全无样式，这是所有视觉问题被掩盖的总根因之一）。

### 1.1 资产媒体不显示（问题一）
- 后端统一资产响应合同：GET /api/assets/intake 列表、单项详情、上传完成、映射、QA、登记等所有返回 artifact 的位置，均携带浏览器可访问的 url（/api/project-files/{project_id}/...）。
- 前端建立单一媒体选择逻辑（已登记 artifact → 最新合格候选 → 最新 intake/unqualified 候选，并明确显示候选状态，候选文件绝不等于 Ready），并在审计列表缩略图、逻辑资产卡片主视觉、资产详情预览三处渲染真实媒体。
- 图片加载失败有明确回退（类型标签 + “无法加载预览”），不出现破图占位。
- 修复首次进入资产页的异步刷新缺口：审计数据异步返回后按指纹判定**实质变化**才整体重渲染，首屏 0 条会在数据到达后自动补齐为真实数量与卡片媒体，且不会 render→loadAudit→render 死循环。
- 修复项目切换竞态：旧项目慢响应不会覆盖新项目审计数据；切换后不再短暂混入上一项目的审计记录。
- 修复审计区重建后上传/总控按钮丢失事件绑定的缺陷。

### 1.2 弹窗内容不完整（问题二）
- 基础 dialog 采用“粘性标题栏 + 唯一滚动正文 + 粘性底部操作栏”结构；新建项目/设置两个静态窗口继续使用 form 网格（固定头尾、正文滚动）。
- 补上两个未纳入粘性底栏的窗口：资产上传窗口（.dialog-actions 非最后一个子元素）与分镜审阅窗口（使用 .review-actions 而非 .dialog-actions）。
- 删除镜头资产目录的双层滚动（.shot-detail-catalog 不再内部滚动，统一由弹窗滚动）。
- 长 artifact ID、路径、JSON/QA 报告统一 overflow-wrap:anywhere 换行；审计详情 pre 内部安全滚动。
- 窄屏（≤760px）form-grid 切单列、弹窗内边距收紧到 16px、底部按钮最小高度 40px。

### 1.3 字体与 UI 层级不统一（问题三）
- 保留既有 --font-sans（Segoe UI Variable / Microsoft YaHei UI / PingFang SC / Noto Sans CJK SC / Source Han Sans SC）与 --font-mono（Cascadia Code / SFMono-Regular / Consolas）本地字体栈，全部为本地系统字体、离线可用。
- 页面标题下限提到 28px（clamp(28px,3vw,38px)）；弹窗标题 19px；卡片标题提升到 12–13px；辅助文字全面不低于 10px（原大量 8/9px 已抬升）。
- 代码/ID 字体统一走 --font-mono；favicon 的衬线 F 改为 sans-serif，品牌与正文不再混用冲突衬线。
- 补齐键盘焦点态（focus-visible 轮廓）、禁用态（opacity/cursor）、prefers-reduced-motion 降级；输入框焦点环统一荧光黄绿色。

### 1.4 验收过程中发现的既有缺陷（顺带修复）
- **styles.css 第 23 行截断污染**：文件内容本身以字面量 “…padding:9p... (line truncated to 2000 chars)” 结尾，导致 CSS 解析在中途终止（浏览器只解析出 44 条规则），整个应用（含审计缩略图、卡片、弹窗、字体）全部失去样式、布局横向溢出 277px。已从 git 基线完整恢复该行（含 .compact/.dialogue-*/.take-*/.cue-*/.execution-confirm/.audio-handoff-map/.check-card 等规则），修复后全文括号平衡（depth=0），页面无横向溢出。

## 2. 根因与修复映射

| # | 根因（已确认） | 修复 | 文件 |
|---|---|---|---|
| B1 | GET /api/assets/intake 的 artifact_payload() 不含 url，上传响应 URL 被前端丢弃 | artifact_payload() 统一注入 url；新增 project_file_url() 安全等价方法 | frameflow/asset_audit.py |
| B2 | project_file_url 按任意 projects/{project_id} 片段判定归属，与“位于项目树内”的声明不符 | 锚定真实 DATA_DIR/projects/{project_id} 项目根（或注入 project_root），用 relative_to 产出相对路径；伪造片段路径一律返回 None；URL 永不包含 .. | frameflow/asset_audit.py |
| C1 | 卡片 .asset-visual 永远是 CSS 类型占位图 | mediaCandidate() 单选媒体 + mediaElementHtml() 渲染 img/video/audio | asset-intake-state.js、asset-workspace.js、styles.css |
| C2 | 审计缩略图分支因列表无 url 长期不进入 | 列表 url 补齐后缩略图渲染图片/视频/音频文件块 | 后端 B1 + asset-workspace.js |
| C3 | 检查器只有文本事实，无媒体预览 | 文件区加入 .asset-preview-panel 大图/视频/音频预览（contain） | asset-workspace.js、styles.css |
| C4 | 首次进入显示 0 条，点击标签才出现；上传后卡片不刷新 | shouldRefreshAssets() 指纹判定 + bind 中全量/局部刷新分流，冷启动自动补齐 | asset-intake-state.js、asset-workspace.js |
| C5 | 项目切换时旧项目记录混入新项目 | auditProjectId 归属守卫 + 慢响应 pid 丢弃 | asset-workspace.js |
| C6 | 加载失败出现破图 | bindMediaFallbacks() 将失败元素替换为类型标签回退 | asset-workspace.js |
| C7 | 审计区重建后上传/总控按钮事件丢失 | rebindAuditTabs() 补绑 #uploadAsset/#runRegulator | asset-workspace.js |
| D1 | 上传窗口底栏非 last-child 未固定；审阅窗口用 .review-actions 未固定 | 补充粘性底栏规则 | styles.css |
| D2 | 镜头目录双层滚动 | .shot-detail-catalog 不再内滚 | styles.css |
| D3 | 长 ID/路径/JSON 撑破窗口 | 统一换行规则 | styles.css |
| D4 | 窄屏 form-grid 双列过挤 | ≤760px 单列 | styles.css |
| E1 | 8/9px 辅助文字过多、卡片标题偏小 | 字号下限 10px、卡片标题 12–13px、页面标题 28px 起 | styles.css |
| E2 | 品牌/正文字体混用 | 本地字体栈统一、mono 统一、favicon 改 sans-serif | styles.css、index.html |
| E3 | 焦点/禁用/动效无统一规则 | focus-visible、disabled、reduced-motion | styles.css |
| F0 | styles.css 第 23 行被截断污染，整表只解析 44 条规则 | 从 git 基线恢复该行内容 | styles.css |

## 3. 修改文件清单

本次任务实际修改（全部为增量，未覆盖/回退/删除用户改动）：

| 文件 | 修改内容 |
|---|---|
| frameflow/asset_audit.py | 新增 project_file_url()（锚定项目根的安全 URL 生成）；artifact_payload() 注入 url |
| asset-intake-state.js | 新增 mediaKind、mediaCandidate、auditFingerprint、shouldRefreshAssets 纯函数 |
| asset-workspace.js | 卡片/缩略图/检查器媒体渲染、失败回退、审计刷新判定、项目守卫、按钮重绑 |
| styles.css | 修复第 23 行截断污染；弹窗粘性头/正文/底栏补全；媒体样式；字号层级；焦点/动效；窄屏规则 |
| index.html | favicon 衬线 F → sans-serif（其余 dialog 结构保留既有增量） |
| tests/test_asset_intake.py | 新增 4 项 URL 合同/服务/登记/越界伪造测试，伪造路径测试改为真实项目根锚定 |
| tests/media-view.test.js | 新增：媒体分类、候选优先级、刷新判定（冷启动/稳定/切换/计数/状态）回归测试 |
| package.json | test 脚本接入 tests/media-view.test.js |

未改动但作为验收基线的既有文件：server.py、api.js、app.js、story-workspace.js、project-manager.js、workflow-state.js 等（其中 server.py 的 artifact_url 与 /api/project-files 安全路由保持不变）。

## 4. 测试命令与结果

```powershell
npm test
python -m unittest discover -s tests -p "test_*.py" -v
```

- npm test：**39/39 通过**
  - tests/workflow-state.test.js：11/11
  - tests/shot-assets.test.js：15/15
  - tests/media-view.test.js：13/13（新增，覆盖 mediaKind/mediaCandidate/shouldRefreshAssets）
- python -m unittest：**37/37 通过（Ran 37 tests, OK）**，含新增：
  - test_intake_list_records_include_project_file_url
  - test_intake_list_url_is_servable_with_media_type（200 + image/png + 内容一致）
  - test_register_response_artifact_keeps_url
  - test_project_file_url_never_escapes_project_tree（伪造片段/跨项目/穿越/注入根）
- JS 语法检查：node --check 全部 12 个 JS 文件 OK。
- 基线说明：任务开始时 npm 26 项、python 33 项即为全绿；所有新增测试均先实现修复再断言，未通过改期望掩盖实现错误。

## 5. 三档视口真实浏览器交互验收

浏览器：http://127.0.0.1:9333/json（HeadlessChrome 151，页面为最新代码 http://127.0.0.1:8790/）。验收方式为 CDP 真实 DOM 测量：打开各窗口后读取 getBoundingClientRect、scrollHeight/clientHeight、滚到底后的动作区位置，并断言窗口完整位于视口内、无横向页面溢出、标题/关闭按钮可见、正文可滚动（内容超长时）、底部操作可见或可达、无控制台错误。

| 窗口 | 1418×802 | 1024×640 | 768×560 |
|---|---|---|---|
| 新建项目 | PASS | PASS | PASS |
| 工作台设置 | PASS | PASS | PASS |
| 项目管理 | PASS | PASS | PASS |
| 资产检查器（含媒体预览） | PASS | PASS | PASS |
| 资产上传 | PASS | PASS | PASS |
| 资产版本历史 | PASS | PASS | PASS |
| 审计详情（含映射入口） | PASS | PASS | PASS |
| 资产映射 | PASS | PASS | PASS |
| 整改/隔离处理 | PASS | PASS | PASS |
| 脚本优化 | PASS | PASS | PASS |
| 脚本版本历史 | PASS | PASS | PASS |
| 分镜审阅（.review-dialog 布局探针） | PASS | PASS | PASS |
| Prompt 修订/重建（.prompt-modal 布局探针） | PASS | PASS | PASS |
| 镜头资产详情（.shot-detail-dialog 布局探针） | PASS | PASS | PASS |

说明：分镜审阅、Prompt 弹窗、镜头详情在当前真实数据下无可直接触发的业务状态（无 QA 失败 artifact、无运行中的优化任务、镜头依赖少于 5 条），故以相同 CSS 类注入布局探针做真实渲染测量；其余全部经真实点击打开。

关键页面行为验收（1418×802 实测）：
- 资产页首屏冷启动：94ms 时审计区为空（0 行）→ 496ms 审计数据到达后自动补齐（1 行 + 标签计数 0/29/1/30），MutationObserver 计数稳定（12 次后不再变化），无渲染死循环。
- 资产卡片 26 张，8 个媒体元素全部加载（8/8 naturalWidth > 0，URL 均为 /api/project-files/e8f59c50-.../），审计缩略图正常加载。
- 资产检查器预览图从 /api/project-files/... 加载成功；整页刷新后卡片媒体与审计计数仍然存在。
- 项目切换：从 e8f59c50 切到 PRJ_DIAG 后立即显示 0/0/0/0、0 行，不混入上一项目记录；切回后数据恢复。
- Esc 键关闭弹窗、关闭按钮关闭弹窗、关闭后页面导航继续可用（切到总览正常渲染）。
- “上传资产”“运行项目总控审计”按钮在审计区异步刷新后仍可点击（后者弹出“资产总控审计完成：16 个 A/A+ 缺口”）。
- 修复前页面横向溢出 277px（styles.css 截断污染导致）；修复后三个视口 documentElement.scrollWidth - clientWidth === 0。
- 浏览器控制台：全程无 console error / 未捕获异常。

## 6. 已知限制与后续建议

1. **业务状态未伪造**：验收使用的真实数据为项目 e8f59c50（29 合格 + 1 待映射）。QA 失败、审计阻塞、融合二次失败等状态没有在真实项目中伪造；相关窗口（Prompt 弹窗、分镜审阅、镜头详情）以同款 CSS 布局探针验证，未做真实业务数据驱动的点击。建议在 QA 数据齐全的项目上补一次真实状态驱动的回归。
2. **styles.css 截断污染**：第 23 行已按 git 基线恢复并全文括号校验（depth=0）。建议后续所有工具在写回超长行时做完整性校验，避免再次写入截断标记。
3. **验收服务器端口**：Harness 实施阶段使用 8790 验收最新代码。最终独立验收已停止 8787 的旧进程并从当前工作区重新启动服务；默认入口现为最新代码，健康检查 200，真实项目 30/30 条 artifact 均返回 URL。
4. **runRegulator 副作用**：验收时点击“运行项目总控审计”对 e8f59c50 项目执行了资产归一化审计（assetRegulator 版本更新、A/A+ 缺口 16 个），这是该按钮的正常业务行为，数据均派生自既有字段，未伪造 Ready/QA/登记状态。
5. **媒体元素数量**：当前项目仅 8 个逻辑资产有已登记文件（26 张卡片），其余资产无候选媒体，属数据现状而非缺陷；候选提示逻辑已就绪，有候选文件的资产会自动显示。
6. **后续建议**：在 CI 中加入 styles.css 括号平衡/行长完整性检查，防止同类污染再次导致整表失效；将 auditFingerprint/shouldRefreshAssets 等纯函数继续扩展为前端视图模型的统一测试面；资产详情底部无单一“主操作”底栏（操作分布在分节内），如产品希望登记/QA 固定在底部，可再加一组 .dialog-footer 动作。

## 7. Codex 最终独立复核

- 默认服务：http://127.0.0.1:8787/，进程 PID 56628；`/api/health` 返回 200。
- 默认服务 URL 合同：项目 e8f59c50-... 共 30 条 artifact，30 条均带 `/api/project-files/...` URL。
- 自动化复跑：前端 39/39、后端 37/37、12 个 JS 文件语法检查全部通过。
- CSS 完整性：628 个左花括号与 628 个右花括号匹配，不含截断污染标记。
- 独立 CDP 复核：1418×802、1024×640、768×560 三档视口均无页面横向溢出；每档均验证新建项目、设置、项目管理、资产检查器、资产上传窗口完整位于视口内，标题、关闭按钮、操作区可见/可达。
- 真实资产：含 30 条 artifact 的项目显示 26 张逻辑资产卡、8 个媒体元素，8/8 图片成功解码。
