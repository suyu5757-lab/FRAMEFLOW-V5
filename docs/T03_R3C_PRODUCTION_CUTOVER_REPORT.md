# T03-R3C Handle-Safe Production Cutover Report

## Result

```text
T03-R3C STATUS: FAIL
PRODUCTION CUTOVER: NOT_PERFORMED
RUNTIME SOURCE OF TRUTH: LEGACY_V3
```

The R3C cutover attempt did not touch or replace the production database.
Candidate B was blocked at the
mandatory Windows rename probe before any production move or replace.

## Baseline and recovery

- Branch: `dev/v5.3.2`
- HEAD before: `a66353e81d8b74e972f034c297258150a10b593a`
- Formal stopped-source `FINAL_LEGACY_SHA`:
  `70f127d640d825ebb452ec78435264b3d2b34f3db8a49ba25575a8ddd0cdc710`
- Post-recovery legacy runtime SHA observed:
  `5f28be2381f75f71753eb1af3cf7699d50f31bb804ec3a2193db28bf6ec70a97`
- The latter changed because the recovered legacy service writes its provider
  capability/profile state during startup; it is not treated as the R3C source.
- Legacy V3 was restarted after the pre-swap block and `/api/health` returned
  `3.0.0`, schema `16`, ready.

## Candidate evidence

- Candidate A:
  `D:\11067\CodexWorkspaces\frameflow-v3\data\.cutover\T03R3C-20260826T155354Z-ac9a373c\smoke_candidate.db`
  - backend opened: YES
  - 19/19 Critical API smoke: PASS
  - SH004–SH020: 17/17
  - restart persistence: PASS
  - release rename probe: PASS
  - production swap eligible: NO
- Candidate B:
  `D:\11067\CodexWorkspaces\frameflow-v3\data\.cutover\T03R3C-20260826T155354Z-ac9a373c\swap_candidate.db`
  - independently migrated from the final stopped legacy snapshot
  - backend opened: NO
  - schema/integrity/StateStore validation: PASS
  - same-volume staging: PASS (`D:` → `D:`)
  - handle-free rename probe: FAIL (`WinError 32`)

## Handle root cause

The R3C harness used `with sqlite3.connect(...) as con`. SQLite's connection
context manager commits or rolls back the transaction but does not close the
connection. The connection therefore retained Candidate B's Windows file
handle when `os.replace`/the rename probe ran. This was reproduced at the
Candidate B pre-production probe; no V5 backend had opened Candidate B.

The code now provides explicit `StateStore.dispose()`,
`RuntimePersistence.dispose()`, factory shutdown, an explicit checkpoint helper
with `finally: connection.close()`, and a mandatory handle-free rename probe.

## Archive and cutover

- Previous R3 and R3B failed directories: preserved and marked
  `FAILED_CUTOVER_ATTEMPT`.
- R3C permanent archive: not formed because Candidate B hard gate failed first.
- Permanent archive files: `0/5`.
- Production V5 SHA: `NONE`.
- Atomic replacement: `NOT_PERFORMED`.
- Production rollback: `NO`; no production replacement occurred.
- Production DB staged: `NO`.
- Archive staged: `NO`.

## Tests

```text
pytest tests/runtime/test_t03_r3c_handles.py tests/migration/test_t03_r3b_cutover.py -v
8 passed, 0 failed
```

The suite covers StateStore dispose, explicit SQLite checkpoint close,
Candidate A backend wait/pipe close, persistence dispose, A/B separation,
cross-volume abort, and same-volume path validation. The independent Candidate
A dry run passed 19/19 APIs and all 17 historical IDs.

The broader `tests/schema tests/migration tests/runtime` run reached
`44 passed, 10 failed`; the 10 failures occurred while creating SQLite test
directories under the Windows-restricted temporary directory and raised
`sqlite3.OperationalError: unable to open database file` before their test
bodies. They did not touch production and are not counted as R3C production
evidence.

## Final gate

```text
Candidate A release probe: PASS
Candidate B backend-opened: NO
Candidate B handle-free probe: FAIL
Permanent archive: 0/5
Atomic replacement: NOT_PERFORMED
V5 production source of truth: NO
READY FOR T00-T03 FINAL RE-AUDIT: NO
```

Per T03-R3C stop rules, no second production Cutover was attempted.
