---
name: gen1-leader-tracks
description: For Gen 1 (RBY Red/Blue/Yellow) challenge timelines — places gym leader intro videos on V1 (2× retime, first-appearance only) and routes leader-specific battle audio across A3 (during intro) and A2 (during battle) with -3dB equal-power crossfade. Auto-detects version from session log meta.json — uses -Blue video variants when version is "Red and Blue" (SurgeBlue, ErikaBlue, etc.); uses base names for Yellow; falls back to base when no -Blue variant exists. Special-cases Giovanni (1/2 = audio-only, 3 = full intro+audio), Rival (audio-only, no video), Rival3/Champion (full intro+audio). Battle gaps for gave-up + trainer-switch insert -3dB crossfade between OLD leader's audio fading out and NEW leader's audio fading in. Trigger phrases: "place gen 1 leader tracks", "insert gym leader intros", "set up gen 1 battle audio", "add leader audio with crossfade", "run leader-tracks for the rby video". Prerequisite: gen1-marker-pipeline phase 2 must have placed labelled markers on the current Resolve timeline.
---

# gen1-leader-tracks

For Gen 1 (RBY) challenge timelines. Inserts gym leader intro videos + routes leader-specific battle audio. Auto-handles version variants (Yellow vs Red/Blue), Giovanni's 3-encounter audio, Rival vs Champion distinction, and -3dB crossfades at battle boundaries.

## When to use

Trigger phrases:
- "place gen 1 leader tracks"
- "insert gym leader intros"
- "set up gen 1 battle audio"
- "add leader audio with crossfade"
- "run leader-tracks for the rby video"

Use after:
1. The edit timeline exists with battle gaps inserted by the orchestrator or equivalent Gen 1 mechanism
2. `gen1-marker-pipeline` phase 2 has placed labelled `Battle Start` / `Battle Finish` markers on the timeline

Use before:
- Any audio normalization
- Fairlight preset application (Gen 1 preset may need A3 routing different from Gen 2 — see `references/audio-routing-spec.md`)
- Final render

## What it does (high-level)

1. **Detect version** from RBYNewLayout session log meta.json (`"version": "Yellow" | "Red and Blue" | ...`); user can override with `--version`.
2. **Read timeline markers** for `<Leader> Battle Start` / `<Leader> Battle Finish` pairs (placed by gen1-marker-pipeline phase 2).
3. **Group by leader** to identify first-appearance vs subsequent appearances.
4. **For each first-appearance battle (with a video asset):**
   - Insert leader intro video on V1 at 2× retime at the battle start frame (pushes downstream V1 content right)
   - Place leader audio on A3 at the same record frame, duration = retimed intro length, source-in = 0
   - Place leader audio on A2 starting at the post-intro frame, source-in = intro duration (continues where A3 cut off), duration through battle end
   - Apply -3dB equal-power crossfade across the A3-end / A2-start boundary (12-frame overlap on each side)
5. **For each subsequent appearance:**
   - No V1 intro
   - Place leader audio on A2 starting at battle start, source-in = 0, looping if battle longer than audio
   - Fade in 0.2s / fade out 0.2s with -3dB equal-power curves
