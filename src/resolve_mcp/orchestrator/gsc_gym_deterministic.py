from __future__ import annotations

"""Contracts for the zero-LLM GSC Gym Leader Challenge workflow."""

import hashlib
import json
import random
import re
import bisect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .gsc_gym_intro_library import (
    GscGymIntroLibraryError,
    load_gsc_gym_intro_library,
)


WORKFLOW_ID = "gsc_gym_leader_deterministic_single_build"
PLAN_SCHEMA = "gsc_gym_leader_deterministic_dry_run_v2"
MAX_FULL_RUN_SECONDS = 600.0
INTRO_TRACK = "Dual Screen Lovelife.mp3"
OUTRO_TRACK = "Golden Goose.mp3"
POST_FINAL_REQUIRED_TRACKS = (
    INTRO_TRACK,
    "Motivated By Clouds.mp3",
    "Roll Me in Stardust.mp3",
)
NONBATTLE_RANDOM_RESERVED_TRACKS = frozenset(
    (*POST_FINAL_REQUIRED_TRACKS, OUTRO_TRACK)
)
WORKFLOW_POST_BATTLE_BGM_POLICY = (
    "fresh_unused_source_zero_after_every_positive_post_battle_gap;"
    "zero_gap_direct_battle_handoff"
)
WORKFLOW_NONBATTLE_REPEAT_POLICY = (
    "no_repeats_except_Dual_Screen_Lovelife_exactly_opening_and_post_final"
)
WORKFLOW_POST_FINAL_BGM_SEQUENCE = (
    "Dual Screen Lovelife.mp3;Motivated By Clouds.mp3;"
    "Roll Me in Stardust.mp3;unused_randomized_track"
)
WORKFLOW_BATTLE_POPULATION_POLICY = (
    "every_retained_physical_attempt_keeps_its_own_A2_battle_range;"
    "only_supplied_identity_attempt_ordinal_1_gets_an_A1_gap;"
    "only_leader_or_rival_identity_attempt_ordinal_1_gets_V2_intro"
)
WORKFLOW_BATTLE_GAP_GEOMETRY = (
    "one_real_60f_timeline_insert_only_for_supplied_identity_attempt_ordinal_1_"
    "at_an_adjacent_autoeditor_A1_boundary;no_gap_before_same_trainer_retries_"
    "even_if_attempt_1_was_removed;preserve_all_A1_source_frames;one_exact_60f_"
    "incoming_side_source_backed_V1_bridge_per_gap;source_overlap_allowed"
)
WORKFLOW_SAME_TRAINER_RETRY_CONTRACT = (
    "same_trainer_retries_keep_distinct_physical_battle_and_A2_ranges_but_"
    "receive_no_additional_A1_gap_or_V2_intro"
)
WORKFLOW_BATTLE_START_CANDIDATE_AUDIT = (
    "inside_retained_start_records_preceding_and_following_join_distances_"
    "validity_and_rejection_reasons_then_requires_one_unique_nearest_candidate"
)
WORKFLOW_PARTY_MEMBER_KO_CONTRACT = (
    "during_team_or_gym_leader_challenge_active_member_KO_plus_replacement_is_"
    "not_battle_end_or_new_battle;future_telemetry_requires_authoritative_battle_"
    "ended_and_paired_party_replacement_lifecycle_evidence;when_bound_logs_lack_"
    "that_evidence_video_recovery_requires_fixed_template_title_and_finite_"
    "attempt_evidence_for_every_raw_battle_run_and_merges_only_exact_same_title_"
    "attempt_otherwise_fail_closed"
)
WORKFLOW_PHYSICAL_ATTEMPT_BGM_START_CONTRACT = (
    "every_physical_attempt_has_distinct_A2_assignment_and_restarts_original_"
    "source_at_asset_source_start_frame"
)
FAIRLIGHT_PRESET_NAME = "Standard Gameplay youtube"
FAIRLIGHT_PRESET_TYPE = "CONSOLE_FLEXI"
WORKFLOW_FAIRLIGHT_FINAL_STAGE_CONTRACT = (
    "media_pool_validation_then_exact_receipt_bound_timeline_preset_as_final_"
    "Resolve_mutation_then_project_save_then_read_only_validation"
)
BATTLE_AUDIO_DIR = "Gen 2 battle audio"
OPENING_INTRO_SPEED_PCT = 400
OPENING_INTRO_TIMELINE_FRAMES = 260
OPENING_INTRO_SOURCE_FRAMES = 512
OPENING_INTRO_DERIVATIVE_FRAMES = 130
BATTLE_GAP_FRAMES = 60
BATTLE_INTRO_FRAMES = 300
CAROUSEL_EXP_HANDOFF_TOLERANCE_FRAMES = 2
SOURCE_PROJECTION_RESIDUAL_TOLERANCE_FRAMES = 2
SOURCE_PROJECTION_MAX_BRACKET_SPAN_FRAMES = 600
KNOWN_GSC_LEADERS = {
    "falkner", "bugsy", "whitney", "morty", "chuck", "jasmine", "pryce",
    "clair", "will", "koga", "bruno", "karen", "lance", "brock", "misty",
    "lt surge", "erika", "janine", "sabrina", "blaine", "blue", "red",
}

RIVAL_LOCATION_BY_TRAINER_ID = {
    1: "initial",
    2: "initial",
    3: "initial",
    4: "azalea",
    5: "azalea",
    6: "azalea",
    7: "burnedtower",
    8: "burnedtower",
    9: "burnedtower",
    10: "goldenrod",
    11: "goldenrod",
    12: "goldenrod",
    13: "victoryroad",
    14: "victoryroad",
    15: "victoryroad",
}
RIVAL2_LOCATION_BY_TRAINER_ID = {
    1: "mtmoon",
    2: "mtmoon",
    3: "mtmoon",
    4: "indigoplateau",
    5: "indigoplateau",
    6: "indigoplateau",
}
RIVAL_LOCATION_BY_TRAINER_CLASS = {
    "RIVAL1": RIVAL_LOCATION_BY_TRAINER_ID,
    "RIVAL2": RIVAL2_LOCATION_BY_TRAINER_ID,
}
# Vanilla Crystal's RIVAL1 and RIVAL2 party records repeat in exact
# grass/fire/water triplets.  This is encoded from the ROM trainer table so
# rival media never depends on observed order, transcript classification, or
# an LLM.  Keep the original RIVAL1-only public map for API compatibility.
RIVAL_STARTER_TYPE_BY_TRAINER_ID = {
    trainer_id: ("grass", "fire", "water")[(trainer_id - 1) % 3]
    for trainer_id in range(1, 16)
}
RIVAL_STARTER_TYPE_BY_TRAINER_CLASS = {
    trainer_class: {
        trainer_id: RIVAL_STARTER_TYPE_BY_TRAINER_ID[trainer_id]
        for trainer_id in locations
    }
    for trainer_class, locations in RIVAL_LOCATION_BY_TRAINER_CLASS.items()
}
# The canonical Crystal source pack names the first encounter after Silver's
# unevolved starter species.  Later encounters use the starter type suffix.
RIVAL_INITIAL_ASSET_SUFFIX_BY_STARTER_TYPE = {
    "grass": "chikorita",
    "fire": "cyndaquil",
    "water": "totodile",
}


@dataclass(frozen=True)
class _IndexedEvent:
    index: int
    elapsed_ms: float
    row: dict[str, Any]


class GscGymDeterministicError(RuntimeError):
    pass


class IncompleteBattleTelemetryError(GscGymDeterministicError):
    """A finalized log stopped while the mapper still owned a physical battle."""

    pass


