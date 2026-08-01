"""Deterministic, idempotent Resolve Media Pool organization for GSC gyms.

The GSC workflow imports one editorial FCPXML.  This module performs the
separate reusable-asset organization transaction without creating another
timeline: it materializes the RBY-parity bin tree, imports only missing
approved assets, moves every Media Pool item to its canonical destination,
and then audits the complete live inventory.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from resolve_mcp.orchestrator.gsc_gym_intro_library import (
    EXPECTED_MASTER_MEDIA,
    EXPECTED_TECHNICAL_CONTRACT,
    INTRO_LIBRARY_SCHEMA,
)


ORGANIZATION_SCHEMA = "gsc_gym_media_pool_bins_v1"
LIVE_AUDIT_SCHEMA = "gsc_gym_media_pool_bins_live_audit_v1"

BGM_AUDIO_EXTENSIONS = (
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".wav",
)

TOP_LEVEL_BINS = (
    "01 NEWEST TIMELINE",
    "02 CODEX TIMELINES",
    "03 ORIGINAL AUTO-EDITOR TIMELINES",
    "04 PROJECT MEDIA",
    "05 SHARED ASSETS",
)

SHARED_BINS = (
    "BGM",
    "Leader Intros",
    "Rival Intros",
    "Show Intros & Outros",
    "Adjustment Clips",
    "Other Shared Assets",
)

EXPECTED_INTRO_CATEGORY_COUNTS = {
    "leader": 16,
    "rival": 21,
}
EXPECTED_INTRO_VARIANT_COUNT = sum(EXPECTED_INTRO_CATEGORY_COUNTS.values())


class GscGymMediaPoolError(RuntimeError):
    """Raised when deterministic Media Pool organization cannot converge."""


def _object_uid(value: Any) -> str:
    try:
        return str(value.GetUniqueId() or "")
    except (AttributeError, TypeError):
        return ""


def _normalized_media_path(value: str | Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        normalized = Path(text).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        normalized = Path(text)
    return str(normalized).replace("\\", "/").rstrip("/").casefold()


def _path_is_within(path_key: str, directory_key: str) -> bool:
    return bool(
        path_key
        and directory_key
        and (path_key == directory_key or path_key.startswith(directory_key + "/"))
    )


def _require_exact_fields(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    label: str,
) -> None:
    mismatches = {
        key: {"expected": expected_value, "actual": actual.get(key)}
        for key, expected_value in expected.items()
        if actual.get(key) != expected_value
        or type(actual.get(key)) is not type(expected_value)
    }
    if mismatches:
        rendered = ", ".join(
            f"{key}={row['actual']!r} (expected {row['expected']!r})"
            for key, row in sorted(mismatches.items())
        )
        raise GscGymMediaPoolError(f"{label} violates the approved contract: {rendered}")


def _require_file(path: str | Path, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise GscGymMediaPoolError(
            f"Required {label} may not be a symbolic link: {candidate}"
        )
    value = candidate.resolve()
    if not value.is_file():
        raise GscGymMediaPoolError(f"Required {label} is missing: {value}")
    return value


def _audio_library_inventory(
    directory: str | Path,
    *,
    role: str,
) -> tuple[Path, list[Path], list[dict[str, Any]]]:
    source = Path(directory)
    if not source.is_dir():
        raise GscGymMediaPoolError(f"Configured {role} BGM directory is missing: {source}")
    source = source.resolve()
    all_files = sorted(
        (path for path in source.rglob("*") if path.is_file()),
        key=lambda path: (
            str(path.relative_to(source)).replace("\\", "/").casefold(),
            str(path.relative_to(source)).replace("\\", "/"),
        ),
    )
    unsupported = [
        path for path in all_files if path.suffix.casefold() not in BGM_AUDIO_EXTENSIONS
    ]
    if unsupported:
        raise GscGymMediaPoolError(
            f"Configured {role} BGM directory contains unsupported file(s): "
            + ", ".join(str(path) for path in unsupported)
        )
    if not all_files:
        raise GscGymMediaPoolError(
            f"Configured {role} BGM directory contains no supported audio: {source}"
        )

    resolved: list[Path] = []
    seen: dict[str, Path] = {}
    for path in all_files:
        if path.is_symlink():
            raise GscGymMediaPoolError(
                f"Configured {role} BGM directory contains a symbolic link: {path}"
            )
        value = path.resolve()
        key = _normalized_media_path(value)
        if not key or key in seen:
            raise GscGymMediaPoolError(
                f"Configured {role} BGM directory has a duplicate/colliding path: {path}"
            )
        seen[key] = value
        resolved.append(value)

    rows = [
        {
            "path": str(path),
            "relative_path": str(path.relative_to(source)).replace("\\", "/"),
            "bytes": path.stat().st_size,
        }
        for path in resolved
    ]
    return source, resolved, rows


def _intro_library_inventory(
    manifest_path: str | Path,
) -> tuple[Path, str, list[dict[str, Any]]]:
    manifest = _require_file(manifest_path, "Gen 2 intro-library manifest")
    try:
        manifest_bytes = manifest.read_bytes()
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GscGymMediaPoolError(
            f"Approved Gen 2 intro-library manifest is unreadable: {manifest}"
        ) from exc
    if not isinstance(payload, dict):
        raise GscGymMediaPoolError("Gen 2 intro-library manifest must be a JSON object")
    if payload.get("schema") != INTRO_LIBRARY_SCHEMA or payload.get("status") != "pass":
        raise GscGymMediaPoolError(
            "Gen 2 intro-library manifest is not the approved passing schema"
        )
    declared_root = payload.get("library_root")
    if not isinstance(declared_root, str) or not declared_root.strip():
        raise GscGymMediaPoolError("Gen 2 intro-library manifest lacks library_root")
    library_root = Path(declared_root).resolve()
    if library_root != manifest.parent.resolve():
        raise GscGymMediaPoolError(
            "Gen 2 intro-library manifest is not located at its declared library_root"
        )
    technical = payload.get("technical_contract")
    if not isinstance(technical, dict):
        raise GscGymMediaPoolError("Gen 2 intro-library technical_contract is not an object")
    _require_exact_fields(
        technical,
        EXPECTED_TECHNICAL_CONTRACT,
        label="Gen 2 intro-library technical_contract",
    )

    variants = payload.get("variants")
    if not isinstance(variants, list) or len(variants) != EXPECTED_INTRO_VARIANT_COUNT:
        raise GscGymMediaPoolError(
            "Gen 2 intro-library manifest must contain exactly "
            f"{EXPECTED_INTRO_VARIANT_COUNT} approved variants; found "
            f"{len(variants) if isinstance(variants, list) else 0}"
        )
    variant_ids: set[str] = set()
    media_paths: set[str] = set()
    category_counts = {key: 0 for key in EXPECTED_INTRO_CATEGORY_COUNTS}
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(variants):
        if not isinstance(raw, dict):
            raise GscGymMediaPoolError(f"Gen 2 intro variants[{index}] is not an object")
        variant_id = raw.get("variant_id")
        if not isinstance(variant_id, str) or not variant_id.strip():
            raise GscGymMediaPoolError(f"Gen 2 intro variants[{index}] lacks variant_id")
        if variant_id in variant_ids:
            raise GscGymMediaPoolError(f"Gen 2 intro manifest repeats {variant_id!r}")
        variant_ids.add(variant_id)
        category = raw.get("category")
        if category not in EXPECTED_INTRO_CATEGORY_COUNTS:
            raise GscGymMediaPoolError(
                f"Gen 2 intro {variant_id!r} has unsupported category {category!r}"
            )
        category_counts[category] += 1
        if raw.get("qa_status") != "pass":
            raise GscGymMediaPoolError(
                f"Gen 2 intro {variant_id!r} is not manifest-approved/pass"
            )
        media = raw.get("media")
        if not isinstance(media, dict):
            raise GscGymMediaPoolError(
                f"Gen 2 intro {variant_id!r} media contract is not an object"
            )
        _require_exact_fields(
            media,
            EXPECTED_MASTER_MEDIA,
            label=f"Gen 2 intro {variant_id!r} media",
        )
        relative_value = raw.get("master_path")
        if not isinstance(relative_value, str) or not relative_value.strip():
            raise GscGymMediaPoolError(
                f"Gen 2 intro {variant_id!r} lacks master_path"
            )
        relative = Path(relative_value)
        if relative.is_absolute() or relative.drive:
            raise GscGymMediaPoolError(
                f"Gen 2 intro {variant_id!r} master_path must be relative"
            )
        candidate = library_root / relative
        if candidate.is_symlink():
            raise GscGymMediaPoolError(
                f"Approved Gen 2 intro master may not be a symbolic link: {candidate}"
            )
        path = candidate.resolve()
        try:
            path.relative_to(library_root)
        except ValueError as exc:
            raise GscGymMediaPoolError(
                f"Gen 2 intro {variant_id!r} escapes library_root"
            ) from exc
        if path.suffix.casefold() != ".mov" or not path.is_file():
            raise GscGymMediaPoolError(
                f"Approved Gen 2 intro master is missing or invalid: {path}"
            )
        path_key = _normalized_media_path(path)
        if not path_key or path_key in media_paths:
            raise GscGymMediaPoolError(
                f"Gen 2 intro manifest has a duplicate/colliding master path: {path}"
            )
        media_paths.add(path_key)
        master_bytes = raw.get("master_bytes")
        if isinstance(master_bytes, bool) or not isinstance(master_bytes, int) or master_bytes <= 0:
            raise GscGymMediaPoolError(
                f"Gen 2 intro {variant_id!r} has invalid master_bytes"
            )
        if path.stat().st_size != master_bytes:
            raise GscGymMediaPoolError(
                f"Gen 2 intro {variant_id!r} byte count changed"
            )
        master_sha256 = raw.get("master_sha256")
        if not isinstance(master_sha256, str) or re.fullmatch(
            r"[0-9A-Fa-f]{64}", master_sha256
        ) is None:
            raise GscGymMediaPoolError(
                f"Gen 2 intro {variant_id!r} has invalid master_sha256"
            )
        rows.append(
            {
                "variant_id": variant_id,
                "category": category,
                "path": str(path),
                "relative_path": str(relative).replace("\\", "/"),
                "bytes": master_bytes,
                "sha256": master_sha256.upper(),
            }
        )

    if category_counts != EXPECTED_INTRO_CATEGORY_COUNTS:
        raise GscGymMediaPoolError(
            "Gen 2 intro manifest category gamut changed: "
            f"{category_counts!r} != {EXPECTED_INTRO_CATEGORY_COUNTS!r}"
        )
    rows.sort(
        key=lambda row: (
            0 if row["category"] == "leader" else 1,
            row["variant_id"].casefold(),
            row["relative_path"].casefold(),
        )
    )
    return library_root, hashlib.sha256(manifest_bytes).hexdigest().upper(), rows


@dataclass(frozen=True)
class _RequiredAsset:
    path: Path
    bin_path: tuple[str, ...]
    kind: str
    identity: str


@dataclass(frozen=True)
class _InventoryContext:
    project_dir: Path
    nonbattle_bgm_root: Path
    battle_bgm_root: Path
    intro_library_root: Path
    required_by_key: dict[str, _RequiredAsset]
    asset_contract: dict[str, Any]


def _inventory_context(
    *,
    project_dir: str | Path,
    nonbattle_bgm_dir: str | Path,
    battle_bgm_dir: str | Path,
    intro_manifest_path: str | Path,
    opening_intro_path: str | Path,
    outro_path: str | Path,
) -> _InventoryContext:
    project_root = Path(project_dir).resolve()
    if not project_root.is_dir():
        raise GscGymMediaPoolError(f"GSC project directory is missing: {project_root}")
    nonbattle_root, nonbattle_files, nonbattle_rows = _audio_library_inventory(
        nonbattle_bgm_dir,
        role="nonbattle",
    )
    battle_root, battle_files, battle_rows = _audio_library_inventory(
        battle_bgm_dir,
        role="battle",
    )
    intro_root, intro_manifest_sha, intro_rows = _intro_library_inventory(
        intro_manifest_path
    )
    opening = _require_file(opening_intro_path, "approved 4x GSC show intro")
    outro = _require_file(outro_path, "approved GSC show outro")

    required: list[_RequiredAsset] = []
    required.extend(
        _RequiredAsset(
            path=path,
            bin_path=(TOP_LEVEL_BINS[4], SHARED_BINS[0]),
            kind=f"{role}_bgm",
            identity=str(path.relative_to(root)).replace("\\", "/"),
        )
        for role, root, paths in (
            ("nonbattle", nonbattle_root, nonbattle_files),
            ("battle", battle_root, battle_files),
        )
        for path in paths
    )
    required.extend(
        _RequiredAsset(
            path=Path(row["path"]),
            bin_path=(
                TOP_LEVEL_BINS[4],
                SHARED_BINS[1] if row["category"] == "leader" else SHARED_BINS[2],
            ),
            kind=f"{row['category']}_intro",
            identity=str(row["variant_id"]),
        )
        for row in intro_rows
    )
    required.extend(
        (
            _RequiredAsset(
                path=opening,
                bin_path=(TOP_LEVEL_BINS[4], SHARED_BINS[3]),
                kind="show_intro",
                identity="approved_4x_opening",
            ),
            _RequiredAsset(
                path=outro,
                bin_path=(TOP_LEVEL_BINS[4], SHARED_BINS[3]),
                kind="show_outro",
                identity="approved_outro",
            ),
        )
    )
    required_by_key: dict[str, _RequiredAsset] = {}
    for asset in required:
        key = _normalized_media_path(asset.path)
        if not key or key in required_by_key:
            raise GscGymMediaPoolError(
                f"Reusable GSC asset paths collide: {asset.path}"
            )
        required_by_key[key] = asset

    asset_contract = {
        "schema": "gsc_gym_reusable_asset_contract_v1",
        "intro_library": {
            "manifest": str(Path(intro_manifest_path).resolve()),
            "manifest_sha256": intro_manifest_sha,
            "library_root": str(intro_root),
            "variant_count": len(intro_rows),
            "category_counts": dict(EXPECTED_INTRO_CATEGORY_COUNTS),
            "files": intro_rows,
            "verification_policy": (
                "manifest_schema_status_technical_contract_path_byte_count_and_sha_identity;"
                "full_media_sha_revalidated_when_a_variant_is_selected_for_timeline_use"
            ),
        },
        "bgm_libraries": {
            "nonbattle": {
                "source_directory": str(nonbattle_root),
                "file_count": len(nonbattle_rows),
                "total_bytes": sum(row["bytes"] for row in nonbattle_rows),
                "files": nonbattle_rows,
            },
            "battle": {
                "source_directory": str(battle_root),
                "file_count": len(battle_rows),
                "total_bytes": sum(row["bytes"] for row in battle_rows),
                "files": battle_rows,
            },
            "combined_file_count": len(nonbattle_rows) + len(battle_rows),
        },
        "show_assets": [
            {"role": "opening_4x", "path": str(opening), "bytes": opening.stat().st_size},
            {"role": "outro", "path": str(outro), "bytes": outro.stat().st_size},
        ],
        "required_asset_count": len(required_by_key),
    }
    return _InventoryContext(
        project_dir=project_root,
        nonbattle_bgm_root=nonbattle_root,
        battle_bgm_root=battle_root,
        intro_library_root=intro_root,
        required_by_key=required_by_key,
        asset_contract=asset_contract,
    )


def _item_properties(item: Any) -> dict[str, Any]:
    try:
        return dict(item.GetClipProperty() or {})
    except (AttributeError, TypeError, ValueError):
        return {}


def _collect_items(
    folder: Any,
    *,
    path: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], Any]]:
    rows = [(path, item) for item in (folder.GetClipList() or [])]
    for child in folder.GetSubFolderList() or []:
        rows.extend(
            _collect_items(
                child,
                path=path + (str(child.GetName() or ""),),
            )
        )
    return rows


def _named_children(parent: Any, name: str) -> list[Any]:
    return [
        folder
        for folder in (parent.GetSubFolderList() or [])
        if str(folder.GetName() or "") == name
    ]


def _unexpected_folder_rows(root: Any) -> list[tuple[tuple[str, ...], Any]]:
    unexpected: list[tuple[tuple[str, ...], Any]] = []

    def visit(parent: Any, path: tuple[str, ...]) -> None:
        if not path:
            allowed = set(TOP_LEVEL_BINS)
        elif path == (TOP_LEVEL_BINS[4],):
            allowed = set(SHARED_BINS)
        else:
            allowed = set()
        for child in parent.GetSubFolderList() or []:
            name = str(child.GetName() or "")
            child_path = path + (name,)
            if name not in allowed:
                unexpected.append((child_path, child))
                continue
            visit(child, child_path)

    visit(root, ())
    return unexpected


def _canonical_folder_inventory(
    root: Any,
) -> tuple[dict[tuple[str, ...], Any], list[str]]:
    folders: dict[tuple[str, ...], Any] = {}
    failures: list[str] = []
    for name in TOP_LEVEL_BINS:
        matches = _named_children(root, name)
        if len(matches) != 1:
            failures.append(f"canonical_top_level_bin_{name!r}_count={len(matches)}")
            continue
        folders[(name,)] = matches[0]
    shared = folders.get((TOP_LEVEL_BINS[4],))
    if shared is None:
        failures.extend(
            f"canonical_shared_bin_{name!r}_count=0" for name in SHARED_BINS
        )
    else:
        for name in SHARED_BINS:
            matches = _named_children(shared, name)
            if len(matches) != 1:
                failures.append(f"canonical_shared_bin_{name!r}_count={len(matches)}")
                continue
            folders[(TOP_LEVEL_BINS[4], name)] = matches[0]
    unexpected = _unexpected_folder_rows(root)
    if unexpected:
        failures.append(
            "unexpected_media_pool_folders="
            + ",".join("/".join(path) for path, _folder in unexpected)
        )
    return folders, failures


def _project_timelines(project: Any) -> list[Any]:
    result: list[Any] = []
    for index in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline is not None:
            result.append(timeline)
    return result


def _timeline_matches(project: Any, name: str) -> list[Any]:
    return [
        timeline
        for timeline in _project_timelines(project)
        if str(timeline.GetName() or "") == name
    ]


def _timeline_media_pool_references(project: Any) -> dict[str, list[dict[str, Any]]]:
    """Return stable MediaPoolItem-UID references across every live timeline."""

    references: dict[str, list[dict[str, Any]]] = {}
    for timeline in _project_timelines(project):
        timeline_uid = _object_uid(timeline)
        if not timeline_uid:
            raise GscGymMediaPoolError(
                "Resolve timeline inventory contains an item without a stable UID"
            )
        get_track_count = getattr(timeline, "GetTrackCount", None)
        get_track_items = getattr(timeline, "GetItemListInTrack", None)
        if not callable(get_track_count) or not callable(get_track_items):
            raise GscGymMediaPoolError(
                "Resolve does not expose timeline track inventory for safe Media Pool "
                "duplicate reconciliation"
            )
        for track_type in ("video", "audio"):
            for track_index in range(1, int(get_track_count(track_type) or 0) + 1):
                for timeline_item in get_track_items(track_type, track_index) or []:
                    get_media_pool_item = getattr(timeline_item, "GetMediaPoolItem", None)
                    media_pool_item = (
                        get_media_pool_item() if callable(get_media_pool_item) else None
                    )
                    if media_pool_item is None:
                        continue
                    media_uid = _object_uid(media_pool_item)
                    if not media_uid:
                        raise GscGymMediaPoolError(
                            "A timeline-referenced Media Pool item has no stable UID; "
                            "duplicate reconciliation is unsafe"
                        )
                    references.setdefault(media_uid, []).append(
                        {
                            "timeline_uid": timeline_uid,
                            "track_type": track_type,
                            "track_index": track_index,
                            "timeline_item_name": str(timeline_item.GetName() or ""),
                        }
                    )
    return references


def _reconcile_required_asset_duplicates(
    project: Any,
    media_pool: Any,
    context: _InventoryContext,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove only provably unused import duplicates and retain live references.

    Resolve's FCPXML importer may create a second MediaPoolItem for an approved
    path that is already present in a reusable bin.  The imported timeline is
    bound to that new item, so blindly deleting the noncanonical occurrence can
    break the edit.  Reconciliation therefore requires one existing canonical
    occurrence, retains the sole occurrence referenced by any project timeline
    (or the canonical occurrence when none are referenced), and deletes only
    stable-UID occurrences proven globally unreferenced.
    """

    grouped: dict[str, list[dict[str, Any]]] = {
        key: [] for key in context.required_by_key
    }
    for row in rows:
        if row["file_path_key"] in grouped:
            grouped[row["file_path_key"]].append(row)
    duplicate_keys = sorted(
        (key for key, found in grouped.items() if len(found) > 1),
        key=lambda key: _normalized_media_path(context.required_by_key[key].path),
    )
    if not duplicate_keys:
        return []

    references_before = _timeline_media_pool_references(project)
    timeline_uids_before = [_object_uid(item) for item in _project_timelines(project)]
    if (
        not all(timeline_uids_before)
        or len(timeline_uids_before) != len(set(timeline_uids_before))
    ):
        raise GscGymMediaPoolError(
            "Resolve timeline inventory is not stable enough for duplicate reconciliation"
        )
    delete_clips = getattr(media_pool, "DeleteClips", None)
    if not callable(delete_clips):
        raise GscGymMediaPoolError(
            "Resolve does not expose DeleteClips for safe Media Pool duplicate reconciliation"
        )

    plans: list[dict[str, Any]] = []
    delete_items: list[Any] = []
    deleted_uids: set[str] = set()
    for key in duplicate_keys:
        asset = context.required_by_key[key]
        found = grouped[key]
        canonical = [row for row in found if row["folder_path"] == asset.bin_path]
        if len(canonical) != 1:
            raise GscGymMediaPoolError(
                "Reusable GSC duplicate reconciliation requires exactly one existing "
                f"canonical occurrence for {asset.path}; found {len(canonical)}"
            )
        uids = [_object_uid(row["item"]) for row in found]
        if not all(uids) or len(uids) != len(set(uids)):
            raise GscGymMediaPoolError(
                "Reusable GSC duplicate occurrences lack distinct stable UIDs: "
                f"{asset.path}"
            )
        referenced = [
            row for row, uid in zip(found, uids) if uid in references_before
        ]
        if len(referenced) > 1:
            raise GscGymMediaPoolError(
                "Multiple duplicate Media Pool items are referenced by live timelines; "
                f"refusing ambiguous reconciliation for {asset.path}"
            )
        retained = referenced[0] if referenced else canonical[0]
        retained_uid = _object_uid(retained["item"])
        discarded = [row for row in found if row is not retained]
        discarded_uids = [_object_uid(row["item"]) for row in discarded]
        if any(uid in references_before for uid in discarded_uids):
            raise GscGymMediaPoolError(
                f"Refusing to delete a timeline-referenced Media Pool item for {asset.path}"
            )
        if any(uid in deleted_uids for uid in discarded_uids):
            raise GscGymMediaPoolError(
                "Duplicate reconciliation selected the same Media Pool UID twice"
            )
        deleted_uids.update(discarded_uids)
        delete_items.extend(row["item"] for row in discarded)
        plans.append(
            {
                "path": str(asset.path),
                "canonical_bin": " / ".join(asset.bin_path),
                "retained_uid": retained_uid,
                "retained_was_referenced": retained_uid in references_before,
                "retained_original_bin": " / ".join(retained["folder_path"]),
                "deleted_unreferenced_uids": discarded_uids,
            }
        )

    if not delete_items or delete_clips(delete_items) is not True:
        raise GscGymMediaPoolError(
            "Resolve could not delete the provably unreferenced reusable-asset duplicates"
        )

    timeline_uids_after = [_object_uid(item) for item in _project_timelines(project)]
    references_after = _timeline_media_pool_references(project)
    if timeline_uids_after != timeline_uids_before or references_after != references_before:
        raise GscGymMediaPoolError(
            "Media Pool duplicate reconciliation changed timeline inventory or references"
        )
    verified_groups: dict[str, list[dict[str, Any]]] = {
        key: [] for key in duplicate_keys
    }
    for row in _pool_rows(media_pool.GetRootFolder()):
        if row["file_path_key"] in verified_groups:
            verified_groups[row["file_path_key"]].append(row)
    for key, plan in zip(duplicate_keys, plans):
        found = verified_groups[key]
        if (
            len(found) != 1
            or _object_uid(found[0]["item"]) != plan["retained_uid"]
        ):
            raise GscGymMediaPoolError(
                "Reusable GSC duplicate deletion did not retain the exact planned item: "
                f"{context.required_by_key[key].path}"
            )
    return plans


