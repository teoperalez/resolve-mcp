from __future__ import annotations

"""Independent, zero-Resolve audit for one deterministic GSC Gym build."""

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
SRC_DIR = REPO_DIR / "src"
for value in (REPO_DIR, SRC_DIR):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from resolve_mcp.orchestrator.gsc_gym_audio import (  # noqa: E402
    DEFAULT_GAINS_DB,
    SOURCE_A2_SCHEMA,
    SOURCE_CLIP_SCHEMA,
)
from resolve_mcp.orchestrator.gsc_gym_deterministic import (  # noqa: E402
    BATTLE_AUDIO_DIR,
    BATTLE_GAP_FRAMES,
    BATTLE_INTRO_FRAMES,
    INTRO_TRACK,
    OUTRO_TRACK,
    POST_FINAL_REQUIRED_TRACKS,
    WORKFLOW_ID,
    choose_battle_tracks,
    choose_nonbattle_tracks,
    validate_zero_llm_workflow,
)
from resolve_mcp.orchestrator.gsc_gym_fcpxml_plan import (  # noqa: E402
    BATTLE_BOUNDARY_POLICY,
    BATTLE_GAP_DUPLICATES_V1_PREROLL,
    BATTLE_GAP_INSERTS_TIMELINE_FRAMES,
    BATTLE_GAP_POLICY,
    parse_autoeditor_fcpxml,
)
from resolve_mcp.orchestrator.gsc_gym_reference import (  # noqa: E402
    audit_surge_reference,
)


SCHEMA = "gsc_gym_offline_deployment_audit_v1"
EXPECTED_GEOMETRY_CHECKS = {
    "opening_then_continuous_body_v1",
    "lossless_a1_boundary_gaps_with_source_backed_v1_bridges",
    "retained_source_preserved_once_on_v2_and_a1",
    "battle_source_boundaries_map_to_exact_final_ranges",
    "explicit_bounded_deterministic_boundary_mappings",
    "inside_battle_starts_record_both_candidates_and_unique_nearest_selection",
    "attempt_level_ranges_with_first_identity_intro_only",
    "continuous_carousel_v1_with_contiguous_cropped_v2_geometry",
}
EXPECTED_FCPXML_CHECKS = {
    "fcpxml_1_10_4k60",
    "sequence_geometry",
    "continuous_primary_v1",
    "opening_400pct_derivative_260f",
    "a1_lossless_boundary_inserts_with_source_backed_v1_bridges",
    "silent_v2_intros_end_at_battle",
    "complete_a2_plan",
    "mapped_boundary_gap_intro_and_battle_bgm_coincide",
    "structured_a2_battle_ids_exact_fades_and_shuffle_assignments",
    "nonbattle_bgm_fresh_after_battles_no_repeat_and_post_final_sequence",
    "source_backed_member_carousel",
    "linked_outro_v1_a3",
}
EXPECTED_BOUNDARY_POLICY = BATTLE_BOUNDARY_POLICY


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _path_key(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).resolve()))


def _origin(segment: dict[str, Any]) -> Path:
    asset = segment["asset"]
    return Path(str(asset.get("origin_path") or asset["path"])).resolve()


