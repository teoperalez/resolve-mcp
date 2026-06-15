"""Generate Mewtwo RBY UMB cut-review artifacts.

Run this immediately after creating the lightweight review base:

  python scripts/build_mewtwo_rby_fcpxml.py --review-base
  python scripts/generate_mewtwo_cut_candidates.py --manifest CODEx/<review-manifest>.json

The output is intentionally review-first and Resolve-free. It first writes the
broad narrative LLM prompt, then runs deterministic waveform, n-gram, and
artifact/short-clip detectors after LLM feedback exists, then compiles every
candidate through FCPXML section-safety rules. High confidence is auto-cut only
for complete auto-editor/FCPXML sections; medium goes to manual review; low is
mark-only on the final Resolve timeline.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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
from scripts import mark_cut_candidates as MCC


DEFAULT_TIMELINE = M.REVIEW_NAME
DEFAULT_MANIFEST = M.CODEX_DIR / f"{M.safe_file_stem(M.REVIEW_NAME)}_manifest.json"
DEFAULT_OUT_DIR = M.CODEX_DIR / "cut_review"
DEFAULT_TRANSCRIPT = M.CODEX_DIR / "transcripts" / f"{M.DIALOGUE_PATH.stem}.json"
TL_FPS = 60.0
STRUCTURAL_CLIP_ID_BASE = 200000
LIVESTREAM_TYPES = {
    "livestream_chat_interaction",
    "livestream_chat_clarification",
    "livestream_chat_aside",
    "livestream_stream_maintenance",
    "livestream_meta_response",
    "chat_interaction",
    "chat_clarification",
    "chat_aside",
    "stream_maintenance",
}
GAMEPLAY_NARRATIVE_TYPES = {
    "false_start",
    "repetition",
    "abandoned_thread",
    "self_correction",
    "mid_clip_false_start",
    "mid_clip_repetition",
    "mid_clip_self_correction",
}


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


def is_livestream_candidate(raw: dict) -> bool:
    values = [
        raw.get("type"),
        raw.get("category"),
        raw.get("kind"),
        raw.get("source"),
    ]
    for value in values:
        text = str(value or "").strip().lower()
        if text in LIVESTREAM_TYPES:
            return True
        if text.startswith(("livestream_", "chat_", "stream_")):
            return True
    return False


def is_gameplay_narrative_candidate(raw: dict) -> bool:
    candidate_type = str(raw.get("type") or "").strip().lower()
    return candidate_type in GAMEPLAY_NARRATIVE_TYPES


def run(cmd: list[str]) -> None:
    print(" ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


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


def set_current_timeline(project, name: str):
    for i in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(i)
        if timeline and (timeline.GetName() or "") == name:
            project.SetCurrentTimeline(timeline)
            return timeline
    raise RuntimeError(f"Timeline not found: {name}")


def dump_manifest_clips(manifest_path: Path) -> tuple[list[dict], str, int]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_video = manifest.get("source_video") or str(M.VIDEO_PATH)
    timeline_name = manifest.get("timeline_name") or manifest_path.stem
    mapping = (manifest.get("spine") or {}).get("audio_source_to_record") or []
    rows: list[dict] = []
    for i, item in enumerate(mapping):
        source_start = int(item["source_start"])
        record_start = int(item["record_start"])
        record_end = int(item["record_end"])
        rows.append(
            {
                "i": i,
                "timeline_i": i,
                "name": Path(source_video).name,
                "start": record_start,
                "dur": record_end - record_start,
                "left": source_start,
                "fps": TL_FPS,
                "color": "",
                "src": resolve_path(source_video),
                "role": item.get("role", "auto"),
            }
        )
    if not rows:
        raise RuntimeError(f"No spine.audio_source_to_record rows in {manifest_path}")
    return rows, timeline_name, 0


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


def artifact_like_waveform(cat: dict, *, review: bool = False) -> bool:
    cat_name = str(cat.get("cat") or "")
    if cat_name == "definite":
        return True
    if not review or cat_name != "possible":
        return False
    run_vs = float(cat.get("run_vs") or 0.0)
    peak = float(cat.get("peak") or 0.0)
    rms = float(cat.get("rms") or 0.0)
    # Keep the medium bucket narrow: this is for short blips with only a trace
    # of voiced energy, not short words that Whisper missed.
    return run_vs < 0.08 or peak < 0.09 or rms < 0.014


CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
DISPOSITION_BY_CONFIDENCE = {
    "high": "auto_cut",
    "medium": "manual_review",
    "low": "mark_only",
}
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "for",
    "from",
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
    "we",
    "with",
    "you",
}
STRUCTURAL_REVIEW_STATUSES = {
    "locked_confirmed",
    "structural_confirmed",
    "revision_needed",
}


def normalize_confidence(value: str | None, default: str = "medium") -> str:
    normalized = (value or default).strip().lower()
    if normalized in CONFIDENCE_RANK:
        return normalized
    return default


def frame_from_seconds(sec: float, fps: float = TL_FPS) -> int:
    return int(round(float(sec) * fps))


def section_index(rows: list[dict]) -> list[dict]:
    sections: list[dict] = []
    for row in rows:
        fps = float(row.get("fps") or TL_FPS)
        start = int(row["left"])
        end = start + int(row["dur"])
        sections.append(
            {
                "clip_index_local": int(row["i"]),
                "clip_index_timeline": int(row.get("timeline_i", row["i"])),
                "source_start_frame": start,
                "source_end_frame": end,
                "source_start_sec": start / fps,
                "source_end_sec": end / fps,
                "timeline_start_frame": int(row["start"]),
                "timeline_end_frame": int(row["start"]) + int(row["dur"]),
                "fps": fps,
            }
        )
    return sorted(sections, key=lambda item: (item["source_start_frame"], item["source_end_frame"]))


def candidate_bounds(raw: dict, fps: float = TL_FPS) -> tuple[int, int]:
    start = raw.get("source_start_frame", raw.get("start_frame"))
    end = raw.get("source_end_frame", raw.get("end_frame"))
    if start is not None and end is not None:
        return int(round(float(start))), int(round(float(end)))
    start_sec = raw.get("source_start_sec", raw.get("start_sec"))
    end_sec = raw.get("source_end_sec", raw.get("end_sec"))
    if start_sec is None or end_sec is None:
        raise ValueError(f"Candidate lacks source bounds: {raw!r}")
    return frame_from_seconds(float(start_sec), fps), frame_from_seconds(float(end_sec), fps)


def classify_section_policy(start_frame: int, end_frame: int, rows: list[dict], tolerance_frames: int = 1) -> dict:
    sections = section_index(rows)
    covered = [
        section
        for section in sections
        if section["source_end_frame"] > start_frame and section["source_start_frame"] < end_frame
    ]
    policy = {
        "whole_section": False,
        "partial_section": False,
        "covered_section_indexes": [section["clip_index_local"] for section in covered],
        "covered_timeline_indexes": [section["clip_index_timeline"] for section in covered],
        "reason": "",
    }
    if not covered:
        policy["partial_section"] = True
        policy["reason"] = "candidate does not overlap a known review-base FCPXML section"
        return policy

    first = covered[0]
    last = covered[-1]
    starts_on_boundary = abs(start_frame - int(first["source_start_frame"])) <= tolerance_frames
    ends_on_boundary = abs(end_frame - int(last["source_end_frame"])) <= tolerance_frames
    fully_covers_all = all(
        start_frame <= int(section["source_start_frame"]) + tolerance_frames
        and end_frame >= int(section["source_end_frame"]) - tolerance_frames
        for section in covered
    )
    whole = starts_on_boundary and ends_on_boundary and fully_covers_all
    policy["whole_section"] = whole
    policy["partial_section"] = not whole
    if whole:
        policy["reason"] = "candidate covers complete FCPXML section boundary/boundaries"
    else:
        policy["reason"] = "candidate starts or ends inside an FCPXML section"
    return policy


def finalized_candidate(raw: dict, rows: list[dict], source: str, proposed_confidence: str = "medium") -> dict:
    start_frame, end_frame = candidate_bounds(raw)
    if end_frame <= start_frame:
        raise ValueError(f"Candidate has invalid source bounds: {raw!r}")

    confidence = normalize_confidence(str(raw.get("confidence") or proposed_confidence), proposed_confidence)
    original_confidence = confidence
    policy = classify_section_policy(start_frame, end_frame, rows)
    downgrade_reasons: list[str] = []

    cut_type = str(raw.get("type") or source)
    if cut_type.startswith("mid_clip_") and confidence == "high":
        confidence = "medium"
        downgrade_reasons.append("mid-clip suggestions require manual review")

    if is_livestream_candidate(raw) and confidence == "high":
        confidence = "medium"
        downgrade_reasons.append("livestream chat/asides require manual review")

    if policy["partial_section"] and confidence == "high":
        confidence = "medium"
        downgrade_reasons.append("high-confidence auto-cuts must remove complete FCPXML sections")

    if not policy["covered_section_indexes"] and confidence != "low":
        confidence = "low"
        downgrade_reasons.append("candidate cannot be mapped to a review-base FCPXML section")

    candidate = dict(raw)
    candidate.update(
        {
            "source": source,
            "source_start_frame": start_frame,
            "source_end_frame": end_frame,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "source_start_sec": round(start_frame / TL_FPS, 6),
            "source_end_sec": round(end_frame / TL_FPS, 6),
            "start_sec": round(start_frame / TL_FPS, 6),
            "end_sec": round(end_frame / TL_FPS, 6),
            "duration_frames": end_frame - start_frame,
            "confidence": confidence,
            "original_confidence": original_confidence,
            "disposition": DISPOSITION_BY_CONFIDENCE[confidence],
            "auto_apply_allowed": confidence == "high" and policy["whole_section"],
            "manual_review_required": confidence == "medium",
            "final_timeline_mark_color": "Pink" if confidence == "low" else "",
            "section_policy": policy,
        }
    )
    if downgrade_reasons:
        candidate["downgrade_reason"] = "; ".join(downgrade_reasons)
    if policy["covered_section_indexes"]:
        candidate.setdefault("clip_index_local", policy["covered_section_indexes"][0])
        candidate.setdefault("clip_index_timeline", policy["covered_timeline_indexes"][0])
    return candidate


def dedupe_candidates(candidates: list[dict]) -> list[dict]:
    merged: dict[tuple[int, int], dict] = {}
    for candidate in candidates:
        key = (int(candidate["source_start_frame"]), int(candidate["source_end_frame"]))
        existing = merged.get(key)
        if existing is None:
            clone = dict(candidate)
            clone["sources"] = [candidate.get("source", "unknown")]
            clone["reasons"] = [candidate.get("reason", "")]
            merged[key] = clone
            continue
        existing["sources"] = sorted(set(existing.get("sources", []) + [candidate.get("source", "unknown")]))
        if candidate.get("reason"):
            existing.setdefault("reasons", []).append(candidate["reason"])
        if is_livestream_candidate(existing) or is_livestream_candidate(candidate):
            keep_sources = existing.get("sources", [])
            keep_reasons = existing.get("reasons", [])
            if is_livestream_candidate(candidate):
                existing.update(candidate)
            existing["sources"] = keep_sources
            existing["reasons"] = keep_reasons
            existing["confidence"] = "medium"
            existing["disposition"] = DISPOSITION_BY_CONFIDENCE["medium"]
            existing["auto_apply_allowed"] = False
            existing["manual_review_required"] = True
            reason = "livestream chat/asides require manual review"
            prior = str(existing.get("downgrade_reason") or "")
            if reason not in prior:
                existing["downgrade_reason"] = "; ".join(item for item in (prior, reason) if item)
            continue
        if CONFIDENCE_RANK[candidate["confidence"]] > CONFIDENCE_RANK[existing["confidence"]]:
            keep_sources = existing.get("sources", [])
            keep_reasons = existing.get("reasons", [])
            existing.clear()
            existing.update(candidate)
            existing["sources"] = keep_sources
            existing["reasons"] = keep_reasons
    return sorted(merged.values(), key=lambda item: (item["source_start_frame"], item["source_end_frame"]))


def normalize_word(value: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", value.lower())


def load_narrative_clips(out_dir: Path, args: argparse.Namespace, rows: list[dict], timeline_start_frame: int) -> list[dict]:
    index_path = out_dir / "narrative" / "clip_index.json"
    if not index_path.exists():
        build_narrative_artifacts(rows, timeline_start_frame, out_dir, args)
    return json.loads(index_path.read_text(encoding="utf-8"))


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


def structural_review_groups() -> list[dict]:
    raw_intervals = M.parse_autoeditor_intervals(M.RAW_AUTOEDITOR_FCPXML)
    groups: list[dict] = []
    next_clip_id = STRUCTURAL_CLIP_ID_BASE
    for group_index, cut in enumerate(locked_manual_cuts()):
        cut_start = int(cut["start_frame"])
        cut_end = int(cut["end_frame"])
        sections: list[dict] = []
        for raw_index, clip in enumerate(raw_intervals):
            start = max(int(clip.start), cut_start)
            end = min(int(clip.end), cut_end)
            if end <= start:
                continue
            section = {
                "i": next_clip_id,
                "timeline_i": next_clip_id,
                "name": M.VIDEO_PATH.name,
                # Structural review rows live in source-frame space. Setting
                # start=left lets the decision normalizer map them directly
                # back to source cuts while still reusing the same HTML widgets.
                "start": start,
                "dur": end - start,
                "left": start,
                "fps": TL_FPS,
                "color": "",
                "src": resolve_path(M.VIDEO_PATH),
                "role": "structural_review",
                "structural_group": group_index,
                "structural_label": cut["label"],
                "structural_source_start_frame": cut_start,
                "structural_source_end_frame": cut_end,
                "raw_interval_index": raw_index,
            }
            sections.append(section)
            next_clip_id += 1
        groups.append(
            {
                **cut,
                "group": group_index,
                "sections": sections,
                "section_indexes": [section["i"] for section in sections],
                "section_count": len(sections),
                "html_review_required": True,
                "default_decision": "cut",
            }
        )
    return groups


def transcript_segment_bounds(segment: dict) -> tuple[float, float]:
    return float(segment.get("start", 0.0)), float(segment.get("end", segment.get("start", 0.0)))


def transcript_excerpt(segments: list[dict], start_sec: float, end_sec: float, max_chars: int = 1800) -> str:
    lines = []
    for segment in segments:
        seg_start, seg_end = transcript_segment_bounds(segment)
        if seg_end <= start_sec or seg_start >= end_sec:
            continue
        text = " ".join(str(segment.get("text") or "").split())
        if not text:
            continue
        lines.append(f"[{seg_start:.2f}-{seg_end:.2f}] {text}")
    excerpt = "\n".join(lines)
    if len(excerpt) > max_chars:
        return excerpt[: max_chars - 18].rstrip() + "\n[excerpt truncated]"
    return excerpt


def build_locked_cut_context(transcript_path: Path, manual_cuts: list[dict]) -> list[dict]:
    if not transcript_path.exists():
        return []
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    segments = transcript.get("segments", [])
    contexts = []
    for cut in manual_cuts:
        start_sec = float(cut["start_sec"])
        end_sec = float(cut["end_sec"])
        contexts.append(
            {
                "label": cut["label"],
                "proposed_start_sec": start_sec,
                "proposed_end_sec": end_sec,
                "before_context": transcript_excerpt(segments, start_sec - 25.0, start_sec, max_chars=900),
                "cut_opening": transcript_excerpt(segments, start_sec, min(end_sec, start_sec + 65.0)),
                "cut_closing": transcript_excerpt(segments, max(start_sec, end_sec - 65.0), end_sec),
                "after_context": transcript_excerpt(segments, end_sec, end_sec + 25.0, max_chars=900),
            }
        )
    return contexts


def build_mewtwo_prompt(clips: list[dict], transcript_path: Path, manual_cuts: list[dict], args: argparse.Namespace) -> str:
    body = "\n".join(MCC.format_clip_line(c) for c in clips)
    locked_context = build_locked_cut_context(transcript_path, manual_cuts)
    gameplay_cut_guidance = (
        "Because `bypass gameplay narrative cuts` is enabled, do not return ordinary "
        "gameplay polish cuts such as false starts, repeated explanations, abandoned "
        "mechanics thoughts, or self-corrections unless they are also explicit edit "
        "notes, restart/structural issues, or livestream chat/asides."
        if args.bypass_gameplay_narrative_cuts
        else (
            "Focus on false starts, repetitions, abandoned narrative threads, "
            "self-corrections, explicit edit notes, and restart explanations."
        )
    )
    livestream_guidance = ""
    livestream_types = ""
    livestream_example = ""
    if args.livestream_edit:
        if args.livestream_cut_chat_interactions:
            livestream_guidance = """
