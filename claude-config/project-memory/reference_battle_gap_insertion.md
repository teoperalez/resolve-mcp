---
name: Battle gap insertion requires delete-and-rebuild — Resolve API can't ripple-insert
description: The "extend V1 backward into the gap" pattern lives in IRLPC Hyperframes apply_cuts_to_fcpxml.mjs; resolve-mcp's runtime equivalent must rebuild V1 + audio tracks
type: reference
originSessionId: fdcb3861-fc35-47c6-990f-ddc3ccd0f436
---

The DaVinci Resolve Python API does NOT support ripple-insert into an existing timeline. `MediaPool.AppendToTimeline()`:
- Without `recordFrame` → appends to the END of the timeline (the bug that broke `scripts/insert_battle_gaps.py`)
- With `recordFrame` → places at the specified position, but returns a TimelineItem in mid-air when the position is already occupied — the new clip doesn't visibly land and the timeline is unchanged

## Canonical workflow (IRLPC Hyperframes)

`C:\Programming\IRLPC Hyperframes\scripts\apply_cuts_to_fcpxml.mjs` solves this at the FCPXML level (BEFORE Resolve imports the timeline). For each battle, the VIDEO ref's battle clip is **back-filled** — its `start` (source in-point) is pulled BACKWARD by `gap_frames`, its `duration` grows by the same amount, and its timeline offset is also pulled back. All subsequent clips on every track are shifted forward by the cumulative gap amount. AUDIO refs are shifted forward only (no extension) so audio is naturally silent in the new pre-roll slot.

Key code at lines 506-541:

```javascript
// On the VIDEO ref we BACK-FILL the gap by extending the BATTLE clip backward
if (ref === videoRef) {
  const padU = shift - prevShift;  // gap introduced by THIS battle
  if (padU > 0) {
    const available = startU;
    const pull = Math.min(padU, Math.max(0, available));
    shiftedOffsetU -= pull;
    startU -= pull;
    durationU += pull;
  }
}
```

The marker for each battle ends up at `b.offsetU + i * battleGapFrames` (post-shift position).

## Runtime equivalent for resolve-mcp

To do the same thing via Resolve's Python API at runtime (no FCPXML round-trip):

1. Capture all V1 clip info: `mpi`, `src_in = GetLeftOffset()`, `src_dur = GetDuration()`, `tl_start = GetStart()`.
2. For each battle, find the V1 clip containing the battle's TL frame; mark it `is_battle`.
3. Compute new positions:
   - Battle clip's `pull = min(gap_frames, src_in)` (back-fill cap)
   - Battle clip's `new_src_in = src_in - pull`, `new_src_dur = src_dur + pull`, `new_tl_start = tl_start + cumulative_shift - pull`
   - Non-battle clips after a battle: `new_tl_start = tl_start + cumulative_shift`, source unchanged
   - `cumulative_shift += pull` after each battle
4. Capture the SAME info for every audio track (A1, A2, etc. that has clips), but those get shifted only (no back-fill).
5. `tl.DeleteClips(all_clips)` for V1 and each audio track.
6. `pool.AppendToTimeline([...])` to rebuild with new positions. Each spec has `mediaPoolItem`, `startFrame`, `endFrame`, `recordFrame`, `trackIndex`, `mediaType`.
7. For each battle: `tl.AddMarker(rel_frame, 'Orange', name, desc, 1, '')` where `rel_frame = new_tl_start - tl.GetStartFrame()`.

## Marker conventions (also IRLPC-validated)

From `C:\Programming\IRLPC Hyperframes\scripts\resolve_set_markers.py`:

- `Timeline.AddMarker(frame_id, ...)` returns False if a marker already exists at that frame → retry with `frame + 1`.
- For clip-level mirror: `clip_frame = leftOffset + (timeline_frame - clip_start)`. If the resulting frame is at `lo` or `lo+1`, Resolve hides it under the clip-edge chrome — nudge to `lo + 2` minimum, and if `TimelineItem.AddMarker` returns False (collision with an existing source-media marker), retry nudging forward by 1, up to 30 attempts.
- When clearing markers: also walk every V1 clip's `GetMarkers()` and `DeleteMarkerAtFrame` so re-runs don't silently no-op.

## Why this matters for the resolve-mcp orchestrator pipeline

The previous `insert_battle_gaps.py` silently appended all 8 "gap" clips to the END of the timeline because it omitted `recordFrame`. Adding `recordFrame` doesn't actually insert — Resolve returns a hollow TimelineItem object that never makes it onto the timeline. The only working approach is delete-and-rebuild (or FCPXML round-trip). Never claim "8 extended" again without verifying V1 clip count went up by 8 AND the inserts are at the expected timeline positions.
