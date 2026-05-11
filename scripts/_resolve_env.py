"""
Common Resolve environment bootstrap — import this at the top of any script.
Sets sys.path and RESOLVE_SCRIPT_LIB so DaVinciResolveScript can be imported
without needing PYTHONPATH set externally.
"""
import sys
import os

sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
os.environ.setdefault('RESOLVE_SCRIPT_LIB', r'C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
