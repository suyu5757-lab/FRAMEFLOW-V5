# FrameFlow 第一轮监管审计后的纠偏执行指令

> 执行对象：本地 DeepSeek 开发 Agent  
> 项目目录：`D:\11067\Codex\2026-08-13\video-2`  
> 验证地址：`http://127.0.0.1:8787/`  
> 任务性质：直接修改、测试和验收，不是再次编写抽象方案。

## 1. 开始前必须读取

完整读取：

1. `DEEPSEEK_STORY_OPTIMIZATION_SHOT_ASSET_PLAN.md`
2. `DEEPSEEK_ASSET_UPLOAD_AUDIT_QUARANTINE_PLAN.md`
3. `D:\11067\CodexHome\skills\video-script-storyboard\SKILL.md`
4. `D:\11067\CodexHome\skills\video-asset-regulator\SKILL.md`
5. 与角色、场景、道具、融合资产对应的领域 Skill。

先运行现有测试，不要在未经验证的情况下覆盖当前实现。

## 2. 当前监管结论

当前实现已经具备以下基础：

- 脚本优化按钮和候选差异窗口；
- 脚本/分镜候选版本接口；
- 资产导入、QA Run、未合格资产和版本接口；
- 资产详情及分镜资产目录组件；
- 前端纯状态测试 26 项；
- 后端 unittest 30 项，其中 29 项通过、1 项失败；
- 服务可以在 `127.0.0.1:8787` 启动，健康接口返回 200。

但是当前实现不能验收，以下问题必须修复。

## 3. P0：统一生产就绪门禁

### 3.1 已确认的问题

`workflow-state.js` 的 `assetProductionReady()` 对 A/A+ 资产没有检查：

- `sha256`；
- `promptQaDecision === 'Approved'`；
- 授权状态；
- 是否已被新版本替代。

`server.py` 的 `/api/assets/artifacts/{artifact_id}/register` 也没有检查 Prompt QA，只检查了领域图片 QA、文件和哈希。

当前真实项目“解毒者 · 第一季”中：

- 8 个资产标记为 `ready`；
- 这 8 个资产的 `promptQaDecision` 全部仍是 `Pending`；
- 因此 8/8 都是与严格门禁冲突的 Ready 状态。

### 3.2 必须修改

建立唯一的生产就绪判定契约，前端、后端、总览、分镜和镜头导演共用同一语义：

1. 本地文件存在；
2. 文件 SHA-256 存在；
3. Prompt 版本存在；
4. Prompt QA 已通过；
5. 对应领域 Generated Image QA 已通过；
6. 资产总控已登记；
7. A/A+ 敏感素材的授权已满足；
8. 当前版本为 active，且没有 superseded；
9. 状态属于允许进入生产的状态。

服务器注册接口必须重新查询并验证真实 Prompt Version/Prompt QA 记录，不能只相信项目 JSON 中的布尔字段。

拒绝注册时返回结构化错误，例如：

- `prompt_missing`
- `prompt_version_missing`
- `prompt_qa_pending`
- `domain_qa_pending`
- `authorization_missing`
- `artifact_superseded`
- `file_missing`
- `hash_missing`

前端只能展示服务器给出的门禁结果，不能自己将资产改为 Ready。

### 3.3 旧数据处理

禁止为了让现有 8 个资产继续显示为 Ready 而把 Prompt QA 自动写成 Approved。

应当：

1. 保留原始文件、artifact、版本和历史状态；
2. 将不一致状态标记为 `legacy_review_required` 或等价状态；
3. 提供迁移预览或修复报告；
4. 引导用户补建 Prompt 版本并完成 Prompt QA；
5. 未通过前，不计入严格生产就绪率；
6. 不静默修改用户已经存在的审批历史。

## 4. P0：补齐逐镜头资产依赖

### 4.1 已确认的问题

当前项目共有 20 个镜头，20 个镜头的 `assetRequirements` 都是空字符串。

`shot-assets.js` 的 `normalizeRequirements()` 只接受数组，因此当前所有分镜都会得到空目录，显示“等待资产总控”，无法实现用户要求的逐镜头资产进度与跳转。

### 4.2 必须修改

1. 建立版本化 `assetRequirements` 数组结构。
2. 每条记录至少包含：
   - `shotId`
   - `assetId`
   - `assetClass`
   - `role`
   - `priority`
   - `required`
   - `requiredReadiness`
   - `source`
