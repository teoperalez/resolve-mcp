"""Apply timeline-record cut ranges to a Resolve timeline.

Use this for recovery from an existing editor-ready timeline when the cut
decisions are already normalized into that timeline's record-frame coordinate
space. The script creates a new timeline, splits/removes each record range
across all populated video/audio tracks, shifts later clips and markers left,
and leaves the source timeline untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


MEDIA_TYPE_BY_TRACK = {"video": 1, "audio": 2}


@dataclass
class ClipSpec:
    media_pool_item: Any
    media_type: int
    track_type: str
    track_index: int
    name: str
    start: int
    duration: int
    left: int
    color: str

    @property
    def end(self) -> int:
        return self.start + self.duration


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def unique_timeline_name(project, base: str) -> str:
    existing = set()
    for index in range(1, int(project.GetTimelineCount()) + 1):
        tl = project.GetTimelineByIndex(index)
        if tl:
            existing.add(tl.GetName())
    if base not in existing:
        return base
    suffix = 2
    while f"{base} {suffix}" in existing:
        suffix += 1
    return f"{base} {suffix}"


def timeline_by_name(project, name: str):
    for index in range(1, int(project.GetTimelineCount()) + 1):
        tl = project.GetTimelineByIndex(index)
        if tl and tl.GetName() == name:
            return tl
    return None


def parse_extra_cut(text: str) -> dict:
    parts = text.split(":", 2)
    if len(parts) < 2:
        raise SystemExit(f"Invalid --extra-cut {text!r}; expected START:END[:LABEL]")
    start = int(parts[0])
    end = int(parts[1])
    if end <= start:
        raise SystemExit(f"Invalid --extra-cut {text!r}; end must be > start")
    return {"start": start, "end": end, "label": parts[2] if len(parts) > 2 else "extra_cut"}


def load_record_cuts(path: Path, extras: list[str], timeline_start: int) -> tuple[list[tuple[int, int]], list[dict]]:
    payload = load_json(path)
    rows = payload.get("merged_ranges") or payload.get("record_cuts") or payload.get("cuts") or payload
    if not isinstance(rows, list):
        raise RuntimeError(f"Unsupported record cut payload in {path}")
    records = []
    for row in rows:
        start = int(row.get("start", row.get("start_frame")))
        end = int(row.get("end", row.get("end_frame")))
        if end > start:
            records.append({**row, "start": start, "end": end, "source": row.get("source") or row.get("label")})
    records.extend(parse_extra_cut(row) for row in extras)
    merged = merge_ranges([(timeline_start + r["start"], timeline_start + r["end"]) for r in records])
    return merged, records


def merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def cut_shift_before(frame: int, cuts: list[tuple[int, int]]) -> int:
    shift = 0
    for start, end in cuts:
        if frame >= end:
            shift += end - start
        elif frame > start:
            shift += frame - start
            break
        else:
            break
    return shift


def marker_inside_cut(frame: int, cuts: list[tuple[int, int]]) -> bool:
    return any(start < frame < end for start, end in cuts)


def subtract_cuts(start: int, end: int, cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    kept = [(start, end)]
    for cut_start, cut_end in cuts:
        if cut_end <= start or cut_start >= end:
            continue
        next_kept: list[tuple[int, int]] = []
        for seg_start, seg_end in kept:
            if cut_end <= seg_start or cut_start >= seg_end:
                next_kept.append((seg_start, seg_end))
                continue
            if cut_start > seg_start:
                next_kept.append((seg_start, cut_start))
            if cut_end < seg_end:
                next_kept.append((cut_end, seg_end))
        kept = [(seg_start, seg_end) for seg_start, seg_end in next_kept if seg_end > seg_start]
    return kept


def collect_specs(timeline) -> list[ClipSpec]:
    specs: list[ClipSpec] = []
    for track_type, media_type in MEDIA_TYPE_BY_TRACK.items():
        for track_index in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            for item in timeline.GetItemListInTrack(track_type, track_index) or []:
                mpi = item.GetMediaPoolItem()
                if not mpi:
                    raise RuntimeError(f"{track_type}{track_index} item {item.GetName()!r} has no MediaPoolItem")
                specs.append(
                    ClipSpec(
                        media_pool_item=mpi,
                        media_type=media_type,
                        track_type=track_type,
                        track_index=track_index,
                        name=item.GetName() or "",
                        start=int(item.GetStart()),
                        duration=int(item.GetDuration()),
                        left=int(item.GetLeftOffset()),
                        color=item.GetClipColor() or "",
                    )
                )
    return sorted(specs, key=lambda s: (s.media_type, s.track_index, s.start, s.left))


def ensure_tracks(timeline, source_timeline) -> None:
    for track_type in ("video", "audio"):
        want = int(source_timeline.GetTrackCount(track_type) or 0)
        while int(timeline.GetTrackCount(track_type) or 0) < want:
            if track_type == "audio":
                timeline.AddTrack(track_type, "stereo")
            else:
                timeline.AddTrack(track_type)


def build_payload(specs: list[ClipSpec], cuts: list[tuple[int, int]], new_start: int, old_start: int) -> tuple[list[dict], list[dict]]:
    payload = []
    colors = []
    for spec in specs:
        for keep_start, keep_end in subtract_cuts(spec.start, spec.end, cuts):
            duration = keep_end - keep_start
            if duration <= 0:
                continue
            local = keep_start - spec.start
            source_start = spec.left + local
            source_end = source_start + duration
            new_record = new_start + (keep_start - old_start) - cut_shift_before(keep_start, cuts)
            payload.append(
                {
                    "mediaPoolItem": spec.media_pool_item,
                    "startFrame": source_start,
                    "endFrame": source_end,
                    "recordFrame": new_record,
                    "trackIndex": spec.track_index,
                    "mediaType": spec.media_type,
                }
            )
            colors.append(
                {
                    "media_type": spec.media_type,
                    "track_type": spec.track_type,
                    "track_index": spec.track_index,
                    "recordFrame": new_record,
                    "startFrame": source_start,
                    "name": spec.name,
                    "color": spec.color,
                }
            )
    payload.sort(key=lambda row: (row["mediaType"], row["trackIndex"], row["recordFrame"], row["startFrame"]))
    return payload, colors


def append_payload(pool, payload: list[dict]) -> int:
    placed = []
    for index in range(0, len(payload), 100):
        placed.extend(pool.AppendToTimeline(payload[index:index + 100]) or [])
    return len(placed)


def add_shifted_markers(source_timeline, target_timeline, cuts: list[tuple[int, int]], old_start: int) -> dict:
    added = 0
    dropped = []
    failures = []
    for rel_raw, marker in sorted((source_timeline.GetMarkers() or {}).items(), key=lambda item: int(round(float(item[0])))):
        old_rel = int(round(float(rel_raw)))
        old_abs = old_start + old_rel
        if marker_inside_cut(old_abs, cuts):
            dropped.append({"old_frame": old_rel, "old_abs": old_abs, "marker": marker})
            continue
        new_rel = old_rel - cut_shift_before(old_abs, cuts)
        ok = target_timeline.AddMarker(
            int(new_rel),
            marker.get("color") or "Blue",
            marker.get("name") or "",
            marker.get("note") or "",
            int(marker.get("duration") or 1),
            marker.get("customData") or "",
        )
        if ok:
            added += 1
        else:
            failures.append({"old_frame": old_rel, "new_frame": new_rel, "marker": marker})
    return {
        "source_count": len(source_timeline.GetMarkers() or {}),
        "added": added,
        "dropped": dropped,
        "failures": failures,
    }


def restore_colors(timeline, colors: list[dict]) -> dict:
    color_map = {
        (row["media_type"], row["track_index"], row["recordFrame"], row["startFrame"], row["name"]): row["color"]
        for row in colors
        if row.get("color")
    }
    restored = 0
    failures = []
    for track_type, media_type in MEDIA_TYPE_BY_TRACK.items():
        for track_index in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            for item in timeline.GetItemListInTrack(track_type, track_index) or []:
                key = (media_type, track_index, int(item.GetStart()), int(item.GetLeftOffset()), item.GetName() or "")
                color = color_map.get(key)
                if not color:
                    continue
                if item.SetClipColor(color):
                    restored += 1
                else:
                    failures.append({"key": key, "color": color})
    return {"restored": restored, "failures": failures}


def track_counts(timeline) -> dict:
    out = {}
    for track_type in ("video", "audio"):
        out[track_type] = {}
        for track_index in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            out[track_type][str(track_index)] = len(timeline.GetItemListInTrack(track_type, track_index) or [])
    return out


def save_project(resolve, project) -> bool:
    save = getattr(project, "Save", None)
    if callable(save):
        return bool(save())
    manager = resolve.GetProjectManager() if resolve else None
    save_project = getattr(manager, "SaveProject", None) if manager else None
    return bool(save_project(project.GetName()) if callable(save_project) else False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cut-ranges", type=Path, required=True)
    parser.add_argument("--extra-cut", action="append", default=[])
    parser.add_argument("--source-timeline", required=True)
    parser.add_argument("--timeline-name", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No Resolve project is open")
    pool = project.GetMediaPool()
    source_timeline = timeline_by_name(project, args.source_timeline)
    if source_timeline is None:
        raise RuntimeError(f"Timeline not found: {args.source_timeline!r}")
    project.SetCurrentTimeline(source_timeline)

    old_start = int(source_timeline.GetStartFrame())
    old_end = int(source_timeline.GetEndFrame())
    cuts, source_records = load_record_cuts(args.cut_ranges, args.extra_cut, old_start)
    removed_frames = sum(end - start for start, end in cuts)
    output_name = unique_timeline_name(project, args.timeline_name)
    specs = collect_specs(source_timeline)
    payload, colors = build_payload(specs, cuts, old_start, old_start)
    base_report = {
        "schema": "rby_umb_apply_record_cuts_to_timeline_v1",
        "dry_run": bool(args.dry_run),
        "project": project.GetName(),
        "source_timeline": source_timeline.GetName(),
        "output_timeline": output_name,
        "cut_ranges": str(args.cut_ranges),
        "source_records": source_records,
        "record_cuts": [{"start": s - old_start, "end": e - old_start, "duration": e - s} for s, e in cuts],
        "record_cut_count": len(cuts),
        "removed_frames": removed_frames,
        "source_start": old_start,
        "source_end": old_end,
        "expected_end": old_end - removed_frames,
        "source_track_counts": track_counts(source_timeline),
        "payload_count": len(payload),
    }
    if args.dry_run:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(base_report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps(base_report, indent=2, ensure_ascii=False, default=str))
        return 0

    target = pool.CreateEmptyTimeline(output_name)
    if target is None:
        raise RuntimeError(f"CreateEmptyTimeline failed for {output_name!r}")
    project.SetCurrentTimeline(target)
    ensure_tracks(target, source_timeline)
    new_start = int(target.GetStartFrame())
    if new_start != old_start:
        payload, colors = build_payload(specs, cuts, new_start, old_start)
    placed = append_payload(pool, payload)
    marker_report = add_shifted_markers(source_timeline, target, cuts, old_start)
    color_report = restore_colors(target, colors)
    save_ok = save_project(resolve, project)

    report = {
        **base_report,
        "dry_run": False,
        "output_timeline": target.GetName(),
        "new_start": new_start,
        "new_end": int(target.GetEndFrame()),
        "placed": placed,
        "expected_placed": len(payload),
        "track_counts": track_counts(target),
        "marker_report": marker_report,
        "color_report": color_report,
        "project_save_ok": save_ok,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({
        "output_timeline": target.GetName(),
        "removed_frames": removed_frames,
        "placed": placed,
        "expected_placed": len(payload),
        "new_end": int(target.GetEndFrame()),
        "expected_end": old_end - removed_frames,
        "markers": marker_report,
        "report": str(args.report),
        "project_save_ok": save_ok,
    }, indent=2, ensure_ascii=False, default=str))

    if placed != len(payload):
        return 2
    if marker_report["failures"] or color_report["failures"]:
        return 3
    if not save_ok:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
