"""Generate Victreebel RBY UMB waveform cut-review artifacts.

This is the first cut pass for the reordered Victreebel pipeline. It runs on
the corrected minimal V1/A1 base before heavy rebuild steps, and it keeps Part 1
and Part 2 separate so source-frame decisions remain unambiguous.

Outputs default to:
  E:/Victreebel Red and Blue Ultra Minimum Battles/CODEx/cut_review/

The review order is intentionally dialogue-first. First resolve explicit spoken
edit instructions/restart declarations, then scan the full dialogue for
repetitions, false starts, abandoned lines, self-corrections, and mid-segment
restart candidates. Audio artifacts and any partial-section dialogue cuts are
then routed to the HTML review surface.

For each part it writes:
  - clips.json
  - categories.json and waves_candidates.png from waveform_qa.py
  - clips_for_review.json with questionable clips colored Pink
  - review/index.html plus audio/waveform assets from build_cut_review.py

It also writes cut_candidates_victreebel.json at the run root.
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

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

from scripts import build_victreebel_rby_fcpxml as B
from scripts import mark_cut_candidates as MCC


DEFAULT_TIMELINE = "Victreebel RBY UMB corrected dialogue FCPXML base markers"
DEFAULT_OUT_DIR = B.CODEX_DIR / "cut_review"
TL_FPS = 60.0


@dataclass(frozen=True)
class PartSpec:
    key: str
    label: str
    video: Path
    dialogue: Path
    fcpxml: Path


PARTS = {
    "part1": PartSpec(
        key="part1",
        label="Part 1",
        video=B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 1.mp4",
        dialogue=B.PART1_DIALOGUE,
        fcpxml=B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 1_ALTERED.fcpxml",
    ),
    "part2": PartSpec(
        key="part2",
        label="Part 2",
        video=B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2.mp4",
        dialogue=B.PART2_DIALOGUE,
        fcpxml=B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2_ALTERED.fcpxml",
    ),
}


def norm_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def resolve_path(path: str | Path) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


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
    for i in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(i)
        if timeline and (timeline.GetName() or "") == name:
            project.SetCurrentTimeline(timeline)
            return timeline
    raise RuntimeError(f"Timeline not found: {name}")


def dump_v1_clips(timeline) -> list[dict]:
    known_sources = {
        part.video.name: str(part.video.resolve())
        for part in PARTS.values()
    }
    known_sources.update({
        part.video.stem: str(part.video.resolve())
        for part in PARTS.values()
    })
    media_cache: dict[str, tuple[str, float]] = {}
    rows: list[dict] = []
    for i, clip in enumerate(sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda c: c.GetStart())):
        name = clip.GetName() or ""
        src = ""
        fps = TL_FPS
        if name in known_sources:
            src = known_sources[name]
        else:
            cached = media_cache.get(name)
            if cached:
                src, fps = cached
            else:
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
        rows.append(
            {
                "i": i,
                "name": name,
                "start": int(clip.GetStart()),
                "dur": int(clip.GetDuration()),
                "left": int(clip.GetLeftOffset()),
                "fps": fps,
                "color": clip.GetClipColor() or "",
                "src": resolve_path(src) if src else "",
            }
        )
    return rows


def rows_for_part(rows: list[dict], part: PartSpec) -> list[dict]:
    wanted = norm_path(part.video)
    out: list[dict] = []
    for row in rows:
        if row.get("src") and norm_path(row["src"]) == wanted:
            local = dict(row)
            local["timeline_i"] = row["i"]
            local["i"] = len(out)
            local["part"] = part.key
            out.append(local)
    return out


def clip_candidate(part: PartSpec, row: dict, cat: dict, disposition: str) -> dict:
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
        "part": part.key,
        "source_video": str(part.video),
        "dialogue_audio": str(part.dialogue),
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


def transcript_override(args: argparse.Namespace, part: PartSpec) -> Path | None:
    raw = getattr(args, f"{part.key}_transcript")
    return Path(raw).resolve() if raw else None


def transcript_path_for(part: PartSpec, transcripts_dir: Path) -> Path:
    return transcripts_dir / f"{part.dialogue.stem}.json"


def ensure_transcript(part: PartSpec, transcripts_dir: Path, args: argparse.Namespace) -> Path | None:
    override = transcript_override(args, part)
    if override:
        if not override.exists():
            raise FileNotFoundError(f"{part.label} transcript override not found: {override}")
        return override

    path = transcript_path_for(part, transcripts_dir)
    if path.exists():
        return path

    if not args.transcribe_narrative:
        print(f"  WARN: no {part.label} narrative transcript found: {path}")
        return None

    transcripts_dir.mkdir(parents=True, exist_ok=True)
    run(
        [
            sys.executable,
            str(SCRIPT_DIR / "transcribe_audio.py"),
            "--audio",
            str(part.dialogue),
            "--out",
            str(transcripts_dir),
            "--model",
            args.narrative_model,
            "--device",
            args.narrative_device,
            "--compute-type",
            args.narrative_compute_type,
            "--language",
            "en",
            "--no-vad",
        ]
    )
    if not path.exists():
        raise FileNotFoundError(f"Transcription finished but did not create expected file: {path}")
    return path


def narrative_clip_from_row(
    row: dict,
    part: PartSpec,
    timeline_start_frame: int,
    global_idx: int,
) -> dict:
    fps = float(row.get("fps") or TL_FPS)
    tl_start = (int(row["start"]) - timeline_start_frame) / TL_FPS
    duration = int(row["dur"]) / TL_FPS
    src_start = int(row["left"]) / fps
    return {
        "idx": global_idx,
        "part": part.key,
        "part_label": part.label,
        "part_clip_idx": int(row["i"]),
        "timeline_clip_idx": int(row.get("timeline_i", row["i"])),
        "tl_start": tl_start,
        "tl_end": tl_start + duration,
        "src_start": src_start,
        "src_end": src_start + duration,
        "duration": duration,
        "source_name": row.get("name") or part.video.name,
    }


def format_narrative_clip_line(clip: dict) -> str:
    base = MCC.format_clip_line(clip)
    header = (
        f"PART={clip['part']} ({clip['part_label']}) "
        f"PART_CLIP={clip['part_clip_idx']} "
        f"TIMELINE_CLIP={clip['timeline_clip_idx']} "
        f"SOURCE={clip['source_name']}"
    )
    return f"{header}\n{base}"


def build_all_parts_narrative_prompt(clips: list[dict], transcript_paths: dict[str, str]) -> str:
    body = "\n".join(format_narrative_clip_line(c) for c in clips)
    return f"""You are reviewing a single finished Pokemon challenge narrative that was recorded in two separate files.

