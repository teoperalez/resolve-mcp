"""Step 3 (v2): 3D rotation rig with animated rotation Y and uniform scale.

Strategy:
- Set static parameters directly via plane[InputID] = value
- For animated params, use indexed assignment: plane[InputID][frame] = value
  This creates a BezierSpline driver automatically with Bezier interp.
- Sample the GSAP easings at every 2 frames so the spline interp is faithful.
"""
import math
import os
import sys
import time as _time

sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

BG_PNG = r'C:\Programming\resolve-mcp\fusion_assets\logo-flip\bg.png'
LOGO_PNG = r'C:\Programming\IRLPC Hyperframes\animations\logo-flip\logo-rbypc.png'
OUT_DIR = r'C:\Programming\resolve-mcp\fusion_out\logo-flip'
os.makedirs(OUT_DIR, exist_ok=True)

FPS = 60.0
DURATION = 132  # frames

# ---------- Easings ----------

def p2_out(t):   return 1 - (1 - t) ** 2
def p2_in(t):    return t ** 2
def p2_inout(t): return 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2
def p3_out(t):   return 1 - (1 - t) ** 3

# ---------- Build sample tables ----------

def build_rotY():
    """Sampled at every 2 frames during dynamic portions."""
    f_anti = round(0.18 * FPS)
    f_spin = round(1.13 * FPS)
    pts = {}
    # Anticipation: 0 -> -12
    step = 2
    for f in range(0, f_anti + 1, step):
        t = min(1.0, f / f_anti) if f_anti else 0
        pts[f] = -12 * p2_out(t)
    pts[f_anti] = -12.0  # ensure exact endpoint
    # Spin: -12 -> 720
    for f in range(f_anti + step, f_spin + 1, step):
        t = (f - f_anti) / (f_spin - f_anti)
        pts[f] = -12 + 732 * p2_inout(t)
    pts[f_spin] = 720.0
    # Settle (no rotation movement)
    pts[DURATION] = 720.0
    return pts

def build_scale():
    """Uniform scale across the wrap."""
    f_anti = round(0.18 * FPS)
    f_spin = round(1.13 * FPS)
    f_settle = round(1.68 * FPS)
    pts = {}
    step = 2
    for f in range(0, f_anti + 1, step):
        t = min(1.0, f / f_anti) if f_anti else 0
        pts[f] = 1.0 + (0.92 - 1.0) * p2_out(t)
    pts[f_anti] = 0.92
    for f in range(f_anti + step, f_spin + 1, step):
        t = (f - f_anti) / (f_spin - f_anti)
        pts[f] = 0.92 + (1.08 - 0.92) * p2_inout(t)
    pts[f_spin] = 1.08
    for f in range(f_spin + step, f_settle + 1, step):
        t = (f - f_spin) / (f_settle - f_spin)
        pts[f] = 1.08 + (1.0 - 1.08) * p2_out(t)
    pts[f_settle] = 1.0
    pts[DURATION] = 1.0
    return pts

ROT_Y = build_rotY()
SCALE = build_scale()
print(f'ROT_Y: {len(ROT_Y)} keys, e.g. f=0:{ROT_Y[0]}, f=30:{ROT_Y.get(30, "-")}, f=68:{ROT_Y[68]}')
print(f'SCALE: {len(SCALE)} keys, e.g. f=0:{SCALE[0]}, f=68:{SCALE[68]}, f=101:{SCALE[101]}')

# ---------- Build Fusion comp ----------

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
tl = proj.GetCurrentTimeline()
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)
print('comp:', comp)

# Wipe to MediaOut
for i, t in list(comp.GetToolList(False).items()):
    if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
        t.Delete()

# Background
bg = comp.AddTool('Loader', -2, 0)
bg.SetAttrs({'TOOLS_Name': 'BG'})
bg.Clip[1] = BG_PNG
bg['Loop'] = 1

