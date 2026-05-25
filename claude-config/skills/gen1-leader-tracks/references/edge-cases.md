# Edge cases

## Giovanni 1, 2, 3 — three distinct keys, three different treatments

The Giovanni encounter pattern in Red/Blue/Yellow:

| Encounter | Story context | Session-log key | Audio file | Intro video? |
|---|---|---|---|---|
| Giovanni 1 | Rocket Game Corner basement (Celadon) — first time you fight Giovanni | `GIOVANNI_1` | `Giovanni 1.mp3` | ✗ **NONE** |
| Giovanni 2 | Silph Co president's office (Saffron) — second fight | `GIOVANNI_2` | `Giovanni 2.mp3` | ✗ **NONE** |
| Giovanni 3 | Viridian Gym — third fight (the actual gym leader battle) | `GIOVANNI_GYM` | `Giovanni 3.mp3` | ✓ **Giovanni.mp4 / GiovanniBlue.mp4** |

The session log emits `GIOVANNI_1`, `GIOVANNI_2`, `GIOVANNI_GYM` as DISTINCT leader keys. The asset map treats them as three separate entries (not a shared "Giovanni" entry).

**Pretty names in marker labels:**
- `GIOVANNI_1` → `"Giovanni (R1)"` → marker `"Giovanni (R1) Battle Start"`
- `GIOVANNI_2` → `"Giovanni (R2)"` → marker `"Giovanni (R2) Battle Start"`
- `GIOVANNI_GYM` → `"Giovanni"` → marker `"Giovanni Battle Start"`

The skill's marker parser (`parse_marker_label`) uses these exact pretty names → leader_key reverse map. If the labels in `session_marker_labels.py` change upstream, update the `_PRETTY_TO_KEY` map in `place_leader_tracks.py`.

## Rival vs Champion — also distinct keys

The session log emits:
- `RIVAL` for the early-game rival battles (typically 2-3 rival encounters before champion)
- `RIVAL3` for the Champion battle (final boss after Elite 4)

The asset map:
- `RIVAL` → `Rival.mp3`, no intro video → Pattern B (A2 only)
- `RIVAL3` → `Champion.mp3` + `Champion.mp4`/`ChampionBlue.mp4` → Pattern A (full intro + audio)

`first_appearance_map` treats RIVAL and RIVAL3 as DIFFERENT keys, so each gets its own "first appearance" — i.e. the FIRST `RIVAL` battle gets Rival.mp3 with a fade-in, and the FIRST `RIVAL3` battle gets the full Champion intro treatment.

## Gave-up + switch crossfade — multiple cases

### Case 1: Same leader gave-up then immediately retried (e.g. Bugsy 1st attempt → Bugsy 2nd attempt)

- **NO leader change** → NO crossfade needed
- Battle gap insertion logic in the upstream pipeline may or may not insert a 60-frame gap (depends on whether it's classified as "gave up" — typically resets stay within the same battle window in the session log)
- A2 audio continues uninterrupted (or has its own internal fade if Resolve's clip edges are involved)

### Case 2: Different leader after gave-up (e.g. Bugsy gave-up → switch to Whitney)

This is the textbook gave-up + switch case described in audio-routing-spec.md §3. Full 60-frame crossfade in the gap region.

### Case 3: Trainer-switch WITHOUT gave-up (just a sequence boundary)

- This happens at the END of one battle's natural Finish marker and START of the next battle's Start marker
- If the markers are CONSECUTIVE (no gap) → standard A2 fade-out + A2 fade-in at the boundary (no special gap-region crossfade needed; the per-clip fades handle it)
- If there's some natural gap (e.g. 30 seconds of travel between battles) → leader audio fades out naturally at battle end; general BGM may fill the gap (if gen1-edit-timeline has a between-battles BGM step)

The skill's `detect_gap_between` function uses a 65-frame tolerance window to identify gap-region crossfade candidates. Larger gaps (multi-second travel) don't trigger the gap-region crossfade; they get standard per-clip fade-in/out only.

## Version edge cases

### `--version` not set + no session log found
- Skill errors out: cannot guess version. User must pass explicit `--version yellow|red_blue`.

### meta.json `version` field unrecognized
- Falls back to None; same error as above. User passes explicit override.

### Leader present in session log but no asset in either version
- Currently no such case (all 16 keys in the asset map have audio at minimum)
- If a future leader is added (e.g. a new Elite 4 member in a fan ROM hack), the skill will warn `unknown leader_key=XYZ — skipped` and continue

## Asset path edge cases

### `--rby-root` points at the wrong location
- Skill validates `rby_root.is_dir()` and errors out if not
- Common gotcha: user has RBYNewLayout at `F:\Programming\` instead of `C:\Programming\` (the FileOrganizer hardcoded `F:\` for this reason). Pass `--rby-root F:\Programming\RBYNewLayout` to override.

### Asset file moved/renamed after last update
- `resolve_video_filename` checks `.exists()` before returning a filename — if missing, returns None and the skill warns "audio/video file missing" and skips the placement
- Re-run `leader_asset_map.py` smoke test to verify all expected files resolve correctly: `python C:\Users\teope\.claude\skills\gen1-leader-tracks\scripts\leader_asset_map.py`

## Marker pairing edge cases

### `Battle Start` without matching `Battle Finish`
- Last battle in a session may not have a Finish marker if the recording ended mid-battle
- Skill warns and SKIPS that battle's audio (can't determine duration)
- Workaround: manually add a Battle Finish marker at the end of V1, then re-run

### Multiple `Battle Start` for the same leader before any `Battle Finish`
- Indicates the session log is malformed (debounce should prevent this)
- Skill matches each Start with the next available Finish for the same leader — extras at the end of the Start list have no Finish, get skipped
- Investigate the session log if this happens

### Markers from a different recording mixed into the timeline
- If the user manually placed markers OR ran gen1-marker-pipeline against the wrong session log, the marker labels may not match the actual battles
- The skill takes marker labels at face value — garbage in, garbage out
- Best practice: clear all green markers via `clear_green_markers.py`, re-run gen1-marker-pipeline phase 2 with the correct `--session`, then re-run this skill

## Jessie and James — not yet wired up

`Jessie and James.mp3` exists in the audio folder but the skill doesn't currently detect when to place it:

- Session log doesn't have a clear `Team Rocket grunt encounter` event (verified on Victreebel run: 0 such events)
- Possible detection rule: any `battle:battle-start` with `data.from` or `data.trainer` containing "ROCKET" or "JESSIE" or "JAMES" — TBD per-recording

When implemented, gated by `--enable-jessie-grunts` flag (off by default).

## Victory.mp3 timing

The `champion:beat-champion-flag` event timestamp is the moment the player BEAT the champion (NOT the start of the Victory fanfare in-game). The Victory.mp3 audio should ideally:
- Start playing IMMEDIATELY at the event timestamp
- Fade in 0.5s
- Continue for ~30-60s during the post-champion sequence
- Fade out at the start of the outro

Currently the skill places it crudely as "at the event ts, on A2, with 0.5s fade-in". Refinement opportunities for v2:
- Detect end of Champion-related events (member-carousel-started? final-tierlist-podium-shown?) and crossfade Victory → next BGM at that boundary
- Adjust placement to align with a visual cue (the in-game Victory text appears N frames after the actual KO; could probe via ffprobe + frame extraction if a future enhancement)