## Livestream/VOD Edit Rules

This run is being reviewed as a livestream edit. In addition to structural
restart verification, identify sections where Teo is responding to chat,
clarifying an aside for chat, doing stream/meta maintenance, or discussing a
tangent that does not advance the main Mewtwo Red/Blue run. Good livestream
candidates include:

- replies to chat messages or usernames when the exchange does not explain the run
- stream maintenance, recording/tech checks, moderation/sub/gift callouts, or chat meta
- side stories, clarifications, or back-and-forth detached from current gameplay
- chat-driven tangents that interrupt the run's clean VOD narrative

Do not flag chat-aware dialogue that directly explains the current route,
mechanics, battle plan, reset count, ROM/version behavior, or why a gameplay
decision matters. For every livestream candidate, include:

- `type`: one of the livestream/chat type values below
- `category`: a short category such as `chat_reply`, `stream_meta`,
  `viewer_clarification`, `off_run_aside`, `tech_check`, or `chat_tangent`
- `thread`: a concise narrative thread label grouping related asides, e.g.
  `ROM setup clarification`, `chat response about routing`, `stream tech`, `off-topic aside`
- `reason`: why this exchange can be removed without harming the main run narrative

Livestream/chat cuts are review candidates, not automatic cuts; prefer
`confidence: "medium"` unless the row is one of the locked structural restarts.
"""
            livestream_types = (
                ", livestream_chat_interaction, livestream_chat_clarification, "
                "livestream_chat_aside, livestream_stream_maintenance, "
                "livestream_meta_response"
            )
            livestream_example = """  {
    "start_sec": 456.10,
    "end_sec": 471.25,
    "confidence": "medium",
    "type": "livestream_chat_aside",
    "category": "off_run_aside",
    "thread": "chat tangent about setup",
    "reason": "Teo answers chat on a side topic that does not affect the current run plan."
  },
