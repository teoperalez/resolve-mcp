"""
Place a BGM track on A2 of the current timeline, aligning its end-of-intro
point regardless of intro retime.

Rule: BGM source startFrame = native_intro_frames - placed_intro_frames.
  - Full-length intro (e.g. Minimum Battles, 100% speed) → offset 0; BGM
    starts from its beginning.
  - 4x-speed retimed intro → offset = the frame reduction (e.g. 1024 - 260
    = 764); BGM is trimmed at its start so the music plays through to the
    same point at the intro's end as if it had played a full-length intro.

The track is placed at timeline frame 0 on A2 and runs to the end of its
source. Future enhancements can chain additional tracks or swap in battle
audio.

Usage:
    python place_bgm.py --game GAME_KEY [--track "Dual Screen Lovelife"]
                        [--track-index 2] [--dry-run]
"""
import sys
import os
import json
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

CATALOG_PATH  = Path('assets/catalog.json')
MANIFEST_PATH = Path.home() / '.resolve-mcp' / 'manifest.json'
DEFAULT_TRACK = 'Dual Screen Lovelife'


def find_subfolder(parent, name):
    for sub in (parent.GetSubFolderList() or []):
        if sub.GetName() == name:
            return sub
    return None


def find_clip_in_bin(bin_, needle: str):
    """Find a MediaPoolItem whose name contains `needle` (case-insensitive)."""
    needle_lo = needle.lower()
    # Exact match first
    for item in (bin_.GetClipList() or []):
        if (item.GetName() or '').lower() == needle_lo:
            return item
    # Substring fallback
    for item in (bin_.GetClipList() or []):
        if needle_lo in (item.GetName() or '').lower():
            return item
    return None


def find_clip_recursive(bin_, needle: str):
    """Walk bin and all its subfolders for a clip whose name contains needle."""
    hit = find_clip_in_bin(bin_, needle)
    if hit:
        return hit
    for sub in (bin_.GetSubFolderList() or []):
        hit = find_clip_recursive(sub, needle)
        if hit:
            return hit
    return None


def _mpi_clip_fps(mpi) -> float | None:
    props = mpi.GetClipProperty() or {}
    for key in ('FPS', 'Video Frame Rate', 'Frame Rate'):
        try:
            v = float(props.get(key) or 0)
            if v > 0:
                return v
        except (ValueError, TypeError):
            pass
    return None


def mpi_duration_frames(mpi, timeline_fps: float) -> int | None:
    """Duration in TIMELINE frames, accounting for fps differences."""
    props = mpi.GetClipProperty() or {}
    clip_fps = _mpi_clip_fps(mpi) or timeline_fps

    for key in ('Video Duration', 'Audio Duration', 'Duration'):
        raw = (props.get(key) or '').strip()
        if not raw:
            continue
        parts = raw.replace(';', ':').split(':')
        if len(parts) == 4:
            h, m, s, f = (int(x) for x in parts)
            total_sec = h * 3600 + m * 60 + s + f / clip_fps
            frames = round(total_sec * timeline_fps)
            if frames > 0:
                return frames
        try:
            n = int(raw)
            if n > 0:
                return round(n * timeline_fps / clip_fps) if clip_fps != timeline_fps else n
        except ValueError:
            pass

    # Try the simple Frames property
    try:
        n = int(props.get('Frames') or 0)
        if n > 0:
            return round(n * timeline_fps / clip_fps) if clip_fps != timeline_fps else n
    except (ValueError, TypeError):
        pass

    return None


