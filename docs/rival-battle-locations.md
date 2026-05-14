# Silver (rival) battle location identification — full rule set

Reference for picking the correct `silver-<location>-<starter_type>-battle-intro.mov` file for each rival encounter in a Gen 2 (Gold/Silver/Crystal/HeartGold/SoulSilver) playthrough.

The rules below are derived from canonical sources (Bulbapedia, Serebii's Crystal and HGSS rival pages, Guide Strats's Crystal walkthrough). Romhacks may deviate slightly but the core signatures remain reliable cues.

---

## Starter type pairing (Part 1 of the answer)

In every Gen 2 game, the rival picks the starter with **type advantage** over the player's choice. This is fixed for the whole video.

| Player picks | Rival picks | Rival starter type → file key |
|---|---|---|
| Chikorita (grass) | Cyndaquil  | `fire` |
| Cyndaquil (fire)  | Totodile   | `water` |
| Totodile (water)  | Chikorita  | `grass` |

**In challenge runs** where the player isn't handed a normal starter (e.g. "Misty's team in Crystal" romhacks), the rival's starter is determined by the romhack — identify it from the rival's Pokémon mentioned in the transcript using the line tables below.

**Pokémon → starter type:**

- **fire**: Cyndaquil, Quilava, Typhlosion
- **water**: Totodile, Croconaw, Feraligatr
- **grass**: Chikorita, Bayleaf, Meganium

---

## Per-battle location (Part 2)

Vanilla Crystal/GSC has **5 pre-E4 rival fights**. HGSS keeps all 5 and adds **2 post-Champion encounters** (Mt. Moon, Indigo Plateau rematch). Below is the canonical table for both game families.

### Team composition tables (canonical)

| # | Location key   | Crystal team @ levels | HGSS team @ levels | Game-version notes |
|---|----------------|-----------------------|--------------------|---------------------|
| 1 | `cherrygrove`  | Starter (Lv 5)        | Starter (Lv 5)     | Same in all versions |
| 2 | `azalea`       | Gastly (12), Zubat (14), Starter (14-16) | Gastly (14), Zubat (16), Starter (18) | "After Bugsy" — west gate of Azalea on the way to Ilex Forest |
| 3 | `burnedtower`  | Magnemite (18), Zubat (20), Gastly (20), Starter (22, 1st evo) | Magnemite (18), Zubat (20), Gastly (20), Starter (22) | Ecruteak Burned Tower; **Magnemite is new but NO Sneasel yet** |
| 4 | `goldenrod`    | Golbat (~28), Haunter (~28), Magnemite (~28), Sneasel (28-30), Starter (30, 1st or 2nd evo) | Golbat (32), Haunter (32), Magnemite (30), Sneasel (34), Starter (34) | Radio Tower / Underground takeover; **Sneasel is the giveaway addition** |
| 5 | `victoryroad`  | Crobat or Golbat (~30), Gengar or Haunter (~32), Magneton (~30), Kadabra (~28), Sneasel (~30), **fully evolved starter** (~32) | Golbat (38), Haunter (37), Magneton (37), Kadabra (37), Sneasel (36), **fully evolved starter** (40) | **Magneton (not Magnemite) and Kadabra are the signatures** |
| 6 | `mtmoon`       | — (post-game in HGSS only) | Crobat (50), Gengar (50), Magneton (51), Alakazam (51), Sneasel (50), **fully evolved starter** (52) | HGSS only; post-Champion |
| 7 | `indigoplateau`| — (post-game in HGSS only) | Same as Mt. Moon, but levels 45-50; **Crobat instead of Golbat** | HGSS only; rematch on Mondays/Wednesdays |

### Distinguishing signatures (in decreasing order of reliability)

1. **Sneasel presence**
   - Sneasel absent → fight is `cherrygrove`, `azalea`, or `burnedtower`
   - Sneasel present → fight is `goldenrod`, `victoryroad`, `mtmoon`, or `indigoplateau`

2. **Magnemite vs Magneton (Sneasel-resolved cases)**
   - Magnemite (not Magneton) + Sneasel absent → `burnedtower`
   - Magnemite + Sneasel present → `goldenrod`
   - Magneton (Magnemite evolved) → `victoryroad`, `mtmoon`, or `indigoplateau`

3. **Starter evolution stage**
   - Starter still at Lv 5 unevolved → `cherrygrove`
   - Starter at first-stage evolution (Bayleaf/Quilava/Croconaw) → `azalea`, `burnedtower`, or `goldenrod`
   - Starter fully evolved (Meganium/Typhlosion/Feraligatr) → `victoryroad`, `mtmoon`, or `indigoplateau`

4. **Zubat vs Golbat vs Crobat**
   - Zubat → `azalea` or `burnedtower`
   - Golbat → `goldenrod` or `victoryroad` (Crystal sometimes shows Golbat at Victory Road)
   - Crobat (= "Silver has matured") → `mtmoon` or `indigoplateau` (HGSS post-game)

5. **Gastly vs Haunter vs Gengar**
   - Gastly → `azalea` or `burnedtower`
   - Haunter → `goldenrod` or `victoryroad`
   - Gengar (Haunter evolved via cutscene trade) → `victoryroad`, `mtmoon`, or `indigoplateau`

6. **Kadabra / Alakazam**
   - Kadabra → `victoryroad`
   - Alakazam → `mtmoon` or `indigoplateau`

7. **Team size**
   - 1 → cherrygrove
   - 3 → azalea
   - 4 → burnedtower
   - 5 → goldenrod
   - 6 → victoryroad / mtmoon / indigoplateau

