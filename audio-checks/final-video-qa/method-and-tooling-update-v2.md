# Final Render Cut-QA Method — v2 (Iteration-Disciplined)

Date: 2026-05-22
Supersedes: `method-and-tooling-update.md` (v1)
Status: PROPOSAL — pending user approval before promotion to `~/.claude/skills/final-render-cut-qa/`

## Why v2

v1 captured the tools but treated final-render QA as a self-contained pass with optional human review. The Brock Red iteration showed that what made convergence work was **multi-pass adversarial review with a Codex audit gate**, not a single Sonnet scan + user spot-check. v2 bakes that discipline in, plus closes 12 gaps identified in v1 review.

## Goal

Review a rendered final video for any remaining false-starts, repetitions, self-corrections, Whisper hallucinations, dead-air gaps, or cut-boundary errors that survived the pre-render pipeline. Produce:

1. Audio + HTML review artifacts the user can scrub through
2. Final verdict in one of four states (see §Verdict)
3. If new cuts are confirmed → automated source-time mapping + canonical-list patch + signal to rebuild pipeline

The skill is the **last gate before delivery**. If it returns PASS_CLEAN the video ships; anything else triggers a rebuild loop.

---

## Primary inputs

Required:
- **Rendered video** (path): the file to QA
- **Project workspace** (path): for relative paths to canonical cut list + replay metadata

Optional but strongly recommended:
- **Canonical source-cut JSON** (default: `plans/prompts/cut-analysis-<stem>.out.md`)
- **Source loose transcript** (default: most-recent `transcripts/*.json`)
- **Cuts replay metadata** (default: `<source-dir>/*_cuts_replay.json`) — REQUIRED for source-time mapping
- **Intro speed override** (default: read from `transcripts/min-battles.json` → 400% if false, 100% if true)
- **Edit timeline name** (default: auto-detect by `_FINAL_4K.mp4` filename ending)

Speaker-style reference (auto-loaded):
- `~/.claude/Teo Speech Style.md` — atomic-numbered-references (§9.4), emphatic-restatement patterns ("really really really"), opener/aside conventions

---

## Pre-flight — unconditional spot-checks (NEW vs v1)

Before any scanning runs, generate audio previews of the highest-risk regions, **all four mandatory**, regardless of scanner findings. Each region historically produced bugs the scanners missed:

1. **Opener:** `0 → 30s` of rendered audio (caught the v1 "This is Brock" duplication)
2. **Each refined battle-end:** `(battle_end_sec − 10s) → (battle_end_sec + 10s)` (battle-transition compound-cut risk)
3. **Outro:** `(render_duration − 30s) → render_duration` (caught the v3 "with a johto version" false-start)
4. **Carousel-start first 5s:** if the timeline has a `Member Carousel Start` marker, preview that frame's neighborhood (verifies V1/V2 layout split is clean)

These are written to `audio-checks/final-video-qa/spot-checks/` and embedded at the TOP of the HTML report, separate from scanner-flagged cuts. The user reviews them first.

Spot-check artifacts cannot be skipped — even on `--auto-confirm-if-canonical-match` runs they're generated, but only embedded in the HTML when human review is triggered. This guarantees they're always available for post-hoc inspection.

Why: the v1 render's 20.5s opener duplication was caught by the user listening to 0–19s, not by any scanner. Codifying this as a mandatory step means future renders can't ship with that class of bug undetected.

---

## Tools used (same set as v1, with three additions)

Tools 1-12 from v1 are unchanged in v2:
1. `ffprobe` (stream inspection)
2. `ffmpeg` (audio extraction)
3. `faster-whisper` (transcription with loose flags)
4. Transcript scanner (long word + n-gram + self-correction)
5. `scripts/find_audio_repetitions.py` (waveform-similarity triage)
6. Waveform RMS verification (4 dBFS thresholds)
7. HTML transcript generator
8. `ffmpeg` audio preview generator
9. Round-3 cross-chunk n-gram review (5–7 grams, gap 30–180s)
10. Battle-window intersection check
11. Pokémon / vocabulary boundary check
12. Cut replay metadata review

