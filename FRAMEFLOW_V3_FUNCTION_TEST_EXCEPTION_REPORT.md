# FrameFlow V3 全功能测试与异常报告

**测试日期：** 2026-08-20  
**产品口径：** FrameFlow V3-only  运行时入口为 `/`，V3 API 为 `/api/v2`；旧版工作台接口按设计返回 `410 legacy_api_retired`。  
**测试工作区：** `D:\11067\Codex\2026-08-13\video-2`  
**报告类型：** 全功能运行时测试、自动化回归、异常边界与环境验收报告

## 1. 结论摘要

V3 自身的核心功能测试通过，未复现 P0/P1 级 V3 业务缺陷：

- V3 Python 专项测试：`29/29` 通过。
- V3 API 全功能矩阵：`5/5` 通过，实际请求项目、图、模板、运行、Agent、Provider、资产、血缘、故事、时间线、代理、渲染、静态文件和旧接口边界。
- 根目录 Node 测试：`39/39` 通过。
- Web Vitest：`5/5` 通过。
- Web TypeScript/Vite 生产构建：通过。
- Python 语法编译：通过。
- `git diff --check`：通过，仅有换行符格式警告，没有空白错误。

当前不能给出“真实交付链完全通过”的原因不是已复现的 V3 逻辑错误，而是本机环境缺少真实执行条件：

1. 本机没有 `ffmpeg`，代理转码和真实 MP4 编码不能完成成功路径验收；已验证任务创建、查询、失败状态和取消边界。
2. 本机没有 Playwright、Chromium、Chrome 或 Edge，无法执行真实浏览器点击、拖拽、键盘和断网恢复 E2E。
3. 没有使用真实付费 Provider；Provider 合约、Mock 路由、凭据脱敏和错误边界已测，真实 Provider 仍需外部验收。
4. `pytest` 未安装；项目现有 Python 测试已使用 `unittest` 执行，不影响已通过的 V3 结果。

### 严重级别汇总

| 级别 | 数量 | 结论 |
|---|---:|---|
| P0 致命 | 0 | 未发现数据丢失、凭据泄露、付费绕过或批准资产覆盖。 |
| P1 高 | 0 | 未发现 V3 核心流程不可用或安全边界失效。 |
| P2 中 | 1 | 环境阻断真实 FFmpeg 成功路径，需在目标机器补测。 |
| P3 低/测试基础设施 | 3 | pytest 未安装、浏览器 E2E 工具缺失、Starlette/httpx 弃用警告。 |
| 旧版合同不通过 | 41 个用例结果 | 旧测试继续调用已退役接口，按 V3-only 设计应迁移或废弃，不计入 V3 产品缺陷。 |

**V3 当前结论：** 代码级回归通过，具备进入“目标机器 + FFmpeg + 真实 Provider + 浏览器 E2E”外部验收的条件；在外部验收完成前，不应宣称最终交付链已完成。

## 2. 测试范围

### 2.1 V3 运行时表面

通过 FastAPI 应用路由盘点得到：

- `65` 个 V3 method-route 注册。
- `56` 个 V3 URL 模板。
- 另有根入口、健康检查、系统诊断、项目文件和生成文件静态服务。
- 旧版 `/api/*` 工作台入口由网关统一退役；`/api/health`、`/api/system/doctor`、项目文件和生成文件属于 V3 运行时支持面。

V3 功能域覆盖如下：

| 功能域 | 已测试内容 |
|---|---|
| 根入口与静态文件 | `/`、V3 构建产物、项目文件服务、生成文件越权路径、未知页面、旧 `/studio/` 入口 |
| 项目 | 列表、读取、创建/更新、缺失项目、项目版本字段 |
| 工作流图 | 读取、保存、revision 冲突、执行环、自环引用、分组、分组环 |
| 工作流模板 | 内置模板列表、自定义模板创建、应用和 revision 冲突 |
| 运行时 | 估价、祖先节点展开、付费审批、运行详情、事件流、缓存命中、缓存失效、重试、暂停、恢复、取消 |
| Agent | 计划创建、快照、补丁预览、锁定节点保护、读取、事件、应用、批准、拒绝、候选列表、凭据脱敏 |
| Provider | 目录、契约、探测、路由预览、能力限制、隐私模式、模型选择、凭据脱敏 |
| 资产库 | 资产列表、元数据更新、引用角色、依赖、revision、资产门、融合门 |
| 资产候选 | 对比组创建、候选归属校验、候选评审、状态保留 |
| 血缘 | 父子血缘创建、读取、跨项目阻断、自指阻断 |
| 故事与分镜 | 结构化故事、revision、质量检查、版本、差异、回滚、候选审批、局部接受、Regulator 交接 |
| 时间线 | 默认文档、多轨片段、revision、批准镜头装配、外部路径阻断 |
| 代理 | 视频 artifact 归属校验、代理作业创建、查询、FFmpeg 缺失失败态 |
| 渲染 | 估价、manifest、输出路径安全、创建、审批、查询、取消、Worker 产物写入（Mock Worker） |
| 数据迁移 | V1/V2/V3 升级、重复迁移幂等、中断回滚、媒体元数据保留 |

