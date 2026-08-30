# FRAMEFLOW V5.3.2 — T26 Manual Adapter Architecture Closure

## Closure status

The former T26 blocker was:

```text
GENERATION_RESULT_BINDING_CONTRACT_REQUIRED
```

This closure freezes the missing canonical relation as:

```text
artifacts.generation_id → generations.id
```

The column is nullable, indexed, and uses restrictive delete behavior. A
Generation owns zero or many result Artifacts.

## Binding semantics

`generations.package_manifest_artifact_id` remains the input package-manifest
relation and its Artifact keeps `generation_id = NULL`. Asset masters, first
and last frames, scene references, prop references, and other reusable input
Artifacts also remain NULL. A Provider or Manual result Artifact uses:

```text
generation_id = owning Generation.id
role = provider_result
shot_id = Generation.shot_id
project_id = Generation.shot_id.project_id
```

The project/shot consistency checks belong to the later trusted binder. Paths
and `tasks.result_json` are not relationship authorities.

Existing Artifacts are backfilled only with NULL. Legacy V3 fields are not
inferred or copied into the V5 relation.

## Scope boundary

```text
Manual Adapter implementation = NOT STARTED in this closure
Result Import implementation = NOT STARTED in this closure
T16 Package Builder = NOT STARTED
T48 Mock E2E = NOT STARTED
```

This document records the architecture decision and migration evidence only.
It does not implement `prepare`, `submit`, `Mark Submitted`, external task ID
binding, result import, or review handoff.

## Closure evidence

The production upgrade used Alembic revision `20260830_01` after creating a
SQLite-consistent backup at:

```text
archives/migrations/v5.3.2/T26-GENERATION-RESULT-BINDING-20260830T111006Z/
```

The backup SHA-256 is:

```text
f5e02c759c07ee19952b53285083903ccd20dc5c387b8886571ffd38d2e16eef
```

The production post-upgrade checks passed for WAL, foreign keys, busy
timeout, integrity, foreign-key violations, unchanged business row counts,
and NULL backfill of all existing Artifacts. The migration manifest in that
directory is the evidence record; it is not Runtime authority.
