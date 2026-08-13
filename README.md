# FRAMEFLOW 个人 AI 视频工作台

这是一个围绕个人 Codex 视频技能链设计的本地优先工作台原型。它把脚本分镜、资产监管、角色/场景/道具设计、融合、镜头导演、配音配乐和 Seedance 打包组织为一条带门控的生产流水线。

## 启动

直接双击 `index.html`，或双击 `启动工作台.bat` 后访问终端显示的本地地址。

如需使用 OpenAI 图片或配音试听生成，请先在当前终端设置 API 密钥，再启动本地服务：

```powershell
$env:OPENAI_API_KEY="你的 API 密钥"
python server.py
```

然后访问 `http://127.0.0.1:8787`。密钥只由本地服务从环境变量读取，不会写入网页或项目数据。

## 当前能力

- 多项目管理与浏览器本地自动保存
- 可视化八阶段生产流水线
- 角色、场景、道具、融合、音频资产分级与状态管理
- 人物资产采用轻量默认：A 级人物先建立主设计图与面部近照，其余视镜头需要追加
- 可编辑脚本、横向分镜板、镜头检查器
- 引用角色映射和 Seedance 中文 Prompt 工作区
- 剪辑时间线与交付状态概览
- 一键复制对应 Codex Skill 任务包
- 导出项目 JSON 和 Markdown 交付报告
- 使用 `gpt-image-2` 生成镜头关键帧，并自动登记生成记录
- Voice Controller 声音资产库、参考声音本地导入和授权状态
- 逐句对白、OpenAI TTS 试听、Take 版本及音频 QA
- 配乐 Cue、版权门禁和 Seedance `@Audio` 交接映射
- 导出独立的音频生产包 JSON

## 技能链

`video-script-storyboard → video-asset-regulator → character / scene / prop → video-fusion-production-director → video-shot-director → voice-controller → seedance-shot-packager → QA`

重要规则已经体现在界面中：稳定 ID、A/B/C 资产分级、Prompt QA 后才生成、A 级资产缺失时阻塞、两次失败后重建 Prompt、Seedance 前必须经过镜头导演、声音克隆前必须验证授权、批准 Take 不被覆盖。

## 数据

项目数据默认保存在浏览器的 `localStorage` 中。建议阶段性使用“导出项目”保存 `.frameflow.json` 备份。

## 后续集成方向

当前版本包含零依赖本地前端和一个 Python 标准库本地服务。图片生成使用 OpenAI Images API，配音试听使用 OpenAI Audio Speech API。参考声音上传只写入本地 `generated/audio/references/`；任何外部克隆或转换仍需单独确认。后续可接入 MiniMax、CosyVoice、ElevenLabs 和音乐生成供应商适配器，并将成本、任务队列与返回文件扩展到统一资产注册表。
