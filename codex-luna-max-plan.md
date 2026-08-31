# Codex Luna Max · UI 修复计划 — 分镜白块 + 资产库上移
> 生成时间：2026-08-25 · 执行模型：luna max · 仅改 UI，不动数据/接口

## 背景
页面 http://127.0.0.1:8787/ 现存两个纯 UI 异常：
1) 故事→分镜 SHOT TABLE 行末 5 个操作按钮显示为白块（见 2026-08-25 截图 SH001–SH010）
2) 统一资产库页顶部两块红框区（右上 4 按钮 + 状态 pills）占用过高，需整体上移为下方资产列表腾出高度

此前已在 `web/src/styles.css` 末尾追加 9) / 10) 段补丁并加 `!important`，但用户硬刷新后问题复现，说明需 luna max 以更系统的方式重做这两处。

## 目标
- 修复后 SHOT TABLE 行末 5 按钮在暗色主题下全部可见、文字可读、禁用态可辨
- 资产库顶部压缩约 40–60px，下方 `S003/BLEND_*` 列表可视行数+2，且保持美观

## 执行范围（只允许改这些）
- `web/src/styles.css`（主战场）
- `web/src/App.tsx` 仅 `StoryView` 的 shot-row 渲染区（最多补 `type="button"` / class，不改逻辑）
- 禁止改动：任何 `frameflow/*.py`、`api/*`、`database`、数据结构、接口字段

## 问题 1 — 分镜行白块

### 定位
- 文件：`web/src/styles.css:178-180` 原规则只有 `min-height/padding`，无 `background/border/color`
- 文件：`web/src/App.tsx:1841` 渲染 `<div className="shot-row-actions"><button>↑</button><button>↓</button><button>复制</button><button>拆分</button><button>删除</button></div>`
- 现象：用户代理默认白底 + 白字在 `#151812` 行背景上呈白块，仅 SH001 的 ↑ 因字符深色勉强可见

### 要求
- 选择器必须强于用户代理：` .shot-table .shot-row .shot-row-actions button ` 并加 `!important` 兜底
- 暗色主题统一：
  - 正常：`background:#1e241b; border:1px solid #2f382a; color:#cbd6c2; border-radius:6px; font-size:9px`
  - hover（非 disabled）：`border-color:rgba(215,255,75,.55); background:rgba(215,255,75,.09); color:var(--acid)`
  - disabled：`opacity:.38; background:#151912; color:#6a7465; border-color:#2a3026; cursor:not-allowed`
- 若单行仍被截断，允许把 ` .shot-row { grid-template-columns: ... minmax(190px,auto)} ` 的最后一列放宽至 `minmax(210px,auto)` 或 `220px`，并保持 `gap:5px` 不换行错位
- 验证：`npm run dev` 后硬刷新 `Ctrl+Shift+R`，SH001–SH010 每行 5 钮均深底浅字，禁用钮灰化

## 问题 2 — 资产库顶部上移

### 定位
- 页：统一资产库 `UNIFIED ASSET LIBRARY · V3 / 统一资产与素材融合`
- 区块 A（右上红框）：`26 项资产 · 1 已登记 · 7 可入镜` + 4 个黄钮 `+新建逻辑资产/刷新/导入候选/保存规格`
- 区块 B（中部红框）：`资产 26 / 待制作 18 / 候选 0 / 审计队列 0 / 已登记 1 / 可入镜 7 / 阻塞 0` pills
- 下方：`FILTER & SORT / 快速定位资产` 面板 + 左右 `S003 / BLEND_*` 列表与详情

### 要求（保持美观与整洁）
- 整体上移，不改结构与功能，仅压内边距与间距：
  - `.asset-library, .story-view, .timeline-view, .settings-view { padding-top:28px→18px; padding-bottom:54px→32px }`
  - `.asset-library-v3 { gap:10px }`
  - `.asset-library-toolbar { gap:10px; margin:10px 0 12px; padding:12px }`（原 18px/13px）
  - `.asset-summary { margin:10px 0 8px; gap:8px }` 内 pill `padding:5px 10px; font-size:9px`
  - `.asset-summary + .asset-library-toolbar / .asset-library-layout { margin-top:6px }`
- 视觉：保持圆角与分隔线，禁止让黄钮换行时被截断；必要时让 ` .asset-library-controls ` 在 ≤1100px 回退为 4 列
- 验证：上移后首屏能多看 1.5–2 行 `BLEND_SH00*`，顶部两红框区与标题间距均匀，无重叠

## 执行步骤（给 luna max）
1. 读 `web/src/styles.css` 全文，确认 9) / 10) 段位置（约 1400 行起）
2. 重做 9) 白块修复为上述强选择器版本（已加 !important 者保留并核对）
3. 重做 10) 顶部压缩，按上述数值逐项压边距；若存在重复的 `.asset-library-controls` 定义，合并为单一 5 列→4 列回退
4. 仅需时改 `web/src/App.tsx:1841` 的 `grid-template-columns` 最后一列至 210/220px（可选）
5. 本地验证：`cd web && npm run dev`，访问 http://127.0.0.1:8787/ ，分别截 故事页 SHOT TABLE 与 资产库首屏
6. 回滚说明：删除 `/* 9) */` 与 `/* 10) */` 两段即回滚

## 验收标准
- [ ] SH001 5 钮与 SH002–SH010 5 钮均为深底浅字，无白块；禁用钮灰化且鼠标为 not-allowed
- [ ] 资产库顶部两红框区整体上移，下方面板与列表上移对应距离，首屏多 40–60px 资产内容
- [ ] 760/980/1100 断点无换行截断，滚动与焦点环正常
- [ ] 未改动任何非 UI 文件

## 回滚
删除 `web/src/styles.css` 末尾 `/* 9) */` 与 `/* 10) */` 段，重启 vite 即可。

