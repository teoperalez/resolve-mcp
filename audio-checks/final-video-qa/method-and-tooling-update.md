# Final Render Cut-QA Method — Tools, Settings, and Proposed Claude Skill

Date: 2026-05-22

This document summarizes the method used to QA the rendered Brock Red video for missed repetitions / false starts, generate human-review artifacts, and converge those findings back into Claude's source-cut pipeline.

## Goal

Review a rendered final video for any remaining:

- repeated takes
- false starts
- self-corrections
- Whisper hallucination artifacts
- suspicious long speechless gaps
- cut-boundary risks

Then produce:

- a human-readable transcript
- an HTML transcript with highlighted expected cuts
- short audio previews around each expected cut
- a Claude handoff with confirmed cuts
- a final Codex verdict on the canonical source-cut list

## Primary Inputs

- Rendered video:
  - `E:\Brock Red\Brock Red Blue versus Crystl (cuts_ all) (edit)_FINAL_4K.mp4`
- Final-render QA workspace:
  - `C:\Programming\resolve-mcp\audio-checks\final-video-qa\`
- Source transcript:
  - `C:\Programming\resolve-mcp\transcripts\4.json`
- Canonical source-cut file:
  - `C:\Programming\resolve-mcp\plans\prompts\cut-analysis-4.out.md`
- Round-3 artifacts:
  - `C:\Programming\resolve-mcp\audio-checks\qa-cuts\round3-ngrams.json`
  - `C:\Programming\resolve-mcp\audio-checks\qa-cuts\round3-checks-report.md`
  - `E:\Brock Red\Brock Red Blue versus Crystl_ALTERED_BATTLEGAPS_cuts_replay.json`

## Tools Used

### 1. `ffprobe`

Purpose:

- Confirm the rendered video duration, streams, resolution, frame rate, and audio presence.

Command pattern:

```powershell
ffprobe -v error `
  -show_entries format=duration:stream=codec_type,codec_name,width,height,r_frame_rate `
  -of json `
  "E:\Brock Red\Brock Red Blue versus Crystl (cuts_ all) (edit)_FINAL_4K.mp4"
```

Observed settings/output:

- video: H.264, `3840x2160`, `60/1`
- audio: AAC
- duration: `1725.802667s`

### 2. `ffmpeg` — Final Audio Extraction

Purpose:

- Extract the rendered video audio to a transcription-friendly WAV.

Command:

```powershell
ffmpeg -y `
  -i "E:\Brock Red\Brock Red Blue versus Crystl (cuts_ all) (edit)_FINAL_4K.mp4" `
  -vn `
  -ac 1 `
  -ar 16000 `
  -c:a pcm_s16le `
  C:\Programming\resolve-mcp\audio-checks\final-video-qa\final_audio.wav
```

Parameters:

- `-vn`: drop video
- `-ac 1`: mono
- `-ar 16000`: 16 kHz sample rate
- `-c:a pcm_s16le`: uncompressed 16-bit PCM WAV

Output:

- `audio-checks/final-video-qa/final_audio.wav`

### 3. `faster-whisper`

Purpose:

- Transcribe the final rendered audio with repetition-friendly settings so false starts and repeated phrases are not hidden by default decoder behavior.

Model/settings:

- model: `large-v3-turbo`
- device: `cuda`
- compute type: `float16`
- language: `en`
- `word_timestamps=True`
- `beam_size=5`
- `vad_filter=False`
- `condition_on_previous_text=False`
- `no_repeat_ngram_size=0`

Why these settings:

- `condition_on_previous_text=False` reduces Whisper's tendency to smooth context across restarts.
- `no_repeat_ngram_size=0` prevents repetition suppression from hiding duplicate takes.
- `vad_filter=False` preserves short partials, silences, and artifact-like spans that matter for cut QA.
- `word_timestamps=True` gives candidate boundary evidence, though waveform evidence is preferred for final boundary confidence.

CUDA setup:

- Windows required NVIDIA pip-package DLL paths to be added before `faster_whisper` / CTranslate2 CUDA execution.
- Added helper:
  - `C:\Programming\resolve-mcp\scripts\_cuda_dlls.py`
- Helper function:
  - `register_nvidia_dll_dirs()`
- It registers:
  - `.venv\Lib\site-packages\nvidia\cublas\bin`
  - `.venv\Lib\site-packages\nvidia\cudnn\bin`
  - other `nvidia\*\bin` directories

Smoke test:

- A 10s WAV clip was transcribed successfully on `cuda/float16`.
- Full final render transcription completed in about 3 minutes.

Output:

