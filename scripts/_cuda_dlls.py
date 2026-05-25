"""Windows CUDA DLL discovery for faster-whisper / CTranslate2 scripts."""

from __future__ import annotations

import glob
import os
import sys


def register_nvidia_dll_dirs() -> None:
    """Add NVIDIA pip-package DLL dirs to the Windows DLL search path."""
    if os.name != "nt":
        return

    for base in sys.path:
        if "site-packages" not in base:
            continue
        for bin_dir in glob.glob(os.path.join(base, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(bin_dir)
            except OSError:
                pass
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
