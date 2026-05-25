# Audio routing — A3 + A2 layering with crossfades

The most distinctive Gen 1 behavior. The leader audio file is split across two tracks so the Fairlight preset can route them with different levels (A3 punchy during the dramatic intro, A2 standard during gameplay).

## §1 Track assignments

| Track | Content |
|---|---|
| **A1** | Dialogue (streamer voice) — untouched by this skill |
| **A2** | Battle music — leader audio CONTINUING from intro end, OR full battle when no intro |
| **A3** | Intro music — leader audio DURING the gym leader intro video (only first-appearance battles with video) |
| A4-A9 | Empty (or Fairlight utility tracks) |

`A3` is the "Music 2" track in the Fairlight preset for Gen 1 (TBD — current "Standard Gameplay youtube" preset for Gen 2 uses A3 for outro audio).

## §2 Per-battle layout patterns

### Pattern A — First appearance, has intro video (e.g. Brock, Misty, Erika, Surge first time)

```
                 intro_start       intro_end          battle_end
                 |                 |                  |
V1:  [.source.][LEADER_INTRO.mp4 2x][.source pushed right by intro duration.]
                 |                 |                  |
A3:              [Leader.mp3 0..D1][fadeout 0.2s]
                                  <---0.2s OVERLAP---->
A2:                                [fadein 0.2s][Leader.mp3 D1..battle_end][fadeout 0.2s]
```

Where:
- `D1 = retimed_intro_duration_frames = original_intro_duration / 2` (200% retime)
- A3 plays source frames `[0, D1)` of the leader audio file
- A2 plays source frames `[D1, D1 + battle_remaining)` — i.e. continues from exactly where A3 ended
- The 0.2s overlap region is the crossfade: A3's last 0.2s + A2's first 0.2s play in parallel; both at -3dB equal-power curve; since it's the SAME audio offset, the sum is acoustically transparent (no perceived dip or boost)

### Pattern B — First appearance, no intro video (Giovanni 1, Giovanni 2, Rival)

```
                 battle_start              battle_end
                 |                         |
V1:  [.source clip with gameplay.][.continues.]
                 |                         |
A3:  (empty)
A2:  [fadein 0.2s][Leader.mp3 0..battle_dur, loop if needed][fadeout 0.2s]
```

