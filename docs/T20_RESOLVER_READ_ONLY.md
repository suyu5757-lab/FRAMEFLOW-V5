# T20 — Resolver Read-only

`core.runtime.resolver.ShotResolver` is a deterministic, non-persistent
projection of one SQLite Runtime snapshot. Its only input is a `shot_id`; its
output is `ResolvedShotContext`, containing the DB Shot identity, parsed and
validated ShotSpec v2.2, ordered character/scene/prop Asset references, their
declared master Artifacts, direct first/last frame Artifacts, and a small typed
issue list.

SQLite is the only authority. Exported T04 manifests are not read and cannot
override current rows. The resolver does not create a cache or resolver state.
It uses ordinary SELECT statements on one connection and performs no INSERT,
UPDATE, DELETE, Task, Event, Generation, ProviderSubmission, ResourceLock,
Asset, Artifact, Shot, or filesystem mutation. It never opens an Artifact path;
the path, hash, version, role, and observed status are returned from the
registered Artifact row.

## Identity and references

The resolver validates that the Shot exists, its Project exists, its Sequence
exists and belongs to that Project, and that `ShotSpec.shot_id` and
`ShotSpec.sequence_id` agree with the DB row. ShotSpec is validated against
`core/schemas/shot_spec_v2.2.schema.json`. Characters and props retain their
input ordering, as does the scene reference. Each Asset must belong to the
Shot's project and resolves only its explicit `master_artifact_id`; there is no
latest-artifact or same-type fallback. The master Artifact must exist, belong
to the same project, match `artifact.asset_id`, and provide path, sha256, and
version metadata.

Non-null `first_frame_artifact_id` and `last_frame_artifact_id` are resolved
directly. A non-null direct frame may have a null `artifact.shot_id` because the
Runtime schema allows a general Artifact, but a different non-null Shot ID is a
conflict. Null direct frame IDs are reported as non-blocking absence; no frame
builder is called.

## Status and readiness

The Runtime MVP schema does not freeze a downstream Asset eligibility enum.
T20 therefore returns Asset and Artifact statuses exactly as observed and does
not turn status names into an invented replacement policy. RETIRED/unknown
Asset status is an `ASSET_STATUS_OBSERVED` non-blocking issue. ARCHIVED Artifact
status is an `ARTIFACT_ARCHIVED` non-blocking issue. The resolver never selects
an active replacement. `ready` means only that the requested references and
identity/metadata relationships have no blocking T20 issue; it is not QA,
Package, Provider, or delivery readiness.

Missing rows, cross-project references, asset/master mismatches, direct-frame
conflicts, invalid ShotSpec, and DB identity conflicts return `ready: false`
with stable typed issues. Missing content is reported, never generated.
Duplicate references are retained in the original list order and reported;
they are not silently deduplicated.

T23 may consume `ResolvedShotContext` for Canonical Prompt work. Prompt
generation, package construction, provider submission, ComfyUI, creative-app
actions, Workbench state changes, migration, and production writes are outside
T20.
