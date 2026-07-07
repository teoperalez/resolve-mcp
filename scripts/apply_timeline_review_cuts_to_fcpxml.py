"""Apply HTML review decisions as timeline-frame cuts to an FCPXML.

This is for review bases where source seconds are not globally unique, such as
split recordings that were reviewed in a combined coordinate system. It rewrites
the FCPXML by original timeline offsets, preserves chosen refs such as dialogue
WAVs, ripples later clips/markers left, and can import the result into Resolve.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import _resolve_env  # noqa: F401


ASSET_OPEN_RE = re.compile(r"<asset\s+([^>]+?)>", re.DOTALL)
ASSET_CLIP_RE = re.compile(r"<asset-clip\s+([^>]+?)\s*/>", re.DOTALL)
ASSET_CLIP_ANY_RE = re.compile(
    r"<asset-clip\s+([^>]+?)\s*/>|<asset-clip\s+([^>]+?)>([\s\S]*?)</asset-clip>",
    re.DOTALL,
)
ATTR_RE = re.compile(r"(\w+)=\"([^\"]*)\"")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_rational(value: str) -> int:
    value = (value or "0s").strip()
    if value in {"", "0s"}:
        return 0
    match = re.match(r"^(-?\d+)/(\d+)s$", value)
    if match:
        num, den = int(match.group(1)), int(match.group(2))
        if den != 60:
            return int(round(num * 60 / den))
        return num
    match = re.match(r"^(-?\d+(?:\.\d+)?)s$", value)
    if match:
        return int(round(float(match.group(1)) * 60))
    raise ValueError(f"Cannot parse FCPXML time value: {value!r}")


def fmt_rational(frames: int) -> str:
    return "0s" if int(frames) == 0 else f"{int(frames)}/60s"


def parse_attrs(text: str) -> dict[str, str]:
    return {match.group(1): match.group(2) for match in ATTR_RE.finditer(text)}


def asset_map(xml: str) -> dict[str, dict[str, str]]:
    assets: dict[str, dict[str, str]] = {}
    for match in ASSET_OPEN_RE.finditer(xml):
        attrs = parse_attrs(match.group(1))
        if attrs.get("id"):
            assets[attrs["id"]] = attrs
    return assets


def parse_spine_clips(xml: str) -> list[dict]:
    spine_match = re.search(r"<spine\b[^>]*>([\s\S]*?)</spine>", xml)
    if not spine_match:
        raise ValueError("No <spine> element found")
    clips: list[dict] = []
    for index, match in enumerate(ASSET_CLIP_ANY_RE.finditer(spine_match.group(1))):
        attrs = parse_attrs(match.group(1) or match.group(2) or "")
        clips.append(
            {
                "order": index,
                "ref": attrs.get("ref", ""),
                "name": attrs.get("name", ""),
                "offset": parse_rational(attrs.get("offset", "0s")),
                "duration": parse_rational(attrs.get("duration", "0s")),
                "start": parse_rational(attrs.get("start", "0s")),
                "_attrs": attrs,
                "_children": match.group(3) or "",
            }
        )
    return clips


def review_clip_by_index(clips_data: dict) -> dict[int, dict]:
    clips = clips_data.get("clips", clips_data if isinstance(clips_data, list) else [])
    return {int(row["i"]): row for row in clips if "i" in row}


def source_seconds_to_timeline_frame(clip: dict, source_sec: float, timeline_fps: float) -> int:
    clip_fps = float(clip.get("fps") or timeline_fps)
    source_frame = int(round(source_sec * clip_fps))
    local_source_frames = source_frame - int(clip["left"])
    local_timeline_frames = int(round(local_source_frames * timeline_fps / clip_fps))
    return int(clip["start"]) + local_timeline_frames


def merge_ranges(rows: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for row in sorted(rows, key=lambda item: (int(item["start"]), int(item["end"]), item.get("source", ""))):
        start, end = int(row["start"]), int(row["end"])
        if end <= start:
            continue
        if not merged or start > int(merged[-1]["end"]):
            merged.append({**row, "sources": [row]})
            continue
        merged[-1]["end"] = max(int(merged[-1]["end"]), end)
        merged[-1]["sources"].append(row)
    return merged


def subtract_ranges(base: dict, restores: list[dict]) -> list[dict]:
    fragments = [(int(base["start"]), int(base["end"]))]
    for restore in restores:
        rs, re = int(restore["start"]), int(restore["end"])
        next_fragments: list[tuple[int, int]] = []
        for start, end in fragments:
            overlap_start, overlap_end = max(start, rs), min(end, re)
            if overlap_end <= overlap_start:
                next_fragments.append((start, end))
                continue
            if start < overlap_start:
                next_fragments.append((start, overlap_start))
            if overlap_end < end:
                next_fragments.append((overlap_end, end))
        fragments = next_fragments
    out = []
    for index, (start, end) in enumerate(fragments):
        if end <= start:
            continue
        row = {**base, "start": start, "end": end}
        if len(fragments) > 1:
            row["fragment_index"] = index + 1
        out.append(row)
    return out


def source_cut_from_timeline_range(row: dict, timeline_fps: float) -> dict:
    clip = row["clip"]
    clip_fps = float(clip.get("fps") or timeline_fps)
    local_start = int(row["start"]) - int(clip["start"])
    local_end = int(row["end"]) - int(clip["start"])
    part_left = int(clip.get("part_source_left", clip.get("left", 0)))
    combined_left = int(clip.get("combined_left", clip.get("left", 0)))
    part_start = part_left + int(round(local_start * clip_fps / timeline_fps))
    part_end = part_left + int(round(local_end * clip_fps / timeline_fps))
    combined_start = combined_left + int(round(local_start * clip_fps / timeline_fps))
    combined_end = combined_left + int(round(local_end * clip_fps / timeline_fps))
    part_end = max(part_end, part_start + 1)
    combined_end = max(combined_end, combined_start + 1)
    return {
        "label": row.get("source") or "html_review_cut",
        "part": clip.get("part"),
        "source_video": clip.get("src"),
        "clip_i": clip.get("i"),
        "timeline_start_frame": int(row["start"]),
        "timeline_end_frame": int(row["end"]),
        "part_source_start_frame": part_start,
        "part_source_end_frame": part_end,
        "part_source_start_sec": part_start / clip_fps,
        "part_source_end_sec": part_end / clip_fps,
        "combined_source_start_frame": combined_start,
        "combined_source_end_frame": combined_end,
        "combined_source_start_sec": combined_start / clip_fps,
        "combined_source_end_sec": combined_end / clip_fps,
        "reason": f"approved HTML review cut from clip {clip.get('i')}",
        "origin": row,
    }


def compile_decision_ranges(
    decisions: dict,
    clips_data: dict,
    segmap: dict,
    auto_segmap: dict,
    structural_segmap: dict,
    candidates: dict,
    timeline_fps: float,
) -> tuple[list[dict], dict]:
    clips_by_i = review_clip_by_index(clips_data)
    raw: list[dict] = []
    whole_cut_indices = sorted(int(index) for index, value in (decisions.get("pink") or {}).items() if value == "cut")
    for clip_i in whole_cut_indices:
        clip = clips_by_i.get(clip_i)
        if not clip:
            raise RuntimeError(f"Decision references missing review clip index {clip_i}")
        raw.append({"start": int(clip["start"]), "end": int(clip["start"]) + int(clip["dur"]), "source": "pink_whole_cut", "clip_i": clip_i, "clip": clip})

    partial_records: list[dict] = []
    for group, ranges in (decisions.get("cuts") or {}).items():
        for cut_index, pair in enumerate(ranges):
            snip_start, snip_end = float(pair[0]), float(pair[1])
            if snip_end <= snip_start:
                continue
            for segment in segmap.get(str(group), []):
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
                start = source_seconds_to_timeline_frame(clip, source_start, timeline_fps)
                end = max(source_seconds_to_timeline_frame(clip, source_end, timeline_fps), start + 1)
                record = {
                    "start": start,
                    "end": end,
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
                raw.append(record)
                partial_records.append(record)

    auto_restore_records: list[dict] = []
    for clip_i_str, value in (decisions.get("auto") or {}).items():
        if value not in {"restore", "keep"}:
            continue
        clip = clips_by_i.get(int(clip_i_str))
        if clip:
            auto_restore_records.append({"start": int(clip["start"]), "end": int(clip["start"]) + int(clip["dur"]), "source": "auto_whole_restore", "clip_i": int(clip_i_str), "clip": clip})

    for group, ranges in (decisions.get("restores") or {}).items():
        for restore_index, pair in enumerate(ranges):
            snip_start, snip_end = float(pair[0]), float(pair[1])
            if snip_end <= snip_start:
                continue
            for segment in auto_segmap.get(str(group), []):
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
                start = source_seconds_to_timeline_frame(clip, source_start, timeline_fps)
                end = max(source_seconds_to_timeline_frame(clip, source_end, timeline_fps), start + 1)
                auto_restore_records.append({"start": start, "end": end, "source": "auto_drag_restore", "group": str(group), "restore_index": restore_index, "clip_i": clip_i, "clip": clip})

    auto_rows = candidates.get("high_confidence_auto_cuts") or candidates.get("auto_cut_candidates") or []
    auto_cut_records: list[dict] = []
    for candidate in auto_rows:
        if candidate.get("confidence") != "high" or candidate.get("disposition") not in {"auto_cut", "auto"}:
            continue
        policy = candidate.get("section_policy") or {}
        if not policy.get("whole_section"):
            raise RuntimeError(f"High-confidence auto-cut is not whole-section safe: {candidate!r}")
        for clip_i in policy.get("covered_section_indexes") or [candidate.get("clip_index_local")]:
            if clip_i is None:
                continue
            clip = clips_by_i.get(int(clip_i))
            if not clip:
                raise RuntimeError(f"Auto candidate references missing review clip index {clip_i}")
            base = {
                "start": int(clip["start"]),
                "end": int(clip["start"]) + int(clip["dur"]),
                "source": "high_confidence_auto_cut",
                "clip_i": int(clip_i),
                "candidate": candidate,
                "clip": clip,
            }
            overlapping_restores = [restore for restore in auto_restore_records if int(restore["end"]) > int(base["start"]) and int(restore["start"]) < int(base["end"])]
            for fragment in subtract_ranges(base, overlapping_restores):
                raw.append(fragment)
                auto_cut_records.append(fragment)

    structural_clip_indices = sorted(
        {
            int(segment["clip_idx"])
            for segments in structural_segmap.values()
            for segment in segments
            if segment.get("kind") == "structural" and "clip_idx" in segment
        }
    )
    structural_restore_records: list[dict] = []
    for clip_i_str, value in (decisions.get("structural") or {}).items():
        if value not in {"restore", "keep"}:
            continue
        clip = clips_by_i.get(int(clip_i_str))
        if clip:
            structural_restore_records.append({"start": int(clip["start"]), "end": int(clip["start"]) + int(clip["dur"]), "source": "structural_whole_restore", "clip_i": int(clip_i_str), "clip": clip})

    structural_cut_records: list[dict] = []
    for clip_i in structural_clip_indices:
        if (decisions.get("structural") or {}).get(str(clip_i), "cut") in {"restore", "keep"}:
            continue
        clip = clips_by_i.get(clip_i)
        if not clip:
            raise RuntimeError(f"Structural review references missing review clip index {clip_i}")
        base = {"start": int(clip["start"]), "end": int(clip["start"]) + int(clip["dur"]), "source": "structural_whole_cut", "clip_i": clip_i, "clip": clip}
        overlapping_restores = [restore for restore in structural_restore_records if int(restore["end"]) > int(base["start"]) and int(restore["start"]) < int(base["end"])]
        for fragment in subtract_ranges(base, overlapping_restores):
            raw.append(fragment)
            structural_cut_records.append(fragment)

    merged = merge_ranges(raw)
    source_cuts = [source_cut_from_timeline_range(row, timeline_fps) for row in merged if row.get("clip")]
    metadata = {
        "schema": "timeline_review_decisions_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeline_fps": timeline_fps,
        "whole_cut_indices": whole_cut_indices,
        "partial_records": partial_records,
        "auto_restore_records": auto_restore_records,
        "auto_cut_records": auto_cut_records,
        "structural_cut_records": structural_cut_records,
        "raw_ranges": raw,
        "merged_ranges": merged,
        "source_cuts": source_cuts,
        "total_cut_frames": sum(int(row["end"]) - int(row["start"]) for row in merged),
    }
    return merged, metadata


def intervals_overlap(start: int, end: int, cuts: list[dict]) -> list[tuple[int, int]]:
    overlaps = []
    for cut in cuts:
        cs, ce = int(cut["start"]), int(cut["end"])
        if ce <= start or cs >= end:
            continue
        overlaps.append((max(start, cs), min(end, ce)))
    return overlaps


def split_keep_segments(start: int, end: int, cuts: list[dict]) -> list[tuple[int, int]]:
    kept = [(start, end)]
    for cs, ce in intervals_overlap(start, end, cuts):
        next_kept: list[tuple[int, int]] = []
        for ks, ke in kept:
            if ce <= ks or cs >= ke:
                next_kept.append((ks, ke))
                continue
            if ks < cs:
                next_kept.append((ks, cs))
            if ce < ke:
                next_kept.append((ce, ke))
        kept = [(ks, ke) for ks, ke in next_kept if ke > ks]
    return kept


def removed_before(frame: int, cuts: list[dict]) -> int:
    removed = 0
    for cut in cuts:
        cs, ce = int(cut["start"]), int(cut["end"])
        if frame >= ce:
            removed += ce - cs
        elif frame > cs:
            removed += frame - cs
            break
        else:
            break
    return removed


def remap_frame(frame: int, cuts: list[dict]) -> int | None:
    for cut in cuts:
        cs, ce = int(cut["start"]), int(cut["end"])
        if cs <= frame < ce:
            return None
    return frame - removed_before(frame, cuts)


def marker_attrs_text(attrs: dict[str, str]) -> str:
    ordered = [key for key in ("start", "duration", "value", "completed", "note") if key in attrs]
    ordered.extend(key for key in attrs.keys() if key not in ordered)
    return " ".join(f'{key}="{attrs[key]}"' for key in ordered)


def remap_child_markers(children: str, old_offset: int, new_offset: int, keep_start: int, keep_end: int, cuts: list[dict]) -> str:
    if not children.strip():
        return ""
    out = []
    marker_pat = re.compile(r"<marker\s+([^>]+?)\s*/>", re.DOTALL)
    for match in marker_pat.finditer(children):
        attrs = parse_attrs(match.group(1))
        if "start" not in attrs:
            continue
        old_abs = old_offset + parse_rational(attrs["start"])
        if old_abs < keep_start or old_abs >= keep_end:
            continue
        new_abs = remap_frame(old_abs, cuts)
        if new_abs is None:
            continue
        attrs["start"] = fmt_rational(new_abs - new_offset)
        out.append("              " + f"<marker {marker_attrs_text(attrs)} />")
    if not out:
        return ""
    return "\n" + "\n".join(out) + "\n            "


def kept_refs(assets: dict[str, dict[str, str]], keep_audio_names: list[str]) -> set[str]:
    lowered = [name.lower() for name in keep_audio_names]
    refs: set[str] = set()
    for ref, attrs in assets.items():
        if attrs.get("hasVideo") == "1":
            refs.add(ref)
            continue
        name = (attrs.get("name") or "").lower()
        if lowered and any(needle in name for needle in lowered):
            refs.add(ref)
    return refs


def strip_video_asset_audio(xml: str) -> str:
    def replace_asset(match: re.Match) -> str:
        attrs = parse_attrs(match.group(1))
        if attrs.get("hasVideo") != "1" or attrs.get("hasAudio") != "1":
            return match.group(0)
        attrs = {key: value for key, value in attrs.items() if key not in {"hasAudio", "audioSources", "audioChannels"}}
        ordered = [key for key in ("id", "name", "start", "hasVideo", "format", "duration") if key in attrs]
        ordered.extend(key for key in attrs.keys() if key not in ordered)
        return "<asset " + " ".join(f'{key}="{attrs[key]}"' for key in ordered) + ">"

    return ASSET_OPEN_RE.sub(replace_asset, xml)


def rewrite_fcpxml(
    xml: str,
    cuts: list[dict],
    keep_audio_names: list[str],
    timeline_name: str,
    keep_video_embedded_audio: bool,
) -> tuple[str, dict]:
    assets = asset_map(xml)
    refs = kept_refs(assets, keep_audio_names)
    all_clips = parse_spine_clips(xml)
    clips = [clip for clip in all_clips if clip["ref"] in refs]
    dropped = len(all_clips) - len(clips)
    cuts = merge_ranges(cuts)

    new_clips: list[dict] = []
    removed_ranges = [{"start": int(row["start"]), "end": int(row["end"]), "duration": int(row["end"]) - int(row["start"])} for row in cuts]
    for clip in clips:
        start = int(clip["offset"])
        end = start + int(clip["duration"])
        for keep_start, keep_end in split_keep_segments(start, end, cuts):
            local = keep_start - start
            new_offset = keep_start - removed_before(keep_start, cuts)
            children = remap_child_markers(str(clip.get("_children") or ""), start, new_offset, keep_start, keep_end, cuts)
            new_clips.append(
                {
                    **clip,
                    "offset": new_offset,
                    "start": int(clip["start"]) + local,
                    "duration": keep_end - keep_start,
                    "_children": children,
                }
            )

    def ref_sort(ref: str) -> int:
        attrs = assets.get(ref, {})
        if attrs.get("hasVideo") == "1":
            return 0
        return 1

    new_clips.sort(key=lambda clip: (int(clip["offset"]), ref_sort(str(clip["ref"])), int(clip["order"])))
    lines = []
    for clip in new_clips:
        attrs = dict(clip["_attrs"])
        attrs["offset"] = fmt_rational(int(clip["offset"]))
        attrs["duration"] = fmt_rational(int(clip["duration"]))
        attrs["start"] = fmt_rational(int(clip["start"]))
        ordered_keys = [key for key in ("name", "ref", "lane", "offset", "duration", "start", "tcFormat") if key in attrs]
        ordered_keys.extend(key for key in attrs.keys() if key not in ordered_keys)
        attr_text = " ".join(f'{key}="{attrs[key]}"' for key in ordered_keys)
        children = str(clip.get("_children") or "")
        if children.strip():
            lines.append("            " + f"<asset-clip {attr_text}>{children}</asset-clip>")
        else:
            lines.append("            " + f"<asset-clip {attr_text} />")

    new_spine = "\n" + "\n".join(lines) + "\n          "
    new_xml = re.sub(r"(<spine\b[^>]*>)([\s\S]*?)(</spine>)", lambda match: match.group(1) + new_spine + match.group(3), xml, count=1)
    if not keep_video_embedded_audio:
        new_xml = strip_video_asset_audio(new_xml)

    new_duration = max((int(clip["offset"]) + int(clip["duration"]) for clip in new_clips), default=0)
    new_xml = re.sub(r'(<sequence\b[^>]*\bduration=")[^"]+(")', lambda match: match.group(1) + fmt_rational(new_duration) + match.group(2), new_xml, count=1)
    new_xml = re.sub(r'(<project\b[^>]*\bname=")[^"]+(")', lambda match: match.group(1) + timeline_name + match.group(2), new_xml, count=1)

    dropped_markers = []

    def remap_marker(match: re.Match) -> str:
        attrs = parse_attrs(match.group(1))
        if "start" not in attrs:
            return match.group(0)
        old = parse_rational(attrs["start"])
        new = remap_frame(old, cuts)
        if new is None:
            dropped_markers.append(attrs)
            return ""
        attrs["start"] = fmt_rational(new)
        return "<marker " + marker_attrs_text(attrs) + " />"

    new_xml = re.sub(r"<marker\s+([^>]+?)\s*/>", remap_marker, new_xml)
    report = {
        "input_clip_count": len(all_clips),
        "kept_input_clip_count": len(clips),
        "dropped_input_clip_count": dropped,
        "output_clip_count": len(new_clips),
        "kept_refs": sorted(refs),
        "video_embedded_audio_kept": keep_video_embedded_audio,
        "removed_timeline_ranges": removed_ranges,
        "total_removed_frames": sum(row["duration"] for row in removed_ranges),
        "output_duration_frames": new_duration,
        "dropped_marker_count": len(dropped_markers),
    }
    return new_xml, report


def import_to_resolve(path: Path, timeline_name: str) -> str:
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError("Could not connect to DaVinci Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        raise RuntimeError("No current Resolve project")
    media_pool = project.GetMediaPool()
    existing = {project.GetTimelineByIndex(index).GetName() for index in range(1, int(project.GetTimelineCount() or 0) + 1)}
    final_name = timeline_name
    suffix = 2
    while final_name in existing:
        final_name = f"{timeline_name} {suffix}"
        suffix += 1
    ok = media_pool.ImportTimelineFromFile(str(path), {"timelineName": final_name})
    if not ok:
        raise RuntimeError(f"Resolve failed to import {path}")
    for index in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline and timeline.GetName() == final_name:
            project.SetCurrentTimeline(timeline)
            return final_name
    return final_name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fcpxml", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--clips", required=True, type=Path)
    parser.add_argument("--segmap", required=True, type=Path)
    parser.add_argument("--auto-segmap", type=Path, default=None)
    parser.add_argument("--structural-segmap", type=Path, default=None)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--normalized-out", required=True, type=Path)
    parser.add_argument("--approved-source-cuts-out", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--timeline-name", required=True)
    parser.add_argument("--keep-audio-name", action="append", default=[])
    parser.add_argument("--keep-video-embedded-audio", action="store_true")
    parser.add_argument("--timeline-fps", type=float, default=60.0)
    parser.add_argument("--import-to-resolve", action="store_true")
    args = parser.parse_args()

    decisions = load_json(args.decisions)
    clips_data = load_json(args.clips)
    segmap = load_json(args.segmap)
    auto_segmap = load_json(args.auto_segmap) if args.auto_segmap and args.auto_segmap.exists() else {}
    structural_segmap = load_json(args.structural_segmap) if args.structural_segmap and args.structural_segmap.exists() else {}
    candidates = load_json(args.candidates)
    cuts, metadata = compile_decision_ranges(decisions, clips_data, segmap, auto_segmap, structural_segmap, candidates, args.timeline_fps)

    xml = args.fcpxml.read_text(encoding="utf-8-sig")
    new_xml, rewrite_report = rewrite_fcpxml(xml, cuts, args.keep_audio_name, args.timeline_name, args.keep_video_embedded_audio)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(new_xml, encoding="utf-8")

    write_json(args.normalized_out, metadata)
    write_json(
        args.approved_source_cuts_out,
        {
            "schema": "celebi_approved_source_cuts_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "approval_sources": [str(args.decisions), str(args.candidates), str(args.normalized_out)],
            "source_cuts": metadata["source_cuts"],
        },
    )
    imported_name = import_to_resolve(args.out, args.timeline_name) if args.import_to_resolve else ""
    report = {
        "schema": "timeline_review_cut_fcpxml_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_fcpxml": str(args.fcpxml),
        "output_fcpxml": str(args.out),
        "timeline_name": args.timeline_name,
        "imported_timeline_name": imported_name,
        "normalized_out": str(args.normalized_out),
        "approved_source_cuts": str(args.approved_source_cuts_out),
        "decision_summary": {
            "raw_ranges": len(metadata["raw_ranges"]),
            "merged_ranges": len(metadata["merged_ranges"]),
            "total_cut_frames": metadata["total_cut_frames"],
            "total_cut_seconds": round(metadata["total_cut_frames"] / args.timeline_fps, 3),
        },
        "rewrite": rewrite_report,
    }
    write_json(args.report, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
