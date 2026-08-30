# FRAMEFLOW 个人 AI 视频工作台

这是一个围绕个人 Video Skills 制作链设计的本地优先 AI 视频工作台。它把脚本分镜、资产监管、角色/场景/道具设计、融合、镜头导演、配音配乐、即梦 CLI 视频生成、视频 QA 与最终合成组织为一条带门控的生产流水线。

## 启动

双击 `启动工作台.bat`，首次运行会安装 `requirements.txt` 中的 FastAPI、Uvicorn、Keyring 等依赖，然后访问 `http://127.0.0.1:8787`。如已安装 OpenCode CLI，启动器还会检测并按需在后台启动 `127.0.0.1:4096`，不会重复启动已有服务。ES Modules、系统凭据和 SQLite 功能不支持直接双击 `index.html` 使用。

推荐在“工作台设置 → 设置与 Provider 控制面”中配置 OpenAI 等文本服务；密钥写入 Windows Credential Manager，数据库和浏览器只保存凭据引用。视频生成使用官方即梦 CLI 的本机登录态，不录入 API Key：

```powershell
$env:OPENAI_API_KEY="你的 OpenAI API 密钥"
```

### 即梦 CLI 视频接入

按即梦官方安装页执行安装：

```powershell
curl -fsSL https://jimeng.jianying.com/cli | bash
$env:USERPROFILE="$PWD/data/dreamina-home"
$env:HOME="$env:USERPROFILE"
dreamina login --headless
dreamina user_credit
```

然后在工作台设置中选择“即梦官方 CLI”，填写 `dreamina`（或 `dreamina.exe` 的完整路径），选择当前 CLI 支持的模型，点击连接探测。工作台只调用本地 CLI：生成命令使用 `text2video`、`image2video` 或 `frames2video`，提交后通过 `query_result --submit_id=... --download_dir=...` 轮询并接收本地视频文件。工作台会把 CLI 登录态放在项目的 `data/dreamina-home/.dreamina_cli`，因此登录前请先设置上面的 `USERPROFILE`；不要把安装命令填写到 CLI 可执行文件字段。

即梦 CLI 的当前模型清单以本机 `dreamina text2video -h`、`image2video -h`、`frames2video -h` 为准：`seedance2.0`、`seedance2.0fast`、`seedance2.0mini` 为 4–15 秒、720p；`seedance2.0_vip`、`seedance2.0fast_vip` 为 4–15 秒、720p/1080p/4K；`seedance2.5` 为 4–30 秒、480p/720p/1080p；`seedance1.5pro` 为 5–12 秒、720p，仅支持图生和首尾帧；`seedance1.0fast` 为 5–10 秒、720p，仅支持图生。图片引用必须是本地文件路径，不能传 URL 或 `asset://`。所有生成仍需经过工作台的付费确认门。

### FrameFlow V3（唯一运行时入口）

FrameFlow V3 使用 React/Vite 工作台作为唯一运行时入口。首次使用先构建前端：

```powershell
Push-Location web
npm install
npm run build
Pop-Location
```

服务启动后访问 `http://127.0.0.1:8787/`。V3 图、模板、监督式运行、Provider 路由预览、Agent 计划/补丁预览、故事、资产库和可交付时间线统一使用 `/api/v2`，保存仍要求 revision 匹配。旧工作台入口和旧 `/api` 接口已退役，不再作为运行时能力。

V3 运行时已支持执行边上游依赖补全、并发批次、节点输入指纹缓存、失败分类/重试、暂停/恢复/取消和服务重启后的 queued/running 任务恢复。普通节点当前执行为可追溯的编排检查点；付费节点必须先确认，且在没有明确 Provider 调度器配置时会安全失败，不会伪造媒体结果或绕过付费确认。

V3 画布支持节点拖拽、缩放、多选、复制、删除、分组/解散、分组折叠、自动布局、关系类型切换、撤销/重做和缩略图；分组关系、折叠状态与节点配置一起受图 revision 保护。付费运行确认前会显示模型、数量、分辨率、时长、费用和受影响节点，运行快照会保留所选节点与完整图配置。

### OpenCode Agent 接入

工作台把 OpenCode 作为独立的 Agent 执行接入点，而不是 OpenAI-compatible API。先安装并在本机启动 OpenCode Server：

```powershell
npm install -g opencode-ai
opencode serve --hostname 127.0.0.1 --port 4096
```

如需为 Server 启用 Basic Auth，可在启动前设置 `OPENCODE_SERVER_PASSWORD`；设置页中的默认用户名为 `opencode`。随后打开“工作台设置 → Agent 接入点、API 与模型路由”，选择 `OpenCode Agent`，依次执行：

1. 填写 Server URL，并按需保存 Server 密码。
2. 点击“检测连接与模型”，从 OpenCode `/provider` 读取已连接的提供商与模型。
3. 先选内部提供商，再选模型；工作台会把两者作为一个完整的 `provider_id/model_id` 绑定保存。
4. 选择 `build` 或 `plan` Agent，最后点击“应用此接入点与模型”。

