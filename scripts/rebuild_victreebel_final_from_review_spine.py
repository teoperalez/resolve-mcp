from __future__ import annotations

"""Build the full Victreebel final timeline from the approved review spine.

This consumes the lightweight Resolve timeline produced by
apply_cut_review_decisions_native.py, so final Pink review decisions stay in the
editorial spine. It then applies the heavier deterministic stages that the
ordinary full rebuild script handles from FCPXML data: source-derived visual
holds, non-boss gaps, and 2x Gen 1 leader intros.
"""

import argparse
import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

import apply_cut_review_decisions_native as review_apply
import rebuild_victreebel_rby_timeline as R
from scripts import build_victreebel_rby_fcpxml as B


SOURCE_TIMELINE = "Victreebel RBY UMB locked editorial review decisions applied native 2"
TIMELINE_BASE = "Victreebel RBY UMB final approved cuts full rebuild"
OUT_DIR = B.CODEX_DIR / "cut_review_locked_autocut" / "final_full_rebuild"
REVIEW_REPORT = (
    B.CODEX_DIR
    / "cut_review_locked_autocut"
    / "review_decisions_applied"
    / "review_decisions_applied_native_report.json"
)
NORMALIZED_RANGES = (
    B.CODEX_DIR
    / "cut_review_locked_autocut"
    / "review_decisions_applied"
    / "review_decisions_normalized_ranges.json"
)


def find_timeline(project, name: str):
    for index in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline and timeline.GetName() == name:
            return timeline
    return None


def media_path(item) -> Path:
    mpi = item.GetMediaPoolItem()
    if not mpi:
        return Path()
    try:
        return Path(mpi.GetClipProperty("File Path") or "")
    except Exception:
        return Path()


def media_fps(item) -> float:
    mpi = item.GetMediaPoolItem()
    if not mpi:
        return float(R.FPS)
    try:
        props = mpi.GetClipProperty() or {}
    except Exception:
        return float(R.FPS)
    for key in ("FPS", "Video Frame Rate", "Frame Rate"):
        try:
            value = float(props.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return float(R.FPS)


def source_duration_for_video(item) -> int:
    duration = int(item.GetDuration())
    fps = media_fps(item)
    if abs(fps - R.FPS) < 0.001:
        return duration
    return max(1, int(round(duration * fps / R.FPS)))


def make_marker(label: str, note: str, color: str, rel_frame: int) -> B.Marker:
    return B.Marker(
        label=label,
        note=note or "",
        color=color or "Green",
        category=note or "",
        name=label,
        session_elapsed_sec=0.0,
        source_part=2,
        source_sec=0.0,
        source_frame=0,
        part_timeline_frame=rel_frame,
        combined_frame=rel_frame,
        snapped=False,
    )


def current_markers(timeline) -> list[B.Marker]:
    markers: list[B.Marker] = []
    for rel_raw, data in (timeline.GetMarkers() or {}).items():
        rel = int(round(float(rel_raw)))
        markers.append(make_marker(data.get("name") or "", data.get("note") or "", data.get("color") or "", rel))
    return sorted(markers, key=lambda marker: marker.combined_frame)


def restore_dropped_structural_markers(markers: list[B.Marker], timeline_start: int) -> list[dict]:
    """Restore dropped Battle Start markers at the post-cut boundary.

    Marker remapping normally drops markers inside deleted intervals. For the
    final build, battle starts are structural: leader intros, battle audio, BGM
    blocking, and section colors all depend on them. If a Battle Start marker
    was inside a removed clip, the battle now starts at the retained cut
    boundary, so restore it there.
    """
    if not REVIEW_REPORT.exists() or not NORMALIZED_RANGES.exists():
        return []

    report = json.loads(REVIEW_REPORT.read_text(encoding="utf-8"))
    metadata = json.loads(NORMALIZED_RANGES.read_text(encoding="utf-8"))
    cuts = metadata.get("merged_ranges") or []
    restored = []
    names = {marker.label for marker in markers}
    for dropped in ((report.get("marker_report") or {}).get("dropped") or []):
        marker_data = dropped.get("marker") or {}
        name = marker_data.get("name") or ""
        if not name.endswith("Battle Start") or name in names:
            continue
        abs_frame = int(dropped.get("abs_frame") or 0)
        containing = next((cut for cut in cuts if int(cut["start"]) <= abs_frame < int(cut["end"])), None)
        if not containing:
            continue
        new_abs = int(containing["start"]) - review_apply.cut_shift_before(int(containing["start"]), cuts)
        rel = new_abs - timeline_start
        markers.append(make_marker(name, marker_data.get("note") or "", marker_data.get("color") or "Green", rel))
        restored.append({"name": name, "old_abs": abs_frame, "new_abs": new_abs, "new_rel": rel})
        names.add(name)
    markers.sort(key=lambda marker: marker.combined_frame)
    return restored


def timeline_clip_to_bclip(item, part: int, src: Path, dialogue: Path) -> B.Clip:
    return B.Clip(
        part=part,
        src=src,
        dialogue=dialogue,
        offset=int(item.GetStart()) - int(item.GetTimeline().GetStartFrame()) if hasattr(item, "GetTimeline") else 0,
        start=int(item.GetLeftOffset()),
        duration=int(item.GetDuration()),
        name=item.GetName() or src.stem,
    )


def collect_dialogue_clips(timeline, timeline_start: int) -> tuple[list[B.Clip], list[B.Clip]]:
    part1: list[B.Clip] = []
    part2: list[B.Clip] = []
    for item in sorted(timeline.GetItemListInTrack("audio", 1) or [], key=lambda c: c.GetStart()):
        path = media_path(item)
        name = path.name.lower()
        if name.endswith("part 1_3.wav"):
            part1.append(
                B.Clip(
                    part=1,
                    src=R.PART1_VIDEO,
                    dialogue=B.PART1_DIALOGUE,
                    offset=int(item.GetStart()) - timeline_start,
                    start=int(item.GetLeftOffset()),
                    duration=int(item.GetDuration()),
                    name=R.PART1_VIDEO.name,
                )
            )
        elif name.endswith("part 2_3.wav"):
            part2.append(
                B.Clip(
                    part=2,
                    src=R.PART2_VIDEO,
                    dialogue=B.PART2_DIALOGUE,
                    offset=int(item.GetStart()) - timeline_start,
                    start=int(item.GetLeftOffset()),
                    duration=int(item.GetDuration()),
                    name=R.PART2_VIDEO.name,
                )
            )
    if not part1 or not part2:
        raise RuntimeError(f"Expected Part 1 and Part 2 dialogue on A1, got part1={len(part1)} part2={len(part2)}")
    return part1, part2


def boundary_video_entries(timeline, timeline_start: int) -> list[R.Entry]:
    entries: list[R.Entry] = []
    for item in sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda c: c.GetStart()):
        path = media_path(item)
        lower = path.name.lower()
        if lower == "blue version intro.mp4":
            entries.append(
                R.Entry(
                    path,
                    1,
                    1,
                    int(item.GetStart()) - timeline_start,
                    int(item.GetLeftOffset()),
                    int(item.GetDuration()),
                    "intro",
                    source_duration=source_duration_for_video(item),
                )
            )
        elif lower == "rby outro w audio.mov":
            entries.append(
                R.Entry(
                    path,
                    1,
                    1,
                    int(item.GetStart()) - timeline_start,
                    int(item.GetLeftOffset()),
                    int(item.GetDuration()),
                    "outro",
                    source_duration=source_duration_for_video(item),
                )
            )
    if len(entries) != 2:
        raise RuntimeError(f"Expected intro and outro V1 boundary clips, got {len(entries)}")
    return entries


