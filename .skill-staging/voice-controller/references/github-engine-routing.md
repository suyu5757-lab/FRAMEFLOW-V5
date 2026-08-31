# Research-informed engine routing

This matrix is a starting point for capability matching. It is not a recommendation to run a model without checking the current repository license, model-weight license, hardware needs, privacy posture, or commercial eligibility.

| Need | Candidate capability | Operational role | Required gate |
| --- | --- | --- | --- |
| Multilingual TTS, zero-shot or cross-lingual voice performance | [CosyVoice](https://github.com/FunAudioLLM/CosyVoice), [Fish Speech](https://github.com/fishaudio/fish-speech), [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS), [F5-TTS](https://github.com/SWivid/F5-TTS) | Generate audition and dialogue candidates | consent/identity, pronunciation QA, provider confirmation |
| Text/lyrics-to-music and iterative music edits | [ACE-Step](https://github.com/ace-step/ACE-Step), [MusicGen/AudioCraft](https://github.com/facebookresearch/audiocraft), [Stable Audio Tools](https://github.com/Stability-AI/stable-audio-tools) | Produce cue candidates, remix/repaint, or score sketches | rights/style boundary, dialogue masking, music QA |
| Stems and source separation | [Demucs](https://github.com/facebookresearch/demucs), [Music-Source-Separation-Training](https://github.com/ZFTurbo/Music-Source-Separation-Training) | Separate vocals, music, ambience, or remix inputs | source rights, phase/artifact check, human listening |
| Transcription and timing reference | [Whisper](https://github.com/openai/whisper) | Generate transcript, VTT/SRT/word timing aids | language accuracy, speaker and timing review |
| Conversion, analysis, fades, muxing, delivery | [FFmpeg](https://github.com/FFmpeg/FFmpeg) | Inspect and render technical deliverables | codec/sample rate/channel/loudness check |

Keep `provider_hint` and `provider_model` separate from the editorial brief. A provider failure should produce a reroutable candidate, not a rewritten creative intent.
