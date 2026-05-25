# Cut aggregation report

## Input: 11 chunks -> 31 raw new cuts

## After dedup: 29 unique new cuts
## Existing cuts: 13; after review: 11 KEEP, 2 MODIFY, 0 REMOVE

## Final cut count: 42

## Total seconds proposed for cutting: 77.76s (was 32.92s in original cut-analysis-4.out.md)

---

## Dedupe events

- **KEPT** [chunk-4] 1089.00-1094.28 (artifact, HIGH)
  **DROPPED** [chunk-3] 1088.82-1094.28 (artifact, high)
  Rule: tighter cut wins

- **KEPT** [chunk-10] 2713.40-2716.92 (false_start, high)
  **DROPPED** [chunk-9] 2713.40-2717.90 (false_start, high)
  Rule: tighter cut wins

---

## Existing-cuts review

- `57.62 -> 78.17` (false_start, high) — **KEEP** (reviews: 1)
  [chunk-0] KEEP: Correctly identifies segs 1-2 [57.62-61.94] 'This is Brock. Brock likes rocks.' as TAKE 1 of the intro, with the clean TAKE 2 at segs 3-4 [78.18-81.20]. End boundary 78.17 lands just before seg 3 starts at 78.18 — clean. No atomic numbered references cross either boundary.

- `172.75 -> 173.05` (artifact, high) — **KEEP** (reviews: 1)
  [chunk-0] KEEP: 0.30s breath/pause between seg 18 [166.18-172.12] 'to find out how far Brock could actually get in Pokemon Crystal' and seg 19 [172.82-178.54] 'with no experience...'. Neither boundary falls inside an atomic numbered reference. Correct artifact cut.

- `258.57 -> 259.05` (artifact, high) — **KEEP** (reviews: 1)
  [chunk-0] KEEP: 0.48s breath inside seg 29 [255.64-261.98] between 'defense curl or' and 'bide in'. Neither 'defense curl' nor 'bide' is a numbered atomic reference. The cut correctly removes dead air mid-sentence. Boundaries are safe.

- `556.00 -> 556.28` (artifact, high) — **KEEP** (reviews: 1)
  [chunk-1] KEEP: Atomic-reference check passes: no noun+number phrase straddles either boundary. 'win this one' ends at ~555.280 and 'just to be as brock-like as possible' picks up cleanly. Word timestamps show 'but' running 555.280-556.120 and 'just' starting 556.120 — the cut at 556.00-556.28 falls within the 'but' word and the inter-word gap before 'just'. This suggests the cut targets a breath or glottal break embedded inside an elongated 'but'. The cut is only 0.28s and the labeled description ('breath between those phrases') is consistent with a held/broken 'but'. Flag for audio verification: if 'but' sounds clipped on output, extend cut start to 555.28 (remove the whole 'but') or shrink to 556.12 (preserve the whole 'but'). No atomic-reference violation either way.

- `599.73 -> 600.42` (artifact, high) — **KEEP** (reviews: 1)
  [chunk-2] APPROVE: Correctly removes a breath/pause artifact inside the seg 78-79 gap. Seg 78 ends 'start to become hard because' at ~599.96; seg 79 starts 'falkner knows' at 601.16. The cut at 599.73-600.42 clips the trailing breath after 'because'. No atomic-reference risk — 'falkner' as a proper noun is intact on both sides and the sentence context is preserved. Remainder of the gap (600.42-601.16, ~0.74s) is still present but acceptable as natural breath after 'because'. APPROVE as-is.

- `810.48 -> 810.97` (artifact, high) — **KEEP** (reviews: 2)
  [chunk-2] FLAG_FOR_AUDIO_VERIFY: Word timestamps for seg 110 show 'now' [809.500-810.640] and 'there's' [810.640-811.440]. The cut window 810.48-810.97 starts INSIDE the word 'now' (per Whisper timestamps) and ends inside 'there's'. Per memory note, Whisper word timestamps can be off by 100-400ms — so the actual throat-clear may genuinely fall in this gap and the word boundaries may be offset. However, the risk of mid-word clipping is real. Recommend re-extracting 809.0-812.0s audio and verifying visually/audibly that the throat-clear is isolated in 810.48-810.97 before committing. If 'now' onset is confirmed to end before 810.48, APPROVE; otherwise, trim cut start to 810.64 (Whisper 'now' end) to be safe. | [chunk-3] modify: The existing cut 810.48–810.97 lands mid-word: 'now' runs 809.500–810.640 per word-level timestamps, so a cut starting at 810.48 clips the back half of 'now' and a cut ending at 810.97 clips the front of 'there's' (810.640–811.440). The chunk-02 overlap requires removing the tail of whatever was said before seg 110's 'now.' The word 'generation' ends at 809.500. Recommended: cut 809.50–810.64 — this removes the full word 'now' (which is the repeated overlap word from chunk-02) and lands cleanly in silence before 'there's' begins at 810.640. Verify against chunk-02 findings to confirm 'generation' is the seam word.

