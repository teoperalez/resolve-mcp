# Codex Adversarial Review — Brock Red Cut Analysis (Round 1)

**Date:** 2026-05-17
**Reviewer:** Codex (you)
**Subject:** Proposed cut list for `Brock Red Blue versus Crystl.mp4` (Pokémon Crystal challenge run, 47:23, 60fps)
**Stake:** The previous cut list (13 entries, ~13.6s removed) shipped a video with a **20-second on-camera duplication** — the streamer's opener "This is Brock. Brock likes rocks." played twice. That fix was patched by hand. This round is the systematic re-analysis to catch every similar miss before the next render.

---

## 1 — Your job

Independently audit the proposed cut list in **`audio-checks/qa-cuts/proposed-cut-list.json`** against the loose-source transcript **`transcripts/4.json`** and report:

1. **MISSED cuts** — places where the streamer false-started, repeated a take, abandoned a thread, or had >2s of empty audio that should be cut. The list below was produced by 11 parallel Sonnet subagents each scanning a 5-min window — they may have missed things across chunk boundaries OR in their own windows.
2. **FALSE-POSITIVE cuts** — entries in the proposed list that would strip legitimate narrative content. Read ±10s of transcript around each proposed cut; if the cut removes a non-redundant word/sentence/transition that advances the narrative, REJECT it.
3. **BAD BOUNDARIES** — cuts whose `start_sec` or `end_sec` lands mid-word, or splits an atomic-numbered-reference (e.g. "Rival 2", "level 14 Onix", "five full heals"), or removes a noun's number/ordinal.
4. **SCHEMA / DATA-INTEGRITY issues** — JSON malformed, src ranges outside [0, 2840.32]s, ranges where `end_sec ≤ start_sec`, overlapping ranges that aren't intentional merges.

Return your verdict as one of:
- **PASS** — zero must-fix items. List of confirmed-good cuts attached.
- **MINOR_FIXED** — you applied trivial fixes yourself (formatting, mid-word boundary nudges within ±0.3s) and re-verified clean. List what you fixed.
- **REJECT** — surgical must-fix list. Each entry: rubric criterion violated, evidence (src range + transcript segment index + transcript text quoted), concrete proposed action (REMOVE cut / MODIFY boundaries to <new range> / ADD missed cut at <new range>).

If REJECT, the planner (Claude) iterates with another subagent pass focused on your must-fix list, then resubmits.

---

## 2 — Files to read (absolute paths)

