"""Deterministic scripting-API audio placement for a receipt-bound GSC timeline.

Resolve is known to map connected FCPXML audio lanes inconsistently.  This
module treats the imported audio as disposable, leaves every video item
untouched, and rebuilds the owned A1/A2/A3 population through
``MediaPool.AppendToTimeline`` with explicit ``trackIndex`` values.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


AUDIO_PLACEMENT_SCHEMA = "gsc_gym_resolve_audio_placement_v2"
AUDIO_TRACK_NAMES = {1: "Dialogue", 2: "BGM", 3: "Outro"}


class GscGymResolveAudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioPlacement:
    track_index: int
    kind: str
    path: str
    record_start: int
    record_end: int
    source_start: int
    source_end: int
    full_source: bool = False
    source_name: str = ""
    media_source_start: int | None = None
    media_duration: int | None = None
    left_handle: int | None = None
    right_handle: int | None = None
    gain_db: float | None = None
    fade_in_frames: int = 0
    fade_out_frames: int = 0
    original_source: bool = False

    def evidence(self) -> dict[str, Any]:
        return {
            "track_index": self.track_index,
            "track_name": AUDIO_TRACK_NAMES[self.track_index],
            "kind": self.kind,
            "path": self.path,
            "record_range": [self.record_start, self.record_end],
            "source_range": [self.source_start, self.source_end],
            "full_source": self.full_source,
            "source_name": self.source_name,
            "media_source_start_frame": self.media_source_start,
            "media_duration_frames": self.media_duration,
            "available_handle_frames": (
                None
                if self.left_handle is None or self.right_handle is None
                else {"left": self.left_handle, "right": self.right_handle}
            ),
            "gain_db": self.gain_db,
            "fade_in_frames": self.fade_in_frames,
            "fade_out_frames": self.fade_out_frames,
            "original_source": self.original_source,
        }


def _norm(value: str | Path) -> str:
    return str(value).replace("\\", "/").casefold()


def _media_path(media: Any) -> str:
    try:
        return str(media.GetClipProperty("File Path") or "")
    except (AttributeError, TypeError):
        try:
            values = media.GetClipProperty() or {}
        except AttributeError:
            return ""
        return str(values.get("File Path") or "") if isinstance(values, dict) else ""


def _media_name(media: Any) -> str:
    try:
        return str(media.GetName() or "")
    except AttributeError:
        return ""


def _timeline_item_path(item: Any) -> str:
    try:
        media = item.GetMediaPoolItem()
    except AttributeError:
        return ""
    return _media_path(media) if media is not None else ""


def _timeline_item_media_name(item: Any) -> str:
    try:
        media = item.GetMediaPoolItem()
    except AttributeError:
        media = None
    return _media_name(media) if media is not None else ""


def _timeline_item_visible_name(item: Any) -> str:
    try:
        return str(item.GetName() or "")
    except AttributeError:
        return ""


def _timeline_item_uid(item: Any) -> str:
    try:
        return str(item.GetUniqueId() or "")
    except AttributeError:
        return ""


def _linked_item_present(target: Any, candidates: Iterable[Any]) -> bool:
    """Compare Resolve timeline-item proxies by their stable UID.

    Resolve returns fresh ``PyRemoteObject`` wrappers from ``GetLinkedItems``;
    Python object membership therefore reports false even for the same live
    timeline item.  Stable item UIDs are the deterministic identity authority.
    """

    target_uid = _timeline_item_uid(target)
    values = list(candidates)
    if target_uid:
        return any(_timeline_item_uid(candidate) == target_uid for candidate in values)
    return target in values


def _stable_media_key(media: Any) -> tuple[str, str, str]:
    try:
        uid = str(media.GetUniqueId() or "")
    except AttributeError:
        uid = ""
    try:
        name = str(media.GetName() or "")
    except AttributeError:
        name = ""
    return (_norm(_media_path(media)), uid, name.casefold())


def _walk_media(folder: Any) -> Iterable[Any]:
    for item in folder.GetClipList() or []:
        yield item
    for child in folder.GetSubFolderList() or []:
        yield from _walk_media(child)


def _range(value: Any, label: str) -> tuple[int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(part, bool) or not isinstance(part, int) for part in value)
    ):
        raise GscGymResolveAudioError(f"{label} must be an exact two-integer frame range.")
    start, end = int(value[0]), int(value[1])
    if start < 0 or end <= start:
        raise GscGymResolveAudioError(f"{label} is empty or negative: {value!r}.")
    return start, end


def _asset_path(value: Any, label: str) -> str:
    if not isinstance(value, dict):
        raise GscGymResolveAudioError(f"{label} asset evidence is missing.")
    path = str(value.get("path") or "").strip()
    if not path:
        raise GscGymResolveAudioError(f"{label} has no exact media path.")
    return path


def _asset_name(value: Any, label: str) -> str:
    if not isinstance(value, dict):
        raise GscGymResolveAudioError(f"{label} asset evidence is missing.")
    name = str(value.get("name") or "").strip()
    if not name:
        raise GscGymResolveAudioError(f"{label} has no exact original media name.")
    return name


def _validate_track_geometry(rows: list[AudioPlacement], track_index: int) -> None:
    previous_end = -1
    for row in sorted(rows, key=lambda item: (item.record_start, item.record_end, item.kind)):
        if row.track_index != track_index:
            raise GscGymResolveAudioError("Audio plan contains a mismatched track index.")
        if row.record_start < previous_end:
            raise GscGymResolveAudioError(
                f"A{track_index} audio plan overlaps at {row.record_start}..{row.record_end}."
            )
        if row.record_end - row.record_start != row.source_end - row.source_start:
            raise GscGymResolveAudioError(
                f"A{track_index} audio plan is not exact 60 fps source/record geometry."
            )
        previous_end = row.record_end


def build_audio_placement_plan(manifest: dict[str, Any]) -> tuple[AudioPlacement, ...]:
    """Build the only accepted A1/A2/A3 scripting placement plan."""

    try:
        dialogue_asset = manifest["a1"]["dialogue_asset"]
        dialogue_rows = manifest["a1"]["placed"]
        bgm_rows = manifest["a2"]["segments"]
        outro = manifest["outro"]
    except (KeyError, TypeError) as exc:
        raise GscGymResolveAudioError("Manifest lacks its deterministic audio contract.") from exc
    if not isinstance(dialogue_rows, list) or not isinstance(bgm_rows, list):
        raise GscGymResolveAudioError("Manifest audio populations must be ordered lists.")
    if "a2_fade_derivatives" in manifest:
        raise GscGymResolveAudioError(
            "A2 manifest contains forbidden rendered fade derivatives."
        )
    source_rows = manifest.get("a2_original_source_clips")
    source_contract = manifest.get("a2_contract_audit")
    a2_manifest = manifest.get("a2")
    if (
        not isinstance(source_rows, list)
        or len(source_rows) != len(bgm_rows)
        or not isinstance(source_contract, dict)
        or source_contract.get("schema") != "gsc_a2_original_source_contract_v1"
        or source_contract.get("status") != "pass"
        or source_contract.get("segment_count") != len(bgm_rows)
        or source_contract.get("original_source_clip_count") != len(source_rows)
        or source_contract.get("materialized_derivative_count") != 0
        or source_contract.get("derived_media_allowed") is not False
        or source_contract.get("renamed_media_allowed") is not False
        or source_contract.get("source_trim_handles_editable") is not True
        or source_contract.get("source_clips") != source_rows
        or not isinstance(a2_manifest, dict)
        or a2_manifest.get("source_contract") != "original_library_media_v1"
        or a2_manifest.get("derived_media_allowed") is not False
        or a2_manifest.get("renamed_timeline_clips_allowed") is not False
        or a2_manifest.get("source_trim_handles_editable") is not True
    ):
        raise GscGymResolveAudioError(
            "Manifest lacks the permanent original-source A2 contract."
        )

    dialogue_path = _asset_path(dialogue_asset, "A1 dialogue")
    dialogue_name = _asset_name(dialogue_asset, "A1 dialogue")
    planned: list[AudioPlacement] = []
    for index, row in enumerate(dialogue_rows, start=1):
        if not isinstance(row, dict):
            raise GscGymResolveAudioError(f"A1 row {index} is not structured evidence.")
        record_start, record_end = _range(row.get("record_range"), f"A1 row {index} record")
        source_start, source_end = _range(row.get("source_range"), f"A1 row {index} source")
        planned.append(
            AudioPlacement(
                1,
                "dialogue",
                dialogue_path,
                record_start,
                record_end,
                source_start,
                source_end,
                source_name=dialogue_name,
            )
        )

    for index, (row, source_row) in enumerate(zip(bgm_rows, source_rows), start=1):
        if not isinstance(row, dict) or not isinstance(source_row, dict):
            raise GscGymResolveAudioError(f"A2 row {index} is not structured evidence.")
        record_start, record_end = _range(row.get("record_range"), f"A2 row {index} record")
        source_start, source_end = _range(row.get("source_range"), f"A2 row {index} source")
        asset = row.get("asset")
        path = _asset_path(asset, f"A2 row {index}")
        name = _asset_name(asset, f"A2 row {index}")
        origin = str(asset.get("origin_path") or "") if isinstance(asset, dict) else ""
        if (
            "baked_gain_db" in row
            or "timeline_gain_db" in row
            or not origin
            or _norm(path) != _norm(origin)
            or Path(path).suffix.casefold() != ".mp3"
            or any(part.casefold() == "a2-fades" for part in Path(path).parts)
            or name != Path(path).name
            or row.get("derived_media") is not False
            or row.get("source_trim_handles_editable") is not True
            or row.get("gain_policy")
            != "editable_timeline_adjust_volume_not_baked"
            or row.get("fade_policy") != "editable_timeline_metadata_not_baked"
        ):
            raise GscGymResolveAudioError(
                f"A2 row {index} is a renamed or rendered derivative, not original media."
            )
        try:
            media_start = int(asset["source_start_frame"])
            media_duration = int(asset["duration_frames"])
            media_end = media_start + media_duration
            gain = float(row["gain_db"])
            fade_in = int(row["fade_in_frames"])
            fade_out = int(row["fade_out_frames"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GscGymResolveAudioError(
                f"A2 row {index} lacks exact source, gain, or fade metadata."
            ) from exc
        handles = {"left": source_start - media_start, "right": media_end - source_end}
        if (
            media_duration <= 0
            or source_start < media_start
            or source_end > media_end
            or handles["left"] < 0
            or handles["right"] < 0
            or not math.isfinite(gain)
            or row.get("media_source_range") != [media_start, media_end]
            or row.get("available_handle_frames") != handles
            or fade_in not in {0, 30}
            or fade_out not in {0, 30}
            or source_row.get("schema") != "gsc_a2_original_source_clip_v1"
            or _norm(str(source_row.get("source_path") or "")) != _norm(path)
            or source_row.get("source_name") != name
            or len(str(source_row.get("source_sha256") or "")) != 64
            or source_row.get("record_range") != [record_start, record_end]
            or source_row.get("source_range") != [source_start, source_end]
            or source_row.get("media_source_start_frame") != media_start
            or source_row.get("media_duration_frames") != media_duration
            or source_row.get("media_source_end_frame") != media_end
            or source_row.get("available_handle_frames") != handles
            or source_row.get("source_trim_handles_editable") is not True
            or source_row.get("derived_media") is not False
            or source_row.get("role") != row.get("role")
            or source_row.get("battle_id") != row.get("battle_id")
            or source_row.get("label") != row.get("label")
            or source_row.get("gain_db") != gain
            or source_row.get("gain_policy")
            != "editable_timeline_adjust_volume_not_baked"
            or source_row.get("fade_in_frames") != fade_in
            or source_row.get("fade_out_frames") != fade_out
            or source_row.get("fade_policy")
            != "editable_timeline_metadata_not_baked"
        ):
            raise GscGymResolveAudioError(
                f"A2 row {index} source-native clip evidence does not match its placement."
            )
        planned.append(
            AudioPlacement(
                2,
                str(row.get("role") or "bgm"),
                path,
                record_start,
                record_end,
                source_start,
                source_end,
                source_name=name,
                media_source_start=media_start,
                media_duration=media_duration,
                left_handle=handles["left"],
                right_handle=handles["right"],
                gain_db=gain,
                fade_in_frames=fade_in,
                fade_out_frames=fade_out,
                original_source=True,
            )
        )

    outro_record_start, outro_record_end = _range(
        outro.get("record_range") if isinstance(outro, dict) else None,
        "A3 outro record",
    )
    outro_asset = outro.get("asset") if isinstance(outro, dict) else None
    outro_path = _asset_path(outro_asset, "A3 outro")
    outro_name = _asset_name(outro_asset, "A3 outro")
    try:
        outro_duration = int(outro_asset["duration_frames"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GscGymResolveAudioError("A3 outro has no exact full-source duration.") from exc
    if outro_duration != outro_record_end - outro_record_start:
        raise GscGymResolveAudioError(
            "A3 must use the full outro source at its exact record duration."
        )
    planned.append(
        AudioPlacement(
            3,
            "outro",
            outro_path,
            outro_record_start,
            outro_record_end,
            0,
            outro_duration,
            full_source=True,
            source_name=outro_name,
        )
    )

    for track_index in AUDIO_TRACK_NAMES:
        _validate_track_geometry(
            [row for row in planned if row.track_index == track_index],
            track_index,
        )
    ordered = tuple(
        sorted(
            planned,
            key=lambda row: (row.track_index, row.record_start, row.record_end, row.kind),
        )
    )
    if not any(row.track_index == 1 for row in ordered) or not any(
        row.track_index == 2 for row in ordered
    ):
        raise GscGymResolveAudioError("The deterministic A1/A2 populations may not be empty.")
    return ordered


def audio_plan_sha256(plan: Iterable[AudioPlacement]) -> str:
    payload = [row.evidence() for row in plan]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()


def _source_range(item: Any) -> list[int] | None:
    if not hasattr(item, "GetSourceStartFrame") or not hasattr(
        item, "GetSourceEndFrame"
    ):
        return None
    try:
        start = int(round(float(item.GetSourceStartFrame())))
        end = int(round(float(item.GetSourceEndFrame())))
    except (TypeError, ValueError):
        return None
    return [start, end] if end > start else None


def _trim_handles(item: Any) -> dict[str, int] | None:
    if not hasattr(item, "GetLeftOffset") or not hasattr(item, "GetRightOffset"):
        return None
    try:
        left = int(round(float(item.GetLeftOffset())))
        right = int(round(float(item.GetRightOffset())))
    except (TypeError, ValueError):
        return None
    return {"left": left, "right": right} if left >= 0 and right >= 0 else None


def _track_name(timeline: Any, index: int) -> str:
    try:
        return str(timeline.GetTrackName("audio", index) or "")
    except AttributeError:
        return ""


def _live_audio_rows(timeline: Any, track_index: int, timeline_start: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in timeline.GetItemListInTrack("audio", track_index) or []:
        start = int(item.GetStart()) - timeline_start
        duration = int(item.GetDuration())
        enabled = bool(item.GetClipEnabled()) if hasattr(item, "GetClipEnabled") else True
        rows.append(
            {
                "item": item,
                "path": _timeline_item_path(item),
                "media_name": _timeline_item_media_name(item),
                "timeline_name": _timeline_item_visible_name(item),
                "record_range": [start, start + duration],
                "source_range": _source_range(item),
                "available_handle_frames": _trim_handles(item),
                "enabled": enabled,
            }
        )
    rows.sort(
        key=lambda row: (
            row["record_range"][0],
            row["record_range"][1],
            _norm(row["path"]),
        )
    )
    return rows


def _video_snapshot(timeline: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = int(timeline.GetTrackCount("video") or 0)
    for track_index in range(1, count + 1):
        for item in timeline.GetItemListInTrack("video", track_index) or []:
            try:
                uid = str(item.GetUniqueId() or "")
            except AttributeError:
                uid = ""
            rows.append(
                {
                    "track_index": track_index,
                    "uid": uid,
                    "path": _norm(_timeline_item_path(item)),
                    "start": int(item.GetStart()),
                    "duration": int(item.GetDuration()),
                    "enabled": (
                        bool(item.GetClipEnabled())
                        if hasattr(item, "GetClipEnabled")
                        else True
                    ),
                }
            )
    rows.sort(key=lambda row: (row["track_index"], row["start"], row["duration"], row["path"], row["uid"]))
    return rows


def _outro_link_state(timeline: Any, plan: tuple[AudioPlacement, ...], timeline_start: int) -> dict[str, Any]:
    outro = next(row for row in plan if row.track_index == 3)
    absolute_start = timeline_start + outro.record_start
    duration = outro.record_end - outro.record_start
    video_matches = [
        item
        for item in timeline.GetItemListInTrack("video", 1) or []
        if int(item.GetStart()) == absolute_start
        and int(item.GetDuration()) == duration
        and _norm(_timeline_item_path(item)) == _norm(outro.path)
    ]
    audio_matches = [
        row["item"]
        for row in _live_audio_rows(timeline, 3, timeline_start)
        if row["record_range"] == [outro.record_start, outro.record_end]
        and _norm(row["path"]) == _norm(outro.path)
    ]
    video = video_matches[0] if len(video_matches) == 1 else None
    audio = audio_matches[0] if len(audio_matches) == 1 else None
    video_links = list(video.GetLinkedItems() or []) if video is not None else []
    audio_links = list(audio.GetLinkedItems() or []) if audio is not None else []
    return {
        "status": (
            "pass"
            if video is not None
            and audio is not None
            and _linked_item_present(audio, video_links)
            and _linked_item_present(video, audio_links)
            else "fail"
        ),
        "video": video,
        "audio": audio,
        "video_match_count": len(video_matches),
        "audio_match_count": len(audio_matches),
        "video_link_count": len(video_links),
        "audio_link_count": len(audio_links),
    }


def audit_audio_placement(timeline: Any, plan: tuple[AudioPlacement, ...]) -> dict[str, Any]:
    timeline_start = int(timeline.GetStartFrame())
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, evidence: Any) -> None:
        checks.append({"name": name, "status": "pass" if passed else "fail", "evidence": evidence})

    count = int(timeline.GetTrackCount("audio") or 0)
    check("exact_audio_track_count", count == 3, {"expected": 3, "actual": count})
    names = {index: _track_name(timeline, index) for index in AUDIO_TRACK_NAMES}
    check("exact_audio_track_names", names == AUDIO_TRACK_NAMES, {"expected": AUDIO_TRACK_NAMES, "actual": names})
    source_native = [row for row in plan if row.track_index == 2]
    check(
        "a2_original_sources_and_editable_trim_handles",
        bool(source_native)
        and all(
            row.original_source
            and row.source_name == Path(row.path).name
            and Path(row.path).suffix.casefold() == ".mp3"
            and not any(
                part.casefold() == "a2-fades" for part in Path(row.path).parts
            )
            and row.media_source_start is not None
            and row.media_duration is not None
            and row.left_handle == row.source_start - row.media_source_start
            and row.right_handle
            == row.media_source_start
            + row.media_duration
            - row.source_end
            and row.left_handle >= 0
            and row.right_handle >= 0
            and row.gain_db is not None
            and math.isfinite(row.gain_db)
            and row.fade_in_frames in {0, 30}
            and row.fade_out_frames in {0, 30}
            for row in source_native
        ),
        {"placements": [row.evidence() for row in source_native]},
    )
    for track_index in AUDIO_TRACK_NAMES:
        actual = _live_audio_rows(timeline, track_index, timeline_start)
        wanted = [row for row in plan if row.track_index == track_index]
        actual_evidence = [
            {
                "record_range": row["record_range"],
                "source_range": row["source_range"],
                "available_handle_frames": row["available_handle_frames"],
                "path": row["path"],
                "media_name": row["media_name"],
                "timeline_name": row["timeline_name"],
                "enabled": row["enabled"],
            }
            for row in actual
        ]
        wanted_evidence = [
            {
                "record_range": [row.record_start, row.record_end],
                "source_range": [row.source_start, row.source_end],
                "available_handle_frames": (
                    {"left": row.left_handle, "right": row.right_handle}
                    if track_index == 2
                    else None
                ),
                "path": row.path,
                "media_name": row.source_name,
                "timeline_name": row.source_name if track_index == 2 else None,
                "enabled": True,
            }
            for row in wanted
        ]
        passed = len(actual_evidence) == len(wanted_evidence) and all(
            actual_row["record_range"] == wanted_row["record_range"]
            and actual_row["source_range"] == wanted_row["source_range"]
            and _norm(actual_row["path"]) == _norm(wanted_row["path"])
            and actual_row["media_name"] == wanted_row["media_name"]
            and (
                track_index != 2
                or actual_row["timeline_name"] == wanted_row["timeline_name"]
            )
            and (
                track_index != 2
                or actual_row["available_handle_frames"]
                == wanted_row["available_handle_frames"]
            )
            and actual_row["enabled"] is True
            for actual_row, wanted_row in zip(actual_evidence, wanted_evidence)
        )
        check(
            f"exact_a{track_index}_scripting_inventory",
            passed,
            {"expected": wanted_evidence, "actual": actual_evidence},
        )
    link = _outro_link_state(timeline, plan, timeline_start)
    check(
        "exact_v1_a3_outro_link",
        link["status"] == "pass",
        {key: value for key, value in link.items() if key not in {"video", "audio"}},
    )
    failed = [row["name"] for row in checks if row["status"] != "pass"]
    return {
        "schema": AUDIO_PLACEMENT_SCHEMA,
        "status": "pass" if not failed else "fail",
        "plan_sha256": audio_plan_sha256(plan),
        "check_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "failed_checks": failed,
        "checks": checks,
    }


def _ensure_media(pool: Any, paths: Iterable[str]) -> dict[str, Any]:
    root = pool.GetRootFolder()
    by_path: dict[str, list[Any]] = {}
    for item in _walk_media(root):
        path = _media_path(item)
        if path:
            by_path.setdefault(_norm(path), []).append(item)
    missing = sorted(
        {str(Path(path).resolve()) for path in paths if _norm(path) not in by_path},
        key=_norm,
    )
    if missing:
        current = pool.GetCurrentFolder() if hasattr(pool, "GetCurrentFolder") else None
        try:
            imported = list(pool.ImportMedia(missing) or [])
            if len(imported) != len(missing):
                raise GscGymResolveAudioError(
                    f"Resolve imported only {len(imported)}/{len(missing)} required audio assets."
                )
        finally:
            if current is not None and hasattr(pool, "SetCurrentFolder"):
                pool.SetCurrentFolder(current)
        by_path.clear()
        for item in _walk_media(root):
            path = _media_path(item)
            if path:
                by_path.setdefault(_norm(path), []).append(item)
    result: dict[str, Any] = {}
    for path in sorted(set(paths), key=_norm):
        candidates = sorted(by_path.get(_norm(path), []), key=_stable_media_key)
        if not candidates:
            raise GscGymResolveAudioError(f"Resolve Media Pool lacks required audio asset: {path}")
        if _media_name(candidates[0]) != Path(path).name:
            raise GscGymResolveAudioError(
                f"Resolve Media Pool renamed original audio asset {Path(path).name!r}."
            )
        result[_norm(path)] = candidates[0]
    return result


def _append_exact(pool: Any, specs: list[dict[str, Any]], batch_size: int = 100) -> list[Any]:
    placed: list[Any] = []
    for offset in range(0, len(specs), batch_size):
        batch = specs[offset : offset + batch_size]
        got = list(pool.AppendToTimeline(batch) or [])
        if len(got) != len(batch):
            raise GscGymResolveAudioError(
                f"Resolve appended only {len(got)}/{len(batch)} scripted audio items."
            )
        placed.extend(got)
    return placed


def repair_receipt_bound_audio(
    *,
    project: Any,
    timeline: Any,
    manifest: dict[str, Any],
    deadline_check: Callable[[str], None] | None = None,
    journal: Callable[[str, dict[str, Any]], None] | None = None,
    allow_mutation: bool = True,
) -> dict[str, Any]:
    """Idempotently replace only audio on the already imported timeline."""

    plan = build_audio_placement_plan(manifest)
    plan_sha = audio_plan_sha256(plan)
    existing_audit = audit_audio_placement(timeline, plan)
    if existing_audit["status"] == "pass":
        return {
            "schema": AUDIO_PLACEMENT_SCHEMA,
            "status": "pass",
            "mode": "reused_exact_live_population",
            "plan_sha256": plan_sha,
            "mutation_count": 0,
            "deleted_audio_item_count": 0,
            "placed_audio_item_count": len(plan),
            "a2_original_source_media": True,
            "a2_source_trim_handles_editable": True,
            "a2_gain_or_fades_baked": False,
            "audit": existing_audit,
        }

    if not allow_mutation:
        raise GscGymResolveAudioError(
            "Completed Fairlight receipt forbids any later audio mutation; live audio "
            "no longer matches its exact deterministic placement."
        )

    if deadline_check:
        deadline_check("preparing receipt-bound GSC scripting audio placement")
    before_video = _video_snapshot(timeline)
    before_audio_count = int(timeline.GetTrackCount("audio") or 0)
    before_items = [
        item
        for track_index in range(1, before_audio_count + 1)
        for item in (timeline.GetItemListInTrack("audio", track_index) or [])
    ]
    if journal:
        journal(
            "pending_audio_clear",
            {
                "schema": AUDIO_PLACEMENT_SCHEMA,
                "plan_sha256": plan_sha,
                "pre_repair_failed_checks": existing_audit["failed_checks"],
                "pre_repair_audio_track_count": before_audio_count,
                "pre_repair_audio_item_count": len(before_items),
            },
        )
    if before_items and timeline.DeleteClips(before_items, False) is not True:
        raise GscGymResolveAudioError("Resolve refused the non-ripple imported-audio clear.")
    if any(
        timeline.GetItemListInTrack("audio", track_index) or []
        for track_index in range(1, int(timeline.GetTrackCount("audio") or 0) + 1)
    ):
        raise GscGymResolveAudioError("Imported audio remained after the non-ripple clear.")

    while int(timeline.GetTrackCount("audio") or 0) > 3:
        index = int(timeline.GetTrackCount("audio") or 0)
        if not hasattr(timeline, "DeleteTrack") or timeline.DeleteTrack("audio", index) is not True:
            raise GscGymResolveAudioError(
                f"Receipt-bound timeline has an extra empty A{index} track Resolve could not remove."
            )
    while int(timeline.GetTrackCount("audio") or 0) < 3:
        if timeline.AddTrack("audio", "stereo") is not True:
            raise GscGymResolveAudioError("Resolve could not add the required stereo audio track.")
    if int(timeline.GetTrackCount("audio") or 0) != 3:
        raise GscGymResolveAudioError("Resolve audio track count is not exactly three.")
    for track_index, name in AUDIO_TRACK_NAMES.items():
        if timeline.SetTrackName("audio", track_index, name) is not True:
            raise GscGymResolveAudioError(f"Resolve could not name A{track_index} {name!r}.")

    if project.SetCurrentTimeline(timeline) is not True:
        raise GscGymResolveAudioError("Resolve could not retain the receipt-bound current timeline.")
    pool = project.GetMediaPool()
    media = _ensure_media(pool, [row.path for row in plan])
    timeline_start = int(timeline.GetStartFrame())
    for track_index in AUDIO_TRACK_NAMES:
        rows = [row for row in plan if row.track_index == track_index]
        specs: list[dict[str, Any]] = []
        for row in rows:
            spec: dict[str, Any] = {
                "mediaPoolItem": media[_norm(row.path)],
                "recordFrame": timeline_start + row.record_start,
                "trackIndex": track_index,
                "mediaType": 2,
            }
            if not row.full_source:
                spec.update({"startFrame": row.source_start, "endFrame": row.source_end})
            specs.append(spec)
        _append_exact(pool, specs)

    link = _outro_link_state(timeline, plan, timeline_start)
    if link["video"] is None or link["audio"] is None:
        raise GscGymResolveAudioError("Scripted audio placement lacks its exact V1/A3 outro pair.")
    link_mutation = False
    if link["status"] != "pass":
        timeline.SetClipsLinked([link["video"], link["audio"]], True)
        link_mutation = True
        linked_postcondition = _outro_link_state(timeline, plan, timeline_start)
        if linked_postcondition["status"] != "pass":
            raise GscGymResolveAudioError(
                "Resolve could not prove the exact V1/A3 outro link postcondition."
            )

    after_video = _video_snapshot(timeline)
    if after_video != before_video:
        raise GscGymResolveAudioError(
            "Non-ripple audio placement changed the receipt-bound video inventory."
        )
    audit = audit_audio_placement(timeline, plan)
    if audit["status"] != "pass":
        raise GscGymResolveAudioError(
            "Scripted audio placement failed: " + ", ".join(audit["failed_checks"])
        )
    report = {
        "schema": AUDIO_PLACEMENT_SCHEMA,
        "status": "pass",
        "mode": "rebuilt_with_scripting_api",
        "plan_sha256": plan_sha,
        "mutation_count": 1,
        "deleted_audio_item_count": len(before_items),
        "placed_audio_item_count": len(plan),
        "track_names": AUDIO_TRACK_NAMES,
        "a2_original_source_media": True,
        "a2_source_trim_handles_editable": True,
        "a2_gain_or_fades_baked": False,
        "non_ripple_delete": True,
        "video_inventory_unchanged": True,
        "outro_link_mutation": link_mutation,
        "audit": audit,
    }
    if journal:
        journal("audio_placement_pass", report)
    return report


__all__ = [
    "AUDIO_PLACEMENT_SCHEMA",
    "AUDIO_TRACK_NAMES",
    "AudioPlacement",
    "GscGymResolveAudioError",
    "audio_plan_sha256",
    "audit_audio_placement",
    "build_audio_placement_plan",
    "repair_receipt_bound_audio",
]
