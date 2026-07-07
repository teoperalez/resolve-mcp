---
name: final-render-cut-qa
description: After a video has been rendered, audit it for missed false-starts, repetitions, self-corrections, Whisper hallucinations, dead-air gaps, and cut-boundary errors. Generates spot-check audio previews + HTML transcript + Codex audit gate + source-time mapping + verdict. Use after the orchestrator final render, or when the user says "QA this render", "watch this final render for missed cuts", "find false starts in the final video", "verify Claude's cut list against the final render", "spot-check the opener of <video>". Trigger phrases include "missed cut", "false start in render", "QA the render", "audit the final video".
---

# final-render-cut-qa

Last gate before delivery. Audits a rendered final video against its canonical source-cut list. Returns one of four verdict states; PASS_CLEAN ships, PASS_WITH_NEW_CUTS triggers exactly one rebuild, REJECT halts, MINOR_FIXED is treated as PASS_CLEAN.

Detailed methodology lives in `references/method.md`. This SKILL.md is the operating procedure.

---

## Inputs

Required:
- `--render-path <PATH>` — the rendered video file (typically `*_FINAL_4K.mp4`)
- `--workspace <PATH>` — the project root (defaults to current working directory)

Optional:
- `--canonical-cut-path <PATH>` — default: `plans/prompts/cut-analysis-<stem>.out.md`
- `--source-transcript <PATH>` — default: most-recent `transcripts/*.json`
- `--replay-metadata <PATH>` — default: `<source-dir>/*_cuts_replay.json`
- `--intro-speed-pct {100|400}` — default: read `transcripts/min-battles.json`
- `--auto-confirm-if-canonical-match` — default ON (silent PASS_CLEAN when no new cuts). Override: `--no-auto-confirm`
- `--max-codex-passes` — default 3
- `--max-rebuild-iterations` — default 1
- `--archive-prior` — default off (rolling 2-version retention); pass to keep every prior run dated

---

## Workspace layout

All artifacts go under `<workspace>/audio-checks/final-video-qa/`:

```
audio-checks/final-video-qa/
├── final_audio.wav                                  # mono 16kHz extract
├── final_transcript_turbo_loose.json                # large-v3-turbo loose decoder
├── final-render-transcript.{md,txt,html}            # human-readable
├── spot-checks/                                     # mandatory pre-flight previews
│   ├── opener.mp3
│   ├── battle-end-N.mp3 (one per refined battle end)
│   ├── outro.mp3
│   └── carousel-start.mp3
├── cut-audio/cut-N-preview.mp3                      # scanner-flagged cut previews
├── waveform-repetitions.json                        # find_audio_repetitions.py output
├── style-suppressed.md                              # Teo Speech Style filter log
├── codex-final-render-brief.md                      # input for Codex audit
├── codex-final-render-review.md                     # Codex verdict
├── claude-confirmed-final-cuts.md                   # user's CUT/KEEP/DEFER decisions
├── source-time-mapping-report.md                    # final-render → source mapping
├── final-verdict.md                                 # the verdict file
└── rebuild-trigger.flag                             # written iff PASS_WITH_NEW_CUTS
```

Per Rule 7: by default, before overwriting any artifact, the prior version is renamed to `<name>_vN-1.<ext>` (rolling 2-version retention). With `--archive-prior`, every run gets a dated suffix and nothing is deleted.

---

## Workflow

### Step 0 — Resolve canonical paths + create workspace

1. Validate `--render-path` exists and is `.mp4`/`.mov`.
2. Resolve all optional paths via defaults or args.
3. Create `audio-checks/final-video-qa/` if absent.
4. If prior `final_audio.wav` exists, rename to `final_audio_v(N-1).wav` (versioning).

### Step 1 — Inspect render

Run `scripts/inspect_render.py <render-path>` which wraps:
```
ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,width,height,r_frame_rate -of json <render-path>
```

Validate: duration > 0, video stream present, audio stream present. Hard-fail with diagnostic if any check fails.

### Step 2 — Extract render audio

```
ffmpeg -y -i <render-path> -vn -ac 1 -ar 16000 -c:a pcm_s16le audio-checks/final-video-qa/final_audio.wav
```

Validate output duration matches input ±0.5s.

### Step 3 — Generate spot-check previews (UNCONDITIONAL)