### 2.2 未在本机完成的外部验收

以下项目已明确记录为外部条件，不伪造为通过：

- 真实 OpenAI、OpenAI-compatible、OpenCode、火山方舟/Seedance、ComfyUI 媒体调用。
- 真实 TTS、图片生成、视频生成和付费确认后的 Provider 结果。
- 真实 FFmpeg 多轨编码、字幕烧录、波形/缩略图输出的成功路径。
- 真实浏览器中的画布拖拽、缩放、框选、键盘快捷键、时间线拖拽和断网恢复。
- 300 节点 / 1000 资产浏览器性能基准。

## 3. 测试环境与限制

| 项目 | 实际值 | 影响 |
|---|---|---|
| OS | Windows 工作区 | 正常 |
| Python | 3.14.6 | `unittest` 可执行 |
| Node.js | v24.18.0 | Node/Web 测试与构建可执行 |
| FastAPI TestClient | 可用 | API 路由矩阵可执行 |
| FFmpeg | 未找到 | 阻断真实视频代理和成功渲染路径 |
| pytest | 未安装 | 改用 `unittest`，不是产品故障 |
| Playwright/Chromium/Chrome/Edge | 均未找到 | 阻断浏览器 E2E |
| 真实 Provider 凭据 | 未用于本轮付费调用 | 只能完成 Mock/配置/脱敏/错误合同测试 |

测试期间观察到 Starlette 的弃用提示：当前 TestClient 使用 httpx 兼容层，提示未来应安装 `httpx2`。这不影响本轮结果，但建议纳入测试依赖升级。

## 4. 自动化测试结果

### 4.1 已通过的测试命令

| 编号 | 命令 | 实际结果 |
|---|---|---|
| T-01 | `python -m unittest tests.test_v3_delivery tests.test_v3 -q` | `29/29` 通过 |
| T-02 | `python -m unittest tests.test_v3_function_matrix -q` | `5/5` 通过 |
| T-03 | `python -m compileall -q server.py frameflow tests` | 通过 |
| T-04 | `npm test` | `39/39` 通过：11 + 15 + 13 |
| T-05 | `cd web; npm test` | `5/5` 通过 |
| T-06 | `cd web; npm run build` | TypeScript 检查和 Vite 生产构建通过 |
| T-07 | `git diff --check` | 通过；仅有 LF/CRLF 警告 |
| T-08 | V3 route introspection | `65` 个 method-route 注册，`56` 个 URL 模板 |

### 4.2 V3 专项测试用例

`tests/test_v3.py` 在迁移到 V3-only API 后共 `24` 项通过，覆盖：

- 数据迁移幂等、中断回滚、旧项目升级。
- 图 projection、revision 冲突、执行环、引用环、分组和分组环。
- 运行估价、付费审批、祖先节点展开、缓存、缓存失效、重试和错误分类。
- 时间线默认值与 optimistic revision。
- 故事结构、质量检查、版本差异、回滚、候选接受、局部分镜接受。
- Provider 目录、探测、路由预览和凭据脱敏。
- 自定义模板和模板应用。
- Agent 计划、补丁、锁定节点、revision 冲突、候选创建时机。
- artifact lineage。

`tests/test_v3_delivery.py` 共 `5` 项通过，覆盖：

- 根入口为 V3，旧工作台接口返回 `410`。
- 批准镜头自动装配时间线。
- 时间线 revision 和外部文件路径阻断。
- 输出文件名目录穿越阻断。
- 渲染审批、快照、manifest、MP4/SRT/JSON/资产清单/制作报告 URL；Worker 使用 Mock 编码器验证交付记录。

`tests/test_v3_function_matrix.py` 共 `5` 项通过，覆盖：

1. 项目、模板、健康、系统诊断、项目文件、生成文件、根静态入口和缺失资源合同。
2. 运行详情、事件、暂停、恢复、取消和重复取消。
3. Agent 读取、计划事件、拒绝、批准、项目级补丁预览和候选列表。
4. 资产库、元数据、引用、对比组、候选评审、融合门、血缘和非法自指。
5. 代理、时间线渲染估价/创建/查询/取消、故事运行读取/拒绝/取消，以及多个旧 API 退役路径。

