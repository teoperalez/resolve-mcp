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

# Wipe to MediaOut
for _, t in list(comp.GetToolList(False).items()):
    if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
        t.Delete()

# Run a Lua chunk that builds an animated plane
lua_chunk = '''
local plane = comp:AddTool("ImagePlane3D", 0, 0)
plane:SetAttrs({TOOLS_Name = "AnimPlane"})

local spline = comp:AddTool("BezierSpline", -2, 0)
spline:SetAttrs({TOOLS_Name = "RotSpline"})

-- Connect spline.Value to plane's Rotate.Y input using bracket notation
plane["Transform3DOp.Rotate.Y"] = spline

-- Set keyframes
spline:SetKeyFrames({
    [0]  = { 0.0 },
    [30] = { 45.0 },
    [60] = { 90.0 },
    [90] = { 180.0 }
})

-- Save a marker so we know the Lua ran
comp:SetData("LuaTestMarker", "done")
'''
comp.Execute(lua_chunk)
print('marker after Execute:', comp.GetData('LuaTestMarker'))

# Verify
print('tools after Execute:')
for i, t in comp.GetToolList(False).items():
    print(f'  [{i}] {t.GetAttrs().get("TOOLS_RegID"):14} {t.GetAttrs().get("TOOLS_Name")}')

plane = comp.FindTool('AnimPlane')
if plane:
    for f in (0, 15, 30, 45, 60, 75, 90):
        v = plane.GetInput('Transform3DOp.Rotate.Y', f)
        print(f'  f={f:2d}: rotY={v}')
else:
    print('NO PLANE FOUND')
