"""Deterministic source-to-record planning for the GSC Gym FCPXML builder.

This module accepts the retained source selections from a zero-LLM
auto-editor FCPXML and explicit source-frame boundaries.  It performs no media
analysis.  First-attempt battle gaps are real timeline inserts placed only at
immutable joins between adjacent auto-editor segments; same-trainer retries
keep their physical ranges without another gap.  A battle start inside a retained
segment maps to the nearest valid adjacent join; an exactly equidistant result
fails closed instead of guessing.  There is no mid-segment split fallback.
Boundaries inside removed source gaps map to their unique contiguous edit join;
the carousel continues to use an exact or next retained boundary.
"""

from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal, Mapping

from .gsc_gym_fcpxml import (
    BATTLE_GAP_FRAMES,
    BATTLE_INTRO_FRAMES,
    FPS,
    HEIGHT,
    OPENING_FRAMES,
    WIDTH,
    BattleSpec,
    CarouselSlice,
    CarouselSpec,
    DialogueInterval,
    IntroOverlay,
    SourceInterval,
)


SCHEMA = "gsc_gym_fcpxml_geometry_plan_v2"
AUDIT_SCHEMA = "gsc_gym_fcpxml_geometry_audit_v2"
MAX_BOUNDARY_SNAP_FRAMES = 600
BATTLE_GAP_POLICY = (
    "real_60f_timeline_insert_only_for_identity_attempt_ordinal_1_at_adjacent_"
    "autoeditor_a1_boundary_preserve_all_a1_source_frames_"
    "with_incoming_v1_bridge_no_retry_gap"
)
BATTLE_GAP_INSERTS_TIMELINE_FRAMES = True
# The incoming V1 bridge is allowed to reuse source already present in the
# outgoing V1 segment when the auto-editor source cut is shorter than 60 frames.
BATTLE_GAP_DUPLICATES_V1_PREROLL = True
BATTLE_BOUNDARY_POLICY = (
    "battle_start_exact_adjacent_join_else_inside_nearest_unique_valid_"
    "adjacent_join_equidistant_fail_closed_else_removed_gap_unique_"
    "adjacent_join_no_midclip_split;battle_end_exact_retained_else_"
    "removed_gap_exact_contiguous_edit_join;carousel_exact_retained_"
    "else_next_start"
)


class GscGymGeometryError(ValueError):
    """Raised when source geometry cannot be mapped without inference."""


@dataclass(frozen=True)
class RetainedSourceInterval:
    record_start_frame: int
    source_start_frame: int
    duration_frames: int
    label: str

    @property
    def record_end_frame(self) -> int:
        return self.record_start_frame + self.duration_frames

    @property
    def source_end_frame(self) -> int:
        return self.source_start_frame + self.duration_frames


@dataclass(frozen=True)
class AutoEditorRetained:
    fcpxml_version: str
    source_ref: str
    source_name: str
    source_uri: str
    source_start_frame: int
    source_duration_frames: int
    intervals: tuple[RetainedSourceInterval, ...]
    record_duration_frames: int
    fcpxml_sha256: str


@dataclass(frozen=True)
class BattleAttemptSourceBoundary:
    attempt_id: str
    canonical_identity: str
    attempt_ordinal: int
    role: Literal["leader", "rival", "trainer"]
    source_start_frame: int
    source_end_frame: int
    start_authority: str
    end_authority: str

    @property
    def battle_id(self) -> str:
        """Compatibility name used by the assembler and older plan consumers."""

        return self.attempt_id


@dataclass(frozen=True)
class CarouselSourceBoundary:
    source_frame: int
    authority: str


@dataclass(frozen=True)
class BoundaryCandidateEvidence:
    side: Literal["preceding", "following"]
    effective_source_frame: int
    original_record_frame: int
    snap_delta_frames: int
    absolute_distance_frames: int
    valid: bool
    rejection_reason: str | None


@dataclass(frozen=True)
class BoundaryMapping:
    raw_source_frame: int
    effective_source_frame: int
    original_record_frame: int
    snap_delta_frames: int
    policy: str
    input_authority: str
    effective_authority: str
    candidates: tuple[BoundaryCandidateEvidence, ...] = ()


@dataclass(frozen=True)
class PlannedBattleAttempt:
    attempt_id: str
    canonical_identity: str
    attempt_ordinal: int
    role: Literal["leader", "rival", "trainer"]
    intro_eligible: bool
    a1_gap_eligible: bool
    source_start_frame: int
    source_end_frame: int
    effective_source_start_frame: int
    effective_source_end_frame: int
    start_snap_delta_frames: int
    end_snap_delta_frames: int
    start_mapping_policy: str
    end_mapping_policy: str
    start_effective_authority: str
    end_effective_authority: str
    start_candidate_evidence: tuple[BoundaryCandidateEvidence, ...]
    original_record_start_frame: int
    original_record_end_frame: int
    final_start_frame: int
    final_end_frame: int
    gap_start_frame: int
    gap_end_frame: int
    start_authority: str
    end_authority: str

    @property
    def battle_id(self) -> str:
        """Compatibility name used by the assembler and older plan consumers."""

        return self.attempt_id


# Compatibility aliases for the first internal prototype.  Both aliases now
# carry explicit attempt identity and ordinal fields; no grouping is performed.
BattleSourceBoundary = BattleAttemptSourceBoundary
PlannedBattle = PlannedBattleAttempt


@dataclass(frozen=True)
class GscGymGeometryPlan:
    body_v1: tuple[SourceInterval, ...]
    dialogue_a1: tuple[DialogueInterval, ...]
    battles: tuple[PlannedBattleAttempt, ...]
    carousel: CarouselSpec
    carousel_mapping: BoundaryMapping
    manifest: dict[str, Any]
    structural_audit: dict[str, Any]

    def assembler_battles(
        self,
        intro_overlays: Mapping[str, IntroOverlay],
    ) -> tuple[BattleSpec, ...]:
        """Bind explicit media overlays to already-final battle geometry."""

        expected_major = {item.battle_id for item in self.battles if item.intro_eligible}
        provided = set(intro_overlays)
        if provided != expected_major:
            missing = sorted(expected_major - provided)
            unexpected = sorted(provided - expected_major)
            raise GscGymGeometryError(
                "Intro overlay binding must exactly match major battles; "
                f"missing={missing}, unexpected={unexpected}."
            )
        rows: list[BattleSpec] = []
        for item in self.battles:
            intro = intro_overlays.get(item.battle_id)
            if intro is not None and intro.kind != item.role:
                raise GscGymGeometryError(
                    f"Intro kind {intro.kind!r} does not match battle role {item.role!r} "
                    f"for {item.battle_id!r}."
                )
            rows.append(
                BattleSpec(
                    battle_id=item.battle_id,
                    role=item.role,
                    start_frame=item.final_start_frame,
                    end_frame=item.final_end_frame,
                    intro=intro,
                    intro_eligible=item.intro_eligible,
                    a1_gap_eligible=item.a1_gap_eligible,
                    canonical_identity=item.canonical_identity,
                    attempt_ordinal=item.attempt_ordinal,
                )
            )
        return tuple(rows)


def _int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GscGymGeometryError(f"{label} must be an integer >= {minimum}; got {value!r}.")
    return value


def _positive(value: object, label: str) -> int:
    return _int(value, label, minimum=1)


