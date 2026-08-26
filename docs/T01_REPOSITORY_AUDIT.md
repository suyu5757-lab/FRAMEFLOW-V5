# FRAMEFLOW V5.3.2

## T01 Repository Audit

审计日期：2026-08-26（Asia/Shanghai）
审计类型：T01-R Repository Audit Remediation
审计边界：只读盘点、分类、迁移映射与冲突记录；本轮不删除、不移动、不重构、不迁移、不改数据库、不改 Skill、不改 Workbench、不改同步机制。

## Executive Summary

当前仓库是一个 V3 实际运行栈与 V5 目标骨架并存的过渡状态：实际入口为根目录 `server.py`（FastAPI）和 `web/`（React/Vite），实际运行时由 `frameflow/database.py` 与 `frameflow/runtime.py` 驱动；V5 的 `core/schemas/`、`core/migration/` 和 `core/runtime/state_store/` 已存在，但尚未接管生产 API、生产数据库或任务运行链。

实际数据库是 `data/frameflow.db` 中的 V3 41 表结构，不是 T02 声明的独立 11 表运行库。`projects`、`tasks`、`artifacts` 等同名表存在结构与所有权冲突，不能通过改名或直接在线迁移解决。必须先保留 V3 兼容边界，完成备份、映射、适配、验证和可回滚演练后，才可切换唯一写入者。

当前 Skill 仓库有一组可工作的图像、视频、Seedance 和音频/语音 Skill；历史目录仍在 `D:\AIGC\SUYU`，没有发现 `photo repair skill`。Seedance 的现实实现是 `seedance-shot-packager` 负责生产包、`frameflow/jimeng_cli.py` 负责官方 CLI 的本地提交/查询/取消；没有发现独立的 Seedance HTTP Provider、Manual Bridge 或 Mock Provider 适配器。

T01-R 审计准出：已建立 Reality Map、五类 Inventory、Workbench/Runtime/Skill/Comfy 分类、CURRENT→TARGET Migration Map、Collision Matrix 和 Protected Legacy List。没有任何现存表面满足删除条件；`DELETE_LATER = 0`。

## Git Reality

以下信息由实际 Git 命令复核，审计文档生成前没有切换分支、重置、清理或推送。

| 项目 | 实际结果 |
|---|---|
| Repository root | `D:/11067/CodexWorkspaces/frameflow-v3` |
| 等价挂载路径 | `D:\cc\workspace` |
| Current branch | `dev/v5.3.2` |
| HEAD before T01-R | `9b674b008ef417c548b27ccb2dea49d76ad5eb2b` |
| `main` | 仍为 `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641`，未回改 |
| Stable tag | `v5.3.2-gate0-baseline` → `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641` |
| Remotes | `origin` → `https://github.com/suyu5757-lab/video-workbench.git`；`local-source` → `C:\Users\11067\Desktop\video 工作台制作` |
| Recent task commits | `9b674b0` T03；`b11a074` T02；`488f0f1` T01.5；`7e405b4` T00 |
| Working tree | dirty；既有修改和未跟踪文件均保留，未纳入本审计提交 |
| Git automation | 未发现每日自动同步脚本；既有 CI/启动任务不执行 Git 同步 |

既有脏项包括 `.gitignore`、`README.md`、`server.py`、`启动工作台.bat` 的修改，若干根目录 V3 文件删除标记，以及大量未跟踪的 V3 文件、审计/指令文件和测试/前端目录。本轮只允许新增本文件，提交前将精确暂存 `docs/T01_REPOSITORY_AUDIT.md`。

## Physical Root Inventory

| Root | Exists | Reparse/symlink observation | Actual role | Rule |
|---|---:|---|---|---|
| `D:\11067\CodexWorkspaces\frameflow-v3` | YES | 未发现 reparse point | 唯一项目根；V3 实现、V5 骨架、测试和文档 | 本轮唯一可写根 |
| `D:\11067\CodexHome\skills` | YES | 未发现 reparse point | 当前 Skill 仓库 | 只读清点；不迁移/改名/删除 |
| `D:\AIGC\SUYU` | YES | 未发现 reparse point | 历史资产、历史文档和历史 Skill | READ_ONLY；不回写、不移动、不复制 |
| `D:\ComfyUI` | YES | 未发现 reparse point | 引擎与权重边界 | 不向项目复制权重或引擎内容 |