def _find_intro_key(game_def):
    for k in game_def.get('assets', {}):
        if 'intro' in k and 'background' not in k:
            return k
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', required=True,
                    help='Game catalog key (used to look up the native intro file)')
    ap.add_argument('--track', default=DEFAULT_TRACK,
                    help=f'BGM track name in the bgm bin (default: "{DEFAULT_TRACK}")')
    ap.add_argument('--track-index', type=int, default=2,
                    help='Audio track index to place on (default: 2 = A2)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    project = resolve.GetProjectManager().GetCurrentProject()
    pool    = project.GetMediaPool()
    tl      = project.GetCurrentTimeline()
    fps     = float(project.GetSetting('timelineFrameRate'))
    tl_start = tl.GetStartFrame()

    print(f'Timeline: "{tl.GetName()}"  fps={fps}  start={tl_start}')

    # ── Find BGM track MPI ──────────────────────────────────────────────────
    root        = pool.GetRootFolder()
    assets_bin  = find_subfolder(root, 'assets')
    if assets_bin is None:
        print('ERROR: "assets" bin not found.', file=sys.stderr)
        return 1
    bgm_bin     = find_subfolder(assets_bin, 'bgm')
    if bgm_bin is None:
        print('ERROR: "bgm" sub-bin not found under "assets".', file=sys.stderr)
        return 1
    bgm_mpi     = find_clip_recursive(bgm_bin, args.track)
    if bgm_mpi is None:
        print(f'ERROR: BGM track "{args.track}" not found in bgm bin.',
              file=sys.stderr)
        return 1
    print(f'BGM track:   {bgm_mpi.GetName()!r}')

    # ── Find ORIGINAL intro MPI to get native frame count ───────────────────
    catalog  = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    if args.game not in catalog:
        print(f'ERROR: "{args.game}" not in {CATALOG_PATH}', file=sys.stderr)
        return 1
    game_def  = catalog[args.game]
    group_key = game_def.get('asset_group', args.game)
    intro_key = _find_intro_key(game_def)
    if not intro_key:
        print(f'ERROR: no intro asset key for game {args.game}', file=sys.stderr)
        return 1
    intro_path_str = (manifest.get(group_key) or {}).get(intro_key)
    if not intro_path_str:
        print(f'ERROR: intro path not in manifest for {group_key}/{intro_key}',
              file=sys.stderr)
        return 1
    intro_filename = Path(intro_path_str).name
    intro_mpi = find_clip_in_bin(assets_bin, intro_filename)
    if intro_mpi is None:
        intro_mpi = find_clip_recursive(assets_bin, intro_filename)
    if intro_mpi is None:
        print(f'ERROR: original intro {intro_filename!r} not in assets bin.',
              file=sys.stderr)
        return 1

    # ── Compute offset ──────────────────────────────────────────────────────
    native_frames = mpi_duration_frames(intro_mpi, fps)
    if not native_frames:
        print(f'ERROR: could not determine native intro duration from MPI.',
              file=sys.stderr)
        return 1

    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    if not v1:
        print('ERROR: no V1 clips on this timeline.', file=sys.stderr)
        return 1
    placed_frames = v1[0].GetDuration()

    offset = max(0, native_frames - placed_frames)
    print(f'Native intro frames: {native_frames}  ({native_frames/fps:.2f}s)')
    print(f'Placed intro frames: {placed_frames}  ({placed_frames/fps:.2f}s)')
    print(f'BGM source offset:   {offset}  ({offset/fps:.2f}s)')

    # ── BGM source range ────────────────────────────────────────────────────
    bgm_total = mpi_duration_frames(bgm_mpi, fps)
    if not bgm_total:
        print('ERROR: could not determine BGM track duration.', file=sys.stderr)
        return 1
    if offset >= bgm_total:
        print(f'ERROR: offset {offset} ≥ BGM total {bgm_total} — nothing to place.',
              file=sys.stderr)
        return 1

    spec = {
        'mediaPoolItem': bgm_mpi,
        'startFrame':    offset,
        'endFrame':      bgm_total,
        'recordFrame':   tl_start,
        'trackIndex':    args.track_index,
        'mediaType':     2,
    }
    print(f'\nPlanned placement: A{args.track_index}  '
          f'src=[{offset}, {bgm_total})  recordFrame={tl_start}  '
          f'(duration={bgm_total - offset} frames = {(bgm_total - offset)/fps:.2f}s)')

    if args.dry_run:
        print('DRY RUN — exiting without changes.')
        return 0

    # Ensure A2 exists
    while tl.GetTrackCount('audio') < args.track_index:
        tl.AddTrack('audio', 'stereo')

    placed = pool.AppendToTimeline([spec]) or []
    print(f'\nPlaced: {len(placed)}/1 BGM clip on A{args.track_index}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