### NEW tool 13 — Codex adversarial review (mandatory)

Purpose:
- Independent cross-model audit of the missed-cuts list BEFORE user confirmation.

Workflow:
- Write `audio-checks/final-video-qa/codex-final-render-brief.md` with: rendered-video path, scanner findings list (every candidate before user filter), classification verdicts, evidence (transcript segments + waveform RMS + audio preview paths), rubric tied to v1's safety rules.
- User feeds the brief to Codex; Codex returns `audio-checks/final-video-qa/codex-final-render-review.md` with one of: APPROVE_FOR_USER_REVIEW / REJECT_WITH_MUST_FIX.
- Only candidates that pass Codex's audit are surfaced to the user for confirmation. Codex-rejected candidates are filtered to a `false-positive-suppressed.md` log (auditable).

Why: round 1's 11 Sonnet subagents independently flagged 31 raw candidates; Codex's audit removed 7 false positives + tightened 10 boundaries. Without that gate, the user reviews 31 candidates and is likely to confirm at least one false positive out of fatigue.

### NEW tool 14 — Teo Speech Style classifier

Purpose:
- Auto-downweight known false-positive patterns from `~/.claude/Teo Speech Style.md`.

Patterns loaded:
- **Atomic numbered references** (§9.4): `"rival 2"`, `"attempt one"`, `"level 14 Onix"`, `"reset 29"`, `"the second gym leader"`, `"five full heals"` — cut boundaries inside these = BLOCKER
- **Emphatic restatements**: `"really really really"`, `"super super easy"`, `"way way way more"` — repeated word ≠ false start
- **Opener vocabulary**: `"Now, ..."`, `"And so..."`, `"And the thing is, ..."` — sentence starters, not repeats
- **Aside conventions**: `"[noun], as it's called here in Japan"` — apparent repeats of the noun are intentional
- **`"but..."`-pivot patterns**: distinguish genuine self-correction from rhetorical pivot
- **Approximate quantifiers**: `"about"`, `"less than"`, `"or so"` — apparent imprecision is intentional

Classifier rule: if a candidate matches one of these patterns AND no waveform-silence boundary > 1s exists between the repeats, downgrade to `INTENTIONAL_RHETORIC` and exclude from missed-cuts list.

### NEW tool 15 — Source-time mapping helper

Purpose:
- Convert a confirmed final-render time to a source time the canonical cut JSON can append.

Location:
- `scripts/map_final_to_source.py`

Algorithm:
```
def final_to_source(final_sec, replay_json, intro_speed_pct, intro_native_sec):
    """
    final_sec: timestamp in the rendered MP4 (seconds)
    replay_json: parsed cuts_replay.json (the `all_cuts` block)
    intro_speed_pct: 100 or 400 (from min-battles.json)
    intro_native_sec: native intro duration before retime (e.g. 17.07)

    Returns: source_sec (timestamp in original source MP4)
    """
    intro_placed_sec = intro_native_sec * 100 / intro_speed_pct
    if final_sec < intro_placed_sec:
        return None  # the time is inside the intro; not a source-time
    # Subtract intro
    edit_tl_sec = final_sec - intro_placed_sec
    # Walk removed_tl_ranges_frames un-applying ripple shifts
    # Each removed range [s, e] in TIMELINE frames means: any edit_tl_sec >= s
    # actually corresponds to a source time that's (e-s) seconds LATER.
    fps = replay_json['den']
    shift_back = 0.0
    for r in replay_json['all_cuts']['removed_tl_ranges_frames']:
        s_sec = r['start'] / fps
        e_sec = r['end'] / fps
        if edit_tl_sec + shift_back >= s_sec:
            shift_back += (e_sec - s_sec)
        else:
            break
    # auto-editor silences are already baked into the V1 layout, so the
    # remaining mapping is: source_sec = first_v1_clip.source_in + edit_tl_sec
    # + shift_back. We approximate by walking V1 clip source-times.
    return edit_tl_sec + shift_back + first_v1_source_in
```

