"""Trim Fusion clip to 132 frames, probe Fusion tool registry for ProtoV2/TintIntensity."""
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

# Trim end of clip to 132 frames.
# Use SetProperty? Or SetClipColor? Better: just use SetClipEnableFlag? Actually,
# the proper method is to use TimelineItem.SetProperty for properties or
# call clip.SetProperty('Duration', 132). Let's see options.
print('\nLooking for trim/length methods on TimelineItem:')
for a in sorted(dir(clip)):
    if any(s in a.lower() for s in ('trim', 'length', 'property', 'duration', 'end')):
        print(' ', a)

print('\nGetProperty result:', clip.GetProperty())  # all props
