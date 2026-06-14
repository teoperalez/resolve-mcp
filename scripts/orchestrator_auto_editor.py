from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator import DEFAULT_WORKFLOW_CONFIG, load_catalog
from resolve_mcp.orchestrator.dependencies import find_auto_editor_command


def quote_command(command: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def str_value(mapping: dict[str, str], key: str, default: str = "") -> str:
    value = mapping.get(key, default)
    if value is None:
        return default
    return str(value).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run auto-editor from an orchestrator project profile.")
    parser.add_argument("--config", type=Path, default=DEFAULT_WORKFLOW_CONFIG)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--input", dest="input_path", default="")
    parser.add_argument("--output", dest="output_path", default="")
    parser.add_argument("--preview", action="store_true", help="Run auto-editor --preview and do not require an output file.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    auto_editor_command, auto_editor_detail = find_auto_editor_command(sys.executable)
    if not auto_editor_command:
        install = f'"{sys.executable}" -m pip install auto-editor'
        raise SystemExit(
            "auto-editor is not installed or is not runnable in this Python environment.\n"
            f"{auto_editor_detail}\n\n"
            f"Install it with:\n{install}"
        )

    catalog = load_catalog(args.config)
    profile = catalog.profile(args.profile)
    mapping = profile.mapping(catalog.repo)

    input_value = args.input_path or str_value(mapping, "auto_editor_input") or str_value(mapping, "dialogue_audio") or str_value(mapping, "source_media")
    if not input_value:
        raise SystemExit("No auto-editor input configured. Set auto_editor_input, dialogue_audio, or source_media.")
    input_path = Path(input_value)
    if not input_path.exists():
        raise SystemExit(f"Auto-editor input does not exist: {input_path}")

    output_value = args.output_path or str_value(mapping, "raw_autoeditor_fcpxml")
    if not output_value:
        stem = input_path.stem.replace(" ", "_")
        output_value = str(Path(str_value(mapping, "project_dir", str(input_path.parent))) / f"{stem}_AUTOEDITOR_RAW.fcpxml")
    output_path = Path(output_value)

    export_mode = str_value(mapping, "auto_editor_export", "final-cut-pro")
    margin = str_value(mapping, "auto_editor_margin", "0.2s")
    edit = str_value(mapping, "auto_editor_edit", "audio")
    when_normal = str_value(mapping, "auto_editor_when_normal", "nil")
    when_silent = str_value(mapping, "auto_editor_when_silent", "cut")
    frame_rate = str_value(mapping, "auto_editor_frame_rate") or str_value(mapping, "timeline_fps", "60")
    extra_args = str_value(mapping, "auto_editor_extra_args")

    command = [
        *auto_editor_command,
        str(input_path),
        "--export",
        export_mode,
        "--output",
        str(output_path),
        "--margin",
        margin,
        "--edit",
        edit,
        "--when-normal",
        when_normal,
        "--when-silent",
        when_silent,
        "--frame-rate",
        frame_rate,
        "--no-open",
    ]
    if args.preview or str_value(mapping, "auto_editor_preview").lower() in {"1", "true", "yes", "on"}:
        command.append("--preview")
    if extra_args:
        command.extend(shlex.split(extra_args))

    print(quote_command(command), flush=True)
    if args.dry_run:
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, cwd=str(catalog.repo), check=False)
    if completed.returncode != 0:
        return int(completed.returncode)
    if "--preview" not in command and not output_path.exists():
        raise SystemExit(f"Auto-editor completed but did not create expected output: {output_path}")
    if output_path.exists():
        print(f"Auto-editor output: {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
