# Gen 1 (RBY) vs Gen 2 (GSC) pipeline differences

The orchestrator workflow for Gen 2 challenges differs from Gen 1 in several material ways. When configuring a Gen 1 edit timeline workflow, apply these overrides.

This doc grounds: ✅ what was verified from on-disk assets · ⚠ what needs implementation when the Gen 1 edit-timeline skill is built · 📝 where it lives now (this skill's scope is only marker labelling)

---

## 1. Gym leader intros are V1, not V2

### Gen 2 behavior (current orchestrator battle-intro stage)
Battle intros are short (~5s) graphics placed on V2 with their tail aligned to the battle start frame. Video-only (mediaType=1) — audio is dropped to avoid conflict with A2 BGM. Source: `_all-battle-intros` and `_all-silver-battle-intros` shared bins.

### Gen 1 behavior (NEW)
Gym leader intros are full clips with VIDEO + AUDIO. They are inserted into **V1** (not V2) at **2× speed** (retime), pushing the source content rightward — same pattern as how the GSC intro is inserted at the start of a Gen 2 edit timeline (`scripts/insert_intro_outro.py`).

**Source folder:** `C:\Programming\RBYNewLayout\gymLeaders\LeaderIntros\` (20 files, mp4)
**Retime:** 200% (matches FileOrganizer / pipeline convention; 2× source playback)
**Placement:** ONLY the first time each gym leader is battled. Subsequent battles against the same leader get NO intro (the leader audio still plays per §3).

### Open detection question
The pipeline needs to know which gym leader each battle is. The session log's `battle:battle-start` event carries `data.leader` (BROCK / MISTY / LT.SURGE / etc.) — this is the authoritative mapping. Walk the session-log battle events in order; first occurrence of each `leader` value triggers an intro insertion at that battle's source-time.

---

## 2. Red/Blue version variants

### Asset matrix

✅ **Verified from `C:\Programming\RBYNewLayout\gymLeaders\LeaderIntros\`:**

| Leader | Yellow asset | Red/Blue asset | Notes |
|---|---|---|---|
| Agatha | Agatha.mp4 | (same) | No variant |
| Blaine | Blaine.mp4 | BlaineBlue.mp4 | Variant exists |
| Brock | Brock.mp4 | (same) | No variant |
| Bruno | Bruno.mp4 | (same) | No variant |
| Champion (Rival 3) | Champion.mp4 | ChampionBlue.mp4 | Variant exists |
| Erika | Erika.mp4 | ErikaBlue.mp4 | Variant exists |
| Giovanni | Giovanni.mp4 | GiovanniBlue.mp4 | Variant exists |
| Koga | Koga.mp4 | KogaBlue.mp4 | Variant exists |
| Lance | Lance.mp4 | (same) | No variant |
| Lorelei | Lorelei.mp4 | (same) | No variant |
| Misty | Misty.mp4 | (same) | No variant |
| Sabrina | Sabrina.mp4 | SabrinaBlue.mp4 | Variant exists |
| Surge | Surge.mp4 | SurgeBlue.mp4 | Variant exists |

7 trainers have Blue variants: Blaine, Champion, Erika, Giovanni, Koga, Sabrina, Surge.
6 trainers do not: Agatha, Brock, Bruno, Lance, Lorelei, Misty.

### Selection rule

```python
def pick_intro_video(leader_name: str, version: str) -> str:
    """
    leader_name: pretty name from session log (Brock, Misty, Lt. Surge, etc.)
    version: "yellow" | "red_blue"  (derived from project metadata or user input)
    """
    base = leader_name.replace(" ", "").replace(".", "")  # "Lt. Surge" -> "LtSurge"
    # Standardize: 'Lt. Surge' -> 'Surge', 'Lorelei' -> 'Lorelei', etc.
    # See LEADER_FILENAME_MAP below.
    base = LEADER_FILENAME_MAP.get(leader_name, base)
    if version == "red_blue":
        blue_variant = f"{base}Blue.mp4"
        if (LEADER_INTROS_DIR / blue_variant).exists():
            return blue_variant
    return f"{base}.mp4"  # Yellow OR fallback when no Blue exists
```

Filename normalization map:
```python
LEADER_FILENAME_MAP = {
    "Lt. Surge": "Surge",       # NOT LtSurge — files use just "Surge"
    "Champion": "Champion",
    "Rival 3": "Champion",       # Champion = Rival 3 in pipeline naming
    "Giovanni": "Giovanni",
    "Giovanni (R1)": "Giovanni",
    "Giovanni (R2)": "Giovanni",
    # All other names map to themselves
}
```

### Version detection
Project metadata should carry `version: "yellow" | "red_blue"`. Possible sources:
- User passes `--version yellow|red_blue` to the Gen 1 edit-timeline skill
- Project name contains "Red and Blue" or "Blue" → `red_blue`; "Yellow" → `yellow`
- Default to `yellow` if ambiguous; warn user.

For Victreebel: filename contains "Red and Blue" → `red_blue` (so use BlaineBlue, ChampionBlue, ErikaBlue, GiovanniBlue, KogaBlue, SabrinaBlue, SurgeBlue when applicable).

### Fallback rule
If a leader doesn't have a `-Blue` variant (Agatha, Brock, Bruno, Lance, Lorelei, Misty), use the single available file regardless of `version`.

---

## 3. Battle audio: per-leader, not random BGM

### Gen 2 behavior (current orchestrator battle-audio stage)
- General BGM (`general`-tagged from `~/.resolve-mcp/bgm-tags.json`) chained randomly between battles
- Battle audio: one canonical track per battle type (rival/gym/other)
  - Rival: "Take them down!.mp3"
  - Gym: "Big Baddies.mp3"
  - Other: "A new Challenger.mp3"

### Gen 1 behavior (NEW)

✅ **Verified from `C:\Programming\RBYNewLayout\gymLeaders\LeaderIntros\audio\`:**

| Track | File |
|---|---|
| Agatha | Agatha.mp3 |
| Blaine | Blaine.mp3 |
| Brock | Brock.mp3 |
| Bruno | Bruno.mp3 |
| Champion | Champion.mp3 |
| Erika | Erika.mp3 |
| Giovanni 1 | Giovanni 1.mp3 |
| Giovanni 2 | Giovanni 2.mp3 |
| Giovanni 3 | Giovanni 3.mp3 |
| Jessie and James | Jessie and James.mp3 |
| Koga | Koga.mp3 |
| Lance | Lance.mp3 |
| Lorelei | Lorelei.mp3 |
| Misty | Misty.mp3 |
| Rival | Rival.mp3 |
| Sabrina | Sabrina.mp3 |
| Surge | Surge.mp3 |
| Victory | Victory.mp3 |

18 tracks. NO `-Blue` variants — audio is shared between Yellow and Blue versions.

### Selection rule per battle
The audio track played for a battle is the leader's named track from this folder. No fallback to random general BGM during battle windows. Between-battle BGM still pulls from the general BGM pool at `C:\Programming\RBYNewLayout\audio\bgm\` (156 tracks).

### Special audio tracks
- `Victory.mp3` — plays after a champion defeat (`champion:beat-champion-flag` event)
- `Jessie and James.mp3` — for Team Rocket grunt battles (if event distinguishes)
- `Rival.mp3` — for non-champion rival battles (Rival 1, Rival 2)

### Reference index
The Electron app's `battleAudioPlaylist.json` at `C:\Programming\RBYNewLayout\battleAudioPlaylist.json` enumerates all 18 paths as the canonical battle-audio asset list.

---

## 4. Gym leader intro audio routing (A2 + A3 crossfade)

This is the biggest behavioral difference from Gen 2.

### Spec

For each first-time gym leader battle:

1. **V1**: insert the gym leader intro video (retimed 200%) at the battle start frame, shifting source content right.
2. **A3**: place the gym leader audio file (`gymLeaders/LeaderIntros/audio/<Leader>.mp3`) starting at the same record frame as the intro video, **duration matched to the intro video's playback duration** (i.e. the retimed length on V1, NOT the original audio length).
3. **A3**: truncate the audio clip at the end-of-intro frame. The source-in remains 0 (start of audio file); source-out = intro duration. So A3 plays the first N seconds of the leader audio, where N = intro video's V1 duration.
4. **A2**: place the SAME audio file starting at the end-of-intro frame. Source-in = the value of N from step 3 (so A2 continues the audio from exactly where A3 cut off). Duration = whatever fits between the end of intro and the battle's natural end.
5. **Crossfade**: A3 and A2 must blend seamlessly across the intro→battle boundary. Resolve's standard −3dB equal-power crossfade with ~12-frame (0.2s) overlap on each side is the convention; the audio source is identical so the overlap is acoustically transparent.

### Why split across A2 + A3
- A2 stays as the "Music" track in the Fairlight preset (`Standard Gameplay youtube` or its Gen 1 equivalent), routed normally
- A3 is "Music 2" — can be tuned for higher relative level during the intro (so the leader theme punches over dialogue/SFX during the dramatic intro) and then drops back to A2's standard level for the battle proper
- The Fairlight preset's bus routing decides the actual mix; the skill just places the clips correctly

### Pseudocode for the Gen 1 audio pipeline

```python
def place_gen1_battle_audio(timeline, battle, leader, version, is_first_appearance):
    leader_audio = LEADER_AUDIO_DIR / f"{leader}.mp3"  # No -Blue variant
    battle_start_frame = battle.tl_start_frame
    battle_end_frame   = battle.tl_end_frame

    if is_first_appearance:
        # 1. Insert intro video on V1 (this shifts everything after it right)
        intro_file = pick_intro_video(leader, version)  # see §2
        intro_clip = insert_v1_clip(
            timeline,
            source=LEADER_INTROS_DIR / intro_file,
            record_frame=battle_start_frame,
            retime_pct=200,
        )
        intro_dur_frames = intro_clip.GetDuration()  # post-retime
        battle_start_frame_in_v1 = intro_clip.GetEnd()  # battle starts AFTER intro

        # 2 + 3. A3: leader audio matched to intro duration
        a3_clip = place_audio(
            timeline,
            source=leader_audio,
            track=3,
            record_frame=battle_start_frame,  # before the intro-shift
            source_in_frames=0,
            duration_frames=intro_dur_frames,
        )

        # 4. A2: leader audio continues from where A3 ended
        a2_clip = place_audio(
            timeline,
            source=leader_audio,
            track=2,
            record_frame=battle_start_frame_in_v1,  # where battle now starts after intro shift
            source_in_frames=intro_dur_frames,
            duration_frames=battle_end_frame - battle_start_frame_in_v1,
        )

        # 5. Crossfade ~0.2s overlap with -3dB equal-power curve
        apply_crossfade(a3_clip, a2_clip, overlap_frames=12)
    else:
        # Subsequent appearance of same leader: no intro, just battle audio on A2
        place_audio(timeline, source=leader_audio, track=2,
                    record_frame=battle_start_frame,
                    duration_frames=battle_end_frame - battle_start_frame)
```

### Edge cases for crossfade
- If `intro_dur_frames > leader_audio_total_duration` (rare; leader audio shorter than 2×-retimed intro): A3 should play the full audio + fade to silence; A2 starts at the audio's natural end (offset = audio_duration) and continues with the next loop OR starts cold. Decide at implementation time.
- If `battle_end_frame - battle_start_frame_in_v1 > (leader_audio_total_duration - intro_dur_frames)`: A2 audio is shorter than the battle window. Loop the leader audio OR fade to silence at the natural end.

---

## 5. Summary table — Gen 1 vs Gen 2 pipeline diffs

| Step | Gen 2 orchestrator | Gen 1 orchestrator |
|---|---|---|
| Marker source | Whisper transcript + battle detection LLM relay | OBS chapter markers + RBY session log (this skill) |
| Battle intros | V2 overlay, 5s, video-only | **V1 insert, 2× retime, first-appearance only, video+audio** |
| Battle intro asset bin | `_all-battle-intros`, `_all-silver-battle-intros` | `gymLeaders/LeaderIntros/*.mp4` (with -Blue variants) |
| Battle audio (per type) | Rival/gym/other one-track-each | **Per-leader named track** |
| Battle audio asset folder | `RBYNewLayout/audio/bgm/` (mixed) | `gymLeaders/LeaderIntros/audio/` |
| General BGM (between battles) | Random from `general`-tagged BGM | Same (random from BGM folder) |
| Audio routing | A2 only | **A3 during intro + A2 after, crossfade** |
| Version variants | N/A | **Yellow uses base name; Red/Blue uses `-Blue` when available** |
| Fairlight preset | "Standard Gameplay youtube" (5 tracks → 9 tracks) | TBD — may need a 4-track preset (Dialogue / Music / Music 2 / Outro) |

---

## 6. Implementation status

**Implemented (this skill, gen1-marker-pipeline):**
- ✅ Phase 1: auto-editor + track rename + FCPXML marker injection
- ✅ Phase 2: in-Resolve marker labelling via session log

**NOT implemented yet** (for a future Gen 1 orchestrator workflow):
- ⚠ Gym leader intro V1 insertion (§1 + §2 + §4)
- ⚠ Per-leader battle audio routing across A3 + A2 with crossfade (§4)
- ⚠ Version detection + -Blue variant selection (§2)
- ⚠ Fairlight preset for Gen 1 (the existing "Standard Gameplay youtube" preset assumes Gen 2 track layout; Gen 1 needs A3 as "Music 2" with different routing)
- ⚠ First-appearance detection (which battle of each leader is the first; only inject intro then)

When that skill is built, this doc is the spec. The pre-Resolve marker workflow (this skill) is the prerequisite; downstream operations sit on top of the labelled markers it produces.