def _frames(value: str | None, label: str) -> int:
    if not value or not value.endswith("s"):
        raise GscGymGeometryError(f"{label} is not an FCPXML time: {value!r}.")
    try:
        rendered = Fraction(value[:-1]) * FPS
    except (ValueError, ZeroDivisionError) as exc:
        raise GscGymGeometryError(f"{label} is not an FCPXML time: {value!r}.") from exc
    if rendered.denominator != 1:
        raise GscGymGeometryError(f"{label} is not frame-aligned at {FPS} fps: {value!r}.")
    return rendered.numerator


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def parse_autoeditor_fcpxml(
    xml: str,
    *,
    source_ref: str | None = None,
) -> AutoEditorRetained:
    """Parse one flat, 4K60 auto-editor spine into retained source intervals.

    The parser accepts FCPXML 1.10 and 1.11 because current auto-editor output
    uses both.  It rejects mixed media, connected clips, gaps, noncontiguous
    record offsets, source repeats, and non-frame-aligned timing.
    """

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise GscGymGeometryError(f"Invalid auto-editor FCPXML: {exc}.") from exc
    version = str(root.get("version") or "")
    if version not in {"1.10", "1.11"}:
        raise GscGymGeometryError(f"Auto-editor FCPXML version must be 1.10 or 1.11; got {version!r}.")

    resources = next((item for item in list(root) if _tag(item) == "resources"), None)
    sequences = [item for item in root.iter() if _tag(item) == "sequence"]
    if resources is None or len(sequences) != 1:
        raise GscGymGeometryError("Auto-editor FCPXML requires one resources block and one sequence.")
    sequence = sequences[0]
    format_ref = str(sequence.get("format") or "")
    formats = {
        str(item.get("id") or ""): item
        for item in list(resources)
        if _tag(item) == "format" and item.get("id")
    }
    fmt = formats.get(format_ref)
    if (
        fmt is None
        or fmt.get("frameDuration") != "1/60s"
        or fmt.get("width") != str(WIDTH)
        or fmt.get("height") != str(HEIGHT)
    ):
        raise GscGymGeometryError("Auto-editor sequence must be exact 3840x2160 progressive 60 fps.")

    spines = [item for item in list(sequence) if _tag(item) == "spine"]
    if len(spines) != 1:
        raise GscGymGeometryError("Auto-editor sequence requires exactly one direct spine.")
    direct = list(spines[0])
    if not direct:
        raise GscGymGeometryError("Auto-editor spine contains no retained clips.")
    if any(_tag(item) != "asset-clip" or item.get("lane") is not None or list(item) for item in direct):
        raise GscGymGeometryError(
            "Auto-editor spine must contain only flat, primary asset-clips with no connected children."
        )

    assets = {
        str(item.get("id") or ""): item
        for item in list(resources)
        if _tag(item) == "asset" and item.get("id")
    }
    direct_refs = {str(item.get("ref") or "") for item in direct}
    video_refs = {
        ref for ref in direct_refs if ref in assets and assets[ref].get("hasVideo") == "1"
    }
    if source_ref is None:
        if len(video_refs) != 1:
            raise GscGymGeometryError(
                f"Auto-editor source asset is ambiguous; video refs={sorted(video_refs)}."
            )
        selected_ref = next(iter(video_refs))
    else:
        selected_ref = source_ref.strip()
        if not selected_ref or selected_ref not in video_refs:
            raise GscGymGeometryError(
                f"Requested source_ref {source_ref!r} is not the sole retained video source."
            )
    if direct_refs != {selected_ref}:
        raise GscGymGeometryError(
            f"Auto-editor spine mixes source refs; expected only {selected_ref!r}, got {sorted(direct_refs)}."
        )

    asset = assets[selected_ref]
    source_name = str(asset.get("name") or "").strip()
    source_start = _frames(asset.get("start") or "0s", "source asset start")
    source_duration = _positive(_frames(asset.get("duration"), "source asset duration"), "source asset duration")
    media_reps = [item for item in list(asset) if _tag(item) == "media-rep"]
    if len(media_reps) != 1 or not str(media_reps[0].get("src") or "").strip():
        raise GscGymGeometryError("Auto-editor source asset requires one original-media URI.")
    source_uri = str(media_reps[0].get("src"))
    tc_start = _frames(sequence.get("tcStart") or "0s", "sequence tcStart")

    intervals: list[RetainedSourceInterval] = []
    record_cursor = 0
    previous_source_end = source_start
    for index, item in enumerate(direct, start=1):
        record_start = _frames(item.get("offset"), f"clip {index} offset") - tc_start
        duration = _positive(_frames(item.get("duration"), f"clip {index} duration"), f"clip {index} duration")
        clip_source_start = _frames(item.get("start"), f"clip {index} start")
        if record_start != record_cursor:
            raise GscGymGeometryError(
                f"Auto-editor record geometry is not contiguous at clip {index}: "
                f"{record_start} != {record_cursor}."
            )
        if clip_source_start < previous_source_end:
            raise GscGymGeometryError(
                "Auto-editor retained source intervals overlap or repeat, creating "
                f"ambiguous source mapping at clip {index}."
            )
        if (
            clip_source_start < source_start
            or clip_source_start + duration > source_start + source_duration
        ):
            raise GscGymGeometryError(f"Auto-editor clip {index} exceeds its source asset bounds.")
        intervals.append(
            RetainedSourceInterval(
                record_start_frame=record_start,
                source_start_frame=clip_source_start,
                duration_frames=duration,
                label=f"auto-editor retained {index:04d}",
            )
        )
        record_cursor += duration
        previous_source_end = clip_source_start + duration

    return AutoEditorRetained(
        fcpxml_version=version,
        source_ref=selected_ref,
        source_name=source_name,
        source_uri=source_uri,
        source_start_frame=source_start,
        source_duration_frames=source_duration,
        intervals=tuple(intervals),
        record_duration_frames=record_cursor,
        fcpxml_sha256=hashlib.sha256(xml.encode("utf-8")).hexdigest().upper(),
    )


def _validate_retained(retained: AutoEditorRetained) -> None:
    if not retained.intervals:
        raise GscGymGeometryError("No retained auto-editor intervals were provided.")
    _int(retained.source_start_frame, "source_start_frame")
    _positive(retained.source_duration_frames, "source_duration_frames")
    if not retained.source_ref.strip() or not retained.source_name.strip() or not retained.source_uri.strip():
        raise GscGymGeometryError("Retained source identity is incomplete.")
    record_cursor = 0
    previous_source_end = retained.source_start_frame
    source_limit = retained.source_start_frame + retained.source_duration_frames
    for index, item in enumerate(retained.intervals, start=1):
        _positive(item.duration_frames, f"retained[{index}].duration_frames")
        if item.record_start_frame != record_cursor:
            raise GscGymGeometryError(
                f"Retained record geometry is not contiguous at interval {index}."
            )
        if item.source_start_frame < previous_source_end:
            raise GscGymGeometryError(
                "Retained source intervals overlap or repeat, creating ambiguous source mapping "
                f"at interval {index}."
            )
        if (
            item.source_start_frame < retained.source_start_frame
            or item.source_end_frame > source_limit
        ):
            raise GscGymGeometryError(f"Retained interval {index} exceeds source bounds.")
        if not item.label.strip():
            raise GscGymGeometryError(f"Retained interval {index} has no label.")
        record_cursor = item.record_end_frame
        previous_source_end = item.source_end_frame
    if retained.record_duration_frames != record_cursor:
        raise GscGymGeometryError(
            f"record_duration_frames={retained.record_duration_frames} but intervals total {record_cursor}."
        )


def _checked_mapping(
    *,
    raw_source_frame: int,
    effective_source_frame: int,
    original_record_frame: int,
    policy: str,
    authority: str,
    label: str,
    max_snap_frames: int,
    candidates: tuple[BoundaryCandidateEvidence, ...] = (),
) -> BoundaryMapping:
    delta = effective_source_frame - raw_source_frame
    if abs(delta) > max_snap_frames:
        raise GscGymGeometryError(
            f"{label} deterministic snap is {delta} frames, exceeding maximum "
            f"absolute delta {max_snap_frames}."
        )
    return BoundaryMapping(
        raw_source_frame=raw_source_frame,
        effective_source_frame=effective_source_frame,
        original_record_frame=original_record_frame,
        snap_delta_frames=delta,
        policy=policy,
        input_authority=authority,
        effective_authority=f"{authority};deterministic_mapping:{policy}",
        candidates=candidates,
    )


def _adjacent_join(
    retained: AutoEditorRetained,
    record_frame: int,
    *,
    label: str,
) -> tuple[RetainedSourceInterval, RetainedSourceInterval]:
    """Return the unique outgoing/incoming auto-editor pair at a record join."""

    outgoing = [
        item for item in retained.intervals if item.record_end_frame == record_frame
    ]
    incoming = [
        item for item in retained.intervals if item.record_start_frame == record_frame
    ]
    if len(outgoing) != 1 or len(incoming) != 1:
        raise GscGymGeometryError(
            f"{label} record frame {record_frame} is not one unique boundary between "
            "adjacent auto-editor segments "
            f"(outgoing={len(outgoing)}, incoming={len(incoming)})."
        )
    return outgoing[0], incoming[0]


