"""
Layout the Member Carousel section of the current timeline as:

  V1: ... gameplay ... [ONE extended clip from Member Carousel Start → outro start] [outro]
  V2: (copies of the original V1 carousel clips, each with CropBottom=530)
   A1+: untouched

Workflow:
  1. Find marker named "Member Carousel Start" on the current timeline.
  2. Identify V1 clips from that marker to just before the outro (the last
     V1 clip is assumed to be the outro).
  3. Copy those clips to V2 (preserving their timeline positions).
  4. Set CropBottom=530 on every new V2 clip.
  5. Delete the original V1 clips in that range.
  6. Append ONE extended clip on V1 covering [carousel_start → outro_start)
     using the first carousel clip's MediaPoolItem with extended source range.

Usage:
    python layout_carousel.py [--dry-run] [--marker-name "..."]
                              [--crop-bottom 530] [--end-at-timeline-end]
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

DEFAULT_MARKER_NAME = 'Member Carousel Start'
DEFAULT_CROP_BOTTOM = 530.0


def _clip_source_path(item) -> str:
    mpi = item.GetMediaPoolItem()
    if mpi is None:
        return ''
    try:
        return (mpi.GetClipProperty('File Path') or '').lower()
    except Exception:
        return ''


def _is_outro_item(item) -> bool:
    name = (item.GetName() or '').lower()
    path = _clip_source_path(item)
    return 'outro' in name or 'outro' in path


def plan_outro_audio_moves_after_frame(tl, target_start: int,
                                       track_index: int = 3) -> list[dict]:
    """Return non-ripple A3 outro-audio moves needed after carousel layout."""
    plans = []
    cursor = int(target_start)
    items = sorted(
        [
            item for item in (tl.GetItemListInTrack('audio', track_index) or [])
            if _is_outro_item(item)
        ],
        key=lambda item: item.GetStart(),
    )
    for item in items:
        start = int(item.GetStart())
        duration = int(item.GetDuration())
        end = int(item.GetEnd())
        if start < cursor:
            plans.append({
                'item': item,
                'track_index': track_index,
                'old_start': start,
                'old_end': end,
                'new_start': cursor,
                'new_end': cursor + duration,
                'duration': duration,
                'source_start': int(item.GetLeftOffset()),
                'source_end': int(item.GetLeftOffset()) + duration,
                'color': item.GetClipColor() or '',
                'name': item.GetName() or '',
                'source_path': _clip_source_path(item),
                'media_pool_item': item.GetMediaPoolItem(),
            })
            cursor += duration
        else:
            cursor = max(cursor, end)
    return plans


def apply_outro_audio_moves(tl, pool, plans: list[dict]) -> int:
    moved = 0
    for plan in plans:
        mpi = plan.get('media_pool_item')
        item = plan.get('item')
        if mpi is None or item is None:
            print(f"  WARN: cannot move outro audio {plan.get('name')!r}: missing media pool item")
            continue
        ok = tl.DeleteClips([item], False)
        if not ok:
            print(f"  WARN: DeleteClips failed for outro audio {plan.get('name')!r}")
            continue
        placed = pool.AppendToTimeline([{
            'mediaPoolItem': mpi,
            'startFrame':    plan['source_start'],
            'endFrame':      plan['source_end'],
            'recordFrame':   plan['new_start'],
            'trackIndex':    plan['track_index'],
            'mediaType':     2,
        }]) or []
        if not placed:
            print(f"  WARN: failed to place outro audio {plan.get('name')!r} at {plan['new_start']}")
            continue
        if plan.get('color'):
            placed[0].SetClipColor(plan['color'])
        moved += 1
        print(
            f"  Moved outro audio {plan.get('name')!r}: "
            f"{plan['old_start']}..{plan['old_end']} -> "
            f"{plan['new_start']}..{plan['new_end']}"
        )
    return moved


def cleanup_duplicate_gameplay_audio(tl, gameplay_name: str,
                                     gameplay_source_path: str) -> int:
    """Remove Resolve-created duplicate gameplay audio from A2+.

    Resolve can materialize embedded multi-channel audio on A2-A5 when an MP4
    MediaPoolItem is appended as a video clip, even with mediaType=1. The
    carousel layout wants only the extended V1 picture bed; A1 remains the
    dialogue/gameplay audio authority.
    """
    gameplay_source_path = (gameplay_source_path or '').lower()
    if not gameplay_name and not gameplay_source_path:
        return 0

    to_delete = []
    for track in range(2, int(tl.GetTrackCount('audio')) + 1):
        for item in (tl.GetItemListInTrack('audio', track) or []):
            same_name = gameplay_name and (item.GetName() or '') == gameplay_name
            same_path = (
                gameplay_source_path
                and _clip_source_path(item) == gameplay_source_path
            )
            if same_name or same_path:
                to_delete.append(item)

    if not to_delete:
        return 0
    ok = tl.DeleteClips(to_delete)
    if not ok:
        print(f'WARNING: failed to delete {len(to_delete)} duplicate gameplay audio clips from A2+.')
        return 0
    return len(to_delete)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help='Report planned operations without modifying Resolve.')
    ap.add_argument('--marker-name', default=DEFAULT_MARKER_NAME,
                    help='Name of the marker that signals the carousel start. '
                         'Comma-separated aliases are accepted.')
    ap.add_argument('--crop-bottom', type=float, default=DEFAULT_CROP_BOTTOM,
                    help='CropBottom value (pixels) applied to each V2 clip')
    ap.add_argument('--end-at-timeline-end', '--no-outro', dest='end_at_timeline_end',
                    action='store_true',
                    help='Use the timeline end as the carousel end instead of treating the last V1 clip as an outro.')
    args = ap.parse_args()

    import DaVinciResolveScript as dvr
    resolve  = dvr.scriptapp('Resolve')
    project  = resolve.GetProjectManager().GetCurrentProject()
    pool     = project.GetMediaPool()
    tl       = project.GetCurrentTimeline()
    fps      = float(project.GetSetting('timelineFrameRate'))
    tl_start = tl.GetStartFrame()

    print(f'Timeline: "{tl.GetName()}"  fps={fps}  start={tl_start}')

    # ── Find the Member Carousel Start marker ───────────────────────────────
    markers = tl.GetMarkers() or {}
    carousel_marker_rel = None
    wanted_marker_names = {
        part.strip().lower()
        for part in args.marker_name.split(',')
        if part.strip()
    }
    for f, m in markers.items():
        if (m.get('name') or '').strip().lower() in wanted_marker_names:
            carousel_marker_rel = f
            break
    if carousel_marker_rel is None:
        print(f'ERROR: No marker named "{args.marker_name}" on this timeline.',
              file=sys.stderr)
        return 1

    carousel_start_abs = tl_start + carousel_marker_rel
    print(f'Carousel marker:  rel={carousel_marker_rel}  abs={carousel_start_abs}'
          f'  ({carousel_marker_rel/fps:.2f}s into TL)')

    # ── Get V1 clips and identify the carousel range + outro ────────────────
    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    if len(v1) < 1:
        print('ERROR: need at least 1 V1 clip.', file=sys.stderr)
        return 1

    if args.end_at_timeline_end:
        outro_clip = None
        outro_tl_start = tl.GetEndFrame()
        v1_range = v1
        print(f'Carousel end: timeline end {outro_tl_start} '
              f'({(outro_tl_start-tl_start)/fps:.2f}s into TL)')
    else:
        if len(v1) < 2:
            print('ERROR: need at least 2 V1 clips (carousel + outro), or use --end-at-timeline-end.', file=sys.stderr)
            return 1
        outro_clip = v1[-1]
        outro_tl_start = outro_clip.GetStart()
        v1_range = v1[:-1]
        print(f'Outro clip (last V1): name={outro_clip.GetName()!r}  '
              f'tl_start={outro_tl_start}  ({(outro_tl_start-tl_start)/fps:.2f}s into TL)')

    # Carousel clips = V1 clips from marker (inclusive) up to outro (exclusive)
    carousel_clips = [c for c in v1_range if c.GetStart() >= carousel_start_abs]
    if not carousel_clips:
        print('ERROR: no V1 clips between the marker and the outro.', file=sys.stderr)
        return 1

    first_carousel       = carousel_clips[0]
    first_carousel_mpi   = first_carousel.GetMediaPoolItem()
    gameplay_name        = first_carousel.GetName() or ''
    gameplay_source_path = _clip_source_path(first_carousel)
    first_carousel_src   = first_carousel.GetLeftOffset()
    first_carousel_tl    = first_carousel.GetStart()

    extend_tl_duration = outro_tl_start - first_carousel_tl
    extend_src_end     = first_carousel_src + extend_tl_duration

    print(f'\nCarousel clips to redistribute: {len(carousel_clips)}  '
          f'(V1[{v1.index(carousel_clips[0])}..{v1.index(carousel_clips[-1])}])')
    print(f'First carousel clip: name={first_carousel.GetName()!r}  '
          f'tl_start={first_carousel_tl}  src=[{first_carousel_src}, '
          f'{first_carousel_src + first_carousel.GetDuration()})')
    print(f'Planned V1 extended clip:  tl=[{first_carousel_tl}, {outro_tl_start})  '
          f'duration={extend_tl_duration} ({extend_tl_duration/fps:.2f}s)  '
          f'src=[{first_carousel_src}, {extend_src_end})')

    # Safety: ensure source has enough room for the extended range
    src_total = first_carousel_mpi.GetClipProperty('Frames') or 0
    try:
        src_total = int(src_total)
    except Exception:
        src_total = 0
    if src_total and extend_src_end > src_total:
        print(f'WARNING: extended source end {extend_src_end} exceeds source '
              f'frame count {src_total}. Will clamp.')
        extend_src_end = src_total

    # ── Build the V2 spec list (copies of carousel clips) ────────────────────
    v2_specs = []
    for c in carousel_clips:
        v2_specs.append({
            'mediaPoolItem': c.GetMediaPoolItem(),
            'startFrame':    c.GetLeftOffset(),
            'endFrame':      c.GetLeftOffset() + c.GetDuration(),
            'recordFrame':   c.GetStart(),
            'trackIndex':    2,
            'mediaType':     1,
        })

    v2_carousel_end = max(
        spec['recordFrame'] + (spec['endFrame'] - spec['startFrame'])
        for spec in v2_specs
    )
    print(f'Last V2 carousel clip will end at {v2_carousel_end}.')

    outro_audio_plans = []
    if args.end_at_timeline_end:
        outro_audio_plans = plan_outro_audio_moves_after_frame(
            tl,
            v2_carousel_end,
            track_index=3,
        )
        if outro_audio_plans:
            planned_end = max(plan['new_end'] for plan in outro_audio_plans)
            if planned_end > outro_tl_start:
                outro_tl_start = planned_end
                extend_tl_duration = outro_tl_start - first_carousel_tl
                extend_src_end = first_carousel_src + extend_tl_duration
                if src_total and extend_src_end > src_total:
                    print(f'WARNING: adjusted source end {extend_src_end} exceeds source '
                          f'frame count {src_total}. Will clamp.')
                    extend_src_end = src_total
                print(f'Adjusted V1 extended clip for moved outro audio: '
                      f'tl=[{first_carousel_tl}, {outro_tl_start}) '
                      f'src=[{first_carousel_src}, {extend_src_end})')

    if args.dry_run:
        print(f'\nDRY RUN — would:\n'
              f'  - Copy {len(v2_specs)} clips to V2\n'
              f'  - Apply CropBottom={args.crop_bottom} to each V2 clip\n'
              f'  - Delete {len(carousel_clips)} V1 clips\n'
              f'  - Append 1 extended V1 clip')
        for plan in outro_audio_plans:
            print(f"  - Move A{plan['track_index']} outro audio {plan['name']!r} "
                  f"from {plan['old_start']} to {plan['new_start']}")
        return 0

    # ── Ensure V2 exists ────────────────────────────────────────────────────
    while tl.GetTrackCount('video') < 2:
        tl.AddTrack('video')

    # ── 1) Copy carousel clips to V2 ────────────────────────────────────────
    print(f'\nStep 1: copying {len(v2_specs)} clips to V2...')
    v2_placed = pool.AppendToTimeline(v2_specs) or []
    print(f'  Placed {len(v2_placed)}/{len(v2_specs)} on V2.')

    if len(v2_placed) != len(v2_specs):
        print('  WARNING: not all V2 placements landed; continuing anyway.')

    # ── 2) Apply CropBottom to each newly placed V2 clip ────────────────────
    print(f'Step 2: applying CropBottom={args.crop_bottom} to V2 clips...')
    n_cropped = 0
    for item in v2_placed:
        try:
            ok = item.SetProperty('CropBottom', args.crop_bottom)
        except Exception as e:
            ok = f'EXC {e}'
        if ok is True:
            n_cropped += 1
        else:
            print(f'  WARN: SetProperty failed on {item.GetName()!r}: returned {ok!r}')
    print(f'  Applied CropBottom to {n_cropped}/{len(v2_placed)} V2 clips.')

    # ── 3) Delete original carousel clips from V1 ───────────────────────────
    print(f'Step 3: deleting {len(carousel_clips)} V1 carousel clips...')
    try:
        ok = tl.DeleteClips(carousel_clips)
    except Exception as e:
        print(f'  ERROR: DeleteClips raised {e}', file=sys.stderr)
        return 1
    print(f'  DeleteClips returned: {ok}')

    # ── 4) Append one extended V1 clip ───────────────────────────────────────
    print(f'Step 4: appending extended V1 clip '
          f'(src=[{first_carousel_src}, {extend_src_end}))...')
    extended_spec = {
        'mediaPoolItem': first_carousel_mpi,
        'startFrame':    first_carousel_src,
        'endFrame':      extend_src_end,
        'recordFrame':   first_carousel_tl,
        'trackIndex':    1,
        'mediaType':     1,
    }
    v1_placed = pool.AppendToTimeline([extended_spec]) or []
    print(f'  Appended: {len(v1_placed)}/1')
    if v1_placed:
        new_clip = v1_placed[0]
        print(f'  New V1 clip: tl_start={new_clip.GetStart()}  '
              f'duration={new_clip.GetDuration()} '
              f'({new_clip.GetDuration()/fps:.2f}s)')

    removed = cleanup_duplicate_gameplay_audio(
        tl,
        gameplay_name=gameplay_name,
        gameplay_source_path=gameplay_source_path,
    )
    if removed:
        print(f'  Removed duplicate gameplay audio from A2+: {removed} clips')

    if outro_audio_plans:
        print('Step 5: moving outro audio after the last V2 carousel clip...')
        moved = apply_outro_audio_moves(tl, pool, outro_audio_plans)
        print(f'  Moved outro audio clips: {moved}/{len(outro_audio_plans)}')

    print('\nDone.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
