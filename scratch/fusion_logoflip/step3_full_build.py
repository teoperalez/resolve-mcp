"""Full Step 3 build in one go, with camera positioned + renderer auto-resolution.

Incremental Lua chunk approach (small Execute calls verified after each).
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


def safe_tool_names(comp):
    """Get tool names; if comp handle is stale, return None."""
    try:
        tl = comp.GetToolList(False)
        if tl is None:
            return None
        return {t.GetAttrs().get('TOOLS_Name') for _, t in tl.items()}
    except Exception:
        return None


def run(comp_holder, label, body):
    """Run a Lua chunk against comp_holder[0]. Re-fetches comp on stale handle."""
    comp = comp_holder[0]
    before = safe_tool_names(comp)
    if before is None:
        # Stale — re-fetch
        comp = refresh_comp(comp_holder)
        before = safe_tool_names(comp) or set()

    comp.Execute(body)
    time.sleep(0.4)

    after = safe_tool_names(comp)
    if after is None:
        comp = refresh_comp(comp_holder)
        after = safe_tool_names(comp) or set()
    added = after - before
    print(f'  [{label}] added: {added or "(none)"}')


def refresh_comp(holder):
    from fusion_logoflip._helpers import get_test_comp
    _, _, _, _, c = get_test_comp()
    holder[0] = c
    print('    (refreshed comp handle)')
    return c


def main():
    ROT_Y = build_rotY()
    SCALE = build_scale()
    print(f'ROT_Y={len(ROT_Y)}, SCALE={len(SCALE)}')

    r, proj, tl, clip, comp = get_test_comp()
    print('project:', proj.GetName(), '| tl:', tl.GetName())
    wipe_comp(comp)
    comp_holder = [comp]

    bg_p = BG_PNG.replace('\\', '\\\\')
    logo_p = LOGO_PNG.replace('\\', '\\\\')

    # Loaders
    run(comp_holder, 'loaders', f'''
local bg = comp:AddTool("Loader", -4, 0)
bg:SetAttrs({{TOOLS_Name = "BG"}})
bg.Clip[1] = "{bg_p}"; bg.Loop = 1
local logo = comp:AddTool("Loader", -4, 2)
logo:SetAttrs({{TOOLS_Name = "Logo"}})
logo.Clip[1] = "{logo_p}"; logo.Loop = 1
''')

    # Plane + texture
    run(comp_holder, 'plane+texture', '''
local plane = comp:AddTool("ImagePlane3D", 0, 2)
plane:SetAttrs({TOOLS_Name = "LogoPlane"})
plane["Transform3DOp.ScaleLock"] = 1
plane.MaterialInput = comp:FindTool("Logo")
''')

    # Splines for rotY and scale
    run(comp_holder, 'rotY-spline', f'''
local plane = comp:FindTool("LogoPlane")
local s = comp:AddTool("BezierSpline", -1, 3)
s:SetAttrs({{TOOLS_Name = "LogoPlane_RotY"}})
s:SetKeyFrames({lua_kf(ROT_Y)})
plane["Transform3DOp.Rotate.Y"] = s
''')

    run(comp_holder, 'scale-spline', f'''
local plane = comp:FindTool("LogoPlane")
local s = comp:AddTool("BezierSpline", -1, 4)
s:SetAttrs({{TOOLS_Name = "LogoPlane_Scale"}})
s:SetKeyFrames({lua_kf(SCALE)})
plane["Transform3DOp.Scale.X"] = s
''')

    # Camera positioned back along +Z so the plane at origin is visible
    run(comp_holder, 'camera', '''
local cam = comp:AddTool("Camera3D", 0, 4)
cam:SetAttrs({TOOLS_Name = "Cam"})
cam["Transform3DOp.Translate.Z"] = 10.0
cam["AoV"] = 30.0
''')

    # 3D merge + renderer, renderer auto-resolution
    run(comp_holder, '3d-pipeline', '''
local plane = comp:FindTool("LogoPlane")
local cam = comp:FindTool("Cam")
local m3d = comp:AddTool("Merge3D", 2, 3)
m3d:SetAttrs({TOOLS_Name = "Scene"})
m3d.SceneInput1 = plane; m3d.SceneInput2 = cam
local rndr = comp:AddTool("Renderer3D", 4, 3)
rndr:SetAttrs({TOOLS_Name = "Render3D"})
rndr.SceneInput = m3d
rndr["UseFrameFormatSettings"] = 1
rndr["RendererType"] = 1
''')

    # 2D merge + wire to MediaOut + Saver
    init_out = os.path.join(OUT_DIR, 'step3c_init.png').replace('\\', '\\\\')
    run(comp_holder, 'final-2d', f'''
local bg = comp:FindTool("BG")
local rndr = comp:FindTool("Render3D")
local mg = comp:AddTool("Merge", 6, 1)
mg:SetAttrs({{TOOLS_Name = "OverBG"}})
mg.Background = bg; mg.Foreground = rndr
local mo = comp:FindTool("MediaOut1")
if mo then mo.Input = mg end
local sv = comp:AddTool("Saver", 8, 3)
sv:SetAttrs({{TOOLS_Name = "TestSaver"}})
sv.OutputFormat = "PNGFormat"
sv.Clip[1] = "{init_out}"
sv.Input = mg
''')

    # Refresh comp before final inspection (handles may be stale)
    if safe_tool_names(comp_holder[0]) is None:
        refresh_comp(comp_holder)
    comp = comp_holder[0]

    print('\nFinal tools:')
    by_name = {}
    for _, t in comp.GetToolList(False).items():
        a = t.GetAttrs()
        nm = a.get('TOOLS_Name')
        by_name[nm] = t
        print(f'  {a.get("TOOLS_RegID"):14} {nm}')

    saver = by_name.get('TestSaver')
    if not saver:
        print('!! Saver missing')
        return

    # Render test frames covering anticipation, mid-spin, settle
    test_frames = [0, 11, 30, 50, 68, 100]
    print('\nRendering test frames:')
    for f in test_frames:
        out = os.path.join(OUT_DIR, f'step3c_f{f:03d}.png')
        try:
            saver.Clip[1] = out
        except Exception:
            refresh_comp(comp_holder)
            comp = comp_holder[0]
            saver = next((t for _, t in comp.GetToolList(False).items()
                          if t.GetAttrs().get('TOOLS_Name') == 'TestSaver'), None)
            saver.Clip[1] = out
        t0 = time.time()
        ok = comp.Render({'Start': f, 'End': f, 'Wait': True})
        print(f'  f={f:3d}: ok={ok} ({time.time()-t0:.2f}s) -> {out}')


if __name__ == '__main__':
    main()
