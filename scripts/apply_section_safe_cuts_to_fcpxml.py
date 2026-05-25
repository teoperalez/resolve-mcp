"""
Apply section-safe cut metadata to an FCPXML.

This deletes only exact FCPXML timeline-position groups listed in
*_SECTION_SAFE_CUTS.json. It never trims or splits a section.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import apply_cuts_to_fcpxml as F


def _delete_sections(xml: str, delete_offsets: set[int],
                     keep_linked_audio: bool = False, den: int = 60) -> tuple[str, dict]:
    clips = F.parse_spine_clips(xml)
    if not clips:
        return xml, {"counts": {"deleted": 0, "kept": 0}, "removed_tl_ranges_frames": []}

    video_refs = F.find_video_refs(xml) or {clips[0]["ref"]}
    if not keep_linked_audio:
        before = len(clips)
        clips = [c for c in clips if c["ref"] in video_refs]
        print(f"  Filtered linked-audio refs: kept {len(clips)}/{before} clips "
              f"(video refs: {sorted(video_refs)})")

    pos_groups: dict[int, list[dict]] = {}
    for c in clips:
        pos_groups.setdefault(c["offset"], []).append(c)
    positions = sorted(pos_groups)

    refs_in_order: list[str] = []
    seen = set()
    for c in clips:
        if c["ref"] not in seen:
            seen.add(c["ref"])
            refs_in_order.append(c["ref"])

    new_clips: list[dict] = []
    removed_tl_ranges: list[tuple[int, int]] = []
    cumulative_shift = 0
    n_deleted = n_kept = 0

    for pos in positions:
        group = pos_groups[pos]
        dur = group[0]["duration"]
        if pos in delete_offsets:
            removed_tl_ranges.append((pos, pos + dur))
            cumulative_shift += dur
            n_deleted += 1
            continue
        new_off = pos - cumulative_shift
        for c in group:
            new_clips.append({**c, "offset": new_off})
        n_kept += 1

    print(f"  Operations: keep={n_kept} delete={n_deleted} trim_start=0 trim_end=0 split/multi=0")
    print(f"  Total timeline frames removed: {cumulative_shift} ({cumulative_shift/den:.2f}s)")

    indent = "\t" * 8
    lines = []
    new_clips.sort(key=lambda c: (
        c["offset"],
        refs_in_order.index(c["ref"]) if c["ref"] in refs_in_order else 999,
    ))
    for c in new_clips:
        attrs = dict(c["_attrs"])
        attrs["offset"] = F.fmt_rational(c["offset"], den)
        attrs["duration"] = F.fmt_rational(c["duration"], den)
        attrs["start"] = F.fmt_rational(c["start"], den)
        ordered = []
        for k in ("name", "ref", "offset", "duration", "start", "tcFormat"):
            if k in attrs:
                ordered.append(k)
        for k in attrs:
            if k not in ordered:
                ordered.append(k)
        pairs = []
        for k in ordered:
            v = attrs[k]
            if k == "tcFormat" and v == "":
                continue
            pairs.append(f'{k}="{v}"')
        lines.append(f'{indent}<asset-clip {" ".join(pairs)} />')

    new_spine_body = "\n" + "\n".join(lines) + "\n" + "\t" * 5
    new_xml = re.sub(
        r"(<spine\b[^>]*>)([\s\S]*?)(</spine>)",
        lambda m: m.group(1) + new_spine_body + m.group(3),
        xml,
        count=1,
    )

    def shift_for_tl(tl_n: int) -> int | None:
        shift = 0
        for rs, re_ in removed_tl_ranges:
            if rs <= tl_n < re_:
                return None
            if tl_n >= re_:
                shift += re_ - rs
        return tl_n - shift

    marker_pat = re.compile(r"<marker\s+([^/]+?)/>", re.DOTALL)

    def remap_marker(m: re.Match) -> str:
        a = F.parse_attrs(m.group(1))
        try:
            tl_n, _ = F.parse_rational(a.get("start", "0s"))
        except ValueError:
            return m.group(0)
        new_tl = shift_for_tl(tl_n)
        if new_tl is None:
            return ""
        a["start"] = F.fmt_rational(new_tl, den)
        out = " ".join(f'{k}="{v}"' for k, v in a.items())
        return f"<marker {out} />"

    new_xml = marker_pat.sub(remap_marker, new_xml)

    return new_xml, {
        "removed_tl_ranges_frames": [{"start": s, "end": e} for s, e in removed_tl_ranges],
        "total_tl_frames_removed": cumulative_shift,
        "den": den,
        "counts": {"keep": n_kept, "delete": n_deleted,
                   "trim_start": 0, "trim_end": 0, "split_multi": 0},
    }


def _with_project_label(xml: str, suffix: str) -> str:
    return re.sub(
        r'(<project\s+name=")([^"]*)(")',
        lambda m: f"{m.group(1)}{m.group(2)} {suffix}{m.group(3)}",
        xml,
        count=1,
    )


def _shift_marker(frame: int, removed_ranges: list[dict]) -> int | None:
    shift = 0
    for r in removed_ranges:
        rs, re_ = int(r["start"]), int(r["end"])
        if rs <= frame < re_:
            return None
        if frame >= re_:
            shift += re_ - rs
    return frame - shift


def _capture_current_ruler_markers() -> list[dict]:
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        return []
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        return []
    markers = []
    for frame, marker in sorted((timeline.GetMarkers() or {}).items()):
        markers.append({
            "frame": int(frame),
            "color": marker.get("color", "Blue"),
            "name": marker.get("name", ""),
            "note": marker.get("note", ""),
            "duration": marker.get("duration", 1),
            "customData": marker.get("customData", ""),
        })
    return markers


def _capture_current_clip_colors() -> list[dict]:
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        return []
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        return []
    colors = []
    for kind in ("video", "audio", "subtitle"):
        try:
            count = timeline.GetTrackCount(kind)
        except Exception:
            count = 0
        for track in range(1, count + 1):
            for clip in timeline.GetItemListInTrack(kind, track) or []:
                color = clip.GetClipColor() or ""
                if not color:
                    continue
                colors.append({
                    "kind": kind,
                    "track": track,
                    "name": clip.GetName() or "",
                    "src_left": clip.GetLeftOffset(),
                    "duration": clip.GetDuration(),
                    "color": color,
                })
    return colors


def _reapply_markers(timeline_name: str, source_markers: list[dict],
                     replay: dict) -> int:
    if not source_markers:
        return 0
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        return 0
    project = resolve.GetProjectManager().GetCurrentProject()
    target = None
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t and (t.GetName() or "") == timeline_name:
            target = t
            break
    if target is None:
        return 0

    project.SetCurrentTimeline(target)
    placed = 0
    removed_ranges = replay.get("removed_tl_ranges_frames", [])
    for marker in source_markers:
        new_frame = _shift_marker(marker["frame"], removed_ranges)
        if new_frame is None:
            continue
        for nudge in range(0, 10):
            if target.AddMarker(new_frame + nudge, marker["color"],
                                marker["name"], marker["note"],
                                marker["duration"], marker["customData"]):
                placed += 1
                break
    return placed


def _reapply_clip_colors(timeline_name: str, source_colors: list[dict]) -> int:
    if not source_colors:
        return 0
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        return 0
    project = resolve.GetProjectManager().GetCurrentProject()
    target = None
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t and (t.GetName() or "") == timeline_name:
            target = t
            break
    if target is None:
        return 0

    project.SetCurrentTimeline(target)
    wanted = {}
    for rec in source_colors:
        key = (rec["kind"], rec["track"], rec["name"], rec["src_left"], rec["duration"])
        wanted.setdefault(key, []).append(rec["color"])

    applied = 0
    for kind in ("video", "audio", "subtitle"):
        try:
            count = target.GetTrackCount(kind)
        except Exception:
            count = 0
        for track in range(1, count + 1):
            for clip in target.GetItemListInTrack(kind, track) or []:
                key = (kind, track, clip.GetName() or "",
                       clip.GetLeftOffset(), clip.GetDuration())
                colors = wanted.get(key)
                if not colors:
                    continue
                color = colors.pop(0)
                if clip.SetClipColor(color):
                    applied += 1
    return applied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="Input FCPXML")
    ap.add_argument("--safe-cuts", required=True, help="*_SECTION_SAFE_CUTS.json")
    ap.add_argument("-o", "--output-dir", default=None)
    ap.add_argument("--import-to-resolve", action="store_true")
    ap.add_argument("--keep-linked-audio", action="store_true")
    args = ap.parse_args()

    in_path = Path(args.input).resolve()
    safe_path = Path(args.safe_cuts).resolve()
    out_dir = Path(args.output_dir).resolve() if args.output_dir else in_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    safe = json.loads(safe_path.read_text(encoding="utf-8"))
    deletes = safe.get("safe_section_deletes", [])
    high_offsets = {d["section_offset"] for d in deletes if d.get("confidence") == "high"}
    all_offsets = {d["section_offset"] for d in deletes if d.get("confidence") in ("high", "medium")}

    source_markers = _capture_current_ruler_markers() if args.import_to_resolve else []
    source_colors = _capture_current_clip_colors() if args.import_to_resolve else []
    if source_markers:
        print(f"Source ruler markers captured for reapply: {len(source_markers)}")
    if source_colors:
        print(f"Source clip colors captured for reapply: {len(source_colors)}")

    print(f"Safe section deletes: {len(deletes)} "
          f"({len(high_offsets)} high, {len(all_offsets) - len(high_offsets)} medium)")

    xml = in_path.read_text(encoding="utf-8")
    stem = in_path.stem
    high_out = out_dir / f"{stem}_SECTION_SAFE_CUTS_HIGH.fcpxml"
    all_out = out_dir / f"{stem}_SECTION_SAFE_CUTS_ALL.fcpxml"

    print("\n-- HIGH-only section deletes --")
    high_xml, high_replay = _delete_sections(
        _with_project_label(xml, "(cuts: high)"),
        high_offsets,
        keep_linked_audio=args.keep_linked_audio,
    )
    high_out.write_text(high_xml, encoding="utf-8")
    print(f"Wrote: {high_out}")

    print("\n-- ALL section deletes --")
    all_xml, all_replay = _delete_sections(
        _with_project_label(xml, "(cuts: all)"),
        all_offsets,
        keep_linked_audio=args.keep_linked_audio,
    )
    all_out.write_text(all_xml, encoding="utf-8")
    print(f"Wrote: {all_out}")

    replay_path = out_dir / f"{stem}_section_safe_cuts_replay.json"
    replay_path.write_text(json.dumps({
        "source_fcpxml": str(in_path),
        "safe_cuts": str(safe_path),
        "high_only": high_replay,
        "all_cuts": all_replay,
        "manual_review_sections": safe.get("manual_review_sections", []),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Replay metadata: {replay_path}")

    if args.import_to_resolve:
        print("\n-- Importing into Resolve --")
        ok_high, name_high = F.import_to_resolve(high_out, "(cuts: high)")
        if ok_high and name_high:
            placed = _reapply_markers(name_high, source_markers, high_replay)
            print(f"  [(cuts: high)] Reapplied ruler markers: {placed}/{len(source_markers)}")
            colored = _reapply_clip_colors(name_high, source_colors)
            print(f"  [(cuts: high)] Reapplied clip colors: {colored}/{len(source_colors)}")
        ok_all, name_all = F.import_to_resolve(all_out, "(cuts: all)")
        if ok_all and name_all:
            placed = _reapply_markers(name_all, source_markers, all_replay)
            print(f"  [(cuts: all)] Reapplied ruler markers: {placed}/{len(source_markers)}")
            colored = _reapply_clip_colors(name_all, source_colors)
            print(f"  [(cuts: all)] Reapplied clip colors: {colored}/{len(source_colors)}")
        F.set_current_timeline_by_name("(cuts: all)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
