"""End-to-end smoke test for gen1-leader-tracks against the Victreebel session log."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from leader_asset_map import resolve_leader, detect_version_from_meta, first_appearance_map

meta_path = Path(os.path.expandvars(
    r'%APPDATA%\rbypc-frontend\logs\2026-05-16T04_28_56_871__Pikachu__Standard\meta.json'
))
meta = json.loads(meta_path.read_text(encoding='utf-8'))
version = detect_version_from_meta(meta)
print(f'meta.json["version"] = {meta["version"]!r} -> detected version: {version!r}')
print(f'meta.json["pokemon"] = {meta["pokemon"]!r} (run is for Victreebel)')
print()

# Victreebel battle sequence (from events.json battle-starts in order)
sequence = ['RIVAL', 'RIVAL', 'BROCK', 'MISTY', 'ERIKA', 'LT.SURGE', 'GIOVANNI_GYM',
            'KOGA', 'BRUNO', 'LORELEI', 'SABRINA', 'BLAINE', 'LANCE', 'AGATHA', 'RIVAL3']

rby = Path(r'C:\Programming\RBYNewLayout')
fmap = first_appearance_map(sequence)

print(f'[Victreebel battle sequence, version={version}]\n')
print(f'{"#":<3} {"leader_key":<14} {"first?":<7} {"video":<28} {"audio":<18}')
print('-' * 90)
for i, key in enumerate(sequence):
    a = resolve_leader(key, version, rby)
    if a is None:
        print(f'{i:<3} {key:<14} -- unknown --')
        continue
    is_first = 'YES' if fmap[i] else 'no'
    video = a.intro_video_filename or '(audio-only)'
    print(f'{i:<3} {key:<14} {is_first:<7} {video:<28} {a.audio_filename:<18}')

print()
print('Summary:')
intros = sum(1 for i, k in enumerate(sequence)
             if fmap[i] and (a := resolve_leader(k, version, rby)) and a.has_intro_video)
audio_only_firsts = sum(1 for i, k in enumerate(sequence)
                         if fmap[i] and (a := resolve_leader(k, version, rby)) and not a.has_intro_video)
repeats = sum(1 for v in fmap.values() if not v)
print(f'  Total battles: {len(sequence)}')
print(f'  First-appearance with V1 intro: {intros}')
print(f'  First-appearance audio-only (Giovanni 1/2, Rival): {audio_only_firsts}')
print(f'  Subsequent appearances (no intro): {repeats}')
