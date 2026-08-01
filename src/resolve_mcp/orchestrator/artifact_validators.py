from __future__ import annotations

import json
from pathlib import Path
from typing import Any


NARRATIVE_REQUIRED_FIELDS = ("start_sec", "end_sec", "confidence", "type", "reason")
STRUCTURE_KINDS = {
    "pokemon_start",
    "pokemon_end",
    "significant_battle_pre_roll",
    "recap_ad_slot",
    "unevolved_failure_propagation",
    "final_outro_recap",
    "member_carousel_start",
}
MARKER_KINDS = {
    "pokemon_start",
    "unevolved_failure_propagation",
    "final_outro_recap",
    "member_carousel_start",
}


def artifact_validation_error(key: str, path: Path) -> str | None:
    """Return a human-readable validation error for required semantic artifacts."""
    if key == "narrative_output":
        return validate_narrative_output_file(path)
    if key == "input_preflight_report":
        return validate_input_preflight_file(path)
    if key == "parts_manifest":
        return validate_parts_manifest_file(path)
    if key == "native_normalized_ranges":
        return validate_normalized_ranges_file(path)
    if key == "post_cut_narrative_audit_report":
        return validate_post_cut_narrative_audit_file(path)
    if key == "approved_source_cuts":
        return validate_approved_source_cuts_file(path)
    if key == "structure_decisions":
        return validate_structure_decisions_file(path)
    if key == "gap_plan":
        return validate_gap_plan_file(path)
    if key == "gap_marker_report":
        return validate_status_report_file(path, "gap marker report")
    if key == "final_manifest":
        return validate_final_manifest_file(path)
    if key == "a1_dialogue_audit_report":
        return validate_a1_dialogue_audit_file(path)
    if key == "rse_assets_report":
        return validate_required_pass_report_file(path, "RSE assets preflight report")
    if key == "bgm_report":
        return validate_bgm_report_file(path)
    if key == "clip_color_report":
        return validate_clip_color_report_file(path)
    if key == "fairlight_report":
        return validate_fairlight_report_file(path)
    if key == "audio_normalization_instructions":
        return validate_audio_normalization_instructions_file(path)
    return None