## 5. V3 API 路由逐项矩阵

下表按 method-route 注册逐项记录。相同业务处理函数的别名也以实际 URL 调用覆盖；`通过`表示响应合同和关键状态均符合预期。

### 5.1 项目、图、模板、运行

| ID | Method | 路由 | 预期 | 实际 | 结果 |
|---|---|---|---|---|---|
| API-01 | GET | `/api/v2/projects` | 返回项目列表 | 返回 `200` 和 `projects` | 通过 |
| API-02 | GET | `/api/v2/projects/{id}` | 返回文档和 revision | 返回 `200` | 通过 |
| API-03 | PUT | `/api/v2/projects/{id}` | 创建/更新 V3 项目 | 返回 `200`，revision 正常递增 | 通过 |
| API-04 | GET | `/api/v2/projects/{id}/graph` | 返回默认 8 节点图 | 返回 `200`，图可读取 | 通过 |
| API-05 | PUT | `/api/v2/projects/{id}/graph` | 保存图并检测 revision | 正确保存；旧 revision 返回 `409` | 通过 |
| API-06 | GET | `/api/v2/workflow-templates` | 返回内置和自定义模板 | 返回 `200` | 通过 |
| API-07 | POST | `/api/v2/workflow-templates` | 创建合法自定义模板 | 返回 `200`；非法图被拒绝 | 通过 |
| API-08 | POST | `/api/v2/projects/{id}/apply-template` | 应用模板 | 返回 `200`；revision 冲突返回 `409` | 通过 |
| API-09 | POST | `/api/v2/runs/estimate` | 计算节点数、付费节点和参数快照 | 返回正确估价和祖先节点 | 通过 |
| API-10 | POST | `/api/v2/runs` | 创建免费或待确认运行 | 免费运行排队；付费运行 `awaiting_confirmation` | 通过 |
| API-11 | GET | `/api/v2/runs/{id}` | 返回运行、节点和审批门 | 返回 `200` | 通过 |
| API-12 | POST | `/api/v2/runs/{id}/approve` | 审批后排队 | 返回 `200`，审批门变更为 approved | 通过 |
| API-13 | POST | `/api/v2/runs/{id}/pause` | queued/running 可暂停 | 受控 queued 状态返回 `200` | 通过 |
| API-14 | POST | `/api/v2/runs/{id}/resume` | paused/failed 可恢复 | 返回 `200` 并重新排队 | 通过 |
| API-15 | POST | `/api/v2/runs/{id}/cancel` | 可取消运行且不能重复取消 | 首次 `200`，重复 `409` | 通过 |
| API-16 | GET | `/api/v2/runs/{id}/events` | 返回 SSE 事件流 | 可读取 created、cached、retry 等事件 | 通过 |

### 5.2 Agent、Provider、血缘

| ID | Method | 路由 | 预期 | 实际 | 结果 |
|---|---|---|---|---|---|
| API-17 | POST | `/api/v2/agent/plans` | 生成待审阅计划，不直接改项目 | 返回 awaiting_review 和脱敏快照 | 通过 |
| API-18 | POST | `/api/v2/projects/{id}/agent/plans` | 项目级 Agent 入口 | 返回计划；路径 ID 不一致会冲突 | 通过 |
| API-19 | POST | `/api/v2/agent/patches/preview` | 预览结构化补丁 | 返回 preview；锁定节点/版本冲突被阻断 | 通过 |
| API-20 | POST | `/api/v2/projects/{id}/agent/patches/preview` | 项目级补丁预览别名 | 返回 `200` | 通过 |
| API-21 | GET | `/api/v2/projects/{id}/agent/plans` | 列出项目计划 | 返回 `plans` | 通过 |
| API-22 | GET | `/api/v2/agent/plans/{id}` | 读取单个计划 | 返回脱敏计划 | 通过 |
| API-23 | GET | `/api/v2/agent/plans/{id}/events` | 读取计划事件 | 返回 created/rejected/applied 事件 | 通过 |
| API-24 | POST | `/api/v2/agent/plans/{id}/apply` | 应用审阅后的补丁 | 图 revision 更新；候选才生成 | 通过 |
| API-25 | POST | `/api/v2/agent/plans/{id}/approve` | 通过审批并应用 | 空补丁受控返回 `200` | 通过 |
| API-26 | POST | `/api/v2/agent/plans/{id}/reject` | 拒绝计划 | 状态变 rejected；再次应用 `409` | 通过 |
| API-27 | GET | `/api/v2/projects/{id}/agent/candidates` | 列出候选版本 | 返回候选且不覆盖 active | 通过 |
| API-28 | GET | `/api/v2/providers/catalog` | 返回能力、模型和状态 | 返回 `200`；未出现 API key/credential_ref | 通过 |
| API-29 | GET | `/api/v2/providers/{id}/contract` | 返回 Provider 合约 | 配置 Provider 返回 `200`，未知 Provider `404` | 通过 |
| API-30 | POST | `/api/v2/providers/{id}/probe` | 探测 Provider | Mock/无密钥边界返回结构化结果 | 通过 |
| API-31 | POST | `/api/v2/providers/route-preview` | 按能力、隐私、尺寸和模型路由 | 返回 selected/拒绝原因及估价 | 通过 |
| API-32 | POST | `/api/v2/artifacts/{id}/lineage` | 创建同项目父子血缘 | 成功；自指和跨项目被拒绝 | 通过 |
| API-33 | GET | `/api/v2/artifacts/{id}/lineage` | 读取父子血缘 | 返回 parents/children | 通过 |

