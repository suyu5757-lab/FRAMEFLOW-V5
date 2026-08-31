# FRAMEFLOW V3 INITIAL AUDIT REPORT

审计日期：2026-08-23  
审计对象：`FRAMEFLOW V3 · AI VIDEO OS` 当前工作区与 `http://127.0.0.1:8787/`  
审计依据：`FRAMEFLOW_V3_AI_VIDEO_OS_全功能测试与上线审计总指令.md`  
审计模式：第一轮只读产品审计；没有修改产品代码、正式数据库或正式项目媒体。破坏性、边界、并发和真实渲染测试均在独立临时数据库 `frameflow-audit-20260823-8792.db` 中执行。

## 1. 最终结论

# NO-GO

当前版本不应进入真实影视项目正式生产。

主要原因不是页面打不开，也不是基础测试失败，而是生产门禁存在已复现的绕过路径：一个 `qa_decision=Pending`、未登记的候选视频，可以被写成“已批准镜头”，通过时间线预检，并由真实 FFmpeg Worker 生成 `succeeded` 的最终 MP4 和交付包。除此之外，Prompt 当前版本权威、重复生成幂等、数据完整性总审计、大项目性能、空项目人工生产路径和恢复能力均未达到上线标准。

上线标准要求 P0=0、P1=0；本轮结果为 P0=0、P1=9，因此只能判定 NO-GO。

## 2. 评分

| 维度 | 得分 | 关键依据 |
|---|---:|---|
| Product Workflow | 5/10 | 首页与主要工作区清晰，但空项目不能在 UI 中手工新增镜头或逻辑资产 |
| Film Production Workflow | 3/10 | 有八阶段工作流、资产监管和交付面，但镜头/Camera/Return/Split 闭环不完整 |
| Asset Management | 5/10 | 有候选、QA、登记、版本、依赖；但未合格视频可进入最终交付 |
| Continuity System | 3/10 | 有跨镜头检查与依赖，但缺少正式空间地图、屏幕方向、位置权威与独立 Camera Board 模型 |
| Prompt & Reference | 3/10 | 有 Prompt 版本与角色字段；旧批准版不 supersede，引用无 priority/scope/conflict authority |
| Frontend | 6/10 | 构建/E2E/三种 Chromium 浏览器可用；存在 4536 行单体组件、可访问性和大项目渲染问题 |
| Backend & Database | 5/10 | FastAPI、WAL、迁移、revision、任务恢复基础良好；核心表缺 FK，审计绿灯可假通过 |
| QA Reliability | 2/10 | 单项 QA API 有门禁，但时间线和最终渲染未强制反查 QA/登记状态 |
| Security | 6/10 | 上传签名、路径归属、凭据脱敏、XSS 基础良好；无鉴权/安全响应头，1GB 上传整包入内存 |
| Production Readiness | 3/10 | 真实 FFmpeg 可运行，但 Provider 不完整、核心门禁失败、大项目性能不可接受 |
| **总分** | **41/100** | **NO-GO** |

## 3. 架构与技术栈

| 层 | 实际实现 |
|---|---|
| 前端 | React 19.1、TypeScript 5.9、Vite 7、XYFlow/React Flow |
| 后端 | FastAPI、Uvicorn、Pydantic 2 |
| 数据库 | SQLite，应用连接启用 foreign keys，数据库为 WAL 模式；版本迁移 1–8 |
| 凭据 | Windows Credential Manager / keyring；API 响应只返回脱敏状态 |
| 媒体 | 项目目录 `data/projects/{project_id}`；FFmpeg/FFprobe；即梦 CLI |
| AI/Provider | OpenAI、OpenAI-compatible、OpenCode、ComfyUI、即梦 CLI 适配层 |
| 后台任务 | asyncio 进程内任务；queued/running 运行和渲染在服务启动时恢复 |
| 测试 | Python unittest、Vitest、Playwright Chromium、GitHub Actions Windows CI |
| 部署 | 本机 `127.0.0.1:8787` 单用户工作台；启动 BAT；无容器/反向代理/多用户鉴权 |

