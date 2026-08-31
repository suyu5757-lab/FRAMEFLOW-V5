---
name: voice-performance-director
description: Design, audition, generate, and QA AI-video character voices, narration, dialogue, clones, and speech-to-speech performances under consent and continuity gates.
---

# Voice Performance Director

Use this skill for character voice identity and performance. Return a structured package to `$voice-controller`; do not make a mixed soundtrack or silently mark an audio file as approved.

## Start with the voice brief

For each recurring character or narrator, define:

- stable voice ID and character/narrator role;
- language, dialect, pronunciation risks, register, age range, pitch/energy, breath/noise profile, and performance traits;
- source type: `design`, `preset`, `clone`, or `speech-to-speech`;
- consent status, evidence reference/hash, allowed use, geography, term, and provider eligibility when identity is reproduced;
- neutral, emotional, and pronunciation-stress audition lines.

Use non-identifying Voice Design when the brief is about a feeling or archetype. A named person's voice is a separate high-risk path and cannot proceed from a vague verbal resemblance.

## Dialogue task contract

Every task needs `DLG###` or `NAR###`, text, voice ID, shot IDs, emotion/intent, target duration when timing matters, operation, and status. Keep text, performance direction, provider settings, and selected take separate so a new audition never replaces an approved take.

Recommended progression:

1. Build or import the profile and confirm consent/scope.
2. Generate three short auditions with the same sentence and different pressure conditions.
3. Choose a continuity anchor: timbre, consonant behavior, breath spacing, pitch range, and emotional ceiling.
4. Generate scene-specific takes with pronunciation notes and shot timing.
5. Listen for identity continuity, language/dialect, text accuracy, emotion, rhythm, target duration, noise, clipping, edit handles, and rights.
6. Create a new version for every revision; select only a QA-approved take.

## Engine routing

Use the provider binding exposed by FrameFlow when it is ready. When it is not, keep the task `external-execution-pending` and export a provider-neutral brief. Candidate engines include multilingual TTS and few-shot voice systems, but verify current code/model licenses and commercial terms before execution.

Paid or external execution always requires immediate user confirmation. Never use a reference recording for cloning unless consent and scope are recorded. Never claim that a voice is the same person because a model produced a similar sample.

## QA return package

Return the voice profile, audition decisions, dialogue tasks, take IDs, artifact IDs/paths, provider/model, technical metadata, QA decision, and unresolved issues. A take is ready for the controller only when it has a stable artifact, a QA decision, and an explicit mapping to its logical asset.

For package validation, run `$voice-controller/scripts/validate_audio_package.py` and then perform human listening. The script checks structure and safety fields; it cannot judge a voice's artistic suitability.
