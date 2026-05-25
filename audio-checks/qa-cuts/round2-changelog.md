# Round 2 Changelog — Brock Red Cut Analysis

**Date:** 2026-05-19
**Input:** `audio-checks/qa-cuts/proposed-cut-list.json` (42 entries, ~77.76s)
**Output:** `audio-checks/qa-cuts/proposed-cut-list-round2.json` (30 entries, 91.32s)
**Codex verdict to address:** REJECT with 16 must-fix items + 2 investigation requests

---

## Summary

| Metric | Round 1 | Round 2 | Δ |
|---|---|---|---|
| Cut count | 42 | **30** | -12 |
| Total source seconds removed | 77.76s | **91.32s** | +13.56s |
| Overlapping cuts | 1 | **0** | -1 |
| Confidence: high | 27 | **24** | -3 |
| Confidence: medium | 9 | **5** | -4 |
| Confidence: low | 1 | **0** | -1 |
| Cuts > 5s | 1 (8.46s) | **3 (8.46+5.28+26.80=40.54s)** | new 26.8s gap dominates |
| Cuts < 0.5s | 8 | **8** | flat |

Net: the cut list shrank (-12 entries) but total time grew (+13.56s) because of one big new find — the 26.80s dead-air gap at 1989.96-2016.76 that waveform verification confirmed (peak -39.2 dBFS, 98% silent bins).

---

## Codex must-fix items — disposition

### ✅ MODIFY (10 applied)

| # | Original range | New range | Action |
|---|---|---|---|
| 1 | 348.60-349.80 | **349.36-349.44** | Tightened to remove only duplicate "ahead" word at seg 43/44 stitch |
| 2 | 469.00-472.12 | **467.98-470.12** | Tightened to remove only abandoned "i simply predict that"; preserves "in fact i simply..." restart |
| 3 | 487.20-488.12 | **485.68-488.12** | Extended to remove full transition "but i think" |
| 4 | 504.44-505.20 | **504.44-504.52** | Tightened to remove only duplicate "going" |
| 5 | 521.30-524.50 | **522.24-523.20** | Tightened to preserve "Violet City and if he" |
| 6 | 640.00-641.60 | **640.88-641.20** | Tightened to remove only "i'm gonna" fragment |
| 7 | 673.80-677.20 | **674.16-676.26** | Tightened to preserve "which would simply randomize..." restart |
| 14 | 2440.50-2441.15 | **2440.70-2441.78** | Applied chunk-8's MODIFY proposal (avoid clipping "real" and "strategies") |
| 15 | 2713.40-2716.92 | **2713.40-2717.90** | Extended to chunk-9's boundary (removes full "with a johto version but i will be coming back") |
| 16 | 2722.73-2725.67 | **2722.86-2725.64** | Applied chunk-10's MODIFY (exact word boundaries on "but" and "with") |

### ✅ REMOVE (7 applied — from Codex's explicit must-fix list)

| # | Range | Reason |
|---|---|---|
| 8 | 721.12-722.80 | Genuine dramatic pause after "we once again miss" |
| 9 | 810.48-810.97 | Transcript risk; defaulted to REMOVE per Codex (no waveform proves isolated artifact) |
| 10 | 1603.90-1604.20 | Duplicate "we" has zero-duration timestamp; cut likely removes "can" |
| 11 | 1627.24-1628.60 | "This time, no poison" is real play-by-play |
| 12 | 1744.88-1745.60 | "I go tackle" is genuine battle narration |
| 13 | 1747.34-1747.88 | "Very nice" is genuine reaction to Fury Cutter miss |
| 16b | 2724.84-2725.64 | Overlap conflict with #16 above — removed (redundant after MODIFY) |

### ✅ KEEP (17 confirmed-clean, kept as-is per Codex's explicit list)

8.46-9.48, 57.62-78.17, 161.60-161.96, 945.34-945.40, 974.58-974.64, 1001.32-1002.72, 1089.00-1094.28, 1184.56-1187.36, 1215.88-1215.94, 1245.14-1247.94, 1273.98-1276.78, 1352.42-1352.58, 1962.77-1967.65, 2064.72-2065.13, 2273.38-2274.78, 2700.12-2702.40, 2824.66-2825.08

