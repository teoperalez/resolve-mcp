from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr
import build_victreebel_rby_fcpxml as builder


LOCKED_DIR = builder.CODEX_DIR / "locked_editorial"
PART1_LOCKED = LOCKED_DIR / "part1_LOCKED_ALTERED.fcpxml"
PART2_LOCKED = LOCKED_DIR / "part2_LOCKED_ALTERED.fcpxml"
APPROVED_CUTS = builder.CODEX_DIR / "approved_cuts_victreebel.json"
CUT_REPLAY = LOCKED_DIR / "cut_replay.json"
TIMELINE_BASE = "Victreebel RBY UMB locked editorial base markers"
EXPECTED_CLIP_COUNTS = {
    "v1_total": 1453,
    "a1_total": 1453,
    "part1_gameplay": 63,
    "part2_gameplay": 1388,
}


def slugify(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "timeline"


def timeline_by_name(project, name: str):
    for index in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline and timeline.GetName() == name:
            return timeline
    return None


def unique_timeline_name(project, base_name: str) -> str:
    existing = {
        (project.GetTimelineByIndex(index).GetName() or "")
        for index in range(1, project.GetTimelineCount() + 1)
        if project.GetTimelineByIndex(index)
    }
    if base_name not in existing:
        return base_name
    for suffix in range(2, 100):
        candidate = f"{base_name} {suffix}"
        if candidate not in existing:
            return candidate
    raise RuntimeError(f"Could not find a unique timeline name for {base_name!r}")


def connect():
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No current Resolve project")
    return resolve, project, project.GetMediaPool()


def load_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_locked_fcpxml(timeline_name: str) -> tuple[Path, Path, dict[str, Any]]:
    for required in (PART1_LOCKED, PART2_LOCKED, APPROVED_CUTS):
        if not required.exists():
            raise FileNotFoundError(required)

    LOCKED_DIR.mkdir(parents=True, exist_ok=True)
    builder.INTRO_PATH = builder.copy_asset(builder.INTRO_SOURCE, "global")
    builder.BGM_PATH = builder.copy_asset(builder.BGM_SOURCE, "global")
    builder.OUTRO_PATH = builder.copy_asset(builder.OUTRO_SOURCE, "global")
    builder.FINAL_NAME = timeline_name

    part1_clips = builder.load_video_clips(PART1_LOCKED, 1, builder.PART1_DIALOGUE)
    part2_clips = builder.load_video_clips(PART2_LOCKED, 2, builder.PART2_DIALOGUE)
    intro_frames = builder.media_duration_frames(builder.INTRO_PATH)
    part1_frames = max(clip.offset + clip.duration for clip in part1_clips)
    markers, timing = builder.build_markers(part2_clips, intro_frames + part1_frames)

    output_stem = slugify(timeline_name)
    fcpxml_path = LOCKED_DIR / f"{output_stem}.fcpxml"
    final_info = builder.build_final_fcpxml(part1_clips, part2_clips, markers, fcpxml_path)

    manifest = {
        "project_dir": str(builder.PROJECT_DIR),
        "timeline_name": timeline_name,
        "source_fcpxmls": {
            "part1_locked": str(PART1_LOCKED),
            "part2_locked": str(PART2_LOCKED),
        },
        "approved_cuts": load_json_if_exists(APPROVED_CUTS),
        "cut_replay": str(CUT_REPLAY) if CUT_REPLAY.exists() else None,
        "dialogue_audio": {
            "part1": str(builder.PART1_DIALOGUE),
            "part2": str(builder.PART2_DIALOGUE),
        },
        "timing": timing,
        "markers": [asdict(marker) for marker in markers],
        "final": final_info,
        "expected_clip_counts": EXPECTED_CLIP_COUNTS,
    }
    manifest_path = LOCKED_DIR / f"{output_stem}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return fcpxml_path, manifest_path, manifest


def marker_groups(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for marker in manifest.get("markers", []):
        grouped.setdefault(int(marker["combined_frame"]), []).append(marker)

    rows = []
    for frame, group in sorted(grouped.items()):
        labels = []
        notes = []
        for marker in group:
            label = marker.get("label") or ""
            note = marker.get("note") or marker.get("category") or ""
            if label and label not in labels:
                labels.append(label)
            if note and note not in notes:
                notes.append(note)
        rows.append({
            "frame": frame,
            "name": " / ".join(labels),
            "note": "\n".join(notes),
            "color": group[0].get("color") or "Blue",
            "events": len(group),
        })
    return rows


def import_timeline(project, media_pool, fcpxml_path: Path, timeline_name: str):
    result = media_pool.ImportTimelineFromFile(str(fcpxml_path), {"timelineName": timeline_name})
    if not result:
        raise RuntimeError(f"ImportTimelineFromFile returned {result!r}")
    timeline = timeline_by_name(project, timeline_name)
    if not timeline:
        count = project.GetTimelineCount()
        timeline = project.GetTimelineByIndex(count) if count else None
        if not timeline:
            raise RuntimeError("Imported timeline was not found")
    project.SetCurrentTimeline(timeline)
    return timeline


def restore_markers(timeline, manifest: dict[str, Any]) -> dict[str, Any]:
    timeline.DeleteMarkersByColor("All")
    grouped_markers = marker_groups(manifest)
    added = 0
    failed = []
    for marker in grouped_markers:
        ok = timeline.AddMarker(
            int(marker["frame"]),
            marker["color"],
            marker["name"],
            marker["note"],
            1,
            "victreebel_locked_editorial",
        )
        if ok:
            added += 1
        else:
            failed.append(marker)
    return {
        "expected_unique_markers": len(grouped_markers),
        "added": added,
        "failed": failed,
        "final_marker_count": len(timeline.GetMarkers() or {}),
    }


def clip_source_path(item) -> str:
    media_pool_item = item.GetMediaPoolItem()
    if not media_pool_item:
        return ""
    try:
        return media_pool_item.GetClipProperty("File Path") or ""
    except Exception:
        return ""


def clip_row(item) -> dict[str, Any]:
    start_abs = int(item.GetStart())
    duration = int(item.GetDuration())
    source_path = clip_source_path(item)
    return {
        "name": item.GetName() or Path(source_path).name,
        "source_path": source_path,
        "source_name": Path(source_path).name,
        "start_abs": start_abs,
        "end_abs": start_abs + duration,
        "duration": duration,
        "src_left": int(item.GetLeftOffset()),
        "clip_color": item.GetClipColor() or "",
    }


def part_for_video(row: dict[str, Any]) -> str | None:
    source_name = (row.get("source_name") or "").lower()
    if source_name == "victreebel red and blue ultra minimum battles part 1.mp4":
        return "part1"
    if source_name == "victreebel red and blue ultra minimum battles part 2.mp4":
        return "part2"
    return None


def expected_dialogue_name(part: str) -> str:
    return {
        "part1": "Victreebel Red and Blue Ultra Minimum Battles part 1_3.wav",
        "part2": "Victreebel Red and Blue Ultra Minimum Battles part 2_3.wav",
    }[part]


def has_exact_dialogue(video_row: dict[str, Any], audio_rows: list[dict[str, Any]]) -> bool:
    part = part_for_video(video_row)
    if not part:
        return True
    expected_name = expected_dialogue_name(part)
    for audio_row in audio_rows:
        if audio_row["source_name"] != expected_name:
            continue
        if audio_row["start_abs"] != video_row["start_abs"]:
            continue
        if audio_row["end_abs"] != video_row["end_abs"]:
            continue
        if audio_row["src_left"] != video_row["src_left"]:
            continue
        return True
    return False


def cut_ranges_frames() -> dict[str, list[tuple[int, int]]]:
    data = load_json_if_exists(APPROVED_CUTS) or {}
    ranges: dict[str, list[tuple[int, int]]] = {}
    for cut in data.get("cuts", []):
        part = str(cut["part"])
        start_frame = int(round(float(cut["start_sec"]) * builder.FPS))
        end_frame = int(round(float(cut["end_sec"]) * builder.FPS))
        ranges.setdefault(part, []).append((start_frame, end_frame))
    return ranges


def overlapping_cut(row: dict[str, Any], ranges: dict[str, list[tuple[int, int]]]) -> dict[str, Any] | None:
    part = part_for_video(row)
    if not part:
        return None
    source_start = int(row["src_left"])
    source_end = source_start + int(row["duration"])
    for cut_start, cut_end in ranges.get(part, []):
        if source_start < cut_end and source_end > cut_start:
            return {
                "part": part,
                "source_start": source_start,
                "source_end": source_end,
                "cut_start": cut_start,
                "cut_end": cut_end,
                "row": row,
            }
    return None


def validate_timeline(resolve, project, timeline, marker_report: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    tracks: dict[str, dict[int, list[dict[str, Any]]]] = {"video": {}, "audio": {}}
    for track_type in ("video", "audio"):
        for track_index in range(1, timeline.GetTrackCount(track_type) + 1):
            rows = [clip_row(item) for item in (timeline.GetItemListInTrack(track_type, track_index) or [])]
            tracks[track_type][track_index] = sorted(rows, key=lambda row: (row["start_abs"], row["end_abs"]))

    video_rows = tracks["video"].get(1, [])
    audio_rows = tracks["audio"].get(1, [])
    source_counts = {
        "v1": dict(sorted(Counter(row["source_name"] for row in video_rows).items())),
        "a1": dict(sorted(Counter(row["source_name"] for row in audio_rows).items())),
    }
    gameplay_video_rows = [row for row in video_rows if part_for_video(row)]
    missing_dialogue = [row for row in gameplay_video_rows if not has_exact_dialogue(row, audio_rows)]
    cut_overlaps = [overlap for row in gameplay_video_rows if (overlap := overlapping_cut(row, cut_ranges_frames()))]

    expected_markers = int(marker_report["expected_unique_markers"])
    part1_count = source_counts["v1"].get("Victreebel Red and Blue Ultra Minimum Battles part 1.mp4", 0)
    part2_count = source_counts["v1"].get("Victreebel Red and Blue Ultra Minimum Battles part 2.mp4", 0)
    drt_path = LOCKED_DIR / f"{slugify(timeline.GetName())}.drt"
    drt_exported = bool(timeline.Export(str(drt_path), resolve.EXPORT_DRT, resolve.EXPORT_NONE))

    checks = {
        "v1_total_matches": len(video_rows) == EXPECTED_CLIP_COUNTS["v1_total"],
        "a1_total_matches": len(audio_rows) == EXPECTED_CLIP_COUNTS["a1_total"],
        "part1_gameplay_matches": part1_count == EXPECTED_CLIP_COUNTS["part1_gameplay"],
        "part2_gameplay_matches": part2_count == EXPECTED_CLIP_COUNTS["part2_gameplay"],
        "a1_dialogue_coverage": not missing_dialogue,
        "approved_cut_ranges_absent": not cut_overlaps,
        "marker_restore_complete": marker_report["added"] == expected_markers and marker_report["final_marker_count"] == expected_markers,
        "drt_exported": drt_exported,
    }

    report = {
        "project": project.GetName(),
        "timeline": timeline.GetName(),
        "start_frame": int(timeline.GetStartFrame()),
        "end_frame": int(timeline.GetEndFrame()),
        "duration_frames": int(timeline.GetEndFrame()) - int(timeline.GetStartFrame()),
        "track_counts": {
            "video_tracks": timeline.GetTrackCount("video"),
            "audio_tracks": timeline.GetTrackCount("audio"),
            "v1": len(video_rows),
            "a1": len(audio_rows),
        },
        "source_counts": source_counts,
        "expected_clip_counts": EXPECTED_CLIP_COUNTS,
        "marker_report": marker_report,
        "manifest_marker_events": len(manifest.get("markers", [])),
        "gameplay_v1_missing_exact_a1_dialogue": missing_dialogue,
        "approved_cut_range_overlaps": cut_overlaps,
        "drt": str(drt_path),
        "checks": checks,
        "ok": all(checks.values()),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline-base", default=TIMELINE_BASE)
    parser.add_argument("--report", type=Path, default=LOCKED_DIR / "locked_editorial_timeline_import_report.json")
    args = parser.parse_args()

    resolve, project, media_pool = connect()
    timeline_name = unique_timeline_name(project, args.timeline_base)
    fcpxml_path, manifest_path, manifest = build_locked_fcpxml(timeline_name)
    timeline = import_timeline(project, media_pool, fcpxml_path, timeline_name)
    marker_report = restore_markers(timeline, manifest)
    report = validate_timeline(resolve, project, timeline, marker_report, manifest)
    report.update({
        "fcpxml": str(fcpxml_path),
        "manifest": str(manifest_path),
        "approved_cuts": str(APPROVED_CUTS),
        "cut_replay": str(CUT_REPLAY),
    })
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())