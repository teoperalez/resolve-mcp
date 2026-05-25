import os, sys, time as _t
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr

r = dvr.scriptapp('Resolve')
proj = r.GetProjectManager().GetCurrentProject()
for i in range(1, proj.GetTimelineCount() + 1):
    t = proj.GetTimelineByIndex(i)
    if t.GetName() == 'logo-flip-fusion-test':
        proj.SetCurrentTimeline(t); _t.sleep(0.5); break
tl = proj.GetCurrentTimeline()
clip = tl.GetItemListInTrack('video', 1)[0]
comp = clip.GetFusionCompByIndex(1)

# Try simple Execute - just return a string
print('simple Lua return:', repr(comp.Execute('return "hello"')))
print('simple Lua add 2 numbers:', repr(comp.Execute('return 1+2')))
print('simple Lua add tool:', repr(comp.Execute('local b = comp:AddTool("Background", 0, 0); return tostring(b)')))
print('after add:', list(comp.GetToolList(False).items()))

# Other ways to run Lua
print('comp.SetData / GetData test:')
print(' SetData:', repr(comp.SetData('test', 'hi')))
print(' GetData:', repr(comp.GetData('test')))
