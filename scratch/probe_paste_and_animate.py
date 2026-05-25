"""Test two approaches for setting keyframes:
1) AddTool('BezierSpline') + ConnectInput
2) comp.Paste(setting_text)

Goal: figure out which one works for animating Transform3DOp.Rotate.Y.
"""
import os, sys
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
# Switch to test timeline
for i in range(1, proj.GetTimelineCount() + 1):
    t = proj.GetTimelineByIndex(i)
    if t.GetName() == 'logo-flip-fusion-test':
        proj.SetCurrentTimeline(t)
        break
import time as _t; _t.sleep(0.5)
tl = proj.GetCurrentTimeline()
print('tl:', tl.GetName())
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)
print('comp:', comp)

# Wipe to MediaOut
for i, t in list(comp.GetToolList(False).items()):
    if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
        t.Delete()

# Approach 1: AddTool BezierSpline + connect via SetInput
print('\n=== Approach 1: Add BezierSpline, connect ===')
plane = comp.AddTool('ImagePlane3D', 0, 0)
spline = comp.AddTool('BezierSpline', -2, 0)
spline.SetAttrs({'TOOLS_Name': 'RotY_anim'})
# Try connecting via direct assignment
try:
    plane['Transform3DOp.Rotate.Y'] = spline
    print('  direct assign: OK')
except Exception as e:
    print(f'  direct assign failed: {e}')

# Try SetExpression
try:
    plane['Transform3DOp.Rotate.Y'].SetExpression(spline.Name + '.Value')
    print('  SetExpression OK')
except Exception as e:
    print(f'  SetExpression failed: {e}')

# Try ConnectTo
try:
    plane['Transform3DOp.Rotate.Y'].ConnectTo(spline)
    print('  ConnectTo OK')
except Exception as e:
    print(f'  ConnectTo failed: {e}')

# Try set keyframes via spline indexing
try:
    spline[0] = 0.0
    spline[30] = 45.0
    spline[60] = 90.0
    print('  spline indexed set OK')
except Exception as e:
    print(f'  spline indexed set failed: {e}')

# Read back rotation at frame 30
try:
    v = plane.GetInput('Transform3DOp.Rotate.Y', 30)
    print(f'  read rotY@30: {v}')
except Exception as e:
    print(f'  read failed: {e}')

# Approach 2: comp.Paste with a template
print('\n=== Approach 2: comp.Paste() with .setting text ===')
plane.Delete()
spline.Delete()

setting = """{
    Tools = ordered() {
        PasteTestPlane = ImagePlane3D {
            CtrlWZoom = false,
            Inputs = {
                ["Transform3DOp.Rotate.Y"] = Input {
                    SourceOp = "PasteTestSpline",
                    Source = "Value",
                },
            },
            ViewInfo = OperatorInfo { Pos = { -200, 30 } },
        },
        PasteTestSpline = BezierSpline {
            SplineColor = { Red = 252, Green = 132, Blue = 195 },
            NameSet = true,
            KeyFrames = {
                [0]  = { 0,   Flags = { Linear = true }, RH = { 10, 30 } },
                [30] = { 45,  Flags = { Linear = true }, LH = { 20, 35 }, RH = { 40, 60 } },
                [60] = { 90,  Flags = { Linear = true }, LH = { 50, 80 } }
            }
        }
    },
    ActiveTool = "PasteTestPlane"
}
"""
ok = comp.Paste(setting)
print('Paste returned:', ok)

# Verify
print('tools after paste:')
for i, t in comp.GetToolList(False).items():
    print(f'  [{i}] {t.GetAttrs().get("TOOLS_RegID"):14} {t.GetAttrs().get("TOOLS_Name")}')

pasted_plane = comp.FindTool('PasteTestPlane')
if pasted_plane:
    for f in (0, 15, 30, 45, 60):
        try:
            v = pasted_plane.GetInput('Transform3DOp.Rotate.Y', f)
            print(f'  f={f:2d}: rotY={v}')
        except Exception as e:
            print(f'  f={f}: read failed: {e}')
else:
    print('  NO PASTED PLANE FOUND')
