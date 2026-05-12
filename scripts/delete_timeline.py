"""Delete a named timeline from the current project. Usage:
    python delete_timeline.py "Timeline Name"
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

if len(sys.argv) < 2:
    print('Usage: delete_timeline.py "Timeline Name"', file=sys.stderr)
    sys.exit(1)

name = sys.argv[1]
project = dvr.scriptapp('Resolve').GetProjectManager().GetCurrentProject()
target = None
for i in range(1, project.GetTimelineCount() + 1):
    t = project.GetTimelineByIndex(i)
    if t and t.GetName() == name:
        target = t
        break

if not target:
    print(f'Not found: "{name}"', file=sys.stderr)
    sys.exit(1)

pool = project.GetMediaPool()
ok = pool.DeleteTimelines([target])
print(f'DeleteTimelines("{name}"): {ok}')
