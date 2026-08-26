# FRAMEFLOW V5.3.2 T00 — Git Sync Audit

## Audit status

- Scope: T00 read-only audit; no sync script was changed or executed.
- Captured: 2026-08-26.
- Project repository: `D:\11067\CodexWorkspaces\frameflow-v3`.
- Skill/history scan roots: `D:\11067\CodexHome\skills`, `D:\AIGC\SUYU`.
- Engine boundary: `D:\ComfyUI` was checked as an external engine root and was not used for project Git operations.
- T01.5 status: **PENDING**. Stable tag, development branch, migration skeleton, and rollback test belong to T01.5 and were intentionally not performed in T00.

## Sync script discovery

No dedicated daily Git auto-sync script was found in the audited project, Skill, or historical roots. The project contains `scripts\verify.mjs`, root launcher/diagnostic batch files, and `.github\workflows\ci.yml`; a read-only scan of 55 non-dependency script/config files found no executable Git command and no filename matching `sync`, `daily`, or `auto-update`. `scripts\verify.mjs` runs test gates and does not implement Git synchronization.

**Script path:** `NOT FOUND IN AUDITED SCOPES`.

This is an observed gap, not a reason to invent or repair a script in T00. T01.5 must re-audit any external scheduler, desktop task, or script outside these roots before declaring Gate 0.

## Three-color policy

| Color | Commands / behavior | T00 observation and policy |
|---|---|---|
| SAFE | `git status`; `git rev-parse`; `git branch --show-current`; `git remote -v`; `git log`; `git tag --list` | Used for this audit; read-only inspection only |
| REVIEW | `git add`; `git commit`; `git push` to the detected current branch; `git pull --rebase`; `git merge` | `add/commit/push current branch` are controlled actions; pull/merge require human review. No sync script containing these commands was found |
| FORBIDDEN | `git reset --hard`; `git checkout .`; `git restore .`; `git clean -fd`; `git push --force`; automatic merge of `main`; automatic branch switching | Never allowed for sync; no such command was observed in the audited script/config files |

Dirty-tree safety required by the master plan: if unmerged files, rebase-in-progress, or merge-in-progress markers exist, automation must abort safely and must not attempt recovery. No merge/rebase/cherry-pick/revert marker was present in the T00 snapshot, but the tree was already dirty and therefore is not safe for unattended synchronization.

## Current Git snapshot

- Current branch: `main`.
- Tracking state: `main...origin/main`.
- HEAD / baseline hash: `7e3e0a9115980fbe599cea74765534417a7d1ea5`.
- Stable tag: none; T00 uses HEAD as the baseline reference hash only.
- `origin` fetch/push: `https://github.com/suyu5757-lab/video-workbench.git`.
- `local-source` fetch/push: `C:\Users\11067\Desktop\video 工作台制作`.
- Existing reachable history contains two commits, so `git log -5` returned:

```text
7e3e0a9 | 2026-08-13T20:31:42+08:00 | suyu | build FRAMEFLOW video workbench with voice control
cd55fbf | 2026-08-13T11:43:45+08:00 | Codex Workspace | chore: establish FRAMEFLOW baseline
```

## Dirty working tree captured before T00 commit

The following state existed before the T00 documents were added. It is preserved; T00 does not reset, restore, clean, or overwrite it.

