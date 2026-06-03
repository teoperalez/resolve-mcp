---
name: Brock/Misty cut-review lessons
description: Reusable challenge-editing knowledge preserved after retiring tracked audio-checks artifacts
type: reference
originSessionId: local-copilot-2026-06-02
---

The old tracked `audio-checks/` tree was a case-specific scratch archive for
Brock Red and Misty Red. Do not restore it for future work. Preserve the lessons
and use maintained scripts plus project-local `CODEx/` outputs instead.

Durable rules:

- Use loose-source transcription for cut QA: `condition_on_previous_text=False`,
  `no_repeat_ngram_size=0`, `vad_filter=False`; default Whisper can hide repeats
  and false starts.
- Always do a whole-script critical read after automated repetition/splice scans.
  Misty only converged after this step.
- Brock opener regression: remove the first "This is Brock. Brock likes rocks."
  take with source cut `57.62-78.17`; preserve the clean restart at `78.18`.
- Final-render QA is mandatory after 4K export. Map render time back to source
  time through cut replay metadata before patching the source-time cut list.
- Waveform thresholds from Brock: `< -45 dBFS` silent, `< -30 dBFS` low-energy,
  `< -20 dBFS` borderline/manual, `>= -20 dBFS` speech-like, avoid auto-cut.
- Treat `WORDS_IN_CLIP(0)` as a candidate only. Brock showed some micro-cuts
  with no words still had speech-like waveform peaks.
- Do not split atomic numbered references such as `Rival 2`, `attempt number
  one`, `reset 29`, `second gym leader`, or `level 14 Onix`.
- Normalize Pokemon/trainer homophones before final text review; normalizer
  issues can disguise broken cuts.

Longer docs: `docs/brock_misty_cut_lessons.md`.