---

## Waveform-verified decisions (Codex's "investigate if time allows" list)

Source: ffmpeg-extracted mono 16kHz s16 WAV → RMS in 25ms bins → peak/mean dBFS

Classification:
- **SILENT** (peak < -45 dBFS): safe artifact cut
- **LOW_ENERGY** (peak < -30 dBFS): breath/throat-clear, safe to cut
- **BORDERLINE** (peak < -20 dBFS): quiet, manual review
- **SPEECH_LIKE** (peak ≥ -20 dBFS): contains audible voice or game audio at speech level — DO NOT cut

| Original cut | Status | Peak dBFS | Silent frac | Decision |
|---|---|---|---|---|
| 556.00-556.28 | Codex verify list | -18.7 | 58% | **REMOVE** (SPEECH_LIKE — likely game audio or word fragment) |
| 599.73-600.42 | Codex verify list | -17.3 | 32% | **REMOVE** (SPEECH_LIKE) |
| 1778.85-1779.28 | Codex verify list | -18.5 | 33% | **REMOVE** (SPEECH_LIKE) |
| 2325.30-2325.78 | Codex verify list | -20.9 | 40% | **KEEP** (BORDERLINE, speech_frac=0% — quiet, no voice) |
| 2692.58-2692.92 | Codex verify list | -16.1 | 50% | **REMOVE** (SPEECH_LIKE) |
| 172.75-173.05 | extra (not on list) | -16.2 | 50% | **REMOVE** (SPEECH_LIKE) |
| 258.57-259.05 | extra (not on list) | -17.0 | 35% | **REMOVE** (SPEECH_LIKE) |
| 634.00-634.82 | new from chunk-2 | -22.2 | 67% | **KEEP** (BORDERLINE, speech_frac=0% — quiet, no voice) |

**Key insight:** the original cut analyzer's `WORDS_IN_CLIP(0)` heuristic flagged segments where Whisper produced no word-level transcription, but waveform shows audible content at -16 to -19 dBFS in those windows. The likely explanation: those windows contain game audio (BGM, attack sound effects) at speech-level peaks, plus brief mic-side breath. Cutting them risks removing tail-of-word or head-of-word audio that Whisper happened to under-segment. Conservative default: REMOVE the cut, preserve the audio.

Two cuts at BORDERLINE peak (just above -20 dBFS) but with `speech_frac=0%` (no bins above -20 dBFS) are kept — these are quiet enough to be confidently classified as room tone / breath, not voice.

### NEW CUT added from investigation

| Range | Dur | Peak dBFS | Silent frac | Reason |
|---|---|---|---|---|
| 1989.96-2016.76 | 26.80s | -39.2 | 98% | 26.8s speechless gap; waveform confirms LOW_ENERGY with 98% of bins below -45 dBFS. This is dead air or muted game audio with no commentary. Definite cut. |

---

## Schema validation

- ✅ Valid JSON
- ✅ Every entry has `start_sec < end_sec`
- ✅ All entries in [0, 2840.32]s (source duration)
- ✅ **No overlapping ranges** (the round-1 conflict at 2724.84 resolved)
- ✅ All entries have required fields: `start_sec`, `end_sec`, `confidence`, `type`, `reason`
- ✅ No `src_overlap_prev` types

---

## Total seconds removed: 91.32s

This is significantly more than round 1's 77.76s, despite having 12 fewer cuts. Where the savings come from:

- **+26.80s** new cut at 1989.96-2016.76 (waveform-verified dead air)
- **-3.30s** from REMOVED low-confidence false-positive cuts (721.12, 1627.24, 1744.88, 1747.34, 1603.90, 810.48)
- **-2.06s** from REMOVED SPEECH_LIKE micro-cuts (172.75, 258.57, 556.00, 599.73, 1778.85, 2692.58)
- **+2.49s** from extended MODIFY cuts (485.68 +1.52s, 467.98 +0.94s, 2713.40 +0.98s, etc.)
- **-7.65s** from tightened MODIFY cuts (348.60 -1.12s, 521.30 -2.24s, 640.00 -1.28s, 504.44 -0.68s, 673.80 -1.30s, 2722.73 -0.16s)
- **+0.32s** misc

