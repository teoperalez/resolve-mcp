"""Build a source-native, editable GSC A2 population.

Every timeline clip keeps the exact original MP3 path, filename, full probed
media duration, and original source in/out.  Gain and fade intent remain
editable timeline metadata; this module never renders, renames, or caches an
audio derivative.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .gsc_gym_bgm import PlannedBgmSlice
from .gsc_gym_fcpxml import BgmSegment


DEFAULT_GAINS_DB = {
    "opening": -8.4,
    "nonbattle": -4.5,
    "battle": -4.5,
    "carousel": -4.5,
}
SOURCE_A2_SCHEMA = "gsc_a2_original_source_contract_v1"
SOURCE_CLIP_SCHEMA = "gsc_a2_original_source_clip_v1"


class GscGymAudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceA2:
    segments: tuple[BgmSegment, ...]
    clips: tuple[dict[str, object], ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _path_key(value: str | Path) -> str:
    return str(Path(value).resolve()).replace("\\", "/").casefold()


def _is_derivative_path(path: Path) -> bool:
    return path.suffix.casefold() != ".mp3" or any(
        part.casefold() == "a2-fades" for part in path.parts
    )


def build_source_a2_contract(
    rows: Iterable[PlannedBgmSlice],
    *,
    deadline_check: Callable[[str], None] | None = None,
    gains_db: Mapping[str, float] = DEFAULT_GAINS_DB,
) -> SourceA2:
    """Bind planned slices directly to their immutable original MP3 media."""

    planned = tuple(rows)
    if not planned:
        raise GscGymAudioError("Cannot build an empty source-native A2 plan.")
    source_hashes: dict[str, str] = {}
    segments: list[BgmSegment] = []
    evidence: list[dict[str, object]] = []

    for index, row in enumerate(planned, start=1):
        if deadline_check:
            deadline_check(f"binding original A2 source {index}/{len(planned)}")
        source = Path(row.asset.path).resolve()
        origin = Path(row.asset.origin_path or row.asset.path).resolve()
        if not source.is_file() or source.stat().st_size <= 0:
            raise GscGymAudioError(f"Missing original A2 source asset: {source}")
        if _path_key(source) != _path_key(origin):
            raise GscGymAudioError(
                f"A2 source must be the original library path, not a renamed derivative: {source}"
            )
        if _is_derivative_path(source):
            raise GscGymAudioError(
                f"A2 source must be an original MP3 outside a2-fades: {source}"
            )
        if row.asset.name != source.name:
            raise GscGymAudioError(
                f"A2 source must retain its original filename: {row.asset.name!r} != {source.name!r}."
            )
        try:
            gain = float(gains_db[row.role])
        except (KeyError, TypeError, ValueError) as exc:
            raise GscGymAudioError(
                f"No finite gain is registered for A2 role {row.role!r}."
            ) from exc
        if not math.isfinite(gain):
            raise GscGymAudioError(
                f"No finite gain is registered for A2 role {row.role!r}."
            )

        media_start = int(row.asset.source_start_frame)
        media_duration = int(row.asset.duration_frames)
        media_end = media_start + media_duration
        source_start = int(row.source_start_frame)
        source_end = int(row.source_end_frame)
        if (
            media_duration <= 0
            or source_start < media_start
            or source_end <= source_start
            or source_end > media_end
        ):
            raise GscGymAudioError(
                f"A2 source range exceeds original media bounds: source={source}, "
                f"media={media_start}..{media_end}, use={source_start}..{source_end}."
            )

        source_key = _path_key(source)
        source_hash = source_hashes.get(source_key)
        if source_hash is None:
            source_hash = _sha256(source)
            source_hashes[source_key] = source_hash
        left_handle = source_start - media_start
        right_handle = media_end - source_end
        segments.append(
            BgmSegment(
                record_start_frame=row.record_start_frame,
                source_start_frame=source_start,
                duration_frames=row.duration_frames,
                asset=row.asset,
                role=row.role,
                label=row.label,
                gain_db=gain,
                battle_id=row.battle_id,
                fade_in_frames=row.fade_in_frames,
                fade_out_frames=row.fade_out_frames,
            )
        )
        evidence.append(
            {
                "schema": SOURCE_CLIP_SCHEMA,
                "record_range": [row.record_start_frame, row.record_end_frame],
                "source_path": str(source),
                "source_name": source.name,
                "source_sha256": source_hash,
                "source_range": [source_start, source_end],
                "media_source_start_frame": media_start,
                "media_duration_frames": media_duration,
                "media_source_end_frame": media_end,
                "available_handle_frames": {
                    "left": left_handle,
                    "right": right_handle,
                },
                "source_trim_handles_editable": True,
                "role": row.role,
                "battle_id": row.battle_id,
                "label": row.label,
                "fade_in_frames": row.fade_in_frames,
                "fade_out_frames": row.fade_out_frames,
                "fade_policy": "editable_timeline_metadata_not_baked",
                "gain_db": gain,
                "gain_policy": "editable_timeline_adjust_volume_not_baked",
                "derived_media": False,
            }
        )
    return SourceA2(tuple(segments), tuple(evidence))


__all__ = [
    "DEFAULT_GAINS_DB",
    "GscGymAudioError",
    "SOURCE_A2_SCHEMA",
    "SOURCE_CLIP_SCHEMA",
    "SourceA2",
    "build_source_a2_contract",
]
