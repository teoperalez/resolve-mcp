"""Probe Fusion tool registry for ProtoV2/TintIntensity availability + general tool list."""
import sys
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

r = dvr.scriptapp('Resolve')
fusion = r.Fusion()
print('Fusion app:', fusion)

# Check Fusion app methods
print('\nFusion top-level methods (filtered for registry/tool/fuse):')
for a in sorted(dir(fusion)):
    if any(s in a.lower() for s in ('registry', 'tool', 'fuse', 'macro', 'plugin')):
        print(' ', a)

# Open the Resolve clip's fusion comp
pm = r.GetProjectManager()
proj = pm.GetCurrentProject()
tl = proj.GetCurrentTimeline()
items = tl.GetItemListInTrack('video', 1)
clip = items[0]
comp = clip.GetFusionCompByIndex(1)
print('\ncomp:', comp)

# Try adding a few suspect tool IDs to see which exist.
# AddTool returns the tool object or None on failure.
test_ids = ['ProtoV2', 'ProtoVortex', 'TintIntensity', 'TintColor', 'Glow', 'Hotspot',
            'Background', 'Loader', 'MediaIn', 'MediaOut', 'Merge', 'Transform',
            'Transform3D', 'ImagePlane3D', 'Renderer3D', 'Merge3D', 'Camera3D',
            'AmbientLight', 'FastNoise', 'Displace', 'HueCurves', 'BrightnessContrast',
            'ColorCorrector', 'DirectionalBlur', 'Blur']
for tid in test_ids:
    t = comp.AddTool(tid, -10000 - test_ids.index(tid), -10000)
    if t is not None:
        print(f'  + AddTool({tid!r}) -> {t.GetAttrs().get("TOOLS_RegID", "?")}')
        # delete it
        t.Delete()
    else:
        print(f'  - AddTool({tid!r}) FAILED')
