# Claude Iteration Prompt — Fix Round 1 Cut Proposal

You are revising the Round 1 Brock Red cut proposal after Codex adversarial review.

Workspace:

`C:\Programming\resolve-mcp\audio-checks\qa-cuts\`

Primary files:

- `proposed-cut-list.json` — current 42-entry proposal under review
- `codex-review.md` — Codex rejection verdict and must-fix list
- `transcripts/4.json` — loose source transcript, single source of truth for transcript evidence
- `aggregation-report.md` — how the current proposal was assembled
- `findings/chunk-NN-findings.json` and `chunks/chunk-NN.md` — evidence trail

Source media is available at:

`E:\Brock Red\Brock Red Blue versus Crystl.mp4`

Your job is to produce a corrected proposal that can be resubmitted to Codex.

## Verdict Context

Codex verdict: `REJECT`.

Reason: Round 1 caught many real false-starts and hallucinations, but the current promoted list is not safe. Several estimated cut boundaries remove real narration, and the final JSON contains an unresolved overlapping duplicate cut at `2724.84-2725.64`.

## Required Output

Write a corrected cut list to:

`C:\Programming\resolve-mcp\audio-checks\qa-cuts\proposed-cut-list-round2.json`

Use the same normalized schema as `proposed-cut-list.json`:

```json
[
  {
    "start_sec": 0.0,
    "end_sec": 0.0,
    "confidence": "high|medium|low",
    "type": "artifact|false_start|repetition|self_correction|stream_chat_acknowledgment",
    "reason": "..."
  }
]
```

Also write a short changelog to:

`C:\Programming\resolve-mcp\audio-checks\qa-cuts\round2-changelog.md`

The changelog must list:

- Every Codex must-fix item and how you handled it
- Any cut you verified with waveform/audio
- Any open issue you intentionally leave for Codex/human review
- Final count and total proposed source seconds removed

## Must-Fix Instructions

Apply these changes directly unless audio/waveform verification gives a concrete reason to choose a different safe boundary. If you deviate, document the evidence.

1. `348.60-349.80`
   - Modify to `349.36-349.44`.
   - Reason: remove only duplicated second `"ahead"` from seg 44. Current cut deletes real words from `"we're just gonna go ahead and use tackle"`.

2. `469.00-472.12`
   - Modify to `467.98-470.12`.
   - Reason: remove first abandoned `"simply predict that"` and preserve clean restart `"in fact i simply predict that..."`.

3. `487.20-488.12`
   - Modify to `485.68-488.12`.
   - Reason: remove whole transition phrase `"but i think"` so the splice lands cleanly: `"we'll just have to see. I think honestly..."`.

4. `504.44-505.20`
   - Modify to `504.44-504.52`.
   - Reason: remove only duplicated `"going"`. Current cut removes `"going to get that far"`.

5. `521.30-524.50`
   - Modify to `522.24-523.20`.
   - Reason: keep `"Violet City and if he"` and remove only the second duplicated `"and if he"`.

6. `640.00-641.60`
   - Modify to `640.88-641.20`.
   - Reason: remove only abandoned `"i'm gonna"`; current cut removes `"a second hit there"` and part of the move call.

7. `673.80-677.20`
   - Modify to `674.16-676.26`.
   - Reason: remove `"i think would just randomize between"` and preserve restart `"which would simply randomize between..."`.

8. `721.12-722.80`
   - Remove from the list.
   - Reason: genuine battle reaction pause after `"we once again miss"`; do not promote a LOW/editorial-discretion pause as an automatic cut.

9. `810.48-810.97`
   - Remove unless waveform verification proves an isolated non-speech artifact.
   - Transcript risk: seg 110 reads `"generation now there's no xp..."`; Whisper word timestamps put the range inside `"now"`/`"there's"`.

10. `1603.90-1604.20`
    - Remove unless waveform/audio verification finds a tighter safe duplicate-`we` cut.
    - Reason: duplicate `"we"` has zero-duration transcript timestamp; current cut likely removes `"can"` and creates `"now we tackle"`.

11. `1627.24-1628.60`
    - Remove from the list.
    - Reason: `"This time, no poison"` is real play-by-play and explains the next action.

12. `1744.88-1745.60`
    - Remove from the list.
    - Reason: `"I go tackle"` is genuine rapid battle narration.

13. `1747.34-1747.88`
    - Remove from the list.
    - Reason: `"Very nice"` is a genuine reaction to a meaningful Fury Cutter miss.

14. `2440.50-2441.15`
    - Modify to `2440.70-2441.78`.
    - Reason: the modification was proposed but not applied. Current boundaries risk clipping `"real"` and leaving a fragment of `"strategies"`.

15. `2713.40-2716.92`
    - Modify to `2713.40-2717.90`.
    - Reason: current dedupe winner is too short and leaves duplicated `"i will be coming back"`. The dropped chunk-9 boundary is the clean splice.

16. Overlap conflict:
    - Current cuts: `2722.73-2725.67` and `2724.84-2725.64`
    - Merge by modifying `2722.73-2725.67` to `2722.86-2725.64`
    - Remove `2724.84-2725.64`
    - Reason: final JSON must not contain overlapping ranges; the second cut is redundant after the modified first cut.

## Additional Checks

Codex confirmed these as clean; keep them unless you discover audio evidence contradicting them:

- `8.46-9.48`
- `57.62-78.17`
- `161.60-161.96`
- `945.34-945.40`
- `974.58-974.64`
- `1001.32-1002.72`
- `1089.00-1094.28`
- `1184.56-1187.36`
- `1215.88-1215.94`
- `1245.14-1247.94`
- `1273.98-1276.78`
- `1352.42-1352.58`
- `1962.77-1967.65`
- `2064.72-2065.13`
- `2273.38-2274.78`
- `2700.12-2702.40`
- `2824.66-2825.08`

Investigate these before resubmitting if time allows:

1. `1989.96-2016.76`
   - There is a 26.80s speechless gap between seg 247 and seg 248.
   - Verify source video/audio before deciding whether to add a cut. It may be meaningful gameplay evidence, not disposable dead air.

2. Old micro-cuts that rely on `WORDS_IN_CLIP(0)` claims:
   - `556.00-556.28`
   - `599.73-600.42`
   - `1778.85-1779.28`
   - `2325.30-2325.78`
   - `2692.58-2692.92`
   - If these have not already been waveform/audio verified, verify or mark them as requiring verification in the changelog.

## Validation Before Returning

Before you finish:

1. Ensure `proposed-cut-list-round2.json` is valid JSON.
2. Ensure every entry has `start_sec < end_sec`.
3. Ensure there are no overlapping ranges unless explicitly intentional and documented. Prefer no overlaps.
4. Recalculate total source seconds removed.
5. Confirm all 16 Codex must-fix items are addressed in `round2-changelog.md`.

Return only:

- Path to `proposed-cut-list-round2.json`
- Path to `round2-changelog.md`
- Final count and total removed seconds
- Any remaining open questions
