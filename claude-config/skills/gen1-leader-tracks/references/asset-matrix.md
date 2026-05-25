# Asset matrix (verified 2026-05-23 against `C:\Programming\RBYNewLayout\gymLeaders\LeaderIntros\`)

## Leader → audio + intro video

| Session-log `data.leader` | Pretty name | Audio file | Yellow video | Red/Blue video | Intro? | Category |
|---|---|---|---|---|---|---|
| `BROCK` | Brock | `Brock.mp3` | `Brock.mp4` | `Brock.mp4` | ✓ | gym_leader |
| `MISTY` | Misty | `Misty.mp3` | `Misty.mp4` | `Misty.mp4` | ✓ | gym_leader |
| `LT.SURGE` | Lt. Surge | `Surge.mp3` | `Surge.mp4` | **`SurgeBlue.mp4`** | ✓ | gym_leader |
| `ERIKA` | Erika | `Erika.mp3` | `Erika.mp4` | **`ErikaBlue.mp4`** | ✓ | gym_leader |
| `KOGA` | Koga | `Koga.mp3` | `Koga.mp4` | **`KogaBlue.mp4`** | ✓ | gym_leader |
| `SABRINA` | Sabrina | `Sabrina.mp3` | `Sabrina.mp4` | **`SabrinaBlue.mp4`** | ✓ | gym_leader |
| `BLAINE` | Blaine | `Blaine.mp3` | `Blaine.mp4` | **`BlaineBlue.mp4`** | ✓ | gym_leader |
| **`GIOVANNI_1`** | Giovanni (R1) | **`Giovanni 1.mp3`** | — | — | **✗** | rocket_special |
| **`GIOVANNI_2`** | Giovanni (R2) | **`Giovanni 2.mp3`** | — | — | **✗** | rocket_special |
| `GIOVANNI_GYM` | Giovanni | **`Giovanni 3.mp3`** | `Giovanni.mp4` | **`GiovanniBlue.mp4`** | ✓ | gym_leader |
| `LORELEI` | Lorelei | `Lorelei.mp3` | `Lorelei.mp4` | `Lorelei.mp4` | ✓ | elite_4 |
| `BRUNO` | Bruno | `Bruno.mp3` | `Bruno.mp4` | `Bruno.mp4` | ✓ | elite_4 |
| `AGATHA` | Agatha | `Agatha.mp3` | `Agatha.mp4` | `Agatha.mp4` | ✓ | elite_4 |
| `LANCE` | Lance | `Lance.mp3` | `Lance.mp4` | `Lance.mp4` | ✓ | elite_4 |
| **`RIVAL`** | Rival | **`Rival.mp3`** | — | — | **✗** | rival |
| `RIVAL3` | Champion | **`Champion.mp3`** | `Champion.mp4` | **`ChampionBlue.mp4`** | ✓ | champion |

## Asset folder paths

Relative to RBYNewLayout repo root (`C:\Programming\RBYNewLayout\` by default):

- **Intro videos:** `gymLeaders/LeaderIntros/*.mp4` (20 files: 13 leaders + 7 -Blue variants)
- **Audio:** `gymLeaders/LeaderIntros/audio/*.mp3` (18 files: per-leader + Giovanni 1/2/3 + Rival + Jessie and James + Victory)

## Special audio (event-driven, not battle-driven)

| Event | Audio file | When |
|---|---|---|
| `champion:beat-champion-flag` | `Victory.mp3` | Placed on A2 starting at the event timestamp, fade in 0.5s |
| (TBD: Team Rocket grunt event) | `Jessie and James.mp3` | Only places if `--enable-jessie-grunts` flag is set; needs an event-detection rule |

## Video files not in audio folder

`Lance.mp4` exists as a video but Lance is in Elite 4 / Indigo Plateau in the run flow.
`Lorelei`, `Bruno`, `Agatha`, `Lance` all have videos + audio — they're Elite 4 members and treated as gym-leader-equivalent (full intro + audio).

## Audio files not in video folder

These appear in `LeaderIntros/audio/` but have NO matching video:
- `Giovanni 1.mp3` — Rocket Game Corner basement encounter
- `Giovanni 2.mp3` — Silph Co president's office encounter
- `Rival.mp3` — early-game rival battles (Rival 1 + Rival 2)
- `Jessie and James.mp3` — Team Rocket grunt fights
- `Victory.mp3` — post-champion-defeat fanfare

These are AUDIO-ONLY placements. The skill places them on A2 only (no V1 intro insert).

## Version variants (-Blue suffix)

7 trainers have `-Blue` video variants in `LeaderIntros/`:

| Base | Blue variant |
|---|---|
| Blaine.mp4 | BlaineBlue.mp4 |
| Champion.mp4 | ChampionBlue.mp4 |
| Erika.mp4 | ErikaBlue.mp4 |
| Giovanni.mp4 | GiovanniBlue.mp4 |
| Koga.mp4 | KogaBlue.mp4 |
| Sabrina.mp4 | SabrinaBlue.mp4 |
| Surge.mp4 | SurgeBlue.mp4 |

Selection rule (from `leader_asset_map.resolve_video_filename`):
```
if version == 'red_blue' and <base>Blue.mp4 exists:
    use <base>Blue.mp4
else:
    use <base>.mp4
```

6 trainers do NOT have `-Blue` variants — use the single base file regardless of version: Agatha, Brock, Bruno, Lance, Lorelei, Misty.

**Audio is shared between versions** — there are no `-Blue` audio variants. The same `Brock.mp3` plays whether the version is Yellow or Red/Blue.

## When updating

If new leader videos or audio files are added to `LeaderIntros/`:
1. Add the entry to `_TABLE` in `scripts/leader_asset_map.py`
2. Update this matrix
3. Update `references/audio-routing-spec.md` if the audio routing differs from the standard pattern (intro-duration on A3, battle-duration on A2)
4. Re-run the skill on a known-good test case to verify regression-free
