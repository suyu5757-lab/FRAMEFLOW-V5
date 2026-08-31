# FRAMEFLOW 项目稳定化与交付方案

> 编制日期：2026-08-17  
> 适用范围：当前 `main` 工作区中的脚本优化、资产审计、镜头资产、前端工作流和 CI 重构内容  
> 目标：在不破坏本地项目数据、不削弱付费调用与 QA 门禁的前提下，使当前代码达到“测试全绿、CI 完整、改动可审查、可安全提交”的状态。

## 1. 当前结论

项目主体已经可运行，前端纯函数测试和 JavaScript 语法检查通过；当前主要阻塞不是功能缺失，而是测试契约、CI 覆盖和改动组织尚未收口。

已确认的问题：

1. 后端测试共 30 项，29 项通过，1 项失败。
2. 失败测试把 `get_secret` 固定为 `test-key`，却没有 mock 脚本优化供应商调用，因而会向真实配置地址发送请求；本次运行得到的 `401` 是外部响应，不是稳定的本地契约。
3. CI 没有执行 `npm test`，因此新增的前端工作流和镜头资产测试不会在 GitHub Actions 中运行。
4. CI 只检查少量 JavaScript 文件，新拆出的模块可能带着语法错误进入主分支。
5. `server.py` 和 `app.js` 仍然偏大，继续叠加功能会提高回归和冲突风险。
6. 当前工作区同时包含大量已修改和未跟踪文件，尚未形成清晰、可回滚的提交边界。
7. Git 提示部分文本文件将发生 LF/CRLF 转换，需要统一仓库换行策略，避免后续出现整文件噪声 diff。

## 2. 本轮稳定化的完成标准

以下条件必须同时满足，才视为当前重构可交付：

- `python -m unittest discover -s tests -v` 全部通过。
- `npm test` 全部通过。
- 所有仓库内 JavaScript 源文件通过 `node --check`。
- CI 同时运行 Python 测试、Node 测试和 JavaScript 语法检查。
- 失败响应的 HTTP 状态码、错误类别、`retryable` 字段有明确且可测试的契约。
- 数据库迁移从空库升级到 v2 成功，已有 v1 数据升级后仍可读取。
- `data/`、生成媒体、凭据和本地附件不进入 Git。
- 本次改动按功能形成若干可独立审查、独立回滚的提交。
- README 中的启动、测试和数据说明与实际命令一致。

### 本次交给编码 Agent 的默认实施范围

首次实施只执行 P0 和 P1：

1. 隔离测试中的真实外部请求。
2. 统一脚本优化错误分类和重试语义。
3. 修复并补充相关后端测试。
4. 让后端与前端现有测试全部通过。
5. 补齐 CI 的 `npm test` 和全量顶层 JavaScript 语法检查。

P2 的大文件拆分、数据库结构调整和 P3 的提交整理不属于首次实施范围。Agent 完成 P0/P1 后应停止并汇报，等待用户确认，不得顺手展开大规模重构。

## 3. P0：先隔离外部请求，再修复错误契约

### 3.1 复审后的根因

`AssetIntakeTests.setUp` 把 `server.get_secret` mock 成 `test-key`。失败测试随后调用 `start_story_run`，但没有 mock `_run_storyboard_agent`，因此测试会使用假密钥访问真实供应商地址。返回 `401` 只说明本次外部服务拒绝了假密钥；在离线、DNS 异常、供应商限流等环境中还会得到其他结果。

因此不能简单地把测试改成固定接受 `401`。第一原则应是：单元/集成测试不得依赖真实网络、真实密钥或开发者机器上的环境变量。

推荐错误语义：

- 本地未配置能力绑定：`409 conflict`，不可重试。
- 本地未配置凭据：`409 configuration`，不可重试。
- 已携带凭据但被上游拒绝：`401/403 auth`，不可盲目重试。
- 上游超时、限流或临时故障：`429/502/503/504`，可按策略重试。

### 3.2 先把失败测试改为确定性测试

修改 `tests/test_asset_intake.py` 中的 `test_story_optimization_creates_candidate_not_overwrite`，显式 mock 脚本 Agent 失败。示意代码如下；实现时可根据最终错误映射调整字段，但不得恢复真实网络调用：

