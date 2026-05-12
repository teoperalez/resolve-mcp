"""Isolated test: try SetProperty('Speed', ...) on the first V1 clip of the
current timeline. Reports which property/value-shape (if any) actually changes
the placed-clip's GetDuration. Sets it back to 100% at the end.

Run this on a timeline whose first V1 clip is something safe to retime (e.g.
an intro). It does NOT touch any other clip or property.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

project = dvr.scriptapp('Resolve').GetProjectManager().GetCurrentProject()
tl      = project.GetCurrentTimeline()
v1      = tl.GetItemListInTrack('video', 1) or []
if not v1:
    print('ERROR: no V1 clips')
    sys.exit(1)

item = v1[0]
print(f'Target clip: {item.GetName()!r}  start={item.GetStart()}  '
      f'duration={item.GetDuration()}')

attempts = [
    ('Speed',         400.0),
    ('Speed',         4.0),
    ('Speed',         400),
    ('PlaybackSpeed', 400.0),
    ('PlaybackSpeed', 4.0),
]

before = item.GetDuration()
winner = None
for key, value in attempts:
    try:
        ok = item.SetProperty(key, value)
    except Exception as e:
        ok = f'EXC {e}'
    after = item.GetDuration()
    changed = (after != before)
    print(f'  SetProperty({key!r}, {value!r}) → returned {ok!r}  '
          f'duration: {before} → {after}  '
          f'{"CHANGED" if changed else "no change"}')
    if changed and winner is None:
        winner = (key, value)
        before = after  # use new baseline for subsequent attempts

print()
print('\n── All settable properties (item.GetProperty(None)) ──')
try:
    props = item.GetProperty()
    if isinstance(props, dict):
        speed_like = {k: v for k, v in props.items()
                      if any(s in k.lower() for s in ('speed', 'time', 'retime', 'rate', 'duration'))}
        for k, v in sorted(speed_like.items()):
            print(f'  {k!r}: {v!r}')
        if not speed_like:
            print('  (none of the property names contain speed/time/retime/rate/duration)')
            print(f'  Full property list ({len(props)} entries):')
            for k in sorted(props):
                print(f'    {k!r}')
    else:
        print(f'  GetProperty() returned: {type(props).__name__} {props!r}')
except Exception as e:
    print(f'  GetProperty(None) failed: {e}')

if winner:
    k, v = winner
    print(f'WORKS: SetProperty({k!r}, {v!r}) changed duration.')
    # Try to reset
    for reset_v in (100.0, 1.0, 100):
        try:
            ok = item.SetProperty(k, reset_v)
        except Exception:
            ok = False
        if ok and item.GetDuration() != before:
            print(f'  Reset OK via SetProperty({k!r}, {reset_v!r}) → '
                  f'{item.GetDuration()}')
            break
    else:
        print(f'  WARNING: could not reset clip to 100% — manual undo may be needed.')
else:
    print('NONE of the attempts changed the clip duration. Need a different '
          'retime approach (Fusion clip, pre-rendered file, etc.).')
