"""Apply browser cut-review decisions to the current Resolve timeline natively.

The HTML review tool saves decisions as::

    {"pink": {"clip_idx": "keep|cut"}, "cuts": {"group": [[snip_s, snip_e]]}}

This script consumes that file plus the review page's ``clips_for_review.json``
and ``segmap.json``. It duplicates the current timeline by default, rebuilds V1
and A1 with the approved ranges removed, ripples later clips left, remaps
timeline markers, and writes a validation report.

It intentionally refuses to run if any track beyond V1/A1 is populated. That
keeps the native rebuild safe for the current Victreebel locked-editorial stage;
later pipeline stages with BGM, V2 graphics, or subtitles should use a broader
timeline-aware cutter.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


DEFAULT_OUT_DIR = Path(r"E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\cut_review_locked_autocut")
DEFAULT_DECISIONS = Path(r"C:\Users\teope\Downloads\pink_decisions (12).json")
DEFAULT_CLIPS = DEFAULT_OUT_DIR / "html_review" / "part2" / "clips_for_review.json"
DEFAULT_SEGMAP = DEFAULT_OUT_DIR / "html_review" / "part2" / "review" / "segmap.json"
DEFAULT_TIMELINE_NAME = "Victreebel RBY UMB locked editorial review decisions native"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def unique_timeline_name(project, base: str) -> str:
    existing = set()
    for index in range(1, int(project.GetTimelineCount()) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline:
            existing.add(timeline.GetName())
    if base not in existing:
        return base
    suffix = 2
    while f"{base} {suffix}" in existing:
        suffix += 1
    return f"{base} {suffix}"


def media_path(item) -> str:
    mpi = item.GetMediaPoolItem()
    if not mpi:
        return ""
    try:
        return mpi.GetClipProperty("File Path") or ""
    except Exception:
        return ""


def media_fps(item, timeline_fps: float) -> float:
    mpi = item.GetMediaPoolItem()
    if not mpi:
        return timeline_fps
    try:
        props = mpi.GetClipProperty() or {}
    except Exception:
        return timeline_fps
    for key in ("FPS", "Video Frame Rate", "Frame Rate"):
        try:
            value = float(props.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return timeline_fps


def merge_ranges(ranges: list[dict]) -> list[dict]:
    ordered = sorted(ranges, key=lambda r: (r["start"], r["end"], r.get("source", "")))
    merged: list[dict] = []
    for item in ordered:
        if item["end"] <= item["start"]:
            continue
        if not merged or item["start"] > merged[-1]["end"]:
            merged.append({**item, "sources": [item]})
            continue
        merged[-1]["end"] = max(merged[-1]["end"], item["end"])
        merged[-1]["sources"].append(item)
    return merged


def cut_shift_before(frame: int, cuts: list[dict]) -> int:
    shift = 0
    for cut in cuts:
        if frame >= cut["end"]:
            shift += cut["end"] - cut["start"]
        elif frame > cut["start"]:
            shift += frame - cut["start"]
            break
        else:
            break
    return shift


def frame_inside_cut(frame: int, cuts: list[dict]) -> bool:
    return any(cut["start"] <= frame < cut["end"] for cut in cuts)


def subtract_cuts(start: int, end: int, cuts: list[dict]) -> list[tuple[int, int]]:
    kept = [(start, end)]
    for cut in cuts:
        if cut["end"] <= start or cut["start"] >= end:
            continue
        next_kept: list[tuple[int, int]] = []
        for seg_start, seg_end in kept:
            if cut["end"] <= seg_start or cut["start"] >= seg_end:
                next_kept.append((seg_start, seg_end))
                continue
            if cut["start"] > seg_start:
                next_kept.append((seg_start, cut["start"]))
            if cut["end"] < seg_end:
                next_kept.append((cut["end"], seg_end))
        kept = [(seg_start, seg_end) for seg_start, seg_end in next_kept if seg_end > seg_start]
    return kept


def review_clip_by_index(clips_data: dict) -> dict[int, dict]:
    clips = clips_data["clips"] if isinstance(clips_data, dict) else clips_data
    return {int(row["i"]): row for row in clips}


def source_seconds_to_timeline_frame(clip: dict, source_sec: float, timeline_fps: float) -> int:
    clip_fps = float(clip.get("fps") or timeline_fps)
    source_frame = int(round(source_sec * clip_fps))
    local_source_frames = source_frame - int(clip["left"])
    local_timeline_frames = int(round(local_source_frames * timeline_fps / clip_fps))
    return int(clip["start"]) + local_timeline_frames


def compile_decision_cuts(decisions: dict, clips_data: dict, segmap: dict, timeline_fps: float) -> tuple[list[dict], dict]:
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

    merged = merge_ranges(raw_ranges)
    metadata = {
        "whole_cut_indices": whole_cut_indices,
        "partial_records": partial_records,
        "raw_ranges": raw_ranges,
        "merged_ranges": merged,
        "total_cut_frames": sum(item["end"] - item["start"] for item in merged),
    }
    return merged, metadata


def assert_review_matches_timeline(timeline, clips_data: dict, sample_indices: set[int]) -> None:
    clips_by_i = review_clip_by_index(clips_data)
    v1 = sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda item: item.GetStart())
    failures = []
    for clip_i in sorted(sample_indices):
        clip = clips_by_i.get(clip_i)
        if not clip:
            failures.append(f"missing review clip {clip_i}")
            continue
        timeline_i = int(clip["timeline_i"])
        idx = timeline_i
        if idx < 0 or idx >= len(v1):
            failures.append(f"clip {clip_i}: zero-based timeline_i {timeline_i} out of range")
            continue
        item = v1[idx]
        got = (int(item.GetStart()), int(item.GetDuration()), int(item.GetLeftOffset()), item.GetName())
        want = (int(clip["start"]), int(clip["dur"]), int(clip["left"]), clip["name"])
        if got != want:
            failures.append(f"clip {clip_i}: timeline mismatch got={got!r} want={want!r}")
    if failures:
        raise RuntimeError("Review artifacts do not match the current timeline:\n" + "\n".join(failures[:20]))


def populated_extra_tracks(timeline) -> list[dict]:
    extras: list[dict] = []
    for track_type in ("video", "audio", "subtitle"):
        track_count = int(timeline.GetTrackCount(track_type) or 0)
        for track_index in range(1, track_count + 1):
            items = timeline.GetItemListInTrack(track_type, track_index) or []
            if not items:
                continue
            if track_type == "video" and track_index == 1:
                continue
            if track_type == "audio" and track_index == 1:
                continue
            extras.append({"type": track_type, "track": track_index, "count": len(items)})
    return extras


def collect_track_segments(timeline, track_type: str, track_index: int, media_type: int, cuts: list[dict], timeline_fps: float, reviewed_indices: set[int], review_by_timeline_index: dict[int, int]) -> tuple[list[dict], list[dict]]:
    payload: list[dict] = []
    color_records: list[dict] = []
    items = sorted(timeline.GetItemListInTrack(track_type, track_index) or [], key=lambda item: item.GetStart())
    for zero_based_index, item in enumerate(items):
        mpi = item.GetMediaPoolItem()
        if not mpi:
            raise RuntimeError(f"{track_type}{track_index} clip #{one_based_index} has no media pool item")
        start = int(item.GetStart())
        duration = int(item.GetDuration())
        end = start + duration
        left = int(item.GetLeftOffset())
        clip_fps = media_fps(item, timeline_fps)
        reviewed_clip_i = review_by_timeline_index.get(zero_based_index)
        clear_color = track_type == "video" and reviewed_clip_i in reviewed_indices
        original_color = item.GetClipColor() or ""
        color = "" if clear_color else original_color
        for keep_start, keep_end in subtract_cuts(start, end, cuts):
            local_start = keep_start - start
            local_end = keep_end - start
            source_start = left + int(round(local_start * clip_fps / timeline_fps))
            source_end = left + int(round(local_end * clip_fps / timeline_fps))
            if source_end <= source_start:
                source_end = source_start + 1
            new_record = keep_start - cut_shift_before(keep_start, cuts)
            spec = {
                "mediaPoolItem": mpi,
                "startFrame": source_start,
                "endFrame": source_end,
                "recordFrame": new_record,
                "trackIndex": track_index,
                "mediaType": media_type,
            }
            payload.append(spec)
            color_records.append({
                "track_type": track_type,
                "track_index": track_index,
                "recordFrame": new_record,
                "startFrame": source_start,
                "duration": keep_end - keep_start,
                "name": item.GetName(),
                "color": color,
                "original_color": original_color,
                "reviewed_clip_i": reviewed_clip_i,
            })
    return payload, color_records


def clear_and_restore_markers(timeline, cuts: list[dict], timeline_start: int) -> dict:
    old = timeline.GetMarkers() or {}
    remapped = []
    dropped = []
    for rel_frame_raw, data in old.items():
        rel_frame = int(round(float(rel_frame_raw)))
        abs_frame = timeline_start + rel_frame
        if frame_inside_cut(abs_frame, cuts):
            dropped.append({"frame": rel_frame, "abs_frame": abs_frame, "marker": data})
            continue
        new_abs = abs_frame - cut_shift_before(abs_frame, cuts)
        remapped.append({"old_frame": rel_frame, "new_frame": new_abs - timeline_start, "marker": data})

    for rel_frame_raw in list(old.keys()):
        timeline.DeleteMarkerAtFrame(int(round(float(rel_frame_raw))))

    add_failures = []
    for record in remapped:
        data = record["marker"]
        ok = timeline.AddMarker(
            int(record["new_frame"]),
            data.get("color") or "Blue",
            data.get("name") or "",
            data.get("note") or "",
            int(data.get("duration") or 1),
            data.get("customData") or "",
        )
        if not ok:
            add_failures.append(record)
    return {"original_count": len(old), "remapped_count": len(remapped), "dropped": dropped, "add_failures": add_failures}


def append_payload(media_pool, payload: list[dict], label: str) -> int:
    print(f"Appending {len(payload)} {label} clip segment(s)...", flush=True)
    placed = media_pool.AppendToTimeline(payload) or []
    print(f"  placed {len(placed)}/{len(payload)} {label} clip segment(s)", flush=True)
    return len(placed)


def save_project(resolve, project) -> bool:
    save = getattr(project, "Save", None)
    if callable(save):
        return bool(save())
    project_manager = resolve.GetProjectManager() if resolve else None
    save_project = getattr(project_manager, "SaveProject", None) if project_manager else None
    if callable(save_project):
        return bool(save_project())
    return False


def restore_colors(timeline, color_records: list[dict]) -> dict:
    color_map = {}
    for record in color_records:
        if record["track_type"] != "video" or record["track_index"] != 1:
            continue
        if not record["color"] and not record["original_color"]:
            continue
        key = (record["recordFrame"], record["startFrame"], record["name"])
        color_map[key] = record["color"]

    restored = 0
    cleared = 0
    failures = []
    for item in sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda clip: clip.GetStart()):
        key = (int(item.GetStart()), int(item.GetLeftOffset()), item.GetName())
        if key not in color_map:
            continue
        color = color_map[key]
        if color:
            ok = item.SetClipColor(color)
            if ok:
                restored += 1
            else:
                failures.append({"key": key, "color": color})
        else:
            clear_method = getattr(item, "ClearClipColor", None)
            ok = clear_method() if callable(clear_method) else item.SetClipColor("Default")
            if ok:
                cleared += 1
            else:
                failures.append({"key": key, "color": ""})
    return {"restored": restored, "cleared": cleared, "failures": failures}


def validate_timeline(timeline, expected_end: int, cut_left_offsets: set[int]) -> dict:
    v1 = sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda item: item.GetStart())
    a1 = sorted(timeline.GetItemListInTrack("audio", 1) or [], key=lambda item: item.GetStart())
    a1_by_span = {(int(item.GetStart()), int(item.GetDuration())): item for item in a1}
    missing_a1 = []
    for index, item in enumerate(v1, start=1):
        name = item.GetName() or ""
        if "Intro" in name or "Outro" in name:
            continue
        span = (int(item.GetStart()), int(item.GetDuration()))
        if span not in a1_by_span:
            missing_a1.append({"v1_index": index, "start": span[0], "duration": span[1], "name": name})

    colors: dict[str, int] = {}
    for item in v1:
        color = item.GetClipColor() or ""
        if color:
            colors[color] = colors.get(color, 0) + 1

    present_cut_left_offsets = []
    for item in v1:
        left = int(item.GetLeftOffset())
        if left in cut_left_offsets:
            present_cut_left_offsets.append({"start": int(item.GetStart()), "left": left, "duration": int(item.GetDuration()), "name": item.GetName()})

    return {
        "timeline": timeline.GetName(),
        "start": int(timeline.GetStartFrame()),
        "end": int(timeline.GetEndFrame()),
        "expected_end": expected_end,
        "end_matches_expected": int(timeline.GetEndFrame()) == expected_end,
        "len_frames": int(timeline.GetEndFrame()) - int(timeline.GetStartFrame()),
        "v1_count": len(v1),
        "a1_count": len(a1),
        "marker_count": len(timeline.GetMarkers() or {}),
        "color_counts": colors,
        "missing_a1_count": len(missing_a1),
        "missing_a1_samples": missing_a1[:20],
        "present_cut_left_offsets": present_cut_left_offsets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--clips", type=Path, default=DEFAULT_CLIPS)
    parser.add_argument("--segmap", type=Path, default=DEFAULT_SEGMAP)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeline-name", default=DEFAULT_TIMELINE_NAME)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-extra-tracks", action="store_true")
    args = parser.parse_args()

    decisions = load_json(args.decisions)
    clips_data = load_json(args.clips)
    segmap = load_json(args.segmap)

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No Resolve project is open")
    source_timeline = project.GetCurrentTimeline()
    if not source_timeline:
        raise RuntimeError("No current Resolve timeline")

    timeline_fps = float(project.GetSetting("timelineFrameRate") or 60.0)
    timeline_start = int(source_timeline.GetStartFrame())
    source_end = int(source_timeline.GetEndFrame())
    expected_timeline = clips_data.get("timeline") if isinstance(clips_data, dict) else None
    if expected_timeline and source_timeline.GetName() != expected_timeline:
        raise RuntimeError(f"Current timeline {source_timeline.GetName()!r} does not match review timeline {expected_timeline!r}")

    extras = populated_extra_tracks(source_timeline)
    if extras and not args.allow_extra_tracks:
        raise RuntimeError(f"Refusing native V1/A1 rebuild because extra tracks are populated: {extras!r}")

    cuts, decision_metadata = compile_decision_cuts(decisions, clips_data, segmap, timeline_fps)
    reviewed_indices = {int(index) for index in (decisions.get("pink") or {}).keys()}
    reviewed_indices.update(int(record["clip_i"]) for record in decision_metadata["partial_records"])
    sample_indices = set(reviewed_indices)
    assert_review_matches_timeline(source_timeline, clips_data, sample_indices)

    expected_end = source_end - int(decision_metadata["total_cut_frames"])
    dry_report = {
        "project": project.GetName(),
        "source_timeline": source_timeline.GetName(),
        "dry_run": args.dry_run,
        "timeline_fps": timeline_fps,
        "timeline_start": timeline_start,
        "source_end": source_end,
        "expected_end_after_cuts": expected_end,
        "decisions": str(args.decisions),
        "clips": str(args.clips),
        "segmap": str(args.segmap),
        "decision_metadata": decision_metadata,
        "extra_tracks": extras,
    }
    if args.dry_run:
        print(json.dumps(dry_report, indent=2, ensure_ascii=False, default=str))
        return 0

    if args.in_place:
        target = source_timeline
        output_name = target.GetName()
    else:
        output_name = unique_timeline_name(project, args.timeline_name)
        target = source_timeline.DuplicateTimeline(output_name)
        if not target:
            raise RuntimeError(f"DuplicateTimeline failed for {output_name!r}")
        project.SetCurrentTimeline(target)

    review_by_timeline_index = {int(row["timeline_i"]): int(row["i"]) for row in clips_data["clips"]}
    video_payload, video_colors = collect_track_segments(target, "video", 1, 1, cuts, timeline_fps, reviewed_indices, review_by_timeline_index)
    audio_payload, audio_colors = collect_track_segments(target, "audio", 1, 2, cuts, timeline_fps, reviewed_indices, review_by_timeline_index)
    all_color_records = video_colors + audio_colors

    marker_report = clear_and_restore_markers(target, cuts, timeline_start)

    delete_items = []
    delete_items.extend(target.GetItemListInTrack("video", 1) or [])
    delete_items.extend(target.GetItemListInTrack("audio", 1) or [])
    print(f"Clearing {len(delete_items)} original V1/A1 item(s) without ripple...", flush=True)
    delete_ok = target.DeleteClips(delete_items, False)
    if not delete_ok:
        raise RuntimeError("DeleteClips returned false while clearing V1/A1")

    media_pool = project.GetMediaPool()
    placed_video_count = append_payload(media_pool, video_payload, "video")
    placed_audio_count = append_payload(media_pool, audio_payload, "audio")
    placed_count = placed_video_count + placed_audio_count
    payload_count = len(video_payload) + len(audio_payload)
    if placed_video_count != len(video_payload) or placed_audio_count != len(audio_payload):
        raise RuntimeError(
            "AppendToTimeline placed "
            f"video={placed_video_count}/{len(video_payload)} "
            f"audio={placed_audio_count}/{len(audio_payload)}"
        )
    color_report = restore_colors(target, all_color_records)

    cut_left_offsets = {int(item["clip"]["left"]) for item in decision_metadata["raw_ranges"] if item.get("source") == "pink_whole_cut"}
    validation = validate_timeline(target, expected_end, cut_left_offsets)
    save_ok = save_project(resolve, project)

    report = {
        **dry_report,
        "dry_run": False,
        "output_timeline": target.GetName(),
        "delete_original_clip_count": len(delete_items),
        "delete_ok": bool(delete_ok),
        "payload_count": payload_count,
        "video_payload_count": len(video_payload),
        "audio_payload_count": len(audio_payload),
        "placed_video_count": placed_video_count,
        "placed_audio_count": placed_audio_count,
        "placed_count": placed_count,
        "marker_report": marker_report,
        "color_report": color_report,
        "validation": validation,
        "project_save_ok": save_ok,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.out_dir / "review_decisions_applied_native_report.json"
    normalized_path = args.out_dir / "review_decisions_normalized_ranges.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    normalized_path.write_text(json.dumps(decision_metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(json.dumps({
        "output_timeline": target.GetName(),
        "total_cut_frames": decision_metadata["total_cut_frames"],
        "placed_count": placed_count,
        "validation": validation,
        "project_save_ok": save_ok,
        "report": str(report_path),
        "normalized_ranges": str(normalized_path),
    }, indent=2, ensure_ascii=False, default=str))
    if not validation["end_matches_expected"] or validation["missing_a1_count"]:
        return 2
    if marker_report["add_failures"] or color_report["failures"]:
        return 3
    if not save_ok:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