### 5.3 资产、故事、时间线、代理、渲染

| ID | Method | 路由 | 预期 | 实际 | 结果 |
|---|---|---|---|---|---|
| API-34 | GET | `/api/v2/projects/{id}/assets` | 返回统一资产库及 readiness | 返回 `200` | 通过 |
| API-35 | PATCH | `/api/v2/projects/{id}/assets/{asset}` | 保存 metadata、引用和依赖 | revision 递增；未知依赖被拒绝 | 通过 |
| API-36 | GET | `/api/v2/projects/{id}/assets/{asset}/comparisons` | 读取对比组 | 返回 comparisons | 通过 |
| API-37 | POST | `/api/v2/projects/{id}/assets/{asset}/comparisons` | 创建候选对比组 | 正确登记候选归属 | 通过 |
| API-38 | POST | `/api/v2/projects/{id}/assets/{asset}/comparisons/{cmp}/review` | 评审候选 | 决策和分数被持久化 | 通过 |
| API-39 | POST | `/api/v2/projects/{id}/assets/{asset}/fusion-gate` | 检查融合门 | 缺失基础资产返回 blocked；非 fusion 返回 `422` | 通过 |
| API-40 | GET | `/api/v2/projects/{id}/asset-gates` | 汇总资产门 | 返回缺失 A 资产和 fusion gates | 通过 |
| API-41 | GET | `/api/v2/projects/{id}/story` | 返回结构化故事和检查 | 返回 `200` | 通过 |
| API-42 | GET | `/api/v2/projects/{id}/story/checks` | 返回生成器/连续性检查 | 返回问题列表和 ok | 通过 |
| API-43 | PUT | `/api/v2/projects/{id}/story` | 保存故事并检测 revision | 成功；旧 revision `409` | 通过 |
| API-44 | GET | `/api/v2/projects/{id}/story/diff` | 比较版本 | 返回新增/删除/变化 | 通过 |
| API-45 | POST | `/api/v2/projects/{id}/story/rollback` | 新版本回滚，不覆盖历史 | 返回新 revision | 通过 |
| API-46 | GET | `/api/v2/projects/{id}/story/versions` | 列出 script/storyboard 版本 | 返回版本记录 | 通过 |
| API-47 | POST | `/api/v2/projects/{id}/story/runs` | 创建故事运行草稿 | 返回 draft 和 source snapshot | 通过 |
| API-48 | GET | `/api/v2/projects/{id}/story/runs` | 列出故事运行 | 返回 runs | 通过 |
| API-49 | GET | `/api/v2/story-runs/{id}` | 读取故事运行 | 返回完整链路状态 | 通过 |
| API-50 | POST | `/api/v2/story-runs/{id}/start` | 启动 storyboard 阶段 | Mock Provider 下进入 review_required | 通过 |
| API-51 | POST | `/api/v2/story-runs/{id}/accept-storyboard` | 接受全部/局部故事板 | 局部接受保留未选镜头 | 通过 |
| API-52 | POST | `/api/v2/story-runs/{id}/accept-regulator` | 接受资产总控 | 生成资产依赖和 missingA 门 | 通过 |
| API-53 | POST | `/api/v2/story-runs/{id}/reject-storyboard` | 拒绝 storyboard | 返回 rejected | 通过 |
| API-54 | POST | `/api/v2/story-runs/{id}/reject-regulator` | 拒绝 regulator | 返回 rejected | 通过 |
| API-55 | POST | `/api/v2/story-runs/{id}/cancel` | 取消故事运行 | 返回 canceled | 通过 |
| API-56 | GET | `/api/v2/projects/{id}/timeline` | 返回默认时间线 | 默认宽高/FPS/轨道结构正确 | 通过 |
| API-57 | PUT | `/api/v2/projects/{id}/timeline` | 保存多轨时间线 | revision 递增；重复/越界被拒绝 | 通过 |
| API-58 | POST | `/api/v2/projects/{id}/timeline/assemble` | 装配批准镜头 | 只装配 approved artifact | 通过 |
| API-59 | POST | `/api/v2/projects/{id}/proxies` | 创建视频代理 | 创建 queued；无 FFmpeg 后可进入 failed | 通过/环境限制 |
| API-60 | GET | `/api/v2/proxies/{id}` | 查询代理状态 | 返回状态、错误或 URL | 通过 |
| API-61 | POST | `/api/v2/renders/estimate` | 生成交付 manifest 和估价 | 返回零费用估价、inputs、tracks | 通过 |
| API-62 | POST | `/api/v2/renders` | 创建渲染作业 | 未确认进入 awaiting_confirmation | 通过 |
| API-63 | GET | `/api/v2/renders/{id}` | 查询渲染作业 | 返回 request/manifest/result/error | 通过 |
| API-64 | POST | `/api/v2/renders/{id}/approve` | 审批渲染 | Mock Worker 下成功生成交付记录 | 通过 |
| API-65 | POST | `/api/v2/renders/{id}/cancel` | 取消渲染 | 首次成功，重复取消 `409` | 通过 |

