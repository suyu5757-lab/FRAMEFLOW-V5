# FRAMEFLOW V5.3.2 — T03-R StateStore Cutover Report

Audit date: 2026-08-26
Task: T03-R SQLite WAL StateStore production integration and controlled cutover
Branch: `dev/v5.3.2`

## Executive result

**T03-R: PARTIAL. Production cutover: NOT_PERFORMED.**

The safe portion of T03-R is implemented and measured: one V5 StateStore
factory, read-only legacy compatibility, a fresh production snapshot and
candidate rehearsal, 11-table/PRAGMA/integrity checks, and explicit cutover
guards. Production replacement is blocked because the current backend still
owns the V3 `Database` directly and cannot start against the V5 11-table
candidate. No production file was moved, replaced, or migrated.

## Required legacy-shot accounting

The current production document contains all required historical records:

| Classification | Count | Rule |
|---|---:|---|
| `MIGRATE_TO_V5` | 0 | No SH004–SH020 record currently passes v2.2 validation. |
| `LEGACY_READ_ONLY_COMPAT` | 17 | Every record is available through `LegacyReadOnlyCompatibility` using `mode=ro`; BLOCKED/PARTIAL/MISSING statuses are not rewritten. |
| `PROVEN_ARCHIVE_ONLY` | 0 | No required record is absent from the source. |
| `UNACCOUNTED` | 0 | All SH004–SH020 IDs were found and read. |

The three ready shots (`SH001`–`SH003`) remain in the fresh candidate. The 17
unfinished historical shots remain in the legacy snapshot and are explicitly
accounted for rather than being inserted with invalid V5 statuses.

## Fresh rehearsal evidence

The rehearsal used a new SQLite backup and a new candidate generated from the
current production file. It did not reuse the T02 candidate and did not write
the production path.

| Gate | Result |
|---|---|
| Source SHA before/after | unchanged (`fccac6a29fa5c91d0ccccdc2545ae1f17010e9349aadd60712401e54d0142cf6`) |
| Source tables | 41 legacy V3 |
| Candidate tables | exact 11 V5 domain tables plus Alembic/internal tables |
| Candidate StateStore open | PASS |
| Candidate WAL | PASS |
| Candidate foreign keys | PASS (`1`) |
| Candidate busy timeout | PASS (`5000`) |
| Candidate integrity check | PASS (`ok`) |
| Candidate foreign-key check | PASS (0 violations) |
| Candidate transaction commit/rollback | PASS in isolated StateStore smoke |
| Candidate close/reopen | PASS |
| Candidate application restart | NOT_PERFORMED |
| Backend startup against V5 candidate | BLOCKED: current V3 backend expects absent tables |
| Workbench smoke on V5 candidate | NOT_PERFORMED |

Temporary evidence paths are intentionally outside Git. The production path
was not used as a candidate, and no database/WAL/SHM file was staged.

No listener was observed on TCP port 8787 during the audit. Process command-line
inspection was denied by the host policy and no writer proof was available;
no process or scheduled task was stopped. This is another reason the
production replacement gate remained closed.

## Ownership and cutover controls

Implemented controls:

- `core/runtime/state_store/factory.py` is the only new production V5 opening
  boundary. It resolves the canonical path, detects `LEGACY_V3`/`MIXED`/V5,
  refuses production initialization, and verifies WAL/FK/busy-timeout.
- `core/migration/legacy_compat.py` opens only with SQLite `mode=ro` and
  rejects write attempts. It supports read access for SH004, SH010, SH015,
  SH020 and the complete required range.
- `core/migration/cutover.py` defaults to preflight/no-op, creates fresh
  side-by-side candidates, checks all 17 legacy IDs, and requires both an
  explicit production flag and a no-active-writer proof before replacement.
- The replacement guard also refuses to proceed while legacy `-wal`/`-shm`
  sidecars exist; checkpointing and verification must happen before any move.
- A replacement failure attempts same-volume restoration of the original
  legacy path; it does not delete the legacy file first.

Not yet closed:

- `server.py` still constructs `frameflow.database.Database` and has
  `INVALID_DIRECT_ACCESS` call points.
- No safe V5 backend adapter exists for the V3 provider/task/workflow routes.
- Backend restart and Workbench smoke on the V5 schema were therefore not
  executed.
- No permanent project archive was created because the production cutover
  gate was not satisfied. The tool can create the required five-file rollback
  evidence set only as part of a reviewed cutover preparation.

## Final status fields

```text
T03-R STATUS: PARTIAL
PRODUCTION CUTOVER: NOT_PERFORMED
RUNTIME SOURCE OF TRUTH: LEGACY_V3
Production DB: D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
Production V5 domain tables: 0
Legacy DB: current production file (not moved; no archive created)
Legacy DB mode: WRITABLE (existing V3 backend remains active)
SH004–SH020: accounted = 17/17; migrated = 0; legacy_read_only = 17; archive_only = 0; unaccounted = 0
WAL: PASS
Foreign keys: FAIL (raw legacy connection reports 0; V3 per-connection setting is not V5 ownership)
Busy timeout: PASS
Integrity check: PASS
Foreign key check: PASS
Transaction commit: PASS (isolated V5 candidate)
Transaction rollback: PASS (isolated V5 candidate)
Close/reopen: PASS (isolated V5 candidate)
Restart persistence: FAIL (backend restart on V5 not performed)
Backend startup: FAIL (V3 backend is not V5-compatible)
Workbench smoke: FAIL (not performed against V5)
Legacy writable runtime disabled: NO
Dual write: NO
Dual source of truth: NO
Cutover rehearsal: FAIL (blocked before app integration rehearsal)
Rollback rehearsal: FAIL (no V5 production state was activated)
Production rollback triggered: NO
READY FOR T00-T03 RE-AUDIT: NO
```
