---
name: music-sound-designer
description: Design and QA AI-video music cues, ambience, foley, sound effects, sound bridges, stems, separation, and rights-aware provider handoffs.
---

# Music and Sound Designer

Use this skill for non-dialogue sound. Return editorial cues and production-ready candidates to `$voice-controller`; do not infer that a musical file is cleared, final-mixed, or ready for the timeline just because it plays.

## Cue before engine

For every music or sound item, define a stable ID, shot coverage, narrative function, entry, development, exit, duration, dialogue-avoidance behavior, texture, rights status, and execution status. Separate “what the sound must do” from “what provider or model may execute it.”

Music cues should answer:

- What changes in the story if this cue is absent?
- Where does it enter, develop, thin out, transition, or exit?
- Which frequencies and transients must leave space for dialogue?
- Is the reference used for rhythm, instrumentation, harmony, density, space, or edit behavior only?
- Does the result need a loop, clean tail, handles, stems, or alternate intensity versions?

Sound design should distinguish ambience, foley, SFX, and transition bridges. Record perspective, sync anchor, decay, layer priority, and whether the source is generated, owned, licensed, or unknown.

## Provider routing

Use a bound music capability when available and request confirmation immediately before paid execution. Otherwise create an `external-execution-pending` package. Research-informed candidates include ACE-Step for text/lyrics and iterative music workflows, MusicGen/AudioCraft or Stable Audio Tools for generative audio, Demucs or related source-separation workflows for stems, Whisper for timing/transcript aids, and FFmpeg/ffprobe for inspection and conversion. Confirm current licenses and model terms before use; code and weights may differ.

Do not request a living artist's recognizable style, a recording's melody/lyrics/signature hook, or an unlicensed master. Turn a reference into a limited functional brief instead.

## QA

Check narrative timing, dialogue masking, edit usability, loop/transition behavior, continuity, channel layout, sample rate, clipping, noise, phase, head/tail, stems, metadata, rights, and source hash. Listen in context with dialogue before approval. Source separation is a candidate transformation, not proof of a clean stem.

Only a QA-approved, registered, explicit handoff asset can enter the assembled timeline. Keep provisional candidates visible and state the exact next action.

## Return package

Return stable cue/item IDs, shot references, provider/model or external handoff, artifact IDs and versions, technical metadata, rights evidence, QA decision, and `@Audio2` / `@Audio3` mapping notes for downstream use.