```python
with mock.patch.object(
    server,
    "_run_storyboard_agent",
    side_effect=server.ProviderError("测试上游暂时不可用", "retryable", 503),
) as run_agent:
    start = self.client.post(
        f"/api/story-optimization-runs/{create.json()['id']}/start"
    )

self.assertEqual(start.status_code, 502)
payload = start.json()
self.assertEqual(payload["code"], "storyboard_failed")
self.assertEqual(payload["category"], "retryable")
self.assertTrue(payload["retryable"])
run_agent.assert_awaited_once()

run = self.client.get(
    f"/api/story-optimization-runs/{create.json()['id']}"
).json()["run"]
self.assertEqual(run["status"], "failed")

doc = self.client.get("/api/projects/PRJ_ASSET").json()["document"]
self.assertEqual(doc["script"], "s")
```

注意：`structured_error` 的字段位于响应顶层，`error` 当前只是兼容用的错误消息字符串，不是嵌套对象。

测试不要只接受一组宽泛状态码。应同时验证：

- 响应状态符合被 mock 的失败类型；
- 返回结构化错误；
- 运行记录进入 `failed`；
- 原脚本未被候选结果覆盖；
- mock 确实被调用且测试期间没有真实外部请求。

### 3.3 再修正 `category` 与 `retryable` 语义

当前 `start_story_run` 把响应 `category` 固定为 `agent`，并对所有异常传入 `retryable=True`，会丢失 `auth`、`configuration`、`validation` 等分类。建议加入统一函数，避免每个路由自行判断：

```python
def provider_error_retryable(status: int, kind: str) -> bool:
    if kind in {"auth", "billing", "configuration", "conflict", "validation"}:
        return False
    return status in {408, 425, 429, 500, 502, 503, 504}
```

`start_story_run` 的异常处理应按以下顺序计算：

1. 读取原异常 `status_code`，没有则使用 `500`。
2. 4xx 保留原状态；上游 5xx 对客户端统一为 `502`。
3. 优先使用异常的 `kind` 作为 category；没有 kind 时使用 HTTP 状态映射。
4. 通过统一函数计算 `retryable`，禁止写死为 `True`。
5. 数据库中的 `error_json` 保存原始上游状态和 kind，便于诊断；响应不得包含密钥或敏感上游正文。

建议把 `get_profile_secret` 的“本地没有凭据”从当前 `503` 调整为明确的 `409 configuration`。它不是上游服务不可用，也不应该触发自动重试。修改后要检查图片、TTS、视频和编排入口是否共享该函数，并补齐回归测试。

推荐错误契约：

| 场景 | HTTP | kind/category | retryable | UI 行为 |
|---|---:|---|---|---|
| 本地未配置凭据 | 409 | `configuration` | false | 打开服务设置 |
| 上游拒绝凭据 | 401/403 | `auth` | false | 检查密钥和账号权限 |
| 未配置能力绑定或状态冲突 | 409 | `configuration` / `conflict` | false | 修正配置或刷新状态 |
| 请求或结构化输出不合法 | 422 | `validation` | false | 修改输入或模型设置 |
| 限流 | 429 | `rate_limit` | true | 延迟后重试 |
| 上游临时故障 | 502/503/504 | `retryable` | true | 保留上下文并重试 |

### 3.4 P0 验收命令

```powershell
python -m unittest tests.test_asset_intake.AssetIntakeTests.test_story_optimization_creates_candidate_not_overwrite -v
python -m unittest discover -s tests -v
```

验收标准：30/30 通过；测试期间没有真实网络请求；失败后没有覆盖项目原文档；配置、认证、验证和临时上游错误的分类与重试语义均有测试。

## 4. P1：补齐 CI，防止已通过的前端测试被遗漏

### 4.1 必须增加的 CI 步骤

将 `.github/workflows/ci.yml` 的验证部分调整为：

```yaml
      - name: Install Python dependencies
        run: python -m pip install -r requirements.txt

      - name: Run backend tests
        run: python -m unittest discover -s tests -v

      - name: Run frontend tests
        run: npm test

      - name: Check JavaScript syntax
        shell: pwsh
        run: |
          $files = Get-ChildItem -Path . -Filter *.js -File |
            Where-Object { $_.FullName -notmatch '[\\/]node_modules[\\/]' }
          foreach ($file in $files) {
            node --check $file.FullName
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          }
```

当前源文件都位于仓库顶层，上述检查可以覆盖 `app.js`、`audio.js`、`api.js`、`assistant.js`、`asset-intake-state.js`、`asset-workspace.js`、`project-manager.js`、`shot-assets.js`、`story-workflow.js`、`story-workspace.js`、`task-packages.js` 和 `workflow-state.js`。

