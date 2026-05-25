"""Create or find a 1920x1080@60fps test timeline for the logo-flip Fusion build."""
import sys
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

r = dvr.scriptapp('Resolve')
pm = r.GetProjectManager()
proj = pm.GetCurrentProject()
mp = proj.GetMediaPool()
print('project:', proj.GetName())

existing = None
for i in range(1, proj.GetTimelineCount() + 1):
    t = proj.GetTimelineByIndex(i)
    if t.GetName() == 'logo-flip-fusion-test':
        existing = t
        break

if existing:
    print('found existing test timeline')
    proj.SetCurrentTimeline(existing)
    tl = existing
else:
    tl = mp.CreateEmptyTimeline('logo-flip-fusion-test')
    print('created new timeline:', tl.GetName() if tl else None)

if tl:
    tl.SetSetting('useCustomSettings', '1')
    tl.SetSetting('timelineResolutionWidth', '1920')
    tl.SetSetting('timelineResolutionHeight', '1080')
    tl.SetSetting('timelineFrameRate', '60')
    print('tl resolution:', tl.GetSetting('timelineResolutionWidth'), 'x', tl.GetSetting('timelineResolutionHeight'))
    print('tl fps:', tl.GetSetting('timelineFrameRate'))
    print('tl start:', tl.GetStartFrame(), 'end:', tl.GetEndFrame())