```text
 M .gitignore
 M README.md
 D app.js
 D audio.js
 D index.html
 M server.py
 D styles.css
 D tests/test_server.py
 M 启动工作台.bat
?? .github/
?? .skill-staging/
?? DEEPSEEK_ASSET_MODAL_TYPOGRAPHY_UI_EXECUTION_PLAN.md
?? DEEPSEEK_ASSET_UPLOAD_AUDIT_QUARANTINE_PLAN.md
?? DEEPSEEK_COMMANDER_PLAN_JIEDU_UX_V2.md
?? DEEPSEEK_REVIEW_ROUND_1_CORRECTION_DIRECTIVE.md
?? DEEPSEEK_STORY_OPTIMIZATION_SHOT_ASSET_PLAN.md
?? DEEPSEEK_UI_ASSET_EXECUTION_REPORT.md
?? FRAMEFLOW_PERFORMANCE_REPORT.md
?? FRAMEFLOW_PROJECT_STABILIZATION_PLAN.md
?? FRAMEFLOW_REMEDIATION_PROGRESS.md
?? FRAMEFLOW_V3_AUDIT_REPORT.md
?? FRAMEFLOW_V3_CODEX_REMEDIATION_EXECUTION_PLAN.md
?? FRAMEFLOW_V3_COMPREHENSIVE_UPGRADE_PLAN.md
?? FRAMEFLOW_V3_FUNCTION_TEST_EXCEPTION_REPORT.md
?? FRAMEFLOW_V3_INITIAL_AUDIT_REPORT_2026-08-23.md
?? FRAMEFLOW_V3_Luna_Max_Continuation_Audit_Plan_v2.md
?? FRAMEFLOW_WORKBENCH_UX_REFACTOR_TASK.md
?? OpenCode_修复指南.md
?? PROJECT_CLEANUP_AUDIT.md
?? UI_MAINTENANCE_2026-08-25.md
?? codex-luna-max-plan.md
?? frameflow/
?? package.json
?? requirements.txt
?? scripts/
?? tests/phase8-baseline.db
?? tests/test_asset_board.py
?? tests/test_asset_v3_improvements.py
?? tests/test_audio_workbench.py
?? tests/test_audit_trail.py
?? tests/test_fusion_prompt_flow.py
?? tests/test_jimeng_cli.py
?? tests/test_maintenance_v3.py
?? tests/test_manual_workflow_v3.py
?? tests/test_opencode_client.py
?? tests/test_recovery_v3.py
?? tests/test_security_boundary.py
?? tests/test_upload_streaming.py
?? tests/test_v3.py
?? tests/test_v3_dashboard.py
?? tests/test_v3_delivery.py
?? tests/test_v3_function_matrix.py
?? tests/test_v3_performance.py
?? tests/test_v3_settings.py
?? web/
?? 诊断_OpenCode.bat
```

The status list above is the pre-document snapshot. The four T00 documents are the only intended additions from this task; unrelated dirty changes remain outside the T00 commit.

## T00 conclusion

The audit can establish the current branch, remotes, baseline hash, dirty-tree condition, and absence of an in-scope sync script. It cannot establish Gate 0 because the actual sync mechanism, stable tag, development branch, compatibility skeleton, and rollback behavior still require the separately authorized T01.5 procedure.

## T01.5 Gate 0 deep audit (appended; T00 snapshot above is unchanged)

### Step 1 — Baseline recheck

The T00 freeze was rechecked before any T01.5 write:

- `main` HEAD: `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641`.
- Existing T00 commit: `docs: freeze FRAMEFLOW V5.3.2 final architecture`.
- Remotes: `origin` and `local-source` as recorded above.
- The working tree remains dirty with the pre-existing M/D/?? set recorded in the T00 section; T01.5 did not sweep it into a commit.
- The configured `local-source` desktop path is absent, so it is not treated as a writable source.

### Step 2 — Stable Tag

Created locally, without push:

```text
v5.3.2-gate0-baseline
```

It is an annotated tag. `git rev-list -n 1 v5.3.2-gate0-baseline` returned:

```text
7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641
```

No tag was force-updated.

### Step 3 — Development branch

Created and validated locally:

```text
dev/v5.3.2
```

Before T01.5 document work, both `dev/v5.3.2` and `main` resolved to `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641`. The worktree was returned to `main` for the external audit, then T01.5 documents were authored on `dev/v5.3.2`; `main` remains the frozen baseline.

### Step 4 — Expanded synchronization audit

#### Windows tasks and startup

The elevated read-only `schtasks.exe /query /fo LIST /v` audit parsed 276 task records. The only FRAMEFLOW-related tasks were:

