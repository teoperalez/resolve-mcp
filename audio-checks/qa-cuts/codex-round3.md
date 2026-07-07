# Codex Adversarial Review — Brock Red Cut Analysis (Round 3)

**Date:** 2026-05-19
**Reviewer:** Codex (you)
**Subject:** Round 2 produced 30 cuts (91.32s source / 22.83s timeline). Round 3 added three checks the prior pipeline missed. Verifying convergence before pipeline commits to rebuild + 4K render.

---

## Quick status

| Round | Source seconds cut | Timeline seconds removed (ALL) | Verdict |
|---|---|---|---|
| v1 (original analyzer) | 32.92 | 13.60 | shipped — missed the 20.5s opener dup |
| Round 1 (Sonnet ×11) | 77.76 | n/a | REJECT by Codex (16 must-fix) |
| **Round 2** | 91.32 | 22.83 | **awaiting your verdict** (all must-fix applied + waveform-verified + 26.8s dead-air added) |

Round 2 has been promoted to the canonical `plans/prompts/cut-analysis-4.out.md`. The FCPXML cuts file (`*_CUTS_ALL.fcpxml`) has been regenerated from it.

Round 3 adds three checks that round 1's chunked approach systematically missed:

1. **Battle-window intersection** (rubric §4.5) — Programmatic check that no cut overlaps a battle start ±2s or a refined battle end.
2. **Pokémon-name boundary fidelity** (rubric §4.6) — Word-level check that no cut boundary lands inside a Pokémon name, trainer name, location, or commonly-mistranscribed move/item token.
3. **Cross-chunk n-gram repeat scan** — Catches repeated 4-grams that are 30-180s apart (the round-1 chunks only had 30s overlap, so anything spanning >30s could be missed).

---

## Your job

Independently audit:

1. The canonical cut list (`plans/prompts/cut-analysis-4.out.md`, 30 entries, 91.32s)
2. The round-3 checks report (`audio-checks/qa-cuts/round3-checks-report.md`)
3. The cross-chunk n-gram candidates (`audio-checks/qa-cuts/round3-ngrams.json`, 50 candidates)
4. The cuts replay metadata (`E:/Brock Red/Brock Red Blue versus Crystl_ALTERED_BATTLEGAPS_cuts_replay.json`)

Return one of:

- **PASS** — zero must-fix items. List confirmed-good entries.
- **MINOR_FIXED** — you applied trivial fixes yourself (formatting, mid-word boundary nudges within ±0.3s) and re-verified clean. List what you fixed.
- **REJECT** — surgical must-fix list. Each entry: rubric criterion, evidence (src range + transcript segment index + transcript text), concrete action.

If PASS, the orchestrator rebuilds the configured post-review workflow stages (re-import FCPXML -> rebuild edit timeline -> re-place markers -> re-do A2 audio + Fairlight -> 4K re-render).

---

## Files to read (absolute paths)

