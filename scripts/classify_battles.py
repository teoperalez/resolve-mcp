"""
Classify each battle in `transcripts/battles.json` as rival / gym / other via
LLM relay.

Writes a relay prompt listing each battle's trainer_name + 1-2 surrounding
transcript snippets (so the classifier has narrative context). Claude returns
a single JSON object mapping battle_index → category. Result cached in
`transcripts/battle-types.json`.

Categories:
  rival — the player's main rival (e.g. Silver/Blue/Gary). Personal stakes.
  gym   — a numbered gym leader battle (Falkner, Bugsy, Whitney, …).
  other — route trainers, team rocket grunts, optional NPCs.

Usage:
    python classify_battles.py [--timeout-sec 600] [--skip-relay]
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
CACHE_PATH      = TRANSCRIPTS_DIR / 'battle-types.json'
TIMEOUT_SEC     = 600


def latest_transcript() -> Path:
    for f in sorted(TRANSCRIPTS_DIR.glob('*.json'),
                    key=lambda f: f.stat().st_mtime, reverse=True):
        if f.name in {'battles.json', 'min-battles.json', 'battle-types.json'}:
            continue
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if isinstance(data, dict) and 'segments' in data:
                return f
        except Exception:
            pass
    raise FileNotFoundError('No usable transcript JSON in transcripts/')


def context_for_battle(battle: dict, transcript: dict, window_sec: float = 30.0) -> str:
    """Return ~30s of transcript around the battle start as context."""
    start = battle['timestamp_sec']
    win_a = start - window_sec
    win_b = start + window_sec
    out = []
    for seg in transcript.get('segments', []):
        if win_a <= seg['start'] <= win_b:
            out.append(f'[{seg["start"]:.1f}s] {seg.get("text", "").strip()}')
    return '\n'.join(out) if out else '(no context)'


def build_prompt(battles: list[dict], transcript: dict) -> str:
    lines = ["""You are classifying Pokémon trainer battles in a YouTube video as one of:

- **rival** — the player's main story rival (often named "Silver" in Gen 2; sometimes "Blue", "Gary", "May", "Barry", etc.). The rival is the recurring antagonist who shows up at multiple plot beats. Often introduced as "Rival" or "Rival 1" in the transcript before getting a proper name.
- **gym** — a numbered gym leader (Gen 2 Johto: Falkner, Bugsy, Whitney, Morty, Chuck, Jasmine, Pryce, Clair; Gen 2 Kanto: Brock, Misty, Lt. Surge, Erika, Janine, Sabrina, Blaine, Blue. Other gens have their own gym leaders).
- **other** — route trainers (Bug Catcher, Lass, Youngster, Sailor, etc.), Team Rocket grunts, optional NPC battles, executives, anything not gym/rival.

For each battle, look at the trainer name AND the ~30s of surrounding transcript context (player commentary often gives away the category — "first gym", "rival fight", "rocket grunt", etc.).

## Battles
"""]
    for i, b in enumerate(battles):
        ctx = context_for_battle(b, transcript)
        lines.append(f"### Battle {i}: {b['trainer_name']!r}  ({b['timestamp_sec']:.1f}s)")
        lines.append(f"description: {b.get('description', '')!r}")
        lines.append('')
        lines.append(f'Transcript context (±30s):')
        lines.append('```')
        lines.append(ctx)
        lines.append('```')
        lines.append('')

    lines.append("""## Output

Reply with ONLY a single JSON object (no markdown fences, no extra text). Keys are battle indices as strings; values are objects with two fields:

```json
{
  "0": {"type": "rival", "reasoning": "short explanation"},
  "1": {"type": "gym", "reasoning": "..."},
  ...
}
```

`type` must be exactly `rival`, `gym`, or `other`. Include every battle index.
""")
    return '\n'.join(lines)


def poll(out_path: Path, timeout_sec: int) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if out_path.exists():
            return json.loads(out_path.read_text(encoding='utf-8').strip())
        time.sleep(2)
    raise TimeoutError(f'No relay response after {timeout_sec}s')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--timeout-sec', type=int, default=TIMEOUT_SEC)
    ap.add_argument('--skip-relay', action='store_true')
    args = ap.parse_args()

    if not BATTLES_JSON.exists():
        print(f'ERROR: {BATTLES_JSON} not found. Run detect_battles.py first.',
              file=sys.stderr)
        return 1
    battles    = json.loads(BATTLES_JSON.read_text(encoding='utf-8'))
    transcript = json.loads(latest_transcript().read_text(encoding='utf-8'))
    print(f'Battles: {len(battles)}  Transcript segs: {len(transcript.get("segments", []))}')

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    in_path  = PROMPTS_DIR / 'battle-types.in.md'
    out_path = PROMPTS_DIR / 'battle-types.out.md'

    if args.skip_relay:
        if not out_path.exists():
            print(f'ERROR: --skip-relay requires existing {out_path}', file=sys.stderr)
            return 1
        result = json.loads(out_path.read_text(encoding='utf-8').strip())
    else:
        if out_path.exists():
            out_path.unlink()
        in_path.write_text(build_prompt(battles, transcript), encoding='utf-8')
        print(f'Relay prompt → {in_path}')
        print(f'Waiting for {out_path} ...')
        try:
            result = poll(out_path, timeout_sec=args.timeout_sec)
        except TimeoutError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1

    # Validate + cache
    types = {}
    for i, b in enumerate(battles):
        info = result.get(str(i)) or result.get(i)
        t = (info or {}).get('type', 'other') if info else 'other'
        if t not in ('rival', 'gym', 'other'):
            t = 'other'
        types[i] = {
            'trainer_name': b['trainer_name'],
            'timestamp_sec': b['timestamp_sec'],
            'type': t,
            'reasoning': (info or {}).get('reasoning', ''),
        }
        print(f"  battle {i}: {b['trainer_name']:14s} → {t}")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(types, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'\nWrote → {CACHE_PATH}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