代码规模警示：`server.py` 5072 行、327 个函数；`web/src/App.tsx` 4536 行、58 个函数/组件。生产包主 JS 为 699.17 KB（gzip 215.34 KB），Vite 报出 >500 KB 警告。

## 4. Route Map 与功能目录

OpenAPI 实测：98 个路径模板、120 个 method-route（GET 45、POST 61、PUT 7、PATCH 3、DELETE 4）。公开 OpenAPI 只保留 `/api/v2`、健康和诊断面；旧 `/api/*` 由网关返回 410。

| ID | 模块/页面 | 主要功能 | UI 入口 | 主要 API | 数据对象 | 本轮状态 |
|---|---|---|---|---|---|---|
| FI-01 | 项目首页 | 项目总览、进度、阻塞、下一步、最近活动 | 首页 / 项目总览 | dashboard/projects | Project、Dashboard | PASS |
| FI-02 | 项目管理 | 创建、切换、归档、恢复、删除 | 项目管理 Dialog | projects CRUD | Project | PARTIAL |
| FI-03 | 故事与分镜 | 规格、剧本、场景、镜头表、检查、版本、回退 | 故事与分镜 | story/checks/diff/rollback/runs | Story、Scene、Shot、Version | FAIL |
| FI-04 | 资产生产工作区 | Shot–Asset Grid、筛选、布局、Prompt、候选、QA、登记 | 资产生产工作区 | asset-board、assets、QA | Asset、Artifact、Prompt | PARTIAL |
| FI-05 | 声音资产工坊 | 人声、音乐、音效、QA、交接 | 声音资产工坊 | audio-studio、audio/tts | Audio、Take、Cue | PARTIAL/BLOCKED |
| FI-06 | 后期时间线 | 镜头装配、多轨、预检、预览、渲染、交付包 | 后期时间线 | timeline、renders、proxies | Timeline、Render | FAIL |
| FI-07 | 统一资产库 | 搜索、范围/状态筛选、排序、规格、依赖、候选、版本 | 统一资产库 | assets、comparisons、gates | Logical Asset、Artifact | PARTIAL |
| FI-08 | 人物与角色 | 角色资产范围视图 | 人物与角色 | assets | Character Asset | PARTIAL |
| FI-09 | 场景与道具 | 场景/道具资产范围视图 | 场景与道具 | assets | Scene/Prop Asset | PARTIAL |
| FI-10 | 融合与候选 | Fusion 资产、融合门、候选 | 融合与候选 | fusion-gate、fusion-prompt-runs | Fusion、Lineage | FAIL |
| FI-11 | 设置 | Provider、凭据、探测、能力绑定 | 设置与 Provider | settings/providers/bindings | Provider Profile | PASS/BLOCKED |
| FI-12 | AI 助手 | Skill 选择、上下文、计划、补丁预览/应用 | AI 助手 Drawer | agent plans/patches | Agent Plan、Candidate | BLOCKED |
| FI-13 | 工作流图 | 节点、边、分组、布局、局部运行、审批 | 工作流/画布内部能力 | graph/templates/runs | Graph、Run、Node Run | PASS |
| FI-14 | Reference | 引用角色、artifact 归属 | 资产规格/依赖 | asset reference roles | Reference Role | FAIL |
| FI-15 | Prompt | 创建、编辑、QA、版本、生成绑定 | 资产卡/制作面板 | prompt-versions/qa | Prompt Version | FAIL |
| FI-16 | 上传 | 图片/视频/音频/字幕候选导入 | 资产/声音导入 | asset-intake | Artifact | PASS/PARTIAL |
| FI-17 | QA | 图片、视频、音频、Reference QA | 资产/声音 QA | qa-runs/submit/register | QA Run、Asset Version | FAIL |
| FI-18 | 版本 | Story、Prompt、Asset、Graph、Timeline | 各模块 | versions/diff/rollback | Version | PARTIAL |
| FI-19 | Generation | 估价、付费确认、运行、暂停/恢复/取消、事件 | 工作流/生成按钮 | runs、tasks | Run、Approval Gate | FAIL |
| FI-20 | Export/Import/Recovery | 项目导入导出、恢复 | V3 UI 无入口 | V3 无项目导入导出端点 | Backup/Manifest | FAIL |
| FI-21 | Camera / Camera Board | 独立机位、镜头语言、面板版本/QA | 无独立页面 | 无专用 API | Camera Panel | BLOCKED/ABSENT |
| FI-22 | Audit Trail | 资产、图、时间线、运行事件 | 分散视图 | events/audit | Event | PARTIAL |

