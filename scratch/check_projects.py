import sys
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr

r = dvr.scriptapp('Resolve')
pm = r.GetProjectManager()
print('current project:', pm.GetCurrentProject().GetName())
print('all projects in current folder:')
for p in pm.GetProjectListInCurrentFolder():
    print(' ', p)