| Task | Trigger | Action | Sync finding |
|---|---|---|---|
| `\FRAMEFLOW OpenCode Agent Runtime` | At logon | External `D:\11067\Codex\2026-08-13\video-2\runtime\opencode-runtime.cmd` | Starts OpenCode on loopback; no Git |
| `\FRAMEFLOW OpenCode Runtime Shutdown` | System shutdown event | External `stop-opencode-runtime.ps1` | Stops OpenCode; no Git |
| `\FRAMEFLOW-V3-Service` | At logon | Project `.venv\Scripts\python.exe -m uvicorn server:app` | Starts V3 service; no Git |

The desktop source `C:\Users\11067\Desktop\video 工作台制作` does not exist. Both Startup folders contain only `desktop.ini`. Run registry inspection found no FRAMEFLOW or Git synchronization entry. The only desktop script launcher found was `启动 DeepSeek Harness.cmd`; it contains no Git command.

#### External scripts and repositories

The external runtime directory exists at `D:\11067\Codex\2026-08-13\video-2\runtime`. Its launcher, shutdown script, registration script, and README describe OpenCode runtime lifecycle only. A read-only scan found no Git command. The external repository itself is a separate dirty `main` worktree with the same `origin`/`local-source` configuration and no Git command in 94 scanned executable/config files. It was not modified.

#### Full command scan

The expanded executable/config scan covered 132 files across the project, Skill repository, historical tree, and external runtime; it found **0** Git command matches. The external FRAMEFLOW repository scan covered 94 files; it found **0** matches. A separate project documentation scan found 32 Git policy/instruction mentions. Those mentions are non-executable documentation, including the T00 policy, this audit, and the user-provided T01.5 instruction file; they are not synchronization mechanisms.

#### Three-color validation

The T00 SAFE / REVIEW / FORBIDDEN table remains the policy authority. T01.5 validated it against the expanded scan:

- SAFE inspection commands were used only for read-only observation.
- REVIEW commands were limited to the explicitly requested Tag, branch, staging, commit, and branch-switch operations; no pull, merge, or push was used.
- No FORBIDDEN command was executed. In particular, no `reset --hard`, `clean -fd`, `checkout .`, `restore .`, force push, automatic main merge, or automatic sync branch switch occurred.
- Dirty-tree abort behavior is now codified in `MIGRATION_SAFETY.md`; unattended synchronization must abort rather than repair or sweep the existing dirty tree.

#### Path safety

