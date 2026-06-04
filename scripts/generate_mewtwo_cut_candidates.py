"""Generate Mewtwo RBY UMB cut-review artifacts.

Run this immediately after creating the lightweight review base:

  python scripts/build_mewtwo_rby_fcpxml.py --review-base --import-to-resolve
  python scripts/generate_mewtwo_cut_candidates.py

The output is intentionally review-first. It builds waveform/HTML review
artifacts from the current V1/A1 spine, writes a full-dialogue narrative prompt,
and records the already-locked manual restart cuts that the builder applies.
Downstream final rebuild, BGM, carousel, color, and delivery steps should gate
on this manifest plus an approved-cuts file.
"""
from __future__ import annotations

import argparse
import json
import os
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
from scripts import mark_cut_candidates as MCC


DEFAULT_TIMELINE = M.REVIEW_NAME
DEFAULT_OUT_DIR = M.CODEX_DIR / "cut_review"
DEFAULT_TRANSCRIPT = M.CODEX_DIR / "transcripts" / f"{M.DIALOGUE_PATH.stem}.json"
TL_FPS = 60.0


def norm_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def resolve_path(path: str | Path) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def run(cmd: list[str]) -> None:
    print(" ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


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


def set_current_timeline(project, name: str):
    for i in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(i)
        if timeline and (timeline.GetName() or "") == name:
            project.SetCurrentTimeline(timeline)
            return timeline
    raise RuntimeError(f"Timeline not found: {name}")


def dump_v1_clips(timeline) -> list[dict]:
    wanted = norm_path(M.VIDEO_PATH)
    rows: list[dict] = []
    media_cache: dict[str, tuple[str, float]] = {}
    for i, clip in enumerate(sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda c: c.GetStart())):
        name = clip.GetName() or ""
        cached = media_cache.get(name)
        if cached:
            src, fps = cached
        else:
            src = ""
            fps = TL_FPS
            media_pool_item = clip.GetMediaPoolItem()
            if media_pool_item:
                try:
                    src = media_pool_item.GetClipProperty("File Path") or ""
                except Exception:
                    src = ""
                try:
                    fps = float(media_pool_item.GetClipProperty("FPS") or TL_FPS)
                except Exception:
                    fps = TL_FPS
            media_cache[name] = (src, fps)
        if src and norm_path(src) != wanted:
            continue
        rows.append(
            {
                "i": len(rows),
                "timeline_i": i,
                "name": name or M.VIDEO_PATH.name,
                "start": int(clip.GetStart()),
                "dur": int(clip.GetDuration()),
                "left": int(clip.GetLeftOffset()),
                "fps": fps,
                "color": clip.GetClipColor() or "",
                "src": resolve_path(src or M.VIDEO_PATH),
            }
        )
    return rows


def clip_candidate(row: dict, cat: dict, disposition: str) -> dict:
    fps = float(row.get("fps") or TL_FPS)
    duration_sec = float(row["dur"]) / TL_FPS
    source_start_sec = float(row["left"]) / fps
    source_end_sec = source_start_sec + duration_sec
    reason = (
        f"waveform {cat.get('cat')} candidate: "
        f"rms={cat.get('rms')}, peak={cat.get('peak')}, "
        f"voiced_run={cat.get('run_vs')}s, zcr={cat.get('zcr')}"
    )
    return {
        "source_video": str(M.VIDEO_PATH),
        "dialogue_audio": str(M.DIALOGUE_PATH),
        "source_start_sec": round(source_start_sec, 6),
        "source_end_sec": round(source_end_sec, 6),
        "source_start_frame": int(round(source_start_sec * fps)),
        "source_end_frame": int(round(source_end_sec * fps)),
        "timeline_start_frame": row["start"],
        "timeline_end_frame": row["start"] + row["dur"],
        "duration_frames": row["dur"],
        "clip_index_local": row["i"],
        "clip_index_timeline": row.get("timeline_i", row["i"]),
        "confidence": "high" if disposition == "auto" else "medium",
        "type": "waveform_artifact" if disposition == "auto" else "waveform_review",
        "disposition": disposition,
        "reason": reason,
        "metrics": {
            "cat": cat.get("cat"),
            "rms": cat.get("rms"),
            "peak": cat.get("peak"),
            "run_vs": cat.get("run_vs"),
            "zcr": cat.get("zcr"),
            "dur_sec": cat.get("dur_sec"),
        },
    }


