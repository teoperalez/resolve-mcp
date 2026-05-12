"""Quick: print the current active timeline + list all timelines in the project."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

project = dvr.scriptapp('Resolve').GetProjectManager().GetCurrentProject()
cur = project.GetCurrentTimeline()
fps = float(project.GetSetting('timelineFrameRate'))
print(f'Project: {project.GetName()}  fps={fps}')
print(f'Current timeline: {cur.GetName() if cur else "(none)"}')
if cur:
    s, e = cur.GetStartFrame(), cur.GetEndFrame()
    v1 = cur.GetItemListInTrack('video', 1) or []
    print(f'  start={s}  end={e}  len_sec={(e-s)/fps:.1f}  V1_clips={len(v1)}')

print(f'\nAll timelines ({project.GetTimelineCount()}):')
for i in range(1, project.GetTimelineCount() + 1):
    t = project.GetTimelineByIndex(i)
    if t:
        s, e = t.GetStartFrame(), t.GetEndFrame()
        v1 = t.GetItemListInTrack('video', 1) or []
        marker = ' ← current' if cur and t.GetName() == cur.GetName() else ''
        print(f'  {i}. "{t.GetName()}"  len_sec={(e-s)/fps:.1f}  V1_clips={len(v1)}{marker}')
