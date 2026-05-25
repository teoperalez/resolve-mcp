"""Probe how to access the Fusion comp inside a timeline item, and trim the clip to 132 frames."""
import sys
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

r = dvr.scriptapp('Resolve')
pm = r.GetProjectManager()
proj = pm.GetCurrentProject()
tl = proj.GetCurrentTimeline()
items = tl.GetItemListInTrack('video', 1)
clip = items[0]
print('clip:', clip.GetName(), 'duration:', clip.GetDuration())

# Probe TimelineItem methods
print('\nTimelineItem fusion/comp-related methods:')
for a in sorted(dir(clip)):
    if 'fusion' in a.lower() or 'comp' in a.lower():
        print(' ', a)

comp = clip.GetFusionCompByIndex(1)
print('\ngot comp:', comp)
print('comp methods (subset):')
for a in sorted(dir(comp)):
    if not a.startswith('_'):
        print(' ', a)
