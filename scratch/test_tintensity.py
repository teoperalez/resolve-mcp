import sys
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
tl = proj.GetCurrentTimeline()
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)
t = comp.AddTool('Tintensity', -10500, -10500)
print('Tintensity:', t)
if t:
    attrs = t.GetAttrs()
    print('  RegID:', attrs.get('TOOLS_RegID'))
    print('  Name:', attrs.get('TOOLS_Name'))
    t.Delete()