Worked example (Brock Red v3):
- final 301.74s → subtract 4.33s intro → edit-timeline 297.41s
- walk removed ranges up to 297.41s: no shifts apply
- map to V1[1] which starts at source 78.83s → source 78.83 + 297.41 − (cumulative auto-editor silence removed in 0-297.41 edit-time)
- = ~467.98s (matches the canonical entry already in the cut list)

Helper script API:
```bash
python scripts/map_final_to_source.py --final-sec 301.74 \
    --replay E:/.../cuts_replay.json --intro-speed 400
# Output: 467.98 (source seconds)
```

Used by Step 8 of the workflow (below).

---

## Workflow (v2 — iteration-disciplined)

Renumbered from v1 to reflect new gates.

### Step 0 — Resolve canonical paths + create workspace

Walk inputs → resolve absolute paths for video, source transcript, canonical cut JSON, replay metadata, intro speed. Create `audio-checks/final-video-qa/` if missing. If `final_audio.wav` exists from a prior run, rename to `final_audio_v(N-1).wav` (versioning per Rule 7) before continuing.

### Step 1 — Inspect render

Run `ffprobe -show_entries format=duration:stream=codec_type,codec_name,width,height,r_frame_rate -of json <video>`. Record duration, video fps, audio stream presence. If video stream missing or fps mismatches expected, hard-fail with diagnostic.

### Step 2 — Extract render audio

`ffmpeg -y -i <video> -vn -ac 1 -ar 16000 -c:a pcm_s16le final_audio.wav`. Validate output exists + duration matches input ±0.5s.

### Step 3 — Generate spot-check previews (NEW — unconditional)

Generate previews for the four high-risk regions enumerated in §Pre-flight. Write to `spot-checks/`. Embed at top of HTML report.

### Step 4 — Transcribe with loose settings

`faster-whisper large-v3-turbo` on `cuda/float16` (CPU `int8` fallback). The four flags non-negotiable: `vad_filter=False`, `condition_on_previous_text=False`, `no_repeat_ngram_size=0`, `word_timestamps=True`. Output: `final_transcript_turbo_loose.json`. Validate schema (segments array with start/end/words).

CUDA fallback flow:
```python
try:
    register_nvidia_dll_dirs()
    model = WhisperModel('large-v3-turbo', device='cuda', compute_type='float16')
except (ImportError, RuntimeError) as e:
    print(f'WARN: CUDA unavailable ({e}) — falling back to CPU int8')
    model = WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')
```

### Step 5 — Scan transcript

Run the four scanners in parallel:
- Long word duration (≥ 1.5s)
- Repeated n-grams (3-7 grams, all windows)
- Self-correction phrase patterns
- Whisper-hallucination signatures (isolated short phrase + ≥ 30s speechless context + sub-frame duration OR known hallucination tokens: "Thank you.", "Bye.", music-lyric snippets)

Run waveform-similarity scan (`find_audio_repetitions.py`) in parallel as triage signal.

### Step 6 — Apply Teo Speech Style classifier

For every raw candidate, check against the patterns in tool 14. Downgrade matching candidates to `INTENTIONAL_RHETORIC`. Log to `style-suppressed.md` for audit.

### Step 7 — Apply scanner+waveform join rule

For each surviving candidate:
- If transcript-flagged AND waveform-similarity-flagged AND gap > 1s → `STRONG_CANDIDATE`
- If transcript-flagged AND waveform RMS in proposed cut window peak < -25 dBFS → `STRONG_CANDIDATE`
- If transcript-flagged only (no waveform corroboration) → `MEDIUM_CANDIDATE`
- If waveform-only (no transcript repeat) → `MANUAL_REVIEW`
- If RMS peak ≥ -20 dBFS (SPEECH_LIKE) inside proposed cut → `PRESERVE_BY_DEFAULT` (excluded from list)

### Step 8 — Battle / vocabulary / replay-metadata checks

