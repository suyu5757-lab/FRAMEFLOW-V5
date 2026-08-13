# FRAMEFLOW 个人 AI 视频工作台

这是一个围绕个人 Codex 视频技能链设计的本地优先工作台原型。它把脚本分镜、资产监管、角色/场景/道具设计、融合、镜头导演和 Seedance 打包组织为一条带门控的生产流水线。

## 启动

直接双击 `index.html`，或双击 `启动工作台.bat` 后访问终端显示的本地地址。

## 当前能力

- 多项目管理与浏览器本地自动保存
- 可视化八阶段生产流水线
- 角色、场景、道具、融合、音频资产分级与状态管理
- 可编辑脚本、横向分镜板、镜头检查器
- 引用角色映射和 Seedance 中文 Prompt 工作区
- 剪辑时间线与交付状态概览
- 一键复制对应 Codex Skill 任务包
- 导出项目 JSON 和 Markdown 交付报告

## 技能链

`video-script-storyboard → video-asset-regulator → character / scene / prop → video-fusion-production-director → video-shot-director → seedance-shot-packager → QA`

重要规则已经体现在界面中：稳定 ID、A/B/C 资产分级、Prompt QA 后才生成、A 级资产缺失时阻塞、两次失败后重建 Prompt、Seedance 前必须经过镜头导演。

## 数据

项目数据默认保存在浏览器的 `localStorage` 中。建议阶段性使用“导出项目”保存 `.frameflow.json` 备份。

## 后续集成方向

当前版本是零依赖本地前端，不直接调用模型 API。下一阶段可增加本地服务层，读取项目目录中的真实素材、接入 OpenAI 图像生成及多家视频模型 API，并将生成任务、成本与返回文件自动登记到资产注册表。
