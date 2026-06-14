from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DependencyCheck:
    id: str
    title: str
    ok: bool
    detail: str
    install_command: list[str]
    required_for: str

    @property
    def install_text(self) -> str:
        return " ".join(f'"{part}"' if " " in part else part for part in self.install_command)


def check_runtime_dependencies(python: str | Path | None = None) -> list[DependencyCheck]:
    python_exe = str(python or sys.executable)
    checks = [
        _check_codex(),
        _check_code(),
        _check_auto_editor(python_exe),
    ]
    return checks


def _check_codex() -> DependencyCheck:
    codex = shutil.which("codex")
    if codex:
        version = _run_version([codex, "--version"])
        detail = f"{codex}" + (f" | {version}" if version else "")
        return DependencyCheck(
            id="codex",
            title="Codex CLI",
            ok=True,
            detail=detail,
            install_command=["npm", "install", "-g", "@openai/codex"],
            required_for="Automatic LLM dispatch",
        )
    return DependencyCheck(
        id="codex",
        title="Codex CLI",
        ok=False,
        detail="Not found on PATH.",
        install_command=["npm", "install", "-g", "@openai/codex"],
        required_for="Automatic LLM dispatch",
    )


def _check_code() -> DependencyCheck:
    code = shutil.which("code")
    if code:
        return DependencyCheck(
            id="code",
            title="VS Code CLI",
            ok=True,
            detail=code,
            install_command=[],
            required_for="Opening prompt/output files for review",
        )
    return DependencyCheck(
        id="code",
        title="VS Code CLI",
        ok=False,
        detail="Not found on PATH. This is optional but useful for reviewing LLM packets.",
        install_command=[],
        required_for="Opening prompt/output files for review",
    )


def _check_auto_editor(python_exe: str) -> DependencyCheck:
    command, detail = find_auto_editor_command(python_exe)
    if command:
        return DependencyCheck(
            id="auto_editor",
            title="auto-editor",
            ok=True,
            detail=detail or "Installed.",
            install_command=[python_exe, "-m", "pip", "install", "auto-editor"],
            required_for="Auto-editor FCPXML generation",
        )
    return DependencyCheck(
        id="auto_editor",
        title="auto-editor",
        ok=False,
        detail=detail or "Python module is not installed.",
        install_command=[python_exe, "-m", "pip", "install", "auto-editor"],
        required_for="Auto-editor FCPXML generation",
    )


def find_auto_editor_command(python_exe: str | Path) -> tuple[list[str] | None, str]:
    python_str = str(python_exe)
    scripts_dir = Path(python_str).parent
    candidates: list[list[str]] = []
    for name in ("auto-editor.exe", "auto-editor.cmd", "auto-editor"):
        candidate = scripts_dir / name
        if candidate.exists():
            candidates.append([str(candidate)])
    path_cmd = shutil.which("auto-editor")
    if path_cmd:
        candidates.append([path_cmd])
    candidates.append([python_str, "-m", "auto_editor"])

    details: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for command in candidates:
        key = tuple(command)
        if key in seen:
            continue
        seen.add(key)
        completed = _run_capture(command + ["--version"])
        detail = (completed.stdout or "").strip()
        if completed.returncode == 0:
            return command, detail
        if detail:
            details.append(detail)
    return None, details[-1] if details else "auto-editor command was not found."


def _run_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, stdout=str(exc))


def _run_version(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (completed.stdout or "").strip().splitlines()[0] if completed.stdout else ""
