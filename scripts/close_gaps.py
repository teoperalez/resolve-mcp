"""
Find and close small gaps (≤ MAX_CLOSE_GAP frames) between clips on V1 and A1.

Strategy:
  1. Collect all clips on each track with source ranges and clip colors.
  2. Compute corrected record-frame positions — small gaps closed, larger gaps preserved.
  3. Delete all clips on the track (no-ripple), then re-insert with corrected positions.
  4. Restore per-clip colors by matching source frame range.

Gaps larger than MAX_CLOSE_GAP (battle gaps, etc.) are left intact.

Usage:
    python close_gaps.py [--dry-run] [--max-gap N]
"""
import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

MAX_CLOSE_GAP = 1  # close gaps of this many frames or fewer


def _clip_fps(mpi, timeline_fps: float) -> float:
    props = mpi.GetClipProperty() or {}
    for key in ('FPS', 'Video Frame Rate', 'Frame Rate'):
        try:
            v = float(props.get(key) or 0)
            if v > 0:
                return v
        except (ValueError, TypeError):
            pass
    return timeline_fps


def collect(tl, track_type, track_idx, timeline_fps: float):
    clips = sorted(tl.GetItemListInTrack(track_type, track_idx) or [],
                   key=lambda c: c.GetStart())
    result = []
    for c in clips:
        mpi = c.GetMediaPoolItem()
        if mpi is None:
            continue
        left      = c.GetLeftOffset()
        dur_tl    = c.GetDuration()
        clip_fps  = _clip_fps(mpi, timeline_fps)
        # src_end in native clip frames (AppendToTimeline startFrame/endFrame use native fps)
        dur_native = round(dur_tl * clip_fps / timeline_fps)
        result.append({
            'item':      c,
            'mpi':       mpi,
            'record':    c.GetStart(),
            'src_start': left,
            'src_end':   left + dur_native,  # exclusive, native clip frames
            'duration':  dur_tl,             # timeline frames, for position arithmetic
            'color':     c.GetClipColor() or '',
        })
    return result


def corrected_positions(clips, max_gap):
    """Return list of (clip_dict, new_record_frame).

    Uses the ORIGINAL gap between each consecutive pair of clips to decide
    whether to close it — not the gap as seen after previous corrections.
    This correctly handles cumulative shifts (all subsequent clips shift by
    the accumulated number of closed gaps).
    """
    if not clips:
        return []
    result = [(clips[0], clips[0]['record'])]
    cur = clips[0]['record'] + clips[0]['duration']
    for i in range(1, len(clips)):
        c    = clips[i]
        prev = clips[i - 1]
        orig_gap = c['record'] - (prev['record'] + prev['duration'])
        if orig_gap <= max_gap:
            new_rec = cur              # close gap: butt up against previous
        else:
            new_rec = cur + orig_gap  # preserve gap size, adjusted for prior shifts
        result.append((c, new_rec))
        cur = new_rec + c['duration']
    return result


def fix_track(tl, pool, track_type, track_idx, media_type, max_gap, dry_run, timeline_fps: float):
    clips = collect(tl, track_type, track_idx, timeline_fps)
    if not clips:
        print(f'{track_type.upper()}{track_idx}: no clips')
        return 0, 0

    planned = corrected_positions(clips, max_gap)
    moves = [(c, nr) for c, nr in planned if nr != c['record']]

    # Gap distribution report
    gaps = [clips[i+1]['record'] - (clips[i]['record'] + clips[i]['duration'])
            for i in range(len(clips) - 1)]
    small = sum(1 for g in gaps if 0 < g <= max_gap)
    large = sum(1 for g in gaps if g > max_gap)
    print(f'{track_type.upper()}{track_idx}: {len(clips)} clips  |  '
          f'{small} gap(s) ≤{max_gap}f to close  |  {large} larger gap(s) preserved')

    if not moves:
        print(f'  Nothing to do.')
        return 0, 0

    if dry_run:
        show = moves[:8]
        for c, nr in show:
            shift = nr - c['record']
            print(f'  clip @{c["record"]}  shift {shift:+d}  '
                  f'src=[{c["src_start"]},{c["src_end"]}]  {c["mpi"].GetName()[:40]}')
        if len(moves) > 8:
            print(f'  … and {len(moves) - 8} more clips shifted')
        return small, 0

    # Color map keyed by corrected record position (timeline frames — unambiguous)
    color_map = {new_rec: c['color'] for c, new_rec in planned if c['color']}

    # Delete all clips (no-ripple: leaves gaps, doesn't shift timeline)
    all_items = [c['item'] for c in clips]
    print(f'  Deleting {len(all_items)} clips (no-ripple)...')
    ok = tl.DeleteClips(all_items, False)
    if not ok:
        print(f'  ERROR: DeleteClips failed', file=sys.stderr)
        return small, 0

    # Re-insert with corrected positions
    clip_infos = []
    for c, new_rec in planned:
        clip_infos.append({
            'mediaPoolItem': c['mpi'],
            'startFrame':   c['src_start'],
            'endFrame':     c['src_end'],
            'recordFrame':  new_rec,
            'trackIndex':   track_idx,
            'mediaType':    media_type,
        })

    placed = pool.AppendToTimeline(clip_infos) or []
    print(f'  Re-placed {len(placed)}/{len(clip_infos)} clips.')

    # Restore clip colors
    if color_map:
        new_clips = sorted(tl.GetItemListInTrack(track_type, track_idx) or [],
                           key=lambda c: c.GetStart())
        restored = 0
        for nc in new_clips:
            col = color_map.get(nc.GetStart())
            if col:
                nc.SetClipColor(col)
                restored += 1
        print(f'  Restored {restored} clip color(s).')

    return small, len(placed)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help='Report gaps without modifying the timeline')
    ap.add_argument('--max-gap', type=int, default=MAX_CLOSE_GAP,
                    help=f'Close gaps ≤ this many frames (default: {MAX_CLOSE_GAP})')
    ap.add_argument('--timeline', metavar='NAME',
                    help='Name of timeline to operate on (default: current timeline)')
    args = ap.parse_args()

    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to DaVinci Resolve.', file=sys.stderr)
        return 1

    project = resolve.GetProjectManager().GetCurrentProject()
    pool    = project.GetMediaPool()

    if args.timeline:
        tl = None
        for i in range(1, project.GetTimelineCount() + 1):
            t = project.GetTimelineByIndex(i)
            if t and t.GetName() == args.timeline:
                tl = t
                break
        if tl is None:
            print(f'ERROR: Timeline "{args.timeline}" not found.', file=sys.stderr)
            return 1
        project.SetCurrentTimeline(tl)
    else:
        tl = project.GetCurrentTimeline()

    fps = float(project.GetSetting('timelineFrameRate'))
    print(f'Timeline: {tl.GetName()}  ({fps:.0f}fps)')
    if args.dry_run:
        print('DRY RUN — no changes will be made\n')

    total_gaps = total_placed = 0
    for track_type, track_idx, media_type in [('video', 1, 1), ('audio', 1, 2)]:
        g, p = fix_track(tl, pool, track_type, track_idx, media_type,
                         args.max_gap, args.dry_run, fps)
        total_gaps   += g
        total_placed += p

    if args.dry_run:
        print(f'\nWould close {total_gaps} gap(s).')
    else:
        print(f'\nClosed {total_gaps} gap(s), re-placed {total_placed} clips total.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