实际项目目录包含 `.github/`、`core/`、`data/`、`docs/`、`frameflow/`、`scripts/`、`tests/` 和 `web/`；项目根没有 `workbench/`，也没有 `comfy/bridge`、`comfy/registry` 或 `comfy/adapters`。

## Workbench Inventory

### Actual Workbench

| Surface | Actual evidence | Classification | V5 implication |
|---|---|---|---|
| `server.py` | FastAPI app；提供健康检查、系统 doctor、项目 CRUD、Provider/Agent、恢复、资产、任务和 V3 API 路由 | REFACTOR | 保留现有入口作为兼容层，逐步把写入委托给 V5 Task Runtime/StateStore；不可直接改成双写 |
| `web/` | React/Vite `frameflow-v3-studio`；含 `src/App.tsx`、资产板、音频工作台、图编辑器、Vitest 和 Playwright | REFACTOR | 作为现有 UI 基础演进到 V5 Workbench；`workbench/` 目标目录当前不存在 |
| 根目录旧文件 | `app.js`、`audio.js`、`index.html`、`styles.css` 在工作树显示用户既有删除标记 | LEGACY | 受保护的历史表面；不在本轮恢复或删除 |
| `/api` 与 `/api/v2` | 实际 API 仍由 `server.py` 提供，README 将 V3 `/api/v2` 作为主工作流 | REFACTOR | 需要 API 兼容适配与版本化切换，不能自动合并或替换 |

### Planned Workbench

`workbench\backend` 与 `workbench\frontend` 未找到，故标记为 `NOT_IMPLEMENTED`，不是可删除目录。当前 `web/` 是实际 UI，不能把“目标目录不存在”误判为“当前 UI 不存在”。

## Runtime Inventory

| Surface | Current role and evidence | Classification | Risk/target |
|---|---|---|---|
| `frameflow/runtime.py` | `execute_v3_run` 读取 `workflow_runs_v3`、`node_runs_v3`，做拓扑就绪、并发批次、指纹缓存、失败分类、重试、暂停/取消和运行事件 | REFACTOR | 现有运行状态依赖 V3 表；目标需接入 StateStore/Task Runtime，并保持 redaction、retry 和 cancellation 语义 |
| `frameflow/database.py` | `Database` 自动创建父目录并迁移，`SCHEMA_VERSION = 16`，使用 `schema_migrations`；连接启用 FK，迁移设置 WAL | LEGACY | 是当前生产写入者，必须作为受保护兼容组件；不得与 V5 StateStore 双写 |
| `data/frameflow.db` | 只读探测为 41 张业务/迁移表，`journal_mode=wal`；裸连接探测 `foreign_keys=0`，`busy_timeout=5000`；V3 连接代码逐连接启用 FK | MIGRATE | 先备份与结构/数据映射，再以单一 owner 切换；本轮没有迁移此库 |
| `core/runtime/state_store/` | T03 新增的 SQLite WAL StateStore；测试覆盖 11 表、并发/锁语义和 JSON payload，但当前只被 StateStore 测试引用 | MIGRATE | 目标运行时持久化候选；必须先做 adapter、兼容读路径、回滚和集成验证 |
| `core/schemas/` | T02 的 11 表声明与 ShotSpec v2.2 JSON Schema | KEEP | 保留为目标契约来源，尚未声明为生产库事实 |
| `core/migration/` | T02 Alembic 离线 SQL 骨架；`env.py` 在线模式明确不执行 | KEEP | 仅能生成 dry-run；不能据此声称生产 DB 已迁移 |
| `frameflow/v3.py`、`workflows.py`、`story.py` | V3 图、时间线、故事和门控辅助函数，读写 V3 表/项目 JSON | REFACTOR | 需要将旧项目文档映射到 V5 project/sequence/shot/artifact 关系 |
| `frameflow/idempotency.py` | 现有 V3 请求/运行幂等辅助 | REFACTOR | 需与 V5 `provider_submissions.idempotency_key/request_hash/shot_spec_version` 对齐 |

## Skill Inventory

### Active Skill Repository: `D:\11067\CodexHome\skills`

下表按实际 Skill 文件和其声明的输入/输出边界盘点；分类是迁移/适配到 V5 Typed Action、Task Runtime 和 artifact/review 契约的工作分类，不代表本轮修改了 Skill。

