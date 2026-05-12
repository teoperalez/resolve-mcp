"""
Detect whether a Pokémon gameplay video is a "Minimum Battles Series" via LLM
relay.

A Minimum Battles Series is one where:
  - The player uses at least 8 DIFFERENT Pokémon over the course of the video
  - The same trainer (or several similar trainers) is fought repeatedly, each
    attempt with a different Pokémon — usually framed as a challenge to find
    the minimum number / different combinations of Pokémon that can win a fight

Workflow:
  1. Read the most recent transcript at `transcripts/*.json`.
  2. Write a prompt to `plans/prompts/min-battles-<stem>.in.md` asking the active
     Claude to classify the video.
  3. Wait for `plans/prompts/min-battles-<stem>.out.md` containing a single JSON
     object: {"is_minimum_battles": bool, "pokemon_count": N,
              "trainers_attempted": [...], "reasoning": "..."}
  4. Cache result to `transcripts/min-battles.json` so `insert_intro_outro.py`
     can read it without re-running the relay.

Usage:
    python detect_minimum_battles.py [--timeout-sec 600] [--skip-relay]
"""
import sys
import os
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

PROMPTS_DIR     = Path('plans/prompts')
TRANSCRIPTS_DIR = Path('transcripts')
CACHE_PATH      = TRANSCRIPTS_DIR / 'min-battles.json'
TIMEOUT_SEC     = 600


def latest_transcript() -> Path:
    candidates = sorted(
        (f for f in TRANSCRIPTS_DIR.glob('*.json')
         if f.name not in {'battles.json', 'min-battles.json'}),
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    for f in candidates:
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if isinstance(data, dict) and 'segments' in data:
                return f
        except Exception:
            pass
    raise FileNotFoundError('No usable transcript found in transcripts/')


def build_prompt(transcript: dict, stem: str) -> str:
    text = (transcript.get('text') or '').strip()
    # 12k chars is roughly half a 30-min transcript — enough for classification
    # without blowing the relay buffer.
    if len(text) > 12000:
        text = text[:12000] + '\n\n[…transcript truncated…]'

    return f"""You are classifying a Pokémon gameplay video as a Minimum Battles Series or a normal playthrough.

## What is a Minimum Battles Series?

A Minimum Battles Series is a specific challenge format where the YouTuber tests how many DIFFERENT Pokémon can beat a particular fight (or a small set of fights), running the same battle over and over with different team members. Signals:

- **At least 8 different Pokémon** used across the video. Look for explicit mentions like "let's try Geodude", "next up Pidgey", "now Caterpie", etc.
- **Repeated attempts at the same (or very similar) trainer fight** — e.g., the same gym leader fought 8–12 times in a row, each with a fresh single Pokémon.
- **Framing language** like "minimum battles", "minimum encounter", "soloing", "can X beat Y", "let's see if [Pokemon] can do it", "next attempt".

## What it is NOT

A normal playthrough is one game progressing through multiple unique trainers/gyms with a stable team of a few Pokémon. The player may switch Pokémon between fights, but each trainer is fought ONCE.

## Transcript (stem: `{stem}`)

```
{text}
```

## Output

Reply with ONLY a single JSON object (no markdown fences, no surrounding text):

{{"is_minimum_battles": true|false, "pokemon_count": N, "trainers_attempted": ["Trainer A", "Trainer B"], "reasoning": "1-2 sentences explaining the call"}}

- `pokemon_count` = your best estimate of distinct Pokémon used by the player.
- `trainers_attempted` = the trainers the player fought (de-duplicated). For a Minimum Battles Series this is usually 1–3 entries; for a normal playthrough it can be many.
- Be decisive: pick true or false, not null.
"""


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
    ap.add_argument('--skip-relay', action='store_true',
                    help='Read existing min-battles-<stem>.out.md without re-asking')
    args = ap.parse_args()

    transcript_path = latest_transcript()
    transcript      = json.loads(transcript_path.read_text(encoding='utf-8'))
    stem            = transcript_path.stem
    print(f'Transcript: {transcript_path}  (stem={stem})')

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    in_path  = PROMPTS_DIR / f'min-battles-{stem}.in.md'
    out_path = PROMPTS_DIR / f'min-battles-{stem}.out.md'

    if args.skip_relay:
        if not out_path.exists():
            print(f'ERROR: --skip-relay requires existing {out_path}', file=sys.stderr)
            return 1
        result = json.loads(out_path.read_text(encoding='utf-8').strip())
    else:
        if out_path.exists():
            out_path.unlink()
        in_path.write_text(build_prompt(transcript, stem), encoding='utf-8')
        print(f'Relay prompt → {in_path}')
        print(f'Waiting for {out_path} ...')
        try:
            result = poll(out_path, timeout_sec=args.timeout_sec)
        except TimeoutError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1

    # Validate shape
    if not isinstance(result, dict) or 'is_minimum_battles' not in result:
        print(f'ERROR: relay response missing is_minimum_battles: {result}',
              file=sys.stderr)
        return 1

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps({**result, 'transcript_stem': stem},
                                     indent=2), encoding='utf-8')
    print(f'\nResult: is_minimum_battles={result["is_minimum_battles"]}  '
          f'pokemon_count={result.get("pokemon_count", "?")}  '
          f'reasoning="{result.get("reasoning", "")}"')
    print(f'Cached → {CACHE_PATH}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