- `audio-checks/final-video-qa/final_transcript_turbo_loose.json`

### 4. Transcript Scanner

Purpose:

- Search the loose final-render transcript for:
  - long word spans
  - repeated n-grams
  - self-correction phrases
  - known stutter forms
  - suspicious adjacent repeats

Core heuristics:

- Long word duration:
  - flag words with duration `>= 1.5s`
- Repeated n-grams:
  - scan `3` to `7` grams
  - focus on repeats within short windows for final-render QA
  - ignore common rhetorical / gameplay phrases after context review
- Self-correction phrases/patterns:
  - `"i mean"`
  - `"actually"`
  - `"no wait"`
  - `"scratch that"`
  - `"but i but"`
  - `"we we"`
  - `"going going"`
  - repeated outro phrases

Important judgment rule:

- A repeated phrase is not automatically a cut.
- Classify each candidate as:
  - true duplicate / false start
  - narrative callback
  - battle reset replay
  - intentional rhetorical framing
  - gameplay state repetition

### 5. `scripts/find_audio_repetitions.py`

Purpose:

- Waveform-side search for near-duplicate audio patterns that transcript-only scanning may miss.

Command used:

```powershell
C:\Programming\resolve-mcp\.venv\Scripts\python.exe `
  C:\Programming\resolve-mcp\scripts\find_audio_repetitions.py `
  C:\Programming\resolve-mcp\audio-checks\final-video-qa\final_audio.wav `
  --window-ms 500 `
  --min-lag-ms 300 `
  --max-lag-ms 3500 `
  --sim-threshold 0.90 `
  --min-duration-ms 300 `
  --out C:\Programming\resolve-mcp\audio-checks\final-video-qa\waveform-repetitions.json
```

Parameters:

- `--window-ms 500`: compare half-second audio windows
- `--min-lag-ms 300`: avoid near-identical adjacent frame noise below 300ms
- `--max-lag-ms 3500`: detect immediate repeated-take patterns up to 3.5s apart
- `--sim-threshold 0.90`: high similarity threshold for candidate repeats
- `--min-duration-ms 300`: sustained match floor

Output:

- `audio-checks/final-video-qa/waveform-repetitions.json`

Use:

- This produced many waveform candidates, but transcript/context review was still required. It is a triage signal, not a final verdict.

### 6. Waveform RMS Verification

Purpose:

- Resolve borderline cuts by checking whether a suspected cut window contains speech-like energy.

Method:

- Extract source audio around a region.
- Convert to 16kHz mono WAV.
- Analyze RMS in 25ms bins.

Thresholds used in the Round 2/3 reports:

- `SILENT`: peak `< -45 dBFS`
- `LOW_ENERGY`: peak `< -30 dBFS`
- `BORDERLINE`: peak `< -20 dBFS`
- `SPEECH_LIKE`: peak `>= -20 dBFS`

Decision rule:

- `SPEECH_LIKE`: do not cut unless there is direct evidence it is safe.
- `LOW_ENERGY`: usually safe artifact / dead-air cut.
- `BORDERLINE`: review manually; keep only when speech fraction is effectively zero.

Important example:

- `1989.96-2016.76`
  - peak: `-39.2 dBFS`
  - silent fraction `< -45 dBFS`: `98.4%`
  - verdict: safe 26.8s dead-air cut

### 7. HTML Transcript Generator

Purpose:

- Create a full human-readable transcript with highlighted expected cuts.

Generated files:

- `audio-checks/final-video-qa/final-render-transcript.md`
- `audio-checks/final-video-qa/final-render-transcript.txt`
- `audio-checks/final-video-qa/final-render-transcript-highlighted.html`

HTML features:

- Full transcript from `final_transcript_turbo_loose.json`
- Timestamped segment rows
- Highlighted `<mark>` spans for expected cuts
- Top cards linking to each cut
- Embedded audio players for review clips

Expected cuts highlighted:

1. Final render `301.74-303.40`
2. Final render `448.64-450.56`
3. Final render `1587.34-1589.24`
4. Final render `1596.84-1600.20`

### 8. `ffmpeg` — Audio Preview Generation

Purpose:

- Generate short human-review audio clips around each expected cut.

Clip rule:

- start `2.00s` before cut start
- end `2.00s` after cut end
- fade in/out `0.25s`

Command pattern:

```powershell
ffmpeg -y `
  -ss <preview_start> `
  -t <preview_duration> `
  -i C:\Programming\resolve-mcp\audio-checks\final-video-qa\final_audio.wav `
  -af "afade=t=in:st=0:d=0.25,afade=t=out:st=<duration_minus_0.25>:d=0.25" `
  -codec:a libmp3lame `
  -b:a 128k `
  C:\Programming\resolve-mcp\audio-checks\final-video-qa\cut-audio\cut-N-preview.mp3