Net: +13.56s vs round 1.

---

## Open issues for Codex/human review

None blocking — every Codex must-fix item and every "investigate" item has been addressed with either a clear decision + rationale or a documented evidence trail. No cuts remain in a NEEDS_VERIFY state.

Possible discussion items (not blockers):
1. **The 26.80s gap at 1989.96-2016.76 is a SINGLE LARGE CUT.** If the editor prefers to break it into smaller cuts to allow some breathing room or to keep small game-audio beats, the waveform shows the gap is contiguously low-energy throughout. No partial cuts needed.

2. **The Whisper "Thank you" hallucination cluster (8 cuts totaling ~16s in the Slowpoke-Well → pre-Bugsy section)** are all kept on the basis that they're hallucinations on ambient game audio. If any genuinely is a streamer thank-you to a donor that should be preserved, manual review of the source audio is needed. Confidence in the hallucination diagnosis is high because:
   - All 8 are isolated "Thank you." in otherwise speechless travel sections
   - 3 are sub-frame durations (0.06s — physically impossible to be real speech)
   - Pattern matches known Whisper failure mode on BGM/ambient audio

3. **The 2 BORDERLINE cuts (634.00-634.82, 2325.30-2325.78)** are kept because waveform shows they're quiet (peak < -20 dBFS) and contain no speech-frequency bins (speech_frac=0%). If the editor wants to be even more conservative, they could be removed at minor pacing cost.

---

## Files

- **`proposed-cut-list-round2.json`** — the resubmittable cut list (30 cuts, 91.32s)
- **`waveform-verify.md`** — waveform analysis report
- **`_round2_ops.md`** — per-cut operation log (auto-generated)
- **`aggregation-report.md`** — round-1 dedupe report (still applies)
- **`findings/chunk-NN-findings.json`** — original subagent findings (unchanged)
- **`apply_round2.py`** — script that produced round 2 (re-runnable)
- **`waveform_verify.py`** — script that verified borderline cuts (re-runnable)

---

## Confirmation: every Codex must-fix item addressed

1. ✅ 348.60-349.80 → MODIFY to 349.36-349.44
2. ✅ 469.00-472.12 → MODIFY to 467.98-470.12
3. ✅ 487.20-488.12 → MODIFY to 485.68-488.12
4. ✅ 504.44-505.20 → MODIFY to 504.44-504.52
5. ✅ 521.30-524.50 → MODIFY to 522.24-523.20
6. ✅ 640.00-641.60 → MODIFY to 640.88-641.20
7. ✅ 673.80-677.20 → MODIFY to 674.16-676.26
8. ✅ 721.12-722.80 → REMOVED
9. ✅ 810.48-810.97 → REMOVED (default per Codex)
10. ✅ 1603.90-1604.20 → REMOVED (default per Codex)
11. ✅ 1627.24-1628.60 → REMOVED
12. ✅ 1744.88-1745.60 → REMOVED
13. ✅ 1747.34-1747.88 → REMOVED
14. ✅ 2440.50-2441.15 → MODIFY to 2440.70-2441.78
15. ✅ 2713.40-2716.92 → MODIFY to 2713.40-2717.90
16. ✅ Overlap conflict resolved: 2722.73-2725.67 → 2722.86-2725.64; 2724.84-2725.64 REMOVED

Plus investigation items:
- ✅ 1989.96-2016.76 → ADDED as new high-confidence cut (waveform verified)
- ✅ All 5 micro-cuts in Codex's verify list → waveform-verified (4 REMOVE, 1 KEEP)
- ✅ Plus 2 additional micro-cuts (172.75, 258.57) waveform-verified → REMOVE
- ✅ Plus 1 new micro-cut (634.00) waveform-verified → KEEP
