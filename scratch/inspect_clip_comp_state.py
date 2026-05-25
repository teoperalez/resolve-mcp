import sys
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
tl = proj.GetCurrentTimeline()
print('tl:', tl.GetName())
items = tl.GetItemListInTrack('video', 1)
print('V1 clips:', len(items))
for ix, clip in enumerate(items):
    print(f'  [{ix}] {clip.GetName()} duration={clip.GetDuration()} fusion_count={clip.GetFusionCompCount()}')
    print(f'      fusion comp names: {clip.GetFusionCompNameList()}')
    for ci in range(1, clip.GetFusionCompCount() + 1):
        c = clip.GetFusionCompByIndex(ci)
        print(f'      [{ci}] {c}')
