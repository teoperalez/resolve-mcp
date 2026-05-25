"""Step 3 incremental: build the 3D scene tool-by-tool via small Lua chunks,
verifying after each one. This avoids the all-or-nothing transactional rollback
that seems to bite the big-chunk approach.
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


def run_chunk(comp, label, lua_body):
    """Run a Lua chunk and verify by checking the comp's tool list after."""
    before = {t.GetAttrs().get('TOOLS_Name') for _, t in comp.GetToolList(False).items()}
    comp.Execute(lua_body)
    time.sleep(0.3)
    after = {t.GetAttrs().get('TOOLS_Name') for _, t in comp.GetToolList(False).items()}
    added = after - before
    print(f'  [{label}] added: {added or "(none)"}')


def main():
    ROT_Y = build_rotY()
    SCALE = build_scale()
    print(f'ROT_Y={len(ROT_Y)}, SCALE={len(SCALE)}')

    r, proj, tl, clip, comp = get_test_comp()
    wipe_comp(comp)

    bg_p = BG_PNG.replace('\\', '\\\\')
    logo_p = LOGO_PNG.replace('\\', '\\\\')

    # Chunk 1: Background + Logo loaders
    run_chunk(comp, 'loaders', f'''
local bg = comp:AddTool("Loader", -4, 0)
bg:SetAttrs({{TOOLS_Name = "BG"}})
bg.Clip[1] = "{bg_p}"
bg.Loop = 1
local logo = comp:AddTool("Loader", -4, 2)
logo:SetAttrs({{TOOLS_Name = "Logo"}})
logo.Clip[1] = "{logo_p}"
logo.Loop = 1
''')

    # Chunk 2: ImagePlane3D, set ScaleLock, connect MaterialInput to Logo
    run_chunk(comp, 'plane', f'''
local plane = comp:AddTool("ImagePlane3D", 0, 2)
plane:SetAttrs({{TOOLS_Name = "LogoPlane"}})
plane["Transform3DOp.ScaleLock"] = 1
local logo = comp:FindTool("Logo")
plane.MaterialInput = logo
''')

    # Chunk 3: RotY spline + connection
    run_chunk(comp, 'rotY-spline', f'''
local plane = comp:FindTool("LogoPlane")
local s = comp:AddTool("BezierSpline", -1, 3)
s:SetAttrs({{TOOLS_Name = "LogoPlane_RotY"}})
s:SetKeyFrames({lua_kf(ROT_Y)})
plane["Transform3DOp.Rotate.Y"] = s
''')

    # Chunk 4: Scale spline + connection
    run_chunk(comp, 'scale-spline', f'''
local plane = comp:FindTool("LogoPlane")
local s = comp:AddTool("BezierSpline", -1, 4)
s:SetAttrs({{TOOLS_Name = "LogoPlane_Scale"}})
s:SetKeyFrames({lua_kf(SCALE)})
plane["Transform3DOp.Scale.X"] = s
''')

    # Chunk 5: Camera3D + Merge3D + Renderer3D
    run_chunk(comp, '3d-pipeline', '''
local cam = comp:AddTool("Camera3D", 0, 4)
cam:SetAttrs({TOOLS_Name = "Cam"})
local plane = comp:FindTool("LogoPlane")
local m3d = comp:AddTool("Merge3D", 2, 3)
m3d:SetAttrs({TOOLS_Name = "Scene"})
m3d.SceneInput1 = plane
m3d.SceneInput2 = cam
local rndr = comp:AddTool("Renderer3D", 4, 3)
rndr:SetAttrs({TOOLS_Name = "Render3D"})
rndr.SceneInput = m3d
''')

    # Chunk 6: 2D merge over bg + wire to MediaOut + Saver
    init_out = os.path.join(OUT_DIR, 'step3_init.png').replace('\\', '\\\\')
    run_chunk(comp, 'final-2d', f'''
local bg = comp:FindTool("BG")
local rndr = comp:FindTool("Render3D")
local mg = comp:AddTool("Merge", 6, 1)
mg:SetAttrs({{TOOLS_Name = "OverBG"}})
mg.Background = bg
mg.Foreground = rndr
local mo = comp:FindTool("MediaOut1")
mo.Input = mg
local sv = comp:AddTool("Saver", 8, 3)
sv:SetAttrs({{TOOLS_Name = "TestSaver"}})
sv.OutputFormat = "PNGFormat"
sv.Clip[1] = "{init_out}"
sv.Input = mg
''')

    # Final tool list
    print('\nFinal tool list:')
    for _, t in comp.GetToolList(False).items():
        a = t.GetAttrs()
        print(f'  {a.get("TOOLS_RegID"):14} {a.get("TOOLS_Name")}')

    # Verify animation via Python
    by_name = {t.GetAttrs().get('TOOLS_Name'): t for _, t in comp.GetToolList(False).items()}
    plane = by_name.get('LogoPlane')
    saver = by_name.get('TestSaver')
    if not plane or not saver:
        print('!! Missing key tools')
        return

    print('\nAnimation check:')
    for f in (0, 5, 11, 20, 30, 50, 68, 100, 130):
        ry = plane.GetInput('Transform3DOp.Rotate.Y', f)
        sx = plane.GetInput('Transform3DOp.Scale.X', f)
        print(f'  f={f:3d}: rotY={ry:8.2f}, scaleX={sx:.4f}')

    # Render
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