3. 接受资产总控候选结果时，把依赖写入对应镜头。
4. 对旧项目增加非破坏性迁移/重建工具：
   - 优先读取已有 regulator 交接包；
   - 其次根据资产的 `relevantShots`、融合依赖和场景 ID 构建候选映射；
   - 无法确定时进入待人工确认，不允许猜测并直接批准。
5. 当前“解毒者”项目至少要形成可审阅的逐镜头依赖候选，不得继续保留 20/20 空目录。
6. 依赖候选必须先预览再应用，保留旧版本。

### 4.3 修复跳转参数

检查 `story-workspace.js` 中分镜资产行。当前生成的 `data-shot-id` 实际始终为空，必须修复。

每次从分镜跳转到资产制作页必须携带：

- `project_id`
- `shot_id`
- `asset_id`
- `asset_class`
- `intended_action`
- `return_to`
- 原页面滚动位置或锚点

资产处理结束后能返回原镜头和原滚动位置。

## 5. P0：上传后真正创建审计流程

### 5.1 已确认的问题

`/api/assets/intake` 虽然接收 `run_audit=true`，但当前只是：

- 技术校验；
- 保存文件；
- 创建 artifact；
- 返回 `generated_pending_qa`。

它没有真正创建 QA Run，也没有执行或阻塞领域审计。页面“上传并进入审计”的文案与实际行为不完全一致。

### 5.2 必须修改

当 `run_audit=true` 且映射完整时：

1. 完成技术校验；
2. 保存安全文件；
3. 创建 artifact；
4. 创建领域 QA Run；
5. 根据 Agent 视觉能力决定：
   - 有视觉能力：进入 `qa_in_progress` 或明确的待执行状态；
   - 无视觉能力：创建 blocked QA Run，原因 `no_vision_capability`；
   - 敏感素材未授权：创建 blocked QA Run，原因 `sensitive_material_unauthorized`；
6. 返回 artifact、QA Run、下一步动作和明确原因；
7. 页面在当前上传窗口显示审计状态、能力、延迟/耗时和错误详情。

不得自动产生图片、视频或其他付费媒体调用。

### 5.3 技术校验失败

对 MIME/签名伪造、损坏或无法解码的文件：

- 不保存危险或损坏字节；
- 记录失败的 intake event 或安全的失败元数据；
- 页面归入“上传失败/未合格记录”；
- 只允许重新上传；
- 不建议重建 Prompt；
- 不得把无效文件写成 artifact Ready。

## 6. P0：Prompt QA 与注册必须形成真实关系

目前 artifact 只保存 `prompt_version` 字符串，但注册时没有验证对应 `prompt_versions` 表记录及其状态。

必须：

1. artifact 的 Prompt 版本必须引用真实 Prompt Version；
2. Prompt Version 必须属于同一项目和同一逻辑资产；
3. Prompt Version 状态必须为 `prompt_qa_approved`；
4. 修订/重建 Prompt 后，旧 artifact 不得借用新 Prompt QA 结果；
5. 新媒体结果必须绑定产生它的准确 Prompt 版本；
6. 外部手工上传也要记录来源和 Prompt/无 Prompt 的明确处理政策；
7. 不能用 `v01` 这种自由文本冒充已验证的数据库引用。

## 7. P1：脚本优化错误契约和撤销

### 7.1 当前失败测试

运行：

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

当前失败：

`test_story_optimization_creates_candidate_not_overwrite`

未配置真实编排 Agent 时，接口返回 401，而测试只接受 409/502。

统一错误契约：

- 缺少凭据：401，`category=auth`；
- Provider 未配置或能力未绑定：409，`category=dependency`；
- 上游调用失败：502，`category=provider`；
- 所有情况都必须保证原脚本不变。

测试必须根据正式契约断言具体状态码和结构化字段，不能仅扩大允许范围来掩盖错误。

### 7.2 撤销能力

当前页面有历史版本展示，但没有确认可用的“恢复此版本”动作。

增加受控恢复接口和 UI：

1. 选择历史脚本/分镜版本；
2. 显示恢复差异；
3. 用户确认；
4. 恢复操作创建新版本，不删除旧版本；
5. 恢复后重新推导资产依赖和阶段，不伪造下游完成状态。

## 8. P1：数据兼容与显示