## Review Contract

The goal is a final timeline free of repetitions, false starts, abandoned
narrative threads, self-correction fragments, explicit editor-note tangents, and
audio artifacts.

Do as much cutting decision work as possible before involving the editor. Return
as few user-facing candidates as possible: auto-cut high-confidence whole-FCPXML
section mistakes through the section-safe pipeline, auto-keep weak/speculative
leads, and reserve HTML/Pink review for true borderline cases after exhaustive
checking or strong candidates that would require a cut boundary inside an
FCPXML section. False positives are more costly than false negatives.

Review in this order:

1. First find clear spoken edit instructions and restart declarations: "cut
    this", "this is a restart", "everything before this was a mistake", "I moved
    that to the outro", or any tangent the speaker says should be removed.
2. Then scan the full dialogue for repetitions, false starts, abandoned
    narrative threads, self-corrections, stale takes, and mid-segment restart
    candidates.
3. Leave non-word artifacts such as breaths, clicks, throat clears, and waveform
    bursts for the HTML/audio-artifact pass unless the transcript itself shows a
    clear mic check or spoken pre-roll.

Candidates that cover whole FCPXML sections can be applied automatically by the
section-safe classifier when the evidence is strong. Candidates that start or
end inside an FCPXML section must be reviewed in HTML/Pink rather than applied
directly, but only report them when the evidence is strong enough to justify
editor attention or remains genuinely borderline after exhaustive checking. Do
not report weak or merely plausible candidates.

