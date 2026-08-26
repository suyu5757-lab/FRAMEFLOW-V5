# FRAMEFLOW V5.3.2

## T01.5 Git & Skill Migration Safety

审计任务：T01.5-R Git & Skill Migration Safety Remediation
日期：2026-08-26（Asia/Shanghai）
项目根：`D:\11067\CodexWorkspaces\frameflow-v3`（等价 `D:\cc\workspace`）

### 1. Executive Verdict

```text
T01.5-R = PASS
Gate 0 = MIGRATION SAFE
```

本轮建立了真实可执行的 branch-aware safe sync 机制，完成了完全隔离的 G1-G5 测试，并为实际 `D:\11067\CodexHome\skills` 建立独立 Git ownership 与稳定快照。没有进入 T02-R、T03-R 或 T05。

远端 GitHub 探针因为当前环境没有可用 Schannel credentials 而 `BLOCKED`；没有为了通过检查修改 credentials 或推送远端。Gate 0 所需的本地稳定快照、开发分支、同步机制、冲突/脏树保护、Skill 恢复和 G1-G5 均通过。

### 2. Git Reality

| Field | Evidence |
|---|---|
| Repo | `D:/11067/CodexWorkspaces/frameflow-v3` |
| Branch | `dev/v5.3.2` |
| HEAD before | `2438d1f0f82fc7a095e02f7d7867d103c8b11b5a` |
| Main SHA | `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641` |
| Project stable tag | `v5.3.2-gate0-baseline` → `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641` |
| Origin | `https://github.com/suyu5757-lab/video-workbench.git` |
| Local source | `C:\Users\11067\Desktop\video 工作台制作`（路径不存在） |
| Dirty state | YES；既有 M/D/?? 文件保持原样，未清理、未 stash、未暂存 |
| Merge/rebase state | 未发现 `MERGE_HEAD`、`CHERRY_PICK_HEAD`、`REVERT_HEAD`、`BISECT_*`、`rebase-merge` 或 `rebase-apply` |

生产项目的已有脏项没有被本轮测试使用或纳入提交。`main` 和 project stable tag 均没有推进。

本轮没有打开 SQLite 连接或执行数据库写操作；对 `data/frameflow.db` 只做了文件存在性、大小、时间和 SHA-256 读取。复核时 `FRAMEFLOW-V3-Service` Scheduled Task 处于 Running，因此运行库可能有独立的外部运行时写入；该并发状态不归因于本轮，也不作为数据库迁移证据。

### 3. Skill Git Ownership

| Field | Evidence |
|---|---|
| Skill root | `D:\11067\CodexHome\skills` |
| Previous ownership | 初始化前不是 Git repo；上级 `D:\11067\CodexHome` 也不是 Git repo |
| Physical relation | Skill root 与上级均无 junction/symlink/reparse；项目 Git 不跟踪该路径；没有发现其他 worktree |
| New ownership | Skill root 自有 Git repo，默认本地分支 `master`，无 remote |
| Stable snapshot | annotated tag `frameflow-skills-baseline-20260826` |
| Snapshot commit | `36b894759f121bd053213160dea42fcd39defc01` |
| Snapshot contents | 117 个非生成文件，含 21 个 `SKILL.md`；排除现有 `__pycache__/*.pyc` |
| Working tree caveat | 仅有未跟踪的现有 `video-character-design-director/scripts/__pycache__/`，未纳入快照 |

项目的 `v5.3.2-gate0-baseline` 本身不包含 `CodexHome\skills`，因此不能单独恢复 Skill。现在的保护模型是“双快照”：项目稳定 tag 保护 FRAMEFLOW 项目；Skill 专属 tag 保护实际 Skill root。恢复实际 Skill 时在 Skill root 使用 `frameflow-skills-baseline-20260826`，不移动路径、不改变 Codex discovery、不覆盖消费者。

快照提交保留了 Skill 文件已有尾随空格/EOF 空行，不把格式清理伪装成业务迁移，也没有修改生产 Skill 业务逻辑。

### 4. Existing Auto-sync Discovery

