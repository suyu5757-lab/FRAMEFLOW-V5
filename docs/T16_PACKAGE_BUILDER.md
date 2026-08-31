# FRAMEFLOW V5.3.2 — T16 Package Builder

## Purpose

T16 creates the provider-neutral, deterministic Shot Package consumed by a
Generation and subsequently read by T26.  A package is an `artifacts` row with
`role = package_manifest`; it is not a Package table or a second Runtime
authority.

## Input contract

`PackageBuilder.prepare(context, canonical_prompt)` accepts exactly T20's
ready `ResolvedShotContext` and T23's `CanonicalPrompt`.  It verifies the
Project/Shot relationship, prompt SHA-256, the exact T23 source Artifact order,
registered Artifact ownership, Asset/Shot binding, approved file path, file
presence, and file SHA-256.

The preserved reference order is:

```text
characters → scene → props → first frame → last frame
```

No asset or prompt is resolved or generated again.

## Output contract

The Artifact-backed JSON has this minimal stable shape:

```text
manifest_type = FRAMEFLOW_V5_SHOT_PACKAGE
package_manifest_version
project_id / shot_id / sequence_id
shot_spec
canonical_prompt { shot_id, shot_spec_version, text, sha256 }
references[] { reference_type, artifact_id, role, type, path, sha256,
               version, asset_id, shot_id }
source_artifact_ids
package_version
logical_sha256
```

`source_artifact_ids` contains only actual registered Artifact IDs, in the
same canonical reference order.  The registered output Artifact is:

```text
type = json
role = package_manifest
status = READY
generation_id = NULL
source_task_id = T16 build Task ID
```

Its canonical path is:

```text
projects/<project_id>/shots/<shot_id>/packages/pkg-<logical-prefix>.json
```

## Identity and version semantics

Logical identity is SHA-256 over canonical JSON of the immutable input: Shot
identity/spec, canonical prompt, and ordered reference Artifact identities and
integrity metadata.  The deterministic values are:

```text
package_version = pkg-<first 24 logical SHA-256 chars>
artifact_id     = PKG_<first 48 logical SHA-256 chars>
```

Therefore identical inputs return the same Task/Artifact and do not create a
duplicate side effect.  A meaningful input change produces a new Artifact and
new path; existing package files are never overwritten.

## Runtime and atomicity

`prepare()` is read-only.  `build()` only creates/enqueues `BUILD_SHOT_PACKAGE`;
the trusted Worker handler writes the file and registers the Artifact.

```text
temporary exclusive file → flush/fsync → byte verification
→ collision re-check → atomic replace → output SHA-256
→ Artifact registration
```

Any write/finalize/registration failure removes the temporary output, removes
the new final output when created, and attempts to remove only directories
created by that request.  It never overwrites a collision.  Retrying the same
failed Task produces one valid final Artifact.

References must resolve inside the controlled projects root or the existing
read-only historical/control roots (`D:\AIGC\SUYU`, `D:\ComfyUI`); symlink and
escape paths fail closed.  Package output is always under the writable Shot
packages directory.

## T26 integration

T16 does not modify T26.  The resulting Artifact ID is directly suitable for
`generations.package_manifest_artifact_id`; T26 then reads its registered
version and path without creating package files or directories.

## Non-goals

No Generation is created by T16.  It does not submit a Provider request, call
the network, create Review/QA state, regenerate prompts/assets, alter Shot
state, or implement T48/Seedance/ComfyUI work.

## Test evidence

`tests/runtime/test_t16_package_builder.py` covers happy path, preparation
purity, deterministic duplicate requests, changed-input versioning, missing
rows/files, hash mismatch, path escape, cross-project/cross-shot rejection,
destination collision, writer/fsync/finalize failures, DB-registration
compensation and retry, and real T26 consumption.
