from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


DEFAULT_TIMELINE = "Victreebel UMB corrected P1P2 full log-hold rebuild"
DEFAULT_REPORT = Path(
    r"E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx"
    r"\final_rebuild_validation_corrected_p1p2.json"
)
DEFAULT_DRT = Path(
    r"E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx"
    r"\drt-checkpoints\Victreebel_UMB_corrected_P1P2_full_final.drt"
)

VISUAL_ONLY_COLORS = {"Orange", "Purple", "Apricot", "Green"}
EXPECTED_DIALOGUE_WAVS = {
    "Victreebel Red and Blue Ultra Minimum Battles part 1_3.wav",
    "Victreebel Red and Blue Ultra Minimum Battles part 2_3.wav",
}


def clip_source_path(item) -> str:
    mpi = item.GetMediaPoolItem()
    if not mpi:
        return ""
    try:
        return mpi.GetClipProperty("File Path") or ""
    except Exception:
        return ""


def clip_row(item) -> dict[str, Any]:
    start = int(item.GetStart())
    duration = int(item.GetDuration())
    path = clip_source_path(item)
    return {
        "name": item.GetName() or Path(path).name,
        "source_path": path,
        "source_name": Path(path).name,
        "start_abs": start,
        "end_abs": start + duration,
        "duration": duration,
        "src_left": int(item.GetLeftOffset()),
        "clip_color": item.GetClipColor() or "",
    }


def timeline_by_name(project, name: str):
    for index in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline and timeline.GetName() == name:
            return timeline
    return None


def same_dialogue_family(video_clip: dict[str, Any], audio_clip: dict[str, Any]) -> bool:
    v_src = (video_clip.get("source_path") or "").lower()
    a_src = (audio_clip.get("source_path") or "").lower()
    if not a_src.endswith(".wav"):
        return False
    v_stem = Path(v_src).stem.lower()
    a_stem = Path(a_src).stem.lower()
    return bool(
        v_stem
        and a_stem.startswith(v_stem)
        and a_stem.endswith(("_1", "_2", "_3", "_4", "_5"))
    )


def has_aligned_a1(video_clip: dict[str, Any], a1_clips: list[dict[str, Any]]) -> bool:
    v_start = int(video_clip["start_abs"])
    v_end = int(video_clip["end_abs"])
    v_src_left = int(video_clip["src_left"])
    for audio_clip in a1_clips:
        if not same_dialogue_family(video_clip, audio_clip):
            continue
        a_start = int(audio_clip["start_abs"])
        a_end = int(audio_clip["end_abs"])
        ov_start = max(v_start, a_start)
        ov_end = min(v_end, a_end)
        if ov_start >= ov_end:
            continue
        a_src_at_overlap = int(audio_clip["src_left"]) + (ov_start - a_start)
        v_src_at_overlap = v_src_left + (ov_start - v_start)
        if a_src_at_overlap == v_src_at_overlap:
            return True
    return False


def is_structural_video(row: dict[str, Any]) -> bool:
    name = (row["name"] or "").lower()
    path = (row["source_path"] or "").replace("\\", "/").lower()
    return (
        "intro" in name
        or "outro" in name
        or "__2x_resolve" in name
        or "retimed-gen1-intros" in path
    )


def one_frame_gaps(rows: list[dict[str, Any]]) -> list[dict[str, int]]:
    out = []
    ordered = sorted(rows, key=lambda row: (row["start_abs"], row["end_abs"]))
    for prev, cur in zip(ordered, ordered[1:]):
        gap = int(cur["start_abs"]) - int(prev["end_abs"])
        if gap == 1:
            out.append({"after": int(prev["end_abs"]), "before": int(cur["start_abs"])})
    return out


