from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from typing import Any


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator import DEFAULT_WORKFLOW_CONFIG, load_catalog
from resolve_mcp.orchestrator.dependencies import find_auto_editor_command


ASSET_START_TAG_RE = re.compile(r"<asset\b(?!-clip\b)[^>]*>", re.IGNORECASE | re.DOTALL)
ATTRIBUTE_RE = re.compile(
    r"(?P<name>[A-Za-z_][\w:.-]*)\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)


def parse_fcpxml_seconds(value: str) -> Fraction:
    """Parse an FCPXML rational-seconds value without losing precision."""
    raw = value.strip()
    if not raw.endswith("s"):
        raise ValueError(f"FCPXML time must end in 's': {value!r}")
    token = raw[:-1].strip()
    if not token:
        raise ValueError(f"FCPXML time has no numeric value: {value!r}")
    try:
        return Fraction(token)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"Invalid FCPXML rational-seconds value: {value!r}") from exc


def format_fcpxml_seconds(value: Fraction, *, denominator_hint: int | None = None) -> str:
    """Format an exact duration, retaining the asset's timescale when possible."""
    if denominator_hint and denominator_hint > 0:
        scaled = value * denominator_hint
        if scaled.denominator == 1:
            return f"{scaled.numerator}/{denominator_hint}s"
    if value.denominator == 1:
        return f"{value.numerator}s"
    return f"{value.numerator}/{value.denominator}s"


