from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

from scripts import build_victreebel_rby_fcpxml as B
from scripts import derive_rby_umb_hold_regions as H
from scripts import place_battle_intros as PBI


FPS = 60
OUT_DIR = B.CODEX_DIR / "full_api_rebuild"
TIMELINE_BASE = "Victreebel RBY UMB full API rebuild 2x gaps verified"
STYLE_PASS_TIMELINE_BASE = "Victreebel UMB CODEx log-hold style pass"
PART1_VIDEO = B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 1.mp4"
PART2_VIDEO = B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2.mp4"


@dataclass
class Entry:
    path: Path
    media_type: int
    track: int
    offset: int
    start: int
    duration: int
    role: str
    part: int | None = None
    source_duration: int | None = None


def log(message: str) -> None:
    print(message, flush=True)


def media_frames(path: Path) -> int:
    return B.media_duration_frames(path)


def native_video_frames(path: Path) -> int:
    data = B.ffprobe(path)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not stream:
        return media_frames(path)
    try:
        frames = int(stream.get("nb_frames") or 0)
        if frames > 0:
            return frames
    except Exception:
        pass
    rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    try:
        num, den = rate.split("/", 1)
        fps = float(num) / float(den)
        dur = float(stream.get("duration") or data["format"]["duration"])
        return max(1, int(round(dur * fps)))
    except Exception:
        return media_frames(path)


def native_video_timeline_frames(path: Path) -> int:
    data = B.ffprobe(path)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not stream:
        return media_frames(path)
    rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    try:
        num, den = rate.split("/", 1)
        native_fps = float(num) / float(den)
        return max(1, int(native_video_frames(path) * FPS / native_fps))
    except Exception:
        return media_frames(path)


def load_parts():
    B.CODEX_DIR.mkdir(parents=True, exist_ok=True)
    B.INTRO_PATH = B.copy_asset(B.INTRO_SOURCE, "global")
    B.BGM_PATH = B.copy_asset(B.BGM_SOURCE, "global")
    B.OUTRO_PATH = B.copy_asset(B.OUTRO_SOURCE, "global")
    p1_src = B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 1_ALTERED.fcpxml"
    p2_src = B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2_ALTERED.fcpxml"
    p1_fixed = B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 1_CODEx_E_DRIVE_SOURCE.fcpxml"
    p2_fixed = B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2_CODEx_E_DRIVE_SOURCE.fcpxml"
    B.write_path_corrected(p1_src, p1_fixed)
    B.write_path_corrected(p2_src, p2_fixed)
    return (
        B.load_video_clips(p1_fixed, 1, B.PART1_DIALOGUE),
        B.load_video_clips(p2_fixed, 2, B.PART2_DIALOGUE),
    )


def closed_holds_for_source(source_video: Path, kinds: set[str]) -> list[dict]:
    events = H.load_json(B.SESSION_DIR / "events.json")
    source_offset = H.source_start_elapsed(B.SESSION_DIR / "meta.json", source_video)
    source_dur = H.source_duration_sec(source_video)
    regions = H.derive_regions(
        events,
        source_offset=source_offset,
        fps=FPS,
        source_dur=source_dur,
        pad_post_battle_start=0.0,
        pad_post_battle_end=0.0,
    )
    out = []
    for region in regions:
        if region.kind not in kinds or region.source_end_frame is None:
            continue
        out.append(
            {
                "label": region.label,
                "kind": region.kind,
                "start": int(region.source_start_frame),
                "end": int(region.source_end_frame),
                "region": asdict(region),
            }
        )
    return sorted(out, key=lambda h: (h["start"], h["end"], h["label"]))


def first_intersecting_hold(holds: list[dict], src_start: int, src_end: int, hold_index: int) -> int | None:
    i = hold_index
    while i < len(holds):
        hold = holds[i]
        if hold["end"] <= src_start:
            i += 1
            continue
        if hold["start"] >= src_end:
            return None
        return i
    return None


def clip_piece(template: B.Clip, offset: int, src_start: int, duration: int,
               label: str | None = None) -> B.Clip | None:
    if duration <= 0:
        return None
    return B.Clip(
        part=template.part,
        src=template.src,
        dialogue=template.dialogue,
        offset=offset,
        start=src_start,
        duration=duration,
        name=label or template.name,
    )


