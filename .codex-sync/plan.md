# Plan — Adversarial QA of Brock Red cut-analysis

Task ID: `brock-cut-qa`
Created: 2026-05-17

## Context

The Brock Red Pokémon Crystal challenge video (47:23, source = `E:\Brock Red\Brock Red Blue versus Crystl.mp4`) went through the resolve-mcp `/edittimeline` pipeline. Step 4 of that pipeline produced `plans/prompts/cut-analysis-4.out.md` — a list of source-time ranges flagged for ripple-deletion as artifacts (throat clears, breath bursts, mic checks) or false-starts (stuttered repeats, abandoned threads).

The first delivered cut on the v1 render (`FINAL_4K v1`) MISSED a major false-start: the streamer recorded **two takes** of the opening line "This is Brock. Brock likes rocks." (src 57.62–61.94s and 78.18–81.20s). Both takes landed in the final because the cut-analysis subagent didn't flag the duplication. v2 patched it manually by adding `{start_sec: 57.62, end_sec: 78.17, type: "false_start"}` to the list. The fact that a 20-second on-camera duplication slipped past the LLM is the trigger for this adversarial loop.

**The loop's purpose:** drive `cut-analysis-4.out.md` to a state where an independent reviewer (Codex) finds zero missed cuts and zero false-positive cuts that strip legitimate narrative. Iterate until Codex returns `PASS` on the formal QA pass with no escalations.

## Must-have

1. **Re-audit the loose-source transcript (`transcripts/4.json`, 350 segs, 2840.3s) end-to-end** for missed false-starts. Specifically:
   - Repeated phrases within ≤30s of each other ("This is Brock" was a 20.5s repeat)
   - Self-corrections — "I mean…", "actually…", "let me restart…", "no wait, …"
   - Abandoned sentence fragments followed by a fresh sentence on the same topic
   - "OK so…" or "alright" markers that start a new take of the same content
2. **Re-audit for atomic-numbered-reference violations.** Phrases like *"Rival 2"*, *"attempt one"*, *"reset 29"*, *"the second gym leader"*, *"my second Pokemon"* travel as one unit. Cuts whose boundary lands between the noun and its number/ordinal/digit are wrong. See `feedback_pokemon_name_normalizer.md` and the `Teo Speech Style.md` §9.4 entry.
3. **Re-audit for `WORDS_IN_CLIP(0)` empty-transcript artifacts** the original analyzer might have under-flagged. Look for short (<1s) gaps between speech segments where the auto-editor preserved a sub-segment with no transcribed words — those are throat clears / breath bursts / mic bumps.
4. **Verify no false-positive cuts.** Read the surrounding ±10s of every flagged cut. If a flag removes a non-redundant word, sentence, or narrative beat, REJECT that flag.
5. **Confirm the existing `apply_cuts_to_fcpxml.py` deletion math is consistent** with the corrected list — the `_cuts_replay.json` after Codex's verdict should show the expected delete count and total seconds removed.

## Should-have

- Cross-reference Pokémon-name normalizer entries (`audio-checks/qa-v6/pokemon_normalizer.json`) — if a cut would split a normalized phrase (e.g. cutting between "Gastly" and the word that follows), flag it.
- Cross-check `SRC_OVERLAP_PREV` cut-type ban — per `feedback_src_overlap_cut_bug.md`, these cuts remove words from BOTH copies and should never be flagged.
- Note any "borderline" cuts where a Haiku subagent might re-classify on a second pass — capture these as "consider manual review" items in the review, not blocker rejections.

## Out of scope

- Re-encoding / re-rendering the source video.
- Modifying the Whisper transcription itself.
- Touching the resolve-mcp Python scripts (`apply_cuts_to_fcpxml.py`, etc.) — fixes happen in the JSON cut list only.
- Re-running the full `/edittimeline` pipeline downstream of Step 5. The 4K re-render is a Claude-side concern, not a Codex QA item.

## Implementation order (Codex's first iteration)

1. Read `plans/prompts/cut-analysis-4.out.md` (current state — 13 entries: 11 high, 2 medium).
2. Read `transcripts/4.json` end-to-end. Build a list of all speech segments with start/end + text.
3. Scan for repeated 2-grams / 3-grams within a 30s sliding window. Flag any cluster where the same phrase appears ≥2 times.
4. Scan for self-correction markers ("I mean", "let me", "actually", "wait", "OK so", "alright so", "no").
5. For each candidate found in steps 3-4: verify the gap between repeats / between the marker and the next sentence is sufficient to indicate a true false-start (vs. an emphatic restatement). Record the proposed cut.
6. Cross-check each EXISTING cut in `cut-analysis-4.out.md` against the loose-source transcript: does it strip a non-redundant word? Does it split an atomic numbered reference?
7. Write `iter-01-codex-execution.md` summarizing findings. Stage a proposed-cuts JSON at `.codex-sync/artifacts/iter-01/proposed-cuts.json`.

After Claude reviews, follow-ups iterate until Codex's QA pass returns PASS.

## Critical files

- `C:\Programming\resolve-mcp\plans\prompts\cut-analysis-4.out.md` — the cut list (mutable target of this loop)
- `C:\Programming\resolve-mcp\transcripts\4.json` — loose-Whisper transcript (read-only reference)
- `C:\Programming\resolve-mcp\transcripts\battles.json` — battle source times (so cuts can't accidentally chop battle context)
- `C:\Programming\resolve-mcp\transcripts\battle-types.json` — battle classifications
- `E:\Brock Red\Brock Red Blue versus Crystl_ALTERED_BATTLEGAPS_cuts_replay.json` — last replay metadata (delete count, removed seconds)
- `E:\Brock Red\Brock Red Blue versus Crystl.mp4` — source video (4K, 60fps, ~47 min) — Codex shouldn't decode this directly; use the transcript.

## Reference materials

- `C:\Users\teope\.claude\projects\C--Programming-resolve-mcp\memory\reference_default_whisper_hides_false_starts.md` — why the loose-source transcript is the right baseline (default Whisper hides duplications)
- `C:\Users\teope\.claude\projects\C--Programming-resolve-mcp\memory\reference_pokemon_name_normalizer.md` — Pokémon-name vocabulary the cut analyzer must not split
- `C:\Users\teope\.claude\projects\C--Programming-resolve-mcp\memory\reference_audio_verify_borderline_cuts.md` — protocol for verifying disputed cut boundaries
- `C:\Users\teope\.claude\projects\C--Programming-resolve-mcp\memory\feedback_src_overlap_cut_bug.md` — SRC_OVERLAP_PREV cuts are forbidden
- `C:\Users\teope\.claude\projects\C--Programming-resolve-mcp\memory\reference_critical_reading_beats_pattern_matching.md` — top-to-bottom read is irreplaceable
- `C:\Users\teope\Teo Speech Style.md` §9.4 — atomic numbered references
- The opener-duplication trigger: src 57.62–78.17s contained TWO takes of "This is Brock. Brock likes rocks." The fact that the original 12-cut output didn't flag this is the smoking gun.

## Definition of done

Codex's QA pass returns `PASS` (not MAJOR_ESCALATE) AND the resulting `cut-analysis-4.out.md` re-applied via `apply_cuts_to_fcpxml.py` produces a `_cuts_replay.json` whose `total_tl_frames_removed / 60` is within ±0.5s of what Codex predicted. At that point the loop halts; Claude promotes the corrected cut list and re-runs Steps 5-17 of `/edittimeline`.
