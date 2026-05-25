"""Step 3: build the entire 3D scene + animation in ONE Lua chunk.

Everything that needs animation (rotation Y, scale) is in the Lua chunk so the
spline-connection ordering is atomic. Static connections (MaterialInput, etc.)
are also done in Lua to keep the build cohesive.
"""
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fusion_logoflip._helpers import (
    BG_PNG, LOGO_PNG, OUT_DIR, FPS, DURATION_FRAMES,
    get_test_comp, wipe_comp, p2_out, p2_inout,
)


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
    d[DURATION_FRAMES] = 720.0
    return sorted(d.items())


def build_scale():
    f_anti = round(0.18 * FPS); f_spin = round(1.13 * FPS); f_settle = round(1.68 * FPS)
    d = {}
    step = 2
    for f in range(0, f_anti + 1, step):
        t = min(1.0, f / f_anti) if f_anti else 0
        d[f] = 1.0 + (0.92 - 1.0) * p2_out(t)
    d[f_anti] = 0.92
    for f in range(f_anti + step, f_spin + 1, step):
        t = (f - f_anti) / (f_spin - f_anti)
        d[f] = 0.92 + (1.08 - 0.92) * p2_inout(t)
    d[f_spin] = 1.08
    for f in range(f_spin + step, f_settle + 1, step):
        t = (f - f_spin) / (f_settle - f_spin)
        d[f] = 1.08 + (1.0 - 1.08) * p2_out(t)
    d[f_settle] = 1.0
    d[DURATION_FRAMES] = 1.0
    return sorted(d.items())


def lua_kf(pts):
    return '{ ' + ', '.join(f'[{f}]={{ {v:.4f} }}' for f, v in pts) + ' }'


def main():
    ROT_Y = build_rotY()
    SCALE = build_scale()
    print(f'ROT_Y={len(ROT_Y)}, SCALE={len(SCALE)} keys')

    r, proj, tl, clip, comp = get_test_comp()
    wipe_comp(comp)

    # Escape paths for Lua (backslashes)
    bg_p = BG_PNG.replace('\\', '\\\\')
    logo_p = LOGO_PNG.replace('\\', '\\\\')
    init_out = os.path.join(OUT_DIR, 'step3_init.png').replace('\\', '\\\\')

    lua = f'''
-- ============================================================
-- Step 3 atomic build: loaders + 3D scene + animation
-- ============================================================

-- Background loader
local bg = comp:AddTool("Loader", -4, 0)
bg:SetAttrs({{TOOLS_Name = "BG"}})
bg.Clip[1] = "{bg_p}"
bg.Loop = 1

-- Logo loader (texture source)
local logo = comp:AddTool("Loader", -4, 2)
logo:SetAttrs({{TOOLS_Name = "Logo"}})
logo.Clip[1] = "{logo_p}"
logo.Loop = 1

-- Image Plane 3D
local plane = comp:AddTool("ImagePlane3D", 0, 2)
plane:SetAttrs({{TOOLS_Name = "LogoPlane"}})
plane.MaterialInput = logo
plane["Transform3DOp.ScaleLock"] = 1

-- Rotation Y spline
local rotS = comp:AddTool("BezierSpline", -1, 3)
rotS:SetAttrs({{TOOLS_Name = "LogoPlane_RotY"}})
rotS:SetKeyFrames({lua_kf(ROT_Y)})
plane["Transform3DOp.Rotate.Y"] = rotS

-- Scale spline (X, locked to Y/Z)
local sclS = comp:AddTool("BezierSpline", -1, 4)
sclS:SetAttrs({{TOOLS_Name = "LogoPlane_Scale"}})
sclS:SetKeyFrames({lua_kf(SCALE)})
plane["Transform3DOp.Scale.X"] = sclS

-- Camera
local cam = comp:AddTool("Camera3D", 0, 4)
cam:SetAttrs({{TOOLS_Name = "Cam"}})

-- 3D merge: plane + camera
local m3d = comp:AddTool("Merge3D", 2, 3)
m3d:SetAttrs({{TOOLS_Name = "Scene"}})
m3d.SceneInput1 = plane
m3d.SceneInput2 = cam

-- 3D renderer -> 2D image
local rndr = comp:AddTool("Renderer3D", 4, 3)
rndr:SetAttrs({{TOOLS_Name = "Render3D"}})
rndr.SceneInput = m3d

-- 2D Merge: bg + rendered logo
local mg = comp:AddTool("Merge", 6, 1)
mg:SetAttrs({{TOOLS_Name = "OverBG"}})
mg.Background = bg
mg.Foreground = rndr

-- Locate existing MediaOut (created when the Fusion clip was inserted)
local mo = comp:FindTool("MediaOut1")
if mo == nil then mo = comp:AddTool("MediaOut", 8, 1) end
mo.Input = mg

-- Saver for our test renders
local sv = comp:AddTool("Saver", 8, 3)
sv:SetAttrs({{TOOLS_Name = "TestSaver"}})
sv.OutputFormat = "PNGFormat"
sv.Clip[1] = "{init_out}"
sv.Input = mg
'''
    print(f'Lua chunk length: {len(lua)} chars')
    comp.Execute(lua)
    print('Execute complete. Sleeping to let comp sync...')
    time.sleep(1.0)

    # Use GetToolList to find tools (FindTool may not see freshly-Lua-created tools)
    by_name = {}
    for _, t in comp.GetToolList(False).items():
        n = t.GetAttrs().get('TOOLS_Name')
        by_name[n] = t
    print('Tools by name:', list(by_name.keys()))

    plane = by_name.get('LogoPlane')
    saver = by_name.get('TestSaver')
    if not plane:
        print('!! LogoPlane not found — Lua failed?')
        return
    if not saver:
        print('!! TestSaver not found')
        return

    # Verify animation
    print('\nVerification:')
    for f in (0, 5, 11, 20, 30, 50, 68, 100, 130):
        ry = plane.GetInput('Transform3DOp.Rotate.Y', f)
        sx = plane.GetInput('Transform3DOp.Scale.X', f)
        print(f'  f={f:3d}: rotY={ry:8.2f}, scaleX={sx:.4f}')

    # Render test frames
    test_frames = [0, 11, 30, 50, 68, 100]
    print('\nRendering test frames:')
    for f in test_frames:
        out = os.path.join(OUT_DIR, f'step3_f{f:03d}.png')
        saver.Clip[1] = out
        t0 = time.time()
        ok = comp.Render({'Start': f, 'End': f, 'Wait': True})
        print(f'  f={f:3d}: ok={ok} ({time.time()-t0:.2f}s) -> {out}')


if __name__ == '__main__':
    main()