def stable_seed(
    *paths: Path,
    deadline_check: Callable[[str], None] | None = None,
    large_file_sample_bytes: int = 4 * 1024 * 1024,
) -> str:
    """Create a deterministic source-bound seed without hashing whole captures."""

    digest = hashlib.sha256()
    for path in paths:
        resolved = path.resolve()
        size = resolved.stat().st_size
        digest.update(str(resolved).encode("utf-8"))
        digest.update(f";size={size};".encode("ascii"))
        with path.open("rb") as handle:
            if size <= large_file_sample_bytes * 4:
                while chunk := handle.read(1024 * 1024):
                    if deadline_check:
                        deadline_check(f"fingerprinting {resolved.name}")
                    digest.update(chunk)
            else:
                width = min(large_file_sample_bytes, size)
                offsets = sorted({0, max(0, (size - width) // 2), max(0, size - width)})
                for offset in offsets:
                    if deadline_check:
                        deadline_check(f"fingerprinting {resolved.name}")
                    handle.seek(offset)
                    payload = handle.read(width)
                    digest.update(f"offset={offset};bytes={len(payload)};".encode("ascii"))
                    digest.update(payload)
    return digest.hexdigest()


def load_events(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise GscGymDeterministicError(f"Expected an event array: {path}")
    return value


def event_frame(row: dict[str, Any], fps: int = 60) -> int:
    elapsed = row.get("tElapsedMs")
    if not isinstance(elapsed, (int, float)) or elapsed < 0:
        raise GscGymDeterministicError(f"Event lacks non-negative tElapsedMs: {row!r}")
    return round(float(elapsed) * fps / 1000.0)


def event_text(row: dict[str, Any]) -> str:
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    fields = [row.get("category"), row.get("name")]
    fields.extend(data.get(key) for key in (
        "trainer", "trainerName", "trainerClass", "leader", "location", "type",
    ))
    return " ".join(str(value) for value in fields if value is not None).lower()


def _event_data(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("data") if isinstance(row.get("data"), dict) else {}


def _normalized_trainer_class(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def _trainer_id(value: Any) -> int:
    if isinstance(value, bool):
        raise GscGymDeterministicError("Boolean trainerId is invalid.")
    try:
        rendered = int(value)
    except (TypeError, ValueError) as exc:
        raise GscGymDeterministicError(f"Invalid trainerId: {value!r}") from exc
    if rendered <= 0 or str(rendered) != str(value).strip().lstrip("+"):
        # JSON integers are the normal form.  Numeric strings are accepted only
        # when they round-trip exactly; floats and lossy coercions are not.
        if not isinstance(value, int):
            raise GscGymDeterministicError(f"Invalid trainerId: {value!r}")
    if rendered <= 0:
        raise GscGymDeterministicError(f"trainerId must be positive: {value!r}")
    return rendered


def _is_exact_battle_start(row: dict[str, Any]) -> bool:
    return row.get("category") == "battle" and row.get("name") == "battle-start"


def _is_exact_battle_end(row: dict[str, Any]) -> bool:
    return row.get("category") == "battle" and row.get("name") == "battle-end"


def _is_mapper_state(row: dict[str, Any]) -> bool:
    return row.get("category") == "state" and row.get("name") == "mapper-state"


def _ordered_events(events: list[dict[str, Any]]) -> list[_IndexedEvent]:
    indexed: list[_IndexedEvent] = []
    previous = -1.0
    for index, row in enumerate(events):
        elapsed = row.get("tElapsedMs")
        if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or elapsed < 0:
            raise GscGymDeterministicError(
                f"Event {index} lacks a non-negative numeric tElapsedMs."
            )
        rendered = float(elapsed)
        if rendered < previous:
            raise GscGymDeterministicError(
                f"Session events are not monotonic at event {index}: {rendered} < {previous}."
            )
        previous = rendered
        indexed.append(_IndexedEvent(index=index, elapsed_ms=rendered, row=row))
    return indexed


def _clean_identity(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^(?:leader|champion)\s+", "", text, flags=re.IGNORECASE)
    return text


def battle_identity(row: dict[str, Any]) -> str:
    data = _event_data(row)
    for key in ("trainer", "trainerName", "leader"):
        value = _clean_identity(data.get(key))
        if value:
            return value
    return _clean_identity(data.get("trainerClass")) or "Unknown Trainer"


def classify_battle(row: dict[str, Any]) -> str | None:
    """Classify only the physical opponent-start telemetry schema.

    ``trainer-ai/gym-leader-battle-start`` describes the selected player AI
    profile and may fire repeatedly inside one physical battle.  It is never
    an editorial battle anchor.
    """

    if not _is_exact_battle_start(row):
        return None
    data = _event_data(row)
    trainer_class = _normalized_trainer_class(data.get("trainerClass"))
    identity = battle_identity(row)
    normalized_identity = re.sub(r"[^a-z0-9]+", " ", identity.casefold()).strip()
    if trainer_class.startswith("RIVAL"):
        return "rival"
    if (
        data.get("isMainBoss") is True
        or bool(_clean_identity(data.get("checkpointKey")))
        or normalized_identity in KNOWN_GSC_LEADERS
        or re.sub(r"_+", " ", trainer_class.casefold()).strip() in KNOWN_GSC_LEADERS
    ):
        return "leader"
    return "trainer"


def canonical_battles(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return exact generic opponent starts, including retries.

    This helper intentionally does not infer physical intervals or collapse
    retries.  ``canonical_battle_groups`` performs that stricter operation.
    """

    battles: list[dict[str, Any]] = []
    seen_event_keys: set[tuple[int, str, int]] = set()
    for indexed in _ordered_events(events):
        row = indexed.row
        role = classify_battle(row)
        if role is None:
            continue
        data = _event_data(row)
        trainer_class = _normalized_trainer_class(data.get("trainerClass"))
        trainer_id = _trainer_id(data.get("trainerId"))
        if not trainer_class:
            raise GscGymDeterministicError(
                f"battle-start event {indexed.index} lacks trainerClass."
            )
        frame = event_frame(row)
        event_key = (frame, trainer_class, trainer_id)
        if event_key in seen_event_keys:
            raise GscGymDeterministicError(
                "Duplicate exact battle-start telemetry at session frame "
                f"{frame}: {trainer_class}/{trainer_id}."
            )
        seen_event_keys.add(event_key)
        battle_key = f"{trainer_class}:{trainer_id}"
        battles.append({
            "frame": frame,
            "session_start_frame": frame,
            "session_start_ms": indexed.elapsed_ms,
            "role": role,
            "identity": battle_identity(row),
            "battle_key": battle_key,
            "trainer_class": trainer_class,
            "trainer_id": trainer_id,
            "checkpoint_key": _clean_identity(data.get("checkpointKey")) or None,
            "event": row.get("name"),
            "event_index": indexed.index,
            "boundary_authority": "exact_battle_battle-start_event_session_clock_only",
        })
    return sorted(battles, key=lambda value: value["frame"])


def _physical_battle_intervals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = _ordered_events(events)
    prep: _IndexedEvent | None = None
    active: dict[str, Any] | None = None
    intervals: list[dict[str, Any]] = []

    for indexed in ordered:
        row = indexed.row
        if not _is_mapper_state(row):
            continue
        data = _event_data(row)
        before = str(data.get("from") or "")
        after = str(data.get("to") or "")

        if after == "To Battle" and before != "To Battle":
            if active is not None:
                raise GscGymDeterministicError(
                    f"Nested To Battle transition during battle at event {indexed.index}."
                )
            if prep is not None:
                raise GscGymDeterministicError(
                    f"Repeated To Battle preparation at event {indexed.index}."
                )
            prep = indexed

        if before == "To Battle" and after == "Battle":
            if active is not None:
                raise GscGymDeterministicError(
                    f"Nested physical battle start at event {indexed.index}."
                )
            if prep is None or prep.index >= indexed.index:
                raise GscGymDeterministicError(
                    f"Physical battle start {indexed.index} lacks its preceding To Battle transition."
                )
            active = {
                "prep": prep,
                "start": indexed,
            }
            prep = None
            continue

        if before == "Battle" and after != "Battle":
            if active is None:
                raise GscGymDeterministicError(
                    f"Orphan physical battle exit at event {indexed.index}."
                )
            intervals.append({**active, "end": indexed})
            active = None

    if active is not None:
        start = active["start"]
        raise IncompleteBattleTelemetryError(
            f"Session ended with an open physical battle from event {start.index}."
        )
    if prep is not None:
        raise IncompleteBattleTelemetryError(
            f"Session ended during an open To Battle preparation from event {prep.index}."
        )
    return intervals


def canonical_battle_attempts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bind each exact opponent start to one complete mapper battle interval."""

    ordered = _ordered_events(events)
    exact_starts = [row for row in ordered if _is_exact_battle_start(row.row)]
    exact_ends = [row for row in ordered if _is_exact_battle_end(row.row)]
    intervals = _physical_battle_intervals(events)
    used_starts: set[int] = set()
    used_ends: set[int] = set()
    attempts: list[dict[str, Any]] = []

    for ordinal, interval in enumerate(intervals, start=1):
        prep: _IndexedEvent = interval["prep"]
        mapper_start: _IndexedEvent = interval["start"]
        mapper_end: _IndexedEvent = interval["end"]
        start_candidates = [
            candidate
            for candidate in exact_starts
            if candidate.index not in used_starts
            and prep.index < candidate.index <= mapper_start.index
        ]
        if len(start_candidates) != 1:
            raise GscGymDeterministicError(
                "Physical battle interval "
                f"{ordinal} requires exactly one generic battle-start between "
                f"events {prep.index} and {mapper_start.index}; found {len(start_candidates)}."
            )
        start_event = start_candidates[0]
        used_starts.add(start_event.index)
        start_data = _event_data(start_event.row)
        trainer_class = _normalized_trainer_class(start_data.get("trainerClass"))
        trainer_id = _trainer_id(start_data.get("trainerId"))
        if not trainer_class:
            raise GscGymDeterministicError(
                f"battle-start event {start_event.index} lacks trainerClass."
            )
        battle_key = f"{trainer_class}:{trainer_id}"

        end_candidates = [
            candidate
            for candidate in exact_ends
            if candidate.index not in used_ends
            and mapper_start.index < candidate.index <= mapper_end.index
        ]
        if len(end_candidates) > 1:
            raise GscGymDeterministicError(
                f"Physical battle interval {ordinal} contains multiple battle-end events."
            )
        direct_end = end_candidates[0] if end_candidates else None
        if direct_end is not None:
            end_data = _event_data(direct_end.row)
            end_class = _normalized_trainer_class(end_data.get("trainerClass"))
            end_id = _trainer_id(end_data.get("trainerId"))
            if (end_class, end_id) != (trainer_class, trainer_id):
                raise GscGymDeterministicError(
                    "battle-end identity does not match its physical interval: "
                    f"{end_class}/{end_id} != {trainer_class}/{trainer_id}."
                )
            if str(end_data.get("outcome") or "") != "Win":
                raise GscGymDeterministicError(
                    f"Unsupported direct battle-end outcome at event {direct_end.index}."
                )
            used_ends.add(direct_end.index)

        role = classify_battle(start_event.row)
        if role is None:
            raise GscGymDeterministicError("Internal exact battle-start classification failure.")
        attempts.append({
            "attempt_ordinal": ordinal,
            "battle_key": battle_key,
            "identity": battle_identity(start_event.row),
            "role": role,
            "trainer_class": trainer_class,
            "trainer_id": trainer_id,
            "checkpoint_key": _clean_identity(start_data.get("checkpointKey")) or None,
            "start_event_index": start_event.index,
            "mapper_start_event_index": mapper_start.index,
            "mapper_end_event_index": mapper_end.index,
            "session_start_ms": start_event.elapsed_ms,
            "session_start_frame": event_frame(start_event.row),
            "session_physical_start_ms": mapper_start.elapsed_ms,
            "session_physical_start_frame": event_frame(mapper_start.row),
            "session_end_ms": mapper_end.elapsed_ms,
            "session_end_frame": event_frame(mapper_end.row),
            "outcome": "Win" if direct_end is not None else "Unknown",
            "direct_end_event_index": direct_end.index if direct_end is not None else None,
            "direct_end_session_frame": (
                event_frame(direct_end.row) if direct_end is not None else None
            ),
            "start_authority": "exact_battle_battle-start_plus_mapper_ToBattle_to_Battle",
            "end_authority": "exact_mapper_Battle_exit",
            "outcome_authority": (
                "exact_battle_battle-end" if direct_end is not None else "not_logged"
            ),
        })

    unused_starts = [row.index for row in exact_starts if row.index not in used_starts]
    unused_ends = [row.index for row in exact_ends if row.index not in used_ends]
    if unused_starts or unused_ends:
        raise GscGymDeterministicError(
            "Unbound generic battle telemetry remains after mapper pairing: "
            f"starts={unused_starts}, ends={unused_ends}."
        )
    return attempts


def canonical_battle_groups(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse only consecutive same-opponent retries into exact ranges."""

    attempts = canonical_battle_attempts(events)
    groups: list[dict[str, Any]] = []
    for attempt in attempts:
        if groups and groups[-1]["battle_key"] == attempt["battle_key"]:
            group = groups[-1]
            group["attempts"].append(attempt)
            group["attempt_count"] += 1
            group["session_end_ms"] = attempt["session_end_ms"]
            group["session_end_frame"] = attempt["session_end_frame"]
            group["outcome"] = attempt["outcome"]
            group["direct_end_event_index"] = attempt["direct_end_event_index"]
            group["direct_end_session_frame"] = attempt["direct_end_session_frame"]
            continue
        groups.append({
            "group_ordinal": len(groups) + 1,
            "battle_key": attempt["battle_key"],
            "identity": attempt["identity"],
            "role": attempt["role"],
            "trainer_class": attempt["trainer_class"],
            "trainer_id": attempt["trainer_id"],
            "checkpoint_key": attempt["checkpoint_key"],
            "attempt_count": 1,
            "attempts": [attempt],
            "session_start_ms": attempt["session_start_ms"],
            "session_start_frame": attempt["session_start_frame"],
            "session_end_ms": attempt["session_end_ms"],
            "session_end_frame": attempt["session_end_frame"],
            "outcome": attempt["outcome"],
            "direct_end_event_index": attempt["direct_end_event_index"],
            "direct_end_session_frame": attempt["direct_end_session_frame"],
            "range_authority": "first_exact_start_to_last_exact_mapper_exit",
            "source_mapping_required": True,
            "final_timeline_mapping_required": True,
        })
    return groups


def first_major_battles(battles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for battle in battles:
        if battle.get("role") not in {"leader", "rival"}:
            continue
        identity = str(battle.get("identity") or "").casefold()
        key = str(battle.get("battle_key") or identity).casefold()
        if not identity or key in seen:
            continue
        seen.add(key)
        result.append(dict(battle))
    return result


def build_a1_gap_plan(
    battles: list[dict[str, Any]],
    *,
    boundary_is_final_timeline: bool = False,
) -> list[dict[str, Any]]:
    """Plan an exact A1-only gap only for identity attempt ordinal one.

    Physical retries remain independent battle/BGM ranges, but their supplied
    identity ordinal is authoritative even when an earlier attempt was removed
    by the dialogue edit.  Canonical group rows do not carry an attempt ordinal
    and already represent the first-attempt editorial boundary, so they retain
    one gap for backwards-compatible preflight reporting.
    """

    rows: list[dict[str, Any]] = []
    for battle in battles:
        identity_key = str(
            battle.get("canonical_identity")
            or battle.get("battle_key")
            or battle.get("identity")
            or ""
        ).strip().casefold()
        if not identity_key:
            raise GscGymDeterministicError(
                "A1 gap planning requires a canonical trainer identity."
            )
        attempt_ordinal = battle.get(
            "identity_attempt_ordinal",
            battle.get("attempt_ordinal"),
        )
        if attempt_ordinal is not None and (
            isinstance(attempt_ordinal, bool)
            or not isinstance(attempt_ordinal, int)
            or attempt_ordinal < 1
        ):
            raise GscGymDeterministicError(
                f"Battle {battle.get('battle_key')!r} has invalid identity attempt "
                f"ordinal {attempt_ordinal!r}."
            )
        if attempt_ordinal is not None and attempt_ordinal > 1:
            continue
        source_session_frame = battle.get("session_start_frame", battle.get("frame"))
        if not isinstance(source_session_frame, int):
            raise GscGymDeterministicError(
                f"Battle {battle.get('battle_key')!r} lacks a session start frame."
            )
        final_frame = battle.get("final_timeline_start_frame")
        if boundary_is_final_timeline:
            if not isinstance(final_frame, int):
                raise GscGymDeterministicError(
                    f"Battle {battle.get('battle_key')!r} lacks its final-timeline mapping."
                )
            if final_frame < BATTLE_GAP_FRAMES:
                raise GscGymDeterministicError(
                    f"Mapped battle {battle.get('battle_key')!r} is too early for its A1 gap."
                )
        rows.append({
            "battle_key": battle.get("battle_key"),
            "identity": battle.get("identity"),
            "role": battle.get("role"),
            "identity_attempt_ordinal": attempt_ordinal,
            "editorial_group_id": battle.get("editorial_group_id"),
            "physical_attempt_count": int(
                battle.get("physical_attempt_count")
                or battle.get("attempt_count")
                or 1
            ),
            "source_session_frame": source_session_frame,
            "final_timeline_battle_frame": final_frame if boundary_is_final_timeline else None,
            "start_offset_from_mapped_battle": -BATTLE_GAP_FRAMES,
            "end_offset_from_mapped_battle": 0,
            "duration_frames": BATTLE_GAP_FRAMES,
            "audio_track": 1,
            "a1_policy": "exact_silence",
            "v1_policy": "continuous",
            "mapping_required": not boundary_is_final_timeline,
            "record_start_frame": (
                final_frame - BATTLE_GAP_FRAMES if boundary_is_final_timeline else None
            ),
            "record_end_frame": final_frame if boundary_is_final_timeline else None,
        })
    return rows


CAROUSEL_START_EVENT = ("view", "member-carousel-started")
CAROUSEL_END_EVENT = ("view", "member-carousel-ended")
CHANNEL_EXP_EVENT = ("view", "channel-exp-bar-shown")

OBS_MARKER_EVENT_KEYS = {
    ("meta", "pokemon-changed"),
    ("event", "first-pokemon-received"),
    ("champion", "beat-champion-flag"),
    ("battle", "battle-start"),
    ("battle", "battle-end"),
    ("view", "post-battle-tiercard-shown"),
    ("view", "post-battle-tiercard-closed"),
    CAROUSEL_START_EVENT,
    CAROUSEL_END_EVENT,
    CHANNEL_EXP_EVENT,
    ("event", "tier-checkpoint"),
    ("event", "fmb-section-complete"),
}


def canonical_obs_marker_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for indexed in _ordered_events(events):
        key = (str(indexed.row.get("category") or ""), str(indexed.row.get("name") or ""))
        if key not in OBS_MARKER_EVENT_KEYS:
            continue
        rows.append({
            "event_index": indexed.index,
            "session_frame": event_frame(indexed.row),
            "name": f"{key[0]}:{key[1]}",
        })
    return rows


def _chapter_marker_matches(
    chapters: list[int],
    markers: list[dict[str, Any]],
    *,
    offset_frame: int,
    tolerance_frames: int,
) -> list[dict[str, Any]]:
    marker_frames = [int(row["session_frame"]) for row in markers]
    last_marker_index = -1
    matches: list[dict[str, Any]] = []
    for chapter_index, chapter_frame in enumerate(chapters):
        target = chapter_frame + offset_frame
        first = max(
            last_marker_index + 1,
            bisect.bisect_left(marker_frames, target - tolerance_frames),
        )
        last = bisect.bisect_right(marker_frames, target + tolerance_frames)
        candidates = list(range(first, last))
        if not candidates:
            continue
        marker_index = min(
            candidates,
            key=lambda index: (
                abs(marker_frames[index] - target),
                marker_frames[index],
                index,
            ),
        )
        marker = markers[marker_index]
        residual = marker_frames[marker_index] - target
        matches.append({
            "chapter_index": chapter_index,
            "chapter_frame": chapter_frame,
            "marker_index": marker_index,
            "event_index": int(marker["event_index"]),
            "marker_session_frame": marker_frames[marker_index],
            "marker_name": marker["name"],
            "residual_frames": residual,
        })
        last_marker_index = marker_index
    return matches


def align_obs_chapters_to_session(
    chapter_frames: list[int],
    events: list[dict[str, Any]],
    *,
    tolerance_frames: int = 8,
    minimum_matches: int = 6,
    minimum_match_ratio: float = 0.35,
    minimum_span_ratio: float = 0.70,
    deadline_check: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Match main OBS chapter frames to canonical session marker events."""

    if tolerance_frames < 0 or tolerance_frames > 12:
        raise GscGymDeterministicError("GSC chapter tolerance must be between 0 and 12 frames.")
    chapters = sorted({int(frame) for frame in chapter_frames if int(frame) > 0})
    markers = canonical_obs_marker_events(events)
    if len(chapters) < minimum_matches:
        raise GscGymDeterministicError(
            f"Source contains only {len(chapters)} non-zero OBS chapters; require {minimum_matches}."
        )
    if len(markers) < minimum_matches:
        raise GscGymDeterministicError(
            f"Session contains only {len(markers)} canonical OBS-marker events; require {minimum_matches}."
        )

    maximum_offset = 6 * 3600 * 60
    seed_chapters = chapters[: min(80, len(chapters))]
    candidate_offsets = {
        int(marker["session_frame"]) - chapter
        for chapter in seed_chapters
        for marker in markers
        if 0 <= int(marker["session_frame"]) - chapter <= maximum_offset
    }
    if not candidate_offsets:
        raise GscGymDeterministicError("No non-negative OBS/session offset candidate exists.")

    ranked: list[tuple[int, float, int, list[dict[str, Any]]]] = []
    for candidate_index, offset in enumerate(candidate_offsets):
        if deadline_check and candidate_index % 128 == 0:
            deadline_check("aligning OBS chapters to GSC session markers")
        matches = _chapter_marker_matches(
            chapters,
            markers,
            offset_frame=offset,
            tolerance_frames=tolerance_frames,
        )
        if not matches:
            continue
        absolute = sorted(abs(int(row["residual_frames"])) for row in matches)
        median = float(absolute[len(absolute) // 2])
        ranked.append((-len(matches), median, offset, matches))
    if not ranked:
        raise GscGymDeterministicError("No OBS chapter sequence aligns to session markers.")
    ranked.sort(key=lambda row: (row[0], row[1], row[2]))
    _negative_count, _median, seed_offset, seed_matches = ranked[0]
    implied = sorted(
        int(row["marker_session_frame"]) - int(row["chapter_frame"])
        for row in seed_matches
    )
    refined_offset = implied[len(implied) // 2]
    candidates = range(
        max(0, refined_offset - tolerance_frames),
        refined_offset + tolerance_frames + 1,
    )
    refined = sorted(
        (
            -len(matches := _chapter_marker_matches(
                chapters,
                markers,
                offset_frame=offset,
                tolerance_frames=tolerance_frames,
            )),
            sum(abs(int(row["residual_frames"])) for row in matches),
            offset,
            matches,
        )
        for offset in candidates
    )[0]
    _negative_count, _error_sum, best_offset, matches = refined
    if len(matches) < minimum_matches:
        raise GscGymDeterministicError(
            f"OBS/session alignment matched {len(matches)} chapters; require {minimum_matches}."
        )
    match_ratio = len(matches) / float(len(chapters))
    chapter_span = chapters[-1] - chapters[0]
    matched_span = int(matches[-1]["chapter_frame"]) - int(matches[0]["chapter_frame"])
    span_ratio = matched_span / float(chapter_span) if chapter_span > 0 else 1.0
    if match_ratio < minimum_match_ratio or span_ratio < minimum_span_ratio:
        raise GscGymDeterministicError(
            "OBS/session chapter coverage is too weak: "
            f"ratio={match_ratio:.3f}, span={span_ratio:.3f}."
        )

    alternative = next(
        (
            row
            for row in ranked
            if abs(int(row[2]) - int(best_offset)) > tolerance_frames * 2
        ),
        None,
    )
    if alternative and -int(alternative[0]) >= len(matches) - 1:
        raise GscGymDeterministicError(
            "OBS/session chapter alignment is ambiguous: "
            f"offsets {best_offset} and {alternative[2]} have nearly equal support."
        )
    absolute = sorted(abs(int(row["residual_frames"])) for row in matches)
    return {
        "schema": "gsc_obs_session_chapter_alignment_v1",
        "status": "pass",
        "offset_frame": int(best_offset),
        "tolerance_frames": int(tolerance_frames),
        "chapter_count": len(chapters),
        "marker_count": len(markers),
        "matched_chapter_count": len(matches),
        "match_ratio": round(match_ratio, 6),
        "span_ratio": round(span_ratio, 6),
        "median_abs_residual_frames": float(absolute[len(absolute) // 2]),
        "max_abs_residual_frames": max(absolute),
        "matches": matches,
    }


def _project_mapper_exit_to_source(
    session_frame: int,
    alignment: dict[str, Any],
    *,
    residual_tolerance_frames: int = SOURCE_PROJECTION_RESIDUAL_TOLERANCE_FRAMES,
    max_bracket_span_frames: int = SOURCE_PROJECTION_MAX_BRACKET_SPAN_FRAMES,
) -> dict[str, Any]:
    """Project one unchaptered mapper exit through two local chapter anchors.

    This is deliberately narrower than a general interpolation fallback.  The
    two nearest matched markers must strictly bracket the mapper exit, be close
    enough to prove a local relationship, and independently agree with the
    alignment's single constant offset within a two-frame rounding allowance.
    """

    if not isinstance(session_frame, int) or session_frame < 0:
        raise GscGymDeterministicError(
            f"Mapper-exit source projection requires a non-negative integer frame: {session_frame!r}."
        )
    if (
        not isinstance(residual_tolerance_frames, int)
        or residual_tolerance_frames < 0
        or residual_tolerance_frames > 2
    ):
        raise GscGymDeterministicError(
            "Mapper-exit source projection residual tolerance must be between 0 and 2 frames."
        )
    if not isinstance(max_bracket_span_frames, int) or max_bracket_span_frames <= 0:
        raise GscGymDeterministicError(
            "Mapper-exit source projection requires a positive bracket-span limit."
        )
    offset = alignment.get("offset_frame")
    if not isinstance(offset, int) or offset < 0:
        raise GscGymDeterministicError(
            "OBS/session alignment lacks its non-negative integer constant offset."
        )

    anchors: list[dict[str, int]] = []
    for raw in alignment.get("matches") or []:
        if not isinstance(raw, dict):
            continue
        marker_frame = raw.get("marker_session_frame")
        chapter_frame = raw.get("chapter_frame")
        event_index = raw.get("event_index")
        if not all(isinstance(value, int) for value in (marker_frame, chapter_frame, event_index)):
            continue
        anchors.append({
            "marker_session_frame": int(marker_frame),
            "chapter_frame": int(chapter_frame),
            "event_index": int(event_index),
            "implied_offset_frame": int(marker_frame) - int(chapter_frame),
        })
    anchors.sort(key=lambda row: (row["marker_session_frame"], row["event_index"]))
    before = next(
        (row for row in reversed(anchors) if row["marker_session_frame"] < session_frame),
        None,
    )
    after = next(
        (row for row in anchors if row["marker_session_frame"] > session_frame),
        None,
    )
    if before is None or after is None:
        raise GscGymDeterministicError(
            "Unchaptered mapper exit is not strictly bracketed by matched OBS chapters."
        )
    bracket_span = after["marker_session_frame"] - before["marker_session_frame"]
    if bracket_span > max_bracket_span_frames:
        raise GscGymDeterministicError(
            "Unchaptered mapper exit chapter bracket is too wide to prove a local "
            f"constant offset: {bracket_span} > {max_bracket_span_frames} frames."
        )

    residuals = [
        before["implied_offset_frame"] - offset,
        after["implied_offset_frame"] - offset,
    ]
    if any(abs(value) > residual_tolerance_frames for value in residuals):
        raise GscGymDeterministicError(
            "Unchaptered mapper exit is bracketed by offsets that do not agree "
            f"with the proven constant offset: residuals={residuals}."
        )
    if abs(before["implied_offset_frame"] - after["implied_offset_frame"]) > residual_tolerance_frames:
        raise GscGymDeterministicError(
            "Unchaptered mapper exit bracket does not have a locally constant "
            f"offset: {before['implied_offset_frame']} vs {after['implied_offset_frame']}."
        )

    source_frame = session_frame - offset
    if source_frame < 0:
        raise GscGymDeterministicError(
            f"Projected mapper exit precedes source frame zero: {source_frame}."
        )
    if not (
        before["chapter_frame"] - residual_tolerance_frames
        < source_frame
        < after["chapter_frame"] + residual_tolerance_frames
    ):
        raise GscGymDeterministicError(
            "Projected mapper exit does not remain inside its matched source bracket."
        )
    return {
        "source_frame": source_frame,
        "session_frame": session_frame,
        "offset_frame": offset,
        "residual_tolerance_frames": residual_tolerance_frames,
        "bracket_span_frames": bracket_span,
        "before": before,
        "after": after,
        "authority": (
            "mapper_exit_projected_through_strictly_bracketing_OBS_chapters_"
            "with_constant_session_offset"
        ),
    }


def map_battle_groups_to_source(
    battles: list[dict[str, Any]],
    alignment: dict[str, Any],
) -> list[dict[str, Any]]:
    by_event_index = {
        int(row["event_index"]): row
        for row in alignment.get("matches") or []
        if isinstance(row, dict) and row.get("event_index") is not None
    }
    mapped: list[dict[str, Any]] = []
    for battle in battles:
        attempts = battle.get("attempts") or []
        if not attempts:
            raise GscGymDeterministicError(
                f"Battle group {battle.get('battle_key')!r} contains no attempts."
            )
        start_event_index = int(attempts[0]["start_event_index"])
        end_event_index = battle.get("direct_end_event_index")
        start_match = by_event_index.get(start_event_index)
        if start_match is None:
            raise GscGymDeterministicError(
                "Exact OBS chapters did not bind the battle start for "
                f"{battle.get('battle_key')}."
            )
        source_start = int(start_match["chapter_frame"])
        end_projection: dict[str, Any] | None = None
        if end_event_index is not None:
            end_match = by_event_index.get(int(end_event_index))
            if end_match is None:
                raise GscGymDeterministicError(
                    "Exact OBS chapters did not bind the direct Win end for "
                    f"{battle.get('battle_key')}."
                )
            source_end = int(end_match["chapter_frame"])
            source_end_authority = "matched_embedded_OBS_chapter_for_exact_battle-end_Win"
        else:
            session_end_frame = battle.get("session_end_frame")
            if not isinstance(session_end_frame, int):
                raise GscGymDeterministicError(
                    "Battle group without a direct Win end lacks its exact mapper-exit frame: "
                    f"{battle.get('battle_key')}."
                )
            end_projection = _project_mapper_exit_to_source(session_end_frame, alignment)
            source_end = int(end_projection["source_frame"])
            source_end_authority = str(end_projection["authority"])
        if source_end <= source_start:
            raise GscGymDeterministicError(
                f"Non-positive source battle range for {battle.get('battle_key')}."
            )
        row = dict(battle)
        row.update({
            "source_start_frame": source_start,
            "source_end_frame": source_end,
            "source_duration_frames": source_end - source_start,
            "source_start_authority": "matched_embedded_OBS_chapter_for_exact_battle-start",
            "source_end_authority": source_end_authority,
            "source_end_projection": end_projection,
            "source_mapping_required": False,
        })
        mapped.append(row)
    return mapped


def map_battle_attempts_to_source(
    attempts: list[dict[str, Any]],
    alignment: dict[str, Any],
) -> list[dict[str, Any]]:
    """Bind every physical attempt to immutable source frames.

    Physical source and BGM ranges remain attempt-level.  A loss followed by a
    retry is therefore still two auditable battle ranges, while downstream A1
    planning inserts a gap only for supplied identity attempt ordinal one.
    """

    by_event_index = {
        int(row["event_index"]): row
        for row in alignment.get("matches") or []
        if isinstance(row, dict) and row.get("event_index") is not None
    }
    mapped: list[dict[str, Any]] = []
    identity_counts: dict[str, int] = {}
    previous_source_end = -1
    for index, attempt in enumerate(attempts, start=1):
        battle_key = str(attempt.get("battle_key") or "").strip()
        if not battle_key:
            raise GscGymDeterministicError(
                f"Physical battle attempt {index} lacks its exact battle key."
            )
        start_event_index = attempt.get("start_event_index")
        if not isinstance(start_event_index, int):
            raise GscGymDeterministicError(
                f"Physical battle attempt {battle_key!r} lacks its start event index."
            )
        start_match = by_event_index.get(start_event_index)
        if start_match is None:
            raise GscGymDeterministicError(
                "Exact OBS chapters did not bind the physical battle start for "
                f"{battle_key}."
            )
        source_start = int(start_match["chapter_frame"])

        direct_end_event_index = attempt.get("direct_end_event_index")
        end_projection: dict[str, Any] | None = None
        if direct_end_event_index is not None:
            if not isinstance(direct_end_event_index, int):
                raise GscGymDeterministicError(
                    f"Physical battle attempt {battle_key!r} has an invalid direct end index."
                )
            end_match = by_event_index.get(direct_end_event_index)
            if end_match is None:
                raise GscGymDeterministicError(
                    "Exact OBS chapters did not bind the direct Win end for physical attempt "
                    f"{battle_key}."
                )
            source_end = int(end_match["chapter_frame"])
            end_authority = "matched_embedded_OBS_chapter_for_exact_battle-end_Win"
        else:
            session_end_frame = attempt.get("session_end_frame")
            if not isinstance(session_end_frame, int):
                raise GscGymDeterministicError(
                    "Physical attempt without a direct Win lacks its exact mapper-exit frame: "
                    f"{battle_key}."
                )
            end_projection = _project_mapper_exit_to_source(session_end_frame, alignment)
            source_end = int(end_projection["source_frame"])
            end_authority = str(end_projection["authority"])
        if source_end <= source_start:
            raise GscGymDeterministicError(
                f"Non-positive source range for physical attempt {battle_key}."
            )
        if source_start < previous_source_end:
            raise GscGymDeterministicError(
                "Physical battle source ranges overlap or are out of order at "
                f"{battle_key}."
            )

        identity_key = battle_key.casefold()
        identity_ordinal = identity_counts.get(identity_key, 0) + 1
        identity_counts[identity_key] = identity_ordinal
        row = dict(attempt)
        row.update({
            "attempt_id": f"{battle_key}:attempt-{identity_ordinal}",
            "canonical_identity": battle_key,
            "identity_attempt_ordinal": identity_ordinal,
            "source_start_frame": source_start,
            "source_end_frame": source_end,
            "source_duration_frames": source_end - source_start,
            "source_start_authority": (
                "matched_embedded_OBS_chapter_for_exact_battle-start"
            ),
            "source_end_authority": end_authority,
            "source_end_projection": end_projection,
            "source_mapping_required": False,
            "final_timeline_mapping_required": True,
        })
        mapped.append(row)
        previous_source_end = source_end
    return mapped


def canonical_carousel_boundary(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the final completed carousel cycle that hands off to Channel EXP.

    The RBY-style overlay can emit more than one complete carousel cycle.  A
    cycle is canonical only when its exact ``view/member-carousel-ended``
    event is followed, in event order, by ``view/channel-exp-bar-shown`` no
    more than two 60-fps frames later.  Old aliases and visual inference are
    intentionally unsupported.
    """

    active_start: _IndexedEvent | None = None
    pairs: list[tuple[_IndexedEvent, _IndexedEvent]] = []
    channel_handoffs: list[_IndexedEvent] = []
    for indexed in _ordered_events(events):
        key = (str(indexed.row.get("category") or ""), str(indexed.row.get("name") or ""))
        if key == CAROUSEL_START_EVENT:
            if active_start is not None:
                raise GscGymDeterministicError(
                    "Nested member-carousel-started events make the canonical boundary ambiguous: "
                    f"events {active_start.index} and {indexed.index}."
                )
            active_start = indexed
        elif key == CAROUSEL_END_EVENT:
            if active_start is None:
                raise GscGymDeterministicError(
                    f"Orphan member-carousel-ended event at index {indexed.index}."
                )
            if indexed.elapsed_ms <= active_start.elapsed_ms:
                raise GscGymDeterministicError(
                    "Member Carousel cycle must have positive elapsed duration: "
                    f"events {active_start.index} and {indexed.index}."
                )
            pairs.append((active_start, indexed))
            active_start = None
        elif key == CHANNEL_EXP_EVENT:
            channel_handoffs.append(indexed)

    if active_start is not None:
        raise GscGymDeterministicError(
            f"Open member-carousel-started event at index {active_start.index}."
        )

    if not pairs:
        return None

    # Only the last completed cycle is eligible.  In particular, do not fall
    # back to an earlier well-formed cycle when a later completed display did
    # not perform the required Channel EXP handoff.  An open later cycle was
    # already rejected above.
    cycle_index = len(pairs) - 1
    start, end = pairs[cycle_index]
    tolerance_ms = CAROUSEL_EXP_HANDOFF_TOLERANCE_FRAMES * 1000.0 / 60.0
    handoff = next(
        (
            candidate
            for candidate in channel_handoffs
            if candidate.index > end.index
            and 0.0 <= candidate.elapsed_ms - end.elapsed_ms <= tolerance_ms
        ),
        None,
    )
    if handoff is None:
        return None

    start_frame = event_frame(start.row)
    end_frame = event_frame(end.row)
    handoff_frame = event_frame(handoff.row)
    if handoff_frame - end_frame > CAROUSEL_EXP_HANDOFF_TOLERANCE_FRAMES:
        raise GscGymDeterministicError(
            "Member Carousel/Channel EXP handoff exceeds its strict frame tolerance."
        )
    return {
        "event_index": start.index,
        "category": CAROUSEL_START_EVENT[0],
        "name": CAROUSEL_START_EVENT[1],
        "session_elapsed_ms": start.elapsed_ms,
        "session_frame": start_frame,
        "end_event_index": end.index,
        "end_session_elapsed_ms": end.elapsed_ms,
        "end_session_frame": end_frame,
        "channel_exp_event_index": handoff.index,
        "channel_exp_session_elapsed_ms": handoff.elapsed_ms,
        "channel_exp_session_frame": handoff_frame,
        "handoff_delta_ms": round(handoff.elapsed_ms - end.elapsed_ms, 6),
        "handoff_delta_frames": handoff_frame - end_frame,
        "handoff_tolerance_frames": CAROUSEL_EXP_HANDOFF_TOLERANCE_FRAMES,
        "completed_cycle_count": len(pairs),
        "qualifying_cycle_count": 1,
        "selected_cycle_ordinal": cycle_index + 1,
        "boundary_authority": (
            "final_completed_view_member-carousel_pair_with_channel_exp_handoff"
        ),
        "source_mapping_required": True,
        "final_timeline_mapping_required": True,
    }


def validate_mapped_geometry(
    gaps: list[dict[str, Any]],
    intros: list[dict[str, Any]],
) -> None:
    for gap in gaps:
        start = gap.get("record_start_frame")
        end = gap.get("record_end_frame")
        if not isinstance(start, int) or not isinstance(end, int) or end - start != BATTLE_GAP_FRAMES:
            raise GscGymDeterministicError(
                f"Mapped A1 gap is not exactly {BATTLE_GAP_FRAMES} frames: {gap!r}"
            )
    gap_end_by_key = {str(row.get("battle_key")): row.get("record_end_frame") for row in gaps}
    for intro in intros:
        start = intro.get("record_start_frame")
        end = intro.get("record_end_frame")
        key = str(intro.get("battle_key"))
        if not isinstance(start, int) or not isinstance(end, int) or end - start != BATTLE_INTRO_FRAMES:
            raise GscGymDeterministicError(
                f"Mapped V2 intro is not exactly {BATTLE_INTRO_FRAMES} frames: {intro!r}"
            )
        if gap_end_by_key.get(key) != end:
            raise GscGymDeterministicError(
                f"V2 intro for {key!r} does not end at its A1 gap end."
            )


def _leader_slug(identity: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", identity.casefold()).strip("-")
    # The overlay checkpoint is ``surge`` while the approved asset is named
    # ``lt-surge-battle-intro.mov``.  Normalize every observed spelling to the
    # one canonical asset stem instead of depending on which identity field
    # happened to win the leader-selection precedence above.
    if slug in {"surge", "lt-surge", "ltsurge", "lieutenant-surge"}:
        return "lt-surge"
    return slug


def _rival_intro_asset_filename(
    trainer_class: str,
    trainer_id: int,
    *,
    starter_type_override: str | None = None,
) -> str:
    locations = RIVAL_LOCATION_BY_TRAINER_CLASS.get(trainer_class)
    if locations is None or trainer_id not in locations:
        raise GscGymDeterministicError(
            "No deterministic rival asset mapping exists for "
            f"{trainer_class}/{trainer_id}."
        )
    starter_types = RIVAL_STARTER_TYPE_BY_TRAINER_CLASS[trainer_class]
    starter_type = starter_type_override or starter_types.get(trainer_id)
    if starter_type not in RIVAL_INITIAL_ASSET_SUFFIX_BY_STARTER_TYPE:
        raise GscGymDeterministicError(
            "No ROM-table rival starter mapping exists for "
            f"{trainer_class}/{trainer_id}."
        )
    location = locations[trainer_id]
    suffix = (
        RIVAL_INITIAL_ASSET_SUFFIX_BY_STARTER_TYPE[starter_type]
        if location == "initial"
        else starter_type
    )
    return f"silver-{location}-{suffix}-battle-intro.mov"


def build_overlay_intro_plan(
    battles: list[dict[str, Any]],
    *,
    leaders_dir: Path | None = None,
    rivals_dir: Path | None = None,
    intro_library_manifest: Path | None = None,
    rival_starter_type: str | None = None,
    boundary_is_final_timeline: bool = True,
) -> list[dict[str, Any]]:
    if rival_starter_type is not None and rival_starter_type not in {"grass", "fire", "water"}:
        raise GscGymDeterministicError("Rival starter type must be grass, fire, or water.")
    if intro_library_manifest is not None:
        if leaders_dir is not None or rivals_dir is not None:
            raise GscGymDeterministicError(
                "Use either the approved intro-library manifest or legacy diagnostic "
                "leader/rival directories, not both."
            )
        try:
            intro_library = load_gsc_gym_intro_library(intro_library_manifest)
        except GscGymIntroLibraryError as exc:
            raise GscGymDeterministicError(str(exc)) from exc
    else:
        intro_library = None
        if leaders_dir is None or rivals_dir is None:
            raise GscGymDeterministicError(
                "Battle intros require the approved intro-library manifest; explicit "
                "leader/rival directories are supported only as diagnostic compatibility."
            )
    result: list[dict[str, Any]] = []
    for battle in first_major_battles(battles):
        boundary_value = (
            battle.get("final_timeline_start_frame")
            if boundary_is_final_timeline
            else battle.get("session_start_frame", battle.get("frame"))
        )
        if not isinstance(boundary_value, int):
            raise GscGymDeterministicError(
                f"Battle {battle.get('battle_key')!r} lacks its required boundary frame."
            )
        battle_start = int(boundary_value)
        if boundary_is_final_timeline and battle_start < BATTLE_INTRO_FRAMES:
            raise GscGymDeterministicError(
                f"Battle at frame {battle_start} is too early for the 300-frame V2 intro."
            )
        if battle["role"] == "rival":
            trainer_class = _normalized_trainer_class(battle.get("trainer_class"))
            trainer_id = _trainer_id(battle.get("trainer_id"))
            asset_filename = _rival_intro_asset_filename(
                trainer_class,
                trainer_id,
                starter_type_override=rival_starter_type,
            )
            variant_id = asset_filename.removesuffix("-battle-intro.mov")
            if intro_library is not None:
                try:
                    approved_master = intro_library.resolve(
                        variant_id,
                        expected_category="rival",
                    )
                except GscGymIntroLibraryError as exc:
                    raise GscGymDeterministicError(str(exc)) from exc
                asset = approved_master.path
            else:
                approved_master = None
                assert rivals_dir is not None
                asset = rivals_dir / asset_filename
        else:
            leader_asset_identity = (
                battle.get("checkpoint_key")
                or str(battle.get("trainer_class") or "").replace("_", " ")
                or battle["identity"]
            )
            variant_id = _leader_slug(str(leader_asset_identity))
            if intro_library is not None:
                try:
                    approved_master = intro_library.resolve(
                        variant_id,
                        expected_category="leader",
                    )
                except GscGymIntroLibraryError as exc:
                    raise GscGymDeterministicError(str(exc)) from exc
                asset = approved_master.path
            else:
                approved_master = None
                assert leaders_dir is not None
                asset = leaders_dir / f"{variant_id}-battle-intro.mov"
        if not asset.is_file() or asset.stat().st_size <= 0:
            raise GscGymDeterministicError(
                f"Missing deterministic {battle['role']} intro for {battle['identity']}: {asset}"
            )
        placement = {
            "identity": battle["identity"],
            "battle_key": battle.get("battle_key"),
            "role": battle["role"],
            "trainer_class": battle.get("trainer_class"),
            "trainer_id": battle.get("trainer_id"),
            "asset": str(asset.resolve()),
            "video_track": 2,
            "duration_frames": BATTLE_INTRO_FRAMES,
            "record_start_offset_from_battle": -BATTLE_INTRO_FRAMES,
            "record_end_offset_from_battle": 0,
            "a1_gap_start_offset_from_battle": -BATTLE_GAP_FRAMES,
            "a1_gap_end_offset_from_battle": 0,
            "ends_at_a1_gap_end": True,
            "v1_policy": "continuous_under_v2_overlay",
            "audio_policy": "silent_video_only",
            "source_session_frame": int(
                battle.get("session_start_frame", battle.get("frame", battle_start))
            ),
            "mapping_required": not boundary_is_final_timeline,
        }
        if approved_master is not None:
            placement["asset_approval"] = approved_master.approval_evidence()
        else:
            placement["asset_approval"] = {
                "schema": "gsc_gym_intro_legacy_directory_diagnostic_v1",
                "status": "diagnostic_only",
                "variant_id": variant_id,
                "master_path": str(asset.resolve()),
            }
        if boundary_is_final_timeline:
            placement.update({
                "record_start_frame": battle_start - BATTLE_INTRO_FRAMES,
                "record_end_frame": battle_start,
                "a1_gap_start_frame": battle_start - BATTLE_GAP_FRAMES,
                "a1_gap_end_frame": battle_start,
                "boundary_authority": "mapped_final_timeline_battle_start",
            })
        else:
            placement.update({
                "record_start_frame": None,
                "record_end_frame": None,
                "a1_gap_start_frame": None,
                "a1_gap_end_frame": None,
                "boundary_authority": "pending_source_to_final_timeline_mapping",
            })
        result.append(placement)
    return result


def choose_nonbattle_tracks(bgm_dir: Path, *, seed: str) -> list[Path]:
    missing = [
        name for name in (*POST_FINAL_REQUIRED_TRACKS, OUTRO_TRACK)
        if not (bgm_dir / name).is_file()
    ]
    if missing:
        raise GscGymDeterministicError(
            "Missing required deterministic non-battle BGM asset(s): "
            + ", ".join(missing)
        )
    blocked = {name.casefold() for name in NONBATTLE_RANDOM_RESERVED_TRACKS}
    pool = sorted(
        (path for path in bgm_dir.glob("*.mp3") if path.name.casefold() not in blocked),
        key=lambda path: path.name.casefold(),
    )
    if not pool:
        raise GscGymDeterministicError("No eligible non-battle BGM remains after reservations.")
    random.Random(int(seed, 16)).shuffle(pool)
    return pool


def choose_battle_tracks(paths: list[Path], *, count: int, seed: str) -> list[Path]:
    """Deterministic shuffle bags with complete first bags and no repeats."""

    pool = sorted(paths, key=lambda path: path.name.casefold())
    if not pool:
        raise GscGymDeterministicError("Battle BGM pool is empty.")
    rng = random.Random(int(seed, 16))
    result: list[Path] = []
    while len(result) < count:
        bag = list(pool)
        rng.shuffle(bag)
        if result and len(bag) > 1 and bag[0] == result[-1]:
            bag[0], bag[1] = bag[1], bag[0]
        result.extend(bag)
    selected = result[:count]
    if any(left == right for left, right in zip(selected, selected[1:])):
        raise GscGymDeterministicError("Battle BGM shuffle produced an immediate repeat.")
    return selected


def validate_zero_llm_workflow(workflow: dict[str, Any]) -> None:
    if workflow.get("id") != WORKFLOW_ID:
        raise GscGymDeterministicError("Wrong workflow selected for GSC deterministic run.")
    if workflow.get("llm_tasks") or workflow.get("review_surfaces"):
        raise GscGymDeterministicError("GSC deterministic workflow must have no LLM or review surfaces.")
    tooling = workflow.get("tooling") if isinstance(workflow.get("tooling"), dict) else {}
    if float(tooling.get("runtime_limit_seconds") or 0) != MAX_FULL_RUN_SECONDS:
        raise GscGymDeterministicError(
            f"GSC deterministic workflow runtime must be exactly {MAX_FULL_RUN_SECONDS:.0f} seconds."
        )
    if float(tooling.get("outer_process_tree_watchdog_seconds") or 0) != MAX_FULL_RUN_SECONDS:
        raise GscGymDeterministicError(
            "GSC deterministic workflow must bind its outer process-tree watchdog "
            f"to exactly {MAX_FULL_RUN_SECONDS:.0f} seconds."
        )
    required_bgm_contract = {
        "post_battle_bgm_transition_policy": WORKFLOW_POST_BATTLE_BGM_POLICY,
        "nonbattle_bgm_repeat_policy": WORKFLOW_NONBATTLE_REPEAT_POLICY,
        "post_final_bgm_sequence": WORKFLOW_POST_FINAL_BGM_SEQUENCE,
        "physical_attempt_bgm_start_contract": (
            WORKFLOW_PHYSICAL_ATTEMPT_BGM_START_CONTRACT
        ),
    }
    mismatched_bgm_fields = {
        key: {"expected": expected, "actual": tooling.get(key)}
        for key, expected in required_bgm_contract.items()
        if tooling.get(key) != expected
    }
    if mismatched_bgm_fields:
        raise GscGymDeterministicError(
            "GSC deterministic workflow BGM contract is missing or changed: "
            f"{mismatched_bgm_fields}."
        )
    required_battle_geometry_contract = {
        "battle_population": WORKFLOW_BATTLE_POPULATION_POLICY,
        "battle_a1_gap_geometry": WORKFLOW_BATTLE_GAP_GEOMETRY,
        "same_trainer_retry_contract": WORKFLOW_SAME_TRAINER_RETRY_CONTRACT,
        "party_member_ko_contract": WORKFLOW_PARTY_MEMBER_KO_CONTRACT,
        "battle_start_candidate_audit": WORKFLOW_BATTLE_START_CANDIDATE_AUDIT,
    }
    mismatched_battle_fields = {
        key: {"expected": expected, "actual": tooling.get(key)}
        for key, expected in required_battle_geometry_contract.items()
        if tooling.get(key) != expected
    }
    if mismatched_battle_fields:
        raise GscGymDeterministicError(
            "GSC deterministic workflow battle lifecycle/geometry contract is "
            f"missing or changed: {mismatched_battle_fields}."
        )
    required_fairlight_contract = {
        "fairlight_preset": FAIRLIGHT_PRESET_NAME,
        "fairlight_preset_type": FAIRLIGHT_PRESET_TYPE,
        "fairlight_final_stage_contract": WORKFLOW_FAIRLIGHT_FINAL_STAGE_CONTRACT,
    }
    mismatched_fairlight_fields = {
        key: {"expected": expected, "actual": tooling.get(key)}
        for key, expected in required_fairlight_contract.items()
        if tooling.get(key) != expected
    }
    if mismatched_fairlight_fields:
        raise GscGymDeterministicError(
            "GSC deterministic workflow Fairlight final-stage contract is missing or changed: "
            f"{mismatched_fairlight_fields}."
        )
    steps = workflow.get("steps")
    if not isinstance(steps, list) or len(steps) != 1:
        raise GscGymDeterministicError(
            "GSC deterministic workflow must expose exactly one full-build step."
        )
    step = steps[0]
    if (
        not isinstance(step, dict)
        or str(step.get("id") or "").casefold() != "full"
        or str(step.get("tool") or "").casefold() != "deterministic_gsc_gym_full"
        or str(step.get("kind") or "").casefold() != "script"
        or step.get("requires_resolve") is not True
        or step.get("llm_task")
        or step.get("pause_after")
        or "fairlight_report" not in list(step.get("artifacts_out") or [])
    ):
        raise GscGymDeterministicError(
            "GSC deterministic workflow must use only the closed full-build script "
            "entrypoint and require its Fairlight report artifact."
        )
