# Rubric: cut-analysis-qa (custom for brock-cut-qa)

Each review uses these blocks in order. Block 1–3 are MANDATORY pass for `APPROVE_FOR_QA`. Block 4 is the domain-specific quality bar — also mandatory.

## Block 1 — Plan adherence

| # | Criterion | Pass threshold |
|---|-----------|----------------|
| 1.1 | Every must-have in `.codex-sync/plan.md` is addressed by this iteration | Walk the plan's must-haves 1–5 one by one; for each, cite specific evidence (line numbers, source-time ranges, transcript segment indices) in the execution report |
| 1.2 | Codex's "What I did" bullets match the brief Claude wrote | Diff brief asks vs claims; flag silent scope creep / skips |
| 1.3 | Every "What I deliberately did NOT do" entry has a defensible technical reason | Reject any "ran out of time" or missing reason |

## Block 2 — Artifact reality check

| # | Criterion | Pass threshold |
|---|-----------|----------------|
| 2.1 | Every `expected_output` exists at the declared path | `Test-Path` each; for the `verifier` on `cut-analysis-corrected`, run the JSON-validation command |
| 2.2 | `proposed-cuts.json` schema valid (each entry has start_sec, end_sec, confidence ∈ {high,medium,low}, type, reason) | JSON validation script in verifier |
| 2.3 | `start_sec < end_sec` for every entry; all entries inside [0, 2840.3] (source duration); no entries overlap each other | Programmatic check |
| 2.4 | Every entry's `reason` cites at least one transcript segment by index or source-time range | Grep each entry — no bare assertions |

## Block 3 — Process compliance

| # | Criterion | Pass threshold |
|---|-----------|----------------|
| 3.1 | Every must-fix item from the prior review (if any) is addressed | Cross-reference each numbered must-fix against this iteration's bullets |
| 3.2 | Foundational issues from earlier iterations are not silently skipped | If a Block 4 "foundational" item from a prior review remains unfixed, hard REJECT before evaluating new flags |
| 3.3 | No SRC_OVERLAP_PREV cuts (forbidden per `feedback_src_overlap_cut_bug.md`) | Grep every entry's `type` field; reject if any equals `src_overlap_prev` or similar |
| 3.4 | Execution report's frontmatter is valid YAML with required fields (iteration, cycle, status, codex_model) | Parse it |

## Block 4 — Cut-analysis quality bar (the actual QA)

| # | Criterion | Pass threshold | Severity |
|---|-----------|----------------|----------|
| 4.1 | **No missed false-start duplications.** Codex must demonstrate it scanned for repeated 2-grams / 3-grams within a 30s sliding window across the whole loose transcript. If a duplication exists in `transcripts/4.json` and is NOT flagged in `cut-analysis-4.out.md` (with reason), the iteration fails | Pattern: enumerate every n-gram repeat ≥2× in ≤30s; the analyzer must explicitly account for each (either flagged as cut OR documented as KEEP with reason — e.g. "emphatic restatement, no silence between") | **blocker** |
| 4.2 | **No missed self-correction markers.** Cuts that should fire on "I mean…", "actually…", "no wait", "let me…", "OK so…" (when followed by a restated sentence) must be present | Codex enumerates every such marker found; either flags it or justifies KEEP | **blocker** |
| 4.3 | **No atomic-numbered-reference splits.** Per `Teo Speech Style.md` §9.4, phrases like "Rival 2", "attempt one", "second gym leader", "level 14 Onix", "Reset 29" travel as one unit. Cut boundaries must not land between the noun/numeral pair | Programmatic check: for each flagged cut, examine the word immediately before `start_sec` and the word immediately after `end_sec` in the loose transcript. If either is an ordinal/cardinal modifying a noun on the other side, REJECT | **blocker** |
| 4.4 | **No false-positive cuts that strip narrative content.** For each flagged cut, the surrounding ±10s of transcript must be inspected; the removed text must be either (a) <1.5s of empty-WORDS_IN_CLIP audio, (b) a true repeat where the second utterance carries the load, OR (c) a self-correction abandoned fragment | If a cut removes a unique narrative beat (a non-repeated word/sentence that advances the story), REJECT and demote/remove that cut | **blocker** |
| 4.5 | **No cut overlaps a battle window.** Each battle in `transcripts/battles.json` has a `timestamp_sec` (battle start, source seconds). A cut's `[start_sec, end_sec)` range must not contain any battle start nor any of the refined battle ends from `plans/prompts/battle-ends-refine-Brock_Red_Blue_versus_Crystl.out.md` | Programmatic intersection check | **high** |
| 4.6 | **Pokémon-name + homophone fidelity.** No cut boundary lands inside a Pokémon name (Geodude, Onix, Kabutops, Bayleaf, Chikorita, Sentret, Bugsy, Falkner, Whitney, etc.) or a known Whisper-mistranscribed token that the normalizer fixes (e.g. "Starby"→"Starmie", "Burt Lane"→"Blaine") | For each cut, the words at ±0.5s of both boundaries must not be Pokémon-name fragments | **high** |
| 4.7 | **The opener-duplication test case passes.** The cut at `start_sec: 57.62, end_sec: 78.17` (the "This is Brock" Take 1 removal) must be present with `confidence: high` and `type: false_start`. The duplicate Take 1 (src 57.62–61.94) and Take 2 (src 78.18–81.20) are the canonical example this loop was created to catch | Direct presence check | **blocker** |
| 4.8 | **No empty-transcript fragments left in.** Any `WORDS_IN_CLIP(0)` runt < 1.5s between two speech segments should be flagged. Codex enumerates the loose transcript's silent gaps; for each gap > 0.3s and < 1.5s between segments, decide CUT (silent breath/throat-clear) or KEEP (natural pause) with reason | Codex's report must show this enumeration | **high** |

## Severity scale

- **blocker** — must be fixed before approval. Any blocker → REJECT.
- **high** — must be fixed before approval. Any high → REJECT.
- **medium** — should be fixed; not auto-blocking but should be documented as "deferred" with rationale.

Verdict gates:
- `APPROVE_FOR_QA` only when every Block 1–3 criterion is Pass AND every Block 4 criterion is Pass with cited evidence.
- `REJECT` if any blocker- or high-severity criterion fails.

## QA pass (Codex side, after `APPROVE_FOR_QA`)

When Claude writes `verdict: APPROVE_FOR_QA`, Codex runs the formal QA checklist Claude attaches. The QA verifies:
1. The `cut-analysis-4.out.md` JSON is valid + all entries conform to schema.
2. The cut list, applied via `python scripts/apply_cuts_to_fcpxml.py "E:/Brock Red/Brock Red Blue versus Crystl_ALTERED_BATTLEGAPS.fcpxml" -o "E:/Brock Red/"`, produces a `_cuts_replay.json` whose `total_tl_frames_removed / 60` is within ±0.5s of Codex's prediction in the execution report.
3. No cut boundary intersects a battle window (re-run the programmatic check).
4. The opener-duplication test case (Block 4.7) is still present in the final file.

QA returns:
- `PASS` — every check above passes. → final handoff.
- `MINOR_FIXED` — Codex fixed a small issue (e.g. trailing whitespace, JSON formatting) and re-ran the checks. → final handoff.
- `MAJOR_ESCALATE` — a check fails in a way that requires re-running the loop. → Claude re-opens with a new brief. Does NOT burn a respawn.

## What "APPROVE_FOR_QA" means

This rubric only ever produces `APPROVE_FOR_QA` or `REJECT`. There is no bare `APPROVE`. The QA pass is non-negotiable — even if Claude is sure the rubric is satisfied, Codex's QA pass must run before final delivery.