def append_clip_piece(out: list[B.Clip], template: B.Clip, record: int,
                      src_start: int, src_end: int, label: str | None = None) -> int:
    piece = clip_piece(template, record, src_start, src_end - src_start, label)
    if piece:
        out.append(piece)
        return record + piece.duration
    return record


def apply_source_holds_to_clips(clips: list[B.Clip], holds: list[dict]) -> tuple[list[B.Clip], dict]:
    """Replace only the V1 picture over hold ranges.

    The editorial formula learned from the Golem reference is not a ripple
    restore. A1 remains the auto-editor-cut dialogue, while V1 is made visually
    continuous over the existing compressed timeline range.
    """
    if not holds:
        return clips, {
            "input_clips": len(clips),
            "output_clips": len(clips),
            "holds_requested": 0,
            "holds_emitted": 0,
            "duration_delta": 0,
            "visual_only": True,
        }

    ordered = sorted(clips, key=lambda c: (c.offset, c.start))
    old_frames = max(c.offset + c.duration for c in ordered)
    record_holds = []
    for hold in holds:
        record_start, start_snapped = B.map_source_frame(ordered, hold["start"])
        record_end, end_snapped = B.map_source_frame(ordered, hold["end"])
        if record_start is None or record_end is None or record_end <= record_start:
            continue
        record_holds.append(
            {
                **hold,
                "record_start": record_start,
                "record_end": record_end,
                "record_duration": record_end - record_start,
                "source_duration": hold["end"] - hold["start"],
                "start_snapped": start_snapped,
                "end_snapped": end_snapped,
            }
        )

    record_holds.sort(key=lambda h: (h["record_start"], h["record_end"]))
    merged: list[dict] = []
    for hold in record_holds:
        if merged and hold["record_start"] < merged[-1]["record_end"]:
            raise RuntimeError(f"Overlapping visual hold regions: {merged[-1]['label']} and {hold['label']}")
        merged.append(hold)

    out: list[B.Clip] = []
    for clip in ordered:
        pieces = [(clip.offset, clip.start, clip.duration)]
        for hold in merged:
            h0 = hold["record_start"]
            h1 = hold["record_end"]
            next_pieces = []
            for off, src, dur in pieces:
                end = off + dur
                if end <= h0 or off >= h1:
                    next_pieces.append((off, src, dur))
                    continue
                if off < h0:
                    keep = h0 - off
                    next_pieces.append((off, src, keep))
                if end > h1:
                    trim = h1 - off
                    next_pieces.append((h1, src + trim, end - h1))
            pieces = next_pieces
        for off, src, dur in pieces:
            piece = clip_piece(clip, off, src, dur)
            if piece:
                out.append(piece)

    template_by_part = {clip.part: clip for clip in ordered}
    for hold in merged:
        template = template_by_part.get(ordered[0].part, ordered[0])
        piece = clip_piece(
            template,
            hold["record_start"],
            hold["start"],
            hold["record_duration"],
            hold["label"],
        )
        if piece:
            out.append(piece)

    out.sort(key=lambda c: (c.offset, c.start, c.name))
    new_frames = max(c.offset + c.duration for c in out)
    report = {
        "input_clips": len(ordered),
        "output_clips": len(out),
        "holds_requested": len(holds),
        "holds_emitted": len(merged),
        "input_frames": old_frames,
        "output_frames": new_frames,
        "duration_delta": new_frames - old_frames,
        "visual_only": True,
        "holds": merged,
    }
    return out, report


def leader_for_marker(label: str) -> str | None:
    leader = B.leader_key(label)
    if not leader or leader == "Rival":
        return None
    if B.leader_video_path(leader) and B.leader_audio_path(leader):
        return leader
    return None