## Critical Scope Rule

Treat Part 1 and Part 2 as ONE continuous video story. The part boundary is not
a narrative reset. False starts, repetitions, and abandoned lines must be checked
across the entire combined clip list, including cases where Part 2 redoes,
rehashes, contradicts, or takes a different direction from something said in
Part 1.

The Part 1 and Part 2 source files stay separate for applying cuts. Every cut
you output must include the `part` field so source times are not mixed.

Transcripts used:
{json.dumps(transcript_paths, indent=2)}

## What To Flag

Flag dialogue cuts:

- explicit edit notes or restart declarations that identify content to remove
- false starts where the speaker begins a line and restarts cleaner later
- true repetitions where one delivery is clearly a failed take or stale setup
- abandoned narrative threads that are superseded later
- cross-part rehashes where Part 2 replaces or invalidates a Part 1 line
- full restart ranges where the speaker explicitly says the previous take was a mistake
- self-corrections, including small repeated words, when the first token/phrase
    is a genuine abandoned fragment rather than intentional emphasis
- mid-clip false starts, repetitions, or self-corrections when only part of a
    section should be removed

Do NOT flag generic non-word audio artifacts in this dialogue pass:

- breaths, clicks, throat clears, or empty waveform artifacts
- generic audio polish that does not change the story
- pure silence/dead air with no spoken words

If a tiny repeated word is a real self-correction, include it only when context
clearly proves the first token/phrase is abandoned. Otherwise auto-keep it and
do not return it as a candidate.

Do not flag a Part 2 recap just because it repeats Part 1. Recaps can be
intentional. Flag the older/staler line only when the later line clearly
functions as the real take, changes direction, or makes the earlier line
misleading in the final story.

Use the `WORDS_IN_CLIP` annotation for precise boundaries after deciding a cut,
not as standalone proof that a clip is an artifact. `WORDS_IN_CLIP(0)` can be a
lead for the later audio-artifact pass, but obvious dialogue context, normal
gaps between words, and clips with overlapping transcript text should not be
reported as artifacts. Do not promote raw duplicate-word or immediate
phrase-repeat heuristics unless the surrounding dialogue proves the first token
or phrase is actually abandoned.

Preserve Teo's style: softeners like "of course", "actually", "basically",
"kind of", "like", and "now" are often intentional. Do not over-tighten natural
cadence. Never split atomic references such as "Rival 2", "rival number two",
"the second gym leader", "attempt number one", or "reset 29".

If a cut is only plausible because evidence is thin, do not output it. Use
`confidence: "medium"` only for a true borderline case after checking the
surrounding transcript, word timings, neighboring clips, and FCPXML section
safety. Those true borderline cases should go to editor review instead of being
silently kept or cut.

## Clip List

Each entry has a `PART=...` header. `src=A-B` is source time within that part's
own media. Output `start_sec` and `end_sec` in that same part-local source time.

{body}

---

## Output

Respond with ONLY a raw JSON array. No markdown fences, no prose.

[
  {{
    "part": "part1",
    "start_sec": 123.45,
    "end_sec": 126.78,
    "confidence": "medium",
    "type": "repetition",
    "reason": "Part 2 later re-delivers this setup cleaner; Part 1 version is an abandoned/stale take"
  }},
  {{
    "part": "part2",
    "start_sec": 456.10,
    "end_sec": 461.30,
    "confidence": "medium",
    "type": "mid_clip_false_start",
    "reason": "Abandoned phrase before a clean restart in the next sub-segment"
  }}
]

