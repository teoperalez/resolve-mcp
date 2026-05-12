"""
Place battle audio (rival / gym themes) on A2 during each battle interval.

Reads:
  - transcripts/battle-types.json      (battle_index → rival/gym/other)
  - ~/.resolve-mcp/bgm-tags.json        (filename → tag including battle_rival / battle_gym)
  - transcripts/battles.json            (source seconds for each battle start)
  - Green markers on the current timeline (battle ends)

For each battle:
  - If type == 'rival' → place the chosen battle_rival track
  - If type == 'gym'   → place the chosen battle_gym track
  - If type == 'other' → leave silent
  - Loop the chosen track if the battle interval is longer than its duration.
    Truncate the last loop at the battle end.

One track per type, used consistently across all battles of that type.
Selection: alphabetical first within the tagged set unless overridden via CLI.

Usage:
    python place_battle_audio.py [--rival-track NAME] [--gym-track NAME]
                                 [--track-index 2] [--dry-run]
"""
import sys
import os
import json
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

TAGS_PATH         = Path.home() / '.resolve-mcp' / 'bgm-tags.json'
BATTLES_JSON      = Path('transcripts/battles.json')
BATTLE_TYPES_JSON = Path('transcripts/battle-types.json')


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


def _mpi_clip_fps(mpi):
    props = mpi.GetClipProperty() or {}
    for key in ('FPS', 'Video Frame Rate', 'Frame Rate'):
        try:
            v = float(props.get(key) or 0)
            if v > 0:
                return v
        except (ValueError, TypeError):
            pass
    return None


def mpi_duration_frames(mpi, timeline_fps):
    props = mpi.GetClipProperty() or {}
    clip_fps = _mpi_clip_fps(mpi) or timeline_fps
    for key in ('Audio Duration', 'Video Duration', 'Duration'):
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
        n = int(props.get('Frames') or 0)
        if n > 0:
            return round(n * timeline_fps / clip_fps) if clip_fps != timeline_fps else n
    except (ValueError, TypeError):
        pass
    return None


def build_v1_source_map(v1_clips, fps):
    entries = []
    for c in v1_clips:
        tl_start = c.GetStart()
        tl_end   = tl_start + c.GetDuration()
        src_start = c.GetLeftOffset() / fps
        src_end   = (c.GetLeftOffset() + c.GetDuration()) / fps
        entries.append((tl_start, tl_end, src_start, src_end, c))
    return entries


def source_sec_to_tl_abs(source_sec, fps, v1_map, snap_tol_sec=0.5):
    for tl_start, _, src_start, src_end, _ in v1_map:
        if src_start <= source_sec <= src_end:
            return tl_start + round((source_sec - src_start) * fps)
    for tl_start, _, src_start, _, _ in v1_map:
        if src_start - snap_tol_sec <= source_sec < src_start:
            return tl_start
    for _, tl_end, _, src_end, _ in v1_map:
        if src_end < source_sec <= src_end + snap_tol_sec:
            return tl_end - 1
    return None


