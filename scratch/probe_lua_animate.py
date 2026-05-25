"""Probe Lua-via-Execute approach for animating an input."""
import os, sys, time as _t
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
for i in range(1, proj.GetTimelineCount() + 1):
    t = proj.GetTimelineByIndex(i)
    if t.GetName() == 'logo-flip-fusion-test':
        proj.SetCurrentTimeline(t)
        break
_t.sleep(0.5)
tl = proj.GetCurrentTimeline()
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)
print('comp:', comp)

# Wipe
for _, t in list(comp.GetToolList(False).items()):
    if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
        t.Delete()

# Try Lua via comp.Execute
lua = '''
local plane = comp:AddTool("ImagePlane3D", 0, 0)
plane:SetAttrs({TOOLS_Name = "LuaPlane"})

local spline = comp:AddTool("BezierSpline")
spline:SetAttrs({TOOLS_Name = "LuaSpline"})

plane.Transform3DOp.Rotate.Y = spline

spline:SetKeyFrames({
    [0]  = { 0.0,  RH = { 10, 0 } },
    [30] = { 45.0, LH = { 20, 30 }, RH = { 40, 60 } },
    [60] = { 90.0, LH = { 50, 80 } }
})

return "ok"
'''
res = comp.Execute(lua)
print('Execute result:', repr(res))

# Verify in Python
plane = comp.FindTool('LuaPlane')
if plane:
    for f in (0, 10, 15, 20, 30, 45, 60):
        try:
            v = plane.GetInput('Transform3DOp.Rotate.Y', f)
            print(f'  f={f:2d}: rotY={v}')
        except Exception as e:
            print(f'  f={f}: {e}')

# Look at spline state
spline = comp.FindTool('LuaSpline')
if spline:
    print('\nspline keyframes:')
    try:
        kf = spline.GetKeyFrames()
        print('  ', kf)
    except Exception as e:
        print('  GetKeyFrames failed:', e)