For all four regions, regardless of scanner findings (see `references/spot-check-regions.md` for detection rules):

| Region | Source | Trigger |
|---|---|---|
| Opener | `0 → 30s` of final audio | Always |
| Each refined battle-end | `(end ± 10s)` | If `plans/prompts/battle-ends-refine-<stem>.out.md` exists |
| Outro | `(duration − 30s) → duration` | Always |
| Carousel-start | `(carousel_frame − 2s) → (carousel_frame + 5s)` | If timeline has `Member Carousel Start` marker |

Each preview: `ffmpeg -ss <s> -t <d> -i final_audio.wav -af "afade=t=in:st=0:d=0.25,afade=t=out:st=<d-0.25>:d=0.25" -codec:a libmp3lame -b:a 128k spot-checks/<name>.mp3`

Even on `--auto-confirm-if-canonical-match`, spot-checks are GENERATED (for post-hoc audit) but only EMBEDDED in HTML when human review is triggered.

### Step 4 — Transcribe with loose settings

Use `scripts/transcribe_loose.py`:
```python
from scripts._cuda_dlls import register_nvidia_dll_dirs
register_nvidia_dll_dirs()
from faster_whisper import WhisperModel

try:
    model = WhisperModel('large-v3-turbo', device='cuda', compute_type='float16')
except Exception as e:
    # CPU fallback — warn if render > 30 min
    if render_duration > 1800:
        print('WARN: CPU fallback on >30min render = ~5h transcription')
        # Prompt for confirmation
    model = WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')

segments, info = model.transcribe(
    'final_audio.wav',
    language='en',
    word_timestamps=True,
    beam_size=5,
    vad_filter=False,
    condition_on_previous_text=False,
    no_repeat_ngram_size=0,
)
```

Output: `final_transcript_turbo_loose.json`. Validate schema (segments array with start/end/words).

### Step 5 — Scan transcript

Four parallel scanners produce a raw candidate list:

1. **Long word duration**: flag words with `duration ≥ 1.5s` (Whisper alignment artifact = often silence collapsed onto one word)
2. **Repeated n-grams**: scan 3-7 grams; same-segment AND adjacent-segment AND ≤30s windows
3. **Self-correction phrases**: regex match `"i mean"`, `"actually"`, `"no wait"`, `"scratch that"`, `"but i but"`, `"we we"`, `"going going"`, `"ahead ahead"`, etc.
4. **Whisper-hallucination signatures**: isolated short phrase + ≥30s speechless context + (sub-frame duration <0.1s OR known hallucination tokens: `"Thank you."`, `"Bye."`, music-lyric snippets)

Also run waveform-similarity triage in parallel:
```
python scripts/find_audio_repetitions.py final_audio.wav \
    --window-ms 500 --min-lag-ms 300 --max-lag-ms 3500 \
    --sim-threshold 0.90 --min-duration-ms 300 \
    --out waveform-repetitions.json
```

### Step 6 — Teo Speech Style classifier

Load patterns from `references/teo-speech-style-patterns.md`. For every raw candidate, check against:
- Atomic numbered references (cut boundary inside = BLOCKER, exclude immediately)
- Emphatic restatements ("really really really" = one rhetorical unit, downgrade to INTENTIONAL_RHETORIC)
- Opener vocabulary ("Now, ...", "And so...")
- Aside conventions
- `"but..."`-pivot patterns
- Approximate quantifiers

Downgraded candidates logged to `style-suppressed.md` (auditable).

### Step 7 — Scanner + waveform join rule

For each surviving candidate, assign signal strength:

| Combination | Classification |
|---|---|
| Transcript-flagged AND waveform-similarity match AND silent-gap > 1s | STRONG_CANDIDATE |
| Transcript-flagged AND RMS peak in proposed cut < −25 dBFS | STRONG_CANDIDATE |
| Transcript-flagged only (no waveform corroboration) | MEDIUM_CANDIDATE |
| Waveform-only (no transcript repeat) | MANUAL_REVIEW |
| RMS peak ≥ −20 dBFS (SPEECH_LIKE) inside proposed cut | PRESERVE_BY_DEFAULT (exclude) |

### Step 8 — Vocabulary + battle + replay-metadata checks

