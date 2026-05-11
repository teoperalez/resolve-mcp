"""
Insert a 1-second (60-frame @ 60fps) gap of source footage at each trainer battle
start position on the current Resolve timeline.

For each battle timestamp:
  1. Maps the audio timestamp → timeline frame via A1 clip positions
  2. Finds the V1 clip at that position
  3. If the clip has >= GAP_FRAMES of tail trim, extends its out-point to backfill
     the source footage, ripple-pushing all subsequent clips right
  4. Adds an orange "Battle" marker at the position on the timeline ruler

Usage:
    python insert_battle_gaps.py transcripts/battles.json [--gap-frames 60] [--dry-run]

IMPORTANT — frame convention:
    TimelineItem.AddMarker(frameId) uses ABSOLUTE SOURCE FRAME:
    src_frame = clip.GetLeftOffset() + (timeline_pos - clip.GetStart())
    NOT a timeline-relative offset.
"""
import sys
import os
import argparse
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

import DaVinciResolveScript as dvr


def build_a1_map(tl):
    """
    Build a lookup list of A1 clips sorted by timeline start.
    Each entry: (timeline_start, timeline_end, source_start_sec, source_end_sec)
    source_start_sec = clip.GetLeftOffset() / fps
    """
    fps   = float(tl.GetSetting('timelineFrameRate'))
    clips = sorted(tl.GetItemListInTrack('audio', 1) or [], key=lambda c: c.GetStart())
    entries = []
    for c in clips:
        tl_start  = c.GetStart()
        tl_end    = tl_start + c.GetDuration()
        src_start = c.GetLeftOffset() / fps          # seconds into source file
        src_end   = (c.GetLeftOffset() + c.GetDuration()) / fps
        entries.append((tl_start, tl_end, src_start, src_end, c))
    return entries, fps


def timestamp_to_timeline_frame(timestamp_sec: float, a1_map: list, fps: float) -> int | None:
    """
    Convert an audio file timestamp (seconds) to a timeline frame by finding
    the A1 clip whose source range contains that timestamp.
    """
    for tl_start, tl_end, src_start, src_end, clip in a1_map:
        if src_start <= timestamp_sec <= src_end:
            offset_frames = round((timestamp_sec - src_start) * fps)
            return tl_start + offset_frames
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('battles', type=Path, help='JSON from detect_battles.py')
    parser.add_argument('--gap-frames', default=60, type=int,
                        help='Frames to insert (default: 60 = 1s @ 60fps)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Report what would happen without modifying Resolve')
    args = parser.parse_args()

    if not args.battles.exists():
        print(f'Battles file not found: {args.battles}', file=sys.stderr)
        return 1

    battles = json.loads(args.battles.read_text(encoding='utf-8'))
    if not battles:
        print('No battles in file — nothing to do.')
        return 0

    resolve  = dvr.scriptapp('Resolve')
    project  = resolve.GetProjectManager().GetCurrentProject()
    tl       = project.GetCurrentTimeline()
    fps      = float(tl.GetSetting('timelineFrameRate'))
    a1_map, _ = build_a1_map(tl)
    v1       = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())

    print(f'Timeline: {fps:.0f}fps  |  Gap: {args.gap_frames}f ({args.gap_frames/fps:.2f}s)')
    print(f'Battles to process: {len(battles)}')
    if args.dry_run:
        print('DRY RUN — no changes will be made\n')

    results = []
    for battle in battles:
        ts   = battle['timestamp_sec']
        name = battle.get('trainer_name', 'unknown')
        desc = battle.get('description', '')

        tl_frame = timestamp_to_timeline_frame(ts, a1_map, fps)
        if tl_frame is None:
            print(f'  {ts:.2f}s  {name}: *** timestamp outside timeline range — skipping')
            results.append({'battle': battle, 'status': 'skipped', 'reason': 'outside timeline'})
            continue

        # Find the V1 clip at this timeline frame
        target_clip = None
        for clip in v1:
            cs = clip.GetStart()
            ce = cs + clip.GetDuration()
            if cs <= tl_frame < ce:
                target_clip = clip
                break

        if target_clip is None:
            print(f'  {ts:.2f}s  {name}: *** no V1 clip at frame {tl_frame} — marking only')
            if not args.dry_run:
                tl.AddMarker(tl_frame, 'Orange', f'Battle: {name}', desc, 1, '')
            results.append({'battle': battle, 'tl_frame': tl_frame, 'status': 'marker_only',
                            'reason': 'no V1 clip at position'})
            continue

        right_offset = target_clip.GetRightOffset()
        has_handles  = right_offset >= args.gap_frames

        print(f'  {ts:.2f}s  {name}  frame={tl_frame}  right_handles={right_offset}f', end='')

        if not has_handles:
            print(f'  *** only {right_offset}f of handle — cannot backfill {args.gap_frames}f, marking only')
            if not args.dry_run:
                tl_ok = tl.AddMarker(tl_frame, 'Orange', f'Battle: {name}', desc, 1, '')
            results.append({'battle': battle, 'tl_frame': tl_frame, 'status': 'marker_only',
                            'reason': f'insufficient handles ({right_offset}f < {args.gap_frames}f)'})
            continue

        print(f'  -> extending {args.gap_frames}f')
        if not args.dry_run:
            # Extend this clip's out-point by gap_frames (un-cut the source footage)
            # Resolve API: SetProperty on duration/end is not directly exposed;
            # use AppendToTimeline with recordFrame at clip end to overwrite+extend.
            clip_end_src = target_clip.GetLeftOffset() + target_clip.GetDuration()
            src_end_new  = clip_end_src + args.gap_frames
            mpi          = target_clip.GetMediaPoolItem()

            # Append the gap segment at the clip's current end (overwrite mode)
            ok = project.GetMediaPool().AppendToTimeline([{
                'mediaPoolItem': mpi,
                'startFrame':    clip_end_src,
                'endFrame':      src_end_new - 1,
                'trackIndex':    1,
                'mediaType':     1,
            }])

            # Also add orange timeline marker at the battle start
            tl.AddMarker(tl_frame, 'Orange', f'Battle: {name}', desc, 1, '')

            results.append({'battle': battle, 'tl_frame': tl_frame,
                            'status': 'extended', 'frames_added': args.gap_frames})
        else:
            results.append({'battle': battle, 'tl_frame': tl_frame,
                            'status': 'would_extend', 'frames_added': args.gap_frames})

    # Summary
    extended     = sum(1 for r in results if r['status'] in ('extended', 'would_extend'))
    marker_only  = sum(1 for r in results if r['status'] == 'marker_only')
    skipped      = sum(1 for r in results if r['status'] == 'skipped')
    print(f'\nSummary: {extended} extended, {marker_only} marker-only, {skipped} skipped')
    return 0


if __name__ == '__main__':
    sys.exit(main())