| Scope | Result |
|---|---|
| Windows Task Scheduler | 只发现三个 FRAMEFLOW 任务：OpenCode Agent Runtime（logon 启动外部 runtime）、OpenCode Runtime Shutdown（关机事件停止外部 runtime）、FRAMEFLOW-V3-Service（logon 启动 project `server:app`）；均无 Git sync |
| User/system Startup | 两个 Startup 目录均只有 `desktop.ini` |
| Registry Run | HKCU/HKLM 相关 Run 项未发现 FRAMEFLOW、Codex、Git、GitHub、sync 或 skills 项 |
| PowerShell profiles | 用户 WindowsPowerShell profile 存在，但未发现相关 Git 操作；PowerShell 7 profile 不存在 |
| Desktop source | `C:\Users\11067\Desktop\video 工作台制作` 不存在 |
| Desktop launchers | 定向检查未发现 Git sync；`启动 DeepSeek Harness.cmd` 不含 Git 命令 |
| Project/scripts | 未发现已有 canonical auto-sync |
| Skill root | 初始化前无 Git owner、无 remote、无 sync script |
| Historical/external scope | `D:\AIGC\SUYU`、外部 runtime 和历史扫描范围未发现 Git sync |

结论：

```text
NO_EXISTING_AUTO_SYNC_CONFIRMED
SCHEDULER_NOT_PREEXISTING
```

本轮没有修改已有 Scheduler，也没有假造一个每日触发时间。canonical 机制已建立并可被人工触发或由后续明确授权的 Scheduler Action 调用；当前不存在真实 daily trigger，因此不声称“已有每日任务”。

### 5. Canonical Sync Mechanism

| Field | Implementation |
|---|---|
| Path | `scripts/git/frameflow_safe_sync.ps1` |
| Language | Windows PowerShell |
| Entrypoint | `-RepositoryRoot`、`-Remote`、`-Path`、`-CommitMessage` 参数；`-Path` 用于精确限定提交范围 |
| Branch detection | 每次调用 `git branch --show-current`；空值立即 `ABORT SAFE` |
| State abort | 检查进行中 Git marker、rebase directories、unmerged files、pre-existing staged changes |
| Dirty behavior | 允许用户明确指定的 dirty paths；不清理、不丢弃、不自动 stash；clean tree 返回 `NO_CHANGES` |
| Protected paths | 阻止 secrets、DB/SQLite、backups、generated、node_modules、venv、媒体归档和超过 100 MB 文件 |
| Commit behavior | 只执行 `git add -- <explicit paths>` 与带消息 commit；不制造空 commit |
| Push behavior | 只执行 `git push <Remote> <CURRENT_BRANCH>`；没有 `--all`、mirror 或 force；不自动拉取/合并 |
| Push failure | 返回 `FAIL SAFE`，不自动 pull/rebase/merge/force；本地 commit 不被重写 |
| Logging | 默认写入 repo Git dir 下 `frameflow-safe-sync.log`，记录 timestamp/repo/branch/HEAD/status/commit/push/result/reason；日志做 secret redaction |
| Temp process output | Git 无输出调用使用两个一次性临时文件捕获 stdout/stderr，进程结束后逐一删除，不进入 Git |

`git push` 只接受运行时检测到的当前分支；脚本源码不写死 `main`、`master` 或 `dev/v5.3.2` 为 push 目标，也不执行 branch switching。

### 6. Git Command Inventory

| Command / class | Class | Reason |
|---|---|---|
| `git rev-parse --show-toplevel`, `git rev-parse HEAD`, `git branch --show-current`, `git status`, `git diff`, `git remote`, `git log`, `git tag` | SAFE | 只读基线、状态、冲突和稳定快照检查 |
| `git add -- <explicit paths>` | SAFE（受控） | 只允许 safe sync 参数提供的路径；预先拒绝 staged state 与受保护路径 |
| `git commit -m <message>` | SAFE（受控） | 仅在明确存在变更且 staged 集合经过检查后执行 |
| `git push <Remote> <CURRENT_BRANCH>` | SAFE（受控） | 当前分支检测后单分支推送；remote 与网络失败均 fail safe |
| `git pull`、`git pull --rebase` | REVIEW | canonical script 不执行；需要人工审查与明确授权 |
| `git merge`、`git rebase` | REVIEW | canonical script 不执行；fixture G2 仅在隔离 repo 制造冲突 |
| `git switch`/branch 操作 | REVIEW / fixture-only | 生产 safe sync 不切分支；fixture 初始化/测试使用隔离 repo |
| reset/restore/clean/force push/automatic main merge | FORBIDDEN | canonical script 静态扫描未发现，生产项目本轮也未执行 |

### 7. Forbidden Command Scan

针对 `scripts/git/frameflow_safe_sync.ps1` 的静态扫描结果：