Run battle-window intersection check (rubric §4.5 from v1 round-3), Pokémon-name boundary check (rubric §4.6), and cut-replay sanity check. Any boundary inside a tracked vocabulary token = BLOCKER REJECT. Any cut overlapping a battle START frame ±2s = BLOCKER. Cuts inside battle commentary (mid-battle artifacts) = WARN (acceptable).

### Step 9 — Mandatory Codex adversarial review (NEW gate)

Write `codex-final-render-brief.md` containing:
- Render path + duration + spot-check preview list
- All STRONG_CANDIDATE + MEDIUM_CANDIDATE entries with full evidence (transcript segment quotes, waveform RMS, preview audio path, classification rationale)
- The 4 v1 rubric blocks (plan adherence, artifact reality, process compliance, cut-analysis quality)
- The user-style filter results (what was suppressed and why)
- Request verdict: APPROVE_FOR_USER_REVIEW (no must-fix) | REJECT_WITH_MUST_FIX (specific entries to remove/add/modify)

Skill pauses, prints "Feed `codex-final-render-brief.md` to Codex; respond when verdict is written to `codex-final-render-review.md`."

On Codex APPROVE → continue Step 10. On Codex REJECT → apply must-fix items (add/remove/modify), increment audit pass counter, re-run Step 9. **Max 3 audit passes. After 3 consecutive rejects: hard-halt, write `final-verdict.md` with state `REJECT` + full rejection history, surface to user for investigation.** No auto-promote-remaining-candidates fallback — if the scanner can't produce a Codex-approvable list in 3 tries, something fundamental is wrong (corrupt transcript, wrong rendered file, classifier bug) and a human must look before any cut decisions ship.

### Step 10 — Generate user review artifacts

Build:
- `final-render-transcript.md` (full timestamped Markdown)
- `final-render-transcript.txt` (plain text)
- `final-render-transcript-highlighted.html` (with `<mark>` spans on every Codex-approved candidate + embedded `<audio>` players)
- Spot-check section at top of HTML (the 4 region previews from Step 3)
- Candidate section below (each Codex-approved cut with preview, classification, suggested action)

For each candidate, generate audio preview: `ffmpeg -ss (start-2) -t (end-start+4) -af "afade=t=in:st=0:d=0.25,afade=t=out:..."` → `cut-audio/cut-N-preview.mp3`.

### Step 11 — User confirmation

Show user the HTML report. User reviews spot-checks + each candidate. For each, user confirms CUT / KEEP / DEFER.

User-confirmed cuts go to `claude-confirmed-final-cuts.md` with final-render timestamps + classification + reason.

### Step 12 — Map confirmed cuts to source time + canonical-list patch

For each user-confirmed cut:
1. Run `scripts/map_final_to_source.py` to convert final-render time → source time
2. Check if a source-time range overlapping the mapped time exists in canonical cut JSON
3. If exists: no action needed (confirmed cut already in canonical — convergence achieved)
4. If NOT exists: append new entry to canonical cut JSON with the mapped source time

Write `source-time-mapping-report.md` documenting each confirmation's mapping decision (already-in-canonical / appended-new).

### Step 13 — Determine final verdict

| State | Condition | Pipeline action |
|---|---|---|
| **PASS_CLEAN** | Codex APPROVE + every user-confirmed cut already in canonical (no appends) | Render ships. No rebuild needed. |
| **PASS_WITH_NEW_CUTS** | Codex APPROVE + user confirmed ≥1 cut NOT in canonical (Step 12 appended) | Trigger rebuild: re-run `apply_cuts_to_fcpxml.py` → reimport (cuts: all) → rebuild Steps 5-17 → re-render → re-invoke this skill (recursion limit: 3 iterations) |
| **MINOR_FIXED** | Codex returned MINOR_FIXED on its own QA pass (formatting/schema fix only) | Treat as PASS_CLEAN |
| **REJECT** | Codex REJECT after 3 audit passes OR user marked render as fundamentally broken (missing audio, corrupt video, wrong timeline rendered) | Halt. Surface diagnostic. Pipeline owner investigates. |

