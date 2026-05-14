"""
Identify (a) the rival's starter Pokémon type and (b) the canonical LOCATION
of each rival battle in a Gen 2 (Gold/Silver/Crystal) playthrough — both
needed to pick the correct `silver-<location>-<type>-battle-intro.mov` to
place over each rival encounter.

In Gen 2, the rival (Silver) picks the starter with type advantage over the
player's choice:

  player chose Chikorita (grass) → rival picks Cyndaquil (FIRE)
  player chose Cyndaquil (fire)  → rival picks Totodile (WATER)
  player chose Totodile (water)  → rival picks Chikorita (GRASS)

(In challenge runs where the player isn't given a normal starter, the
streamer still mentions the rival's Pokémon — the LLM identifies the type
from those mentions.)

Locations available as intro files (one per encounter):

  cherrygrove, azalea, burnedtower, goldenrod, victoryroad,
  indigoplateau, mtmoon

The LLM maps each rival_battle's transcript context to one of these
locations. Use the description text from battles.json and the timing within
the video as cues.

If no rival battles are classified in transcripts/battle-types.json, the
script short-circuits — no relay needed.

Result cached in `transcripts/rival-starter.json`:

  {
    "rival_starter_type": "fire" | "water" | "grass" | null,
    "confidence": "high" | "medium" | "low",
    "evidence": "...",
    "reasoning": "...",
    "rivals_by_battle_index": { "0": "cherrygrove", "5": "burnedtower", ... }
  }

Usage:
    python classify_rival_starter.py [--timeout-sec 600] [--skip-relay]
"""
import sys
import os
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

TRANSCRIPTS_DIR = Path('transcripts')
PROMPTS_DIR     = Path('plans/prompts')
BATTLES_JSON    = TRANSCRIPTS_DIR / 'battles.json'
BATTLE_TYPES    = TRANSCRIPTS_DIR / 'battle-types.json'
CACHE_PATH      = TRANSCRIPTS_DIR / 'rival-starter.json'
TIMEOUT_SEC     = 600


def latest_transcript() -> Path:
    skip = {'battles.json', 'min-battles.json', 'battle-types.json',
            'rival-starter.json'}
    for f in sorted(TRANSCRIPTS_DIR.glob('*.json'),
                    key=lambda f: f.stat().st_mtime, reverse=True):
        if f.name in skip:
            continue
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if isinstance(data, dict) and 'segments' in data:
                return f
        except Exception:
            pass
    raise FileNotFoundError('No usable transcript JSON in transcripts/')


def context_around(seg_list: list, t_sec: float, window: float = 45.0) -> str:
    win_a = t_sec - window
    win_b = t_sec + window
    out = []
    for s in seg_list:
        if win_a <= s['start'] <= win_b:
            out.append(f'[{s["start"]:.1f}s] {s.get("text", "").strip()}')
    return '\n'.join(out) if out else '(no context)'


CANONICAL_LOCATIONS = [
    'cherrygrove', 'azalea', 'burnedtower', 'goldenrod',
    'victoryroad', 'indigoplateau', 'mtmoon',
]


