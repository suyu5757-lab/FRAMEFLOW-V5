# T03 Candidate A Formal Evidence Stabilization Closure

Date: 2026-08-28  
Branch: `dev/v5.3.2`  
Repair base: `8c663ab609171b50b93f623ff58bbda7d43d52a6`

## Scope and decision

This closure addresses only the Candidate A formal-evidence physical SHA
drift. Production cutover was forbidden for this run. No call to
`perform_production_cutover` was made, `data/frameflow.db` was not replaced,
and `data/runtime-startup.json` remains absent.

The previous run remains historical evidence:

```text
run = T03FINAL-20260828T122832Z-bab2dd19
recorded formal SHA = 1682c25313356186cc7fd5d3ffa0eafb9588bfd94c680bbcb3e6282f0c123681
stabilized current SHA = eb98fedc0d087dd0ea3526e1670b721e3eb5b88af4588af07cb819a88b703155
classification = PHYSICAL_SQLITE_EVIDENCE_DRIFT_WITH_LOGICAL_STATE_STABLE
```

The stabilization closure is PASS. The production state is still
`LEGACY_V3`; this is not production cutover approval.

## Positive root-cause determination

The root cause is two linked conditions:

1. Candidate A is a smoke candidate. Its runtime writes the isolated smoke
   fixture into SQLite WAL. Those writes are expected during the 19/19 and
   17/17 probes and are removed by the explicit fixture cleanup.
2. The old formal harness captured the main-file SHA before the complete
   SQLite lifecycle had been stabilized. When the final write connection was
   released, SQLite checkpointed/reclaimed the WAL and rewrote database pages.
   The logical V5 state was unchanged after cleanup, but the main-file bytes
   changed.

This is therefore:

```text
Case A: legitimate SQLite physical stabilization
Case D: evidence capture timing bug
```

It is not a provider mutation, hidden migration, wrong path, or Candidate B
write. The process-tree probe also showed that the formal Popen PID and the
actual Windows listener PID differ, but both isolated runtime processes were
gone after stop; no residual Candidate A runtime remained to write the DB.

## Fresh byte-level timeline

Evidence:

```text
data/.cutover/T03-A-EVIDENCE-STABILIZATION-20260828T130341Z-c4042fe3/
candidate-a-byte-level-timeline.json
process-tree-shutdown-probe.json
```

The timeline used a fresh isolated Legacy fixture and a fresh Candidate A on
isolated port `58388`. `alembic_version.version_num` was
`2026082601` throughout; the application runtime schema version was `22`;
SQLite `user_version` was `0` throughout.

| Stage | Main SHA | WAL / frames | SHM | Journal | Pages / free | Logical SHA | Result |
|---|---|---:|---|---|---:|---|---|
| `A_PRE_OPEN` | `4830b959…fca8a0` | 0 / 0 | yes | wal | 29 / 0 | `b404ed2e…3f604` | A0, backend unopened |
| `A_FIRST_RUNNING` after 19/17 | `4830b959…fca8a0` | 41,232 / 10 | yes | wal | 29 / 0 | `addf749b…04ef0f` | ready, 19/19, 17/17 |
| `A_FIRST_STOPPED` | `4830b959…fca8a0` | 41,232 / 10 | yes | wal | 29 / 0 | `addf749b…04ef0f` | listener free |
| `A_RESTART_RUNNING` after 19/17 | `4830b959…fca8a0` | 82,432 / 20 | yes | wal | 29 / 0 | `a8a0b4e2…5012fa` | ready, 19/19, 17/17 |
| `A_RESTART_STOPPED` | `4830b959…fca8a0` | 82,432 / 20 | yes | wal | 29 / 0 | `a8a0b4e2…5012fa` | listener free |
| `A_AFTER_DISPOSE` / cleanup | `ae8126d1…23681a` | absent / 0 | no | delete | 29 / 0 | `b404ed2e…3f604` | cleanup restored baseline |
| `A_AFTER_CHECKPOINT` | `ae8126d1…23681a` | absent / 0 | no | delete | 29 / 0 | `b404ed2e…3f604` | checkpoint `[0,0,0]` |
| `A_FINAL_STABLE` | `ae8126d1…23681a` | absent / 0 | no | delete | 29 / 0 | `b404ed2e…3f604` | stable |
| `A_AFTER_A1_CAPTURE` | `ae8126d1…23681a` | 0 / 0 | yes | wal | 29 / 0 | `b404ed2e…3f604` | read-only evidence opened/closed |
| final stable after A1 checkpoint | `ae8126d1…23681a` | absent / 0 | no | delete | 29 / 0 | `b404ed2e…3f604` | stable |

All stages reported `integrity_check=ok` and zero foreign-key violations.
The header hash and first-page hash stayed constant; the whole-file SHA
changed only after later database pages were rewritten during WAL
checkpoint/reclaim. `page_count`, `freelist_count`, schema revision, and
`user_version` did not change.

The shutdown process probe recorded Popen PID `9892` and listener PID
`31188`; after stop, both isolated PIDs disappeared and port `58388` was
free. This rules out a surviving application writer as the cause.