The canonical path check for `D:\AIGC\SUYU` inspected `D:\`, `D:\AIGC`, and `D:\AIGC\SUYU`. All resolved to their requested physical paths and none had the ReparsePoint attribute. The historical tree and `D:\ComfyUI` were read-only audit targets; neither received a write. The existing `data\frameflow.db` was not created, migrated, or schema-modified.

### Step 5 — Migration safety skeleton

Added on `dev/v5.3.2`:

- `docs/MIGRATION_SAFETY.md` — classification, BREAKING requirements, branch policy, dirty-tree abort rules, and rollback runbook.
- `docs/GATE0_CHECKLIST.md` — auditable Gate 0 exit checklist.

The other three T00 documents are unchanged. This audit file is the only T00 document updated, by this appended T01.5 section.

### Step 6 — Rollback verification

A disposable branch `codex/t01.5-rollback-probe` was created from `dev/v5.3.2`. It added only `docs/.t01.5-rollback-probe.md` in commit `91fb0c3fc564f2f4f67989c3cda2c61347a802bf`. `git revert --no-edit HEAD` produced `56c518b600ac99f743b0aebccb207a4541d9d9b5`, removed the probe file, and left the disposable branch tree equal to `dev/v5.3.2`. During verification, `main`, `dev/v5.3.2`, and `v5.3.2-gate0-baseline` all resolved to `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641`. The disposable probe branch was then deleted. No formal branch, stable Tag, or existing user change was altered.

### Step 7 — Gate 0 conclusion

**Gate 0 — MIGRATION SAFE: PASS.** The stable Tag, development branch, expanded sync audit, three-color policy, dirty-tree abort policy, migration safety skeleton, and real rollback evidence are present. No T02 or feature work is authorized by this result; the next task must still be explicitly issued.

## T01.5-R Remediation — Git & Skill Migration Safety

审计日期：2026-08-26。此章节追加在 T00 原始快照和 T01.5 历史记录之后；历史章节不改写。

### Remediation baseline

- 当前项目分支：`dev/v5.3.2`。
- T01-R 提交前 HEAD：`2438d1f0f82fc7a095e02f7d7867d103c8b11b5a`。
- `main`：`7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641`，未推进。
- `v5.3.2-gate0-baseline`：仍解析到 `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641`。
- 既有 dirty tree、用户修改和未跟踪文件保持不变，没有 reset、restore、clean 或 stash。

### Skill Git ownership and stable restore

`D:\11067\CodexHome\skills` 在 remediation 前不是 Git repo；上级 `D:\11067\CodexHome` 也不是 repo，没有发现 worktree/junction/symlink 或项目跟踪关系。本轮在完成 ownership/discovery 分析后，为该目录建立独立本地 Git repo：

```text
tag: frameflow-skills-baseline-20260826
commit: 36b894759f121bd053213160dea42fcd39defc01
files: 117 non-generated files / 21 SKILL.md
remote: none
```

快照排除现有 `__pycache__/*.pyc`，未修改 Skill 文件内容、路径或 discovery。项目 stable tag 与 Skill stable tag 是两个明确的保护层：前者恢复项目，后者恢复真实 Skill root。

### Auto-sync discovery decision

扩展检查了 Task Scheduler、用户/系统 Startup、Registry Run、PowerShell profiles、桌面源、项目脚本、Skill root、历史 `D:\AIGC\SUYU` 和外部 runtime。现有三个 FRAMEFLOW Scheduled Task 只负责 OpenCode/V3 服务启动或关闭，未发现 Git 命令；桌面源 `C:\Users\11067\Desktop\video 工作台制作` 不存在；Startup 仅有 `desktop.ini`；相关 Registry Run 项不存在。

结论：

```text
NO_EXISTING_AUTO_SYNC_CONFIRMED
SCHEDULER_NOT_PREEXISTING
```

本轮没有伪造 daily trigger，没有修改已有任务。canonical mechanism 已建立于：

```text
scripts/git/frameflow_safe_sync.ps1
```

它每次检测 `git branch --show-current`，detached HEAD、进行中操作 marker、unmerged files、pre-existing staged changes 时 `ABORT SAFE`；dirty tree 只允许显式 `-Path`，不清理、不 stash、不丢弃；clean tree 返回 `NO_CHANGES`；提交后只执行 `git push <Remote> <CURRENT_BRANCH>`，push 失败不自动 pull/rebase/merge/force。

### Static and fixture evidence

- PowerShell script parse：PASS。
- 禁止模式 `reset --hard`、`checkout .`、`restore .`、`clean -fd`、`push --force`、`push -f`：全部未发现。
- `python -m unittest discover -s tests/git_safety -p "test_*.py" -v`：exit `0`，10 tests passed，0 failed，0 blocked。
- G1 dev push isolation：PASS，remote dev 更新、remote main 不变。
- G2 conflict abort：PASS，真实 `AA` unmerged 保留、无 commit/push/resolution。
- G3 no branch switch：PASS。
- G4 dirty/untracked preservation：PASS。
- G5 stable Skill restore：PASS；隔离 fixture stable contract 与真实 Skill stable tag 的 `character_asset_check.py` 均恢复并执行成功。

### Remote probe

`git ls-remote --tags origin refs/tags/v5.3.2-gate0-baseline` 因 GitHub Schannel `SEC_E_NO_CREDENTIALS (0x8009030e)` 阻塞。没有修改 credentials、没有运行 remote push、没有声称远端 tag 存在或不存在；本地 tag 不变。

### Remediation verdict

```text
T01.5-R = PASS
Gate 0 — MIGRATION SAFE = PASS
```

完整证据见 `docs/T01_5_MIGRATION_SAFETY_REPORT.md`。本章节不授权 T02-R、T03-R 或 T05；完成本 Task 后必须停止并等待下一条明确指令。