def loop_placements(track_mpi, track_dur, tl_start_abs, tl_end_abs,
                    track_index, trainer_name):
    """Return AppendToTimeline specs that fill [tl_start_abs, tl_end_abs) with
    the track played back-to-back; the final instance is truncated to fit."""
    specs = []
    cur = tl_start_abs
    loop_idx = 0
    while cur < tl_end_abs:
        remaining = tl_end_abs - cur
        place_dur = min(track_dur, remaining)
        if place_dur <= 0:
            break
        specs.append({
            'mediaPoolItem': track_mpi,
            'startFrame':    0,
            'endFrame':      place_dur,
            'recordFrame':   cur,
            'trackIndex':    track_index,
            'mediaType':     2,
            '_name':         f'{trainer_name} (loop {loop_idx})',
        })
        cur      += place_dur
        loop_idx += 1
    return specs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rival-track', default=None,
                    help='Filename of the track to use for rival battles (otherwise the first battle_rival in bgm-tags.json)')
    ap.add_argument('--gym-track', default=None,
                    help='Filename of the track to use for gym battles (otherwise the first battle_gym in bgm-tags.json)')
    ap.add_argument('--track-index', type=int, default=2,
                    help='Audio track to place on (default: 2 = A2)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if not TAGS_PATH.exists():
        print(f'ERROR: {TAGS_PATH} not found. Run classify_bgm.py first.',
              file=sys.stderr)
        return 1
    tags = json.loads(TAGS_PATH.read_text(encoding='utf-8'))

    if not BATTLE_TYPES_JSON.exists():
        print(f'ERROR: {BATTLE_TYPES_JSON} not found. Run classify_battles.py first.',
              file=sys.stderr)
        return 1
    battle_types = json.loads(BATTLE_TYPES_JSON.read_text(encoding='utf-8'))

    if not BATTLES_JSON.exists():
        print(f'ERROR: {BATTLES_JSON} not found.', file=sys.stderr)
        return 1
    battles = json.loads(BATTLES_JSON.read_text(encoding='utf-8'))

    import DaVinciResolveScript as dvr
    resolve  = dvr.scriptapp('Resolve')
    project  = resolve.GetProjectManager().GetCurrentProject()
    pool     = project.GetMediaPool()
    tl       = project.GetCurrentTimeline()
    fps      = float(project.GetSetting('timelineFrameRate'))
    tl_start = tl.GetStartFrame()

    print(f'Timeline: "{tl.GetName()}"  fps={fps}')

    root    = pool.GetRootFolder()
    assets  = find_subfolder(root, 'assets')
    bgm_bin = find_subfolder(assets, 'bgm') if assets else None
    if bgm_bin is None:
        print('ERROR: bgm bin not found.', file=sys.stderr)
        return 1
    bgm_clips = collect_clips_recursive(bgm_bin)
    name_to_mpi = {(c.GetName() or '').strip(): c for c in bgm_clips}

    # Select rival / gym tracks
    def pick_first(tag_value):
        candidates = sorted(fn for fn, v in tags.items() if v.get('tag') == tag_value)
        return candidates[0] if candidates else None

    rival_name = args.rival_track or pick_first('battle_rival')
    gym_name   = args.gym_track   or pick_first('battle_gym')
    print(f'Rival track: {rival_name!r}')
    print(f'Gym track:   {gym_name!r}')

    if not rival_name and not gym_name:
        print('Nothing to place (no battle_rival or battle_gym tracks tagged).')
        return 0

    rival_mpi = name_to_mpi.get(rival_name) if rival_name else None
    gym_mpi   = name_to_mpi.get(gym_name)   if gym_name   else None
    rival_dur = mpi_duration_frames(rival_mpi, fps) if rival_mpi else None
    gym_dur   = mpi_duration_frames(gym_mpi,   fps) if gym_mpi   else None

    if rival_name and not rival_mpi:
        print(f'WARN: rival track {rival_name!r} not found in bgm bin.')
    if gym_name and not gym_mpi:
        print(f'WARN: gym track {gym_name!r} not found in bgm bin.')

    # Build V1 source-sec map for battle starts
    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    if len(v1) < 3:
        print('ERROR: V1 needs intro + gameplay + outro.', file=sys.stderr)
        return 1
    v1_map = build_v1_source_map(v1[1:-1], fps)

    markers = tl.GetMarkers() or {}
    greens  = sorted(((f, m.get('name', '')) for f, m in markers.items()
                      if m.get('color') == 'Green'))

    # Build battle pairs with types
    used = set()
    specs = []
    for i, b in enumerate(battles):
        btype_info = battle_types.get(str(i)) or battle_types.get(i)
        btype      = (btype_info or {}).get('type', 'other')
        if btype not in ('rival', 'gym'):
            print(f"  battle {i} ({b['trainer_name']}): type={btype} → skip")
            continue

        start_abs = source_sec_to_tl_abs(b['timestamp_sec'], fps, v1_map)
        if start_abs is None:
            print(f"  battle {i} ({b['trainer_name']}): could not map start")
            continue

        # Find matching green marker by trainer name
        end_abs = None
        for f, name in greens:
            if f in used:
                continue
            if b['trainer_name'].lower() in (name or '').lower():
                end_abs = tl_start + f
                used.add(f)
                break
        if end_abs is None:
            print(f"  battle {i} ({b['trainer_name']}): no green end marker")
            continue

        # Pick track for this type
        track_mpi = rival_mpi if btype == 'rival' else gym_mpi
        track_dur = rival_dur if btype == 'rival' else gym_dur
        if not track_mpi or not track_dur:
            print(f"  battle {i} ({b['trainer_name']}): no track for type={btype}")
            continue

        battle_specs = loop_placements(track_mpi, track_dur,
                                       start_abs, end_abs,
                                       args.track_index, b['trainer_name'])
        loops_needed = len(battle_specs)
        dur_sec = (end_abs - start_abs) / fps
        track_sec = track_dur / fps
        print(f"  battle {i} ({b['trainer_name']:14s}): "
              f"type={btype} dur={dur_sec:5.1f}s track={track_sec:5.1f}s "
              f"loops={loops_needed}")
        specs.extend(battle_specs)

    print(f'\nPlanned placements: {len(specs)}')
    for sp in specs:
        rel_s = (sp['recordFrame'] - tl_start) / fps
        dur_s = sp['endFrame'] / fps
        print(f"  A{sp['trackIndex']}  rel={rel_s:7.1f}s  dur={dur_s:6.2f}s  {sp['_name']}")

    if args.dry_run:
        print('\nDRY RUN — no changes made.')
        return 0

    # Ensure track exists
    while tl.GetTrackCount('audio') < args.track_index:
        tl.AddTrack('audio', 'stereo')

    payload = [{k: v for k, v in s.items() if not k.startswith('_')} for s in specs]
    placed  = pool.AppendToTimeline(payload) or []
    print(f'\nPlaced: {len(placed)}/{len(payload)} battle-audio clips on A{args.track_index}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