| Skill | Current inputs | Current outputs | Dependencies/consumers | Classification | V5 target/risk |
|---|---|---|---|---|---|
| `image-copy` | 图片、提示词、视觉参考 | 复现提示词、关键词、模式与参数建议 | `image-blending`、`image-explore` | MIGRATE | 需记录来源、版本、授权和 Prompt QA；不直接生成文件 |
| `image-explore` | 角色/物件/场景提示词或参考 | 变体、原创化、场景重构 prompt pack | `video-asset-regulator`、fusion | MIGRATE | 需转为可审计的 Typed Action/asset version |
| `image-blending` | 角色、物件、场景 prompt 或图像 | 融合方案、正/负提示词、诊断、尺寸建议 | fusion director、shot director | MIGRATE | 需保留参考角色映射与融合 QA 状态 |
| `video-script-storyboard` | 概念、脚本、参考素材 | 可执行 storyboard、shot 表、风险与下一步清单 | `video-asset-regulator` | MIGRATE | ShotSpec/版本化映射是主要兼容风险 |
| `video-asset-regulator` | storyboard handoff、项目资产现状 | 资产依赖表、A/B/C 分类、缺口与路由 | 角色/场景/道具/fusion/Seedance | MIGRATE | 需绑定 stable IDs、artifact readiness 和 review |
| `video-character-design-director` | 角色 brief、参考、连续性要求 | character bible、参考视图计划、角色 prompt pack | asset regulator、fusion | MIGRATE | 需迁移 approved asset 与 identity anchors |
| `video-scene-design-director` | 场景 triad、空间/光线/机位需求 | scene DNA、空间布局、场景 prompt pack、readiness | asset regulator、fusion | MIGRATE | 需映射 scene artifact 与 shot 依赖 |
| `video-prop-design-director` | 道具 brief、结构/材质/交互要求 | prop bible、设计表、prompt pack、fusion test | asset regulator、fusion | MIGRATE | 需映射 prop artifact、交互约束与 QA |
| `video-fusion-production-director` | 已准备角色/道具/场景资产 | 融合生产包、参考帧计划、fusion QA | `video-shot-director` | MIGRATE | 需让融合结果成为可审计 artifact，而非裸图片 |
| `video-shot-director` | storyboard、资产、连续性和导演意图 | per-shot 生成包、视频 QA、编辑交接 | `seedance-shot-packager`、QA | MIGRATE | 需写入 ShotSpec、Provider submission 与 review |
| `seedance-shot-packager` | shot director handoff、参考素材、音频角色 | Seedance/Jimeng 执行包、`@Image/@Video/@Audio` 映射、fallback | `frameflow/jimeng_cli.py`、人工执行 | MIGRATE | 当前是 packaging Skill，不是 Provider API；适配缺口高 |
| `music-sound-designer` | cue、音乐、氛围、foley、版权信息 | 音频生产包、stems、QA 与 handoff | `voice-controller`、timeline、Seedance | MIGRATE | 需对接 audio artifact、rights gate 和 review |
| `voice-performance-director` | voice/dialogue brief、授权和连续性要求 | voice brief、试听/Take QA、handoff | `voice-controller`、timeline | MIGRATE | 需保留 consent/license evidence，禁止无授权克隆 |
| `voice-controller` | voices、dialogues、music cues、sound design | 跨轨 approved handoff、时间线/镜头/Seedance 路由 | 音频专家、timeline、shot | MIGRATE | 需映射 artifact/version/review，禁止隐式合并 |
| `data-analysis-beta` | 结构化数据与分析任务 | 数据质量、报告/图表类分析 | 非核心视频生产支持 | KEEP | 与本轮 V5 生产迁移无直接耦合，保持只读/独立 |

### Historical Skill Repository: `D:\AIGC\SUYU`

历史目录实际包含 `image skill`（`image-blending`、`image-copy`、`image-explore`）、`video skill`（`video-asset-builder`、`video-asset-regulator`、`video-scene-asset-builder`、`video-script-storyboard`）和 `seedance skill`（`seedance-shot-packager`）。这些 Skill/README/历史 docs 是只读遗留面，统一分类 `LEGACY`，不得在本轮迁移、改名、删除或回写。未发现名为 `photo repair skill` 的目录或 Skill；其计划状态为 `NOT_IMPLEMENTED`。

## Provider Inventory

