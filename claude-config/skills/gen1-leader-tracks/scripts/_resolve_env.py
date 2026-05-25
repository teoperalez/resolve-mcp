"""Bootstrap DaVinciResolveScript import path. Import at the top of every Resolve-touching script.

Standalone copy (vendored from resolve-mcp/scripts/_resolve_env.py) so the skill
doesn't depend on the resolve-mcp checkout being at any specific path.
"""
import os
import sys

sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
os.environ.setdefault('RESOLVE_SCRIPT_LIB',
                       r'C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