def marker_rows(timeline) -> list[dict[str, Any]]:
    rows = []
    for rel, data in (timeline.GetMarkers() or {}).items():
        rows.append(
            {
                "rel": int(round(float(rel))),
                "name": data.get("name") or "",
                "color": data.get("color") or "",
                "note": data.get("note") or "",
            }
        )
    return sorted(rows, key=lambda row: (row["rel"], row["name"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", default=DEFAULT_TIMELINE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--drt", type=Path, default=DEFAULT_DRT)
    args = parser.parse_args()

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = timeline_by_name(project, args.timeline)
    if not timeline:
        raise RuntimeError(f"Timeline not found: {args.timeline}")
    project.SetCurrentTimeline(timeline)

    tracks: dict[str, dict[int, list[dict[str, Any]]]] = {"video": {}, "audio": {}}
    for track_type in ("video", "audio"):
        for index in range(1, timeline.GetTrackCount(track_type) + 1):
            rows = [clip_row(item) for item in (timeline.GetItemListInTrack(track_type, index) or [])]
            tracks[track_type][index] = sorted(rows, key=lambda row: (row["start_abs"], row["end_abs"]))

    v1 = tracks["video"].get(1, [])
    v2 = tracks["video"].get(2, [])
    a1 = tracks["audio"].get(1, [])
    a2_plus = [
        row
        for index, rows in tracks["audio"].items()
        if index >= 2
        for row in rows
    ]

    coverage_missing = []
    visual_only_exceptions = []
    for row in v1:
        if is_structural_video(row):
            continue
        if has_aligned_a1(row, a1):
            continue
        if row["clip_color"] in VISUAL_ONLY_COLORS:
            visual_only_exceptions.append(row)
        else:
            coverage_missing.append(row)

    bad_a1_sources = sorted(
        {
            row["source_name"]
            for row in a1
            if row["source_name"].endswith(".wav") and row["source_name"] not in EXPECTED_DIALOGUE_WAVS
        }
    )
    raw_gameplay_audio_a2_plus = [
        row
        for row in a2_plus
        if row["source_name"].endswith(".mp4")
        and "victreebel red and blue ultra minimum battles part" in row["source_name"].lower()
    ]
    v2_crop_failures = []
    for item in timeline.GetItemListInTrack("video", 2) or []:
        try:
            crop = float(item.GetProperty("CropBottom") or 0)
        except Exception:
            crop = 0.0
        if abs(crop - 530.0) > 0.01:
            row = clip_row(item)
            row["crop_bottom"] = crop
            v2_crop_failures.append(row)

    markers = marker_rows(timeline)
    marker_names = Counter(row["name"] for row in markers)
    v1_color_counts = Counter(row["clip_color"] or "-" for row in v1)
    leader_video_count = sum(1 for row in v1 if "__2x_resolve2" in (row["source_name"] or ""))
    leader_audio_count = sum(
        1
        for row in a2_plus
        if "__2x_resolve2" in (row["source_name"] or "")
        or "leader" in (row["source_path"] or "").lower()
    )

    args.drt.parent.mkdir(parents=True, exist_ok=True)
    drt_exported = bool(timeline.Export(str(args.drt), resolve.EXPORT_DRT, resolve.EXPORT_NONE))

    report = {
        "project": project.GetName(),
        "timeline": timeline.GetName(),
        "timeline_start": int(timeline.GetStartFrame()),
        "timeline_end": int(timeline.GetEndFrame()),
        "track_counts": {
            "video": {str(i): len(rows) for i, rows in tracks["video"].items()},
            "audio": {str(i): len(rows) for i, rows in tracks["audio"].items()},
        },
        "v1_color_counts": dict(sorted(v1_color_counts.items())),
        "a1_wav_sources": sorted({row["source_name"] for row in a1 if row["source_name"].endswith(".wav")}),
        "bad_a1_sources": bad_a1_sources,
        "coverage_missing_count": len(coverage_missing),
        "coverage_missing": coverage_missing,
        "visual_only_exceptions_count": len(visual_only_exceptions),
        "visual_only_exceptions": visual_only_exceptions,
        "raw_gameplay_audio_a2_plus_count": len(raw_gameplay_audio_a2_plus),
        "raw_gameplay_audio_a2_plus": raw_gameplay_audio_a2_plus,
        "v2_crop_failures": v2_crop_failures,
        "one_frame_gaps": {
            "v1": one_frame_gaps(v1),
            "v2": one_frame_gaps(v2),
            "a1": one_frame_gaps(a1),
            "a2": one_frame_gaps(tracks["audio"].get(2, [])),
            "a3": one_frame_gaps(tracks["audio"].get(3, [])),
        },
        "leader_video_count": leader_video_count,
        "leader_audio_count": leader_audio_count,
        "marker_count": len(markers),
        "member_carousel_start_markers": marker_names.get("Member Carousel Start", 0),
        "final_tierlist_markers": sum(1 for row in markers if row["name"].startswith("Final Tierlist")),
        "drt_path": str(args.drt),
        "drt_exported": drt_exported,
    }
    report["ok"] = (
        not bad_a1_sources
        and not coverage_missing
        and not raw_gameplay_audio_a2_plus
        and not v2_crop_failures
        and all(not gaps for gaps in report["one_frame_gaps"].values())
        and leader_video_count == 13
        and leader_audio_count >= 13
        and marker_names.get("Member Carousel Start", 0) == 1
        and drt_exported
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
