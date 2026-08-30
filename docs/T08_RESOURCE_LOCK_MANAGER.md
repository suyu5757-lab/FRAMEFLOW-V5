# FRAMEFLOW V5.3.2 — T08 ResourceLockManager

## Result and architecture decision

`core/runtime/resource_locks/manager.py` implements the persistent Resource
Lock MVP over the existing `resource_locks` table. The V5.3.2 four-resource
matrix is now complete and symmetric.

ADR-008, the Scope Freeze, and the approved T08 architecture clarification
define the following matrix:

| Resource pair | T08 contract | Source |
|---|---|---|
| `PHOTOSHOP` + `AFTER_EFFECTS` | CONFLICT | ADR-008 / Scope Freeze |
| `PHOTOSHOP` + `RESOLVE` | CONFLICT | ADR-008 / Scope Freeze |
| `AFTER_EFFECTS` + `RESOLVE` | CONFLICT | ADR-008 / Scope Freeze |
| `COMFY_GPU` + `PHOTOSHOP` | ALLOW | ADR-008 / Scope Freeze |
| `COMFY_GPU` + `AFTER_EFFECTS` | CONFLICT | ADR-008 clarification / Scope Freeze |
| `COMFY_GPU` + `RESOLVE` | CONFLICT | ADR-008 clarification / Scope Freeze |

The additional conflicts are a conservative production-safety policy for the
target RTX 4060 Laptop with 8GB VRAM. Photoshop may still run concurrently
with COMFY_GPU for image/control work; After Effects and DaVinci Resolve may
use GPU acceleration and VRAM, so they remain mutually exclusive with
COMFY_GPU in V5.3.2. Future resources or resource profiles require a new
architecture decision and remain fail-closed until then.

## Resources and storage

The only accepted resource IDs are:

```text
PHOTOSHOP
AFTER_EFFECTS
RESOLVE
COMFY_GPU
```

Runtime truth is the existing SQLite `resource_locks` table with its primary
key on `resource_id`. No second lock table, lock database, or in-memory lock
source is created. `HELD` and `RELEASED` are the minimal T08 status
semantics; release retains the row so a later acquisition updates the same
primary-key record rather than creating lock history ahead of T10 EventLog.

Every owner must already exist in the Runtime `tasks` table. Resource IDs are
strictly allowlisted and arbitrary paths or names are rejected.

## Lock contract

`acquire(resource_id, owner_task_id)` uses one `BEGIN IMMEDIATE` transaction
for owner validation, active lease/conflict inspection, and insert/update.
The transaction is committed before any external work could occur. The
default and frozen values are:

```text
lease_timeout = 300 seconds
heartbeat interval = 30 seconds
```

Re-acquiring an unexpired lock by the same owner is idempotent and returns
the existing row without creating a duplicate or changing its acquired time.
Another owner or any conflicting frozen resource receives
`ResourceBusyError`.

`heartbeat()` and `release()` require both the current `owner_task_id` and a
non-expired `HELD` lease. Wrong owners, released locks, and expired owners
cannot mutate the row. Heartbeat changes only `heartbeat_at`; it does not
change the owner, Task attempt, Task result, or resource ID.

Lease validity is calculated as:

```text
heartbeat_at + lease_timeout > current_time
```

`inspect_expired()` reports stale `HELD` rows without changing Task state or
starting a supervisor/recovery loop. `acquire()` may take over an expired
row by updating the same primary-key record. After takeover, the old owner
fails both heartbeat and release because owner validation is performed in
the write transaction. This protects the current owner from stale-owner ABA
actions without needing a new schema column.

## Worker and future-task boundaries

T08 does not integrate the T07 Worker. The current Task model has no frozen,
typed resource-requirement field, so T08 keeps acquisition explicit and does
not infer a lock from arbitrary `payload_json`. Future Worker integration may
use a trusted requirement registry and must ensure resource waiting is not an
execution attempt and release happens in `finally`.

T08 does not implement EventLog, Provider Idempotency, Supervisor, restart
recovery, Creative App execution, or ResourceLock background watchdogs.

## Test and database boundary

Tests use isolated SQLite databases and injectable clocks; they do not wait
300 seconds and do not write the canonical production database. The
production database is only checked read-only for WAL, foreign keys,
busy-timeout, schema, revision, integrity, and absence of T08 test rows.
