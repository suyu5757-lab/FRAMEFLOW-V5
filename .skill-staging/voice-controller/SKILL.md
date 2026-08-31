---
name: voice-controller
description: "Orchestrate production audio for AI video: voice, dialogue, music, ambience, sound effects, rights, QA, handoff, and timeline readiness. Route character-performance work to voice-performance-director and music/sound work to music-sound-designer."
---

# Voice Controller

Use this skill as the production-audio router and gatekeeper for an AI-video project. It owns the cross-track contract: stable IDs, provider-neutral briefs, consent and rights gates, technical QA, approved-artifact mapping, and the handoff to the timeline, shot director, or Seedance packager.

## Route first

Classify the request before designing anything:

- Character voice, TTS, voice design, clone, speech-to-speech, dialogue, narration, audition, pronunciation, or take regeneration → `$voice-performance-director`.
- Music cue, score, ambience, foley, sound effect, sound bridge, stems, separation, remix, or music rights → `$music-sound-designer`.
- Cross-track timing, explicit approved-asset selection, QA decision, registration, loudness/delivery, timeline assembly, or a mixed handoff → continue here and use both specialist outputs as inputs.

Do not silently merge specialist output into a production-ready artifact. The controller must preserve the specialist's status, provider, model, source, consent/license evidence, QA decision, and unresolved blockers.

## Workbench contract

FrameFlow's audio workbench is the durable source of intent. Read and write the project audio document through:

- `GET /api/v2/projects/{project_id}/audio-studio`
- `PUT /api/v2/projects/{project_id}/audio-studio` with `expected_revision`
- `POST /api/v2/projects/{project_id}/audio/tts` only after explicit paid-execution confirmation
- `POST /api/v2/projects/{project_id}/asset-intake` for an uploaded file mapped to a logical audio, music, or SFX asset

The document contains `voices`, `dialogues`, `music_cues`, `sound_design`, and `handoff`. Every file is an artifact version attached to a logical asset; a URL alone is not a production-ready result.

Use this state vocabulary consistently:

`planned` → `user-confirmation-required` → `external-execution-pending` or `generated-pending-qa` → `qa_in_progress` → `approved_pending_registration` → `ready`.

`blocked`, `revision_required`, `rejected`, and `superseded` are terminal or corrective states until an explicit new version is created. Never label an unregistered file as ready.

## Controller gates

Before a mixed handoff, check all of the following:

1. Every recurring voice has a stable profile, language/dialect, performance traits, source type, and consent status.
2. Every dialogue task has text, voice ID, shot IDs, emotion/intent, target duration when material, and a selected take or a clearly stated pending status.
3. Every music/sound item has a narrative function, shot coverage, entry/exit behavior, rights status, and provider/external-execution hint.
4. Every selected artifact has technical validation, a QA owner, a QA decision, source hash/path, and registration status.
5. `handoff.approved_asset_ids` is explicit. A provisional handoff never enters an assembled production timeline.
6. The handoff names `@Audio1` dialogue/voice, `@Audio2` music, and `@Audio3` ambience/SFX responsibilities when a downstream packager needs them.

When a gate fails, return the smallest corrective action, the owning specialist, and the exact next status. Do not invent provider output or imply that an unbound capability is available.

## Provider-neutral routing

Treat providers as replaceable execution backends. Keep the brief and the artifact contract stable even when the engine changes. A practical research-informed routing table is in `references/github-engine-routing.md`; it is a capability map, not a license approval.

Potential routes include multilingual TTS and voice performance engines, text/lyrics-to-music engines, source separation, transcription, and FFmpeg/ffprobe. Verify current repository licenses, model licenses, hosting constraints, and commercial eligibility before execution. Model weights and code can have different licenses.

## Safety and confirmation

- A named person's voice, clone reference, or recognizable identity requires consent evidence and scope before execution.
- A style reference can guide rhythm, instrumentation, space, or energy; it must not be turned into a request to reproduce a living artist, recording, melody, lyric, or signature hook.
- Any paid or externally hosted generation requires a clear confirmation immediately before the call. A plan or draft is not confirmation.
- Preserve private references as hashes and metadata where possible; do not echo sensitive source material into prompts or logs.

## QA and handoff

Use `$voice-controller/scripts/validate_audio_package.py` for the package-level schema check. Pair it with artifact technical validation and human listening. The validator is a guardrail, not a substitute for listening or rights review.

For final handoff, return:

- stable IDs and the selected version for each voice, dialogue, cue, ambience, and SFX item;
- artifact IDs, paths/URLs, provider/model, source type, rights/consent evidence, and QA decisions;
- shot timing, handles, clean/dry versus processed versions, stems or separation notes, and unresolved blockers;
- a short downstream instruction for `video-shot-director`, timeline assembly, or `seedance-shot-packager`.

The canonical object shape and timeline mapping rules are in `references/workbench-audio-contract.md`.