def load_narrative_output_rows(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    rows = _extract_narrative_rows(payload)
    if rows is None:
        raise ValueError("expected a JSON array, or an object with a candidates/cuts array")
    return rows


def validate_narrative_output_file(path: Path) -> str | None:
    if not path.exists():
        return "missing narrative LLM output"
    try:
        rows = load_narrative_output_rows(path)
    except Exception as exc:
        return f"invalid narrative LLM output: {exc}"
    if not rows:
        return "narrative LLM output is empty; the review gate must return at least one candidate/review row"
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            return f"narrative LLM row {index} must be a JSON object"
        missing = [field for field in NARRATIVE_REQUIRED_FIELDS if field not in row]
        if missing:
            return f"narrative LLM row {index} is missing required field(s): {', '.join(missing)}"
        bounds_error = _bounds_error(row)
        if bounds_error:
            return f"narrative LLM row {index} has invalid bounds: {bounds_error}"
        for field in ("confidence", "type", "reason"):
            if not str(row.get(field) or "").strip():
                return f"narrative LLM row {index} has an empty {field!r} field"
    return None


def validate_input_preflight_file(path: Path) -> str | None:
    if not path.exists():
        return "missing input preflight report"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid input preflight report: {exc}"
    if not isinstance(payload, dict):
        return "input preflight report must be a JSON object"
    if payload.get("schema") != "minimum_battles_input_preflight_v1":
        return "input preflight report has unsupported schema"
    if payload.get("status") != "pass":
        missing = payload.get("missing") or []
        return "input preflight did not pass" + (f": {', '.join(map(str, missing))}" if missing else "")
    return None


def validate_parts_manifest_file(path: Path) -> str | None:
    if not path.exists():
        return "missing auto-editor parts manifest"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid auto-editor parts manifest: {exc}"
    if not isinstance(payload, dict):
        return "auto-editor parts manifest must be a JSON object"
    if payload.get("schema") != "minimum_battles_auto_editor_parts_v1":
        return "auto-editor parts manifest has unsupported schema"
    parts = payload.get("parts")
    if not isinstance(parts, list) or not parts:
        return "auto-editor parts manifest must contain at least one part"
    seen_indexes: set[int] = set()
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            return f"parts[{index}] must be a JSON object"
        try:
            part_index = int(part["index"])
        except (KeyError, TypeError, ValueError):
            return f"parts[{index}] has invalid index"
        if part_index in seen_indexes:
            return f"duplicate part index {part_index}"
        seen_indexes.add(part_index)
        for field in ("source_media", "fcpxml", "dialogue_audio", "track_folder"):
            value = str(part.get(field) or "")
            if not value:
                return f"parts[{index}] is missing {field}"
            if field != "track_folder" and not Path(value).exists():
                return f"parts[{index}].{field} does not exist: {value}"
        track_folder = Path(str(part.get("track_folder") or ""))
        if not track_folder.is_dir():
            return f"parts[{index}].track_folder is not a directory: {track_folder}"
        for field in ("raw_duration_frames", "edited_duration_frames"):
            try:
                value = int(part.get(field, 0))
            except (TypeError, ValueError):
                return f"parts[{index}].{field} must be an integer"
            if value < 0:
                return f"parts[{index}].{field} must be non-negative"
    return None


def validate_structure_decisions_file(path: Path) -> str | None:
    if not path.exists():
        return "missing minimum-battles structure decisions"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid minimum-battles structure decisions: {exc}"
    if not isinstance(payload, dict):
        return "structure decisions must be a JSON object"
    if payload.get("schema") != "minimum_battles_structure_decisions_v1":
        return "structure decisions have unsupported schema"
    items = payload.get("items")
    if not isinstance(items, list):
        return "structure decisions must contain an items array"
    if not items:
        return "structure decisions are empty; approved structure is required before gap planning"
    seen_ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            return f"items[{index}] must be a JSON object"
        item_id = str(item.get("id") or "")
        if not item_id:
            return f"items[{index}] is missing id"
        if item_id in seen_ids:
            return f"duplicate structure decision id {item_id!r}"
        seen_ids.add(item_id)
        kind = str(item.get("kind") or "")
        if kind not in STRUCTURE_KINDS:
            return f"items[{index}] has unsupported kind {kind!r}"
        if item.get("approved") is not True:
            return f"items[{index}] is not explicitly approved"
        if "source_frame" not in item and "review_frame" not in item:
            return f"items[{index}] must include source_frame or review_frame"
        marker = item.get("marker") or {}
        if marker:
            if not isinstance(marker, dict):
                return f"items[{index}].marker must be an object"
            if marker.get("add"):
                marker_type = str(marker.get("type") or "")
                if marker_type not in MARKER_KINDS:
                    return f"items[{index}].marker has unsupported type {marker_type!r}"
                if not str(marker.get("name") or "").strip():
                    return f"items[{index}].marker needs a name"
    return None


def validate_gap_plan_file(path: Path) -> str | None:
    if not path.exists():
        return "missing minimum-battles gap plan"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid minimum-battles gap plan: {exc}"
    if not isinstance(payload, dict):
        return "gap plan must be a JSON object"
    if payload.get("schema") != "minimum_battles_gap_plan_v1":
        return "gap plan has unsupported schema"
    try:
        gap_frames = int(payload.get("gap_frames", 0))
        marker_offset_frames = int(payload.get("marker_offset_frames", 34))
        tolerance = int(payload.get("marker_offset_tolerance_frames", 12))
    except (TypeError, ValueError):
        return "gap_frames, marker_offset_frames, and marker_offset_tolerance_frames must be integers"
    if gap_frames <= 0:
        return "gap_frames must be positive"
    gaps = payload.get("gaps")
    if not isinstance(gaps, list):
        return "gap plan must contain a gaps array"
    if not gaps:
        return "gap plan is empty; minimum-battles structure should produce explicit gaps"
    seen_ids: set[str] = set()
    for index, gap in enumerate(gaps):
        if not isinstance(gap, dict):
            return f"gaps[{index}] must be a JSON object"
        gap_id = str(gap.get("id") or "")
        if not gap_id:
            return f"gaps[{index}] is missing id"
        if gap_id in seen_ids:
            return f"duplicate gap id {gap_id!r}"
        seen_ids.add(gap_id)
        kind = str(gap.get("kind") or "")
        if kind not in STRUCTURE_KINDS:
            return f"gaps[{index}] has unsupported kind {kind!r}"
        try:
            row_gap_frames = int(gap.get("gap_frames", gap_frames))
        except (TypeError, ValueError):
            return f"gaps[{index}].gap_frames must be an integer"
        if row_gap_frames != gap_frames:
            return f"gaps[{index}] gap_frames {row_gap_frames} does not match plan gap_frames {gap_frames}"
        if "final_gap_start_frame" not in gap:
            return f"gaps[{index}] is missing final_gap_start_frame"
        v2_hold = gap.get("v2_hold")
        if v2_hold:
            if not isinstance(v2_hold, dict):
                return f"gaps[{index}].v2_hold must be an object"
            if v2_hold.get("add") or v2_hold.get("extend") or v2_hold.get("duration_frames"):
                return (
                    f"gaps[{index}] uses legacy v2_hold; visual holds must be continuous "
                    "V1 clip extensions/coverage, not V2 overlays or stills"
                )
        v1_error = _validate_v1_gap_cover(gap, index, row_gap_frames)
        if v1_error:
            return v1_error
        marker = gap.get("marker") or {}
        if marker:
            if not isinstance(marker, dict):
                return f"gaps[{index}].marker must be an object"
            if marker.get("add"):
                marker_type = str(marker.get("type") or "")
                if marker_type not in MARKER_KINDS:
                    return f"gaps[{index}].marker has unsupported type {marker_type!r}"
                if not str(marker.get("name") or "").strip():
                    return f"gaps[{index}].marker needs a name"
                try:
                    marker_frame = int(marker["frame"])
                    gap_start = int(gap["final_gap_start_frame"])
                except (KeyError, TypeError, ValueError):
                    return f"gaps[{index}].marker.frame and final_gap_start_frame must be integers"
                expected = gap_start + marker_offset_frames
                if abs(marker_frame - expected) > tolerance and not str(gap.get("exception_reason") or "").strip():
                    return (
                        f"gaps[{index}].marker.frame {marker_frame} is outside tolerance "
                        f"for expected {expected}"
                    )
    return None


def validate_a1_dialogue_audit_file(path: Path) -> str | None:
    if not path.exists():
        return "missing A1 dialogue audit report"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid A1 dialogue audit report: {exc}"
    if not isinstance(payload, dict):
        return "A1 dialogue audit report must be a JSON object"
    if payload.get("status") == "pass" or payload.get("pass") is True:
        return None
    finding_count = payload.get("finding_count")
    if finding_count is not None:
        return f"A1 dialogue audit did not pass; finding_count={finding_count}"
    return "A1 dialogue audit did not pass"


def validate_normalized_ranges_file(path: Path) -> str | None:
    if not path.exists():
        return "missing normalized HTML review decisions"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid normalized HTML review decisions: {exc}"
    if not isinstance(payload, dict):
        return "normalized HTML review decisions must be a JSON object"
    if "timeline_fps" not in payload:
        return "normalized HTML review decisions are missing timeline_fps"
    for key in ("whole_cut_indices", "partial_records"):
        if key in payload and not isinstance(payload[key], list):
            return f"normalized HTML review decisions field {key!r} must be a list"
    return None


def validate_post_cut_narrative_audit_file(path: Path) -> str | None:
    if not path.exists():
        return "missing post-cut narrative audit report"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid post-cut narrative audit report: {exc}"
    if not isinstance(payload, dict):
        return "post-cut narrative audit report must be a JSON object"
    if payload.get("schema") != "minimum_battles_post_cut_narrative_audit_v1":
        return "post-cut narrative audit report has unsupported schema"
    if not isinstance(payload.get("deterministic_findings"), list):
        return "post-cut narrative audit report must contain deterministic_findings"
    if not isinstance(payload.get("actionable_findings"), list):
        return "post-cut narrative audit report must contain actionable_findings"
    status = str(payload.get("status") or "")
    if status and status not in {"needs_semantic_review", "pass", "passed", "clear", "complete"}:
        return f"post-cut narrative audit report has unsupported status {status!r}"
    return None


def validate_approved_source_cuts_file(path: Path) -> str | None:
    if not path.exists():
        return "missing approved source cuts"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid approved source cuts: {exc}"
    if not isinstance(payload, dict):
        return "approved source cuts must be a JSON object"
    source_cuts = payload.get("source_cuts")
    if not isinstance(source_cuts, list):
        return "approved source cuts must contain a source_cuts array"
    for index, cut in enumerate(source_cuts):
        if not isinstance(cut, dict):
            return f"source_cuts[{index}] must be a JSON object"
        start = _first_present(cut, "part_source_start_frame", "combined_source_start_frame", "source_start_frame", "start_frame")
        end = _first_present(cut, "part_source_end_frame", "combined_source_end_frame", "source_end_frame", "end_frame")
        try:
            start_frame = int(start)
            end_frame = int(end)
        except (TypeError, ValueError):
            return f"source_cuts[{index}] must include numeric start/end frame fields"
        if end_frame <= start_frame:
            return f"source_cuts[{index}] end frame must be greater than start frame"
    return None


def validate_final_manifest_file(path: Path) -> str | None:
    if not path.exists():
        return "missing final manifest"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid final manifest: {exc}"
    if not isinstance(payload, dict):
        return "final manifest must be a JSON object"
    status_error = _status_failure(payload, "final manifest")
    if status_error:
        return status_error
    identity_keys = {
        "timeline",
        "timeline_name",
        "output_timeline",
        "final_timeline",
        "final_fcpxml",
        "fcpxml",
        "fcpxml_path",
    }
    if not any(key in payload and str(payload.get(key) or "").strip() for key in identity_keys):
        return "final manifest must name the final timeline or final FCPXML"
    return None


def validate_status_report_file(path: Path, label: str) -> str | None:
    if not path.exists():
        return f"missing {label}"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid {label}: {exc}"
    if not isinstance(payload, dict):
        return f"{label} must be a JSON object"
    return _status_failure(payload, label)


def validate_required_pass_report_file(path: Path, label: str) -> str | None:
    error = validate_status_report_file(path, label)
    if error:
        return error
    payload = _load_json(path)
    status = str(payload.get("status") or "").lower()
    if payload.get("ok") is not True and payload.get("pass") is not True and status not in {
        "pass",
        "passed",
        "ok",
        "complete",
        "ready",
    }:
        return f"{label} does not explicitly pass"
    return None


def validate_bgm_report_file(path: Path) -> str | None:
    if not path.exists():
        return "missing BGM report"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid BGM report: {exc}"
    if not isinstance(payload, dict):
        return "BGM report must be a JSON object"
    status_error = _status_failure(payload, "BGM report")
    if status_error:
        return status_error
    for key in ("a2_gaps", "a2_non_bgm", "a2_bgm_mismatches", "overhanging_items"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return f"BGM report has non-empty {key}"
    higher_audio = payload.get("higher_audio_nonempty")
    if isinstance(higher_audio, dict) and any(higher_audio.values()):
        return "BGM report has audio clips above A2"
    item_counts = payload.get("item_counts") or {}
    if isinstance(item_counts, dict) and int(item_counts.get("A2") or 0) <= 0:
        return "BGM report shows no A2 BGM clips"
    has_coverage_evidence = any(
        key in payload
        for key in ("a2_gaps", "a2_bgm_mismatches", "bgm", "placements", "item_counts")
    )
    if not has_coverage_evidence:
        return "BGM report must include A2 coverage/placement evidence"
    return None


def validate_clip_color_report_file(path: Path) -> str | None:
    error = validate_status_report_file(path, "clip color report")
    if error:
        return error
    payload = _load_json(path)
    try:
        failed = int(payload.get("clip_updates_failed", 0) or 0)
    except (TypeError, ValueError):
        return "clip color report clip_updates_failed must be numeric"
    if failed:
        return f"clip color report has {failed} failed clip update(s)"
    return None


def validate_fairlight_report_file(path: Path) -> str | None:
    if not path.exists():
        return "missing Fairlight report"
    try:
        payload = _load_json(path)
    except Exception as exc:
        return f"invalid Fairlight report: {exc}"
    if not isinstance(payload, dict):
        return "Fairlight report must be a JSON object"
    status = str(payload.get("status") or "").lower()
    if status not in {"applied", "pass", "passed", "complete"} and payload.get("ok") is not True:
        return "Fairlight report does not prove the preset was applied"
    if not str(payload.get("timeline") or payload.get("timeline_name") or "").strip():
        return "Fairlight report must name the timeline"
    if not str(payload.get("preset") or "").strip():
        return "Fairlight report must name the preset"
    return None


def validate_audio_normalization_instructions_file(path: Path) -> str | None:
    if not path.exists():
        return "missing audio normalization handoff instructions"
    text = path.read_text(encoding="utf-8-sig")
    lower = text.lower()
    for phrase in ("normalize audio", "sample peak", "independent"):
        if phrase not in lower:
            return f"audio normalization handoff instructions are missing {phrase!r}"
    return None


def _load_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError("file is empty")
    return json.loads(text)


def _extract_narrative_rows(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("candidates", "cuts"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return None


def _bounds_error(row: dict[str, Any]) -> str | None:
    try:
        start = float(row["start_sec"])
        end = float(row["end_sec"])
    except (TypeError, ValueError):
        return "start_sec/end_sec must be numeric"
    if end <= start:
        return "end_sec must be greater than start_sec"
    return None


def _validate_v1_gap_cover(gap: dict[str, Any], index: int, row_gap_frames: int) -> str | None:
    cover_key = ""
    cover: Any = None
    for key in ("v1_hold", "v1_cover", "visual_hold"):
        if key in gap:
            cover_key = key
            cover = gap.get(key)
            break
    if cover is None:
        return f"gaps[{index}] is missing V1 continuous hold/cover metadata"
    if not isinstance(cover, dict):
        return f"gaps[{index}].{cover_key} must be an object"
    if cover.get("continuous") is False:
        return f"gaps[{index}].{cover_key}.continuous must not be false"
    if "track_index" in cover:
        try:
            track_index = int(cover["track_index"])
        except (TypeError, ValueError):
            return f"gaps[{index}].{cover_key}.track_index must be an integer"
        if track_index != 1:
            return f"gaps[{index}].{cover_key}.track_index must be 1 for V1"
    track = str(cover.get("track") or cover.get("track_name") or "").strip().lower()
    if track and track not in {"v1", "video 1", "video:1", "video_track_1"}:
        return f"gaps[{index}].{cover_key} must target V1, got {track!r}"
    method = str(cover.get("method") or cover.get("type") or "").strip().lower()
    if any(token in method for token in ("still", "freeze", "image", "overlay", "v2", "higher")):
        return f"gaps[{index}].{cover_key} uses non-continuous hold method {method!r}"
    if "duration_frames" in cover:
        try:
            duration = int(cover["duration_frames"])
        except (TypeError, ValueError):
            return f"gaps[{index}].{cover_key}.duration_frames must be an integer"
        if duration < row_gap_frames:
            return f"gaps[{index}].{cover_key}.duration_frames must cover at least the A1 gap duration"
    return None


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _status_failure(payload: dict[str, Any], label: str) -> str | None:
    if payload.get("ok") is False:
        return f"{label} did not pass: ok=false"
    if payload.get("pass") is False:
        return f"{label} did not pass: pass=false"
    status = str(payload.get("status") or "").strip().lower()
    if status in {"fail", "failed", "failure", "error", "missing", "blocked"}:
        return f"{label} status is {status!r}"
    for key in ("failures", "errors"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return f"{label} has non-empty {key}"
    return None