def clip_entries(clips: list[B.Clip], media_type: int, track: int, role: str, path_attr: str) -> list[R.Entry]:
    out: list[R.Entry] = []
    for clip in clips:
        path = getattr(clip, path_attr)
        if path is None:
            continue
        out.append(R.Entry(path, media_type, track, clip.offset, clip.start, clip.duration, role, clip.part))
    return out


def build_entries_from_spine(timeline, timeline_start: int) -> tuple[list[R.Entry], dict]:
    part1_audio, part2_audio = collect_dialogue_clips(timeline, timeline_start)

    part1_holds = R.closed_holds_for_source(R.PART1_VIDEO, {"intro_stats", "intro_moveset", "intro_card"})
    part2_holds = R.closed_holds_for_source(R.PART2_VIDEO, {"post_battle_data_card", "final_tierlist"})
    part1_video, part1_hold_report = R.apply_source_holds_to_clips(part1_audio, part1_holds)
    part2_video, part2_hold_report = R.apply_source_holds_to_clips(part2_audio, part2_holds)

    entries = boundary_video_entries(timeline, timeline_start)
    entries.extend(clip_entries(part1_video, 1, 1, "gameplay", "src"))
    entries.extend(clip_entries(part2_video, 1, 1, "gameplay", "src"))
    entries.extend(clip_entries(part1_audio, 2, 1, "dialogue", "dialogue"))
    entries.extend(clip_entries(part2_audio, 2, 1, "dialogue", "dialogue"))

    intro = next(entry for entry in entries if entry.role == "intro")
    outro = next(entry for entry in entries if entry.role == "outro")
    B.BGM_PATH = B.copy_asset(B.BGM_SOURCE, "global")
    B.OUTRO_PATH = B.copy_asset(B.OUTRO_SOURCE, "global")
    bgm_frames = R.media_frames(B.BGM_PATH)
    entries.append(R.Entry(B.BGM_PATH, 2, 2, intro.offset, 0, min(bgm_frames, intro.duration), "intro_music"))
    entries.append(R.Entry(B.OUTRO_PATH, 2, 3, outro.offset, 0, outro.duration, "outro_audio"))

    return entries, {"part1": part1_hold_report, "part2": part2_hold_report}


