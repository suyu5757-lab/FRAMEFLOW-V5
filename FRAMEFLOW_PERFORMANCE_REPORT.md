# FRAMEFLOW V3 Performance Report

## Scope

This report verifies audit item `FF-P1-009` using an isolated SQLite database with 1,000 logical assets and 300 shots. No formal project, formal media, or Provider was used.

## Audit baseline

| Measure | Audit baseline |
|---|---:|
| Asset Library API | 9,012 ms |
| Dashboard API | 8,851 ms |
| Asset Library UI | about 46 s / 1,000 mounted items |

## Remediation

- Replaced per-asset relation/Prompt reads with bounded batch projections.
- Moved full hash integrity to explicit `/integrity` requests; library reads never claim a cached green audit.
- Added server query contract: `page`, `page_size`, `q`, `asset_type`, `status`, `sort`.
- Added v13/v14 project projection indexes, verified with `EXPLAIN QUERY PLAN`.
- Added `VirtualAssetList`; its 1,000-item test keeps the rendered slice below 30 rows.

## Acceptance results

| Measure | Result | Threshold |
|---|---:|---:|
| Asset Library HTTP p95 | 76.10 ms | < 1,000 ms |
| Dashboard HTTP p95 | 107.57 ms | < 1,000 ms |
| Library response | 100 of 1,000 items | server pagination |
| Virtual list window | < 30 rows | non-linear DOM growth |

Evidence: `tests/test_v3_performance.py`, `web/src/components/VirtualAssetList.test.ts`, full Python `110/110 PASS`, Vitest `33/33 PASS`.

## Status

`FF-P1-009` is VERIFIED. This is not a release decision; P2/P3 and final re-audit remain required.