def narrative_clip_from_row(row: dict, timeline_start_frame: int, idx: int) -> dict:
    fps = float(row.get("fps") or TL_FPS)
    tl_start = (int(row["start"]) - timeline_start_frame) / TL_FPS
    duration = int(row["dur"]) / TL_FPS
    src_start = int(row["left"]) / fps
    return {
        "idx": idx,
        "timeline_clip_idx": int(row.get("timeline_i", row["i"])),
        "tl_start": tl_start,
        "tl_end": tl_start + duration,
        "src_start": src_start,
        "src_end": src_start + duration,
        "duration": duration,
        "source_name": row.get("name") or M.VIDEO_PATH.name,
    }


def locked_manual_cuts() -> list[dict]:
    cuts = [
        (
            "remove_rom_mistake_restart_explanation",
            M.RESTART_CUT_START_SEC,
            M.RESTART_CUT_END_SEC,
            "ROM mistake/restart explanation; resumes at clean retake.",
        ),
        (
            "remove_full_run_restart_explanation",
            M.FULL_RESTART_CUT_START_SEC,
            M.FULL_RESTART_CUT_END_SEC,
            "Full run restart explanation/rebuild; resumes at clean Brock retry plan.",
        ),
    ]
    return [
        {
            "label": label,
            "source_video": str(M.VIDEO_PATH),
            "start_sec": start,
            "end_sec": end,
            "start_frame": M.source_frame(start),
            "end_frame": M.source_frame(end),
            "confidence": "locked",
            "type": "explicit_restart_cut",
            "reason": reason,
        }
        for label, start, end, reason in cuts
    ]


def build_mewtwo_prompt(clips: list[dict], transcript_path: Path, manual_cuts: list[dict]) -> str:
    body = "\n".join(MCC.format_clip_line(c) for c in clips)
    return f"""You are reviewing a Mewtwo Pokemon Red/Blue Ultra Minimum Battles redo timeline before any heavy rebuild steps.

## Review Contract

Return only strong cut candidates that should be reviewed or applied before the
final rebuild. Focus on false starts, repetitions, abandoned narrative threads,
self-corrections, explicit edit notes, and restart explanations. Do not cut
natural Teo cadence, useful game-mechanic explanation, battle context, reset
count information, or intentional recap.

Two source-time cuts are already locked into the review base and should not be
returned again:

{json.dumps(manual_cuts, indent=2)}

The transcript used for this prompt is:
{transcript_path}

## Clip List

Each entry shows timeline time (`tl`) and original source time (`src`) in
seconds. Output `start_sec` and `end_sec` in original source time.

{body}

---

Respond with ONLY a raw JSON array. No markdown fences, no prose.

[
  {{
    "start_sec": 123.45,
    "end_sec": 126.78,
    "confidence": "medium",
    "type": "repetition",
    "reason": "Earlier failed take is replaced by a cleaner line shortly after."
  }}
]

Allowed `type` values: explicit_edit_note, false_start, repetition,
abandoned_thread, full_restart, self_correction, mid_clip_false_start,
mid_clip_repetition, mid_clip_self_correction.
"""