### Cross-check by gym-leader position

The streamer's gym progress is a strong sanity check on composition. Order is identical in Crystal and HGSS.

| Rival fight comes... | Then location is |
|---|---|
| Before Falkner (Gym 1) | `cherrygrove` |
| After Bugsy (Gym 2), before Whitney (Gym 3) | `azalea` |
| After Whitney, before Morty (Gym 4) | `burnedtower` |
| After Pryce (Gym 7), before Clair (Gym 8) | `goldenrod` |
| After Clair, before Elite 4 | `victoryroad` |
| After becoming Champion | `mtmoon` (early post-game) or `indigoplateau` (rematch) |

When team composition and gym-position disagree (rare, e.g. romhacks with unusual rival teams), **trust position over composition** — the streamer's progress through the gyms is more stable than the romhack's specific roster choices.

### Things to ignore

- **Explicit transcript mentions of place names can mislead.** The streamer might say "we're at the Burned Tower" while describing surroundings during a Cherrygrove fight, or "Azalea" while travelling through it for a Slowpoke Well event that isn't a rival battle. Always verify against composition + gym position before trusting verbal cues.
- **detect_battles trainer names** (`"Rival 1"`, `"Rival 2"`, etc.) are **in-video ordinals**, not canonical positions. If the streamer skipped or cut a fight, the numbering shifts. Use the rules above to recover the canonical location.
- **Mahogany Town Rocket Hideout** has a cutscene encounter with Silver in HGSS but typically **no battle** — don't slot a rival here.

---

## Decision tree (machine-friendly)

```
def rival_location(team, gym_position, video_time):
    has_sneasel       = 'Sneasel' in team
    has_magneton      = 'Magneton' in team
    has_magnemite     = 'Magnemite' in team
    has_crobat        = 'Crobat' in team
    starter_evolved   = any(p in team for p in [
        'Meganium', 'Typhlosion', 'Feraligatr'])
    team_size         = len(team)

    # 1. Single-Pokemon team → always cherrygrove
    if team_size == 1:
        return 'cherrygrove'

    # 2. No Sneasel, has Magnemite (not Magneton) → burnedtower
    if not has_sneasel and has_magnemite and not has_magneton:
        return 'burnedtower'

    # 3. No Sneasel, no Magnemite, no Magneton → azalea
    if not has_sneasel and not has_magnemite and not has_magneton:
        return 'azalea'

    # 4. Has Sneasel + Magnemite (not Magneton) + starter not fully evolved → goldenrod
    if has_sneasel and has_magnemite and not starter_evolved:
        return 'goldenrod'

    # 5. Has Sneasel + Magneton + fully evolved starter
    if has_sneasel and has_magneton and starter_evolved:
        # Crobat = HGSS post-game (Silver matured)
        if has_crobat:
            # Distinguish Mt. Moon (early post-game) vs Indigo Plateau (rematch)
            # — only difference is video position: Mt. Moon is the FIRST
            # post-Champion encounter, Indigo Plateau is the rematch.
            if gym_position == 'post_champion_first':
                return 'mtmoon'
            return 'indigoplateau'
        return 'victoryroad'

    # 6. Fallback: use gym position only
    POSITION_MAP = {
        'pre_falkner':        'cherrygrove',
        'between_bugsy_whitney':  'azalea',
        'between_whitney_morty':  'burnedtower',
        'between_pryce_clair':    'goldenrod',
        'between_clair_e4':       'victoryroad',
        'post_champion_first':    'mtmoon',
        'post_champion_rematch':  'indigoplateau',
    }
    return POSITION_MAP.get(gym_position)
```

---

## Worked example: Misty Red and Blue Crystal Gym Leader Challenge

The streamer plays Crystal with Misty's Gen 1 team. Three rival fights detected:

| Battle | Source-sec | Team observed | Gym position | Sneasel? | Magneton? | → Location |
|---|---|---|---|---|---|---|
| Rival 1 | 344.9s  | Chikorita L5 | pre-Falkner | no | no | `cherrygrove` (rule 1: single Pokémon) |
| Rival 2 | 1009.9s | Gastly + Bayleaf + Zubat | after Bugsy, before Whitney | no | no | `azalea` (rule 3: no Sneasel, no Magnemite line) |
| Rival 3 | 1944.4s | Haunter + Magnemite + Bayleaf + Zubat | after Whitney, before Morty | no | no | `burnedtower` (rule 2: Magnemite without Sneasel/Magneton; gym position confirms) |

Rival starter type = `grass` (Chikorita line throughout).

Resulting file picks:
- `silver-cherrygrove-grass-battle-intro.mov`
- `silver-azalea-grass-battle-intro.mov`
- `silver-burnedtower-grass-battle-intro.mov`

---

## Sources

- [Pokémon Crystal — Rival Battles (Serebii)](https://www.serebii.net/crystal/rival.shtml)
- [Pokémon HeartGold & SoulSilver — Your Rival (Serebii)](https://www.serebii.net/heartgoldsoulsilver/rival.shtml)
- [Silver (game) — Bulbapedia](https://bulbapedia.bulbagarden.net/wiki/Silver_(game))
- [All Rival Battles + Team Comps (Pokémon Crystal) — Guide Strats](https://guidestrats.com/pokemon-crystal-all-rival-battles/)
- [Silver's Pokémon Teams (HG/SS) — Pokémon Archive Wiki](https://pokemon-archive.fandom.com/wiki/Silver's_Pok%C3%A9mon_Teams_(HeartGold/SoulSilver))
