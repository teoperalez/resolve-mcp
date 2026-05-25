# Codex review brief template

Written to `<workspace>/audio-checks/final-video-qa/codex-final-render-brief.md` by Step 9 of the skill. The user pastes this into a Codex session and Codex writes the verdict to `codex-final-render-review.md`.

The current Codex CLI sandbox can't reach `C:\Programming\...` — Step 9 runs as a manual relay. When sandbox is resolved (see `codex-integration-status.md`), this template stays the same but the dispatch becomes automated.

## Template

```markdown
# Codex Adversarial Review — Final Render Cut-QA, {TASK_LABEL}

Date: {ISO_DATE}
Skill: final-render-cut-qa
Render: {RENDER_PATH}
Render duration: {DURATION_SEC}s
Codex audit pass: {N} of max 3

## Your job

Independently audit the missed-cuts list produced by the final-render QA scanners. Return one of:
- **APPROVE_FOR_USER_REVIEW** — every candidate is a real missed cut worth surfacing to the user.
- **REJECT_WITH_MUST_FIX** — at least one candidate is a false positive (would clip real narration) OR boundary lands wrong OR violates a safety rule.

## Inputs to read

- **Render:** `{RENDER_PATH}`
- **Source transcript (loose):** `{SOURCE_TRANSCRIPT_PATH}`
- **Final-render transcript (loose):** `{FINAL_TRANSCRIPT_PATH}`
- **Canonical source-cut list:** `{CANONICAL_CUT_PATH}`
- **Replay metadata:** `{REPLAY_METADATA_PATH}`
- **Battle anchors:** `transcripts/battles.json` + `plans/prompts/battle-ends-refine-*.out.md`
- **This brief's evidence section** (below)

## Rubric (mandatory checks)

1. **No cut boundary inside a Pokémon name, trainer name, location, atomic-numbered reference.** See `references/vocab-boundary-check.md`. Any violation = REJECT.
2. **No cut overlaps a battle START frame ±2s.** WARN-level on inside-battle (commentary), BLOCKER on battle-start.
3. **No cut would remove narrative content.** Read ±10s of transcript around each proposed cut; if the removed text adds anything (clarification, aside, transition word), REJECT that flag.
4. **No SRC_OVERLAP_PREV cuts** (forbidden — removes words from both copies of duplicates).
5. **Source-time math sanity** — every flagged final-render time should map to a source time via the algorithm in `references/source-time-mapping.md`. If a flag's mapped source time would overlap an existing canonical entry, note it.
6. **Whisper hallucination heuristic check** — for any flag claiming WHISPER_HALLUCINATION, verify: isolated short phrase + ≥30s speechless context + sub-frame duration OR known hallucination token ("Thank you.", "Bye.", music-lyric snippet).
7. **Teo Speech Style** — verify the candidate isn't an emphatic restatement, opener vocabulary, aside, or atomic-numbered reference (see `references/teo-speech-style-patterns.md`).

## Spot-check regions (always reviewed independently)

These are the 4 mandatory pre-flight regions; verify each preview matches the rendered audio:
- `spot-checks/opener.mp3` — first 30s
- `spot-checks/battle-end-N.mp3` (one per refined battle end ±10s)
- `spot-checks/outro.mp3` — last 30s
- `spot-checks/carousel-start.mp3` — carousel-start neighborhood (if marker present)

## Candidate cuts under review

{CANDIDATES_TABLE}

Schema: each row = {final_start_sec, final_end_sec, mapped_source_sec, confidence, classification, transcript_evidence, waveform_evidence, preview_path}

## Suppressed by Teo Speech Style filter (for transparency)

{STYLE_SUPPRESSED_TABLE}

These were classified as INTENTIONAL_RHETORIC and excluded from the candidate list. Verify no legitimate cuts were suppressed in error.

## Output format

Write your verdict to `{REVIEW_PATH}` as a single Markdown document:

```yaml
---
verdict: APPROVE_FOR_USER_REVIEW | REJECT_WITH_MUST_FIX
audit_pass: {N}
date: {ISO_DATE}
---

## Summary
<1-2 sentences>

## Must-fix items (REJECT only)
1. category: false_positive | bad_boundary | vocabulary_violation | battle_intersection | hallucination_miscategorized | speech_style_violation
   severity: blocker | high | medium
   candidate: <final_start_sec>-<final_end_sec>
   transcript_evidence: <quoted text + segment index>
   action: REMOVE | MODIFY <new range> | RECLASSIFY <new type>
   rationale: <1-3 sentences>

## Confirmed clean (APPROVE only)
- <candidate range> — brief rationale

## Spot-check verdicts
- opener: CLEAN | FLAG <reason>
- battle-end-N: CLEAN | FLAG <reason>
- outro: CLEAN | FLAG <reason>
- carousel-start: CLEAN | FLAG <reason>

## Open questions for Claude
- (any concerns the must-fix list couldn't capture)
```

## Constraint reminders

- Read inputs from `{RENDER_PATH}` + `{SOURCE_TRANSCRIPT_PATH}` + canonical-cut + replay-metadata + this brief.
- Do NOT modify any input file.
- Do NOT add cuts not in the candidate list (if you find a missed cut, list it as an Open Question — the next audit pass picks it up).
- Do NOT auto-promote candidates the Teo Speech Style filter suppressed — note them as concerns instead.
- Stay inside the project root. The Codex sandbox should be able to read these paths; if not, request a path-fix from Claude.
```

## Variables substituted at write-time

- `{TASK_LABEL}` — e.g. "Brock Red FINAL_4K v3"
- `{ISO_DATE}` — current date in ISO 8601
- `{RENDER_PATH}` — absolute path to the rendered MP4
- `{DURATION_SEC}` — duration from ffprobe
- `{N}` — current audit pass number (1, 2, or 3)
- `{SOURCE_TRANSCRIPT_PATH}` — `transcripts/<stem>.json`
- `{FINAL_TRANSCRIPT_PATH}` — `audio-checks/final-video-qa/final_transcript_turbo_loose.json`
- `{CANONICAL_CUT_PATH}` — `plans/prompts/cut-analysis-<stem>.out.md`
- `{REPLAY_METADATA_PATH}` — `<source-dir>/*_cuts_replay.json`
- `{CANDIDATES_TABLE}` — Markdown table of STRONG_CANDIDATE + MEDIUM_CANDIDATE entries
- `{STYLE_SUPPRESSED_TABLE}` — Markdown table of suppressions from `style-suppressed.md`
- `{REVIEW_PATH}` — `audio-checks/final-video-qa/codex-final-render-review.md` (where Codex writes the response)
