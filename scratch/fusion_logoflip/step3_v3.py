"""Step 3 v3: Build the 3D scene + rotation/scale animation via Lua.

We generate Lua keyframe tables in Python and execute them via comp.Execute().
Verification reads back via Python.
"""
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fusion_logoflip._helpers import (
    BG_PNG, LOGO_PNG, OUT_DIR, FPS, DURATION_FRAMES,
    get_test_comp, wipe_comp, p2_out, p2_inout,
)


def build_rotY():
    f_anti = round(0.18 * FPS)
    f_spin = round(1.13 * FPS)
    pts = []
    step = 2
    for f in range(0, f_anti + 1, step):
        t = min(1.0, f / f_anti) if f_anti else 0
        pts.append((f, -12 * p2_out(t)))
    if pts[-1][0] != f_anti:
        pts.append((f_anti, -12.0))
    for f in range(f_anti + step, f_spin + 1, step):
        t = (f - f_anti) / (f_spin - f_anti)
        pts.append((f, -12 + 732 * p2_inout(t)))
    if pts[-1][0] != f_spin:
        pts.append((f_spin, 720.0))
    pts.append((DURATION_FRAMES, 720.0))
    # Dedup keyframes
    seen = {}
    for f, v in pts:
        seen[f] = v
    return sorted(seen.items())


def build_scale():
    f_anti = round(0.18 * FPS)
    f_spin = round(1.13 * FPS)
    f_settle = round(1.68 * FPS)
    pts = []
    step = 2
    for f in range(0, f_anti + 1, step):
        t = min(1.0, f / f_anti) if f_anti else 0
        pts.append((f, 1.0 + (0.92 - 1.0) * p2_out(t)))
    if pts[-1][0] != f_anti: pts.append((f_anti, 0.92))
    for f in range(f_anti + step, f_spin + 1, step):
        t = (f - f_anti) / (f_spin - f_anti)
        pts.append((f, 0.92 + (1.08 - 0.92) * p2_inout(t)))
    if pts[-1][0] != f_spin: pts.append((f_spin, 1.08))
    for f in range(f_spin + step, f_settle + 1, step):
        t = (f - f_spin) / (f_settle - f_spin)
        pts.append((f, 1.08 + (1.0 - 1.08) * p2_out(t)))
    if pts[-1][0] != f_settle: pts.append((f_settle, 1.0))
    pts.append((DURATION_FRAMES, 1.0))
    seen = {}
    for f, v in pts:
        seen[f] = v
    return sorted(seen.items())


def lua_keyframes(pts):
    """Return Lua table literal: '{ [0] = { 0.0 }, [30] = { 45.0 }, ... }'"""
    parts = [f'[{f}]={{ {v:.6f} }}' for f, v in pts]
    return '{ ' + ', '.join(parts) + ' }'


def main():
    ROT_Y = build_rotY()
    SCALE = build_scale()
    print(f'ROT_Y: {len(ROT_Y)} keys (first 3: {ROT_Y[:3]}, last: {ROT_Y[-1]})')
    print(f'SCALE: {len(SCALE)} keys (first 3: {SCALE[:3]}, last: {SCALE[-1]})')

    r, proj, tl, clip, comp = get_test_comp()
    print('active tl:', tl.GetName())

    wipe_comp(comp)

    # --- Python: add Loaders, Camera3D, Merge3D, Renderer3D, 2D merge, MediaOut, Saver ---
    bg = comp.AddTool('Loader', -4, 0); bg.SetAttrs({'TOOLS_Name': 'BG'})
    bg.Clip[1] = BG_PNG; bg['Loop'] = 1

    logo = comp.AddTool('Loader', -4, 2); logo.SetAttrs({'TOOLS_Name': 'Logo'})
    logo.Clip[1] = LOGO_PNG; logo['Loop'] = 1

    cam = comp.AddTool('Camera3D', 0, 4); cam.SetAttrs({'TOOLS_Name': 'Cam'})

    # ImagePlane3D — we'll add this via Lua so we can attach animated splines in the same call.
    lua_setup = f'''
local plane = comp:AddTool("ImagePlane3D", 0, 2)
plane:SetAttrs({{TOOLS_Name = "LogoPlane"}})

-- Lock scale axes so X drives all three
plane["Transform3DOp.ScaleLock"] = 1

-- Rotation Y spline
local rotYS = comp:AddTool("BezierSpline", -1, 2)
rotYS:SetAttrs({{TOOLS_Name = "LogoPlane_RotY"}})
plane["Transform3DOp.Rotate.Y"] = rotYS
rotYS:SetKeyFrames({lua_keyframes(ROT_Y)})

-- Scale X spline (locked to Y/Z via ScaleLock)
local scaleS = comp:AddTool("BezierSpline", -1, 3)
scaleS:SetAttrs({{TOOLS_Name = "LogoPlane_Scale"}})
plane["Transform3DOp.Scale.X"] = scaleS
scaleS:SetKeyFrames({lua_keyframes(SCALE)})
'''
    print('\n--- Lua chunk ---')
    print(lua_setup[:500] + '...')
    comp.Execute(lua_setup)

    # Now re-find plane (created in Lua) and wire MaterialInput + downstream
    plane = comp.FindTool('LogoPlane')
    print('\nplane after lua:', plane)
    plane.MaterialInput = logo.Output

    m3d = comp.AddTool('Merge3D', 2, 3); m3d.SetAttrs({'TOOLS_Name': 'Scene'})
    m3d.SceneInput1 = plane.Output
    m3d.SceneInput2 = cam.Output

    rndr = comp.AddTool('Renderer3D', 4, 3); rndr.SetAttrs({'TOOLS_Name': 'Render3D'})
    rndr.SceneInput = m3d.Output

    merge2d = comp.AddTool('Merge', 6, 1); merge2d.SetAttrs({'TOOLS_Name': 'OverBG'})
    merge2d.Background = bg.Output
    merge2d.Foreground = rndr.Output

    mo = comp.FindTool('MediaOut1') or comp.AddTool('MediaOut', 8, 1)
    mo.Input = merge2d.Output

    saver = comp.AddTool('Saver', 8, 3); saver.SetAttrs({'TOOLS_Name': 'TestSaver'})
    saver['OutputFormat'] = 'PNGFormat'
    saver.Clip[1] = os.path.join(OUT_DIR, 'step3_v3_init.png')
    saver.Input = merge2d.Output

    print('\ntools after build:')
    for i, t in comp.GetToolList(False).items():
        print(f'  [{i}] {t.GetAttrs().get("TOOLS_RegID"):14} {t.GetAttrs().get("TOOLS_Name")}')

    # Verify animation
    print('\nverification (rotation Y / scale X):')
    for f in (0, 11, 30, 50, 68, 100, 130):
        ry = plane.GetInput('Transform3DOp.Rotate.Y', f)
        sx = plane.GetInput('Transform3DOp.Scale.X', f)
        print(f'  f={f:3d}: rotY={ry:7.2f}  scaleX={sx:.4f}')

    # Render test frames covering anticipation/spin/settle
    test_frames = [0, 11, 30, 50, 68, 100]
    print('\nrendering test frames:')
    for f in test_frames:
        out = os.path.join(OUT_DIR, f'step3_f{f:03d}.png')
        saver.Clip[1] = out
        t0 = time.time()
        ok = comp.Render({'Start': f, 'End': f, 'Wait': True})
        print(f'  f={f:3d}: ok={ok} ({time.time()-t0:.2f}s) -> {out}')


if __name__ == '__main__':
    main()