All paths are on `C:\Programming\resolve-mcp\` unless noted.

### Input transcript (single source of truth)
- **`transcripts/4.json`** — `faster-whisper large-v3` with `condition_on_previous_text=False, no_repeat_ngram_size=0, beam_size=5` (the "loose source" Whisper run that keeps false-starts visible). 350 segments, 2840.32s total. Word-level timestamps included.

### The cut list under review
- **`audio-checks/qa-cuts/proposed-cut-list.json`** — 42 entries (29 new + 13 from prior pass, with 2 MODIFY recommendations attached). This is the file to audit.

### Per-chunk subagent findings (the evidence trail)
- **`audio-checks/qa-cuts/findings/chunk-NN-findings.json`** (NN = 00..10) — each Sonnet subagent's output. Schemas vary slightly across subagents (some used `start_sec`/`end_sec`, others `src_start`/`src_end`, others `cut_start`/`cut_end`, others `start`/`end`) — the aggregator normalized these.
- **`audio-checks/qa-cuts/aggregation-report.md`** — dedupe events, existing-cuts-review reconciliation (where two subagents disagreed about KEEP/MODIFY).

### Per-chunk transcript slices (5-min windows w/ 30s overlap)
- **`audio-checks/qa-cuts/chunks/chunk-NN.md`** (NN = 00..10) — what each subagent was given. Includes word-level timestamps for the overlap regions (±30s).

### Reference materials (read these before judging)
- **`C:\Users\teope\.claude\projects\C--Programming-resolve-mcp\memory\reference_default_whisper_hides_false_starts.md`** — why the loose transcript is the right baseline (default Whisper merges duplicates silently)
- **`C:\Users\teope\.claude\projects\C--Programming-resolve-mcp\memory\reference_pokemon_name_normalizer.md`** — Pokémon vocabulary the analyzer must not split
- **`C:\Users\teope\.claude\projects\C--Programming-resolve-mcp\memory\reference_audio_verify_borderline_cuts.md`** — protocol for verifying borderline cuts via ffmpeg + large-v3 re-transcribe
- **`C:\Users\teope\.claude\projects\C--Programming-resolve-mcp\memory\feedback_src_overlap_cut_bug.md`** — `src_overlap_prev` cuts forbidden
- **`C:\Users\teope\Teo Speech Style.md`** §9.4 — atomic-numbered-references travel as one unit

### Battle anchors (cuts must not chop a battle window)
- **`transcripts/battles.json`** — 6 battles, source seconds: Rival 1 @ 341.47, Honest Abe @ 538.14, Falkner @ 622.97, Jamesy Proton @ 1048.46, Bugsy @ 1340.98, Rival 2 @ 2390.53.
- **`transcripts/battle-types.json`** — types (rival/gym/other)
- **`plans/prompts/battle-ends-refine-Brock_Red_Blue_versus_Crystl.out.md`** — refined battle-end source-seconds

### The current "ground truth" cuts file (the one that ships to apply_cuts)
- **`plans/prompts/cut-analysis-4.out.md`** — the 13-entry file the v1 render used. Will be replaced by `proposed-cut-list.json` (re-formatted to schema) once you approve.

---

## 3 — Methodology (so you can reproduce + check)

### Step A — Chunking
Loose transcript split into 11 × 5-min windows with 30s overlap on each side:
```
chunk 00:  0.00 -  300.00s    (segs 0-36)
chunk 01: 270.00 -  570.00s   (segs 31-76)
chunk 02: 540.00 -  840.00s   (segs 72-111)
chunk 03: 810.00 - 1110.00s   (segs 110-132)
chunk 04: 1080.00 - 1380.00s  (segs 128-152)
chunk 05: 1350.00 - 1650.00s  (segs 147-198)
chunk 06: 1620.00 - 1920.00s  (segs 191-239)
chunk 07: 1890.00 - 2190.00s  (segs 239-266)
chunk 08: 2160.00 - 2460.00s  (segs 264-296)
chunk 09: 2430.00 - 2730.00s  (segs 292-332)
chunk 10: 2700.00 - 2840.32s  (segs 328-349)
```
Each chunk file includes segments + word-level timestamps for the overlap regions, so subagents could verify cross-chunk-boundary repeats.

### Step B — Parallel Sonnet subagents
Each chunk dispatched to ONE Sonnet subagent with this rubric:
1. False starts / abandoned threads
2. Repeated takes (3+ word phrase, ≤30s apart, silence between repeats)
3. Self-correction markers ("I mean", "actually", "no wait", "let me", "OK so", "scratch that", "back up")
4. Empty / silent runts (gaps 0.5-1.5s = likely CUT; 1.5-2.0s borderline; >2.0s natural transition KEEP)
5. Atomic-numbered-reference check on EXISTING cuts (verify no boundary lands between a noun and its number/ordinal)

Each subagent received:
- Its chunk's transcript file
- The list of EXISTING cuts in its window (so it wouldn't re-discover them)
- Instructions to write JSON findings + return a summary

### Step C — Aggregation (this run's output)
Script `audio-checks/qa-cuts/aggregate.py` merged the 11 findings:
- 31 raw new cuts → 29 deduped (2 overlap-region duplicates collapsed: one at chunk-3/4 boundary @ 1088-1094s "even" 5.46s span, one at chunk-9/10 boundary @ 2713s false start)
- 13 existing cuts → 11 KEEP, 2 MODIFY, 0 REMOVE
- **42 final unified cuts** removing ~77.76s of source time (was ~32.92s in original list)

### Step D — Cross-boundary scan
Within each chunk, the subagent had word-level timestamps for the ±30s overlap regions. Cross-chunk repeats beyond 30s were not systematically checked. **If you find repeats > 30s apart, that's a method gap worth flagging.**

---

## 4 — Specific concerns the subagents raised (please verify)

### 4.1 — Whisper "Thank you." hallucinations (high confidence, but verify)
The Slowpoke Well + post-Proton + pre-Bugsy silent-travel section has **8 isolated "Thank you." segments** flagged as Whisper hallucinations triggered by ambient game audio:
- seg 0 [8.46-9.48] — "Thank you." at video start (chunk 00 flagged this)
- seg 118 [945.34-945.40] — 0.06s sub-frame hallucination (chunk 03)
- seg 119 [974.58-974.64] — 0.06s sub-frame hallucination (chunk 03)
- seg 120 [1001.32-1002.72] — 1.40s hallucination (chunk 03)
- seg 139 [1184.56-1187.36] — 2.80s hallucination (chunk 04)
- seg 140 [1215.88-1215.94] — 0.06s sub-frame (chunk 04)
- seg 141 [1245.14-1247.94] — 2.80s hallucination (chunk 04)
- seg 142 [1273.98-1276.78] — 2.80s hallucination (chunk 04)
- seg 269 [~2273s] — 2.8s borderline KEEP (subagent kept as social interrupt — please verify)

**Audit question:** are all 8 truly hallucinations? Listen to the source audio at each timestamp if you can (the source MP4 is at `E:\Brock Red\Brock Red Blue versus Crystl.mp4` — but Codex sandbox may not reach it; if you can't decode the video, judge from context). If the streamer ever genuinely says "thank you" to a donor mid-stream, the cut would lose that.

### 4.2 — Existing cut MODIFY recommendations (2 cases)
- `2440.50 → 2441.15` (artifact) → proposed `2440.70 → 2441.78` (chunk-8 found both edges mid-word per Whisper word-timestamps)
- `2722.73 → 2725.67` (false_start) → proposed `2722.86 → 2725.64` (chunk-10 found both edges 3-30ms mid-word; chunk-9 said KEEP — disagreement; chunk-10's word-timestamp evidence is more specific)

**Audit question:** Whisper word-timestamps can be off by 100-400ms per `reference_whisper_word_timestamps_unreliable.md`. Should we trust them as ground truth for the modifications, or stick with original boundaries?

### 4.3 — Redundant cut overlap (need merge)
- `2722.73 → 2725.67` (existing, MODIFY proposed to 2722.86-2725.64)
- `2724.84 → 2725.64` (new, chunk-10) — chunk-10 explicitly said "if MODIFY is applied, drop this new cut"

The aggregator did NOT auto-merge. Two cuts in the final list overlap. Codex must decide: apply MODIFY + drop new (subagent's preference), or keep both as-is.

### 4.4 — Low/medium confidence cuts the editor may want to KEEP
- `721.12 → 722.80` (LOW, 1.68s) — "after we once again miss" — possibly intentional dramatic pause
- `1603.90 → 1604.20` (MEDIUM) — "we we can tackle" stutter, no word-level timestamps to bound precisely
- `1744.88 → 1745.60` (MEDIUM, 0.72s) — "I go tackle." — genuine narration beat
- `1747.34 → 1747.88` (LOW, 0.54s) — "Very nice." — genuine reaction
- `504.44 → 505.20` (MEDIUM) — "going going" stutter, no word-level timestamps

**Audit question:** which of these should be downgraded to REJECT (false-positive) vs kept as is?

### 4.5 — Method gap: cross-chunk repeats > 30s apart
The 30s overlap caught adjacent-chunk repeats. Repeats spanning 60+ seconds across non-overlapping chunks were not systematically scanned. **If Codex finds a phrase repeated 1+ minute apart, that's a missed cut category.**

### 4.6 — Unverified large gaps in chunks 07
- chunk-07 flagged a 26.8s silent gap at 1989.96-2016.76 (between segs 247-248) as potentially cuttable but didn't propose a cut. Verify: if it's dead air with no game-relevant content, it should be cut. The auto-editor should have removed pure silence already, so this gap may represent gameplay that's intentionally there.

---

## 5 — Out of scope (please don't flag)

- Pokémon-name normalization corrections (separate pipeline — `audio-checks/qa-v6/pokemon_normalizer.json`)
- Audio waveform analysis beyond what's in the loose transcript (we don't have the audio in this loop)
- Timeline-frame math for `apply_cuts_to_fcpxml.py` (that's a separate verification step after Codex approves)
- The intro/outro retime decisions (handled elsewhere)
- Battle marker placement (handled elsewhere)

---

## 6 — Output format Codex should return

A single JSON object written to `audio-checks/qa-cuts/codex-review.md` (next to this file), schema:

```json
{
  "verdict": "PASS | MINOR_FIXED | REJECT",
  "summary": "1-2 sentence overall judgment",
  "must_fix": [
    {
      "category": "missed_cut | false_positive | bad_boundary | schema",
      "severity": "blocker | high | medium",
      "src_range": "X.XX-Y.YY (or N/A for schema issues)",
      "transcript_evidence": "segment index + quoted text from transcripts/4.json",
      "action": "ADD <new range> | REMOVE <existing range> | MODIFY <existing range> to <new range>",
      "rationale": "1-3 sentences"
    }
  ],
  "minor_fixed_applied": [
    {"what": "...", "where": "...", "why_minor": "..."}
  ],
  "confirmed_clean": [
    "src_range — brief rationale"
  ],
  "open_questions_for_claude": [
    "..."
  ]
}
```

If REJECT, the planner spawns another Sonnet round focused on your must-fix list, then resubmits to you. We iterate until you return PASS.

---

## 7 — Round 1 stats

- **Subagent passes:** 11 (one per 5-min chunk)
- **Raw cuts proposed:** 31 new + 13 existing reviewed = 44 entries
- **After dedupe:** 42 final unified cuts
- **Total source seconds proposed for removal:** ~77.76s (vs 32.92s in v2 cut list — adding ~45s of removed content)
- **Highest-value finds:** opener TAKE 1 (20.55s, already in v2), Whisper "Thank you" hallucination cluster (~16s across 8 segments), "anyway that's gonna do it" outro repeat (2.28s), "with a johto version" → "with a gen 2 version" outro self-correction (3.52s), "randomize between which i think would just randomize between" mid-Falkner-explanation self-correction (3.4s)
- **Confidence distribution:** 27 HIGH / 9 MEDIUM / 1 LOW / 5 inherited from prior pass (all HIGH)

---

**End of brief.** Begin review by reading `proposed-cut-list.json` and `transcripts/4.json`, then walk each entry. Return JSON to `audio-checks/qa-cuts/codex-review.md`.
