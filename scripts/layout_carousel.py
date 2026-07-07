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

    if args.dry_run:
        print(f'\nDRY RUN — would:\n'
              f'  - Copy {len(v2_specs)} clips to V2\n'
              f'  - Apply CropBottom={args.crop_bottom} to each V2 clip\n'
              f'  - Delete {len(carousel_clips)} V1 clips\n'
              f'  - Append 1 extended V1 clip')
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

    print('\nDone.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
