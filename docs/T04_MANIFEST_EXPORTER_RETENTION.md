# T04 — Manifest Exporter + Artifact Retention v2

## Contract

T04 adds two explicitly callable, non-startup services:

- `core.runtime.manifest.ManifestExporter` produces a deterministic
  `FRAMEFLOW_V5_PROJECT_MANIFEST` JSON projection.
- `core.runtime.retention.RetentionService` produces a dry-run plan and can
  apply a reviewed plan by moving files to the archive and updating only the
  affected `artifacts` rows.

SQLite WAL remains the Runtime source of truth. The manifest is an export and
inspection record, not an import source. The exporter includes the authoritative
project, sequence, shot, asset, artifact, generation, and review records. It
does not dump task payloads, task errors, event payloads, provider request data,
resource-lock state, or secrets. JSON columns retain their database column name
and are serialized as parsed JSON when valid.

Artifact provenance includes nullable `generation_id`. The exporter projects
this field exactly as stored: package/input/reference Artifacts remain NULL,
while a Generation result Artifact points to its owning Generation. SQLite is
still authoritative; exporting this relation does not create an import path
or permit Manifest data to override Runtime state.

The final JSON file is written with canonical serialization from
`frameflow.idempotency.canonical_json`, followed by flush, `fsync`, and
`os.replace`. A write failure leaves the previous final file byte-identical;
when there was no previous final, no final file is created.

## Storage and retention

The actual V5 storage root is `data/projects/<project_id>`. The default archive
root is the repository `archives/`; the managed namespace is
`archives/<project_id>/<shot_id>/<generation_id>/`. The pre-existing
`archives/migrations/` namespace is excluded from T04 size accounting and is
not inspected or rearranged by Apply.

The default policy keeps the two newest generations per shot, ordered by
`created_at` with the generation ID used only as a deterministic tie breaker.
Approved generations are determined by the latest canonical `reviews` decision
(`APPROVED` or `QA_APPROVED`); conflicting latest decisions and approved
generation statuses without a review fail closed. A generation containing a
locked asset's `master_artifact_id` is protected. Multiple files discovered in
the same `generations/<generation_id>/` directory form one retention unit.

T04 archives rather than deletes. It never purges archive content. Every
source path must resolve under its project root and outside the archive,
`D:\AIGC\SUYU`, and `D:\ComfyUI`; symlink/path escape and destination collision
are rejected. Apply moves and verifies every file in a unit, then updates all
Artifact paths and statuses (`ARCHIVED`) in one SQLite transaction. A move,
verification, or database failure compensates already-moved files. If
compensation cannot restore every source, the result is
`RETENTION_COMPENSATION_FAILED` and no further units are processed.

## Archive size

The approved V5.3.2 T04 Closure decision freezes
`max_archive_size_gb = 100` in `config/runtime-retention.json`. It is a
warning-only threshold, not a filesystem quota or an automatic purge,
deletion, or rotation trigger. The warning condition is inclusive:
`current_archive_size_bytes + candidate_size_bytes >= 100 * 1024**3` emits
`ARCHIVE_SIZE_THRESHOLD_EXCEEDED` with current, candidate, projected, and
threshold byte values. The calculation only counts the managed
`archives/<project_id>/<shot_id>/<generation_id>/` namespace and excludes
`archives/migrations/`.

The service reads this formal config when no test policy is injected. Missing,
malformed, non-finite, zero, and negative values fail explicitly; there is no
silent fallback. Crossing the warning never changes keep-last, approved, or
locked-master protection and never deletes any archive or Legacy evidence.
