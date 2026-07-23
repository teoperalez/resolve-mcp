from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator import DEFAULT_WORKFLOW_CONFIG, load_catalog
from resolve_mcp.orchestrator.dependencies import find_auto_editor_command
from resolve_mcp.orchestrator.models import ProjectProfile, expand_templates


class AutoEditorMultiError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def quote_command(command: list[object]) -> str:
    return " ".join(f'"{part}"' if " " in str(part) else str(part) for part in command)


def normalize_path_list(profile: ProjectProfile, mapping: dict[str, str], key: str) -> list[Path]:
    raw = profile.parameters.get(key)
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            values = json.loads(text)
            if not isinstance(values, list):
                raise AutoEditorMultiError(f"{key} must be a JSON list.")
        else:
            values = [part.strip() for part in text.split(";") if part.strip()]
    else:
        raise AutoEditorMultiError(f"{key} must be a list or semicolon-delimited string.")
    return [Path(str(expand_templates(str(value), mapping))) for value in values]


def text_value(profile: ProjectProfile, mapping: dict[str, str], key: str, default: str = "") -> str:
    if key in profile.parameters:
        value = profile.parameters[key]
    elif key in profile.paths:
        value = profile.paths[key]
    else:
        value = mapping.get(key, default)
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(expand_templates(str(value), mapping)).strip()


def int_value(profile: ProjectProfile, mapping: dict[str, str], key: str, default: int) -> int:
    value = text_value(profile, mapping, key, str(default))
    try:
        return int(value)
    except ValueError:
        raise AutoEditorMultiError(f"{key} must be an integer, got {value!r}")


def parse_time_frames(value: str, fps: int) -> int:
    value = (value or "0s").strip()
    if value == "0s":
        return 0
    match = re.fullmatch(r"(\d+)/(\d+)s", value)
    if match:
        num, den = int(match.group(1)), int(match.group(2))
        return round(num * fps / den)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)s", value)
    if match:
        return round(float(match.group(1)) * fps)
    raise ValueError(f"Cannot parse FCPXML time {value!r}")


def fcpxml_duration_info(path: Path, fps: int) -> dict[str, int]:
    if not path.exists():
        return {"raw_duration_frames": 0, "edited_duration_frames": 0}
    root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    resources = root.find("resources")
    raw_duration = 0
    video_refs: set[str] = set()
    if resources is not None:
        for asset in resources.findall("asset"):
            if asset.get("hasVideo") == "1":
                if asset.get("id"):
                    video_refs.add(str(asset.get("id")))
                raw_duration = max(raw_duration, parse_time_frames(asset.get("duration", "0s"), fps))
    edited_duration = 0
    for asset_clip in root.iter("asset-clip"):
        ref = asset_clip.get("ref")
        if video_refs and ref not in video_refs:
            continue
        offset = parse_time_frames(asset_clip.get("offset", "0s"), fps)
        duration = parse_time_frames(asset_clip.get("duration", "0s"), fps)
        edited_duration = max(edited_duration, offset + duration)
    return {"raw_duration_frames": raw_duration, "edited_duration_frames": edited_duration}


def expected_fcpxml_for_source(source: Path) -> Path:
    return source.with_name(f"{source.stem}_ALTERED.fcpxml")


def expected_track_folder_for_source(source: Path) -> Path:
    return source.with_name(f"{source.stem}_tracks")


def selected_parts(profile: ProjectProfile, mapping: dict[str, str]) -> list[Path]:
    return normalize_path_list(profile, mapping, "used_source_parts") or normalize_path_list(profile, mapping, "source_parts")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run auto-editor for every source part in an orchestrator profile.")
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("ORCHESTRATOR_CONFIG_PATH") or DEFAULT_WORKFLOW_CONFIG))
    parser.add_argument("--profile", default=os.environ.get("ORCHESTRATOR_PROFILE_ID") or "")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.profile:
        raise SystemExit("No profile supplied. Use --profile or ORCHESTRATOR_PROFILE_ID.")

    catalog = load_catalog(args.config)
    profile = catalog.profile(args.profile)
    mapping = profile.mapping(catalog.repo)
    parts = selected_parts(profile, mapping)
    if not parts:
        raise SystemExit("No source parts configured. Set used_source_parts or source_parts.")

    auto_editor_command, auto_editor_detail = find_auto_editor_command(sys.executable)
    if not auto_editor_command:
        install = f'"{sys.executable}" -m pip install auto-editor'
        raise SystemExit(
            "auto-editor is not installed or is not runnable in this Python environment.\n"
            f"{auto_editor_detail}\n\nInstall it with:\n{install}"
        )

    fps = int_value(profile, mapping, "timeline_fps", 60)
    dialogue_track_index = int_value(profile, mapping, "dialogue_track_index", 4)
    export_mode = text_value(profile, mapping, "auto_editor_export", "resolve")
    margin = text_value(profile, mapping, "auto_editor_margin", "0.1sec")
    edit = text_value(profile, mapping, "auto_editor_edit", "audio:stream=0")
    extra_args = text_value(profile, mapping, "auto_editor_extra_args")
    manifest_path = Path(mapping.get("parts_manifest") or Path(mapping["codex_dir"]) / "minimum_battles" / "auto_editor" / "parts_manifest.json")

    rows: list[dict[str, Any]] = []
    for index, source in enumerate(parts, start=1):
        if not source.exists():
            raise SystemExit(f"Source media does not exist: {source}")
        fcpxml = expected_fcpxml_for_source(source)
        track_folder = expected_track_folder_for_source(source)
        dialogue_audio = track_folder / f"{dialogue_track_index}.wav"
        command: list[object] = [
            *auto_editor_command,
            source,
            "--margin",
            margin,
            "--edit",
            edit,
            "--export",
            export_mode,
            "--no-open",
        ]
        if extra_args:
            command.extend(shlex.split(extra_args))

        if args.force or not (fcpxml.exists() and dialogue_audio.exists()):
            print(quote_command(command), flush=True)
            if not args.dry_run:
                completed = subprocess.run([str(part) for part in command], cwd=str(catalog.repo), check=False)
                if completed.returncode != 0:
                    return int(completed.returncode)
        else:
            print(f"Reusing auto-editor outputs for part {index}: {fcpxml}")

        if not args.dry_run:
            if not fcpxml.exists():
                raise SystemExit(f"auto-editor did not create expected FCPXML: {fcpxml}")
            if not dialogue_audio.exists():
                raise SystemExit(f"auto-editor did not create expected dialogue audio: {dialogue_audio}")

        durations = fcpxml_duration_info(fcpxml, fps) if fcpxml.exists() else {"raw_duration_frames": 0, "edited_duration_frames": 0}
        rows.append(
            {
                "index": index,
                "source_media": str(source),
                "fcpxml": str(fcpxml),
                "dialogue_audio": str(dialogue_audio),
                "track_folder": str(track_folder),
                **durations,
            }
        )

    manifest = {
        "schema": "minimum_battles_auto_editor_parts_v1",
        "generated_at": now(),
        "profile": profile.id,
        "fps": fps,
        "dialogue_track_index": dialogue_track_index,
        "auto_editor": {
            "command": auto_editor_command,
            "detail": auto_editor_detail,
            "export": export_mode,
            "margin": margin,
            "edit": edit,
            "extra_args": extra_args,
        },
        "dry_run": args.dry_run,
        "parts": rows,
    }
    if not args.dry_run:
        write_json(manifest_path, manifest)
        print(f"Wrote parts manifest: {manifest_path}")
    else:
        print(json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