All paths are on `C:\Programming\resolve-mcp\` unless noted.

### Canonical cut list (THE TARGET — currently 30 cuts, 91.32s)
- **`plans/prompts/cut-analysis-4.out.md`** — promoted from round 2; this is the file the pipeline will use

### Round-3 verification artifacts
- **`audio-checks/qa-cuts/round3-checks-report.md`** — battle-intersection + Pokémon-name + n-gram top-50 summary
- **`audio-checks/qa-cuts/round3-ngrams.json`** — full cross-chunk n-gram repeat candidates (sorted by gap)
- **`audio-checks/qa-cuts/round3_checks.py`** — script that produced them (re-runnable)

### Round-2 evidence trail
- **`audio-checks/qa-cuts/proposed-cut-list-round2.json`** — round-2 list (= canonical contents, same SHA)
- **`audio-checks/qa-cuts/round2-changelog.md`** — every must-fix disposition + waveform-verification decisions
- **`audio-checks/qa-cuts/waveform-verify.md`** — RMS/peak analysis of 9 borderline cuts (incl. the 26.8s dead-air gap)

### Round-1 evidence trail
- **`audio-checks/qa-cuts/aggregation-report.md`** — round-1 dedupe + existing-cut review
- **`audio-checks/qa-cuts/findings/chunk-NN-findings.json`** (×11) — per-Sonnet subagent JSON

### Loose-source transcript (single source of truth)
- **`transcripts/4.json`** — faster-whisper large-v3 (350 segs, 2840.32s, word-level timestamps)

### Battle anchors
- **`transcripts/battles.json`** — 6 battle start source-seconds
- **`plans/prompts/battle-ends-refine-Brock_Red_Blue_versus_Crystl.out.md`** — refined battle-end source-seconds
- **`transcripts/battle-types.json`** — rival/gym/other classifications

### Cuts replay metadata (the apply_cuts result)
- **`E:/Brock Red/Brock Red Blue versus Crystl_ALTERED_BATTLEGAPS_cuts_replay.json`** — apply_cuts_to_fcpxml.py output. Key fields:
  - `all_cuts.counts`: 9 delete, 8 trim_start, 11 trim_end, 6 split/multi
  - `all_cuts.total_tl_frames_removed`: 1370 frames @ 60fps = 22.83s
  - `all_cuts.removed_tl_ranges_frames`: list of every interval removed in timeline space
  - Source 91.32s vs timeline 22.83s discrepancy: most of the source-time cuts target silence the auto-editor already removed (e.g. the 26.80s dead-air gap at 1989.96-2016.76 is mostly auto-editor silence, contributing ~0s timeline time)

### User-confirmed cuts (already converged into canonical)
- **`audio-checks/final-video-qa/claude-confirmed-final-cuts.md`** — user's manual QA on the final render
- **`audio-checks/final-video-qa/claude-response-to-confirmed-cuts.md`** — my response (all 4 already in round-2)

---

## What round 3 found

### Check 4.5 — Battle-window intersection
**Result: 12 WARN-level findings, 0 blockers.**

All 12 cuts that fall "inside a battle window" are cuts of artifacts/false-starts DURING battle commentary, not chops of the battle action itself. The commentary continues uninterrupted around each cut. Examples:
- `349.36-349.44` (0.08s "ahead" duplicate) inside Rival 1 commentary — battle continues
- `1989.96-2016.76` (26.80s dead air) inside the long Bugsy reset cycle — no commentary, just dead air between attempts
- `1352.42-1352.58` (0.16s "girl" Whisper stitch artifact) inside Bugsy — barely a frame, no impact

**Audit question:** Verify that the cuts inside battle windows are removing artifacts/false-starts and not chopping live action commentary. If any specific cut removes a meaningful battle commentary beat, REJECT it.

### Check 4.6 — Pokémon-name boundary fidelity
**Result: PASS — 0 findings.**

The script checked the word at start_sec ± 0.3s and end_sec ± 0.3s for every cut against a ~50-entry vocabulary (Pokémon names, trainers, locations, key moves, items). No boundary lands inside or adjacent to a tracked word.

**Audit question:** Spot-check 3-5 cuts manually to confirm the script's logic is sound.

### NEW — Cross-chunk n-gram repeat scan
**Result: 50 candidates with 30-180s gaps between occurrences.**

The chunk-internal scan used 30s overlap, so cross-window n-gram repeats with gaps >30s might have been missed. This check uses content-bearing 4-grams (stopword-only n-grams filtered).

**Key observations:**
- Many candidates are **legitimate narrative callbacks** ("find out how far" appears in the intro and is recalled later — this is normal video structure, not a duplicate take)
- Many are **natural battle commentary repetition** ("that brings out the scyther" recurs across multiple Bugsy reset attempts — each reset is a new battle, not a re-take)
- A few **might be real cross-chunk false starts** worth verifying:
  - `"be able to get through"` 1768.60s → 1807.12s (37.8s gap) — Bugsy attempt commentary
  - `"two damage per hit"` 2445.40s → 2489.18s (42.5s gap) — Rival 2 attempt commentary
  - `"get put to sleep"` 2402.78s → 2471.96s (68.4s gap) → 2505.30s — three occurrences within Rival 2 attempts

**Audit question:** Walk the n-gram list (or at least the top 20 by gap-shortest-first) and flag any that are TRUE duplicates (false-start + restart) rather than narrative callbacks or battle-reset re-commentary. For each true duplicate, propose a cut.

---

## Specific concerns to address

### A. Source-time vs timeline-time discrepancy
The canonical list cuts 91.32s of source but the FCPXML only removes 22.83s of timeline. The 68.49s difference is because many cuts target silence the auto-editor already removed. This is FINE (apply_cuts handles silently), but if you see anything alarming in `cuts_replay.json` (e.g. multi-position splits that shouldn't be there, ripple math that doesn't add up), flag it.

### B. The 26.80s dead-air cut (1989.96-2016.76)
This is the largest single cut. Waveform-verified: peak −39.2 dBFS, 98% silent. It contributes ~0s to timeline (auto-editor already excluded it). Codex round 2 didn't see this added.

**Audit question:** Verify the waveform claim (re-extract ffmpeg if needed, OR trust the report). If valid, this cut is a "no-op for FCPXML, but documents the gap was intentional" entry. If the waveform analysis was wrong and there IS commentary in that window, REJECT.

### C. The 5 SPEECH_LIKE removals
Round 2 removed 6 micro-cuts that the original analyzer flagged as `WORDS_IN_CLIP(0)` but waveform showed they contained -16 to -19 dBFS audio (likely game audio + brief breath, but possibly word-fragments that Whisper missed). Removed cuts:
- 172.75-173.05, 258.57-259.05, 556.00-556.28, 599.73-600.42, 1778.85-1779.28, 2692.58-2692.92

**Audit question:** Is the conservative removal the right call? If you think these should still be cut as artifacts (and the waveform-detected audio is just game sound that we're OK losing), recommend REINSTATE.

---

## Schema / validation status

- ✅ Valid JSON (parseable)
- ✅ Every entry has `start_sec < end_sec`
- ✅ All entries in [0, 2840.32]s
- ✅ **No overlapping ranges** (zero pairs where `a.end > b.start`)
- ✅ All entries have required fields: `start_sec`, `end_sec`, `confidence`, `type`, `reason`
- ✅ No `src_overlap_prev` types
- ✅ apply_cuts_to_fcpxml.py runs cleanly (no errors)
- ✅ Pokémon-name boundary check passes (0 findings)
- ✅ Battle-window intersection check: 12 WARN, 0 blockers
- ✅ Cross-chunk n-gram scan: 50 candidates for manual review

---

## Output format Codex should return

Write a single document to `audio-checks/qa-cuts/codex-review-round3.md`:

```markdown
# Codex Round 3 Verdict