## 6. 异常与安全边界结果

| 编号 | 场景 | 预期 | 实际 | 级别 | 结论 |
|---|---|---|---|---|---|
| E-01 | 旧 `/api/projects` | 明确退役，不静默转发 | `410`, `legacy_api_retired` | 信息 | 符合 V3-only |
| E-02 | 旧 Provider/资产/故事接口 | 统一退役 | 代表性路径均 `410` | 信息 | 符合 V3-only |
| E-03 | 项目 revision 冲突 | 拒绝过期写入 | `409` | P1 安全边界 | 通过 |
| E-04 | 图执行环 | 拒绝保存 | `422` | P1 数据完整性 | 通过 |
| E-05 | 图引用环 | 允许保存 | `200` | 功能合同 | 通过 |
| E-06 | Agent 修改锁定节点 | 拒绝预览 | `422` | P1 安全边界 | 通过 |
| E-07 | Agent project/graph revision 过期 | 计划失效 | `409` | P1 数据完整性 | 通过 |
| E-08 | 付费运行未确认 | 不执行媒体调用 | `awaiting_confirmation` | P1 费用安全 | 通过 |
| E-09 | 重复审批/取消 | 拒绝非法状态迁移 | `409` | P2 状态机 | 通过 |
| E-10 | Provider catalog/Agent snapshot | 不返回 credential/API key | 未发现敏感字段 | P0 安全 | 通过 |
| E-11 | 时间线外部绝对路径 | 不允许直接渲染 | 估价 `422` | P0 路径安全 | 通过 |
| E-12 | 渲染输出 `../outside.mp4` | 阻断目录穿越 | `422` | P0 路径安全 | 通过 |
| E-13 | artifact 不属于当前项目 | 阻断时间线/代理 | 结构化 `404/422` | P0 数据隔离 | 通过 |
| E-14 | 血缘自指 | 拒绝自指 | `422` | P1 数据完整性 | 通过 |
| E-15 | 资产非 fusion 调 fusion gate | 拒绝错误类型 | `422` | P2 输入校验 | 通过 |
| E-16 | 旧 `/studio/` 页面 | 不再提供旧入口 | `404` | 信息 | 符合全新 V3 |
| E-17 | 代理/渲染缺 FFmpeg | 任务可观测失败，不崩溃 | 任务返回/查询成功，失败信息可读 | P2 环境 | 待目标机补测 |

## 7. 全量旧测试集合结果与分类

最后一次 Python 全量执行命令：

```powershell
python -m unittest discover -s tests -p 'test_*.py' -q
```

结果：`Ran 86 tests`，`45` 个通过，`22` 个 failure，`19` 个 error。非通过项集中在旧接口测试，具体如下：

