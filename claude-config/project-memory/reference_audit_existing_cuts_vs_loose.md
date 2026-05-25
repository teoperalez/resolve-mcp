---
name: Audit existing cuts against loose source transcript to find over-aggressive boundaries
description: Cuts added in earlier iterations (e.g. AUDIT-v5 from v6 era) were often based on the default Whisper transcript which hid false-starts. The result: cut boundaries removed only part of the duplicate, leaving fragments. Re-auditing against the loose source transcript catches these.
type: reference
project: resolve-mcp
originSessionId: d67a4cf0-ef49-42f3-87a4-44f400894785
---
## The class of bugs this catches

A cut at source 2587.55-2590.57 had reason "AUDIT-v5: removes 'Starmie wants Bubble Beam' false-start move call". The intent was to remove "this starmie wants bubble beam but seriously this starmie wants surf". But the boundaries (set against default-Whisper word timestamps) actually only removed "this starmie wants bubble beam but seri" — leaving "ously this starmie wants surf" which Whisper then transcribed at the splice as awkward fragments.

Result: v6, v7, v8, v9, v10, v11, v12 all had the bubble beam stutter audible in the final audio. **Seven iterations.** The user finally noticed it on critical re-reading; my automated scans never caught it because the duplicate "starmie wants" was split across the cut splice.

## How to find these

1. Generate the loose source transcript (`large-v3 condition_on_previous_text=False no_repeat_ngram_size=0 vad_filter=False`)
2. For each cut in the existing cut list:
   - Get the source word timestamps from loose transcript that fall inside the cut range
   - Get the words immediately before and after the cut
   - Check: does the cut START at a clean word boundary?
   - Check: does the cut END at a clean word boundary?
   - If either boundary is INSIDE a stretched word (>1.5s) in the loose transcript, suspect the cut is over-aggressive
3. For suspect cuts, re-extract the source audio in that region (±5s) and re-transcribe with large-v3 to verify the actual content
4. Revise cut boundaries to align with actual word boundaries from the loose source

## Tool support

`scripts/audit_cuts_against_loose.py --cuts <cut.json> --loose <loose_transcript.json>` flags:
- `boundary_in_long_word` (>1.5s)
- `repeated_ngram_after_cut` (n-gram before cut repeats within 5s after)
- `atomic_numbered_split` (e.g. cut splits "Rival 2", "attempt one")

This catches MOST over-aggressive cuts. But the script doesn't catch the most insidious class: cuts that remove a COMPLETE THOUGHT along with the false-start. Example: cut 604.72-610.30 removed "might actually be a little bit of a challenge" (complete thought) along with the trailing false-start "number one is that he's pretty fast and he can". The cut analyzer for `audit_cuts_against_loose.py` doesn't know "might actually be a little bit of a challenge" is a complete thought worth preserving — only a human reading the audio can tell.

## Process

When the user reports an issue or critical reading reveals a problem:

1. Find the issue's source-time
2. Look up that source position in the loose source transcript word boundaries
3. Identify what the speaker actually said (false-start + clean restart structure)
4. Determine the IDEAL cut: keep the complete thought, remove only the false-start fragment
5. Use word-aligned source-time boundaries from the loose transcript (NOT default-Whisper word timestamps which can be off by 100-400ms)
6. Update the cut in `plans/prompts/cut-analysis-<stem>.out.md`
7. Document with `AUDIT-vN (loose-source-verified word boundaries)` reason field
8. Rebuild

## Cuts found over-aggressive in Misty Red (canonical examples)

| Cut | Old | New | What was being preserved |
|---|---|---|---|
| 604.72-610.30 | (broken — removed complete thought) | **606.50-610.22** | "might actually be a little bit of a challenge" preserved |
| 2587.55-2590.57 | (broken — left mid-seriously fragment) | **2589.46-2592.80** | "this starmie wants" first occurrence preserved, removes "bubble beam but seriously this starmie wants" |
| 3071.26-3073.98 | (broken — partial cut, left 29 stutter) | **3071.12-3073.44** | "so" preserved, removes "she might actually turn out to pretty so" |
| 2969.1-2971.38 | (broken — left "We've" stutter before "20-ish") | **2968.92-2971.52** | "call it right there." preserved, removes "We've taken like 29 resets." |
| 1342.62-1343.13 | (partial — only 0.51s silence cut, missed false-start) | **1340.32-1342.76** | "morty" preserved, removes "that would put her above her" false-start |

All five fixed in v13. The remaining cuts in the list were validated word-aligned via the loose source.

## Default Whisper vs loose: which to trust for cut decisions

**Always loose.** Default Whisper merges false-starts into smeared words (e.g. a 4.84-second "Misty" word at src 392.04-396.88 actually contained "Misty's come ... Misty has to go up against"). Cut decisions based on default-Whisper timestamps will be wrong.

Loose transcript settings: `large-v3, beam_size=5, vad_filter=False, condition_on_previous_text=False, no_repeat_ngram_size=0`. CPU int8 is fine (~25-40 min for 47-min source).

## When loose still smears

Even loose Whisper can smear long words (the "she's" 2.52s case at src 1342.44-1344.96 actually contained the entire "that would put her above her that would mean she's" passage). Workaround: extract a 10-15s window around suspect stretched words and re-transcribe THAT clip with same settings. Short-window transcription is more accurate than full-track because Whisper's context window doesn't get a chance to merge.
