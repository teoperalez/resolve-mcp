from __future__ import annotations

"""Executable audit of the deterministic GSC workflow against Lt. Surge."""

import hashlib
import json
from pathlib import Path
from typing import Any

from .gsc_gym_deterministic import (
    BATTLE_GAP_FRAMES,
    BATTLE_INTRO_FRAMES,
    OPENING_INTRO_DERIVATIVE_FRAMES,
    OPENING_INTRO_SPEED_PCT,
    OPENING_INTRO_SOURCE_FRAMES,
    OPENING_INTRO_TIMELINE_FRAMES,
    WORKFLOW_ID,
    WORKFLOW_BATTLE_GAP_GEOMETRY,
    WORKFLOW_BATTLE_POPULATION_POLICY,
    WORKFLOW_BATTLE_START_CANDIDATE_AUDIT,
    WORKFLOW_PARTY_MEMBER_KO_CONTRACT,
    WORKFLOW_PHYSICAL_ATTEMPT_BGM_START_CONTRACT,
    WORKFLOW_SAME_TRAINER_RETRY_CONTRACT,
)
from .gsc_gym_fcpxml_plan import (
    BATTLE_GAP_DUPLICATES_V1_PREROLL,
    BATTLE_GAP_INSERTS_TIMELINE_FRAMES,
    BATTLE_GAP_POLICY,
)


REFERENCE_AUDIT_SCHEMA = "gsc_gym_leader_surge_reference_audit_v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _named_checks(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("name")): row
        for row in report.get("checks", [])
        if isinstance(row, dict) and row.get("name")
    }