def build_narrative_artifacts(rows: list[dict], timeline_start_frame: int, out_dir: Path, args: argparse.Namespace) -> dict:
    narrative_dir = out_dir / "narrative"
    narrative_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = args.transcript.resolve()

    clips = [
        narrative_clip_from_row(row, timeline_start_frame, i + 1)
        for i, row in enumerate(rows)
    ]
    if transcript_path.exists():
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        MCC.attach_transcript_to_clips(clips, transcript.get("segments", []))
        MCC.annotate_clip_relationships(clips)
    else:
        print(f"  WARN: narrative transcript missing: {transcript_path}")
        for clip in clips:
            clip["transcript"] = []
            clip["words_in_clip"] = []

    index_path = narrative_dir / "clip_index.json"
    prompt_path = narrative_dir / "mewtwo_narrative_cut_review.in.md"
    out_path = narrative_dir / "mewtwo_narrative_cut_review.out.json"
    manual_cuts = locked_manual_cuts()

    write_json(index_path, clips)
    prompt_path.write_text(
        build_mewtwo_prompt(clips, transcript_path, manual_cuts),
        encoding="utf-8",
    )

    return {
        "clip_count": len(clips),
        "transcript": str(transcript_path),
        "clip_index": str(index_path),
        "prompt": str(prompt_path),
        "expected_output": str(out_path),
    }


