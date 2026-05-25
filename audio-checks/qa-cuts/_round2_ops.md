# Round 2 Changelog

Date: 2026-05-19T22:33:42.797584
Input: audio-checks\qa-cuts\proposed-cut-list.json  (42 cuts)
Output: audio-checks\qa-cuts\proposed-cut-list-round2.json  (30 cuts, 91.32s total)

## Operations applied

- `8.46-9.48` **KEEP** — confirmed clean by Codex
- `57.62-78.17` **KEEP** — confirmed clean by Codex
- `161.60-161.96` **KEEP** — confirmed clean by Codex
- `172.75-173.05` **REMOVE_VERIFIED** — waveform shows SPEECH_LIKE peak (-16 to -19 dBFS) — likely game audio or word fragment; not a clean artifact cut
- `258.57-259.05` **REMOVE_VERIFIED** — waveform shows SPEECH_LIKE peak (-16 to -19 dBFS) — likely game audio or word fragment; not a clean artifact cut
- `348.60-349.80` **MODIFY** — -> 349.36-349.44
- `469.00-472.12` **MODIFY** — -> 467.98-470.12
- `487.20-488.12` **MODIFY** — -> 485.68-488.12
- `504.44-505.20` **MODIFY** — -> 504.44-504.52
- `521.30-524.50` **MODIFY** — -> 522.24-523.2
- `556.00-556.28` **REMOVE_VERIFIED** — waveform shows SPEECH_LIKE peak (-16 to -19 dBFS) — likely game audio or word fragment; not a clean artifact cut
- `599.73-600.42` **REMOVE_VERIFIED** — waveform shows SPEECH_LIKE peak (-16 to -19 dBFS) — likely game audio or word fragment; not a clean artifact cut
- `634.00-634.82` **KEEP_VERIFIED** — waveform BORDERLINE/LOW_ENERGY — quiet, no speech (peak < -20 dBFS, speech_frac=0%); safe artifact cut
- `640.00-641.60` **MODIFY** — -> 640.88-641.2
- `673.80-677.20` **MODIFY** — -> 674.16-676.26
- `721.12-722.80` **REMOVE** — Removed per Codex review: this 1.68s pause after 'we once again miss' is a genuine battle reaction beat, not an artifact. LOW confidence + dramatic context = should be editor-discretion KEEP, not an automatic cut.
- `810.48-810.97` **REMOVE** — Removed per Codex review: transcript risk — seg 110 reads 'generation now there's no xp...' and Whisper word timestamps put the cut range inside 'now'/'there's'. Without waveform verification proving an isolated non-speech artifact, the cut risks clipping real words. Defaulting to REMOVE.
- `945.34-945.40` **KEEP** — confirmed clean by Codex
- `974.58-974.64` **KEEP** — confirmed clean by Codex
- `1001.32-1002.72` **KEEP** — confirmed clean by Codex
- `1089.00-1094.28` **KEEP** — confirmed clean by Codex
- `1184.56-1187.36` **KEEP** — confirmed clean by Codex
- `1215.88-1215.94` **KEEP** — confirmed clean by Codex
- `1245.14-1247.94` **KEEP** — confirmed clean by Codex
- `1273.98-1276.78` **KEEP** — confirmed clean by Codex
- `1352.42-1352.58` **KEEP** — confirmed clean by Codex
- `1603.90-1604.20` **REMOVE** — Removed per Codex review: the duplicate 'we' has zero-duration transcript timestamp and the current cut likely removes 'can', producing 'now we tackle' instead of 'now we can tackle'. Without waveform-verified tighter boundary, REMOVE.
- `1627.24-1628.60` **REMOVE** — Removed per Codex review: 'This time, no poison' is genuine play-by-play that explains the next action in the poison-repetition sequence. Not an artifact.
- `1744.88-1745.60` **REMOVE** — Removed per Codex review: 'I go tackle' is genuine rapid battle narration, even though Brock only has Tackle available. Removing the narration beat hurts clarity, not pacing.
- `1747.34-1747.88` **REMOVE** — Removed per Codex review: 'Very nice' is a genuine reaction to a meaningful Fury Cutter miss. Real reaction beat, not an artifact.
- `1778.85-1779.28` **REMOVE_VERIFIED** — waveform shows SPEECH_LIKE peak (-16 to -19 dBFS) — likely game audio or word fragment; not a clean artifact cut
- `1962.77-1967.65` **KEEP** — confirmed clean by Codex
- `2064.72-2065.13` **KEEP** — confirmed clean by Codex
- `2273.38-2274.78` **KEEP** — confirmed clean by Codex
- `2325.30-2325.78` **KEEP_VERIFIED** — waveform BORDERLINE/LOW_ENERGY — quiet, no speech (peak < -20 dBFS, speech_frac=0%); safe artifact cut
- `2440.50-2441.15` **MODIFY** — -> 2440.7-2441.78
- `2692.58-2692.92` **REMOVE_VERIFIED** — waveform shows SPEECH_LIKE peak (-16 to -19 dBFS) — likely game audio or word fragment; not a clean artifact cut
- `2700.12-2702.40` **KEEP** — confirmed clean by Codex
- `2713.40-2716.92` **MODIFY** — -> 2713.4-2717.9
- `2722.73-2725.67` **MODIFY** — -> 2722.86-2725.64
- `2724.84-2725.64` **REMOVE** — Removed per Codex review item #16 (overlap conflict): this new mid-clip cut is redundant after the modified cut 2722.86-2725.64 above. Final JSON must not contain overlapping ranges.
- `2824.66-2825.08` **KEEP** — confirmed clean by Codex
- `1989.96-2016.76` **ADD_NEW** — Investigation cut (1989.96-2016.76): waveform verified 98% silent (<-45dBFS), peak -39.2 dBFS - 26.8s of dead air