# FRAMEFLOW V5.3.2 — Skill Migration Safety

## Gate 0 policy

Status: **PASS**. This document is the T01.5 migration-safety skeleton and policy; it does not implement T02, change a Skill contract, or alter Runtime state.

The protected baseline is the annotated tag `v5.3.2-gate0-baseline`, resolving to `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641`. The development branch is `dev/v5.3.2`. `main` remains the frozen T00 line and is not used for T01.5 implementation commits.

## 1. Change classification

Every future Skill change must carry exactly one classification in its change record:

| Class | Definition | Compatibility expectation |
|---|---|---|
| `INTERNAL` | Implementation optimization, logging, tests, or internal refactoring with no external contract change | Existing callers and outputs remain contract-compatible |
| `NON_BREAKING` | Adds optional fields, optional capabilities, or additive behavior while old inputs and calls still run | Existing callers continue to work without changes |
| `BREAKING` | Deletes or renames a field, changes a required field, changes an action, changes a return structure, or changes a directory/schema contract | Block release until the required migration set is complete and tested |

The classification is based on the externally observable Skill contract, not on the size of the diff. A small path or return-shape change can be `BREAKING`; a large internal test refactor can remain `INTERNAL`.

## 2. BREAKING change required set

No `BREAKING` Skill change may replace the legacy contract until all of the following are present and passing:

1. **Compatibility adapter:** accepts the legacy input/contract and maps it to the new implementation without silently dropping required meaning.
2. **Migration script:** deterministically transforms persisted or archived legacy data.
3. **Migration test:** covers representative legacy inputs and verifies valid new output.
4. **Rollback test:** proves the new change can be reverted to the stable contract/data state without corrupting locked or approved artifacts.
5. **Deprecation note:** identifies the old contract, migration path, support window, and explicit removal gate.

The four operational obligations are therefore: adapter; migration script plus test; rollback test; and deprecation declaration. All five concrete evidence items above must be linked from the task record.

Required compatibility path:

```text
legacy input
→ compatibility adapter
→ new implementation
→ schema/contract validation
→ valid output
```

Only a passing path allows the old contract to be deprecated. `LOCKED` asset masters and approved generations are never rewritten as a migration shortcut.

## 3. Branch and baseline rules

- Work that can affect Skill contracts starts from the stable baseline and is committed on `dev/v5.3.2` or a task branch based on it.
- `main` is the protected frozen baseline for T00/T01.5 evidence; it must not receive an unreviewed Skill rewrite.
- `v5.3.2-gate0-baseline` is an annotated, non-moving reference. It is not force-updated.
- No T01.5 operation pushes a tag or branch. Remote publication requires a separate explicit authorization.
- Every task records branch, HEAD, stable-tag resolution, dirty state, and the exact staged paths before committing.

## 4. Dirty-tree and conflict abort policy

Automation must **ABORT SAFE** without attempting repair when any of these conditions is present:

- unmerged files;
- `.git\rebase-merge`, `.git\rebase-apply`, `MERGE_HEAD`, `CHERRY_PICK_HEAD`, or `REVERT_HEAD`;
- a merge, rebase, cherry-pick, or revert already in progress;
- the current branch is not the branch explicitly authorized by the task;
- staged paths include files outside the task allowlist.

An unattended sync must not use a dirty working tree as input. Existing modified or untracked user files remain untouched and must never be swept into a commit by a wildcard add.

The following are forbidden for sync or migration recovery:

```text
git reset --hard
git checkout .
git restore .
git clean -fd
git push --force
automatic merge of main
automatic branch switching
```

`git pull --rebase` and `git merge` are review-only operations, never automatic recovery. If a provider, sync, or migration step is uncertain, stop and preserve the current state for human review.

## 5. Sync audit result

The expanded T01.5 audit found no daily Git auto-sync script in the project root, Skill repository, historical tree, external FRAMEFLOW runtime tree, or desktop launcher scope. The desktop source named by the configured `local-source` remote (`C:\Users\11067\Desktop\video 工作台制作`) does not exist. Windows has FRAMEFLOW scheduled tasks for OpenCode runtime start/shutdown and the V3 service, but none performs Git synchronization.

The absence is recorded as `NOT FOUND`; no replacement script is invented. The audit found zero executable Git-command matches across the project/Skill/history/external-runtime script scan and zero matches in the external FRAMEFLOW repository scan. Documentation and user-instruction files may contain policy examples such as forbidden Git commands; those are not executable synchronization mechanisms.

## 6. Required preflight for future Skill work

Before any Skill refactor:

1. Read the current stable tag and verify it resolves to the intended commit.
2. Detect the current branch and verify it is the authorized development branch.
3. Check `git status`, conflict markers, and staged-path allowlist.
4. Classify each contract-affecting change.
5. For `BREAKING`, prepare the adapter, migration script/test, rollback test, and deprecation note before removing the legacy path.
6. Run legacy-input compatibility tests and the relevant Skill contract tests.
7. Record the evidence and commit only exact task paths.

## 7. Rollback verification record

T01.5 uses a disposable, explicitly named probe branch to exercise a real reversible commit. The probe must:

1. start from `dev/v5.3.2` without touching `main` or the stable tag;
2. add one isolated probe file and commit only that path;
3. run `git revert --no-edit` on that probe commit;
4. verify the probe file is gone, the resulting branch is clean with respect to the probe, and `main`/stable-tag hashes are unchanged;
5. delete only the disposable probe branch after evidence capture.

The executed probe commit was `91fb0c3fc564f2f4f67989c3cda2c61347a802bf`; its revert commit was `56c518b600ac99f743b0aebccb207a4541d9d9b5`. The probe branch was deleted after verification. The probe was not a product or Skill change.

## 8. Gate 0 exit rule

Gate 0 is eligible for `PASS` only when all of the following are evidenced:

- annotated stable tag resolves to the T00 freeze commit;
- `dev/v5.3.2` exists and starts at that commit;
- `main` remains at the freeze commit;
- project/external scheduler and script audit is complete, including a truthful `NOT FOUND` result where applicable;
- SAFE / REVIEW / FORBIDDEN policy is recorded;
- dirty-tree abort behavior is explicit;
- this migration policy is committed;
- real rollback verification is complete (`91fb0c3` → `56c518b` on the disposable branch);
- no Skill business logic, Runtime, DB, Workbench, historical asset, ComfyUI, or model change is included.

T02 and all feature development remain blocked until this exit rule is satisfied.
