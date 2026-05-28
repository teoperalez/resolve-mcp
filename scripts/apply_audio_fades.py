"""
Apply -3dB (constant-power) audio fades to A2 BGM/battle clips at the edges
that surround a battle, plus the very last A2 clip's end.

Resolve's scripting API doesn't expose audio fade properties on TimelineItems
(GetProperty returns an empty dict for audio clips), so we pre-render faded
variants via ffmpeg and replace the originals at the same timeline position.

The half-sine (`hsin`) ffmpeg afade curve matches Resolve's "Cross Fade -3dB"
behavior (constant power).

Edges that get fades:
  - The last general BGM clip BEFORE each battle (fade-out at end)
  - The last loop of each battle's audio (fade-out)
  - The first loop of each battle's audio (fade-in)
  - The first general BGM clip AFTER each battle (fade-in at start)
  - The very last A2 clip on the timeline (fade-out at end)

Cache: ~/.resolve-mcp/cache/audio-fades/<stem>__s<start>_e<end>__fi<N>_fo<N>.mp3

Usage:
    python apply_audio_fades.py [--track-index 2] [--fade-sec 1.0] [--dry-run]
"""
import sys
import os
import json
import argparse
import hashlib
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

CACHE_DIR        = Path.home() / '.resolve-mcp' / 'cache' / 'audio-fades'
TAGS_PATH        = Path.home() / '.resolve-mcp' / 'bgm-tags.json'
BATTLE_AUDIO_TAGS = {'battle_rival', 'battle_gym', 'battle_generic'}


def _clip_source_path(item) -> str:
    mpi = item.GetMediaPoolItem()
    if mpi is None:
        return ''
    try:
        return mpi.GetClipProperty('File Path') or ''
    except Exception:
        return ''


def dominant_a1_source(tl) -> tuple[str, str]:
    counts = {}
    for item in (tl.GetItemListInTrack('audio', 1) or []):
        src = _clip_source_path(item)
        if not src:
            continue
        key = (src, item.GetName() or '')
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return '', ''
    return max(counts.items(), key=lambda kv: kv[1])[0]


def fail_if_track_has_gameplay_audio(tl, track_index: int) -> bool:
    gameplay_src, gameplay_name = dominant_a1_source(tl)
    if not gameplay_src:
        return False
    dupes = [
        item for item in (tl.GetItemListInTrack('audio', track_index) or [])
        if _clip_source_path(item) == gameplay_src
    ]
    if not dupes:
        return False
    print(f'ERROR: A{track_index} contains raw gameplay-source audio before fades.', file=sys.stderr)
    print(f'       source={gameplay_src}', file=sys.stderr)
    print(f'       name={gameplay_name!r}, clips={len(dupes)}', file=sys.stderr)
    print('       Rebuild or clean the music bed before running apply_audio_fades.py.', file=sys.stderr)
    return True


