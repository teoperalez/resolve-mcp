"""Ordered Gen 1 RBY Ultra Minimum Battles pipeline runner.

This is a guardrail script, not a magic one-button editor. Its job is to keep
the run in the Victreebel-approved order so later heavy passes cannot happen
before cut review artifacts exist.

Order:
  1. review-base              minimal V1/A1 FCPXML, no visual holds
  2. narrative-prompt         broad narrative LLM prompt from review-base sections
  3. narrative-llm-review     external/GUI LLM dispatch writes narrative output
  4. programmatic-candidates  waveform, n-gram, artifact/short-clip detectors
  5. compile-cut-candidates   enforce FCPXML whole-section cut policy
 6. apply-html-decisions     offline source-time normalizer from pink_decisions
 7. compile-approved-cuts    source-time cut list for deterministic rebuild
  8. a1-dialogue-audit       rerun faster-whisper and verify A1 FCPXML dialogue
  9. extract-game-audio       game-audio WAV for BGM bridge sections
 10. final-assembly           launch Resolve and assemble the final timeline once
 11. clip-colors              color final timeline clips by deterministic sections
 12. fairlight                apply the configured Fairlight timeline preset
 13. audio-normalization-handoff
                              write Computer Use instructions for Resolve normalization
 14. validate-order
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
SRC_DIR = REPO_DIR / "src"
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator.artifact_validators import artifact_validation_error
from scripts import build_rby_umb_fcpxml as M


CUT_REVIEW_DIR = M.CODEX_DIR / "cut_review"
REVIEW_MANIFEST = M.profile_path("review_manifest", M.CODEX_DIR / f"{M.safe_file_stem(M.REVIEW_NAME)}_manifest.json")
CUT_CANDIDATES = M.profile_path("candidate_manifest", CUT_REVIEW_DIR / "cut_candidates.json")
NARRATIVE_PROMPT = M.profile_path("narrative_prompt", CUT_REVIEW_DIR / "narrative" / "review.in.md")
NARRATIVE_CLIP_INDEX = M.profile_path("narrative_clip_index", CUT_REVIEW_DIR / "narrative" / "clip_index.json")
NARRATIVE_OUTPUT = M.profile_path("narrative_output", CUT_REVIEW_DIR / "narrative" / "review.out.json")
WAVEFORM_CANDIDATES = M.profile_path("waveform_candidates", CUT_REVIEW_DIR / "waveform_candidates.json")
NGRAM_CANDIDATES = M.profile_path("ngram_candidates", CUT_REVIEW_DIR / "ngram_candidates.json")
ARTIFACT_CANDIDATES = M.profile_path("artifact_candidates", CUT_REVIEW_DIR / "artifact_candidates.json")
PROGRAMMATIC_CANDIDATES = M.profile_path("programmatic_candidates", CUT_REVIEW_DIR / "programmatic_candidates.json")
HTML_DECISIONS = M.profile_path("html_decisions", CUT_REVIEW_DIR / "review" / "pink_decisions.json")
HTML_CLIPS = M.profile_path("html_clips", CUT_REVIEW_DIR / "clips_for_review.json")
HTML_SEGMAP = M.profile_path("html_segmap", CUT_REVIEW_DIR / "review" / "segmap.json")
HTML_AUTO_SEGMAP = CUT_REVIEW_DIR / "review" / "auto_segmap.json"
HTML_STRUCTURAL_SEGMAP = CUT_REVIEW_DIR / "review" / "structural_segmap.json"
NATIVE_APPLIED_DIR = M.CODEX_DIR / "review_decisions_native"
NATIVE_NORMALIZED = M.profile_path("native_normalized_ranges", NATIVE_APPLIED_DIR / "review_decisions_normalized_ranges.json")
APPROVED_NARRATIVE = M.profile_path("approved_narrative", CUT_REVIEW_DIR / "approved_narrative_cuts.json")
APPROVED_SOURCE_CUTS = M.profile_path("approved_source_cuts", CUT_REVIEW_DIR / "approved_source_cuts.json")
FINAL_BASE_NAME = M.FINAL_NAME
FINAL_MANIFEST = M.profile_path("final_manifest", M.CODEX_DIR / f"{M.safe_file_stem(FINAL_BASE_NAME)}_manifest.json")
A1_DIALOGUE_AUDIT_REPORT = M.profile_path("a1_dialogue_audit_report", CUT_REVIEW_DIR / "a1_dialogue_audit.json")
A1_DIALOGUE_AUDIT_TRANSCRIPT_DIR = M.profile_path(
    "a1_dialogue_audit_transcript_dir",
    CUT_REVIEW_DIR / "a1-dialogue-audit-transcript",
)
GAME_AUDIO = M.profile_path("game_audio", M.PROJECT_DIR / f"{M.source_name()}_tracks" / f"{M.source_name()}_3.wav")
GAME_AUDIO_STREAM = M.profile_text("game_audio_stream", "0:a:2")
BGM_REPORT = M.profile_path("bgm_report", M.CODEX_DIR / "qa-reports" / "rby-umb-bgm.json")
INTRO_OUTRO_REPORT = M.profile_path("intro_outro_report", M.CODEX_DIR / "qa-reports" / "rby-umb-intro-outro.json")
GEN1_INTROS_REPORT = M.profile_path("gen1_intros_report", M.CODEX_DIR / "qa-reports" / "battle-intros-placements.json")
CLIP_COLOR_REPORT = M.profile_path("clip_color_report", M.CODEX_DIR / "qa-reports" / "rby-umb-clip-colors.json")
FAIRLIGHT_REPORT = M.profile_path("fairlight_report", M.CODEX_DIR / "qa-reports" / "rby-umb-fairlight.json")
AUDIO_NORMALIZATION_INSTRUCTIONS = M.profile_path(
    "audio_normalization_instructions",
    M.CODEX_DIR / "qa-reports" / "audio-normalization-computer-use.md",
)
PIPELINE_STATE = M.profile_path("pipeline_state", M.CODEX_DIR / "rby_umb_pipeline_state.json")
PIPELINE_REPORT = M.profile_path("pipeline_order_report", M.CODEX_DIR / "rby_umb_pipeline_order_report.json")
PIPELINE_CACHE_DIR = M.profile_path("pipeline_cache_dir", M.CODEX_DIR / "orchestrator_cache")
PIPELINE_STOP_REPORT = M.profile_path("pipeline_stop_report", M.CODEX_DIR / "orchestrator_stop.json")
DEFAULT_WORKFLOW_CONFIG = REPO_DIR / "config" / "orchestrator_workflows.json"
DEFAULT_PROFILE_ID = ""


def profile_float_default(key: str, default: float) -> float:
    try:
        return M.profile_float(key, default)
    except (TypeError, ValueError):
        return default


GAME_KEY = M.profile_text("game_key") or M.profile_text("game_version") or "pokemon_red_blue"
STRUCTURAL_INTRO_SPEED = int(profile_float_default("intro_speed_pct", profile_float_default("intro_speed", 400.0)))
POST_INTRO_GAP_SEC = profile_float_default("post_intro_gap_sec", 1.0)
GEN1_INTRO_SPEED = profile_float_default("gen1_intro_speed", 2.0)
GEN1_INTRO_ROOT = M.profile_path("gen1_intro_root", Path(r"C:\Programming\RBYNewLayout\gymLeaders\LeaderIntros"))
BGM_DIR = M.profile_path("bgm_dir", Path(r"C:\Programming\RBYNewLayout\audio\bgm"))
FAIRLIGHT_PRESET = M.profile_text("fairlight_preset", "Standard Gameplay youtube")
FAIRLIGHT_PRESET_TYPE = M.profile_text("fairlight_preset_type", "CONSOLE_FLEXI")
AUDIO_NORMALIZATION_TARGET_DB = profile_float_default("audio_normalization_target_db", -9.0)
WHISPER_MODEL = M.profile_text("whisper_model", "large-v3-turbo")
WHISPER_DEVICE = M.profile_text("whisper_device", "cuda")
WHISPER_COMPUTE_TYPE = M.profile_text("whisper_compute_type", "float16")
OPENING_BGM_OFFSET_SEC = profile_float_default(
    "opening_bgm_offset_sec",
    profile_float_default("opening_first_source_offset_sec", 13.0),
)


ORDER = [
    "review-base",
    "narrative-prompt",
    "narrative-llm-review",
    "programmatic-candidates",
    "compile-cut-candidates",
    "apply-html-decisions",
    "compile-approved-cuts",
    "a1-dialogue-audit",
    "extract-game-audio",
    "final-assembly",
    "clip-colors",
    "fairlight",
    "audio-normalization-handoff",
    "validate-order",
]


STAGE_OUTPUTS: dict[str, list[Path]] = {
    "review-base": [REVIEW_MANIFEST, M.profile_path("review_fcpxml", M.CODEX_DIR / "cut_review" / "review_base.fcpxml")],
    "narrative-prompt": [NARRATIVE_PROMPT, NARRATIVE_CLIP_INDEX],
    "programmatic-candidates": [WAVEFORM_CANDIDATES, NGRAM_CANDIDATES, ARTIFACT_CANDIDATES, PROGRAMMATIC_CANDIDATES],
    "compile-cut-candidates": [CUT_CANDIDATES, HTML_CLIPS, HTML_SEGMAP],
    "apply-html-decisions": [NATIVE_NORMALIZED],
    "compile-approved-cuts": [APPROVED_SOURCE_CUTS],
    "a1-dialogue-audit": [A1_DIALOGUE_AUDIT_REPORT],
    "extract-game-audio": [GAME_AUDIO],
    "final-base": [FINAL_MANIFEST],
    "structural-intro-outro": [INTRO_OUTRO_REPORT],
    "gen1-intros": [GEN1_INTROS_REPORT],
    "bgm": [BGM_REPORT],
    "clip-colors": [CLIP_COLOR_REPORT],
    "fairlight": [FAIRLIGHT_REPORT],
    "audio-normalization-handoff": [AUDIO_NORMALIZATION_INSTRUCTIONS],
    "final-assembly": [FINAL_MANIFEST, A1_DIALOGUE_AUDIT_REPORT, INTRO_OUTRO_REPORT, GEN1_INTROS_REPORT, BGM_REPORT, CLIP_COLOR_REPORT],
    "validate-order": [PIPELINE_REPORT],
}
CACHE_ARTIFACTS = {
    "carousel": PIPELINE_CACHE_DIR / "carousel.json",
}
CACHE_ONLY_STAGES = {"find-member-carousel", "carousel", "carousel-dry-run"}
OUTPUT_EXISTENCE_CACHE_STAGES = {"final-base"}
STAGE_DEPENDENCIES: dict[str, list[Path]] = {
    "final-base": [CUT_CANDIDATES, APPROVED_SOURCE_CUTS],
    "a1-dialogue-audit": [FINAL_MANIFEST, APPROVED_SOURCE_CUTS],
    "structural-intro-outro": [FINAL_MANIFEST],
    "gen1-intros": [INTRO_OUTRO_REPORT],
    "bgm": [INTRO_OUTRO_REPORT, GEN1_INTROS_REPORT, GAME_AUDIO],
    "find-member-carousel": [BGM_REPORT, GEN1_INTROS_REPORT],
    "carousel": [BGM_REPORT, GEN1_INTROS_REPORT],
    "carousel-dry-run": [BGM_REPORT, GEN1_INTROS_REPORT],
    "clip-colors": [INTRO_OUTRO_REPORT, GEN1_INTROS_REPORT, BGM_REPORT, CACHE_ARTIFACTS["carousel"]],
    "fairlight": [CLIP_COLOR_REPORT],
    "audio-normalization-handoff": [FAIRLIGHT_REPORT],
    "final-assembly": [APPROVED_SOURCE_CUTS, A1_DIALOGUE_AUDIT_REPORT, GAME_AUDIO],
    "validate-order": [FAIRLIGHT_REPORT, AUDIO_NORMALIZATION_INSTRUCTIONS],
}
CACHE_TIMESTAMP_FRESHNESS_STAGES = {"final-assembly"}
INTRO_GAP_DEPENDENT_STAGES = {
    "structural-intro-outro",
    "gen1-intros",
    "bgm",
    "find-member-carousel",
    "carousel",
    "carousel-dry-run",
    "clip-colors",
    "fairlight",
    "audio-normalization-handoff",
    "final-assembly",
    "validate-order",
}
NARRATIVE_OUTPUT_DEPENDENT_STAGES = {
    "programmatic-candidates",
    "compile-cut-candidates",
    "apply-html-decisions",
    "compile-approved-cuts",
    "a1-dialogue-audit",
    "extract-game-audio",
    "final-base",
    "structural-intro-outro",
    "gen1-intros",
    "bgm",
    "find-member-carousel",
    "carousel",
    "carousel-dry-run",
    "final-assembly",
    "clip-colors",
    "fairlight",
    "audio-normalization-handoff",
    "validate-order",
}


class PipelineStop(RuntimeError):
    """A required input or decision is missing, so the orchestrator must stop."""


def run(cmd: list[str]) -> None:
    print(" ".join(f'"{part}"' if " " in str(part) else str(part) for part in cmd), flush=True)
    subprocess.run([str(part) for part in cmd], check=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def stage_cache_path(stage: str) -> Path:
    return PIPELINE_CACHE_DIR / f"{stage}.json"


def stage_outputs_exist(stage: str) -> bool:
    outputs = STAGE_OUTPUTS.get(stage, [])
    return bool(outputs) and all(path.exists() for path in outputs)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def stage_dependencies_fresh(stage: str, outputs: list[Path], cache_path: Path | None = None) -> bool:
    declared_deps = STAGE_DEPENDENCIES.get(stage, [])
    if any(not path.exists() for path in declared_deps):
        return False
    deps = list(declared_deps)
    if not deps:
        return True
    newest_dep = max(_mtime(path) for path in deps)
    if stage in CACHE_TIMESTAMP_FRESHNESS_STAGES and cache_path is not None and cache_path.exists():
        return _mtime(cache_path) >= newest_dep
    if outputs:
        return min(_mtime(path) for path in outputs) >= newest_dep
    if cache_path is not None and cache_path.exists():
        return _mtime(cache_path) >= newest_dep
    return False


def intro_outro_report_status() -> dict:
    status = {
        "required_gap_sec": POST_INTRO_GAP_SEC,
        "current": POST_INTRO_GAP_SEC <= 0,
    }
    if POST_INTRO_GAP_SEC <= 0:
        return status
    if not INTRO_OUTRO_REPORT.exists():
        status.update({"current": False, "reason": "missing_intro_outro_report"})
        return status
    try:
        report = read_json(INTRO_OUTRO_REPORT)
    except Exception as exc:
        status.update({"current": False, "reason": f"unreadable_intro_outro_report: {exc}"})
        return status
    fps = float(report.get("fps") or profile_float_default("timeline_fps", 60.0))
    expected_gap_frames = max(0, int(round(POST_INTRO_GAP_SEC * fps)))
    gap_frames = int(report.get("post_intro_gap_frames") or -1)
    base_shift_frames = int(report.get("base_timeline_shift_frames") or -1)
    gameplay_shift_frames = int(report.get("gameplay_shift_frames") or -1)
    intro_duration_frames = int(report.get("intro_duration_frames") or 0)
    markers_expected = int(report.get("markers_expected") or 0)
    markers_reapplied = int(report.get("markers_reapplied") or 0)
    marker_mappings = report.get("marker_mappings") or []
    gap_source_ok = report.get("post_intro_gap_source") == "timeline_markers"
    gap_names_ok = bool(report.get("post_intro_gap_start_marker")) and bool(report.get("post_intro_gap_end_marker"))
    gap_bounds_ok = (
        report.get("post_intro_gap_source_start_frame") is not None
        and report.get("post_intro_gap_source_end_frame") is not None
        and int(report.get("post_intro_gap_source_end_frame")) - int(report.get("post_intro_gap_source_start_frame")) == gap_frames
        and report.get("post_intro_gap_placed_start_frame") is not None
        and report.get("post_intro_gap_placed_end_frame") is not None
        and int(report.get("post_intro_gap_placed_end_frame")) - int(report.get("post_intro_gap_placed_start_frame")) == gap_frames
    )
    gap_ok = gap_frames == expected_gap_frames and gap_source_ok and gap_names_ok and gap_bounds_ok
    marker_required = bool(report.get("post_intro_gap_marker_correspondence_required"))
    marker_counts_ok = markers_expected > 0 and markers_reapplied == markers_expected
    marker_mappings_ok = (
        len(marker_mappings) == markers_expected
        and all(row.get("placed_frame") is not None for row in marker_mappings)
    )
    a1_gap_overlap_count = report.get("post_intro_a1_gap_overlap_count")
    a1_gap_ok = a1_gap_overlap_count is not None and int(a1_gap_overlap_count) == 0
    source_a1_overlap_count = int(report.get("post_intro_gap_source_a1_overlap_count") or 0)
    a1_gap_shift_frames = int(report.get("a1_gap_shift_frames") or 0)
    video_gap_shift_frames = int(report.get("video_gap_shift_frames") or 0)
    marker_gap_shift_frames = int(report.get("marker_gap_shift_frames") or 0)
    a1_shift_ok = (
        (source_a1_overlap_count > 0 and a1_gap_shift_frames == gap_frames)
        or (source_a1_overlap_count == 0 and a1_gap_shift_frames == 0)
    )
    video_shift_ok = video_gap_shift_frames == a1_gap_shift_frames
    marker_gap_shift_ok = marker_gap_shift_frames == a1_gap_shift_frames
    marker_rows_shift_ok = True
    gap_start = report.get("post_intro_gap_source_start_frame")
    for row in marker_mappings:
        source_frame = int(row.get("source_frame") or 0)
        row_gap_shift = int(row.get("gap_shift_frames") or 0)
        expected_gap_shift = (
            marker_gap_shift_frames
            if gap_start is not None and source_frame >= int(gap_start)
            else 0
        )
        expected_new = source_frame + intro_duration_frames + expected_gap_shift
        if row_gap_shift != expected_gap_shift or int(row.get("expected_new_frame") or -1) != expected_new:
            marker_rows_shift_ok = False
            break
    shift_ok = (
        base_shift_frames == intro_duration_frames
        and gameplay_shift_frames == intro_duration_frames
        and a1_shift_ok
        and video_shift_ok
        and marker_gap_shift_ok
        and marker_rows_shift_ok
    )
    status.update(
        {
            "expected_gap_frames": expected_gap_frames,
            "actual_gap_frames": gap_frames,
            "gap_source_ok": gap_source_ok,
            "gap_names_ok": gap_names_ok,
            "gap_bounds_ok": gap_bounds_ok,
            "marker_correspondence_required": marker_required,
            "markers_expected": markers_expected,
            "markers_reapplied": markers_reapplied,
            "marker_counts_ok": marker_counts_ok,
            "marker_mappings_ok": marker_mappings_ok,
            "post_intro_a1_gap_ok": a1_gap_ok,
            "source_a1_gap_overlap_count": source_a1_overlap_count,
            "a1_gap_shift_frames": a1_gap_shift_frames,
            "a1_shift_ok": a1_shift_ok,
            "video_gap_shift_frames": video_gap_shift_frames,
            "video_shift_ok": video_shift_ok,
            "marker_gap_shift_frames": marker_gap_shift_frames,
            "marker_gap_shift_ok": marker_gap_shift_ok,
            "marker_rows_shift_ok": marker_rows_shift_ok,
            "marker_shift_ok": shift_ok,
            "current": gap_ok and marker_required and marker_counts_ok and marker_mappings_ok and a1_gap_ok and shift_ok,
        }
    )
    return status


def a1_dialogue_audit_status() -> dict:
    status = {
        "exists": A1_DIALOGUE_AUDIT_REPORT.exists(),
        "current": False,
        "pass": False,
    }
    if not A1_DIALOGUE_AUDIT_REPORT.exists():
        status["reason"] = "missing_a1_dialogue_audit_report"
        return status
    try:
        report = read_json(A1_DIALOGUE_AUDIT_REPORT)
    except Exception as exc:
        status["reason"] = f"unreadable_a1_dialogue_audit_report: {exc}"
        return status
    finding_count = int(report.get("finding_count") or 0)
    report_status = str(report.get("status") or "")
    status.update(
        {
            "report_status": report_status,
            "finding_count": finding_count,
            "transcript": report.get("transcript"),
            "current": report_status == "pass" and finding_count == 0,
            "pass": report_status == "pass" and finding_count == 0,
        }
    )
    return status


def narrative_output_status() -> dict:
    error = artifact_validation_error("narrative_output", NARRATIVE_OUTPUT)
    return {
        "exists": NARRATIVE_OUTPUT.exists(),
        "valid": error is None,
        "path": str(NARRATIVE_OUTPUT),
        "reason": error,
    }


def require_valid_narrative_output(stage: str) -> None:
    error = artifact_validation_error("narrative_output", NARRATIVE_OUTPUT)
    if not error:
        return
    stop_for_user(
        stage,
        "Narrative LLM review output is required before downstream cut candidate stages and is invalid/incomplete.",
        missing=[f"{NARRATIVE_OUTPUT} ({error})"],
        options=[
            "Rerun the orchestrator narrative-llm-review step and save a valid non-empty JSON array.",
            "Regenerate the narrative prompt if the transcript/clip index is stale, then rerun narrative-llm-review.",
            "Stop here and explicitly approve a named fallback policy before any downstream cut stages run.",
        ],
    )


def stage_cache_complete(stage: str) -> bool:
    outputs = STAGE_OUTPUTS.get(stage, [])
    if stage in NARRATIVE_OUTPUT_DEPENDENT_STAGES and artifact_validation_error("narrative_output", NARRATIVE_OUTPUT):
        return False
    if outputs and not stage_outputs_exist(stage):
        return False
    if stage == "a1-dialogue-audit" and not a1_dialogue_audit_status().get("pass"):
        return False
    path = stage_cache_path(stage)
    if not path.exists():
        if stage in INTRO_GAP_DEPENDENT_STAGES and not intro_outro_report_status().get("current"):
            return False
        return bool(outputs) and stage_outputs_exist(stage) and stage_dependencies_fresh(stage, outputs, path)
    try:
        payload = read_json(path)
    except Exception:
        return False
    if stage in OUTPUT_EXISTENCE_CACHE_STAGES and bool(outputs) and stage_dependencies_fresh(stage, outputs, path):
        return True
    if payload.get("status") not in {"complete", "warning", "cached"}:
        return False
    if stage in INTRO_GAP_DEPENDENT_STAGES and not intro_outro_report_status().get("current"):
        return False
    if not stage_dependencies_fresh(stage, outputs, path):
        return False
    return bool(outputs) or stage in CACHE_ONLY_STAGES


def stop_for_user(stage: str, reason: str, *, missing: list[str] | None = None, options: list[str] | None = None) -> None:
    missing = missing or []
    options = options or [
        "Fix or provide the missing asset/data, then rerun this same orchestrator step.",
        "Update the active project profile in the orchestrator GUI if the path or setting is wrong.",
        "Explicitly tell the agent which alternate artifact or fallback policy you want used.",
    ]
    payload = {
        "schema": "rby_umb_orchestrator_stop_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "reason": reason,
        "missing": missing,
        "options": options,
        "next_action": "Ask the user which option to use before continuing.",
    }
    write_json(PIPELINE_STOP_REPORT, payload)
    lines = [
        f"STOP: Stage {stage!r} cannot continue autonomously.",
        f"Reason: {reason}",
    ]
    if missing:
        lines.append("Missing required asset/data:")
        lines.extend(f"  - {item}" for item in missing)
    lines.append("Ask the user how to proceed:")
    lines.extend(f"  {index}. {option}" for index, option in enumerate(options, 1))
    lines.append(f"Stop report: {PIPELINE_STOP_REPORT}")
    raise PipelineStop("\n".join(lines))


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def active_profile_parameters() -> dict:
    config_path = Path(os.environ.get("ORCHESTRATOR_CONFIG_PATH") or DEFAULT_WORKFLOW_CONFIG)
    profile_id = os.environ.get("ORCHESTRATOR_PROFILE_ID") or DEFAULT_PROFILE_ID
    if not config_path.exists():
        return {}
    try:
        data = read_json(config_path)
    except Exception as exc:
        print(f"WARN: could not read orchestrator config for profile flags: {config_path}: {exc}")
        return {}
    for profile in data.get("profiles", []):
        if profile.get("id") == profile_id:
            return dict(profile.get("parameters") or {})
    return {}


def profile_source_audio_offset_args() -> list[str]:
    """Return --source-audio-offset values from profile parameters.

    Split source captures are combined into one game-audio bridge WAV. The BGM
    pass needs the original V1 source file -> combined-WAV frame offset map so
    gameplay bridges stay sample-aligned after the final rebuild.
    """
    rows: list[str] = []
    raw_offsets = M.PROFILE.get("source_audio_offsets")
    if isinstance(raw_offsets, list):
        rows.extend(str(item) for item in raw_offsets if str(item).strip())
    elif isinstance(raw_offsets, str) and raw_offsets.strip():
        try:
            parsed = json.loads(raw_offsets)
        except json.JSONDecodeError:
            parsed = [part.strip() for part in raw_offsets.split(";") if part.strip()]
        if isinstance(parsed, list):
            rows.extend(str(item) for item in parsed if str(item).strip())
        else:
            rows.append(str(parsed))

    for key, value in sorted(M.PROFILE.items()):
        if key.startswith("source_audio_offset_") and value:
            rows.append(str(value))

    deduped: list[str] = []
    seen: set[str] = set()
    for row in rows:
        row = row.strip()
        if not row or "=" not in row:
            continue
        if row.lower() in seen:
            continue
        deduped.append(row)
        seen.add(row.lower())
    return deduped


def cut_candidate_flags() -> list[str]:
    params = active_profile_parameters()
    flags: list[str] = []
    if truthy(params.get("livestream_edit_mode")):
        flags.append("--livestream-edit")
    if truthy(params.get("livestream_cut_chat_interactions")):
        flags.append("--livestream-cut-chat-interactions")
    if truthy(params.get("livestream_bypass_gameplay_narrative_cuts")):
        flags.append("--bypass-gameplay-narrative-cuts")
    return flags


def safe_decision_filename_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in value).strip(" ._")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned or "cut_review"


def decision_filename_for_clips(clips_data: dict) -> str:
    source_video = clips_data.get("source_video") if isinstance(clips_data, dict) else ""
    stem = Path(source_video).stem if source_video else "cut_review"
    return f"{safe_decision_filename_stem(stem)}_cut_review_decisions.json"


def html_decision_file_candidates() -> list[Path]:
    candidates = [HTML_DECISIONS]
    if not HTML_CLIPS.exists():
        return candidates
    try:
        clips_data = read_json(HTML_CLIPS)
    except Exception:
        return candidates
    filename = decision_filename_for_clips(clips_data)
    candidates.append(HTML_DECISIONS.parent / filename)
    source_video = clips_data.get("source_video") if isinstance(clips_data, dict) else ""
    if source_video:
        source_path = Path(source_video)
        candidates.append(source_path.parent / filename)
        candidates.append(source_path.parent / "pink_decisions.json")
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            deduped.append(candidate)
            seen.add(key)
    return deduped


def resolve_html_decisions_path() -> Path | None:
    existing = [path for path in html_decision_file_candidates() if path.exists()]
    if not existing:
        return None
    chosen = max(existing, key=lambda path: path.stat().st_mtime)
    if chosen.resolve() != HTML_DECISIONS.resolve():
        HTML_DECISIONS.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(chosen, HTML_DECISIONS)
        print(f"Using review decisions from {chosen}; copied to {HTML_DECISIONS}")
    return HTML_DECISIONS


def require(paths: list[Path], stage: str) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        stop_for_user(
            stage,
            "Required input artifact(s) are missing.",
            missing=missing,
        )


def connect():
    import _resolve_env  # noqa: F401
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError(
            "Could not connect to DaVinci Resolve. Check Resolve is open and "
            "Preferences > General > External scripting using is set to Local."
        )
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        raise RuntimeError("No current Resolve project")
    return resolve, project


def set_current_timeline(name: str):
    _resolve, project = connect()
    for i in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(i)
        if timeline and (timeline.GetName() or "") == name:
            project.SetCurrentTimeline(timeline)
            return timeline
    raise RuntimeError(f"Timeline not found in Resolve: {name}")


def timeline_from_manifest(path: Path, fallback: str) -> str:
    if not path.exists():
        return fallback
    data = read_json(path)
    return data.get("resolve_import", {}).get("timeline") or data.get("timeline_name") or fallback


def select_base_timeline(preferred_name: str, fallback_name: str):
    _resolve, project = connect()
    names_to_try = [preferred_name, fallback_name]
    for name in list(names_to_try):
        if "orchestrator final base" in name:
            names_to_try.append(name.replace("orchestrator final base", "final rebuild base"))
        if "CODEx final rebuild base" in name and "RBY UMB" not in name:
            names_to_try.append(name.replace("CODEx final rebuild base", "RBY UMB CODEx final rebuild base"))

    seen: set[str] = set()
    for name in names_to_try:
        if not name or name in seen:
            continue
        seen.add(name)
        for i in range(1, int(project.GetTimelineCount() or 0) + 1):
            timeline = project.GetTimelineByIndex(i)
            if timeline and (timeline.GetName() or "") == name:
                project.SetCurrentTimeline(timeline)
                return timeline

    candidates = []
    for i in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(i)
        if not timeline:
            continue
        name = timeline.GetName() or ""
        if "(edit)" in name or "(gen1 intros)" in name:
            continue
        if "final rebuild base" in name or "final base" in name:
            candidates.append(timeline)
    if candidates:
        candidates.sort(key=lambda tl: tl.GetName() or "")
        selected = candidates[-1]
        project.SetCurrentTimeline(selected)
        return selected

    raise RuntimeError(
        "Timeline not found in Resolve. Tried: "
        + ", ".join(repr(name) for name in seen)
    )


def timeline_shape_score(name: str, base_name: str) -> tuple[int, str]:
    """Prefer the deterministic finished shape over earlier faulty rebuilds."""
    if name == base_name:
        return (0, name)
    if not name.startswith(base_name):
        return (-1, name)
    has_structural = "(edit)" in name
    has_gen1 = "(gen1 intros)" in name
    structural_before_gen1 = name.find("(edit)") != -1 and (
        name.find("(gen1 intros)") == -1 or name.find("(edit)") < name.find("(gen1 intros)")
    )
    gen1_before_structural = name.find("(gen1 intros)") != -1 and (
        name.find("(edit)") == -1 or name.find("(gen1 intros)") < name.find("(edit)")
    )
    score = 1
    if has_structural:
        score += 10
    if has_gen1:
        score += 20
    if structural_before_gen1:
        score += 30
    if gen1_before_structural:
        score -= 30
    return (score, name)


def select_structural_timeline(base_name: str):
    _resolve, project = connect()
    current = project.GetCurrentTimeline()
    if current:
        current_name = current.GetName() or ""
        if current_name.startswith(base_name) and "(edit)" in current_name and "(gen1 intros)" not in current_name:
            return current

    candidates = []
    for i in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(i)
        if not timeline:
            continue
        name = timeline.GetName() or ""
        if name.startswith(base_name) and "(edit)" in name and "(gen1 intros)" not in name:
            candidates.append(timeline)
    if candidates:
        candidates.sort(key=lambda tl: timeline_shape_score(tl.GetName() or "", base_name))
        selected = candidates[-1]
        project.SetCurrentTimeline(selected)
        return selected
    return set_current_timeline(base_name)


def select_finished_timeline(base_name: str):
    _resolve, project = connect()
    current = project.GetCurrentTimeline()
    if current:
        current_name = current.GetName() or ""
        if current_name.startswith(base_name) and "(edit)" in current_name and "(gen1 intros)" in current_name:
            if current_name.find("(edit)") < current_name.find("(gen1 intros)"):
                return current

    candidates = []
    for i in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(i)
        if not timeline:
            continue
        name = timeline.GetName() or ""
        if name == base_name or name.startswith(base_name + " "):
            candidates.append(timeline)
    if not candidates:
        raise RuntimeError(f"No final timeline found with base name: {base_name}")
    candidates.sort(key=lambda tl: timeline_shape_score(tl.GetName() or "", base_name))
    selected = candidates[-1]
    project.SetCurrentTimeline(selected)
    return selected


def resolve_clip_source_path(item) -> str:
    try:
        mpi = item.GetMediaPoolItem()
    except Exception:
        mpi = None
    if mpi is None:
        return ""
    try:
        return mpi.GetClipProperty("File Path") or ""
    except Exception:
        return ""


def is_intro_like_video(item) -> bool:
    name = (item.GetName() or "").lower()
    path = resolve_clip_source_path(item).replace("\\", "/").lower()
    return (
        "intro" in name
        or "__2x_resolve" in name
        or "retimed-gen1-intros" in path
        or "/gymleaders/leaderintros/" in path
    )


def intro_video_a1_overlaps(timeline) -> list[dict]:
    videos = []
    for track in range(1, int(timeline.GetTrackCount("video") or 0) + 1):
        for item in timeline.GetItemListInTrack("video", track) or []:
            if is_intro_like_video(item):
                videos.append((track, item))
    a1_items = timeline.GetItemListInTrack("audio", 1) or []
    overlaps = []
    for track, video in videos:
        v0 = video.GetStart()
        v1 = v0 + video.GetDuration()
        for audio in a1_items:
            a0 = audio.GetStart()
            a1 = a0 + audio.GetDuration()
            if v0 < a1 and a0 < v1:
                overlaps.append({
                    "video_track": track,
                    "video": video.GetName() or "",
                    "video_start": v0,
                    "video_end": v1,
                    "audio": audio.GetName() or "",
                    "audio_start": a0,
                    "audio_end": a1,
                })
    return overlaps


def carousel_marker_name(timeline) -> str | None:
    for _rel, data in (timeline.GetMarkers() or {}).items():
        marker_parts = {
            part.strip().lower()
            for part in (data.get("name") or "").split("/")
            if part.strip()
        }
        if marker_parts & {"member carousel start", "member carousel", "final tierlist closed"}:
            return data.get("name") or ""
    return None


def mark_state(stage: str, status: str, **extra) -> None:
    state = {}
    if PIPELINE_STATE.exists():
        state = read_json(PIPELINE_STATE)
    record = {
        "stage": stage,
        "status": status,
        "at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    state.setdefault("history", []).append(
        record
    )
    state["last_stage"] = stage
    state["last_status"] = status
    write_json(PIPELINE_STATE, state)
    cache_payload = {
        "schema": "rby_umb_stage_cache_v1",
        **record,
        "outputs": [str(path) for path in STAGE_OUTPUTS.get(stage, [])],
    }
    write_json(stage_cache_path(stage), cache_payload)


def artifact_status() -> dict:
    carousel_marker = None
    intro_overlap_count = None
    current_timeline = None
    track_counts = None
    intro_gap_status = intro_outro_report_status()
    a1_audit_status = a1_dialogue_audit_status()
    narrative_status = narrative_output_status()
    try:
        _resolve, project = connect()
        timeline = project.GetCurrentTimeline()
        if timeline:
            current_timeline = timeline.GetName()
            track_counts = {
                "v1": len(timeline.GetItemListInTrack("video", 1) or []),
                "v2": len(timeline.GetItemListInTrack("video", 2) or []),
                "a1": len(timeline.GetItemListInTrack("audio", 1) or []),
                "a2": len(timeline.GetItemListInTrack("audio", 2) or []),
                "a3": len(timeline.GetItemListInTrack("audio", 3) or []),
            }
            intro_overlap_count = len(intro_video_a1_overlaps(timeline))
            carousel_marker = carousel_marker_name(timeline)
    except Exception as exc:
        current_timeline = f"Resolve unavailable: {exc}"

    return {
        "review_manifest": REVIEW_MANIFEST.exists(),
        "narrative_prompt": NARRATIVE_PROMPT.exists(),
        "narrative_clip_index": NARRATIVE_CLIP_INDEX.exists(),
        "narrative_output": narrative_status["valid"],
        "narrative_output_status": narrative_status,
        "waveform_candidates": WAVEFORM_CANDIDATES.exists(),
        "ngram_candidates": NGRAM_CANDIDATES.exists(),
        "artifact_candidates": ARTIFACT_CANDIDATES.exists(),
        "programmatic_candidates": PROGRAMMATIC_CANDIDATES.exists(),
        "cut_candidates": CUT_CANDIDATES.exists(),
        "html_decisions": HTML_DECISIONS.exists(),
        "html_auto_segmap": HTML_AUTO_SEGMAP.exists(),
        "html_structural_segmap": HTML_STRUCTURAL_SEGMAP.exists(),
        "native_normalized_ranges": NATIVE_NORMALIZED.exists(),
        "approved_narrative": APPROVED_NARRATIVE.exists(),
        "approved_source_cuts": APPROVED_SOURCE_CUTS.exists(),
        "final_manifest": FINAL_MANIFEST.exists(),
        "a1_dialogue_audit_report": A1_DIALOGUE_AUDIT_REPORT.exists(),
        "a1_dialogue_audit": a1_audit_status,
        "a1_dialogue_audit_pass": a1_audit_status.get("pass"),
        "intro_outro_report": INTRO_OUTRO_REPORT.exists(),
        "gen1_intros_report": GEN1_INTROS_REPORT.exists(),
        "game_audio": GAME_AUDIO.exists(),
        "bgm_report": BGM_REPORT.exists(),
        "clip_color_report": CLIP_COLOR_REPORT.exists(),
        "fairlight_report": FAIRLIGHT_REPORT.exists(),
        "audio_normalization_instructions": AUDIO_NORMALIZATION_INSTRUCTIONS.exists(),
        "post_intro_gap": intro_gap_status,
        "post_intro_gap_current": intro_gap_status.get("current"),
        "carousel_layout_complete": stage_cache_complete("carousel"),
        "current_timeline": current_timeline,
        "track_counts": track_counts,
        "intro_video_a1_overlap_count": intro_overlap_count,
        "carousel_marker_on_current_timeline": carousel_marker,
    }


def require_orchestrator_profile() -> None:
    if M.ACTIVE_PROFILE_ID:
        return
    stop_for_user(
        "profile",
        "No orchestrator profile is active. This runner is intentionally profile-driven so it does not fall back to an old project.",
        options=[
            "Run this through the orchestrator GUI.",
            "Run scripts/orchestrator_run.py with --profile <profile_id>.",
            "Set ORCHESTRATOR_PROFILE_ID and ORCHESTRATOR_CONFIG_PATH before invoking this runner directly.",
        ],
    )


def run_cached_stage(args: argparse.Namespace, stage: str, func) -> int | None:
    if stage in NARRATIVE_OUTPUT_DEPENDENT_STAGES and stage != "validate-order":
        require_valid_narrative_output(stage)
    if getattr(args, "reuse_cache", True) and not args.force and stage_cache_complete(stage):
        print(f"Cache hit for stage {stage!r}; outputs already exist.")
        mark_state(stage, "cached", cache=str(stage_cache_path(stage)))
        return 0
    mark_state(stage, "running")
    try:
        result = func(args)
    except Exception as exc:
        mark_state(stage, "failed", error=str(exc))
        raise
    if stage in STAGE_OUTPUTS and not stage_outputs_exist(stage):
        missing = [str(path) for path in STAGE_OUTPUTS[stage] if not path.exists()]
        mark_state(stage, "stopped", missing=missing)
        stop_for_user(stage, "The stage finished but did not produce its declared output artifact(s).", missing=missing)
    if not isinstance(result, int) or result == 0:
        mark_state(stage, "complete", cache=str(stage_cache_path(stage)))
    return result


def stage_review_base(args: argparse.Namespace) -> None:
    run(
        [
            sys.executable,
            SCRIPT_DIR / "build_rby_umb_fcpxml.py",
            "--review-base",
        ]
    )
    mark_state("review-base", "complete", manifest=str(REVIEW_MANIFEST))


def stage_narrative_prompt(args: argparse.Namespace) -> None:
    require([REVIEW_MANIFEST], "narrative-prompt")
    cmd = [
        sys.executable,
        SCRIPT_DIR / "generate_rby_umb_cut_candidates.py",
        "--stage",
        "narrative-prompt",
        "--manifest",
        REVIEW_MANIFEST,
    ]
    cmd.extend(cut_candidate_flags())
    run(
        cmd
    )
    mark_state("narrative-prompt", "complete", prompt=str(NARRATIVE_PROMPT), clip_index=str(NARRATIVE_CLIP_INDEX))


def stage_programmatic_candidates(args: argparse.Namespace) -> None:
    require([REVIEW_MANIFEST], "programmatic-candidates")
    require_valid_narrative_output("programmatic-candidates")
    cmd = [
        sys.executable,
        SCRIPT_DIR / "generate_rby_umb_cut_candidates.py",
        "--stage",
        "programmatic-candidates",
        "--manifest",
        REVIEW_MANIFEST,
    ]
    cmd.extend(cut_candidate_flags())
    run(
        cmd
    )
    mark_state(
        "programmatic-candidates",
        "complete",
        waveform=str(WAVEFORM_CANDIDATES),
        ngram=str(NGRAM_CANDIDATES),
        artifacts=str(ARTIFACT_CANDIDATES),
        combined=str(PROGRAMMATIC_CANDIDATES),
    )


def stage_compile_cut_candidates(args: argparse.Namespace) -> None:
    require_valid_narrative_output("compile-cut-candidates")
    require(
        [REVIEW_MANIFEST, WAVEFORM_CANDIDATES, NGRAM_CANDIDATES, ARTIFACT_CANDIDATES, PROGRAMMATIC_CANDIDATES],
        "compile-cut-candidates",
    )
    cmd = [
        sys.executable,
        SCRIPT_DIR / "generate_rby_umb_cut_candidates.py",
        "--stage",
        "compile",
        "--manifest",
        REVIEW_MANIFEST,
    ]
    cmd.extend(cut_candidate_flags())
    run(cmd)
    mark_state("compile-cut-candidates", "complete", manifest=str(CUT_CANDIDATES))


def stage_cut_candidates(args: argparse.Namespace) -> None:
    """Legacy alias: build prompt, then finish candidate compile only after valid LLM output."""
    stage_narrative_prompt(args)
    require_valid_narrative_output("cut-candidates")
    stage_programmatic_candidates(args)
    stage_compile_cut_candidates(args)


def stage_apply_html_decisions(args: argparse.Namespace) -> None:
    require([CUT_CANDIDATES, HTML_CLIPS, HTML_SEGMAP], "apply-html-decisions")
    decisions_path = resolve_html_decisions_path()
    if not decisions_path:
        manifest = read_json(CUT_CANDIDATES)
        medium = manifest.get("medium_confidence_review_candidates") or manifest.get("review_candidates") or []
        auto = manifest.get("high_confidence_auto_cuts") or manifest.get("auto_cut_candidates") or []
        structural = manifest.get("structural_review_groups") or []
        clips_data = read_json(HTML_CLIPS)
        suggested_name = decision_filename_for_clips(clips_data)
        if medium or auto or structural:
            raise RuntimeError(
                "Cut candidates require HTML review before this stage can run. "
                f"Open {CUT_REVIEW_DIR / 'review' / 'index.html'}, review the Manual, Automatic, and Structural tabs, "
                f"save {suggested_name} beside the source video or place a copy at {HTML_DECISIONS}."
            )
        NATIVE_APPLIED_DIR.mkdir(parents=True, exist_ok=True)
        write_json(
            NATIVE_NORMALIZED,
            {
                "schema": "rby_umb_offline_html_review_decisions_v1",
                "whole_cut_indices": [],
                "partial_records": [],
                "auto_whole_restore_indices": [],
                "auto_restore_records": [],
                "auto_restore_source_ranges": [],
                "raw_ranges": [],
                "merged_ranges": [],
                "total_cut_frames": 0,
                "total_auto_restore_frames": 0,
                "note": "No medium-confidence candidates required HTML review.",
            },
        )
        print(f"No medium-confidence review candidates; wrote empty HTML-decision normalization: {NATIVE_NORMALIZED}")
        mark_state("apply-html-decisions", "complete", normalized=str(NATIVE_NORMALIZED), offline=True, empty=True)
        return
    decisions = read_json(decisions_path)
    if decisions.get("dry_run_auto_approved") and (
        any(value == "cut" for value in (decisions.get("pink") or {}).values())
        or any((decisions.get("cuts") or {}).values())
    ):
        raise RuntimeError(
            "Refusing dry-run auto-approved HTML decisions. The review page contains "
            "medium-confidence and partial-section cut leads, so a generated "
            "'cut every Pink section' file must not flow into approved source cuts. "
            f"Open {CUT_REVIEW_DIR / 'review' / 'index.html'}, make the review "
            f"decisions manually, save a fresh pink_decisions.json without "
            f"dry_run_auto_approved=true, then rerun apply-html-decisions."
        )
    clips_data = read_json(HTML_CLIPS)
    segmap = read_json(HTML_SEGMAP)
    auto_segmap = read_json(HTML_AUTO_SEGMAP) if HTML_AUTO_SEGMAP.exists() else {}
    structural_segmap = read_json(HTML_STRUCTURAL_SEGMAP) if HTML_STRUCTURAL_SEGMAP.exists() else {}
    _merged, metadata = compile_html_decision_cuts(decisions, clips_data, segmap, 60.0, auto_segmap, structural_segmap)
    NATIVE_APPLIED_DIR.mkdir(parents=True, exist_ok=True)
    write_json(NATIVE_NORMALIZED, metadata)
    print(f"Wrote offline normalized HTML review decisions: {NATIVE_NORMALIZED}")
    mark_state("apply-html-decisions", "complete", normalized=str(NATIVE_NORMALIZED), offline=True)


def review_clip_by_index(clips_data: dict) -> dict[int, dict]:
    clips = clips_data.get("clips", clips_data if isinstance(clips_data, list) else [])
    return {int(item["i"]): item for item in clips if "i" in item}


def merge_timeline_ranges(ranges: list[dict]) -> list[dict]:
    ordered = sorted(ranges, key=lambda item: (int(item["start"]), int(item["end"]), item.get("source", "")))
    merged: list[dict] = []
    for item in ordered:
        if int(item["end"]) <= int(item["start"]):
            continue
        if not merged or int(item["start"]) > int(merged[-1]["end"]):
            merged.append({**item, "sources": [item]})
            continue
        merged[-1]["end"] = max(int(merged[-1]["end"]), int(item["end"]))
        merged[-1]["sources"].append(item)
    return merged


def subtract_timeline_restores(cut: dict, restores: list[dict]) -> list[dict]:
    fragments = [(int(cut["start"]), int(cut["end"]))]
    for restore in restores:
        restore_start = int(restore["start"])
        restore_end = int(restore["end"])
        next_fragments: list[tuple[int, int]] = []
        for start, end in fragments:
            overlap_start = max(start, restore_start)
            overlap_end = min(end, restore_end)
            if overlap_end <= overlap_start:
                next_fragments.append((start, end))
                continue
            if start < overlap_start:
                next_fragments.append((start, overlap_start))
            if overlap_end < end:
                next_fragments.append((overlap_end, end))
        fragments = next_fragments
    output = []
    for index, (start, end) in enumerate(fragments):
        if end <= start:
            continue
        row = {**cut, "start": start, "end": end}
        if len(fragments) > 1:
            row["fragment_index"] = index + 1
        output.append(row)
    return output


def source_seconds_to_timeline_frame(clip: dict, source_sec: float, timeline_fps: float) -> int:
    clip_fps = float(clip.get("fps") or timeline_fps)
    source_frame = int(round(source_sec * clip_fps))
    local_source_frames = source_frame - int(clip["left"])
    local_timeline_frames = int(round(local_source_frames * timeline_fps / clip_fps))
    return int(clip["start"]) + local_timeline_frames


def compile_html_decision_cuts(
    decisions: dict,
    clips_data: dict,
    segmap: dict,
    timeline_fps: float,
    auto_segmap: dict | None = None,
    structural_segmap: dict | None = None,
) -> tuple[list[dict], dict]:
    clips_by_i = review_clip_by_index(clips_data)
    raw_ranges: list[dict] = []
    whole_cut_indices = sorted(int(index) for index, value in (decisions.get("pink") or {}).items() if value == "cut")
    for clip_i in whole_cut_indices:
        clip = clips_by_i.get(clip_i)
        if not clip:
            raise RuntimeError(f"Decision references missing review clip index {clip_i}")
        raw_ranges.append({
            "start": int(clip["start"]),
            "end": int(clip["start"]) + int(clip["dur"]),
            "source": "pink_whole_cut",
            "clip_i": clip_i,
            "clip": clip,
        })

    partial_records: list[dict] = []
    for group, ranges in (decisions.get("cuts") or {}).items():
        segments = segmap.get(str(group), [])
        for cut_index, pair in enumerate(ranges):
            snip_start, snip_end = float(pair[0]), float(pair[1])
            if snip_end <= snip_start:
                continue
            for segment in segments:
                overlap_start = max(snip_start, float(segment["snip_start"]))
                overlap_end = min(snip_end, float(segment["snip_end"]))
                if overlap_end <= overlap_start:
                    continue
                clip_i = int(segment["clip_idx"])
                clip = clips_by_i.get(clip_i)
                if not clip:
                    raise RuntimeError(f"Segmap references missing review clip index {clip_i}")
                source_start = float(segment["src_start"]) + (overlap_start - float(segment["snip_start"]))
                source_end = float(segment["src_start"]) + (overlap_end - float(segment["snip_start"]))
                frame_start = source_seconds_to_timeline_frame(clip, source_start, timeline_fps)
                frame_end = source_seconds_to_timeline_frame(clip, source_end, timeline_fps)
                if frame_end <= frame_start:
                    frame_end = frame_start + 1
                record = {
                    "start": frame_start,
                    "end": frame_end,
                    "source": "drag_cut",
                    "group": str(group),
                    "cut_index": cut_index,
                    "clip_i": clip_i,
                    "kind": segment.get("kind"),
                    "source_start_sec": round(source_start, 4),
                    "source_end_sec": round(source_end, 4),
                    "snip_start": overlap_start,
                    "snip_end": overlap_end,
                    "clip": clip,
                }
                raw_ranges.append(record)
                partial_records.append(record)

    auto_segmap = auto_segmap or {}
    auto_whole_restore_indices = sorted(
        int(index)
        for index, value in (decisions.get("auto") or {}).items()
        if value in {"restore", "keep"}
    )
    auto_restore_records: list[dict] = []
    for clip_i in auto_whole_restore_indices:
        clip = clips_by_i.get(clip_i)
        if not clip:
            raise RuntimeError(f"Auto decision references missing review clip index {clip_i}")
        auto_restore_records.append({
            "start": int(clip["start"]),
            "end": int(clip["start"]) + int(clip["dur"]),
            "source": "auto_whole_restore",
            "clip_i": clip_i,
            "clip": clip,
        })

    for group, ranges in (decisions.get("restores") or {}).items():
        segments = auto_segmap.get(str(group), [])
        for restore_index, pair in enumerate(ranges):
            snip_start, snip_end = float(pair[0]), float(pair[1])
            if snip_end <= snip_start:
                continue
            for segment in segments:
                if segment.get("kind") != "auto":
                    continue
                overlap_start = max(snip_start, float(segment["snip_start"]))
                overlap_end = min(snip_end, float(segment["snip_end"]))
                if overlap_end <= overlap_start:
                    continue
                clip_i = int(segment["clip_idx"])
                clip = clips_by_i.get(clip_i)
                if not clip:
                    raise RuntimeError(f"Auto segmap references missing review clip index {clip_i}")
                source_start = float(segment["src_start"]) + (overlap_start - float(segment["snip_start"]))
                source_end = float(segment["src_start"]) + (overlap_end - float(segment["snip_start"]))
                frame_start = source_seconds_to_timeline_frame(clip, source_start, timeline_fps)
                frame_end = source_seconds_to_timeline_frame(clip, source_end, timeline_fps)
                if frame_end <= frame_start:
                    frame_end = frame_start + 1
                auto_restore_records.append({
                    "start": frame_start,
                    "end": frame_end,
                    "source": "auto_drag_restore",
                    "group": str(group),
                    "restore_index": restore_index,
                    "clip_i": clip_i,
                    "kind": segment.get("kind"),
                    "source_start_sec": round(source_start, 4),
                    "source_end_sec": round(source_end, 4),
                    "snip_start": overlap_start,
                    "snip_end": overlap_end,
                    "clip": clip,
                })

    structural_segmap = structural_segmap or {}
    structural_clip_indices = sorted(
        {
            int(segment["clip_idx"])
            for segments in structural_segmap.values()
            for segment in segments
            if segment.get("kind") == "structural" and "clip_idx" in segment
        }
    )
    structural_decisions = decisions.get("structural") or {}
    structural_whole_restore_indices = sorted(
        int(index)
        for index, value in structural_decisions.items()
        if value in {"restore", "keep"}
    )
    structural_restore_records: list[dict] = []
    for clip_i in structural_whole_restore_indices:
        clip = clips_by_i.get(clip_i)
        if not clip:
            raise RuntimeError(f"Structural decision references missing review clip index {clip_i}")
        structural_restore_records.append({
            "start": int(clip["start"]),
            "end": int(clip["start"]) + int(clip["dur"]),
            "source": "structural_whole_restore",
            "clip_i": clip_i,
            "clip": clip,
        })

    for group, ranges in (decisions.get("structural_restores") or {}).items():
        segments = structural_segmap.get(str(group), [])
        for restore_index, pair in enumerate(ranges):
            snip_start, snip_end = float(pair[0]), float(pair[1])
            if snip_end <= snip_start:
                continue
            for segment in segments:
                if segment.get("kind") != "structural":
                    continue
                overlap_start = max(snip_start, float(segment["snip_start"]))
                overlap_end = min(snip_end, float(segment["snip_end"]))
                if overlap_end <= overlap_start:
                    continue
                clip_i = int(segment["clip_idx"])
                clip = clips_by_i.get(clip_i)
                if not clip:
                    raise RuntimeError(f"Structural segmap references missing review clip index {clip_i}")
                source_start = float(segment["src_start"]) + (overlap_start - float(segment["snip_start"]))
                source_end = float(segment["src_start"]) + (overlap_end - float(segment["snip_start"]))
                frame_start = source_seconds_to_timeline_frame(clip, source_start, timeline_fps)
                frame_end = source_seconds_to_timeline_frame(clip, source_end, timeline_fps)
                if frame_end <= frame_start:
                    frame_end = frame_start + 1
                structural_restore_records.append({
                    "start": frame_start,
                    "end": frame_end,
                    "source": "structural_drag_restore",
                    "group": str(group),
                    "restore_index": restore_index,
                    "clip_i": clip_i,
                    "kind": segment.get("kind"),
                    "source_start_sec": round(source_start, 4),
                    "source_end_sec": round(source_end, 4),
                    "snip_start": overlap_start,
                    "snip_end": overlap_end,
                    "clip": clip,
                })

    structural_cut_records: list[dict] = []
    for clip_i in structural_clip_indices:
        if structural_decisions.get(str(clip_i), "cut") in {"restore", "keep"}:
            continue
        clip = clips_by_i.get(clip_i)
        if not clip:
            raise RuntimeError(f"Structural cut references missing review clip index {clip_i}")
        cut_record = {
            "start": int(clip["start"]),
            "end": int(clip["start"]) + int(clip["dur"]),
            "source": "structural_whole_cut",
            "clip_i": clip_i,
            "clip": clip,
        }
        overlapping_restores = [
            restore
            for restore in structural_restore_records
            if int(restore["end"]) > int(cut_record["start"]) and int(restore["start"]) < int(cut_record["end"])
        ]
        for fragment in subtract_timeline_restores(cut_record, overlapping_restores):
            raw_ranges.append(fragment)
            structural_cut_records.append(fragment)

    merged = merge_timeline_ranges(raw_ranges)
    auto_restore_ranges = [source_cut_from_timeline_range(row, timeline_fps) for row in auto_restore_records if row.get("clip")]
    structural_restore_ranges = [source_cut_from_timeline_range(row, timeline_fps) for row in structural_restore_records if row.get("clip")]
    metadata = {
        "schema": "rby_umb_offline_html_review_decisions_v1",
        "dry_run_auto_approved": bool(decisions.get("dry_run_auto_approved")),
        "whole_cut_indices": whole_cut_indices,
        "partial_records": partial_records,
        "auto_whole_restore_indices": auto_whole_restore_indices,
        "auto_restore_records": auto_restore_records,
        "auto_restore_source_ranges": auto_restore_ranges,
        "structural_clip_indices": structural_clip_indices,
        "structural_whole_restore_indices": structural_whole_restore_indices,
        "structural_restore_records": structural_restore_records,
        "structural_restore_source_ranges": structural_restore_ranges,
        "structural_cut_records": structural_cut_records,
        "raw_ranges": raw_ranges,
        "merged_ranges": merged,
        "total_cut_frames": sum(int(item["end"]) - int(item["start"]) for item in merged),
        "total_auto_restore_frames": sum(int(item["end_frame"]) - int(item["start_frame"]) for item in auto_restore_ranges),
        "total_structural_restore_frames": sum(int(item["end_frame"]) - int(item["start_frame"]) for item in structural_restore_ranges),
    }
    return merged, metadata


def source_cut_from_timeline_range(row: dict, timeline_fps: float) -> dict:
    clip = row["clip"]
    clip_fps = float(clip.get("fps") or timeline_fps)
    local_start = int(row["start"]) - int(clip["start"])
    local_end = int(row["end"]) - int(clip["start"])
    start_frame = int(clip["left"]) + int(round(local_start * clip_fps / timeline_fps))
    end_frame = int(clip["left"]) + int(round(local_end * clip_fps / timeline_fps))
    return {
        "label": row.get("source") or "html_review_cut",
        "start_frame": start_frame,
        "end_frame": max(end_frame, start_frame + 1),
        "start_sec": start_frame / clip_fps,
        "end_sec": max(end_frame, start_frame + 1) / clip_fps,
        "reason": f"approved HTML review cut from clip {clip.get('i')}",
        "origin": row,
    }


def assert_no_dry_run_html_approval(stage: str) -> None:
    if not APPROVED_SOURCE_CUTS.exists():
        return
    payload = read_json(APPROVED_SOURCE_CUTS)
    approval_sources = [str(item) for item in payload.get("approval_sources") or []]
    uses_html_normalization = any(str(NATIVE_NORMALIZED) in source for source in approval_sources)
    if not uses_html_normalization:
        return

    metadata = read_json(NATIVE_NORMALIZED) if NATIVE_NORMALIZED.exists() else {}
    decisions = read_json(HTML_DECISIONS) if HTML_DECISIONS.exists() else {}
    if metadata.get("dry_run_auto_approved") or decisions.get("dry_run_auto_approved"):
        raise RuntimeError(
            f"Stage {stage!r} would consume approved source cuts that include "
            "dry-run auto-approved HTML review decisions. Delete/regenerate the "
            "HTML normalization and approved source-cut artifacts after making "
            "manual decisions in the HTML review page."
        )


def merge_source_cuts(rows: list[dict]) -> list[dict]:
    ordered = sorted(rows, key=lambda r: (int(r["start_frame"]), int(r["end_frame"])))
    merged: list[dict] = []
    for row in ordered:
        start = int(row["start_frame"])
        end = int(row["end_frame"])
        if not merged or start > int(merged[-1]["end_frame"]):
            merged.append({**row, "sources": [row]})
            continue
        merged[-1]["end_frame"] = max(int(merged[-1]["end_frame"]), end)
        merged[-1]["end_sec"] = merged[-1]["end_frame"] / M.FPS
        merged[-1]["sources"].append(row)
    return merged


def normalize_source_cut(row: dict, origin: str) -> dict:
    start_frame = row.get("start_frame", row.get("source_start_frame"))
    end_frame = row.get("end_frame", row.get("source_end_frame"))
    if start_frame is None or end_frame is None:
        start_sec = row.get("start_sec", row.get("source_start_sec"))
        end_sec = row.get("end_sec", row.get("source_end_sec"))
        if start_sec is None or end_sec is None:
            raise RuntimeError(f"Approved cut lacks source bounds: {row!r}")
        start_frame = M.source_frame(float(start_sec))
        end_frame = M.source_frame(float(end_sec))
    start_frame = int(round(float(start_frame)))
    end_frame = int(round(float(end_frame)))
    if end_frame <= start_frame:
        raise RuntimeError(f"Approved cut has invalid source bounds: {row!r}")
    return {
        **row,
        "label": row.get("label") or row.get("type") or origin,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "start_sec": start_frame / M.FPS,
        "end_sec": end_frame / M.FPS,
        "origin": origin,
    }


def subtract_source_ranges(cut: dict, restores: list[dict]) -> list[dict]:
    fragments = [(int(cut["start_frame"]), int(cut["end_frame"]))]
    for restore in restores:
        restore_start = int(restore["start_frame"])
        restore_end = int(restore["end_frame"])
        next_fragments: list[tuple[int, int]] = []
        for start, end in fragments:
            overlap_start = max(start, restore_start)
            overlap_end = min(end, restore_end)
            if overlap_end <= overlap_start:
                next_fragments.append((start, end))
                continue
            if start < overlap_start:
                next_fragments.append((start, overlap_start))
            if overlap_end < end:
                next_fragments.append((overlap_end, end))
        fragments = next_fragments
    output = []
    for index, (start, end) in enumerate(fragments):
        if end <= start:
            continue
        suffix = "" if len(fragments) == 1 else f"_part_{index + 1}"
        output.append(
            {
                **cut,
                "label": f"{cut.get('label', 'auto_cut')}{suffix}",
                "start_frame": start,
                "end_frame": end,
                "start_sec": start / M.FPS,
                "end_sec": end / M.FPS,
                "auto_restore_subtracted": bool(restores),
            }
        )
    return output


def stage_compile_approved_cuts(args: argparse.Namespace) -> None:
    require([CUT_CANDIDATES], "compile-approved-cuts")
    rows: list[dict] = []
    approval_sources: list[str] = []

    candidate_manifest = read_json(CUT_CANDIDATES)
    normalized_metadata = read_json(NATIVE_NORMALIZED) if NATIVE_NORMALIZED.exists() else {}
    auto_restore_rows = [
        normalize_source_cut(row, "auto_cut_restore")
        for row in normalized_metadata.get("auto_restore_source_ranges", [])
    ]
    auto_rows = candidate_manifest.get("high_confidence_auto_cuts") or candidate_manifest.get("auto_cut_candidates") or []
    if auto_rows:
        approval_sources.append(f"{CUT_CANDIDATES}:high_confidence_auto_cuts")
        for row in auto_rows:
            if row.get("confidence") != "high" or row.get("disposition") not in {"auto_cut", "auto"}:
                continue
            policy = row.get("section_policy") or {}
            if not policy.get("whole_section"):
                raise RuntimeError(f"High-confidence auto-cut is not FCPXML-section safe: {row!r}")
            auto_cut = normalize_source_cut(row, "high_confidence_auto_cut")
            rows.extend(subtract_source_ranges(auto_cut, auto_restore_rows))

    if NATIVE_NORMALIZED.exists():
        approval_sources.append(str(NATIVE_NORMALIZED))
        metadata = normalized_metadata
        decisions = read_json(HTML_DECISIONS) if HTML_DECISIONS.exists() else {}
        if metadata.get("dry_run_auto_approved") or decisions.get("dry_run_auto_approved"):
            raise RuntimeError(
                "Refusing to compile approved source cuts from dry-run auto-approved "
                "HTML decisions. Re-run apply-html-decisions after saving manual "
                "review decisions from the HTML page."
            )
        timeline_fps = 60.0
        for row in metadata.get("raw_ranges", []):
            if row.get("clip"):
                rows.append(source_cut_from_timeline_range(row, timeline_fps))

    if APPROVED_NARRATIVE.exists():
        approval_sources.append(str(APPROVED_NARRATIVE))
        payload = read_json(APPROVED_NARRATIVE)
        narrative_rows = payload if isinstance(payload, list) else payload.get("cuts", [])
        for row in narrative_rows:
            if row.get("status") in {"reject", "rejected", "keep"}:
                continue
            rows.append(normalize_source_cut(row, "approved_narrative"))

    if not approval_sources and not args.allow_empty_approved_cuts:
        raise RuntimeError(
            "No approved review source exists yet. Create HTML review decisions at "
            f"{HTML_DECISIONS}, or approved narrative cuts at {APPROVED_NARRATIVE}. "
            "Use --allow-empty-approved-cuts only after intentionally approving no extra cuts."
        )

    merged = merge_source_cuts(rows)
    write_json(
        APPROVED_SOURCE_CUTS,
        {
            "schema": "rby_umb_approved_source_cuts_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "Structural restart cuts are included only when approved by the HTML structural review decisions.",
            "approval_sources": approval_sources,
            "source_cuts": merged,
        },
    )
    print(f"Wrote {len(merged)} approved source cut(s): {APPROVED_SOURCE_CUTS}")
    mark_state("compile-approved-cuts", "complete", source_cuts=str(APPROVED_SOURCE_CUTS), count=len(merged))


def stage_final_base(args: argparse.Namespace) -> None:
    require([CUT_CANDIDATES, APPROVED_SOURCE_CUTS], "final-base")
    assert_no_dry_run_html_approval("final-base")
    run(
        [
            sys.executable,
            SCRIPT_DIR / "build_rby_umb_fcpxml.py",
            "--timeline-name",
            FINAL_BASE_NAME,
            "--manifest",
            FINAL_MANIFEST,
            "--extra-source-cuts",
            APPROVED_SOURCE_CUTS,
            "--import-to-resolve",
        ]
    )
    mark_state("final-base", "complete", manifest=str(FINAL_MANIFEST))


def stage_a1_dialogue_audit(args: argparse.Namespace) -> None:
    require([APPROVED_SOURCE_CUTS], "a1-dialogue-audit")
    run_cached_stage(args, "final-base", stage_final_base)
    require([FINAL_MANIFEST], "a1-dialogue-audit")
    run(
        [
            sys.executable,
            SCRIPT_DIR / "audit_fcpxml_a1_dialogue.py",
            "--manifest",
            FINAL_MANIFEST,
            "--audio",
            M.DIALOGUE_PATH,
            "--out",
            A1_DIALOGUE_AUDIT_REPORT,
            "--transcript-dir",
            A1_DIALOGUE_AUDIT_TRANSCRIPT_DIR,
            "--model",
            WHISPER_MODEL,
            "--device",
            WHISPER_DEVICE,
            "--compute-type",
            WHISPER_COMPUTE_TYPE,
            "--fps",
            str(M.FPS),
        ]
    )
    report = read_json(A1_DIALOGUE_AUDIT_REPORT)
    mark_state(
        "a1-dialogue-audit",
        "complete",
        report=str(A1_DIALOGUE_AUDIT_REPORT),
        transcript=report.get("transcript"),
        finding_count=report.get("finding_count", 0),
    )


def stage_structural_intro_outro(args: argparse.Namespace) -> None:
    require([FINAL_MANIFEST], "structural-intro-outro")
    base_timeline = select_base_timeline(timeline_from_manifest(FINAL_MANIFEST, FINAL_BASE_NAME), FINAL_BASE_NAME).GetName()
    cmd = [
        sys.executable,
        SCRIPT_DIR / "insert_intro_outro.py",
        "--game",
        GAME_KEY,
        "--source-timeline",
        base_timeline,
        "--intro-speed",
        str(STRUCTURAL_INTRO_SPEED),
        "--post-intro-gap-sec",
        str(POST_INTRO_GAP_SEC),
        "--report",
        INTRO_OUTRO_REPORT,
    ]
    if POST_INTRO_GAP_SEC > 0:
        cmd.append("--require-markers-for-post-intro-gap")
    run(
        cmd
    )
    mark_state(
        "structural-intro-outro",
        "complete",
        report=str(INTRO_OUTRO_REPORT),
        game_key=GAME_KEY,
        intro_speed=STRUCTURAL_INTRO_SPEED,
        post_intro_gap_sec=POST_INTRO_GAP_SEC,
    )


def stage_gen1_intros(args: argparse.Namespace) -> None:
    require([FINAL_MANIFEST, INTRO_OUTRO_REPORT], "gen1-intros")
    base_timeline = select_base_timeline(timeline_from_manifest(FINAL_MANIFEST, FINAL_BASE_NAME), FINAL_BASE_NAME).GetName()
    select_structural_timeline(base_timeline)
    run(
        [
            sys.executable,
            SCRIPT_DIR / "place_battle_intros.py",
            "--gen1-insert",
            "--gen1-root",
            GEN1_INTRO_ROOT,
            "--gen1-video-track",
            "2",
            "--gen1-speed",
            str(GEN1_INTRO_SPEED),
            "--gen1-battle-audio-track",
            "2",
            "--report",
            GEN1_INTROS_REPORT,
        ]
    )
    mark_state("gen1-intros", "complete", report=str(GEN1_INTROS_REPORT), speed=GEN1_INTRO_SPEED)


def stage_extract_game_audio(args: argparse.Namespace) -> None:
    GAME_AUDIO.parent.mkdir(parents=True, exist_ok=True)
    if GAME_AUDIO.exists() and not args.force:
        print(f"Game audio exists: {GAME_AUDIO}")
        mark_state("extract-game-audio", "complete", game_audio=str(GAME_AUDIO), reused=True)
        return
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            M.VIDEO_PATH,
            "-map",
            GAME_AUDIO_STREAM,
            "-ac",
            "2",
            "-ar",
            "48000",
            GAME_AUDIO,
        ]
    )
    mark_state("extract-game-audio", "complete", game_audio=str(GAME_AUDIO), reused=False)


def stage_bgm(args: argparse.Namespace, dry_run: bool) -> None:
    require([CUT_CANDIDATES, APPROVED_SOURCE_CUTS, GAME_AUDIO], "bgm")
    base_timeline = select_base_timeline(timeline_from_manifest(FINAL_MANIFEST, FINAL_BASE_NAME), FINAL_BASE_NAME).GetName()
    selected = select_finished_timeline(base_timeline)
    cmd = [
        sys.executable,
        SCRIPT_DIR / "place_rby_umb_bgm.py",
        "--game-audio",
        GAME_AUDIO,
        "--bgm-dir",
        BGM_DIR,
        "--leader-audio-dir",
        GEN1_INTRO_ROOT / "audio",
        "--opening-first-source-offset-sec",
        str(OPENING_BGM_OFFSET_SEC),
        "--report",
        BGM_REPORT,
    ]
    for offset in profile_source_audio_offset_args():
        cmd.extend(["--source-audio-offset", offset])
    if dry_run:
        cmd.append("--dry-run")
    run(cmd)
    mark_state(
        "bgm-dry-run" if dry_run else "bgm",
        "complete",
        report=str(BGM_REPORT),
        timeline=selected.GetName(),
        opening_first_source_offset_sec=OPENING_BGM_OFFSET_SEC,
    )


def stage_carousel(args: argparse.Namespace, dry_run: bool) -> None:
    require([CUT_CANDIDATES, APPROVED_SOURCE_CUTS], "carousel")
    cmd = [
        sys.executable,
        SCRIPT_DIR / "layout_carousel.py",
        "--marker-name",
        "Member Carousel Start,Member Carousel,Final Tierlist Closed",
        "--end-at-timeline-end",
    ]
    if dry_run:
        cmd.append("--dry-run")
    run(cmd)
    mark_state("carousel-dry-run" if dry_run else "carousel", "complete")


def stage_find_member_carousel(args: argparse.Namespace) -> None:
    _resolve, project = connect()
    timeline = project.GetCurrentTimeline()
    if timeline:
        marker = carousel_marker_name(timeline)
        if marker:
            print(f"Carousel marker already present on current timeline: {marker!r}")
            mark_state("find-member-carousel", "complete", reused_existing_marker=True, marker=marker)
            return
    run([sys.executable, SCRIPT_DIR / "find_member_carousel.py", "--max-candidates", "30"])
    mark_state("find-member-carousel", "complete")


def stage_clip_colors(args: argparse.Namespace, dry_run: bool = False) -> None:
    require([FINAL_MANIFEST], "clip-colors")
    timeline_name = select_base_timeline(timeline_from_manifest(FINAL_MANIFEST, FINAL_BASE_NAME), FINAL_BASE_NAME).GetName()
    current = select_finished_timeline(timeline_name)
    cmd = [
        sys.executable,
        SCRIPT_DIR / "color_v1_content_sections.py",
        "--timeline",
        current.GetName(),
        "--manifest",
        FINAL_MANIFEST,
        "--report",
        CLIP_COLOR_REPORT,
        "--video-tracks",
        "all",
        "--no-clear",
        "--skip-markers",
        "--summary",
    ]
    if getattr(args, "strict_apply", False):
        cmd.append("--strict-apply")
    if dry_run:
        cmd.append("--dry-run")
    run(cmd)
    color_status = "complete"
    extra: dict[str, object] = {"report": str(CLIP_COLOR_REPORT)}
    if CLIP_COLOR_REPORT.exists() and not dry_run:
        report = read_json(CLIP_COLOR_REPORT)
        extra["clip_color_api_available"] = (report.get("clip_color_probe") or {}).get("available")
        extra["clip_updates_applied"] = report.get("clip_updates_applied", 0)
        extra["clip_updates_failed"] = report.get("clip_updates_failed", 0)
        if report.get("clip_updates_failed", 0):
            color_status = "warning"
    mark_state("clip-colors-dry-run" if dry_run else "clip-colors", color_status, **extra)


def stage_fairlight(args: argparse.Namespace) -> None:
    require([FINAL_MANIFEST, CLIP_COLOR_REPORT], "fairlight")
    timeline_name = select_base_timeline(timeline_from_manifest(FINAL_MANIFEST, FINAL_BASE_NAME), FINAL_BASE_NAME).GetName()
    current = select_finished_timeline(timeline_name)
    run(
        [
            sys.executable,
            SCRIPT_DIR / "apply_fairlight_preset.py",
            "--timeline",
            current.GetName(),
            "--preset",
            FAIRLIGHT_PRESET,
            "--type",
            FAIRLIGHT_PRESET_TYPE,
        ]
    )
    write_json(
        FAIRLIGHT_REPORT,
        {
            "schema": "rby_umb_fairlight_report_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "timeline": current.GetName(),
            "preset": FAIRLIGHT_PRESET,
            "preset_type": FAIRLIGHT_PRESET_TYPE,
            "status": "applied",
        },
    )
    mark_state(
        "fairlight",
        "complete",
        report=str(FAIRLIGHT_REPORT),
        timeline=current.GetName(),
        preset=FAIRLIGHT_PRESET,
        preset_type=FAIRLIGHT_PRESET_TYPE,
    )


def stage_audio_normalization_handoff(args: argparse.Namespace) -> None:
    require([FINAL_MANIFEST, FAIRLIGHT_REPORT], "audio-normalization-handoff")
    timeline_name = select_base_timeline(timeline_from_manifest(FINAL_MANIFEST, FINAL_BASE_NAME), FINAL_BASE_NAME).GetName()
    current = select_finished_timeline(timeline_name)
    tracks = []
    for track_index in range(1, int(current.GetTrackCount("audio") or 0) + 1):
        clips = current.GetItemListInTrack("audio", track_index) or []
        if clips:
            tracks.append({"track": track_index, "clip_count": len(clips)})

    target = f"{AUDIO_NORMALIZATION_TARGET_DB:.1f}"
    track_list = ", ".join(f"A{row['track']}" for row in tracks) or "no populated audio tracks detected"
    a2_row = next((row for row in tracks if row["track"] == 2), None)
    a2_hint = (
        f"A2 is populated ({a2_row['clip_count']} clips); unlock A2 before selection if it is locked."
        if a2_row
        else "A2 is not populated in the API report; inspect the visible timeline before normalization."
    )
    lines = [
        "# Audio Normalization Computer Use Handoff",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Timeline: {current.GetName()}",
        f"Target level: {target} dBFS",
        f"Populated tracks: {track_list}",
        "",
        "## Codex Agent Instructions",
        "",
        "Use Computer Use for this step. Do not use Resolve Python for normalization; Resolve does not expose Normalize Audio Levels through the scripting API.",
        "This is an exact UI procedure. Do not use Ctrl+A, the Resolve top menu, track header selection alone, or any method that selects video clips.",
        "",
        "1. Bring DaVinci Resolve to the foreground and keep the timeline above active.",
        "2. Open the Edit page or Fairlight page.",
        f"3. {a2_hint}",
        "4. Drag-select all audio clips only across the populated audio lanes. Include A1/A2/A3 when populated, but do not include any video clips. If any video clip is selected, clear the selection and redo the audio-only drag selection.",
        "5. Verify the audio clips are still selected. The Inspector should show an audio multi-clip selection, not a video clip or 'Nothing to inspect'.",
        "6. Find the longest visible A2 clip and right-click in the center/body of that selected A2 clip, away from fade handles and clip edges. If the right-click collapses the multi-selection, close the menu and redo the audio-only drag selection before continuing.",
        "7. Click Normalize Audio Levels... from that selected audio clip context menu.",
        "8. Set Normalization Mode to Sample Peak Program.",
        f"9. Set Target Level to {target} dBFS.",
        "10. Use Independent clip reference if Resolve shows the Relative/Independent choice.",
        "11. Click Normalize, then save the Resolve project.",
        "",
        "## Populated Audio Tracks",
        "",
    ]
    if tracks:
        lines.extend(f"- A{row['track']}: {row['clip_count']} clips" for row in tracks)
    else:
        lines.append("- None detected; inspect the timeline manually before rendering.")
    lines.extend(
        [
            "",
            "## Prerequisites",
            "",
            f"- Fairlight preset report: {FAIRLIGHT_REPORT}",
            f"- Final manifest: {FINAL_MANIFEST}",
        ]
    )
    AUDIO_NORMALIZATION_INSTRUCTIONS.parent.mkdir(parents=True, exist_ok=True)
    AUDIO_NORMALIZATION_INSTRUCTIONS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote Computer Use audio-normalization handoff: {AUDIO_NORMALIZATION_INSTRUCTIONS}")
    mark_state(
        "audio-normalization-handoff",
        "complete",
        instructions=str(AUDIO_NORMALIZATION_INSTRUCTIONS),
        timeline=current.GetName(),
        tracks=tracks,
        target_db=AUDIO_NORMALIZATION_TARGET_DB,
    )


def stage_final_assembly(args: argparse.Namespace) -> None:
    require([APPROVED_SOURCE_CUTS, GAME_AUDIO], "final-assembly")
    run_cached_stage(args, "final-base", stage_final_base)
    run_cached_stage(args, "a1-dialogue-audit", stage_a1_dialogue_audit)
    run_cached_stage(args, "structural-intro-outro", stage_structural_intro_outro)
    run_cached_stage(args, "gen1-intros", stage_gen1_intros)
    run_cached_stage(args, "bgm", lambda ns: stage_bgm(ns, dry_run=False))
    run_cached_stage(args, "find-member-carousel", stage_find_member_carousel)
    run_cached_stage(args, "carousel", lambda ns: stage_carousel(ns, dry_run=False))
    run_cached_stage(args, "clip-colors", lambda ns: stage_clip_colors(ns, dry_run=False))
    mark_state(
        "final-assembly",
        "complete",
        manifest=str(FINAL_MANIFEST),
        a1_dialogue_audit_report=str(A1_DIALOGUE_AUDIT_REPORT),
        intro_outro_report=str(INTRO_OUTRO_REPORT),
        gen1_intros_report=str(GEN1_INTROS_REPORT),
        bgm_report=str(BGM_REPORT),
        clip_color_report=str(CLIP_COLOR_REPORT),
    )


def stage_validate_order(args: argparse.Namespace) -> int:
    status = artifact_status()
    missing = []
    for key in (
        "review_manifest",
        "narrative_prompt",
        "narrative_output",
        "programmatic_candidates",
        "cut_candidates",
        "approved_source_cuts",
        "final_manifest",
        "a1_dialogue_audit_report",
        "intro_outro_report",
        "gen1_intros_report",
        "game_audio",
        "bgm_report",
        "clip_color_report",
        "fairlight_report",
        "audio_normalization_instructions",
    ):
        if not status.get(key):
            missing.append(key)
    if not status.get("carousel_marker_on_current_timeline"):
        missing.append("carousel_marker_on_current_timeline")
    if not status.get("carousel_layout_complete"):
        missing.append("carousel_layout_complete")
    if not status.get("post_intro_gap_current"):
        missing.append("post_intro_gap_marker_correspondence")
    if not status.get("a1_dialogue_audit_pass"):
        missing.append("a1_dialogue_audit_pass")
    if status.get("intro_video_a1_overlap_count"):
        missing.append("intro_video_a1_overlap_count_must_be_zero")
    report = {
        "schema": "rby_umb_pipeline_order_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "order": ORDER,
        "status": status,
        "missing_for_finished_timeline": missing,
    }
    write_json(PIPELINE_REPORT, report)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    mark_state("validate-order", "complete" if not missing else "missing", report=str(PIPELINE_REPORT), missing=missing)
    return 2 if args.strict and missing else 0


def stage_plan(args: argparse.Namespace) -> None:
    commands = [
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "review-base"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "narrative-prompt"],
        ["LLM", "narrative-llm-review", str(NARRATIVE_PROMPT), "->", str(NARRATIVE_OUTPUT)],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "programmatic-candidates"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "compile-cut-candidates"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "apply-html-decisions"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "compile-approved-cuts"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "a1-dialogue-audit"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "extract-game-audio"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "structural-intro-outro"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "gen1-intros"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "bgm"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "carousel"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "final-assembly"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "clip-colors"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "fairlight"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "audio-normalization-handoff"],
        [sys.executable, SCRIPT_DIR / "run_rby_umb_pipeline.py", "--stage", "validate-order", "--strict"],
    ]
    report = {
        "order": ORDER,
        "commands": [[str(part) for part in cmd] for cmd in commands],
        "artifacts": artifact_status(),
    }
    plan_path = M.profile_path("pipeline_plan", M.CODEX_DIR / "rby_umb_pipeline_plan.json")
    try:
        write_json(plan_path, report)
    except OSError as exc:
        report["plan_write_warning"] = f"Could not write {plan_path}: {exc}"
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--stage",
        choices=[
            "plan",
            "review-base",
            "narrative-prompt",
            "programmatic-candidates",
            "compile-cut-candidates",
            "cut-candidates",
            "apply-html-decisions",
            "compile-approved-cuts",
            "a1-dialogue-audit",
            "final-base",
            "structural-intro-outro",
            "gen1-intros",
            "extract-game-audio",
            "bgm-dry-run",
            "bgm",
            "carousel-dry-run",
            "carousel",
            "clip-colors-dry-run",
            "clip-colors",
            "fairlight",
            "audio-normalization-handoff",
            "final-assembly",
            "validate-order",
            "all-through-candidates",
        ],
        default="plan",
    )
    parser.add_argument("--strict", action="store_true", help="Make validate-order fail when finished-stage artifacts are missing.")
    parser.add_argument("--force", action="store_true", help="Overwrite stage outputs where supported.")
    parser.add_argument(
        "--no-reuse-cache",
        dest="reuse_cache",
        action="store_false",
        default=True,
        help="Re-run the requested stage even when its cached outputs already exist.",
    )
    parser.add_argument("--strict-apply", action="store_true",
                        help="For clip-colors, fail if Resolve does not actually persist requested clip colors.")
    parser.add_argument("--allow-empty-approved-cuts", action="store_true",
                        help="Allow compile-approved-cuts to write an empty approved source-cut file.")
    args = parser.parse_args()

    require_orchestrator_profile()

    if args.stage == "plan":
        run_cached_stage(args, "plan", stage_plan)
        return 0
    if args.stage == "review-base":
        run_cached_stage(args, "review-base", stage_review_base)
        return 0
    if args.stage == "narrative-prompt":
        run_cached_stage(args, "narrative-prompt", stage_narrative_prompt)
        return 0
    if args.stage == "programmatic-candidates":
        run_cached_stage(args, "programmatic-candidates", stage_programmatic_candidates)
        return 0
    if args.stage == "compile-cut-candidates":
        run_cached_stage(args, "compile-cut-candidates", stage_compile_cut_candidates)
        return 0
    if args.stage == "cut-candidates":
        run_cached_stage(args, "cut-candidates", stage_cut_candidates)
        return 0
    if args.stage == "apply-html-decisions":
        run_cached_stage(args, "apply-html-decisions", stage_apply_html_decisions)
        return 0
    if args.stage == "compile-approved-cuts":
        run_cached_stage(args, "compile-approved-cuts", stage_compile_approved_cuts)
        return 0
    if args.stage == "a1-dialogue-audit":
        run_cached_stage(args, "a1-dialogue-audit", stage_a1_dialogue_audit)
        return 0
    if args.stage == "final-base":
        run_cached_stage(args, "final-base", stage_final_base)
        return 0
    if args.stage == "structural-intro-outro":
        run_cached_stage(args, "structural-intro-outro", stage_structural_intro_outro)
        return 0
    if args.stage == "gen1-intros":
        run_cached_stage(args, "gen1-intros", stage_gen1_intros)
        return 0
    if args.stage == "extract-game-audio":
        run_cached_stage(args, "extract-game-audio", stage_extract_game_audio)
        return 0
    if args.stage == "bgm-dry-run":
        run_cached_stage(args, "bgm-dry-run", lambda ns: stage_bgm(ns, dry_run=True))
        return 0
    if args.stage == "bgm":
        run_cached_stage(args, "bgm", lambda ns: stage_bgm(ns, dry_run=False))
        return 0
    if args.stage == "carousel-dry-run":
        run_cached_stage(args, "carousel-dry-run", lambda ns: stage_carousel(ns, dry_run=True))
        return 0
    if args.stage == "carousel":
        run_cached_stage(args, "carousel", lambda ns: stage_carousel(ns, dry_run=False))
        return 0
    if args.stage == "clip-colors-dry-run":
        run_cached_stage(args, "clip-colors-dry-run", lambda ns: stage_clip_colors(ns, dry_run=True))
        return 0
    if args.stage == "clip-colors":
        run_cached_stage(args, "clip-colors", lambda ns: stage_clip_colors(ns, dry_run=False))
        return 0
    if args.stage == "fairlight":
        run_cached_stage(args, "fairlight", stage_fairlight)
        return 0
    if args.stage == "audio-normalization-handoff":
        run_cached_stage(args, "audio-normalization-handoff", stage_audio_normalization_handoff)
        return 0
    if args.stage == "final-assembly":
        run_cached_stage(args, "final-assembly", stage_final_assembly)
        return 0
    if args.stage == "validate-order":
        return run_cached_stage(args, "validate-order", stage_validate_order) or 0
    if args.stage == "all-through-candidates":
        run_cached_stage(args, "review-base", stage_review_base)
        run_cached_stage(args, "narrative-prompt", stage_narrative_prompt)
        require_valid_narrative_output("all-through-candidates")
        run_cached_stage(args, "programmatic-candidates", stage_programmatic_candidates)
        run_cached_stage(args, "compile-cut-candidates", stage_compile_cut_candidates)
        return 0
    raise RuntimeError(f"Unhandled stage: {args.stage}")


if __name__ == "__main__":
    raise SystemExit(main())
