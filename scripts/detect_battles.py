"""
Identify first-time trainer battle starts from a Pokémon stream transcript.

Uses the relay pattern from IRLPC Hyperframes (scripts/lib/llm.mjs):
  1. Writes a prompt to plans/prompts/battle-detect-<stem>.in.md
  2. Polls for plans/prompts/battle-detect-<stem>.out.md (written by Claude Code)
  3. Parses and saves the battles JSON

Usage:
    python detect_battles.py transcripts/4.json [--out transcripts/battles.json]

Claude Code workflow (separate step):
    - Read the generated .in.md file
    - Analyze the transcript
    - Write the JSON response to the corresponding .out.md file
    - The script will auto-detect it and continue

Output JSON format:
    [
      {
        "timestamp_sec": 42.3,
        "trainer_name": "Brock",
        "description": "brief reason this is a battle start"
      }
    ]
"""
import sys
import os
import argparse
import json
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401


SYSTEM_PROMPT = """You are analyzing a Pokémon game stream transcript to identify trainer battles.

Find every moment where the player starts a battle against a NAMED TRAINER (gym leaders, rival, etc.) FOR THE FIRST TIME.
- Include: gym leaders, rival encounters, named trainers (e.g. "Bug Catcher Bob wants to fight!")
- Exclude: wild Pokémon encounters, rematches with trainers already seen
- Use dialogue context to determine "first time" (no prior mention of that trainer's name earlier in the transcript)

Return ONLY a JSON array. No explanation, no markdown fences, just raw JSON:
[
  {
    "timestamp_sec": <float — seconds into the audio when the battle starts>,
    "trainer_name": "<trainer name or 'unknown'>",
    "description": "<one sentence explaining what dialogue/context signals this battle start>"
  }
]

If no trainer battle starts are found, return: []"""


def build_prompt(data: dict) -> str:
    duration = data.get('duration', 0)
    segments = data.get('segments', [])
    audio    = data.get('audio', 'unknown')

    lines = [f'# Battle Detection — {Path(audio).name}',
             f'Duration: {duration:.1f}s | Segments: {len(segments)}', '',
             '## System', '', SYSTEM_PROMPT, '',
             '## Transcript (timestamped)', '']
    for seg in segments:
        lines.append(f'[{seg["start"]:8.2f}] {seg["text"].strip()}')

    lines += ['', '---', '',
              '**Write your JSON response to the corresponding `.out.md` file.**']
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('transcript', type=Path)
    parser.add_argument('--out',          default=None, type=Path)
    parser.add_argument('--plans-dir',    default='plans/prompts', type=Path)
    parser.add_argument('--poll-sec',     default=2.0,  type=float)
    parser.add_argument('--timeout-sec',  default=600,  type=float, help='Max wait for .out.md (seconds)')
    args = parser.parse_args()

    if not args.transcript.exists():
        print(f'Transcript not found: {args.transcript}', file=sys.stderr)
        return 1

    data     = json.loads(args.transcript.read_text(encoding='utf-8'))
    out_path = args.out or args.transcript.parent / 'battles.json'

    # Write relay prompt
    args.plans_dir.mkdir(parents=True, exist_ok=True)
    stem     = args.transcript.stem
    in_path  = args.plans_dir / f'battle-detect-{stem}.in.md'
    resp_path = args.plans_dir / f'battle-detect-{stem}.out.md'

    # Remove stale out file from previous run
    if resp_path.exists():
        resp_path.unlink()

    prompt_text = build_prompt(data)
    in_path.write_text(prompt_text, encoding='utf-8')
    in_mtime = in_path.stat().st_mtime

    print(f'Prompt written to: {in_path}')
    print(f'Waiting for Claude Code to write response to: {resp_path}')
    print(f'(timeout: {args.timeout_sec:.0f}s)')

    deadline = time.time() + args.timeout_sec
    while time.time() < deadline:
        if resp_path.exists() and resp_path.stat().st_mtime >= in_mtime:
            raw = resp_path.read_text(encoding='utf-8').strip()
            # Strip markdown fences if present
            if raw.startswith('```'):
                raw = '\n'.join(raw.split('\n')[1:])
            if raw.endswith('```'):
                raw = '\n'.join(raw.split('\n')[:-1])
            raw = raw.strip()
            try:
                battles = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f'Could not parse JSON from {resp_path}: {e}', file=sys.stderr)
                print(f'Raw content:\n{raw}', file=sys.stderr)
                return 1

            for b in battles:
                b.setdefault('first_time', True)

            out_path.write_text(json.dumps(battles, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'\nFound {len(battles)} battle starts:')
            for b in battles:
                print(f'  {b["timestamp_sec"]:8.2f}s  {b.get("trainer_name","?"):20s}  {b.get("description","")[:60]}')
            print(f'Wrote {out_path}')
            return 0

        time.sleep(args.poll_sec)

    print(f'Timeout after {args.timeout_sec:.0f}s — no response received.', file=sys.stderr)
    print(f'To respond manually, write JSON to: {resp_path}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