def _general_bgm_occurrences(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reconstruct original-source nonbattle identity starts independently."""

    occurrences: list[dict[str, Any]] = []
    previous_was_general = False
    for segment in segments:
        role = str(segment.get("role") or "")
        if role == "battle":
            previous_was_general = False
            continue
        origin = _origin(segment)
        record_range = [int(value) for value in segment["record_range"]]
        source_range = [int(value) for value in segment["source_range"]]
        continuation = bool(
            previous_was_general
            and occurrences
            and _path_key(occurrences[-1]["source"]) == _path_key(origin)
            and occurrences[-1]["record_range"][1] == record_range[0]
            and occurrences[-1]["source_range"][1] == source_range[0]
        )
        if continuation:
            occurrences[-1]["record_range"][1] = record_range[1]
            occurrences[-1]["source_range"][1] = source_range[1]
            occurrences[-1]["roles"].append(role)
            occurrences[-1]["segment_count"] += 1
        else:
            occurrences.append(
                {
                    "source": str(origin),
                    "filename": origin.name,
                    "record_range": record_range,
                    "source_range": source_range,
                    "roles": [role],
                    "segment_count": 1,
                }
            )
        previous_was_general = True
    return occurrences


def _project_occurrences(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": _path_key(row["source"]),
            "filename": str(row["filename"]),
            "record_range": list(row["record_range"]),
            "source_range": list(row["source_range"]),
        }
        for row in rows
    ]


def _fcpxml_frames(value: str | None) -> int:
    if not value or not value.endswith("s"):
        raise ValueError(f"Invalid FCPXML frame time: {value!r}.")
    frames = Fraction(value[:-1]) * 60
    if frames.denominator != 1:
        raise ValueError(f"Non-integral 60 fps FCPXML time: {value!r}.")
    return frames.numerator


def _file_uri_path(value: str) -> Path:
    parsed = urlparse(value)
    if parsed.scheme.casefold() != "file":
        raise ValueError(f"FCPXML original-media URI is not file-backed: {value!r}.")
    decoded = unquote(parsed.path).replace("/", "\\")
    if len(decoded) >= 3 and decoded[0] == "\\" and decoded[2] == ":":
        decoded = decoded[1:]
    elif parsed.netloc:
        decoded = f"\\\\{parsed.netloc}{decoded}"
    return Path(decoded).resolve()


def _fcpxml_a2_rows(raw_xml: str) -> list[dict[str, Any]]:
    """Read the source-native lane-3 population independently from XML."""

    root = ET.fromstring(raw_xml)
    resources = {
        node.get("id"): node
        for node in root.findall("./resources/asset")
        if node.get("id")
    }
    sequence = root.find("./library/event/project/sequence")
    spine = sequence.find("spine") if sequence is not None else None
    if sequence is None or spine is None:
        raise ValueError("FCPXML has no sequence spine.")
    timeline_start = _fcpxml_frames(sequence.get("tcStart"))
    rows: list[dict[str, Any]] = []
    for parent in list(spine):
        if parent.get("lane") is not None or parent.tag not in {"clip", "asset-clip"}:
            continue
        parent_record = _fcpxml_frames(parent.get("offset")) - timeline_start
        parent_source = _fcpxml_frames(parent.get("start"))
        for child in list(parent):
            if child.tag != "asset-clip" or child.get("lane") != "3":
                continue
            resource = resources.get(child.get("ref"))
            media_rep = resource.find("media-rep") if resource is not None else None
            volume = child.find("adjust-volume")
            if resource is None or media_rep is None or volume is None:
                raise ValueError("A2 XML clip lacks original-media or adjust-volume evidence.")
            duration = _fcpxml_frames(child.get("duration"))
            record_start = (
                parent_record
                + _fcpxml_frames(child.get("offset"))
                - parent_source
            )
            amount = str(volume.get("amount") or "")
            if not amount.endswith("dB"):
                raise ValueError("A2 XML adjust-volume is not expressed in dB.")
            rows.append(
                {
                    "record_range": [record_start, record_start + duration],
                    "source_range": [
                        _fcpxml_frames(child.get("start")),
                        _fcpxml_frames(child.get("start")) + duration,
                    ],
                    "timeline_name": str(child.get("name") or ""),
                    "source_path": str(_file_uri_path(str(media_rep.get("src") or ""))),
                    "resource_name": str(resource.get("name") or ""),
                    "media_source_range": [
                        _fcpxml_frames(resource.get("start")),
                        _fcpxml_frames(resource.get("start"))
                        + _fcpxml_frames(resource.get("duration")),
                    ],
                    "gain_db": float(amount[:-2]),
                }
            )
    rows.sort(key=lambda row: (row["record_range"], _path_key(row["source_path"])))
    return rows


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def audit(
    result_path: Path,
    *,
    config_path: Path,
    reference_contract_path: Path,
    expected_carousel_source_frame: int | None,
) -> dict[str, Any]:
    result_path = result_path.resolve()
    result = _read_json(result_path)
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("Execution result has no artifacts object.")
    manifest_path = Path(str(artifacts["manifest"])).resolve()
    fcpxml_path = Path(str(artifacts["fcpxml"])).resolve()
    autoeditor_path = Path(str(artifacts["autoeditor"])).resolve()
    manifest = _read_json(manifest_path)
    raw_xml = fcpxml_path.read_text(encoding="utf-8-sig")
    try:
        xml_a2_rows = _fcpxml_a2_rows(raw_xml)
        xml_a2_error: str | None = None
    except (ET.ParseError, OSError, TypeError, ValueError) as exc:
        xml_a2_rows = []
        xml_a2_error = str(exc)
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, evidence: Any) -> None:
        checks.append(
            {
                "name": name,
                "status": "pass" if bool(condition) else "fail",
                "evidence": evidence,
            }
        )

    check(
        "execution_is_offline_zero_llm_and_under_600_seconds",
        result.get("status") == "pass"
        and result.get("workflow_id") == WORKFLOW_ID
        and result.get("zero_llm") is True
        and float(result.get("wall_clock_limit_seconds") or 0) == 600
        and 0 < float(result.get("elapsed_seconds") or 0) <= 600
        and result.get("resolve_mutations") == 0
        and result.get("resolve_dry_run_ready") is True
        and result.get("deployment_ready") is False,
        {
            "status": result.get("status"),
            "workflow_id": result.get("workflow_id"),
            "zero_llm": result.get("zero_llm"),
            "wall_clock_limit_seconds": result.get("wall_clock_limit_seconds"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "resolve_mutations": result.get("resolve_mutations"),
            "resolve_dry_run_ready": result.get("resolve_dry_run_ready"),
            "deployment_ready": result.get("deployment_ready"),
        },
    )

    fcpxml_sha = _sha256(fcpxml_path)
    manifest_sha = _sha256(manifest_path)
    check(
        "artifact_hashes_are_receipt_bound",
        fcpxml_sha == str(result.get("fcpxml_sha256") or "").upper()
        == str(manifest.get("fcpxml_sha256") or "").upper()
        and manifest_sha == str(result.get("manifest_sha256") or "").upper(),
        {
            "fcpxml": str(fcpxml_path),
            "fcpxml_sha256": fcpxml_sha,
            "manifest": str(manifest_path),
            "manifest_sha256": manifest_sha,
        },
    )

    geometry_audit = manifest["geometry_plan"]["structural_audit"]
    xml_audit = manifest["structural_audit"]
    geometry_names = {
        row["name"] for row in geometry_audit.get("checks") or [] if row.get("status") == "pass"
    }
    xml_names = {
        row["name"] for row in xml_audit.get("checks") or [] if row.get("status") == "pass"
    }
    check(
        "internal_deterministic_audits_are_complete",
        manifest.get("deterministic") is True
        and manifest.get("zero_llm") is True
        and manifest.get("llm_steps") == 0
        and manifest["geometry_plan"].get("deterministic") is True
        and manifest["geometry_plan"].get("llm_steps") == 0
        and geometry_audit.get("status") == "pass"
        and geometry_audit.get("check_count") == geometry_audit.get("passed_count") == 7
        and geometry_names == EXPECTED_GEOMETRY_CHECKS
        and xml_audit.get("status") == "pass"
        and xml_audit.get("check_count") == xml_audit.get("passed_count") == 11
        and xml_names == EXPECTED_FCPXML_CHECKS
        and manifest["a2_contract_audit"].get("status") == "pass",
        {
            "geometry_checks": sorted(geometry_names),
            "fcpxml_checks": sorted(xml_names),
            "a2_contract_status": manifest["a2_contract_audit"].get("status"),
        },
    )

    timeline = manifest["timeline"]
    opening = manifest["opening"]
    lineage = manifest["opening_lineage"]
    check(
        "opening_is_approved_4x_gsc_derivative_in_4k60_timeline",
        timeline.get("fps") == 60
        and timeline.get("width") == 3840
        and timeline.get("height") == 2160
        and opening.get("record_range") == [0, 260]
        and opening.get("duration_frames") == 260
        and opening.get("pre_retimed_rate_percent") == 400
        and lineage.get("speed_percent") == 400
        and lineage.get("timeline_frames") == 260
        and _path_key(opening["asset"]["path"]) == _path_key(lineage["derivative"])
        and _path_key(lineage["source"]) != _path_key(lineage["derivative"]),
        {
            "timeline": timeline,
            "opening": opening,
            "opening_lineage": lineage,
        },
    )

    battles = manifest["battles"]
    geometry_battles = manifest["geometry_plan"]["battles"]
    a1 = manifest["a1"]
    a1_placed = a1.get("placed") or []
    geometry_dialogue = manifest["geometry_plan"].get("dialogue_a1") or []
    body_v1 = manifest.get("body_v1") or []
    battle_checks: list[bool] = []
    gap_boundary_checks: list[bool] = []
    retry_boundary_checks: list[bool] = []
    approval_paths: list[str] = []
    identity_last_ordinals: dict[str, int] = {}
    expected_gap_ranges: list[list[int]] = []
    expected_gap_rows: list[dict[str, Any]] = []
    expected_intro_count = 0
    for placed, geometry in zip(battles, geometry_battles):
        start, end = geometry["final_record_range"]
        identity = " ".join(
            str(geometry.get("canonical_identity") or "").casefold().split()
        )
        ordinal = geometry.get("attempt_ordinal")
        ordinal_ok = (
            not isinstance(ordinal, bool)
            and isinstance(ordinal, int)
            and ordinal >= 1
        )
        prior_ordinal = identity_last_ordinals.get(identity)
        ordinal_ok = ordinal_ok and (
            prior_ordinal is None or int(ordinal) > prior_ordinal
        )
        if ordinal_ok:
            identity_last_ordinals[identity] = int(ordinal)
        role = geometry["role"]
        expected_gap = ordinal_ok and int(ordinal) == 1
        expected_intro = role in {"leader", "rival"} and expected_gap
        expected_intro_count += int(expected_intro)
        intro = placed.get("intro_asset")
        intro_range = placed.get("intro_range")
        gap_range = geometry.get("gap_range")
        gap_geometry_ok = (
            isinstance(gap_range, list)
            and len(gap_range) == 2
            and int(gap_range[1]) == int(start)
            and int(gap_range[1]) - int(gap_range[0]) == BATTLE_GAP_FRAMES
            if expected_gap
            else gap_range is None
        )
        battle_checks.append(
            placed.get("battle_id") == geometry.get("battle_id")
            and placed.get("record_range") == [start, end]
            and identity != ""
            and ordinal_ok
            and " ".join(
                str(placed.get("canonical_identity") or "").casefold().split()
            ) == identity
            and placed.get("attempt_ordinal") == ordinal
            and placed.get("a1_gap_eligible") is expected_gap
            and geometry.get("a1_gap_eligible") is expected_gap
            and gap_geometry_ok
            and end > start
            and placed.get("intro_eligible") is expected_intro
            and geometry.get("intro_eligible") is expected_intro
            and (
                (
                    intro_range == [start - BATTLE_INTRO_FRAMES, start]
                    and isinstance(intro, dict)
                    and intro.get("duration_frames") == BATTLE_INTRO_FRAMES
                    and intro.get("video_fps") == 60
                )
                if expected_intro
                else intro_range is None and intro is None
            )
        )
        expected_bridge_label = f"battle-gap-v1-bridge:{geometry.get('battle_id')}"
        if expected_gap and isinstance(gap_range, list) and len(gap_range) == 2:
            gap_start, gap_end = [int(value) for value in gap_range]
            expected_gap_ranges.append([gap_start, gap_end])
            expected_gap_rows.append(
                {
                    "battle_id": geometry.get("battle_id"),
                    "start_frame": gap_start,
                    "end_frame": gap_end,
                    "duration_frames": BATTLE_GAP_FRAMES,
                }
            )
            left_a1 = [
                row for row in a1_placed if int(row["record_range"][1]) == gap_start
            ]
            right_a1 = [
                row for row in a1_placed if int(row["record_range"][0]) == gap_end
            ]
            bridges = [
                row
                for row in body_v1
                if row.get("label") == expected_bridge_label
                and row.get("record_range") == [gap_start, gap_end]
                and int(row["source_range"][1]) - int(row["source_range"][0])
                == BATTLE_GAP_FRAMES
            ]
            gap_boundary_checks.append(
                len(left_a1) == len(right_a1) == len(bridges) == 1
                and all(
                    max(int(row["record_range"][0]), gap_start)
                    >= min(int(row["record_range"][1]), gap_end)
                    for row in a1_placed
                )
            )
        elif ordinal_ok:
            left_a1 = [
                row for row in a1_placed if int(row["record_range"][1]) == int(start)
            ]
            right_a1 = [
                row for row in a1_placed if int(row["record_range"][0]) == int(start)
            ]
            retry_boundary_checks.append(
                len(left_a1) == len(right_a1) == 1
                and not any(
                    row.get("label") == expected_bridge_label for row in body_v1
                )
            )
        if isinstance(intro, dict):
            approval_paths.append(_path_key(intro["path"]))
    observed_a1_gaps: list[list[int]] = []
    dialogue_cursor = int(opening["record_range"][1])
    for row in sorted(a1_placed, key=lambda item: item["record_range"]):
        record_start, record_end = [int(value) for value in row["record_range"]]
        if record_start > dialogue_cursor:
            observed_a1_gaps.append([dialogue_cursor, record_start])
        dialogue_cursor = record_end
    main_program_end = int(manifest["carousel"]["v1_record_range"][1])
    if dialogue_cursor < main_program_end:
        observed_a1_gaps.append([dialogue_cursor, main_program_end])
    manifest_gap_rows = list(a1.get("battle_gaps") or [])
    exact_gap_count = len(expected_gap_ranges)
    placed_a1_frames = sum(
        int(row["record_range"][1]) - int(row["record_range"][0])
        for row in a1_placed
    )
    geometry_a1_frames = sum(
        int(row["record_range"][1]) - int(row["record_range"][0])
        for row in geometry_dialogue
    )
    retained_a1_frames = int(
        manifest["geometry_plan"]["input"]["retained_record_duration_frames"]
    )
    a1_signatures_match = [
        (row.get("record_range"), row.get("source_range"), row.get("label"))
        for row in a1_placed
    ] == [
        (row.get("record_range"), row.get("source_range"), row.get("label"))
        for row in geometry_dialogue
    ]
    check(
        "physical_attempts_keep_ranges_with_ordinal1_gaps_and_intros",
        len(battles)
        == len(geometry_battles)
        == int(result["retained_physical_attempt_count"])
        and int(result["exact_a1_gap_count"]) == exact_gap_count
        and int(result["canonical_physical_attempt_count"])
        == int(result["video_recovery_binding"]["resolved_attempt_count"])
        and int(result["canonical_physical_attempt_count"])
        >= int(result["retained_physical_attempt_count"])
        and all(battle_checks)
        and all(gap_boundary_checks)
        and all(retry_boundary_checks)
        and observed_a1_gaps == expected_gap_ranges
        and manifest_gap_rows == expected_gap_rows
        and len(approval_paths) == int(result["major_intro_count"])
        == expected_intro_count
        and a1.get("gap_policy") == BATTLE_GAP_POLICY
        and a1.get("gap_inserts_timeline_frames")
        is BATTLE_GAP_INSERTS_TIMELINE_FRAMES
        and a1.get("gap_duplicates_v1_preroll")
        is BATTLE_GAP_DUPLICATES_V1_PREROLL
        and a1.get("a1_removed_frames") == 0
        and a1.get("inserted_gap_total_frames")
        == BATTLE_GAP_FRAMES * exact_gap_count
        and a1.get("input_clip_count") == a1.get("placed_clip_count")
        == len(a1_placed)
        == len(geometry_dialogue)
        == int(manifest["geometry_plan"]["input"]["retained_interval_count"])
        and placed_a1_frames == geometry_a1_frames == retained_a1_frames
        and a1_signatures_match
        and manifest["geometry_plan"]["contract"].get("boundary_policy")
        == EXPECTED_BOUNDARY_POLICY,
        {
            "canonical_physical_attempt_count": result["canonical_physical_attempt_count"],
            "retained_physical_attempt_count": result["retained_physical_attempt_count"],
            "exact_a1_gap_count": result["exact_a1_gap_count"],
            "major_intro_count": result["major_intro_count"],
            "gap_policy": a1.get("gap_policy"),
            "gap_inserts_timeline_frames": a1.get("gap_inserts_timeline_frames"),
            "gap_duplicates_v1_preroll": a1.get("gap_duplicates_v1_preroll"),
            "a1_removed_frames": a1.get("a1_removed_frames"),
            "inserted_gap_total_frames": a1.get("inserted_gap_total_frames"),
            "placed_a1_frames": placed_a1_frames,
            "retained_a1_frames": retained_a1_frames,
            "expected_ordinal1_gap_count": exact_gap_count,
            "expected_gap_ranges": expected_gap_ranges,
            "observed_a1_gaps": observed_a1_gaps,
            "all_gap_boundaries_lossless": all(gap_boundary_checks),
            "all_retry_boundaries_contiguous": all(retry_boundary_checks),
            "boundary_policy": manifest["geometry_plan"]["contract"].get("boundary_policy"),
        },
    )

    approvals = manifest["battle_intro_approvals"]
    approved_paths: list[str] = []
    approvals_ok = True
    for approval in approvals:
        technical = approval.get("technical_contract") or {}
        approved_paths.append(_path_key(approval["master_path"]))
        approvals_ok = approvals_ok and (
            approval.get("schema") == "gsc_gym_intro_master_approval_v1"
            and approval.get("status") == "pass"
            and technical.get("container") == "MOV"
            and technical.get("codec") == "Apple ProRes 4444"
            and technical.get("alpha") == "straight"
            and technical.get("width") == 3840
            and technical.get("height") == 2160
            and technical.get("fps") == 60
            and technical.get("frames") == BATTLE_INTRO_FRAMES
            and technical.get("audio") == "none"
            and len(str(approval.get("master_sha256") or "")) == 64
            and len(str(approval.get("library_manifest_sha256") or "")) == 64
        )
    check(
        "intro_assets_are_manifest_approved_silent_300f_masters",
        approvals_ok
        and len(approvals) == int(result["major_intro_count"])
        and Counter(approved_paths) == Counter(approval_paths),
        {
            "approval_count": len(approvals),
            "placed_intro_count": len(approval_paths),
            "library_manifest_sha256_values": sorted(
                {str(row.get("library_manifest_sha256")) for row in approvals}
            ),
        },
    )

    segments = manifest["a2"]["segments"]
    cursor = 0
    contiguous = True
    for segment in segments:
        start, end = segment["record_range"]
        contiguous = contiguous and start == cursor and end > start
        cursor = end
    reservations = manifest["audio_reservations"]
    battle_root = Path(str(reservations["battle_library_root"])).resolve()
    dual_key = _path_key(reservations["dual_screen_lovelife"])
    golden_key = _path_key(reservations["golden_goose_blocked_from_a2"])
    dual_rows = [row for row in segments if _path_key(_origin(row)) == dual_key]
    golden_rows = [
        row
        for row in segments
        if _path_key(_origin(row)) == golden_key
        or _origin(row).name.casefold() == OUTRO_TRACK.casefold()
    ]
    battle_audio_ok = all(
        _path_key(_origin(row).parent) == _path_key(battle_root)
        for row in segments
        if row["role"] == "battle"
    )
    battle_coverage_ok = True
    for battle in battles:
        assigned = [row for row in segments if row.get("battle_id") == battle["battle_id"]]
        assigned.sort(key=lambda row: row["record_range"])
        if not assigned:
            battle_coverage_ok = False
            continue
        battle_cursor = battle["record_range"][0]
        for row in assigned:
            battle_coverage_ok = battle_coverage_ok and row["record_range"][0] == battle_cursor
            battle_cursor = row["record_range"][1]
        battle_coverage_ok = battle_coverage_ok and battle_cursor == battle["record_range"][1]
        battle_coverage_ok = battle_coverage_ok and (
            int(assigned[0]["source_range"][0])
            == int(assigned[0]["asset"]["source_start_frame"])
        )
        battle_coverage_ok = battle_coverage_ok and assigned[0]["fade_in_frames"] == 30
        battle_coverage_ok = battle_coverage_ok and assigned[-1]["fade_out_frames"] == 30

    source_rows = manifest.get("a2_original_source_clips")
    source_contract = manifest.get("a2_contract_audit")
    source_native_ok = (
        "a2_fade_derivatives" not in manifest
        and isinstance(source_rows, list)
        and len(source_rows) == len(segments)
        and isinstance(source_contract, dict)
        and source_contract.get("schema") == SOURCE_A2_SCHEMA
        and source_contract.get("status") == "pass"
        and source_contract.get("original_source_clip_count") == len(segments)
        and source_contract.get("materialized_derivative_count") == 0
        and source_contract.get("derived_media_allowed") is False
        and source_contract.get("renamed_media_allowed") is False
        and source_contract.get("source_trim_handles_editable") is True
        and source_contract.get("source_clips") == source_rows
        and manifest["a2"].get("source_contract")
        == "original_library_media_v1"
        and manifest["a2"].get("derived_media_allowed") is False
        and manifest["a2"].get("renamed_timeline_clips_allowed") is False
        and manifest["a2"].get("source_trim_handles_editable") is True
    )
    source_evidence: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {}
    for index, segment in enumerate(segments):
        source_row = (
            source_rows[index]
            if isinstance(source_rows, list) and index < len(source_rows)
            else None
        )
        asset = segment.get("asset") if isinstance(segment, dict) else None
        asset = asset if isinstance(asset, dict) else {}
        source_path = Path(str(asset.get("path") or "")).resolve()
        origin_path = Path(str(asset.get("origin_path") or "")).resolve()
        actual_sha: str | None = None
        try:
            source_key = _path_key(source_path)
            actual_sha = source_hashes.get(source_key)
            if actual_sha is None and source_path.is_file():
                actual_sha = _sha256(source_path)
                source_hashes[source_key] = actual_sha
            source_start, source_end = [int(value) for value in segment["source_range"]]
            media_start = int(asset["source_start_frame"])
            media_duration = int(asset["duration_frames"])
            media_end = media_start + media_duration
            handles = {
                "left": source_start - media_start,
                "right": media_end - source_end,
            }
            gain = float(segment["gain_db"])
            expected_gain = float(DEFAULT_GAINS_DB[segment["role"]])
        except (KeyError, OSError, TypeError, ValueError):
            source_native_ok = False
            source_start = source_end = media_start = media_duration = media_end = -1
            handles = {"left": -1, "right": -1}
            gain = expected_gain = float("nan")
        row_ok = bool(
            isinstance(source_row, dict)
            and actual_sha is not None
            and source_path.is_file()
            and _path_key(source_path) == _path_key(origin_path)
            and source_path.suffix.casefold() == ".mp3"
            and not any(
                part.casefold() == "a2-fades" for part in source_path.parts
            )
            and asset.get("name") == source_path.name
            and "baked_gain_db" not in segment
            and "timeline_gain_db" not in segment
            and segment.get("media_source_range") == [media_start, media_end]
            and segment.get("available_handle_frames") == handles
            and handles["left"] >= 0
            and handles["right"] >= 0
            and segment.get("source_trim_handles_editable") is True
            and segment.get("derived_media") is False
            and segment.get("gain_policy")
            == "editable_timeline_adjust_volume_not_baked"
            and segment.get("fade_policy")
            == "editable_timeline_metadata_not_baked"
            and math.isfinite(gain)
            and gain == expected_gain
            and source_row.get("schema") == SOURCE_CLIP_SCHEMA
            and _path_key(str(source_row.get("source_path") or ""))
            == _path_key(source_path)
            and source_row.get("source_name") == source_path.name
            and str(source_row.get("source_sha256") or "").upper() == actual_sha
            and source_row.get("record_range") == segment.get("record_range")
            and source_row.get("source_range") == segment.get("source_range")
            and source_row.get("media_source_start_frame") == media_start
            and source_row.get("media_duration_frames") == media_duration
            and source_row.get("media_source_end_frame") == media_end
            and source_row.get("available_handle_frames") == handles
            and source_row.get("source_trim_handles_editable") is True
            and source_row.get("derived_media") is False
            and source_row.get("role") == segment.get("role")
            and source_row.get("battle_id") == segment.get("battle_id")
            and source_row.get("label") == segment.get("label")
            and source_row.get("gain_db") == segment.get("gain_db")
            and source_row.get("gain_policy")
            == "editable_timeline_adjust_volume_not_baked"
            and source_row.get("fade_in_frames")
            == segment.get("fade_in_frames")
            and source_row.get("fade_out_frames")
            == segment.get("fade_out_frames")
            and source_row.get("fade_policy")
            == "editable_timeline_metadata_not_baked"
        )
        source_native_ok = source_native_ok and row_ok
        source_evidence.append(
            {
                "source": str(source_path),
                "source_name": source_path.name,
                "source_exists": source_path.is_file(),
                "source_sha256": actual_sha,
                "source_range": [source_start, source_end],
                "media_source_range": [media_start, media_end],
                "available_handle_frames": handles,
                "status": "pass" if row_ok else "fail",
            }
        )
    xml_source_native_ok = len(xml_a2_rows) == len(segments) and all(
        xml_row.get("record_range") == segment.get("record_range")
        and xml_row.get("source_range") == segment.get("source_range")
        and _path_key(str(xml_row.get("source_path") or ""))
        == _path_key(str(segment["asset"]["path"]))
        == _path_key(str(segment["asset"]["origin_path"]))
        and xml_row.get("timeline_name") == segment["asset"].get("name")
        and xml_row.get("resource_name") == segment["asset"].get("name")
        and xml_row.get("media_source_range")
        == segment.get("media_source_range")
        and float(xml_row.get("gain_db")) == float(segment.get("gain_db"))
        and Path(str(xml_row.get("source_path") or "")).suffix.casefold()
        == ".mp3"
        and not any(
            part.casefold() == "a2-fades"
            for part in Path(str(xml_row.get("source_path") or "")).parts
        )
        for xml_row, segment in zip(xml_a2_rows, segments)
    )
    check(
        "a2_is_contiguous_original_source_editable_and_reserved",
        contiguous
        and cursor == manifest["a2"]["complete_range"][1]
        == manifest["carousel"]["v1_record_range"][1]
        == manifest["outro"]["record_range"][0]
        and segments[0]["record_range"][0] == 0
        and segments[0]["source_range"][0] == 764
        and segments[0]["role"] == "opening"
        and _path_key(_origin(segments[0])) == dual_key
        and bool(dual_rows)
        and not golden_rows
        and reservations.get("golden_goose_owned_by_linked_outro_audio") is True
        and battle_audio_ok
        and battle_coverage_ok
        and source_native_ok
        and xml_source_native_ok,
        {
            "complete_range": manifest["a2"]["complete_range"],
            "segment_count": len(segments),
            "battle_segment_count": sum(row["role"] == "battle" for row in segments),
            "original_source_clip_count": (
                len(source_rows) if isinstance(source_rows, list) else None
            ),
            "materialized_derivative_count": 0,
            "forbidden_a2_fade_derivatives_key_present": (
                "a2_fade_derivatives" in manifest
            ),
            "dual_screen_role_values": sorted({row["role"] for row in dual_rows}),
            "golden_goose_a2_count": len(golden_rows),
            "battle_library_root": str(battle_root),
            "source_evidence": source_evidence,
            "fcpxml_a2_error": xml_a2_error,
            "fcpxml_a2_rows": xml_a2_rows,
        },
    )

    general_occurrences = _general_bgm_occurrences(segments)
    occurrence_counts = Counter(_path_key(row["source"]) for row in general_occurrences)
    dual_occurrences = [
        row for row in general_occurrences if _path_key(row["source"]) == dual_key
    ]
    ordered_battles = sorted(battles, key=lambda row: row["record_range"])
    final_battle_end = int(ordered_battles[-1]["record_range"][1])
    a2_end = int(manifest["a2"]["complete_range"][1])
    post_final_occurrences = [
        row
        for row in general_occurrences
        if int(row["record_range"][0]) >= final_battle_end
    ]
    required_paths = [
        Path(str(path)).resolve()
        for path in reservations.get("post_final_required_tracks") or []
    ]
    required_keys = {_path_key(path) for path in required_paths}
    required_names_ok = (
        len(required_paths) == len(POST_FINAL_REQUIRED_TRACKS) == 3
        and [path.name.casefold() for path in required_paths]
        == [name.casefold() for name in POST_FINAL_REQUIRED_TRACKS]
        and _path_key(required_paths[0]) == dual_key
    )
    fourth_key = (
        _path_key(post_final_occurrences[3]["source"])
        if len(post_final_occurrences) == 4
        else None
    )
    before_final_keys = {
        _path_key(row["source"])
        for row in general_occurrences
        if int(row["record_range"][0]) < final_battle_end
    }
    post_final_ok = bool(
        required_names_ok
        and len(post_final_occurrences) == 4
        and [_path_key(row["source"]) for row in post_final_occurrences[:3]]
        == [_path_key(path) for path in required_paths]
        and post_final_occurrences[0]["record_range"][0] == final_battle_end
        and all(
            left["record_range"][1] == right["record_range"][0]
            for left, right in zip(post_final_occurrences, post_final_occurrences[1:])
        )
        and all(row["source_range"][0] == 0 for row in post_final_occurrences)
        and post_final_occurrences[3]["record_range"][1] == a2_end
        and fourth_key is not None
        and fourth_key not in required_keys
        and fourth_key != golden_key
        and fourth_key not in before_final_keys
        and post_final_occurrences[3]["filename"].casefold()
        not in {name.casefold() for name in (*POST_FINAL_REQUIRED_TRACKS, OUTRO_TRACK)}
    )

    handoffs_ok = len(ordered_battles) > 0
    expected_handoffs: list[dict[str, Any]] = []
    occurrence_starts = {
        int(row["record_range"][0]): row for row in general_occurrences
    }
    for index, battle in enumerate(ordered_battles):
        battle_end = int(battle["record_range"][1])
        next_boundary = (
            int(ordered_battles[index + 1]["record_range"][0])
            if index + 1 < len(ordered_battles)
            else a2_end
        )
        segment_index = next(
            (
                row_index
                for row_index, row in enumerate(segments)
                if int(row["record_range"][0]) == battle_end
            ),
            None,
        )
        direct = next_boundary == battle_end
        boundary_segment = None if segment_index is None else segments[segment_index]
        if direct:
            next_battle_id = ordered_battles[index + 1]["battle_id"]
            row_ok = bool(
                boundary_segment is not None
                and boundary_segment.get("role") == "battle"
                and boundary_segment.get("battle_id") == next_battle_id
                and int(boundary_segment["source_range"][0])
                == int(boundary_segment["asset"]["source_start_frame"])
            )
            source: str | None = None
            source_start: int | None = None
            mode = "direct_battle_handoff"
        else:
            occurrence = occurrence_starts.get(battle_end)
            row_ok = bool(
                boundary_segment is not None
                and boundary_segment.get("role") != "battle"
                and occurrence is not None
                and int(boundary_segment["source_range"][0]) == 0
                and int(occurrence["source_range"][0]) == 0
            )
            source = None if occurrence is None else str(occurrence["source"])
            source_start = None if occurrence is None else int(occurrence["source_range"][0])
            mode = "fresh_source_zero_nonbattle"
        handoffs_ok = handoffs_ok and row_ok
        expected_handoffs.append(
            {
                "battle_id": battle["battle_id"],
                "battle_end_frame": battle_end,
                "next_boundary_frame": next_boundary,
                "mode": mode,
                "source": source,
                "source_start_frame": source_start,
            }
        )

    seed = str(manifest["source_binding"]["seed_sha256"])
    contract = manifest.get("nonbattle_bgm_contract") or {}
    reported_handoffs = list(contract.get("post_battle_handoffs") or [])

    def _project_handoff(row: dict[str, Any]) -> dict[str, Any]:
        source = row.get("source")
        return {
            "battle_id": row.get("battle_id"),
            "battle_end_frame": row.get("battle_end_frame"),
            "next_boundary_frame": row.get("next_boundary_frame"),
            "mode": row.get("mode"),
            "source": None if source is None else _path_key(str(source)),
            "source_start_frame": row.get("source_start_frame"),
        }

    contract_metadata_ok = bool(
        contract.get("schema") == "gsc_gym_nonbattle_bgm_contract_v2"
        and contract.get("status") == "pass"
        and contract.get("selection_seed") == seed.upper()
        and contract.get("random_without_replacement") is True
        and contract.get("only_repeat_exception") == INTRO_TRACK
        and contract.get("post_final_allocation_policy")
        == "fair_share_required_three_plus_exact_next_unused_random;extend_required_"
        "in_reverse_order_to_fit_fourth_natural_duration"
        and contract.get("post_final_exact_identity_count") == 4
        and contract.get("post_final_fourth_identity_policy")
        == "exact_next_unused_seeded_random_asset_finishes_A2"
        and contract.get("post_final_required_filenames")
        == list(POST_FINAL_REQUIRED_TRACKS)
        and _project_occurrences(list(contract.get("post_final_occurrences") or []))
        == _project_occurrences(post_final_occurrences)
        and [_project_handoff(row) for row in reported_handoffs]
        == [_project_handoff(row) for row in expected_handoffs]
    )
    nondual_nonrepeat_ok = all(
        count == 1
        for key, count in occurrence_counts.items()
        if key != dual_key
    )
    exact_dual_ok = bool(
        len(dual_occurrences) == 2
        and len(
            [
                row
                for row in general_occurrences
                if row["filename"].casefold() == INTRO_TRACK.casefold()
            ]
        )
        == 2
        and [row["record_range"][0] for row in dual_occurrences]
        == [0, final_battle_end]
        and dual_occurrences[0]["source_range"][0] == 764
        and dual_occurrences[1]["source_range"][0] == 0
    )
    check(
        "nonbattle_bgm_original_sources_fresh_nonrepeating_and_exact_post_final",
        source_native_ok
        and exact_dual_ok
        and nondual_nonrepeat_ok
        and handoffs_ok
        and post_final_ok
        and contract_metadata_ok
        and not golden_rows,
        {
            "identity_occurrences": general_occurrences,
            "identity_start_counts": dict(sorted(occurrence_counts.items())),
            "dual_screen_occurrence_starts": [
                row["record_range"][0] for row in dual_occurrences
            ],
            "final_battle_end_frame": final_battle_end,
            "post_final_occurrences": post_final_occurrences,
            "post_battle_handoffs": expected_handoffs,
            "reported_contract": contract,
            "golden_goose_a2_count": len(golden_rows),
        },
    )

    bgm_dir = Path(str(reservations["dual_screen_lovelife"])).resolve().parent
    expected_nonbattle = choose_nonbattle_tracks(bgm_dir, seed=seed)
    actual_nonbattle = [
        Path(str(row["source"]))
        for row in general_occurrences
        if _path_key(row["source"]) not in required_keys
    ]
    assignment_check = next(
        row
        for row in xml_audit["checks"]
        if row["name"] == "structured_a2_battle_ids_exact_fades_and_shuffle_assignments"
    )
    assignment_evidence = assignment_check["evidence"]
    library_paths = [battle_root / name for name in assignment_evidence["library_filenames"]]
    expected_battle = choose_battle_tracks(
        library_paths,
        count=len(assignment_evidence["assignments"]),
        seed=seed,
    )
    actual_battle = [Path(row["source_path"]) for row in assignment_evidence["assignments"]]
    physical_attempt_restarts = all(
        int(row.get("initial_source_frame", -1))
        == int(row.get("asset_source_start_frame", -2))
        for row in assignment_evidence["assignments"]
    )
    check(
        "source_bound_random_music_decks_recompute_exactly",
        [_path_key(path) for path in actual_nonbattle]
        == [_path_key(path) for path in expected_nonbattle[: len(actual_nonbattle)]]
        and [_path_key(path) for path in actual_battle]
        == [_path_key(path) for path in expected_battle]
        and assignment_evidence.get("assignment_seed") == seed.upper()
        and assignment_evidence.get("assignment_policy")
        == "deterministic_shuffle_bag_no_immediate_repeat"
        and assignment_evidence.get("complete_bags") is True
        and physical_attempt_restarts
        and not any(
            _path_key(left) == _path_key(right)
            for left, right in zip(actual_battle, actual_battle[1:])
        ),
        {
            "seed_sha256": seed,
            "randomized_nonbattle_identity_starts": [
                path.name for path in actual_nonbattle
            ],
            "expected_nonbattle_prefix": [
                path.name for path in expected_nonbattle[: len(actual_nonbattle)]
            ],
            "battle_assignments": [path.name for path in actual_battle],
            "battle_library": [path.name for path in library_paths],
            "physical_attempt_bgm_restarts": physical_attempt_restarts,
        },
    )

    carousel = manifest["carousel"]
    slices = carousel["v2_slices"]
    carousel_cursor = carousel["v1_record_range"][0]
    slices_contiguous = True
    for row in slices:
        slices_contiguous = (
            slices_contiguous and row["record_range"][0] == carousel_cursor
        )
        carousel_cursor = row["record_range"][1]
    carousel_check = next(
        row for row in xml_audit["checks"] if row["name"] == "source_backed_member_carousel"
    )
    carousel_boundary = manifest["carousel_boundary"]
    expected_source_ok = (
        expected_carousel_source_frame is None
        or carousel_boundary.get("source_frame") == expected_carousel_source_frame
    )
    check(
        "member_carousel_is_source_bound_and_crop_530",
        expected_source_ok
        and carousel_boundary.get("status") == "pass"
        and carousel.get("v1_continuous_source_backed_clip_count") == 1
        and len(slices) == carousel.get("v2_slice_count")
        == int(result["carousel_v2_slice_count"])
        and bool(slices)
        and slices_contiguous
        and carousel_cursor == carousel["v1_record_range"][1]
        and carousel_check.get("status") == "pass"
        and carousel_check["evidence"].get("crop_bottom_pixels") == 530,
        {
            "raw_source_frame": carousel_boundary.get("source_frame"),
            "candidate_source_frames": carousel_boundary.get("candidate_source_frames"),
            "v1_record_range": carousel["v1_record_range"],
            "v2_slice_count": len(slices),
            "crop_bottom_pixels": carousel_check["evidence"].get("crop_bottom_pixels"),
        },
    )

    outro = manifest["outro"]
    check(
        "outro_is_link_evidenced_gsc_mov_on_v1_a3",
        outro.get("record_range")[0] == carousel["v1_record_range"][1]
        and outro.get("record_range")[1] > outro.get("record_range")[0]
        and outro.get("video_track") == "V1"
        and outro.get("audio_track") == "A3"
        and outro.get("linked_same_source_uri") is True
        and outro.get("standalone_golden_goose_clip") is False
        and Path(outro["asset"]["path"]).suffix.casefold() == ".mov",
        {
            "record_range": outro.get("record_range"),
            "asset": outro.get("asset"),
            "video_track": outro.get("video_track"),
            "audio_track": outro.get("audio_track"),
            "linked_same_source_uri": outro.get("linked_same_source_uri"),
            "standalone_golden_goose_clip": outro.get("standalone_golden_goose_clip"),
            "live_link_state_pending_receipt_bound_resolve_validation": True,
        },
    )

    root = ET.fromstring(raw_xml)
    formats = {
        row.get("id"): row
        for row in list(next(item for item in list(root) if item.tag.endswith("resources")))
        if row.tag.endswith("format")
    }
    sequences = [row for row in root.iter() if row.tag.endswith("sequence")]
    sequence_format = formats.get(sequences[0].get("format")) if len(sequences) == 1 else None
    check(
        "fcpxml_root_is_one_4k60_sequence",
        root.get("version") == "1.10"
        and len(sequences) == 1
        and sequence_format is not None
        and sequence_format.get("frameDuration") == "1/60s"
        and sequence_format.get("width") == "3840"
        and sequence_format.get("height") == "2160",
        {
            "fcpxml_version": root.get("version"),
            "sequence_count": len(sequences),
            "format": None if sequence_format is None else dict(sequence_format.attrib),
        },
    )

    repair = manifest["auto_editor_asset_duration_repair"]
    retained = parse_autoeditor_fcpxml(autoeditor_path.read_text(encoding="utf-8-sig"))
    source_frames = int(result["source_contract"]["dialogue_stream"]["timeline_frames_at_60fps"])
    check(
        "auto_editor_duration_is_raise_only_and_full_source_bound",
        repair.get("policy_id")
        == "v2:raise-only-to-max-asset-clip-source-end-and-probed-full-source-duration-"
        "before-parse-and-atomic-promotion"
        and repair.get("changed") is True
        and repair.get("repaired_asset_count") == 1
        and ".tmp-" not in json.dumps(repair)
        and retained.source_duration_frames == source_frames
        and str(repair.get("output_sha256") or "").upper() == _sha256(autoeditor_path)
        and repair["source_duration_binding"].get("duration_frames") == source_frames
        and result["source_contract"].get("dialogue_audio_ordinal") == 5,
        {
            "dialogue_audio_ordinal": result["source_contract"].get("dialogue_audio_ordinal"),
            "source_duration_frames": source_frames,
            "parsed_autoeditor_source_duration_frames": retained.source_duration_frames,
            "repair_policy_id": repair.get("policy_id"),
            "repair_output_sha256": repair.get("output_sha256"),
        },
    )

    config = _read_json(config_path.resolve())
    workflow = next(
        row for row in config.get("workflows") or [] if row.get("id") == WORKFLOW_ID
    )
    workflow_ok = True
    try:
        if not isinstance(workflow, dict):
            raise ValueError("registered workflow missing")
        validate_zero_llm_workflow(workflow)
    except (ValueError, TypeError, KeyError, RuntimeError):
        workflow_ok = False
    surge = audit_surge_reference(
        contract_path=reference_contract_path,
        workflow_config_path=config_path,
    )
    check(
        "registered_single_step_and_surge_reference_contract_pass",
        workflow_ok
        and surge.get("status") == "pass"
        and surge.get("deployment_ready") is True
        and len(surge.get("checks") or {}) == 17
        and all((surge.get("checks") or {}).values())
        and not surge.get("failed_checks"),
        {
            "workflow_validation": "pass" if workflow_ok else "fail",
            "surge_status": surge.get("status"),
            "surge_check_count": len(surge.get("checks") or {}),
            "surge_evidence": surge.get("evidence"),
        },
    )

    failed = [row["name"] for row in checks if row["status"] != "pass"]
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "pass" if not failed else "fail",
        "deployment_ready_for_receipt_bound_resolve_import": not failed,
        "resolve_contacted": False,
        "llm_steps": 0,
        "result": str(result_path),
        "manifest": str(manifest_path),
        "fcpxml": str(fcpxml_path),
        "check_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "failed_checks": failed,
        "checks": checks,
        "offline_limitation": (
            "The linked V1/A3 outro source/range is proven in FCPXML; actual Resolve "
            "link state is intentionally deferred to the receipt-bound live validator."
        ),
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    report["content_sha256"] = hashlib.sha256(canonical).hexdigest().upper()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_DIR / "config" / "orchestrator_workflows.json",
    )
    parser.add_argument(
        "--reference-contract",
        type=Path,
        default=REPO_DIR / "config" / "gsc_gym_leader_reference_contract.json",
    )
    parser.add_argument("--expected-carousel-source-frame", type=int)
    args = parser.parse_args()
    report = audit(
        args.result,
        config_path=args.config,
        reference_contract_path=args.reference_contract,
        expected_carousel_source_frame=args.expected_carousel_source_frame,
    )
    if args.output:
        _atomic_json(args.output.resolve(), report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
