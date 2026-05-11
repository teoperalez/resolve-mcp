"""
Clear all clips from audio tracks START through END (inclusive).

Usage:
    python clear_audio_tracks.py [start=2] [end=5]

Examples:
    python clear_audio_tracks.py          # clears A2–A5
    python clear_audio_tracks.py 3 6      # clears A3–A6
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

import DaVinciResolveScript as dvr

start_track = int(sys.argv[1]) if len(sys.argv) > 1 else 2
end_track   = int(sys.argv[2]) if len(sys.argv) > 2 else 5

resolve  = dvr.scriptapp('Resolve')
tl       = resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
n_tracks = tl.GetTrackCount('audio')

print(f'Clearing audio tracks {start_track}–{end_track} (timeline has {n_tracks} audio tracks)')

all_items = []
for t in range(start_track, end_track + 1):
    if t > n_tracks:
        print(f'  A{t}: does not exist, skipping')
        continue
    items = tl.GetItemListInTrack('audio', t) or []
    print(f'  A{t}: {len(items)} clips')
    all_items.extend(items)

if not all_items:
    print('Nothing to delete.')
    sys.exit(0)

print(f'Deleting {len(all_items)} clips total...')
result = tl.DeleteClips(all_items)
print('Done:', result)
