# OpenCode 连接失败修复指南 — 针对截图 `All connection attempts failed`

> **结论先行：不是额度问题。** FrameFlow 的探活是 `GET http://127.0.0.1:4096/global/health`，截图中延迟 2033ms 后报 `All connection attempts failed` 说明本地 OpenCode Server 根本没在监听 4096，有没有额度都连不上。

## 1. 截图信息解读

* `Provider 目录` 中 `OpenCode Agent` 已接入（黄灯 `已接入`）
* 中间大卡 `CONNECTION STATUS：连接失败 / 无法连接 OpenCode Server: All connection attempts failed / 2033ms / 重排能力 编排 Agent / 最近检测 2026/8/25 13:08:03`
* `Base URL: http://127.0.0.1:4096` / `Server 用户名 opencode` / `Agent buiid`
* 代码层面探活（`frameflow/opencode_client.py: probe_opencode`）就是同时请求 `/global/health` 和 `/provider`，任意一个连不上就抛 `ProviderError("无法连接 OpenCode Server", "connection", 502)`

## 2. 立刻怎么做（按顺序）

### 步骤 A — 双击 `诊断_OpenCode.bat`
已为你生成在项目根目录，双击后会依次检查：是否安装、4096 是否监听、/health、/provider、密码环境变量、FrameFlow 8787。红色 `X` 项即病根。

### 步骤 B — 手动把 Server 跑起来
打开一个**新的** PowerShell 窗口（不要关），执行：

```powershell
# 1. 确认安装
opencode --version
# 若提示找不到，先装
npm install -g opencode-ai

# 2. 启动 Server（前台运行，保持窗口不关）
opencode serve --hostname 127.0.0.1 --port 4096

# 3. 另开一个 PowerShell 验证
Invoke-RestMethod -Uri http://127.0.0.1:4096/global/health | ConvertTo-Json -Depth 5
# 期待：{"healthy": true, "version": "x.x.x"}

Invoke-RestMethod -Uri http://127.0.0.1:4096/provider | Select-Object -ExpandProperty connected
# 期待：列出你已登录的 provider，例如 opencode-go
# 若为空，说明你在 opencode 里还没登录 / 还有额度但未连接，完成登录后再试
```

> `启动工作台.bat` 当前版本**不会**自动帮你拉起 OpenCode，必须单独起。关掉启动 Server 的窗口 = 又会连不上。

### 步骤 C — 回到 FrameFlow 重检
`设置与 Provider` → 选中 `OpenCode Agent`（红框那条）：
1. `Base URL` 确认是 `http://127.0.0.1:4096`（不要加 `/` 后缀）
2. `Server 用户名` 保持 `opencode`
3. `Server 密码`：只有当你启动前设置了 `$env:OPENCODE_SERVER_PASSWORD` 才需要填；没设就留空。两边必须一致，否则健康检查也会 401
4. 点右上角 `连接检测`，直到显示 `已配置 / 4 个 Provider 配置` 且延迟 < 500ms
5. 再点右侧 `保存绑定`，最后 `应用此接入点与模型`

## 3. 常见坑位对照表

| 现象 | 原因 | 解法 |
|---|---|---|
| `All connection attempts failed` 延迟 2-4s | Server 没启动 / 端口被占 / 防火墙拦 127.0.0.1 | `opencode serve` 前台启动；`netstat -ano \| findstr 4096` 查 PID；企业杀毒放行 127.0.0.1 |
| `401 Unauthorized` | 设了 `OPENCODE_SERVER_PASSWORD` 但 FrameFlow 没填或填错 | 两边同步，重启 Server 后再检测 |
| `provider connected 为空` 但 health 通过 | OpenCode 里没登录，额度在别处 | 在 opencode TUI 里完成 `opencode-go` 登录 / 授权，再 `GET /provider` 应见 `connected: ["opencode-go"]` |
| `4096 被占用` | 上次异常退出未释放 | `netstat -ano \| findstr 4096` 找到 PID → 任务管理器结束，或换端口并同步改 FrameFlow 的 Base URL |
| 启动后瞬间又掉 | Node 版本过旧 / 权限不足 | 升级 Node ≥20，以管理员 PowerShell 启动试一次看报错 |

## 4. 带密码的启动方式（如需要）

```powershell
$env:OPENCODE_SERVER_PASSWORD="你设置的强密码"
opencode serve --hostname 127.0.0.1 --port 4096
# 然后在 FrameFlow 的 OpenCode Agent 密码框填同一个值，再点连接检测
```

## 5. 仍连不上时，请贴这三段输出

1. `诊断_OpenCode.bat` 的完整截图
2. `opencode serve` 窗口的启动日志前 30 行
3. PowerShell 中 `Invoke-RestMethod http://127.0.0.1:4096/global/health` 的返回

额度本身由 OpenCode 内部 provider 管理，只要 `/provider` 的 `connected` 里出现了你的 provider，FrameFlow 就会在 `model_catalog` 里列出 `provider_id/model_id` 供绑定。

---
*生成时间 2026-08-25 针对 frameflow-v3 `frameflow/opencode_client.py` 探活逻辑*
