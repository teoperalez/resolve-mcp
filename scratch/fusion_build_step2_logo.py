"""Step 2: add logo Loader, scale to 593x333 (78% of 760 px stage, contain),
center on canvas, merge over bg. Render frame 0, compare to reference.
"""
import os
import sys
import time

sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

BG_PNG = r'C:\Programming\resolve-mcp\fusion_assets\logo-flip\bg.png'
LOGO_PNG = r'C:\Programming\IRLPC Hyperframes\animations\logo-flip\logo-rbypc.png'
OUT_DIR = r'C:\Programming\resolve-mcp\fusion_out\logo-flip'

# Logo scale: 78% of min(80vw, 760px) at 1920x1080 = 593 px (limit is 760, .logo is 78%)
# PNG native: 3840 px wide. Scale factor = 593/3840 = 0.15443.
LOGO_SCALE = 593.0 / 3840.0

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
tl = proj.GetCurrentTimeline()
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)

comp.Lock()
try:
    comp.StartUndo('add logo')

    # Clean: keep only MediaOut, wipe rest
    for i, t in list(comp.GetToolList(False).items()):
        if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
            t.Delete()

    # Background loader
    bg = comp.AddTool('Loader', 0, 0)
    bg.SetAttrs({'TOOLS_Name': 'BG'})
    bg.Clip[1] = BG_PNG
    bg['Loop'] = 1

    # Logo loader
    logo = comp.AddTool('Loader', 0, 2)
    logo.SetAttrs({'TOOLS_Name': 'Logo'})
    logo.Clip[1] = LOGO_PNG
    logo['Loop'] = 1

    # Transform to scale logo to 593 px wide (centered at default 0.5, 0.5)
    xform = comp.AddTool('Transform', 2, 2)
    xform.SetAttrs({'TOOLS_Name': 'LogoXform'})
    xform.Input = logo.Output
    xform['Size'] = LOGO_SCALE  # uniform scale

    # Merge: bg in Background, logo in Foreground
    merge = comp.AddTool('Merge', 4, 1)
    merge.SetAttrs({'TOOLS_Name': 'MergeLogo'})
    merge.Background = bg.Output
    merge.Foreground = xform.Output

    # MediaOut
    mo = comp.FindTool('MediaOut1') or comp.AddTool('MediaOut', 6, 1)
    mo.Input = merge.Output

    # Saver for test render
    saver = comp.AddTool('Saver', 6, 3)
    saver.SetAttrs({'TOOLS_Name': 'TestSaver'})
    test_path = os.path.join(OUT_DIR, 'step2_logo_f000.png')
    saver.Clip[1] = test_path
    saver['OutputFormat'] = 'PNGFormat'
    saver.Input = merge.Output

    comp.EndUndo(True)
finally:
    comp.Unlock()

print('tools:')
for i, t in comp.GetToolList(False).items():
    print(f'  [{i}] {t.GetAttrs().get("TOOLS_RegID"):14} ({t.GetAttrs().get("TOOLS_Name")})')

print('rendering...')
t0 = time.time()
ok = comp.Render({'Start': 0, 'End': 0, 'Wait': True})
print('ok?', ok, 'in', round(time.time() - t0, 2), 's -> ', test_path)