OpenCode 内部模型凭据仍由 OpenCode 自己管理；工作台只保存 OpenCode Server 的可选 Basic Auth 密码。切换模型时会同时提交 `providerID` 与 `modelID`，避免只切模型名却沿用旧提供商。

## 当前能力

- FastAPI + SQLite WAL 项目持久化、浏览器备份与版本冲突检测
- OpenAI、DeepSeek/OpenAI-compatible、OpenCode Agent、即梦官方 CLI 与 ComfyUI 配置及能力检测
- API 密钥写入系统凭据库；即梦 CLI 的 Cookie/token 由 CLI 自己管理，FrameFlow 不读取、不回传
- 全局 ChatGPT 式助手侧栏，Responses API 严格结构化补丁与人工应用
- 监督式 Agent 计划：完整输入快照、结构化图补丁、费用/审批预览、revision 门和候选版本
- 可视化八阶段生产流水线
- 角色、场景、道具、融合、音频资产分级与状态管理
- 人物资产采用轻量默认：A 级人物先建立主设计图与面部近照，其余视镜头需要追加
- 可编辑脚本、横向分镜板、镜头检查器
- 即梦 CLI 视频模型的独立执行包与后台任务
- 引用角色映射、中文 Prompt、付费确认、轮询、取消和两次重试门禁
- 多轨可编辑时间线：视频、叠加、对白、配乐、环境声、音效和字幕
- 代理预览、批准镜头自动装配、FFmpeg 确定性导出与不可变 manifest
- 一键复制对应 Codex Skill 任务包
- 导出项目 JSON 和 Markdown 交付报告
- 使用 `gpt-image-2` 生成镜头关键帧，并自动登记生成记录
- Voice Controller 声音资产库、参考声音本地导入和授权状态
- 逐句对白、OpenAI TTS 试听、Take 版本及音频 QA
- 配乐 Cue、版权门禁和 Seedance `@Audio` 交接映射
- 导出独立音频生产包 JSON
- FFmpeg 环境检测、视频标准化拼接、最终 MP4 与 manifest
- 脚本优化：候选版本 + 前后差异审阅 + 版本化（不覆盖原脚本）
- 分镜资产目录：逐镜头角色/场景/道具/融合/声音依赖与真实准备状态
- 资产导入与审计中心：技术校验、领域 QA 路由、监管登记、未合格资产库
- 失败整改闭环：决策弹窗、提示词修订/重建、新 Prompt 版本与重新 Prompt QA

## 技能链

`video-script-storyboard → video-asset-regulator → character / scene / prop → video-fusion-production-director → video-shot-director → voice-controller → seedance-shot-packager → QA`

重要规则已经体现在界面中：稳定 ID、A/B/C 资产分级、Prompt QA 后才生成、A 级资产缺失时阻塞、两次失败后重建 Prompt、Seedance 前必须经过镜头导演、声音克隆前必须验证授权、批准 Take 不被覆盖。

## 数据

项目主数据保存在 `data/frameflow.db`，媒体位于 `data/projects/{project_id}/`；两者均已加入 `.gitignore`。浏览器 `localStorage` 作为离线备份，设置页支持导入 `.frameflow.json` 并预览冲突。

## 开发与验证

```powershell
python -m pip install -r requirements.txt
python -m unittest tests.test_maintenance_v3 tests.test_v3 tests.test_v3_dashboard tests.test_v3_delivery tests.test_v3_function_matrix tests.test_v3_settings tests.test_asset_board tests.test_asset_v3_improvements tests.test_fusion_prompt_flow tests.test_opencode_client tests.test_jimeng_cli -v
npm test                                     # 根目录 V3 Web 测试入口
Push-Location web
npm test                                     # React/Vitest 单元测试
npx tsc -b --pretty false                    # 前端类型检查
npm run build                                # V3 前端构建
npx playwright install chromium
npm run test:e2e                             # Chromium 工作台验收
Pop-Location
$files = Get-ChildItem -Path . -Filter *.js -File | Where-Object { $_.FullName -notmatch '[\\/]node_modules[\\/]' }
foreach ($file in $files) { node --check $file.FullName; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
```

数据库使用版本化迁移（`schema_migrations` 记录版本 1–8）；第 8 版增加项目生命周期状态，迁移可重复执行，`Database.rollback_to(1)` 可回滚新增表并在重新启动时安全重放；运行时只读取 V3 项目、图、资产、时间线和交付作业模型，不启动旧版工作台。

OpenAI 助手使用 Responses API 且默认 `store:false`；图片使用 Images API；TTS 会在返回记录中标记 AI 合成披露。所有付费媒体调用都要求显式确认。即梦 CLI 视频任务采用官方 `submit_id` + `query_result` 后台轮询，成功结果从 CLI 下载目录复制并登记到本地资产库。
