from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse


REPO_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_DIR / "scripts"
SRC_DIR = REPO_DIR / "src"
for path in (REPO_DIR, SCRIPT_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from resolve_mcp.orchestrator.fcpxml_review import load_fcpxml_review_model
from scripts import mark_cut_candidates as MCC


COMMON_REPEAT_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "for",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "this",
    "to",
    "uh",
    "um",
    "we",
    "with",
    "you",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm_file_path(value: str) -> str:
    if value.startswith("file://"):
        parsed = urlparse(value)
        path = unquote(parsed.path)
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path.replace("/", "\\")
    return value


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_word(value: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", value.lower())


def collapse_text(value: str) -> str:
    return " ".join(str(value or "").split())


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def source_label(path_text: str) -> str:
    if not path_text:
        return ""
    return Path(path_text.replace("\\", "/")).name


def clips_from_fcpxml(fcpxml: Path, fps: float) -> tuple[list[dict], str]:
    model = load_fcpxml_review_model(fcpxml, fps=fps, video_only=True)
    clips: list[dict] = []
    first_source = ""
    for idx, segment in enumerate(model.video_segments, start=1):
        source_path = norm_file_path(segment.source_path)
        if source_path and not first_source:
            first_source = source_path
        tl_start = segment.offset_frames / fps
        duration = segment.duration_frames / fps
        src_start = segment.source_start_frames / fps
        clips.append(
            {
                "idx": idx,
                "timeline_clip_idx": idx,
                "tl_start": tl_start,
                "tl_end": tl_start + duration,
                "src_start": src_start,
                "src_end": src_start + duration,
                "duration": duration,
                "source_name": segment.name or source_label(source_path),
                "source_path": source_path,
                "segment_id": segment.id,
            }
        )
    return clips, first_source


def attach_transcript(clips: list[dict], transcript_path: Path) -> list[dict]:
    transcript = read_json(transcript_path)
    segments = transcript.get("segments") if isinstance(transcript, dict) else []
    if not isinstance(segments, list):
        raise ValueError(f"Transcript has no segments array: {transcript_path}")
    MCC.attach_transcript_to_clips(clips, segments)
    MCC.annotate_clip_relationships(clips)
    return clips


def word_stream(clips: list[dict]) -> list[dict]:
    words: list[dict] = []
    for clip in sorted(clips, key=lambda item: item["tl_start"]):
        for word in sorted(clip.get("words_in_clip") or [], key=lambda item: float(item.get("start", 0.0))):
            raw = collapse_text(word.get("word") or "")
            norm = normalize_word(raw)
            if not norm:
                continue
            ws = float(word.get("start", clip["src_start"]))
            we = float(word.get("end", ws))
            midpoint = (ws + we) / 2.0
            tl_mid = clip["tl_start"] + max(0.0, midpoint - clip["src_start"])
            words.append(
                {
                    "word": raw,
                    "norm": norm,
                    "source_start": ws,
                    "source_end": we,
                    "timeline": tl_mid,
                    "clip_idx": clip["idx"],
                }
            )
    words.sort(key=lambda item: (item["timeline"], item["source_start"]))
    return words


def context_words(words: list[dict], index: int, radius: int = 12) -> str:
    start = max(0, index - radius)
    end = min(len(words), index + radius + 1)
    out = []
    for i in range(start, end):
        text = words[i]["word"]
        if i == index:
            text = f"[{text}]"
        out.append(text)
    return " ".join(out)


def clip_context(clips_by_idx: dict[int, dict], clip_idx: int, radius: int = 2) -> str:
    rows = []
    for idx in range(max(1, clip_idx - radius), clip_idx + radius + 1):
        clip = clips_by_idx.get(idx)
        if not clip:
            continue
        words = " ".join(word.get("word", "") for word in (clip.get("words_in_clip") or [])).strip()
        if not words:
            words = " / ".join(t.get("text", "") for t in (clip.get("transcript") or []) if t.get("text")).strip()
        rows.append(f"[{idx}] tl={clip['tl_start']:.2f}-{clip['tl_end']:.2f} src={clip['src_start']:.2f}-{clip['src_end']:.2f}: {collapse_text(words)}")
    return "\n".join(rows)


def add_finding(findings: list[dict], seen: set[tuple], finding: dict) -> None:
    key = (
        finding.get("type"),
        round(float(finding.get("timeline_start", 0.0)), 2),
        round(float(finding.get("timeline_end", 0.0)), 2),
        tuple(finding.get("clip_indexes") or []),
    )
    if key in seen:
        return
    seen.add(key)
    finding["id"] = f"finding_{len(findings) + 1:04d}"
    findings.append(finding)


def deterministic_findings(clips: list[dict], words: list[dict]) -> list[dict]:
    clips_by_idx = {int(clip["idx"]): clip for clip in clips}
    findings: list[dict] = []
    seen: set[tuple] = set()

    for clip in clips:
        words_in = clip.get("words_in_clip") or []
        no_transcript = not any(collapse_text(t.get("text") or "") for t in clip.get("transcript") or [])
        if clip.get("dup_text_cluster_artifact"):
            add_finding(
                findings,
                seen,
                {
                    "type": "short_no_word_cluster_artifact",
                    "severity": "high",
                    "timeline_start": clip["tl_start"],
                    "timeline_end": clip["tl_end"],
                    "source_start": clip["src_start"],
                    "source_end": clip["src_end"],
                    "clip_indexes": [clip["idx"]],
                    "text": clip_context(clips_by_idx, clip["idx"]),
                    "reason": "The clip is a short no-word runt inside a repeated transcript-text cluster.",
                    "suggested_action": "Review as a likely artifact cut.",
                },
            )
        elif no_transcript and not words_in and 0.12 <= clip["duration"] <= 1.2:
            add_finding(
                findings,
                seen,
                {
                    "type": "short_no_transcript_clip",
                    "severity": "medium",
                    "timeline_start": clip["tl_start"],
                    "timeline_end": clip["tl_end"],
                    "source_start": clip["src_start"],
                    "source_end": clip["src_end"],
                    "clip_indexes": [clip["idx"]],
                    "text": clip_context(clips_by_idx, clip["idx"]),
                    "reason": "This short clip has no Whisper words or transcript text after cuts were applied.",
                    "suggested_action": "Listen once; cut if it is a breath, mouth noise, or stray artifact.",
                },
            )
        gap = clip.get("internal_word_gap")
        if gap and float(gap.get("gap_sec") or 0.0) >= 5.0:
            add_finding(
                findings,
                seen,
                {
                    "type": "long_internal_word_gap",
                    "severity": "medium",
                    "timeline_start": clip["tl_start"],
                    "timeline_end": clip["tl_end"],
                    "source_start": clip["src_start"],
                    "source_end": clip["src_end"],
                    "clip_indexes": [clip["idx"]],
                    "text": clip_context(clips_by_idx, clip["idx"]),
                    "reason": (
                        f"Whisper sees a {float(gap['gap_sec']):.2f}s source word gap between "
                        f"{gap.get('before_word')!r} and {gap.get('after_word')!r}."
                    ),
                    "suggested_action": "Check whether the joined thought is coherent after silence stripping.",
                },
            )
        overlap = float(clip.get("src_overlap_with_prev") or 0.0)
        if overlap >= 0.25:
            add_finding(
                findings,
                seen,
                {
                    "type": "source_overlap_with_previous_clip",
                    "severity": "medium",
                    "timeline_start": clip["tl_start"],
                    "timeline_end": min(clip["tl_end"], clip["tl_start"] + overlap),
                    "source_start": clip["src_start"],
                    "source_end": min(clip["src_end"], clip["src_start"] + overlap),
                    "clip_indexes": [max(1, clip["idx"] - 1), clip["idx"]],
                    "text": clip_context(clips_by_idx, clip["idx"], radius=2),
                    "reason": f"This clip overlaps the previous source range by {overlap:.2f}s.",
                    "suggested_action": "Review for audible duplication. Prefer timeline-instance repair over source-time cuts if duplicated words are real.",
                },
            )

    for i in range(len(words) - 1):
        a = words[i]
        b = words[i + 1]
        if a["norm"] != b["norm"]:
            continue
        if a["norm"] in COMMON_REPEAT_WORDS and len(a["norm"]) <= 3:
            continue
        if b["timeline"] - a["timeline"] > 1.5:
            continue
        add_finding(
            findings,
            seen,
            {
                "type": "adjacent_repeated_word",
                "severity": "medium",
                "timeline_start": a["timeline"],
                "timeline_end": b["timeline"],
                "source_start": a["source_start"],
                "source_end": b["source_end"],
                "clip_indexes": sorted({int(a["clip_idx"]), int(b["clip_idx"])}),
                "text": context_words(words, i, radius=10),
                "reason": f"Adjacent repeated word: {a['word']!r}.",
                "suggested_action": "Review as possible stutter or duplicate word; keep if emphatic.",
            },
        )

    occupied: set[int] = set()
    for n in range(8, 1, -1):
        for i in range(0, len(words) - (2 * n) + 1):
            if any(pos in occupied for pos in range(i, i + 2 * n)):
                continue
            left = [word["norm"] for word in words[i : i + n]]
            right = [word["norm"] for word in words[i + n : i + 2 * n]]
            if left != right:
                continue
            if len(set(left) - COMMON_REPEAT_WORDS) < 1:
                continue
            if words[i + n]["timeline"] - words[i + n - 1]["timeline"] > 4.0:
                continue
            for pos in range(i, i + 2 * n):
                occupied.add(pos)
            add_finding(
                findings,
                seen,
                {
                    "type": "adjacent_repeated_phrase",
                    "severity": "high" if n >= 4 else "medium",
                    "timeline_start": words[i + n]["timeline"],
                    "timeline_end": words[i + 2 * n - 1]["timeline"],
                    "source_start": words[i + n]["source_start"],
                    "source_end": words[i + 2 * n - 1]["source_end"],
                    "clip_indexes": sorted({int(word["clip_idx"]) for word in words[i : i + 2 * n]}),
                    "text": context_words(words, i + n, radius=max(10, n * 2)),
                    "reason": f"Immediate repeated {n}-word phrase in the rendered word stream.",
                    "suggested_action": "Review the second phrase as a likely narrative duplicate.",
                },
            )

    findings.sort(key=lambda item: (float(item["timeline_start"]), item["type"]))
    return findings


def actionable_findings(findings: list[dict]) -> list[dict]:
    """Return the compact human-review list from the conservative full finding set."""
    likely_emphasis_words = {"very", "really", "rock", "type", "harden", "game", "low"}
    out: list[dict] = []
    for finding in findings:
        finding_type = finding.get("type")
        if finding_type in {"short_no_word_cluster_artifact", "short_no_transcript_clip", "adjacent_repeated_phrase"}:
            out.append(finding)
            continue
        if finding_type == "adjacent_repeated_word":
            reason = str(finding.get("reason") or "").lower()
            if not any(f"'{word}'" in reason for word in likely_emphasis_words):
                out.append(finding)
    return out


def clip_lines(clips: list[dict]) -> str:
    return "\n".join(MCC.format_clip_line(clip) for clip in clips)


def finding_lines(findings: list[dict]) -> str:
    if not findings:
        return "No deterministic findings."
    lines = []
    for finding in findings:
        lines.append(
            f"- {finding['id']} {finding['severity']} {finding['type']} "
            f"tl={finding['timeline_start']:.2f}-{finding['timeline_end']:.2f}s "
            f"src={finding['source_start']:.2f}-{finding['source_end']:.2f}s "
            f"clips={finding.get('clip_indexes')}: {finding['reason']}\n"
            f"  Context: {collapse_text(finding.get('text', ''))}"
        )
    return "\n".join(lines)


def build_master_prompt(payload: dict) -> str:
    chunks = payload["chunks"]
    findings = payload["deterministic_findings"]
    actionable = payload["actionable_findings"]
    chunk_lines = "\n".join(
        f"- {chunk['id']}: {chunk['path']} ({chunk['start_sec']:.2f}-{chunk['end_sec']:.2f}s, {chunk['clip_count']} clips)"
        for chunk in chunks
    )
    return f"""You are performing a final post-cut narrative audit for a Pokemon minimum-battles video.

This is a start-to-end consistency gate after cut decisions were applied. The goal is
not to find every stylistic improvement; it is to catch remaining narrative errors
that would make the editor waste a 2+ hour listen-through:

- repeated takes or duplicate words that survived earlier cut passes
- abandoned lines before cleaner retakes
- obvious cut-boundary artifacts, throat clears, mic bumps, and empty no-word clips
- confusing joins where the final rendered narrative no longer flows
- explicit edit notes or restart explanations that still remain

Preserve natural Teo cadence, game-mechanic explanation, Pokemon lists, reset
count context, intentional recaps, outro/member beats, and emphasis repeats.

Review every chunk prompt listed below. Return a single JSON array of only the
remaining moments that need human listen/review or cutting. Use final timeline
seconds as `timeline_start_sec`/`timeline_end_sec`, and source seconds as
`start_sec`/`end_sec` when available. If the full pass finds nothing meaningful,
return a JSON array with one row:

{{
  "timeline_start_sec": 0,
  "timeline_end_sec": 0.001,
  "start_sec": 0,
  "end_sec": 0.001,
  "confidence": "low",
  "type": "post_cut_audit_clear",
  "reason": "Full post-cut narrative audit found no remaining actionable narrative cuts."
}}

Output contract: raw JSON array only.

Project: {payload['timeline_name']}
Source FCPXML: {payload['source_fcpxml']}
Final timeline duration: {payload['duration_sec']:.3f}s
Clip count: {payload['clip_count']}
Word count: {payload['word_count']}

## Chunk Prompts

{chunk_lines}

## Deterministic Findings To Check First

The compact actionable subset has {len(actionable)} rows:

{finding_lines(actionable)}

The full conservative finding set has {len(findings)} rows:

{finding_lines(findings)}
"""


def build_chunk_prompt(payload: dict, chunk: dict, clips: list[dict], findings: list[dict]) -> str:
    local_findings = [
        finding
        for finding in findings
        if float(finding["timeline_end"]) >= chunk["start_sec"] and float(finding["timeline_start"]) <= chunk["end_sec"]
    ]
    return f"""You are reviewing one contiguous chunk in a final post-cut narrative audit.

Return only actionable remaining narrative/cut issues in this chunk. This is a
final consistency pass after prior cut decisions, so be conservative and focus
on things a human would otherwise have to catch during a 2+ hour listen.

Use:
- `timeline_start_sec` / `timeline_end_sec` for final timeline positions
- `start_sec` / `end_sec` for source positions when the issue maps to source
- `confidence`: high, medium, or low
- `type`: repeated_word, repeated_phrase, abandoned_thread, boundary_artifact,
  no_word_artifact, confusing_join, explicit_edit_note, restart_explanation, or other
- `reason`: short plain-English explanation

Return raw JSON array only. Empty array is allowed for a chunk if no issue is found.

Project: {payload['timeline_name']}
Chunk: {chunk['id']}
Timeline span: {chunk['start_sec']:.2f}-{chunk['end_sec']:.2f}s
Clips in chunk: {chunk['clip_count']}

## Deterministic Findings In This Chunk

{finding_lines(local_findings)}

## Full Clip List For This Chunk

Each line shows final timeline time (`tl`) and original source time (`src`).
`WORDS_IN_CLIP` is the actual spoken word content carried by that clip.

{clip_lines(clips)}
"""


def build_chunks(clips: list[dict], duration_sec: float, chunk_sec: float, overlap_sec: float) -> list[dict]:
    chunks: list[dict] = []
    start = 0.0
    index = 1
    while start < duration_sec:
        end = min(duration_sec, start + chunk_sec)
        expanded_start = max(0.0, start - overlap_sec)
        expanded_end = min(duration_sec, end + overlap_sec)
        chunk_clips = [
            clip
            for clip in clips
            if clip["tl_end"] >= expanded_start and clip["tl_start"] <= expanded_end
        ]
        chunks.append(
            {
                "id": f"chunk_{index:03d}",
                "start_sec": start,
                "end_sec": end,
                "expanded_start_sec": expanded_start,
                "expanded_end_sec": expanded_end,
                "clip_indexes": [clip["idx"] for clip in chunk_clips],
                "clip_count": len(chunk_clips),
            }
        )
        index += 1
        start = end
    return chunks


def adjacent_groups(positions: list[int]) -> list[list[int]]:
    groups: list[list[int]] = []
    current: list[int] = []
    for position in sorted(set(positions)):
        if current and position == current[-1] + 1:
            current.append(position)
            continue
        if current:
            groups.append(current)
        current = [position]
    if current:
        groups.append(current)
    return groups


def finding_clip_indexes(finding: dict, clips: list[dict]) -> list[int]:
    start = float(finding.get("timeline_start") or 0.0)
    end = float(finding.get("timeline_end") or start)
    indexes = {int(index) for index in finding.get("clip_indexes") or []}
    for clip in clips:
        if float(clip["tl_end"]) <= start or float(clip["tl_start"]) >= end:
            continue
        indexes.add(int(clip["idx"]))
    return sorted(indexes)


def review_manifest_from_audit(
    payload: dict,
    clips: list[dict],
    findings: list[dict],
    out_dir: Path,
    fps: float,
    cap: float,
) -> tuple[Path, Path, Path]:
    clip_indexes_by_finding = {finding["id"]: finding_clip_indexes(finding, clips) for finding in findings}
    pink_indexes = {index for indexes in clip_indexes_by_finding.values() for index in indexes}
    reason_by_i: dict[int, list[str]] = {}
    for finding in findings:
        summary = (
            f"{finding.get('id')} | {finding.get('severity')} | {finding.get('type')} | "
            f"{finding.get('reason')} | {finding.get('suggested_action', '')} | "
            f"{collapse_text(finding.get('text', ''))}"
        )
        for clip_i in clip_indexes_by_finding.get(finding["id"], []):
            reason_by_i.setdefault(int(clip_i), []).append(summary)

    review_clips: list[dict] = []
    for clip in clips:
        clip_i = int(clip["idx"])
        src_start = float(clip["src_start"])
        tl_start = float(clip["tl_start"])
        dur = float(clip["duration"])
        review_clips.append(
            {
                "i": clip_i,
                "timeline_i": int(clip.get("timeline_clip_idx") or clip_i),
                "name": clip.get("source_name") or source_label(clip),
                "start": int(round(tl_start * fps)),
                "dur": max(1, int(round(dur * fps))),
                "left": int(round(src_start * fps)),
                "fps": fps,
                "color": "Pink" if clip_i in pink_indexes else "",
                "src": clip.get("source_path") or payload.get("source_video") or "",
                "role": "post_cut_narrative_audit_review_section",
                "part": 1,
                "part_source_left": int(round(src_start * fps)),
                "combined_left": int(round(src_start * fps)),
            }
        )

    manual_review_candidates = []
    for finding in findings:
        covered = clip_indexes_by_finding.get(finding["id"], [])
        manual_review_candidates.append(
            {
                "id": finding["id"],
                "type": finding.get("type"),
                "category": "post_cut_narrative_audit",
                "confidence": finding.get("severity"),
                "reason": finding.get("reason"),
                "suggested_action": finding.get("suggested_action"),
                "timeline_start_sec": finding.get("timeline_start"),
                "timeline_end_sec": finding.get("timeline_end"),
                "source_start_sec": finding.get("source_start"),
                "source_end_sec": finding.get("source_end"),
                "text": finding.get("text"),
                "section_policy": {
                    "whole_section": False,
                    "covered_section_indexes": covered,
                },
            }
        )

    manifest = {
        "schema": "post_cut_narrative_audit_cut_review_manifest_v1",
        "source_video": payload.get("source_video") or "",
        "dialogue_audio": payload.get("source_video") or "",
        "audit_report": str(out_dir / "audit.json"),
        "manual_review_candidates": manual_review_candidates,
        "auto_cut_candidates": [],
        "structural_cuts": [],
        "structural_restart_reviews": [],
        "structural_review_groups": [],
        "livestream_review": {},
        "clips": review_clips,
        "candidate_count": len(manual_review_candidates),
        "auto_cut_candidate_count": 0,
    }

    clip_pos_by_i = {int(row["i"]): pos for pos, row in enumerate(review_clips)}
    groups = adjacent_groups([clip_pos_by_i[index] for index in pink_indexes if index in clip_pos_by_i])
    group_by_clip_i: dict[int, int] = {}
    segment_by_clip_i: dict[int, tuple[int, float, float]] = {}
    for group_index, group in enumerate(groups):
        pos = 0.0
        first = group[0]
        if first - 1 >= 0:
            ctx = review_clips[first - 1]
            pos += min(float(ctx["dur"]) / fps, cap)
        for clip_pos in group:
            row = review_clips[clip_pos]
            clip_i = int(row["i"])
            duration = float(row["dur"]) / fps
            group_by_clip_i[clip_i] = group_index
            segment_by_clip_i[clip_i] = (group_index, pos, pos + duration)
            pos += duration

    preload_cuts: dict[str, list[list[float]]] = {}
    for finding in findings:
        f_start = float(finding.get("timeline_start") or 0.0)
        f_end = float(finding.get("timeline_end") or f_start)
        for clip_i in clip_indexes_by_finding.get(finding["id"], []):
            if clip_i not in segment_by_clip_i:
                continue
            clip = clips[clip_i - 1] if 0 < clip_i <= len(clips) and int(clips[clip_i - 1]["idx"]) == clip_i else None
            if clip is None:
                clip = next((row for row in clips if int(row["idx"]) == clip_i), None)
            if clip is None:
                continue
            overlap_start = max(f_start, float(clip["tl_start"]))
            overlap_end = min(f_end, float(clip["tl_end"]))
            if overlap_end <= overlap_start:
                continue
            group_index, segment_start, _segment_end = segment_by_clip_i[clip_i]
            local_start = segment_start + (overlap_start - float(clip["tl_start"]))
            local_end = segment_start + (overlap_end - float(clip["tl_start"]))
            if local_end - local_start < 0.01:
                continue
            preload_cuts.setdefault(str(group_index), []).append([round(local_start, 3), round(local_end, 3)])

    for group, ranges in list(preload_cuts.items()):
        merged: list[list[float]] = []
        for start, end in sorted(ranges):
            if not merged or start > merged[-1][1] + 0.02:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        preload_cuts[group] = [[round(start, 3), round(end, 3)] for start, end in merged]

    preload = {
        "pink": {},
        "cuts": preload_cuts,
        "auto": {},
        "restores": {},
        "structural": {},
        "structural_restores": {},
    }
    candidates = {
        "schema": "post_cut_narrative_audit_cut_candidates_v1",
        "source_audit": str(out_dir / "audit.json"),
        "manual_review_candidates": manual_review_candidates,
        "findings": findings,
        "reason_by_clip_index": reason_by_i,
        "suggested_cut_box_count": sum(len(ranges) for ranges in preload_cuts.values()),
    }

    manifest_path = out_dir / "audit_cut_review_clips.json"
    preload_path = out_dir / "audit_cut_review_preload.json"
    candidates_path = out_dir / "audit_cut_review_candidates.json"
    write_json(manifest_path, manifest)
    write_json(preload_path, preload)
    write_json(candidates_path, candidates)
    return manifest_path, preload_path, candidates_path


def build_cut_review_html(payload: dict, clips: list[dict], out_dir: Path, fps: float, cap: float) -> None:
    source_video = payload.get("source_video") or ""
    if not source_video or not Path(source_video).exists():
        raise RuntimeError(f"Cannot build audit cut-review HTML because source video is missing: {source_video}")
    manifest_path, preload_path, _candidates_path = review_manifest_from_audit(
        payload,
        clips,
        payload.get("actionable_findings") or [],
        out_dir,
        fps,
        cap,
    )
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "build_cut_review.py"),
        "--mic",
        source_video,
        "--clips",
        str(manifest_path),
        "--out-dir",
        str(out_dir),
        "--preload",
        str(preload_path),
        "--tl-fps",
        str(fps),
        "--cap",
        str(cap),
    ]
    subprocess.run(cmd, check=True)


