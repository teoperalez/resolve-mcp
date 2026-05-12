"""Probe what audio fade properties an audio TimelineItem exposes.

Walks the first A2 clip's properties and tries setting common fade names."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

tl = dvr.scriptapp('Resolve').GetProjectManager().GetCurrentProject().GetCurrentTimeline()
a2 = tl.GetItemListInTrack('audio', 2) or []
if not a2:
    print('No A2 clips.')
    sys.exit(1)

item = a2[0]
print(f'Clip: {item.GetName()!r}  start={item.GetStart()}  dur={item.GetDuration()}')

print('\n── Full GetProperty() dict ──')
props = item.GetProperty()
if isinstance(props, dict):
    for k in sorted(props):
        print(f'  {k!r}: {props[k]!r}')

print('\n── SetProperty probes ──')
attempts = [
    ('AudioFadeIn', 60),
    ('AudioFadeOut', 60),
    ('FadeIn', 60),
    ('FadeOut', 60),
    ('LeftAudioFade', 60),
    ('RightAudioFade', 60),
    ('AudioFadeInFrames', 60),
    ('AudioFadeOutFrames', 60),
]
for key, value in attempts:
    try:
        ok = item.SetProperty(key, value)
    except Exception as e:
        ok = f'EXC {e}'
    after = item.GetProperty(key)
    print(f'  SetProperty({key!r}, {value}) → {ok!r}  GetProperty now={after!r}')
