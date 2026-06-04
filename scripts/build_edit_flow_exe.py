from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
PYTHON = REPO_DIR / ".venv" / "Scripts" / "python.exe"
ENTRY = REPO_DIR / "scripts" / "edit_flow_gui.py"
BIN_DIR = REPO_DIR / "bin"
NAME = "ResolveEditFlow"


def main() -> int:
    python = PYTHON if PYTHON.exists() else Path(sys.executable)
    if shutil.which(str(python)) is None and not python.exists():
        raise RuntimeError(f"Python not found: {python}")

    try:
        subprocess.run(
            [str(python), "-m", "PyInstaller", "--version"],
            cwd=REPO_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "PyInstaller is not installed. Run:\n"
            "  uv sync --extra gui-build\n"
            "or:\n"
            "  .venv\\Scripts\\python.exe -m pip install pyinstaller"
        ) from exc

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(python),
        "-m",
        "PyInstaller",
        "--onefile",
        "--noconsole",
        "--clean",
        "--name",
        NAME,
        "--distpath",
        str(BIN_DIR),
        "--workpath",
        str(REPO_DIR / "build" / "pyinstaller"),
        "--specpath",
        str(REPO_DIR / "build" / "pyinstaller"),
        str(ENTRY),
    ]
    print(" ".join(f'"{part}"' if " " in part else part for part in cmd), flush=True)
    subprocess.run(cmd, cwd=REPO_DIR, check=True)
    exe = BIN_DIR / f"{NAME}.exe"
    if not exe.exists():
        raise FileNotFoundError(exe)
    print(f"Built {exe} ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
