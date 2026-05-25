import os, sys, time as _t
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
for i in range(1, proj.GetTimelineCount() + 1):
    t = proj.GetTimelineByIndex(i)
    if t.GetName() == 'logo-flip-fusion-test':
        proj.SetCurrentTimeline(t); _t.sleep(0.5); break
tl = proj.GetCurrentTimeline()
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)

print('TOOL LIST RIGHT NOW (no wipe, no add):')
for i, t in comp.GetToolList(False).items():
    a = t.GetAttrs()
    print(f'  [{i}] RegID={a.get("TOOLS_RegID"):14} Name={a.get("TOOLS_Name")}')

plane = comp.FindTool('TestPlane')
print('\nFindTool TestPlane:', plane)
if plane:
    for f in (0, 5, 11, 20, 30, 50, 68, 100, 130):
        v = plane.GetInput('Transform3DOp.Rotate.Y', f)
        print(f'  f={f:3d}: rotY={v}')
