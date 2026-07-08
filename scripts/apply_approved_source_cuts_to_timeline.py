"""Apply approved combined-source cuts to an existing Resolve timeline.

This is for late-stage RBY UMB recovery when the canonical FCPXML rebuild is
blocked by missing hold-region data, but a Codex structural Resolve timeline is
available. The script maps ``approved_source_cuts.json`` onto source-backed
V1/A1 clips, creates a fresh timeline, shifts every later clip/marker left by
the actual removed record ranges, and writes a validation report.
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
    item: Any
    media_pool_item: Any
    track_type: str
    track_index: int
    media_type: int
    name: str
    source_path: str
    start: int
    duration: int
    left: int
    color: str
    source_offset: int | None

    @property
    def end(self) -> int:
        return self.start + self.duration

    @property
    def source_start(self) -> int | None:
        if self.source_offset is None:
            return None
        return self.left + self.source_offset

    @property
    def source_end(self) -> int | None:
        if self.source_offset is None:
            return None
        return self.left + self.duration + self.source_offset


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def norm_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").lower()


def parse_source_offsets(rows: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        if "=" not in row:
            raise SystemExit(f"Invalid --source-offset {row!r}; expected SOURCE=FRAMES")
        key, value = row.split("=", 1)
        key = norm_path(key.strip())
        if not key:
            raise SystemExit(f"Invalid empty source key in --source-offset {row!r}")
        try:
            out[key] = int(value.strip())
        except ValueError as exc:
            raise SystemExit(f"Invalid frame offset in --source-offset {row!r}") from exc
    return out


def source_offset_for_path(path: str, offsets: dict[str, int]) -> int | None:
    full = norm_path(path)
    name = Path(path).name.lower()
    stem = Path(path).stem.lower()
    for key, frames in offsets.items():
        if key in {full, name, stem} or key in full:
            return frames
    return None


def media_path(item) -> str:
    try:
        mpi = item.GetMediaPoolItem()
    except Exception:
        mpi = None
    if not mpi:
        return ""
    try:
        return mpi.GetClipProperty("File Path") or ""
    except Exception:
        return ""


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


def frame_inside_cut(frame: int, cuts: list[tuple[int, int]]) -> bool:
    return any(start <= frame < end for start, end in cuts)


def subtract_record_cuts(start: int, end: int, cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
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


def collect_specs(timeline, offsets: dict[str, int]) -> list[ClipSpec]:
    specs: list[ClipSpec] = []
    for track_type, media_type in MEDIA_TYPE_BY_TRACK.items():
        for track_index in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            for item in timeline.GetItemListInTrack(track_type, track_index) or []:
                mpi = item.GetMediaPoolItem()
                if not mpi:
                    raise RuntimeError(f"{track_type}{track_index} item {item.GetName()!r} has no MediaPoolItem")
                path = media_path(item)
                specs.append(
                    ClipSpec(
                        item=item,
                        media_pool_item=mpi,
                        track_type=track_type,
                        track_index=track_index,
                        media_type=media_type,
                        name=item.GetName() or "",
                        source_path=path,
                        start=int(item.GetStart()),
                        duration=int(item.GetDuration()),
                        left=int(item.GetLeftOffset()),
                        color=item.GetClipColor() or "",
                        source_offset=source_offset_for_path(path, offsets),
                    )
                )
    return sorted(specs, key=lambda s: (s.media_type, s.track_index, s.start, s.left))


def load_source_cuts(path: Path) -> list[dict]:
    payload = load_json(path)
    rows = payload.get("source_cuts", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise RuntimeError(f"Could not read source cuts from {path}")
    out = []
    for row in rows:
        start = int(row.get("start_frame"))
        end = int(row.get("end_frame"))
        if end > start:
            out.append({**row, "start_frame": start, "end_frame": end})
    return sorted(out, key=lambda r: (r["start_frame"], r["end_frame"]))


def derive_record_cuts(specs: list[ClipSpec], source_cuts: list[dict]) -> tuple[list[tuple[int, int]], list[dict]]:
    record_ranges: list[tuple[int, int]] = []
    mappings: list[dict] = []
    for spec in specs:
        src_start = spec.source_start
        src_end = spec.source_end
        if src_start is None or src_end is None:
            continue
        for cut in source_cuts:
            overlap_start = max(src_start, int(cut["start_frame"]))
            overlap_end = min(src_end, int(cut["end_frame"]))
            if overlap_end <= overlap_start:
                continue
            record_start = spec.start + (overlap_start - src_start)
            record_end = spec.start + (overlap_end - src_start)
            if record_end <= record_start:
                continue
            record_ranges.append((record_start, record_end))
            mappings.append(
                {
                    "track_type": spec.track_type,
                    "track_index": spec.track_index,
                    "clip_name": spec.name,
                    "clip_start": spec.start,
                    "source_path": spec.source_path,
                    "source_offset": spec.source_offset,
                    "source_cut_start": cut["start_frame"],
                    "source_cut_end": cut["end_frame"],
                    "overlap_source_start": overlap_start,
                    "overlap_source_end": overlap_end,
                    "record_start": record_start,
                    "record_end": record_end,
                    "label": cut.get("label"),
                    "reason": cut.get("reason"),
                }
            )
    return merge_ranges(record_ranges), mappings


def build_payload(specs: list[ClipSpec], record_cuts: list[tuple[int, int]], new_start: int, old_start: int) -> tuple[list[dict], list[dict]]:
    payload: list[dict] = []
    colors: list[dict] = []
    for spec in specs:
        split_for_cuts = spec.source_offset is not None
        pieces = subtract_record_cuts(spec.start, spec.end, record_cuts) if split_for_cuts else [(spec.start, spec.end)]
        for keep_start, keep_end in pieces:
            duration = keep_end - keep_start
            if duration <= 0:
                continue
            local = keep_start - spec.start
            source_start = spec.left + local
            source_end = source_start + duration
            new_record = new_start + (keep_start - old_start) - cut_shift_before(keep_start, record_cuts)
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
                    "duration": duration,
                    "name": spec.name,
                    "color": spec.color,
                }
            )
    payload.sort(key=lambda s: (s["mediaType"], s["trackIndex"], s["recordFrame"], s["startFrame"]))
    return payload, colors


def ensure_tracks(timeline, source_timeline) -> None:
    for track_type in ("video", "audio"):
        want = int(source_timeline.GetTrackCount(track_type) or 0)
        while int(timeline.GetTrackCount(track_type) or 0) < want:
            if track_type == "audio":
                timeline.AddTrack(track_type, "stereo")
            else:
                timeline.AddTrack(track_type)


def add_shifted_markers(source_timeline, target_timeline, record_cuts: list[tuple[int, int]], new_start: int, old_start: int) -> dict:
    added = 0
    dropped = []
    failures = []
    for rel_raw, data in sorted((source_timeline.GetMarkers() or {}).items(), key=lambda kv: int(round(float(kv[0])))):
        old_rel = int(round(float(rel_raw)))
        old_abs = old_start + old_rel
        if frame_inside_cut(old_abs, record_cuts):
            dropped.append({"old_frame": old_rel, "old_abs": old_abs, "marker": data})
            continue
        new_rel = old_rel - cut_shift_before(old_abs, record_cuts)
        ok = target_timeline.AddMarker(
            int(new_rel),
            data.get("color") or "Blue",
            data.get("name") or "",
            data.get("note") or "",
            int(data.get("duration") or 1),
            data.get("customData") or "",
        )
        if ok:
            added += 1
        else:
            failures.append({"old_frame": old_rel, "new_frame": new_rel, "marker": data})
    return {
        "source_count": len(source_timeline.GetMarkers() or {}),
        "added": added,
        "dropped": dropped,
        "failures": failures,
    }


def restore_colors(timeline, colors: list[dict]) -> dict:
    by_key = {
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
                color = by_key.get(key)
                if not color:
                    continue
                if item.SetClipColor(color):
                    restored += 1
                else:
                    failures.append({"key": key, "color": color})
    return {"restored": restored, "failures": failures}


def append_payload(pool, payload: list[dict]) -> int:
    placed = []
    for i in range(0, len(payload), 100):
        placed.extend(pool.AppendToTimeline(payload[i:i + 100]) or [])
    return len(placed)


def track_counts(timeline) -> dict:
    out = {}
    for track_type in ("video", "audio"):
        out[track_type] = {}
        for track_index in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            out[track_type][str(track_index)] = len(timeline.GetItemListInTrack(track_type, track_index) or [])
    return out


def validate_cut_absence(timeline, offsets: dict[str, int], source_cuts: list[dict]) -> list[dict]:
    findings = []
    specs = collect_specs(timeline, offsets)
    for spec in specs:
        src_start = spec.source_start
        src_end = spec.source_end
        if src_start is None or src_end is None:
            continue
        for cut in source_cuts:
            overlap_start = max(src_start, int(cut["start_frame"]))
            overlap_end = min(src_end, int(cut["end_frame"]))
            if overlap_end > overlap_start:
                findings.append(
                    {
                        "track_type": spec.track_type,
                        "track_index": spec.track_index,
                        "clip_name": spec.name,
                        "clip_start": spec.start,
                        "source_path": spec.source_path,
                        "overlap_source_start": overlap_start,
                        "overlap_source_end": overlap_end,
                        "cut_start": cut["start_frame"],
                        "cut_end": cut["end_frame"],
                    }
                )
    return findings


def save_project(resolve, project) -> bool:
    save = getattr(project, "Save", None)
    if callable(save):
        return bool(save())
    manager = resolve.GetProjectManager() if resolve else None
    save_project = getattr(manager, "SaveProject", None) if manager else None
    return bool(save_project(project.GetName()) if callable(save_project) else False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cuts", type=Path, required=True)
    parser.add_argument("--source-timeline", required=True)
    parser.add_argument("--timeline-name", required=True)
    parser.add_argument("--source-offset", action="append", default=[],
                        help="Map source path/name/stem substring to combined source frames, e.g. part 2.mkv=36646")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    offsets = parse_source_offsets(args.source_offset)
    source_cuts = load_source_cuts(args.source_cuts)

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
    specs = collect_specs(source_timeline, offsets)
    record_cuts, mappings = derive_record_cuts(specs, source_cuts)
    removed_frames = sum(end - start for start, end in record_cuts)
    output_name = unique_timeline_name(project, args.timeline_name)
    dry_report = {
        "schema": "rby_umb_apply_approved_source_cuts_to_timeline_v1",
        "dry_run": bool(args.dry_run),
        "project": project.GetName(),
        "source_timeline": source_timeline.GetName(),
        "output_timeline": output_name,
        "source_cuts": str(args.source_cuts),
        "source_cut_count": len(source_cuts),
        "source_offsets": offsets,
        "source_start": old_start,
        "source_end": old_end,
        "record_cuts": [{"start": s, "end": e, "duration": e - s} for s, e in record_cuts],
        "record_cut_count": len(record_cuts),
        "mapped_overlap_count": len(mappings),
        "removed_frames": removed_frames,
        "expected_end": old_end - removed_frames,
        "mappings": mappings,
        "source_track_counts": track_counts(source_timeline),
    }
    if args.dry_run:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(dry_report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps(dry_report, indent=2, ensure_ascii=False, default=str))
        return 0

    new_timeline = pool.CreateEmptyTimeline(output_name)
    if new_timeline is None:
        raise RuntimeError(f"CreateEmptyTimeline failed for {output_name!r}")
    project.SetCurrentTimeline(new_timeline)
    ensure_tracks(new_timeline, source_timeline)
    new_start = int(new_timeline.GetStartFrame())

    payload, colors = build_payload(specs, record_cuts, new_start, old_start)
    placed = append_payload(pool, payload)
    marker_report = add_shifted_markers(source_timeline, new_timeline, record_cuts, new_start, old_start)
    color_report = restore_colors(new_timeline, colors)
    validation_findings = validate_cut_absence(new_timeline, offsets, source_cuts)
    save_ok = save_project(resolve, project)

    report = {
        **dry_report,
        "dry_run": False,
        "output_timeline": new_timeline.GetName(),
        "new_start": new_start,
        "new_end": int(new_timeline.GetEndFrame()),
        "placed": placed,
        "expected_placed": len(payload),
        "track_counts": track_counts(new_timeline),
        "marker_report": marker_report,
        "color_report": color_report,
        "validation_overlap_count": len(validation_findings),
        "validation_overlaps": validation_findings[:50],
        "project_save_ok": save_ok,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({
        "output_timeline": new_timeline.GetName(),
        "removed_frames": removed_frames,
        "record_cut_count": len(record_cuts),
        "placed": placed,
        "expected_placed": len(payload),
        "new_end": int(new_timeline.GetEndFrame()),
        "expected_end": old_end - removed_frames,
        "markers": marker_report,
        "validation_overlap_count": len(validation_findings),
        "report": str(args.report),
        "project_save_ok": save_ok,
    }, indent=2, ensure_ascii=False, default=str))

    if placed != len(payload):
        return 2
    if marker_report["failures"] or color_report["failures"]:
        return 3
    if validation_findings:
        return 4
    if not save_ok:
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
