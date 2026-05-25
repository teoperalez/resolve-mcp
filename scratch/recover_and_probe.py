"""Reconnect to Resolve and probe 3D tool input IDs. No locking."""
import sys
import time

sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

r = None
for i in range(6):
    r = dvr.scriptapp('Resolve')
    print(f'attempt {i}: r={r}')
    if r:
        break
    time.sleep(2)
if r is None:
    sys.exit('Could not connect to Resolve')

pm = r.GetProjectManager()
proj = pm.GetCurrentProject()
tl = proj.GetCurrentTimeline()
print('project:', proj.GetName(), '| tl:', tl.GetName())
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)
print('comp:', comp)

# Wipe everything except MediaOut, no locking
for i, t in list(comp.GetToolList(False).items()):
    if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
        t.Delete()

plane = comp.AddTool('ImagePlane3D', -2000, 0)
print('plane:', plane)
print('\n=== plane.GetInputList() ===')
for k, inp in plane.GetInputList().items():
    a = inp.GetAttrs()
    name = a.get('INPS_Name', '?')
    iid = a.get('INPS_ID', '?')
    print(f'  [{k:3}] ID={iid:35} Name={name}')

# Cleanup probe tool
plane.Delete()
