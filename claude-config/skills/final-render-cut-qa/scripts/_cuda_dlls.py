"""Register NVIDIA pip-package DLL dirs before CTranslate2 / faster-whisper imports on Windows.

On Windows, faster-whisper's CUDA backend (CTranslate2) needs cuBLAS + cuDNN DLLs on the
DLL search path. The `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` pip packages install
them under `<venv>/Lib/site-packages/nvidia/*/bin/` but don't add them to PATH.

Call `register_nvidia_dll_dirs()` ONCE before `from faster_whisper import WhisperModel`.

This is the same helper that lives in `C:/Programming/resolve-mcp/scripts/_cuda_dlls.py`.
We duplicate it here so the skill is standalone (doesn't depend on the resolve-mcp checkout).
"""
import os
import sys
from pathlib import Path


def register_nvidia_dll_dirs() -> list[str]:
    """Add every `nvidia/*/bin` dir from the active venv's site-packages to DLL search path.

    Returns list of added paths (for logging).
    """
    added = []
    if sys.platform != 'win32':
        return added  # No-op on non-Windows

    # Find site-packages — works for both venv and non-venv setups
    import site
    candidates = []
    for sp in site.getsitepackages():
        candidates.append(Path(sp))
    # Also check current venv
    if hasattr(sys, 'prefix'):
        candidates.append(Path(sys.prefix) / 'Lib' / 'site-packages')

    seen = set()
    for sp_dir in candidates:
        if not sp_dir.exists() or sp_dir in seen:
            continue
        seen.add(sp_dir)
        nvidia_dir = sp_dir / 'nvidia'
        if not nvidia_dir.exists():
            continue
        for sub in nvidia_dir.iterdir():
            bin_dir = sub / 'bin'
            if bin_dir.is_dir():
                try:
                    os.add_dll_directory(str(bin_dir))
                    added.append(str(bin_dir))
                except (FileNotFoundError, OSError):
                    pass
    return added


if __name__ == '__main__':
    added = register_nvidia_dll_dirs()
    if added:
        print(f'Registered {len(added)} NVIDIA DLL dir(s):')
        for p in added:
            print(f'  {p}')
    else:
        print('No NVIDIA DLL dirs found (non-Windows or packages not installed)')