def add_nonboss_gaps(entries: list[Entry], markers: list[B.Marker]) -> list[dict]:
    events: list[dict] = []
    total_shift = 0
    starts = sorted(
        [m for m in markers if m.label.endswith("Battle Start")],
        key=lambda m: m.combined_frame,
    )
    for marker in starts:
        if leader_for_marker(marker.label):
            continue
        base = marker.combined_frame
        target_frame = base + total_shift
        videos = sorted(
            [e for e in entries if e.role == "gameplay" and e.media_type == 1],
            key=lambda e: e.offset,
        )
        target_idx = None
        for i, entry in enumerate(videos):
            if entry.offset <= target_frame < entry.offset + entry.duration:
                target_idx = i
                break
        if target_idx is None:
            for i, entry in enumerate(videos):
                if target_frame <= entry.offset <= target_frame + FPS:
                    target_idx = i
                    target_frame = entry.offset
                    break
        if target_idx is None:
            events.append({"label": marker.label, "status": "skipped_no_clip", "pull": 0})
            continue
        target = videos[target_idx]
        pull = min(FPS, target.start)
        if target_idx > 0 and videos[target_idx - 1].path == target.path:
            prev = videos[target_idx - 1]
            pull = min(pull, max(0, target.start - (prev.start + prev.duration)))
        if pull <= 0:
            events.append({"label": marker.label, "status": "skipped_no_handle", "pull": 0})
            continue
        old_offset = target.offset
        old_start = target.start
        old_dur = target.duration
        for entry in entries:
            if entry.offset >= old_offset:
                entry.offset += pull
            is_same_video = (
                entry.role == "gameplay"
                and entry.path == target.path
                and entry.offset == old_offset + pull
                and entry.start == old_start
                and entry.duration == old_dur
            )
            is_same_audio = (
                target.part
                and entry.role == "dialogue"
                and entry.part == target.part
                and entry.offset == old_offset + pull
                and entry.start == old_start
                and entry.duration == old_dur
            )
            if is_same_video or is_same_audio:
                entry.start -= pull
                entry.duration += pull
        for other in markers:
            if other.combined_frame >= base:
                other.combined_frame += pull
        total_shift += pull
        events.append(
            {
                "label": marker.label,
                "status": "inserted",
                "pull": pull,
                "original_frame": base,
                "new_frame": target_frame,
                "source": str(target.path),
            }
        )
    return events


def split_for_insertions(entries: list[Entry], insertions: list[dict]) -> list[Entry]:
    out: list[Entry] = []
    for entry in entries:
        pieces = [(entry.offset, entry.start, entry.duration)]
        for ins in sorted(insertions, key=lambda x: x["frame"]):
            new_pieces = []
            for off, start, dur in pieces:
                frame = ins["frame"]
                if off < frame < off + dur:
                    left = frame - off
                    new_pieces.append((off, start, left))
                    new_pieces.append((frame, start + left, dur - left))
                else:
                    new_pieces.append((off, start, dur))
            pieces = new_pieces
        for off, start, dur in pieces:
            if dur > 0:
                out.append(
                    Entry(
                        entry.path,
                        entry.media_type,
                        entry.track,
                        off,
                        start,
                        dur,
                        entry.role,
                        entry.part,
                        entry.source_duration,
                    )
                )
    return out


def apply_leader_insertions(entries: list[Entry], markers: list[B.Marker]) -> tuple[list[Entry], list[dict]]:
    insertions: list[dict] = []
    for marker in sorted(
        [m for m in markers if m.label.endswith("Battle Start")],
        key=lambda m: m.combined_frame,
    ):
        leader = leader_for_marker(marker.label)
        if not leader:
            continue
        video = PBI.retime_gen1_media(B.leader_video_path(leader), 2.0, "video")
        audio = PBI.retime_gen1_media(B.leader_audio_path(leader), 2.0, "audio")
        insertions.append(
            {
                "leader": leader,
                "label": marker.label,
                "frame": marker.combined_frame,
                "video": video,
                "audio": audio,
                "duration": native_video_timeline_frames(video),
            }
        )

    split = split_for_insertions(entries, insertions)
    final: list[Entry] = []
    cumulative = 0
    idx = 0
    insertions.sort(key=lambda x: x["frame"])
    for entry in sorted(split, key=lambda x: (x.offset, x.media_type, x.track)):
        while idx < len(insertions) and insertions[idx]["frame"] <= entry.offset:
            cumulative += insertions[idx]["duration"]
            idx += 1
        entry.offset += cumulative
        final.append(entry)

    for marker in markers:
        marker.combined_frame += sum(i["duration"] for i in insertions if i["frame"] <= marker.combined_frame)

    cumulative = 0
    for ins in insertions:
        record = ins["frame"] + cumulative
        ins["record_frame"] = record
        final.append(
            Entry(
                ins["video"],
                1,
                1,
                record,
                0,
                ins["duration"],
                "leader_intro",
                source_duration=native_video_frames(ins["video"]),
            )
        )
        final.append(Entry(ins["audio"], 2, 3, record, 0, ins["duration"], "leader_intro_audio"))
        cumulative += ins["duration"]

    return sorted(final, key=lambda e: (e.offset, e.media_type, e.track)), insertions


