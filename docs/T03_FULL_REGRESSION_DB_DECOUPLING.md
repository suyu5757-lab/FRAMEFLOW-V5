# T03 full regression DB decoupling

## Executive summary

The prior production-cutover attempt correctly reached V5, passed its runtime
gates, then rolled back because the full regression suite still treated the
canonical path as an implicit Legacy fixture. This change removes that test
architecture defect. It does not alter migration mapping, candidate A/B,
runtime ownership, port ownership, or production data.

The complete original failure inventory is in
`T03_FULL_REGRESSION_DB_ASSUMPTION_MATRIX.md`: 31/31 entries were classified
and resolved without skip or xfail.

## Canonical and fixture contracts

* Production canonical is runtime-mode dependent: Legacy before cutover and
  V5 StateStore after a successful cutover.
* `legacy_v3.db` is created per test under `FRAMEFLOW_TEST_TMP`.
* `v5-candidate.db` is produced from that fixture by the real offline
  migrator.
* `legacy_readonly.db` is a distinct SQLite backup used only through
  `LegacyReadOnlyCompatibility`.
* V5 and Legacy paths are asserted unequal. Missing Legacy configuration still
  fails closed; there is no fallback to `data/frameflow.db`.

## Test architecture changes

`tests/conftest.py` now owns the real SQLite Legacy fixture factory and an
opt-in `FRAMEFLOW_TEST_CANONICAL_DB` pytest hook. The hook only exists inside
pytest and allows the full suite to bind canonical guards to an existing
isolated V5 fixture. It cannot affect a normal process or production runtime.

Affected migration, startup-config, formal-launcher, server-persistence,
handle-lifecycle, and historical-shot tests now request explicit fixture
paths. Their pools and subprocesses are disposed by the existing test lifecycle
before rename probes. V3 tests already patch `server.DB_PATH` to per-test files
and do not reference production canonical.

## Production-state simulation

`test_post_cutover_db_contract.py` models:

1. Legacy canonical in a test directory;
2. a test-only `os.replace` to V5 canonical plus separate Legacy readonly DB;
3. rollback by restoring a backup of the separate Legacy readonly DB.

It asserts 11 V5 domain tables, explicit distinct paths, SH004-SH020=17/17,
blocked Legacy writes, persistence disposal, and an absent startup config after
the simulated rollback.

## Evidence

| Gate | Result |
| --- | --- |
| Original full command after repair, Legacy rollback state | 117 passed, 0 failed/errors/blocked |
| Same full command with isolated canonical=V5 | 117 passed, 0 failed/errors/blocked |
| V3 regression | 37 passed |
| V5 canonical-is-not-Legacy / rollback contract | PASS |
| Added skipped blocker tests | 0 |
| Added xfailed blocker tests | 0 |

## Independent audit

1. No test unconditionally treats `data/frameflow.db` as Legacy.
2. No fixture opens production canonical for data/schema work.
3. V3 tests use patched per-test DB paths.
4. V5 tests use isolated V5 candidates.
5. Legacy compatibility uses explicit isolated readonly paths.
6. Successful V5 cutover is simulated with real SQLite replacement.
7. Legacy rollback is simulated independently.
8. Persistence is disposed and subprocess test environments are explicit.
9. No blocker was hidden with skip/xfail.
10. The exact full suite passes with canonical=V5.

## Production safety and verdict

No production replacement or intentional production mutation was performed.
The live runtime remains Legacy V3, 41 tables, integrity checked, with no
`runtime-startup.json`; port 8787 remains under the expected FRAMEFLOW owner.
There is no dual write and no dual source of truth.

**Final verdict: the full-regression database assumption blocker is closed.**
