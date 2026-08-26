# FRAMEFLOW V5.3.2 — SQLite WAL StateStore

Scope: T03 only. This document records the minimal StateStore layer; TaskStore, Queue, Worker, ResourceLockManager, Provider Gateway, and scheduler behavior remain later Tasks.

## Boundary and database safety

The existing `D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db` is a V3-era 41-table database. T03 never opens it for schema creation or migration. `StateStore(initialize=True)` refuses the canonical production path; tests use an isolated temporary file database and an in-memory SQLAlchemy metadata check.

The default connection target remains the Runtime Source of Truth path for future runtime use:

```text
sqlite:///D:/11067/CodexWorkspaces/frameflow-v3/data/frameflow.db
```

No state-store import creates a file or changes the production schema.

## Initialization choice

T03 uses `core/schemas/runtime_mvp.metadata.create_all()` only for an explicitly initialized isolated test database. This reuses the single T02 11-table declaration and avoids a second schema definition. The Alembic path remains offline-only; T03 does not run Alembic online against production. A later controlled migration task can decide how the existing V3 schema is transformed after backup and migration tests.

## SQLite connection policy

Every new pooled SQLite connection applies:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
```

`busy_timeout=5000` is also supplied through the SQLite connection factory. `StateStore.pragmas()` exposes the observed values, `table_names()` exposes the current database table list, and `wal_file_exists` provides a filesystem-level WAL sidecar check during an active write. `close()` disposes the engine and returns all pooled connections.

## Transaction and CRUD policy

Project, Sequence, Shot, Asset, Artifact, and Generation create/update operations use `engine.begin()` explicitly. JSON-bearing fields are serialized at the boundary: `shot_spec_json`, `metadata_json`, `source_artifacts_json`, and the Runtime JSON fields remain stored as JSON text. Read/list operations return stable row mappings.

Each write accepts an optional event specification. When provided, the entity mutation and the `events` insert use the same transaction. A duplicate event ID test proves that the entity insert rolls back together with the event insert. This is the T10 EventLog seam, not a full EventLog implementation.

The API deliberately does not expose TaskStore or queue/worker behavior. The `tasks` table is created from the T02 metadata so later Tasks have a stable state surface, but T03 performs no task scheduling.

## Persistence and concurrency decisions

- SQLite WAL is validated on a temporary file database, not the production database.
- Foreign-key enforcement is validated with a deliberately invalid Sequence insert.
- Persistence is validated by closing the StateStore and reopening the same temporary path.
- Two connections simulate a writer holding a transaction. The second writer waits for the first writer to release the lock and succeeds within the configured timeout rather than failing immediately.
- Temporary databases are removed by Python's `TemporaryDirectory` cleanup after each test; no project `data\` file is used.

## Scope classification

This is a `NON_BREAKING` additive persistence layer under `docs/MIGRATION_SAFETY.md`: it adds a new `core/runtime/state_store` API without changing existing Skills, Workbench routes, Provider adapters, or creative-app behavior. It remains subject to the existing typed-action, non-destructive, provenance, and future Task Runtime gates.