| Pattern | Found |
|---|---:|
| `reset --hard` | False |
| `checkout .` | False |
| `restore .` | False |
| `clean -fd` | False |
| `push --force` | False |
| `push -f` | False |
| PowerShell parse | PASS |

项目文档中存在政策示例字符串不等于执行记录；本轮没有在生产仓库执行任何 FORBIDDEN 命令。

### 8. G1-G5

测试命令：

```text
python -m unittest discover -s tests/git_safety -p "test_*.py" -v
```

工作目录：`D:\11067\CodexWorkspaces\frameflow-v3`
最终退出码：`0`
最终结果：`Ran 10 tests ... OK`

| Test | Result | Evidence/assertions |
|---|---|---|
| G1 Dev Push Isolation | PASS | 隔离 repo 从同一 base 建立 `main`/`dev/v5.3.2` 与 bare remote；safe sync 提交 fixture Skill 文件；remote dev SHA 等于 local HEAD，remote main SHA 保持 base |
| G2 Merge Conflict Abort | PASS | fixture 制造真实 add/add unmerged 状态（`AA conflict.txt`）；safe sync 非零退出并输出 `ABORT SAFE`；冲突状态保留，remote dev SHA 未改变 |
| G3 No Branch Switching | PASS | sync 前后 `git branch --show-current` 均为 `dev/v5.3.2`；没有生产 branch switch |
| G4 Dirty Tree Preservation | PASS | fixture 同时有 modified tracked file 与 untracked file；只同步指定 tracked path；两份用户内容字节/文本保持，untracked 仍为 `??` |
| G5 Stable Skill Restoration | PASS | fixture stable tag 恢复后执行旧 `render('legacy')` contract 得到 `stable:legacy`；实际 Skill tag 提取 `character_asset_check.py`，用稳定输入执行成功并输出 `Readiness: ready` |

每个 fixture 使用独立 `%TEMP%\frameflow-t015-*` repo 与 `*-origin.git` bare remote；没有使用生产项目做破坏性 Gate test。测试目录由测试生成并保留为临时证据，未进入项目 Git。

### 9. Skill Restore Evidence

真实 Skill 快照：

```text
Skill root: D:\11067\CodexHome\skills
Stable tag: frameflow-skills-baseline-20260826
Stable commit: 36b894759f121bd053213160dea42fcd39defc01
Contract: video-character-design-director/scripts/character_asset_check.py
```

稳定输入为一个 priority B 角色记录，包含 `master_reference`、身份/发型/服装/动作/continuity anchors。测试先在临时副本放入故障实现，再从 Skill stable tag 提取原始脚本，最后执行：

```text
python <temporary-restored-character_asset_check.py> <temporary-character.json>
```

结果：exit code `0`，输出包含 `Readiness: ready`。实际 `D:\11067\CodexHome\skills` 文件未被破坏或改写；恢复目标是临时副本，证明 stable tag 对真实 Skill 内容可恢复、可执行。

### 10. Remote Probe

| Probe | Result |
|---|---|
| Read-only `git ls-remote --tags origin refs/tags/v5.3.2-gate0-baseline` | BLOCKED |
| Reason | GitHub HTTPS Schannel `SEC_E_NO_CREDENTIALS (0x8009030e)` |
| Remote push | NOT RUN |
| Credential change | NOT RUN |
| Remote tag conflict decision | 无法读取远端，未声称存在/不存在；不 force、不覆盖 |

项目 stable tag 仍只在本地，符合本轮不擅自推送 tag/branch 的规则。远端可达性与认证应由后续明确授权的人工探针处理。

### 11. Gate 0 Decision

| Requirement | Result |
|---|---:|
| Stable snapshot | PASS |
| Development branch | PASS |
| Sync mechanism identified/established | PASS |
| Current-branch detection | PASS |
| Current-branch-only push | PASS |
| Merge/rebase/conflict abort | PASS |
| No destructive Git | PASS |
| Skill change classification | PASS；沿用 `docs/MIGRATION_SAFETY.md` |
| Migration test skeleton | PASS；既有 `tests/migration/` 保留，本轮未进入 T02 |
| Rollback / Skill restore | PASS；G5 fixture + 实际 Skill stable tag |
| G1 | PASS |
| G2 | PASS |
| G3 | PASS |
| G4 | PASS |
| G5 | PASS |

结论：

```text
MIGRATION SAFE
```

本结论只表示 T01.5-R/Gate 0 的 Git 与 Skill migration safety 条件完成。不会自动授权或开始 T02-R、T03-R、T05。