- **Battle-window intersection**: load `transcripts/battles.json` + `plans/prompts/battle-ends-refine-*.out.md`. Any cut overlapping a battle START frame ±2s = BLOCKER REJECT.
- **Pokémon / vocabulary boundary**: load vocab dict from `references/vocab-boundary-check.md`. Any cut boundary landing inside a tracked token = BLOCKER REJECT.
- **Replay metadata sanity**: load `cuts_replay.json`, verify counts (delete + trim_start + trim_end + split_multi) sum to expected operations, removed seconds within ±5s of canonical-list-sum.

### Step 9 — Codex adversarial review (MANDATORY GATE)

**KNOWN LIMITATION:** the Codex CLI sandbox on this Windows machine cannot reach `C:\Programming\...`. Until resolved (see `references/codex-integration-status.md`), Step 9 runs as a **manual relay**:

1. Write `codex-final-render-brief.md` containing: render path + duration, all STRONG_CANDIDATE + MEDIUM_CANDIDATE entries with full evidence (transcript quotes, waveform RMS, audio preview paths, classifications), and the rubric from `references/codex-review-brief-template.md`.
2. Print to user: `"Codex brief ready at <path>. Paste into your Codex session and write the verdict to codex-final-render-review.md, then reply 'codex done'."`
3. Poll for `codex-final-render-review.md` existence (60s intervals, max 30 min wait).
4. Parse verdict:
   - **APPROVE_FOR_USER_REVIEW** → continue Step 10
   - **REJECT_WITH_MUST_FIX** → apply must-fix items (add/remove/modify), increment audit pass counter, re-run Step 9 from top
5. After 3 consecutive REJECT verdicts, hard-halt: write `final-verdict.md` with state `REJECT` + full rejection history. Surface to user. No auto-promote-remaining-candidates fallback.

### Step 10 — Generate user review artifacts

Build the HTML report at `final-render-transcript-highlighted.html` using `scripts/build_review_html.py`:
- Top section: spot-check region previews (the 4 from Step 3)
- Middle section: Codex-approved scanner candidates with `<mark>` spans in the transcript + embedded `<audio>` players + classification + suggested action
- Bottom section: full timestamped transcript

Also write:
- `final-render-transcript.md` (timestamped Markdown)
- `final-render-transcript.txt` (plain text)

For each Codex-approved candidate, ensure an audio preview exists at `cut-audio/cut-N-preview.mp3` (generate if absent).

### Step 11 — User confirmation

