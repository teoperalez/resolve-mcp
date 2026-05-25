"""Fix the blank 3D render: pull camera back, enable auto-resolution on renderer,
ensure renderer uses our Cam."""
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fusion_logoflip._helpers import OUT_DIR, get_test_comp


def main():
    r, proj, tl, clip, comp = get_test_comp()
    by_name = {t.GetAttrs().get('TOOLS_Name'): t for _, t in comp.GetToolList(False).items()}
    cam = by_name.get('Cam')
    rndr = by_name.get('Render3D')
    plane = by_name.get('LogoPlane')
    saver = by_name.get('TestSaver')
    print('Tools:', list(by_name.keys()))

    # Move camera back along Z so the plane (at origin) is in view
    comp.Execute('''
local cam = comp:FindTool("Cam")
cam["Transform3DOp.Translate.Z"] = 10.0
cam["AoV"] = 30.0

local rndr = comp:FindTool("Render3D")
rndr["UseFrameFormatSettings"] = 1   -- auto-resolution from comp frame format
rndr["RendererType"] = 1             -- 1 = software (deterministic)
''')
    time.sleep(0.5)

    # Skip verification — go straight to render

    # Render a few frames
    for f in (0, 30, 50, 68):
        out = os.path.join(OUT_DIR, f'step3b_f{f:03d}.png')
        saver.Clip[1] = out
        t0 = time.time()
        ok = comp.Render({'Start': f, 'End': f, 'Wait': True})
        print(f'  f={f:3d}: ok={ok} ({time.time()-t0:.2f}s) -> {out}')


if __name__ == '__main__':
    main()
