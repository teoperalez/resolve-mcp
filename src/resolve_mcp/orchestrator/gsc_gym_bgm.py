"""Pure frame-exact A2 planning for deterministic GSC Gym Leader edits.

The opening begins part-way through Dual Screen Lovelife so the music reaches
the same point at the end of the 4x picture intro as it did with the native GSC
intro.  Every positive post-battle gap starts a new, never-before-used general
track at source frame zero.  The final battle instead starts the reserved
Dual Screen Lovelife -> Motivated By Clouds -> Roll Me in Stardust sequence,
then hands the remaining suffix to still-unused randomized tracks.

No files are probed or rendered here.  Callers provide immutable, already
probed :class:`MediaAsset` values.  Every planned slice keeps that full
original-media descriptor; trims, gain, and fade intent belong to the
timeline contract and never create renamed derivatives.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Literal

from .gsc_gym_deterministic import POST_FINAL_REQUIRED_TRACKS
from .gsc_gym_fcpxml import BATTLE_EDGE_FADE_FRAMES, MediaAsset


FPS = 60
OPENING_TIMELINE_FRAMES = 260
NATIVE_OPENING_TIMELINE_FRAMES = 1024
OPENING_AUDIO_SOURCE_OFFSET_FRAMES = (
    NATIVE_OPENING_TIMELINE_FRAMES - OPENING_TIMELINE_FRAMES
)
class GscGymBgmError(ValueError):
    """Raised when an A2 plan cannot satisfy the closed deterministic rules."""


@dataclass(frozen=True)
class BattleAudioRange:
    battle_id: str
    record_start_frame: int
    record_end_frame: int
    asset: MediaAsset

    @property
    def duration_frames(self) -> int:
        return self.record_end_frame - self.record_start_frame


@dataclass(frozen=True)
class PlannedBgmSlice:
    record_start_frame: int
    source_start_frame: int
    duration_frames: int
    asset: MediaAsset
    role: Literal["opening", "nonbattle", "battle", "carousel"]
    label: str
    battle_id: str | None = None
    fade_in_frames: int = 0
    fade_out_frames: int = 0

    @property
    def record_end_frame(self) -> int:
        return self.record_start_frame + self.duration_frames

    @property
    def source_end_frame(self) -> int:
        return self.source_start_frame + self.duration_frames


def _normalized_path(asset: MediaAsset) -> str:
    return str(asset.origin_path or asset.path).replace("\\", "/").casefold()


def _normalized_name(asset: MediaAsset) -> str:
    return asset.name.casefold().removesuffix(".mp3").strip()


def _is_dual_screen_lovelife(asset: MediaAsset) -> bool:
    return "dual screen lovelife" in _normalized_name(asset) or (
        "dual screen lovelife" in _normalized_path(asset)
    )


def _is_golden_goose(asset: MediaAsset) -> bool:
    return "golden goose" in _normalized_name(asset) or "golden goose" in _normalized_path(asset)


def _filename(asset: MediaAsset) -> str:
    return Path(str(asset.origin_path or asset.path)).name.casefold()


def _is_gen2_battle_audio(asset: MediaAsset) -> bool:
    value = "/" + _normalized_path(asset).lstrip("/")
    return "/gscnewlayout/audio/gen 2 battle audio/" in value


def _validate_asset(asset: MediaAsset, label: str) -> None:
    if int(asset.duration_frames) <= 0:
        raise GscGymBgmError(f"{label} has no positive duration.")
    if int(asset.source_start_frame) < 0:
        raise GscGymBgmError(f"{label} has a negative source start.")


def _split_at_carousel(
    row: PlannedBgmSlice,
    carousel_start_frame: int,
) -> tuple[PlannedBgmSlice, ...]:
    """Split a general slice at the carousel boundary without restarting music."""

    if row.role == "battle" or not (
        row.record_start_frame < carousel_start_frame < row.record_end_frame
    ):
        role = "carousel" if row.record_start_frame >= carousel_start_frame else row.role
        return (replace(row, role=role),)
    left_duration = carousel_start_frame - row.record_start_frame
    return (
        replace(row, duration_frames=left_duration),
        replace(
            row,
            record_start_frame=carousel_start_frame,
            source_start_frame=row.source_start_frame + left_duration,
            duration_frames=row.duration_frames - left_duration,
            role="carousel",
            label=f"carousel | {row.asset.name}",
        ),
    )


def _general_role(record_start: int, carousel_start_frame: int, *, opening: bool) -> Literal[
    "opening", "nonbattle", "carousel"
]:
    if opening:
        return "opening"
    return "carousel" if record_start >= carousel_start_frame else "nonbattle"


def _general_slice(
    *,
    record_start: int,
    duration: int,
    asset: MediaAsset,
    carousel_start_frame: int,
    opening: bool = False,
    label_prefix: str | None = None,
    source_start_frame: int | None = None,
) -> list[PlannedBgmSlice]:
    role = _general_role(record_start, carousel_start_frame, opening=opening)
    prefix = label_prefix or (
        "opening bed" if role == "opening" else "carousel" if role == "carousel" else "nonbattle"
    )
    candidate = PlannedBgmSlice(
        record_start_frame=record_start,
        source_start_frame=(
            asset.source_start_frame
            if source_start_frame is None
            else source_start_frame
        ),
        duration_frames=duration,
        asset=asset,
        role=role,
        label=f"{prefix} | {asset.name}",
    )
    return list(_split_at_carousel(candidate, carousel_start_frame))


def _consume_unique_assets(
    *,
    record_start: int,
    duration: int,
    assets: tuple[MediaAsset, ...],
    asset_index: int,
    carousel_start_frame: int,
    opening_first: bool = False,
    label_prefix: str | None = None,
    first_source_start_frame: int | None = None,
) -> tuple[list[PlannedBgmSlice], int]:
    """Consume source-zero identities once, discarding any interval-end tail."""

    rows: list[PlannedBgmSlice] = []
    cursor = record_start
    remaining = duration
    first = True
    while remaining:
        if asset_index >= len(assets):
            raise GscGymBgmError(
                "The randomized non-battle deck was exhausted; tracks may not wrap or repeat."
            )
        asset = assets[asset_index]
        asset_index += 1  # starting an identity consumes it permanently
        source_start = (
            first_source_start_frame
            if first and first_source_start_frame is not None
            else asset.source_start_frame
        )
        asset_end = asset.source_start_frame + asset.duration_frames
        available_duration = asset_end - source_start
        if available_duration <= 0 or source_start < asset.source_start_frame:
            raise GscGymBgmError(
                f"Non-battle source start is outside the full original media: {asset.name}."
            )
        tail = remaining - available_duration
        if (
            0 < tail < BATTLE_EDGE_FADE_FRAMES
            and available_duration > BATTLE_EDGE_FADE_FRAMES - tail
        ):
            take = available_duration - (BATTLE_EDGE_FADE_FRAMES - tail)
        else:
            take = min(remaining, available_duration)
        if take <= 0:
            continue
        label = (
            label_prefix
            if label_prefix is not None
            else "opening bed"
            if opening_first and first
            else None
        )
        rows.extend(
            _general_slice(
                record_start=cursor,
                duration=take,
                asset=asset,
                carousel_start_frame=carousel_start_frame,
                opening=opening_first and first,
                label_prefix=label,
                source_start_frame=source_start,
            )
        )
        cursor += take
        remaining -= take
        first = False
    return rows, asset_index


def _consume_post_final(
    *,
    record_start: int,
    duration: int,
    required_assets: tuple[MediaAsset, ...],
    randomized_assets: tuple[MediaAsset, ...],
    randomized_index: int,
    carousel_start_frame: int,
) -> tuple[list[PlannedBgmSlice], int]:
    """Fair-share the suffix across the exact three-plus-one identity sequence."""

    identity_slots = len(required_assets) + 1
    if duration < identity_slots * BATTLE_EDGE_FADE_FRAMES:
        raise GscGymBgmError(
            "The post-final-battle range is too short for the three required tracks "
            "and one unused randomized filler."
        )
    if randomized_index >= len(randomized_assets):
        raise GscGymBgmError(
            "No unused randomized non-battle identity remains for the post-final suffix."
        )

    filler_asset = randomized_assets[randomized_index]
    if filler_asset.duration_frames < BATTLE_EDGE_FADE_FRAMES:
        raise GscGymBgmError(
            "The exact next unused randomized identity is too short to finish the "
            "post-final suffix with the required final fade."
        )

    required_takes: list[int] = []
    remaining = duration
    for index, asset in enumerate(required_assets):
        remaining_slots = len(required_assets) - index + 1
        fair_share = remaining // remaining_slots
        take = min(asset.duration_frames, fair_share)
        if take < BATTLE_EDGE_FADE_FRAMES:
            raise GscGymBgmError(
                f"Post-final required track is too short for its deterministic share: {asset.name}."
            )
        required_takes.append(take)
        remaining -= take

    deficit = max(0, remaining - filler_asset.duration_frames)
    for index in range(len(required_assets) - 1, -1, -1):
        if deficit == 0:
            break
        capacity = required_assets[index].duration_frames - required_takes[index]
        extension = min(capacity, deficit)
        required_takes[index] += extension
        remaining -= extension
        deficit -= extension
    if deficit:
        raise GscGymBgmError(
            "The exact next unused randomized identity cannot finish the post-final "
            "suffix and the required tracks have insufficient natural duration to rebalance it."
        )

    rows: list[PlannedBgmSlice] = []
    cursor = record_start
    for index, (asset, take) in enumerate(zip(required_assets, required_takes), start=1):
        rows.extend(
            _general_slice(
                record_start=cursor,
                duration=take,
                asset=asset,
                carousel_start_frame=carousel_start_frame,
                label_prefix=f"post-final required {index:02d}",
            )
        )
        cursor += take
    rows.extend(
        _general_slice(
            record_start=cursor,
            duration=remaining,
            asset=filler_asset,
            carousel_start_frame=carousel_start_frame,
            label_prefix="post-final unused random",
        )
    )
    return rows, randomized_index + 1


def _consume_battle_track(battle: BattleAudioRange) -> list[PlannedBgmSlice]:
    rows: list[PlannedBgmSlice] = []
    cursor = battle.record_start_frame
    remaining = battle.duration_frames
    while remaining:
        available = battle.asset.duration_frames
        tail_after_loop = remaining - available
        if 0 < tail_after_loop < BATTLE_EDGE_FADE_FRAMES and available > (
            BATTLE_EDGE_FADE_FRAMES - tail_after_loop
        ):
            take = available - (BATTLE_EDGE_FADE_FRAMES - tail_after_loop)
        else:
            take = min(remaining, available)
        rows.append(
            PlannedBgmSlice(
                record_start_frame=cursor,
                source_start_frame=battle.asset.source_start_frame,
                duration_frames=take,
                asset=battle.asset,
                role="battle",
                label=f"battle | {battle.battle_id} | {battle.asset.name}",
                battle_id=battle.battle_id,
            )
        )
        cursor += take
        remaining -= take
    return rows


def _with_edge_fades(rows: list[PlannedBgmSlice]) -> tuple[PlannedBgmSlice, ...]:
    if not rows:
        return ()
    result = list(rows)

    def family(row: PlannedBgmSlice) -> str:
        return "battle" if row.role == "battle" else "general"

    for index in range(len(result) - 1):
        left = result[index]
        right = result[index + 1]
        if family(left) == family(right):
            continue
        if left.duration_frames < BATTLE_EDGE_FADE_FRAMES:
            raise GscGymBgmError(
                f"A2 slice before battle edge is shorter than the exact "
                f"{BATTLE_EDGE_FADE_FRAMES}-frame fade: {left.label}."
            )
        if right.duration_frames < BATTLE_EDGE_FADE_FRAMES:
            raise GscGymBgmError(
                f"A2 slice after battle edge is shorter than the exact "
                f"{BATTLE_EDGE_FADE_FRAMES}-frame fade: {right.label}."
            )
        result[index] = replace(left, fade_out_frames=BATTLE_EDGE_FADE_FRAMES)
        result[index + 1] = replace(
            right,
            fade_in_frames=BATTLE_EDGE_FADE_FRAMES,
        )
    final = result[-1]
    if final.duration_frames < BATTLE_EDGE_FADE_FRAMES:
        raise GscGymBgmError(
            "The final carousel BGM slice is too short for its exact 30-frame fade-out."
        )
    result[-1] = replace(final, fade_out_frames=BATTLE_EDGE_FADE_FRAMES)
    return tuple(result)


def plan_gsc_gym_bgm(
    *,
    opening_track: MediaAsset,
    post_final_required_tracks: Iterable[MediaAsset],
    randomized_nonbattle_tracks: Iterable[MediaAsset],
    battles: Iterable[BattleAudioRange],
    carousel_start_frame: int,
    fill_end_frame: int,
) -> tuple[PlannedBgmSlice, ...]:
    """Build a complete, exact A2 plan from frame zero to the outro boundary."""

    _validate_asset(opening_track, "opening_track")
    if not _is_dual_screen_lovelife(opening_track):
        raise GscGymBgmError("Dual Screen Lovelife must own the opening A2 source tape.")
    if _is_golden_goose(opening_track):
        raise GscGymBgmError("Golden Goose is blocked from A2.")
    opening_asset_end = opening_track.source_start_frame + opening_track.duration_frames
    opening_source_start = opening_track.source_start_frame + OPENING_AUDIO_SOURCE_OFFSET_FRAMES
    if opening_source_start >= opening_asset_end:
        raise GscGymBgmError(
            "Dual Screen Lovelife is too short for the 764-frame 4x-intro compensation."
        )
    if fill_end_frame <= OPENING_TIMELINE_FRAMES:
        raise GscGymBgmError("A2 fill must extend beyond the 4x opening intro.")
    if not OPENING_TIMELINE_FRAMES <= carousel_start_frame < fill_end_frame:
        raise GscGymBgmError("Carousel start must be inside the main A2 fill range.")

    seen_general = {_normalized_path(opening_track)}
    required_assets = tuple(post_final_required_tracks)
    expected_required = tuple(name.casefold() for name in POST_FINAL_REQUIRED_TRACKS)
    if tuple(_filename(asset) for asset in required_assets) != expected_required:
        raise GscGymBgmError(
            "Post-final required tracks must be exactly Dual Screen Lovelife, "
            "Motivated By Clouds, then Roll Me in Stardust."
        )
    for index, asset in enumerate(required_assets, start=1):
        _validate_asset(asset, f"post_final_required_tracks[{index}]")
        if asset.source_start_frame != 0:
            raise GscGymBgmError("Every post-final required track must start at source frame zero.")
        if index == 1 and _normalized_path(asset) != _normalized_path(opening_track):
            raise GscGymBgmError(
                "The post-final Dual Screen Lovelife asset must match the opening identity."
            )
        if _is_golden_goose(asset) or _is_gen2_battle_audio(asset):
            raise GscGymBgmError(f"Invalid post-final required A2 asset: {asset.name}.")

    randomized_assets: list[MediaAsset] = []
    for index, asset in enumerate(randomized_nonbattle_tracks, start=1):
        _validate_asset(asset, f"randomized_nonbattle_tracks[{index}]")
        if _filename(asset) in set(expected_required) or _is_golden_goose(asset):
            raise GscGymBgmError(
                f"Reserved track entered the randomized non-battle deck: {asset.name}."
            )
        if _is_gen2_battle_audio(asset):
            raise GscGymBgmError(
                f"Gen 2 battle audio entered the non-battle deck: {asset.name}."
            )
        normalized = _normalized_path(asset)
        if normalized in seen_general:
            raise GscGymBgmError(f"Non-battle deck contains a repeated asset: {asset.name}.")
        seen_general.add(normalized)
        if asset.source_start_frame != 0:
            raise GscGymBgmError(
                f"Randomized non-battle track must begin at source frame zero: {asset.name}."
            )
        randomized_assets.append(asset)

    ordered_battles = sorted(
        tuple(battles),
        key=lambda item: (item.record_start_frame, item.record_end_frame, item.battle_id),
    )
    previous_end = 0
    battle_ids: set[str] = set()
    for index, battle in enumerate(ordered_battles, start=1):
        _validate_asset(battle.asset, f"battles[{index}].asset")
        if not battle.battle_id or battle.battle_id in battle_ids:
            raise GscGymBgmError("Every physical battle attempt needs a unique battle_id.")
        battle_ids.add(battle.battle_id)
        if battle.record_start_frame < previous_end or battle.record_end_frame <= battle.record_start_frame:
            raise GscGymBgmError("Battle audio ranges must be positive, ordered, and disjoint.")
        if battle.record_end_frame > carousel_start_frame:
            raise GscGymBgmError("Battle audio may not extend into the final member carousel.")
        if not _is_gen2_battle_audio(battle.asset):
            raise GscGymBgmError(
                f"Battle audio is not lineaged to GSCNewLayout Gen 2 battle audio: "
                f"{battle.asset.name}."
            )
        if _is_golden_goose(battle.asset) or _is_dual_screen_lovelife(battle.asset):
            raise GscGymBgmError(f"Reserved A2 asset used as battle music: {battle.asset.name}.")
        previous_end = battle.record_end_frame

    if not ordered_battles:
        raise GscGymBgmError("The post-final BGM contract requires at least one retained battle.")

    rows: list[PlannedBgmSlice] = []
    first_battle = ordered_battles[0]
    opening_and_random = (opening_track, *tuple(randomized_assets))
    opening_rows, opening_index = _consume_unique_assets(
        record_start=0,
        duration=first_battle.record_start_frame,
        assets=opening_and_random,
        asset_index=0,
        carousel_start_frame=carousel_start_frame,
        opening_first=True,
        first_source_start_frame=opening_source_start,
    )
    rows.extend(opening_rows)
    randomized_index = max(0, opening_index - 1)

    for battle_index, battle in enumerate(ordered_battles):
        rows.extend(_consume_battle_track(battle))
        if battle_index + 1 < len(ordered_battles):
            next_battle = ordered_battles[battle_index + 1]
            gap = next_battle.record_start_frame - battle.record_end_frame
            if gap > 0:
                general, randomized_index = _consume_unique_assets(
                    record_start=battle.record_end_frame,
                    duration=gap,
                    assets=tuple(randomized_assets),
                    asset_index=randomized_index,
                    carousel_start_frame=carousel_start_frame,
                    label_prefix=f"post-battle fresh | {battle.battle_id}",
                )
                rows.extend(general)
        else:
            post_final, randomized_index = _consume_post_final(
                record_start=battle.record_end_frame,
                duration=fill_end_frame - battle.record_end_frame,
                required_assets=required_assets,
                randomized_assets=tuple(randomized_assets),
                randomized_index=randomized_index,
                carousel_start_frame=carousel_start_frame,
            )
            rows.extend(post_final)

    if not rows or rows[0].record_start_frame != 0:
        raise GscGymBgmError("A2 did not begin at timeline frame zero.")
    if rows[0].source_start_frame != opening_source_start or not _is_dual_screen_lovelife(rows[0].asset):
        raise GscGymBgmError("A2 opening lost the exact Dual Screen Lovelife source offset.")
    timeline_cursor = 0
    for row in rows:
        if row.record_start_frame != timeline_cursor or row.duration_frames <= 0:
            raise GscGymBgmError("A2 output is not exact and contiguous.")
        if row.source_start_frame < row.asset.source_start_frame:
            raise GscGymBgmError(f"A2 source underflow: {row.label}.")
        if row.source_end_frame > row.asset.source_start_frame + row.asset.duration_frames:
            raise GscGymBgmError(f"A2 source overflow: {row.label}.")
        timeline_cursor = row.record_end_frame
    if timeline_cursor != fill_end_frame:
        raise GscGymBgmError(
            f"A2 ended at {timeline_cursor}; exact outro boundary {fill_end_frame} is required."
        )

    identity_starts: list[PlannedBgmSlice] = []
    for index, row in enumerate(rows):
        if row.role == "battle":
            continue
        previous = rows[index - 1] if index else None
        if (
            previous is None
            or previous.role == "battle"
            or _normalized_path(previous.asset) != _normalized_path(row.asset)
        ):
            identity_starts.append(row)
    identity_keys = [_normalized_path(row.asset) for row in identity_starts]
    dual_key = _normalized_path(opening_track)
    repeated = {
        key for key in identity_keys
        if identity_keys.count(key) > (2 if key == dual_key else 1)
    }
    if repeated or identity_keys.count(dual_key) != 2:
        raise GscGymBgmError(
            "Non-battle identities may not repeat; Dual Screen Lovelife must occur "
            "exactly once at opening and once after the final battle."
        )

    for index, battle in enumerate(ordered_battles):
        next_start = (
            ordered_battles[index + 1].record_start_frame
            if index + 1 < len(ordered_battles)
            else fill_end_frame
        )
        if next_start == battle.record_end_frame:
            continue
        fresh = next(
            (row for row in rows if row.record_start_frame == battle.record_end_frame),
            None,
        )
        if fresh is None or fresh.role == "battle" or fresh.source_start_frame != 0:
            raise GscGymBgmError(
                f"Battle {battle.battle_id} did not hand off to a fresh source-zero BGM identity."
            )

    final_end = ordered_battles[-1].record_end_frame
    suffix_starts = [row for row in identity_starts if row.record_start_frame >= final_end]
    required_names = [_filename(asset) for asset in required_assets]
    actual_prefix = [_filename(row.asset) for row in suffix_starts[: len(required_assets)]]
    if actual_prefix != required_names or len(suffix_starts) != len(required_assets) + 1:
        raise GscGymBgmError(
            "Post-final BGM must contain exactly the required three-track prefix "
            "followed by one unused randomized identity that finishes A2."
        )
    if any(row.source_start_frame != 0 for row in suffix_starts):
        raise GscGymBgmError("Every post-final BGM identity must start at source frame zero.")
    return _with_edge_fades(rows)


__all__ = [
    "BATTLE_EDGE_FADE_FRAMES",
    "BattleAudioRange",
    "GscGymBgmError",
    "NATIVE_OPENING_TIMELINE_FRAMES",
    "OPENING_AUDIO_SOURCE_OFFSET_FRAMES",
    "OPENING_TIMELINE_FRAMES",
    "PlannedBgmSlice",
    "plan_gsc_gym_bgm",
]
