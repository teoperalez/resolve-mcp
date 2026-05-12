"""
Phase 2 of the BGM tagging pipeline: audio-feature analysis via librosa.

For each track listed in ~/.resolve-mcp/bgm-tags.json, compute:
  - bpm                — estimated tempo (beats per minute)
  - rms_mean           — average energy (loudness proxy)
  - spectral_centroid  — average spectral centroid Hz ("brightness")
  - onset_rate         — onsets per second (percussive density)
  - duration_sec       — total length

A heuristic classifies each track from audio alone into one of:
  battle      — BPM ≥ 120 AND high onset_rate, OR fast + bright
  energetic   — BPM 100–120 or middle energy
  calm        — slow tempo / low onset_rate

The script merges these into bgm-tags.json under the `audio_features` key and
flags **mismatches** between the LLM name-tag and the audio classification —
e.g. a track tagged `general` by name but classified `battle` by audio.

The actual `tag` field is NOT overwritten — you decide whether to update it
based on the flagged mismatches.

Usage:
    python analyze_bgm_audio.py [--limit N] [--reanalyze]
"""
import sys
import os
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

TAGS_PATH = Path.home() / '.resolve-mcp' / 'bgm-tags.json'

# Heuristic thresholds — tuned for typical lo-fi/chiptune/orchestral mixes.
# "Battle" requires fast tempo AND high onset density AND solid energy. Loose
# thresholds false-positive uptempo lo-fi.
BPM_FAST        = 130
BPM_MED         = 110
ONSET_HIGH      = 5.0     # onsets per second (high percussive density)
ONSET_MED       = 3.5
RMS_HIGH        = 0.12    # rough energy threshold (varies per file)
SPECTRAL_BRIGHT = 3000.0  # Hz


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


def audio_features(path: Path) -> dict | None:
    """Return BPM / energy / brightness for the file, or None on failure."""
    try:
        import librosa
        import numpy as np
    except ImportError as e:
        print(f'  librosa import failed: {e}')
        return None

    try:
        # Load mono, native sample rate. For long files (>10 min) load only
        # the first 3 minutes to keep this fast.
        y, sr = librosa.load(str(path), mono=True, sr=None, duration=180.0)
        if y.size == 0:
            return None

        duration_sec = float(len(y)) / sr
        rms_mean     = float(np.mean(librosa.feature.rms(y=y)[0]))
        sc_mean      = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)[0]))
        onset_env    = librosa.onset.onset_strength(y=y, sr=sr)
        onsets       = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
        onset_rate   = float(len(onsets)) / duration_sec if duration_sec > 0 else 0.0
        tempo, _     = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
        bpm          = float(tempo.item() if hasattr(tempo, 'item') else tempo)

        return {
            'bpm':                round(bpm, 1),
            'rms_mean':           round(rms_mean, 4),
            'spectral_centroid':  round(sc_mean, 0),
            'onset_rate':         round(onset_rate, 2),
            'duration_sec':       round(duration_sec, 1),
        }
    except Exception as e:
        print(f'  feature extraction failed: {e}')
        return None


def classify_from_audio(features: dict) -> str:
    bpm     = features['bpm']
    rms     = features['rms_mean']
    bright  = features['spectral_centroid']
    onsets  = features['onset_rate']

    # Battle: fast AND high onset AND solid energy. All three required to avoid
    # tagging chill-but-uptempo lo-fi as battle.
    if bpm >= BPM_FAST and onsets >= ONSET_HIGH and rms >= RMS_HIGH:
        return 'battle'
    # Energetic: at least 2 of (medium BPM, medium onsets, high energy).
    energetic_hits = sum([
        bpm >= BPM_MED,
        onsets >= ONSET_MED,
        rms >= RMS_HIGH,
    ])
    if energetic_hits >= 2:
        return 'energetic'
    return 'calm'