def render_fade_variant(source_path: Path, start_frame: int, end_frame: int,
                        fps: float, fade_in_frames: int, fade_out_frames: int) -> Path | None:
    """Pre-render an audio slice with fade-in and/or fade-out via ffmpeg.
    Cached by (source, range, fades). Returns the rendered path or None on failure."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    stem = source_path.stem.replace(' ', '_')
    key  = f's{start_frame}_e{end_frame}_fi{fade_in_frames}_fo{fade_out_frames}'
    out_path = CACHE_DIR / f'{stem}__{key}.mp3'
    if out_path.exists():
        return out_path

    start_sec = start_frame / fps
    dur_sec   = (end_frame - start_frame) / fps
    fi_sec    = fade_in_frames  / fps
    fo_sec    = fade_out_frames / fps

    filters = []
    if fade_in_frames > 0:
        filters.append(f'afade=t=in:st=0:d={fi_sec}:curve=hsin')
    if fade_out_frames > 0:
        fo_start = max(0.0, dur_sec - fo_sec)
        filters.append(f'afade=t=out:st={fo_start}:d={fo_sec}:curve=hsin')
    afilter = ','.join(filters) if filters else 'anull'

    cmd = [
        'ffmpeg', '-y',
        '-ss', f'{start_sec:.4f}', '-i', str(source_path),
        '-t', f'{dur_sec:.4f}',
        '-af', afilter,
        '-c:a', 'libmp3lame', '-q:a', '2',
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0 or not out_path.exists():
        msg = r.stderr.decode('utf-8', 'ignore').splitlines()[-3:]
        print(f'    ffmpeg failed:\n      ' + '\n      '.join(msg))
        return None
    return out_path


def import_into_assets(pool, assets_bin, path: Path):
    """Import a file into the assets bin and return its MPI (or None on fail).
    Reuses existing MPI if the file is already imported."""
    # Search by filename in assets bin (recursive)
    def search(bin_):
        for item in (bin_.GetClipList() or []):
            if (item.GetName() or '').lower() == path.name.lower():
                return item
        for sub in (bin_.GetSubFolderList() or []):
            hit = search(sub)
            if hit:
                return hit
        return None

    existing = search(assets_bin)
    if existing:
        return existing

    prev = pool.GetCurrentFolder()
    pool.SetCurrentFolder(assets_bin)
    imported = pool.ImportMedia([str(path)]) or []
    if prev is not None:
        pool.SetCurrentFolder(prev)
    return imported[0] if imported else None


def find_subfolder(parent, name):
    for sub in (parent.GetSubFolderList() or []):
        if sub.GetName() == name:
            return sub
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--track-index', type=int, default=2,
                    help='Audio track (default: 2 = A2)')
    ap.add_argument('--fade-sec', type=float, default=1.0,
                    help='Fade duration in seconds (default 1.0)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if not TAGS_PATH.exists():
        print(f'ERROR: {TAGS_PATH} not found.', file=sys.stderr)
        return 1
    tags = json.loads(TAGS_PATH.read_text(encoding='utf-8'))

    import DaVinciResolveScript as dvr
    resolve  = dvr.scriptapp('Resolve')
    project  = resolve.GetProjectManager().GetCurrentProject()
    pool     = project.GetMediaPool()
    tl       = project.GetCurrentTimeline()
    fps      = float(project.GetSetting('timelineFrameRate'))
    tl_start = tl.GetStartFrame()

    root    = pool.GetRootFolder()
    assets  = find_subfolder(root, 'assets')
    if assets is None:
        print('ERROR: assets bin not found.', file=sys.stderr)
        return 1

    fade_frames = max(1, int(round(args.fade_sec * fps)))
    print(f'Timeline: "{tl.GetName()}"  fps={fps}  fade={fade_frames}f ({args.fade_sec}s)')
    if fail_if_track_has_gameplay_audio(tl, args.track_index):
        return 2

    # Collect A2 clips in order, with helper metadata
    a2 = sorted(tl.GetItemListInTrack('audio', args.track_index) or [],
                key=lambda c: c.GetStart())
    if not a2:
        print('A2 is empty.')
        return 0

    items = []
    for c in a2:
        mpi  = c.GetMediaPoolItem()
        name = (mpi.GetName() if mpi else (c.GetName() or '')).strip()
        tag  = (tags.get(name) or {}).get('tag', 'general')
        items.append({
            'item':     c,
            'name':     name,
            'tag':      tag,
            'is_battle': tag in BATTLE_AUDIO_TAGS,
            'start':    c.GetStart(),
            'end':      c.GetStart() + c.GetDuration(),
            'src_path': mpi.GetClipProperty('File Path') if mpi else '',
            'src_off':  c.GetLeftOffset(),
            'dur':      c.GetDuration(),
        })

    # Group consecutive same-name clips into "battle groups"
    fades_needed = []  # list of (item_index_in_items, fade_in_frames, fade_out_frames)
    fade_map: dict[int, tuple[int, int]] = {}  # idx → (fi, fo)

    def add(idx: int, fi: int = 0, fo: int = 0):
        existing = fade_map.get(idx, (0, 0))
        fade_map[idx] = (max(existing[0], fi), max(existing[1], fo))

    # Walk A2 and find runs of consecutive battle clips with same name
    i = 0
    while i < len(items):
        if items[i]['is_battle']:
            # Find run [i, j) of same-named consecutive battle clips
            j = i + 1
            while (j < len(items) and items[j]['is_battle']
                   and items[j]['name'] == items[i]['name']
                   and items[j]['start'] == items[j - 1]['end']):
                j += 1
            # First loop of this battle group → fade-in
            add(i, fi=fade_frames)
            # Last loop of this battle group → fade-out
            add(j - 1, fo=fade_frames)
            # The clip just BEFORE this battle group (if any) → fade-out
            if i > 0:
                add(i - 1, fo=fade_frames)
            # The clip just AFTER this battle group (if any) → fade-in
            if j < len(items):
                add(j, fi=fade_frames)
            i = j
        else:
            i += 1

    # Last A2 clip → fade-out
    add(len(items) - 1, fo=fade_frames)

    # Print the plan
    print(f'\nClips needing fades: {len(fade_map)}')
    for idx in sorted(fade_map):
        fi, fo = fade_map[idx]
        it = items[idx]
        rel = (it['start'] - tl_start) / fps
        print(f"  [{idx:3d}] rel={rel:7.1f}s  dur={it['dur']/fps:6.2f}s  "
              f"tag={it['tag']:14s}  fi={fi}f fo={fo}f  {it['name']!r}")

    if args.dry_run:
        print('\nDRY RUN — no changes made.')
        return 0

    # For each clip needing a fade, render variant + replace
    # Collect replacement specs first so we can delete + append in batches.
    to_delete = []
    new_specs = []

    for idx in sorted(fade_map):
        fi, fo = fade_map[idx]
        it     = items[idx]
        if not it['src_path']:
            print(f"  [{idx}] no source path — skip")
            continue
        src    = Path(it['src_path'])
        if not src.exists():
            print(f"  [{idx}] source missing: {src}")
            continue

        out = render_fade_variant(src, it['src_off'], it['src_off'] + it['dur'],
                                   fps, fi, fo)
        if out is None:
            print(f"  [{idx}] render failed for {it['name']}")
            continue

        # Import (or find) the rendered file in assets
        new_mpi = import_into_assets(pool, assets, out)
        if new_mpi is None:
            print(f"  [{idx}] import failed for {out.name}")
            continue

        # New clip is full length of the rendered file (the fades are baked in)
        new_specs.append({
            'mediaPoolItem': new_mpi,
            'recordFrame':   it['start'],
            'trackIndex':    args.track_index,
            'mediaType':     2,
            '_idx':          idx,
        })
        to_delete.append(it['item'])

    if not to_delete:
        print('Nothing to do.')
        return 0

    print(f'\nReplacing {len(to_delete)} clips with faded variants...')
    ok = tl.DeleteClips(to_delete)
    print(f'  DeleteClips returned: {ok}')

    payload = [{k: v for k, v in s.items() if not k.startswith('_')} for s in new_specs]
    placed  = pool.AppendToTimeline(payload) or []
    print(f'  Placed {len(placed)}/{len(payload)} faded variants.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
