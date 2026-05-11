"""
Ripple delete clips shorter than MIN_FRAMES from Video 1 and Audio 1.

Usage:
    python remove_short_clips.py [min_frames=5]

Examples:
    python remove_short_clips.py        # removes clips < 5 frames
    python remove_short_clips.py 10     # removes clips < 10 frames
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

import DaVinciResolveScript as dvr

min_frames = int(sys.argv[1]) if len(sys.argv) > 1 else 5

resolve = dvr.scriptapp('Resolve')
tl      = resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()

short_clips = []
for track_type, track_idx in [('video', 1), ('audio', 1)]:
    items = tl.GetItemListInTrack(track_type, track_idx) or []
    short = [c for c in items if c.GetDuration() < min_frames]
    if short:
        print(f'{track_type.upper()} track {track_idx}: {len(short)} clips under {min_frames} frames')
        for c in short:
            print(f'  start={c.GetStart()}  dur={c.GetDuration()}  "{c.GetName()}"')
    short_clips.extend(short)

if not short_clips:
    print(f'No clips under {min_frames} frames found on V1 or A1.')
    sys.exit(0)

print(f'\nRipple deleting {len(short_clips)} clips...')
result = tl.DeleteClips(short_clips, True)
print('Done:', result)