def connect():
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Resolve scripting connection failed")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No current project")
    return resolve, project, project.GetMediaPool()


def unique_timeline_name(project, base: str) -> str:
    names = {
        project.GetTimelineByIndex(i).GetName()
        for i in range(1, project.GetTimelineCount() + 1)
        if project.GetTimelineByIndex(i)
    }
    if base not in names:
        return base
    n = 2
    while f"{base} {n}" in names:
        n += 1
    return f"{base} {n}"


def walk(folder):
    for item in folder.GetClipList() or []:
        yield item
    for sub in folder.GetSubFolderList() or []:
        yield from walk(sub)


def clip_path(item) -> str:
    try:
        return (item.GetClipProperty("File Path") or "").replace("\\", "/").lower()
    except Exception:
        return ""


def import_media(pool, paths: list[Path]) -> dict[str, object]:
    wanted = {str(p.resolve()).replace("\\", "/").lower(): p for p in paths}
    found = {}
    for item in walk(pool.GetRootFolder()):
        p = clip_path(item)
        if p in wanted:
            found[p] = item
    missing = [str(p) for k, p in wanted.items() if k not in found]
    log(f"media wanted={len(wanted)} already={len(found)} missing={len(missing)}")
    for i in range(0, len(missing), 25):
        got = pool.ImportMedia(missing[i : i + 25]) or []
        log(f"  imported media batch {i // 25 + 1}: {len(got)} item(s)")
        for item in got:
            p = clip_path(item)
            if p in wanted:
                found[p] = item
    for item in walk(pool.GetRootFolder()):
        p = clip_path(item)
        if p in wanted:
            found[p] = item
    unresolved = [str(p) for k, p in wanted.items() if k not in found]
    if unresolved:
        raise RuntimeError("Could not import/find media: " + json.dumps(unresolved, indent=2))
    return found


def append_entries(pool, entries: list[Entry], items: dict[str, object], tl_start: int) -> int:
    payload = []
    for entry in entries:
        key = str(entry.path.resolve()).replace("\\", "/").lower()
        payload.append(
            {
                "mediaPoolItem": items[key],
                "startFrame": entry.start,
                "endFrame": entry.start + (entry.source_duration or entry.duration),
                "recordFrame": tl_start + entry.offset,
                "trackIndex": entry.track,
                "mediaType": entry.media_type,
            }
        )
    payload.sort(key=lambda s: (s["recordFrame"], s["trackIndex"], s["mediaType"]))
    placed = 0
    batch_size = 20
    for i in range(0, len(payload), batch_size):
        end = min(i + batch_size, len(payload))
        log(f"  appending {i + 1}-{end}/{len(payload)}")
        got = pool.AppendToTimeline(payload[i:end]) or []
        placed += len(got)
        log(f"  appended {end}/{len(payload)} placed={placed}")
        time.sleep(0.05)
    return placed


def add_markers(timeline, markers: list[B.Marker], insertions: list[dict], gaps: list[dict]) -> None:
    timeline.DeleteMarkersByColor("All")

    def mark(frame: int, color: str, name: str, note: str = "", duration: int = 1) -> None:
        timeline.AddMarker(int(frame), color, name, note, max(1, int(duration)), "")

    mark(0, "Blue", "REF Intro Start", "API rebuild")
    for gap in gaps:
        if gap["status"] == "inserted":
            mark(gap["new_frame"], "Cyan", "Non-boss Battle Gap", gap["label"], gap["pull"])
    for ins in insertions:
        mark(ins["record_frame"], "Purple", f'{ins["leader"]} Leader Intro Start', "2x Gen 1 intro", ins["duration"])
        mark(ins["record_frame"] + ins["duration"], "Purple", f'{ins["leader"]} Leader Intro End', "2x Gen 1 intro")
    for marker in sorted(markers, key=lambda m: m.combined_frame):
        mark(marker.combined_frame, marker.color or "Green", marker.label, marker.note or marker.category)


def source_name(item) -> str:
    mpi = item.GetMediaPoolItem()
    return mpi.GetName() if mpi else item.GetName()


def one_frame_gaps(items) -> list[dict]:
    gaps = []
    ordered = sorted(items, key=lambda c: c.GetStart())
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.GetStart() - prev.GetEnd() == 1:
            gaps.append({"frame": prev.GetEnd(), "prev": prev.GetName(), "next": nxt.GetName()})
    return gaps