## 5. 验证证据

### 5.1 自动化与构建

| 测试 | 结果 |
|---|---|
| Python 回归 | 83/83 PASS |
| Vitest | 6 files、32/32 PASS |
| TypeScript + Vite production build | PASS；主 chunk 699.17 KB 警告 |
| Playwright Chromium | 隔离重跑 8/8 PASS |
| Chrome/Edge 烟测 | 首屏和六个主要工作区可导航；仅 `/favicon.ico` 404 |
| npm audit | 0 个已知漏洞（177 dependencies） |
| pip check | PASS |
| Python 漏洞数据库扫描 | BLOCKED：环境未安装 `pip-audit` |
| Secret 静态模式扫描 | 77 个源码/配置文件；仅测试 fixture 命中，未发现真实凭据 |

首次并行执行 build 与 E2E 时出现 1 次失败，是构建清空 `dist` 与 E2E 启动并发造成的审计干扰；按 CI 的串行顺序重跑为 8/8，不计产品缺陷。

### 5.2 运行时、浏览器与性能

| 检查 | 实际结果 |
|---|---|
| 8787 健康 | `degraded`；视频 ready，orchestrator/image/vision/TTS/music/SFX 等未就绪 |
| system doctor | FFmpeg、FFprobe、前端、数据库、keyring 均可识别 |
| Lighthouse | Accessibility 91、Best Practices 100、SEO 100 |
| 首屏性能 | LCP 298 ms、CLS 0.01、391 DOM elements |
| 可访问性失败 | 隐藏 AI Drawer 内仍有可聚焦元素；多处低对比度；表单缺 id/name |
| 浏览器 Console | 正式页面无 JS error；Chrome/Edge 仅 favicon 404 |
| 网络 | 所有主要读请求 200；页面切换重复触发多次相同 dashboard GET |
| 离线保存 | 明确提示“无法连接”，未保存草稿保留；恢复网络后保存成功 |
| XSS | 项目名/剧本文本载荷未执行，React 以文本/textarea 值呈现 |
| 路径穿越 | 未读取越界文件；一种编码路径返回 500 而非受控 4xx |

### 5.3 数据库与正式数据实态

SQLite `integrity_check=ok`，声明的外键检查 0 违规，journal mode 为 WAL。正式库包含 2 个项目、31 artifacts、29 asset versions、29 QA runs、16 prompt versions、141 asset events。

应用级存储检查为 `ok=false`：

- `PRJ_F3843DF0760F` 有数据库项目记录但没有项目目录。
- `PRJ_32B543F4B566` 有包含大量媒体与文档的项目目录，但没有数据库项目记录。
- 正式项目 31 artifacts / 29 versions，但 `artifact_lineage_v3=0`、`asset_reference_roles_v4=0`。

系统级 `/api/v2/system/data-audit` 却返回 `ok=true`，因为其 `ok` 计算没有包含 missing/unregistered project directories。

### 5.4 大项目压力

隔离数据集：1000 assets、300 shots。