# Logo loader (will texture the 3D plane via MaterialInput)
logo = comp.AddTool('Loader', -2, 2)
logo.SetAttrs({'TOOLS_Name': 'Logo'})
logo.Clip[1] = LOGO_PNG
logo['Loop'] = 1

# Camera3D
cam = comp.AddTool('Camera3D', 0, 4)
cam.SetAttrs({'TOOLS_Name': 'Cam'})

# ImagePlane3D
plane = comp.AddTool('ImagePlane3D', 0, 2)
plane.SetAttrs({'TOOLS_Name': 'LogoPlane'})
plane.MaterialInput = logo.Output

# Merge3D combining plane + camera
m3d = comp.AddTool('Merge3D', 2, 3)
m3d.SetAttrs({'TOOLS_Name': 'Scene'})
m3d.SceneInput1 = plane.Output
m3d.SceneInput2 = cam.Output

# Renderer3D
rndr = comp.AddTool('Renderer3D', 4, 3)
rndr.SetAttrs({'TOOLS_Name': 'Render3D'})
rndr.SceneInput = m3d.Output

# 2D merge over bg
merge2d = comp.AddTool('Merge', 6, 1)
merge2d.SetAttrs({'TOOLS_Name': 'OverBG'})
merge2d.Background = bg.Output
merge2d.Foreground = rndr.Output

# MediaOut
mo = comp.FindTool('MediaOut1')
if not mo:
    mo = comp.AddTool('MediaOut', 8, 1)
mo.Input = merge2d.Output

# Saver
saver = comp.AddTool('Saver', 8, 3)
saver.SetAttrs({'TOOLS_Name': 'TestSaver'})
saver['OutputFormat'] = 'PNGFormat'
saver.Clip[1] = os.path.join(OUT_DIR, 'step3_f000.png')
saver.Input = merge2d.Output

print('tools after build:')
for i, t in comp.GetToolList(False).items():
    print(f'  [{i}] {t.GetAttrs().get("TOOLS_RegID"):14} {t.GetAttrs().get("TOOLS_Name")}')

# ---------- Set keyframes ----------
print('\nsetting keyframes...')
try:
    rot_y_input = plane['Transform3DOp.Rotate.Y']
    print('rot_y_input:', rot_y_input)
    for f in sorted(ROT_Y.keys()):
        try:
            rot_y_input[f] = ROT_Y[f]
        except Exception as e:
            print(f'  WARN keyframe rotY @ f={f}: {e}')
    print(f'  set {len(ROT_Y)} rotY keyframes')
except Exception as e:
    print('rotation keyframing failed:', e)

# Scale uniformly: enable ScaleLock, then animate Scale.X
try:
    plane['Transform3DOp.ScaleLock'] = 1  # lock X/Y/Z together
    sx_input = plane['Transform3DOp.Scale.X']
    for f in sorted(SCALE.keys()):
        try:
            sx_input[f] = SCALE[f]
        except Exception as e:
            print(f'  WARN keyframe scale @ f={f}: {e}')
    print(f'  set {len(SCALE)} scaleX keyframes (locked uniform)')
except Exception as e:
    print('scale keyframing failed:', e)

# Read back a few values to verify
print('\nverifying keyframes...')
for f in (0, 11, 30, 50, 68, 100, 130):
    try:
        v = plane.GetInput('Transform3DOp.Rotate.Y', f)
        s = plane.GetInput('Transform3DOp.Scale.X', f)
        print(f'  frame {f:3d}: rotY={v:.2f}, scale={s:.4f}')
    except Exception as e:
        print(f'  frame {f:3d}: read failed: {e}')

# ---------- Test render: 4 key frames ----------
test_frames = [0, 30, 50, 68]
print('\nrendering test frames...')
for f in test_frames:
    out = os.path.join(OUT_DIR, f'step3_f{f:03d}.png')
    saver.Clip[1] = out
    t0 = _time.time()
    ok = comp.Render({'Start': f, 'End': f, 'Wait': True})
    print(f'  frame {f}: ok={ok} ({_time.time()-t0:.2f}s) -> {out}')