| Surface | Reality | Classification | Migration note |
|---|---|---|---|
| `frameflow/provider_adapters.py` | 有 provider-neutral contract、capability spec、retry policy、normalize；实际类含 `OpenAIAdapter`、`OpenAICompatibleAdapter`、`OpenCodeAdapter`、`JimengCLIAdapter`、`ComfyUIAdapter` | MIGRATE | 需把提交、进度、取消和规范化结果落到 V5 `provider_submissions`/`generations`/`artifacts`；当前仍由 V3 API 调用 |
| `frameflow/providers.py` | OpenAI/compatible 的 HTTP、structured response、image、image edit、speech 和错误分类 | MIGRATE | 需受 Typed Action、幂等、shot spec version 和 approval gate 约束 |
| `frameflow/jimeng_cli.py` | 调用本地 `dreamina` CLI；支持模型探测、`text2video`/`image2video`/`frames2video`、`query_result`、取消和下载结果 | MIGRATE | 这是实际 Seedance 路径的本地 CLI 边界，不是独立 Seedance HTTP Adapter；必须保留手工确认/本地文件/凭据隔离 |
| `frameflow/opencode_client.py` | OpenCode Server 的独立 Agent 接入与结构化请求 | MIGRATE | 需映射为 Typed Action，LLM 不得获得自由 Shell 或直接 DB 写入权 |
| `server.py` Provider routes | 实际负责 profile、capability、health/doctor、task API 组合 | REFACTOR | 未来由 Task Runtime 统一提交/状态/错误；不能保留并行写入路径 |
| Manual Bridge | 未发现独立 `manual_bridge` 模块或目录 | NOT_IMPLEMENTED | 当前仅有 `frameflow/runtime.py` 的 `executor=manual` 阻塞语义；尚非可执行 Provider |
| Mock Provider | 未发现独立 Mock Provider 适配器或 API | NOT_IMPLEMENTED | 只能在后续测试隔离层定义，不能把 checkpoint 当成真实媒体 Provider |

## Seedance Reality

当前 Seedance 链路必须按事实区分三层：

1. `D:\11067\CodexHome\skills\seedance-shot-packager` 输出执行包、参考文件角色、时序、风险和 fallback；它不是 Provider Adapter。
2. `frameflow/jimeng_cli.py` 是项目内的实际本地 CLI 接入，使用官方 `dreamina` 命令和本地登录态，能提交/查询/取消并下载结果；它仍属于 V3 `frameflow/` 代码。
3. 独立 Seedance HTTP API、Manual Bridge 和 Mock Provider 目录/类均未发现。后续必须通过 Provider/Task Runtime 契约补齐，不能在审计中把 Skill packaging 或普通 checkpoint 记为已实现 Provider。

## ComfyUI Inventory

| Surface | Reality | Classification | Boundary |
|---|---|---|---|
| `D:\ComfyUI` | 物理根存在，是外部引擎/权重边界 | KEEP | 不复制权重、模型或引擎文件到项目 |
| `frameflow/provider_adapters.py::ComfyUIAdapter` | 已有面向配置 URL 的 ComfyUI HTTP probe/submit/progress/normalize/cancel | MIGRATE | 需迁移到 V5 provider submission/resource lock 约束；不能视为目标目录结构已存在 |
| `comfy/bridge` | 未找到 | NOT_IMPLEMENTED | 目标桥接层未实现，不创建于本轮 |
| `comfy/registry` | 未找到 | NOT_IMPLEMENTED | 目标能力注册表未实现 |
| `comfy/adapters` | 未找到 | NOT_IMPLEMENTED | 目标项目内适配器目录未实现 |
| Project-local weights | 未发现应有复制；本轮没有复制 | KEEP | 继续禁止从 `D:\ComfyUI` 或历史根复制权重 |

## QA/Retry/Recovery

| Capability | Actual surface | Reality | Classification |
|---|---|---|---|
| Asset QA/readiness | `frameflow/asset_audit.py`、`frameflow/production_gate.py` | 有资产分类、artifact 使用/QA/readiness、引用与生产 artifact gate | MIGRATE |
| Data integrity | `frameflow/data_integrity.py` | 只读扫描项目目录、注册媒体、哈希/路径边界；恢复前不自动登记孤儿文件 | KEEP |
| Audit trail | `frameflow/audit_trail.py` | 有脱敏快照和事件记录 | KEEP |
| Runtime retry | `frameflow/runtime.py`、`frameflow/provider_adapters.py` | 有 retryable/non-retryable 分类、attempt、backoff policy/节点重试 | REFACTOR |
| User retry actions | `frameflow/dashboard.py` | 有 retry story/generation/delivery 等 UI 任务动作 | REFACTOR |
| Recovery | `frameflow/recovery.py` | 有 verified backup、export hash、scan、Preview/Apply、冲突和 manifest token 校验 | KEEP |
| Recovery DB ownership | `recovery_plans_v11` in V3 DB | 当前恢复记录仍写入旧 41 表库 | MIGRATE |
| Failure/contract tests | root tests 有大量 V3 用例；前端有 Playwright e2e；未发现 root `tests/contract`、`tests/failure`、`tests/benchmark` | 部分存在、目标套件缺失 | NOT_IMPLEMENTED |