def _map_battle_start(
    retained: AutoEditorRetained,
    source_frame: int,
    *,
    end_record_frame: int,
    minimum_record_frame: int,
    requires_gap: bool,
    label: str,
    authority: str,
    max_snap_frames: int,
) -> BoundaryMapping:
    exact_starts = [
        item for item in retained.intervals if item.source_start_frame == source_frame
    ]
    if len(exact_starts) > 1:
        raise GscGymGeometryError(
            f"{label} source frame {source_frame} has ambiguous retained interval starts."
        )
    if exact_starts:
        item = exact_starts[0]
        _adjacent_join(retained, item.record_start_frame, label=label)
        return _checked_mapping(
            raw_source_frame=source_frame,
            effective_source_frame=source_frame,
            original_record_frame=item.record_start_frame,
            policy="battle_start_exact_retained_interval_start",
            authority=authority,
            label=label,
            max_snap_frames=max_snap_frames,
        )

    exact_ends = [
        item for item in retained.intervals if item.source_end_frame == source_frame
    ]
    exact_end_records = sorted({item.record_end_frame for item in exact_ends})
    if len(exact_end_records) > 1:
        raise GscGymGeometryError(
            f"{label} source frame {source_frame} has ambiguous retained interval ends."
        )
    if exact_end_records:
        _adjacent_join(retained, exact_end_records[0], label=label)
        return _checked_mapping(
            raw_source_frame=source_frame,
            effective_source_frame=source_frame,
            original_record_frame=exact_end_records[0],
            policy="battle_start_exact_retained_interval_end",
            authority=authority,
            label=label,
            max_snap_frames=max_snap_frames,
        )

    inside = [
        item
        for item in retained.intervals
        if item.source_start_frame < source_frame < item.source_end_frame
    ]
    if len(inside) > 1:
        raise GscGymGeometryError(
            f"{label} source frame {source_frame} has ambiguous containing retained intervals."
        )
    if inside:
        item = inside[0]
        candidates: list[tuple[int, int, int, str]] = []
        candidate_evidence: list[BoundaryCandidateEvidence] = []

        def consider(
            *,
            side: Literal["preceding", "following"],
            effective_source_frame: int,
            record_frame: int,
            policy: str,
        ) -> None:
            delta = effective_source_frame - source_frame
            rejection_reasons: list[str] = []
            if abs(delta) > max_snap_frames:
                rejection_reasons.append("exceeds_max_snap_frames")
            if not minimum_record_frame <= record_frame < end_record_frame:
                rejection_reasons.append("violates_attempt_order_or_positive_duration")
            outgoing_count = sum(
                interval.record_end_frame == record_frame
                for interval in retained.intervals
            )
            incoming_count = sum(
                interval.record_start_frame == record_frame
                for interval in retained.intervals
            )
            incoming: RetainedSourceInterval | None = None
            if outgoing_count != 1 or incoming_count != 1:
                rejection_reasons.append("not_one_unique_adjacent_autoeditor_join")
            else:
                _, incoming = _adjacent_join(retained, record_frame, label=label)
            if (
                requires_gap
                and incoming is not None
                and incoming.source_start_frame - BATTLE_GAP_FRAMES
                < retained.source_start_frame
            ):
                rejection_reasons.append("insufficient_incoming_left_handle_for_gap")
            valid = not rejection_reasons
            candidate_evidence.append(
                BoundaryCandidateEvidence(
                    side=side,
                    effective_source_frame=effective_source_frame,
                    original_record_frame=record_frame,
                    snap_delta_frames=delta,
                    absolute_distance_frames=abs(delta),
                    valid=valid,
                    rejection_reason=(
                        ";".join(rejection_reasons)
                        if rejection_reasons
                        else None
                    ),
                )
            )
            if valid:
                candidates.append(
                    (abs(delta), effective_source_frame, record_frame, policy)
                )

        consider(
            side="preceding",
            effective_source_frame=item.source_start_frame,
            record_frame=item.record_start_frame,
            policy="battle_start_inside_retained_nearest_preceding_adjacent_join",
        )
        consider(
            side="following",
            effective_source_frame=item.source_end_frame,
            record_frame=item.record_end_frame,
            policy="battle_start_inside_retained_nearest_following_adjacent_join",
        )

        if not candidates:
            raise GscGymGeometryError(
                f"{label} has no adjacent auto-editor segment boundary within "
                f"{max_snap_frames} frames that preserves ordering and a positive "
                "physical attempt."
            )
        minimum_distance = min(candidate[0] for candidate in candidates)
        nearest = [
            candidate for candidate in candidates if candidate[0] == minimum_distance
        ]
        if len(nearest) != 1:
            raise GscGymGeometryError(
                f"{label} source frame {source_frame} is exactly equidistant from "
                "two valid adjacent auto-editor joins; deterministic mapping fails "
                "closed."
            )
        _, effective_source_frame, record_frame, policy = nearest[0]
        return _checked_mapping(
            raw_source_frame=source_frame,
            effective_source_frame=effective_source_frame,
            original_record_frame=record_frame,
            policy=policy,
            authority=authority,
            label=label,
            max_snap_frames=max_snap_frames,
            candidates=tuple(candidate_evidence),
        )

    preceding = [item for item in retained.intervals if item.source_end_frame < source_frame]
    following = [item for item in retained.intervals if item.source_start_frame > source_frame]
    if not preceding or not following:
        raise GscGymGeometryError(
            f"{label} source frame {source_frame} has no bounded removed-gap edit join."
        )
    before = preceding[-1]
    after = following[0]
    if before.record_end_frame != after.record_start_frame:
        raise GscGymGeometryError(
            f"{label} removed source gap does not map to one contiguous edit join."
        )
    _adjacent_join(retained, before.record_end_frame, label=label)
    return _checked_mapping(
        raw_source_frame=source_frame,
        effective_source_frame=source_frame,
        original_record_frame=before.record_end_frame,
        policy="battle_start_removed_gap_exact_contiguous_edit_join",
        authority=authority,
        label=label,
        max_snap_frames=max_snap_frames,
    )


def _map_battle_end(
    retained: AutoEditorRetained,
    source_frame: int,
    *,
    label: str,
    authority: str,
    max_snap_frames: int,
) -> BoundaryMapping:
    candidates = [
        item.record_start_frame + source_frame - item.source_start_frame
        for item in retained.intervals
        if item.source_start_frame <= source_frame <= item.source_end_frame
    ]
    unique = sorted(set(candidates))
    if len(unique) > 1:
        raise GscGymGeometryError(
            f"{label} source frame {source_frame} has ambiguous exact record mappings {unique}."
        )
    if unique:
        return _checked_mapping(
            raw_source_frame=source_frame,
            effective_source_frame=source_frame,
            original_record_frame=unique[0],
            policy="battle_end_exact_retained_boundary",
            authority=authority,
            label=label,
            max_snap_frames=max_snap_frames,
        )

    preceding = [item for item in retained.intervals if item.source_end_frame < source_frame]
    following = [item for item in retained.intervals if item.source_start_frame > source_frame]
    if not preceding or not following:
        raise GscGymGeometryError(
            f"{label} source frame {source_frame} has no bounded removed-gap edit join."
        )
    before = preceding[-1]
    after = following[0]
    if before.record_end_frame != after.record_start_frame:
        raise GscGymGeometryError(
            f"{label} removed source gap does not map to one contiguous edit join."
        )
    return _checked_mapping(
        raw_source_frame=source_frame,
        effective_source_frame=source_frame,
        original_record_frame=before.record_end_frame,
        policy="battle_end_removed_gap_exact_contiguous_edit_join",
        authority=authority,
        label=label,
        max_snap_frames=max_snap_frames,
    )