If `--auto-confirm-if-canonical-match` (default ON) AND every Step-7 STRONG_CANDIDATE maps to an existing canonical-cut entry (validated via Step 12's mapping check first), **skip the user prompt** and proceed to PASS_CLEAN.

Otherwise: open the HTML report; ask user to review each candidate and confirm CUT / KEEP / DEFER. Write decisions to `claude-confirmed-final-cuts.md`.

### Step 12 — Map confirmed cuts to source-time + canonical-list patch

For each user-confirmed CUT:
1. Run `scripts/map_final_to_source.py --final-sec <T> --replay <path> --intro-speed <pct>` → get source time
2. Check overlap with canonical entries (load `cut-analysis-<stem>.out.md`, scan for `(start_sec, end_sec)` ranges within ±1s of mapped time)
3. If overlap: log "already in canonical" — no action
4. If no overlap: append new entry to canonical with mapped source time; FIRST back up canonical to `<canonical>.v(N-1).bak`

Validate every appended entry with `scripts/validate_cut_schema.py` before write.

Write `source-time-mapping-report.md` documenting every mapping decision.

### Step 13 — Determine verdict

| State | Condition | Action |
|---|---|---|
| **PASS_CLEAN** | Codex APPROVE + every confirmed cut already in canonical (no appends) | Render ships. Write `final-verdict.md` with `next_action: ship`. |
| **PASS_WITH_NEW_CUTS** | Codex APPROVE + >=1 cut appended to canonical | Trigger rebuild. Write `rebuild-trigger.flag` for the orchestrator rebuild gate. Re-invoke this skill after rebuild - **MAX 1 rebuild iteration**. If second-round QA also returns PASS_WITH_NEW_CUTS, hard-halt with REJECT. |
| **MINOR_FIXED** | Codex returned MINOR_FIXED (formatting/schema fix only) | Treat as PASS_CLEAN |
| **REJECT** | 3 Codex rejects OR user marked render fundamentally broken OR replay-metadata sanity failed | Halt. Write `final-verdict.md` with state REJECT + full diagnostic + rejection history. Surface to user for investigation. |

Write `final-verdict.md` per the schema in `references/verdict-schema.md`.

---

## Required helper scripts

Implementations live in `scripts/` next to this SKILL.md. See `references/script-specs.md` for full APIs:

- `scripts/_cuda_dlls.py` — register NVIDIA pip-package DLL dirs (Windows)
- `scripts/inspect_render.py` — ffprobe wrapper, JSON output
- `scripts/transcribe_loose.py` — faster-whisper with the 4 loose flags + CUDA fallback
- `scripts/scan_transcript.py` — 4 parallel scanners (long-word, n-gram, self-correction, hallucination)
- `scripts/find_audio_repetitions.py` — already exists in resolve-mcp, copy/symlink
- `scripts/teo_style_filter.py` — pattern-match against `references/teo-speech-style-patterns.md`
- `scripts/map_final_to_source.py` — final-render → source-time mapping (see `references/source-time-mapping.md`)
- `scripts/validate_cut_schema.py` — JSON schema validator
- `scripts/build_review_html.py` — HTML report generator
- `scripts/run.py` — master orchestrator, signature matches the `--render-path / --workspace / ...` from §Inputs

---

## Safety rules (10 mandatory)

1. **Never assume final-render timestamps are source timestamps.** Always run `map_final_to_source.py` before appending to canonical.
2. **Never auto-confirm a cut touching a Pokémon name, trainer name, location, or atomic-numbered reference.** Codex audit gate enforces; validator double-checks at write time.
3. **Treat SPEECH_LIKE waveform windows (peak ≥ −20 dBFS) as preserve-by-default.** Removal requires user override.
4. **Battle-reset commentary often repeats real game-state phrases.** Classify as BATTLE_RESET_REPLAY, not TRUE_DUPLICATE.
5. **Intro thesis + outro summary phrases recur naturally** ("find out how far Brock can get" at 108s + 168s + 230s). Classify as NARRATIVE_CALLBACK.
6. **Emphatic restatements are not false starts.** "Really really really close" = one unit. Teo Speech Style classifier enforces.
7. **Codex adversarial review is mandatory.** Skill cannot return PASS without ≥1 Codex APPROVE.
8. **Spot-check previews are mandatory and unfiltered.** All 4 regions always generated regardless of scanner findings.
9. **Skill must not edit `plan.md`, `manifest.json`, `rubric.md`, or any `iter-*-claude-*.md`** from a parallel `/claude-codex-sync-*` loop if active.
10. **Skill never rebuilds the timeline itself.** Signals PASS_WITH_NEW_CUTS and exits; the orchestrator re-invokes the rebuild pipeline.

---

## Acceptance criteria (run is complete when)

1. Final render audio transcribed with loose settings; output passes JSON schema validation
2. All 4 spot-check previews exist
3. Every transcript-flagged candidate has BOTH transcript evidence AND waveform RMS classification
4. Teo Speech Style classifier has run; `style-suppressed.md` written (even if empty)
5. Codex review run at least once with verdict in `codex-final-render-review.md` (OR `REJECT` after 3 retries)
6. Every user-confirmed cut has a source-time mapping in `source-time-mapping-report.md`
7. Every new cut appended to canonical preserves the schema validator
8. `final-verdict.md` written with one of the 4 verdict states + cited reasoning
9. Rolling 2-version artifact retention honored
10. If PASS_WITH_NEW_CUTS, `rebuild-trigger.flag` written for orchestrator consumption

---

## TODO: Codex integration

Currently Step 9 runs as a manual relay because the Codex CLI sandbox can't reach `C:\Programming\...`. When the sandbox issue is resolved (codex-plugin-cc install path or wrapper script), Step 9 should auto-invoke Codex via the `codex:codex-rescue` subagent or `codex-plugin-cc` slash command. See `references/codex-integration-status.md`.

The skill is designed to be a drop-in replacement: when Codex automation works, only the relay-prompt loop in Step 9 needs to change. All other steps + the artifact contract stay identical.
