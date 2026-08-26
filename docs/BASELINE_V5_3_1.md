# FRAMEFLOW V5.3.1 Baseline

## Snapshot

- Snapshot type: T00 read-only baseline for `FRAMEFLOW V5.3.2 FINAL`.
- Captured: 2026-08-26.
- Authority: `FRAMEFLOW_最终留存版_V5.3.2_FINAL_正确版_展开版_归档主计划.md`.
- Purpose: record observed repository and external-boundary state before the V5.3.2 scope freeze.
- This document records facts observed during T00; it does not claim that the V5.3.2 runtime or schema has been implemented.

## Audit method

The audit used read-only path inspection (`Test-Path`, `Get-Item`, `Get-ChildItem`), Git inspection (`status`, `rev-parse`, `branch`, `remote`, `tag --list`, `log`), and a read-only scan of project/Skill/history script candidates for Git commands. No file was written to `D:\AIGC\SUYU` or `D:\ComfyUI`.

## Physical boundary observations

| Logical role | Physical path | Observed state at T00 | Boundary |
|---|---|---|---|
| Project root | `D:\11067\CodexWorkspaces\frameflow-v3` | Exists; Git worktree | Only writable project root; mounted as `D:\cc\workspace` in the source plan |
| Skill repository | `D:\11067\CodexHome\skills` | Exists | Writable Skill repository; no Skill changes in T00 |
| Historical assets | `D:\AIGC\SUYU` | Exists | READ_ONLY; no writes permitted |
| ComfyUI engine | `D:\ComfyUI` | Exists; contains `models`, `custom_nodes`, `input`, and `output` | Engine/weights boundary; do not copy weights into the project |
| V5.3.2 docs directory | `D:\11067\CodexWorkspaces\frameflow-v3\docs` | Absent before T00 document creation | Created only to hold the four T00 documents |
| Canonical planned Workbench directory | `D:\11067\CodexWorkspaces\frameflow-v3\workbench` | Absent | No Workbench code was created or moved in T00 |
| Existing database | `D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db` | Pre-existing file | Not created or modified by T00; V5.3.2 target remains SQLite WAL at this path |

## Existing project surface

The current repository has a V3-era application surface, including `server.py`, `web\`, `frameflow\`, `tests\`, `scripts\`, and `.github\workflows\ci.yml`. The README describes a FastAPI/SQLite workbench served from the repository and a V3 API surface. The canonical V5.3.2 directory layout (`workbench\backend`, `workbench\frontend`, `core\`, `comfy\registry`, and related folders) was not present at the time of the audit.

The project `.gitignore` ignores `data\`, so the existing database is a local runtime artifact rather than a tracked source file. T00 does not infer that its current schema is the V5.3.2 11-table MVP; that schema is a frozen target for later implementation tasks.

## Existing Skill and historical asset inventory

The active Skill repository currently contains the system skills plus these relevant video/image production packages:

- Image-related: `image-blending`, `image-copy`, `image-explore`.
- Video-related: `video-asset-regulator`, `video-character-design-director`, `video-fusion-production-director`, `video-prop-design-director`, `video-scene-design-director`, `video-script-storyboard`, `video-shot-director`.
- Seedance-related: `seedance-shot-packager`.
- Audio/voice-related packages are present, including `music-sound-designer`, `voice-controller`, and `voice-performance-director`.

The historical read-only tree contains:

- `D:\AIGC\SUYU\image skill` with image blending/copy/explore assets.
- `D:\AIGC\SUYU\video skill` with video asset/storyboard assets.
- `D:\AIGC\SUYU\seedance skill` with `seedance-shot-packager`.
- `D:\AIGC\SUYU\docs` with earlier FRAMEFLOW planning documents.
- No directory named `D:\AIGC\SUYU\photo repair skill` was found.

No historical Skill was migrated, deleted, or edited by T00.

## Git baseline

- Repository root: `D:\11067\CodexWorkspaces\frameflow-v3`.
- Current branch: `main`.
- Tracking state: `main...origin/main`.
- Current HEAD: `7e3e0a9115980fbe599cea74765534417a7d1ea5`.
- Existing tags: none returned by `git tag --list`.
- Merge/rebase/cherry-pick/revert state markers: none found.
- The working tree was already dirty before T00 document creation. The complete status snapshot is recorded in [GIT_SYNC_AUDIT.md](./GIT_SYNC_AUDIT.md).

The two reachable commits returned by `git log -5` were:

1. `7e3e0a9` — 2026-08-13 20:31:42 +08:00 — `suyu` — `build FRAMEFLOW video workbench with voice control`
2. `cd55fbf` — 2026-08-13 11:43:45 +08:00 — `Codex Workspace` — `chore: establish FRAMEFLOW baseline`

The repository currently has an `origin` remote pointing to `https://github.com/suyu5757-lab/video-workbench.git` and a `local-source` remote pointing to `C:\Users\11067\Desktop\video 工作台制作` for fetch/push. T00 records these values; it does not pull, merge, push, create a tag, or create a branch.

## Baseline conclusion

The workspace is usable as the V5.3.2 controlled implementation root, but it is not yet structurally equivalent to the frozen target architecture. The main T00 risks are an already-dirty `main` worktree, absent canonical `docs\`/`workbench\` directories, an existing but unclassified database, and the absence of a discoverable daily Git sync script in the audited scopes. These facts are recorded for the next separately authorized task; T00 performs no remediation.

## T00 non-actions

- No Skill, Runtime, database schema, Workbench UI, sync script, or model was changed.
- No legacy file was moved or deleted.
- No file was copied from `D:\AIGC\SUYU` or `D:\ComfyUI` into the project.
- No local video model, video LoRA, or training workflow was introduced.