```

Generated clips:

- `cut-audio/cut-1-preview.mp3`
  - duration: `5.66s`
  - preview: `299.74-305.40`
- `cut-audio/cut-2-preview.mp3`
  - duration: `5.92s`
  - preview: `446.64-452.56`
- `cut-audio/cut-3-preview.mp3`
  - duration: `5.90s`
  - preview: `1585.34-1591.24`
- `cut-audio/cut-4-preview.mp3`
  - duration: `7.36s`
  - preview: `1594.84-1602.20`

### 9. Round-3 Cross-Chunk N-Gram Review

Purpose:

- Verify that the chunked Sonnet pass did not miss repeats spanning more than the 30s overlap.

Inputs:

- `audio-checks/qa-cuts/round3-ngrams.json`
- `transcripts/4.json`

Candidate count:

- `50`

Classification labels used:

- `NARRATIVE_CALLBACK`
- `BATTLE_RESET_REPLAY`
- `TRUE_DUPLICATE`
- `TRUE_DUPLICATE -> CUT proposal`
- `TRUE_DUPLICATE -> MANUAL_REVIEW`

Outcome:

- All 50 were classified as either:
  - `NARRATIVE_CALLBACK`
  - `BATTLE_RESET_REPLAY`
- No new true duplicate cuts were found.

### 10. Battle-Window Intersection Check

Purpose:

- Confirm that cuts inside battle windows remove artifacts / commentary errors rather than meaningful battle action.

Inputs:

- `transcripts/battles.json`
- `plans/prompts/battle-ends-refine-Brock_Red_Blue_versus_Crystl.out.md`
- `plans/prompts/cut-analysis-4.out.md`

Outcome:

- 12 WARN-level inside-battle cuts
- 0 blockers
- All WARNs were accepted as commentary-level artifact / false-start / dead-air cuts.

### 11. Pokémon / Vocabulary Boundary Check

Purpose:

- Ensure cut boundaries do not split Pokémon names, trainer names, moves, items, or known domain vocabulary.

Outcome:

- PASS
- No boundary landed inside a tracked token.

Manual spot checks:

- `349.36-349.44`
- `522.24-523.20`
- `640.88-641.20`
- `1352.42-1352.58`
- `2440.70-2441.78`

### 12. Cut Replay Metadata Review

Purpose:

- Confirm `apply_cuts_to_fcpxml.py` output was sane and timeline math matched expectations.

Input:

- `E:\Brock Red\Brock Red Blue versus Crystl_ALTERED_BATTLEGAPS_cuts_replay.json`

Key values:

- source cuts: `30`
- `all_cuts.total_tl_frames_removed`: `1370`
- fps denominator: `60`
- timeline removed: `22.83s`
- action counts:
  - deletes: `9`
  - trim_start: `8`
  - trim_end: `11`
  - split_multi: `6`

Interpretation:

- Source seconds cut: `91.32s`
- Timeline seconds removed: `22.83s`
- Discrepancy is expected because many source-time cuts target silence that auto-editor had already removed.

## Final Confirmed Cuts From Human Review

The user reviewed the HTML/audio previews and confirmed all four final-render QA cuts as reasonable.

These final-render times map to canonical source-time cuts already present in `cut-analysis-4.out.md`:

| Human-reviewed final-render cut | Source-time cut already present | Type |
|---|---:|---|
| `301.74-303.40` | `467.98-470.12` | false_start |
| `448.64-450.56` | `674.16-676.26` | self_correction |
| `1587.34-1589.24` | `2700.12-2702.40` | repetition |
| `1596.84-1600.20` | `2713.40-2717.90` | false_start |

## Final Artifacts Produced

- `audio-checks/final-video-qa/final_audio.wav`
- `audio-checks/final-video-qa/final_transcript_turbo_loose.json`
- `audio-checks/final-video-qa/final-render-transcript.md`
- `audio-checks/final-video-qa/final-render-transcript.txt`
- `audio-checks/final-video-qa/final-render-transcript-highlighted.html`
- `audio-checks/final-video-qa/cut-audio/cut-1-preview.mp3`
- `audio-checks/final-video-qa/cut-audio/cut-2-preview.mp3`
- `audio-checks/final-video-qa/cut-audio/cut-3-preview.mp3`
- `audio-checks/final-video-qa/cut-audio/cut-4-preview.mp3`
- `audio-checks/final-video-qa/missed-cuts-review.md`
- `audio-checks/final-video-qa/claude-confirmed-final-cuts.md`
- `audio-checks/qa-cuts/codex-review-round3.md`

## Proposed Claude Skill

### Skill name

`final-render-cut-qa`

### Purpose

Use this skill after a rendered edit exists, before committing to a final rebuild/render, to catch missed repetitions, false starts, and self-corrections in the actual viewer-facing output.

### Trigger phrases

- "watch this final render for missed cuts"
- "QA this rendered video for repetitions"
- "find false starts in the final video"
- "make an HTML transcript with highlighted cuts"
- "generate audio previews around expected cuts"
- "verify Claude's cut list against the final render"

### Required inputs

- Path to rendered video
- Path to project workspace
- Optional path to canonical source-cut JSON
- Optional path to source loose transcript
- Optional path to cuts replay metadata for source-time mapping

### Workflow

1. **Inspect render**
   - Run `ffprobe` on the video.
   - Record duration, video frame rate, resolution, audio stream.

2. **Extract render audio**
   - Use `ffmpeg`.
   - Output mono 16kHz PCM WAV.
   - Store under a dedicated QA folder.

3. **Transcribe with loose settings**
   - Use `faster-whisper`.
   - Model: `large-v3-turbo` by default.
   - Device: `cuda`, compute type `float16` when available.
   - CPU fallback: `int8`.
   - Parameters:
     - `language='en'`
     - `word_timestamps=True`
     - `beam_size=5`
     - `vad_filter=False`
     - `condition_on_previous_text=False`
     - `no_repeat_ngram_size=0`
   - On Windows, register NVIDIA pip DLL dirs before importing / running CTranslate2.

4. **Scan transcript**
   - Flag long word spans (`>=1.5s`).
   - Scan 3-7 gram repeats.
   - Search for known self-correction / stutter patterns.
   - Generate candidate list with timestamps and surrounding segment context.

5. **Classify candidates**
   - `TRUE_DUPLICATE`
   - `FALSE_START`
   - `SELF_CORRECTION`
   - `NARRATIVE_CALLBACK`
   - `BATTLE_RESET_REPLAY`
   - `INTENTIONAL_RHETORIC`
   - `MANUAL_REVIEW`

6. **Generate review artifacts**
   - Full Markdown transcript.
   - Full TXT transcript.
   - Highlighted HTML transcript.
   - For every proposed cut:
     - generate audio preview from `cut_start - 2s` to `cut_end + 2s`
     - apply `0.25s` fade in/out
     - embed the audio in HTML.

7. **Human confirmation**
   - Ask user to review the highlighted HTML and audio previews.
   - If the user confirms a cut, produce Claude handoff.

8. **Map final-render times to source times**
   - If canonical source-cut list is source-time based, do not directly paste final-render times into it.
   - Use cuts replay metadata or timeline/source mapping to map final render time back to source ranges.
   - Verify that confirmed final-render cuts are present in canonical source-cut list.

9. **Final verdict**
   - Write `PASS`, `MINOR_FIXED`, or `REJECT`.
   - Include:
     - must-fix list if any
     - confirmed clean cuts
     - n-gram verdicts if a cross-chunk scan was part of the pass
     - open questions for Claude

### Default output files

Use a folder like:

`audio-checks/final-video-qa/`

Default outputs:

- `final_audio.wav`
- `final_transcript_turbo_loose.json`
- `final-render-transcript.md`
- `final-render-transcript.txt`
- `final-render-transcript-highlighted.html`
- `cut-audio/cut-N-preview.mp3`
- `missed-cuts-review.md`
- `claude-confirmed-final-cuts.md`

### Safety / judgment rules

- Do not cut a repeated phrase only because it appears twice.
- Battle reset commentary often repeats real game-state phrases; classify as `BATTLE_RESET_REPLAY`, not `TRUE_DUPLICATE`.
- Intro thesis and outro summary phrases often recur naturally; classify as `NARRATIVE_CALLBACK`.
- Prefer waveform evidence over Whisper word timestamps around quiet boundaries.
- Treat `SPEECH_LIKE` waveform windows as preserve-by-default.
- Never assume final-render timestamps are source timestamps.

### Acceptance criteria

The skill is complete when:

- final render audio is transcribed with loose settings
- every proposed missed cut has transcript evidence
- every proposed missed cut has an audio preview
- user-confirmed cuts are mapped or matched to source-cut entries
- Claude receives a concise handoff listing only unapplied confirmed cuts
- final verdict file is written
