"""Probe Camera3D and Renderer3D input IDs to find translate.Z, AoV, resolution."""
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

by_name = {t.GetAttrs().get('TOOLS_Name'): t for _, t in comp.GetToolList(False).items()}
cam = by_name.get('Cam')
rndr = by_name.get('Render3D')
plane = by_name.get('LogoPlane')
print('Cam:', cam, 'Rndr:', rndr, 'Plane:', plane)

print('\n=== Camera3D inputs (filtered: trans/angle/fov/aov/focal/perspect/clip) ===')
for k, inp in cam.GetInputList().items():
    iid = inp.GetAttrs().get('INPS_ID', '')
    nm = inp.GetAttrs().get('INPS_Name', '')
    if any(s in iid.lower() for s in ('translate', 'angle', 'fov', 'aov', 'focal', 'persp', 'clip', 'transform3dop')):
        print(f'  ID={iid:42} Name={nm}')

print('\n=== Renderer3D inputs (filtered: width/height/size/render/cam/output/format/aa/sampling) ===')
for k, inp in rndr.GetInputList().items():
    iid = inp.GetAttrs().get('INPS_ID', '')
    nm = inp.GetAttrs().get('INPS_Name', '')
    if any(s in iid.lower() for s in ('width','height','size','renderer','camera','output','format','process','sample','aa')):
        print(f'  ID={iid:42} Name={nm}')

print('\n=== Renderer3D ALL input IDs (just IDs) ===')
all_ids = []
for k, inp in rndr.GetInputList().items():
    all_ids.append(inp.GetAttrs().get('INPS_ID', ''))
# Print as pairs
for i in range(0, len(all_ids), 4):
    print('  ', ' | '.join(all_ids[i:i+4]))

# Read current cam Z translate
print('\nCurrent cam translate Z:', cam.GetInput('Transform3DOp.Translate.Z'))
print('Current cam AoV:', cam.GetInput('AoV'))