- `1778.85 -> 1779.28` (artifact, high) — **KEEP** (reviews: 1)
  [chunk-6] CONFIRM: The cut falls inside seg 225 [1775.88-1782.10]: 'time because I want to check one last thing which is what if Brock was smart'. The described gap between 'thing' and 'is what' (0.43s) is a genuine silent pause mid-sentence — a natural breath-gap or false-start pause in delivery. No atomic numbered reference straddles this boundary ('one last thing' is not a numbered reference — 'thing' is a standalone noun, not a noun+number pair). No word from a named entity or ordinal is split. The cut removes dead air only; the sentence remains grammatically intact before and after: '...check one last thing [CUT] what if Brock was smart enough...'. CONFIRM with no modification needed.

- `1962.77 -> 1967.65` (artifact, high) — **KEEP** (reviews: 1)
  [chunk-7] CONFIRM: seg 243 ends at 1960.08, seg 244 begins at 1967.66. The cut window (1962.77–1967.65) falls entirely inside the 7.58s silent gap between those segments, ending 0.01s before the next speech onset. Clean artifact removal, no speech at risk.

- `2325.30 -> 2325.78` (artifact, high) — **KEEP** (reviews: 1)
  [chunk-8] APPROVE: 0.48s artifact mid-segment 278 ('poisons us so we might actually lose to this kakuna on that basis'). Word-level timestamps not provided for seg 278, but the segment spans 2320.22-2329.22 and the cut window is interior — consistent with a throat-clear or breath burst landing in a gap between clauses. No numbered references in seg 278. APPROVE as flagged.

- `2440.50 -> 2441.15` (artifact, high) — **MODIFY** (reviews: 1)
  [chunk-8] MODIFY: The cut intent is valid — 'strategies' is a redundant filler word given 'available to us' already appeared in seg 293. However both cut edges land mid-word per the provided timestamps. Extending to [2440.70, 2441.78] produces a clean splice: '...we don't have any real available to us here' — grammatically tight and the word boundaries are honored. No atomic numbered references involved.
  Proposed mod: {'start': 2440.7, 'end': 2441.78, 'rationale_for_change': "Word-level timestamps show 'real' ends at 2440.700 and 'strategies' spans 2440.700-2441.780. The original cut at 2440.50 starts 200ms BEFORE 'real' ends, clipping into that word. The original cut at 2441.15 ends 630ms BEFORE 'strategies' ends, leaving a trailing fragment of 'strategies' audible. The intended splice is 'don't have any real [cut] available to us here' — to achieve clean word boundaries the cut must be pushed to start no earlier than 2440.70 (after 'real') and extend to at least 2441.78 (after 'strategies' fully ends). Suggested: 2440.70-2441.78."}

- `2692.58 -> 2692.92` (artifact, high) — **KEEP** (reviews: 1)
  [chunk-9] KEEP: 0.33s silent gap inside the transition 'i don't know oh but it turns out' (segs 326-327). Word timestamps are not in the overlap window for this range but the segment boundary context confirms a clean artifact cut removing dead air. Duration (0.33s) and classification (silent gap) are correct.

- `2064.72 -> 2065.13` (false_start, medium) — **KEEP** (reviews: 1)
  [chunk-7] CONFIRM: Seg 253 contains '…really really really close but i but with that said i think'. The 0.41s cut excises the 'i but' stutter leaving '…close but with that said i think' — grammatically intact. No atomic-numbered reference in proximity. Clean false-start cut.

- `2722.73 -> 2725.67` (false_start, medium) — **MODIFY** (reviews: 2)
  [chunk-9] KEEP: Word timestamps for seg 331 confirm the cut boundaries are clean. 'but' ends ~2722.73 (word span 2722.18-2722.73), then silence before 'with his greater' (2722.86). The cut removes 'with his greater but' (2722.86-2724.84) and lands on the restart 'with' at 2725.64. No atomic-numbered-reference is split; 'his much improved team' is intact. Boundary sits in a silence gap, not mid-word. Valid false-start cut. | [chunk-10] MODIFY: The existing cut boundary at 2722.73 is mid-word on 'but' (2722.18-2722.86). Word timestamps from seg 331 confirm the word does not end until 2722.86. The end boundary 2725.67 is also 3ms past the word boundary at 2725.64. Correcting both endpoints to exact word boundaries preserves the intended cut while avoiding audible chops.
  Proposed mod: {'new_start': 2722.86, 'new_end': 2725.64, 'rationale': "Start 2722.73 falls inside the word 'but' (word span 2722.18-2722.86), causing a mid-word cut. Correcting start to 2722.86 (exact end of 'but' / start of 'with') lands cleanly at the word boundary. End 2725.67 is 30ms into 'with' (starts 2725.64) — correct to 2725.64 to avoid cutting the first phoneme of 'with'. Merged effect: removes 'with his greater but', retaining 'but with his much improved team'. The new_cut at 2724.84-2725.64 above is redundant if this modification is applied — apply the MODIFY and drop the new mid-clip cut."}