def covered_by_intervals(start: int, end: int, intervals: list[tuple[int, int]]) -> bool:
    """Return True when [start, end) is fully covered by dialogue intervals."""
    cursor = start
    for a_start, a_end in sorted(intervals):
        if a_end <= cursor:
            continue
        if a_start > cursor:
            return False
        cursor = max(cursor, a_end)
        if cursor >= end:
            return True
    return cursor >= end


def self_audit(timeline, insertions: list[dict], gaps: list[dict]) -> dict:
    v1 = timeline.GetItemListInTrack("video", 1) or []
    a1 = timeline.GetItemListInTrack("audio", 1) or []
    a2 = timeline.GetItemListInTrack("audio", 2) or []
    a3 = timeline.GetItemListInTrack("audio", 3) or []
    gameplay_v = [c for c in v1 if "part 1.mp4" in source_name(c).lower() or "part 2.mp4" in source_name(c).lower()]
    dialogue_a = [c for c in a1 if "_3.wav" in source_name(c).lower()]
    a_spans = [(c.GetStart(), c.GetEnd()) for c in dialogue_a]
    missing = [c for c in gameplay_v if not covered_by_intervals(c.GetStart(), c.GetEnd(), a_spans)]
    bad_a1 = sorted({source_name(c) for c in a1 if "_3.wav" not in source_name(c).lower()})
    leader_v = [c for c in v1 if source_name(c).lower().endswith("__2x_resolve2.mp4")]
    leader_a = [c for c in a3 if source_name(c).lower().endswith("__2x_resolve2.mp3")]
    gap_map = {
        "v1": one_frame_gaps(v1),
        "a1": one_frame_gaps(a1),
        "a2": one_frame_gaps(a2),
        "a3": one_frame_gaps(a3),
    }
    violations = []
    if missing:
        violations.append("gameplay V1 clips missing aligned A1 dialogue")
    if bad_a1:
        violations.append("A1 contains non-dialogue sources")
    if sum(len(v) for v in gap_map.values()):
        violations.append("one-frame gaps detected")
    if len(leader_v) != len(insertions) or len(leader_a) != len(insertions):
        violations.append("leader intro count mismatch")
    return {
        "timeline": timeline.GetName(),
        "track_counts": {"v1": len(v1), "a1": len(a1), "a2": len(a2), "a3": len(a3)},
        "gameplay_v1": len(gameplay_v),
        "gameplay_a1_dialogue": len(dialogue_a),
        "missing_dialogue_count": len(missing),
        "missing_dialogue_examples": [
            {"name": source_name(c), "start": c.GetStart(), "end": c.GetEnd()} for c in missing[:10]
        ],
        "bad_a1_sources": bad_a1,
        "one_frame_gap_count": sum(len(v) for v in gap_map.values()),
        "one_frame_gaps": gap_map,
        "leader_video_count": len(leader_v),
        "leader_audio_count": len(leader_a),
        "leader_expected_count": len(insertions),
        "leader_clips": [
            {"name": source_name(c), "start": c.GetStart(), "end": c.GetEnd(), "duration": c.GetDuration()}
            for c in leader_v
        ],
        "nonboss_gap_inserted_count": sum(1 for g in gaps if g["status"] == "inserted"),
        "nonboss_gap_events": gaps,
        "marker_count": len(timeline.GetMarkers() or {}),
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply-log-holds",
        action="store_true",
        help="replace auto-editor micro-cuts with continuous logged visual-card spans",
    )
    parser.add_argument(
        "--timeline-base",
        default=None,
        help="base name for the created Resolve timeline",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    part1_audio, part2_audio = load_parts()
    part1_video = part1_audio
    part2_video = part2_audio
    hold_report: dict[str, dict] = {}
    if args.apply_log_holds:
        part1_holds = closed_holds_for_source(PART1_VIDEO, {"intro_stats", "intro_moveset", "intro_card"})
        part2_holds = closed_holds_for_source(PART2_VIDEO, {"post_battle_data_card", "final_tierlist"})
        part1_video, hold_report["part1"] = apply_source_holds_to_clips(part1_audio, part1_holds)
        part2_video, hold_report["part2"] = apply_source_holds_to_clips(part2_audio, part2_holds)
        hold_path = OUT_DIR / "victreebel_log_hold_regions_report.json"
        hold_path.write_text(json.dumps(hold_report, indent=2), encoding="utf-8")
        log(
            "applied log holds: "
            f"part1 {hold_report['part1']['holds_emitted']}/{hold_report['part1']['holds_requested']} "
            f"delta={hold_report['part1']['duration_delta']}f; "
            f"part2 {hold_report['part2']['holds_emitted']}/{hold_report['part2']['holds_requested']} "
            f"delta={hold_report['part2']['duration_delta']}f"
        )
    intro_frames = B.video_duration_frames(B.INTRO_PATH)
    intro_native_frames = native_video_frames(B.INTRO_PATH)
    bgm_frames = media_frames(B.BGM_PATH)
    outro_frames = B.video_duration_frames(B.OUTRO_PATH)
    outro_native_frames = native_video_frames(B.OUTRO_PATH)
    part1_len = max(c.offset + c.duration for c in part1_audio)
    part2_base = intro_frames + part1_len
    markers, timing = B.build_markers(part2_audio, part2_base)

    entries: list[Entry] = [
        Entry(B.INTRO_PATH, 1, 1, 0, 0, intro_frames, "intro", source_duration=intro_native_frames),
        Entry(B.BGM_PATH, 2, 2, 0, 0, min(bgm_frames, intro_frames), "intro_music"),
    ]
    for clip in part1_video:
        entries.append(Entry(clip.src, 1, 1, intro_frames + clip.offset, clip.start, clip.duration, "gameplay", 1))
    for clip in part1_audio:
        entries.append(Entry(clip.dialogue, 2, 1, intro_frames + clip.offset, clip.start, clip.duration, "dialogue", 1))
    for clip in part2_video:
        entries.append(Entry(clip.src, 1, 1, part2_base + clip.offset, clip.start, clip.duration, "gameplay", 2))
    for clip in part2_audio:
        entries.append(Entry(clip.dialogue, 2, 1, part2_base + clip.offset, clip.start, clip.duration, "dialogue", 2))
    end_without_outro = max(part2_base + c.offset + c.duration for c in part2_audio)
    entries.append(Entry(B.OUTRO_PATH, 1, 1, end_without_outro, 0, outro_frames, "outro", source_duration=outro_native_frames))
    entries.append(Entry(B.OUTRO_PATH, 2, 3, end_without_outro, 0, outro_frames, "outro_audio"))

    gaps = add_nonboss_gaps(entries, markers)
    entries, insertions = apply_leader_insertions(entries, markers)
    log(f"prepared entries={len(entries)} leaders={len(insertions)} nonboss_gaps={sum(1 for g in gaps if g['status'] == 'inserted')}")

    resolve, project, pool = connect()
    default_base = STYLE_PASS_TIMELINE_BASE if args.apply_log_holds else TIMELINE_BASE
    name = unique_timeline_name(project, args.timeline_base or default_base)
    timeline = pool.CreateEmptyTimeline(name)
    if not timeline:
        raise RuntimeError("CreateEmptyTimeline failed")
    project.SetCurrentTimeline(timeline)
    while timeline.GetTrackCount("audio") < 3:
        timeline.AddTrack("audio", "stereo")
    timeline.SetSetting("timelineFrameRate", "60")
    timeline.SetSetting("timelinePlaybackFrameRate", "60")
    timeline.SetSetting("timelineResolutionWidth", "1920")
    timeline.SetSetting("timelineResolutionHeight", "1080")
    tl_start = timeline.GetStartFrame()
    paths = sorted({e.path.resolve() for e in entries})
    items = import_media(pool, paths)
    placed = append_entries(pool, entries, items, tl_start)
    add_markers(timeline, markers, insertions, gaps)
    time.sleep(1)

    report = self_audit(timeline, insertions, gaps)
    report["entries_expected"] = len(entries)
    report["placed_count"] = placed
    report["timing"] = timing
    report["log_holds"] = hold_report
    report["ok"] = not report["violations"] and placed == len(entries)
    drt = OUT_DIR / f"{timeline.GetName()}.drt"
    try:
        report["drt_exported"] = bool(timeline.Export(str(drt), resolve.EXPORT_DRT, resolve.EXPORT_NONE))
        report["drt"] = str(drt)
    except Exception as exc:
        report["drt_exported"] = False
        report["drt_error"] = repr(exc)
    report["ok"] = report["ok"] and report["drt_exported"]
    report_path = OUT_DIR / f"{timeline.GetName()}_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(json.dumps(report, indent=2))
    if not report["ok"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