检查现有导入数据：`audio.voices`、`dialogues`、`musicCues`、`ambience` 中存在 PowerShell 风格对象字符串，而不是 JSON Object。

不得直接删除这些记录。增加导入诊断：

- 能安全解析的转换为对象；
- 无法安全解析的标记 `migration_review_required`；
- 在系统医生/项目迁移报告中显示；
- 不让错误类型导致音频页面崩溃。

此项不应阻塞 P0，但必须记录和测试。

## 9. 必须新增或修改的测试

至少增加以下回归测试：

1. A 级资产 Prompt QA Pending 时，`assetProductionReady()` 必须为 false。
2. A 级资产缺少 SHA-256 时必须为 false。
3. 被 superseded 的资产必须为 false。
4. 服务端 register 在 Prompt Version 缺失时返回 `prompt_version_missing`。
5. 服务端 register 在 Prompt QA Pending 时返回 `prompt_qa_pending`。
6. 不能引用另一个资产的 Prompt Version。
7. 旧项目的错误 Ready 状态不会被静默改成 Prompt QA Approved。
8. 20 个旧镜头空依赖可以生成候选，但应用前不会改项目。
9. 接受依赖候选后，每个已映射镜头得到数组结构。
10. 空字符串 `assetRequirements` 不导致 JS 崩溃。
11. 分镜资产跳转带有正确 `shot_id` 与 `return_to`。
12. `run_audit=true` 会创建 QA Run。
13. 无视觉能力会创建 blocked QA Run，而不是伪造通过。
14. 敏感素材未授权会创建 blocked QA Run。
15. 技术校验失败不会保存危险文件。
16. 脚本优化缺少凭据返回正式定义的结构化错误。
17. 脚本优化失败后原脚本、镜头和版本均不变。
18. 恢复历史版本会创建新版本，不删除历史。

不得删除现有测试，不得降低已有断言强度。

## 10. 验证命令

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
npm test
python -m py_compile server.py
node --check app.js
node --check story-workspace.js
node --check asset-workspace.js
node --check shot-assets.js
node --check workflow-state.js
```

如果使用 pytest，先说明环境是否已经安装；不能因为 pytest 不存在而声称后端测试通过。

## 11. 浏览器验收

启动 `http://127.0.0.1:8787/` 后完成：

1. 打开“解毒者 · 第一季”。
2. 确认不一致的旧 Ready 资产不再错误计入严格就绪率。
3. 页面明确显示缺少 Prompt/Prompt QA 的原因。
4. 打开故事与分镜，确认 20 个镜头不再全部显示空资产目录。
5. 点击一个镜头资产，确认进入正确资产及动作。
6. 返回时回到原镜头和滚动位置。
7. 上传一个映射完整的安全图片，确认自动创建 QA Run。
8. 在无视觉能力情况下确认显示 blocked 原因。
9. 上传敏感素材但不提供授权，确认审计被阻塞。
10. 为资产创建 Prompt Version，并保持 Prompt QA Pending，确认不能注册。
11. Prompt QA 通过、领域 QA 通过后再注册，确认才进入 Ready。
12. 脚本优化未配置 Agent 时，在当前页面显示结构化错误，原脚本不变。
13. 通过历史版本执行恢复，确认形成新版本。
14. 刷新浏览器并重启服务，确认状态仍存在。
15. 控制台没有未处理异常。

## 12. 禁止事项

- 禁止批量删除文件或目录。
- 禁止删除用户项目、资产和历史版本。
- 禁止自动把 Pending 改为 Approved。
- 禁止前端绕过服务器状态机。
- 禁止为了通过测试修改测试，使其不再验证真实门禁。
- 禁止静默切换 Agent、模型或供应商。
- 禁止自动发起付费媒体调用。
- 禁止覆盖原始媒体文件。

## 13. 完成报告格式

完成后报告：

1. 每个 P0/P1 问题的修复结果；
2. 修改文件完整路径；
3. 数据库迁移版本及回滚方式；
4. 旧数据修复策略；
5. 新增接口和状态；
6. 全部测试命令与逐项结果；
7. 浏览器验收结果；
8. 当前仍未解决的问题；
9. 不一致数据是否经过用户确认；
10. 可以由监管者立即复查的操作路径。

现在直接开始修复。不要再次输出抽象计划，也不要在 P0 未通过时宣布完成。