6. **For gave-up + switch transitions** (battle gap between two different leaders' battles):
   - OLD leader's A2 audio fades out across the gap
   - NEW leader's A2 audio fades in across the gap (overlap = full gap duration = 60 frames)
7. **For champion-defeat post-battle:** place `Victory.mp3` on A2 starting at `champion:beat-champion-flag` event time, fade in 0.5s.

## Asset matrix

See `references/asset-matrix.md` for the full table. Summary:

| Leader (event `data.leader`) | Audio | Video (Yellow) | Video (Red/Blue) | Intro? |
|---|---|---|---|---|
| BROCK | Brock.mp3 | Brock.mp4 | Brock.mp4 | ✓ |
| MISTY | Misty.mp3 | Misty.mp4 | Misty.mp4 | ✓ |
| LT.SURGE | Surge.mp3 | Surge.mp4 | **SurgeBlue.mp4** | ✓ |
| ERIKA | Erika.mp3 | Erika.mp4 | **ErikaBlue.mp4** | ✓ |
| KOGA | Koga.mp3 | Koga.mp4 | **KogaBlue.mp4** | ✓ |
| SABRINA | Sabrina.mp3 | Sabrina.mp4 | **SabrinaBlue.mp4** | ✓ |
| BLAINE | Blaine.mp3 | Blaine.mp4 | **BlaineBlue.mp4** | ✓ |
| **GIOVANNI_1** | **Giovanni 1.mp3** | — | — | **✗ audio only** |
| **GIOVANNI_2** | **Giovanni 2.mp3** | — | — | **✗ audio only** |
| GIOVANNI_GYM (= "Giovanni 3") | **Giovanni 3.mp3** | Giovanni.mp4 | **GiovanniBlue.mp4** | ✓ |
| LORELEI | Lorelei.mp3 | Lorelei.mp4 | Lorelei.mp4 | ✓ |
| BRUNO | Bruno.mp3 | Bruno.mp4 | Bruno.mp4 | ✓ |
| AGATHA | Agatha.mp3 | Agatha.mp4 | Agatha.mp4 | ✓ |
| LANCE | Lance.mp3 | Lance.mp4 | Lance.mp4 | ✓ |
| **RIVAL** (1/2) | **Rival.mp3** | — | — | **✗ audio only** |
| RIVAL3 (Champion) | **Champion.mp3** | Champion.mp4 | **ChampionBlue.mp4** | ✓ |

Special audio (event-driven, not battle):
- After `champion:beat-champion-flag` → place `Victory.mp3` on A2
- Optional: Team Rocket grunt fights → `Jessie and James.mp3` (event TBD; pass `--enable-jessie-grunts` if applicable)

## Version detection

Default: read `%APPDATA%\rbypc-frontend\logs\<latest>\meta.json` `"version"` field.

| meta.json value | Skill version |
|---|---|
| `"Yellow"` | `yellow` (use base names) |
| `"Red"` / `"Blue"` / `"Red and Blue"` | `red_blue` (use -Blue variants when available) |

Override with `--version yellow` or `--version red_blue`. Required if no session log is found.

## Audio routing — A3 + A2 crossfade

The skill produces this layout for each first-appearance battle:

```
                   intro_start    intro_end           battle_end
                   |              |                   |
V1: [...source...][LEADER.MP4 2x][...source shifted right...]
                   |              |                   |
A3:               [Leader.mp3 0..D1, fadeout last 0.2s]
A2:                          [Leader.mp3 D1..end, fadein first 0.2s, loop if needed]
                              <--- 0.2s overlap with -3dB equal power crossfade
                              (A3 ends slightly inside the A2 region; the same audio
                               offset is playing on both tracks during the overlap)
```

Where `D1` = retimed intro duration on the timeline = `original_intro_dur / 2` (because 2× retime).

For subsequent appearances:
```
V1: [...source clip with battle gameplay...]
A2: [Leader.mp3 0..battle_dur, fadein 0.2s, fadeout 0.2s, loop if needed]
A3: (no clip)
```

For gave-up + switch (battle gap of 60 frames between two different leaders' battles):
```
                        gap_start      gap_end
                        |              |
V1: [...prev battle][1s source extend][next battle source...]
A2: [...OLD.mp3 fade out across gap][NEW.mp3 fade in from start across gap...]
```

Crossfade region = full 60 frames of the gap. Both clips overlap fully across the gap with linear -3dB curves.

## Prerequisites

1. **Resolve running**, project open, edit timeline current
2. **Battle gaps already inserted** (any process that adds 60-frame source extensions at battle starts where the player gave up + switched trainers)
3. **gen1-marker-pipeline phase 2 has run** — `<Leader> Battle Start` / `<Leader> Battle Finish` markers must exist on the current timeline
4. **RBYNewLayout assets** at `C:\Programming\RBYNewLayout\gymLeaders\LeaderIntros\` and `C:\Programming\RBYNewLayout\gymLeaders\LeaderIntros\audio\` (the skill resolves paths relative to RBYNewLayout root, configurable via `--rby-root <path>`)
5. **Resolve media pool** has the leader intro videos + audio files already imported into bins (or the skill will import them — TBD: check `gymleaders` shared bin from `import_assets.py`)

## Inputs

| Arg | Required? | Default | Description |
|---|---|---|---|
| `--workspace <path>` | optional | cwd | Project root |
| `--version yellow\|red_blue` | optional | auto-detect from session log | Override version |
| `--rby-root <path>` | optional | `C:\Programming\RBYNewLayout` | RBYNewLayout repo root |
| `--session-dir <path>` | optional | latest under `%APPDATA%\rbypc-frontend\logs\` | Specific session for version detection |
| `--enable-jessie-grunts` | optional flag | off | Place `Jessie and James.mp3` for grunt fights (TODO: needs event detection rule) |
| `--no-victory` | optional flag | off | Skip the post-champion `Victory.mp3` placement |
| `--dry-run` | optional flag | off | Print plan without modifying timeline |
| `--audio-track-bgm` | optional | 2 | A-track index for ongoing battle audio |
| `--audio-track-intro` | optional | 3 | A-track index for intro-duration leader audio |

## Outputs

- V1 modifications: N intro video inserts (N = number of first-appearance battles with video assets)
- A3 placements: N intro-duration audio clips (one per first-appearance battle)
- A2 placements: M total leader audio clips (M = total battle count, including subsequent appearances)
- Crossfade fades applied on every clip boundary
- `audio-checks/gen1-leader-tracks/placement-report.md` summarizing every clip placed (record frame, source range, duration, crossfade)

## Constraints

- Skill **does NOT** insert battle gaps itself — those must exist on the timeline before this runs
- Skill **does NOT** detect battles — relies on markers placed by gen1-marker-pipeline phase 2
- Skill **does NOT** touch A1 (dialogue) or any other tracks not explicitly listed
- Skill **does NOT** modify V1 source clips themselves — only inserts intro videos at first-appearance battle starts
- Skill **does NOT** apply Fairlight preset (separate verify-fairlight-preset skill handles that; note that Gen 1 may need a different preset than "Standard Gameplay youtube" because the A3 routing is different — see references/audio-routing-spec.md §4)

## Files

- `scripts/leader_asset_map.py` — pure data + version logic (importable, no Resolve dependency)
- `scripts/place_leader_tracks.py` — orchestrator
- `scripts/_resolve_env.py` — Resolve API bootstrap
- `references/asset-matrix.md` — full leader → asset table
- `references/audio-routing-spec.md` — A2/A3 layering rules with examples
- `references/edge-cases.md` — Giovanni 1/2/3, Rival/Champion, gave-up crossfade, version variants
- `references/version-detection.md` — meta.json field semantics