def _map_exact_or_next_start(
    retained: AutoEditorRetained,
    source_frame: int,
    *,
    label: str,
    authority: str,
    policy_prefix: str,
    max_snap_frames: int,
) -> BoundaryMapping:
    candidates = [
        item.record_start_frame + source_frame - item.source_start_frame
        for item in retained.intervals
        if item.source_start_frame <= source_frame <= item.source_end_frame
    ]
    unique = sorted(set(candidates))
    if len(unique) > 1:
        raise GscGymGeometryError(
            f"{label} source frame {source_frame} has ambiguous exact record mappings {unique}."
        )
    if unique:
        return _checked_mapping(
            raw_source_frame=source_frame,
            effective_source_frame=source_frame,
            original_record_frame=unique[0],
            policy=f"{policy_prefix}_exact_retained_boundary",
            authority=authority,
            label=label,
            max_snap_frames=max_snap_frames,
        )

    following = [item for item in retained.intervals if item.source_start_frame > source_frame]
    if not following:
        raise GscGymGeometryError(
            f"{label} source frame {source_frame} has no following retained interval boundary."
        )
    item = following[0]
    return _checked_mapping(
        raw_source_frame=source_frame,
        effective_source_frame=item.source_start_frame,
        original_record_frame=item.record_start_frame,
        policy=f"{policy_prefix}_removed_gap_snap_to_next_retained_start",
        authority=authority,
        label=label,
        max_snap_frames=max_snap_frames,
    )


def map_carousel_boundary(
    retained: AutoEditorRetained,
    boundary: CarouselSourceBoundary,
    *,
    max_snap_frames: int = MAX_BOUNDARY_SNAP_FRAMES,
) -> BoundaryMapping:
    """Resolve the fixed detector boundary with exact-or-next-start policy."""

    _validate_retained(retained)
    maximum = _positive(max_snap_frames, "max_snap_frames")
    source_frame = _int(boundary.source_frame, "carousel.source_frame")
    source_min = retained.source_start_frame
    source_max = source_min + retained.source_duration_frames
    if not boundary.authority.strip():
        raise GscGymGeometryError("Carousel source boundary requires explicit mapping authority.")
    if not source_min <= source_frame < source_max:
        raise GscGymGeometryError("Carousel source boundary is outside source media.")
    return _map_exact_or_next_start(
        retained,
        source_frame,
        label="carousel",
        authority=boundary.authority,
        policy_prefix="carousel",
        max_snap_frames=maximum,
    )


def _validate_boundaries(
    retained: AutoEditorRetained,
    battles: tuple[BattleSourceBoundary, ...],
    carousel: CarouselSourceBoundary,
    max_snap_frames: int,
) -> tuple[list[dict[str, Any]], BoundaryMapping]:
    if not battles:
        raise GscGymGeometryError("At least one retained battle boundary is required.")
    if not any(item.role == "leader" for item in battles):
        raise GscGymGeometryError("A GSC Gym Leader Challenge requires at least one leader battle.")
    source_min = retained.source_start_frame
    carousel_mapping = map_carousel_boundary(
        retained,
        carousel,
        max_snap_frames=max_snap_frames,
    )
    carousel_source = carousel.source_frame

    rows: list[dict[str, Any]] = []
    ids: set[str] = set()
    identity_last_ordinals: dict[str, int] = {}
    identity_roles: dict[str, str] = {}
    previous_end = source_min
    previous_original_end = -1
    previous_original_start = -1
    for index, battle in enumerate(battles, start=1):
        if not battle.battle_id.strip() or battle.battle_id in ids:
            raise GscGymGeometryError(f"Attempt {index} requires a non-empty unique attempt_id.")
        ids.add(battle.battle_id)
        canonical_identity = " ".join(battle.canonical_identity.casefold().split())
        if not canonical_identity:
            raise GscGymGeometryError(
                f"Attempt {battle.battle_id!r} requires a canonical_identity."
            )
        if (
            isinstance(battle.attempt_ordinal, bool)
            or not isinstance(battle.attempt_ordinal, int)
            or battle.attempt_ordinal < 1
        ):
            raise GscGymGeometryError(
                f"Attempt {battle.battle_id!r} requires a positive identity ordinal."
            )
        prior_ordinal = identity_last_ordinals.get(canonical_identity)
        if prior_ordinal is not None and battle.attempt_ordinal <= prior_ordinal:
            raise GscGymGeometryError(
                f"Attempt {battle.battle_id!r} has ordinal {battle.attempt_ordinal}; "
                f"canonical identity {battle.canonical_identity!r} requires a value "
                f"greater than retained ordinal {prior_ordinal}."
            )
        prior_role = identity_roles.get(canonical_identity)
        if prior_role is not None and prior_role != battle.role:
            raise GscGymGeometryError(
                f"Canonical identity {battle.canonical_identity!r} changes role "
                f"from {prior_role!r} to {battle.role!r}."
            )
        identity_last_ordinals[canonical_identity] = battle.attempt_ordinal
        identity_roles[canonical_identity] = battle.role
        if battle.role not in {"leader", "rival", "trainer"}:
            raise GscGymGeometryError(f"Battle {battle.battle_id!r} has unsupported role {battle.role!r}.")
        if not battle.start_authority.strip() or not battle.end_authority.strip():
            raise GscGymGeometryError(
                f"Battle {battle.battle_id!r} requires explicit start and end mapping authority."
            )
        start = _int(battle.source_start_frame, f"{battle.battle_id}.source_start_frame")
        end = _int(battle.source_end_frame, f"{battle.battle_id}.source_end_frame")
        if end <= start:
            raise GscGymGeometryError(f"Battle {battle.battle_id!r} has a non-positive source range.")
        if start < previous_end:
            raise GscGymGeometryError(
                f"Battle {battle.battle_id!r} is out of order or overlaps the prior physical attempt."
            )
        gap_eligible = battle.attempt_ordinal == 1
        if (
            (gap_eligible and start - BATTLE_GAP_FRAMES < source_min)
            or end > carousel_source
        ):
            raise GscGymGeometryError(
                f"Battle {battle.battle_id!r} cannot fit before the carousel"
                + (" with 60 source-preroll frames." if gap_eligible else ".")
            )
        end_mapping = _map_battle_end(
            retained,
            end,
            label=f"battle {battle.battle_id} end",
            authority=battle.end_authority,
            max_snap_frames=max_snap_frames,
        )
        start_mapping = _map_battle_start(
            retained,
            start,
            end_record_frame=end_mapping.original_record_frame,
            minimum_record_frame=previous_original_end,
            requires_gap=gap_eligible,
            label=f"battle {battle.battle_id} start",
            authority=battle.start_authority,
            max_snap_frames=max_snap_frames,
        )
        if end_mapping.original_record_frame <= start_mapping.original_record_frame:
            raise GscGymGeometryError(
                f"Battle {battle.battle_id!r} collapses or reverses after deterministic boundary mapping."
            )
        if start_mapping.original_record_frame <= previous_original_start:
            raise GscGymGeometryError(
                f"Battle {battle.battle_id!r} start mapping is ambiguous or not strictly ordered."
            )
        if start_mapping.original_record_frame < previous_original_end:
            raise GscGymGeometryError(
                f"Battle {battle.battle_id!r} overlaps the previous mapped physical attempt."
            )
        if (
            gap_eligible
            and start_mapping.effective_source_frame - BATTLE_GAP_FRAMES < source_min
        ):
            raise GscGymGeometryError(
                f"Battle {battle.battle_id!r} effective start lacks 60 source-preroll frames."
            )
        rows.append(
            {
                "boundary": battle,
                "start_mapping": start_mapping,
                "end_mapping": end_mapping,
                "original_start": start_mapping.original_record_frame,
                "original_end": end_mapping.original_record_frame,
                "intro_eligible": (
                    battle.role in {"leader", "rival"}
                    and battle.attempt_ordinal == 1
                ),
                "a1_gap_eligible": gap_eligible,
            }
        )
        previous_end = end
        previous_original_start = start_mapping.original_record_frame
        previous_original_end = end_mapping.original_record_frame

    if rows[-1]["original_end"] > carousel_mapping.original_record_frame:
        raise GscGymGeometryError("Last battle maps after the carousel boundary.")
    return rows, carousel_mapping