| 操作 | 实际结果 |
|---|---:|
| 保存完整项目文档 | 44 ms |
| 读取项目 | 41 ms / 236 KB |
| 读取 Story | 72 ms / 615 KB |
| 读取 Asset Board | 100 ms / 352 KB |
| 读取 Asset Library | **9012 ms / 1.10 MB** |
| 读取 Dashboard | **8851 ms** |
| UI 资产库完整出现 | 约 **46 秒**；1000 列表项、7333 DOM elements |
| UI Asset Board | 691 ms；1301 React Flow nodes、约 20716 DOM elements |
| 资产库本地精确搜索 | 17 ms |

结果：大型项目初始加载和切换不可接受，且资产库没有列表虚拟化。

## 6. Bug 清单

### FF-P1-001：未 QA/未登记视频可生成最终交付物

- Severity：P1 Launch Blocker
- Module：Shot → Timeline → Render → Delivery
- Reproduce：上传真实 1 秒 MP4；保持 `qa_decision=Pending`、不登记；把 artifact ID 写入 `status=approved/directorApproved=true` 的 SH001；装配时间线；预检；创建并批准渲染。
- Expected：装配、预检或渲染必须阻止未 Approved、未登记、非 active version 的输入。
- Actual：预检 `delivery_ready=true`，真实 FFmpeg 渲染 `succeeded`，生成最终 MP4、manifest、SRT 和 delivery.zip；manifest 明确记录 `artifact_qa_decision=Pending`。
- Root Cause：`generated_pending_qa` 和 `Pending` 被当作 ready；镜头 document 的批准布尔值是权威，未反查 asset_versions active/QA registration；`delivery_set=single` 还能绕过 preflight blocking。
- Affected：`frameflow/v3.py:403`、`:411`、`:414`、`:529`；`server.py:1640`、`:1732`、`:1897`、`:1923`。
- Fix：建立单一服务端 `production_artifact_gate`，只接受文件存在 + hash + QA Approved + registered active asset version + project ownership；装配、预检、preview、estimate、create、approve、worker 启动前全部复检；任何 delivery_set 均不得绕过。
- Regression Risk：高；会影响旧项目中靠宽松状态进入时间线的素材，需要迁移报告与人工重审。

### FF-P1-002：Prompt v02 Approved 后 v01 仍为 Approved

- Reproduce：创建 Prompt v1→Approved；创建 v2→Approved；读取版本列表。
- Actual：v1 与 v2 均为 `prompt_qa_approved`。
- Root Cause：QA 只更新目标行，不 supersede 同资产旧批准版本。
- Affected：`server.py:4357-4358`、`frameflow/asset_audit.py:675-696`。
- Fix：同一事务中把旧 approved/current 改为 superseded，加入每资产最多一个 current-approved 的数据库约束或权威表。
- Regression Risk：中高；需处理现有多批准状态。

### FF-P1-003：图片生成可提交与 Approved Prompt 不同的正文

- Reproduce：资产存在 Approved prompt version；请求体保留 current prompt_version，但把 `prompt` 改为任意未审文本。
- Expected：实际送 Provider 的 Prompt 必须从批准版本行读取并校验 hash/ID。
- Actual：服务端采用 `body.prompt or asset.prompt`，只比对版本 ID，不比对正文。
- Root Cause：Prompt authority 未绑定内容。
- Affected：`server.py:2944-2949`。
- Fix：忽略客户端 Prompt 正文，按 prompt_version 查询 Approved 行；保存 prompt hash 到 generation snapshot。
- Regression Risk：中。

### FF-P1-004：重复 Generate 没有幂等保护

- Reproduce：对同一 project/graph revision/paid node 并发 POST 10 次。
- Actual：10/10 返回 200，创建 10 个不同 run ID 和 10 个 `awaiting_confirmation` 审批门。
- Root Cause：没有 idempotency key、请求指纹唯一约束或在途任务锁。
- Affected：`server.py:950-972`。
- Fix：project + graph revision + selected nodes + parameters + actor 的幂等指纹；同指纹在途只返回原 run；审批接口也需一次性令牌。
- Regression Risk：中高。