## SHA capture path and corrected boundary

Old capture path:

```text
scripts/verify_t03_sol_final.py:45-51   sha256(path)
scripts/verify_t03_sol_final.py:408      candidate_sha256_after_probe = sha256(candidate)
```

The old line ran after `cleanup_probe_fixtures`, but without an explicit final
checkpoint and stable-file proof. The later `verify_formal_launcher_evidence`
path rehashed the candidate and correctly rejected the stale claim at
`core/migration/production_environment.py:208-218`.

Corrected path:

```text
scripts/verify_t03_sol_final.py:122      listener_pids
scripts/verify_t03_sol_final.py:134      wait_for_port_free
scripts/verify_t03_sol_final.py:170      stabilize_candidate_after_probe
scripts/verify_t03_sol_final.py:520      final stabilization call
scripts/verify_t03_sol_final.py:522      SHA bound to final stable state
scripts/verify_t03_sol_final.py:545      final_stabilization evidence payload
core/migration/production_environment.py:208-239  fail-closed final-state validator
```

The corrected sequence is:

```text
backend stopped
isolated port FREE
fixture cleanup connection closed
explicit wal_checkpoint(TRUNCATE)
checkpoint not busy
WAL and SHM absent
four physical samples stable
schema/logical evidence captured
final SHA captured
current file revalidated
```

## Candidate A contract decision

Raw physical SHA is not Candidate A semantic identity. Candidate A is allowed
to open and exercise SQLite, so valid WAL/checkpoint lifecycle activity can
change file bytes while preserving the migrated business state.

The semantic identity remains:

```text
frozen source SHA
migration revision and implementation
schema contract and schema fingerprint
logical SHA and all 11 domain-table fingerprints
business primary-key fingerprint
row accounting
UNKNOWN = 0
UNACCOUNTED = 0
SH004-SH020 = 17/17
```

Physical SHA remains mandatory as final-artifact integrity evidence, but only
after the final stabilization boundary. The gate was strengthened with
`final_stabilization`; it was not removed or weakened.

## Fresh isolated certification

Evidence root:

```text
data/.cutover/T03-A-STABILIZATION-CERT-20260828T131639Z-74701e43/
```

Candidate A passed:

```text
first ready = true; status = ready; Workbench = 19/19; SH004-SH020 = 17/17
restart ready = true; status = ready; Workbench = 19/19; SH004-SH020 = 17/17
final checkpoint = [[0,0,0]]
WAL = absent; SHM = absent; stable samples = 4
formal final SHA = 4e92c960402155b86c593161366a95bd8672e64fdac0c08454d9190a387fe0ab
current final SHA = 4e92c960402155b86c593161366a95bd8672e64fdac0c08454d9190a387fe0ab
final evidence/current SHA match = YES
A0/A1 logical delta = NONE
Candidate A rename away/back = PASS; SHA/logical unchanged
```

Candidate B remained a closed-file artifact:

```text
backend-opened = NO
validation = PASS
rename = PASS
A0/B0 semantic equivalence = PASS
UNKNOWN = 0
UNACCOUNTED = 0
SH004-SH020 = 17/17
```

No Candidate B database was opened by a Runtime backend, including after its
rename probe.

## Negative regression

The old failure mode is now explicit: an evidence payload whose recorded SHA
does not equal `final_stabilization.final_candidate_sha256` is rejected with
`formal launcher final stabilization SHA is inconsistent`. The corrected
formal harness produces self-consistent evidence and the validator rechecks
the current candidate bytes.

## Isolated full pre-swap dry-run

Evidence:

```text
data/.cutover/T03-A-STABILIZATION-CERT-20260828T131639Z-74701e43/PRE_SWAP_DRY_RUN.json
```

The isolated dry-run completed fresh Legacy fixture/archive, Candidate A
first/restart/final stabilization, Candidate B/B0, archive finalization,
runtime-config validation, A/B equivalence, and aggregate pre-swap gates.

```text
ALL PRE_SWAP GATES = PASS
perform_production_cutover = NOT_CALLED
production DB touched = NO
```

## Regression results

```text
focused readiness/lifecycle/handles/port/formal = 50 passed
schema/migration/runtime = 130 passed
V3 = 37 passed
post-cutover DB contract = 1 passed
Git safety = 10 passed
full suite = 268 passed
failed = 0
errors = 0
blocked = 0
```

The only output warning was the pre-existing Starlette/httpx deprecation
warning.

## Production safety audit

At closure time, production remained:

```text
runtime source of truth = LEGACY_V3
canonical = D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
health = HTTP 200 / status ready / ready true / runtime_mode legacy
schema = 16 / tables = 41 / integrity = ok / FK violations = 0
runtime-startup.json = ABSENT
8787 = one healthy Legacy owner
Production DB replaced = NO
Production DB intentionally migrated = NO
Dual write = NO
Dual source = NO
```

The previous `T03FINAL-20260828T122832Z-bab2dd19` `PRE_SWAP_ABORT` remains
preserved. No production cutover authorization is implied by this closure.