| 文件 | 结果 | 原因 | 是否 V3 缺陷 |
|---|---:|---|---|
| `tests/test_v3.py` | `24/24` 通过 | 已迁移到 `/api/v2` V3 合同 | 否 |
| `tests/test_v3_delivery.py` | `5/5` 通过 | V3 交付测试 | 否 |
| `tests/test_v3_function_matrix.py` | `5/5` 通过 | V3 路由/异常矩阵 | 否 |
| `tests/test_opencode_client.py` | `4/4` 通过 | Provider 客户端纯模块测试 | 否 |
| `tests/test_provider_adapters.py` | `7/8` 通过 | 1 项仍创建旧 `/api/provider-profiles` | 否，测试合同过期 |
| `tests/test_asset_intake.py` | 失败/错误集中出现 | 继续调用旧 `/api/assets/*` 和旧故事优化入口，收到 `410` 后仍按旧 JSON 取字段 | 否，测试合同过期 |
| `tests/test_server.py` | 失败/错误集中出现 | 继续调用旧 `/api/projects`、`/api/provider-profiles` 等；另断言旧版本 `2.5.0` | 否，测试合同过期 |

### 7.1 旧测试失败的共同表现

旧测试收到以下设计内响应：

```json
{
  "code": "legacy_api_retired",
  "message": "旧版接口已在 FrameFlow V3 中退役，请使用 /api/v2。",
  "retryable": false
}
```

部分旧测试没有先断言 HTTP 状态，而是继续读取旧字段，例如 `json["artifact"]`、`json["profiles"]` 或 `json["id"]`，因此表现为 `KeyError`。这些是旧测试未迁移造成的级联错误，不是 V3 API 返回结构随机变化。

### 7.2 处理建议

- 不恢复旧路由，也不为了让旧测试通过而重新暴露旧版内容。
- 将 `tests/test_server.py`、`tests/test_asset_intake.py` 和 Provider API 部分迁移到 `/api/v2`，或从 V3 发布门禁中移除并标记为 legacy contract。
- 新测试统一使用 `tests/test_v3.py`、`tests/test_v3_delivery.py` 和 `tests/test_v3_function_matrix.py` 作为 V3 回归基线。

## 8. 前端功能测试结论

### 已验证

- React/Vite 入口可构建。
- 图编辑器单元测试 `5/5`：节点/边转换、组隐藏、关系颜色和编辑快照相关逻辑。
- 根目录业务状态测试 `39/39`：项目阶段状态、资产就绪、融合阻断、Seedance 门、媒体解析和项目切换刷新。
- `web/src/api.ts` 未发现旧 `/api/*` 调用；前端调用面统一为 `/api/v2`。
- `web/dist` 生产文件成功生成，根 `/` 可服务 `id="root"` 的 V3 页面。

### 尚未完成真实浏览器验证

因为环境没有浏览器自动化运行时，本轮没有声称以下动作已在真实 DOM 中通过：

- 无限画布拖拽、缩放、框选、多选、连接、删除、撤销和键盘操作。
- Agent 面板的真实输入、审批、拒绝和错误 toast。
- 时间线 clip 拖拽、拆分、字幕增加、音频轨编辑。
- 断网、恢复、重复点击和长任务轮询。
- 300 节点/1000 资产的性能和内存。

这些属于下一轮浏览器 E2E，不应被当前 Vitest 和 build 结果替代。

## 9. 异常清单与后续动作

### EX-01：FFmpeg 不存在

- **严重级别：** P2，环境阻断。
- **现象：** `Get-Command ffmpeg` 返回未找到。
- **影响：** 代理生成和 V3 真实交付 Worker 无法验证成功编码；Mock Worker 成功路径已通过。
- **复现：**

  ```powershell
  ffmpeg -version
  ```

- **建议：** 在目标机器安装并加入 PATH，然后执行代理 360p/540p/720p、视频+叠加+对白+配乐+字幕的真实导出。

### EX-02：浏览器 E2E 工具缺失

- **严重级别：** P3，测试基础设施。
- **现象：** Playwright、Chromium、Chrome、Edge 均未找到。
- **影响：** 无法对真实 UI 交互和性能给出通过结论。
- **建议：** 配置浏览器自动化依赖后，新增 V3-only 浏览器测试套件。

### EX-03：pytest 未安装

- **严重级别：** P3，测试基础设施。
- **现象：** `python -m pytest -q` 返回 `No module named pytest`。
- **影响：** 未使用 pytest runner；项目 unittest 测试正常执行。
- **建议：** 若团队标准要求 pytest，补充测试依赖；否则保留 `unittest` 作为当前无依赖回归入口。

### EX-04：旧测试合同未迁移

- **严重级别：** 不作为 V3 产品异常；发布前需清理测试门禁。
- **现象：** 全量集合出现 `22 failure + 19 error`，均集中于旧 `/api` 合同和旧版本号。
- **影响：** 直接将全量旧集合作为 CI 门禁会错误阻断 V3-only 发布。
- **建议：** 更新/隔离旧测试，不恢复旧运行时接口。

