"""
Find gaps in Audio 1 longer than MIN_GAP frames and place red markers at the
END of each gap (where the next clip starts) on:
  1. The timeline ruler
  2. The V1 clip at that position

IMPORTANT — marker frameId convention for TimelineItem.AddMarker():
    frameId = clip.GetLeftOffset() + (gap_end - clip.GetStart())
    i.e. the ABSOLUTE SOURCE FRAME, not a timeline-relative offset.
    Using a timeline-relative offset (e.g. 60) places the marker before the
    clip's in-point and it will never be visible.

Usage:
    python mark_audio_gaps.py [min_gap_frames=5]

Examples:
    python mark_audio_gaps.py        # marks gaps > 5 frames
    python mark_audio_gaps.py 30     # marks gaps > 30 frames (0.5s @ 60fps)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

import DaVinciResolveScript as dvr

min_gap = int(sys.argv[1]) if len(sys.argv) > 1 else 5

resolve = dvr.scriptapp('Resolve')
tl      = resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
fps     = float(tl.GetSetting('timelineFrameRate'))

a1 = sorted(tl.GetItemListInTrack('audio', 1) or [], key=lambda x: x.GetStart())
v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda x: x.GetStart())

gaps = []
for i in range(len(a1) - 1):
    gap_start = a1[i].GetStart() + a1[i].GetDuration()
    gap_end   = a1[i + 1].GetStart()
    size      = gap_end - gap_start
    if size > min_gap:
        gaps.append((gap_end, size))

print(f'Timeline: {fps:.0f}fps  |  A1 clips: {len(a1)}  |  Gaps > {min_gap}f: {len(gaps)}')

if not gaps:
    print('No gaps found.')
    sys.exit(0)

for gap_end, size in gaps:
    label = f'Gap {size}f'
    note  = f'Audio gap: {size} frames ({size / fps:.2f}s)'

    # 1. Timeline ruler marker
    tl_ok = tl.AddMarker(gap_end, 'Red', label, note, 1, '')

    # 2. V1 clip marker using absolute source frame
    clip_ok = False
    for clip in v1:
        cs = clip.GetStart()
        ce = cs + clip.GetDuration()
        if cs <= gap_end < ce:
            src_frame = clip.GetLeftOffset() + (gap_end - cs)
            clip_ok = clip.AddMarker(src_frame, 'Red', label, note, 1, '')
            break
        elif gap_end == ce:
            src_frame = clip.GetLeftOffset() + clip.GetDuration() - 1
            clip_ok = clip.AddMarker(src_frame, 'Red', label, note, 1, '')
            break

    print(f'  frame {gap_end}  {size}f ({size / fps:.2f}s)  timeline={tl_ok}  V1={clip_ok}')

print('Done.')