def classify_item(
    *,
    name: str,
    item_type: str,
    file_path: str,
    newest_timeline_name: str,
    context: _InventoryContext,
) -> tuple[str, ...]:
    """Return the one canonical bin path for a GSC Media Pool item."""

    lowered_name = name.casefold()
    if item_type.casefold() == "timeline":
        if name == "1s":
            return (TOP_LEVEL_BINS[4], SHARED_BINS[4])
        if name == newest_timeline_name:
            return (TOP_LEVEL_BINS[0],)
        if "codex" in lowered_name or "deterministic" in lowered_name:
            return (TOP_LEVEL_BINS[1],)
        return (TOP_LEVEL_BINS[2],)

    path_key = _normalized_media_path(file_path)
    required = context.required_by_key.get(path_key)
    if required is not None:
        return required.bin_path
    if _path_is_within(path_key, _normalized_media_path(context.project_dir)):
        return (TOP_LEVEL_BINS[3],)
    return (TOP_LEVEL_BINS[4], SHARED_BINS[5])


def _pool_rows(root: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for folder_path, item in _collect_items(root):
        properties = _item_properties(item)
        rows.append(
            {
                "folder_path": folder_path,
                "item": item,
                "name": str(item.GetName() or ""),
                "item_type": str(properties.get("Type") or ""),
                "file_path": str(properties.get("File Path") or ""),
                "file_path_key": _normalized_media_path(
                    properties.get("File Path") or ""
                ),
            }
        )
    return rows


def _unexpected_library_items(
    rows: Iterable[dict[str, Any]],
    context: _InventoryContext,
) -> list[dict[str, Any]]:
    roots = (
        ("nonbattle_bgm", _normalized_media_path(context.nonbattle_bgm_root)),
        ("battle_bgm", _normalized_media_path(context.battle_bgm_root)),
        ("intro", _normalized_media_path(context.intro_library_root)),
    )
    unexpected: list[dict[str, Any]] = []
    for row in rows:
        key = row["file_path_key"]
        if not key or key in context.required_by_key:
            continue
        matching_root = next((name for name, root in roots if _path_is_within(key, root)), None)
        if matching_root is None:
            continue
        unexpected.append(
            {
                "library": matching_root,
                "name": row["name"],
                "file_path": row["file_path"],
                "current_bin": " / ".join(row["folder_path"]),
            }
        )
    unexpected.sort(key=lambda row: (_normalized_media_path(row["file_path"]), row["name"]))
    return unexpected


def audit_media_pool(
    project: Any,
    *,
    newest_timeline_name: str,
    project_dir: str | Path,
    nonbattle_bgm_dir: str | Path,
    battle_bgm_dir: str | Path,
    intro_manifest_path: str | Path,
    opening_intro_path: str | Path,
    outro_path: str | Path,
    expected_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only audit of the complete reusable-asset and bin contract."""

    context = _inventory_context(
        project_dir=project_dir,
        nonbattle_bgm_dir=nonbattle_bgm_dir,
        battle_bgm_dir=battle_bgm_dir,
        intro_manifest_path=intro_manifest_path,
        opening_intro_path=opening_intro_path,
        outro_path=outro_path,
    )
    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()
    folders, folder_failures = _canonical_folder_inventory(root)
    rows = _pool_rows(root)

    timelines = _timeline_matches(project, newest_timeline_name)
    newest_uid = _object_uid(timelines[0]) if len(timelines) == 1 else ""
    occurrences: dict[str, list[dict[str, Any]]] = {
        key: [] for key in context.required_by_key
    }
    misfiled: list[dict[str, Any]] = []
    newest_media_pool_items = 0
    for row in rows:
        target = classify_item(
            name=row["name"],
            item_type=row["item_type"],
            file_path=row["file_path"],
            newest_timeline_name=newest_timeline_name,
            context=context,
        )
        if (
            row["item_type"].casefold() == "timeline"
            and row["name"] == newest_timeline_name
        ):
            newest_media_pool_items += 1
        if row["file_path_key"] in occurrences:
            occurrences[row["file_path_key"]].append(
                {
                    "name": row["name"],
                    "file_path": row["file_path"],
                    "current_bin": " / ".join(row["folder_path"]),
                }
            )
        if row["folder_path"] != target:
            misfiled.append(
                {
                    "name": row["name"],
                    "type": row["item_type"],
                    "file_path": row["file_path"],
                    "current_bin": " / ".join(row["folder_path"]),
                    "expected_bin": " / ".join(target),
                }
            )

    missing = [
        str(context.required_by_key[key].path)
        for key, found in occurrences.items()
        if not found
    ]
    duplicated = [
        {
            "path": str(context.required_by_key[key].path),
            "occurrences": found,
        }
        for key, found in occurrences.items()
        if len(found) > 1
    ]
    wrong_bins = [
        {
            "path": str(context.required_by_key[key].path),
            "current_bin": found[0]["current_bin"],
            "expected_bin": " / ".join(context.required_by_key[key].bin_path),
        }
        for key, found in occurrences.items()
        if len(found) == 1
        and tuple(part.strip() for part in found[0]["current_bin"].split(" / ") if part.strip())
        != context.required_by_key[key].bin_path
    ]
    unexpected_library_items = _unexpected_library_items(rows, context)

    kind_present_counts: dict[str, int] = {}
    for key, asset in context.required_by_key.items():
        if len(occurrences[key]) == 1:
            kind_present_counts[asset.kind] = kind_present_counts.get(asset.kind, 0) + 1
    checks: dict[str, bool] = {
        "canonical_folder_layout_exact": not folder_failures,
        "one_newest_timeline": len(timelines) == 1,
        "newest_timeline_uid_present": bool(newest_uid),
        "one_newest_media_pool_item": newest_media_pool_items == 1,
        "all_items_in_canonical_bins": not misfiled,
        "all_required_reusable_assets_present_once": not missing and not duplicated,
        "all_required_reusable_assets_in_canonical_bins": (
            not missing and not duplicated and not wrong_bins
        ),
        "full_approved_leader_intro_gamut": (
            kind_present_counts.get("leader_intro", 0)
            == EXPECTED_INTRO_CATEGORY_COUNTS["leader"]
        ),
        "full_approved_rival_intro_gamut": (
            kind_present_counts.get("rival_intro", 0)
            == EXPECTED_INTRO_CATEGORY_COUNTS["rival"]
        ),
        "no_unapproved_or_stale_library_items": not unexpected_library_items,
        "show_intro_and_outro_present_once": (
            kind_present_counts.get("show_intro", 0) == 1
            and kind_present_counts.get("show_outro", 0) == 1
        ),
    }
    report_checks: dict[str, bool] = {}
    if expected_report is not None:
        expected_newest = expected_report.get("newest_timeline") or {}
        report_checks = {
            "report_schema": expected_report.get("schema") == ORGANIZATION_SCHEMA,
            "report_status": expected_report.get("status") == "pass",
            "report_project_uid": (
                str(expected_report.get("project_uid") or "") == _object_uid(project)
            ),
            "report_newest_timeline_name": (
                str(expected_newest.get("name") or "") == newest_timeline_name
            ),
            "report_newest_timeline_uid": (
                bool(newest_uid)
                and str(expected_newest.get("timeline_uid") or "") == newest_uid
            ),
            "report_layout": expected_report.get("layout")
            == {"top_level": list(TOP_LEVEL_BINS), "shared": list(SHARED_BINS)},
            "report_asset_contract_exact": (
                expected_report.get("asset_contract") == context.asset_contract
            ),
        }
        checks.update(report_checks)

    failed_checks = [name for name, passed in checks.items() if passed is not True]
    failed_checks.extend(folder_failures)
    counts = {
        " / ".join(key): len(folder.GetClipList() or [])
        for key, folder in folders.items()
    }
    return {
        "schema": LIVE_AUDIT_SCHEMA,
        "status": "pass" if not failed_checks else "fail",
        "project_uid": _object_uid(project),
        "newest_timeline": {
            "name": newest_timeline_name,
            "timeline_uid": newest_uid,
        },
        "layout": {"top_level": list(TOP_LEVEL_BINS), "shared": list(SHARED_BINS)},
        "asset_contract": context.asset_contract,
        "required_asset_inventory": {
            "expected_count": len(context.required_by_key),
            "present_once_count": sum(1 for found in occurrences.values() if len(found) == 1),
            "missing_paths": missing,
            "duplicate_paths": duplicated,
            "misfiled_paths": wrong_bins,
            "unexpected_library_items": unexpected_library_items,
            "present_kind_counts": kind_present_counts,
        },
        "checks": checks,
        "report_checks": report_checks,
        "failed_checks": failed_checks,
        "misfiled_items": misfiled,
        "counts": counts,
    }


def audit_media_pool_organization(
    project: Any,
    report: dict[str, Any],
    *,
    newest_timeline_name: str,
    project_dir: str | Path,
    nonbattle_bgm_dir: str | Path,
    battle_bgm_dir: str | Path,
    intro_manifest_path: str | Path,
    opening_intro_path: str | Path,
    outro_path: str | Path,
) -> dict[str, Any]:
    return audit_media_pool(
        project,
        newest_timeline_name=newest_timeline_name,
        project_dir=project_dir,
        nonbattle_bgm_dir=nonbattle_bgm_dir,
        battle_bgm_dir=battle_bgm_dir,
        intro_manifest_path=intro_manifest_path,
        opening_intro_path=opening_intro_path,
        outro_path=outro_path,
        expected_report=report,
    )


def organize_media_pool(
    project: Any,
    *,
    newest_timeline_name: str,
    project_dir: str | Path,
    nonbattle_bgm_dir: str | Path,
    battle_bgm_dir: str | Path,
    intro_manifest_path: str | Path,
    opening_intro_path: str | Path,
    outro_path: str | Path,
) -> dict[str, Any]:
    """Converge the live Media Pool to the complete reusable GSC contract."""

    context = _inventory_context(
        project_dir=project_dir,
        nonbattle_bgm_dir=nonbattle_bgm_dir,
        battle_bgm_dir=battle_bgm_dir,
        intro_manifest_path=intro_manifest_path,
        opening_intro_path=opening_intro_path,
        outro_path=outro_path,
    )
    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()

    def get_or_add(parent: Any, name: str) -> Any:
        matches = _named_children(parent, name)
        if len(matches) > 1:
            raise GscGymMediaPoolError(
                f"Canonical Media Pool bin {name!r} is duplicated"
            )
        if matches:
            return matches[0]
        folder = media_pool.AddSubFolder(parent, name)
        if folder is None:
            raise GscGymMediaPoolError(f"Could not create Media Pool bin {name!r}")
        return folder

    folders: dict[tuple[str, ...], Any] = {}
    shared = None
    for name in TOP_LEVEL_BINS:
        folder = get_or_add(root, name)
        folders[(name,)] = folder
        if name == TOP_LEVEL_BINS[4]:
            shared = folder
    assert shared is not None
    for name in SHARED_BINS:
        folders[(TOP_LEVEL_BINS[4], name)] = get_or_add(shared, name)

    initial_rows = _pool_rows(root)
    unexpected_before = _unexpected_library_items(initial_rows, context)
    if unexpected_before:
        raise GscGymMediaPoolError(
            "Media Pool contains unapproved/stale assets inside a configured GSC "
            "library: "
            + ", ".join(row["file_path"] for row in unexpected_before)
        )
    deduplicated = _reconcile_required_asset_duplicates(
        project,
        media_pool,
        context,
        initial_rows,
    )
    if deduplicated:
        initial_rows = _pool_rows(root)
    occurrences: dict[str, list[Any]] = {key: [] for key in context.required_by_key}
    for row in initial_rows:
        if row["file_path_key"] in occurrences:
            occurrences[row["file_path_key"]].append(row["item"])
    duplicates_before = [
        str(context.required_by_key[key].path)
        for key, found in occurrences.items()
        if len(found) > 1
    ]
    if duplicates_before:
        raise GscGymMediaPoolError(
            "Reusable GSC duplicate reconciliation did not converge: "
            + ", ".join(duplicates_before)
        )

    missing_by_bin: dict[tuple[str, ...], list[_RequiredAsset]] = {}
    for key, asset in context.required_by_key.items():
        if not occurrences[key]:
            missing_by_bin.setdefault(asset.bin_path, []).append(asset)
    for values in missing_by_bin.values():
        values.sort(key=lambda asset: (_normalized_media_path(asset.path), asset.identity))

    get_current_folder = getattr(media_pool, "GetCurrentFolder", None)
    set_current_folder = getattr(media_pool, "SetCurrentFolder", None)
    import_media = getattr(media_pool, "ImportMedia", None)
    import_rows: list[dict[str, Any]] = []
    if missing_by_bin:
        if not callable(get_current_folder) or not callable(set_current_folder):
            raise GscGymMediaPoolError(
                "Resolve does not expose current-folder APIs for deterministic imports"
            )
        if not callable(import_media):
            raise GscGymMediaPoolError(
                "Resolve does not expose ImportMedia for deterministic reusable assets"
            )
        previous_folder = get_current_folder()
        if previous_folder is None:
            raise GscGymMediaPoolError(
                "Resolve did not expose the selected Media Pool folder before import"
            )
        import_error: Exception | None = None
        try:
            folder_order = {
                (TOP_LEVEL_BINS[4], name): index
                for index, name in enumerate(SHARED_BINS)
            }
            for bin_path in sorted(missing_by_bin, key=lambda key: folder_order[key]):
                assets = missing_by_bin[bin_path]
                if not set_current_folder(folders[bin_path]):
                    raise GscGymMediaPoolError(
                        f"Could not select canonical import bin {' / '.join(bin_path)}"
                    )
                paths = [str(asset.path) for asset in assets]
                imported = import_media(paths)
                try:
                    api_returned_count = len(list(imported or []))
                except TypeError:
                    api_returned_count = 0
                import_rows.append(
                    {
                        "bin": " / ".join(bin_path),
                        "call_count": 1,
                        "requested_count": len(paths),
                        "api_returned_count": api_returned_count,
                        "paths": paths,
                    }
                )
        except Exception as exc:
            import_error = exc
        finally:
            if not set_current_folder(previous_folder):
                raise GscGymMediaPoolError(
                    "Could not restore the previously selected Media Pool folder"
                )
        if import_error is not None:
            if isinstance(import_error, GscGymMediaPoolError):
                raise import_error
            raise GscGymMediaPoolError(
                "Resolve failed while importing reusable GSC assets"
            ) from import_error

    verified_rows = _pool_rows(root)
    verified_occurrences: dict[str, list[Any]] = {
        key: [] for key in context.required_by_key
    }
    for row in verified_rows:
        if row["file_path_key"] in verified_occurrences:
            verified_occurrences[row["file_path_key"]].append(row["item"])
    missing_after = [
        str(context.required_by_key[key].path)
        for key, found in verified_occurrences.items()
        if not found
    ]
    duplicate_after = [
        str(context.required_by_key[key].path)
        for key, found in verified_occurrences.items()
        if len(found) > 1
    ]
    if missing_after or duplicate_after:
        details: list[str] = []
        if missing_after:
            details.append("missing=" + ", ".join(missing_after))
        if duplicate_after:
            details.append("duplicated=" + ", ".join(duplicate_after))
        raise GscGymMediaPoolError(
            "Reusable GSC asset import did not converge to one Media Pool item per "
            "approved disk path: "
            + "; ".join(details)
        )

    rows = _pool_rows(root)
    grouped: dict[tuple[str, ...], list[Any]] = {key: [] for key in folders}
    newest_matches = 0
    for row in rows:
        target = classify_item(
            name=row["name"],
            item_type=row["item_type"],
            file_path=row["file_path"],
            newest_timeline_name=newest_timeline_name,
            context=context,
        )
        if target == (TOP_LEVEL_BINS[0],):
            newest_matches += 1
        if row["folder_path"] != target:
            grouped[target].append(row["item"])
    if newest_matches != 1:
        raise GscGymMediaPoolError(
            "Expected exactly one newest timeline Media Pool item named "
            f"{newest_timeline_name!r}; found {newest_matches}"
        )

    moved: dict[str, int] = {}
    for key, items in grouped.items():
        if not items:
            continue
        if not media_pool.MoveClips(items, folders[key]):
            raise GscGymMediaPoolError(
                f"Could not move {len(items)} item(s) into {' / '.join(key)}"
            )
        moved[" / ".join(key)] = len(items)

    removed_empty_folders: list[str] = []
    unexpected_folders = _unexpected_folder_rows(root)
    if unexpected_folders:
        set_current_folder = getattr(media_pool, "SetCurrentFolder", None)
        if callable(set_current_folder) and not set_current_folder(root):
            raise GscGymMediaPoolError(
                "Could not select Media Pool root before canonical folder cleanup"
            )
        delete_folders = getattr(media_pool, "DeleteFolders", None)
        if not callable(delete_folders):
            raise GscGymMediaPoolError(
                "Resolve does not expose DeleteFolders for canonical folder cleanup"
            )
        for path, folder in unexpected_folders:
            if _collect_items(folder):
                raise GscGymMediaPoolError(
                    "Refusing to remove non-empty noncanonical Media Pool folder: "
                    + " / ".join(path)
                )
            if not delete_folders([folder]):
                raise GscGymMediaPoolError(
                    "Could not remove empty noncanonical Media Pool folder: "
                    + " / ".join(path)
                )
            removed_empty_folders.append(" / ".join(path))

    newest_timelines = _timeline_matches(project, newest_timeline_name)
    newest_uid = (
        _object_uid(newest_timelines[0]) if len(newest_timelines) == 1 else ""
    )
    if len(newest_timelines) != 1 or not newest_uid:
        raise GscGymMediaPoolError(
            "Expected exactly one UID-bearing newest timeline named "
            f"{newest_timeline_name!r}"
        )
    report = {
        "schema": ORGANIZATION_SCHEMA,
        "status": "pass",
        "project_uid": _object_uid(project),
        "newest_timeline": {
            "name": newest_timeline_name,
            "timeline_uid": newest_uid,
        },
        "layout": {"top_level": list(TOP_LEVEL_BINS), "shared": list(SHARED_BINS)},
        "asset_contract": context.asset_contract,
        "imports": {
            "call_count": len(import_rows),
            "requested_count": sum(row["requested_count"] for row in import_rows),
            "by_bin": import_rows,
        },
        "moved": moved,
        "deduplication": {
            "policy": (
                "retain_sole_globally_timeline_referenced_occurrence_else_existing_"
                "canonical;delete_only_stable_uid_globally_unreferenced_occurrences"
            ),
            "path_count": len(deduplicated),
            "deleted_item_count": sum(
                len(row["deleted_unreferenced_uids"]) for row in deduplicated
            ),
            "paths": deduplicated,
        },
        "removed_empty_folders": removed_empty_folders,
        "timeline_creation_count": 0,
    }
    live_audit = audit_media_pool_organization(
        project,
        report,
        newest_timeline_name=newest_timeline_name,
        project_dir=project_dir,
        nonbattle_bgm_dir=nonbattle_bgm_dir,
        battle_bgm_dir=battle_bgm_dir,
        intro_manifest_path=intro_manifest_path,
        opening_intro_path=opening_intro_path,
        outro_path=outro_path,
    )
    if live_audit["status"] != "pass":
        raise GscGymMediaPoolError(
            "Canonical GSC Media Pool audit failed after organization: "
            + ", ".join(live_audit["failed_checks"])
        )
    report["counts"] = live_audit["counts"]
    report["live_audit"] = live_audit
    return report


__all__ = [
    "EXPECTED_INTRO_CATEGORY_COUNTS",
    "EXPECTED_INTRO_VARIANT_COUNT",
    "GscGymMediaPoolError",
    "LIVE_AUDIT_SCHEMA",
    "ORGANIZATION_SCHEMA",
    "SHARED_BINS",
    "TOP_LEVEL_BINS",
    "audit_media_pool",
    "audit_media_pool_organization",
    "classify_item",
    "organize_media_pool",
]