### EX-05：Starlette/httpx 弃用警告

- **严重级别：** P3。
- **现象：** TestClient 提示当前 httpx 兼容方式未来弃用，应安装 `httpx2`。
- **影响：** 本轮不影响测试结果，未来依赖升级可能影响测试启动。
- **建议：** 固定并升级测试依赖，完成一次 TestClient 兼容性验证。

## 10. 发布建议

### 可以确认的事项

- V3-only 根入口和 `/api/v2` API 合同在本地可用。
- V3 数据迁移、图编排、Agent 审批、资产门、故事版本、时间线 revision、渲染审批和路径安全已有自动化证据。
- 旧接口没有静默回退，代表性旧接口均明确返回 `410`。
- 未发现凭据写入项目快照、Agent 快照、Provider 目录或 render 快照的问题。

### 发布前必须补齐的事项

1. 安装并验证 FFmpeg，完成真实代理和多轨导出成功路径。
2. 配置浏览器 E2E 运行时，执行 UI 全流程和断网恢复。
3. 在用户允许的非付费或明确批准范围内完成真实 Provider 验收。
4. 把旧测试迁移到 V3-only，避免 CI 继续把预期的 `410` 视为失败。
5. 在目标机器执行 300 节点/1000 资产性能基准。
6. 发布前保留数据库备份、项目导出、迁移报告和本报告。

## 11. 证据文件

- [V3 综合升级计划](D:\11067\Codex\2026-08-13\video-2\FRAMEFLOW_V3_COMPREHENSIVE_UPGRADE_PLAN.md)
- [V3 交付测试](D:\11067\Codex\2026-08-13\video-2\tests\test_v3_delivery.py)
- [V3 功能测试](D:\11067\Codex\2026-08-13\video-2\tests\test_v3.py)
- [V3 功能矩阵测试](D:\11067\Codex\2026-08-13\video-2\tests\test_v3_function_matrix.py)
- [V3 API 客户端](D:\11067\Codex\2026-08-13\video-2\web\src\api.ts)
- [V3 React 工作台](D:\11067\Codex\2026-08-13\video-2\web\src\App.tsx)

## 12. 本轮设置板块重做增量报告（2026-08-20）

### 12.1 结论

设置板块已按“全新 V3 迭代”重新实现。旧设置界面没有恢复，旧 `/api/provider-profiles`、`/api/provider-presets`、`/api/settings/*` 路径仍然由 V3 网关返回 `410 legacy_api_retired`。新设置控制面唯一使用 `/api/v2/settings*`。

工作台已重启并完成在线检查：

| 检查项 | 结果 |
|---|---|
| `GET /api/health` | `200`，V3 `3.0.0`，schema `6` |
| `GET /api/v2/settings` | `200`，settings `3.0` |
| 在线 Provider 数量 | `4` |
| 能力清单 | `11` 项 |
| 真实 OpenAI 模型探测 | 成功，`118` 个模型，约 `1888ms` |
| Web 构建 | 通过 |
| Web Vitest | `5/5` 通过 |
| V3 Python 回归（含设置） | `39/39` 通过 |
| 根目录 Node 回归 | `39/39` 通过（11 + 15 + 13） |

### 12.2 新增功能范围

#### 设置总览

- V3-only 运行时、产品版本、schema 版本。
- SQLite 数据库路径和状态。
- 系统凭据库可用性及后端类型。
- FFmpeg / ffprobe 探测状态。
- OpenAI 配置状态、Provider 数量和磁盘可用空间。
- 一键重新检测全部设置状态。

#### Provider 管理

- 统一 Provider 目录：OpenAI、OpenAI-compatible、火山方舟、OpenCode、ComfyUI。
- 新建、保存、启用/停用和删除自定义 Provider。
- DeepSeek、OpenCode、ComfyUI 快速接入预设。
- Base URL、能力声明、扩展 JSON 配置。
- OpenCode Server 用户名、Agent、Provider/model 参数。
- 连接探测、最近健康状态、模型目录、模型 readiness。

#### 凭据边界

- API key 只写入系统凭据库。
- 支持从允许的环境变量导入。
- 支持清除系统凭据；不会修改环境变量。
- 页面只显示脱敏状态，不回显明文。
- 设置接口、Provider 目录、探测结果和测试输出均未发现明文密钥。

#### 能力路由

- `orchestrator`、`vision`、`image`、`image_edit`、`video`、`tts`、`music`、`sfx`、`lip_sync`、`upscale`、`upload` 共 11 项能力。
- 每项能力可绑定 Provider 和模型。
- 已停用 Provider 不允许作为默认绑定。
- 不支持目标能力的 Provider 不允许绑定。
- 编排模型仍经过当前 Provider 模型约束校验。