Allowed `part` values: `part1`, `part2`.
Allowed `type` values: `explicit_edit_note`, `false_start`, `repetition`,
`abandoned_thread`, `full_restart`, `self_correction`,
`mid_clip_false_start`, `mid_clip_repetition`, `mid_clip_self_correction`.
"""


def build_narrative_artifacts(
    part_rows: dict[str, list[dict]],
    timeline_start_frame: int,
    out_dir: Path,
    args: argparse.Namespace,
) -> dict:
    narrative_dir = out_dir / "narrative"
    transcript_dir = args.transcripts_dir.resolve() if args.transcripts_dir else out_dir / "transcripts"
    narrative_dir.mkdir(parents=True, exist_ok=True)

    all_clips: list[dict] = []
    transcript_paths: dict[str, str] = {}
    global_idx = 1

    for part in PARTS.values():
        rows = part_rows.get(part.key, [])
        if not rows:
            continue
        transcript_path = ensure_transcript(part, transcript_dir, args)
        if transcript_path is None:
            continue
        transcript_paths[part.key] = str(transcript_path)
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        clips = [
            narrative_clip_from_row(row, part, timeline_start_frame, global_idx + i)
            for i, row in enumerate(rows)
        ]
        MCC.attach_transcript_to_clips(clips, transcript.get("segments", []))
        # Relationship annotations are source-local. Run per part so Part 1 and
        # Part 2 source frames are never compared as the same media timeline.
        MCC.annotate_clip_relationships(clips)
        all_clips.extend(clips)
        global_idx += len(clips)

    all_clips.sort(key=lambda c: (c["tl_start"], c["idx"]))

    index_path = narrative_dir / "all_parts_clip_index.json"
    write_json(index_path, all_clips)

    prompt_path = narrative_dir / "all_parts_narrative_cut_review.in.md"
    out_path = narrative_dir / "all_parts_narrative_cut_review.out.json"
    if all_clips:
        prompt_path.write_text(
            build_all_parts_narrative_prompt(all_clips, transcript_paths),
            encoding="utf-8",
        )
    else:
        prompt_path.write_text(
            "No narrative transcript files were available. Re-run with "
            "--transcribe-narrative or --part1-transcript/--part2-transcript.",
            encoding="utf-8",
        )

    return {
        "clip_count": len(all_clips),
        "transcripts": transcript_paths,
        "clip_index": str(index_path),
        "prompt": str(prompt_path),
        "expected_output": str(out_path),
    }


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def build_part_artifacts(
    part: PartSpec,
    rows: list[dict],
    out_dir: Path,
    args: argparse.Namespace,
) -> dict:
    part_dir = out_dir / part.key
    part_dir.mkdir(parents=True, exist_ok=True)
    clips_path = part_dir / "clips.json"
    write_json(clips_path, {"part": part.key, "source_video": str(part.video), "clips": rows})

    if not part.dialogue.exists():
        raise FileNotFoundError(f"Missing dialogue WAV for {part.label}: {part.dialogue}")

    if not args.skip_waveform:
        run(
            [
                sys.executable,
                str(SCRIPT_DIR / "waveform_qa.py"),
                "--mic",
                str(part.dialogue),
                "--clips",
                str(clips_path),
                "--out-dir",
                str(part_dir),
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

    categories_path = part_dir / "categories.json"
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
            review_candidates.append(clip_candidate(part, row, cat, "review"))
        elif cat_name in auto_cats:
            review_row["color"] = "Orange"
            auto_candidates.append(clip_candidate(part, row, cat, "auto"))
        review_rows.append(review_row)

    review_clips_path = part_dir / "clips_for_review.json"
    write_json(
        review_clips_path,
        {
            "part": part.key,
            "source_video": str(part.video),
            "dialogue_audio": str(part.dialogue),
            "clips": review_rows,
        },
    )

    review_dir = part_dir / "review"
    if not args.skip_html:
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / "build_cut_review.py"),
            "--mic",
            str(part.dialogue),
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
        "part": part.key,
        "label": part.label,
        "source_video": str(part.video),
        "dialogue_audio": str(part.dialogue),
        "fcpxml": str(part.fcpxml),
        "clips": len(rows),
        "auto_cut_candidates": auto_candidates,
        "review_candidates": review_candidates,
        "artifacts": {
            "clips": str(clips_path),
            "categories": str(categories_path),
            "waves": str(part_dir / "waves_candidates.png"),
            "review_clips": str(review_clips_path),
            "review_html": str(review_dir / "index.html"),
            "segmap": str(review_dir / "segmap.json"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", default=DEFAULT_TIMELINE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--part", choices=["all", "part1", "part2"], default="all")
    parser.add_argument("--waveform-sr", type=int, default=16000)
    parser.add_argument("--review-sr", type=int, default=44100)
    parser.add_argument("--speech-rms", type=float, default=0.020)
    parser.add_argument("--voiced-zcr", type=float, default=0.25)
    parser.add_argument("--review-categories", default="possible")
    parser.add_argument("--auto-categories", default="definite")
    parser.add_argument("--part1-transcript", type=Path, default=None)
    parser.add_argument("--part2-transcript", type=Path, default=None)
    parser.add_argument("--transcripts-dir", type=Path, default=None)
    parser.add_argument("--transcribe-narrative", action="store_true")
    parser.add_argument("--narrative-model", default="large-v3")
    parser.add_argument("--narrative-device", default="cuda")
    parser.add_argument("--narrative-compute-type", default="float16")
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
    write_json(out_dir / "clips_all_v1.json", {"timeline": timeline.GetName(), "clips": rows})

    all_part_rows = {part.key: rows_for_part(rows, part) for part in PARTS.values()}

    narrative = None
    if not args.skip_narrative_prompt:
        print("\nBuilding all-parts dialogue review prompt (instructions + repetitions + false starts)...")
        narrative = build_narrative_artifacts(
            all_part_rows,
            int(timeline.GetStartFrame()),
            out_dir,
            args,
        )
        print(f"  Narrative clips indexed: {narrative['clip_count']}")
        print(f"  Prompt: {narrative['prompt']}")

    wanted_parts = list(PARTS.values()) if args.part == "all" else [PARTS[args.part]]
    part_reports = []
    for part in wanted_parts:
        part_rows = all_part_rows[part.key]
        if not part_rows:
            raise RuntimeError(f"No V1 clips found for {part.label}: {part.video}")
        print(f"\n{part.label}: {len(part_rows)} V1 clips")
        part_reports.append(build_part_artifacts(part, part_rows, out_dir, args))

    auto_candidates = [c for p in part_reports for c in p["auto_cut_candidates"]]
    review_candidates = [c for p in part_reports for c in p["review_candidates"]]
    report = {
        "schema": "victreebel_cut_candidates_v1",
        "review_policy": "explicit_instruction_then_full_dialogue_then_audio_artifacts",
        "selection_policy": "auto_cut_high_confidence_whole_sections_auto_keep_weak_leads_minimize_user_review_false_positive_averse",
        "review_order": [
            {
                "stage": 1,
                "name": "explicit_instruction_scan",
                "focus": "spoken edit notes, restart declarations, cut-this/tangent removal instructions",
                "artifact": narrative["prompt"] if narrative else None,
            },
            {
                "stage": 2,
                "name": "full_dialogue_llm_review",
                "focus": "repetitions, false starts, abandoned narratives, self-corrections, mid-segment candidates",
                "artifact": narrative["prompt"] if narrative else None,
            },
            {
                "stage": 3,
                "name": "audio_artifact_html_review",
                "focus": "confirmed no-dialogue artifacts, mic bumps, throat clears, transcription hallucinations with evidence, and strong partial-section candidates",
                "artifacts": [p["artifacts"]["review_html"] for p in part_reports],
            },
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": project.GetName(),
        "timeline": timeline.GetName(),
        "timeline_fps": TL_FPS,
        "review_categories": args.review_categories,
        "auto_categories": args.auto_categories,
        "parts": part_reports,
        "counts": {
            "parts": len(part_reports),
            "v1_clips_all": len(rows),
            "auto_cut_candidates": len(auto_candidates),
            "review_candidates": len(review_candidates),
        },
        "narrative": narrative,
        "auto_cut_candidates": auto_candidates,
        "review_candidates": review_candidates,
    }
    report_path = out_dir / "cut_candidates_victreebel.json"
    write_json(report_path, report)
    print(f"\nWrote candidate manifest: {report_path}")
    print(
        "Candidates: "
        f"explicit-instruction/full-dialogue prompt first, then "
        f"{len(auto_candidates)} auto-cut definite, "
        f"{len(review_candidates)} audio-artifact/manual-review"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