verdict: PASS | MINOR_FIXED | REJECT
summary: <1-2 sentences>

## Must-fix items (REJECT only)
1. category: missed_cut | false_positive | bad_boundary | schema | battle_intersection | pokemon_boundary | ngram_repeat
   severity: blocker | high | medium
   src_range: X.XX-Y.YY (or N/A)
   transcript_evidence: <segment index + quoted text>
   action: ADD <new range> | REMOVE <existing range> | MODIFY <existing> to <new range>
   rationale: <1-3 sentences>

## Minor fixes applied (MINOR_FIXED only)
- ...

## Confirmed clean (final list)
- <src_range> — type — confidence — brief rationale

## N-gram repeat verdicts
For each of the 50 candidates in round3-ngrams.json:
- "<ngram>": NARRATIVE_CALLBACK | BATTLE_RESET_REPLAY | TRUE_DUPLICATE → CUT proposal | TRUE_DUPLICATE → MANUAL_REVIEW

## Open questions for Claude
- ...
```

If PASS, pipeline rebuilds & re-renders. If REJECT, I iterate Sonnet pass focused on your must-fix list.

---

## Round 3 stats

- **Subagent passes total:** 11 (round-1)
- **Verification scripts:** waveform RMS analysis (round-2), battle-intersection + Pokémon-name + cross-chunk n-gram scan (round-3)
- **Total cuts:** 30 (was 42 in round-1, was 13 in v1)
- **Source seconds removed:** 91.32s
- **Timeline seconds removed:** 22.83s (ALL) / 20.03s (HIGH only)
- **Convergence signals:** User's manual final-render QA flagged 4 cuts; all 4 already in canonical list

---

**End of brief.** Begin review by reading `plans/prompts/cut-analysis-4.out.md` + `audio-checks/qa-cuts/round3-checks-report.md`, then walk the n-gram candidates. Return verdict to `audio-checks/qa-cuts/codex-review-round3.md`.
