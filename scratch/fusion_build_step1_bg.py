"""Step 1: clean comp, add bg loader → MediaOut → Saver test render of frame 0.

This is a checkpoint. After running, we expect bg.png pixels to round-trip
through Fusion unchanged (no resize/colorspace shift) and a single PNG to
appear at C:\\Programming\\resolve-mcp\\fusion_out\\logo-flip\\step1_bg_f000.png.
"""
import os
import sys
import time

sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

BG_PNG = r'C:\Programming\resolve-mcp\fusion_assets\logo-flip\bg.png'
OUT_DIR = r'C:\Programming\resolve-mcp\fusion_out\logo-flip'
os.makedirs(OUT_DIR, exist_ok=True)

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
tl = proj.GetCurrentTimeline()
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)
print('comp:', comp)

# Wipe existing tools (keep MediaOut1) so we have a clean canvas.
comp.Lock()
try:
    comp.StartUndo('clean and build bg')
    tools = comp.GetToolList(False)  # dict keyed by index
    print('existing tools:', {i: t.GetAttrs().get('TOOLS_RegID') for i, t in tools.items()})
    for i, t in list(tools.items()):
        regid = t.GetAttrs().get('TOOLS_RegID')
        if regid != 'MediaOut':
            t.Delete()

    # Add Loader for bg.png
    bg = comp.AddTool('Loader', 0, 0)
    bg.Clip[1] = BG_PNG  # type: ignore[attr-defined]
    bg.SetAttrs({'TOOLS_Name': 'BG'})
    bg['Loop'] = 1  # Loop in case duration mismatch
    print('Loader added, Clip[1]=', bg.Clip[1] if hasattr(bg, 'Clip') else None)

    # Find MediaOut1 and wire bg.Output -> MediaOut.Input
    media_out = comp.FindTool('MediaOut1')
    if media_out is None:
        media_out = comp.AddTool('MediaOut', 4, 0)
    media_out.Input = bg.Output

    # Add a Saver for our test renders (separate from MediaOut so the timeline
    # clip and the script-rendered stills stay independent).
    saver = comp.AddTool('Saver', 4, 2)
    saver.SetAttrs({'TOOLS_Name': 'TestSaver'})
    test_path = os.path.join(OUT_DIR, 'step1_bg_f000.png')
    saver.Clip[1] = test_path
    saver['OutputFormat'] = 'PNGFormat'
    saver.Input = bg.Output

    comp.EndUndo(True)
finally:
    comp.Unlock()

# Confirm tool list
print('\nTools after build:')
for i, t in comp.GetToolList(False).items():
    print(f'  [{i}] {t.GetAttrs().get("TOOLS_RegID")} ({t.GetAttrs().get("TOOLS_Name")})')

# Render frame 0 of comp
print('\nrendering frame 0...')
start = time.time()
ok = comp.Render({'Start': 0, 'End': 0, 'StepRender': False, 'Wait': True})
print('render ok?', ok, 'in', round(time.time() - start, 2), 's')
print('saved to:', test_path, '— exists?', os.path.exists(test_path))
