"""Probe what RetimeProcess actually does. Sets it to various values and
reports whether the clip's GetDuration changes.

If duration changes → RetimeProcess controls speed.
If duration doesn't change → RetimeProcess is just the interpolation method
(Nearest / Frame Blend / Optical Flow) applied when speed is changed via some
OTHER mechanism we haven't found yet.

Also probes related property names to surface anything retime-related.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

tl   = dvr.scriptapp('Resolve').GetProjectManager().GetCurrentProject().GetCurrentTimeline()
v1   = tl.GetItemListInTrack('video', 1) or []
item = v1[0]
print(f'Clip: {item.GetName()!r}  duration={item.GetDuration()}')
print(f'Initial RetimeProcess: {item.GetProperty("RetimeProcess")!r}')
print()

# Try RetimeProcess values 0–6
print('── SetProperty("RetimeProcess", N) ──')
for n in range(7):
    before = item.GetDuration()
    try:
        ok = item.SetProperty('RetimeProcess', n)
    except Exception as e:
        ok = f'EXC {e}'
    after = item.GetDuration()
    cur   = item.GetProperty('RetimeProcess')
    print(f'  set={n:2d}  returned={ok!r:8}  duration {before}→{after}  '
          f'GetProperty now={cur!r}')

# Reset to 0
item.SetProperty('RetimeProcess', 0)

# Probe other retime-related names
print('\n── Other retime-related property probes ──')
for key in ('TimeStretch', 'TimeScale', 'ClipSpeed', 'ResolveTimeScale',
            'TimelineSpeed', 'PlaybackRate', 'FrameRate', 'Frame Rate',
            'Retime', 'RetimeSpeed', 'Reverse', 'ReverseClip'):
    val = item.GetProperty(key)
    print(f'  GetProperty({key!r}): {val!r}')

# Full property dump
print('\n── Full GetProperty() dict ──')
props = item.GetProperty()
if isinstance(props, dict):
    for k in sorted(props):
        print(f'  {k!r}: {props[k]!r}')
else:
    print(f'  unexpected: {type(props).__name__}  {props!r}')