### FF-P1-005：空项目无法在 UI 中手工建立生产链

- Reproduce：新建空项目；进入故事与分镜、统一资产库。
- Actual：故事页只有保存、AI 优化、资产 Prompt、进入资产生产；0 镜头时没有新增镜头；资产库没有新建逻辑资产。Provider 不可用时只能停在空项目。
- Root Cause：UI 把资产/镜头创建依赖于 AI 或内部 API fixture。
- Affected：`web/src/App.tsx:1802-1855`、`:1469`。
- Fix：提供手工新增/复制/删除/排序/Split Shot，以及 Character/Scene/Prop/Fusion/Audio 逻辑资产创建入口。
- Regression Risk：中。

### FF-P1-006：系统 data-audit 可在库盘失配时返回绿灯

- Reproduce：新建项目后立即检查 storage integrity 和 system data-audit。
- Actual：项目 integrity 为 missing_project_directory/ok=false；system data-audit 仍 ok=true。
- Root Cause：`ok` 计算遗漏 unregistered/missing directories；项目创建也不创建目录。
- Affected：`frameflow/maintenance.py:247-252`、`server.py:692-738`。
- Fix：统一两套完整性规则；创建项目时原子创建目录；审计 ok 必须包含库盘双向一致性。
- Regression Risk：中；需要区分真正空项目与丢失目录。

### FF-P1-007：现有生产数据存在孤立目录/缺失目录，且缺少 V3 恢复入口

- Actual：一个 DB 项目缺目录，一个大量媒体目录缺 DB 项目；V3 没有项目导入/导出/恢复端点与 UI；启动脚本没有自动一致性备份/checkpoint。
- Root Cause：旧导入端点被 V3 网关 410，但没有 V3 替代能力；删除保留媒体会产生孤立目录。
- Affected：`server.py:221-228`、`:486-498`、启动脚本。
- Fix：实现只读恢复预览、hash/MIME 重建、冲突合并、原子 SQLite backup、WAL checkpoint、可验证导出 manifest。
- Regression Risk：高；必须先备份正式 DB 与媒体清单。

### FF-P1-008：Reference Authority 模型不完整

- Actual：reference 表只有 role/source/notes，没有 priority、scope、authority/conflict；无法保证 @Image 顺序与冲突消解。
- Root Cause：模型只覆盖“角色”，没有生产权威关系。
- Affected：`frameflow/database.py:389-401`、`frameflow/schemas.py:319-328`。
- Fix：增加 priority、scope、authority、conflict_group、effective_version；Prompt packaging 按冻结快照输出顺序映射。
- Regression Risk：高；影响 Prompt、镜头历史和旧 Reference 数据迁移。

### FF-P1-009：目标规模下 Asset Library/Dashboard 不可用

- Reproduce：1000 assets + 300 shots。
- Actual：assets 9.0s、dashboard 8.9s、资产库完整 UI 约 46s；1000 行全部挂载。
- Root Cause：library projection 重复聚合、Dashboard 重算完整 library、无分页/增量/虚拟化，页面切换还重复请求 dashboard。
- Affected：`server.py:3505`、`web/src/App.tsx:1469`。
- Fix：SQL 聚合/索引、分页、轻量 dashboard projection、ETag/缓存、AbortController 去重、列表和画布窗口化。
- Regression Risk：中高。

### P2/P3 问题摘要

