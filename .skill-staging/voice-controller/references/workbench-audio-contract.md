# FrameFlow audio workbench contract

## Durable document

The project document stores one audio object:

```json
{
  "version": 1,
  "selected_mode": "overview",
  "voices": [],
  "dialogues": [],
  "music_cues": [],
  "sound_design": [],
  "handoff": {
    "status": "provisional",
    "approved_asset_ids": [],
    "notes": ""
  }
}
```

IDs are durable intent IDs (`V001`, `DLG001`, `CUE001`, `SND001`). Media files use artifact IDs and are never identified only by a filename or URL.

## Logical asset versus artifact

Use a logical asset for the editorial identity (`AUD001`, `MUS001`, `SFX001`) and create a new artifact version for every import, render, take, or rebuild. An artifact is eligible for timeline assembly only when its server-side status is `ready`, it has a local path, and the handoff explicitly includes its logical asset ID.

The browser may propose a mapping, but the server remains authoritative for state transitions, QA, registration, and active versions.

## Timing rules

- Dialogue is placed at the first referenced shot start unless the specialist supplies an explicit timecode.
- Music, ambience, and SFX preserve their cue duration; if a duration is intentionally omitted, the controller must call that out rather than guessing silently.
- Music and ambience receive short fades by default; dialogue stays dry and un-faded unless the take brief says otherwise.
- Shot references are semantic anchors, not proof that a file is approved.

## Handoff tokens

Use `@Audio1` for dialogue/voice performance, `@Audio2` for music cues, and `@Audio3` for ambience or key SFX. Each token must point to a selected, QA'd artifact or remain explicitly provisional.

## API expectations

Use optimistic revision checks when saving the audio document. Use asset intake for local files and the dedicated TTS endpoint only after execution confirmation. After either action, refresh the project snapshot and asset library before presenting the next gate.