A2 only. Fade in/out 0.2s. If `battle_dur > audio_duration`, loop the audio file (the orchestrator may concatenate or use Resolve's clip-loop feature).

### Pattern C — Subsequent appearance of same leader (no intro)

Same as Pattern B regardless of whether the leader has an intro video — intros only play on first appearance.

## §3 Gave-up + switch crossfade (battle gap)

When the player gives up on Leader X and immediately fights Leader Y (no rest period), a 60-frame battle gap is inserted by the upstream pipeline. In that gap, A2 crossfades:

```
                       gap_start          gap_end (= next battle_start)
                       |                  |
V1:  [...X battle][1s source extend][Y battle starts]
                       |                  |
A2:  [...X.mp3]====================>(fadeout across full gap)
                       (fadein across full gap)=====>[Y.mp3...]
                       <--- 60-frame full crossfade ---->
```

The OLD leader's A2 audio extends INTO the gap (still source-frames continuing) but fades out across the full 60 frames using `-3dB equal-power`. The NEW leader's A2 audio starts AT the gap_start frame, source-in = 0, fades in across the same 60 frames. Both clips overlap fully across the gap.

**Special case — gave-up + switch where NEW leader has an intro video:**

Leader Y is a first-appearance with an intro video. Then:
- The intro video inserts on V1 at the battle start (gap_end), pushing further-right content
- A3 placement = Pattern A for Y
- A2 placement at gap_end = Pattern A "post-intro" segment, source-in = D1
- The gap-region A2 crossfade still applies: OLD X's A2 fades out across the gap; NEW Y's A2 starts at `gap_end + D1` (not at gap_end)
- Within the gap region, A2 has ONLY X fading out (no Y on A2 yet — Y enters A2 after its intro)

This creates a brief A2 silence at the very end of the gap → start of intro. The intro's A3 music kicks in immediately so the silence is masked by the intro music. Smooth.

## §4 Fairlight preset implications

The current resolve-mcp Fairlight preset "Standard Gameplay youtube" was built for Gen 2 and has:
- A1: Dialogue
- A2: Music
- A3: Music 2 (in Gen 2, used for outro audio)
- A4-A9: utility/empty

For Gen 1, A3 needs to be routed for INTRO music — likely with similar bus + compression as A2 but maybe at +2-3dB to make the dramatic leader theme punch. The simplest path: KEEP the existing preset (which works), but adjust A3's input fader manually in Fairlight after this skill runs.

A future enhancement: build a "Standard Gameplay youtube Gen 1" preset variant with explicit A3 = "Leader Intro Music" routing, save it via the Fairlight preset workflow, and have the verify-fairlight-preset skill detect which preset is needed by project type.

## §5 Fade curve details

Resolve supports `-3dB equal-power` (constant power across the crossfade — no dip) and `-6dB linear` (the default for `apply_audio_fades.py`). For leader-track crossfades, `-3dB equal-power` is preferred because:
- A3 and A2 carry the SAME audio source during the overlap
- Linear fades would cause a -3dB dip in the middle of the overlap (where both clips are at -6dB)
- Equal-power keeps the sum at unity throughout

Resolve property names (from `apply_audio_fades.py`):
- Fade-in shape: `'Fade In Type'` = `'Equal Power'` (alternatives: `'Linear'`, `'S Curve'`)
- Fade-out shape: `'Fade Out Type'` = `'Equal Power'`
- Fade-in duration in seconds: `'Fade In Sec'`
- Fade-out duration in seconds: `'Fade Out Sec'`

Or set frame-precise via the timeline's standard cross-dissolve transition.

## §6 Looping when audio shorter than battle

Most leader audio tracks are 2-5 minutes long. Most battles are 1-3 minutes (much shorter than the audio). So looping is rare. But for:
- Long Bugsy-style resets: battle window can be 15-30+ minutes
- Lorelei/Bruno/Agatha can take many resets

When `battle_duration > audio_duration - source_in`:
- Resolve does NOT auto-loop. The clip ends at the audio's natural end.
- Options:
  1. **Place multiple copies** of the same audio back-to-back, each with cross-fade between them
  2. **Use Resolve's Loop property** if available (TBD — check Resolve API)
  3. **Extend the source** by appending the file to itself in the media pool (creates a 2x-length asset)

The orchestrator currently does NOT handle the loop case — it places one copy and may end short. Document this limitation in the placement-report.md.

## §7 Victory.mp3 after champion

Triggered by the session log's `champion:beat-champion-flag` event (single event, no debounce needed since it fires once per run).

Placement:
- Audio file: `gymLeaders/LeaderIntros/audio/Victory.mp3`
- Track: A2 (replaces the Champion battle audio that was playing)
- Record frame: the event's `tElapsedMs` mapped through the V1 clip table → timeline frame
- Source in: 0 (start of file)
- Duration: natural audio length (or until outro starts, whichever shorter)
- Fade in: 0.5s `-3dB equal-power`
- Fade out: 1.0s `-3dB equal-power` at the end
- Crossfade with whatever Champion audio was on A2 at that point (a `-3dB equal-power` 0.5s region)

Skip with `--no-victory` flag.

## §8 Diagnostic — placement-report.md

After execute_plan runs, the skill writes `audio-checks/gen1-leader-tracks/placement-report.md` summarizing every clip placed. Useful for diffing iterations + verifying the plan matches reality.

Schema:
```markdown
# Gen 1 Leader Tracks — placement report

Date: <ISO>
Timeline: <name>
Version: yellow | red_blue
Battles: N (M first appearances)

## V1 intro inserts (K placements)
| Leader | Record frame | Retime | Video file | Duration (frames) |
|---|---|---|---|---|
| Brock | 230400 | 200% | Brock.mp4 | 154 |
...

## A3 placements (K)
...

## A2 placements (N)
...

## Crossfades applied (J)
| Type | Region | Old → New | Curve |
|---|---|---|---|
| intro→battle | [230400-230554] | Brock A3 → Brock A2 | -3dB EP |
| gave-up switch | [350200-350260] | KOGA → ERIKA | -3dB EP |
...

## Warnings
- audio file XYZ.mp3 not found at expected path
- battle K has no end marker; skipped
...
```
