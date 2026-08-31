# FRAMEFLOW V3 · UI 维护报告 — 2026-08-25

**范围**：仅界面层（`web/src/styles.css` + `web/src/App.tsx` 语义化），不涉及任何业务逻辑、API 或数据流变更。
**访问基准**：http://127.0.0.1:8787/

## 巡检方式
- 静态审计 `styles.css`（1340 行）与 `App.tsx`（约 4400 行）的布局结构
- 核查 `AssetBoardFlow.tsx` 中 ReactFlow 容器与表格层的尺寸约束
- 覆盖页面：首页 / 故事 / 资产生产画布 / 声音工坊 / 后期时间线 / 统一资产库 / 设置

## 发现的界面异常（已归类）

### A · 顶栏挤压
`studio-topbar` 采用 `justify-content: space-between` + `gap:16px`，但右侧 `top-actions` 为 `min-width: max-content` 且无滚动容器。窗口缩至 900–1150px 时，“AI 助手 / 快捷键 / 保存 / 启动工作流” 会被推挤出视口或换行错位。

### B · 画布零高度
`.canvas-wrap { height: 100% }` 处于 `studio-content`（`overflow-y: auto`）内，父级未声明 flex 高度时，`ReactFlow` 初始测量高度为 0，切到“资产生产工作区”后首次出现空白需二次 resize 才显示。

### C · 资产画布工具条溢出
`.asset-board-toolbar .canvas-tools` 为单行横向，密集模式下（筛选、列宽、分组开关）总宽度 > 800px，中等宽度下被右侧截断且无法横滑。

### D · 时间线双重定义
`styles.css` 中 `.timeline-v2` 先后出现两套高度定义（`height:100%` vs `height:auto`），且 `.timeline-v2-layout` 的固定 620px 与小屏自适应覆盖顺序不明确，偶发时间线在 1050px 断点下塌陷。

### E · 资产库列定义覆盖
`.asset-library-controls` 在文件末尾被二次定义为 5 列（line 1000），覆盖了前文 4 列版本，窄窗回退逻辑不一致，导致搜索框与筛选器错行。

### F · 滚动条与焦点
细滚动条仅在部分面板定制，深色背景下对比不足；焦点环使用默认 outline，在暗色背景上发虚。

### G · 语义化
顶栏按钮缺 `type="button"`，在被意外包入 `<form>` 或触发回车时会误提交（纯 UI 层面但影响可访问性与稳定性）。

## 已落盘修复（styles.css 末尾追加 section，可安全回滚）

位于 `web/src/styles.css` 末尾 `/* ── UI MAINTENANCE 2026-08-25 ── */`：

1. **顶栏可横滑**：`top-actions` 增加 `overflow-x: auto` 并隐藏滚动条，`studio-topbar` 禁止换行挤压。
2. **画布 flex 化**：`.canvas-wrap/.asset-board-wrap` 改为 `display:flex; flex-direction:column; height:100%`，内部 `.react-flow` 设 `flex:1` 与 `min-height:360px`。
3. **工具条自适应**：`.asset-board-toolbar` 允许 `flex-wrap`，工具区改为 `flex-wrap: wrap`，窄窗下左右内边距收至 12px。
4. **时间线归一**：保留滚动修复版（`overflow-y:auto`），统一 `min-height:620px`，仅在 ≤1050px 时改 `height:auto`。
5. **资产库列回退**：以 5 列为主，≤1100px 回退至 4 列，避免搜索框单独占行时的跳动。
6. **滚动条统一**：补充 `scrollbar-color` 到主滚动容器与资产详情、镜头列表。
7. **小屏对话框**：对话框/抽屉在 760px 下改用 `100dvh` 计算最大高度，避免移动端地址栏遮挡。
8. **抛光**：卡片增加柔和过渡，焦点环统一为 `rgba(215,255,75,.9)`。

`web/src/App.tsx` 仅补充 `type="button"` 到顶栏 4 个按钮（项目管理 / AI 助手 / 快捷键 / 保存 / 启动工作流），零逻辑变更。

## 验证建议
```bash
cd web && npm run dev   # 或 npm run build && npm run preview
# 访 http://127.0.0.1:8787/ 依次检查：
# 1) 顶栏在 900/1100/760 宽度下横滑不截断
# 2) 资产生产画布首次切入即有高度，无需二次 resize
# 3) 资产库搜索与筛选在 680/900/1100 宽度下不错行
# 4) 时间线在 1050/720 断点下不塌陷
```

## 回滚
删除 `styles.css` 末尾从 `/* ── UI MAINTENANCE` 到文件结尾的段落即可。

---
维护人：muse-spark · 仅 UI 层