"""
        else:
            livestream_guidance = """
## Livestream/VOD Edit Rules

Livestream mode is enabled, but chat/asides detection is off for this pass. Do
not add chat-specific cuts unless they also satisfy the ordinary narrative or
structural cut rules.
"""
    return f"""You are reviewing a Mewtwo Pokemon Red/Blue Ultra Minimum Battles redo timeline before any heavy rebuild steps.

## Review Contract

Return only strong cut candidates that should be reviewed or applied before the
final rebuild. {gameplay_cut_guidance} Do not cut
natural Teo cadence, useful game-mechanic explanation, battle context, reset
count information, or intentional recap.

{livestream_guidance}

These structural restart ranges are proposed separately from ordinary gameplay
narrative cuts. Verify them using the transcript context and include one JSON
record for each structural restart cut in your output:

- Use `status: "locked_confirmed"` when the proposed source-time bounds are correct.
- Use `status: "revision_needed"` and corrected `start_sec` / `end_sec` if the
  transcript shows the structural cut boundaries should move.
- These structural restart rows document the proposed source-time boundaries.
  The HTML review lets the editor cut/restore the underlying FCPXML sections.

{json.dumps(manual_cuts, indent=2)}

Transcript context for the structural restart ranges:

{json.dumps(locked_context, indent=2)}

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
  }},
{livestream_example}
  {{
    "label": "remove_full_run_restart_explanation",
    "start_sec": 1818.50,
    "end_sec": 2080.53,
    "confidence": "locked",
    "type": "full_restart",
    "status": "locked_confirmed",
    "reason": "The source leaves the failed Ice Beam/save-state branch and resumes at the clean Brock retry plan."
  }}
]

