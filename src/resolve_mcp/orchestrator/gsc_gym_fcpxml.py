"""Pure, deterministic FCPXML assembly for GSC Gym Leader Challenges.

The module deliberately has no Resolve, subprocess, network, random, clock, or
LLM dependency.  Its caller must provide every edit boundary and every media
choice in final-timeline frame coordinates.  Invalid or incomplete geometry is
rejected before any XML is returned.
"""

from __future__ import annotations

import hashlib
import math
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Literal


FPS = 60
WIDTH = 3840
HEIGHT = 2160
TIMELINE_START_FRAME = 216_000
OPENING_FRAMES = 260
OPENING_RATE_PERCENT = 400
BATTLE_GAP_FRAMES = 60
BATTLE_INTRO_FRAMES = 300
BATTLE_EDGE_FADE_FRAMES = 30
BATTLE_BGM_ASSIGNMENT_POLICY = "deterministic_shuffle_bag_no_immediate_repeat"
CAROUSEL_BOTTOM_CROP_PIXELS = 530
CAROUSEL_BOTTOM_CROP_PERCENT = 100 * CAROUSEL_BOTTOM_CROP_PIXELS / HEIGHT
POST_FINAL_REQUIRED_NONBATTLE_FILENAMES = (
    "Dual Screen Lovelife.mp3",
    "Motivated By Clouds.mp3",
    "Roll Me in Stardust.mp3",
)
GOLDEN_GOOSE_FILENAME = "Golden Goose.mp3"

SCHEMA = "gsc_gym_fcpxml_build_v2"
AUDIT_SCHEMA = "gsc_gym_fcpxml_structural_audit_v2"


class GscGymFcpxmlError(ValueError):
    """Raised when an explicit assembly input violates the closed contract."""


@dataclass(frozen=True)
class MediaAsset:
    path: Path | str
    name: str
    duration_frames: int
    source_start_frame: int = 0
    audio_channels: int = 2
    origin_path: Path | str | None = None
    video_fps: int = FPS


@dataclass(frozen=True)
class OpeningSpec:
    asset: MediaAsset
    pre_retimed_rate_percent: int


@dataclass(frozen=True)
class SourceInterval:
    record_start_frame: int
    source_start_frame: int
    duration_frames: int
    label: str = ""

    @property
    def record_end_frame(self) -> int:
        return self.record_start_frame + self.duration_frames


@dataclass(frozen=True)
class DialogueInterval:
    record_start_frame: int
    source_start_frame: int
    duration_frames: int
    label: str
    gain_db: float = 0.0

    @property
    def record_end_frame(self) -> int:
        return self.record_start_frame + self.duration_frames


@dataclass(frozen=True)
class IntroOverlay:
    asset: MediaAsset
    subject: str
    kind: Literal["leader", "rival"]


@dataclass(frozen=True)
class BattleSpec:
    battle_id: str
    role: Literal["leader", "rival", "trainer"]
    start_frame: int
    end_frame: int
    intro: IntroOverlay | None = None
    intro_eligible: bool | None = None
    a1_gap_eligible: bool = True
    canonical_identity: str = ""
    attempt_ordinal: int = 1


@dataclass(frozen=True)
class BgmSegment:
    record_start_frame: int
    source_start_frame: int
    duration_frames: int
    asset: MediaAsset
    role: Literal["opening", "nonbattle", "battle", "carousel"]
    label: str
    gain_db: float = 0.0
    battle_id: str | None = None
    fade_in_frames: int = 0
    fade_out_frames: int = 0

    @property
    def record_end_frame(self) -> int:
        return self.record_start_frame + self.duration_frames


@dataclass(frozen=True)
class CarouselSlice:
    record_start_frame: int
    source_start_frame: int
    duration_frames: int
    label: str

    @property
    def record_end_frame(self) -> int:
        return self.record_start_frame + self.duration_frames


@dataclass(frozen=True)
class CarouselSpec:
    v1: SourceInterval
    v2_slices: tuple[CarouselSlice, ...]


@dataclass(frozen=True)
class OutroSpec:
    asset: MediaAsset
    gain_db: float


@dataclass(frozen=True)
class GscGymFcpxmlSpec:
    timeline_name: str
    source_video: MediaAsset
    dialogue_audio: MediaAsset
    opening: OpeningSpec
    body_v1: tuple[SourceInterval, ...]
    dialogue_a1: tuple[DialogueInterval, ...]
    battles: tuple[BattleSpec, ...]
    bgm_a2: tuple[BgmSegment, ...]
    carousel: CarouselSpec
    outro: OutroSpec
    timeline_start_frame: int = TIMELINE_START_FRAME
    battle_bgm_library_filenames: tuple[str, ...] = ()
    battle_bgm_assignment_policy: str = BATTLE_BGM_ASSIGNMENT_POLICY
    battle_bgm_seed: str = ""


@dataclass(frozen=True)
class GscGymFcpxmlBuild:
    xml: str
    manifest: dict[str, Any]
    structural_audit: dict[str, Any]


@dataclass(frozen=True)
class _PlacedAudio:
    record_start_frame: int
    source_start_frame: int
    duration_frames: int
    label: str
    gain_db: float
    input_index: int

    @property
    def record_end_frame(self) -> int:
        return self.record_start_frame + self.duration_frames


@dataclass(frozen=True)
class _PrimaryAnchor:
    element: ET.Element
    record_start_frame: int
    source_start_frame: int
    duration_frames: int
    role: str

    @property
    def record_end_frame(self) -> int:
        return self.record_start_frame + self.duration_frames


@dataclass(frozen=True)
class _NonbattleOccurrence:
    asset: MediaAsset
    record_start_frame: int
    record_end_frame: int
    source_start_frame: int
    segment_indices: tuple[int, ...]
    roles: tuple[str, ...]


def _require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GscGymFcpxmlError(f"{label} must be an integer >= {minimum}; got {value!r}.")
    return value


def _require_positive(value: object, label: str) -> int:
    return _require_int(value, label, minimum=1)


