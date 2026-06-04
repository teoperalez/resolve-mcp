"""Ordered Mewtwo RBY Ultra Minimum Battles pipeline runner.

This is a guardrail script, not a magic one-button editor. Its job is to keep
the run in the Victreebel-approved order so later heavy passes cannot happen
before cut review artifacts exist.

Order:
  1. review-base              minimal V1/A1 FCPXML, no visual holds
  2. cut-candidates           waveform HTML review + full-dialogue prompt
  3. apply-html-decisions     optional native V1/A1 cutter from pink_decisions
  4. compile-approved-cuts    source-time cut list for deterministic rebuild
  5. final-base               visual-hold rebuild with approved source cuts
  6. gen1-intros              2x Gen 1 leader intro insertion
  7. extract-game-audio       game-audio WAV for BGM bridge sections
  8. bgm / bgm-dry-run        A2 RBY UMB BGM/game-audio bed
  9. carousel / carousel-dry-run
  10. validate-order
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

import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

from scripts import build_mewtwo_rby_fcpxml as M


CUT_REVIEW_DIR = M.CODEX_DIR / "cut_review"
REVIEW_MANIFEST = M.CODEX_DIR / f"{M.safe_file_stem(M.REVIEW_NAME)}_manifest.json"
CUT_CANDIDATES = CUT_REVIEW_DIR / "cut_candidates_mewtwo.json"
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
PIPELINE_STATE = M.CODEX_DIR / "mewtwo_pipeline_state.json"
PIPELINE_REPORT = M.CODEX_DIR / "mewtwo_pipeline_order_report.json"


ORDER = [
    "review-base",
    "cut-candidates",
    "apply-html-decisions",
    "compile-approved-cuts",
    "final-base",
    "gen1-intros",
    "extract-game-audio",
    "bgm",
    "carousel",
    "validate-order",
]


def run(cmd: list[str]) -> None:
    print(" ".join(f'"{part}"' if " " in str(part) else str(part) for part in cmd), flush=True)
    subprocess.run([str(part) for part in cmd], check=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


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
                name = (data.get("name") or "").strip().lower()
                if name in {"member carousel start", "member carousel"}:
                    carousel_marker = data.get("name") or ""
                    break
    except Exception as exc:
        current_timeline = f"Resolve unavailable: {exc}"

    return {
        "review_manifest": REVIEW_MANIFEST.exists(),
        "cut_candidates": CUT_CANDIDATES.exists(),
        "html_decisions": HTML_DECISIONS.exists(),
        "native_normalized_ranges": NATIVE_NORMALIZED.exists(),
        "approved_narrative": APPROVED_NARRATIVE.exists(),
        "approved_source_cuts": APPROVED_SOURCE_CUTS.exists(),
        "final_manifest": FINAL_MANIFEST.exists(),
        "game_audio": GAME_AUDIO.exists(),
        "bgm_report": BGM_REPORT.exists(),
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
            "--import-to-resolve",
        ]
    )
    mark_state("review-base", "complete", manifest=str(REVIEW_MANIFEST))


def stage_cut_candidates(args: argparse.Namespace) -> None:
    require([REVIEW_MANIFEST], "cut-candidates")
    timeline_name = timeline_from_manifest(REVIEW_MANIFEST, M.REVIEW_NAME)
    run(
        [
            sys.executable,
            SCRIPT_DIR / "generate_mewtwo_cut_candidates.py",
            "--timeline",
            timeline_name,
        ]
    )
    mark_state("cut-candidates", "complete", manifest=str(CUT_CANDIDATES))


def stage_apply_html_decisions(args: argparse.Namespace) -> None:
    require([CUT_CANDIDATES, HTML_DECISIONS, HTML_CLIPS, HTML_SEGMAP], "apply-html-decisions")
    timeline_name = timeline_from_manifest(REVIEW_MANIFEST, M.REVIEW_NAME)
    set_current_timeline(timeline_name)
    run(
        [
            sys.executable,
            SCRIPT_DIR / "apply_cut_review_decisions_native.py",
            "--decisions",
            HTML_DECISIONS,
            "--clips",
            HTML_CLIPS,
            "--segmap",
            HTML_SEGMAP,
            "--out-dir",
            NATIVE_APPLIED_DIR,
            "--timeline-name",
            "Mewtwo RBY UMB redo approved review spine",
        ]
    )
    mark_state("apply-html-decisions", "complete", normalized=str(NATIVE_NORMALIZED))


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

    if NATIVE_NORMALIZED.exists():
        approval_sources.append(str(NATIVE_NORMALIZED))
        metadata = read_json(NATIVE_NORMALIZED)
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
        "Member Carousel Start,Member Carousel",
        "--end-at-timeline-end",
    ]
    if dry_run:
        cmd.append("--dry-run")
    run(cmd)
    mark_state("carousel-dry-run" if dry_run else "carousel", "complete")


def stage_validate_order(args: argparse.Namespace) -> int:
    status = artifact_status()
    missing = []
    for key in ("review_manifest", "cut_candidates", "approved_source_cuts", "final_manifest", "game_audio", "bgm_report"):
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
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "cut-candidates"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "apply-html-decisions"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "compile-approved-cuts"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "final-base"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "gen1-intros"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "extract-game-audio"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "bgm-dry-run"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "bgm"],
        [sys.executable, SCRIPT_DIR / "find_member_carousel.py", "--max-candidates", "30"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "carousel-dry-run"],
        [sys.executable, SCRIPT_DIR / "run_mewtwo_rby_umb_pipeline.py", "--stage", "carousel"],
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
            "validate-order",
            "all-through-candidates",
        ],
        default="plan",
    )
    parser.add_argument("--strict", action="store_true", help="Make validate-order fail when finished-stage artifacts are missing.")
    parser.add_argument("--force", action="store_true", help="Overwrite stage outputs where supported.")
    parser.add_argument("--allow-empty-approved-cuts", action="store_true",
                        help="Allow compile-approved-cuts to write an empty approved source-cut file.")
    args = parser.parse_args()

    if args.stage == "plan":
        stage_plan(args)
        return 0
    if args.stage == "review-base":
        stage_review_base(args)
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
    if args.stage == "validate-order":
        return stage_validate_order(args)
    if args.stage == "all-through-candidates":
        stage_review_base(args)
        stage_cut_candidates(args)
        return 0
    raise RuntimeError(f"Unhandled stage: {args.stage}")


if __name__ == "__main__":
    raise SystemExit(main())
