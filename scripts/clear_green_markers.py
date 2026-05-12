"""Delete all green markers on the current timeline (used to clean up wrongly
placed Battle End markers before re-running mark_battle_ends.py)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

tl = dvr.scriptapp('Resolve').GetProjectManager().GetCurrentProject().GetCurrentTimeline()
markers = tl.GetMarkers() or {}
green = [f for f, m in markers.items() if m.get('color') == 'Green']
print(f'Found {len(green)} green marker(s).')
for f in green:
    ok = tl.DeleteMarkerAtFrame(f)
    print(f'  delete @{f}: {ok}')
print('Done.')
