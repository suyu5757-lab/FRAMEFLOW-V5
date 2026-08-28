# T03 Final Pre-Swap Triple-Gate Closure

Date: 2026-08-28
Branch: `dev/v5.3.2`
Baseline: `603a70c398f250ffe440e0fc244e5294ae56078c`

## Decision

This closure performed no Production cutover. Production remained the Legacy
V3 canonical database:

```text
D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
41 tables
schema version 16
runtime-startup.json ABSENT
8787 = one healthy Legacy owner
```

The failed run `T03FINAL-20260828T140500Z-0b2dc631` remains preserved as a
`PRE_SWAP_ABORT`. Its evidence was read only and was not rewritten.

## Root-cause matrix

| Gate | Positive finding | Evidence | Corrective boundary |
|---|---|---|---|
| Archive readonly | The database had Windows ReadOnly attribute `1`; the four JSON/Markdown artifacts had attribute `32` and were writable. | Failed-run archive file audit and `PRE_SWAP_ABORT.json`. | `verify_archive_finalization()` requires exactly five artifacts and every artifact ReadOnly; `finalize_archive_readonly()` applies attributes only after all five files are written. |
| Runtime config binding | `data/runtime-startup.json` did not exist because the failed run never called `perform_production_cutover()`. The reported path was a target path, not an existing config. | Failed-run config presence check and `core/migration/cutover.py` config write immediately before replacement. | `prepare_v5_runtime_config()` writes an isolated or production-target config, and `verify_runtime_config_binding()` separately reports target path, existence, run ID, archive path, and validity. |
| Maintenance freshness | The token was valid from `2026-08-28T14:06:31Z` through `2026-08-28T16:06:31Z`; no expiry or owner failure occurred. The final freshness predicate was never evaluated because the earlier A0/B0 gate aborted first. | Failed-run maintenance state and timestamps. | `verify_maintenance_freshness()` checks active TTL, elevated controller, paused tasks, non-restored state, no respawn, stored FREE state, and a fresh live port probe. |
| Formal interpreter | Actual execution path matched the required path exactly. | `FORMAL_PATH_MATCH=True`. | Reporting typo only; no runtime defect. |

The previous A0/B0 failure also had an evidence-shape error: the operator
payload used `A0_PRE_BACKEND` and `B0_PRE_BACKEND`, while the formal constants
are `A0_MIGRATION_BASELINE` and `B0_MIGRATION_BASELINE`. The corrected dry-run
uses the formal constants.

## Correct lifecycle

```text
fresh isolated Legacy fixture
SQLite-consistent archive creation
Candidate A A0 with A0_MIGRATION_BASELINE
Candidate A first readiness and 19/19 + 17/17
Candidate A restart readiness and 19/19 + 17/17
Candidate A shutdown, cleanup, checkpoint, four stable samples
Candidate A A1, logical delta, and rename proof
Candidate B independent migration and B0_MIGRATION_BASELINE
Candidate B validation and rename proof
no Candidate B reopen
A0/B0 semantic equivalence
write v5_candidate_fingerprint.json from B0
finalize all five archive artifacts ReadOnly
independent archive validation
prepare and validate current-run isolated V5 config
fresh maintenance-equivalent state and live FREE probe
aggregate all pre-swap gates
STOP before perform_production_cutover
```

The two-hour maintenance TTL remains bounded and is not disabled or silently
refreshed. A future real cutover must establish maintenance at the start of
the bounded offline procedure and perform the final freshness check immediately
before the single authorized replacement.

## Implemented controls

`core/migration/preswap.py` provides:

```text
ARCHIVE_REQUIRED_ARTIFACTS
finalize_archive_readonly()
verify_archive_finalization()
prepare_v5_runtime_config()
verify_runtime_config_binding()
verify_maintenance_freshness()
```

`scripts/verify_t03_final_preswap.py` is a no-swap formal harness. It has no
call to `perform_production_cutover` and uses:

```text
D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe
```

## Negative and positive regression

`tests/migration/test_t03_final_preswap_gates.py` proves:

```text
DB ReadOnly + one writable JSON artifact -> aggregate FAIL
all five finalized ReadOnly -> PASS
wrong config run ID -> FAIL
wrong config archive -> FAIL
active paused maintenance + FREE port -> PASS
expired maintenance token -> FAIL
```

## Fresh isolated dry-run

Run:

```text
T03-TRIPLE-GATE-20260828T144221Z-b92a6c72
```

Evidence:

```text
data/.cutover/T03-TRIPLE-GATE-20260828T144221Z-b92a6c72/PRE_SWAP_DRY_RUN.json
```

The dry-run proved:

```text
archive readonly = PASS
runtime config THIS RUN = PASS
maintenance freshness = PASS
Candidate A first/restart = ready=true
Candidate A Workbench = 19/19 and 19/19
Candidate A SH004-SH020 = 17/17 and 17/17
Candidate A final stabilization = PASS; four stable samples; WAL/SHM absent
Candidate B backend-opened = NO
Candidate B validation = PASS
Candidate B rename = PASS
A0/B0 equivalence = PASS
ALL PRE_SWAP GATES = PASS
perform_production_cutover = NOT_CALLED
Production DB touched = NO
```

## Regression results

```text
focused = 55 passed
schema/migration/runtime = 135 passed
V3 = 37 passed
full suite = 273 passed
failed = 0
errors = 0
blocked = 0
```

The only test warning remains the pre-existing Starlette/httpx deprecation
warning.

## Final independent Production audit

```text
Administrator = TRUE
branch = dev/v5.3.2
HEAD = 603a70c398f250ffe440e0fc244e5294ae56078c
Task Action = run-hidden.vbs -> start-frameflow-stack.ps1 -RuntimeOnly
runtime_mode = legacy
status = ready
ready = true
doctor database = canonical
canonical tables = 41
schema = 16
integrity = ok
foreign_key_check = 0
runtime-startup.json = ABSENT
Production DB replaced = NO
Production DB intentionally migrated = NO
Dual write = NO
Dual source = NO
```

This document closes the three pre-swap evidence defects only. It does not
authorize a Production replacement. A separate explicit authorization is
required for any future one-swap cutover.