Write verdict to `final-verdict.md` with full reasoning + next-action checklist.

---

## Source-time mapping algorithm — full spec

See Step 8 of v1 + tool 15. The algorithm in `scripts/map_final_to_source.py`:

```python
def final_to_source(final_sec, replay_path, intro_speed_pct, intro_native_sec,
                    first_v1_source_in_sec):
    """Map a final-render timestamp to source-video time."""
    import json
    replay = json.loads(open(replay_path).read())
    fps = replay['den']

    intro_placed_sec = intro_native_sec * 100 / intro_speed_pct

    if final_sec < intro_placed_sec:
        raise ValueError(f'final {final_sec}s is inside intro (0..{intro_placed_sec}s); not a source time')

    # Time relative to the edit timeline's source-content start
    edit_tl_sec = final_sec - intro_placed_sec

    # Walk removed_tl_ranges_frames; each removed range shifts source-time forward
    shift = 0.0
    for r in replay['all_cuts']['removed_tl_ranges_frames']:
        rs = r['start'] / fps
        re = r['end'] / fps
        if edit_tl_sec + shift >= rs:
            shift += (re - rs)
        else:
            break

    return first_v1_source_in_sec + edit_tl_sec + shift
```

Inputs needed:
- `replay_path`: `<source-dir>/*_cuts_replay.json` (produced by `apply_cuts_to_fcpxml.py`)
- `intro_speed_pct`: 100 or 400 (read from `transcripts/min-battles.json`)
- `intro_native_sec`: native intro duration (17.07s for GSCPC Intro Short, 19.0s for RB-style intros — read from intro asset's `Video Duration` property)
- `first_v1_source_in_sec`: the source-time of the first non-intro V1 clip on the edit timeline (read via Resolve API once at skill start)

For Brock Red v3:
- `intro_placed_sec` = 17.07 × 100/400 = 4.27s
- `first_v1_source_in_sec` = 78.83 (after the opener-cut applied)

---

## Verdict schema

Output: `audio-checks/final-video-qa/final-verdict.md`

```yaml
---
schema_version: 2
verdict: PASS_CLEAN | PASS_WITH_NEW_CUTS | MINOR_FIXED | REJECT
date: <ISO>
render_path: <abs path>
render_sha256: <hex>
canonical_cut_path: <abs path>
canonical_cut_sha256: <hex>
codex_audit_passes: <int 1-3>
user_confirmed_cuts: <int>
new_cuts_appended: <int>
next_action: ship | rebuild | halt-and-investigate
---

## Summary
<1-2 sentences>

## Verdict reasoning
<which condition matched + cited evidence>

## User-confirmed cuts
| Final-render time | Source-time | In canonical? | Action |
|---|---|---|---|
...

## Codex audit history
- Pass 1: <APPROVE | REJECT count>
- Pass 2: ...

## Next action checklist
- [ ] ...
```

---

## Artifact versioning policy

Per Rule 7 (cap at 2 on disk):
- First run: writes to `final-video-qa/` (current).
- Second run: renames each prior artifact to `*_v(N-1).ext` before overwriting. Keeps prior + current.
- Third run onward: deletes v(N-2), renames current to v(N-1), writes new current. Always exactly 2 versions on disk.

Artifacts subject to versioning:
- `final_audio.wav`
- `final_transcript_turbo_loose.json`
- `final-render-transcript.{md,txt,html}`
- `cut-audio/*.mp3`
- `spot-checks/*.mp3`
- `waveform-repetitions.json`
- `codex-final-render-brief.md`
- `codex-final-render-review.md`
- `claude-confirmed-final-cuts.md`
- `final-verdict.md`

Source-cut JSON (`plans/prompts/cut-analysis-<stem>.out.md`) is versioned separately by the cut-analysis pipeline (not this skill). On PASS_WITH_NEW_CUTS, the skill appends entries and writes a `<canonical>.v(N-1).bak` backup before the append.

Flag `--archive-prior` forces archive-all mode (keep every prior run permanently, dated suffix). Default: rolling 2-version retention.

---

## Schema enforcement

Every output JSON validated against an explicit schema before write. Mandated cut-entry schema:

```json
{
  "start_sec": <float>,            // 0 ≤ start < end ≤ source_duration
  "end_sec": <float>,
  "confidence": "high|medium|low",
  "type": "false_start|repetition|self_correction|artifact|whisper_hallucination|stream_chat_acknowledgment",
  "reason": "<string, cite transcript segment(s) and waveform evidence>"
}
```

Optional metadata fields (prefixed `_`, ignored by `apply_cuts_to_fcpxml.py`):
- `_source_chunk`: which subagent / scanner produced this
- `_dedup_with`: dedupe lineage
- `_waveform_peak_dbfs`: float
- `_codex_audit_pass`: int
- `_classification`: NARRATIVE_CALLBACK / BATTLE_RESET_REPLAY / etc.

Validator: `scripts/validate_cut_schema.py` (called by skill at every artifact-write point).

---

## CUDA fallback flow

```python
def init_whisper():
    try:
        from scripts._cuda_dlls import register_nvidia_dll_dirs
        register_nvidia_dll_dirs()
        from faster_whisper import WhisperModel
        model = WhisperModel('large-v3-turbo', device='cuda', compute_type='float16')
        print('Whisper: CUDA float16')
        return model
    except (ImportError, RuntimeError, OSError) as e:
        print(f'WARN: CUDA init failed ({type(e).__name__}: {e})')
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')
            print('Whisper: CPU int8 (slower, ~10x runtime)')
            return model
        except ImportError:
            raise RuntimeError('faster-whisper not installed — pip install faster-whisper')
```

If CPU fallback triggers and the render is > 30 min, prompt user to confirm before spending ~5h on a CPU transcription.

---

## /edittimeline integration

The skill is invoked automatically as **Step 18** of `/edittimeline` (after Step 17's 4K render completes successfully).

Invocation mode in `/edittimeline`:
```bash
python ~/.claude/skills/final-render-cut-qa/run.py \
    --render-path "<FINAL_4K path>" \
    --workspace "$PWD" \
    --auto-confirm-if-canonical-match \
    --max-codex-passes 3 \
    --max-rebuild-iterations 2
```

`--auto-confirm-if-canonical-match` (**DEFAULT ON**): if every user-confirmed cut maps to an entry already in canonical, skip the user-confirmation prompt and return PASS_CLEAN silently. Override with `--no-auto-confirm` for runs where you want to eyeball the HTML regardless.

`--max-rebuild-iterations` (**DEFAULT 1**): if PASS_WITH_NEW_CUTS triggers a rebuild, cap to ONE full rebuild cycle (~2h compute) before escalating. If the post-rebuild re-QA still returns PASS_WITH_NEW_CUTS, halt and surface to user for investigation. Rationale: a second-round miss after one rebuild suggests the pipeline isn't converging and a human needs to look.

User-triggered invocation (manual mode, no auto-confirm):
- "watch this final render for missed cuts"
- "QA this rendered video for repetitions"
- "find false starts in the final video"
- "verify Claude's cut list against the final render"
- "spot-check the opener of <video>"

---

## Safety rules (expanded from v1)

1. **Never assume final-render timestamps are source timestamps.** Always run `map_final_to_source.py` before appending to canonical.
2. **Never auto-confirm a cut that would touch a Pokémon name, trainer name, location, or atomic-numbered reference.** Codex audit gate enforces this; the validator double-checks at write time.
3. **Treat SPEECH_LIKE waveform windows (peak ≥ −20 dBFS) as preserve-by-default.** Removal requires user override.
4. **Battle-reset commentary often repeats real game-state phrases.** Classify as BATTLE_RESET_REPLAY, not TRUE_DUPLICATE. The user's style doc has explicit examples.
5. **Intro thesis + outro summary phrases recur naturally** ("find out how far Brock can get" appears at 108s + 168s + 230s). Classify as NARRATIVE_CALLBACK.
6. **Emphatic restatements are not false starts.** "Really really really close" is one rhetorical unit, not three takes. The Teo Speech Style classifier enforces this.
7. **Codex adversarial review is mandatory.** Skill cannot return PASS without at least one Codex audit pass returning APPROVE_FOR_USER_REVIEW.
8. **Spot-check previews are mandatory and unfiltered.** The 4 high-risk regions are always presented to the user regardless of scanner findings.
9. **The skill must not edit `plan.md`, `manifest.json`, `rubric.md`, or any `iter-*-claude-*.md` file** from a parallel `/claude-codex-sync-*` loop if one is active. Stay in `audio-checks/final-video-qa/` and `plans/prompts/cut-analysis-*.out.md` (for append only).
10. **The skill never rebuilds the timeline itself.** It signals PASS_WITH_NEW_CUTS and exits; the user (or `/edittimeline` orchestrator) re-invokes the rebuild pipeline. Decoupling QA from rebuild prevents recursion bugs.

---

## Acceptance criteria

Skill is complete and ready for promotion when:

1. ✅ Final render audio is transcribed with loose settings, output passes JSON schema validation
2. ✅ Spot-check previews exist for all 4 high-risk regions (opener / each battle-end / outro / carousel-start if present)
3. ✅ Every transcript-flagged candidate has BOTH transcript evidence AND waveform RMS classification
4. ✅ Teo Speech Style classifier has run and `style-suppressed.md` exists (even if empty)
5. ✅ Codex adversarial review has run at least once with verdict written to `codex-final-render-review.md`
6. ✅ Every user-confirmed cut has a source-time mapping (via `map_final_to_source.py`) written to `source-time-mapping-report.md`
7. ✅ Every new cut appended to canonical preserves the schema validator
8. ✅ Final verdict file written with one of the 4 verdict states + cited reasoning
9. ✅ Artifact versioning policy honored (2 versions max on disk; older runs renamed before overwrite)
10. ✅ If PASS_WITH_NEW_CUTS triggers a rebuild, the rebuild signal is written to `rebuild-trigger.flag` for `/edittimeline` to consume

---

## Migration from v1

The v1 doc (`method-and-tooling-update.md`) is preserved as a reference for what the Brock Red ad-hoc run actually did. v2 is the codified skill spec.

When the skill is promoted to `~/.claude/skills/final-render-cut-qa/`:
- `SKILL.md` = condensed version of this doc (the "what to do" parts)
- `references/source-time-mapping.md` = the algorithm spec
- `references/teo-speech-style.md` = pattern list (copy from `~/.claude/Teo Speech Style.md`)
- `references/codex-review-brief-template.md` = template for Step 9
- `scripts/map_final_to_source.py`, `scripts/validate_cut_schema.py`, `scripts/_cuda_dlls.py` = helpers
- `scripts/run.py` = master entrypoint matching the `--render-path / --workspace / --auto-confirm-if-canonical-match / --max-codex-passes / --max-rebuild-iterations` signature

After v2 promotion, delete v1 + v2 source docs per Rule 7 (the skill IS the canonical record).

---

## Design decisions (locked, 2026-05-22)

User answered the four design questions:

| Decision | Value | Rationale |
|---|---|---|
| `--auto-confirm-if-canonical-match` default | **ON** | Silent PASS_CLEAN when no new cuts. Override with `--no-auto-confirm` for explicit review. |
| `--max-rebuild-iterations` default | **1** | One rebuild then escalate. A second-round miss after a rebuild = pipeline isn't converging. |
| Spot-check regions | **All 4** (opener / battle-ends / outro / carousel-start) | Each one historically caught a real bug. |
| Codex 3-strike behavior | **Auto-halt + escalate** | Fail closed. No auto-promote of unreviewed candidates. |

These decisions are baked into the workflow above. No further open questions for v2.