## Creative App Inventory

| App/capability | Actual evidence | Classification | Target note |
|---|---|---|---|
| Photoshop | 未发现项目内正式 Photoshop adapter/agent/resource-lock 实现 | NOT_IMPLEMENTED | 目标需经 `PHOTOSHOP` Resource Lock，不可假定已接入 |
| After Effects | 未发现正式 AE adapter/agent/resource-lock 实现 | NOT_IMPLEMENTED | 目标需经 `AE` Resource Lock |
| Resolve | 未发现正式 Resolve adapter/agent/resource-lock 实现 | NOT_IMPLEMENTED | 目标需经 `RESOLVE` Resource Lock |
| Comfy GPU | 有外部 ComfyUI 和项目内 HTTP adapter，但未发现目标 `COMFY_GPU` lock manager | NOT_IMPLEMENTED | 目标要求 GPU 锁；当前不应把 HTTP adapter 当成锁实现 |
| FFmpeg | `frameflow/media.py` 有 ffmpeg/ffprobe 检测、标准化、拼接、字幕/音频轨与导出 | MIGRATE | 作为 deterministic media utility 迁移到 Task Runtime/artifact flow |
| Audio/voice UI | `web/` 有 Audio Studio；V3 代码有 TTS、音频 cue、timeline handoff | MIGRATE | 需接 V5 artifact/review/rights；未发现独立 Creative App agent |
| Resource Lock service | 未发现正式锁服务；当前未形成 PS/AE/Resolve/Comfy GPU 互斥执行层 | NOT_IMPLEMENTED | 目标规则是 PS 可与 Comfy GPU 并发，其余互斥；需后续单独实现和测试 |

## Classification Matrix

分类定义：`KEEP` 保留并作为当前/目标稳定输入；`MIGRATE` 通过适配、映射和验证迁入 V5；`REFACTOR` 保留能力但需要边界/所有权重构；`LEGACY` 只读保护的历史/兼容表面；`DELETE_LATER` 只有在迁移完成、兼容层撤除、回滚与 V5 E2E 均通过后才可候选删除；`NOT_IMPLEMENTED` 是计划表面不存在的额外状态，不计入五类删除决策。