| ID | 级别 | 问题 |
|---|---|---|
| FF-P2-010 | P2 | 大多数核心 V2 表（artifacts、asset_versions、prompt_versions、QA、reference、lineage 等）没有数据库 FK；`foreign_key_check=0` 不能证明这些表无孤儿 |
| FF-P2-011 | P2 | 本地服务无 Authentication、Origin/CSRF/TrustedHost 保护和 CSP/X-Content-Type-Options/X-Frame-Options 等响应头；仅靠 127.0.0.1 边界 |
| FF-P2-012 | P2 | 最大上传 1GB，`await file.read(MAX_UPLOAD+1)` 整包入内存，存在本机内存耗尽风险 |
| FF-P2-013 | P2 | Audit Trail 不完整：项目/故事普通编辑缺少统一 actor/reason/before/after；`studio-user` 为固定字符串 |
| FF-P2-014 | P2 | Lighthouse：隐藏 Drawer 保留可聚焦元素、低对比度、表单缺 id/name；Accessibility 91 |
| FF-P2-015 | P2 | 前后端巨型单文件、无 lint/coverage/security CI、主 bundle 超 500KB |
| FF-P2-016 | P2 | Camera Board、独立 Camera Panel QA/version、Scene 空间坐标/方位/入口/动作区权威未形成专用模型 |
| FF-P3-017 | P3 | 编码路径穿越被阻止但抛出未处理 ValueError，返回 500 |
| FF-P3-018 | P3 | Chrome/Edge 请求 `/favicon.ico` 得到 404 |
| FF-P3-019 | P3 | 项目重名被允许且无提示；两个同名项目只能依赖 ID 区分 |

## 7. 模块测试矩阵

| Test ID | Module | Scenario | Expected | Actual | Result | Severity |
|---|---|---|---|---|---|---|
| T-PROJ-01 | Project | 空/空格/101 字名称 | 拒绝 | 422 | PASS | — |
| T-PROJ-02 | Project | 中文/Emoji/特殊字符 | 安全保存 | 201，XSS 不执行 | PASS | — |
| T-PROJ-03 | Project | 重名 | 警告或明确允许 | 静默创建第二项目 | FAIL | P3 |
| T-PROJ-04 | Project | revision 并发更新 | 一次成功、一次冲突 | 200 + 409 | PASS | — |
| T-PROJ-05 | Project | 刷新/服务重启 | 数据保留 | 项目、Story、Asset、Artifact 均保留 | PASS | — |
| T-STORY-01 | Story | 中文、多段落、Prompt injection 字符串 | 持久化、不执行 | PASS | PASS | — |
| T-STORY-02 | Story | 删除 SH002 | SH003 ID 不变 | SH001、SH003 | PASS | — |
| T-STORY-03 | Story | 空项目手工新增镜头 | 可操作 | 无 UI 入口 | FAIL | P1 |
| T-ASSET-01 | Asset | 创建 character/scene/prop/fusion | 创建并持久化 | API PASS | PASS/PARTIAL | — |
| T-ASSET-02 | Asset | 重复资产名 | 拒绝 | 409 | PASS | — |
| T-UP-01 | Upload | 0KB/伪 PNG/错误扩展名 | 拒绝 | 422 | PASS | — |
| T-UP-02 | Upload | 中文/空格/括号 PNG | 安全保存 | PASS，文件名归一化 | PASS | — |
| T-UP-03 | Upload | 真实 MP4 | 技术校验 | PASS | PASS | — |
| T-QA-01 | QA Gate | Pending artifact 进入交付 | 阻止 | 最终渲染 succeeded | FAIL | P1 |
| T-PROMPT-01 | Prompt | v1/v2 依次 Approved | v1 superseded | 两个 approved | FAIL | P1 |
| T-PROMPT-02 | Prompt | 篡改正文但沿用 approved version ID | 阻止 | 代码采用客户端正文 | FAIL | P1 |
| T-REF-01 | Reference | Role/Priority/Scope/Conflict | 全部可冻结 | 仅 Role 部分存在 | FAIL | P1 |
| T-GEN-01 | Generation | Generate ×10 | 幂等/锁 | 10 个不同 run | FAIL | P1 |
| T-GEN-02 | Generation | 未确认付费 | 不执行 | awaiting_confirmation | PASS | — |
| T-TIME-01 | Timeline | Approved Shot 装配 | 正确装配 | PASS | PASS | — |
| T-TIME-02 | Timeline | Pending QA 输入 | 阻止 | delivery_ready=true | FAIL | P1 |
| T-RENDER-01 | Render | 真实 FFmpeg | 生成可追溯交付 | succeeded + manifest/package | PASS，但输入门禁失败 | P1 |
| T-NET-01 | Network | Offline 保存 | 提示且保留草稿 | PASS | PASS | — |
| T-NET-02 | Network | 恢复后保存 | 可继续 | PASS | PASS | — |
| T-SEC-01 | Security | XSS | 不执行 | PASS | PASS | — |
| T-SEC-02 | Security | 路径穿越 | 不读取文件 | 未泄露，部分 500 | PARTIAL | P3 |
| T-SEC-03 | Security | 凭据响应扫描 | 不泄露 | PASS | PASS | — |
| T-PERF-01 | Performance | 1000 assets/300 shots | 可用 | 9s API、约46s UI | FAIL | P1 |
| T-BROW-01 | Browser | Chromium E2E | 主要流程稳定 | 8/8 | PASS | — |
| T-BROW-02 | Browser | Chrome/Edge | 主要页面可导航 | PASS，favicon 404 | PASS/P3 | P3 |
| T-EXPORT-01 | Recovery | V3 导入/导出/恢复 | 可用 | 无入口/无端点 | FAIL | P1 |

