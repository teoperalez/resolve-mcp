"""Step 3: replace the 2D Transform with a full 3D scene so we can rotate the
logo around its Y-axis through 720°+ in a perspective view.

GSAP timeline (charge=0, speed=1) for `wrap` rotationY:
  0.00s..0.18s  : power2.out  →  0  →  -12
  0.18s..1.13s  : power2.inOut →  -12 → +720  (i.e. delta +732)
  end           : snap to 0

GSAP scale on the wrap:
  0.00s..0.18s  : power2.out  →  1.00 → 0.92
  0.18s..1.13s  : power2.inOut →  0.92 → 1.08
  1.13s..1.68s  : power2.out  →  1.08 → 1.00

At 60fps, t·60 = frame:
  0.18s = 10.8 ≈ frame 11
  1.13s = 67.8 ≈ frame 68
  1.68s = 100.8 ≈ frame 101

We sample each easing curve at intermediate frames so the bezier between
keyframes is close to GSAP's easing. We'll use Bezier splines and let Fusion
interpolate between dense samples.
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
FPS = 60.0
DURATION_FRAMES = 132

# ──────────────────────────────────────────────────────────────────────────────
# Easing functions — GSAP equivalents

def ease_power2_out(t):
    return 1 - (1 - t) ** 2

def ease_power2_in(t):
    return t ** 2

def ease_power2_inout(t):
    return 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2

def ease_power3_out(t):
    return 1 - (1 - t) ** 3

def ease_power3_inout(t):
    return 4 * t ** 3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2

# ──────────────────────────────────────────────────────────────────────────────
# Build the rotation Y curve and uniform-scale curve, sampled at 1-frame intervals.

def build_rotation_curve():
    """Returns dict frame -> degrees for rotationY."""
    frames = {}
    # 0.00..0.18s: 0 -> -12 (power2.out)
    f_anti_end = round(0.18 * FPS)
    for f in range(0, f_anti_end + 1):
        t = f / f_anti_end
        v = 0 + (-12 - 0) * ease_power2_out(t)
        frames[f] = v
    # 0.18..1.13s: -12 -> 720 (power2.inOut)
    f_spin_end = round(1.13 * FPS)
    for f in range(f_anti_end + 1, f_spin_end + 1):
        t = (f - f_anti_end) / (f_spin_end - f_anti_end)
        v = -12 + (720 - (-12)) * ease_power2_inout(t)
        frames[f] = v
    # GSAP: tl.set(wrap, { rotationY: 0 }) at end of timeline (i.e. instant snap).
    # We mimic by snapping back to 0 in the settle. Since rotationY=720 is visually
    # identical to 0 (full revolutions), the snap is invisible. So we just hold 720.
    for f in range(f_spin_end + 1, DURATION_FRAMES + 1):
        frames[f] = 720.0
    return frames

def build_scale_curve():
    """Returns dict frame -> scale (uniform)."""
    frames = {}
    f_anti_end = round(0.18 * FPS)        # 11
    f_spin_end = round(1.13 * FPS)        # 68
    f_settle_end = round(1.68 * FPS)      # 101
    # 0..0.18: 1.00 -> 0.92  (power2.out)
    for f in range(0, f_anti_end + 1):
        t = f / f_anti_end
        frames[f] = 1.00 + (0.92 - 1.00) * ease_power2_out(t)
    # 0.18..1.13: 0.92 -> 1.08 (power2.inOut)
    for f in range(f_anti_end + 1, f_spin_end + 1):
        t = (f - f_anti_end) / (f_spin_end - f_anti_end)
        frames[f] = 0.92 + (1.08 - 0.92) * ease_power2_inout(t)
    # 1.13..1.68: 1.08 -> 1.00 (power2.out)
    for f in range(f_spin_end + 1, f_settle_end + 1):
        t = (f - f_spin_end) / (f_settle_end - f_spin_end)
        frames[f] = 1.08 + (1.00 - 1.08) * ease_power2_out(t)
    for f in range(f_settle_end + 1, DURATION_FRAMES + 1):
        frames[f] = 1.00
    return frames

ROT_CURVE = build_rotation_curve()
SCALE_CURVE = build_scale_curve()
print('Rotation curve samples:', {k: round(v, 2) for k, v in list(ROT_CURVE.items())[::10]})
print('Scale curve samples   :', {k: round(v, 3) for k, v in list(SCALE_CURVE.items())[::10]})

# ──────────────────────────────────────────────────────────────────────────────

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
tl = proj.GetCurrentTimeline()
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)

comp.Lock()
try:
    comp.StartUndo('Step 3: 3D rotation rig')

    # Clean: keep only MediaOut
    for i, t in list(comp.GetToolList(False).items()):
        if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
            t.Delete()

    # Background loader
    bg = comp.AddTool('Loader', 0, 0); bg.SetAttrs({'TOOLS_Name': 'BG'}); bg.Clip[1] = BG_PNG; bg['Loop'] = 1

    # Logo loader (texture source)
    logo = comp.AddTool('Loader', 0, 2); logo.SetAttrs({'TOOLS_Name': 'Logo'}); logo.Clip[1] = LOGO_PNG; logo['Loop'] = 1

    # ImagePlane3D — textured by the logo
    plane = comp.AddTool('ImagePlane3D', 2, 2); plane.SetAttrs({'TOOLS_Name': 'LogoPlane'})
    plane.MaterialInput = logo.Output
    # Plane size: ImagePlane3D in Fusion has a Size input that scales the plane.
    # The default plane is 1x1 unit. We'll size it via Transform3D below or via the plane's scale.

    # Camera3D — we'll set position so the plane renders at ~593 px when scaled to 1.0
    cam = comp.AddTool('Camera3D', 2, 4); cam.SetAttrs({'TOOLS_Name': 'Cam'})

    # Merge3D combining plane + camera
    merge3d = comp.AddTool('Merge3D', 4, 3); merge3d.SetAttrs({'TOOLS_Name': 'Scene'})
    merge3d.SceneInput1 = plane.Output
    merge3d.SceneInput2 = cam.Output

    # Renderer3D — flatten back to 2D
    rndr = comp.AddTool('Renderer3D', 6, 3); rndr.SetAttrs({'TOOLS_Name': 'Render3D'})
    rndr.SceneInput = merge3d.Output
    # Use software renderer for determinism (OpenGL renderer can differ)
    rndr['RendererType'] = 0  # 0 = software, 1 = OpenGL (default values may vary)
    rndr['Width'] = 1920
    rndr['Height'] = 1080

    # 2D merge: bg + rendered 3D
    merge = comp.AddTool('Merge', 8, 1); merge.SetAttrs({'TOOLS_Name': 'OverBG'})
    merge.Background = bg.Output
    merge.Foreground = rndr.Output

    mo = comp.FindTool('MediaOut1') or comp.AddTool('MediaOut', 10, 1)
    mo.Input = merge.Output

    saver = comp.AddTool('Saver', 10, 3); saver.SetAttrs({'TOOLS_Name': 'TestSaver'})
    saver['OutputFormat'] = 'PNGFormat'
    saver.Input = merge.Output

    # Set camera FOV — the CSS `perspective: 1400px` on a 760-wide stage gives
    # 2 * atan(380/1400) = ~30.4 degrees (full FOV).
    # Fusion Camera3D 'AoV' (Angle of View) input — set to 30.
    try:
        cam['AoV'] = 30.0
    except Exception:
        pass
    # camera position default is (0,0,0) looking at -Z; move it back
    try:
        cam['Transform3DOp.Translate.Z'] = 7.0  # may not be the right attr — fallback
    except Exception:
        pass

    # Animate plane rotation Y and uniform scale.
    # First connect to a BezierSpline for each.
    try:
        plane.Transform3DOp.Rotate.Y = comp.BezierSpline()
        plane.Transform3DOp.Scale.X = comp.BezierSpline()
        plane.Transform3DOp.Scale.Y = comp.BezierSpline()
        plane.Transform3DOp.Scale.Z = comp.BezierSpline()
    except Exception as e:
        print('Could not attach BezierSpline:', e)

    # Try several alternate attribute paths — Fusion's Image Plane 3D varies.
    print('plane attribute names (looking for rotation/scale):')
    for a in dir(plane):
        if 'rot' in a.lower() or 'scal' in a.lower() or 'transform' in a.lower():
            print(' ', a)

    comp.EndUndo(True)
finally:
    comp.Unlock()

# Render frame 0 to test scene
print('\nrendering frame 0...')
ok = comp.Render({'Start': 0, 'End': 0, 'Wait': True})
saver.Clip[1] = os.path.join(OUT_DIR, 'step3_baseline_f000.png')
ok = comp.Render({'Start': 0, 'End': 0, 'Wait': True})
print('ok?', ok)
