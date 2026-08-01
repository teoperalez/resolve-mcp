"""Receipt-bound one-import Resolve dry run for deterministic GSC timelines."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .gsc_gym_bins import (
    EXPECTED_INTRO_CATEGORY_COUNTS,
    GscGymMediaPoolError,
    ORGANIZATION_SCHEMA as MEDIA_POOL_ORGANIZATION_SCHEMA,
    audit_media_pool_organization,
    organize_media_pool,
)
from .gsc_gym_deterministic import FAIRLIGHT_PRESET_NAME, FAIRLIGHT_PRESET_TYPE
from .gsc_gym_resolve_audio import (
    AUDIO_TRACK_NAMES,
    GscGymResolveAudioError,
    repair_receipt_bound_audio,
)


WIDTH = 3840
HEIGHT = 2160
FPS = 60
TIMELINE_START_FRAME = 216_000
CAROUSEL_CROP_BOTTOM = 530.0
RECEIPT_SCHEMA = "gsc_gym_resolve_dry_run_receipt_v1"
LIVE_AUDIT_SCHEMA = "gsc_gym_resolve_live_audit_v1"
MEDIA_POOL_INPUT_SCHEMA = "gsc_gym_media_pool_bin_inputs_v1"
MEDIA_POOL_BINDING_SCHEMA = "gsc_gym_media_pool_bins_receipt_binding_v1"
FAIRLIGHT_REPORT_SCHEMA = "gsc_gym_fairlight_report_v1"
FAIRLIGHT_BINDING_SCHEMA = "gsc_gym_fairlight_receipt_binding_v1"
FAIRLIGHT_FILE_EVIDENCE_SCHEMA = "gsc_gym_fairlight_preset_file_evidence_v1"


class GscGymResolveError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _media_pool_report_path(receipt_path: Path) -> Path:
    suffix = "__resolve-dry-run.receipt.json"
    if receipt_path.name.endswith(suffix):
        stem = receipt_path.name[: -len(suffix)]
        return receipt_path.with_name(f"{stem}__media-pool-bins.report.json")
    return receipt_path.with_name(f"{receipt_path.stem}.media-pool-bins.report.json")


def _fairlight_report_path(receipt_path: Path) -> Path:
    suffix = "__resolve-dry-run.receipt.json"
    if receipt_path.name.endswith(suffix):
        stem = receipt_path.name[: -len(suffix)]
        return receipt_path.with_name(f"{stem}__fairlight.report.json")
    return receipt_path.with_name(f"{receipt_path.stem}.fairlight.report.json")


def _fairlight_preset_paths() -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[3]
    repo_path = (
        repo_root
        / "assets"
        / "fairlight-presets"
        / FAIRLIGHT_PRESET_TYPE
        / f"{FAIRLIGHT_PRESET_NAME}.dat"
    ).resolve()
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    host_path = (
        appdata
        / "Blackmagic Design"
        / "DaVinci Resolve"
        / "Preferences"
        / "Fairlight"
        / "Presets"
        / FAIRLIGHT_PRESET_TYPE
        / f"{FAIRLIGHT_PRESET_NAME}.dat"
    ).resolve()
    return repo_path, host_path


def _file_evidence(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "size": int(stat.st_size),
        "sha256": _sha256(resolved),
    }


def _install_exact_fairlight_preset() -> tuple[str, dict[str, Any]]:
    repo_path, host_path = _fairlight_preset_paths()
    if not repo_path.is_file():
        raise GscGymResolveError(
            f"Repository Fairlight preset is missing: {repo_path}"
        )
    repo_evidence = _file_evidence(repo_path)
    host_path.parent.mkdir(parents=True, exist_ok=True)
    install_status = "already-installed"
    if not host_path.is_file() or _sha256(host_path) != repo_evidence["sha256"]:
        install_status = "overwritten" if host_path.exists() else "installed"
        temporary = host_path.with_name(f".{host_path.name}.tmp-{os.getpid()}")
        temporary.unlink(missing_ok=True)
        try:
            shutil.copy2(repo_path, temporary)
            if _sha256(temporary) != repo_evidence["sha256"]:
                raise GscGymResolveError(
                    "Copied Fairlight preset bytes do not match the repository source."
                )
            os.replace(temporary, host_path)
        finally:
            temporary.unlink(missing_ok=True)
    host_evidence = _file_evidence(host_path)
    exact_match = repo_evidence["sha256"] == host_evidence["sha256"]
    if not exact_match:
        raise GscGymResolveError(
            "Installed Resolve Fairlight preset bytes do not match the repository contract."
        )
    return install_status, {
        "schema": FAIRLIGHT_FILE_EVIDENCE_SCHEMA,
        "repo_path": str(repo_path),
        "host_path": str(host_path),
        "repo_sha256": repo_evidence["sha256"],
        "host_sha256": host_evidence["sha256"],
        "exact_match": True,
        "repo_file": repo_evidence,
        "host_file": host_evidence,
    }


def _media_pool_inputs(manifest: dict[str, Any]) -> dict[str, Any]:
    raw = manifest.get("media_pool_bins")
    if not isinstance(raw, dict):
        raise GscGymResolveError(
            "GSC manifest lacks the deterministic reusable Media Pool input contract."
        )
    if raw.get("schema") != MEDIA_POOL_INPUT_SCHEMA:
        raise GscGymResolveError(
            "GSC manifest has an unsupported reusable Media Pool input schema."
        )
    if raw.get("full_reusable_library") is not True:
        raise GscGymResolveError(
            "GSC Media Pool contract must require the full reusable asset library."
        )
    if type(raw.get("timeline_creation_count")) is not int or raw.get(
        "timeline_creation_count"
    ) != 0:
        raise GscGymResolveError(
            "GSC Media Pool contract may not create a utility or successor timeline."
        )
    required_paths = (
        "project_dir",
        "nonbattle_bgm_dir",
        "battle_bgm_dir",
        "intro_manifest_path",
        "opening_intro_path",
        "outro_path",
    )
    missing = [
        key
        for key in required_paths
        if not isinstance(raw.get(key), str) or not str(raw.get(key)).strip()
    ]
    if missing:
        raise GscGymResolveError(
            "GSC Media Pool input contract lacks required path(s): "
            + ", ".join(missing)
        )
    try:
        source_parent = Path(str(manifest["source_asset"]["path"])).resolve().parent
        opening_path = str(manifest["opening"]["asset"]["path"])
        outro_path = str(manifest["outro"]["asset"]["path"])
        reservations = manifest["audio_reservations"]
        battle_root = str(reservations["battle_library_root"])
        nonbattle_root = Path(str(reservations["dual_screen_lovelife"])).resolve().parent
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise GscGymResolveError(
            "GSC manifest cannot cross-bind its Media Pool paths to editorial assets."
        ) from exc
    path_checks = {
        "project_dir": _normalized_path(str(source_parent)),
        "opening_intro_path": _normalized_path(opening_path),
        "outro_path": _normalized_path(outro_path),
        "battle_bgm_dir": _normalized_path(battle_root),
        "nonbattle_bgm_dir": _normalized_path(str(nonbattle_root)),
    }
    mismatched = [
        key
        for key, expected in path_checks.items()
        if _normalized_path(str(raw[key])) != expected
    ]
    if mismatched:
        raise GscGymResolveError(
            "GSC Media Pool paths are not cross-bound to the exact source, show "
            "assets, or audio reservations: "
            + ", ".join(mismatched)
        )
    return raw


def _media_pool_kwargs(
    inputs: dict[str, Any], *, timeline_name: str
) -> dict[str, Any]:
    return {
        "newest_timeline_name": timeline_name,
        "project_dir": inputs["project_dir"],
        "nonbattle_bgm_dir": inputs["nonbattle_bgm_dir"],
        "battle_bgm_dir": inputs["battle_bgm_dir"],
        "intro_manifest_path": inputs["intro_manifest_path"],
        "opening_intro_path": inputs["opening_intro_path"],
        "outro_path": inputs["outro_path"],
    }


def _media_pool_binding(
    *,
    report_path: Path,
    report: dict[str, Any],
    project_uid: str,
    timeline_uid: str,
    mode: str,
) -> dict[str, Any]:
    asset_contract = report.get("asset_contract") or {}
    intro_library = asset_contract.get("intro_library") or {}
    category_counts = intro_library.get("category_counts") or {}
    bgm_libraries = asset_contract.get("bgm_libraries") or {}
    return {
        "schema": MEDIA_POOL_BINDING_SCHEMA,
        "status": "pass",
        "mode": mode,
        "report_path": str(report_path),
        "report_sha256": _sha256(report_path),
        "report_schema": str(report.get("schema") or ""),
        "project_uid": project_uid,
        "timeline_uid": timeline_uid,
        "required_reusable_asset_count": int(
            asset_contract.get("required_asset_count") or 0
        ),
        "bgm_asset_count": int(bgm_libraries.get("combined_file_count") or 0),
        "leader_intro_count": int(category_counts.get("leader") or 0),
        "rival_intro_count": int(category_counts.get("rival") or 0),
        "show_asset_count": len(list(asset_contract.get("show_assets") or [])),
        "timeline_creation_count": int(report.get("timeline_creation_count") or 0),
    }


def _validate_media_pool_report_identity(
    report: dict[str, Any],
    *,
    project_uid: str,
    timeline_name: str,
    timeline_uid: str,
) -> None:
    newest = report.get("newest_timeline") or {}
    asset_contract = report.get("asset_contract") or {}
    intro_library = asset_contract.get("intro_library") or {}
    intro_counts = intro_library.get("category_counts") or {}
    bgm_libraries = asset_contract.get("bgm_libraries") or {}
    bgm_count = bgm_libraries.get("combined_file_count")
    show_assets = asset_contract.get("show_assets") or []
    required_count = asset_contract.get("required_asset_count")
    expected_required_count = (
        int(bgm_count or 0)
        + sum(EXPECTED_INTRO_CATEGORY_COUNTS.values())
        + 2
    )
    valid = (
        report.get("schema") == MEDIA_POOL_ORGANIZATION_SCHEMA
        and report.get("status") == "pass"
        and str(report.get("project_uid") or "") == project_uid
        and str(newest.get("name") or "") == timeline_name
        and str(newest.get("timeline_uid") or "") == timeline_uid
        and type(report.get("timeline_creation_count")) is int
        and report.get("timeline_creation_count") == 0
        and asset_contract.get("schema") == "gsc_gym_reusable_asset_contract_v1"
        and intro_counts == EXPECTED_INTRO_CATEGORY_COUNTS
        and type(bgm_count) is int
        and bgm_count > 0
        and isinstance(show_assets, list)
        and len(show_assets) == 2
        and type(required_count) is int
        and required_count == expected_required_count
        and (report.get("live_audit") or {}).get("status") == "pass"
    )
    if not valid:
        raise GscGymResolveError(
            "Reusable Media Pool report is not bound to the exact project/timeline "
            "UIDs or attempts to create another timeline."
        )


def _uid(value: Any, label: str) -> str:
    if value is None or not hasattr(value, "GetUniqueId"):
        raise GscGymResolveError(f"Resolve {label} does not expose a stable unique ID.")
    rendered = str(value.GetUniqueId() or "").strip()
    if not rendered:
        raise GscGymResolveError(f"Resolve {label} returned an empty unique ID.")
    return rendered


def timeline_inventory(project: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = int(project.GetTimelineCount() or 0)
    for index in range(1, count + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline is None:
            raise GscGymResolveError(f"Resolve returned no timeline at inventory index {index}.")
        rows.append(
            {
                "index": index,
                "name": str(timeline.GetName() or ""),
                "uid": _uid(timeline, f"timeline at index {index}"),
            }
        )
    if len({row["uid"] for row in rows}) != len(rows):
        raise GscGymResolveError("Resolve timeline inventory contains duplicate UIDs.")
    return rows


def _timeline_by_uid(project: Any, uid: str) -> Any | None:
    for index in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline is not None and _uid(timeline, f"timeline at index {index}") == uid:
            return timeline
    return None


def _fairlight_binding(
    *,
    report_path: Path,
    report: dict[str, Any],
    project_uid: str,
    timeline_uid: str,
    mode: str,
    current_run_apply_count: int,
) -> dict[str, Any]:
    return {
        "schema": FAIRLIGHT_BINDING_SCHEMA,
        "status": "pass",
        "mode": mode,
        "report_path": str(report_path),
        "report_sha256": _sha256(report_path),
        "report_schema": str(report.get("schema") or ""),
        "project_uid": project_uid,
        "timeline_uid": timeline_uid,
        "preset": FAIRLIGHT_PRESET_NAME,
        "preset_type": FAIRLIGHT_PRESET_TYPE,
        "apply_result": report.get("apply_result") is True,
        "project_saved": report.get("project_saved") is True,
        "lifetime_apply_count": int(report.get("apply_count") or 0),
        "current_run_apply_count": int(current_run_apply_count),
    }


def _validate_fairlight_report(
    report: dict[str, Any],
    *,
    project: Any,
    timeline_name: str,
    timeline_uid: str,
    require_saved: bool,
) -> None:
    project_uid = _uid(project, "Fairlight project")
    preset_files = report.get("preset_file_evidence") or {}
    repo_path, host_path = _fairlight_preset_paths()
    try:
        repo_current = _file_evidence(repo_path)
        host_current = _file_evidence(host_path)
    except OSError as exc:
        raise GscGymResolveError(
            "Receipt-bound Fairlight preset evidence is no longer readable."
        ) from exc
    expected_status = "pass" if require_saved else "applied_pending_save"
    checks = {
        "schema": report.get("schema") == FAIRLIGHT_REPORT_SCHEMA,
        "status": report.get("status") == expected_status,
        "project_name": report.get("project_name") == str(project.GetName() or ""),
        "project_uid": report.get("project_uid") == project_uid,
        "timeline_name": report.get("timeline_name") == timeline_name,
        "timeline_uid": report.get("timeline_uid") == timeline_uid,
        "preset": report.get("preset") == FAIRLIGHT_PRESET_NAME,
        "preset_type": report.get("preset_type") == FAIRLIGHT_PRESET_TYPE,
        "api": report.get("apply_api")
        == "Project.ApplyFairlightPresetToCurrentTimeline",
        "apply_result": report.get("apply_result") is True,
        "apply_count": type(report.get("apply_count")) is int
        and int(report.get("apply_count") or 0) == 1,
        "save_result": report.get("project_saved") is require_saved,
        "inventory_stable": report.get("timeline_inventory_before")
        == report.get("timeline_inventory_after")
        == timeline_inventory(project),
        "post_apply_current_uid": report.get("post_apply_current_timeline_uid")
        == timeline_uid,
        "post_apply_live_audit": (report.get("post_apply_live_audit") or {}).get(
            "status"
        )
        == "pass",
        "preset_file_schema": preset_files.get("schema")
        == FAIRLIGHT_FILE_EVIDENCE_SCHEMA,
        "repo_path": Path(str(preset_files.get("repo_path") or "")).resolve()
        == repo_path,
        "host_path": Path(str(preset_files.get("host_path") or "")).resolve()
        == host_path,
        "repo_file_current": preset_files.get("repo_file") == repo_current,
        "host_file_current": preset_files.get("host_file") == host_current,
        "repo_host_sha_exact": (
            preset_files.get("repo_sha256")
            == preset_files.get("host_sha256")
            == repo_current["sha256"]
            == host_current["sha256"]
            and preset_files.get("exact_match") is True
        ),
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    if failed:
        raise GscGymResolveError(
            "Fairlight evidence does not prove the exact preset on the exact "
            "receipt-bound saved timeline: "
            + ", ".join(failed)
        )


def _load_fairlight_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GscGymResolveError(
            f"Receipt-bound Fairlight report is unreadable: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise GscGymResolveError("Receipt-bound Fairlight report is not a JSON object.")
    return payload


def _complete_pending_fairlight_save(
    *,
    manager: Any,
    project: Any,
    timeline: Any,
    manifest: dict[str, Any],
    report_path: Path,
    report: dict[str, Any],
    deadline_check: Any | None,
) -> dict[str, Any]:
    timeline_uid = _uid(timeline, "receipt-bound Fairlight timeline")
    timeline_name = str(timeline.GetName() or "")
    _validate_fairlight_report(
        report,
        project=project,
        timeline_name=timeline_name,
        timeline_uid=timeline_uid,
        require_saved=False,
    )
    if project.SetCurrentTimeline(timeline) is not True:
        raise GscGymResolveError(
            "Resolve could not reselect the receipt-bound timeline for Fairlight save recovery."
        )
    post_apply_audit = audit_live_timeline(timeline, manifest)
    if post_apply_audit.get("status") != "pass":
        raise GscGymResolveError(
            "Fairlight pending-save recovery failed the final live audit: "
            + ", ".join(post_apply_audit.get("failed_checks") or [])
        )
    if deadline_check:
        deadline_check("saving the already-applied receipt-bound Fairlight preset")
    if manager.SaveProject() is not True:
        raise GscGymResolveError(
            "Resolve could not save the already-applied Fairlight preset."
        )
    report.update(
        {
            "status": "pass",
            "project_saved": True,
            "save_result": True,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "post_apply_live_audit": post_apply_audit,
        }
    )
    _atomic_json(report_path, report)
    _validate_fairlight_report(
        report,
        project=project,
        timeline_name=timeline_name,
        timeline_uid=timeline_uid,
        require_saved=True,
    )
    return report


def _apply_final_fairlight_preset(
    *,
    manager: Any,
    project: Any,
    timeline: Any,
    manifest: dict[str, Any],
    receipt: dict[str, Any],
    receipt_path: Path,
    report_path: Path,
    deadline_check: Any | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    project_uid = _uid(project, "Fairlight project")
    timeline_uid = _uid(timeline, "receipt-bound Fairlight timeline")
    timeline_name = str(timeline.GetName() or "")
    inventory_before = timeline_inventory(project)
    if project.SetCurrentTimeline(timeline) is not True:
        raise GscGymResolveError(
            "Resolve could not select the exact receipt-bound timeline for Fairlight."
        )
    install_status, preset_file_evidence = _install_exact_fairlight_preset()
    receipt.update(
        {
            "status": "fairlight_pending_apply",
            "fairlight_preset": {
                "schema": FAIRLIGHT_BINDING_SCHEMA,
                "status": "pending_apply",
                "report_path": str(report_path),
                "project_uid": project_uid,
                "timeline_uid": timeline_uid,
                "preset": FAIRLIGHT_PRESET_NAME,
                "preset_type": FAIRLIGHT_PRESET_TYPE,
            },
        }
    )
    _atomic_json(receipt_path, receipt)
    if deadline_check:
        deadline_check("applying the final receipt-bound Fairlight preset")
    try:
        apply_result = project.ApplyFairlightPresetToCurrentTimeline(
            FAIRLIGHT_PRESET_NAME
        )
    except Exception as exc:
        receipt.update(
            {
                "status": "failed_fairlight_apply_exception_ambiguous",
                "fairlight_error": str(exc),
            }
        )
        _atomic_json(receipt_path, receipt)
        raise GscGymResolveError(
            f"Resolve Fairlight preset application raised: {exc}"
        ) from exc
    if apply_result is not True:
        receipt.update(
            {
                "status": "failed_fairlight_apply",
                "fairlight_error": f"Apply returned {apply_result!r} instead of True.",
            }
        )
        _atomic_json(receipt_path, receipt)
        raise GscGymResolveError(
            f"Resolve Fairlight preset application returned {apply_result!r}."
        )

    # Fairlight is the final Resolve mutation. Persist it immediately; every
    # operation below this save is receipt/report writing or read-only audit.
    if deadline_check:
        deadline_check("saving immediately after the final Fairlight mutation")
    save_error = ""
    try:
        save_result = manager.SaveProject()
    except Exception as exc:
        save_result = False
        save_error = str(exc)
    if save_result is True:
        receipt.update(
            {
                "status": "fairlight_saved_pending_read_only_validation",
                "project_saved": True,
                "fairlight_preset": {
                    "schema": FAIRLIGHT_BINDING_SCHEMA,
                    "status": "saved_pending_read_only_validation",
                    "report_path": str(report_path),
                    "project_uid": project_uid,
                    "timeline_uid": timeline_uid,
                    "preset": FAIRLIGHT_PRESET_NAME,
                    "preset_type": FAIRLIGHT_PRESET_TYPE,
                    "apply_result": True,
                    "project_saved": True,
                },
            }
        )
        _atomic_json(receipt_path, receipt)

    inventory_after = timeline_inventory(project)
    if inventory_after != inventory_before:
        raise GscGymResolveError(
            "Fairlight application changed the receipt-bound timeline inventory."
        )
    current = project.GetCurrentTimeline()
    current_uid = _uid(current, "post-Fairlight current timeline")
    if current_uid != timeline_uid:
        raise GscGymResolveError(
            "Fairlight application displaced the exact receipt-bound current timeline UID."
        )
    post_apply_audit = audit_live_timeline(timeline, manifest)
    if post_apply_audit.get("status") != "pass":
        raise GscGymResolveError(
            "Final post-Fairlight live audit failed: "
            + ", ".join(post_apply_audit.get("failed_checks") or [])
        )
    report = {
        "schema": FAIRLIGHT_REPORT_SCHEMA,
        "status": "pass" if save_result is True else "applied_pending_save",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_name": str(project.GetName() or ""),
        "project_uid": project_uid,
        "timeline_name": timeline_name,
        "timeline_uid": timeline_uid,
        "preset": FAIRLIGHT_PRESET_NAME,
        "preset_type": FAIRLIGHT_PRESET_TYPE,
        "apply_api": "Project.ApplyFairlightPresetToCurrentTimeline",
        "apply_result": True,
        "apply_count": 1,
        "install_status": install_status,
        "preset_file_evidence": preset_file_evidence,
        "timeline_inventory_before": inventory_before,
        "timeline_inventory_after": inventory_after,
        "post_apply_current_timeline_uid": current_uid,
        "post_apply_live_audit": post_apply_audit,
        "project_saved": save_result is True,
        "save_result": save_result is True,
    }
    if save_result is True:
        report["saved_at"] = datetime.now(timezone.utc).isoformat()
    if save_error:
        report["save_error"] = save_error
    _atomic_json(report_path, report)
    if save_result is not True:
        receipt.update(
            {
                "status": "fairlight_applied_pending_save",
                "fairlight_error": (
                    "Resolve could not save the already-applied Fairlight preset."
                    + (f" {save_error}" if save_error else "")
                ),
                "fairlight_preset": {
                    "schema": FAIRLIGHT_BINDING_SCHEMA,
                    "status": "applied_pending_save",
                    "report_path": str(report_path),
                    "report_sha256": _sha256(report_path),
                    "project_uid": project_uid,
                    "timeline_uid": timeline_uid,
                    "preset": FAIRLIGHT_PRESET_NAME,
                    "preset_type": FAIRLIGHT_PRESET_TYPE,
                    "apply_result": True,
                },
            }
        )
        _atomic_json(receipt_path, receipt)
        raise GscGymResolveError(
            "Resolve could not save the already-applied Fairlight preset."
        )
    _validate_fairlight_report(
        report,
        project=project,
        timeline_name=timeline_name,
        timeline_uid=timeline_uid,
        require_saved=True,
    )
    binding = _fairlight_binding(
        report_path=report_path,
        report=report,
        project_uid=project_uid,
        timeline_uid=timeline_uid,
        mode="applied_final_preset_and_saved",
        current_run_apply_count=1,
    )
    return report, binding


def _ensure_final_fairlight_preset(
    *,
    manager: Any,
    project: Any,
    timeline: Any,
    manifest: dict[str, Any],
    receipt: dict[str, Any],
    receipt_path: Path,
    report_path: Path,
    deadline_check: Any | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    project_uid = _uid(project, "Fairlight project")
    timeline_uid = _uid(timeline, "receipt-bound Fairlight timeline")
    timeline_name = str(timeline.GetName() or "")
    existing_binding = receipt.get("fairlight_preset")
    if isinstance(existing_binding, dict) and existing_binding.get("status") == "pass":
        expected = (
            existing_binding.get("schema") == FAIRLIGHT_BINDING_SCHEMA
            and existing_binding.get("project_uid") == project_uid
            and existing_binding.get("timeline_uid") == timeline_uid
            and Path(str(existing_binding.get("report_path") or "")).resolve()
            == report_path
            and report_path.is_file()
            and str(existing_binding.get("report_sha256") or "").upper()
            == _sha256(report_path)
        )
        if not expected:
            raise GscGymResolveError(
                "Existing Fairlight receipt binding is stale or targets a different UID."
            )
        report = _load_fairlight_report(report_path)
        _validate_fairlight_report(
            report,
            project=project,
            timeline_name=timeline_name,
            timeline_uid=timeline_uid,
            require_saved=True,
        )
        return report, _fairlight_binding(
            report_path=report_path,
            report=report,
            project_uid=project_uid,
            timeline_uid=timeline_uid,
            mode="reused_exact_saved_report_without_reapply",
            current_run_apply_count=0,
        )
    if report_path.is_file():
        report = _load_fairlight_report(report_path)
        if report.get("status") == "applied_pending_save":
            report = _complete_pending_fairlight_save(
                manager=manager,
                project=project,
                timeline=timeline,
                manifest=manifest,
                report_path=report_path,
                report=report,
                deadline_check=deadline_check,
            )
            mode = "saved_existing_applied_report_without_reapply"
        else:
            _validate_fairlight_report(
                report,
                project=project,
                timeline_name=timeline_name,
                timeline_uid=timeline_uid,
                require_saved=True,
            )
            mode = "adopted_exact_interrupted_saved_report_without_reapply"
        return report, _fairlight_binding(
            report_path=report_path,
            report=report,
            project_uid=project_uid,
            timeline_uid=timeline_uid,
            mode=mode,
            current_run_apply_count=0,
        )
    if isinstance(existing_binding, dict):
        raise GscGymResolveError(
            "Ambiguous incomplete Fairlight journal has no report; refusing to reapply."
        )
    return _apply_final_fairlight_preset(
        manager=manager,
        project=project,
        timeline=timeline,
        manifest=manifest,
        receipt=receipt,
        receipt_path=receipt_path,
        report_path=report_path,
        deadline_check=deadline_check,
    )


def resolve_receipt_deployment_ready(receipt: dict[str, Any]) -> bool:
    fairlight = receipt.get("fairlight_preset")
    structural = bool(
        receipt.get("schema") == RECEIPT_SCHEMA
        and receipt.get("status") == "pass"
        and receipt.get("project_saved") is True
        and isinstance(receipt.get("project_uid"), str)
        and bool(str(receipt.get("project_uid") or "").strip())
        and isinstance(receipt.get("timeline_uid"), str)
        and bool(str(receipt.get("timeline_uid") or "").strip())
        and isinstance(fairlight, dict)
        and fairlight.get("schema") == FAIRLIGHT_BINDING_SCHEMA
        and fairlight.get("status") == "pass"
        and fairlight.get("project_uid") == receipt.get("project_uid")
        and fairlight.get("timeline_uid") == receipt.get("timeline_uid")
        and fairlight.get("preset") == FAIRLIGHT_PRESET_NAME
        and fairlight.get("preset_type") == FAIRLIGHT_PRESET_TYPE
        and fairlight.get("apply_result") is True
        and fairlight.get("project_saved") is True
        and fairlight.get("report_schema") == FAIRLIGHT_REPORT_SCHEMA
        and type(fairlight.get("lifetime_apply_count")) is int
        and fairlight.get("lifetime_apply_count") == 1
        and type(fairlight.get("current_run_apply_count")) is int
    )
    if not structural:
        return False
    report_path = Path(str(fairlight.get("report_path") or ""))
    report_sha = str(fairlight.get("report_sha256") or "").upper()
    try:
        return bool(
            report_path.is_absolute()
            and report_path.is_file()
            and len(report_sha) == 64
            and _sha256(report_path) == report_sha
        )
    except OSError:
        return False


def _normalized_path(value: str) -> str:
    return str(Path(value)).replace("\\", "/").casefold()


def _item_path(item: Any) -> str:
    media = item.GetMediaPoolItem() if hasattr(item, "GetMediaPoolItem") else None
    if media is None:
        return ""
    try:
        return str(media.GetClipProperty("File Path") or "")
    except TypeError:
        properties = media.GetClipProperty() or {}
        return str(properties.get("File Path") or "") if isinstance(properties, dict) else ""


def _expected_tracks(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    opening = manifest["opening"]
    carousel = manifest["carousel"]
    outro = manifest["outro"]
    source_path = manifest["source_asset"]["path"]
    dialogue_path = manifest["a1"]["dialogue_asset"]["path"]
    outro_path = outro["asset"]["path"]
    rows: dict[str, list[dict[str, Any]]] = {
        "V1": [
            {
                "kind": "opening",
                "record_range": opening["record_range"],
                "path": opening["asset"]["path"],
            }
        ],
        "V2": [],
        "A1": [],
        "A2": [],
        "A3": [
            {
                "kind": "outro-a3",
                "record_range": outro["record_range"],
                "path": outro_path,
            }
        ],
    }
    rows["V1"].extend(
        {
            "kind": "body-v1",
            "record_range": item["record_range"],
            "path": source_path,
        }
        for item in manifest["body_v1"]
    )
    rows["V1"].append(
        {
            "kind": "carousel-v1",
            "record_range": carousel["v1_record_range"],
            "path": source_path,
        }
    )
    rows["V1"].append(
        {
            "kind": "outro-v1",
            "record_range": outro["record_range"],
            "path": outro_path,
        }
    )
    rows["V2"].extend(
        {
            "kind": "battle-intro-v2",
            "record_range": item["intro_range"],
            "path": item["intro_asset"]["path"],
        }
        for item in manifest["battles"]
        if item.get("intro_range") is not None
    )
    rows["V2"].extend(
        {
            "kind": "carousel-v2",
            "record_range": item["record_range"],
            "path": source_path,
            "crop_bottom": CAROUSEL_CROP_BOTTOM,
        }
        for item in carousel["v2_slices"]
    )
    rows["A1"].extend(
        {
            "kind": "dialogue-a1",
            "record_range": item["record_range"],
            "path": dialogue_path,
        }
        for item in manifest["a1"]["placed"]
    )
    rows["A2"].extend(
        {
            "kind": f"{item['role']}-a2",
            "record_range": item["record_range"],
            "path": item["asset"]["path"],
        }
        for item in manifest["a2"]["segments"]
    )
    for values in rows.values():
        values.sort(key=lambda item: (item["record_range"][0], item["record_range"][1], item["kind"]))
    return rows


def _live_track(timeline: Any, track_type: str, index: int, timeline_start: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in timeline.GetItemListInTrack(track_type, index) or []:
        start = int(item.GetStart()) - timeline_start
        duration = int(item.GetDuration())
        enabled = True
        if hasattr(item, "GetClipEnabled"):
            enabled = bool(item.GetClipEnabled())
        result.append(
            {
                "item": item,
                "name": str(item.GetName() or ""),
                "record_range": [start, start + duration],
                "path": _item_path(item),
                "enabled": enabled,
            }
        )
    result.sort(key=lambda row: (row["record_range"][0], row["record_range"][1], row["name"]))
    return result


def _setting_int(timeline: Any, key: str) -> int:
    try:
        return int(round(float(str(timeline.GetSetting(key) or "0"))))
    except (TypeError, ValueError):
        return 0


def audit_live_timeline(timeline: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    expected_name = str(manifest["timeline"]["name"])
    timeline_start = int(timeline.GetStartFrame())
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, evidence: Any) -> None:
        checks.append({"name": name, "status": "pass" if passed else "fail", "evidence": evidence})

    resolution = {
        "width": _setting_int(timeline, "timelineResolutionWidth"),
        "height": _setting_int(timeline, "timelineResolutionHeight"),
        "fps": _setting_int(timeline, "timelineFrameRate"),
        "playback_fps": _setting_int(timeline, "timelinePlaybackFrameRate"),
    }
    check(
        "identity_and_4k60",
        str(timeline.GetName() or "") == expected_name
        and timeline_start == int(manifest["timeline"]["start_frame"])
        and resolution == {"width": WIDTH, "height": HEIGHT, "fps": FPS, "playback_fps": FPS},
        {
            "name": str(timeline.GetName() or ""),
            "expected_name": expected_name,
            "timeline_start": timeline_start,
            "resolution": resolution,
        },
    )
    track_counts = {
        "video": int(timeline.GetTrackCount("video") or 0),
        "audio": int(timeline.GetTrackCount("audio") or 0),
    }
    check("exact_track_count", track_counts == {"video": 2, "audio": 3}, track_counts)
    audio_track_names = {
        index: str(timeline.GetTrackName("audio", index) or "")
        for index in AUDIO_TRACK_NAMES
    }
    check(
        "exact_audio_track_names",
        audio_track_names == AUDIO_TRACK_NAMES,
        {"expected": AUDIO_TRACK_NAMES, "actual": audio_track_names},
    )

    expected = _expected_tracks(manifest)
    live = {
        "V1": _live_track(timeline, "video", 1, timeline_start),
        "V2": _live_track(timeline, "video", 2, timeline_start),
        "A1": _live_track(timeline, "audio", 1, timeline_start),
        "A2": _live_track(timeline, "audio", 2, timeline_start),
        "A3": _live_track(timeline, "audio", 3, timeline_start),
    }
    matched_live: dict[str, list[dict[str, Any]]] = {}
    for track in ("V1", "V2", "A1", "A2", "A3"):
        actual = live[track]
        wanted = expected[track]
        geometry = [row["record_range"] for row in actual]
        wanted_geometry = [row["record_range"] for row in wanted]
        paths = [_normalized_path(row["path"]) for row in actual]
        wanted_paths = [_normalized_path(row["path"]) for row in wanted]
        passed = (
            geometry == wanted_geometry
            and paths == wanted_paths
            and all(row["enabled"] for row in actual)
        )
        check(
            f"exact_{track.lower()}_inventory",
            passed,
            {
                "expected": [
                    {"record_range": row["record_range"], "path": row["path"], "kind": row["kind"]}
                    for row in wanted
                ],
                "actual": [
                    {
                        "record_range": row["record_range"],
                        "path": row["path"],
                        "name": row["name"],
                        "enabled": row["enabled"],
                    }
                    for row in actual
                ],
            },
        )
        matched_live[track] = actual

    crop_values: list[float] = []
    carousel_expected = [row for row in expected["V2"] if row["kind"] == "carousel-v2"]
    carousel_ranges = {tuple(row["record_range"]) for row in carousel_expected}
    for row in matched_live["V2"]:
        if tuple(row["record_range"]) not in carousel_ranges:
            continue
        properties = row["item"].GetProperty() or {}
        try:
            crop_values.append(float(properties.get("CropBottom") or 0.0))
        except (TypeError, ValueError):
            crop_values.append(float("nan"))
    check(
        "carousel_crop_bottom_only_contract",
        len(crop_values) == len(carousel_expected)
        and all(abs(value - CAROUSEL_CROP_BOTTOM) < 0.01 for value in crop_values),
        {"expected": CAROUSEL_CROP_BOTTOM, "values": crop_values},
    )

    v1_outro_range = tuple(manifest["outro"]["record_range"])
    outro_video = next(
        (row["item"] for row in matched_live["V1"] if tuple(row["record_range"]) == v1_outro_range),
        None,
    )
    outro_audio = next(
        (row["item"] for row in matched_live["A3"] if tuple(row["record_range"]) == v1_outro_range),
        None,
    )
    video_links = list(outro_video.GetLinkedItems() or []) if outro_video is not None else []
    audio_links = list(outro_audio.GetLinkedItems() or []) if outro_audio is not None else []
    video_uid = _uid(outro_video, "V1 outro item") if outro_video is not None else ""
    audio_uid = _uid(outro_audio, "A3 outro item") if outro_audio is not None else ""
    linked = bool(
        video_uid
        and audio_uid
        and any(_uid(item, "V1 outro linked item") == audio_uid for item in video_links)
        and any(_uid(item, "A3 outro linked item") == video_uid for item in audio_links)
    )
    check(
        "outro_v1_a3_link_state",
        linked,
        {
            "record_range": list(v1_outro_range),
            "video_link_count": len(video_links),
            "audio_link_count": len(audio_links),
        },
    )

    failed = [row for row in checks if row["status"] != "pass"]
    return {
        "schema": LIVE_AUDIT_SCHEMA,
        "status": "pass" if not failed else "fail",
        "timeline_name": str(timeline.GetName() or ""),
        "timeline_uid": _uid(timeline, "live dry-run timeline"),
        "check_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "checks": checks,
        "failed_checks": [row["name"] for row in failed],
    }


def _inventory_delta(before: Iterable[dict[str, Any]], after: Iterable[dict[str, Any]]) -> set[str]:
    return {str(row["uid"]) for row in after} - {str(row["uid"]) for row in before}


def run_resolve_dry_run(
    *,
    resolve: Any,
    fcpxml_path: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    receipt_path: Path,
    media_pool_report_path: Path | None = None,
    fairlight_report_path: Path | None = None,
    expected_project_name: str,
    deadline_check: Any | None = None,
) -> dict[str, Any]:
    """Build one receipt-bound timeline, apply final Fairlight, save, and validate."""

    fcpxml_path = fcpxml_path.resolve()
    manifest_path = manifest_path.resolve()
    receipt_path = receipt_path.resolve()
    if not fcpxml_path.is_file() or not manifest_path.is_file():
        raise GscGymResolveError("Resolve dry run requires current FCPXML and manifest artifacts.")
    try:
        manifest_on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GscGymResolveError(
            f"Resolve dry-run manifest is unreadable: {manifest_path}"
        ) from exc
    if not isinstance(manifest_on_disk, dict) or manifest_on_disk != manifest:
        raise GscGymResolveError(
            "Resolve dry-run manifest payload does not match the exact manifest file."
        )
    fcpxml_sha = _sha256(fcpxml_path)
    manifest_fcpxml_sha = str(manifest.get("fcpxml_sha256") or "").strip().upper()
    if not manifest_fcpxml_sha or manifest_fcpxml_sha != fcpxml_sha:
        raise GscGymResolveError(
            "Resolve dry-run FCPXML is not bound by the exact offline-audited manifest hash."
        )
    if deadline_check:
        deadline_check("connecting receipt-bound Resolve dry run")
    manager = resolve.GetProjectManager() if resolve is not None else None
    project = manager.GetCurrentProject() if manager is not None else None
    if project is None:
        raise GscGymResolveError("Resolve has no current project.")
    project_name = str(project.GetName() or "")
    if project_name != expected_project_name:
        raise GscGymResolveError(
            f"Current Resolve project is {project_name!r}; exact {expected_project_name!r} is required."
        )
    project_uid = _uid(project, "project")
    timeline_name = str(manifest["timeline"]["name"])
    manifest_sha = _sha256(manifest_path)
    media_pool_inputs = _media_pool_inputs(manifest)
    media_pool_kwargs = _media_pool_kwargs(
        media_pool_inputs,
        timeline_name=timeline_name,
    )
    media_pool_report_path = (
        Path(media_pool_report_path).resolve()
        if media_pool_report_path is not None
        else _media_pool_report_path(receipt_path).resolve()
    )
    fairlight_report_path = (
        Path(fairlight_report_path).resolve()
        if fairlight_report_path is not None
        else _fairlight_report_path(receipt_path).resolve()
    )

    receipt: dict[str, Any] | None = None
    if receipt_path.is_file():
        try:
            parsed = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GscGymResolveError(f"Unreadable Resolve dry-run receipt: {receipt_path}") from exc
        if not isinstance(parsed, dict) or parsed.get("schema") != RECEIPT_SCHEMA:
            raise GscGymResolveError("Resolve dry-run receipt has an unsupported schema.")
        receipt = parsed
        immutable_match = (
            receipt.get("project_uid") == project_uid
            and receipt.get("timeline_name") == timeline_name
            and receipt.get("fcpxml_sha256") == fcpxml_sha
            and receipt.get("manifest_sha256") == manifest_sha
        )
        if not immutable_match:
            raise GscGymResolveError(
                "Existing Resolve receipt does not bind this exact project/FCPXML/manifest."
            )

    inventory_before: list[dict[str, Any]]
    imported: Any | None = None
    if receipt is not None and str(receipt.get("timeline_uid") or ""):
        imported = _timeline_by_uid(project, str(receipt["timeline_uid"]))
        if imported is None:
            raise GscGymResolveError("Receipt-bound dry-run timeline UID no longer exists.")
        inventory_before = list(receipt.get("timeline_inventory_before_import") or [])
    elif receipt is not None:
        inventory_before = list(receipt.get("timeline_inventory_before_import") or [])
        current = timeline_inventory(project)
        additions = _inventory_delta(inventory_before, current)
        candidates = [
            row for row in current
            if row["uid"] in additions and row["name"] == timeline_name
        ]
        if len(additions) == 1 and len(candidates) == 1:
            imported = _timeline_by_uid(project, candidates[0]["uid"])
            # The journal was written before ImportTimelineFromFile and the
            # sole receipt-bound inventory delta proves that import completed
            # before interruption.  Recovery adopts that one import; it must
            # not report zero or perform a second import.
            receipt["editorial_import_count"] = 1
            receipt["status"] = "recovered_import_pending_validation"
            _atomic_json(receipt_path, receipt)
        elif additions:
            raise GscGymResolveError(
                "Interrupted import recovery found an unexpected Resolve timeline inventory delta."
            )
    else:
        inventory_before = timeline_inventory(project)
        if any(row["name"] == timeline_name for row in inventory_before):
            raise GscGymResolveError(
                "A timeline with the deterministic dry-run name already exists without its receipt."
            )
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "status": "pending_import",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project_name": project_name,
            "project_uid": project_uid,
            "timeline_name": timeline_name,
            "timeline_uid": None,
            "fcpxml": str(fcpxml_path),
            "fcpxml_sha256": fcpxml_sha,
            "manifest": str(manifest_path),
            "manifest_sha256": manifest_sha,
            "timeline_inventory_before_import": inventory_before,
            "editorial_import_count": 0,
        }
        _atomic_json(receipt_path, receipt)

    if imported is None:
        if deadline_check:
            deadline_check("importing one deterministic GSC dry-run timeline")
        media_pool = project.GetMediaPool()
        imported = media_pool.ImportTimelineFromFile(
            str(fcpxml_path),
            {"timelineName": timeline_name},
        )
        if imported is None:
            raise GscGymResolveError("Resolve rejected the deterministic GSC FCPXML import.")
        receipt["editorial_import_count"] = 1
        # Persist the mutation count immediately.  Any subsequent identity,
        # selection, inventory, or live-audit failure must not falsely report
        # that Resolve was untouched after the import API returned a timeline.
        receipt["status"] = "import_returned_pending_identity_validation"
        _atomic_json(receipt_path, receipt)
    timeline_uid = _uid(imported, "imported dry-run timeline")
    if str(imported.GetName() or "") != timeline_name:
        raise GscGymResolveError("Resolve changed the deterministic dry-run timeline name.")
    if project.SetCurrentTimeline(imported) is not True:
        raise GscGymResolveError("Resolve could not select the imported dry-run timeline.")

    inventory_after = timeline_inventory(project)
    delta = _inventory_delta(inventory_before, inventory_after)
    if delta != {timeline_uid} or len(inventory_after) != len(inventory_before) + 1:
        raise GscGymResolveError(
            "Resolve import did not create exactly one receipt-bound timeline UID."
        )
    receipt.update(
        {
            "status": "imported_pending_validation",
            "timeline_uid": timeline_uid,
            "timeline_inventory_after_import": inventory_after,
        }
    )
    _atomic_json(receipt_path, receipt)

    # Resolve is known to map connected FCPXML audio lanes inconsistently.
    # The imported video is authoritative; audio is rebuilt on this same UID
    # with explicit scripting-API track indices and a receipt journal.
    completed_fairlight_binding = receipt.get("fairlight_preset")
    fairlight_already_complete = bool(
        isinstance(completed_fairlight_binding, dict)
        and completed_fairlight_binding.get("schema") == FAIRLIGHT_BINDING_SCHEMA
        and completed_fairlight_binding.get("status") == "pass"
    )
    if fairlight_already_complete:
        completed_media_pool_binding = receipt.get("media_pool_bins")
        if not (
            isinstance(completed_media_pool_binding, dict)
            and completed_media_pool_binding.get("schema")
            == MEDIA_POOL_BINDING_SCHEMA
            and completed_media_pool_binding.get("status") == "pass"
        ):
            raise GscGymResolveError(
                "Completed Fairlight receipt lacks its prerequisite saved Media Pool binding."
            )

    def audio_journal(status: str, evidence: dict[str, Any]) -> None:
        receipt.update(
            {
                "status": status,
                "audio_scripting_placement": evidence,
            }
        )
        _atomic_json(receipt_path, receipt)

    try:
        audio_report = repair_receipt_bound_audio(
            project=project,
            timeline=imported,
            manifest=manifest,
            deadline_check=deadline_check,
            journal=audio_journal,
            allow_mutation=not fairlight_already_complete,
        )
    except GscGymResolveAudioError as exc:
        receipt.update(
            {
                "status": "failed_audio_scripting_placement",
                "audio_scripting_error": str(exc),
            }
        )
        _atomic_json(receipt_path, receipt)
        raise GscGymResolveError(str(exc)) from exc

    audit = audit_live_timeline(imported, manifest)
    if audit["status"] != "pass":
        receipt.update({"status": "failed_live_audit", "live_audit": audit})
        _atomic_json(receipt_path, receipt)
        raise GscGymResolveError(
            "Receipt-bound Resolve live audit failed: " + ", ".join(audit["failed_checks"])
        )

    media_pool_timeline_inventory_before = timeline_inventory(project)
    if deadline_check:
        deadline_check("organizing deterministic reusable GSC Media Pool assets")
    media_pool_report: dict[str, Any] | None = None
    media_pool_mode = ""
    existing_binding = receipt.get("media_pool_bins")
    try:
        if isinstance(existing_binding, dict) and existing_binding.get("status") == "pass":
            binding_valid = (
                existing_binding.get("schema") == MEDIA_POOL_BINDING_SCHEMA
                and str(existing_binding.get("project_uid") or "") == project_uid
                and str(existing_binding.get("timeline_uid") or "") == timeline_uid
                and Path(str(existing_binding.get("report_path") or "")).resolve()
                == media_pool_report_path
                and existing_binding.get("report_schema")
                == MEDIA_POOL_ORGANIZATION_SCHEMA
                and type(existing_binding.get("timeline_creation_count")) is int
                and existing_binding.get("timeline_creation_count") == 0
            )
            if not binding_valid:
                raise GscGymResolveError(
                    "Existing reusable Media Pool receipt binding does not match the "
                    "exact project, timeline, report path, or zero-timeline contract."
                )
            if not media_pool_report_path.is_file():
                raise GscGymResolveError(
                    "Receipt-bound reusable Media Pool report is missing."
                )
            if _sha256(media_pool_report_path) != str(
                existing_binding.get("report_sha256") or ""
            ).upper():
                raise GscGymResolveError(
                    "Receipt-bound reusable Media Pool report hash changed."
                )
            parsed_report = json.loads(
                media_pool_report_path.read_text(encoding="utf-8")
            )
            if not isinstance(parsed_report, dict):
                raise GscGymResolveError(
                    "Receipt-bound reusable Media Pool report is not a JSON object."
                )
            media_pool_report = parsed_report
            _validate_media_pool_report_identity(
                media_pool_report,
                project_uid=project_uid,
                timeline_name=timeline_name,
                timeline_uid=timeline_uid,
            )
            media_pool_mode = "reused_exact_bound_report"
        elif media_pool_report_path.is_file():
            parsed_report = json.loads(
                media_pool_report_path.read_text(encoding="utf-8")
            )
            if not isinstance(parsed_report, dict):
                raise GscGymResolveError(
                    "Interrupted reusable Media Pool report is not a JSON object."
                )
            media_pool_report = parsed_report
            _validate_media_pool_report_identity(
                media_pool_report,
                project_uid=project_uid,
                timeline_name=timeline_name,
                timeline_uid=timeline_uid,
            )
            media_pool_mode = "adopted_exact_interrupted_report"
        else:
            receipt.update(
                {
                    "status": "media_pool_bins_pending",
                    "audio_scripting_placement": audio_report,
                    "live_audit": audit,
                    "media_pool_bins": {
                        "schema": MEDIA_POOL_BINDING_SCHEMA,
                        "status": "pending",
                        "report_path": str(media_pool_report_path),
                        "project_uid": project_uid,
                        "timeline_uid": timeline_uid,
                        "timeline_creation_count": 0,
                    },
                }
            )
            _atomic_json(receipt_path, receipt)
            media_pool_report = organize_media_pool(project, **media_pool_kwargs)
            _validate_media_pool_report_identity(
                media_pool_report,
                project_uid=project_uid,
                timeline_name=timeline_name,
                timeline_uid=timeline_uid,
            )
            _atomic_json(media_pool_report_path, media_pool_report)
            media_pool_mode = "organized_full_reusable_library"

        media_pool_live_audit = audit_media_pool_organization(
            project,
            media_pool_report,
            **media_pool_kwargs,
        )
        if media_pool_live_audit.get("status") != "pass":
            raise GscGymResolveError(
                "Reusable Media Pool live audit failed: "
                + ", ".join(media_pool_live_audit.get("failed_checks") or [])
            )
        media_pool_timeline_inventory_after = timeline_inventory(project)
        if media_pool_timeline_inventory_after != media_pool_timeline_inventory_before:
            raise GscGymResolveError(
                "Reusable Media Pool organization changed the Resolve timeline inventory."
            )
        bound_timeline_after_bins = _timeline_by_uid(project, timeline_uid)
        if (
            bound_timeline_after_bins is None
            or str(bound_timeline_after_bins.GetName() or "") != timeline_name
        ):
            raise GscGymResolveError(
                "Reusable Media Pool organization displaced the exact receipt-bound timeline UID."
            )
        media_pool_binding = _media_pool_binding(
            report_path=media_pool_report_path,
            report=media_pool_report,
            project_uid=project_uid,
            timeline_uid=timeline_uid,
            mode=media_pool_mode,
        )
        receipt.update(
            {
                "status": "media_pool_bins_validated_pending_save",
                "media_pool_bins": media_pool_binding,
                "media_pool_timeline_inventory_before": media_pool_timeline_inventory_before,
                "media_pool_timeline_inventory_after": media_pool_timeline_inventory_after,
            }
        )
        receipt.pop("media_pool_bins_error", None)
        _atomic_json(receipt_path, receipt)
    except (
        GscGymMediaPoolError,
        GscGymResolveError,
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        receipt.update(
            {
                "status": "failed_media_pool_bins",
                "media_pool_bins_error": str(exc),
            }
        )
        _atomic_json(receipt_path, receipt)
        if isinstance(exc, GscGymResolveError):
            raise
        raise GscGymResolveError(str(exc)) from exc

    if deadline_check:
        deadline_check("starting final receipt-bound Fairlight transaction")
    try:
        fairlight_report, fairlight_binding = _ensure_final_fairlight_preset(
            manager=manager,
            project=project,
            timeline=imported,
            manifest=manifest,
            receipt=receipt,
            receipt_path=receipt_path,
            report_path=fairlight_report_path,
            deadline_check=deadline_check,
        )
    except (GscGymResolveError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if receipt.get("status") not in {
            "fairlight_applied_pending_save",
            "failed_fairlight_apply",
            "failed_fairlight_apply_exception_ambiguous",
        }:
            receipt["status"] = "failed_fairlight"
        receipt["fairlight_error"] = str(exc)
        receipt["project_saved"] = receipt.get("project_saved") is True
        _atomic_json(receipt_path, receipt)
        if isinstance(exc, GscGymResolveError):
            raise
        raise GscGymResolveError(str(exc)) from exc

    final_audit = audit_live_timeline(imported, manifest)
    if final_audit.get("status") != "pass":
        receipt.update(
            {
                "status": "failed_post_fairlight_live_audit",
                "final_live_audit": final_audit,
                "project_saved": fairlight_report.get("project_saved") is True,
            }
        )
        _atomic_json(receipt_path, receipt)
        raise GscGymResolveError(
            "Final read-only live validation after Fairlight failed: "
            + ", ".join(final_audit.get("failed_checks") or [])
        )
    current = project.GetCurrentTimeline()
    if _uid(current, "final current timeline") != timeline_uid:
        raise GscGymResolveError(
            "Final read-only validation found a different current timeline UID."
        )
    final_inventory = timeline_inventory(project)
    if final_inventory != media_pool_timeline_inventory_after:
        raise GscGymResolveError(
            "Final read-only validation found a changed timeline inventory."
        )
    receipt.update(
        {
            "status": "pass",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "editorial_import_count": int(receipt.get("editorial_import_count") or 0),
            "outro_link_mutation": bool(audio_report.get("outro_link_mutation")),
            "audio_scripting_placement": audio_report,
            "live_audit": final_audit,
            "pre_fairlight_live_audit": audit,
            "final_live_audit": final_audit,
            "media_pool_bins": media_pool_binding,
            "fairlight_preset": fairlight_binding,
            "fairlight_apply_count": int(
                fairlight_binding.get("lifetime_apply_count") or 0
            ),
            "project_saved": fairlight_report.get("project_saved") is True,
        }
    )
    if not resolve_receipt_deployment_ready(receipt):
        receipt["status"] = "failed_fairlight_completion_gate"
        _atomic_json(receipt_path, receipt)
        raise GscGymResolveError(
            "Resolve receipt cannot pass without exact saved Fairlight evidence."
        )
    _atomic_json(receipt_path, receipt)
    return receipt


__all__ = [
    "CAROUSEL_CROP_BOTTOM",
    "GscGymResolveError",
    "LIVE_AUDIT_SCHEMA",
    "RECEIPT_SCHEMA",
    "audit_live_timeline",
    "resolve_receipt_deployment_ready",
    "run_resolve_dry_run",
    "timeline_inventory",
]
