# FrameFlow V3 工作台审查与修复报告

审查日期：2026-08-22  
正式项目：`e8f59c50-5db2-44e9-a4f7-fc3c41f0cc84`（《解毒者》）  
当前数据库 schema：`8`

## 结论

V3 已作为唯一运行时工作台。正式项目媒体与资产版本保持不变，数据审计通过，主服务 8787 已加载修复后的前端和后端。当前健康状态为 `degraded`，原因是本机 OpenCode、OpenAI 图片和音频 Provider 未达到可用条件；这是真实能力状态，不再伪报可用。即梦本地视频能力探测为 `ready`，本轮未执行任何付费生成。

## 基线与数据修复

- 一致性 SQLite 备份：`backups/pre-v3-repair-20260822-162301/frameflow-consistent.db`
- 基线清单：`backups/pre-v3-repair-20260822-162301/baseline-manifest.json`
- 正式项目修复前后均为 20 个镜头、31 个 artifact、29 个资产版本、31 个媒体文件、76,893,274 bytes。
- 正式项目资产 JSON 未改变；31 个 artifact 的 `sha256`、路径、版本和状态均与基线一致。
- 实际媒体校验：缺失文件 `0`，hash 不匹配 `0`。
- 从已验证 artifact metadata 推导并同步 38 条资产—镜头关系，故事资产需求、资产依赖和看板 `shot_dependency` 边保持一致；未确定关系不自动标记 ready。
- 审计接口：`GET /api/v2/system/data-audit`，清理后结果：孤立记录 `0`、无效 artifact 引用 `0`、无效故事资产引用 `0`、看板重复 ID `0`、孤立项目目录 `0`、缺失正式项目目录 `0`。

## 主要修复

### 后端与数据层

- 增加 schema 8 的项目生命周期 `active|archived`，默认隐藏 archived 项目。
- 项目删除现在阻止 `queued/running/awaiting_confirmation/paused` 运行，并返回逐表清理统计；数据库项目记录会完整清理，正式媒体文件保留。
- Provider 健康从真实 binding、model、probe 和数据库状态计算，返回 `ready/degraded/not_ready` 与 capability 原因。
- 旧 `/api/*` 返回结构化 410 迁移提示；旧路由已从运行时路由表移除，OpenAPI 仅暴露 V3、健康、诊断和项目媒体文件边界。
- 新增可重复的数据审计和资产关系修复能力，关系修复记录资产事件并不改变 readiness。
- API 客户端统一结构化错误，项目切换使用 AbortController、请求序列号和项目作用域保护，避免旧项目响应覆盖当前项目。

### Web 工作台

- 项目切换先清空旧快照，再以取消信号加载新项目的 dashboard、graph、story、assets、board、timeline 和 audit。
- 归档、恢复、删除、创建、切换均有明确状态和活动运行保护。
- 资产候选按 logical asset 分组；画布区分 candidate、shot dependency、handoff 和 blocked 语义。
- 付费 workflow、图片生成、渲染和最终导出均经过可访问 Dialog 确认；取消付费流程不会创建 run 或调用 Provider。
- 移除 `window.alert/confirm`，加入 Esc 关闭、焦点可见、ARIA role/label、键盘操作和响应式布局。
- 启动脚本增加 dist、数据库、FFmpeg/FFprobe 检查，禁止静默运行过期或缺失前端构建。

### 旧版本隔离

备份后，以下内容逐项移动到 `backups/pre-v3-repair-20260822-162301/quarantine/`，未删除正式媒体：

- 9 个已确认非正式项目目录：`PRJ_ASSET`、`PRJ_ASSET_V3`、`PRJ_BOARD`、`PRJ_DELIVERY`、`PRJ_LIVE_7e912908`、`PRJ_LIVE_ac9fb13c`、`PRJ_LIVE_HTTP`、`PRJ_MATRIX`、`PRJ_SMOKE`。
- 48 个 `tests/test-*.db*` 临时数据库文件。
- 3 个旧 UI 审计浏览器 profile。
- 14 个旧根目录页面/状态模块、7 个旧 2.5 测试/HTTP smoke 文件，以及 6 个调试/重启临时文件。
- 旧项目 `PRJ_18660F2C3512` 通过 V3 删除 API 清理数据库记录；其项目文件策略为保留而不自动删除。
- 测试和 Playwright 的临时数据库、项目媒体、生成目录和 CLI home 均进入系统临时目录，不再污染 `data/projects`。

根目录 `npm test` 已迁移为当前 Web Vitest 入口；旧模块和测试均保留在隔离备份中，可恢复审阅。

## 验收证据

| 检查项 | 结果 |
| --- | --- |
| 当前 V3 Python 回归 | 71/71 通过（含维护/归档/删除/资产关系契约） |
| 根目录 `npm test` / Web Vitest | 3 files / 12 tests 通过 |
| Web TypeScript | 通过 |
| Web production build | 通过；仅有 bundle >500KB 提示 |
| Playwright Chromium | 3/3 通过；项目管理/工作区导航/404/422/410/敏感信息/归档恢复删除/付费取消均覆盖 |
| 主端口 `8787` | schema 8，`degraded`，健康能力真实 |
| `/api/projects` | 410，迁移提示 |
| `/openapi.json` | 不含旧 `/api/projects` 路径 |
| `/api/v2/system/data-audit` | `ok=true`，仅保留正式项目 |
| `system/doctor` | 前端 dist、数据库、FFmpeg、FFprobe 均可识别 |

## 剩余风险与后续建议

1. OpenCode、OpenAI 图片和音频 Provider 仍需用户配置/恢复健康后才能变为 `ready`；本报告没有替用户写入密钥，也没有触发付费调用。
2. 前端产物 JS gzip 前约 588KB，建议下一轮按页面做动态 import / manual chunks。
3. 当前 CI 已覆盖 V3 Python、根目录 JS 入口、Web Vitest、TypeScript、build 和 Playwright；后续可在 CI 中增加真正的 Windows FFmpeg fixture 与失败日志 artifact 保留策略。
4. 隔离区是可恢复备份，不是不可逆物理销毁；如需永久删除备份，应在人工确认后逐个明确路径处理。