def _duration_denominator_hint(raw: str) -> int | None:
    match = re.fullmatch(r"\s*[+-]?\d+/(\d+)s\s*", raw)
    return int(match.group(1)) if match else None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _fraction_string(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _time_report(raw: str, value: Fraction) -> dict[str, Any]:
    return {
        "fcpxml": raw,
        "fraction_seconds": _fraction_string(value),
        "seconds": float(value),
    }


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _decode_xml(payload: bytes) -> tuple[str, bytes]:
    bom = b"\xef\xbb\xbf" if payload.startswith(b"\xef\xbb\xbf") else b""
    return payload[len(bom) :].decode("utf-8"), bom


def _replace_asset_durations(xml_text: str, replacements: dict[str, str]) -> str:
    seen: set[str] = set()

    def replace_tag(match: re.Match[str]) -> str:
        tag = match.group(0)
        attributes = {item.group("name"): item for item in ATTRIBUTE_RE.finditer(tag)}
        id_match = attributes.get("id")
        if id_match is None or id_match.group("value") not in replacements:
            return tag
        asset_id = id_match.group("value")
        duration_match = attributes.get("duration")
        if duration_match is None:
            raise ValueError(f"FCPXML asset {asset_id!r} has no duration attribute to repair")
        seen.add(asset_id)
        value_start, value_end = duration_match.span("value")
        return f"{tag[:value_start]}{replacements[asset_id]}{tag[value_end:]}"

    repaired = ASSET_START_TAG_RE.sub(replace_tag, xml_text)
    missing = set(replacements) - seen
    if missing:
        raise ValueError(f"Could not locate asset start tag(s) for duration repair: {sorted(missing)!r}")
    return repaired


def default_duration_repair_report_path(fcpxml_path: Path) -> Path:
    return fcpxml_path.with_suffix(".asset-duration-repair.json")


def repair_fcpxml_asset_durations(
    input_path: Path,
    *,
    output_path: Path | None = None,
    report_path: Path | None = None,
    minimum_asset_durations: dict[str, Fraction] | None = None,
) -> dict[str, Any]:
    """Raise undersized FCPXML asset durations to cover every required source range.

    The XML is changed textually only at affected ``asset@duration`` values so the
    producer's whitespace, attribute ordering, quoting, and declaration survive.
    Durations are never reduced.  Optional exact caller-bound minima support a
    probed full-media duration when the last retained clip ends before the source.
    """
    input_path = input_path.resolve()
    output_path = (output_path or input_path).resolve()
    report_path = (report_path or default_duration_repair_report_path(output_path)).resolve()

    original_bytes = input_path.read_bytes()
    xml_text, bom = _decode_xml(original_bytes)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid FCPXML document {input_path}: {exc}") from exc

    assets: dict[str, dict[str, Any]] = {}
    for element in root.iter():
        if _local_name(element.tag) != "asset":
            continue
        asset_id = element.get("id")
        duration_raw = element.get("duration")
        if not asset_id or duration_raw is None:
            continue
        if asset_id in assets:
            raise ValueError(f"Duplicate FCPXML asset id: {asset_id!r}")
        duration = parse_fcpxml_seconds(duration_raw)
        assets[asset_id] = {
            "duration_raw": duration_raw,
            "duration": duration,
            "clip_count": 0,
            "max_end": None,
            "max_end_clips": [],
        }

    clip_ordinal = 0
    for element in root.iter():
        if _local_name(element.tag) != "asset-clip":
            continue
        clip_ordinal += 1
        asset_id = element.get("ref")
        if asset_id not in assets:
            continue
        start_raw = element.get("start", "0s")
        duration_raw = element.get("duration")
        if duration_raw is None:
            continue
        start = parse_fcpxml_seconds(start_raw)
        duration = parse_fcpxml_seconds(duration_raw)
        if duration < 0:
            raise ValueError(f"asset-clip #{clip_ordinal} has a negative duration: {duration_raw!r}")
        source_end = start + duration
        entry = assets[asset_id]
        entry["clip_count"] += 1
        provenance = {
            "asset_clip_ordinal": clip_ordinal,
            "name": element.get("name", ""),
            "start": _time_report(start_raw, start),
            "duration": _time_report(duration_raw, duration),
            "source_end": _time_report(format_fcpxml_seconds(source_end), source_end),
        }
        if entry["max_end"] is None or source_end > entry["max_end"]:
            entry["max_end"] = source_end
            entry["max_end_clips"] = [provenance]
        elif source_end == entry["max_end"]:
            entry["max_end_clips"].append(provenance)

    minimums: dict[str, Fraction] = {}
    for asset_id, raw_minimum in (minimum_asset_durations or {}).items():
        if asset_id not in assets:
            raise ValueError(
                f"Minimum duration references missing FCPXML asset id: {asset_id!r}"
            )
        minimum = Fraction(raw_minimum)
        if minimum < 0:
            raise ValueError(
                f"Minimum duration for FCPXML asset {asset_id!r} cannot be negative"
            )
        minimums[asset_id] = minimum

    replacements: dict[str, str] = {}
    asset_reports: list[dict[str, Any]] = []
    for asset_id, entry in assets.items():
        before: Fraction = entry["duration"]
        max_end: Fraction | None = entry["max_end"]
        minimum = minimums.get(asset_id)
        candidates = [before]
        if max_end is not None:
            candidates.append(max_end)
        if minimum is not None:
            candidates.append(minimum)
        after = max(candidates)
        after_raw = entry["duration_raw"]
        repaired = after > before
        if repaired:
            after_raw = format_fcpxml_seconds(
                after,
                denominator_hint=_duration_denominator_hint(entry["duration_raw"]),
            )
            replacements[asset_id] = after_raw
        asset_reports.append(
            {
                "asset_id": asset_id,
                "referencing_asset_clip_count": entry["clip_count"],
                "declared_duration_before": _time_report(entry["duration_raw"], before),
                "declared_duration_after": _time_report(after_raw, after),
                "max_referenced_source_end": (
                    _time_report(format_fcpxml_seconds(max_end), max_end) if max_end is not None else None
                ),
                "minimum_duration_floor": (
                    _time_report(format_fcpxml_seconds(minimum), minimum)
                    if minimum is not None
                    else None
                ),
                "max_source_end_provenance": entry["max_end_clips"],
                "repair_applied": repaired,
            }
        )

    repaired_text = _replace_asset_durations(xml_text, replacements) if replacements else xml_text
    repaired_bytes = bom + repaired_text.encode("utf-8")
    if output_path != input_path or repaired_bytes != original_bytes:
        _atomic_write(output_path, repaired_bytes)

    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "auto-editor-fcpxml-asset-duration-repair",
        "input_fcpxml": str(input_path),
        "output_fcpxml": str(output_path),
        "changed": bool(replacements),
        "repaired_asset_count": len(replacements),
        "asset_count": len(assets),
        "input_sha256": _sha256(original_bytes),
        "output_sha256": _sha256(repaired_bytes),
        "policy": {
            "calculation": (
                "max(declared asset@duration, asset-clip@start + asset-clip@duration, "
                "optional caller-bound minimum), grouped by asset-clip@ref"
            ),
            "mutation": "raise asset@duration only; never reduce it",
            "precision": "exact rational seconds via fractions.Fraction",
        },
        "assets": asset_reports,
    }
    _atomic_write(report_path, (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    report["report_path"] = str(report_path)
    return report


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