| ID | Surface | Classification | V5 action / reason |
|---:|---|---|---|
| K01 | `core/schemas/` 11 表与 ShotSpec v2.2 声明 | KEEP | 目标契约来源 |
| K02 | `core/migration/` Alembic offline 骨架 | KEEP | 保留 dry-run 迁移声明 |
| K03 | `tests/schema`、`tests/migration`、`tests/runtime` V5 用例 | KEEP | 独立验证资产 |
| K04 | root V3 Python tests 与 DB fixtures | KEEP | 当前兼容行为回归网 |
| K05 | `web/tests`、Vitest、Playwright | KEEP | 当前 UI 回归网 |
| K06 | `frameflow/recovery.py` 安全恢复流程 | KEEP | 已有 Preview/Apply/manifest 保护 |
| K07 | `frameflow/audit_trail.py`、`data_integrity.py` | KEEP | 审计与只读完整性基础 |
| K08 | `frameflow/secrets_store.py` | KEEP | 凭据引用/系统凭据边界 |
| K09 | 冻结架构、范围、ADR、Git 审计及本 T01 文档 | KEEP | 事实与决策记录 |
| M01 | `data/frameflow.db` 41 表生产库 | MIGRATE | 备份/映射/适配后切换唯一 owner |
| M02 | `data/projects/{project_id}` 媒体与 V3 项目 JSON | MIGRATE | 映射到 artifact/asset/shot 存储，不复制外部历史资产 |
| M03 | `core/runtime/state_store/` | MIGRATE | 接入 V5 Runtime，完成兼容读、单写和回滚验证 |
| M04 | 当前 active Skill fleet | MIGRATE | 迁移为版本化 Typed Action/artifact/review handoff |
| M05 | `seedance-shot-packager` | MIGRATE | 保留 packaging，补 Provider/Task submission 边界 |
| M06 | `frameflow/jimeng_cli.py` | MIGRATE | 接入 V5 provider submission，保持本地 CLI/确认边界 |
| M07 | `frameflow/opencode_client.py` | MIGRATE | 接入 Typed Action；禁止自由 Shell |
| M08 | `frameflow/asset_audit.py` | MIGRATE | 迁移到 V5 artifacts/assets/reviews |
| M09 | `frameflow/production_gate.py` | MIGRATE | 迁移为 V5 approved-artifact gate |
| M10 | `frameflow/recovery.py` 的 V3 DB 写入部分 | MIGRATE | 迁移 recovery metadata 但保留安全流程 |
| M11 | `frameflow/media.py` FFmpeg utility | MIGRATE | 接入 V5 artifact/task 追踪 |
| M12 | `frameflow/upload_storage.py` | MIGRATE | 统一项目存储 owner 与 artifact registration |
| M13 | `frameflow/dashboard.py` 的业务状态动作 | MIGRATE | 迁移到 V5 task/review/event 状态 |
| M14 | `frameflow/provider_adapters.py` 的输出/提交契约 | MIGRATE | 落到 provider_submissions/generations/artifacts |
| R01 | `web/` actual Workbench UI | REFACTOR | 演进为 V5 Workbench，保留兼容行为 |
| R02 | `server.py` FastAPI actual entry | REFACTOR | 收敛为 API/Task Runtime 边界 |
| R03 | `frameflow/runtime.py` V3 executor | REFACTOR | 由 V5 StateStore/Task Runtime 接管状态 |
| R04 | `frameflow/v3.py`、`workflows.py`、`story.py` | REFACTOR | 保留 V3 读取适配，拆分 V5 domain mapping |
| R05 | `frameflow/agent.py` patch/agent orchestration | REFACTOR | 限制为 Typed Action 与审批预览 |
| R06 | `frameflow/providers.py` raw provider functions | REFACTOR | 收敛凭据、幂等、错误和 artifact contract |
| R07 | `.github/workflows/ci.yml` | REFACTOR | 保留 CI；补齐 V5 tests/dry-run 后再扩展 |
| R08 | `frameflow/idempotency.py` V3 幂等辅助 | REFACTOR | 对齐 provider submission 版本化键 |
| R09 | Windows `FRAMEFLOW-V3-Service`/OpenCode startup tasks | REFACTOR | 保留运行职责，明确不承担 Git sync/迁移职责 |
| R10 | `frameflow/maintenance.py` maintenance actions | REFACTOR | 后续接 V5 ownership；禁止在迁移前删除遗留记录 |
| L01 | `frameflow/database.py` V3 Database 与 migrations 1–16 | LEGACY | 生产兼容 owner；迁移完成前 DO NOT DELETE |
| L02 | V3 41-table schema/data model 的旧同名表 | LEGACY | 受保护数据事实；不得直接覆盖/重命名 |
| L03 | `D:\AIGC\SUYU` 历史 docs/assets/Skills | LEGACY | READ_ONLY，未完成映射前保留 |
| L04 | 根目录旧 `app.js`/`audio.js`/`index.html`/`styles.css` 删除标记 | LEGACY | 用户既有脏状态；不在本轮恢复、删除或提交 |
| N01 | `workbench\backend`、`workbench\frontend` | NOT_IMPLEMENTED | 计划表面不存在 |
| N02 | `comfy\bridge` | NOT_IMPLEMENTED | 计划桥接层不存在 |
| N03 | `comfy\registry` | NOT_IMPLEMENTED | 计划注册表不存在 |
| N04 | `comfy\adapters` | NOT_IMPLEMENTED | 计划项目内适配器目录不存在 |
| N05 | Photoshop/AE/Resolve/正式 Comfy GPU Agent | NOT_IMPLEMENTED | 未发现正式 Creative App/Resource Lock 实现 |
| N06 | 每日自动 Git 同步脚本 | NOT_IMPLEMENTED | 项目、外部脚本、任务计划审计均 NOT FOUND |
| N07 | root `tests/contract`、`tests/failure`、`tests/benchmark` | NOT_IMPLEMENTED | 目标验证套件尚未建立 |
| N08 | `photo repair skill` | NOT_IMPLEMENTED | 历史与 active Skill 根均未发现 |

分类计数：

| Classification | Count |
|---|---:|
| KEEP | 9 |
| MIGRATE | 14 |
| REFACTOR | 10 |
| LEGACY | 4 |
| DELETE_LATER | 0 |
| NOT_IMPLEMENTED | 8 |

## Migration Map: CURRENT → TARGET