Allowed `type` values: explicit_restart_cut, explicit_edit_note, false_start, repetition,
abandoned_thread, full_restart, self_correction, mid_clip_false_start,
mid_clip_repetition, mid_clip_self_correction{livestream_types}.
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
        build_mewtwo_prompt(clips, transcript_path, manual_cuts, args),
        encoding="utf-8",
    )

    return {
        "clip_count": len(clips),
        "transcript": str(transcript_path),
        "clip_index": str(index_path),
        "prompt": str(prompt_path),
        "expected_output": str(out_path),
    }


def build_waveform_candidates(rows: list[dict], out_dir: Path, args: argparse.Namespace) -> dict:
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
    candidates = []
    for row in rows:
        cat = categories_by_i.get(int(row["i"]), {})
        cat_name = cat.get("cat", "")
        if cat_name in auto_cats:
            candidates.append(finalized_candidate(clip_candidate(row, cat, "auto"), rows, "waveform", "high"))
        elif args.include_possible_waveform_review and cat_name in review_cats and artifact_like_waveform(cat, review=True):
            candidates.append(finalized_candidate(clip_candidate(row, cat, "review"), rows, "waveform", "medium"))

    waveform_path = out_dir / "waveform_candidates.json"
    write_json(
        waveform_path,
        {
            "schema": "mewtwo_waveform_candidates_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidates": candidates,
            "categories": str(categories_path),
            "clips": str(clips_path),
        },
    )
    return {
        "candidates": candidates,
        "clips": str(clips_path),
        "categories": str(categories_path),
        "waves": str(out_dir / "waves_candidates.png"),
        "waveform_candidates": str(waveform_path),
    }


