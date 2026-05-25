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

# Wipe
for _, t in list(comp.GetToolList(False).items()):
    if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
        t.Delete()

print('Step 1: add plane only')
comp.Execute('local p = comp:AddTool("ImagePlane3D", 0, 2); p:SetAttrs({TOOLS_Name = "LogoPlane"})')
print('  found:', comp.FindTool('LogoPlane'))

print('Step 2: add ScaleLock')
comp.Execute('local p = comp:FindTool("LogoPlane"); p["Transform3DOp.ScaleLock"] = 1')
print('  scale lock now:', comp.FindTool('LogoPlane').GetInput('Transform3DOp.ScaleLock'))

print('Step 3: add BezierSpline')
comp.Execute('comp:AddTool("BezierSpline", -1, 2):SetAttrs({TOOLS_Name = "LogoPlane_RotY"})')
print('  found:', comp.FindTool('LogoPlane_RotY'))

print('Step 4: try connecting via bracket assignment')
comp.Execute('local p = comp:FindTool("LogoPlane"); local s = comp:FindTool("LogoPlane_RotY"); p["Transform3DOp.Rotate.Y"] = s')
# Check if connected
plane = comp.FindTool('LogoPlane')
print('  rotY input attrs:', plane.GetInput('Transform3DOp.Rotate.Y'))
print('  GetInput at f=0:', plane.GetInput('Transform3DOp.Rotate.Y', 0))

print('Step 5: SetKeyFrames')
comp.Execute('local s = comp:FindTool("LogoPlane_RotY"); s:SetKeyFrames({[0]={0.0}, [30]={45.0}, [60]={90.0}})')
print('  rotY @ 30:', plane.GetInput('Transform3DOp.Rotate.Y', 30))

print('Step 6: Try the full keyframe list with all values')
# Cleanup spline first
comp.Execute('local s = comp:FindTool("LogoPlane_RotY"); if s then s:Delete() end')
# Re-add and connect
comp.Execute('local p = comp:FindTool("LogoPlane"); local s = comp:AddTool("BezierSpline", -1, 2); s:SetAttrs({TOOLS_Name = "LogoPlane_RotY"}); p["Transform3DOp.Rotate.Y"] = s')
# Generate dense keyframes
import math
pts = []
f_anti = 11
f_spin = 68
for f in range(0, f_anti + 1, 2):
    t = f / f_anti
    pts.append((f, -12 * (1 - (1-t)**2)))
for f in range(13, f_spin + 1, 2):
    t = (f - f_anti) / (f_spin - f_anti)
    e = 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2
    pts.append((f, -12 + 732 * e))
pts.append((132, 720))
seen = {}
for f, v in pts:
    seen[f] = v
kf_lua = '{ ' + ', '.join(f'[{f}]={{ {v:.4f} }}' for f, v in sorted(seen.items())) + ' }'
print('  kf_lua len:', len(kf_lua), 'first 200 chars:', kf_lua[:200])
comp.Execute(f'local s = comp:FindTool("LogoPlane_RotY"); s:SetKeyFrames({kf_lua})')
for f in (0, 11, 30, 50, 68, 100, 130):
    print(f'  f={f}: rotY={plane.GetInput("Transform3DOp.Rotate.Y", f)}')