如果以后把源码移动到子目录，应显式扩展搜索范围，但排除 `node_modules` 和生成目录。

### 4.2 建议增加的 CI 保护

- 设置 `timeout-minutes: 15`，避免异常网络或测试进程永久占用 runner。
- 为同一分支的新推送取消旧任务，减少重复运行。
- Python 测试必须使用临时数据库，不允许打开或修改仓库内 `data/frameflow.db`。
- 测试不得依赖真实 OpenAI、DeepSeek 或火山方舟凭据。
- 所有付费调用都必须 mock，并验证未确认时不会发出请求。

可选的并发配置：

```yaml
concurrency:
  group: frameflow-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

### 4.3 P1 验收

- 本地 `npm test` 和 Python 测试全绿。
- 推送分支后 GitHub Actions 全绿。
- 人为给任意新 JS 模块加入语法错误时，CI 必须失败；恢复后重新通过。

## 5. 延期专项：统一换行符并控制 Git 噪声

当前工作区已有大量未提交业务修改，不适合在首次稳定化实施中执行全仓库换行规范化。此项只保留为后续独立任务；P0/P1 Agent 不得运行 `git add --renormalize .`，也不得批量重写现有文件。

在仓库根目录新增 `.gitattributes`：

```gitattributes
* text=auto
*.py text eol=lf
*.js text eol=lf
*.json text eol=lf
*.md text eol=lf
*.yml text eol=lf
*.yaml text eol=lf
*.css text eol=lf
*.html text eol=lf
*.bat text eol=crlf
```

实施注意：

1. 先完成当前逻辑修改并提交，再单独做换行规范化。
2. 不要把换行规范化和业务改动放在同一个提交中。
3. 规范化前后分别运行测试，确认只有行尾发生变化。
4. 不要对 SQLite、图片、音频和视频等二进制文件做文本规范化。

## 6. P2：降低 `server.py` 和 `app.js` 的维护风险

此项不应阻塞 P0/P1 交付，应在测试与 CI 全绿后逐步进行。每次只迁移一个领域，并保持 API 路径和前端行为不变。

### 6.1 后端目标结构

```text
frameflow/
  api/
    projects.py
    providers.py
    story.py
    assets.py
    tasks.py
    media.py
  services/
    story_service.py
    asset_service.py
    provider_service.py
    render_service.py
  database.py
  schemas.py
  workflows.py