def build_ngram_candidates(rows: list[dict], out_dir: Path, args: argparse.Namespace, timeline_start_frame: int) -> dict:
    clips = load_narrative_clips(out_dir, args, rows, timeline_start_frame)
    words: list[dict] = []
    for clip in clips:
        for word in clip.get("words_in_clip") or []:
            token = normalize_word(str(word.get("word") or ""))
            if not token:
                continue
            words.append({"token": token, "word": word.get("word", ""), "start": float(word["start"]), "end": float(word["end"])})
    words.sort(key=lambda item: item["start"])

    diagnostics: list[dict] = []
    seen_keys: set[tuple[int, int]] = set()
    last_seen: dict[tuple[str, ...], int] = {}
    for n in (5, 4, 3):
        last_seen.clear()
        for i in range(0, max(0, len(words) - n + 1)):
            phrase = tuple(words[i + j]["token"] for j in range(n))
            if any(not token for token in phrase):
                continue
            if not any(token not in STOPWORDS and len(token) > 3 for token in phrase):
                continue
            previous = last_seen.get(phrase)
            last_seen[phrase] = i
            if previous is None:
                continue
            gap = float(words[i]["start"]) - float(words[previous + n - 1]["end"])
            if gap < 0.05 or gap > 12.0:
                continue
            start_sec = float(words[previous]["start"])
            end_sec = float(words[previous + n - 1]["end"])
            key = (frame_from_seconds(start_sec), frame_from_seconds(end_sec))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            phrase_text = " ".join(word["word"].strip() for word in words[previous:previous + n]).strip()
            raw = {
                "start_sec": start_sec,
                "end_sec": end_sec,
                "confidence": "medium",
                "type": "ngram_repetition",
                "reason": f"Programmatic {n}-gram repeat within {gap:.2f}s: {phrase_text!r}.",
                "metrics": {
                    "ngram_size": n,
                    "repeat_gap_sec": round(gap, 4),
                    "phrase": phrase_text,
                    "second_start_sec": round(float(words[i]["start"]), 4),
                },
            }
            diagnostics.append(finalized_candidate(raw, rows, "ngram", "medium"))
            if len(diagnostics) >= int(args.max_ngram_candidates):
                break
        if len(diagnostics) >= int(args.max_ngram_candidates):
            break

    candidates = diagnostics if args.include_ngram_review else []

    path = out_dir / "ngram_candidates.json"
    write_json(
        path,
        {
            "schema": "mewtwo_ngram_candidates_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": (
                "N-gram matches are diagnostics by default. Exact phrase repeats "
                "are not reliable cut candidates without narrative confirmation."
            ),
            "candidates": candidates,
            "diagnostics": diagnostics,
            "include_ngram_review": bool(args.include_ngram_review),
        },
    )
    return {"candidates": candidates, "ngram_candidates": str(path)}


def build_artifact_candidates(rows: list[dict], out_dir: Path, args: argparse.Namespace, timeline_start_frame: int) -> dict:
    clips = load_narrative_clips(out_dir, args, rows, timeline_start_frame)
    row_by_idx = {int(row["i"]): row for row in rows}
    categories_path = out_dir / "categories.json"
    categories = json.loads(categories_path.read_text(encoding="utf-8")) if categories_path.exists() else []
    categories_by_i = {int(cat["i"]): cat for cat in categories if "i" in cat}
    candidates: list[dict] = []
    for clip in clips:
        row = row_by_idx.get(int(clip["idx"]) - 1)
        if not row:
            continue
        cat = categories_by_i.get(int(row["i"]), {})
        has_words = bool(clip.get("words_in_clip"))
        duration = float(clip.get("duration") or 0.0)
        raw = {
            "source_start_sec": float(clip["src_start"]),
            "source_end_sec": float(clip["src_end"]),
            "timeline_start_frame": int(row["start"]),
            "timeline_end_frame": int(row["start"]) + int(row["dur"]),
            "clip_index_local": int(row["i"]),
            "clip_index_timeline": int(row.get("timeline_i", row["i"])),
            "metrics": {
                "duration_sec": round(duration, 6),
                "words_in_clip": len(clip.get("words_in_clip") or []),
                "dup_text_cluster_size": clip.get("dup_text_cluster_size"),
                "waveform_cat": cat.get("cat"),
                "waveform_rms": cat.get("rms"),
                "waveform_peak": cat.get("peak"),
                "waveform_run_vs": cat.get("run_vs"),
                "waveform_zcr": cat.get("zcr"),
            },
        }
        if not has_words and duration <= 0.25:
            if not artifact_like_waveform(cat, review=False):
                continue
            raw.update(
                {
                    "confidence": "high",
                    "type": "empty_extremely_short_artifact",
                    "reason": "Extremely short FCPXML section with no word-level transcript content and definite artifact-like waveform.",
                }
            )
            candidates.append(finalized_candidate(raw, rows, "artifact_short_clip", "high"))
        elif not has_words and duration <= 0.70:
            if not artifact_like_waveform(cat, review=True):
                continue
            raw.update(
                {
                    "confidence": "medium",
                    "type": "empty_short_artifact_review",
                    "reason": "Short FCPXML section with no word-level transcript content and borderline artifact-like waveform.",
                }
            )
            candidates.append(finalized_candidate(raw, rows, "artifact_short_clip", "medium"))
        elif clip.get("dup_text_cluster_artifact"):
            if not artifact_like_waveform(cat, review=True):
                continue
            raw.update(
                {
                    "confidence": "medium",
                    "type": "duplicate_text_cluster_artifact",
                    "reason": "Short duplicate-text cluster member with no real words inside the clip.",
                }
            )
            candidates.append(finalized_candidate(raw, rows, "artifact_short_clip", "medium"))

    path = out_dir / "artifact_candidates.json"
    write_json(
        path,
        {
            "schema": "mewtwo_artifact_short_clip_candidates_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidates": candidates,
        },
    )
    return {"candidates": candidates, "artifact_candidates": str(path)}


