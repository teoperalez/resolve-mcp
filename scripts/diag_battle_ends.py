"""Diagnostic: show timeline geometry and where each Battle End marker sits
relative to V1 clip ranges. Prints in seconds-on-timeline so you can compare to
what you see in Resolve."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

resolve  = dvr.scriptapp('Resolve')
project  = resolve.GetProjectManager().GetCurrentProject()
tl       = project.GetCurrentTimeline()
fps      = float(project.GetSetting('timelineFrameRate'))
tl_start = tl.GetStartFrame()
tl_end   = tl.GetEndFrame()

print(f'Timeline: "{tl.GetName()}"  fps={fps}  start={tl_start}  end={tl_end}  '
      f'len_frames={tl_end - tl_start}  len_sec={(tl_end - tl_start)/fps:.1f}')

v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
print(f'\nV1: {len(v1)} clips')
print(f'  first clip: tl_start={v1[0].GetStart()} ({(v1[0].GetStart()-tl_start)/fps:.1f}s into TL)  '
      f'name={v1[0].GetName()!r}')
last = v1[-1]
last_end = last.GetStart() + last.GetDuration()
print(f'  last  clip: tl_end  ={last_end} ({(last_end-tl_start)/fps:.1f}s into TL)  '
      f'name={last.GetName()!r}')

# Look at the first 3 and last 3 V1 clips' source ranges (in source seconds)
def src_range_sec(c):
    return (c.GetLeftOffset() / fps,
            (c.GetLeftOffset() + c.GetDuration()) / fps)

print(f'\nFirst 3 V1 clips (tl_pos_sec  ←→  src_pos_sec):')
for c in v1[:3]:
    tl_s = (c.GetStart() - tl_start) / fps
    tl_e = (c.GetStart() + c.GetDuration() - tl_start) / fps
    src_s, src_e = src_range_sec(c)
    print(f'  tl [{tl_s:8.2f} - {tl_e:8.2f}]  src [{src_s:8.2f} - {src_e:8.2f}]  '
          f'{c.GetName()!r}')

print(f'\nLast 3 V1 clips (tl_pos_sec  ←→  src_pos_sec):')
for c in v1[-3:]:
    tl_s = (c.GetStart() - tl_start) / fps
    tl_e = (c.GetStart() + c.GetDuration() - tl_start) / fps
    src_s, src_e = src_range_sec(c)
    print(f'  tl [{tl_s:8.2f} - {tl_e:8.2f}]  src [{src_s:8.2f} - {src_e:8.2f}]  '
          f'{c.GetName()!r}')

# Markers
markers = tl.GetMarkers() or {}
green = {f: m for f, m in markers.items() if m.get('color') == 'Green'}
print(f'\nMarkers (Green only): {len(green)}')
for f in sorted(green):
    m = green[f]
    tl_offset_sec = (f - tl_start) / fps
    # Is f inside any V1 clip's TIMELINE range?
    inside = next(
        (c for c in v1
         if c.GetStart() <= f < c.GetStart() + c.GetDuration()),
        None
    )
    inside_str = ('inside V1 clip' if inside else '*** OUTSIDE all V1 clips ***')
    print(f'  frame={f}  tl={tl_offset_sec:8.2f}s  '
          f'name={m.get("name", "")!r}  [{inside_str}]')
