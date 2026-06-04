from __future__ import annotations

"""Create a corrected timeline with the channel intro at 4x speed.

This is intentionally a timeline rebuild from the current Resolve timeline,
not an in-place trim. It preserves all downstream placements while applying
the timing transform that a 4x intro requires:

  - V1 intro becomes a pre-rendered 400% video-only asset.
  - Everything after the original intro moves left by the saved frames.
  - The first A2 opening BGM clip stays at timeline start but is left-cut by
    the saved frames so the music at the gameplay cut remains aligned.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

import DaVinciResolveScript as dvr


RETIME_DIR = Path("_data") / "cache" / "retimed-intros"
A2_LEFT_CUT_DIR = Path("_data") / "cache" / "a2-left-cuts"
REPORT_DIR = Path("_data") / "qa-reports"
DRT_DIR = Path("_data") / "drt-checkpoints"
TARGET_SPEED = 4.0


def norm_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").lower()


def clip_props(item: Any) -> dict[str, Any]:
    mpi = item.GetMediaPoolItem()
    if not mpi:
        return {}
    try:
        props = mpi.GetClipProperty() or {}
    except Exception:
        return {}
    return props if isinstance(props, dict) else {}


def clip_path(item: Any) -> str:
    return str(clip_props(item).get("File Path") or "")


def clip_fps(item: Any, timeline_fps: float) -> float:
    raw = clip_props(item).get("FPS")
    try:
        fps = float(raw)
    except (TypeError, ValueError):
        return timeline_fps
    return fps if fps > 0 else timeline_fps


def get_markers(item: Any) -> dict[str, dict[str, Any]]:
    try:
        markers = item.GetMarkers() or {}
    except Exception:
        return {}
    return {str(k): dict(v) for k, v in markers.items()}


def source_span_frames(media_type: int, duration: int, source_fps: float, timeline_fps: float) -> int:
    if media_type == 1:
        return max(1, int(round(duration * source_fps / timeline_fps)))
    return duration


def find_timeline(project: Any, name: str) -> Any | None:
    for index in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline and timeline.GetName() == name:
            return timeline
    return None


def unique_timeline_name(project: Any, base: str) -> str:
    names = set()
    for index in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline:
            names.add(timeline.GetName())
    if base not in names:
        return base
    suffix = 2
    while f"{base} {suffix}" in names:
        suffix += 1
    return f"{base} {suffix}"


def find_media_by_path(folder: Any, wanted: Path) -> Any | None:
    wanted_norm = norm_path(wanted.resolve())
    get_clips = getattr(folder, "GetClipList", None)
    clips = get_clips() if callable(get_clips) else []
    for item in clips or []:
        try:
            path = item.GetClipProperty("File Path") or ""
        except Exception:
            path = ""
        if path and norm_path(Path(path).resolve()) == wanted_norm:
            return item
    get_subfolders = getattr(folder, "GetSubFolderList", None)
    subfolders = get_subfolders() if callable(get_subfolders) else []
    for child in subfolders or []:
        found = find_media_by_path(child, wanted)
        if found:
            return found
    return None


def import_media(pool: Any, path: Path) -> Any:
    root = pool.GetRootFolder()
    existing = find_media_by_path(root, path)
    if existing:
        return existing
    imported = pool.ImportMedia([str(path.resolve())]) or []
    if imported:
        return imported[0]
    found = find_media_by_path(root, path)
    if found:
        return found
    raise RuntimeError(f"Could not import media: {path}")


def ensure_tracks(timeline: Any, video_count: int, audio_count: int) -> None:
    while int(timeline.GetTrackCount("video") or 0) < video_count:
        timeline.AddTrack("video")
    while int(timeline.GetTrackCount("audio") or 0) < audio_count:
        timeline.AddTrack("audio", "stereo")


def ensure_retimed_intro(src: Path, timeline_fps: float, target_frames: int) -> Path:
    RETIME_DIR.mkdir(parents=True, exist_ok=True)
    fps_label = int(timeline_fps) if float(timeline_fps).is_integer() else timeline_fps
    out = RETIME_DIR / f"{src.stem}__400pct_{fps_label}fps{src.suffix}"
    if out.exists() and out.stat().st_size > 0 and out.stat().st_mtime >= src.stat().st_mtime:
        return out

    fps_text = str(int(timeline_fps) if float(timeline_fps).is_integer() else timeline_fps)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-filter:v",
        f"setpts=PTS/{TARGET_SPEED:.8g},fps={fps_text}",
        "-frames:v",
        str(target_frames),
        "-r",
        fps_text,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-write_tmcd",
        "0",
        "-dn",
        "-sn",
        "-an",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not out.exists():
        tail = "\n".join(proc.stderr.splitlines()[-8:])
        raise RuntimeError(f"ffmpeg failed while retiming intro:\n{tail}")
    return out


def safe_stem(text: str, limit: int = 90) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", text).strip("_")
    return cleaned[:limit] or "clip"


def render_a2_left_cut(source: Path, source_start: int, duration: int, timeline_fps: float) -> Path:
    A2_LEFT_CUT_DIR.mkdir(parents=True, exist_ok=True)
    out = A2_LEFT_CUT_DIR / (
        f"{safe_stem(source.stem)}__leftcut_s{source_start}_d{duration}.wav"
    )
    if out.exists() and out.stat().st_size > 0 and out.stat().st_mtime >= source.stat().st_mtime:
        return out

    start_sec = source_start / timeline_fps
    duration_sec = duration / timeline_fps
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start_sec:.9f}",
        "-i",
        str(source),
        "-t",
        f"{duration_sec:.9f}",
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "pcm_s16le",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 or not out.exists():
        tail = "\n".join(proc.stderr.splitlines()[-8:])
        raise RuntimeError(f"ffmpeg failed while rendering A2 left-cut BGM:\n{tail}")
    return out


def collect_clips(timeline: Any, timeline_fps: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index = 0
    for track_type, media_type in (("video", 1), ("audio", 2)):
        for track in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            for item in sorted(timeline.GetItemListInTrack(track_type, track) or [], key=lambda c: c.GetStart()):
                index += 1
                mpi = item.GetMediaPoolItem()
                if not mpi:
                    raise RuntimeError(f"Timeline item has no MediaPoolItem: {item.GetName()!r}")
                rows.append(
                    {
                        "index": index,
                        "item": item,
                        "mpi": mpi,
                        "media_type": media_type,
                        "track": track,
                        "name": item.GetName() or "",
                        "path": clip_path(item),
                        "old_start": int(item.GetStart()),
                        "old_end": int(item.GetEnd()),
                        "old_duration": int(item.GetDuration()),
                        "old_left": int(item.GetLeftOffset()),
                        "color": item.GetClipColor() or "",
                        "source_fps": clip_fps(item, timeline_fps),
                        "markers": get_markers(item),
                    }
                )
    return rows


def marker_payload(marker: dict[str, Any]) -> tuple[str, str, str, int, str]:
    return (
        marker.get("color") or "Blue",
        marker.get("name") or "",
        marker.get("note") or "",
        int(marker.get("duration") or 1),
        marker.get("customData") or "",
    )


def add_clip_markers(item: Any, markers: dict[str, dict[str, Any]], new_left: int, source_end: int) -> int:
    added = 0
    for frame_key, marker in markers.items():
        try:
            frame_id = int(float(frame_key))
        except ValueError:
            continue
        if frame_id < new_left or frame_id >= source_end:
            continue
        color, name, note, duration, custom_data = marker_payload(marker)
        if item.AddMarker(frame_id, color, name, note, duration, custom_data):
            added += 1
    return added


def add_timeline_markers(
    source_markers: dict[Any, dict[str, Any]],
    new_timeline: Any,
    old_intro_duration: int,
    new_intro_duration: int,
    delta: int,
) -> dict[str, int]:
    added = 0
    dropped_inside_intro_tail = 0
    for rel_key, marker in source_markers.items():
        old_rel = int(float(rel_key))
        if old_rel >= old_intro_duration:
            new_rel = old_rel - delta
        elif old_rel > new_intro_duration:
            dropped_inside_intro_tail += 1
            continue
        else:
            new_rel = old_rel
        color, name, note, duration, custom_data = marker_payload(marker)
        if new_timeline.AddMarker(new_rel, color, name, note, duration, custom_data):
            added += 1
    return {"added": added, "dropped_inside_intro_tail": dropped_inside_intro_tail}


def save_project(resolve: Any, project: Any) -> bool:
    save = getattr(project, "Save", None)
    if callable(save):
        try:
            if save():
                return True
        except Exception:
            pass
    try:
        return bool(resolve.GetProjectManager().SaveProject())
    except Exception:
        return False


def build_plans(
    rows: list[dict[str, Any]],
    *,
    intro_row: dict[str, Any],
    old_timeline_start: int,
    new_timeline_start: int,
    old_intro_duration: int,
    delta: int,
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for row in rows:
        if row["index"] == intro_row["index"]:
            continue

        old_rel_start = row["old_start"] - old_timeline_start
        old_rel_end = row["old_end"] - old_timeline_start
        role = "shifted"
        new_left = row["old_left"]
        new_duration = row["old_duration"]

        if old_rel_start >= old_intro_duration:
            new_start = new_timeline_start + old_rel_start - delta
        elif row["media_type"] == 2 and row["track"] == 2 and old_rel_start == 0 and old_rel_end > old_intro_duration:
            role = "a2_opening_left_cut"
            new_start = new_timeline_start
            new_left = row["old_left"] + delta
            new_duration = row["old_duration"] - delta
            if new_duration <= 0:
                raise RuntimeError("Opening A2 clip is shorter than intro delta; cannot left-cut safely")
        elif old_rel_end <= old_intro_duration:
            role = "dropped_inside_original_intro"
            continue
        else:
            raise RuntimeError(
                "Unhandled clip crossing the removed intro tail: "
                f'{row["name"]!r} track={row["track"]} old_rel=[{old_rel_start},{old_rel_end})'
            )

        plans.append({**row, "new_start": new_start, "new_left": new_left, "new_duration": new_duration, "role": role})
    return sorted(plans, key=lambda row: (row["new_start"], row["track"], row["media_type"], row["index"]))


def append_plans(pool: Any, plans: list[dict[str, Any]], timeline_fps: float) -> dict[str, int]:
    placed = 0
    colored = 0
    clip_markers_added = 0
    for start in range(0, len(plans), 50):
        chunk = plans[start : start + 50]
        payload = []
        for plan in chunk:
            source_span = source_span_frames(
                plan["media_type"],
                plan["new_duration"],
                plan["source_fps"],
                timeline_fps,
            )
            payload.append(
                {
                    "mediaPoolItem": plan["mpi"],
                    "startFrame": plan["new_left"],
                    "endFrame": plan["new_left"] + source_span,
                    "recordFrame": plan["new_start"],
                    "trackIndex": plan["track"],
                    "mediaType": plan["media_type"],
                }
            )
            plan["new_source_end"] = plan["new_left"] + source_span

        got = pool.AppendToTimeline(payload) or []
        if len(got) != len(chunk):
            raise RuntimeError(f"AppendToTimeline placed {len(got)}/{len(chunk)} clips for chunk starting {start}")
        placed += len(got)

        for plan, item in zip(chunk, got):
            if plan["color"] and item.SetClipColor(plan["color"]):
                colored += 1
            clip_markers_added += add_clip_markers(
                item,
                plan["markers"],
                plan["new_left"],
                plan["new_source_end"],
            )
    return {"placed": placed, "colored": colored, "clip_markers_added": clip_markers_added}


def prepare_rendered_left_cut_a2(pool: Any, plans: list[dict[str, Any]], timeline_fps: float) -> dict[str, Any]:
    rendered: list[dict[str, Any]] = []
    for plan in plans:
        if plan["role"] != "a2_opening_left_cut":
            continue
        original_path = Path(plan["path"])
        original_source_start = int(plan["new_left"])
        rendered_path = render_a2_left_cut(
            original_path,
            original_source_start,
            int(plan["new_duration"]),
            timeline_fps,
        )
        plan["mpi"] = import_media(pool, rendered_path)
        plan["path"] = str(rendered_path)
        plan["name"] = rendered_path.name
        plan["source_fps"] = timeline_fps
        plan["new_left"] = 0
        plan["markers"] = {}
        plan["rendered_left_cut_source_start"] = original_source_start
        plan["rendered_left_cut_path"] = str(rendered_path)
        rendered.append(
            {
                "original_path": str(original_path),
                "rendered_path": str(rendered_path),
                "source_start": original_source_start,
                "duration": int(plan["new_duration"]),
            }
        )
    return {"count": len(rendered), "items": rendered}


def verify(new_timeline: Any, old_report: dict[str, Any], delta: int) -> dict[str, Any]:
    start = int(new_timeline.GetStartFrame())
    v1 = sorted(new_timeline.GetItemListInTrack("video", 1) or [], key=lambda c: c.GetStart())
    a2 = sorted(new_timeline.GetItemListInTrack("audio", 2) or [], key=lambda c: c.GetStart())
    intro = v1[0] if v1 else None
    first_gameplay = v1[1] if len(v1) > 1 else None
    first_a2 = a2[0] if a2 else None
    second_a2 = a2[1] if len(a2) > 1 else None

    intro_duration = int(intro.GetDuration()) if intro else 0
    first_a2_left = int(first_a2.GetLeftOffset()) if first_a2 else None
    rendered_left_cut = bool(old_report.get("a2_left_cut_rendered"))
    expected_a2_left = 0 if rendered_left_cut else (
        old_report["old_first_a2_left"] + delta if old_report.get("old_first_a2_left") is not None else None
    )
    checks = {
        "intro_is_4x_length": abs(intro_duration - old_report["old_intro_duration"] / TARGET_SPEED) <= 1,
        "gameplay_starts_after_intro": bool(first_gameplay and int(first_gameplay.GetStart()) == start + intro_duration),
        "a2_starts_at_timeline_start": bool(first_a2 and int(first_a2.GetStart()) == start),
        "a2_left_cut_matches_delta": first_a2_left == expected_a2_left,
        "a2_rendered_left_cut_present": (
            not rendered_left_cut
            or bool(first_a2 and f"leftcut_s{delta}" in (first_a2.GetName() or ""))
        ),
        "a2_first_second_contiguous": bool(first_a2 and second_a2 and int(first_a2.GetEnd()) == int(second_a2.GetStart())),
        "timeline_end_shifted": int(new_timeline.GetEndFrame()) == old_report["old_timeline_end"] - delta,
    }
    return {
        "timeline": new_timeline.GetName(),
        "timeline_start": start,
        "timeline_end": int(new_timeline.GetEndFrame()),
        "intro_name": intro.GetName() if intro else None,
        "intro_path": clip_path(intro) if intro else None,
        "intro_duration": intro_duration,
        "intro_duration_sec": intro_duration / old_report["timeline_fps"],
        "first_gameplay_start": int(first_gameplay.GetStart()) if first_gameplay else None,
        "first_a2_name": first_a2.GetName() if first_a2 else None,
        "first_a2_start": int(first_a2.GetStart()) if first_a2 else None,
        "first_a2_end": int(first_a2.GetEnd()) if first_a2 else None,
        "first_a2_left": first_a2_left,
        "checks": checks,
        "ok": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-timeline", default=None)
    parser.add_argument("--timeline-base", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Resolve scripting connection failed")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No current Resolve project")
    if args.source_timeline:
        source = find_timeline(project, args.source_timeline)
        if not source:
            raise RuntimeError(f"Timeline not found: {args.source_timeline}")
        project.SetCurrentTimeline(source)
    else:
        source = project.GetCurrentTimeline()
    if not source:
        raise RuntimeError("No current timeline")

    pool = project.GetMediaPool()
    timeline_fps = float(project.GetSetting("timelineFrameRate"))
    old_timeline_start = int(source.GetStartFrame())
    rows = collect_clips(source, timeline_fps)
    v1 = [row for row in rows if row["media_type"] == 1 and row["track"] == 1]
    a2 = [row for row in rows if row["media_type"] == 2 and row["track"] == 2]
    if len(v1) < 2:
        raise RuntimeError("Expected at least intro + gameplay on V1")
    intro_row = v1[0]
    if "blue version intro" not in intro_row["name"].lower() and "blue version intro" not in Path(intro_row["path"]).name.lower():
        raise RuntimeError(f"First V1 clip does not look like the Blue intro: {intro_row['name']!r}")
    if not a2:
        raise RuntimeError("A2 is empty; cannot verify or repair opening BGM")

    old_intro_duration = intro_row["old_duration"]
    estimated_new_intro_duration = int(round(old_intro_duration / TARGET_SPEED))
    estimated_delta = old_intro_duration - estimated_new_intro_duration
    old_report = {
        "project": project.GetName(),
        "source_timeline": source.GetName(),
        "current_page": resolve.GetCurrentPage(),
        "timeline_fps": timeline_fps,
        "old_timeline_start": old_timeline_start,
        "old_timeline_end": int(source.GetEndFrame()),
        "old_intro_name": intro_row["name"],
        "old_intro_path": intro_row["path"],
        "old_intro_duration": old_intro_duration,
        "old_intro_duration_sec": old_intro_duration / timeline_fps,
        "estimated_new_intro_duration": estimated_new_intro_duration,
        "estimated_new_intro_duration_sec": estimated_new_intro_duration / timeline_fps,
        "estimated_delta": estimated_delta,
        "old_first_a2_name": a2[0]["name"],
        "old_first_a2_left": a2[0]["old_left"],
        "old_first_a2_start": a2[0]["old_start"],
        "old_first_a2_end": a2[0]["old_end"],
        "clip_count": len(rows),
        "timeline_marker_count": len(source.GetMarkers() or {}),
    }
    print(json.dumps({"phase": "analysis", **old_report}, indent=2))

    if args.dry_run:
        return 0

    retimed_path = ensure_retimed_intro(
        Path(intro_row["path"]),
        timeline_fps,
        estimated_new_intro_duration,
    )
    retimed_mpi = import_media(pool, retimed_path)

    timeline_base = args.timeline_base or f"{source.GetName()} intro 4x bgm left cut"
    new_name = unique_timeline_name(project, timeline_base)
    new_timeline = pool.CreateEmptyTimeline(new_name)
    if not new_timeline:
        raise RuntimeError(f"CreateEmptyTimeline failed for {new_name!r}")
    project.SetCurrentTimeline(new_timeline)
    new_timeline.SetSetting("timelineFrameRate", str(int(timeline_fps) if timeline_fps.is_integer() else timeline_fps))
    new_timeline.SetSetting("timelinePlaybackFrameRate", str(int(timeline_fps) if timeline_fps.is_integer() else timeline_fps))
    new_timeline.SetSetting("timelineResolutionWidth", project.GetSetting("timelineResolutionWidth"))
    new_timeline.SetSetting("timelineResolutionHeight", project.GetSetting("timelineResolutionHeight"))
    ensure_tracks(new_timeline, int(source.GetTrackCount("video") or 0), int(source.GetTrackCount("audio") or 0))
    new_timeline_start = int(new_timeline.GetStartFrame())

    intro_placed = pool.AppendToTimeline(
        [
            {
                "mediaPoolItem": retimed_mpi,
                "recordFrame": new_timeline_start,
                "trackIndex": 1,
                "mediaType": 1,
            }
        ]
    ) or []
    if len(intro_placed) != 1:
        raise RuntimeError("Retimed intro was not placed")
    new_intro = intro_placed[0]
    if intro_row["color"]:
        new_intro.SetClipColor(intro_row["color"])
    new_intro_duration = int(new_intro.GetDuration())
    delta = old_intro_duration - new_intro_duration
    if delta <= 0:
        raise RuntimeError(f"Retimed intro duration did not shrink the intro: old={old_intro_duration} new={new_intro_duration}")

    plans = build_plans(
        rows,
        intro_row=intro_row,
        old_timeline_start=old_timeline_start,
        new_timeline_start=new_timeline_start,
        old_intro_duration=old_intro_duration,
        delta=delta,
    )
    left_cut_render_report = prepare_rendered_left_cut_a2(pool, plans, timeline_fps)
    old_report["a2_left_cut_rendered"] = left_cut_render_report["count"] > 0
    append_report = append_plans(pool, plans, timeline_fps)
    marker_report = add_timeline_markers(
        source.GetMarkers() or {},
        new_timeline,
        old_intro_duration,
        new_intro_duration,
        delta,
    )
    time.sleep(1)

    verify_report = verify(new_timeline, old_report, delta)
    DRT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\-]+", "_", new_timeline.GetName()).strip("_")
    drt_path = DRT_DIR / f"{safe_name}.drt"
    try:
        drt_exported = bool(new_timeline.Export(str(drt_path), resolve.EXPORT_DRT, resolve.EXPORT_NONE))
    except Exception as exc:
        drt_exported = False
        verify_report["drt_error"] = repr(exc)
    save_ok = save_project(resolve, project)

    report = {
        **old_report,
        "new_timeline": new_timeline.GetName(),
        "retimed_intro_path": str(retimed_path),
        "new_intro_duration": new_intro_duration,
        "new_intro_duration_sec": new_intro_duration / timeline_fps,
        "actual_delta": delta,
        "actual_delta_sec": delta / timeline_fps,
        "plans": {
            "total": len(plans),
            "a2_opening_left_cut": sum(1 for plan in plans if plan["role"] == "a2_opening_left_cut"),
            "shifted": sum(1 for plan in plans if plan["role"] == "shifted"),
        },
        "a2_left_cut_render": left_cut_render_report,
        "append": append_report,
        "markers": marker_report,
        "verify": verify_report,
        "drt": str(drt_path),
        "drt_exported": drt_exported,
        "project_save_ok": save_ok,
    }
    report["ok"] = verify_report["ok"] and drt_exported and save_ok

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{safe_name}_intro_4x_bgm_left_cut_report.json"
    report["report"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
