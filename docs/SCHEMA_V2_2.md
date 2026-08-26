# FRAMEFLOW V5.3.2 — Schema v2.2 and ShotSpec Migration Notes

Scope: T02 only. This record describes declarations and dry-run migration code; it does not migrate `data\frameflow.db`.

## Runtime schema decisions

The existing local database was probed read-only and contains 41 V3-era tables. T02 therefore declares a separate provider-neutral target rather than guessing that the production schema is already V5.3.2. The target is exactly the 11-table Runtime MVP from the master plan:

```text
projects, sequences, shots, assets, artifacts, tasks, events,
resource_locks, generations, provider_submissions, reviews
```

The declarations in `core/schemas/runtime_mvp.py` preserve the V5.3.2 corrections:

- `shots.metadata_json` stores extensible shot metadata.
- `assets.master_artifact_id` points to the current asset master.
- `artifacts.asset_id` and `artifacts.source_artifacts_json` preserve provenance.
- `tasks.payload_json`, `tasks.result_json`, and `tasks.error_json` preserve execution evidence.
- `tasks.status` admits `WAITING_FOR_RESOURCE` and `CANCELLED`.
- `generations.package_manifest_artifact_id` tracks the package manifest as an Artifact; no `package_id` is introduced.
- `provider_submissions.idempotency_key` is documented as including `shot_spec_version`, and `request_hash` is persisted beside it.
- SQLite runtime requirements are declared as `journal_mode=WAL`, `foreign_keys=ON`, and `busy_timeout=5000`.

The provider capability profile is intentionally not a twelfth Runtime table. Its v2.2 declaration fields remain explicit beside the table contract, including `estimated_cost_per_submit` and `last_verified_at`; unknown Manual Bridge cost is `null`/`UNKNOWN`, never an invented zero.

`assets.master_artifact_id` and package-manifest provenance are ID links in this declaration so the 11-table creation order remains portable and avoids circular DDL dependencies. Artifact provenance remains explicit and is validated by column contract tests.

## ShotSpec v2.2 decisions

`shot_spec_v2.2.schema.json` declares 31 top-level fields:

- 17 required core fields: identity, sequence, duration, story purpose, characters, scene, props, action, camera, start/end state, dialogue, first/last frame Artifact references, must-keep, must-avoid, and status.
- 14 optional extensions: expression, performance intent, lighting, weather, time of day, visual style, audio cues, quality priority, cost priority, continuity in/out, provider preferences, reference assets, and motion-reference Artifact.

Optional extensions are not required by JSON Schema and declare `default: null`. The canonical migration output materializes all 14 keys with `null` when no source value exists. The camera remains a core object with exactly six subfields: `size`, `height`, `angle`, `motion`, `lens_intent`, and `composition`; missing legacy camera data is normalized to null-valued subfields.

The schema rejects unknown properties, missing core fields, non-positive durations, invalid status values, and incomplete camera objects. Provider-specific configuration is intentionally not a ShotSpec field.

## v1 to v2.2 compatibility path

`scripts/migrate_shot_spec_v1_to_v2_2.py` is a pure in-memory compatibility adapter with a CLI for explicit JSON input/output:

```text
legacy v1 / V3 mapping
→ compatibility adapter
→ canonical v2.2 mapping
→ JSON Schema validation
```

Supported legacy aliases include common V3/camelCase forms such as `id`/`shotId`, `sequenceId`, `duration`/`durationSec`, `purpose`/`storyPurpose`, `action`/`subjectAction`, `characterIds`, `sceneId`, `propIds`, `startState`, `endState`, and first/last frame Artifact aliases. Conservative defaults make incomplete legacy shots valid without inventing provider configuration: `SQ001`, `S_UNKNOWN`, duration `1.0`, empty core text/list/object values, and null optional extensions.

The adapter never opens a database, never writes an asset, and never mutates its input mapping. LOCKED and APPROVED asset records remain byte-for-byte unchanged in the migration tests. `downgrade_shot_spec_v2_2_to_v1` supplies a legacy-shaped representation for rollback and round-trip tests.

## Alembic boundary

`core/migration/alembic.ini`, `env.py`, and the `20260826_01_runtime_mvp.py` revision provide an offline-first Alembic skeleton. The supported T02 proof is:

```text
alembic -c core/migration/alembic.ini upgrade head --sql
```

The output includes the three required SQLite PRAGMA statements and CREATE TABLE statements for the 11 target tables. `env.py` refuses online execution so the existing production database cannot be altered during T02. `downgrade()` emits the reverse table order for later controlled use, but no online downgrade is run in this task.

## Compatibility classification

No existing Skill business logic or external Skill contract was changed. The new schema and adapter are additive T02 declarations. The legacy-to-v2.2 path is treated as migration-sensitive and follows the Gate 0 policy: adapter code, migration tests, a rollback/round-trip test, and explicit non-rewrite protection for LOCKED/APPROVED assets.
