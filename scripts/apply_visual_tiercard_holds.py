from __future__ import annotations

"""Apply visually-picked V1-only tiercard holds for the Victreebel RBY UMB pass.

The hold edges here come from a contact-sheet pass around the live timeline's
leader finish / Beat Champion markers. A1 and music tracks are intentionally
left alone: only V1 is replaced with one continuous source span over each card.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


OUT_DIR = Path(r"E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\visual_tiercard_pass")
PART2_NAME = "Victreebel Red and Blue Ultra Minimum Battles part 2.mp4"


# rel_start/end are current-timeline-relative frames before this pass.
# start_clip_index/end_clip_index are audit breadcrumbs from the visual sheet.
VISUAL_HOLDS = [
    {"label": "Brock", "start_clip_index": 180, "end_clip_index": 190, "rel_start": 48399, "rel_end": 49927, "source_start": 49803},
    {"label": "Misty", "start_clip_index": 227, "end_clip_index": 236, "rel_start": 55067, "rel_end": 56132, "source_start": 58544},
    {"label": "Erika", "start_clip_index": 291, "end_clip_index": 297, "rel_start": 63468, "rel_end": 65587, "source_start": 69115},
    {"label": "Lt. Surge", "start_clip_index": 339, "end_clip_index": 353, "rel_start": 70307, "rel_end": 71571, "source_start": 77800},
    {"label": "Giovanni", "start_clip_index": 458, "end_clip_index": 464, "rel_start": 85840, "rel_end": 87178, "source_start": 103805},
    {"label": "Koga", "start_clip_index": 506, "end_clip_index": 514, "rel_start": 94551, "rel_end": 96104, "source_start": 114611},
    {"label": "Sabrina", "start_clip_index": 744, "end_clip_index": 762, "rel_start": 127462, "rel_end": 130880, "source_start": 160280},
    {"label": "Blaine", "start_clip_index": 792, "end_clip_index": 799, "rel_start": 135112, "rel_end": 136155, "source_start": 170245},
    {"label": "Champion", "start_clip_index": 1018, "end_clip_index": 1020, "rel_start": 166841, "rel_end": 168145, "source_start": 213476},
]


def media_path(item) -> str:
    mpi = item.GetMediaPoolItem()
    if not mpi:
        return ""
    try:
        return mpi.GetClipProperty("File Path") or ""
    except Exception:
        return ""


def find_timeline(project, name: str):
    for i in range(1, project.GetTimelineCount() + 1):
        tl = project.GetTimelineByIndex(i)
        if tl and tl.GetName() == name:
            return tl
    return None


def unique_timeline_name(project, base: str) -> str:
    if not find_timeline(project, base):
        return base
    n = 2
    while find_timeline(project, f"{base} {n}"):
        n += 1
    return f"{base} {n}"


def duplicate_current(project, name: str):
    current = project.GetCurrentTimeline()
    if not current:
        raise RuntimeError("No current timeline")
    new_name = unique_timeline_name(project, name)
    dup = current.DuplicateTimeline(new_name)
    if not dup:
        raise RuntimeError(f"DuplicateTimeline failed for {new_name!r}")
    project.SetCurrentTimeline(dup)
    return dup


def overlapping(items, start: int, end: int):
    return [it for it in items if it.GetStart() < end and it.GetStart() + it.GetDuration() > start]


def cleanup_duplicate_source_audio(timeline, source_name: str, ranges: list[tuple[int, int]]) -> int:
    to_delete = []
    for track in range(2, timeline.GetTrackCount("audio") + 1):
        for item in timeline.GetItemListInTrack("audio", track) or []:
            if Path(media_path(item)).name != source_name:
                continue
            istart = item.GetStart()
            iend = istart + item.GetDuration()
            if any(istart < end and iend > start for start, end in ranges):
                to_delete.append(item)
    if to_delete:
        timeline.DeleteClips(to_delete, False)
    return len(to_delete)


def add_audit_markers(timeline, start_frame: int, holds: list[dict]) -> None:
    prefix = "Visual Tiercard V1 Hold Start:"
    for rel, data in list((timeline.GetMarkers() or {}).items()):
        if (data.get("name") or "").startswith(prefix):
            timeline.DeleteMarkerAtFrame(int(round(float(rel))))
    for hold in holds:
        rel = hold["rel_start"]
        note = (
            f"visual pass; old clips {hold['start_clip_index']}..{hold['end_clip_index'] - 1}; "
            f"src={hold['source_start']} dur={hold['rel_end'] - hold['rel_start']}"
        )
        timeline.AddMarker(rel, "Yellow", f"{prefix} {hold['label']}", note, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline-name", default="Victreebel UMB CODEx visual tiercard V1 hold pass")
    ap.add_argument("--in-place", action="store_true", help="Modify current timeline instead of duplicating it first.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    resolve = dvr.scriptapp("Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No Resolve project is open")
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No current timeline")
    fps = float(project.GetSetting("timelineFrameRate") or 60)
    start_frame = int(timeline.GetStartFrame())
    before_name = timeline.GetName()

    if args.dry_run:
        target = timeline
    elif args.in_place:
        target = timeline
    else:
        target = duplicate_current(project, args.timeline_name)
        timeline = target
        start_frame = int(timeline.GetStartFrame())

    v1 = timeline.GetItemListInTrack("video", 1) or []
    a1_count_before = len(timeline.GetItemListInTrack("audio", 1) or [])
    report: dict[str, object] = {
        "source_timeline": before_name,
        "timeline": timeline.GetName(),
        "fps": fps,
        "dry_run": args.dry_run,
        "visual_holds": [],
    }

    payload = []
    delete_items = []
    source_ranges = []
    for hold in VISUAL_HOLDS:
        abs_start = start_frame + hold["rel_start"]
        abs_end = start_frame + hold["rel_end"]
        dur = abs_end - abs_start
        if dur <= 0:
            raise RuntimeError(f"Bad hold duration for {hold['label']}")
        touched = overlapping(v1, abs_start, abs_end)
        if not touched:
            raise RuntimeError(f"No V1 clips overlap {hold['label']} range {abs_start}-{abs_end}")
        mpi = touched[0].GetMediaPoolItem()
        if not mpi:
            raise RuntimeError(f"Missing media pool item for {hold['label']}")
        if Path(media_path(touched[0])).name != PART2_NAME:
            raise RuntimeError(f"{hold['label']} start clip is not {PART2_NAME}: {media_path(touched[0])}")
        delete_items.extend(touched)
        source_ranges.append((abs_start, abs_end))
        payload.append({
            "mediaPoolItem": mpi,
            "startFrame": hold["source_start"],
            "endFrame": hold["source_start"] + dur,
            "recordFrame": abs_start,
            "trackIndex": 1,
            "mediaType": 1,
        })
        report["visual_holds"].append({
            **hold,
            "abs_start": abs_start,
            "abs_end": abs_end,
            "duration": dur,
            "deleted_clip_count": len(touched),
            "deleted_clip_indices_hint": [hold["start_clip_index"], hold["end_clip_index"]],
        })

    if args.dry_run:
        print(json.dumps(report, indent=2))
        return 0

    delete_unique = []
    seen = set()
    for item in delete_items:
        key = (item.GetStart(), item.GetDuration(), item.GetLeftOffset(), item.GetName())
        if key not in seen:
            seen.add(key)
            delete_unique.append(item)
    if delete_unique:
        ok = timeline.DeleteClips(delete_unique, False)
        report["delete_count"] = len(delete_unique)
        report["delete_ok"] = bool(ok)
        if not ok:
            raise RuntimeError("DeleteClips returned false")

    placed = []
    pool = project.GetMediaPool()
    for spec in payload:
        got = pool.AppendToTimeline([spec]) or []
        placed.extend(got)
    report["placed_count"] = len(placed)
    if len(placed) != len(payload):
        raise RuntimeError(f"Placed {len(placed)}/{len(payload)} visual holds")

    removed_audio = cleanup_duplicate_source_audio(timeline, PART2_NAME, source_ranges)
    report["duplicate_source_audio_removed"] = removed_audio
    add_audit_markers(timeline, start_frame, VISUAL_HOLDS)

    # Verify V1 has exactly one clip over each hold and A1 was not rewritten.
    v1_after = timeline.GetItemListInTrack("video", 1) or []
    a1_after = timeline.GetItemListInTrack("audio", 1) or []
    checks = []
    for hold in VISUAL_HOLDS:
        abs_start = start_frame + hold["rel_start"]
        abs_end = start_frame + hold["rel_end"]
        hits = overlapping(v1_after, abs_start, abs_end)
        a1_hits = overlapping(a1_after, abs_start, abs_end)
        checks.append({
            "label": hold["label"],
            "v1_overlap_count": len(hits),
            "v1_exact": bool(
                len(hits) == 1
                and hits[0].GetStart() == abs_start
                and hits[0].GetStart() + hits[0].GetDuration() == abs_end
                and hits[0].GetLeftOffset() == hold["source_start"]
            ),
            "a1_overlap_count": len(a1_hits),
        })
    report["checks"] = checks
    report["a1_count_before"] = a1_count_before
    report["a1_count_after"] = len(a1_after)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUT_DIR / "visual_tiercard_v1_hold_pass_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    drt = OUT_DIR / f"{timeline.GetName()}.drt"
    report["drt_path"] = str(drt)
    report["drt_exported"] = bool(timeline.Export(str(drt), resolve.EXPORT_DRT, resolve.EXPORT_NONE))
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"timeline={timeline.GetName()}")
    print(f"placed={len(placed)} deleted={report['delete_count']} removed_audio={removed_audio}")
    print(f"report={report_path}")
    print(f"drt={drt} exported={report['drt_exported']}")
    for check in checks:
        print(f"{check['label']}: V1={check['v1_overlap_count']} exact={check['v1_exact']} A1={check['a1_overlap_count']}")
    if not all(c["v1_exact"] and c["a1_overlap_count"] > 0 for c in checks):
        return 2
    if not report["drt_exported"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
