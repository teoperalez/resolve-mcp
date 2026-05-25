---
name: SRC_OVERLAP_PREV cuts remove words from BOTH copies
description: The cut-analyzer SRC_OVERLAP_PREV heuristic was wrong — flagging the overlap range removes those source frames from both overlapping clips, deleting the words entirely instead of just removing the duplicate playback.
type: reference
project: resolve-mcp
originSessionId: d67a4cf0-ef49-42f3-87a4-44f400894785
---
## The bug

The cut analyzer (`scripts/mark_cut_candidates.py`) used to flag `SRC_OVERLAP_PREV` as a HIGH-confidence cut, with the reasoning *"X seconds of source frames play TWICE — cut the overlap, the OTHER copy still plays."*

That reasoning is wrong. `apply_cuts_to_fcpxml.py` works on **source-frame ranges**, not per-clip-instance. When you flag a cut at the overlap range:

- Clip N-1 (whose tail covers that range) gets `trim_end` applied → loses those frames from its tail.
- Clip N (whose head covers that range) gets `trim_start` applied → loses those frames from its head.
- Both copies of the words inside that range get removed.

## The proof

In Misty Red v5 dialogue review, cut at source 342.92-343.62 was tagged SRC_OVERLAP_PREV=0.70s. Source words inside that range:

- 342.90-343.12  ' number'
- 343.12-343.42  ' two'

After the cut, the rendered audio went from *"...rival number two for now though..."* to *"...rival for now though..."* — both copies lost. Same bug for cut at 1006.23-1007.0 which lost *"his bayleaf"*.

## What `apply_cuts_to_fcpxml.py` actually does (per-clip overlap handling)

For each spine position, it computes overlap between the clip's source range `[src_start, src_end)` and each cut range `[cs, ce)`. Action chosen:

- cut covers entire clip → DELETE
- cut covers head only (`cs <= src_start, ce < src_end`) → TRIM_START (clip plays `[ce, src_end)`)
- cut covers tail only (`cs > src_start, ce >= src_end`) → TRIM_END (clip plays `[src_start, cs)`)
- cut interior subset → SPLIT into two pieces

For two adjacent clips with overlapping source ranges, the same cut range hits both: TRIM_END on the prior clip + TRIM_START on the next. The overlap "duplicate playback" still gets eliminated, but the underlying audio of those frames is gone from the timeline entirely.

## Current status

- Cut analyzer prompt updated (`mark_cut_candidates.py` line ~469): **do not flag SRC_OVERLAP_PREV cuts.** Leave the duplicate playback. Mildly awkward, doesn't lose words.
- The two SRC_OVERLAP cuts in `cut-analysis-4.out.md` were reverted (2026-05-15).

## If we ever want to fix it properly

Two paths:

1. **Fix upstream battle-gap insertion** to not produce overlapping source ranges in the first place. The overlap was introduced when extending V1 clips to fill battle gaps without first capping the pull at the gap-to-prev distance.

2. **Add a clip-instance-targeted cut format** to the analyzer + apply step. Instead of `(start_sec, end_sec)` source-frame range, use `(clip_index, "trim_start" | "trim_end", duration_sec)` for SRC_OVERLAP fixes. apply_cuts would need to recognize this and only modify the named clip instance, not pattern-match the source range against everyone.

Path 1 is cleaner. Until either is done, leave SRC_OVERLAP audio as-is.

## Rule of thumb when flagging cuts

Cuts are SOURCE-FRAME ranges. Anywhere those source frames appear in any clip on the timeline gets cut. If two clips legitimately need to play the same source frames (e.g. via overlap from upstream processing), DO NOT flag the source range — you'll cut both. Flag only source ranges that should never appear anywhere on the timeline.
