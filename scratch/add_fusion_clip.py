"""Add an empty Fusion Composition clip to the logo-flip-fusion-test timeline."""
import sys
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

r = dvr.scriptapp('Resolve')
pm = r.GetProjectManager()
proj = pm.GetCurrentProject()
tl = proj.GetCurrentTimeline()
print('tl:', tl.GetName())
print('start:', tl.GetStartFrame())

# Set playhead to start frame so the insertion lands at frame 0 of the timeline.
proj.SetCurrentTimeline(tl)
tl_start = tl.GetStartFrame()

# InsertFusionCompositionIntoTimeline takes no args — inserts a 5-second Fusion comp clip
# at the current playhead position on V1.
res = tl.InsertFusionCompositionIntoTimeline()
print('insert result:', res)
print('end now:', tl.GetEndFrame())

# Inspect the resulting clip
items = tl.GetItemListInTrack('video', 1) or []
print('V1 clip count:', len(items))
for it in items:
    print(' ', it.GetName(), 'start:', it.GetStart(), 'end:', it.GetEnd(),
          'duration:', it.GetDuration(), 'fusion comp count:', it.GetFusionCompCount())