| Current reality | Target ownership/contract | Required bridge and gate | Status |
|---|---|---|---|
| `server.py` + V3 `/api`/`/api/v2` | V5 Workbench API + Task Runtime | API compatibility adapter；同一请求只能有一个 DB owner；contract tests | NOT STARTED |
| `web/` React/Vite V3 UI | V5 Workbench frontend | 保留稳定 ID/revision；逐域替换 API；UI e2e 与 rollback | NOT STARTED |
| `frameflow/database.py` + 41-table `data/frameflow.db` | V5 11-table Runtime DB/StateStore | verified backup、schema/data mapping、read adapter、cutover、downgrade/restore drill | NOT STARTED |
| V3 project JSON in `data/projects` | `projects` → `sequences` → `shots` + `metadata_json`/artifact links | stable ID mapping、asset/artifact registration、approved/LOCKED no-rewrite guard | NOT STARTED |
| `frameflow/runtime.py` V3 graph executor | V5 Task Runtime + `tasks/events/resource_locks` | state adapter、idempotent submit、retry/cancel/recovery contract、integration tests | NOT STARTED |
| V3 `provider_profiles`/raw provider calls | `provider_submissions` + `generations` + artifacts | request hash/idempotency key with `shot_spec_version`; typed action and approval | NOT STARTED |
| `frameflow/provider_adapters.py` | provider-neutral V5 adapter boundary | normalize result → artifact; no direct UI/DB side effects outside Task Runtime | NOT STARTED |
| `seedance-shot-packager` | V5 shot handoff + provider submit | packaging remains Skill; Jimeng CLI/Manual/Mock must be separate explicit providers | PARTIAL / GAP |
| `frameflow/jimeng_cli.py` | Seedance provider adapter/submitter | provider submission row, polling events, artifact registration, safe cancel/retry | NOT STARTED |
| Active Skill repository | versioned Skill catalog + Typed Action | preserve inputs/outputs/consumer contract, approval/review evidence | NOT STARTED |
| `D:\AIGC\SUYU` | read-only legacy source | per-surface mapping and rollback evidence before any future archival | PROTECTED |
| `D:\ComfyUI` + current HTTP adapter | V5 `comfy/bridge` + registry + Resource Lock | explicit bridge, registry, adapter tests; no weight copy | NOT IMPLEMENTED |
| FFmpeg/audio/timeline utilities | V5 artifact/task/review pipeline | deterministic output manifest and approved artifact binding | NOT STARTED |
| V3 asset QA/recovery/audit | V5 `reviews`/`events`/artifact readiness | preserve evidence, no implicit auto-apply, migration replay tests | NOT STARTED |
| no formal PS/AE/Resolve/Comfy locks | Creative App Runtime + Resource Lock | define lock ownership, concurrency matrix, timeout/recovery tests | NOT IMPLEMENTED |

## Collision Matrix

| Ownership domain | Current owner | Target owner | Collision | Required resolution |
|---|---|---|---|---|
| Database | `frameflow/database.py` / V3 `data/frameflow.db` | V5 StateStore/11-table runtime | Same names (`projects`, `tasks`, `artifacts`) have incompatible columns/semantics; 41 tables vs 11 | One-way export/import adapter, verified backup, shadow/dry-run, cutover, rollback; no dual write |
| Runtime state | `frameflow/runtime.py` reads/writes `workflow_runs_v3`/`node_runs_v3` | V5 `tasks`, `events`, `resource_locks` and StateStore | Two executors could advance the same work with different state machines | Freeze V3 executor per migration boundary; one task owner; replay and cancellation contract |
| State persistence | V3 `Database.connect()` + legacy `schema_migrations` | `core/runtime/state_store/store.py` + Alembic target | WAL/FK behavior and transaction ownership differ; bare DB probe reports FK off | Define connection PRAGMAs centrally, verify `foreign_keys=ON`, preserve WAL/busy timeout, no production migration in audit |
| Provider submissions | V3 `tasks.provider_task_id`/provider profiles | V5 `provider_submissions`/`generations` | Retry or duplicate requests could create duplicate paid submissions | Idempotency key + request hash + `shot_spec_version`; Task Runtime only submitter; explicit approval |
| Workbench/API | `server.py` V3 endpoints and `web/` | planned V5 Workbench API/`workbench` | UI contracts and revision rules may diverge | Compatibility adapter, endpoint-by-endpoint contract tests, no automatic API cutover |
| Skill execution | Skill repo and historical Skills produce prompt/plan handoffs | V5 Skill catalog + Typed Action | Similar names/versions and outputs may be interpreted as executable side effects | Versioned registry, explicit input/output schemas, approval gate; no Skill business-logic migration in this audit |
| Project storage | `data/projects/{id}` and V3 artifacts/media paths | V5 assets/artifacts and immutable manifests | Same files may be registered twice or rewritten while approved | Stable IDs, hash manifest, LOCKED/approved no-rewrite rule, staged copy only after migration approval |
| QA/review | V3 `asset_qa_runs`, production gate, dashboard actions | V5 `reviews`, artifact readiness and events | A V3 approved/rejected state can be lost in a new artifact row | Preserve evidence and decisions as immutable migration facts; replay tests before cutover |
| Creative apps/resources | No formal lock owner found; FFmpeg is utility | V5 Resource Lock (`PHOTOSHOP`, `AE`, `RESOLVE`, `COMFY_GPU`) | Concurrent app/GPU work could race or violate mutual exclusion | Implement lock manager and concurrency tests before enabling app execution |

