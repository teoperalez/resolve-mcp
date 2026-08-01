from __future__ import annotations

"""Validate and map a content-bound GSC video-recovery receipt.

This is the narrow integration seam between deterministic video telemetry
recovery and the GSC gym workflow.  The receipt embeds every raw Battle run,
an explicit retain/discard decision for each run, the resolved physical
battles, the closed-atlas special identities, and the cross-media projection
proof.  It never invokes OCR, a learned model, an LLM, Resolve, or UI control.
"""

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .gsc_gym_video_recovery import (
    EXPECTED_MAIN_PROJECTION_FRAMES,
    PROJECTION_METHOD,
    SEMANTIC_RUN_RESOLUTION_POLICY_ID,
    DiscardedRawBattleRun,
    FixedHeaderSemanticEvidence,
    GscVideoRecoveryError,
    IdentityMatch,
    ProjectionAnchor,
    RawStateRun,
    RecoveryDeadline,
    ResolvedBattleRun,
    RunResolution,
    build_mapped_recovered_attempts,
    finite_komikax_identity_titles,
    fixed_header_semantics_sha256,
    raw_runs_sha256,
    validate_finalized_vertical_linkage,
    validate_projection_proof,
    validate_run_resolution,
)


RECOVERY_RECEIPT_SCHEMA = "gsc_gym_content_bound_recovery_receipt_v2"
RECOVERY_RECEIPT_STATUS = "pass"
RECOVERY_MODE = "content_bound_video_recovery_receipt"
FPS = 60
MAX_PROJECTION_RESIDUAL_FRAMES = 1
MAX_IDENTITY_DISTANCE = 0.08
MIN_IDENTITY_RUNNER_UP_MARGIN = 0.012


class GscGymRecoveryReceiptError(GscVideoRecoveryError):
    """A recovery receipt is missing, stale, ambiguous, or internally invalid."""


