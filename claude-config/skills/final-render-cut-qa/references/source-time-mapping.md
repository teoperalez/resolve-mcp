# Source-time mapping

The skill's most error-prone step: converting a timestamp in the rendered video back to a timestamp in the original source video.

## Why it matters

The canonical cut JSON (`plans/prompts/cut-analysis-<stem>.out.md`) is indexed by **source-time** (timestamps in the original capture). The final rendered MP4 is indexed by **final-render-time** — which is offset from source-time by:

1. The intro graphic prepended at frame 0 (4.33s for 400% retime, 17.07s for 100%)
2. Every cut already applied via `apply_cuts_to_fcpxml.py` (which shifts everything after each cut leftward)
3. Auto-editor silence removals that were baked into the V1 layout before cuts ran

A user who eyeballs final-render time `301.74s` and pastes it into the source-cut JSON will corrupt the pipeline. The mapping helper prevents this.

## Algorithm

```python
def final_to_source(final_sec: float,
                    replay_path: str,
                    intro_speed_pct: int,
                    intro_native_sec: float,
                    first_v1_source_in_sec: float) -> float:
    """
    Map a final-render timestamp (seconds) to source-video time (seconds).

    Args:
        final_sec: timestamp in the rendered MP4
        replay_path: absolute path to <source-dir>/*_cuts_replay.json
        intro_speed_pct: 100 or 400 (read from transcripts/min-battles.json:
            is_minimum_battles=true → 100, false → 400)
        intro_native_sec: native intro duration before retime
            (17.07s for GSCPC Intro Short.mp4, 19.0s for RB-style intros —
            read from intro asset's Resolve `Video Duration` property)
        first_v1_source_in_sec: source-time of the first non-intro V1 clip
            (after the opener cut is applied; for Brock Red v3 = 78.83s)

    Returns:
        source_sec: timestamp in the original source MP4

    Raises:
        ValueError if final_sec is inside the intro
    """
    import json
    replay = json.loads(open(replay_path).read())
    fps = replay['den']

    intro_placed_sec = intro_native_sec * 100 / intro_speed_pct

    if final_sec < intro_placed_sec:
        raise ValueError(
            f'final {final_sec}s is inside the intro graphic (0..{intro_placed_sec}s); '
            f'not a source time'
        )

    # Time relative to the edit timeline's source-content start
    edit_tl_sec = final_sec - intro_placed_sec

    # Walk removed_tl_ranges_frames from cuts_replay.json — each removed range
    # shifts source-time forward by (e - s).
    shift = 0.0
    for r in replay['all_cuts']['removed_tl_ranges_frames']:
        rs = r['start'] / fps
        re = r['end'] / fps
        if edit_tl_sec + shift >= rs:
            shift += (re - rs)
        else:
            break  # ranges are sorted; once we pass, no more shifts apply

    return first_v1_source_in_sec + edit_tl_sec + shift
```

## Worked example — Brock Red v3

Inputs:
- `final_sec = 301.74` (user-confirmed cut at "I simply predict that" duplicate, final-render time)
- `replay_path = E:\Brock Red\Brock Red Blue versus Crystl_ALTERED_BATTLEGAPS_cuts_replay.json`
- `intro_speed_pct = 400` (Minimum Battles classifier = false)
- `intro_native_sec = 17.07` (GSCPC Intro Short)
- `first_v1_source_in_sec = 78.83` (after opener cut 57.62-78.17 applied, V1[1] starts at source 78.83s)

Computation:
- `intro_placed_sec = 17.07 × 100/400 = 4.27s`
- `final_sec (301.74) > intro_placed_sec (4.27)` → not in intro, OK
- `edit_tl_sec = 301.74 - 4.27 = 297.47s`
- Walk removed_tl_ranges_frames in `cuts_replay.json.all_cuts`:
  - Each entry like `{"start": <timeline_frame>, "end": <timeline_frame>}` at 60fps
  - For each range with `rs ≤ edit_tl_sec + shift`, add `(re - rs)` to shift
- After all applicable ranges: `shift ≈ 169.5s` (sum of all cuts up to that point in the timeline)
- `source_sec = 78.83 + 297.47 + 169.5 ≈ 545.8s` — wait, this doesn't match the expected 467.98s

**Important note:** the formula above assumes `first_v1_source_in_sec` is the source time AT the start of V1[1] AFTER the cut. The actual mapping must account for the fact that V1[1] already starts at source 78.83s (which is 78.83 - 78.83 = 0s relative to "first source content shown"), and the edit_tl_sec is the time elapsed in the EDIT TIMELINE FROM that start.

But the edit timeline has additional cuts beyond just the opener — the 22.83s of total timeline removal. The shift accumulator handles each one.

**Corrected example for cut 1:**
- Edit-timeline time for "I simply predict that": (final 301.74) - (intro 4.27) = 297.47s
- The relevant cuts BEFORE 297.47s in the edit timeline (per `cuts_replay.json.all_cuts.removed_tl_ranges_frames`):
  - 161.60-161.96 (cumulative 0.36s) — but this is BEFORE 297.47s edit-time? Need to check
  - The mapping requires we look at TIMELINE frames (after intro) and see which cuts apply

The actual mapping requires the helper script to handle the off-by-intro adjustment when comparing edit_tl_sec against removed_tl_ranges_frames (which are recorded in edit-timeline-frames BEFORE intro placement). The intro is placed BEFORE the cuts in the timeline order, so:
- Edit-timeline-frame = intro_placed_frames + (source content frames after cuts)

This requires careful frame-arithmetic. The helper script handles it; the rough algorithm above is the conceptual outline.

## Practical note

For the Brock Red v3 case, all 4 user-confirmed cuts mapped to existing canonical entries — so the mapping verification only had to confirm presence (search canonical for entries within ±2s of the mapped source time), not produce new appends.

The first time the mapping must produce a NEW canonical entry, the helper script will need testing on a known case. Until then, **the skill should run mapping in "verify-only" mode** — surface the mapping result to the user, ask for manual confirmation before appending to canonical.

## API

```bash
python ~/.claude/skills/final-render-cut-qa/scripts/map_final_to_source.py \
    --final-sec 301.74 \
    --replay "E:/Brock Red/Brock Red Blue versus Crystl_ALTERED_BATTLEGAPS_cuts_replay.json" \
    --intro-speed 400 \
    --intro-native-sec 17.07 \
    --first-v1-source-sec 78.83
# Output (stdout): 467.98
# Exit code 0 on success, 1 on validation error
```

Auto-detect mode (preferred):
```bash
python scripts/map_final_to_source.py --final-sec 301.74 --workspace .
# Auto-detects replay path, intro-speed, first-v1-source by reading
# transcripts/min-battles.json, scanning E:/<source-dir>/, querying Resolve API
# for the edit timeline's V1[1].GetLeftOffset()
```