## 8. FRAMEFLOW Launch Blocker List

按修复顺序：

1. P1：所有时间线/渲染入口强制 QA Approved + registered active version；修复 Pending/generated_pending_qa 被视为 ready。
2. P1：Prompt Approved 唯一权威、旧版 superseded、生成正文绑定批准版本 hash。
3. P1：Generation/Render 幂等键、在途锁、一次性审批令牌。
4. P1：修复 data-audit 假绿灯；先对正式库和 `PRJ_32B543F4B566` 做只读恢复预览。
5. P1：实现 V3 backup/export/import/recovery，补充定期 SQLite backup + WAL checkpoint + manifest 校验。
6. P1：为无 AI 环境补齐手工新增 Shot/Scene/Character/Prop/Fusion/Audio 和 Split/Retry/Return 操作。
7. P1：Reference priority/scope/authority/conflict 与冻结映射。
8. P1：分页、聚合优化、虚拟化，达到大项目性能门槛。
9. 环境阻断：恢复 orchestrator/image/vision/TTS/music/SFX Provider，随后执行真实付费 Provider 验收。

## 9. 未宣称通过的范围

- 没有触发任何真实付费 OpenAI/即梦生成。
- 没有 Firefox（当前机器未安装）。
- Python 依赖漏洞数据库扫描因未安装 `pip-audit` 而 BLOCKED。
- Camera Board、独立 Scene 空间权威、Reference Conflict、Split Shot、Asset Return Loop、项目 Export/Import 在当前 V3 中无完整可操作面，不能标为 PASS。
- 没有破坏或改写《解毒者》正式项目；正式库只做读取和一致性检查。

## 10. 建议验收门槛

修复后至少增加以下自动化：

1. `pending artifact -> approved shot -> assemble` 必须 409。
2. `pending/unregistered artifact -> render estimate/create/approve/worker` 每层都必须阻断。
3. 同资产第二个 Prompt Approved 时，第一个必须自动 superseded，且数据库只能有一个 current-approved。
4. 已批准 prompt_version + 篡改正文必须 409。
5. Generate ×10 只能返回一个 run ID。
6. data-audit 在 missing/unregistered directory 时必须 `ok=false`。
7. 1000 assets/300 shots：assets/dashboard p95 <1s，本地 UI 可交互 <3s，列表 DOM 不随总量线性增长。
8. 新项目无需 Provider 也能手工完成 Project→Story→Shot→Asset→QA→Timeline 基础闭环。

只有这些门槛和真实 Provider/回归/数据完整性全部通过后，才可重新评估 CONDITIONAL GO 或 GO。