def _require_gain(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise GscGymFcpxmlError(f"{label} must be a finite number; got {value!r}.")
    return float(value)


def _asset_path(asset: MediaAsset) -> Path:
    value = str(asset.path).strip()
    if not value:
        raise GscGymFcpxmlError("Media asset path may not be empty.")
    path = Path(value)
    if not path.is_absolute():
        raise GscGymFcpxmlError(f"Media asset path must be absolute: {value!r}.")
    return path


def _origin_path(asset: MediaAsset) -> Path:
    if asset.origin_path is None:
        return _asset_path(asset)
    value = str(asset.origin_path).strip()
    path = Path(value)
    if not value or not path.is_absolute():
        raise GscGymFcpxmlError(f"Media origin_path must be absolute: {value!r}.")
    return path


def _validate_asset(asset: MediaAsset, label: str) -> None:
    _asset_path(asset)
    _origin_path(asset)
    if not asset.name.strip():
        raise GscGymFcpxmlError(f"{label}.name may not be empty.")
    _require_positive(asset.duration_frames, f"{label}.duration_frames")
    _require_int(asset.source_start_frame, f"{label}.source_start_frame")
    _require_positive(asset.audio_channels, f"{label}.audio_channels")
    if asset.video_fps not in {30, 60}:
        raise GscGymFcpxmlError(
            f"{label}.video_fps must be 30 or 60 for the closed GSC media contract."
        )


def _validate_source_use(asset: MediaAsset, source_start: int, duration: int, label: str) -> None:
    start = _require_int(source_start, f"{label}.source_start_frame")
    size = _require_positive(duration, f"{label}.duration_frames")
    lower = asset.source_start_frame
    upper = lower + asset.duration_frames
    if start < lower or start + size > upper:
        raise GscGymFcpxmlError(
            f"{label} source range [{start}, {start + size}) is outside "
            f"{asset.name!r} [{lower}, {upper})."
        )


def _normalized_words(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _lineage_words(asset: MediaAsset) -> str:
    return _normalized_words(str(_origin_path(asset)).replace("\\", "/"))


def _is_dual_screen_lovelife(asset: MediaAsset) -> bool:
    return "dual screen lovelife" in _lineage_words(asset)


def _is_golden_goose(asset: MediaAsset) -> bool:
    return "golden goose" in _lineage_words(asset)


def _is_gsc_battle_audio(asset: MediaAsset) -> bool:
    normalized = str(_origin_path(asset)).replace("\\", "/").casefold()
    return "/gscnewlayout/audio/gen 2 battle audio/" in f"/{normalized.lstrip('/')}"


def _normalized_path_key(path: Path) -> str:
    return str(path).replace("\\", "/").casefold()


def _origin_key(asset: MediaAsset) -> str:
    return _normalized_path_key(_origin_path(asset))


def _origin_filename(asset: MediaAsset) -> str:
    return _origin_path(asset).name


def _is_general_occurrence_continuation(
    left: BgmSegment,
    right: BgmSegment,
) -> bool:
    """Return whether adjacent original-source rows are one occurrence."""

    if (
        left.role == "battle"
        or right.role == "battle"
        or left.record_end_frame != right.record_start_frame
        or _origin_key(left.asset) != _origin_key(right.asset)
    ):
        return False
    return (
        _normalized_path_key(_asset_path(left.asset))
        == _normalized_path_key(_asset_path(right.asset))
        and right.source_start_frame
        == left.source_start_frame + left.duration_frames
    )


def _nonbattle_occurrences(spec: GscGymFcpxmlSpec) -> tuple[_NonbattleOccurrence, ...]:
    occurrences: list[_NonbattleOccurrence] = []
    previous_general: BgmSegment | None = None
    for index, row in enumerate(spec.bgm_a2, start=1):
        if row.role == "battle":
            previous_general = None
            continue
        if (
            occurrences
            and previous_general is not None
            and _is_general_occurrence_continuation(previous_general, row)
        ):
            prior = occurrences[-1]
            occurrences[-1] = _NonbattleOccurrence(
                asset=prior.asset,
                record_start_frame=prior.record_start_frame,
                record_end_frame=row.record_end_frame,
                source_start_frame=prior.source_start_frame,
                segment_indices=(*prior.segment_indices, index),
                roles=(*prior.roles, row.role),
            )
        else:
            occurrences.append(
                _NonbattleOccurrence(
                    asset=row.asset,
                    record_start_frame=row.record_start_frame,
                    record_end_frame=row.record_end_frame,
                    source_start_frame=row.source_start_frame,
                    segment_indices=(index,),
                    roles=(row.role,),
                )
            )
        previous_general = row
    return tuple(occurrences)


def _nonbattle_bgm_contract(spec: GscGymFcpxmlSpec) -> dict[str, Any]:
    """Validate and describe the closed RBY-parity non-battle BGM contract."""

    occurrences = _nonbattle_occurrences(spec)
    if not occurrences:
        raise GscGymFcpxmlError("A2 has no non-battle BGM occurrences.")
    final_battle_end = spec.battles[-1].end_frame
    identity_counts: dict[str, int] = {}
    for occurrence in occurrences:
        identity = _origin_filename(occurrence.asset).casefold()
        identity_counts[identity] = identity_counts.get(identity, 0) + 1

    dual_occurrences = [
        occurrence for occurrence in occurrences
        if _is_dual_screen_lovelife(occurrence.asset)
    ]
    dual_starts = [item.record_start_frame for item in dual_occurrences]
    if dual_starts != [0, final_battle_end]:
        raise GscGymFcpxmlError(
            "Dual Screen Lovelife must have exactly two occurrence starts: "
            f"frame 0 and final battle end {final_battle_end}; got {dual_starts}."
        )
    if len({_origin_key(item.asset) for item in dual_occurrences}) != 1:
        raise GscGymFcpxmlError(
            "Post-final Dual Screen Lovelife must reuse the exact opening identity."
        )

    dual_filename = POST_FINAL_REQUIRED_NONBATTLE_FILENAMES[0].casefold()
    repeated_non_dual = {
        name: count
        for name, count in identity_counts.items()
        if name != dual_filename and count > 1
    }
    if repeated_non_dual:
        raise GscGymFcpxmlError(
            "Non-battle BGM identities may not repeat outside the two approved "
            f"Dual Screen Lovelife occurrences: {repeated_non_dual}."
        )

    occurrence_by_start = {item.record_start_frame: item for item in occurrences}
    segment_by_start = {item.record_start_frame: item for item in spec.bgm_a2}
    handoffs: list[dict[str, Any]] = []
    for index, battle in enumerate(spec.battles):
        next_battle = spec.battles[index + 1] if index + 1 < len(spec.battles) else None
        if next_battle is not None and next_battle.start_frame == battle.end_frame:
            successor = segment_by_start.get(battle.end_frame)
            if (
                successor is None
                or successor.role != "battle"
                or successor.battle_id != next_battle.battle_id
            ):
                raise GscGymFcpxmlError(
                    f"Zero-gap battle handoff after {battle.battle_id!r} must be direct "
                    f"to battle {next_battle.battle_id!r}."
                )
            handoffs.append(
                {
                    "battle_id": battle.battle_id,
                    "battle_end_frame": battle.end_frame,
                    "mode": "direct_battle",
                    "next_battle_id": next_battle.battle_id,
                }
            )
            continue

        next_boundary = (
            next_battle.start_frame
            if next_battle is not None
            else spec.carousel.v1.record_end_frame
        )
        if next_boundary <= battle.end_frame:
            raise GscGymFcpxmlError(
                f"Battle {battle.battle_id!r} has an invalid post-battle boundary."
            )
        fresh = occurrence_by_start.get(battle.end_frame)
        if fresh is None or fresh.source_start_frame != 0:
            raise GscGymFcpxmlError(
                f"Positive post-battle gap after {battle.battle_id!r} must begin a "
                "fresh source-zero non-battle BGM identity at the battle end."
            )
        handoffs.append(
            {
                "battle_id": battle.battle_id,
                "battle_end_frame": battle.end_frame,
                "mode": "fresh_source_zero_nonbattle",
                "identity": _origin_filename(fresh.asset),
                "origin_path": str(_origin_path(fresh.asset)),
            }
        )

    post_final = [
        item for item in occurrences
        if item.record_start_frame >= final_battle_end
    ]
    expected_prefix = [name.casefold() for name in POST_FINAL_REQUIRED_NONBATTLE_FILENAMES]
    actual_prefix = [
        _origin_filename(item.asset).casefold()
        for item in post_final[: len(expected_prefix)]
    ]
    if len(post_final) != 4 or actual_prefix != expected_prefix:
        raise GscGymFcpxmlError(
            "Post-final non-battle BGM must contain exactly four identity starts: "
            "Dual Screen Lovelife, Motivated By Clouds, Roll Me in Stardust, then "
            "one unused random track that owns the remainder."
        )
    if any(item.source_start_frame != 0 for item in post_final):
        raise GscGymFcpxmlError(
            "Every post-final non-battle BGM identity must begin at source frame zero."
        )
    reserved_filenames = {
        *(name.casefold() for name in POST_FINAL_REQUIRED_NONBATTLE_FILENAMES),
        GOLDEN_GOOSE_FILENAME.casefold(),
    }
    filler_identity = _origin_filename(post_final[3].asset).casefold()
    identities_before_filler = {
        _origin_filename(item.asset).casefold()
        for item in occurrences
        if item.record_start_frame < post_final[3].record_start_frame
    }
    if filler_identity in reserved_filenames or filler_identity in identities_before_filler:
        raise GscGymFcpxmlError(
            "The fourth post-final BGM identity must be unused and nonreserved."
        )

    occurrence_evidence = [
        {
            "occurrence_index": index,
            "identity": _origin_filename(item.asset),
            "origin_path": str(_origin_path(item.asset)),
            "record_range": [item.record_start_frame, item.record_end_frame],
            "source_start_frame": item.source_start_frame,
            "segment_indices": list(item.segment_indices),
            "roles": list(item.roles),
        }
        for index, item in enumerate(occurrences, start=1)
    ]
    return {
        "schema": "gsc_fcpxml_nonbattle_bgm_contract_v2",
        "status": "pass",
        "occurrence_coalescing_policy": (
            "same_original_path_plus_exact_source_continuity"
        ),
        "occurrence_count": len(occurrences),
        "occurrences": occurrence_evidence,
        "identity_occurrence_counts": {
            _origin_filename(item.asset): identity_counts[
                _origin_filename(item.asset).casefold()
            ]
            for item in occurrences
        },
        "dual_screen_lovelife_occurrence_starts": dual_starts,
        "dual_screen_lovelife_policy": "exactly_twice_opening_and_post_final",
        "golden_goose_blocked": True,
        "post_battle_handoffs": handoffs,
        "post_final_start_frame": final_battle_end,
        "post_final_required_prefix": list(POST_FINAL_REQUIRED_NONBATTLE_FILENAMES),
        "post_final_first_four_identities": [
            _origin_filename(item.asset) for item in post_final[:4]
        ],
        "post_final_occurrence_count": len(post_final),
        "post_final_fourth_identity_owns_remainder": True,
        "post_final_fourth_identity_unused_nonreserved": True,
    }


def _validate_ordered_contiguous(
    rows: Iterable[tuple[int, int]],
    *,
    expected_start: int,
    expected_end: int,
    label: str,
) -> None:
    cursor = expected_start
    for index, (start, duration) in enumerate(rows, start=1):
        if start != cursor:
            raise GscGymFcpxmlError(
                f"{label}[{index}] starts at {start}; exact contiguous start {cursor} is required."
            )
        cursor += duration
    if cursor != expected_end:
        raise GscGymFcpxmlError(
            f"{label} ends at {cursor}; exact end {expected_end} is required."
        )


def _place_dialogue_losslessly(
    intervals: tuple[DialogueInterval, ...],
) -> tuple[_PlacedAudio, ...]:
    """Place every authoritative A1 interval without trimming or splitting."""

    return tuple(
        _PlacedAudio(
            record_start_frame=interval.record_start_frame,
            source_start_frame=interval.source_start_frame,
            duration_frames=interval.duration_frames,
            label=interval.label,
            gain_db=float(interval.gain_db),
            input_index=input_index,
        )
        for input_index, interval in enumerate(intervals, start=1)
    )


def _battle_assignment_rows(spec: GscGymFcpxmlSpec) -> list[dict[str, Any]]:
    """Return one structured source assignment for every physical battle."""

    rows: list[dict[str, Any]] = []
    for battle in spec.battles:
        segments = [
            item
            for item in spec.bgm_a2
            if item.role == "battle" and item.battle_id == battle.battle_id
        ]
        if not segments:
            raise GscGymFcpxmlError(
                f"Battle {battle.battle_id!r} has no structured A2 assignment."
            )
        segments.sort(key=lambda item: item.record_start_frame)
        origins = {
            str(_origin_path(item.asset).resolve()).replace("\\", "/").casefold():
            _origin_path(item.asset).resolve()
            for item in segments
        }
        if len(origins) != 1:
            raise GscGymFcpxmlError(
                f"Battle {battle.battle_id!r} changes BGM source inside its range."
            )
        origin = next(iter(origins.values()))
        first = segments[0]
        if (
            first.record_start_frame != battle.start_frame
            or first.source_start_frame != first.asset.source_start_frame
        ):
            raise GscGymFcpxmlError(
                f"Battle {battle.battle_id!r} must restart its original BGM source "
                "at the physical attempt boundary."
            )
        rows.append(
            {
                "battle_id": battle.battle_id,
                "canonical_identity": battle.canonical_identity,
                "attempt_ordinal": battle.attempt_ordinal,
                "record_range": [battle.start_frame, battle.end_frame],
                "source_path": str(origin),
                "source_name": origin.name,
                "initial_source_frame": first.source_start_frame,
                "asset_source_start_frame": first.asset.source_start_frame,
                "segment_count": len(segments),
                "policy": spec.battle_bgm_assignment_policy,
                "seed": spec.battle_bgm_seed,
            }
        )
    return rows


def _validate_spec(spec: GscGymFcpxmlSpec) -> tuple[_PlacedAudio, ...]:
    if not spec.timeline_name.strip():
        raise GscGymFcpxmlError("timeline_name may not be empty.")
    if spec.timeline_start_frame != TIMELINE_START_FRAME:
        raise GscGymFcpxmlError(
            f"GSC timeline_start_frame must be {TIMELINE_START_FRAME}; got {spec.timeline_start_frame}."
        )

    _validate_asset(spec.source_video, "source_video")
    _validate_asset(spec.dialogue_audio, "dialogue_audio")
    _validate_asset(spec.opening.asset, "opening.asset")
    _validate_asset(spec.outro.asset, "outro.asset")
    _require_gain(spec.outro.gain_db, "outro.gain_db")

    if spec.opening.pre_retimed_rate_percent != OPENING_RATE_PERCENT:
        raise GscGymFcpxmlError(
            f"Opening must be the approved pre-retimed {OPENING_RATE_PERCENT}% derivative."
        )
    if spec.opening.asset.duration_frames != OPENING_FRAMES:
        raise GscGymFcpxmlError(
            f"Opening derivative must be exactly {OPENING_FRAMES} frames at {FPS} fps."
        )
    if spec.opening.asset.video_fps != 30:
        raise GscGymFcpxmlError(
            "The approved GSC 400pct opening derivative must retain its native 30 fps media format."
        )
    if spec.source_video.video_fps != 60 or spec.outro.asset.video_fps != 60:
        raise GscGymFcpxmlError("Gameplay source and GSC outro media must be native 60 fps.")
    if not spec.body_v1:
        raise GscGymFcpxmlError("body_v1 must contain at least one explicit source interval.")

    cursor = OPENING_FRAMES
    for index, interval in enumerate(spec.body_v1, start=1):
        _require_int(interval.record_start_frame, f"body_v1[{index}].record_start_frame")
        _require_positive(interval.duration_frames, f"body_v1[{index}].duration_frames")
        if interval.record_start_frame != cursor:
            raise GscGymFcpxmlError(
                f"body_v1[{index}] starts at {interval.record_start_frame}; {cursor} is required."
            )
        _validate_source_use(
            spec.source_video,
            interval.source_start_frame,
            interval.duration_frames,
            f"body_v1[{index}]",
        )
        cursor = interval.record_end_frame

    carousel = spec.carousel
    _require_positive(carousel.v1.duration_frames, "carousel.v1.duration_frames")
    if carousel.v1.record_start_frame != cursor:
        raise GscGymFcpxmlError(
            f"Carousel V1 starts at {carousel.v1.record_start_frame}; body V1 ends at {cursor}."
        )
    _validate_source_use(
        spec.source_video,
        carousel.v1.source_start_frame,
        carousel.v1.duration_frames,
        "carousel.v1",
    )
    carousel_end = carousel.v1.record_end_frame
    if not carousel.v2_slices:
        raise GscGymFcpxmlError("Carousel requires at least one V2 slice.")
    for index, item in enumerate(carousel.v2_slices, start=1):
        if not item.label.strip():
            raise GscGymFcpxmlError(f"carousel.v2_slices[{index}].label may not be empty.")
        _require_positive(item.duration_frames, f"carousel.v2_slices[{index}].duration_frames")
        _validate_source_use(
            spec.source_video,
            item.source_start_frame,
            item.duration_frames,
            f"carousel.v2_slices[{index}]",
        )
    _validate_ordered_contiguous(
        ((item.record_start_frame, item.duration_frames) for item in carousel.v2_slices),
        expected_start=carousel.v1.record_start_frame,
        expected_end=carousel_end,
        label="carousel.v2_slices",
    )

    _require_positive(spec.outro.asset.duration_frames, "outro.asset.duration_frames")
    battles = spec.battles
    if not battles:
        raise GscGymFcpxmlError("A GSC Gym Leader Challenge must contain at least one retained battle.")
    if not any(item.role == "leader" for item in battles):
        raise GscGymFcpxmlError("A GSC Gym Leader Challenge must contain at least one leader battle.")
    previous_battle_end = OPENING_FRAMES
    previous_gap_end = OPENING_FRAMES
    previous_intro_end = OPENING_FRAMES
    battle_ids: set[str] = set()
    identity_last_ordinals: dict[str, int] = {}
    identity_roles: dict[str, str] = {}
    for index, battle in enumerate(battles, start=1):
        prior_battle_end = previous_battle_end
        if not battle.battle_id.strip() or battle.battle_id in battle_ids:
            raise GscGymFcpxmlError(f"battles[{index}].battle_id must be non-empty and unique.")
        battle_ids.add(battle.battle_id)
        if battle.role not in {"leader", "rival", "trainer"}:
            raise GscGymFcpxmlError(f"Unsupported battle role: {battle.role!r}.")
        canonical_identity = " ".join(battle.canonical_identity.casefold().split())
        if not canonical_identity:
            raise GscGymFcpxmlError(
                f"battles[{index}].canonical_identity must be non-empty."
            )
        if isinstance(battle.attempt_ordinal, bool) or not isinstance(
            battle.attempt_ordinal, int
        ) or battle.attempt_ordinal < 1:
            raise GscGymFcpxmlError(
                f"battles[{index}].attempt_ordinal must be a positive integer."
            )
        prior_ordinal = identity_last_ordinals.get(canonical_identity)
        if prior_ordinal is not None and battle.attempt_ordinal <= prior_ordinal:
            raise GscGymFcpxmlError(
                f"battles[{index}] identity ordinal must be greater than retained "
                f"ordinal {prior_ordinal}."
            )
        prior_role = identity_roles.get(canonical_identity)
        if prior_role is not None and prior_role != battle.role:
            raise GscGymFcpxmlError(
                f"battles[{index}] changes canonical identity role from "
                f"{prior_role!r} to {battle.role!r}."
            )
        identity_last_ordinals[canonical_identity] = battle.attempt_ordinal
        identity_roles[canonical_identity] = battle.role
        _require_int(battle.start_frame, f"battles[{index}].start_frame")
        _require_positive(battle.end_frame - battle.start_frame, f"battles[{index}] duration")
        if battle.start_frame < previous_battle_end or battle.end_frame > carousel.v1.record_start_frame:
            raise GscGymFcpxmlError(
                f"battles[{index}] is out of order or outside the body V1 range."
            )
        if not isinstance(battle.a1_gap_eligible, bool):
            raise GscGymFcpxmlError(
                f"battles[{index}].a1_gap_eligible must be boolean."
            )
        expected_gap_eligible = battle.attempt_ordinal == 1
        if battle.a1_gap_eligible != expected_gap_eligible:
            raise GscGymFcpxmlError(
                f"battles[{index}] A1 gap eligibility must equal identity attempt "
                "ordinal == 1."
            )
        if battle.a1_gap_eligible:
            gap_start = battle.start_frame - BATTLE_GAP_FRAMES
            if (
                gap_start < OPENING_FRAMES
                or gap_start < previous_gap_end
                or gap_start < prior_battle_end
            ):
                raise GscGymFcpxmlError(
                    f"battles[{index}] cannot receive a distinct 60-frame A1 gap."
                )
            previous_gap_end = battle.start_frame
        previous_battle_end = battle.end_frame

        default_intro_eligible = (
            battle.role in {"leader", "rival"}
            and battle.attempt_ordinal == 1
        )
        intro_eligible = (
            default_intro_eligible
            if battle.intro_eligible is None
            else battle.intro_eligible
        )
        if not isinstance(intro_eligible, bool):
            raise GscGymFcpxmlError(
                f"battles[{index}].intro_eligible must be boolean when supplied."
            )
        if intro_eligible != default_intro_eligible:
            raise GscGymFcpxmlError(
                f"battles[{index}] intro eligibility must identify only leader/rival "
                "identity attempt ordinal 1."
            )
        if battle.role == "trainer" and intro_eligible:
            raise GscGymFcpxmlError(
                f"Trainer battle {battle.battle_id!r} may not be intro-eligible."
            )
        if intro_eligible:
            if battle.intro is None:
                raise GscGymFcpxmlError(f"Major battle {battle.battle_id!r} requires a V2 intro.")
            if battle.intro.kind != battle.role:
                raise GscGymFcpxmlError(
                    f"Intro kind {battle.intro.kind!r} does not match {battle.role!r}."
                )
            if not battle.intro.subject.strip():
                raise GscGymFcpxmlError(f"Intro subject for {battle.battle_id!r} may not be empty.")
            _validate_asset(battle.intro.asset, f"battles[{index}].intro.asset")
            if battle.intro.asset.video_fps != 60:
                raise GscGymFcpxmlError(
                    f"Battle intro {battle.intro.asset.name!r} must be native 60 fps."
                )
            _validate_source_use(
                battle.intro.asset,
                battle.intro.asset.source_start_frame,
                BATTLE_INTRO_FRAMES,
                f"battles[{index}].intro",
            )
            intro_start = battle.start_frame - BATTLE_INTRO_FRAMES
            if (
                intro_start < OPENING_FRAMES
                or intro_start < previous_intro_end
                or intro_start < prior_battle_end
            ):
                raise GscGymFcpxmlError(
                    f"Intro for {battle.battle_id!r} overlaps the opening, a prior battle, "
                    "or another V2 intro."
                )
            previous_intro_end = battle.start_frame
        elif battle.intro is not None:
            raise GscGymFcpxmlError(
                f"Non-eligible battle {battle.battle_id!r} may not receive a leader/rival intro."
            )

    previous_dialogue_end = OPENING_FRAMES
    for index, interval in enumerate(spec.dialogue_a1, start=1):
        if not interval.label.strip():
            raise GscGymFcpxmlError(f"dialogue_a1[{index}].label may not be empty.")
        _require_positive(interval.duration_frames, f"dialogue_a1[{index}].duration_frames")
        _require_gain(interval.gain_db, f"dialogue_a1[{index}].gain_db")
        if (
            interval.record_start_frame < previous_dialogue_end
            or interval.record_start_frame < OPENING_FRAMES
            or interval.record_end_frame > carousel_end
        ):
            raise GscGymFcpxmlError(
                f"dialogue_a1[{index}] is overlapping, out of order, or outside main V1."
            )
        _validate_source_use(
            spec.dialogue_audio,
            interval.source_start_frame,
            interval.duration_frames,
            f"dialogue_a1[{index}]",
        )
        previous_dialogue_end = interval.record_end_frame

    expected_dialogue_gaps = [
        (battle.start_frame - BATTLE_GAP_FRAMES, battle.start_frame)
        for battle in battles
        if battle.a1_gap_eligible
    ]
    observed_dialogue_gaps: list[tuple[int, int]] = []
    dialogue_cursor = OPENING_FRAMES
    for interval in spec.dialogue_a1:
        if interval.record_start_frame > dialogue_cursor:
            observed_dialogue_gaps.append(
                (dialogue_cursor, interval.record_start_frame)
            )
        dialogue_cursor = interval.record_end_frame
    if dialogue_cursor < carousel_end:
        observed_dialogue_gaps.append((dialogue_cursor, carousel_end))
    if observed_dialogue_gaps != expected_dialogue_gaps:
        raise GscGymFcpxmlError(
            "A1 timeline holes must exactly equal ordinal-1 battle gaps; "
            f"expected={expected_dialogue_gaps}, observed={observed_dialogue_gaps}."
        )

    for index, battle in enumerate(battles, start=1):
        if not battle.a1_gap_eligible:
            continue
        gap_start = battle.start_frame - BATTLE_GAP_FRAMES
        gap_end = battle.start_frame
        intersections = [
            interval
            for interval in spec.dialogue_a1
            if max(interval.record_start_frame, gap_start)
            < min(interval.record_end_frame, gap_end)
        ]
        left = [
            interval
            for interval in spec.dialogue_a1
            if interval.record_end_frame == gap_start
        ]
        right = [
            interval
            for interval in spec.dialogue_a1
            if interval.record_start_frame == gap_end
        ]
        expected_bridge_label = f"battle-gap-v1-bridge:{battle.battle_id}"
        named_bridges = [
            interval
            for interval in spec.body_v1
            if interval.label == expected_bridge_label
        ]
        if intersections or len(left) != 1 or len(right) != 1:
            raise GscGymFcpxmlError(
                f"battles[{index}] gap must be a real 60-frame insert between one "
                "complete outgoing and one complete incoming A1 interval; "
                f"intersections={len(intersections)}, left={len(left)}, right={len(right)}."
            )
        if (
            len(named_bridges) != 1
            or named_bridges[0].record_start_frame != gap_start
            or named_bridges[0].record_end_frame != gap_end
        ):
            raise GscGymFcpxmlError(
                f"battles[{index}] gap requires one exact source-backed V1 bridge "
                f"named {expected_bridge_label!r}; found {len(named_bridges)}."
            )
        bridge = named_bridges[0]
        if bridge.source_start_frame + BATTLE_GAP_FRAMES != right[0].source_start_frame:
            raise GscGymFcpxmlError(
                f"battles[{index}] V1 bridge must extend the incoming segment left by "
                f"exactly {BATTLE_GAP_FRAMES} source frames."
            )
    expected_bridge_labels = {
        f"battle-gap-v1-bridge:{battle.battle_id}"
        for battle in battles
        if battle.a1_gap_eligible
    }
    actual_bridge_labels = {
        interval.label
        for interval in spec.body_v1
        if interval.label.startswith("battle-gap-v1-bridge:")
    }
    if actual_bridge_labels != expected_bridge_labels:
        raise GscGymFcpxmlError(
            "V1 battle-gap bridge labels must exactly match the battle population; "
            f"expected={sorted(expected_bridge_labels)}, "
            f"actual={sorted(actual_bridge_labels)}."
        )

    if not spec.bgm_a2:
        raise GscGymFcpxmlError("bgm_a2 must be a complete explicit plan.")
    for index, segment in enumerate(spec.bgm_a2, start=1):
        if not segment.label.strip():
            raise GscGymFcpxmlError(f"bgm_a2[{index}].label may not be empty.")
        if segment.role not in {"opening", "nonbattle", "battle", "carousel"}:
            raise GscGymFcpxmlError(f"Unsupported A2 role: {segment.role!r}.")
        _validate_asset(segment.asset, f"bgm_a2[{index}].asset")
        _validate_source_use(
            segment.asset,
            segment.source_start_frame,
            segment.duration_frames,
            f"bgm_a2[{index}]",
        )
        _require_gain(segment.gain_db, f"bgm_a2[{index}].gain_db")
        asset_path = _asset_path(segment.asset)
        origin_path = _origin_path(segment.asset)
        if (
            _normalized_path_key(asset_path) != _normalized_path_key(origin_path)
            or segment.asset.name != asset_path.name
            or asset_path.suffix.casefold() != ".mp3"
            or any(part.casefold() == "a2-fades" for part in asset_path.parts)
        ):
            raise GscGymFcpxmlError(
                f"bgm_a2[{index}] must use its original MP3 library path and filename; "
                "renamed or a2-fades derivatives are forbidden."
            )
        for edge, value in (
            ("fade_in_frames", segment.fade_in_frames),
            ("fade_out_frames", segment.fade_out_frames),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value not in {0, BATTLE_EDGE_FADE_FRAMES}
                or value > segment.duration_frames
            ):
                raise GscGymFcpxmlError(
                    f"bgm_a2[{index}].{edge} must be 0 or exact "
                    f"{BATTLE_EDGE_FADE_FRAMES} frames within the segment."
                )
        if segment.role == "battle":
            if not str(segment.battle_id or "").strip():
                raise GscGymFcpxmlError(
                    f"Battle A2 segment {segment.label!r} requires a structured battle_id."
                )
        elif segment.battle_id is not None:
            raise GscGymFcpxmlError(
                f"Non-battle A2 segment {segment.label!r} may not carry battle_id."
            )
        if _is_golden_goose(segment.asset):
            raise GscGymFcpxmlError("Golden Goose is blocked from A2; the linked MOV owns outro audio.")
        if segment.role == "battle" and not _is_gsc_battle_audio(segment.asset):
            raise GscGymFcpxmlError(
                f"Battle A2 segment {segment.label!r} is not lineaged to "
                "GSCNewLayout/audio/Gen 2 battle audio."
            )
        if segment.role != "battle" and _is_gsc_battle_audio(segment.asset):
            raise GscGymFcpxmlError(
                f"Gen 2 battle audio may not be used by non-battle segment {segment.label!r}."
            )

    _validate_ordered_contiguous(
        ((item.record_start_frame, item.duration_frames) for item in spec.bgm_a2),
        expected_start=0,
        expected_end=carousel_end,
        label="bgm_a2",
    )
    if spec.bgm_a2[0].fade_in_frames != 0:
        raise GscGymFcpxmlError("A2 may not fade in at timeline frame zero.")
    if spec.bgm_a2[-1].fade_out_frames != BATTLE_EDGE_FADE_FRAMES:
        raise GscGymFcpxmlError(
            f"A2 must end with an exact {BATTLE_EDGE_FADE_FRAMES}-frame fade at the outro."
        )
    for index, (left, right) in enumerate(zip(spec.bgm_a2, spec.bgm_a2[1:]), start=1):
        left_family = "battle" if left.role == "battle" else "general"
        right_family = "battle" if right.role == "battle" else "general"
        required = BATTLE_EDGE_FADE_FRAMES if left_family != right_family else 0
        if left.fade_out_frames != required or right.fade_in_frames != required:
            raise GscGymFcpxmlError(
                "A2 transition fade contract failed between segments "
                f"{index} and {index + 1}: required={required}, "
                f"left_out={left.fade_out_frames}, right_in={right.fade_in_frames}."
            )
    opening_rows = [item for item in spec.bgm_a2 if item.role == "opening"]
    if not opening_rows:
        raise GscGymFcpxmlError("A2 requires the initial Dual Screen Lovelife source tape.")
    opening_bgm = opening_rows[0]
    if (
        opening_bgm.record_start_frame != 0
        or opening_bgm.record_end_frame < OPENING_FRAMES
        or not _is_dual_screen_lovelife(opening_bgm.asset)
    ):
        raise GscGymFcpxmlError(
            "Dual Screen Lovelife must begin at frame zero and cover the complete 260-frame picture intro."
        )
    if any(not _is_dual_screen_lovelife(item.asset) for item in opening_rows):
        raise GscGymFcpxmlError("Only Dual Screen Lovelife may carry the opening A2 role.")

    for segment in spec.bgm_a2:
        overlaps = [
            battle
            for battle in battles
            if max(segment.record_start_frame, battle.start_frame)
            < min(segment.record_end_frame, battle.end_frame)
        ]
        if segment.role == "battle":
            if len(overlaps) != 1:
                raise GscGymFcpxmlError(
                    f"Battle BGM segment {segment.label!r} must lie inside exactly one battle."
                )
            battle = overlaps[0]
            if segment.battle_id != battle.battle_id:
                raise GscGymFcpxmlError(
                    f"Battle BGM segment {segment.label!r} declares {segment.battle_id!r} "
                    f"but overlaps {battle.battle_id!r}."
                )
            if (
                segment.record_start_frame < battle.start_frame
                or segment.record_end_frame > battle.end_frame
            ):
                raise GscGymFcpxmlError(
                    f"Battle BGM segment {segment.label!r} crosses a battle boundary."
                )
        elif overlaps:
            raise GscGymFcpxmlError(
                f"Non-battle A2 segment {segment.label!r} overlaps a battle interval."
            )
    for battle in battles:
        coverage = [
            (segment.record_start_frame, segment.duration_frames)
            for segment in spec.bgm_a2
            if segment.role == "battle"
            and segment.battle_id == battle.battle_id
            and segment.record_start_frame >= battle.start_frame
            and segment.record_end_frame <= battle.end_frame
        ]
        _validate_ordered_contiguous(
            coverage,
            expected_start=battle.start_frame,
            expected_end=battle.end_frame,
            label=f"battle BGM for {battle.battle_id}",
        )

    _nonbattle_bgm_contract(spec)

    assignments = _battle_assignment_rows(spec)
    if spec.battle_bgm_assignment_policy != BATTLE_BGM_ASSIGNMENT_POLICY:
        raise GscGymFcpxmlError(
            "Battle BGM assignment policy must be the deterministic complete shuffle bag."
        )
    library = tuple(spec.battle_bgm_library_filenames)
    if library:
        if any(not str(name).strip() for name in library) or len(set(library)) != len(library):
            raise GscGymFcpxmlError("Battle BGM library filenames must be non-empty and unique.")
        if not spec.battle_bgm_seed.strip():
            raise GscGymFcpxmlError("A source-bound battle BGM seed is required with a library contract.")
        assigned_names = [str(row["source_name"]) for row in assignments]
        if any(name not in set(library) for name in assigned_names):
            raise GscGymFcpxmlError("A battle assignment is outside the contracted Gen 2 library.")
        if len(library) > 1 and any(
            left == right for left, right in zip(assigned_names, assigned_names[1:])
        ):
            raise GscGymFcpxmlError("Battle BGM assignments contain an immediate repeat.")
        for start in range(0, len(assigned_names) - len(library) + 1, len(library)):
            if set(assigned_names[start:start + len(library)]) != set(library):
                raise GscGymFcpxmlError(
                    f"Battle BGM assignment bag at index {start} is not complete."
                )

    return _place_dialogue_losslessly(spec.dialogue_a1)


def _fcpxml_time(frames: int) -> str:
    value = Fraction(frames, FPS)
    return f"{value.numerator}/{value.denominator}s"


def _frames(value: str | None) -> int:
    if not value or not value.endswith("s"):
        raise GscGymFcpxmlError(f"Invalid FCPXML time: {value!r}.")
    rendered = Fraction(value[:-1]) * FPS
    if rendered.denominator != 1:
        raise GscGymFcpxmlError(f"FCPXML time is not frame-aligned at {FPS} fps: {value!r}.")
    return rendered.numerator


def _uri(path: Path) -> str:
    raw = str(path).replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", raw):
        return "file://localhost/" + urllib.parse.quote(raw, safe="/:")
    return "file://localhost" + urllib.parse.quote(raw, safe="/")


def _gain(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


class _ResourceRegistry:
    def __init__(self, resources: ET.Element) -> None:
        self.resources = resources
        self.counter = 2
        self.cache: dict[
            tuple[str, bool, bool],
            tuple[str, tuple[str, int, int, int, int | None, str]],
        ] = {}
        self.rows: list[dict[str, Any]] = []

    def add(self, asset: MediaAsset, *, video: bool, audio: bool) -> str:
        path = _asset_path(asset)
        key = (_uri(path), video, audio)
        descriptor = (
            asset.name,
            asset.source_start_frame,
            asset.duration_frames,
            asset.audio_channels,
            asset.video_fps,
            _normalized_path_key(_origin_path(asset)),
        )
        if key in self.cache:
            ref, registered = self.cache[key]
            if descriptor != registered:
                raise GscGymFcpxmlError(
                    "One original-media URI has conflicting full-media descriptors: "
                    f"{path}."
                )
            return ref
        ref = f"r{self.counter}"
        self.counter += 1
        attrs = {
            "id": ref,
            "name": asset.name,
            "start": _fcpxml_time(asset.source_start_frame),
            "duration": _fcpxml_time(asset.duration_frames),
        }
        if video:
            attrs["hasVideo"] = "1"
            attrs["format"] = "r1" if asset.video_fps == 30 else "r0"
        if audio:
            attrs["hasAudio"] = "1"
            attrs["audioSources"] = "1"
            attrs["audioChannels"] = str(asset.audio_channels)
        node = ET.SubElement(self.resources, "asset", attrs)
        ET.SubElement(node, "media-rep", {"kind": "original-media", "src": key[0]})
        self.cache[key] = (ref, descriptor)
        self.rows.append(
            {
                "ref": ref,
                "name": asset.name,
                "path": str(path),
                "uri": key[0],
                "has_video": video,
                "has_audio": audio,
                "source_start_frame": asset.source_start_frame,
                "duration_frames": asset.duration_frames,
                "origin_path": str(_origin_path(asset)),
                "video_fps": asset.video_fps,
            }
        )
        return ref


def _transform(parent: ET.Element) -> None:
    ET.SubElement(parent, "adjust-transform", {"position": "0 0", "anchor": "0 0", "scale": "1 1"})


def _primary_clip(
    spine: ET.Element,
    *,
    name: str,
    record_start: int,
    source_start: int,
    duration: int,
    video_ref: str,
    asset: MediaAsset,
) -> ET.Element:
    node = ET.SubElement(
        spine,
        "clip",
        {
            "enabled": "1",
            "name": name,
            "format": "r1" if asset.video_fps == 30 else "r0",
            "offset": _fcpxml_time(TIMELINE_START_FRAME + record_start),
            "start": _fcpxml_time(source_start),
            "duration": _fcpxml_time(duration),
            "tcFormat": "NDF",
        },
    )
    _transform(node)
    ET.SubElement(
        node,
        "video",
        {
            "ref": video_ref,
            "offset": _fcpxml_time(asset.source_start_frame),
            "start": _fcpxml_time(asset.source_start_frame),
            "duration": _fcpxml_time(asset.duration_frames),
        },
    )
    return node


def _anchor_for(anchors: list[_PrimaryAnchor], record_frame: int, label: str) -> _PrimaryAnchor:
    for anchor in anchors:
        if anchor.record_start_frame <= record_frame < anchor.record_end_frame:
            return anchor
    raise GscGymFcpxmlError(f"{label} starts at {record_frame}, outside primary V1 coverage.")


def _connected_offset(anchor: _PrimaryAnchor, record_frame: int) -> int:
    return anchor.source_start_frame + record_frame - anchor.record_start_frame


def _add_connected_audio(
    anchor: _PrimaryAnchor,
    *,
    ref: str,
    name: str,
    lane: int,
    record_start: int,
    source_start: int,
    duration: int,
    gain_db: float,
) -> ET.Element:
    node = ET.SubElement(
        anchor.element,
        "asset-clip",
        {
            "enabled": "1",
            "ref": ref,
            "name": name,
            "lane": str(lane),
            "offset": _fcpxml_time(_connected_offset(anchor, record_start)),
            "start": _fcpxml_time(source_start),
            "duration": _fcpxml_time(duration),
        },
    )
    ET.SubElement(node, "adjust-volume", {"amount": _gain(gain_db)})
    return node


def _asset_dict(asset: MediaAsset) -> dict[str, Any]:
    return {
        "path": str(_asset_path(asset)),
        "origin_path": str(_origin_path(asset)),
        "name": asset.name,
        "source_start_frame": asset.source_start_frame,
        "duration_frames": asset.duration_frames,
        "video_fps": asset.video_fps,
    }


def _serialize_xml(root: ET.Element) -> str:
    ET.indent(root, space="    ")
    payload = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + payload + "\n"


def _child_record_range(parent: ET.Element, child: ET.Element, tc_start: int) -> tuple[int, int]:
    parent_record = _frames(parent.get("offset")) - tc_start
    parent_source = _frames(parent.get("start"))
    child_record = parent_record + _frames(child.get("offset")) - parent_source
    return child_record, child_record + _frames(child.get("duration"))


def _audit_xml(
    xml: str,
    spec: GscGymFcpxmlSpec,
    placed_dialogue: tuple[_PlacedAudio, ...],
    refs: dict[str, Any],
) -> dict[str, Any]:
    root = ET.fromstring(xml)
    sequence = root.find("./library/event/project/sequence")
    spine = sequence.find("spine") if sequence is not None else None
    if sequence is None or spine is None:
        raise GscGymFcpxmlError("Internal structural audit found no sequence/spine.")
    tc_start = _frames(sequence.get("tcStart"))
    direct = list(spine)
    primary = [
        (
            _frames(node.get("offset")) - tc_start,
            _frames(node.get("offset")) - tc_start + _frames(node.get("duration")),
            node,
        )
        for node in direct
        if node.tag in {"clip", "asset-clip"} and node.get("lane") is None
    ]

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, evidence: Any) -> None:
        checks.append({"name": name, "status": "pass" if passed else "fail", "evidence": evidence})

    total_frames = spec.carousel.v1.record_end_frame + spec.outro.asset.duration_frames
    check(
        "fcpxml_1_10_4k60",
        root.get("version") == "1.10"
        and root.find("./resources/format") is not None
        and root.find("./resources/format").get("frameDuration") == "1/60s"
        and root.find("./resources/format").get("width") == str(WIDTH)
        and root.find("./resources/format").get("height") == str(HEIGHT),
        {"version": root.get("version"), "fps": FPS, "width": WIDTH, "height": HEIGHT},
    )
    check(
        "sequence_geometry",
        tc_start == TIMELINE_START_FRAME and _frames(sequence.get("duration")) == total_frames,
        {"timeline_start_frame": tc_start, "duration_frames": _frames(sequence.get("duration"))},
    )
    expected_primary = [(0, OPENING_FRAMES)]
    expected_primary.extend((item.record_start_frame, item.record_end_frame) for item in spec.body_v1)
    expected_primary.append((spec.carousel.v1.record_start_frame, spec.carousel.v1.record_end_frame))
    expected_primary.append((spec.carousel.v1.record_end_frame, total_frames))
    actual_primary = [(start, end) for start, end, _ in primary]
    check(
        "continuous_primary_v1",
        actual_primary == expected_primary,
        {"expected": expected_primary, "actual": actual_primary},
    )
    opening_node = primary[0][2]
    check(
        "opening_400pct_derivative_260f",
        opening_node.tag == "asset-clip"
        and opening_node.get("ref") == refs["opening"]
        and primary[0][:2] == (0, OPENING_FRAMES)
        and spec.opening.pre_retimed_rate_percent == OPENING_RATE_PERCENT,
        {
            "record_range": list(primary[0][:2]),
            "pre_retimed_rate_percent": spec.opening.pre_retimed_rate_percent,
        },
    )

    connected: list[tuple[ET.Element, ET.Element, int, int]] = []
    for _, _, parent in primary:
        for child in list(parent):
            if child.get("lane") is None:
                continue
            start, end = _child_record_range(parent, child, tc_start)
            connected.append((parent, child, start, end))

    actual_a1 = sorted(
        (
            start,
            end - start,
            _frames(child.get("start")),
            child.get("lane"),
            child.get("ref"),
        )
        for _, child, start, end in connected
        if child.tag == "asset-clip" and child.get("ref") == refs["dialogue"]
    )
    expected_a1 = sorted(
        (
            item.record_start_frame,
            item.duration_frames,
            item.source_start_frame,
            "2",
            refs["dialogue"],
        )
        for item in placed_dialogue
    )
    gaps = [
        (battle.start_frame - BATTLE_GAP_FRAMES, battle.start_frame, battle.battle_id)
        for battle in spec.battles
        if battle.a1_gap_eligible
    ]
    gap_intersections = [
        {"battle_id": battle_id, "gap": [gap_start, gap_end], "a1": [start, start + duration]}
        for start, duration, _, _, _ in actual_a1
        for gap_start, gap_end, battle_id in gaps
        if max(start, gap_start) < min(start + duration, gap_end)
    ]
    gap_v1_coverage = [
        {
            "battle_id": battle_id,
            "gap": [gap_start, gap_end],
            "v1_coverage_frames": sum(
                max(0, min(end, gap_end) - max(start, gap_start))
                for start, end, _ in primary
            ),
        }
        for gap_start, gap_end, battle_id in gaps
    ]
    boundary_rows = []
    for gap_start, gap_end, battle_id in gaps:
        left = [
            row for row in actual_a1 if row[0] + row[1] == gap_start
        ]
        right = [row for row in actual_a1 if row[0] == gap_end]
        expected_bridge_label = f"battle-gap-v1-bridge:{battle_id}"
        bridge_specs = [
            item for item in spec.body_v1 if item.label == expected_bridge_label
        ]
        bridge = [
            (start, end, node)
            for start, end, node in primary
            if start == gap_start
            and end == gap_end
            and len(bridge_specs) == 1
            and node.find("video") is not None
            and node.find("video").get("ref") == refs["source"]
            and str(node.get("name") or "").endswith(f"| {expected_bridge_label}")
            and _frames(node.get("start")) == bridge_specs[0].source_start_frame
        ]
        boundary_rows.append(
            {
                "battle_id": battle_id,
                "gap": [gap_start, gap_end],
                "left_a1_boundary_count": len(left),
                "right_a1_boundary_count": len(right),
                "v1_bridge_count": len(bridge),
                "v1_bridge_label": expected_bridge_label,
            }
        )
    check(
        "a1_lossless_boundary_inserts_with_source_backed_v1_bridges",
        actual_a1 == expected_a1
        and not gap_intersections
        and all(end - start == BATTLE_GAP_FRAMES for start, end, _ in gaps)
        and all(row["v1_coverage_frames"] == BATTLE_GAP_FRAMES for row in gap_v1_coverage)
        and all(
            row["left_a1_boundary_count"] == 1
            and row["right_a1_boundary_count"] == 1
            and row["v1_bridge_count"] == 1
            for row in boundary_rows
        )
        and len(actual_a1) == len(spec.dialogue_a1)
        and sum(row[1] for row in actual_a1)
        == sum(item.duration_frames for item in spec.dialogue_a1),
        {
            "policy": (
                "real_60f_timeline_insert_only_for_identity_attempt_ordinal_1_at_"
                "adjacent_autoeditor_a1_boundary_preserve_all_a1_source_frames_"
                "with_incoming_v1_bridge_no_retry_gap"
            ),
            "inserts_timeline_frames": True,
            "incoming_v1_bridge_may_overlap_previous_source": True,
            "a1_removed_frames": 0,
            "inserted_gap_total_frames": BATTLE_GAP_FRAMES * len(gaps),
            "gap_count": len(gaps),
            "gaps": [{"battle_id": item[2], "start": item[0], "end": item[1]} for item in gaps],
            "v1_coverage": gap_v1_coverage,
            "boundary_evidence": boundary_rows,
            "placed_clip_count": len(actual_a1),
            "intersections": gap_intersections,
        },
    )

    expected_intros = sorted(
        (
            battle.start_frame - BATTLE_INTRO_FRAMES,
            BATTLE_INTRO_FRAMES,
            refs["intros"][battle.battle_id],
            f"GSC V2 Intro | {battle.battle_id} | {battle.intro.subject}",
        )
        for battle in spec.battles
        if battle.intro is not None
    )
    intro_refs = set(refs["intros"].values())
    actual_intros = sorted(
        (start, end - start, child.get("ref"), child.get("name"))
        for _, child, start, end in connected
        if child.tag == "asset-clip" and child.get("lane") == "1" and child.get("ref") in intro_refs
    )
    check(
        "silent_v2_intros_end_at_battle",
        actual_intros == expected_intros
        and all(start + duration in {battle.start_frame for battle in spec.battles} for start, duration, _, _ in actual_intros),
        {"expected": expected_intros, "actual": actual_intros, "lane": "V2", "audio_components": 0},
    )

    expected_a2 = sorted(
        (
            item.record_start_frame,
            item.duration_frames,
            item.source_start_frame,
            refs["bgm"][index],
            item.asset.name,
        )
        for index, item in enumerate(spec.bgm_a2, start=1)
    )
    actual_a2 = sorted(
        (start, end - start, _frames(child.get("start")), child.get("ref"), child.get("name"))
        for _, child, start, end in connected
        if child.tag == "asset-clip" and child.get("lane") == "3"
    )
    check(
        "complete_a2_plan",
        actual_a2 == expected_a2
        and expected_a2[0][0] == 0
        and expected_a2[-1][0] + expected_a2[-1][1] == spec.carousel.v1.record_end_frame,
        {"expected": expected_a2, "actual": actual_a2, "lane": "A2"},
    )
    boundary_coincidence = []
    for battle in spec.battles:
        battle_segments = sorted(
            (
                item for item in spec.bgm_a2
                if item.role == "battle" and item.battle_id == battle.battle_id
            ),
            key=lambda item: item.record_start_frame,
        )
        boundary_coincidence.append(
            {
                "battle_id": battle.battle_id,
                "mapped_battle_start": battle.start_frame,
                "battle_bgm_start": (
                    battle_segments[0].record_start_frame
                    if battle_segments
                    else None
                ),
                "a1_gap_end": (
                    battle.start_frame if battle.a1_gap_eligible else None
                ),
                "intro_end": (
                    battle.start_frame if battle.intro is not None else None
                ),
            }
        )
    check(
        "mapped_boundary_gap_intro_and_battle_bgm_coincide",
        all(
            row["battle_bgm_start"] == row["mapped_battle_start"]
            and (
                row["a1_gap_end"] is None
                or row["a1_gap_end"] == row["mapped_battle_start"]
            )
            and (
                row["intro_end"] is None
                or row["intro_end"] == row["mapped_battle_start"]
            )
            for row in boundary_coincidence
        ),
        boundary_coincidence,
    )
    assignments = _battle_assignment_rows(spec)
    transitions = [
        {
            "left_record_range": [left.record_start_frame, left.record_end_frame],
            "right_record_range": [right.record_start_frame, right.record_end_frame],
            "left_role": left.role,
            "right_role": right.role,
            "fade_out_frames": left.fade_out_frames,
            "fade_in_frames": right.fade_in_frames,
        }
        for left, right in zip(spec.bgm_a2, spec.bgm_a2[1:])
        if (left.role == "battle") != (right.role == "battle")
    ]
    assignment_names = [str(row["source_name"]) for row in assignments]
    library = tuple(spec.battle_bgm_library_filenames)
    complete_bags = all(
        set(assignment_names[start:start + len(library)]) == set(library)
        for start in range(0, len(assignment_names) - len(library) + 1, len(library))
    ) if library else True
    check(
        "structured_a2_battle_ids_exact_fades_and_shuffle_assignments",
        len(assignments) == len(spec.battles)
        and all(row["policy"] == BATTLE_BGM_ASSIGNMENT_POLICY for row in assignments)
        and all(
            row["fade_out_frames"] == BATTLE_EDGE_FADE_FRAMES
            and row["fade_in_frames"] == BATTLE_EDGE_FADE_FRAMES
            for row in transitions
        )
        and spec.bgm_a2[-1].fade_out_frames == BATTLE_EDGE_FADE_FRAMES
        and (
            not library
            or (
                bool(spec.battle_bgm_seed)
                and set(assignment_names).issubset(set(library))
                and complete_bags
                and (
                    len(library) <= 1
                    or not any(
                        left == right
                        for left, right in zip(assignment_names, assignment_names[1:])
                    )
                )
            )
        ),
        {
            "battle_edge_fade_frames": BATTLE_EDGE_FADE_FRAMES,
            "transitions": transitions,
            "final_fade_out_frames": spec.bgm_a2[-1].fade_out_frames,
            "assignment_policy": spec.battle_bgm_assignment_policy,
            "assignment_seed": spec.battle_bgm_seed,
            "library_filenames": list(library),
            "assignments": assignments,
            "complete_bags": complete_bags,
        },
    )
    nonbattle_contract = _nonbattle_bgm_contract(spec)
    check(
        "nonbattle_bgm_fresh_after_battles_no_repeat_and_post_final_sequence",
        nonbattle_contract["status"] == "pass"
        and nonbattle_contract["dual_screen_lovelife_occurrence_starts"]
        == [0, spec.battles[-1].end_frame]
        and [
            str(name).casefold()
            for name in nonbattle_contract["post_final_first_four_identities"][:3]
        ]
        == [name.casefold() for name in POST_FINAL_REQUIRED_NONBATTLE_FILENAMES]
        and nonbattle_contract["post_final_occurrence_count"] == 4
        and nonbattle_contract["post_final_fourth_identity_unused_nonreserved"]
        and nonbattle_contract["post_final_fourth_identity_owns_remainder"],
        nonbattle_contract,
    )

    carousel_parent = next(
        (node for _, _, node in primary if node.get("name", "").startswith("GSC Member Carousel V1 |")),
        None,
    )
    actual_slices: list[tuple[int, int, int, str, str | None]] = []
    if carousel_parent is not None:
        for child in list(carousel_parent):
            if child.tag != "clip" or child.get("lane") != "1" or not child.get("name", "").startswith("Member Carousel V2 |"):
                continue
            start, end = _child_record_range(carousel_parent, child, tc_start)
            crop = child.find("./adjust-crop/trim-rect")
            actual_slices.append(
                (
                    start,
                    end - start,
                    _frames(child.get("start")),
                    child.get("name", ""),
                    crop.get("bottom") if crop is not None else None,
                )
            )
    actual_slices.sort()
    expected_slices = [
        (
            item.record_start_frame,
            item.duration_frames,
            item.source_start_frame,
            f"Member Carousel V2 | {index:03d} | {item.label}",
            f"{CAROUSEL_BOTTOM_CROP_PERCENT:.6f}".rstrip("0").rstrip("."),
        )
        for index, item in enumerate(spec.carousel.v2_slices, start=1)
    ]
    check(
        "source_backed_member_carousel",
        carousel_parent is not None
        and actual_slices == expected_slices
        and sum(item[1] for item in actual_slices) == spec.carousel.v1.duration_frames,
        {
            "v1_range": [spec.carousel.v1.record_start_frame, spec.carousel.v1.record_end_frame],
            "v1_continuous_clip_count": 1 if carousel_parent is not None else 0,
            "v2_expected": expected_slices,
            "v2_actual": actual_slices,
            "crop_bottom_pixels": CAROUSEL_BOTTOM_CROP_PIXELS,
            "crop_bottom_percent": CAROUSEL_BOTTOM_CROP_PERCENT,
        },
    )

    outro_parent = primary[-1][2]
    outro_children = [
        (child, start, end)
        for parent, child, start, end in connected
        if parent is outro_parent and child.tag == "clip" and child.get("lane") == "4"
    ]
    video = outro_parent.find("video")
    audio = outro_children[0][0].find("audio") if len(outro_children) == 1 else None
    resources = {node.get("id"): node for node in root.findall("./resources/asset")}
    video_resource = resources.get(video.get("ref")) if video is not None else None
    audio_resource = resources.get(audio.get("ref")) if audio is not None else None
    video_uri = video_resource.find("media-rep").get("src") if video_resource is not None else None
    audio_uri = audio_resource.find("media-rep").get("src") if audio_resource is not None else None
    check(
        "linked_outro_v1_a3",
        video is not None
        and audio is not None
        and video.get("ref") == refs["outro_video"]
        and audio.get("ref") == refs["outro_audio"]
        and video_uri == audio_uri
        and outro_children[0][1:] == (spec.carousel.v1.record_end_frame, total_frames),
        {
            "record_range": [spec.carousel.v1.record_end_frame, total_frames],
            "video_uri": video_uri,
            "audio_uri": audio_uri,
            "audio_lane": "A3",
            "standalone_golden_goose": False,
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
        names = ", ".join(item["name"] for item in failed)
        raise GscGymFcpxmlError(f"Generated FCPXML failed its structural audit: {names}.")
    return audit


def assemble_gsc_gym_fcpxml(spec: GscGymFcpxmlSpec) -> GscGymFcpxmlBuild:
    """Assemble and audit one deterministic, import-ready FCPXML 1.10 document."""

    placed_dialogue = _validate_spec(spec)
    total_frames = spec.carousel.v1.record_end_frame + spec.outro.asset.duration_frames

    root = ET.Element("fcpxml", {"version": "1.10"})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        {
            "id": "r0",
            "name": "FFVideoFormat3840x2160p60",
            "frameDuration": "1/60s",
            "width": str(WIDTH),
            "height": str(HEIGHT),
            "colorSpace": "1-1-1 (Rec. 709)",
        },
    )
    ET.SubElement(
        resources,
        "format",
        {
            "id": "r1",
            "name": "FFVideoFormat3840x2160p30",
            "frameDuration": "1/30s",
            "width": str(WIDTH),
            "height": str(HEIGHT),
            "colorSpace": "1-1-1 (Rec. 709)",
        },
    )
    registry = _ResourceRegistry(resources)
    source_ref = registry.add(spec.source_video, video=True, audio=False)
    dialogue_ref = registry.add(spec.dialogue_audio, video=False, audio=True)
    opening_ref = registry.add(spec.opening.asset, video=True, audio=False)
    intro_refs = {
        battle.battle_id: registry.add(battle.intro.asset, video=True, audio=False)
        for battle in spec.battles
        if battle.intro is not None
    }
    bgm_refs = {
        index: registry.add(item.asset, video=False, audio=True)
        for index, item in enumerate(spec.bgm_a2, start=1)
    }
    outro_video_ref = registry.add(spec.outro.asset, video=True, audio=True)
    outro_audio_ref = registry.add(spec.outro.asset, video=False, audio=True)

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": spec.timeline_name})
    project = ET.SubElement(event, "project", {"name": spec.timeline_name})
    sequence = ET.SubElement(
        project,
        "sequence",
        {
            "format": "r0",
            "tcStart": _fcpxml_time(spec.timeline_start_frame),
            "duration": _fcpxml_time(total_frames),
            "tcFormat": "NDF",
        },
    )
    spine = ET.SubElement(sequence, "spine")
    anchors: list[_PrimaryAnchor] = []

    opening_node = ET.SubElement(
        spine,
        "asset-clip",
        {
            "enabled": "1",
            "ref": opening_ref,
            "name": f"GSC Opening 400pct | {spec.opening.asset.name}",
            "format": "r1" if spec.opening.asset.video_fps == 30 else "r0",
            "offset": _fcpxml_time(spec.timeline_start_frame),
            "start": _fcpxml_time(spec.opening.asset.source_start_frame),
            "duration": _fcpxml_time(OPENING_FRAMES),
            "tcFormat": "NDF",
        },
    )
    _transform(opening_node)
    anchors.append(_PrimaryAnchor(opening_node, 0, spec.opening.asset.source_start_frame, OPENING_FRAMES, "opening"))

    for index, interval in enumerate(spec.body_v1, start=1):
        node = _primary_clip(
            spine,
            name=f"GSC V1 | {index:04d} | {interval.label or spec.source_video.name}",
            record_start=interval.record_start_frame,
            source_start=interval.source_start_frame,
            duration=interval.duration_frames,
            video_ref=source_ref,
            asset=spec.source_video,
        )
        anchors.append(
            _PrimaryAnchor(
                node,
                interval.record_start_frame,
                interval.source_start_frame,
                interval.duration_frames,
                "body",
            )
        )

    carousel = spec.carousel
    carousel_node = _primary_clip(
        spine,
        name=f"GSC Member Carousel V1 | {spec.source_video.name}",
        record_start=carousel.v1.record_start_frame,
        source_start=carousel.v1.source_start_frame,
        duration=carousel.v1.duration_frames,
        video_ref=source_ref,
        asset=spec.source_video,
    )
    carousel_anchor = _PrimaryAnchor(
        carousel_node,
        carousel.v1.record_start_frame,
        carousel.v1.source_start_frame,
        carousel.v1.duration_frames,
        "carousel",
    )
    anchors.append(carousel_anchor)

    outro_start = carousel.v1.record_end_frame
    outro_node = _primary_clip(
        spine,
        name=f"GSC Linked Outro V1 | {spec.outro.asset.name}",
        record_start=outro_start,
        source_start=spec.outro.asset.source_start_frame,
        duration=spec.outro.asset.duration_frames,
        video_ref=outro_video_ref,
        asset=spec.outro.asset,
    )
    outro_anchor = _PrimaryAnchor(
        outro_node,
        outro_start,
        spec.outro.asset.source_start_frame,
        spec.outro.asset.duration_frames,
        "outro",
    )
    anchors.append(outro_anchor)

    for item in placed_dialogue:
        anchor = _anchor_for(anchors, item.record_start_frame, f"A1 {item.label!r}")
        _add_connected_audio(
            anchor,
            ref=dialogue_ref,
            name=f"GSC A1 | {item.input_index:04d} | {item.label}",
            lane=2,
            record_start=item.record_start_frame,
            source_start=item.source_start_frame,
            duration=item.duration_frames,
            gain_db=item.gain_db,
        )

    for battle in spec.battles:
        if battle.intro is None:
            continue
        intro_start = battle.start_frame - BATTLE_INTRO_FRAMES
        anchor = _anchor_for(anchors, intro_start, f"V2 intro {battle.battle_id!r}")
        intro_node = ET.SubElement(
            anchor.element,
            "asset-clip",
            {
                "enabled": "1",
                "ref": intro_refs[battle.battle_id],
                "name": f"GSC V2 Intro | {battle.battle_id} | {battle.intro.subject}",
                "format": "r1" if battle.intro.asset.video_fps == 30 else "r0",
                "lane": "1",
                "offset": _fcpxml_time(_connected_offset(anchor, intro_start)),
                "start": _fcpxml_time(battle.intro.asset.source_start_frame),
                "duration": _fcpxml_time(BATTLE_INTRO_FRAMES),
                "tcFormat": "NDF",
            },
        )
        _transform(intro_node)

    for index, item in enumerate(spec.bgm_a2, start=1):
        anchor = _anchor_for(anchors, item.record_start_frame, f"A2 {item.label!r}")
        _add_connected_audio(
            anchor,
            ref=bgm_refs[index],
            name=item.asset.name,
            lane=3,
            record_start=item.record_start_frame,
            source_start=item.source_start_frame,
            duration=item.duration_frames,
            gain_db=item.gain_db,
        )

    crop_percent = f"{CAROUSEL_BOTTOM_CROP_PERCENT:.6f}".rstrip("0").rstrip(".")
    for index, item in enumerate(carousel.v2_slices, start=1):
        node = ET.SubElement(
            carousel_node,
            "clip",
            {
                "enabled": "1",
                "name": f"Member Carousel V2 | {index:03d} | {item.label}",
                "format": "r1" if spec.source_video.video_fps == 30 else "r0",
                "lane": "1",
                "offset": _fcpxml_time(_connected_offset(carousel_anchor, item.record_start_frame)),
                "start": _fcpxml_time(item.source_start_frame),
                "duration": _fcpxml_time(item.duration_frames),
                "tcFormat": "NDF",
            },
        )
        crop = ET.SubElement(node, "adjust-crop", {"mode": "trim"})
        ET.SubElement(crop, "trim-rect", {"bottom": crop_percent})
        _transform(node)
        ET.SubElement(
            node,
            "video",
            {
                "ref": source_ref,
                "offset": _fcpxml_time(spec.source_video.source_start_frame),
                "start": _fcpxml_time(spec.source_video.source_start_frame),
                "duration": _fcpxml_time(spec.source_video.duration_frames),
            },
        )

    linked_audio = ET.SubElement(
        outro_node,
        "clip",
        {
            "enabled": "1",
            "name": f"GSC Linked Outro A3 | {spec.outro.asset.name}",
            "lane": "4",
            "offset": _fcpxml_time(spec.outro.asset.source_start_frame),
            "start": _fcpxml_time(spec.outro.asset.source_start_frame),
            "duration": _fcpxml_time(spec.outro.asset.duration_frames),
        },
    )
    ET.SubElement(linked_audio, "adjust-volume", {"amount": _gain(float(spec.outro.gain_db))})
    ET.SubElement(
        linked_audio,
        "audio",
        {
            "ref": outro_audio_ref,
            "offset": _fcpxml_time(spec.outro.asset.source_start_frame),
            "start": _fcpxml_time(spec.outro.asset.source_start_frame),
            "duration": _fcpxml_time(spec.outro.asset.duration_frames),
            "srcCh": ", ".join(str(index) for index in range(1, spec.outro.asset.audio_channels + 1)),
        },
    )

    xml = _serialize_xml(root)
    refs: dict[str, Any] = {
        "source": source_ref,
        "dialogue": dialogue_ref,
        "opening": opening_ref,
        "intros": intro_refs,
        "bgm": bgm_refs,
        "outro_video": outro_video_ref,
        "outro_audio": outro_audio_ref,
    }
    audit = _audit_xml(xml, spec, placed_dialogue, refs)

    gaps = [
        {
            "battle_id": battle.battle_id,
            "start_frame": battle.start_frame - BATTLE_GAP_FRAMES,
            "end_frame": battle.start_frame,
            "duration_frames": BATTLE_GAP_FRAMES,
        }
        for battle in spec.battles
        if battle.a1_gap_eligible
    ]
    battle_assignments = _battle_assignment_rows(spec)
    nonbattle_contract = _nonbattle_bgm_contract(spec)
    manifest = {
        "schema": SCHEMA,
        "deterministic": True,
        "llm_steps": 0,
        "fcpxml_version": "1.10",
        "fcpxml_sha256": hashlib.sha256(xml.encode("utf-8")).hexdigest().upper(),
        "timeline": {
            "name": spec.timeline_name,
            "fps": FPS,
            "width": WIDTH,
            "height": HEIGHT,
            "start_frame": spec.timeline_start_frame,
            "duration_frames": total_frames,
        },
        "source_asset": _asset_dict(spec.source_video),
        "opening": {
            "asset": _asset_dict(spec.opening.asset),
            "record_range": [0, OPENING_FRAMES],
            "duration_frames": OPENING_FRAMES,
            "pre_retimed_rate_percent": OPENING_RATE_PERCENT,
        },
        "body_v1": [
            {
                "record_range": [item.record_start_frame, item.record_end_frame],
                "source_range": [item.source_start_frame, item.source_start_frame + item.duration_frames],
                "label": item.label,
            }
            for item in spec.body_v1
        ],
        "battles": [
            {
                "battle_id": item.battle_id,
                "role": item.role,
                "canonical_identity": item.canonical_identity,
                "attempt_ordinal": item.attempt_ordinal,
                "intro_eligible": (
                    item.role in {"leader", "rival"} and item.attempt_ordinal == 1
                    if item.intro_eligible is None
                    else item.intro_eligible
                ),
                "a1_gap_eligible": item.a1_gap_eligible,
                "record_range": [item.start_frame, item.end_frame],
                "intro_range": (
                    [item.start_frame - BATTLE_INTRO_FRAMES, item.start_frame]
                    if item.intro is not None
                    else None
                ),
                "intro_asset": (
                    _asset_dict(item.intro.asset) if item.intro is not None else None
                ),
            }
            for item in spec.battles
        ],
        "a1": {
            "gap_policy": (
                "real_60f_timeline_insert_only_for_identity_attempt_ordinal_1_at_"
                "adjacent_autoeditor_a1_boundary_preserve_all_a1_source_frames_"
                "with_incoming_v1_bridge_no_retry_gap"
            ),
            "gap_inserts_timeline_frames": True,
            "gap_duplicates_v1_preroll": True,
            "incoming_v1_bridge_may_overlap_previous_source": True,
            "a1_removed_frames": 0,
            "inserted_gap_total_frames": BATTLE_GAP_FRAMES * len(gaps),
            "dialogue_asset": _asset_dict(spec.dialogue_audio),
            "input_clip_count": len(spec.dialogue_a1),
            "placed_clip_count": len(placed_dialogue),
            "placed": [
                {
                    "record_range": [item.record_start_frame, item.record_end_frame],
                    "source_range": [item.source_start_frame, item.source_start_frame + item.duration_frames],
                    "label": item.label,
                    "input_index": item.input_index,
                }
                for item in placed_dialogue
            ],
            "battle_gaps": gaps,
        },
        "a2": {
            "complete_range": [0, spec.carousel.v1.record_end_frame],
            "source_contract": "original_library_media_v1",
            "derived_media_allowed": False,
            "renamed_timeline_clips_allowed": False,
            "source_trim_handles_editable": True,
            "segments": [
                {
                    "record_range": [item.record_start_frame, item.record_end_frame],
                    "source_range": [item.source_start_frame, item.source_start_frame + item.duration_frames],
                    "asset": _asset_dict(item.asset),
                    "media_source_range": [
                        item.asset.source_start_frame,
                        item.asset.source_start_frame + item.asset.duration_frames,
                    ],
                    "available_handle_frames": {
                        "left": item.source_start_frame - item.asset.source_start_frame,
                        "right": (
                            item.asset.source_start_frame
                            + item.asset.duration_frames
                            - item.source_start_frame
                            - item.duration_frames
                        ),
                    },
                    "source_trim_handles_editable": True,
                    "role": item.role,
                    "label": item.label,
                    "battle_id": item.battle_id,
                    "fade_in_frames": item.fade_in_frames,
                    "fade_out_frames": item.fade_out_frames,
                    "fade_policy": "editable_timeline_metadata_not_baked",
                    "gain_db": item.gain_db,
                    "gain_policy": "editable_timeline_adjust_volume_not_baked",
                    "derived_media": False,
                }
                for item in spec.bgm_a2
            ],
            "dual_screen_lovelife_occurrence_policy": (
                "exactly_twice_opening_and_post_final"
            ),
            "nonbattle_bgm_contract": nonbattle_contract,
            "golden_goose_blocked": True,
            "battle_audio_lineage": "GSCNewLayout/audio/Gen 2 battle audio",
            "battle_edge_fade_frames": BATTLE_EDGE_FADE_FRAMES,
            "battle_assignment_policy": spec.battle_bgm_assignment_policy,
            "battle_assignment_seed": spec.battle_bgm_seed,
            "battle_library_filenames": list(spec.battle_bgm_library_filenames),
            "battle_assignments": battle_assignments,
        },
        "carousel": {
            "v1_record_range": [carousel.v1.record_start_frame, carousel.v1.record_end_frame],
            "v1_continuous_source_backed_clip_count": 1,
            "v2_slice_count": len(carousel.v2_slices),
            "v2_slices": [
                {
                    "record_range": [item.record_start_frame, item.record_end_frame],
                    "source_range": [
                        item.source_start_frame,
                        item.source_start_frame + item.duration_frames,
                    ],
                    "label": item.label,
                }
                for item in carousel.v2_slices
            ],
            "v2_contiguous": True,
            "crop_bottom_pixels": CAROUSEL_BOTTOM_CROP_PIXELS,
            "crop_bottom_percent": CAROUSEL_BOTTOM_CROP_PERCENT,
        },
        "outro": {
            "asset": _asset_dict(spec.outro.asset),
            "record_range": [outro_start, total_frames],
            "video_track": "V1",
            "audio_track": "A3",
            "linked_same_source_uri": True,
            "standalone_golden_goose_clip": False,
        },
        "resources": registry.rows,
        "structural_audit": audit,
    }
    return GscGymFcpxmlBuild(xml=xml, manifest=manifest, structural_audit=audit)


__all__ = [
    "AUDIT_SCHEMA",
    "BATTLE_BGM_ASSIGNMENT_POLICY",
    "BATTLE_EDGE_FADE_FRAMES",
    "BATTLE_GAP_FRAMES",
    "BATTLE_INTRO_FRAMES",
    "BgmSegment",
    "BattleSpec",
    "CAROUSEL_BOTTOM_CROP_PERCENT",
    "CAROUSEL_BOTTOM_CROP_PIXELS",
    "CarouselSlice",
    "CarouselSpec",
    "DialogueInterval",
    "FPS",
    "GscGymFcpxmlBuild",
    "GscGymFcpxmlError",
    "GscGymFcpxmlSpec",
    "HEIGHT",
    "IntroOverlay",
    "MediaAsset",
    "OPENING_FRAMES",
    "OPENING_RATE_PERCENT",
    "OpeningSpec",
    "OutroSpec",
    "SCHEMA",
    "SourceInterval",
    "TIMELINE_START_FRAME",
    "WIDTH",
    "assemble_gsc_gym_fcpxml",
]
