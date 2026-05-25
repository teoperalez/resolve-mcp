---
name: Dialogue review QA protocol — multi-stage critical pass before delivery
description: The complete process for producing a publishable-quality dialogue review WAV+text from a raw cut timeline. Built across v6→v13 iterations on Misty Red. Pattern-matching alone is insufficient — every delivery needs both automated scans AND whole-script critical reading.
type: reference
project: resolve-mcp
originSessionId: d67a4cf0-ef49-42f3-87a4-44f400894785
---
## The goal

Hand off a "nearly perfect" dialogue review at bedtime so the user wakes up to a timeline that only needs minor adjustments. **Accuracy over speed.** Multi-iteration convergence is expected — typically 3-5 cycles before zero real issues remain.

## The fundamental insight

**Pattern detection catches surface issues. Whole-script critical reading catches narrative breaks.** Scripts like `find_audio_repetitions.py` and chunked subagent QA find duplicates, hallucinations, and Pokemon-name typos. But they will NEVER catch issues like:

- An over-aggressive cut that removes "might actually be a little bit of a challenge" along with a false-start (creating a "Bugsy can." dangling fragment)
- A cut boundary that removes only HALF of a duplicate ("29 resets... 20-ish resets" survives in audio because the cut starts mid-word)
- Awkward grammar that a human reader would immediately notice ("she would probably **be** Blaine" should be "**beat** Blaine")

These are caught only by sitting down and reading the script top-to-bottom as a published video, asking *"does this paragraph make sense as a finished narrative?"*

A competing model (Gemini Flash, less capable than Claude) caught dozens of issues on first read of v8 that my entire automated pipeline had missed. The QA standard is: I should never deliver something that another model can immediately spot issues in.

## The 4-stage protocol

### Stage 1 — Orchestrator pre-compute (`scripts/dialogue_qa_pipeline.py phase1`)

Build all the artifacts subagents need:
1. **Waveform repetition candidates** via `find_audio_repetitions.py` (MFCC self-similarity at 0.4-3s lag, sim > 0.95) — catches duplicates Whisper merged
2. **Loose-source transcript** via `large-v3 device=cpu compute_type=int8 condition_on_previous_text=False no_repeat_ngram_size=0 vad_filter=False` — exposes false-starts default Whisper hides
3. **v6→source map + splice timestamps** from live Resolve timeline V1 clips — identifies where Whisper hallucinates phantom words
4. **Pokemon-name + homophone normalizer** dictionary
5. **Chunk audio + artifacts into 6 packets** (5-min chunks with 15s overlap)

### Stage 2 — Parallel chunked subagent QA

Dispatch 6 Haiku subagents (`model: "haiku"`) — one per chunk. Each compares default vs loose transcript word-by-word, cross-references waveform candidates, audits Pokemon names against normalizer, optionally extracts sub-clips and re-transcribes with large-v3. Each writes findings to a JSON.

**Known subagent failure modes:**
- They over-flag waveform similarity matches without verifying actual text repetition (false positives — natural prosody has high MFCC similarity)
- They sometimes use a different output schema than requested (recovery: tolerate either schema in aggregation)
- They may miss subtle cross-segment issues

### Stage 3 — Main-thread QA pass + audit

Aggregate subagent findings + spot-check each flag via direct audio extraction (`ffmpeg -ss N -to M` + re-transcribe). Then run:

- **`audit_cuts_against_loose.py`** on the existing cut list — flags cuts with boundary inside long word (>1.5s false-start signature), dangling n-gram after cut end, or atomic numbered reference splits.
- **Repeated-phrase scan** on loose source — find every 3+gram that repeats within 3s (likely false-start)
- **Hidden false-start scan** — for each stretched word (>1.5s) in source loose, extract that audio window and re-transcribe with no-repeat. Long words often smear hidden false-starts that even the loose pass missed.

### Stage 4 — Whole-script critical reading (the irreplaceable step)

Read `*_NORMALIZED.txt` top to bottom as a published video script. Flag every spot where:

- Narrative breaks ("And there are a few reasons to think that Bugsy can. Number one is..." — wait, Bugsy can WHAT?)
- A claim is set up but never paid off
- Grammar collapses ("would probably be Blaine" should be "beat")
- A sentence has a missing word that makes it nonsensical
- Two adjacent sentences should be one
- An obvious duplicate survives ("we've taken like 29 resets we've taken like 20-ish resets")
- Pokemon-name typos the normalizer missed
- Speaker style is broken (per `Teo Speech Style.md` §9.4)

For each issue found, verify against source-time word boundaries (from loose source transcript) and either:
- Add/revise a cut (with high-confidence word-aligned boundaries)
- Add a normalizer entry
- Document why it's intentional (speaker style, KEEP-per-safelist)

## Output

Three files per iteration vN:

1. **`<name>_vN.wav`** — the dialogue audio
2. **`<name>_vN_NORMALIZED.txt`** — publishable text with Pokemon names + homophones + STT errors corrected
3. **`<name>_vN_REPORT.md`** — what changed vs prior version, what's verified clean, what's pending

## Iteration discipline

After each vN:
1. Run the full protocol on vN
2. If new issues found → revise cuts/normalizer → build v(N+1)
3. Repeat until critical reading finds zero real issues
4. Stop at converged dialogue (per user instruction) OR continue into downstream pipeline

**The pipeline reached convergence at v13 on Misty Red (10 iterations).** v6 had ~30 issues a competing model caught at first read. v13 had zero on a careful re-read.

## Tools built for this protocol

- `scripts/dialogue_qa_pipeline.py` — Stage 1 orchestrator
- `scripts/find_audio_repetitions.py` — MFCC self-similarity scan
- `scripts/audit_cuts_against_loose.py` — cut-boundary audit
- `scripts/normalize_pokemon_text.py` — Pokemon-name + homophone normalizer (multi-pass + cross-segment)
- `audio-checks/qa-v6/pokemon_normalizer.json` — canonical dictionary (~80 entries)

## When to deviate

- If user pushes back on a specific cut → audio-verify with `large-v3 no_repeat_ngram_size=0 vad_filter=False` on the disputed window
- If a sentence reads weird → check if Whisper dropped a word (compare default to loose), and if so add a normalizer entry; if the AUDIO is wrong, that's a cut issue
- Borderline emphatic-restatement vs false-start: KEEP per Teo style §9.4 unless clear false-start signature (incomplete first attempt + measurable pause + clean restart)
