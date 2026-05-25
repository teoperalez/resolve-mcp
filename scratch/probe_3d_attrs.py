"""Add a fresh ImagePlane3D + Camera3D + Renderer3D and dump their input attribute IDs
so we know how to set rotation/scale and renderer width/height."""
import sys
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
tl = proj.GetCurrentTimeline()
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)
print('comp:', comp)

# Wipe existing tools (keep MediaOut)
for i, t in list(comp.GetToolList(False).items()):
    if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
        t.Delete()

plane = comp.AddTool('ImagePlane3D', -2000, 0)
cam = comp.AddTool('Camera3D', -2000, 2)
rndr = comp.AddTool('Renderer3D', -2000, 4)
print('plane:', plane)
print('cam:', cam)
print('rndr:', rndr)

# Use Fusion's GetInputList() to enumerate animatable inputs
print('\n=== plane inputs ===')
inputs = plane.GetInputList()
for k, inp in inputs.items():
    attrs = inp.GetAttrs()
    name = attrs.get('INPS_Name', attrs.get('INPS_ID'))
    iid = attrs.get('INPS_ID')
    print(f'  [{k}] ID={iid:30} Name={name}')

print('\n=== cam inputs ===')
for k, inp in cam.GetInputList().items():
    a = inp.GetAttrs()
    if any(s in a.get('INPS_ID', '').lower() for s in ('aov', 'transform', 'position', 'translate', 'angle', 'fov', 'focal')):
        print(f'  [{k}] {a.get("INPS_ID")} | {a.get("INPS_Name")}')

print('\n=== rndr inputs ===')
for k, inp in rndr.GetInputList().items():
    a = inp.GetAttrs()
    if any(s in a.get('INPS_ID', '').lower() for s in ('width', 'height', 'render', 'type')):
        print(f'  [{k}] {a.get("INPS_ID")} | {a.get("INPS_Name")}')

# Try setting some inputs to see syntax
print('\n=== Testing input setter syntax on plane.Transform3DOp.RotateY-like names ===')
test_names = ['RotateY', 'Rotation.Y', 'Transform3DOp.Rotate.Y', 'EulerRotation.Y', 'TransformRotateY']
for n in test_names:
    try:
        val = plane[n] if n in [a.get_attr() if hasattr(a, 'get_attr') else '' for a in []] else None
        # Try direct getitem
        v = plane[n]
        print(f'  plane[{n!r}] -> {v}')
    except Exception as e:
        print(f'  plane[{n!r}] FAILED: {e}')