def _split_retained_at_points(
    retained: AutoEditorRetained,
    battle_rows: list[dict[str, Any]],
    carousel_mapping: BoundaryMapping,
    dialogue_gain_db: float,
) -> tuple[
    tuple[SourceInterval, ...],
    tuple[DialogueInterval, ...],
    CarouselSpec,
    dict[str, int],
]:
    battle_by_record = {
        int(item["original_start"]): item["boundary"]
        for item in battle_rows
    }
    if len(battle_by_record) != len(battle_rows):
        raise GscGymGeometryError(
            "Physical battle starts do not map to unique retained-edit boundaries."
        )
    gap_eligible_ids = {
        row["boundary"].battle_id
        for row in battle_rows
        if bool(row["a1_gap_eligible"])
    }
    carousel_source = carousel_mapping.effective_source_frame
    body_v1: list[SourceInterval] = []
    dialogue: list[DialogueInterval] = []
    carousel_slices: list[CarouselSlice] = []
    final_battle_starts: dict[str, int] = {}
    processed_battles: set[str] = set()
    record_cursor = OPENING_FRAMES
    carousel_record_start: int | None = None

    def emit_retained(source_start: int, duration: int, label: str, *, carousel_part: bool) -> None:
        nonlocal record_cursor
        if duration <= 0:
            return
        if carousel_part:
            carousel_slices.append(
                CarouselSlice(
                    record_start_frame=record_cursor,
                    source_start_frame=source_start,
                    duration_frames=duration,
                    label=label,
                )
            )
        else:
            body_v1.append(
                SourceInterval(
                    record_start_frame=record_cursor,
                    source_start_frame=source_start,
                    duration_frames=duration,
                    label=label,
                )
            )
        dialogue.append(
            DialogueInterval(
                record_start_frame=record_cursor,
                source_start_frame=source_start,
                duration_frames=duration,
                label=label,
                gain_db=dialogue_gain_db,
            )
        )
        record_cursor += duration

    for retained_index, item in enumerate(retained.intervals, start=1):
        battle_at_source: dict[int, BattleSourceBoundary] = {}
        for record_frame, battle in battle_by_record.items():
            if battle.battle_id in processed_battles:
                continue
            # Retained record intervals are treated as half-open here.  A
            # boundary at a cut join is compiled at the following clip's
            # start, which preserves stable segment labels while mapping to
            # the same unique record frame.
            if item.record_start_frame <= record_frame < item.record_end_frame:
                source_frame = (
                    item.source_start_frame + record_frame - item.record_start_frame
                )
                existing = battle_at_source.get(source_frame)
                if existing is not None and existing.battle_id != battle.battle_id:
                    raise GscGymGeometryError(
                        "Multiple physical battles map to one retained source split point."
                    )
                battle_at_source[source_frame] = battle
        split_points = list(battle_at_source)
        if (
            carousel_record_start is None
            and item.source_start_frame <= carousel_source <= item.source_end_frame
        ):
            split_points.append(carousel_source)
        split_points = sorted(set(split_points))
        source_cursor = item.source_start_frame
        for point in split_points:
            is_carousel = carousel_record_start is not None
            emit_retained(
                source_cursor,
                point - source_cursor,
                f"{item.label} part before source {point}",
                carousel_part=is_carousel,
            )
            if point == carousel_source:
                if carousel_record_start is not None:
                    raise GscGymGeometryError("Carousel boundary was encountered more than once.")
                carousel_record_start = record_cursor
            battle = battle_at_source.get(point)
            if battle is not None and battle.battle_id not in processed_battles:
                if carousel_record_start is not None:
                    raise GscGymGeometryError(
                        f"Battle {battle.battle_id!r} starts at or after the carousel boundary."
                    )
                if (
                    point != item.source_start_frame
                    or record_cursor < OPENING_FRAMES
                ):
                    raise GscGymGeometryError(
                        f"Battle {battle.battle_id!r} did not compile at the incoming "
                        "side of an immutable auto-editor segment boundary."
                    )
                if battle.battle_id in gap_eligible_ids:
                    bridge_source_start = point - BATTLE_GAP_FRAMES
                    if bridge_source_start < retained.source_start_frame:
                        raise GscGymGeometryError(
                            f"Battle {battle.battle_id!r} incoming V1 segment has only "
                            f"{point - retained.source_start_frame} source frames of left "
                            f"handle; {BATTLE_GAP_FRAMES} are required."
                        )
                    # Insert a real 60-frame record range between the complete
                    # outgoing and incoming A1 clips.  Only V1 occupies this
                    # range; a same-trainer retry deliberately skips it.
                    body_v1.append(
                        SourceInterval(
                            record_start_frame=record_cursor,
                            source_start_frame=bridge_source_start,
                            duration_frames=BATTLE_GAP_FRAMES,
                            label=f"battle-gap-v1-bridge:{battle.battle_id}",
                        )
                    )
                    record_cursor += BATTLE_GAP_FRAMES
                final_battle_starts[battle.battle_id] = record_cursor
                processed_battles.add(battle.battle_id)
            source_cursor = point
        emit_retained(
            source_cursor,
            item.source_end_frame - source_cursor,
            f"{item.label} part {retained_index:04d}",
            carousel_part=carousel_record_start is not None,
        )

    if carousel_record_start is None:
        raise GscGymGeometryError("Carousel boundary was not encountered in retained geometry.")
    if processed_battles != {item["boundary"].battle_id for item in battle_rows}:
        raise GscGymGeometryError("Not every effective battle-start boundary was compiled once.")
    if not body_v1:
        raise GscGymGeometryError("Carousel boundary leaves no body V1 after the opening.")
    if not carousel_slices:
        raise GscGymGeometryError("Carousel boundary leaves no retained V2 slices.")
    carousel_duration = sum(item.duration_frames for item in carousel_slices)
    source_limit = retained.source_start_frame + retained.source_duration_frames
    if carousel_source + carousel_duration > source_limit:
        raise GscGymGeometryError(
            "Continuous carousel V1 bed would exceed source media: "
            f"[{carousel_source}, {carousel_source + carousel_duration}) > {source_limit}."
        )
    carousel = CarouselSpec(
        v1=SourceInterval(
            record_start_frame=carousel_record_start,
            source_start_frame=carousel_source,
            duration_frames=carousel_duration,
            label="continuous source-backed member carousel V1",
        ),
        v2_slices=tuple(carousel_slices),
    )
    return tuple(body_v1), tuple(dialogue), carousel, final_battle_starts


def _map_final_boundary(
    original_record_frame: int,
    battle_rows: list[dict[str, Any]],
    *,
    include_insert_at_boundary: bool,
) -> int:
    inserted = sum(
        BATTLE_GAP_FRAMES
        for row in battle_rows
        if bool(row["a1_gap_eligible"])
        and (
            int(row["original_start"]) < original_record_frame
            or (
                include_insert_at_boundary
                and int(row["original_start"]) == original_record_frame
            )
        )
    )
    return OPENING_FRAMES + original_record_frame + inserted


def _source_ranges(rows: tuple[DialogueInterval, ...]) -> list[tuple[int, int]]:
    return [
        (item.source_start_frame, item.source_start_frame + item.duration_frames)
        for item in rows
    ]


