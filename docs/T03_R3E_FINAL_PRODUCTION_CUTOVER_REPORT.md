# T03-R3E Final Production Cutover Report

## Final status

```text
T03-R3E STATUS: FAIL
PRODUCTION CUTOVER: ROLLED_BACK
RUNTIME SOURCE OF TRUTH: LEGACY_V3
READY FOR T00-T03 FINAL RE-AUDIT: NO
```

The one authorized atomic replacement succeeded, but the first mandatory
post-cutover compatibility gate failed. The failed V5 database was preserved,
the Legacy archive was restored atomically, Legacy backend health was verified,
and no second cutover was attempted.

## Historical context

- R3 failed because candidate and production were on different volumes.
- R3B failed with `WinError 32` because the candidate remained open.
- R3C reproduced the root cause: `with sqlite3.connect(...)` commits but does
  not close the SQLite connection.
- R3D fixed explicit connection closure, StateStore/SQLAlchemy disposal,
  factory cleanup, and Windows test temporary-directory ACL handling.
  R3D evidence was `96 passed, 0 failed, 0 blocked`, commit `46cba10`.

## Run and database evidence

```text
Run ID:
T03R3E-20260827T073218Z-1d10d139

FINAL_LEGACY_SHA:
5f28be2381f75f71753eb1af3cf7699d50f31bb804ec3a2193db28bf6ec70a97

Permanent archive:
D:\11067\CodexWorkspaces\frameflow-v3\archives\migrations\v5.3.2\T03R3E-20260827T073218Z-1d10d139

Legacy archive files:
5/5

Legacy archive SHA:
249b7581a66ba9c127b80f3c855aab19a447e9215deb22f775389bed6a314843

Legacy archive integrity:
PASS

Legacy archive mode:
READ_ONLY

Candidate B SHA:
a5a39e33c27b5f5c0f33c4a1cdfc8edf06739f80c82793709b1f6c3a21bb8447

Preserved failed V5 production backup SHA:
8a34b07d37dbf207009651e40497f49c9cf5ee641cf6ba1eea339689e6084d6a

V5 production SHA during cutover:
a5a39e33c27b5f5c0f33c4a1cdfc8edf06739f80c82793709b1f6c3a21bb8447

Production SHA after Legacy rollback verification:
4e742df1c46fb0af92f56426cecd04dd03e8a0cd5daa02ffa55fcc64fcda6455

The post-rollback SHA differs from the archive restore SHA because the
restarted Legacy runtime writes its normal provider capability/profile state;
the active database remained a 41-table Legacy DB with integrity `ok`.
```

The final stopped Legacy baseline had 41 tables, integrity `ok`, and zero FK
violations. Legacy `SH004`–`SH020` accounting was `17/17`, with
`UNACCOUNTED=0` and `UNKNOWN=0`. Candidate B was independently migrated from
the final Legacy archive, not from the live database or a prior candidate.

## Pre-swap gates

```text
Candidate B backend-opened: NO
Candidate B validation: PASS
Candidate B domain tables: 11
Candidate B schema drift: 0
Candidate B integrity: PASS
Candidate B foreign-key check: 0 violations
Candidate B validation PRAGMA gate: journal_mode=WAL, foreign_keys=1, busy_timeout=5000
Candidate B handle-free D: rename probe: PASS
Candidate volume: D:
Production volume: D:
Same-volume: PASS
Archive: 5/5 before swap
8787/8877 stopped before swap: PASS
Production WAL/SHM sidecars before swap: absent
```

## Atomic replacement and rollback

```text
Atomic replacement: PASS (one authorized attempt)
Production V5 tables immediately after replacement: 11 domain tables
V3 schema pollution immediately after replacement: NO
Production V5 integrity immediately after replacement: PASS
Production V5 foreign-key violations immediately after replacement: 0
```

V5 backend PID `23144` started on `127.0.0.1:8787` and returned HTTP 200 with
`runtime_mode=v5`. The required live legacy compatibility checks then returned
HTTP 500 for all 17 historical shots. The backend log identified the exact
cause:

```text
FRAMEFLOW_LEGACY_READONLY_DB is not configured
```

Per the R3E stop rule, no further V5 production checks were run. The V5
backend was stopped, its production DB was preserved as
`data\.cutover\<run>\failed_v5_production.db`, and the canonical path was
restored from a SQLite-consistent rollback candidate made from the permanent
archive. The archive itself remains read-only.

```text
Production rollback triggered: YES
Rollback verification: PASS
Restored Legacy table count: 41
Restored Legacy integrity: ok
Legacy backend after rollback: PASS
8787 health after rollback: PASS (Legacy V3, schema 16)
```

## Post-cutover gate results

```text
Backend: PASS after rollback; V5 backend was not retained
8787 health: PASS after rollback
Workbench critical APIs: passed=15, failed=0 before the stop rule
Workbench full 19-API gate: NOT_COMPLETED
Workbench P0 smoke: NOT_COMPLETED after the failing compatibility gate
SH004–SH020 accessible post-cutover: 0/17 (all returned 500)
Legacy archive SELECT: PASS
Legacy archive INSERT/UPDATE/DELETE: BLOCKED (3/3)
Legacy writable runtime disabled: NO (rollback restored Legacy ownership)
Invalid direct writable access in V5 gateway: 0 observed
Dual write: NO
Dual source of truth: NO after rollback
Transaction rollback post-cutover: NOT_COMPLETED
FK enforcement post-cutover: NOT_COMPLETED
Restart persistence post-cutover: NOT_COMPLETED
```

The V5 health payload was HTTP 200 and `runtime_mode=v5`; its provider
capabilities remained the known T03-R2 deferred/unbound state. The blocking
R3E failure was the missing Legacy archive configuration, not a provider
readiness claim.

## Test accounting

```text
Automated pre-cutover regression: 96 passed, 0 failed
R3D blocked: 0
Live R3E critical routes before stop: 15 passed, 0 failed
Live R3E legacy compatibility gate: 0 passed, 17 failed
Skipped: 0
Blocked: 0
```

The failed V5 database, Candidate B staging directory, and all three preserved
preflight run directories were not staged in Git. Production DB, archive, and
candidate were never staged. Current branch remains `dev/v5.3.2`.

The next permitted step is a separately authorized remediation/re-audit of the
production V5 startup configuration. This task is complete and must not retry
the cutover.
