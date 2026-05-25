---
iteration: 1
cycle: 0
kind: initial-brief
plan_path: .codex-sync/plan.md
manifest_path: .codex-sync/manifest.json
elapsed_seconds: 0
---

# Brief — iter-01 (cycle 0)

## What to build this iteration

Audit `plans/prompts/cut-analysis-4.out.md` (current state: 13 entries — 11 high, 2 medium — see `manifest.json` for SHA) against the loose-source transcript `transcripts/4.json` (350 segments, 2840.3s). Your goal this iteration is to:

1. **Verify every EXISTING flag** against `rubric.md` Block 4. For each entry, classify as KEEP / REMOVE / MODIFY with a transcript-cited reason. Document this verification in `qa-notes.md`.
2. **Enumerate every MISSED cut.** Build a fresh candidate list from the loose transcript using the four detection passes described in `plan.md` §"Implementation order" steps 3-5: n-gram repeats in 30s window, self-correction markers, atomic-numbered-reference splits, WORDS_IN_CLIP(0) fragments.
3. **Stage** the combined cut list as `.codex-sync/artifacts/iter-01/proposed-cuts.json` (schema-compatible with `cut-analysis-4.out.md` — each entry: `start_sec`, `end_sec`, `confidence` ∈ {high,medium}, `type`, `reason`). Each entry's `reason` MUST cite at least one transcript segment by index or source-time range.
4. **Predict** the resulting `total_tl_frames_removed / 60` (delta from current 13.60s baseline if your `proposed-cuts.json` were applied via `scripts/apply_cuts_to_fcpxml.py`). Report this in your execution report's "Cut audit summary" section.

This is an INITIAL pass. Don't try to be exhaustive across all 8 rubric Block 4 criteria — focus on Blocks 4.1 (n-gram repeats), 4.2 (self-correction markers), 4.3 (atomic-numbered-reference splits), and 4.7 (opener-duplication test). The other Block 4 items will be tightened in follow-up iterations if Claude rejects.

## Must-have for this iteration

- [ ] Read `plans/prompts/cut-analysis-4.out.md` end-to-end and inventory every existing entry's `start_sec`/`end_sec`/`type`/`confidence` into `qa-notes.md` (a table) — addresses plan must-have #4
- [ ] Read `transcripts/4.json` and build a list of every speech segment with start/end/text. Note silent gaps (>0.3s) between segments
- [ ] Scan for repeated 2-grams / 3-grams / 4-grams within a 30s sliding window. Report findings in `qa-notes.md` as a table — addresses rubric §4.1 (blocker), plan must-have #1
- [ ] Scan for self-correction markers ("I mean", "actually", "no wait", "let me", "OK so", "alright so", "scratch that"). Report as table — addresses rubric §4.2 (blocker)
- [ ] For each existing flag in `cut-analysis-4.out.md`, examine word at `start_sec - 0.3s` and `end_sec + 0.3s`. If either is part of an ordinal/cardinal+noun pair (e.g. "Rival" + "2", "level" + "14"), flag as MODIFY with corrected boundaries — addresses rubric §4.3 (blocker)
- [ ] Verify the existing entry at `start_sec: 57.62, end_sec: 78.17` (opener-duplication test) is present with `confidence: high` and `type: false_start`. If missing or weakened, that's a foundational error — addresses rubric §4.7 (blocker)
- [ ] Stage `proposed-cuts.json` containing the combined KEEP-existing + NEW-from-audit list (drop REMOVE entries; replace MODIFY entries with corrected boundaries)
- [ ] Write `lint.log` = output of `python -m json.tool .codex-sync/artifacts/iter-01/proposed-cuts.json` (or `NO_LINT_TOOL` if unavailable)
- [ ] Write `asset-integrity.json` = SHA-256 of every input file read (compare against `manifest.json`)
- [ ] Predict `total_tl_frames_removed / 60` for the proposed cut list

## Nice-to-have if cheap

- Enumerate WORDS_IN_CLIP(0) candidate runts (>0.3s, <1.5s gaps between speech segments) — rubric §4.8 (high)
- Cross-check Pokémon-name fidelity at every flagged boundary — rubric §4.6 (high)
- Cross-check battle-window intersection (no cut overlaps `battles.json` start ±30s) — rubric §4.5 (high)

## Out of scope this iteration

- Modifying `plan.md`, `manifest.json`, `rubric.md`, `claude-policy.md`
- Modifying `cut-analysis-4.out.md` itself (Claude promotes only after PASS)
- Re-running `apply_cuts_to_fcpxml.py` (Claude does this in the QA pass)
- Re-decoding the source video for visual analysis
- Any network calls
- Editing files outside `C:\Programming\resolve-mcp\` (except read-only inputs from `E:\Brock Red\` listed in manifest)

## Files Codex should touch (predicted)

- `.codex-sync/artifacts/iter-01/proposed-cuts.json` — new file
- `.codex-sync/artifacts/iter-01/qa-notes.md` — new file
- `.codex-sync/artifacts/iter-01/lint.log` — new file
- `.codex-sync/artifacts/iter-01/asset-integrity.json` — new file
- `.codex-sync/iter-01-codex-execution.md` — new file (write LAST, atomically)

## Asset integrity expectations

After this iteration, the following `manifest.json` outputs should exist:
- `proposed-cuts` at `.codex-sync/artifacts/iter-01/proposed-cuts.json`
- `review-notes` at `.codex-sync/artifacts/iter-01/qa-notes.md`

The `cut-analysis-corrected` expected_output is NOT promoted this iteration — Claude promotes it after PASS.

## Reference materials to read first

- `.codex-sync/plan.md` §"Implementation order" — the four detection passes
- `.codex-sync/rubric.md` Block 4 — the 8 cut-analysis criteria with severity
- `.codex-sync/manifest.json` — absolute paths + SHA-256 of all inputs
- `plans/prompts/cut-analysis-4.out.md` — current cut list
- `transcripts/4.json` — single source of truth for transcript

## Halt conditions Codex should respect

- Stop after writing the execution report. The watcher manages re-invocation.
- If lint or schema validation fails, ship the failure honestly in the execution report — `status: partial`.
- Do NOT approve your own work. Claude reviews next.
- If you discover the loose transcript itself looks wrong (e.g. timestamps don't match the source video duration of 2840.3s), surface that as an "Open question" — do not modify the transcript.
