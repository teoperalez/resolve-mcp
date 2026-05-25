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

# Wipe to MediaOut
for _, t in list(comp.GetToolList(False).items()):
    if t.GetAttrs().get('TOOLS_RegID') != 'MediaOut':
        t.Delete()

# Wrap in pcall - any error message will be saved in comp:GetData
lua = r'''
local ok, err = pcall(function()
    local plane = comp:AddTool("ImagePlane3D", 0, 2)
    plane:SetAttrs({TOOLS_Name = "TestPlane"})
    local logo = comp:AddTool("Loader", -4, 2)
    logo:SetAttrs({TOOLS_Name = "TestLogo"})
    logo.Clip[1] = "C:\\Programming\\IRLPC Hyperframes\\animations\\logo-flip\\logo-rbypc.png"

    -- Try various connection syntaxes
    plane.MaterialInput = logo
end)
if not ok then comp:SetData("LuaError", tostring(err))
else comp:SetData("LuaError", "OK") end
'''
comp.Execute(lua)
_t.sleep(0.5)
print('LuaError:', comp.GetData('LuaError'))

print('\ntools after:')
for i, t in comp.GetToolList(False).items():
    a = t.GetAttrs()
    print(f'  [{i}] {a.get("TOOLS_RegID"):14} {a.get("TOOLS_Name")}')