def _canonical_sha256(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GscGymRecoveryReceiptError(
            "Recovery receipt contains non-canonical JSON values."
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: Any) -> bool:
    return re.fullmatch(r"[0-9a-fA-F]{64}", str(value or "")) is not None


def _sha256(value: Any, label: str) -> str:
    if not _valid_sha256(value):
        raise GscGymRecoveryReceiptError(f"{label} must be a full SHA-256 digest.")
    return str(value).lower()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GscGymRecoveryReceiptError(f"{label} must be a JSON object.")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise GscGymRecoveryReceiptError(f"{label} must be a JSON array.")
    return value


def _integer(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GscGymRecoveryReceiptError(f"{label} must be an integer.")
    if minimum is not None and value < minimum:
        raise GscGymRecoveryReceiptError(f"{label} must be at least {minimum}.")
    return value


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GscGymRecoveryReceiptError(f"{label} must be numeric.")
    result = float(value)
    if not math.isfinite(result):
        raise GscGymRecoveryReceiptError(f"{label} must be finite.")
    if minimum is not None and result < minimum:
        raise GscGymRecoveryReceiptError(f"{label} must be at least {minimum}.")
    return result


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GscGymRecoveryReceiptError(f"{label} must be a non-empty string.")
    return value.strip()


def _same_path(left: Any, right: Path) -> bool:
    if not str(left or "").strip():
        return False
    try:
        normalized_left = os.path.normcase(str(Path(str(left)).resolve()))
        normalized_right = os.path.normcase(str(right.resolve()))
    except (OSError, ValueError):
        return False
    return normalized_left == normalized_right


def _hash_file_stable(
    path: Path,
    *,
    deadline: RecoveryDeadline,
    label: str,
) -> tuple[str, os.stat_result]:
    path = path.resolve()
    if not path.is_file():
        raise GscGymRecoveryReceiptError(f"Missing {label}: {path}")
    before = path.stat()
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                deadline.check(f"hashing {label}")
                chunk = stream.read(8 * 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise GscGymRecoveryReceiptError(f"Could not hash {label}: {path}: {exc}") from exc
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise GscGymRecoveryReceiptError(f"{label} changed while it was being hashed.")
    return digest.hexdigest(), after


def _read_receipt(path: Path) -> tuple[dict[str, Any], str, os.stat_result]:
    path = path.resolve()
    if not path.is_file():
        raise GscGymRecoveryReceiptError(f"Missing recovery receipt: {path}")
    before = path.stat()
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GscGymRecoveryReceiptError(f"Unreadable recovery receipt: {path}: {exc}") from exc
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise GscGymRecoveryReceiptError("Recovery receipt changed while it was being read.")
    if not isinstance(value, dict):
        raise GscGymRecoveryReceiptError("Recovery receipt must be a JSON object.")
    return value, hashlib.sha256(raw).hexdigest(), after


def _validate_bound_file(
    binding: Mapping[str, Any],
    actual_path: Path,
    *,
    deadline: RecoveryDeadline,
    label: str,
    require_size_mtime: bool,
) -> tuple[str, os.stat_result]:
    if not _same_path(binding.get("path"), actual_path):
        raise GscGymRecoveryReceiptError(f"Recovery receipt {label} path is stale.")
    expected_sha = _sha256(binding.get("sha256"), f"{label} sha256")
    actual_sha, stat = _hash_file_stable(actual_path, deadline=deadline, label=label)
    if actual_sha != expected_sha:
        raise GscGymRecoveryReceiptError(f"Recovery receipt {label} SHA-256 is stale.")
    if require_size_mtime:
        expected_bytes = _integer(binding.get("bytes"), f"{label} bytes", minimum=1)
        expected_mtime = _integer(
            binding.get("mtime_ns"), f"{label} mtime_ns", minimum=1
        )
        if (expected_bytes, expected_mtime) != (stat.st_size, stat.st_mtime_ns):
            raise GscGymRecoveryReceiptError(
                f"Recovery receipt {label} size/mtime binding is stale."
            )
    return actual_sha, stat


def _parse_raw_resolution(
    value: Mapping[str, Any],
) -> tuple[tuple[RawStateRun, ...], RunResolution, str]:
    policy_id = _text(value.get("policy_id"), "raw resolution policy_id")
    if policy_id != SEMANTIC_RUN_RESOLUTION_POLICY_ID:
        raise GscGymRecoveryReceiptError(
            "Recovery receipt uses an obsolete raw Battle bounce policy; regenerate it "
            "with fixed-header party-replacement grouping."
        )
    raw_values = _array(value.get("raw_battle_runs"), "raw_battle_runs")
    if not raw_values:
        raise GscGymRecoveryReceiptError("Recovery receipt contains no raw Battle runs.")

    raw_runs: list[RawStateRun] = []
    previous_end = -1
    for expected_ordinal, raw_value in enumerate(raw_values, start=1):
        row = _object(raw_value, f"raw_battle_runs[{expected_ordinal - 1}]")
        ordinal = _integer(row.get("ordinal"), "raw Battle ordinal", minimum=1)
        if ordinal != expected_ordinal:
            raise GscGymRecoveryReceiptError(
                "Raw Battle run ordinals must be dense, unique, and ordered."
            )
        if row.get("state") != "battle":
            raise GscGymRecoveryReceiptError(
                "raw_battle_runs may contain only exact lowercase Battle-state runs."
            )
        start = _integer(row.get("start_frame"), "raw Battle start_frame", minimum=0)
        end = _integer(row.get("end_frame"), "raw Battle end_frame", minimum=1)
        if end <= start or start < previous_end:
            raise GscGymRecoveryReceiptError("Raw Battle ranges overlap or are empty.")
        previous_end = end
        minimum_distance = _number(
            row.get("minimum_winner_distance"),
            "raw Battle minimum_winner_distance",
            minimum=0,
        )
        maximum_distance = _number(
            row.get("maximum_winner_distance"),
            "raw Battle maximum_winner_distance",
            minimum=0,
        )
        if maximum_distance < minimum_distance:
            raise GscGymRecoveryReceiptError(
                "Raw Battle maximum_winner_distance is below its minimum."
            )
        raw_runs.append(
            RawStateRun(
                ordinal=ordinal,
                state="battle",
                start_frame=start,
                end_frame=end,
                minimum_winner_distance=minimum_distance,
                maximum_winner_distance=maximum_distance,
                minimum_margin=_number(
                    row.get("minimum_margin"), "raw Battle minimum_margin", minimum=0
                ),
            )
        )
    raw_tuple = tuple(raw_runs)
    declared_raw_sha = _sha256(value.get("raw_runs_sha256"), "raw_runs_sha256")
    actual_raw_sha = raw_runs_sha256(raw_tuple)
    if declared_raw_sha != actual_raw_sha:
        raise GscGymRecoveryReceiptError("Raw Battle run content hash is stale.")

    semantic_values = _array(
        value.get("fixed_header_semantics"), "fixed_header_semantics"
    )
    semantics: list[FixedHeaderSemanticEvidence] = []
    for index, semantic_value in enumerate(semantic_values):
        row = _object(
            semantic_value,
            f"fixed_header_semantics[{index}]",
        )
        semantics.append(
            FixedHeaderSemanticEvidence(
                raw_run_ordinal=_integer(
                    row.get("raw_run_ordinal"),
                    "fixed-header raw_run_ordinal",
                    minimum=1,
                ),
                probe_frame=_integer(
                    row.get("probe_frame"),
                    "fixed-header probe_frame",
                    minimum=0,
                ),
                title_template_sha256=_sha256(
                    row.get("title_template_sha256"),
                    "fixed-header title_template_sha256",
                ),
                title_evidence_sha256=_sha256(
                    row.get("title_evidence_sha256"),
                    "fixed-header title_evidence_sha256",
                ),
                title_normalized_distance=_number(
                    row.get("title_normalized_distance"),
                    "fixed-header title_normalized_distance",
                    minimum=0,
                ),
                title_runner_up_distance=_number(
                    row.get("title_runner_up_distance"),
                    "fixed-header title_runner_up_distance",
                    minimum=0,
                ),
                attempt=_integer(
                    row.get("attempt"),
                    "fixed-header declared attempt",
                    minimum=1,
                ),
                matched_attempt=_integer(
                    row.get("matched_attempt"),
                    "fixed-header matched attempt",
                    minimum=1,
                ),
                attempt_template_sha256=_sha256(
                    row.get("attempt_template_sha256"),
                    "fixed-header attempt_template_sha256",
                ),
                attempt_evidence_sha256=_sha256(
                    row.get("attempt_evidence_sha256"),
                    "fixed-header attempt_evidence_sha256",
                ),
                attempt_normalized_distance=_number(
                    row.get("attempt_normalized_distance"),
                    "fixed-header attempt_normalized_distance",
                    minimum=0,
                ),
                attempt_runner_up_distance=_number(
                    row.get("attempt_runner_up_distance"),
                    "fixed-header attempt_runner_up_distance",
                    minimum=0,
                ),
            )
        )
    semantic_tuple = tuple(semantics)
    declared_semantic_sha = _sha256(
        value.get("fixed_header_semantics_sha256"),
        "fixed_header_semantics_sha256",
    )
    actual_semantic_sha = fixed_header_semantics_sha256(semantic_tuple)
    if declared_semantic_sha != actual_semantic_sha:
        raise GscGymRecoveryReceiptError(
            "Fixed-header semantic evidence content hash is stale."
        )

    resolved_values = _array(value.get("resolved_battles"), "resolved_battles")
    if not resolved_values:
        raise GscGymRecoveryReceiptError(
            "Recovery receipt contains no retained physical battle attempts."
        )
    resolved: list[ResolvedBattleRun] = []
    for expected_ordinal, resolved_value in enumerate(resolved_values, start=1):
        row = _object(resolved_value, f"resolved_battles[{expected_ordinal - 1}]")
        ordinal = _integer(row.get("ordinal"), "resolved battle ordinal", minimum=1)
        if ordinal != expected_ordinal:
            raise GscGymRecoveryReceiptError(
                "Resolved battle ordinals must be dense, unique, and ordered."
            )
        source_values = _array(
            row.get("source_raw_run_ordinals"), "source_raw_run_ordinals"
        )
        source_ordinals = tuple(
            _integer(item, "source raw-run ordinal", minimum=1)
            for item in source_values
        )
        resolved.append(
            ResolvedBattleRun(
                ordinal=ordinal,
                start_frame=_integer(
                    row.get("start_frame"), "resolved battle start_frame", minimum=0
                ),
                end_frame=_integer(
                    row.get("end_frame"), "resolved battle end_frame", minimum=1
                ),
                source_raw_run_ordinals=source_ordinals,
                identity_probe_frame=_integer(
                    row.get("identity_probe_frame"),
                    "resolved battle identity_probe_frame",
                    minimum=0,
                ),
            )
        )

    decision_values = _array(value.get("decisions"), "raw Battle decisions")
    if len(decision_values) != len(raw_tuple):
        raise GscGymRecoveryReceiptError(
            "Every raw Battle run must have exactly one explicit retain/discard decision."
        )
    decisions: dict[int, dict[str, Any]] = {}
    discarded: list[DiscardedRawBattleRun] = []
    for decision_value in decision_values:
        row = _object(decision_value, "raw Battle decision")
        raw_ordinal = _integer(
            row.get("raw_run_ordinal"), "decision raw_run_ordinal", minimum=1
        )
        if raw_ordinal in decisions:
            raise GscGymRecoveryReceiptError("A raw Battle run has duplicate decisions.")
        if raw_ordinal > len(raw_tuple):
            raise GscGymRecoveryReceiptError("A decision references a missing raw Battle run.")
        decision = row.get("decision")
        evidence = _text(row.get("evidence"), "raw Battle decision evidence")
        if decision == "retained":
            battle_ordinal = _integer(
                row.get("resolved_battle_ordinal"),
                "retained resolved_battle_ordinal",
                minimum=1,
            )
            if battle_ordinal > len(resolved):
                raise GscGymRecoveryReceiptError(
                    "A retained decision references a missing resolved battle."
                )
            decisions[raw_ordinal] = {
                "decision": decision,
                "resolved_battle_ordinal": battle_ordinal,
                "evidence": evidence,
            }
        elif decision == "discarded":
            reason_code = _text(row.get("reason_code"), "discard reason_code")
            decisions[raw_ordinal] = {
                "decision": decision,
                "reason_code": reason_code,
                "evidence": evidence,
            }
            discarded.append(
                DiscardedRawBattleRun(
                    raw_run_ordinal=raw_ordinal,
                    reason_code=reason_code,
                    evidence=evidence,
                )
            )
        else:
            raise GscGymRecoveryReceiptError(
                "A raw Battle decision must be exactly 'retained' or 'discarded'."
            )
    if set(decisions) != set(range(1, len(raw_tuple) + 1)):
        raise GscGymRecoveryReceiptError(
            "Every raw Battle run must be covered by exactly one explicit decision."
        )

    source_to_battle: dict[int, int] = {}
    for battle in resolved:
        for raw_ordinal in battle.source_raw_run_ordinals:
            if raw_ordinal in source_to_battle:
                raise GscGymRecoveryReceiptError(
                    "A raw Battle run is retained by more than one resolved battle."
                )
            source_to_battle[raw_ordinal] = battle.ordinal
    for raw_ordinal, decision in decisions.items():
        expected_battle = source_to_battle.get(raw_ordinal)
        if decision["decision"] == "retained":
            if expected_battle != decision["resolved_battle_ordinal"]:
                raise GscGymRecoveryReceiptError(
                    "A retained decision is not bound to its resolved battle source list."
                )
        elif expected_battle is not None:
            raise GscGymRecoveryReceiptError(
                "A discarded raw Battle run also appears in a resolved battle."
            )

    resolution = RunResolution(
        policy_id=policy_id,
        raw_runs_sha256=actual_raw_sha,
        battles=tuple(resolved),
        fixed_header_semantics=semantic_tuple,
        discarded_battle_runs=tuple(discarded),
    )
    try:
        validate_run_resolution(raw_tuple, resolution)
    except GscVideoRecoveryError as exc:
        raise GscGymRecoveryReceiptError(str(exc)) from exc
    resolution_sha = _canonical_sha256(
        {
            "policy_id": policy_id,
            "raw_runs_sha256": actual_raw_sha,
            "raw_battle_runs": raw_values,
            "fixed_header_semantics_sha256": actual_semantic_sha,
            "fixed_header_semantics": semantic_values,
            "decisions": decision_values,
            "resolved_battles": resolved_values,
        }
    )
    return raw_tuple, resolution, resolution_sha


def _parse_projection(value: Mapping[str, Any]):
    if value.get("method") != PROJECTION_METHOD:
        raise GscGymRecoveryReceiptError("Projection receipt uses an unapproved method.")
    offset = _integer(value.get("expected_offset_frames"), "projection offset")
    if offset != EXPECTED_MAIN_PROJECTION_FRAMES:
        raise GscGymRecoveryReceiptError("Projection receipt must use the proven fixed -6f offset.")
    residual = _integer(
        value.get("residual_tolerance_frames"),
        "projection residual tolerance",
        minimum=0,
    )
    if residual > MAX_PROJECTION_RESIDUAL_FRAMES:
        raise GscGymRecoveryReceiptError(
            "Projection receipt exceeds the maximum 1f audited residual."
        )
    anchors: list[ProjectionAnchor] = []
    for index, anchor_value in enumerate(_array(value.get("anchors"), "projection anchors")):
        row = _object(anchor_value, f"projection anchor {index}")
        anchors.append(
            ProjectionAnchor(
                vertical_frame=_integer(
                    row.get("vertical_frame"), "projection vertical_frame", minimum=0
                ),
                main_frame=_integer(
                    row.get("main_frame"), "projection main_frame", minimum=0
                ),
                normalized_distance=_number(
                    row.get("normalized_distance"),
                    "projection normalized_distance",
                    minimum=0,
                ),
                runner_up_distance=_number(
                    row.get("runner_up_distance"),
                    "projection runner_up_distance",
                    minimum=0,
                ),
                vertical_window_sha256=_sha256(
                    row.get("vertical_window_sha256"),
                    "projection vertical_window_sha256",
                ),
                main_window_sha256=_sha256(
                    row.get("main_window_sha256"),
                    "projection main_window_sha256",
                ),
                method=_text(row.get("method"), "projection anchor method"),
            )
        )
    proof = validate_projection_proof(
        anchors,
        expected_offset_frames=EXPECTED_MAIN_PROJECTION_FRAMES,
        residual_tolerance_frames=residual,
    )
    declared_proof_sha = _sha256(value.get("proof_sha256"), "projection proof_sha256")
    if proof.evidence_sha256 != declared_proof_sha:
        raise GscGymRecoveryReceiptError("Projection proof content hash is stale.")
    return proof


def _closed_identity_metadata(title: str, trainer_id: int) -> tuple[str, str, str, int]:
    if title.startswith("LEADER "):
        name = title.removeprefix("LEADER ")
        return name.title(), "leader", re.sub(r"[^A-Z0-9]+", "_", name), 1
    if title.startswith("ELITE FOUR "):
        name = title.removeprefix("ELITE FOUR ")
        return name.title(), "leader", name, 1
    if title == "CHAMPION LANCE":
        return "Lance", "leader", "LANCE", 1
    if title == "LEGEND RED":
        return "Red", "leader", "RED", 1
    if title in {"RIVAL1", "RIVAL2"}:
        if trainer_id <= 0:
            raise GscGymRecoveryReceiptError(
                "RIVAL1/RIVAL2 special identities require a positive trainer_id."
            )
        return "Rival", "rival", title, trainer_id
    raise GscGymRecoveryReceiptError(
        "Special identity is outside the finite KOMIKAX leader/rival title set."
    )


def _parse_special_identities(
    values: Sequence[Any],
    battles: Sequence[ResolvedBattleRun],
) -> tuple[dict[int, IdentityMatch], dict[int, int], str]:
    finite_titles = set(finite_komikax_identity_titles())
    by_battle = {battle.ordinal: battle for battle in battles}
    matches: dict[int, IdentityMatch] = {}
    rival_ids: dict[int, int] = {}
    previous_ordinal = 0
    normalized_rows: list[dict[str, Any]] = []
    for index, identity_value in enumerate(values):
        row = _object(identity_value, f"special_identities[{index}]")
        battle_ordinal = _integer(
            row.get("resolved_battle_ordinal"),
            "special identity resolved_battle_ordinal",
            minimum=1,
        )
        if battle_ordinal <= previous_ordinal or battle_ordinal in matches:
            raise GscGymRecoveryReceiptError(
                "Special identities must be unique and ordered by resolved battle."
            )
        previous_ordinal = battle_ordinal
        battle = by_battle.get(battle_ordinal)
        if battle is None:
            raise GscGymRecoveryReceiptError(
                "Special identity references a missing resolved battle."
            )
        title = _text(row.get("display_text"), "special identity display_text")
        if title not in finite_titles:
            raise GscGymRecoveryReceiptError(
                "Special identity is outside the finite KOMIKAX leader/rival title set."
            )
        start = _integer(
            row.get("vertical_start_frame"), "special identity vertical_start_frame", minimum=0
        )
        end = _integer(
            row.get("vertical_end_frame"), "special identity vertical_end_frame", minimum=1
        )
        probe = _integer(
            row.get("identity_probe_frame"),
            "special identity identity_probe_frame",
            minimum=0,
        )
        if (start, end, probe) != (
            battle.start_frame,
            battle.end_frame,
            battle.identity_probe_frame,
        ):
            raise GscGymRecoveryReceiptError(
                "Special identity is not exactly range/probe-bound to its resolved battle."
            )
        trainer_id = _integer(row.get("trainer_id"), "special identity trainer_id", minimum=1)
        identity, role, trainer_class, canonical_trainer_id = _closed_identity_metadata(
            title, trainer_id
        )
        if role == "leader" and trainer_id != canonical_trainer_id:
            raise GscGymRecoveryReceiptError(
                "Finite KOMIKAX leader identities must use canonical trainer_id 1."
            )
        best_distance = _number(
            row.get("normalized_distance"),
            "special identity normalized_distance",
            minimum=0,
        )
        runner_up = _number(
            row.get("runner_up_distance"),
            "special identity runner_up_distance",
            minimum=0,
        )
        if (
            best_distance > MAX_IDENTITY_DISTANCE
            or runner_up < best_distance
            or runner_up - best_distance < MIN_IDENTITY_RUNNER_UP_MARGIN
        ):
            raise GscGymRecoveryReceiptError(
                "Special identity finite-atlas match is weak or ambiguous."
            )
        evidence_sha = _sha256(
            row.get("evidence_sha256"), "special identity evidence_sha256"
        )
        matches[battle_ordinal] = IdentityMatch(
            display_text=title,
            identity=identity,
            role=role,
            trainer_class=trainer_class,
            trainer_id=canonical_trainer_id if role == "leader" else None,
            normalized_distance=best_distance,
            runner_up_distance=runner_up,
            evidence_sha256=evidence_sha,
        )
        if role == "rival":
            rival_ids[battle_ordinal] = trainer_id
        normalized_rows.append(
            {
                "resolved_battle_ordinal": battle_ordinal,
                "vertical_start_frame": start,
                "vertical_end_frame": end,
                "identity_probe_frame": probe,
                "display_text": title,
                "trainer_id": trainer_id,
                "normalized_distance": best_distance,
                "runner_up_distance": runner_up,
                "evidence_sha256": evidence_sha,
            }
        )
    return matches, rival_ids, _canonical_sha256(normalized_rows)


def _validate_mapped_attempts(
    attempts: Sequence[Mapping[str, Any]],
    *,
    main_frame_count: int,
) -> str:
    required = {
        "attempt_ordinal",
        "attempt_id",
        "battle_key",
        "canonical_identity",
        "identity_attempt_ordinal",
        "identity",
        "role",
        "trainer_class",
        "trainer_id",
        "checkpoint_key",
        "session_start_frame",
        "session_end_frame",
        "source_start_frame",
        "source_end_frame",
        "source_duration_frames",
        "source_start_authority",
        "source_end_authority",
        "source_mapping_required",
        "final_timeline_mapping_required",
        "already_mapped_to_main_source",
        "synthetic_session_events",
    }
    previous_end = -1
    for expected_ordinal, attempt in enumerate(attempts, start=1):
        missing = required - set(attempt)
        if missing:
            raise GscGymRecoveryReceiptError(
                f"Mapped attempt {expected_ordinal} lacks downstream keys: {sorted(missing)}."
            )
        if attempt["attempt_ordinal"] != expected_ordinal:
            raise GscGymRecoveryReceiptError("Mapped attempt ordinals are not dense and ordered.")
        start = _integer(
            attempt["source_start_frame"], "mapped source_start_frame", minimum=0
        )
        end = _integer(attempt["source_end_frame"], "mapped source_end_frame", minimum=1)
        duration = _integer(
            attempt["source_duration_frames"], "mapped source_duration_frames", minimum=1
        )
        if start < previous_end or end <= start or duration != end - start:
            raise GscGymRecoveryReceiptError(
                "Mapped main-source attempt ranges overlap, are empty, or have stale duration."
            )
        if end > main_frame_count:
            raise GscGymRecoveryReceiptError(
                "Mapped attempt extends beyond the bound main source frame count."
            )
        previous_end = end
        if (
            attempt["source_mapping_required"] is not False
            or attempt["final_timeline_mapping_required"] is not True
            or attempt["already_mapped_to_main_source"] is not True
            or attempt["synthetic_session_events"] is not False
        ):
            raise GscGymRecoveryReceiptError(
                "Mapped attempt does not declare the deterministic recovery seam flags."
            )
    return _canonical_sha256(list(attempts))


def validate_and_map_recovery_receipt(
    receipt_path: Path,
    *,
    main_source_path: Path,
    events_path: Path,
    meta_path: Path,
    deadline: RecoveryDeadline,
    expected_main_frame_count: int | None = None,
) -> dict[str, Any]:
    """Validate one immutable receipt and return main-source mapped attempts.

    All expensive hashes consume the caller's shared recovery deadline.  The
    returned ``recovery_binding.content_sha256`` binds the receipt, all four
    media/log inputs, the explicit run resolution, projection proof, identity
    evidence, and the final mapped-attempt content hash.
    """

    deadline.check("starting recovery receipt validation")
    receipt_path = receipt_path.resolve()
    main_source_path = main_source_path.resolve()
    events_path = events_path.resolve()
    meta_path = meta_path.resolve()
    receipt, receipt_sha, _receipt_stat = _read_receipt(receipt_path)
    if receipt.get("schema") != RECOVERY_RECEIPT_SCHEMA:
        raise GscGymRecoveryReceiptError(
            "Unsupported GSC recovery receipt schema; v1 receipts use the obsolete "
            "bounce policy and must be regenerated."
        )
    if receipt.get("status") != RECOVERY_RECEIPT_STATUS:
        raise GscGymRecoveryReceiptError("GSC recovery receipt status is not pass.")
    if receipt.get("fps") != FPS:
        raise GscGymRecoveryReceiptError("GSC recovery receipt must be exact 60fps.")
    for flag in ("no_ocr", "no_model", "no_llm"):
        if receipt.get(flag) is not True:
            raise GscGymRecoveryReceiptError(
                f"GSC recovery receipt must explicitly declare {flag}=true."
            )

    main_binding = _object(receipt.get("main_source"), "main_source")
    main_sha, main_stat = _validate_bound_file(
        main_binding,
        main_source_path,
        deadline=deadline,
        label="main source",
        require_size_mtime=True,
    )
    main_frame_count = _integer(
        main_binding.get("frame_count"), "main source frame_count", minimum=1
    )
    if expected_main_frame_count is not None:
        expected_frames = _integer(
            expected_main_frame_count, "expected main frame count", minimum=1
        )
        if main_frame_count != expected_frames:
            raise GscGymRecoveryReceiptError(
                "Recovery receipt main source frame_count disagrees with the caller."
            )

    log_binding = _object(receipt.get("canonical_logs"), "canonical_logs")
    events_binding = _object(log_binding.get("events"), "canonical_logs.events")
    meta_binding = _object(log_binding.get("meta"), "canonical_logs.meta")
    events_sha, _events_stat = _validate_bound_file(
        events_binding,
        events_path,
        deadline=deadline,
        label="canonical events.json",
        require_size_mtime=False,
    )
    meta_sha, _meta_stat = _validate_bound_file(
        meta_binding,
        meta_path,
        deadline=deadline,
        label="canonical meta.json",
        require_size_mtime=False,
    )

    vertical_binding = _object(receipt.get("vertical"), "vertical")
    linkage = validate_finalized_vertical_linkage(
        meta_path,
        events_path=events_path,
        deadline=deadline,
        verify_sha256=True,
    )
    manifest_path = Path(linkage["manifest_path"]).resolve()
    capture_path = Path(linkage["capture_path"]).resolve()
    manifest_binding = _object(vertical_binding.get("manifest"), "vertical.manifest")
    capture_binding = _object(vertical_binding.get("capture"), "vertical.capture")
    manifest_sha, manifest_stat = _validate_bound_file(
        manifest_binding,
        manifest_path,
        deadline=deadline,
        label="finalized vertical manifest",
        require_size_mtime=True,
    )
    if not _same_path(capture_binding.get("path"), capture_path):
        raise GscGymRecoveryReceiptError("Recovery receipt vertical capture path is stale.")
    capture_sha = _sha256(capture_binding.get("sha256"), "vertical capture sha256")
    capture_bytes = _integer(
        capture_binding.get("bytes"), "vertical capture bytes", minimum=1
    )
    capture_mtime = _integer(
        capture_binding.get("mtime_ns"), "vertical capture mtime_ns", minimum=1
    )
    capture_stat = capture_path.stat()
    if capture_sha != str(linkage["sha256"]).lower():
        raise GscGymRecoveryReceiptError("Recovery receipt vertical capture SHA-256 is stale.")
    if (capture_bytes, capture_mtime) != (
        capture_stat.st_size,
        capture_stat.st_mtime_ns,
    ):
        raise GscGymRecoveryReceiptError(
            "Recovery receipt vertical capture size/mtime binding is stale."
        )

    raw_runs, resolution, resolution_sha = _parse_raw_resolution(
        _object(receipt.get("raw_battle_resolution"), "raw_battle_resolution")
    )
    proof = _parse_projection(_object(receipt.get("projection"), "projection"))
    identity_matches, rival_ids, identities_sha = _parse_special_identities(
        _array(receipt.get("special_identities"), "special_identities"),
        resolution.battles,
    )
    mapped_payload = build_mapped_recovered_attempts(
        resolution=resolution,
        raw_runs=raw_runs,
        projection_proof=proof,
        identity_matches=identity_matches,
        rival_trainer_ids=rival_ids,
    )
    attempts = list(mapped_payload["attempts"])
    attempts_sha = _validate_mapped_attempts(
        attempts,
        main_frame_count=main_frame_count,
    )
    if attempts_sha != mapped_payload.get("attempts_sha256"):
        raise GscGymRecoveryReceiptError("Mapped-attempt content hash is internally stale.")
    declared_attempts_sha = receipt.get("mapped_attempts_sha256")
    if declared_attempts_sha is not None and (
        _sha256(declared_attempts_sha, "mapped_attempts_sha256") != attempts_sha
    ):
        raise GscGymRecoveryReceiptError("Receipt mapped_attempts_sha256 is stale.")

    source_alignment = {
        "schema": "gsc_gym_recovery_source_alignment_v1",
        "status": "pass",
        "method": PROJECTION_METHOD,
        "expected_offset_frames": proof.expected_offset_frames,
        "expected_offset_seconds": proof.expected_offset_frames / FPS,
        "maximum_audited_residual_frames": proof.residual_tolerance_frames,
        "anchor_count": len(proof.anchors),
        "projection_proof_sha256": proof.evidence_sha256,
        "main_source_frame_count": main_frame_count,
    }
    binding_material = {
        "receipt_sha256": receipt_sha,
        "main_source_sha256": main_sha,
        "events_sha256": events_sha,
        "meta_sha256": meta_sha,
        "vertical_manifest_sha256": manifest_sha,
        "vertical_capture_sha256": capture_sha,
        "raw_resolution_sha256": resolution_sha,
        "fixed_header_semantics_sha256": fixed_header_semantics_sha256(
            resolution.fixed_header_semantics
        ),
        "projection_proof_sha256": proof.evidence_sha256,
        "special_identities_sha256": identities_sha,
        "mapped_attempts_sha256": attempts_sha,
    }
    recovery_binding = {
        "schema": "gsc_gym_recovery_binding_v1",
        "status": "pass",
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "main_source": {
            "path": str(main_source_path),
            "bytes": main_stat.st_size,
            "mtime_ns": main_stat.st_mtime_ns,
            "frame_count": main_frame_count,
            "sha256": main_sha,
        },
        "canonical_logs": {
            "events": {"path": str(events_path), "sha256": events_sha},
            "meta": {"path": str(meta_path), "sha256": meta_sha},
        },
        "vertical": {
            "manifest": {
                "path": str(manifest_path),
                "bytes": manifest_stat.st_size,
                "mtime_ns": manifest_stat.st_mtime_ns,
                "sha256": manifest_sha,
            },
            "capture": {
                "path": str(capture_path),
                "bytes": capture_stat.st_size,
                "mtime_ns": capture_stat.st_mtime_ns,
                "sha256": capture_sha,
            },
        },
        "raw_resolution_sha256": resolution_sha,
        "raw_resolution_policy_id": resolution.policy_id,
        "fixed_header_semantics_sha256": fixed_header_semantics_sha256(
            resolution.fixed_header_semantics
        ),
        "fixed_header_semantic_count": len(resolution.fixed_header_semantics),
        "projection_proof_sha256": proof.evidence_sha256,
        "special_identities_sha256": identities_sha,
        "mapped_attempts_sha256": attempts_sha,
        "content_sha256": _canonical_sha256(binding_material),
        "raw_battle_run_count": len(raw_runs),
        "resolved_attempt_count": len(attempts),
        "special_identity_count": len(identity_matches),
        "no_ocr": True,
        "no_model": True,
        "no_llm": True,
        "synthetic_session_events": False,
    }
    return {
        "schema": "gsc_gym_recovery_integration_v1",
        "status": "pass",
        "mode": RECOVERY_MODE,
        "mapped_attempts": attempts,
        "mapped_attempts_sha256": attempts_sha,
        "source_alignment": source_alignment,
        "recovery_binding": recovery_binding,
    }
