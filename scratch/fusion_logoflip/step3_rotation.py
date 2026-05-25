"""Step 3: 3D scene + rotationY + scale animation."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fusion_logoflip._helpers import (
    BG_PNG, LOGO_PNG, OUT_DIR, FPS, DURATION_FRAMES,
    get_test_comp, wipe_comp, render_frames, p2_out, p2_inout,
)


def build_rotY():
    f_anti = round(0.18 * FPS)
    f_spin = round(1.13 * FPS)
    pts = {}
    step = 2
    for f in range(0, f_anti + 1, step):
        t = min(1.0, f / f_anti) if f_anti else 0
        pts[f] = -12 * p2_out(t)
    pts[f_anti] = -12.0
    for f in range(f_anti + step, f_spin + 1, step):
        t = (f - f_anti) / (f_spin - f_anti)
        pts[f] = -12 + 732 * p2_inout(t)
    pts[f_spin] = 720.0
    pts[DURATION_FRAMES] = 720.0
    return pts


def build_scale():
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
    pts[DURATION_FRAMES] = 1.0
    return pts


def main():
    ROT_Y = build_rotY()
    SCALE = build_scale()
    print(f'rotY keys: {len(ROT_Y)}, scale keys: {len(SCALE)}')

    r, proj, tl, clip, comp = get_test_comp()
    print('tl active:', tl.GetName(), 'comp:', comp)

    wipe_comp(comp)

    # Loaders
    bg = comp.AddTool('Loader', -2, 0)
    bg.SetAttrs({'TOOLS_Name': 'BG'})
    bg.Clip[1] = BG_PNG
    bg['Loop'] = 1

    logo = comp.AddTool('Loader', -2, 2)
    logo.SetAttrs({'TOOLS_Name': 'Logo'})
    logo.Clip[1] = LOGO_PNG
    logo['Loop'] = 1

    # 3D scene
    cam = comp.AddTool('Camera3D', 0, 4)
    cam.SetAttrs({'TOOLS_Name': 'Cam'})

    plane = comp.AddTool('ImagePlane3D', 0, 2)
    plane.SetAttrs({'TOOLS_Name': 'LogoPlane'})
    plane.MaterialInput = logo.Output

    m3d = comp.AddTool('Merge3D', 2, 3)
    m3d.SetAttrs({'TOOLS_Name': 'Scene'})
    m3d.SceneInput1 = plane.Output
    m3d.SceneInput2 = cam.Output

    rndr = comp.AddTool('Renderer3D', 4, 3)
    rndr.SetAttrs({'TOOLS_Name': 'Render3D'})
    rndr.SceneInput = m3d.Output

    # 2D merge over bg
    merge2d = comp.AddTool('Merge', 6, 1)
    merge2d.SetAttrs({'TOOLS_Name': 'OverBG'})
    merge2d.Background = bg.Output
    merge2d.Foreground = rndr.Output

    mo = comp.FindTool('MediaOut1')
    if not mo:
        mo = comp.AddTool('MediaOut', 8, 1)
    mo.Input = merge2d.Output

    saver = comp.AddTool('Saver', 8, 3)
    saver.SetAttrs({'TOOLS_Name': 'TestSaver'})
    saver['OutputFormat'] = 'PNGFormat'
    saver.Clip[1] = os.path.join(OUT_DIR, 'step3_unset.png')
    saver.Input = merge2d.Output

    print('tools after build:')
    for i, t in comp.GetToolList(False).items():
        print(f'  [{i}] {t.GetAttrs().get("TOOLS_RegID"):14} {t.GetAttrs().get("TOOLS_Name")}')

    # ---- Keyframes ----
    print('\nsetting rotation Y keyframes...')
    rot_y = plane['Transform3DOp.Rotate.Y']
    for f in sorted(ROT_Y.keys()):
        rot_y[f] = ROT_Y[f]
    print(f'  set {len(ROT_Y)} keyframes')

    print('setting scale (lock + Scale.X) keyframes...')
    plane['Transform3DOp.ScaleLock'] = 1
    sx = plane['Transform3DOp.Scale.X']
    for f in sorted(SCALE.keys()):
        sx[f] = SCALE[f]
    print(f'  set {len(SCALE)} keyframes')

    # Verify
    print('\nverification:')
    for f in (0, 11, 30, 50, 68, 100, 130):
        try:
            v = plane.GetInput('Transform3DOp.Rotate.Y', f)
            s = plane.GetInput('Transform3DOp.Scale.X', f)
            print(f'  f={f:3d}: rotY={v:7.2f}  scale={s:.4f}')
        except Exception as e:
            print(f'  f={f}: {e}')

    # Render test frames
    test_frames = [0, 11, 30, 50, 68, 100]
    print('\nrendering test frames:')
    for f, out, ok, sec in render_frames(comp, saver, test_frames, 'step3_f{frame:03d}.png'):
        print(f'  f={f}: ok={ok} ({sec:.2f}s) -> {out}')


if __name__ == '__main__':
    main()
