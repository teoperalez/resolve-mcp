"""Generic Pokemon minimum-battles review-first pipeline runner.

This runner is intentionally profile-driven. It provides the stage contract for
multi-part minimum-battles projects while the heavy builders are added in
separate, testable slices.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
SRC_DIR = REPO_DIR / "src"
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator import DEFAULT_WORKFLOW_CONFIG, load_catalog
from resolve_mcp.orchestrator.artifact_validators import artifact_validation_error
from resolve_mcp.orchestrator.dependencies import find_auto_editor_command
from resolve_mcp.orchestrator.models import ProjectProfile, WorkflowCatalog, expand_templates


ORDER = [
    "input-preflight",
    "auto-editor-multi",
    "review-base",
    "narrative-prompt",
    "narrative-llm-review",
    "programmatic-candidates",
    "compile-cut-candidates",
    "apply-html-decisions",
    "post-cut-narrative-audit",
    "compile-approved-cuts",
    "structure-decisions",
    "gap-plan",
    "final-base-fcpxml",
    "a1-dialogue-audit",
    "rse-assets-preflight",
    "resolve-final-assembly",
    "bgm",
    "clip-colors",
    "fairlight",
    "audio-normalization-handoff",
    "validate-order",
]

STAGE_OUTPUT_KEYS: dict[str, list[str]] = {
    "input-preflight": ["input_preflight_report"],
    "auto-editor-multi": ["parts_manifest"],
    "review-base": ["review_fcpxml", "review_manifest", "html_clips", "source_map"],
    "narrative-prompt": ["narrative_prompt", "narrative_clip_index"],
    "narrative-llm-review": ["narrative_output"],
    "programmatic-candidates": [
        "waveform_candidates",
        "ngram_candidates",
        "artifact_candidates",
        "programmatic_candidates",
        "categories_json",
    ],
    "compile-cut-candidates": ["candidate_manifest", "html_index", "html_segmap"],
    "apply-html-decisions": ["native_normalized_ranges"],
    "post-cut-narrative-audit": [
        "post_cut_narrative_audit_report",
        "post_cut_narrative_audit_prompt",
        "post_cut_narrative_audit_index",
    ],
    "compile-approved-cuts": ["approved_source_cuts"],
    "structure-decisions": ["structure_decisions"],
    "gap-plan": ["gap_plan"],
    "final-base-fcpxml": ["final_fcpxml", "final_manifest", "gap_marker_report"],
    "a1-dialogue-audit": ["a1_dialogue_audit_report"],
    "rse-assets-preflight": ["rse_assets_report"],
    "resolve-final-assembly": ["final_manifest"],
    "bgm": ["bgm_report"],
    "clip-colors": ["clip_color_report"],
    "fairlight": ["fairlight_report"],
    "audio-normalization-handoff": ["audio_normalization_instructions"],
    "validate-order": ["pipeline_order_report"],
    "plan": ["pipeline_plan"],
}

NO_CACHE_STAGES = {"input-preflight", "validate-order"}

STAGE_IMPLEMENTATION: dict[str, dict[str, str]] = {
    "input-preflight": {
        "status": "implemented",
        "owner": "scripts/run_minimum_battles_pipeline.py:stage_input_preflight",
        "notes": "Checks selected source parts, core RSE assets, BGM folder, timeline settings, and auto-editor availability.",
    },
    "auto-editor-multi": {
        "status": "implemented",
        "owner": "scripts/orchestrator_auto_editor_multi.py",
        "notes": "Runs auto-editor per selected source part and writes a canonical parts manifest.",
    },
    "review-base": {
        "status": "partial",
        "owner": "scripts/build_minimum_battles_fcpxml.py --review-base",
        "notes": "Current builder rejects multi-part stitching and only supports one combined auto-editor FCPXML.",
    },
    "narrative-prompt": {
        "status": "partial",
        "owner": "scripts/generate_rby_umb_cut_candidates.py --stage narrative-prompt",
        "notes": "Reuses the RBY candidate generator; the RSE/minimum-battles prompt contract is not yet a dedicated implementation.",
    },
    "narrative-llm-review": {
        "status": "manual_gate",
        "owner": "LLM/human review artifact at narrative_output",
        "notes": "This must be real reviewed JSON. The runner refuses to synthesize placeholder narrative decisions.",
    },
    "programmatic-candidates": {
        "status": "partial",
        "owner": "scripts/generate_rby_umb_cut_candidates.py --stage programmatic-candidates",
        "notes": "Reuses RBY waveform/ngram/artifact detectors; generic minimum-battles detector contracts still need a dedicated pass.",
    },
    "compile-cut-candidates": {
        "status": "partial",
        "owner": "scripts/generate_rby_umb_cut_candidates.py --stage compile",
        "notes": "Uses the existing review HTML compiler, but the candidate schema still carries RBY lineage.",
    },
    "apply-html-decisions": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs deterministic normalization of HTML whole-clip decisions, auto decisions, restores, and drag cuts.",
    },
    "post-cut-narrative-audit": {
        "status": "partial",
        "owner": "scripts/build_post_cut_narrative_audit.py",
        "notes": "Builds an audit surface, but downstream approval compilation is not wired into this generic pipeline yet.",
    },
    "compile-approved-cuts": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs minimum-battles source-time cut compiler that merges initial review and post-cut audit approvals.",
    },
    "structure-decisions": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs approved visual structure decisions from visual evidence, not transcript-only guesses.",
    },
    "gap-plan": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs canonical gap_plan.json with one-second A1 gaps, continuous V1 coverage, marker policy, recap holds, and multi-battle pre-roll rule.",
    },
    "final-base-fcpxml": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs final-base FCPXML builder for approved cuts, A1 gaps, continuous V1 holds, intro/outro, and markers.",
    },
    "a1-dialogue-audit": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs fresh Whisper audit over final-base A1 clips before Resolve assembly.",
    },
    "rse-assets-preflight": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs Resolve/media-pool preflight for RSE intro, outro, background, and BGM assets.",
    },
    "resolve-final-assembly": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs deterministic Resolve import/assembly and structural timeline verification.",
    },
    "bgm": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs continuous A2 BGM placement using source-frame audio durations and verifier comparisons.",
    },
    "clip-colors": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs final timeline clip-color pass for review/debug visibility.",
    },
    "fairlight": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs Fairlight preset application to the exact finished timeline plus saved-project report.",
    },
    "audio-normalization-handoff": {
        "status": "placeholder",
        "owner": "not implemented",
        "notes": "Needs Computer Use handoff after Fairlight with the repo's audio-only selection instructions.",
    },
    "validate-order": {
        "status": "implemented",
        "owner": "scripts/run_minimum_battles_pipeline.py:stage_validate_order",
        "notes": "Writes artifact and implementation audit; strict mode fails on missing artifacts, invalid artifacts, placeholders, and partial implementations.",
    },
}

BLOCKING_IMPLEMENTATION_STATUSES = {"partial", "placeholder", "unknown"}


class PipelineStop(RuntimeError):
    """A required input, decision, or implementation slice is missing."""


@dataclass
class Context:
    catalog: WorkflowCatalog
    profile: ProjectProfile
    mapping: dict[str, str]

    def text(self, key: str, default: str = "") -> str:
        value: Any
        if key in self.profile.parameters:
            value = self.profile.parameters[key]
        elif key in self.profile.paths:
            value = self.profile.paths[key]
        else:
            value = self.mapping.get(key, default)
        if value is None:
            return default
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(expand_templates(str(value), self.mapping)).strip()

    def raw_parameter(self, key: str, default: Any = None) -> Any:
        return self.profile.parameters.get(key, default)

    def path(self, key: str, default: Path | None = None) -> Path:
        value = self.mapping.get(key)
        if value:
            return Path(value)
        if default is not None:
            return default
        raise KeyError(f"Profile {self.profile.id!r} has no path or parameter {key!r}")

    def int_value(self, key: str, default: int) -> int:
        raw = self.raw_parameter(key, self.mapping.get(key, default))
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise PipelineStop(f"Profile setting {key!r} must be an integer, got {raw!r}")

    def float_value(self, key: str, default: float) -> float:
        raw = self.raw_parameter(key, self.mapping.get(key, default))
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise PipelineStop(f"Profile setting {key!r} must be numeric, got {raw!r}")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def run(cmd: list[object]) -> None:
    printable = " ".join(f'"{part}"' if " " in str(part) else str(part) for part in cmd)
    print(printable, flush=True)
    subprocess.run([str(part) for part in cmd], check=True)


def normalize_path_list(ctx: Context, key: str) -> list[Path]:
    raw = ctx.raw_parameter(key)
    if raw in (None, ""):
        return []
    values: list[Any]
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise PipelineStop(f"Profile setting {key!r} must be a JSON list.")
            values = parsed
        else:
            values = [part.strip() for part in text.split(";") if part.strip()]
    else:
        raise PipelineStop(f"Profile setting {key!r} must be a list or semicolon-delimited string.")
    return [Path(str(expand_templates(str(value), ctx.mapping))) for value in values]


def stage_paths(ctx: Context, stage: str) -> list[Path]:
    return [ctx.path(key) for key in STAGE_OUTPUT_KEYS.get(stage, [])]


def outputs_complete(ctx: Context, stage: str) -> bool:
    outputs = stage_paths(ctx, stage)
    if not outputs:
        return False
    for key in STAGE_OUTPUT_KEYS.get(stage, []):
        path = ctx.path(key)
        if not path.exists():
            return False
        if artifact_validation_error(key, path):
            return False
    return True


def mark_state(ctx: Context, stage: str, status: str, **extra: Any) -> None:
    state_path = ctx.path("pipeline_state", ctx.path("pipeline_order_report").with_name("pipeline_state.json"))
    state = read_json(state_path) if state_path.exists() else {}
    state.setdefault("schema", "minimum_battles_pipeline_state_v1")
    state.setdefault("profile", ctx.profile.id)
    state["updated_at"] = now()
    state.setdefault("stages", {})
    state["stages"][stage] = {"status": status, "updated_at": now(), **extra}
    write_json(state_path, state)


def stop_for_user(
    ctx: Context,
    stage: str,
    reason: str,
    *,
    missing: list[str] | None = None,
    options: list[str] | None = None,
) -> None:
    options = options or [
        "Provide or regenerate the missing data, then rerun this step.",
        "Update the project profile path/setting in the orchestrator GUI.",
        "Explicitly approve a named fallback or narrower implementation slice.",
    ]
    payload = {
        "schema": "minimum_battles_orchestrator_stop_v1",
        "generated_at": now(),
        "profile": ctx.profile.id,
        "stage": stage,
        "reason": reason,
        "missing": missing or [],
        "options": options,
    }
    stop_path = ctx.path("pipeline_stop_report", ctx.path("pipeline_order_report").with_name("orchestrator_stop.json"))
    write_json(stop_path, payload)
    lines = [
        f"STOP: Stage {stage!r} cannot continue autonomously.",
        f"Reason: {reason}",
    ]
    if missing:
        lines.append("Missing/invalid:")
        lines.extend(f"  - {item}" for item in missing)
    lines.append(f"Stop report: {stop_path}")
    lines.append("Ask the user how to proceed before continuing:")
    lines.extend(f"  {index}. {option}" for index, option in enumerate(options, start=1))
    raise PipelineStop("\n".join(lines))


def load_context(args: argparse.Namespace) -> Context:
    config = args.config or Path(os.environ.get("ORCHESTRATOR_CONFIG_PATH") or DEFAULT_WORKFLOW_CONFIG)
    profile_id = args.profile or os.environ.get("ORCHESTRATOR_PROFILE_ID") or ""
    if not profile_id:
        raise PipelineStop(
            "No orchestrator profile is active. Run through the orchestrator GUI, "
            "use scripts/orchestrator_run.py --profile <profile_id>, or pass --profile."
        )
    catalog = load_catalog(config)
    profile = catalog.profile(profile_id)
    os.environ["ORCHESTRATOR_PROFILE_ID"] = profile.id
    os.environ["ORCHESTRATOR_WORKFLOW_ID"] = profile.workflow_id
    os.environ["ORCHESTRATOR_CONFIG_PATH"] = str(config)
    return Context(catalog=catalog, profile=profile, mapping=profile.mapping(catalog.repo))


def selected_source_parts(ctx: Context) -> list[Path]:
    return normalize_path_list(ctx, "used_source_parts") or normalize_path_list(ctx, "source_parts")


def source_parts_for_report(ctx: Context) -> tuple[list[Path], list[Path]]:
    all_parts = normalize_path_list(ctx, "source_parts")
    used_parts = normalize_path_list(ctx, "used_source_parts") or all_parts
    return all_parts, used_parts


def stage_input_preflight(ctx: Context, _args: argparse.Namespace) -> None:
    all_parts, used_parts = source_parts_for_report(ctx)
    missing: list[str] = []
    warnings: list[str] = []
    if not all_parts:
        missing.append("source_parts is empty")
    if not used_parts:
        missing.append("used_source_parts/source_parts produced no selected media")
    all_part_set = {str(path).casefold() for path in all_parts}
    for path in used_parts:
        if all_part_set and str(path).casefold() not in all_part_set:
            warnings.append(f"used source part is not listed in source_parts: {path}")
        if not path.exists():
            missing.append(f"source media does not exist: {path}")

    file_keys = ["intro_asset", "outro_asset", "background_infinite_asset"]
    for key in file_keys:
        path_text = ctx.text(key)
        if not path_text:
            missing.append(f"{key} is not configured")
            continue
        path = Path(path_text)
        if not path.exists():
            missing.append(f"{key} does not exist: {path}")

    dir_keys = ["bgm_dir"]
    for key in dir_keys:
        path_text = ctx.text(key)
        if not path_text:
            missing.append(f"{key} is not configured")
            continue
        path = Path(path_text)
        if not path.is_dir():
            missing.append(f"{key} is not a directory: {path}")

    fps = ctx.int_value("timeline_fps", 60)
    dialogue_track_index = ctx.int_value("dialogue_track_index", 4)
    gap_frames = ctx.int_value("gap_frames", 60)
    marker_offset_frames = ctx.int_value("marker_offset_frames", 34)
    if fps <= 0:
        missing.append(f"timeline_fps must be positive, got {fps}")
    if dialogue_track_index <= 0:
        missing.append(f"dialogue_track_index must be positive, got {dialogue_track_index}")
    if gap_frames <= 0:
        missing.append(f"gap_frames must be positive, got {gap_frames}")
    if marker_offset_frames < 0:
        missing.append(f"marker_offset_frames must be non-negative, got {marker_offset_frames}")

    auto_editor_command, auto_editor_detail = find_auto_editor_command(sys.executable)
    if not auto_editor_command:
        missing.append(f"auto-editor is not runnable in this Python environment: {auto_editor_detail}")

    report = {
        "schema": "minimum_battles_input_preflight_v1",
        "generated_at": now(),
        "profile": ctx.profile.id,
        "status": "missing" if missing else "pass",
        "fps": fps,
        "dialogue_track_index": dialogue_track_index,
        "gap_frames": gap_frames,
        "marker_offset_frames": marker_offset_frames,
        "source_parts": [str(path) for path in all_parts],
        "used_source_parts": [str(path) for path in used_parts],
        "asset_paths": {
            "intro_asset": ctx.text("intro_asset"),
            "outro_asset": ctx.text("outro_asset"),
            "background_infinite_asset": ctx.text("background_infinite_asset"),
            "bgm_dir": ctx.text("bgm_dir"),
        },
        "auto_editor_command": auto_editor_command,
        "auto_editor_detail": auto_editor_detail,
        "warnings": warnings,
        "missing": missing,
    }
    write_json(ctx.path("input_preflight_report"), report)
    if missing:
        stop_for_user(ctx, "input-preflight", "Required source media, assets, settings, or auto-editor are missing.", missing=missing)
    print(f"PASS: input preflight wrote {ctx.path('input_preflight_report')}")


def stage_auto_editor_multi(ctx: Context, args: argparse.Namespace) -> None:
    run(
        [
            sys.executable,
            SCRIPT_DIR / "orchestrator_auto_editor_multi.py",
            "--config",
            args.config or Path(os.environ.get("ORCHESTRATOR_CONFIG_PATH") or DEFAULT_WORKFLOW_CONFIG),
            "--profile",
            ctx.profile.id,
        ]
        + (["--force"] if args.force else [])
        + (["--dry-run"] if args.dry_run else [])
    )


def cut_candidate_common_args(ctx: Context) -> list[object]:
    args: list[object] = [
        "--manifest",
        ctx.path("review_manifest"),
        "--out-dir",
        ctx.path("cut_review_dir", ctx.path("candidate_manifest").parent),
        "--transcript",
        ctx.path("transcript_json", ctx.path("candidate_manifest").parent / "transcripts" / "transcript.json"),
        "--waveform-sr",
        ctx.int_value("waveform_sr", 16000),
        "--review-sr",
        ctx.int_value("review_sr", 44100),
        "--speech-rms",
        ctx.float_value("speech_rms", 0.02),
        "--voiced-zcr",
        ctx.float_value("voiced_zcr", 0.25),
    ]
    if str(ctx.text("livestream_edit_mode")).lower() in {"1", "true", "yes", "on"}:
        args.append("--livestream-edit")
    if str(ctx.text("livestream_cut_chat_interactions")).lower() in {"1", "true", "yes", "on"}:
        args.append("--livestream-cut-chat-interactions")
    if str(ctx.text("livestream_bypass_gameplay_narrative_cuts")).lower() in {"1", "true", "yes", "on"}:
        args.append("--bypass-gameplay-narrative-cuts")
    return args


def stage_review_base(ctx: Context, args: argparse.Namespace) -> None:
    run(
        [
            sys.executable,
            SCRIPT_DIR / "build_minimum_battles_fcpxml.py",
            "--config",
            args.config or Path(os.environ.get("ORCHESTRATOR_CONFIG_PATH") or DEFAULT_WORKFLOW_CONFIG),
            "--profile",
            ctx.profile.id,
            "--review-base",
        ]
    )


def stage_narrative_prompt(ctx: Context, _args: argparse.Namespace) -> None:
    run(
        [
            sys.executable,
            SCRIPT_DIR / "generate_rby_umb_cut_candidates.py",
            "--stage",
            "narrative-prompt",
            *cut_candidate_common_args(ctx),
        ]
    )


def stage_narrative_llm_review(ctx: Context, _args: argparse.Namespace) -> None:
    output = ctx.path("narrative_output")
    validation_error = artifact_validation_error("narrative_output", output) if output.exists() else "missing narrative LLM output"
    if output.exists() and not validation_error:
        print(f"Narrative output already exists: {output}")
        return
    stop_for_user(
        ctx,
        "narrative-llm-review",
        "The narrative review is a real review gate; the runner must not create placeholder cut decisions.",
        missing=[f"{output} ({validation_error})"],
        options=[
            "Run the configured LLM narrative review and write the reviewed JSON output, then rerun this stage.",
            "Have a human provide an approved narrative review JSON file at narrative_output.",
            "Explicitly approve a named fallback review artifact path in the profile.",
        ],
    )


def stage_programmatic_candidates(ctx: Context, _args: argparse.Namespace) -> None:
    run(
        [
            sys.executable,
            SCRIPT_DIR / "generate_rby_umb_cut_candidates.py",
            "--stage",
            "programmatic-candidates",
            *cut_candidate_common_args(ctx),
        ]
    )


def stage_compile_cut_candidates(ctx: Context, _args: argparse.Namespace) -> None:
    run(
        [
            sys.executable,
            SCRIPT_DIR / "generate_rby_umb_cut_candidates.py",
            "--stage",
            "compile",
            *cut_candidate_common_args(ctx),
        ]
    )


def stage_post_cut_narrative_audit(ctx: Context, _args: argparse.Namespace) -> None:
    fcpxml = ctx.path("post_cut_fcpxml", ctx.path("review_fcpxml"))
    if not fcpxml.exists():
        stop_for_user(
            ctx,
            "post-cut-narrative-audit",
            "The cut-applied FCPXML is missing, so the post-cut narrative audit cannot run.",
            missing=[str(fcpxml)],
        )
    transcript = ctx.path("transcript_json", ctx.path("candidate_manifest").parent / "transcripts" / "transcript.json")
    if not transcript.exists():
        stop_for_user(
            ctx,
            "post-cut-narrative-audit",
            "The transcript JSON is missing, so the post-cut narrative audit cannot run.",
            missing=[str(transcript)],
        )
    run(
        [
            sys.executable,
            SCRIPT_DIR / "build_post_cut_narrative_audit.py",
            "--fcpxml",
            fcpxml,
            "--transcript",
            transcript,
            "--out-dir",
            ctx.path("post_cut_narrative_audit_dir"),
            "--source-video",
            ctx.path("source_media", Path(ctx.text("source_media"))),
            "--timeline-name",
            f"{ctx.profile.name} - post-cut narrative audit",
            "--fps",
            ctx.float_value("timeline_fps", 60.0),
        ]
    )


def stage_not_implemented(ctx: Context, stage: str, next_step: str) -> None:
    stop_for_user(
        ctx,
        stage,
        f"The {stage!r} contract is wired, but its builder is not implemented yet.",
        options=[
            f"Implement {next_step}, then rerun this same stage.",
            "Run an earlier completed stage only.",
            "Explicitly approve a temporary manual artifact path for this stage.",
        ],
    )


def build_implementation_audit(ctx: Context) -> dict[str, Any]:
    workflow = ctx.catalog.workflow(ctx.profile.workflow_id)
    workflow_order = [step.id for step in workflow.steps]
    workflow_only = [stage for stage in workflow_order if stage not in ORDER]
    runner_only = [stage for stage in ORDER if stage not in workflow_order]
    order_matches = workflow_order == ORDER

    stages: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    manual_gates: list[str] = []
    for index, stage in enumerate(ORDER, start=1):
        implementation = STAGE_IMPLEMENTATION.get(
            stage,
            {
                "status": "unknown",
                "owner": "not declared",
                "notes": "No implementation audit metadata is registered for this stage.",
            },
        )
        status = implementation["status"]
        is_blocking = status in BLOCKING_IMPLEMENTATION_STATUSES
        if is_blocking:
            blockers.append(f"{stage}:{status}")
        if status == "manual_gate":
            manual_gates.append(stage)
        workflow_step = None
        if stage in workflow_order:
            workflow_step = workflow.step(stage)
        stages[stage] = {
            "index": index,
            "implementation_status": status,
            "blocking": is_blocking,
            "owner": implementation.get("owner", ""),
            "notes": implementation.get("notes", ""),
            "declared_outputs": STAGE_OUTPUT_KEYS.get(stage, []),
            "workflow_declared": workflow_step is not None,
            "workflow_title": workflow_step.title if workflow_step else "",
            "requires_resolve": bool(workflow_step.requires_resolve) if workflow_step else False,
            "pause_after": bool(workflow_step.pause_after) if workflow_step else False,
        }

    if not order_matches:
        blockers.append("workflow_order_mismatch")
    if workflow_only:
        blockers.append("workflow_steps_not_in_runner")
    if runner_only:
        blockers.append("runner_stages_not_in_workflow")

    return {
        "schema": "minimum_battles_implementation_audit_v1",
        "workflow_id": workflow.id,
        "workflow_order": workflow_order,
        "runner_order": ORDER,
        "order_matches": order_matches,
        "workflow_only": workflow_only,
        "runner_only": runner_only,
        "manual_gates": manual_gates,
        "blocking_items": blockers,
        "ready_for_exact_reproduction": not blockers,
        "stages": stages,
        "semantic_contracts": {
            "narrative_output": "must be real reviewed JSON; placeholders are refused",
            "gap_plan": "must be first-class JSON and must use continuous V1 coverage for A1 gaps/holds",
            "bgm_report": "must prove continuous A2 BGM with source-duration placement, no A2 gaps, no non-BGM on A2",
            "fairlight_report": "must prove the configured Fairlight preset was applied to the finished timeline",
        },
    }


def stage_plan(ctx: Context, _args: argparse.Namespace) -> None:
    commands = []
    for stage in ORDER:
        command = [sys.executable, SCRIPT_DIR / "run_minimum_battles_pipeline.py", "--stage", stage]
        commands.append(command)
    report = {
        "schema": "minimum_battles_pipeline_plan_v1",
        "generated_at": now(),
        "profile": ctx.profile.id,
        "order": ORDER,
        "commands": [[str(part) for part in command] for command in commands],
        "artifacts": {
            key: str(ctx.path(key))
            for keys in STAGE_OUTPUT_KEYS.values()
            for key in keys
            if key in ctx.mapping
        },
    }
    write_json(ctx.path("pipeline_plan"), report)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


def stage_validate_order(ctx: Context, args: argparse.Namespace) -> int:
    statuses: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    implementation_audit = build_implementation_audit(ctx)
    for stage, keys in STAGE_OUTPUT_KEYS.items():
        if stage in {"plan", "validate-order"}:
            continue
        stage_status = {}
        for key in keys:
            path = ctx.path(key)
            validation_error = artifact_validation_error(key, path) if path.exists() else None
            stage_status[key] = {
                "path": str(path),
                "exists": path.exists(),
                "valid": path.exists() and not validation_error,
                "validation_error": validation_error,
            }
            if not path.exists() or validation_error:
                missing.append(f"{stage}:{key}")
        statuses[stage] = stage_status
    implementation_blockers = list(implementation_audit["blocking_items"])
    report = {
        "schema": "minimum_battles_pipeline_order_report_v1",
        "generated_at": now(),
        "profile": ctx.profile.id,
        "order": ORDER,
        "ready_for_exact_reproduction": not missing and not implementation_blockers,
        "status": statuses,
        "missing_for_finished_timeline": missing,
        "implementation_blockers": implementation_blockers,
        "implementation_audit": implementation_audit,
    }
    write_json(ctx.path("pipeline_order_report"), report)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 2 if args.strict and (missing or implementation_blockers) else 0


def run_stage(ctx: Context, args: argparse.Namespace, stage: str) -> int:
    if stage not in NO_CACHE_STAGES and args.reuse_cache and not args.force and outputs_complete(ctx, stage):
        print(f"Cache hit for stage {stage!r}; declared outputs already exist.")
        mark_state(ctx, stage, "cached")
        return 0
    mark_state(ctx, stage, "running")
    try:
        if stage == "plan":
            stage_plan(ctx, args)
        elif stage == "input-preflight":
            stage_input_preflight(ctx, args)
        elif stage == "auto-editor-multi":
            stage_auto_editor_multi(ctx, args)
        elif stage == "review-base":
            stage_review_base(ctx, args)
        elif stage == "narrative-prompt":
            stage_narrative_prompt(ctx, args)
        elif stage == "narrative-llm-review":
            stage_narrative_llm_review(ctx, args)
        elif stage == "programmatic-candidates":
            stage_programmatic_candidates(ctx, args)
        elif stage == "compile-cut-candidates":
            stage_compile_cut_candidates(ctx, args)
        elif stage == "apply-html-decisions":
            stage_not_implemented(ctx, stage, "generic HTML decision normalization")
        elif stage == "post-cut-narrative-audit":
            stage_post_cut_narrative_audit(ctx, args)
        elif stage == "compile-approved-cuts":
            stage_not_implemented(ctx, stage, "minimum-battles approved source-cut compiler")
        elif stage == "structure-decisions":
            stage_not_implemented(ctx, stage, "minimum-battles structure decision compiler")
        elif stage == "gap-plan":
            stage_not_implemented(ctx, stage, "minimum-battles gap-plan compiler")
        elif stage == "final-base-fcpxml":
            stage_not_implemented(ctx, stage, "scripts/build_minimum_battles_fcpxml.py --final-base")
        elif stage == "a1-dialogue-audit":
            stage_not_implemented(ctx, stage, "multi-part/final-base A1 dialogue audit")
        elif stage == "rse-assets-preflight":
            stage_not_implemented(ctx, stage, "RSE asset import/relink preflight")
        elif stage == "resolve-final-assembly":
            stage_not_implemented(ctx, stage, "Resolve final FCPXML import stage")
        elif stage == "bgm":
            stage_not_implemented(ctx, stage, "scripts/place_minimum_battles_bgm.py")
        elif stage == "clip-colors":
            stage_not_implemented(ctx, stage, "minimum-battles clip color pass")
        elif stage == "fairlight":
            stage_not_implemented(ctx, stage, "Fairlight preset application for this workflow")
        elif stage == "audio-normalization-handoff":
            stage_not_implemented(ctx, stage, "minimum-battles Computer Use normalization handoff")
        elif stage == "validate-order":
            return stage_validate_order(ctx, args)
        else:
            raise RuntimeError(f"Unhandled stage: {stage}")
    except Exception as exc:
        mark_state(ctx, stage, "failed", error=str(exc))
        raise
    for key in STAGE_OUTPUT_KEYS.get(stage, []):
        path = ctx.path(key)
        if not path.exists():
            stop_for_user(ctx, stage, "The stage finished but did not produce its declared output artifact.", missing=[str(path)])
        validation_error = artifact_validation_error(key, path)
        if validation_error:
            stop_for_user(ctx, stage, "The stage produced an invalid output artifact.", missing=[f"{path} ({validation_error})"])
    mark_state(ctx, stage, "complete")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--profile", default="")
    parser.add_argument("--stage", choices=["plan", *ORDER], default="plan")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-reuse-cache", dest="reuse_cache", action="store_false", default=True)
    args = parser.parse_args()

    try:
        ctx = load_context(args)
        return run_stage(ctx, args, args.stage)
    except PipelineStop as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
