"""Build the FULL step 3 graph in a single Lua chunk so connection/keyframe
order is atomic within Fusion's Lua context."""
import os, sys, time as _t
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr

# --- Compute keyframes ---
FPS = 60.0

def p2_out(t):  return 1 - (1 - t) ** 2
def p2_inout(t): return 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2

def build_rotY():
    f_anti = round(0.18 * FPS); f_spin = round(1.13 * FPS)
    d = {}
    step = 2
    for f in range(0, f_anti + 1, step):
        t = min(1.0, f / f_anti) if f_anti else 0
        d[f] = -12 * p2_out(t)
    d[f_anti] = -12.0
    for f in range(f_anti + step, f_spin + 1, step):
        t = (f - f_anti) / (f_spin - f_anti)
        d[f] = -12 + 732 * p2_inout(t)
    d[f_spin] = 720.0
    d[132] = 720.0
    return sorted(d.items())

ROT_Y = build_rotY()
print(f'ROT_Y: {len(ROT_Y)} keys')

def lua_kf(pts):
    return '{ ' + ', '.join(f'[{f}]={{ {v:.4f} }}' for f, v in pts) + ' }'

# --- Connect to Resolve ---
r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
for i in range(1, proj.GetTimelineCount() + 1):
    t = proj.GetTimelineByIndex(i)
    if t.GetName() == 'logo-flip-fusion-test':
        proj.SetCurrentTimeline(t); _t.sleep(0.5); break
tl = proj.GetCurrentTimeline()
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)
for _, t in list(comp.GetToolList(False).items()):
    if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
        t.Delete()

lua = f'''
-- single-chunk build: plane, spline, keyframes, connection
local plane = comp:AddTool("ImagePlane3D", 0, 0)
plane:SetAttrs({{TOOLS_Name = "TestPlane"}})

local rotS = comp:AddTool("BezierSpline", -1, 0)
rotS:SetAttrs({{TOOLS_Name = "TestRotY"}})

-- Set keyframes FIRST so the spline has values, then connect
rotS:SetKeyFrames({lua_kf(ROT_Y)})
plane["Transform3DOp.Rotate.Y"] = rotS
'''
print('lua len:', len(lua))
comp.Execute(lua)

plane = comp.FindTool('TestPlane')
print('plane found:', plane)
if plane:
    for f in (0, 5, 11, 20, 30, 50, 68, 100, 130):
        v = plane.GetInput('Transform3DOp.Rotate.Y', f)
        print(f'  f={f:3d}: rotY={v}')
