"""Ordered Mewtwo RBY Ultra Minimum Battles pipeline runner.

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
  8. extract-game-audio       game-audio WAV for BGM bridge sections
  9. final-assembly           launch Resolve and assemble the final timeline once
 10. clip-colors              color final timeline clips by deterministic sections
 11. validate-order
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from scripts import build_mewtwo_rby_fcpxml as M


CUT_REVIEW_DIR = M.CODEX_DIR / "cut_review"
REVIEW_MANIFEST = M.CODEX_DIR / f"{M.safe_file_stem(M.REVIEW_NAME)}_manifest.json"
CUT_CANDIDATES = CUT_REVIEW_DIR / "cut_candidates_mewtwo.json"
NARRATIVE_PROMPT = CUT_REVIEW_DIR / "narrative" / "mewtwo_narrative_cut_review.in.md"
NARRATIVE_CLIP_INDEX = CUT_REVIEW_DIR / "narrative" / "clip_index.json"
NARRATIVE_OUTPUT = CUT_REVIEW_DIR / "narrative" / "mewtwo_narrative_cut_review.out.json"
WAVEFORM_CANDIDATES = CUT_REVIEW_DIR / "waveform_candidates.json"
NGRAM_CANDIDATES = CUT_REVIEW_DIR / "ngram_candidates.json"
ARTIFACT_CANDIDATES = CUT_REVIEW_DIR / "artifact_candidates.json"
PROGRAMMATIC_CANDIDATES = CUT_REVIEW_DIR / "programmatic_candidates.json"
HTML_DECISIONS = CUT_REVIEW_DIR / "review" / "pink_decisions.json"
HTML_CLIPS = CUT_REVIEW_DIR / "clips_for_review.json"
HTML_SEGMAP = CUT_REVIEW_DIR / "review" / "segmap.json"
NATIVE_APPLIED_DIR = M.CODEX_DIR / "review_decisions_native"
NATIVE_NORMALIZED = NATIVE_APPLIED_DIR / "review_decisions_normalized_ranges.json"
APPROVED_NARRATIVE = CUT_REVIEW_DIR / "approved_narrative_cuts_mewtwo.json"
APPROVED_SOURCE_CUTS = CUT_REVIEW_DIR / "approved_source_cuts_mewtwo.json"
FINAL_BASE_NAME = "Mewtwo RBY UMB redo CODEx final rebuild base"
FINAL_MANIFEST = M.CODEX_DIR / f"{M.safe_file_stem(FINAL_BASE_NAME)}_manifest.json"
GAME_AUDIO = (
    M.PROJECT_DIR
    / "Mewtwo Red and Blue Ultra Minimum Battles Redo_tracks"
    / "Mewtwo Red and Blue Ultra Minimum Battles Redo_3.wav"
)
BGM_REPORT = M.CODEX_DIR / "qa-reports" / "mewtwo-rby-umb-bgm.json"
CLIP_COLOR_REPORT = M.CODEX_DIR / "qa-reports" / "mewtwo-rby-umb-clip-colors.json"
PIPELINE_STATE = M.CODEX_DIR / "mewtwo_pipeline_state.json"
PIPELINE_REPORT = M.CODEX_DIR / "mewtwo_pipeline_order_report.json"


ORDER = [
    "review-base",
    "narrative-prompt",
    "narrative-llm-review",
    "programmatic-candidates",
    "compile-cut-candidates",
    "apply-html-decisions",
    "compile-approved-cuts",
    "extract-game-audio",
    "final-assembly",
    "clip-colors",
    "validate-order",
]


def run(cmd: list[str]) -> None:
    print(" ".join(f'"{part}"' if " " in str(part) else str(part) for part in cmd), flush=True)
    subprocess.run([str(part) for part in cmd], check=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def require(paths: list[Path], stage: str) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise RuntimeError(
            f"Stage {stage!r} is not ready. Missing required artifact(s):\n"
            + "\n".join(f"  - {item}" for item in missing)
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


def select_finished_timeline(base_name: str):
    _resolve, project = connect()
    current = project.GetCurrentTimeline()
    if current and (current.GetName() or "").startswith(base_name) and "(gen1 intros)" in (current.GetName() or ""):
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
    candidates.sort(key=lambda tl: ("(gen1 intros)" in (tl.GetName() or ""), tl.GetName() or ""))
    selected = candidates[-1]
    project.SetCurrentTimeline(selected)
    return selected


def mark_state(stage: str, status: str, **extra) -> None:
    state = {}
    if PIPELINE_STATE.exists():
        state = read_json(PIPELINE_STATE)
    state.setdefault("history", []).append(
        {
            "stage": stage,
            "status": status,
            "at": datetime.now(timezone.utc).isoformat(),
            **extra,
        }
    )
    state["last_stage"] = stage
    state["last_status"] = status
    write_json(PIPELINE_STATE, state)


def artifact_status() -> dict:
    carousel_marker = None
    current_timeline = None
    track_counts = None
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
            for _rel, data in (timeline.GetMarkers() or {}).items():
                marker_parts = {
                    part.strip().lower()
                    for part in (data.get("name") or "").split("/")
                    if part.strip()
                }
                if marker_parts & {"member carousel start", "member carousel", "final tierlist closed"}:
                    carousel_marker = data.get("name") or ""
                    break
    except Exception as exc:
        current_timeline = f"Resolve unavailable: {exc}"

    return {
        "review_manifest": REVIEW_MANIFEST.exists(),
        "narrative_prompt": NARRATIVE_PROMPT.exists(),
        "narrative_clip_index": NARRATIVE_CLIP_INDEX.exists(),
        "narrative_output": NARRATIVE_OUTPUT.exists(),
        "waveform_candidates": WAVEFORM_CANDIDATES.exists(),
        "ngram_candidates": NGRAM_CANDIDATES.exists(),
        "artifact_candidates": ARTIFACT_CANDIDATES.exists(),
        "programmatic_candidates": PROGRAMMATIC_CANDIDATES.exists(),
        "cut_candidates": CUT_CANDIDATES.exists(),
        "html_decisions": HTML_DECISIONS.exists(),
        "native_normalized_ranges": NATIVE_NORMALIZED.exists(),
        "approved_narrative": APPROVED_NARRATIVE.exists(),
        "approved_source_cuts": APPROVED_SOURCE_CUTS.exists(),
        "final_manifest": FINAL_MANIFEST.exists(),
        "game_audio": GAME_AUDIO.exists(),
        "bgm_report": BGM_REPORT.exists(),
        "clip_color_report": CLIP_COLOR_REPORT.exists(),
        "current_timeline": current_timeline,
        "track_counts": track_counts,
        "carousel_marker_on_current_timeline": carousel_marker,
    }


def stage_review_base(args: argparse.Namespace) -> None:
    run(
        [
            sys.executable,
            SCRIPT_DIR / "build_mewtwo_rby_fcpxml.py",
            "--review-base",
        ]
    )
    mark_state("review-base", "complete", manifest=str(REVIEW_MANIFEST))


def stage_narrative_prompt(args: argparse.Namespace) -> None:
    require([REVIEW_MANIFEST], "narrative-prompt")
    run(
        [
            sys.executable,
            SCRIPT_DIR / "generate_mewtwo_cut_candidates.py",
            "--stage",
            "narrative-prompt",
            "--manifest",
            REVIEW_MANIFEST,
        ]
    )
    mark_state("narrative-prompt", "complete", prompt=str(NARRATIVE_PROMPT), clip_index=str(NARRATIVE_CLIP_INDEX))


def stage_programmatic_candidates(args: argparse.Namespace) -> None:
    require([REVIEW_MANIFEST, NARRATIVE_OUTPUT], "programmatic-candidates")
    run(
        [
            sys.executable,
            SCRIPT_DIR / "generate_mewtwo_cut_candidates.py",
            "--stage",
            "programmatic-candidates",
            "--manifest",
            REVIEW_MANIFEST,
        ]
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
    require(
        [REVIEW_MANIFEST, NARRATIVE_OUTPUT, WAVEFORM_CANDIDATES, NGRAM_CANDIDATES, ARTIFACT_CANDIDATES, PROGRAMMATIC_CANDIDATES],
        "compile-cut-candidates",
    )
    run(
        [
            sys.executable,
            SCRIPT_DIR / "generate_mewtwo_cut_candidates.py",
            "--stage",
            "compile",
            "--manifest",
            REVIEW_MANIFEST,
        ]
    )
    mark_state("compile-cut-candidates", "complete", manifest=str(CUT_CANDIDATES))


def stage_cut_candidates(args: argparse.Namespace) -> None:
    """Legacy alias: build prompt, then finish candidate compile only if LLM output already exists."""
    stage_narrative_prompt(args)
    if not NARRATIVE_OUTPUT.exists():
        print(
            f"Waiting for LLM narrative output before programmatic/compile stages: {NARRATIVE_OUTPUT}\n"
            "Run --stage programmatic-candidates after the LLM step completes."
        )
        return
    stage_programmatic_candidates(args)
    stage_compile_cut_candidates(args)


def stage_apply_html_decisions(args: argparse.Namespace) -> None:
    require([CUT_CANDIDATES, HTML_CLIPS, HTML_SEGMAP], "apply-html-decisions")
    if not HTML_DECISIONS.exists():
        manifest = read_json(CUT_CANDIDATES)
        medium = manifest.get("medium_confidence_review_candidates") or manifest.get("review_candidates") or []
        if medium:
            raise RuntimeError(
                "Medium-confidence cut candidates require manual HTML review before this stage can run. "
                f"Open {CUT_REVIEW_DIR / 'review' / 'index.html'}, save pink_decisions.json, and place it at {HTML_DECISIONS}."
            )
        NATIVE_APPLIED_DIR.mkdir(parents=True, exist_ok=True)
        write_json(
            NATIVE_NORMALIZED,
            {
                "schema": "mewtwo_offline_html_review_decisions_v1",
                "whole_cut_indices": [],
                "partial_records": [],
                "raw_ranges": [],
                "merged_ranges": [],
                "total_cut_frames": 0,
                "note": "No medium-confidence candidates required HTML review.",
            },
        )
        print(f"No medium-confidence review candidates; wrote empty HTML-decision normalization: {NATIVE_NORMALIZED}")
        mark_state("apply-html-decisions", "complete", normalized=str(NATIVE_NORMALIZED), offline=True, empty=True)
        return
    decisions = read_json(HTML_DECISIONS)
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
    _merged, metadata = compile_html_decision_cuts(decisions, clips_data, segmap, 60.0)
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

    merged = merge_timeline_ranges(raw_ranges)
    metadata = {
        "schema": "mewtwo_offline_html_review_decisions_v1",
        "dry_run_auto_approved": bool(decisions.get("dry_run_auto_approved")),
        "whole_cut_indices": whole_cut_indices,
        "partial_records": partial_records,
        "raw_ranges": raw_ranges,
        "merged_ranges": merged,
        "total_cut_frames": sum(int(item["end"]) - int(item["start"]) for item in merged),
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


def stage_compile_approved_cuts(args: argparse.Namespace) -> None:
    require([CUT_CANDIDATES], "compile-approved-cuts")
    rows: list[dict] = []
    approval_sources: list[str] = []

    candidate_manifest = read_json(CUT_CANDIDATES)
    auto_rows = candidate_manifest.get("high_confidence_auto_cuts") or candidate_manifest.get("auto_cut_candidates") or []
    if auto_rows:
        approval_sources.append(f"{CUT_CANDIDATES}:high_confidence_auto_cuts")
        for row in auto_rows:
            if row.get("confidence") != "high" or row.get("disposition") not in {"auto_cut", "auto"}:
                continue
            policy = row.get("section_policy") or {}
            if not policy.get("whole_section"):
                raise RuntimeError(f"High-confidence auto-cut is not FCPXML-section safe: {row!r}")
            rows.append(normalize_source_cut(row, "high_confidence_auto_cut"))

    if NATIVE_NORMALIZED.exists():
        approval_sources.append(str(NATIVE_NORMALIZED))
        metadata = read_json(NATIVE_NORMALIZED)
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
            "schema": "mewtwo_approved_source_cuts_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "Locked restart cuts are not repeated here; build_mewtwo_rby_fcpxml.py always applies them.",
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
            SCRIPT_DIR / "build_mewtwo_rby_fcpxml.py",
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


def stage_gen1_intros(args: argparse.Namespace) -> None:
    require([FINAL_MANIFEST], "gen1-intros")
    set_current_timeline(timeline_from_manifest(FINAL_MANIFEST, FINAL_BASE_NAME))
    run(
        [
            sys.executable,
            SCRIPT_DIR / "place_battle_intros.py",
            "--gen1-insert",
            "--gen1-speed",
            "2",
        ]
    )
    mark_state("gen1-intros", "complete")


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
            "0:a:2",
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
    cmd = [
        sys.executable,
        SCRIPT_DIR / "place_rby_umb_bgm.py",
        "--game-audio",
        GAME_AUDIO,
        "--end-at-timeline-end",
        "--report",
        BGM_REPORT,
    ]
    if dry_run:
        cmd.append("--dry-run")
    run(cmd)
    mark_state("bgm-dry-run" if dry_run else "bgm", "complete", report=str(BGM_REPORT))


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


def stage_clip_colors(args: argparse.Namespace, dry_run: bool = False) -> None:
    require([FINAL_MANIFEST], "clip-colors")
    timeline_name = timeline_from_manifest(FINAL_MANIFEST, FINAL_BASE_NAME)
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


def stage_final_assembly(args: argparse.Namespace) -> None:
    require([APPROVED_SOURCE_CUTS, GAME_AUDIO], "final-assembly")
    stage_final_base(args)
    stage_gen1_intros(args)
    stage_bgm(args, dry_run=False)
    run([sys.executable, SCRIPT_DIR / "find_member_carousel.py", "--max-candidates", "30"])
    stage_carousel(args, dry_run=False)
    stage_clip_colors(args, dry_run=False)
    mark_state(
        "final-assembly",
        "complete",
        manifest=str(FINAL_MANIFEST),
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
        "game_audio",
        "bgm_report",
        "clip_color_report",
    ):
        if not status.get(key):
            missing.append(key)
    if not status.get("carousel_marker_on_current_timeline"):
        missing.append("carousel_marker_on_current_timeline")
    report = {
        "schema": "mewtwo_pipeline_order_report_v1",
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
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "review-base"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "narrative-prompt"],
        ["LLM", "narrative-llm-review", str(NARRATIVE_PROMPT), "->", str(NARRATIVE_OUTPUT)],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "programmatic-candidates"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "compile-cut-candidates"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "apply-html-decisions"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "compile-approved-cuts"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "extract-game-audio"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "final-assembly"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "clip-colors"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "validate-order", "--strict"],
    ]
    report = {
        "order": ORDER,
        "commands": [[str(part) for part in cmd] for cmd in commands],
        "artifacts": artifact_status(),
    }
    write_json(M.CODEX_DIR / "mewtwo_pipeline_plan.json", report)
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
            "final-base",
            "gen1-intros",
            "extract-game-audio",
            "bgm-dry-run",
            "bgm",
            "carousel-dry-run",
            "carousel",
            "clip-colors-dry-run",
            "clip-colors",
            "final-assembly",
            "validate-order",
            "all-through-candidates",
        ],
        default="plan",
    )
    parser.add_argument("--strict", action="store_true", help="Make validate-order fail when finished-stage artifacts are missing.")
    parser.add_argument("--force", action="store_true", help="Overwrite stage outputs where supported.")
    parser.add_argument("--strict-apply", action="store_true",
                        help="For clip-colors, fail if Resolve does not actually persist requested clip colors.")
    parser.add_argument("--allow-empty-approved-cuts", action="store_true",
                        help="Allow compile-approved-cuts to write an empty approved source-cut file.")
    args = parser.parse_args()

    if args.stage == "plan":
        stage_plan(args)
        return 0
    if args.stage == "review-base":
        stage_review_base(args)
        return 0
    if args.stage == "narrative-prompt":
        stage_narrative_prompt(args)
        return 0
    if args.stage == "programmatic-candidates":
        stage_programmatic_candidates(args)
        return 0
    if args.stage == "compile-cut-candidates":
        stage_compile_cut_candidates(args)
        return 0
    if args.stage == "cut-candidates":
        stage_cut_candidates(args)
        return 0
    if args.stage == "apply-html-decisions":
        stage_apply_html_decisions(args)
        return 0
    if args.stage == "compile-approved-cuts":
        stage_compile_approved_cuts(args)
        return 0
    if args.stage == "final-base":
        stage_final_base(args)
        return 0
    if args.stage == "gen1-intros":
        stage_gen1_intros(args)
        return 0
    if args.stage == "extract-game-audio":
        stage_extract_game_audio(args)
        return 0
    if args.stage == "bgm-dry-run":
        stage_bgm(args, dry_run=True)
        return 0
    if args.stage == "bgm":
        stage_bgm(args, dry_run=False)
        return 0
    if args.stage == "carousel-dry-run":
        stage_carousel(args, dry_run=True)
        return 0
    if args.stage == "carousel":
        stage_carousel(args, dry_run=False)
        return 0
    if args.stage == "clip-colors-dry-run":
        stage_clip_colors(args, dry_run=True)
        return 0
    if args.stage == "clip-colors":
        stage_clip_colors(args, dry_run=False)
        return 0
    if args.stage == "final-assembly":
        stage_final_assembly(args)
        return 0
    if args.stage == "validate-order":
        return stage_validate_order(args)
    if args.stage == "all-through-candidates":
        stage_review_base(args)
        stage_narrative_prompt(args)
        if not NARRATIVE_OUTPUT.exists():
            raise RuntimeError(f"LLM narrative output is required before programmatic candidate stages: {NARRATIVE_OUTPUT}")
        stage_programmatic_candidates(args)
        stage_compile_cut_candidates(args)
        return 0
    raise RuntimeError(f"Unhandled stage: {args.stage}")


if __name__ == "__main__":
    raise SystemExit(main())