def audit_surge_reference(
    *,
    contract_path: Path,
    workflow_config_path: Path,
) -> dict[str, Any]:
    contract = _read_json(contract_path)
    evidence = contract["evidence"]
    strict = contract["strict_invariants"]
    structural_path = Path(evidence["structural_audit"]["path"])
    bgm_path = Path(evidence["bgm_audit"]["path"])
    drt_path = Path(evidence["post_bgm_drt"]["path"])
    structural = _read_json(structural_path)
    bgm = _read_json(bgm_path)
    workflow_config = _read_json(workflow_config_path)
    workflow = next(
        (row for row in workflow_config.get("workflows", []) if row.get("id") == WORKFLOW_ID),
        None,
    )
    tooling = workflow.get("tooling", {}) if isinstance(workflow, dict) else {}
    structural_checks = _named_checks(structural)
    checks: dict[str, bool] = {}
    evidence_out: dict[str, Any] = {}

    for key, path in (
        ("structural_audit", structural_path),
        ("bgm_audit", bgm_path),
        ("post_bgm_drt", drt_path),
    ):
        expected = str(evidence[key]["sha256"]).upper()
        actual = _sha256(path) if path.is_file() else ""
        checks[f"{key}_fingerprint_exact"] = actual == expected
        evidence_out[f"{key}_sha256"] = actual

    format_row = structural_checks.get("format_4k60", {})
    format_evidence = format_row.get("evidence", {})
    checks["reference_format_4k60"] = (
        format_row.get("status") == "pass"
        and float(format_evidence.get("fps", 0)) == float(strict["fps"])
        and int(format_evidence.get("width", 0)) == int(strict["width"])
        and int(format_evidence.get("height", 0)) == int(strict["height"])
    )

    opening = structural_checks.get("opening_intro_4x", {})
    opening_evidence = opening.get("evidence", {})
    checks["reference_opening_intro_exact"] = (
        opening.get("status") == "pass"
        and str(opening_evidence.get("name", "")).startswith("GSCPC Intro Short__400pct")
        and int(opening_evidence.get("duration", 0)) == int(strict["opening_intro_frames"])
    )

    gaps = structural_checks.get("ten_exact_a1_gaps_with_v1_holds", {}).get("evidence", [])
    checks["reference_a1_gaps_exact"] = (
        len(gaps) == int(strict["major_exact_gap_count_observed"])
        and all(
            int(row["marker_abs"]) - int(row["gap_start_abs"]) == int(strict["battle_gap_frames"])
            and int(row["a1_overlap_frames"]) == 0
            and int(row["v1_missing_frames"]) == 0
            for row in gaps
        )
    )

    intros = structural_checks.get("ten_silent_5s_v2_intros", {}).get("evidence", [])
    checks["reference_v2_intros_exact"] = (
        len(intros) == int(strict["major_intro_count_observed"])
        and all(
            int(row["duration"]) == int(strict["battle_intro_frames"])
            and int(row["end"]) - int(row["start"]) == int(strict["battle_intro_frames"])
            for row in intros
        )
        and all(int(intro["end"]) == int(gap["marker_abs"]) for intro, gap in zip(intros, gaps))
    )

    outro = structural_checks.get("outro_video_audio_sync", {}).get("evidence", {})
    video = outro.get("video", [])
    a3 = (outro.get("a3") or [[]])[0]
    # The structural JSON records matching source names and record ranges, but it
    # does not expose Resolve's link-state metadata.  Treat this as source/range
    # evidence only; the future live validator must prove actual linkage.
    checks["reference_outro_matching_mov_source_and_range_v1_a3"] = (
        len(video) == 3
        and len(a3) == 3
        and video[0] == a3[0] == "GSC Assets outro.mov"
        and video[1:] == a3[1:]
    )

    carousel = structural_checks.get("member_carousel_layout", {}).get("evidence", {})
    crop_values = carousel.get("crop_values", [])
    checks["reference_carousel_geometry"] = (
        int(carousel.get("v1_count", 0)) == 1
        and int(carousel.get("v2_count", 0)) == int(strict["carousel_v2_count_observed"])
        and carousel.get("v2_contiguous") is True
        and bool(crop_values)
        and all(float(value) == float(strict["carousel_v2_crop_bottom"]) for value in crop_values)
    )

    a2 = structural_checks.get("continuous_frame_exact_a2_bed", {}).get("evidence", {})
    checks["reference_a2_continuous_to_outro"] = (
        not a2.get("discontinuities")
        and int(a2.get("end", -1)) == int(a2.get("outro_start", -2))
        and a2.get("source_offsets_ok") is True
        and not a2.get("raw_gameplay_audio")
    )

    expected_tracks = set(strict["battle_bgm_tracks"])
    actual_tracks = {Path(path).name for path in bgm.get("battle_tracks", [])}
    assignments = bgm.get("battle_assignments", [])
    assignment_names = [str(row.get("source_name")) for row in assignments]
    no_repeat = all(a != b for a, b in zip(assignment_names, assignment_names[1:]))
    complete_bags = all(
        set(assignment_names[index:index + len(expected_tracks)]) == expected_tracks
        for index in range(0, len(assignment_names) - len(expected_tracks) + 1, len(expected_tracks))
    )
    checks["reference_battle_bgm_shuffle_contract"] = (
        actual_tracks == expected_tracks
        and bool(assignments)
        and no_repeat
        and complete_bags
        and all(row.get("policy") == "deterministic_shuffle_bag_no_immediate_repeat" for row in assignments)
    )

    bgm_checks = (bgm.get("audit") or {}).get("checks", {})
    checks["reference_latest_bgm_preservation_and_continuity"] = all(
        bgm_checks.get(key) is True
        for key in (
            "all_a1_v1_v2_a3_and_other_non_a2_content_unchanged",
            "markers_unchanged",
            "a2_exact_plan_ranges",
            "a2_continuous",
            "a2_stops_at_outro",
            "all_15_battle_ranges_exact",
            "all_a2_sources_start_at_zero",
        )
    )

    battle_contract = [
        row for row in bgm.get("battle_contract", []) if isinstance(row, dict)
    ]
    intro_battles = [
        row
        for row in battle_contract
        if isinstance(row.get("v2_items_ending_at_start"), list)
        and row.get("v2_items_ending_at_start")
    ]
    # This later post-BGM report is population evidence, not the strict gap
    # authority.  Exact 60-frame geometry is proved above only for the ten major
    # battles in the fingerprinted no-flash structural audit.
    checks["reference_later_population_is_15_ranges_and_10_intro_battles"] = (
        len(battle_contract) == int(strict["later_battle_range_count_observed"])
        and len(intro_battles) == int(strict["later_intro_battle_count_observed"])
        and len(battle_contract) - len(intro_battles)
        == int(strict["later_minor_battle_without_intro_count_observed"])
        and all(int(row.get("end") or 0) > int(row.get("start") or 0) for row in battle_contract)
    )

    known_drift = contract.get("known_manual_drift_to_reject") or {}
    observed_non_strict_gaps = sorted(
        int(row.get("gap_duration") or 0)
        for row in battle_contract
        if int(row.get("gap_duration") or 0) != int(strict["battle_gap_frames"])
    )
    observed_non_strict_intros = sorted(
        int(item.get("duration") or 0)
        for row in intro_battles
        for item in row.get("v2_items_ending_at_start") or []
        if int(item.get("duration") or 0) != int(strict["battle_intro_frames"])
    )
    checks["known_manual_drift_is_fingerprinted_not_accepted"] = (
        observed_non_strict_gaps
        == sorted(int(value) for value in known_drift.get("gap_lengths_frames") or [])
        and observed_non_strict_intros
        == [int(known_drift.get("short_intro_frames") or 0)]
        and BATTLE_GAP_FRAMES not in observed_non_strict_gaps
        and BATTLE_INTRO_FRAMES not in observed_non_strict_intros
    )

    checks["implementation_constants_match_reference"] = (
        OPENING_INTRO_SPEED_PCT == int(strict["opening_intro_speed_pct"])
        and OPENING_INTRO_TIMELINE_FRAMES == int(strict["opening_intro_frames"])
        and OPENING_INTRO_SOURCE_FRAMES == 512
        and OPENING_INTRO_DERIVATIVE_FRAMES == 130
        and BATTLE_INTRO_FRAMES == int(strict["battle_intro_frames"])
        and BATTLE_GAP_FRAMES == int(strict["battle_gap_frames"])
    )
    # Surge remains immutable visual evidence for exact one-second gaps and V1
    # coverage.  Its historical implementation muted time already present in
    # the edit, however, so the current implementation contract is proved from
    # the planner constants and registered workflow rather than inheriting that
    # now-rejected destructive A1 policy.
    gap_geometry = str(tooling.get("battle_a1_gap_geometry") or "").casefold()
    boundary_mapping = str(tooling.get("battle_edit_boundary_mapping") or "").casefold()
    checks["implementation_lossless_inserted_a1_gap_policy"] = (
        BATTLE_GAP_INSERTS_TIMELINE_FRAMES is True
        and BATTLE_GAP_DUPLICATES_V1_PREROLL is True
        and BATTLE_GAP_POLICY
        == (
            "real_60f_timeline_insert_only_for_identity_attempt_ordinal_1_at_"
            "adjacent_autoeditor_a1_boundary_preserve_all_a1_source_frames_"
            "with_incoming_v1_bridge_no_retry_gap"
        )
        and all(
            token in gap_geometry
            for token in (
                "real_60f_timeline_insert",
                "adjacent_autoeditor_a1_boundary",
                "preserve_all_a1_source_frames",
                "source_backed_v1_bridge",
                "identity_attempt_ordinal_1",
                "no_gap_before_same_trainer_retries",
            )
        )
        and "zero_inserted_timeline_frames" not in gap_geometry
        and "adjacent_join" in boundary_mapping
        and "no_midclip_split" in boundary_mapping
        and "exact_split" not in boundary_mapping
    )
    checks["workflow_is_zero_llm_and_encodes_geometry"] = (
        isinstance(workflow, dict)
        and workflow.get("llm_tasks") == []
        and workflow.get("review_surfaces") == []
        and int(tooling.get("runtime_limit_seconds", 0)) == 600
        and int(tooling.get("opening_intro_speed_pct", 0)) == int(strict["opening_intro_speed_pct"])
        and int(tooling.get("battle_intro_duration_frames", 0)) == int(strict["battle_intro_frames"])
        and int(tooling.get("battle_a1_gap_frames", 0)) == int(strict["battle_gap_frames"])
        and tooling.get("battle_intro_track") == "V2_over_continuous_V1"
        and tooling.get("a2_continuity") == "frame_exact_timeline_start_to_outro_start"
        and tooling.get("battle_population") == WORKFLOW_BATTLE_POPULATION_POLICY
        and tooling.get("battle_a1_gap_geometry") == WORKFLOW_BATTLE_GAP_GEOMETRY
        and tooling.get("same_trainer_retry_contract")
        == WORKFLOW_SAME_TRAINER_RETRY_CONTRACT
        and tooling.get("party_member_ko_contract")
        == WORKFLOW_PARTY_MEMBER_KO_CONTRACT
        and tooling.get("physical_attempt_bgm_start_contract")
        == WORKFLOW_PHYSICAL_ATTEMPT_BGM_START_CONTRACT
        and tooling.get("battle_start_candidate_audit")
        == WORKFLOW_BATTLE_START_CANDIDATE_AUDIT
    )

    failed = [name for name, passed in checks.items() if not passed]
    registered_steps = workflow.get("steps", []) if isinstance(workflow, dict) else []
    deployment_blockers = []
    if [str(row.get("id") or "") for row in registered_steps] == ["prepare"]:
        deployment_blockers.append(
            "workflow registers only a read-only prepare stage; no receipt-bound Resolve assembly or validation"
        )
    deployment_ready = not failed and not deployment_blockers
    return {
        "schema": REFERENCE_AUDIT_SCHEMA,
        "status": "pass" if not failed else "fail",
        "reference_status": "pass" if not failed else "fail",
        "deployment_ready": deployment_ready,
        "reference": contract.get("reference"),
        "checks": checks,
        "failed_checks": failed,
        "evidence": evidence_out,
        "deployment_blockers": deployment_blockers,
        "deployment_conclusion": (
            "reference_contract_and_registered_dry_run_path_satisfied"
            if deployment_ready
            else "reference_contract_satisfied_but_live_orchestrator_not_deployable"
            if not failed
            else "do_not_deploy_reference_contract_failed"
        ),
    }