def build_programmatic_candidates(rows: list[dict], out_dir: Path, args: argparse.Namespace, timeline_start_frame: int) -> dict:
    waveform = build_waveform_candidates(rows, out_dir, args)
    ngram = build_ngram_candidates(rows, out_dir, args, timeline_start_frame)
    artifacts = build_artifact_candidates(rows, out_dir, args, timeline_start_frame)
    candidates = waveform["candidates"] + ngram["candidates"] + artifacts["candidates"]
    path = out_dir / "programmatic_candidates.json"
    write_json(
        path,
        {
            "schema": "mewtwo_programmatic_candidates_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "detectors": {
                "waveform": waveform.get("waveform_candidates"),
                "ngram": ngram.get("ngram_candidates"),
                "artifact_short_clip": artifacts.get("artifact_candidates"),
            },
            "candidates": candidates,
        },
    )
    return {
        "candidates": candidates,
        "artifacts": {
            **{key: value for key, value in waveform.items() if key != "candidates"},
            **{key: value for key, value in ngram.items() if key != "candidates"},
            **{key: value for key, value in artifacts.items() if key != "candidates"},
            "programmatic_candidates": str(path),
        },
    }


def load_candidate_file(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    for key in ("candidates", "cuts", "source_cuts"):
        if isinstance(payload.get(key), list):
            return payload[key]
    raise RuntimeError(f"Candidate file does not contain a candidate list: {path}")


def load_narrative_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    for key in ("candidates", "cuts"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def is_structural_narrative_review(raw: dict) -> bool:
    status = str(raw.get("status") or "").strip().lower()
    if status in STRUCTURAL_REVIEW_STATUSES:
        return True
    locked_labels = {cut["label"] for cut in locked_manual_cuts()}
    cut_type = str(raw.get("type") or "").strip().lower()
    return raw.get("label") in locked_labels and cut_type in {"explicit_restart_cut", "full_restart"}


def load_narrative_structural_reviews(path: Path) -> list[dict]:
    locked_by_label = {cut["label"]: cut for cut in locked_manual_cuts()}
    reviews = []
    for raw in load_narrative_rows(path):
        if not is_structural_narrative_review(raw):
            continue
        row = dict(raw)
        start_frame, end_frame = candidate_bounds(row)
        label = row.get("label") or row.get("type") or "structural_restart_cut"
        reference = locked_by_label.get(label)
        row.update(
            {
                "label": label,
                "source": "narrative_llm_structural_review",
                "source_video": row.get("source_video") or str(M.VIDEO_PATH),
                "source_start_frame": start_frame,
                "source_end_frame": end_frame,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "source_start_sec": round(start_frame / TL_FPS, 6),
                "source_end_sec": round(end_frame / TL_FPS, 6),
                "start_sec": round(start_frame / TL_FPS, 6),
                "end_sec": round(end_frame / TL_FPS, 6),
                "confidence": row.get("confidence") or "locked",
                "status": row.get("status") or "locked_confirmed",
                "structural_cut": True,
                "html_review_required": False,
                "final_rebuild_cut": True,
            }
        )
        if reference:
            row["locked_reference"] = reference
            row["matches_locked_reference"] = (
                abs(start_frame - int(reference["start_frame"])) <= 2
                and abs(end_frame - int(reference["end_frame"])) <= 2
            )
        reviews.append(row)
    return reviews


def load_narrative_candidates(path: Path, rows: list[dict], args: argparse.Namespace) -> list[dict]:
    candidates = []
    for raw in load_narrative_rows(path):
        if is_structural_narrative_review(raw):
            continue
        if raw.get("status") in {"reject", "rejected", "keep"}:
            continue
        if args.bypass_gameplay_narrative_cuts and is_gameplay_narrative_candidate(raw) and not is_livestream_candidate(raw):
            continue
        candidates.append(finalized_candidate(raw, rows, "narrative_llm", normalize_confidence(raw.get("confidence"), "medium")))
    return candidates


def build_compiled_review_html(
    rows: list[dict],
    medium_candidates: list[dict],
    auto_candidates: list[dict],
    structural_reviews: list[dict],
    out_dir: Path,
    args: argparse.Namespace,
) -> dict:
    review_dir = out_dir / "review"
    categories_path = out_dir / "categories.json"
    review_section_indexes = {
        int(index)
        for candidate in medium_candidates
        for index in candidate.get("section_policy", {}).get("covered_section_indexes", [])
    }
    auto_section_indexes = {
        int(index)
        for candidate in auto_candidates
        for index in candidate.get("section_policy", {}).get("covered_section_indexes", [])
    }
    structural_groups = structural_review_groups()
    structural_reviews_by_label = {str(row.get("label")): row for row in structural_reviews}
    structural_rows = []
    for group in structural_groups:
        review = structural_reviews_by_label.get(str(group.get("label")))
        if review:
            group["llm_review"] = review
            group["status"] = review.get("status") or group.get("status")
            group["reason"] = review.get("reason") or group.get("reason")
            group["matches_locked_reference"] = review.get("matches_locked_reference")
        structural_rows.extend(group.get("sections") or [])
    review_rows = []
    for row in rows:
        review_row = dict(row)
        if int(row["i"]) in review_section_indexes:
            review_row["color"] = "Pink"
        review_rows.append(review_row)
    review_rows.extend(structural_rows)

    review_clips_path = out_dir / "clips_for_review.json"
    write_json(
        review_clips_path,
        {
            "source_video": str(M.VIDEO_PATH),
            "dialogue_audio": str(M.DIALOGUE_PATH),
            "structural_cuts": locked_manual_cuts(),
            "structural_restart_reviews": structural_reviews,
            "structural_review_groups": structural_groups,
            "manual_review_candidates": medium_candidates,
            "auto_cut_candidates": auto_candidates,
            "livestream_review": {
                "enabled": bool(args.livestream_edit),
                "cut_chat_interactions": bool(args.livestream_cut_chat_interactions),
                "bypass_gameplay_narrative_cuts": bool(args.bypass_gameplay_narrative_cuts),
            },
            "clips": review_rows,
            "candidate_count": len(medium_candidates),
            "auto_cut_candidate_count": len(auto_candidates),
        },
    )

    if not args.skip_html and (review_section_indexes or auto_section_indexes or structural_groups):
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / "build_cut_review.py"),
            "--mic",
            str(M.DIALOGUE_PATH),
            "--clips",
            str(review_clips_path),
            "--out-dir",
            str(review_dir),
            "--sr",
            str(args.review_sr),
            "--tl-fps",
            str(TL_FPS),
        ]
        if categories_path.exists():
            cmd.extend(["--categories", str(categories_path)])
        preload = review_dir / "pink_decisions.json"
        if preload.exists():
            cmd.extend(["--preload", str(preload)])
        if args.reuse_assets:
            cmd.append("--reuse-assets")
        run(cmd)
    else:
        review_dir.mkdir(parents=True, exist_ok=True)
        if not (review_dir / "segmap.json").exists():
            write_json(review_dir / "segmap.json", {})
        if not (review_dir / "index.html").exists():
            (review_dir / "index.html").write_text(
                "<!doctype html><meta charset=\"utf-8\"><title>Cut Review</title>"
                "<body><h1>No medium-confidence cut candidates need manual review.</h1></body>",
                encoding="utf-8",
            )

    return {
        "review_clips": str(review_clips_path),
        "review_html": str(review_dir / "index.html"),
        "segmap": str(review_dir / "segmap.json"),
        "auto_segmap": str(review_dir / "auto_segmap.json"),
        "structural_segmap": str(review_dir / "structural_segmap.json"),
    }