### 12.3 新增 V3 API 验证矩阵

| API | 成功路径 | 异常/安全边界 |
|---|---:|---:|
| `GET /api/v2/settings` | 通过 | 明确 V3-only、凭据脱敏 |
| `GET /api/v2/settings/providers` | 通过 | 预设目录返回脱敏配置 |
| `POST /api/v2/settings/providers` | 通过 | 非 HTTPS 远程地址返回 `422` |
| `POST /api/v2/settings/providers/from-preset/{id}` | 通过 | 缺失预设返回 `404` |
| `PATCH /api/v2/settings/providers/{id}` | 通过 | 配置更新不改变 Provider 类型 |
| `DELETE /api/v2/settings/providers/{id}` | 通过 | 默认配置和仍在绑定的配置禁止删除 |
| `POST .../credential` | 通过（Mock 凭据库） | 响应不包含明文 secret |
| `POST .../credential/import` | 通过（Mock 环境变量） | 缺失环境变量返回 `404` |
| `DELETE .../credential` | 通过 | 清除操作幂等，不删除环境变量 |
| `POST .../probe` | 通过（Mock + 真实 OpenAI） | Provider 错误沿用分类和可重试边界 |
| `GET .../models` | 通过 | 只返回缓存模型目录 |
| `GET /api/v2/settings/capability-bindings` | 通过 | 返回绑定 Provider 摘要 |
| `PUT /api/v2/settings/capability-bindings` | 通过 | 停用 Provider 返回 `409` |
| `GET /api/v2/settings/orchestrator-model-options` | 通过 | 返回 V3 模型选项 |
| 旧 `/api/provider-profiles` | `410` | 未恢复旧接口 |

### 12.4 本轮发现并修复的异常

#### SET-01：设置能力总览为空

- **级别：** P1（已修复）。
- **原因：** 用临时 OpenAI profile 生成统一契约时，OpenAI adapter 没有把通用能力清单作为默认值，导致总览接口的能力数组为空。
- **修复：** 设置总览直接使用统一 Provider contract 的 `CAPABILITIES`，固定返回 11 项 V3 能力。
- **回归：** `test_settings_overview_is_v3_only_and_redacted` 通过。

#### SET-02：非法 Base URL 校验会产生 500

- **级别：** P2（已修复）。
- **原因：** Pydantic `RequestValidationError.errors()` 的 `ctx.error` 是 `ValueError` 对象，直接放入 `JSONResponse` 时无法 JSON 序列化。
- **修复：** 统一校验异常处理使用 `jsonable_encoder(exc.errors())`。
- **回归：** 非 HTTPS 远程地址现在稳定返回 `422 validation_error`。

#### SET-03：旧运行进程不会自动加载新设置页面

- **级别：** P2（环境问题，已处理）。
- **现象：** 重启前 `/api/health` 正常，但新 `/api/v2/settings` 返回 `404`。
- **原因：** 8787 端口仍由旧 Python 进程占用。
- **处理：** 停止旧进程并用当前 V3 代码重启；重启后健康接口和设置接口均为 `200`。

### 12.5 当前仍需外部条件补测的项

- 设置页面真实浏览器点击、键盘输入、响应式布局和刷新恢复：本机未安装 Playwright/Chromium，当前已完成 TypeScript、构建和 HTTP 自动化验证。
- ComfyUI 真实本地服务探测：当前机器未确认存在运行中的 ComfyUI 服务，已验证无服务时错误分类路径。
- OpenCode Server 真实连接：需用户提供正在运行的 Server 和已连接模型后补测；设置页已提供 Server URL、用户名、Agent 和模型入口。
- API key 写入 Windows Credential Manager 的真实写入路径：自动化测试使用 Mock 防止测试密钥写入用户系统；真实在线 OpenAI 探测已经验证读取现有凭据并成功调用 `/models`。

### 12.6 本轮证据文件

- [设置专项测试](D:\11067\Codex\2026-08-13\video-2\tests\test_v3_settings.py)
- [V3 设置 API](D:\11067\Codex\2026-08-13\video-2\server.py)
- [设置页面](D:\11067\Codex\2026-08-13\video-2\web\src\App.tsx)
- [设置 API 客户端](D:\11067\Codex\2026-08-13\video-2\web\src\api.ts)
- [设置类型](D:\11067\Codex\2026-08-13\video-2\web\src\types.ts)
- [设置样式](D:\11067\Codex\2026-08-13\video-2\web\src\styles.css)