def _coalesce_source_ranges(rows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for start, end in rows:
        if result and result[-1][1] == start:
            result[-1] = (result[-1][0], end)
        else:
            result.append((start, end))
    return result


def _planned_source_ranges(
    body: tuple[SourceInterval, ...],
    carousel: CarouselSpec,
) -> list[tuple[int, int]]:
    rows = [
        (item.source_start_frame, item.source_start_frame + item.duration_frames)
        for item in body
        if not item.label.startswith("battle-gap-v1-bridge:")
    ]
    rows.extend(
        (item.source_start_frame, item.source_start_frame + item.duration_frames)
        for item in carousel.v2_slices
    )
    return rows


def _audit_plan(
    retained: AutoEditorRetained,
    body: tuple[SourceInterval, ...],
    dialogue: tuple[DialogueInterval, ...],
    planned_battles: tuple[PlannedBattleAttempt, ...],
    carousel: CarouselSpec,
    carousel_mapping: BoundaryMapping,
    max_snap_frames: int,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, evidence: Any) -> None:
        checks.append({"name": name, "status": "pass" if passed else "fail", "evidence": evidence})

    body_geometry = [
        (item.record_start_frame, item.record_end_frame, item.source_start_frame, item.label)
        for item in body
    ]
    body_contiguous = bool(body) and body[0].record_start_frame == OPENING_FRAMES
    body_contiguous = body_contiguous and all(
        left.record_end_frame == right.record_start_frame for left, right in zip(body, body[1:])
    )
    body_contiguous = body_contiguous and body[-1].record_end_frame == carousel.v1.record_start_frame
    check(
        "opening_then_continuous_body_v1",
        body_contiguous,
        {"opening_frames": OPENING_FRAMES, "body": body_geometry},
    )

    bridges = [item for item in body if item.label.startswith("battle-gap-v1-bridge:")]
    gap_battles = tuple(
        item for item in planned_battles if item.a1_gap_eligible
    )
    retry_battles = tuple(
        item for item in planned_battles if not item.a1_gap_eligible
    )
    a1_ranges = [(item.record_start_frame, item.record_end_frame) for item in dialogue]
    gap_intersections = [
        {
            "battle_id": battle.battle_id,
            "dialogue": [start, end],
            "gap": [battle.gap_start_frame, battle.gap_end_frame],
        }
        for battle in gap_battles
        for start, end in a1_ranges
        if max(start, battle.gap_start_frame) < min(end, battle.gap_end_frame)
    ]
    boundary_gap_evidence = []
    for battle in gap_battles:
        overlap_frames = sum(
            max(
                0,
                min(item.record_end_frame, battle.gap_end_frame)
                - max(item.record_start_frame, battle.gap_start_frame),
            )
            for item in body
        )
        expected_label = f"battle-gap-v1-bridge:{battle.battle_id}"
        matching_bridges = [item for item in bridges if item.label == expected_label]
        left_a1 = [
            item for item in dialogue if item.record_end_frame == battle.gap_start_frame
        ]
        right_a1 = [
            item for item in dialogue if item.record_start_frame == battle.gap_end_frame
        ]
        bridge_source_matches_incoming = bool(
            len(matching_bridges) == 1
            and len(right_a1) == 1
            and matching_bridges[0].source_start_frame + BATTLE_GAP_FRAMES
            == right_a1[0].source_start_frame
        )
        source_overlap_frames = 0
        if len(matching_bridges) == 1 and len(left_a1) == 1:
            source_overlap_frames = max(
                0,
                left_a1[0].source_start_frame + left_a1[0].duration_frames
                - matching_bridges[0].source_start_frame,
            )
        boundary_gap_evidence.append(
            {
                "battle_id": battle.battle_id,
                "gap_range": [battle.gap_start_frame, battle.gap_end_frame],
                "v1_coverage_frames": overlap_frames,
                "matching_v1_bridge_count": len(matching_bridges),
                "v1_bridge": (
                    {
                        "record_range": [
                            matching_bridges[0].record_start_frame,
                            matching_bridges[0].record_end_frame,
                        ],
                        "source_range": [
                            matching_bridges[0].source_start_frame,
                            matching_bridges[0].source_start_frame
                            + matching_bridges[0].duration_frames,
                        ],
                        "label": matching_bridges[0].label,
                    }
                    if len(matching_bridges) == 1
                    else None
                ),
                "left_a1_boundary_count": len(left_a1),
                "right_a1_boundary_count": len(right_a1),
                "bridge_source_matches_incoming_a1": bridge_source_matches_incoming,
                "v1_source_overlap_with_outgoing_a1_frames": source_overlap_frames,
            }
        )
    check(
        "lossless_a1_boundary_gaps_with_source_backed_v1_bridges",
        len(bridges) == len(gap_battles)
        and all(
            item.gap_end_frame - item.gap_start_frame == BATTLE_GAP_FRAMES
            for item in gap_battles
        )
        and all(
            item.gap_start_frame == item.gap_end_frame == item.final_start_frame
            for item in retry_battles
        )
        and all(
            row["v1_coverage_frames"] == BATTLE_GAP_FRAMES
            and row["matching_v1_bridge_count"] == 1
            and row["left_a1_boundary_count"] == 1
            and row["right_a1_boundary_count"] == 1
            and row["bridge_source_matches_incoming_a1"] is True
            for row in boundary_gap_evidence
        )
        and not gap_intersections
        and carousel.v1.record_end_frame
        == (
            OPENING_FRAMES
            + retained.record_duration_frames
            + BATTLE_GAP_FRAMES * len(gap_battles)
        ),
        {
            "policy": BATTLE_GAP_POLICY,
            "inserts_timeline_frames": BATTLE_GAP_INSERTS_TIMELINE_FRAMES,
            "duplicates_v1_preroll": BATTLE_GAP_DUPLICATES_V1_PREROLL,
            "a1_removed_frames": 0,
            "inserted_gap_total_frames": BATTLE_GAP_FRAMES * len(gap_battles),
            "gap_count": len(gap_battles),
            "same_trainer_retry_gap_count": 0,
            "retry_battle_ids": [item.battle_id for item in retry_battles],
            "v1_bridges": boundary_gap_evidence,
            "retained_record_duration_frames": retained.record_duration_frames,
            "main_program_end_frame": carousel.v1.record_end_frame,
            "a1_intersections": gap_intersections,
        },
    )

    original_sources = _coalesce_source_ranges(
        [
            (item.source_start_frame, item.source_end_frame)
            for item in retained.intervals
        ]
    )
    planned_sources = _coalesce_source_ranges(_planned_source_ranges(body, carousel))
    dialogue_sources = _coalesce_source_ranges(_source_ranges(dialogue))
    check(
        "retained_source_preserved_once_on_v2_and_a1",
        planned_sources == original_sources
        and dialogue_sources == original_sources
        and sum(end - start for start, end in dialogue_sources) == retained.record_duration_frames,
        {
            "original": original_sources,
            "planned_v1_or_v2": planned_sources,
            "dialogue_a1": dialogue_sources,
        },
    )

    battle_geometry_ok = all(
        item.gap_end_frame == item.final_start_frame
        and item.gap_end_frame - item.gap_start_frame
        == (BATTLE_GAP_FRAMES if item.a1_gap_eligible else 0)
        and item.final_end_frame > item.final_start_frame
        for item in planned_battles
    )
    check(
        "battle_source_boundaries_map_to_exact_final_ranges",
        battle_geometry_ok,
        [
            {
                "battle_id": item.battle_id,
                "attempt_id": item.attempt_id,
                "canonical_identity": item.canonical_identity,
                "attempt_ordinal": item.attempt_ordinal,
                "intro_eligible": item.intro_eligible,
                "a1_gap_eligible": item.a1_gap_eligible,
                "raw_source_range": [item.source_start_frame, item.source_end_frame],
                "effective_source_range": [
                    item.effective_source_start_frame,
                    item.effective_source_end_frame,
                ],
                "snap_deltas": [
                    item.start_snap_delta_frames,
                    item.end_snap_delta_frames,
                ],
                "mapping_policies": [
                    item.start_mapping_policy,
                    item.end_mapping_policy,
                ],
                "input_authorities": [item.start_authority, item.end_authority],
                "effective_authorities": [
                    item.start_effective_authority,
                    item.end_effective_authority,
                ],
                "original_record_range": [
                    item.original_record_start_frame,
                    item.original_record_end_frame,
                ],
                "final_record_range": [item.final_start_frame, item.final_end_frame],
                "gap_range": (
                    [item.gap_start_frame, item.gap_end_frame]
                    if item.a1_gap_eligible
                    else None
                ),
            }
            for item in planned_battles
        ],
    )

    mapping_rows = [
        (
            item.source_start_frame,
            item.effective_source_start_frame,
            item.start_snap_delta_frames,
            item.start_mapping_policy,
            item.start_authority,
            item.start_effective_authority,
        )
        for item in planned_battles
    ]
    mapping_rows.extend(
        (
            item.source_end_frame,
            item.effective_source_end_frame,
            item.end_snap_delta_frames,
            item.end_mapping_policy,
            item.end_authority,
            item.end_effective_authority,
        )
        for item in planned_battles
    )
    mapping_rows.append(
        (
            carousel_mapping.raw_source_frame,
            carousel_mapping.effective_source_frame,
            carousel_mapping.snap_delta_frames,
            carousel_mapping.policy,
            carousel_mapping.input_authority,
            carousel_mapping.effective_authority,
        )
    )
    check(
        "explicit_bounded_deterministic_boundary_mappings",
        all(
            effective - raw == delta
            and abs(delta) <= max_snap_frames
            and bool(policy)
            and bool(input_authority)
            and bool(effective_authority)
            for raw, effective, delta, policy, input_authority, effective_authority in mapping_rows
        )
        and all("exact_split" not in item.start_mapping_policy for item in planned_battles),
        {
            "max_snap_frames": max_snap_frames,
            "mappings": [
                {
                    "raw_source_frame": raw,
                    "effective_source_frame": effective,
                    "snap_delta_frames": delta,
                    "policy": policy,
                    "input_authority": input_authority,
                    "effective_authority": effective_authority,
                }
                for raw, effective, delta, policy, input_authority, effective_authority in mapping_rows
            ],
        },
    )

    inside_nearest = [
        item
        for item in planned_battles
        if item.start_mapping_policy.startswith(
            "battle_start_inside_retained_nearest_"
        )
    ]
    candidate_evidence_ok = all(
        not item.start_candidate_evidence
        for item in planned_battles
        if item not in inside_nearest
    )
    candidate_audit_rows: list[dict[str, Any]] = []
    for item in inside_nearest:
        candidates = item.start_candidate_evidence
        valid = [candidate for candidate in candidates if candidate.valid]
        minimum = min(
            (candidate.absolute_distance_frames for candidate in valid),
            default=None,
        )
        nearest = [
            candidate
            for candidate in valid
            if candidate.absolute_distance_frames == minimum
        ]
        selected_ok = (
            len(candidates) == 2
            and {candidate.side for candidate in candidates}
            == {"preceding", "following"}
            and len(nearest) == 1
            and nearest[0].effective_source_frame
            == item.effective_source_start_frame
            and nearest[0].original_record_frame
            == item.original_record_start_frame
            and nearest[0].side in item.start_mapping_policy
            and all(
                candidate.snap_delta_frames
                == candidate.effective_source_frame - item.source_start_frame
                and candidate.absolute_distance_frames
                == abs(candidate.snap_delta_frames)
                and ((candidate.rejection_reason is None) == candidate.valid)
                for candidate in candidates
            )
        )
        candidate_evidence_ok = candidate_evidence_ok and selected_ok
        candidate_audit_rows.append(
            {
                "battle_id": item.battle_id,
                "selected_effective_source_frame": item.effective_source_start_frame,
                "selected_original_record_frame": item.original_record_start_frame,
                "candidates": [
                    {
                        "side": candidate.side,
                        "effective_source_frame": candidate.effective_source_frame,
                        "original_record_frame": candidate.original_record_frame,
                        "snap_delta_frames": candidate.snap_delta_frames,
                        "absolute_distance_frames": candidate.absolute_distance_frames,
                        "valid": candidate.valid,
                        "rejection_reason": candidate.rejection_reason,
                    }
                    for candidate in candidates
                ],
            }
        )
    check(
        "inside_battle_starts_record_both_candidates_and_unique_nearest_selection",
        candidate_evidence_ok,
        candidate_audit_rows,
    )

    expected_intro_flags = [
        item.role in {"leader", "rival"} and item.attempt_ordinal == 1
        for item in planned_battles
    ]
    check(
        "attempt_level_ranges_with_first_identity_intro_only",
        [item.intro_eligible for item in planned_battles] == expected_intro_flags
        and [item.a1_gap_eligible for item in planned_battles]
        == [item.attempt_ordinal == 1 for item in planned_battles]
        and len({item.attempt_id for item in planned_battles}) == len(planned_battles),
        [
            {
                "attempt_id": item.attempt_id,
                "canonical_identity": item.canonical_identity,
                "attempt_ordinal": item.attempt_ordinal,
                "intro_eligible": item.intro_eligible,
                "a1_gap_eligible": item.a1_gap_eligible,
            }
            for item in planned_battles
        ],
    )

    carousel_slices = carousel.v2_slices
    carousel_contiguous = bool(carousel_slices)
    carousel_contiguous = carousel_contiguous and carousel_slices[0].record_start_frame == carousel.v1.record_start_frame
    carousel_contiguous = carousel_contiguous and all(
        left.record_end_frame == right.record_start_frame
        for left, right in zip(carousel_slices, carousel_slices[1:])
    )
    carousel_contiguous = carousel_contiguous and carousel_slices[-1].record_end_frame == carousel.v1.record_end_frame
    check(
        "continuous_carousel_v1_with_contiguous_cropped_v2_geometry",
        carousel_contiguous
        and carousel.v1.source_start_frame == carousel_mapping.effective_source_frame
        and carousel.v1.duration_frames == sum(item.duration_frames for item in carousel_slices)
        and (
            carousel_slices[-1].source_start_frame
            + carousel_slices[-1].duration_frames
            == retained.intervals[-1].source_end_frame
        ),
        {
            "v1_record_range": [carousel.v1.record_start_frame, carousel.v1.record_end_frame],
            "v1_source_range": [carousel.v1.source_start_frame, carousel.v1.source_start_frame + carousel.v1.duration_frames],
            "v2_slices": [
                {
                    "record_range": [item.record_start_frame, item.record_end_frame],
                    "source_range": [item.source_start_frame, item.source_start_frame + item.duration_frames],
                    "crop_bottom_pixels": 530,
                }
                for item in carousel_slices
            ],
            "final_retained_source_content_end_frame": retained.intervals[-1].source_end_frame,
        },
    )

    failed = [item for item in checks if item["status"] != "pass"]
    audit = {
        "schema": AUDIT_SCHEMA,
        "status": "pass" if not failed else "fail",
        "deterministic": True,
        "llm_steps": 0,
        "check_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "checks": checks,
    }
    if failed:
        raise GscGymGeometryError(
            "Generated geometry failed structural audit: "
            + ", ".join(item["name"] for item in failed)
        )
    return audit


def plan_gsc_gym_geometry(
    retained: AutoEditorRetained,
    battles: tuple[BattleSourceBoundary, ...],
    carousel_boundary: CarouselSourceBoundary,
    *,
    dialogue_gain_db: float,
    max_snap_frames: int = MAX_BOUNDARY_SNAP_FRAMES,
) -> GscGymGeometryPlan:
    """Compile explicit source geometry into final assembler frame geometry."""

    _validate_retained(retained)
    if isinstance(dialogue_gain_db, bool) or not isinstance(dialogue_gain_db, (int, float)):
        raise GscGymGeometryError("dialogue_gain_db must be a finite number.")
    dialogue_gain = float(dialogue_gain_db)
    if not math.isfinite(dialogue_gain):
        raise GscGymGeometryError("dialogue_gain_db must be a finite number.")
    max_snap = _positive(max_snap_frames, "max_snap_frames")

    boundary_rows, carousel_mapping = _validate_boundaries(
        retained,
        battles,
        carousel_boundary,
        max_snap,
    )
    body, dialogue, carousel, compiled_starts = _split_retained_at_points(
        retained,
        boundary_rows,
        carousel_mapping,
        dialogue_gain,
    )

    planned_battles: list[PlannedBattleAttempt] = []
    for row in boundary_rows:
        boundary: BattleSourceBoundary = row["boundary"]
        start_mapping: BoundaryMapping = row["start_mapping"]
        end_mapping: BoundaryMapping = row["end_mapping"]
        final_start = _map_final_boundary(
            int(row["original_start"]),
            boundary_rows,
            include_insert_at_boundary=True,
        )
        final_end = _map_final_boundary(
            int(row["original_end"]),
            boundary_rows,
            include_insert_at_boundary=False,
        )
        if compiled_starts.get(boundary.battle_id) != final_start:
            raise GscGymGeometryError(
                f"Independent battle mapping disagrees for {boundary.battle_id!r}."
            )
        intro_eligible = bool(row["intro_eligible"])
        a1_gap_eligible = bool(row["a1_gap_eligible"])
        if final_start - BATTLE_INTRO_FRAMES < OPENING_FRAMES and intro_eligible:
            raise GscGymGeometryError(
                f"Major battle {boundary.battle_id!r} begins too early for its 300-frame intro."
            )
        planned_battles.append(
            PlannedBattleAttempt(
                attempt_id=boundary.attempt_id,
                canonical_identity=boundary.canonical_identity,
                attempt_ordinal=boundary.attempt_ordinal,
                role=boundary.role,
                intro_eligible=intro_eligible,
                a1_gap_eligible=a1_gap_eligible,
                source_start_frame=boundary.source_start_frame,
                source_end_frame=boundary.source_end_frame,
                effective_source_start_frame=start_mapping.effective_source_frame,
                effective_source_end_frame=end_mapping.effective_source_frame,
                start_snap_delta_frames=start_mapping.snap_delta_frames,
                end_snap_delta_frames=end_mapping.snap_delta_frames,
                start_mapping_policy=start_mapping.policy,
                end_mapping_policy=end_mapping.policy,
                start_effective_authority=start_mapping.effective_authority,
                end_effective_authority=end_mapping.effective_authority,
                start_candidate_evidence=start_mapping.candidates,
                original_record_start_frame=int(row["original_start"]),
                original_record_end_frame=int(row["original_end"]),
                final_start_frame=final_start,
                final_end_frame=final_end,
                gap_start_frame=(
                    final_start - BATTLE_GAP_FRAMES
                    if a1_gap_eligible
                    else final_start
                ),
                gap_end_frame=final_start,
                start_authority=boundary.start_authority,
                end_authority=boundary.end_authority,
            )
        )
    planned_tuple = tuple(planned_battles)
    expected_carousel_record = _map_final_boundary(
        carousel_mapping.original_record_frame,
        boundary_rows,
        include_insert_at_boundary=True,
    )
    if carousel.v1.record_start_frame != expected_carousel_record:
        raise GscGymGeometryError(
            "Independent carousel mapping disagrees: "
            f"{carousel.v1.record_start_frame} != {expected_carousel_record}."
        )

    audit = _audit_plan(
        retained,
        body,
        dialogue,
        planned_tuple,
        carousel,
        carousel_mapping,
        max_snap,
    )
    manifest = {
        "schema": SCHEMA,
        "deterministic": True,
        "llm_steps": 0,
        "input": {
            "autoeditor_fcpxml_sha256": retained.fcpxml_sha256,
            "autoeditor_fcpxml_version": retained.fcpxml_version,
            "source_ref": retained.source_ref,
            "source_name": retained.source_name,
            "source_uri": retained.source_uri,
            "source_range": [
                retained.source_start_frame,
                retained.source_start_frame + retained.source_duration_frames,
            ],
            "retained_interval_count": len(retained.intervals),
            "retained_record_duration_frames": retained.record_duration_frames,
        },
        "contract": {
            "fps": FPS,
            "width": WIDTH,
            "height": HEIGHT,
            "opening_frames": OPENING_FRAMES,
            "battle_gap_frames": BATTLE_GAP_FRAMES,
            "battle_intro_frames": BATTLE_INTRO_FRAMES,
            "boundary_policy": BATTLE_BOUNDARY_POLICY,
            "max_boundary_snap_frames": max_snap,
            "gap_policy": BATTLE_GAP_POLICY,
            "battle_gap_inserts_timeline_frames": BATTLE_GAP_INSERTS_TIMELINE_FRAMES,
            "battle_gap_duplicates_v1_preroll": BATTLE_GAP_DUPLICATES_V1_PREROLL,
            "a1_removed_frames": 0,
            "v1_bridge_policy": (
                "one_exact_60f_incoming_side_source_backed_bridge_per_gap_"
                "with_source_overlap_allowed"
            ),
            "carousel_policy": "continuous_source_v1_plus_retained_contiguous_v2",
        },
        "body_v1": [
            {
                "record_range": [item.record_start_frame, item.record_end_frame],
                "source_range": [item.source_start_frame, item.source_start_frame + item.duration_frames],
                "label": item.label,
            }
            for item in body
        ],
        "dialogue_a1": [
            {
                "record_range": [item.record_start_frame, item.record_end_frame],
                "source_range": [item.source_start_frame, item.source_start_frame + item.duration_frames],
                "label": item.label,
            }
            for item in dialogue
        ],
        "battles": [
            {
                "battle_id": item.battle_id,
                "attempt_id": item.attempt_id,
                "canonical_identity": item.canonical_identity,
                "attempt_ordinal": item.attempt_ordinal,
                "role": item.role,
                "intro_eligible": item.intro_eligible,
                "a1_gap_eligible": item.a1_gap_eligible,
                "source_range": [item.source_start_frame, item.source_end_frame],
                "raw_source_range": [item.source_start_frame, item.source_end_frame],
                "effective_source_range": [
                    item.effective_source_start_frame,
                    item.effective_source_end_frame,
                ],
                "start_snap_delta_frames": item.start_snap_delta_frames,
                "end_snap_delta_frames": item.end_snap_delta_frames,
                "start_mapping_policy": item.start_mapping_policy,
                "end_mapping_policy": item.end_mapping_policy,
                "start_effective_authority": item.start_effective_authority,
                "end_effective_authority": item.end_effective_authority,
                "start_candidate_evidence": [
                    {
                        "side": candidate.side,
                        "effective_source_frame": candidate.effective_source_frame,
                        "original_record_frame": candidate.original_record_frame,
                        "snap_delta_frames": candidate.snap_delta_frames,
                        "absolute_distance_frames": candidate.absolute_distance_frames,
                        "valid": candidate.valid,
                        "rejection_reason": candidate.rejection_reason,
                    }
                    for candidate in item.start_candidate_evidence
                ],
                "original_record_range": [item.original_record_start_frame, item.original_record_end_frame],
                "final_record_range": [item.final_start_frame, item.final_end_frame],
                "gap_range": (
                    [item.gap_start_frame, item.gap_end_frame]
                    if item.a1_gap_eligible
                    else None
                ),
                "start_authority": item.start_authority,
                "end_authority": item.end_authority,
            }
            for item in planned_tuple
        ],
        "carousel": {
            "source_boundary_frame": carousel_boundary.source_frame,
            "raw_source_boundary_frame": carousel_mapping.raw_source_frame,
            "effective_source_boundary_frame": carousel_mapping.effective_source_frame,
            "snap_delta_frames": carousel_mapping.snap_delta_frames,
            "mapping_policy": carousel_mapping.policy,
            "boundary_authority": carousel_boundary.authority,
            "effective_boundary_authority": carousel_mapping.effective_authority,
            "original_record_boundary_frame": carousel_mapping.original_record_frame,
            "final_record_boundary_frame": carousel.v1.record_start_frame,
            "v1_source_range": [
                carousel.v1.source_start_frame,
                carousel.v1.source_start_frame + carousel.v1.duration_frames,
            ],
            "v1_record_range": [carousel.v1.record_start_frame, carousel.v1.record_end_frame],
            "v2_slice_count": len(carousel.v2_slices),
            "v2_crop_bottom_pixels": 530,
            "final_retained_source_content_end_frame": retained.intervals[-1].source_end_frame,
        },
        "structural_audit": audit,
    }
    return GscGymGeometryPlan(
        body_v1=body,
        dialogue_a1=dialogue,
        battles=planned_tuple,
        carousel=carousel,
        carousel_mapping=carousel_mapping,
        manifest=manifest,
        structural_audit=audit,
    )


__all__ = [
    "AUDIT_SCHEMA",
    "AutoEditorRetained",
    "BATTLE_GAP_DUPLICATES_V1_PREROLL",
    "BATTLE_GAP_INSERTS_TIMELINE_FRAMES",
    "BATTLE_GAP_POLICY",
    "BATTLE_BOUNDARY_POLICY",
    "BoundaryCandidateEvidence",
    "BoundaryMapping",
    "BattleAttemptSourceBoundary",
    "BattleSourceBoundary",
    "CarouselSourceBoundary",
    "GscGymGeometryError",
    "GscGymGeometryPlan",
    "MAX_BOUNDARY_SNAP_FRAMES",
    "PlannedBattle",
    "PlannedBattleAttempt",
    "RetainedSourceInterval",
    "SCHEMA",
    "map_carousel_boundary",
    "parse_autoeditor_fcpxml",
    "plan_gsc_gym_geometry",
]