def compile_candidate_manifest(
    rows: list[dict],
    timeline_name: str,
    timeline_start_frame: int,
    out_dir: Path,
    args: argparse.Namespace,
) -> dict:
    narrative_path = out_dir / "narrative" / "mewtwo_narrative_cut_review.out.json"
    waveform_path = out_dir / "waveform_candidates.json"
    ngram_path = out_dir / "ngram_candidates.json"
    artifact_path = out_dir / "artifact_candidates.json"
    programmatic_path = out_dir / "programmatic_candidates.json"
    missing = [path for path in (narrative_path, waveform_path, ngram_path, artifact_path, programmatic_path) if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing candidate compiler input(s):\n" + "\n".join(f"  - {path}" for path in missing))

    narrative_candidates = load_narrative_candidates(narrative_path, rows, args)
    structural_reviews = load_narrative_structural_reviews(narrative_path)
    programmatic_candidates = []
    for path, source in (
        (waveform_path, "waveform"),
        (ngram_path, "ngram"),
        (artifact_path, "artifact_short_clip"),
    ):
        for candidate in load_candidate_file(path):
            programmatic_candidates.append(finalized_candidate(candidate, rows, source, candidate.get("confidence", "medium")))

    all_candidates = dedupe_candidates(narrative_candidates + programmatic_candidates)
    high = [candidate for candidate in all_candidates if candidate["confidence"] == "high"]
    medium = [candidate for candidate in all_candidates if candidate["confidence"] == "medium"]
    low = [candidate for candidate in all_candidates if candidate["confidence"] == "low"]
    livestream_medium = [candidate for candidate in medium if is_livestream_candidate(candidate)]
    review_artifacts = build_compiled_review_html(rows, medium, high, structural_reviews, out_dir, args)

    report = {
        "schema": "mewtwo_cut_candidates_v2",
        "review_policy": "llm_then_programmatic_then_fcpxml_section_safe_compile",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeline": timeline_name,
        "timeline_start_frame": timeline_start_frame,
        "timeline_fps": TL_FPS,
        "livestream_review": {
            "enabled": bool(args.livestream_edit),
            "cut_chat_interactions": bool(args.livestream_cut_chat_interactions),
            "bypass_gameplay_narrative_cuts": bool(args.bypass_gameplay_narrative_cuts),
        },
        "locked_manual_cuts": locked_manual_cuts(),
        "review_order": [
            {
                "stage": 1,
                "name": "broad_narrative_llm_review",
                "artifact": str(narrative_path),
                "focus": "structural restart verification plus semantic false starts, repeated takes, abandoned thoughts, edit notes, and self-corrections",
            },
            {
                "stage": 2,
                "name": "waveform_and_ngram_detection",
                "artifacts": [str(waveform_path), str(ngram_path)],
                "focus": "programmatic waveform anomalies plus repeated n-gram leads",
            },
            {
                "stage": 3,
                "name": "artifact_and_short_clip_detection",
                "artifact": str(artifact_path),
                "focus": "empty transcript clips, extremely short clips, duplicate-text cluster artifacts",
            },
            {
                "stage": 4,
                "name": "fcpxml_section_safe_compiler",
                "focus": "high confidence is allowed only for complete FCPXML sections; partial-section cuts are downgraded",
            },
        ],
        "counts": {
            "v1_clips": len(rows),
            "locked_manual_cuts": len(locked_manual_cuts()),
            "structural_restart_reviews": len(structural_reviews),
            "structural_review_sections": sum(len(group.get("sections") or []) for group in structural_review_groups()),
            "high_confidence_auto_cuts": len(high),
            "medium_confidence_review_candidates": len(medium),
            "livestream_review_candidates": len(livestream_medium),
            "low_confidence_mark_only_candidates": len(low),
            "all_candidates": len(all_candidates),
        },
        "artifacts": {
            "narrative_prompt": str(out_dir / "narrative" / "mewtwo_narrative_cut_review.in.md"),
            "narrative_output": str(narrative_path),
            "waveform_candidates": str(waveform_path),
            "ngram_candidates": str(ngram_path),
            "artifact_candidates": str(artifact_path),
            "programmatic_candidates": str(programmatic_path),
            **review_artifacts,
        },
        "structural_restart_reviews": structural_reviews,
        "structural_review_groups": structural_review_groups(),
        "candidates": all_candidates,
        "high_confidence_auto_cuts": high,
        "medium_confidence_review_candidates": medium,
        "low_confidence_mark_only_candidates": low,
        "auto_cut_candidates": high,
        "review_candidates": medium,
        "mark_only_candidates": low,
    }
    report_path = out_dir / "cut_candidates_mewtwo.json"
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=["narrative-prompt", "programmatic-candidates", "compile", "all"],
        default="all",
        help=(
            "narrative-prompt builds the LLM packet; programmatic-candidates runs "
            "waveform/n-gram/artifact detectors; compile merges LLM + programmatic "
            "outputs with FCPXML section-safety rules."
        ),
    )
    parser.add_argument("--timeline", default=DEFAULT_TIMELINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--from-resolve", action="store_true", help="Read clips from a live Resolve timeline instead of the offline manifest.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--transcript", type=Path, default=DEFAULT_TRANSCRIPT)
    parser.add_argument("--waveform-sr", type=int, default=16000)
    parser.add_argument("--review-sr", type=int, default=44100)
    parser.add_argument("--speech-rms", type=float, default=0.020)
    parser.add_argument("--voiced-zcr", type=float, default=0.25)
    parser.add_argument("--review-categories", default="possible")
    parser.add_argument("--auto-categories", default="definite")
    parser.add_argument(
        "--include-possible-waveform-review",
        action="store_true",
        help="Promote narrowly artifact-like waveform 'possible' clips into manual review. Off by default.",
    )
    parser.add_argument(
        "--include-ngram-review",
        action="store_true",
        help="Promote exact n-gram repeat diagnostics into manual review. Off by default because repeats need narrative confirmation.",
    )
    parser.add_argument("--reuse-assets", action="store_true")
    parser.add_argument("--skip-waveform", action="store_true")
    parser.add_argument("--skip-html", action="store_true")
    parser.add_argument("--skip-narrative-prompt", action="store_true")
    parser.add_argument("--livestream-edit", action="store_true", help="Add livestream/VOD editorial instructions to the narrative LLM prompt.")
    parser.add_argument(
        "--livestream-cut-chat-interactions",
        action="store_true",
        help="Ask the narrative LLM to find chat replies, stream asides, and off-run clarifications for manual review.",
    )
    parser.add_argument(
        "--bypass-gameplay-narrative-cuts",
        action="store_true",
        help="Ignore ordinary gameplay narrative polish cuts from the LLM while keeping structural and livestream candidates.",
    )
    parser.add_argument("--max-ngram-candidates", type=int, default=80)
    args = parser.parse_args()

    args.review_categories = [c.strip() for c in args.review_categories.split(",") if c.strip()]
    args.auto_categories = [c.strip() for c in args.auto_categories.split(",") if c.strip()]
    if args.livestream_cut_chat_interactions:
        args.livestream_edit = True

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.from_resolve:
        resolve, project = connect()
        timeline = set_current_timeline(project, args.timeline)
        resolve.OpenPage("edit")
        timeline_name = timeline.GetName()
        timeline_start_frame = int(timeline.GetStartFrame())
        print(f"Project: {project.GetName()}")
        print(f"Timeline: {timeline_name}")
        rows = dump_v1_clips(timeline)
    else:
        rows, timeline_name, timeline_start_frame = dump_manifest_clips(args.manifest)
        print(f"Manifest: {args.manifest}")
        print(f"Timeline: {timeline_name}")
    print(f"Output: {out_dir}")

    if not rows:
        raise RuntimeError(f"No V1 clips from expected source: {M.VIDEO_PATH}")
    write_json(out_dir / "clips_all_v1.json", {"timeline": timeline_name, "clips": rows})

    narrative = None
    if args.stage in {"narrative-prompt", "all"} and not args.skip_narrative_prompt:
        print("\nBuilding broad narrative LLM review prompt...")
        narrative = build_narrative_artifacts(rows, timeline_start_frame, out_dir, args)
        print(f"  Narrative clips indexed: {narrative['clip_count']}")
        print(f"  Prompt: {narrative['prompt']}")
        if args.stage == "narrative-prompt":
            return 0

    programmatic = None
    if args.stage in {"programmatic-candidates", "all"}:
        narrative_output = out_dir / "narrative" / "mewtwo_narrative_cut_review.out.json"
        if not narrative_output.exists():
            print(
                f"  WARN: LLM narrative output is not present yet: {narrative_output}\n"
                "        Continuing with programmatic detectors only; compile will require the LLM output."
            )
        print("\nRunning programmatic cut-candidate detectors...")
        programmatic = build_programmatic_candidates(rows, out_dir, args, timeline_start_frame)
        print(
            "  Programmatic candidates: "
            f"{len(programmatic['candidates'])} "
            f"({programmatic['artifacts']['programmatic_candidates']})"
        )
        if args.stage == "programmatic-candidates":
            return 0

    if args.stage in {"compile", "all"}:
        print("\nCompiling LLM + programmatic candidates with FCPXML section-safety policy...")
        report = compile_candidate_manifest(rows, timeline_name, timeline_start_frame, out_dir, args)
        print(f"\nWrote candidate manifest: {out_dir / 'cut_candidates_mewtwo.json'}")
        print(
            "Candidates: "
            f"{report['counts']['high_confidence_auto_cuts']} high auto-cut, "
            f"{report['counts']['medium_confidence_review_candidates']} medium review, "
            f"{report['counts']['low_confidence_mark_only_candidates']} low mark-only"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
