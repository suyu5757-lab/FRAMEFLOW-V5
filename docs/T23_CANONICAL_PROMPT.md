# T23 — Provider-agnostic Canonical Prompt

## Contract source

No independent FINAL Canonical Prompt Compiler or schema existed in the
repository at T23 inspection time. The `video-shot-director` Skill's output
contract is a downstream director/generation handoff and contains provider
handoff fields, so it is not used as the canonical semantic contract.

T23 therefore uses the compatible inherited V5.3 Canonical Prompt contract:

```text
SUBJECT
ACTION
PERFORMANCE
ENVIRONMENT
CAMERA
LIGHTING
TIMING
CONTINUITY
AUDIO
CONSTRAINTS
```

This source is recorded as `inherited compatible V5.3 Canonical Prompt
contract`; it is not claimed to be a new field-by-field FINAL plan definition.

## Input and output

`CanonicalPromptCompiler.compile()` accepts only T20's
`ResolvedShotContext`. It returns `PromptCompileResult`; a not-ready T20
context returns `success=false` and no production prompt. A successful result
contains the fixed-order ten sections, deterministic `canonical_text`, the
ShotSpec version (`2.2`), ordered `source_artifact_ids`, warnings, and a pure
SHA-256 of the text. No output is persisted.

Empty optional values render as `NONE`, so section presence and line order do
not drift. Newlines are normalized to LF and non-dialogue outer whitespace is
canonicalized. Dialogue is preserved as literal text, without translation or
rewriting. Input order is preserved for characters, props, `must_keep`, and
`must_avoid`.

## Field mapping

- `SUBJECT`: resolved character/scene/prop Asset identity, type, status, and
  version. No appearance, wardrobe, age, or other metadata is invented.
- `ACTION`: `subject_action`, `start_state`, and `end_state`.
- `PERFORMANCE`: `expression` and `performance_intent` only.
- `ENVIRONMENT`: resolved scene identity plus `weather`, `time_of_day`, and
  `visual_style`.
- `CAMERA`: the six ShotSpec camera fields without provider camera parameters.
- `LIGHTING`: explicit `lighting` and `visual_style` only.
- `TIMING`: exact `duration_sec`.
- `CONTINUITY`: supplied continuity/state fields and PRESENT/ABSENT first/last
  frame semantics; no continuity decision engine is introduced.
- `AUDIO`: exact `dialogue` and explicit `audio_cues` only.
- `CONSTRAINTS`: ordered `must_keep` and `must_avoid` semantic constraints.

Artifact IDs are structured provenance. Artifact paths and SHA-256 values do
not enter natural-language `canonical_text`. T20-resolved character, scene,
prop masters, first frame, and last frame are included in deterministic source
artifact order. Optional `motion_reference_artifact_id` and `reference_assets`
are not re-resolved by T23 when T20 has not exposed them; T23 returns a
non-blocking warning instead of guessing.

`provider_preferences`, `quality_priority`, and `cost_priority` are not
compiled into semantic text. No Seedance/Runway/Kling/Veo syntax, model name,
API endpoint, provider limit, negative-prompt format, cost, or task ID is
introduced. Provider adapters and package construction are later boundaries.

## Safety and boundaries

The compiler is a pure deterministic composition step. It makes no external
LLM/API call, executes no ShotSpec text, creates no Task/Event/Artifact/
Generation, changes no Runtime row, reads no Manifest, opens no Artifact path,
and writes no prompt/package file. Prompt injection-like text is treated as
literal production content.

T26 Manual Adapter and T16 Package Builder remain outside T23. T23 produces an
in-memory semantic prompt only; it does not create provider prompts or package
files.