def build_artifacts(rows: list[dict], out_dir: Path, args: argparse.Namespace) -> dict:
    clips_path = out_dir / "clips.json"
    write_json(
        clips_path,
        {
            "source_video": str(M.VIDEO_PATH),
            "dialogue_audio": str(M.DIALOGUE_PATH),
            "clips": rows,
        },
    )

    if not M.DIALOGUE_PATH.exists():
        raise FileNotFoundError(f"Missing dialogue WAV: {M.DIALOGUE_PATH}")

    if not args.skip_waveform:
        run(
            [
                sys.executable,
                str(SCRIPT_DIR / "waveform_qa.py"),
                "--mic",
                str(M.DIALOGUE_PATH),
                "--clips",
                str(clips_path),
                "--out-dir",
                str(out_dir),
                "--sr",
                str(args.waveform_sr),
                "--speech-rms",
                str(args.speech_rms),
                "--voiced-zcr",
                str(args.voiced_zcr),
                "--tl-fps",
                str(TL_FPS),
            ]
        )

    categories_path = out_dir / "categories.json"
    if not categories_path.exists():
        raise FileNotFoundError(f"Missing categories output: {categories_path}")
    categories = json.loads(categories_path.read_text(encoding="utf-8"))
    categories_by_i = {int(c["i"]): c for c in categories if "i" in c}

    review_cats = set(args.review_categories)
    auto_cats = set(args.auto_categories)
    review_rows = []
    review_candidates = []
    auto_candidates = []
    for row in rows:
        cat = categories_by_i.get(int(row["i"]), {})
        cat_name = cat.get("cat", "")
        review_row = dict(row)
        if cat_name in review_cats:
            review_row["color"] = "Pink"
            review_candidates.append(clip_candidate(row, cat, "review"))
        elif cat_name in auto_cats:
            review_row["color"] = "Orange"
            auto_candidates.append(clip_candidate(row, cat, "auto"))
        review_rows.append(review_row)

    review_clips_path = out_dir / "clips_for_review.json"
    write_json(
        review_clips_path,
        {
            "source_video": str(M.VIDEO_PATH),
            "dialogue_audio": str(M.DIALOGUE_PATH),
            "clips": review_rows,
        },
    )

    review_dir = out_dir / "review"
    if not args.skip_html:
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / "build_cut_review.py"),
            "--mic",
            str(M.DIALOGUE_PATH),
            "--clips",
            str(review_clips_path),
            "--out-dir",
            str(review_dir),
            "--categories",
            str(categories_path),
            "--sr",
            str(args.review_sr),
            "--tl-fps",
            str(TL_FPS),
        ]
        preload = review_dir / "pink_decisions.json"
        if preload.exists():
            cmd.extend(["--preload", str(preload)])
        if args.reuse_assets:
            cmd.append("--reuse-assets")
        run(cmd)

    return {
        "source_video": str(M.VIDEO_PATH),
        "dialogue_audio": str(M.DIALOGUE_PATH),
        "clips": len(rows),
        "auto_cut_candidates": auto_candidates,
        "review_candidates": review_candidates,
        "artifacts": {
            "clips": str(clips_path),
            "categories": str(categories_path),
            "waves": str(out_dir / "waves_candidates.png"),
            "review_clips": str(review_clips_path),
            "review_html": str(review_dir / "index.html"),
            "segmap": str(review_dir / "segmap.json"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", default=DEFAULT_TIMELINE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--transcript", type=Path, default=DEFAULT_TRANSCRIPT)
    parser.add_argument("--waveform-sr", type=int, default=16000)
    parser.add_argument("--review-sr", type=int, default=44100)
    parser.add_argument("--speech-rms", type=float, default=0.020)
    parser.add_argument("--voiced-zcr", type=float, default=0.25)
    parser.add_argument("--review-categories", default="possible")
    parser.add_argument("--auto-categories", default="definite")
    parser.add_argument("--reuse-assets", action="store_true")
    parser.add_argument("--skip-waveform", action="store_true")
    parser.add_argument("--skip-html", action="store_true")
    parser.add_argument("--skip-narrative-prompt", action="store_true")
    args = parser.parse_args()

    args.review_categories = [c.strip() for c in args.review_categories.split(",") if c.strip()]
    args.auto_categories = [c.strip() for c in args.auto_categories.split(",") if c.strip()]

    resolve, project = connect()
    timeline = set_current_timeline(project, args.timeline)
    resolve.OpenPage("edit")

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Project: {project.GetName()}")
    print(f"Timeline: {timeline.GetName()}")
    print(f"Output: {out_dir}")

    rows = dump_v1_clips(timeline)
    if not rows:
        raise RuntimeError(f"No V1 clips from expected source: {M.VIDEO_PATH}")
    write_json(out_dir / "clips_all_v1.json", {"timeline": timeline.GetName(), "clips": rows})

    narrative = None
    if not args.skip_narrative_prompt:
        print("\nBuilding full-dialogue review prompt...")
        narrative = build_narrative_artifacts(rows, int(timeline.GetStartFrame()), out_dir, args)
        print(f"  Narrative clips indexed: {narrative['clip_count']}")
        print(f"  Prompt: {narrative['prompt']}")

    artifact_report = build_artifacts(rows, out_dir, args)
    auto_candidates = artifact_report["auto_cut_candidates"]
    review_candidates = artifact_report["review_candidates"]
    report = {
        "schema": "mewtwo_cut_candidates_v1",
        "review_policy": "review_base_before_heavy_rebuild",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": project.GetName(),
        "timeline": timeline.GetName(),
        "timeline_fps": TL_FPS,
        "locked_manual_cuts": locked_manual_cuts(),
        "review_order": [
            {
                "stage": 1,
                "name": "locked_manual_restart_cuts",
                "focus": "source-time cuts already applied to review base",
                "count": len(locked_manual_cuts()),
            },
            {
                "stage": 2,
                "name": "full_dialogue_review",
                "focus": "repetitions, false starts, abandoned narratives, self-corrections, restart candidates",
                "artifact": narrative["prompt"] if narrative else None,
            },
            {
                "stage": 3,
                "name": "audio_artifact_html_review",
                "focus": "confirmed no-dialogue artifacts, mic bumps, throat clears, waveform outliers",
                "artifact": artifact_report["artifacts"]["review_html"],
            },
        ],
        "counts": {
            "v1_clips": len(rows),
            "locked_manual_cuts": len(locked_manual_cuts()),
            "auto_cut_candidates": len(auto_candidates),
            "review_candidates": len(review_candidates),
        },
        "narrative": narrative,
        "artifacts": artifact_report["artifacts"],
        "auto_cut_candidates": auto_candidates,
        "review_candidates": review_candidates,
    }
    report_path = out_dir / "cut_candidates_mewtwo.json"
    write_json(report_path, report)
    print(f"\nWrote candidate manifest: {report_path}")
    print(
        "Candidates: "
        f"{len(report['locked_manual_cuts'])} locked manual cuts, "
        f"{len(auto_candidates)} waveform auto candidates, "
        f"{len(review_candidates)} waveform review candidates"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