def build_prompt(transcript: dict, rival_battles_with_index: list[tuple[int, dict]]) -> str:
    segments = transcript.get('segments', [])
    # Intro context = first 120s of the video — most challenges announce the
    # team / starter choice up front.
    intro_ctx = '\n'.join(
        f'[{s["start"]:.1f}s] {s.get("text", "").strip()}'
        for s in segments if s['start'] < 120
    )

    rival_ctx_blocks = []
    for ordinal, (battle_index, b) in enumerate(rival_battles_with_index, start=1):
        ctx = context_around(segments, b['timestamp_sec'])
        rival_ctx_blocks.append(
            f'### Rival battle {ordinal} '
            f'(battle_index={battle_index}, trainer={b["trainer_name"]!r}, '
            f'@ {b["timestamp_sec"]:.1f}s)\n'
            f'description: {b.get("description", "")!r}\n\n'
            f'Transcript context (±45s):\n```\n{ctx}\n```'
        )
    rival_blocks_str = '\n\n'.join(rival_ctx_blocks)

    return f"""You are providing context for the rival battle intros in a Pokémon Gold/Silver/Crystal video. We need two pieces of information:

1. The **rival's starter type** (one of `fire`, `water`, `grass`) — fixed for the whole video.
2. The **canonical location** of each rival battle (one of `cherrygrove`, `azalea`, `burnedtower`, `goldenrod`, `victoryroad`, `indigoplateau`, `mtmoon`) — used to pick the right `silver-<location>-<type>-battle-intro.mov` per battle.

## Part 1 — Rival starter type

In Gen 2 the rival picks the starter with type advantage over the player:

| Player picks  | Rival picks  | Rival type → key |
|---------------|--------------|------------------|
| Chikorita     | Cyndaquil    | `fire`           |
| Cyndaquil     | Totodile     | `water`          |
| Totodile      | Chikorita    | `grass`          |

In challenge runs the player may not actually pick a starter — they're handed a pre-built team. In those cases the rival's starter is whatever the romhack assigns; identify it from the rival's Pokémon mentioned in the transcript.

**Pokémon → type:**

- Fire: Cyndaquil, Quilava, Typhlosion
- Water: Totodile, Croconaw, Feraligatr
- Grass: Chikorita, Bayleaf, Meganium

Pick your answer in this order:

1. Intro context (first 120s) — the streamer often announces "the rival has Cyndaquil" or "we picked X, so the rival has Y".
2. Each rival battle's transcript — during the fight, the streamer names the rival's Pokémon ("his Bayleaf is going to outspeed us").
3. Inference from the player's pick when only the player's starter is mentioned.

## Part 2 — Per-battle location

Map each rival battle to one of these canonical Gen-2 locations. Vanilla Crystal/GSC has 5 pre-E4 rival fights; HGSS keeps all 5 and adds 2 post-Champion encounters (mtmoon, indigoplateau).

### Canonical team table (research-grounded; sources: Bulbapedia, Serebii)

| # | Location key | Team (Crystal levels in parens) | Gym position |
|---|---|---|---|
| 1 | `cherrygrove` | Starter only (Lv 5) | Pre-Falkner |
| 2 | `azalea` | Gastly (12) + Zubat (14) + Starter (14-16) | After Bugsy, before Whitney |
| 3 | `burnedtower` | Magnemite (18) + Zubat (20) + Gastly (20) + Starter (22, 1st evo) | After Whitney, before Morty |
| 4 | `goldenrod` | Golbat + Haunter + Magnemite + **Sneasel** + Starter (~30, 1st or 2nd evo) | After Pryce, before Clair (Radio Tower / Underground takeover) |
| 5 | `victoryroad` | Crobat/Golbat + Gengar/Haunter + **Magneton** + Kadabra + Sneasel + **fully evolved starter** | After Clair, before E4 |
| 6 | `mtmoon` | Crobat + Gengar + Magneton + **Alakazam** + Sneasel + fully evolved starter (L50+) | HGSS post-Champion (first encounter) |
| 7 | `indigoplateau` | Same as Mt. Moon but levels 45-50 | HGSS post-Champion (Mon/Wed rematch) |

### Distinguishing signatures (in decreasing reliability)

**1. Sneasel** — appears starting at Goldenrod. The single strongest signal.
   - No Sneasel → `cherrygrove`, `azalea`, or `burnedtower`
   - Sneasel present → `goldenrod`, `victoryroad`, `mtmoon`, or `indigoplateau`

**2. Magnemite vs Magneton** (Sneasel-resolved)
   - Magnemite (not evolved) + no Sneasel → `burnedtower`
   - Magnemite + Sneasel → `goldenrod`
   - Magneton → `victoryroad` / `mtmoon` / `indigoplateau`

**3. Starter evolution stage**
   - Unevolved Lv 5 starter → `cherrygrove`
   - First-stage evolution (Bayleaf/Quilava/Croconaw) → `azalea` / `burnedtower` / `goldenrod`
   - Fully evolved (Meganium/Typhlosion/Feraligatr) → `victoryroad` / `mtmoon` / `indigoplateau`

**4. Zubat → Golbat → Crobat**
   - Zubat → `azalea` / `burnedtower`
   - Golbat → `goldenrod` / `victoryroad`
   - Crobat (Silver "matured") → `mtmoon` / `indigoplateau`

**5. Gastly → Haunter → Gengar**
   - Gastly → `azalea` / `burnedtower`
   - Haunter → `goldenrod` / `victoryroad`
   - Gengar → `victoryroad` (Crystal) or `mtmoon` / `indigoplateau` (HGSS post-game)

**6. Kadabra → Alakazam**
   - Kadabra → `victoryroad`
   - Alakazam → `mtmoon` or `indigoplateau`

**7. Team size**
   - 1 → `cherrygrove`
   - 3 → `azalea`
   - 4 → `burnedtower`
   - 5 → `goldenrod`
   - 6 → `victoryroad` / `mtmoon` / `indigoplateau`

### Cross-check by gym position

| Rival fight comes... | Then location is |
|---|---|
| Before Falkner | `cherrygrove` |
| After Bugsy, before Whitney | `azalea` |
| After Whitney, before Morty | `burnedtower` |
| After Pryce, before Clair | `goldenrod` |
| After Clair, before E4 | `victoryroad` |
| Post-Champion (first) | `mtmoon` |
| Post-Champion (rematch) | `indigoplateau` |

When composition and gym position disagree (rare, romhack territory), **trust gym position over composition** — the streamer's gym progress is more stable than the romhack's specific roster.

### Things to ignore / common pitfalls

- **Explicit transcript mentions of place names can MISLEAD.** The streamer might say "Burned Tower" while describing surroundings during a different fight. Always verify against composition + gym position before trusting verbal cues.
- **`Rival N` from detect_battles is an in-video ordinal, NOT a canonical position.** If the streamer skipped or cut a fight, the numbering shifts. Use the rules above to recover canonical location.
- **Mahogany Rocket Hideout has a Silver CUTSCENE in HGSS but typically no battle** — don't slot a rival here.

## Intro context (first 120 seconds)

```
{intro_ctx}
```

## Rival battle contexts ({len(rival_battles_with_index)} found)

{rival_blocks_str}

## Output

Reply with ONLY a single JSON object (no markdown fences, no extra text):

```json
{{
  "rival_starter_type": "fire" | "water" | "grass" | null,
  "confidence": "high" | "medium" | "low",
  "evidence": "short quote / paraphrase that gave away the starter type (with timestamp if possible)",
  "reasoning": "1-2 sentences",
  "rivals_by_battle_index": {{
    "0": "cherrygrove",
    "5": "burnedtower",
    "7": "goldenrod"
  }}
}}
```

`rivals_by_battle_index` keys are battle index strings (from the `battle_index=N` shown in each block above). Values are one of the canonical-location strings. Include every rival battle.

If you genuinely cannot pin down a location for some rival, use `null` for that one and explain in `reasoning`. If you cannot determine the starter type, set `rival_starter_type` to `null` and explain what's missing.
"""