def name_to_audio_compat(name_tag: str, audio_class: str) -> bool:
    """Return True if the name-tag and audio classification are 'compatible'
    (i.e., no obvious mismatch)."""
    battle_name_tags = {'battle_rival', 'battle_gym', 'battle_generic'}
    if name_tag in battle_name_tags:
        # Battle-named tracks should be 'battle' or 'energetic'
        return audio_class in ('battle', 'energetic')
    if name_tag == 'general':
        # General-named tracks should be 'calm' or 'energetic' (not full battle)
        return audio_class != 'battle'
    return True  # 'exclude' — don't bother flagging


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--limit', type=int, default=0,
                    help='Process at most N tracks (0 = all)')
    ap.add_argument('--reanalyze', action='store_true',
                    help='Recompute features even if already present')
    args = ap.parse_args()

    if not TAGS_PATH.exists():
        print(f'ERROR: {TAGS_PATH} not found. Run classify_bgm.py first.',
              file=sys.stderr)
        return 1

    tags = json.loads(TAGS_PATH.read_text(encoding='utf-8'))
    print(f'Loaded {len(tags)} tagged tracks from {TAGS_PATH}')

    # Build filename → file-path map by walking the bgm bin in Resolve so we
    # use the actual paths the project knows about.
    import DaVinciResolveScript as dvr
    project = dvr.scriptapp('Resolve').GetProjectManager().GetCurrentProject()
    pool    = project.GetMediaPool()
    root    = pool.GetRootFolder()
    assets  = find_subfolder(root, 'assets')
    bgm_bin = find_subfolder(assets, 'bgm') if assets else None
    if bgm_bin is None:
        print('ERROR: bgm bin not found.', file=sys.stderr)
        return 1

    fn_to_path: dict[str, str] = {}
    for clip in collect_clips_recursive(bgm_bin):
        name = (clip.GetName() or '').strip()
        path = clip.GetClipProperty('File Path') or ''
        if name and path:
            fn_to_path[name] = path

    # Process each tagged track
    to_process = [fn for fn in tags
                  if (args.reanalyze or not tags[fn].get('audio_features'))
                  and tags[fn].get('tag') != 'exclude']
    if args.limit > 0:
        to_process = to_process[:args.limit]
    print(f'Tracks to analyze: {len(to_process)}')

    t0 = time.time()
    for i, fn in enumerate(to_process, 1):
        path_str = fn_to_path.get(fn)
        if not path_str:
            print(f'  [{i:3d}/{len(to_process)}] {fn!r}: no file path')
            continue
        path = Path(path_str)
        if not path.exists():
            print(f'  [{i:3d}/{len(to_process)}] {fn!r}: file missing: {path}')
            continue

        print(f'  [{i:3d}/{len(to_process)}] {fn!r}...', end='', flush=True)
        feats = audio_features(path)
        if feats is None:
            print('  FAILED')
            continue
        audio_cls = classify_from_audio(feats)
        tags[fn]['audio_features']     = feats
        tags[fn]['audio_classification'] = audio_cls
        tags[fn]['name_audio_match']   = name_to_audio_compat(tags[fn]['tag'], audio_cls)

        print(f'  bpm={feats["bpm"]:5.1f}  onsets={feats["onset_rate"]:.2f}/s  '
              f'rms={feats["rms_mean"]:.3f}  → {audio_cls}'
              f'{"  MISMATCH" if not tags[fn]["name_audio_match"] else ""}')

        # Save progress every 25 tracks so a crash doesn't lose work
        if i % 25 == 0:
            TAGS_PATH.write_text(json.dumps(tags, indent=2, ensure_ascii=False),
                                 encoding='utf-8')

    TAGS_PATH.write_text(json.dumps(tags, indent=2, ensure_ascii=False), encoding='utf-8')
    elapsed = time.time() - t0
    print(f'\nDone in {elapsed:.1f}s. Wrote → {TAGS_PATH}')

    # Mismatch report
    mismatches = [(fn, v) for fn, v in tags.items()
                  if v.get('audio_features') and not v.get('name_audio_match', True)]
    print(f'\nMismatches between name-tag and audio classification: {len(mismatches)}')
    for fn, v in mismatches:
        feats = v['audio_features']
        print(f'  {fn!r}: name={v["tag"]:14s}  audio={v["audio_classification"]:9s}'
              f'  bpm={feats["bpm"]:5.1f}  onsets={feats["onset_rate"]:.2f}/s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