def render_html(payload: dict) -> str:
    def table_rows(findings: list[dict]) -> str:
        rows = []
        for finding in findings:
            rows.append(
                "<tr>"
                f"<td>{html.escape(finding['id'])}</td>"
                f"<td>{html.escape(finding['severity'])}</td>"
                f"<td>{html.escape(finding['type'])}</td>"
                f"<td>{fmt_time(finding['timeline_start'])}-{fmt_time(finding['timeline_end'])}</td>"
                f"<td>{finding['source_start']:.2f}-{finding['source_end']:.2f}</td>"
                f"<td>{html.escape(', '.join(map(str, finding.get('clip_indexes') or [])))}</td>"
                f"<td>{html.escape(finding['reason'])}<pre>{html.escape(collapse_text(finding.get('text', '')))}</pre></td>"
                "</tr>"
            )
        if not rows:
            rows.append("<tr><td colspan=\"7\">No findings.</td></tr>")
        return "".join(rows)

    actionable_rows = table_rows(payload["actionable_findings"])
    conservative_rows = table_rows(payload["deterministic_findings"])
    chunk_items = "\n".join(
        f"<li><a href=\"chunks/{html.escape(Path(chunk['path']).name)}\">{html.escape(chunk['id'])}</a> "
        f"{fmt_time(chunk['start_sec'])}-{fmt_time(chunk['end_sec'])} ({chunk['clip_count']} clips)</li>"
        for chunk in payload["chunks"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Post-cut Narrative Audit</title>
<style>
body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #111318; color: #edf1f7; }}
header {{ padding: 16px 20px; border-bottom: 1px solid #303845; background: #171b22; }}
main {{ padding: 18px 20px 28px; }}
h1 {{ margin: 0 0 8px; font-size: 21px; }}
a {{ color: #8db7ff; }}
.meta {{ color: #a7b3c2; display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; }}
.panel {{ border: 1px solid #303845; border-radius: 8px; padding: 14px; background: #1b2029; margin-bottom: 16px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ border-bottom: 1px solid #303845; padding: 8px; vertical-align: top; }}
th {{ color: #a7b3c2; text-align: left; }}
pre {{ white-space: pre-wrap; color: #c8d0db; font-family: Consolas, monospace; font-size: 12px; margin: 6px 0 0; }}
li {{ margin: 4px 0; }}
</style>
</head>
<body>
<header>
  <h1>Post-cut Narrative Audit</h1>
  <div class="meta">
    <span>{html.escape(payload['timeline_name'])}</span>
    <span>{payload['clip_count']} clips</span>
    <span>{fmt_time(payload['duration_sec'])}</span>
    <span>{len(payload['actionable_findings'])} actionable</span>
    <span>{len(payload['deterministic_findings'])} conservative findings</span>
  </div>
</header>
<main>
  <section class="panel">
    <h2>Semantic Review Packet</h2>
    <p>Master prompt: <a href="{html.escape(Path(payload['master_prompt']).name)}">{html.escape(Path(payload['master_prompt']).name)}</a></p>
    <p>Expected reviewed output: <code>{html.escape(payload['expected_output'])}</code></p>
    <ul>{chunk_items}</ul>
  </section>
  <section class="panel">
    <h2>Actionable Findings</h2>
    <table>
      <thead><tr><th>ID</th><th>Severity</th><th>Type</th><th>Timeline</th><th>Source</th><th>Clips</th><th>Reason / Context</th></tr></thead>
      <tbody>{actionable_rows}</tbody>
    </table>
  </section>
  <section class="panel">
    <h2>Full Conservative Findings</h2>
    <table>
      <thead><tr><th>ID</th><th>Severity</th><th>Type</th><th>Timeline</th><th>Source</th><th>Clips</th><th>Reason / Context</th></tr></thead>
      <tbody>{conservative_rows}</tbody>
    </table>
  </section>
</main>
</body>
</html>
"""


def build_audit(args: argparse.Namespace) -> dict:
    clips, inferred_source = clips_from_fcpxml(args.fcpxml, args.fps)
    attach_transcript(clips, args.transcript)
    words = word_stream(clips)
    findings = deterministic_findings(clips, words)
    actionable = actionable_findings(findings)
    duration_sec = max((clip["tl_end"] for clip in clips), default=0.0)
    source_video = str(args.source_video or inferred_source)

    chunks = build_chunks(clips, duration_sec, args.chunk_sec, args.overlap_sec)
    payload = {
        "schema": "minimum_battles_post_cut_narrative_audit_v1",
        "generated_at": now(),
        "timeline_name": args.timeline_name,
        "source_fcpxml": str(args.fcpxml),
        "source_video": source_video,
        "transcript": str(args.transcript),
        "duration_sec": duration_sec,
        "clip_count": len(clips),
        "word_count": len(words),
        "deterministic_finding_count": len(findings),
        "deterministic_findings": findings,
        "actionable_finding_count": len(actionable),
        "actionable_findings": actionable,
        "chunks": chunks,
        "status": "needs_semantic_review",
        "expected_output": str(args.out_dir / "review.out.json"),
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir = args.out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for chunk in chunks:
        chunk_path = chunks_dir / f"{chunk['id']}.in.md"
        chunk_clips = [clips[idx - 1] for idx in chunk["clip_indexes"] if 0 < idx <= len(clips)]
        chunk["path"] = str(chunk_path)
        chunk_path.write_text(build_chunk_prompt(payload, chunk, chunk_clips, findings), encoding="utf-8")

    master_prompt = args.out_dir / "review.in.md"
    payload["master_prompt"] = str(master_prompt)
    master_prompt.write_text(build_master_prompt(payload), encoding="utf-8")
    write_json(args.out_dir / "clip_index.json", clips)
    write_json(args.out_dir / "word_stream.json", words)
    write_json(args.out_dir / "deterministic_findings.json", findings)
    write_json(args.out_dir / "actionable_findings.json", actionable)
    write_json(args.out_dir / "audit.json", payload)
    (args.out_dir / "audit_report.html").write_text(render_html(payload), encoding="utf-8")
    build_cut_review_html(payload, clips, args.out_dir, args.fps, cap=3.0)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a post-cut full narrative audit packet from a cut-applied FCPXML.")
    parser.add_argument("--fcpxml", required=True, type=Path)
    parser.add_argument("--transcript", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--source-video", type=Path, default=None)
    parser.add_argument("--timeline-name", default="Post-cut Narrative Audit")
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--chunk-sec", type=float, default=1200.0)
    parser.add_argument("--overlap-sec", type=float, default=20.0)
    args = parser.parse_args()
    payload = build_audit(args)
    print(f"Wrote {args.out_dir / 'index.html'}")
    print(f"Master prompt: {payload['master_prompt']}")
    print(f"Chunks: {len(payload['chunks'])}")
    print(f"Clips: {payload['clip_count']}, words: {payload['word_count']}, findings: {payload['deterministic_finding_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