## Protected Legacy List — DO NOT DELETE YET

The following remain protected until a later, separately authorized migration has passed compatibility, data integrity, rollback, and V5 end-to-end gates:

- `server.py`, `web/`, and the whole `frameflow/` V3 runtime/provider/recovery surface.
- `frameflow/database.py`, its migrations 1–16, `schema_migrations`, and the live `data/frameflow.db` database.
- `data/projects/` media and project JSON, including files with approved/locked semantics.
- Root files carrying pre-existing deletion markers (`app.js`, `audio.js`, `index.html`, `styles.css`) and all other pre-existing dirty files.
- `D:\AIGC\SUYU` and every historical docs/asset/Skill directory under it.
- `D:\ComfyUI` and its external engine/weight contents.
- Existing active Skills under `D:\11067\CodexHome\skills`; this audit did not modify any Skill file.
- T00/T01.5/T02/T03 commits and their frozen/audit documents.

No item above is a deletion proposal. This list is a guardrail for future work, not authorization to remove or move anything.

## DELETE_LATER Guard

`DELETE_LATER` is currently empty. A component may only be reclassified to `DELETE_LATER` after all of the following are evidenced in a later authorized task:

1. A complete CURRENT→TARGET mapping exists, including data, files, IDs, versions, and external references.
2. A compatibility adapter has run successfully and its contract tests pass.
3. Approved/LOCKED assets and immutable audit/review evidence are preserved without rewrite.
4. A verified backup/export and a tested rollback/downgrade path exist.
5. V5 end-to-end tests prove the replacement owns the behavior and no active consumer remains.
6. Supervisor explicitly authorizes the deletion task.

Until then, no `git rm`, filesystem delete, move, rename, `git clean`, or broad cleanup is allowed. This T01-R pass executed none of those operations.

## Validation

Read-only checks performed for this audit included:

- `git rev-parse --show-toplevel`, `git branch --show-current`, `git rev-parse HEAD`, `git status`, `git status --short`, `git remote -v`, `git log -n 10`, and `git tag --list`.
- `Test-Path`, `Get-Item`, `Get-ChildItem` and reparse-point inspection for the project, Skill, history, and ComfyUI roots.
- Directory/file inventory for `web/`, `server.py`, `frameflow/`, `core/`, `tests/`, `docs/`, planned `workbench/` and planned `comfy/` paths.
- Read-only source inspection of `frameflow/runtime.py`, `frameflow/database.py`, `frameflow/providers.py`, `frameflow/provider_adapters.py`, `frameflow/jimeng_cli.py`, `frameflow/recovery.py`, V3 modules, CI, README, active Skills, and historical Skill folders.
- Read-only SQLite probe of `data/frameflow.db`: 41 tables, WAL mode, busy timeout, foreign-key behavior, and migration version; no `INSERT`, `UPDATE`, `ALTER`, `DROP`, `VACUUM`, or migration command was run against it.
- External automation audit recorded in `docs/GIT_SYNC_AUDIT.md`: no daily Git sync script was found; scheduled tasks cover service/OpenCode startup and shutdown only.

Document self-check requirements for T01-R are: all five classifications are present, `NOT_IMPLEMENTED` is used for absent planned surfaces, all required inventory/migration/collision/protected sections exist, the four physical roots are named, and `DELETE_LATER` remains zero. The only intended new file from this task is `docs/T01_REPOSITORY_AUDIT.md`.
