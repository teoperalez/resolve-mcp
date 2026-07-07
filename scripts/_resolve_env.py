"""
Common Resolve environment bootstrap — import this at the top of any script.
Sets sys.path, Resolve scripting env vars, and Windows DLL search paths so
DaVinciResolveScript can be imported without external shell setup.
"""
import sys
import os
from pathlib import Path

SCRIPT_API = Path(os.environ.get(
    'RESOLVE_SCRIPT_API',
    r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting',
))
MODULES_DIR = SCRIPT_API / 'Modules'
SCRIPT_LIB = Path(os.environ.get(
    'RESOLVE_SCRIPT_LIB',
    r'C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll',
))


def _prepend_env_path(path: Path) -> None:
    if not path.is_dir():
        return
    current = os.environ.get('PATH', '')
    entries = [Path(entry) for entry in current.split(os.pathsep) if entry]
    try:
        needle = path.resolve()
        exists = any(entry.resolve() == needle for entry in entries if entry.exists())
    except OSError:
        exists = False
    if not exists:
        os.environ['PATH'] = str(path) + (os.pathsep + current if current else '')


def _add_dll_dir(path: Path) -> None:
    if not path.is_dir():
        return
    if hasattr(os, 'add_dll_directory'):
        try:
            os.add_dll_directory(str(path))
        except OSError:
            pass
    _prepend_env_path(path)


os.environ.setdefault('RESOLVE_SCRIPT_API', str(SCRIPT_API))
os.environ.setdefault('RESOLVE_SCRIPT_LIB', str(SCRIPT_LIB))

if MODULES_DIR.is_dir() and str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))

if sys.platform.startswith('win'):
    pyhome = Path(sys.base_prefix or sys.prefix)
    if pyhome.is_dir():
        os.environ.setdefault('PYTHON3HOME', str(pyhome))
    for dll_dir in (
        SCRIPT_LIB.parent,
        pyhome,
        pyhome / 'DLLs',
        Path(sys.prefix),
        Path(sys.prefix) / 'DLLs',
    ):
        _add_dll_dir(dll_dir)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