server.py
```

职责约束：

- `server.py`：创建 FastAPI 应用、注册异常处理器、挂载路由和静态文件。
- `api/*.py`：解析请求、权限/状态校验、调用 service、构造响应。
- `services/*.py`：业务事务、状态迁移、外部供应商调用编排。
- `database.py`：连接、迁移和通用持久化，不包含 HTTP 对象。
- `providers.py`：供应商协议、响应解析和错误归一化。

第一步建议迁移脚本优化路由，因为它已经形成完整边界且有端到端测试。迁移顺序：

1. 抽出错误映射和脚本优化 service。
2. 抽出 `/api/story-optimization-runs/*` 路由。
3. 保持原 URL、请求体和响应体不变。
4. 跑完整测试后再迁移资产审计路由。

### 6.2 前端目标结构

现有前端已经开始模块化，下一步应让 `app.js` 只承担应用启动和共享上下文装配：

```text
js/
  core/
    api.js
    store.js
    events.js
  views/
    project-manager.js
    story-workspace.js
    asset-workspace.js
    audio-workspace.js
  domain/
    workflow-state.js
    story-workflow.js
    shot-assets.js
    asset-intake-state.js
  app.js
```

迁移原则：

- 纯状态推导函数不得直接访问 DOM、`localStorage` 或网络。
- API 调用集中在 `api.js`。
- 视图模块只通过明确的 context/store 接口读写状态。
- 每迁移一个模块，先补纯函数测试，再移动代码。
- 不在同一次提交中同时改 DOM 结构、业务规则和 CSS。

### 6.3 P2 验收

- `server.py` 主要只剩应用装配和静态入口。
- `app.js` 主要只剩初始化、路由和模块连接。
- API 契约无变化，现有测试和本次新增回归测试持续通过。
- 关键业务规则可以脱离浏览器和外部 API 单独测试。

## 7. P2：数据库与本地数据保护

当前 `data/` 已被忽略，应继续保持。任何迁移、回滚或删除项目前，先执行数据保护检查。

### 7.1 迁移验证矩阵

至少覆盖：

1. 空数据库直接初始化到 schema v2。
2. v1 数据库升级到 v2，原项目和 Seedance 2.0/2.5 配置仍可读取。
3. 重复启动不会重复执行迁移。
4. 升级失败时事务回滚，不留下半迁移状态。
5. `rollback_to(1)` 仅用于测试或明确维护操作，不应出现在普通启动路径。

### 7.2 删除语义

- 删除项目记录前继续阻止存在活动任务的项目被删除。
- 保留“删除数据库记录但不自动递归删除媒体目录”的安全策略。
- 如果未来提供媒体清理功能，必须先列出明确文件清单并逐个删除；禁止递归批量删除项目目录。

### 7.3 凭据保护验证

自动化测试应断言：

- API 响应不包含明文密钥。
- SQLite 中只保存 `credential_ref`。
- 导出的 `.frameflow.json` 不包含凭据。
- 日志、异常详情和供应商探测响应经过脱敏。
- 关闭或删除 provider profile 时，不误删其他 profile 共用的系统凭据。

## 8. P3：整理当前工作区并形成可审查提交

不要将当前所有改动一次性提交。推荐顺序如下：

1. `test: align story optimization auth error contract`
   - 错误重试语义
   - 对应后端测试

2. `ci: run backend and frontend verification`
   - GitHub Actions
   - `package.json`
   - 必要的测试入口

3. `feat: add story optimization workflow`
   - `story-workflow.js`
   - `story-workspace.js`
   - 相关后端路由、schema、数据库迁移和测试

4. `feat: add asset intake audit and quarantine flow`
   - `asset-intake-state.js`
   - `asset-workspace.js`
   - `frameflow/asset_audit.py`
   - 对应接口和测试

5. `feat: add shot asset readiness workflow`
   - `shot-assets.js`
   - `workflow-state.js`
   - 对应前端测试

6. `refactor: integrate workbench modules`
   - `app.js`
   - `index.html`
   - `styles.css`
   - `project-manager.js`
   - `api.js`
   - `assistant.js`

7. `docs: update Frameflow setup and architecture`
   - README
   - 设计与审计文档

8. `chore: normalize repository line endings`
   - `.gitattributes`
   - 仅包含换行规范化

每个提交前运行与其相关的测试；第 2 个提交之后，每个提交都应运行完整验证。不要提交：

- `data/`
- `generated/`
- `.env*`
- `.codex-remote-attachments/`
- `__pycache__/`
- API Key、访问令牌、含敏感信息的日志

## 9. 建议补充的自动化测试

按优先级补充：

### 高优先级

- 缺少凭据返回 401 且 `retryable=false`。
- 供应商返回 429/502 时 `retryable=true`。
- 脚本优化失败后项目原脚本和镜头不变。
- 重复启动或重复接受候选不会创建重复版本。
- 未显式确认时，图片、TTS、视频等付费调用不会发出网络请求。
- 资产技术校验通过不等于 QA 通过，也不等于生产就绪。

### 中优先级

- v1 到 v2 的真实 fixture 迁移测试。
- 项目 revision 冲突后的前端恢复路径。
- provider profile 删除、能力解绑和凭据引用生命周期。
- Seedance 后台任务在应用重启后的恢复或明确失败策略。
- 静态文件与项目媒体路径的编码、目录穿越和 MIME 校验。

### 后续

- Playwright 浏览器冒烟测试：启动、打开项目、切换工作区、保存、刷新后恢复。
- 使用小型本地 mock server 验证 OpenAI-compatible 和 Ark 响应适配。
- FFmpeg 不存在、输入损坏和中途失败时的清理与错误提示。

## 10. 最终执行顺序

```text
确认工作区与本地数据
  → 修复 401/retryable 契约与测试
  → 后端测试全绿
  → CI 加入 npm test 和全量 JS 语法检查
  → 本地完整验证
  → 按领域拆分提交
  → 推送分支并确认 CI 全绿
  → 再开始 server.py / app.js 渐进拆分
```

## 11. 完整验收清单

```powershell
python -m unittest discover -s tests -v
npm test

$files = Get-ChildItem -Path . -Filter *.js -File
foreach ($file in $files) {
    node --check $file.FullName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

git status --short
git diff --check
```

交付前人工确认：

- [ ] 后端 30/30 测试通过。
- [ ] 前端 26/26 测试通过。
- [ ] JavaScript 全量语法检查通过。
- [ ] CI 与本地执行相同的关键验证。
- [ ] 无真实外部付费调用发生在测试中。
- [ ] 无密钥、本地数据库或生成媒体进入 Git。
- [ ] 数据库迁移和旧数据读取已验证。
- [ ] 提交按功能拆分，换行调整与业务改动分离。
- [ ] README 与真实启动、测试命令一致。

## 12. 建议的优先级结论

立即处理 P0 和 P1：修复错误契约、让测试全绿、补齐 CI。这三项改动小、收益高，可以直接消除当前交付阻塞。

代码拆分属于 P2，不建议在测试仍失败时大范围展开。先建立可靠的自动化保护，再逐个领域迁移，能够显著降低 `server.py` 和 `app.js` 拆分过程中的回归风险。

## 13. 编码 Agent 执行协议

接手本方案的 Agent 必须遵循以下协议：

### 开始前

1. 完整阅读本文件和仓库中的 `AGENTS.md`。
2. 运行 `git status --short --branch`，把现有修改视为用户资产，不覆盖、不回退、不清理。
3. 阅读相关实现和测试后再修改，不得只根据本方案中的示意代码盲贴。
4. 先运行一次完整基线测试并记录准确结果。

### 实施中

1. 只修改 P0/P1 必需文件，优先范围为：
   - `server.py`
   - `tests/test_asset_intake.py`
   - 必要时 `tests/test_server.py`
   - `.github/workflows/ci.yml`
   - 必要时 `README.md`
2. 不调用真实 OpenAI、DeepSeek、火山方舟或其他付费/外部生成服务。
3. 测试必须 mock 外部边界，并断言 mock 被调用或未被调用。
4. 保持现有 API 路径、成功响应和数据库 schema 不变。
5. 不删除文件或目录，不修改 `data/`、`generated/` 和本地数据库。
6. 不做 `server.py`/`app.js` 大规模拆分，不做全仓库格式化或换行规范化。
7. 不提交、不推送，除非用户另行明确授权。
8. 如果发现方案与代码事实冲突，以实际代码和测试证据为准，先做最小安全调整，并在结果中说明差异。

### 修改后

按顺序运行：

```powershell
python -m unittest tests.test_asset_intake.AssetIntakeTests.test_story_optimization_creates_candidate_not_overwrite -v
python -m unittest discover -s tests -v
npm test

$files = Get-ChildItem -Path . -Filter *.js -File
foreach ($file in $files) {
    node --check $file.FullName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

git diff --check
git status --short
```

最终汇报必须包括：

- 根因结论；
- 修改文件列表；
- 错误契约最终定义；
- 每条验证命令及结果；
- 是否发生任何真实网络调用；
- 未完成事项或残余风险；
- 明确声明没有修改本地数据库、没有提交、没有推送。

## 14. 可直接复制给编码 Agent 的任务指令

```text
请依据仓库根目录的 FRAMEFLOW_PROJECT_STABILIZATION_PLAN.md，对当前 FRAMEFLOW 工作台执行首次稳定化实施。

工作范围严格限定为文档中的 P0 和 P1：隔离测试中的真实供应商请求；修复脚本优化错误的 category/retryable 契约；让后端测试稳定全绿；补齐 CI 的 npm test 和顶层 JavaScript 语法检查。完成后停止，不要开始 P2/P3。

开始前请完整阅读 FRAMEFLOW_PROJECT_STABILIZATION_PLAN.md 和 AGENTS.md，检查 git status，并保护工作区里所有现有修改。不要删除、回退或覆盖用户已有内容；不要修改 data/、generated/ 或任何本地数据库；不要运行真实 OpenAI、DeepSeek、火山方舟或其他外部付费调用。测试中的外部边界必须 mock，并验证没有真实网络依赖。

请先复现基线测试，再按最小改动原则实施。注意：此前出现的 401 很可能来自测试使用 test-key 访问了真实供应商，并不能直接定义为稳定契约。应先让 test_story_optimization_creates_candidate_not_overwrite 确定性 mock _run_storyboard_agent，再分别处理本地未配置凭据、上游拒绝凭据、验证失败和临时上游故障的状态码、category 与 retryable 语义。结构化错误字段位于响应 JSON 顶层，error 当前是兼容消息字符串。

不要进行 server.py/app.js 大规模拆分，不要全仓库格式化或规范化换行，不要提交或推送。实现后运行文档第 13 节的全部验证命令，并报告根因、修改文件、最终错误契约、测试结果、是否有真实网络调用、残余风险，以及确认未修改数据库、未提交、未推送。如果实现事实与文档示意冲突，请以代码和测试证据为准做最小安全调整，并清楚说明。
```
