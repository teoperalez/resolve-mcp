# MARKER_RULES — event → marker mapping

Mirrored from `C:\Programming\RBYNewLayout\scripts\session_marker_labels.py` (which itself mirrors `utils\sessionLog-main.js`). When this table changes upstream, re-copy `session_marker_labels.py` into this skill's `scripts/` dir.

## Rules (event filter + debounce)

| # | category | name pattern | debounce (ms) |
|---|---|---|---|
| 1 | view | `intro-started` | 1500 |
| 2 | view | `pregame-card-shown` | 1500 |
| 3 | event | `first-pokemon-received` | 1500 |
| 4 | battle | `battle-start` | 2000 |
| 5 | battle | `battle-end` | 2000 |
| 6 | champion | `beat-champion-flag` | 1500 |
| 7 | view | `post-battle-tiercard-shown` | 1500 |
| 8 | view | `post-battle-tiercard-closed` | 1500 |
| 9 | view | regex `^final-tierlist-(podium\|traditional)-shown$` | 1500 |
| 10 | view | `member-carousel-started` | 1500 |

Events matching one of these rules and that pass the per-`category:name` debounce produce one entry in the `replay_markers()` output. Order is event order.

## Label algorithm (`_label_for(ev)`)

| Event | Label format |
|---|---|
| `battle:battle-start` with `data.leader=BROCK` | `"Brock Battle Start"` |
| `battle:battle-end` with `data.from=MISTY` | `"Misty Battle Finish"` |
| `view:intro-started` | `"Intro"` |
| `view:pregame-card-shown` | `"Get Pokemon"` |
| `event:first-pokemon-received` | `"First Pokemon"` |
| `champion:beat-champion-flag` | `"Beat Champion"` |
| `view:post-battle-tiercard-shown` | `"Post-Battle Tiercard"` |
| `view:post-battle-tiercard-closed` | `"Post-Battle Tiercard Closed"` |
| `view:final-tierlist-podium-shown` | `"Final Tierlist (Podium)"` |
| `view:final-tierlist-traditional-shown` | `"Final Tierlist (Traditional)"` |
| `view:member-carousel-started` | `"Member Carousel"` |

`_leader_label()` maps raw leader keys → pretty names:

| Raw | Pretty |
|---|---|
| `BROCK` | Brock |
| `MISTY` | Misty |
| `LT.SURGE` | Lt. Surge |
| `ERIKA` | Erika |
| `KOGA` | Koga |
| `SABRINA` | Sabrina |
| `BLAINE` | Blaine |
| `GIOVANNI_GYM` | Giovanni |
| `GIOVANNI_1` | Giovanni (R1) |
| `GIOVANNI_2` | Giovanni (R2) |
| `LORELEI` | Lorelei |
| `BRUNO` | Bruno |
| `AGATHA` | Agatha |
| `LANCE` | Lance |
| `RIVAL3` | Champion |
| `RIVAL` | Rival |
| (any other) | `.title()` form |

## Color algorithm (`_color_for(ev)`)

Battle markers use leader type color. Non-battle markers use a fixed map:

| Leader | Color | Type |
|---|---|---|
| BROCK | Sand | Rock |
| MISTY | Sky | Water |
| LT.SURGE | Yellow | Electric |
| ERIKA | Green | Grass |
| KOGA | Purple | Poison |
| SABRINA | Pink | Psychic |
| BLAINE | Red | Fire |
| GIOVANNI_GYM | Cream | Ground |
| GIOVANNI_1 | Cream | — |
| GIOVANNI_2 | Cream | — |
| LORELEI | Cyan | Ice |
| BRUNO | Cocoa | Fighting |
| AGATHA | Lavender | Ghost |
| LANCE | Fuchsia | Dragon |
| RIVAL3 (Champion) | Rose | — |
| RIVAL (1/2) | Mint | — |

Non-battle markers:

| Event | Color |
|---|---|
| `view:intro-started` | Cyan |
| `view:pregame-card-shown` | Sky |
| `event:first-pokemon-received` | Mint |
| `champion:beat-champion-flag` | Rose |
| `view:post-battle-tiercard-shown/closed` | Yellow |
| `view:final-tierlist-*` | Purple |
| `view:member-carousel-started` | Sand |
| (fallback by category) | view=Blue, event=Green, champion=Purple, battle=Red |

Default if nothing matches: `Blue`.

## Note format

Notes are built from `data` fields the event carries. The function checks for keys `leader`, `from`, `to`, `trainer` and concatenates `k=v` pairs with `; `. Example: `"leader=BROCK; trainer=ROCK_SHADES"`.

## Resolve marker palette (valid color strings)

`AddMarker` accepts exactly these 16 colors:
`Blue Cyan Green Yellow Red Pink Purple Fuchsia Rose Lavender Sky Mint Lemon Sand Cocoa Cream`

Any other string silently fails. The skill's color map only uses valid values.

## Event schema reference (events.json)

```json
{
  "tElapsedMs": 123456,
  "tc": "00:34:17:23",
  "wallTime": "2026-04-27T14:19:40.123Z",
  "category": "battle",
  "name": "battle-start",
  "data": { "leader": "BROCK" }
}
```

- `tElapsedMs`: milliseconds from session start
- `tc`: SMPTE timecode (60fps)
- `wallTime`: ISO 8601 (UTC) for diagnostics
- `category` + `name`: matched against `_MARKER_RULES`
- `data`: rule-specific payload (leader/from/to/trainer)

## Debounce semantics

Per-`category:name` key. If event `[cat=battle, name=battle-start, tElapsedMs=10000]` fires, then `[cat=battle, name=battle-start, tElapsedMs=11500]` fires, the second one is dropped because `11500 - 10000 = 1500 < 2000ms`. The first sets `last_fire_ms["battle:battle-start"] = 10000`. After 2000ms have elapsed, the next matching event will pass.

Different `category:name` keys have independent debounce timers.
