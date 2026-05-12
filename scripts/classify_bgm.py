"""
Phase 1 of the BGM tagging pipeline: name-based LLM classification.

Lists all clips in the bgm bin of the current Resolve project and writes a
relay prompt asking Claude to tag each track based on the vibe of its
filename. Categories:

  battle_rival    — sounds like a rival theme (urgent, melodic, "personal")
  battle_gym      — sounds like a gym leader theme (epic, escalating)
  battle_generic  — fast/energetic battle-y vibe but not gym/rival-specific
  general         — calm/ambient/exploration; default
  exclude         — definitely shouldn't be placed (jingles, intros, etc.)

The relay output is merged into `~/.resolve-mcp/bgm-tags.json`:

  {
    "<filename>": {
      "tag":        "battle_gym",
      "name_conf":  "high|medium|low",
      "name_reason": "explanation",
      "audio_features": null   // filled in by analyze_bgm_audio.py later
    },
    ...
  }

Usage:
    python classify_bgm.py [--timeout-sec 600] [--skip-relay]
"""
import sys
import os
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

PROMPTS_DIR = Path('plans/prompts')
TAGS_PATH   = Path.home() / '.resolve-mcp' / 'bgm-tags.json'
TIMEOUT_SEC = 600


def find_subfolder(parent, name):
    for sub in (parent.GetSubFolderList() or []):
        if sub.GetName() == name:
            return sub
    return None


def collect_clips_recursive(bin_):
    out = list(bin_.GetClipList() or [])
    for sub in (bin_.GetSubFolderList() or []):
        out.extend(collect_clips_recursive(sub))
    return out


def build_prompt(filenames: list[str]) -> str:
    lines = ['You are tagging music tracks by vibe based ONLY on their filenames.',
             '',
             '## Categories (pick exactly one per track)',
             '',
             '- **battle_rival** — sounds like a Pokémon RIVAL theme: urgent, melodic, "personal stakes" vibe. Names that suggest a personal duel or confrontation. Examples by vibe: "Take them down!", "This one\'s For Real!"',
             '- **battle_gym** — sounds like a Pokémon GYM LEADER theme: epic, escalating, big boss energy. Names suggesting a major fight or titanic clash. Examples by vibe: "Clash of Titans", "Big Baddies"',
             '- **battle_generic** — fast/energetic/percussive battle vibe but not specifically gym or rival. A solid general-purpose action track.',
             '- **general** — calm, ambient, lo-fi, exploration, neutral, chill, jazz, journey, melodic-but-mellow. The DEFAULT for anything that isn\'t obviously battle.',
             '- **exclude** — clearly not BGM material: jingles, stings, intros, sound effects, voice samples, anything under ~30 seconds of likely actual music.',
             '',
             '## Rules',
             '',
             '- ONE tag per track. No multi-tagging.',
             '- Default to **general** if uncertain. Battle tags should be reserved for tracks whose names *clearly* convey action/conflict.',
             '- Be conservative with `battle_rival` and `battle_gym` — these are narrative-specific. Many tracks will be `battle_generic` instead.',
             '- `exclude` is rare; only use it when the name strongly suggests it isn\'t actually music (jingle, sting, voice clip, etc.).',
             '',
             '## Tracks',
             '',
             'Classify each of the following:',
             '']
    for fn in filenames:
        lines.append(f'- `{fn}`')

    lines += ['',
              '## Output',
              '',
              'Reply with ONLY a single JSON object (no markdown fences, no commentary). Keys are filenames as listed above; values are objects with three fields:',
              '',
              '```json',
              '{',
              '  "<filename>": {"tag": "battle_gym", "name_conf": "high", "name_reason": "1 short sentence"},',
              '  ...',
              '}',
              '```',
              '',
              'Tag must be exactly one of: `battle_rival`, `battle_gym`, `battle_generic`, `general`, `exclude`. `name_conf` must be `high`, `medium`, or `low`. Include every filename listed.',
              '']
    return '\n'.join(lines)


def poll(out_path: Path, timeout_sec: int) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if out_path.exists():
            return json.loads(out_path.read_text(encoding='utf-8').strip())
        time.sleep(2)
    raise TimeoutError(f'No relay response after {timeout_sec}s')


def merge_tags(existing: dict, new_tags: dict) -> dict:
    """Update existing tags with new classifications (preserving audio_features)."""
    merged = dict(existing)
    for fn, info in new_tags.items():
        prev = merged.get(fn, {})
        merged[fn] = {
            'tag':         info.get('tag', 'general'),
            'name_conf':   info.get('name_conf', 'medium'),
            'name_reason': info.get('name_reason', ''),
            'audio_features': prev.get('audio_features'),
        }
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--timeout-sec', type=int, default=TIMEOUT_SEC)
    ap.add_argument('--skip-relay', action='store_true',
                    help='Skip the relay; read existing bgm-tags.in/.out.md only')
    args = ap.parse_args()

    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    project = resolve.GetProjectManager().GetCurrentProject()
    pool    = project.GetMediaPool()
    root    = pool.GetRootFolder()
    assets  = find_subfolder(root, 'assets')
    if assets is None:
        print('ERROR: "assets" bin not found.', file=sys.stderr)
        return 1
    bgm_bin = find_subfolder(assets, 'bgm')
    if bgm_bin is None:
        print('ERROR: "bgm" sub-bin not found.', file=sys.stderr)
        return 1

    clips     = collect_clips_recursive(bgm_bin)
    filenames = sorted({(c.GetName() or '').strip() for c in clips if c.GetName()})
    print(f'BGM clips found: {len(filenames)}')

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    in_path  = PROMPTS_DIR / 'bgm-tags.in.md'
    out_path = PROMPTS_DIR / 'bgm-tags.out.md'

    if args.skip_relay:
        if not out_path.exists():
            print(f'ERROR: --skip-relay requires existing {out_path}', file=sys.stderr)
            return 1
        new_tags = json.loads(out_path.read_text(encoding='utf-8').strip())
    else:
        if out_path.exists():
            out_path.unlink()
        in_path.write_text(build_prompt(filenames), encoding='utf-8')
        print(f'Relay prompt → {in_path}')
        print(f'Waiting for {out_path} ...')
        try:
            new_tags = poll(out_path, timeout_sec=args.timeout_sec)
        except TimeoutError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1

    if not isinstance(new_tags, dict):
        print(f'ERROR: expected JSON object in {out_path}, got {type(new_tags).__name__}',
              file=sys.stderr)
        return 1
    missing = set(filenames) - set(new_tags.keys())
    if missing:
        print(f'WARN: {len(missing)} filename(s) missing from relay response. '
              f'Defaulting to "general".')
        for fn in missing:
            new_tags[fn] = {'tag': 'general', 'name_conf': 'low',
                            'name_reason': 'missing from relay response'}

    existing = {}
    if TAGS_PATH.exists():
        try:
            existing = json.loads(TAGS_PATH.read_text(encoding='utf-8'))
        except Exception:
            existing = {}

    merged = merge_tags(existing, new_tags)
    TAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TAGS_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding='utf-8')

    # Summary
    by_tag: dict[str, int] = {}
    for v in merged.values():
        by_tag[v['tag']] = by_tag.get(v['tag'], 0) + 1
    print(f'\nWrote tags → {TAGS_PATH}')
    print('Tag distribution:')
    for tag, n in sorted(by_tag.items()):
        print(f'  {tag:18s} {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