def save_project(resolve, project) -> bool:
    save = getattr(project, "Save", None)
    if callable(save):
        return bool(save())
    manager = resolve.GetProjectManager()
    save_project = getattr(manager, "SaveProject", None)
    return bool(save_project()) if callable(save_project) else False


def count_timeline_items(timeline) -> int:
    total = 0
    for track_type in ("video", "audio"):
        for track in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            total += len(timeline.GetItemListInTrack(track_type, track) or [])
    return total


def append_entries(pool, entries: list[R.Entry], items: dict[str, object], tl_start: int, start_index: int = 0) -> int:
    ordered = sorted(entries, key=lambda e: (tl_start + e.offset, e.track, e.media_type))
    remaining = ordered[start_index:]
    if not remaining:
        return 0
    print(f"resuming append at planned entry {start_index + 1}/{len(ordered)}", flush=True)
    return R.append_entries(pool, remaining, items, tl_start)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-timeline", default=SOURCE_TIMELINE)
    parser.add_argument("--timeline-base", default=TIMELINE_BASE)
    parser.add_argument("--resume-timeline", default=None, help="Append remaining planned entries to an existing partial timeline.")
    parser.add_argument("--resume-from", type=int, default=None, help="Number of planned entries already placed. Defaults to current item count.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Resolve scripting connection failed")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No Resolve project is open")
    pool = project.GetMediaPool()

    source = find_timeline(project, args.source_timeline)
    if not source:
        raise RuntimeError(f"Could not find source timeline {args.source_timeline!r}")
    project.SetCurrentTimeline(source)
    timeline_start = int(source.GetStartFrame())
    entries, hold_report = build_entries_from_spine(source, timeline_start)
    markers = current_markers(source)
    restored_markers = restore_dropped_structural_markers(markers, timeline_start)

    gap_markers = copy.deepcopy(markers)
    gaps = R.add_nonboss_gaps(entries, gap_markers)
    entries, insertions = R.apply_leader_insertions(entries, gap_markers)
    report = {
        "source_timeline": source.GetName(),
        "source_start": timeline_start,
        "source_end": int(source.GetEndFrame()),
        "entries_prepared": len(entries),
        "log_holds": hold_report,
        "restored_structural_markers": restored_markers,
        "nonboss_gaps": gaps,
        "leader_insertions": insertions,
    }

    if args.dry_run:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 0

    if args.resume_timeline:
        timeline = find_timeline(project, args.resume_timeline)
        if not timeline:
            raise RuntimeError(f"Could not find resume timeline {args.resume_timeline!r}")
        project.SetCurrentTimeline(timeline)
        resume_from = args.resume_from if args.resume_from is not None else count_timeline_items(timeline)
        if resume_from < 0 or resume_from > len(entries):
            raise RuntimeError(f"Bad resume index {resume_from}; planned entries={len(entries)}")
    else:
        name = R.unique_timeline_name(project, args.timeline_base)
        timeline = pool.CreateEmptyTimeline(name)
        if not timeline:
            raise RuntimeError(f"CreateEmptyTimeline failed for {name!r}")
        project.SetCurrentTimeline(timeline)
        while timeline.GetTrackCount("audio") < 3:
            timeline.AddTrack("audio", "stereo")
        timeline.SetSetting("timelineFrameRate", "60")
        timeline.SetSetting("timelinePlaybackFrameRate", "60")
        timeline.SetSetting("timelineResolutionWidth", "1920")
        timeline.SetSetting("timelineResolutionHeight", "1080")
        resume_from = 0

    tl_start = int(timeline.GetStartFrame())
    items = R.import_media(pool, sorted({entry.path.resolve() for entry in entries}))
    newly_placed = append_entries(pool, entries, items, tl_start, resume_from)
    placed = resume_from + newly_placed
    R.add_markers(timeline, markers=gap_markers, insertions=insertions, gaps=gaps)
    time.sleep(1)

    audit = R.self_audit(timeline, insertions, gaps)
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
            "timeline_start": tl_start,
            "timeline_end": int(timeline.GetEndFrame()),
            "placed_count": placed,
            "newly_placed_count": newly_placed,
            "resume_from": resume_from,
            "entries_expected": len(entries),
            "audit": audit,
            "drt": str(drt),
            "drt_exported": drt_exported,
            "project_save_ok": save_ok,
        }
    )
    report["ok"] = placed == len(entries) and not audit["violations"] and drt_exported and save_ok
    report_path = OUT_DIR / f"{timeline.GetName()}_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
