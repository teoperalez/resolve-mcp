from __future__ import annotations

"""Apply the missing Victreebel post-battle V1 visual holds.

This is a project-specific repair pass for the approved-cuts full rebuild. It
duplicates the current/final timeline by default, deletes only V1 clips over the
target hold spans, and places one continuous Part 2 video clip over each span.
A1, A2, A3, V2, markers, BGM, battle audio, and carousel layout are left alone.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


SOURCE_TIMELINE = "Victreebel RBY UMB final approved cuts full rebuild"
TIMELINE_BASE = "Victreebel RBY UMB final approved cuts full rebuild visual holds old rule fixed"
OUT_DIR = Path(
    r"E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\cut_review_locked_autocut\final_full_rebuild_hold_fixed"
)
PART2_NAME = "Victreebel Red and Blue Ultra Minimum Battles part 2.mp4"
PART2_PATH = Path(r"E:\Victreebel Red and Blue Ultra Minimum Battles") / PART2_NAME


OLD_RULE_VISUAL_HOLDS = [
    {"label": "Brock", "source_start": 49803, "duration": 1528},
    {"label": "Misty", "source_start": 58544, "duration": 1065},
    {"label": "Erika", "source_start": 69115, "duration": 2119},
    {"label": "Lt. Surge", "source_start": 77800, "duration": 1264},
    {"label": "Giovanni", "source_start": 103805, "duration": 1338},
    {"label": "Koga", "source_start": 114611, "duration": 1553},
    {"label": "Sabrina", "source_start": 160280, "duration": 3418},
    {"label": "Blaine", "source_start": 170245, "duration": 1043},
    {"label": "Champion", "source_start": 213476, "duration": None},
]


def find_timeline(project, name: str):
    for index in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline and timeline.GetName() == name:
            return timeline
    return None


def unique_timeline_name(project, base: str) -> str:
    if not find_timeline(project, base):
        return base
    index = 2
    while find_timeline(project, f"{base} {index}"):
        index += 1
    return f"{base} {index}"


def media_path(item) -> str:
    media_pool_item = item.GetMediaPoolItem()
    if not media_pool_item:
        return ""
    try:
        return media_pool_item.GetClipProperty("File Path") or ""
    except Exception:
        return ""


def overlapping(items, start: int, end: int):
    return [item for item in items if item.GetStart() < end and item.GetEnd() > start]


def marker_map(timeline) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for rel_raw, data in (timeline.GetMarkers() or {}).items():
        name = data.get("name") or ""
        rel = int(round(float(rel_raw)))
        out.setdefault(name, []).append(rel)
    for frames in out.values():
        frames.sort()
    return out


def source_frame_at(v1_items, abs_frame: int) -> tuple[object, int]:
    for item in v1_items:
        if item.GetStart() <= abs_frame < item.GetEnd():
            return item, int(item.GetLeftOffset()) + (abs_frame - int(item.GetStart()))
    raise RuntimeError(f"No V1 item covers frame {abs_frame}")


def record_frame_for_source(v1_items, start_frame: int, source_frame: int) -> tuple[int, bool]:
    part2_items = [
        item
        for item in v1_items
        if Path(media_path(item)).name == PART2_NAME
    ]
    for item in part2_items:
        left = int(item.GetLeftOffset())
        right = left + int(item.GetDuration())
        if left <= source_frame < right:
            return int(item.GetStart()) - start_frame + (source_frame - left), False
    later = [
        item
        for item in part2_items
        if int(item.GetLeftOffset()) > source_frame
    ]
    if not later:
        raise RuntimeError(f"No later Part 2 V1 clip after source frame {source_frame}")
    next_item = min(later, key=lambda item: int(item.GetLeftOffset()))
    return int(next_item.GetStart()) - start_frame, True


def next_structural_start(markers: dict[str, list[int]], after_rel: int) -> int | None:
    starts = []
    for name, frames in markers.items():
        if name.endswith("Leader Intro Start") or name.endswith("Battle Start"):
            starts.extend(frame for frame in frames if frame > after_rel)
    return min(starts) if starts else None


def build_holds(timeline, start_frame: int) -> list[dict]:
    markers = marker_map(timeline)
    v1_items = sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda item: item.GetStart())
    holds = []
    for spec in OLD_RULE_VISUAL_HOLDS:
        leader = spec["label"]
        source_start = int(spec["source_start"])
        rel_start, snapped_to_next_clip = record_frame_for_source(v1_items, start_frame, source_start)
        if leader == "Champion":
            continue
        rel_end = rel_start + int(spec["duration"])
        next_start = next_structural_start(markers, rel_start)
        if next_start is not None and rel_end > next_start:
            rel_end = next_start
        if rel_end <= rel_start:
            raise RuntimeError(f"Bad hold span for {leader}: {rel_start}-{rel_end}")
        holds.append(
            {
                "label": leader,
                "kind": "post_battle_visual_hold",
                "rel_start": rel_start,
                "rel_end": rel_end,
                "duration": rel_end - rel_start,
                "source_start": source_start,
                "source_item_path": str(PART2_PATH),
                "snapped_to_next_retained_clip": snapped_to_next_clip,
                "rule": "old_rule_last_battle_overlay_source_anchor_to_data_card_end",
            }
        )

    beat = (markers.get("Beat Champion") or [None])[0]
    tierlist_candidates = [
        frame
        for name, frames in markers.items()
        if name.startswith("Final Tierlist")
        for frame in frames
        if beat is not None and frame > beat
    ]
    if beat is None or not tierlist_candidates:
        raise RuntimeError("Missing Beat Champion or later Final Tierlist marker")
    rel_start = beat
    champion_spec = next(hold for hold in OLD_RULE_VISUAL_HOLDS if hold["label"] == "Champion")
    rel_start, snapped_to_next_clip = record_frame_for_source(
        v1_items,
        start_frame,
        int(champion_spec["source_start"]),
    )
    rel_end = min(tierlist_candidates)
    source_start = int(champion_spec["source_start"])
    holds.append(
        {
            "label": "Champion",
            "kind": "champion_post_battle_visual_hold",
            "rel_start": rel_start,
            "rel_end": rel_end,
            "duration": rel_end - rel_start,
            "source_start": source_start,
            "source_item_path": str(PART2_PATH),
            "snapped_to_next_retained_clip": snapped_to_next_clip,
            "rule": "old_rule_last_battle_overlay_before_Beat_Champion_to_first_Final_Tierlist_marker",
        }
    )
    return sorted(holds, key=lambda hold: hold["rel_start"])


def duplicate_current(project, timeline, base_name: str):
    name = unique_timeline_name(project, base_name)
    dup = timeline.DuplicateTimeline(name)
    if not dup:
        raise RuntimeError(f"DuplicateTimeline failed for {name!r}")
    project.SetCurrentTimeline(dup)
    return dup


def save_project(resolve, project) -> bool:
    save = getattr(project, "Save", None)
    if callable(save):
        return bool(save())
    save_project = getattr(resolve.GetProjectManager(), "SaveProject", None)
    return bool(save_project()) if callable(save_project) else False


def append_video_clip(pool, spec: dict, color: str | None = None):
    got = pool.AppendToTimeline([spec]) or []
    if len(got) != 1:
        raise RuntimeError(f"AppendToTimeline placed {len(got)} clip(s) for {spec}")
    clip = got[0]
    if color is not None:
        try:
            if color:
                clip.SetClipColor(color)
            else:
                clip.ClearClipColor()
        except Exception:
            pass
    return clip


def apply_holds(project, timeline, holds: list[dict], start_frame: int) -> dict:
    pool = project.GetMediaPool()
    v1_items = sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda item: item.GetStart())
    delete_items = []
    payload = []
    boundary_payload = []
    for hold in holds:
        abs_start = start_frame + hold["rel_start"]
        abs_end = start_frame + hold["rel_end"]
        touched = overlapping(v1_items, abs_start, abs_end)
        if not touched:
            raise RuntimeError(f"No V1 clips overlap {hold['label']} hold {abs_start}-{abs_end}")
        media_pool_item = touched[0].GetMediaPoolItem()
        delete_items.extend(touched)
        for item in touched:
            item_start = int(item.GetStart())
            item_end = int(item.GetEnd())
            item_left = int(item.GetLeftOffset())
            item_color = item.GetClipColor() or ""
            if item_start < abs_start:
                keep_duration = abs_start - item_start
                boundary_payload.append(
                    (
                        {
                            "mediaPoolItem": item.GetMediaPoolItem(),
                            "startFrame": item_left,
                            "endFrame": item_left + keep_duration,
                            "recordFrame": item_start,
                            "trackIndex": 1,
                            "mediaType": 1,
                        },
                        item_color,
                    )
                )
            if item_end > abs_end:
                trim = abs_end - item_start
                keep_duration = item_end - abs_end
                boundary_payload.append(
                    (
                        {
                            "mediaPoolItem": item.GetMediaPoolItem(),
                            "startFrame": item_left + trim,
                            "endFrame": item_left + trim + keep_duration,
                            "recordFrame": abs_end,
                            "trackIndex": 1,
                            "mediaType": 1,
                        },
                        item_color,
                    )
                )
        payload.append(
            {
                "mediaPoolItem": media_pool_item,
                "startFrame": hold["source_start"],
                "endFrame": hold["source_start"] + hold["duration"],
                "recordFrame": abs_start,
                "trackIndex": 1,
                "mediaType": 1,
            }
        )

    unique = []
    seen = set()
    for item in delete_items:
        key = (item.GetStart(), item.GetEnd(), item.GetLeftOffset(), item.GetName())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    delete_ok = bool(timeline.DeleteClips(unique, False)) if unique else True
    if not delete_ok:
        raise RuntimeError("DeleteClips returned false")

    placed = []
    for spec, color in boundary_payload:
        placed.append(append_video_clip(pool, spec, color))
    for spec, _hold in zip(payload, holds, strict=True):
        placed.append(append_video_clip(pool, spec, "Purple"))

    prefix = "Visual Hold Fixed:"
    for rel_raw, data in list((timeline.GetMarkers() or {}).items()):
        if (data.get("name") or "").startswith(prefix):
            timeline.DeleteMarkerAtFrame(int(round(float(rel_raw))))
    for hold in holds:
        note = f"src={hold['source_start']} dur={hold['duration']}; {hold['rule']}"
        timeline.AddMarker(hold["rel_start"], "Purple", f"{prefix} {hold['label']}", note, 1)

    return {
        "deleted_count": len(unique),
        "placed_count": len(placed),
        "hold_clip_count": len(payload),
        "boundary_clip_count": len(boundary_payload),
    }


def verify_holds(timeline, holds: list[dict], start_frame: int) -> list[dict]:
    v1_items = sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda item: item.GetStart())
    a1_items = sorted(timeline.GetItemListInTrack("audio", 1) or [], key=lambda item: item.GetStart())
    checks = []
    for hold in holds:
        abs_start = start_frame + hold["rel_start"]
        abs_end = start_frame + hold["rel_end"]
        v_hits = overlapping(v1_items, abs_start, abs_end)
        a_hits = overlapping(a1_items, abs_start, abs_end)
        exact = (
            len(v_hits) == 1
            and int(v_hits[0].GetStart()) == abs_start
            and int(v_hits[0].GetEnd()) == abs_end
            and int(v_hits[0].GetLeftOffset()) == hold["source_start"]
            and (v_hits[0].GetClipColor() or "") == "Purple"
        )
        checks.append(
            {
                "label": hold["label"],
                "rel_start": hold["rel_start"],
                "rel_end": hold["rel_end"],
                "duration": hold["duration"],
                "source_start": hold["source_start"],
                "v1_overlap_count": len(v_hits),
                "v1_exact": exact,
                "v1_color": v_hits[0].GetClipColor() if v_hits else None,
                "a1_overlap_count": len(a_hits),
            }
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-timeline", default=SOURCE_TIMELINE)
    parser.add_argument("--timeline-base", default=TIMELINE_BASE)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Resolve scripting connection failed")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No Resolve project is open")
    source = find_timeline(project, args.source_timeline)
    if not source:
        raise RuntimeError(f"Timeline not found: {args.source_timeline}")
    project.SetCurrentTimeline(source)
    start_frame = int(source.GetStartFrame())
    holds = build_holds(source, start_frame)

    report: dict[str, object] = {
        "source_timeline": source.GetName(),
        "dry_run": args.dry_run,
        "timeline_start": start_frame,
        "holds": holds,
    }
    if args.dry_run:
        print(json.dumps(report, indent=2))
        return 0

    timeline = source if args.in_place else duplicate_current(project, source, args.timeline_base)
    start_frame = int(timeline.GetStartFrame())
    apply_report = apply_holds(project, timeline, holds, start_frame)
    checks = verify_holds(timeline, holds, start_frame)
    drt = OUT_DIR / f"{timeline.GetName()}.drt"
    try:
        drt_exported = bool(timeline.Export(str(drt), resolve.EXPORT_DRT, resolve.EXPORT_NONE))
    except Exception as exc:
        drt_exported = False
        report["drt_error"] = repr(exc)
    save_ok = save_project(resolve, project)

    report.update(
        {
            "timeline": timeline.GetName(),
            "timeline_end": int(timeline.GetEndFrame()),
            "apply": apply_report,
            "checks": checks,
            "drt": str(drt),
            "drt_exported": drt_exported,
            "project_save_ok": save_ok,
        }
    )
    report["ok"] = all(c["v1_exact"] and c["a1_overlap_count"] > 0 for c in checks) and drt_exported and save_ok
    report_path = OUT_DIR / f"{timeline.GetName()}_visual_hold_fix_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