def poll(out_path: Path, timeout_sec: int) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if out_path.exists():
            raw = out_path.read_text(encoding='utf-8').strip()
            return json.loads(raw)
        time.sleep(2)
    raise TimeoutError(f'No relay response after {timeout_sec}s — expected {out_path}')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--timeout-sec', type=int, default=TIMEOUT_SEC)
    ap.add_argument('--skip-relay', action='store_true',
                    help='Read existing .out.md and cache without re-running the relay')
    args = ap.parse_args()

    if not BATTLES_JSON.exists():
        print(f'ERROR: {BATTLES_JSON} not found — run detect_battles.py first',
              file=sys.stderr)
        return 1
    if not BATTLE_TYPES.exists():
        print(f'ERROR: {BATTLE_TYPES} not found — run classify_battles.py first',
              file=sys.stderr)
        return 1

    battles = json.loads(BATTLES_JSON.read_text(encoding='utf-8'))
    types   = json.loads(BATTLE_TYPES.read_text(encoding='utf-8'))

    # Filter to rival battles only — keep both the original battle_index and the entry
    rivals_with_idx: list[tuple[int, dict]] = []
    for i, b in enumerate(battles):
        t = types.get(str(i)) or types.get(i)
        if t and t.get('type') == 'rival':
            rivals_with_idx.append((i, b))

    if not rivals_with_idx:
        result = {
            'rival_starter_type': None,
            'confidence': 'n/a',
            'reasoning': 'No rival battles classified in battle-types.json — '
                         'no Silver intro selection needed.',
            'rivals_by_battle_index': {},
        }
        CACHE_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                              encoding='utf-8')
        print(f'No rival battles — wrote {CACHE_PATH}')
        return 0

    print(f'Found {len(rivals_with_idx)} rival battle(s):')
    for i, b in rivals_with_idx:
        print(f'  battle_index={i:2d}  {b["timestamp_sec"]:7.1f}s  {b["trainer_name"]}')

    t_path = latest_transcript()
    stem   = t_path.stem
    transcript = json.loads(t_path.read_text(encoding='utf-8'))

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    in_path  = PROMPTS_DIR / 'rival-starter.in.md'
    out_path = PROMPTS_DIR / 'rival-starter.out.md'

    if args.skip_relay:
        if not out_path.exists():
            print(f'ERROR: --skip-relay requires existing {out_path}', file=sys.stderr)
            return 1
        print(f'Skip-relay: reading {out_path}')
        result = json.loads(out_path.read_text(encoding='utf-8').strip())
    else:
        if out_path.exists():
            out_path.unlink()
        in_path.write_text(build_prompt(transcript, rivals_with_idx),
                           encoding='utf-8')
        print(f'Relay prompt → {in_path}')
        print(f'Waiting for {out_path} ...')
        try:
            result = poll(out_path, args.timeout_sec)
        except TimeoutError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1

    CACHE_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                          encoding='utf-8')
    print(f'\nRival starter: {result.get("rival_starter_type")!r} '
          f'(confidence: {result.get("confidence")})')
    print(f'  evidence: {result.get("evidence", "")}')
    print(f'  reasoning: {result.get("reasoning", "")}')
    print(f'\nCached: {CACHE_PATH}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
