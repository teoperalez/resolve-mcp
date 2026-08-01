from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


FPS = 60
ROOT = Path(r"F:\Roxanne Minimum\CODEx\full_track_review\narrative_audit")
RULE_DIR = ROOT / "visual_marker_review" / "v1_clip_start_rule"
PLAN_PATH = ROOT / "reduced_a1_gap_plan.json"
FEATURES_PATH = RULE_DIR / "v1_clip_start_features.json"
VISUAL_MARKERS_PATH = RULE_DIR / "v1_clip_start_marker_plan.json"
OUT_DIR = ROOT / "finished_timeline"
STILLS_DIR = OUT_DIR / "holds"
HOLD_VIDEO_DIR = OUT_DIR / "hold_videos"
BUILD_REPORT = OUT_DIR / "finished_timeline_build_report.json"
VERIFY_REPORT = OUT_DIR / "finished_timeline_verify_report.json"

SOURCE_TIMELINE_NAME = "Roxanne Minimum Wrap Up - reduced A1 gaps"
OUTPUT_TIMELINE_BASE = "Roxanne Minimum Final Review - finished timeline"

INTRO_ASSET = Path(r"F:\Programming\RSENewLayout\RSE Short intro.mp4")
OUTRO_ASSET = Path(r"F:\RSE Assets\RSE Assets.mp4")
BGM_DIR = Path(r"F:\Programming\RSENewLayout\audio\bgm")

INTRO_MARKER_COLOR = "Blue"
POKEMON_MARKER_COLOR = "Pink"
RECAP_MARKER_COLOR = "Cyan"
OUTRO_MARKER_COLOR = "Purple"


@dataclass(frozen=True)
class ClipSpec:
    item: object
    name: str
    start: int
    end: int
    duration: int
    left: int
    media_type: int
    track_index: int
    clip_color: str


@dataclass(frozen=True)
class HoldPlan:
    key: str
    label: str
    start: int
    end: int
    source_clip_index: int
    source_sec: float
    kind: str

    @property
    def duration(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class V1Segment:
    item: object
    name: str
    start: int
    end: int
    left: int
    kind: str
    hold_key: str
    clip_color: str

    @property
    def duration(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class MediaTiming:
    source_fps: float
    timeline_fps: float
    duration_seconds: float
    source_frames: int
    timeline_frames: int


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm_path(path: Path | str) -> str:
    return str(Path(path).resolve()).replace("\\", "/").lower()


def walk(folder):
    for item in folder.GetClipList() or []:
        yield item
    for sub in folder.GetSubFolderList() or []:
        yield from walk(sub)


def clip_path(item) -> str:
    try:
        props = item.GetClipProperty() or {}
        raw = props.get("File Path") or props.get("File Name") or ""
        if raw and (":" in raw or raw.startswith("\\\\")):
            return norm_path(raw)
    except Exception:
        pass
    return ""


def find_or_import_media(pool, paths: list[Path]) -> dict[str, object]:
    wanted = {norm_path(path): path for path in paths}
    found: dict[str, object] = {}
    for item in walk(pool.GetRootFolder()):
        key = clip_path(item)
        if key in wanted:
            found[key] = item

    missing = [str(path) for key, path in wanted.items() if key not in found]
    for index in range(0, len(missing), 25):
        batch = missing[index:index + 25]
        if not batch:
            continue
        imported = pool.ImportMedia(batch) or []
        print(f"Imported media batch {index // 25 + 1}: {len(imported)}/{len(batch)}", flush=True)
        for item in imported:
            key = clip_path(item)
            if key in wanted:
                found[key] = item

    for item in walk(pool.GetRootFolder()):
        key = clip_path(item)
        if key in wanted:
            found[key] = item

    unresolved = [str(path) for key, path in wanted.items() if key not in found]
    if unresolved:
        raise RuntimeError("Could not find/import media:\n" + "\n".join(unresolved))
    return found


def media_timing(item, timeline_fps: float) -> MediaTiming:
    props = item.GetClipProperty() or {}
    clip_fps = timeline_fps
    for key in ("FPS", "Video Frame Rate", "Frame Rate"):
        try:
            value = float(props.get(key) or 0)
            if value > 0:
                clip_fps = value
                break
        except (TypeError, ValueError):
            pass

    for key in ("Video Duration", "Audio Duration", "Duration"):
        raw = (props.get(key) or "").strip()
        if not raw:
            continue
        parts = raw.replace(";", ":").split(":")
        if len(parts) == 4:
            try:
                hours, minutes, seconds, frames = (int(part) for part in parts)
            except ValueError:
                continue
            source_frames = round((hours * 3600 + minutes * 60 + seconds) * clip_fps + frames)
            total_sec = source_frames / clip_fps
            frames_tl = round(total_sec * timeline_fps)
            if source_frames > 0 and frames_tl > 0:
                return MediaTiming(
                    source_fps=clip_fps,
                    timeline_fps=timeline_fps,
                    duration_seconds=total_sec,
                    source_frames=source_frames,
                    timeline_frames=frames_tl,
                )
        try:
            native = int(raw)
            if native > 0:
                total_sec = native / clip_fps
                return MediaTiming(
                    source_fps=clip_fps,
                    timeline_fps=timeline_fps,
                    duration_seconds=total_sec,
                    source_frames=native,
                    timeline_frames=max(1, round(total_sec * timeline_fps)),
                )
        except (TypeError, ValueError):
            pass

    for key in ("Frames", "Video Frames", "Audio Frames"):
        try:
            native = int(props.get(key) or 0)
            if native > 0:
                total_sec = native / clip_fps
                return MediaTiming(
                    source_fps=clip_fps,
                    timeline_fps=timeline_fps,
                    duration_seconds=total_sec,
                    source_frames=native,
                    timeline_frames=max(1, round(total_sec * timeline_fps)),
                )
        except (TypeError, ValueError):
            pass

    raise RuntimeError(f"Could not determine media duration for {item.GetName()!r}: {props}")


def media_duration_tl_frames(item, timeline_fps: float) -> int:
    return media_timing(item, timeline_fps).timeline_frames


def unique_timeline_name(project, base: str) -> str:
    existing = set()
    for index in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline:
            existing.add(timeline.GetName())
    name = base
    n = 2
    while name in existing:
        name = f"{base} {n}"
        n += 1
    return name


def find_timeline(project, name: str):
    for index in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline and timeline.GetName() == name:
            return timeline
    return None


def ensure_tracks(timeline, video_tracks: int, audio_tracks: int) -> None:
    while int(timeline.GetTrackCount("video") or 0) < video_tracks:
        timeline.AddTrack("video")
    while int(timeline.GetTrackCount("audio") or 0) < audio_tracks:
        timeline.AddTrack("audio", "stereo")


def collect_track_specs(timeline, track_type: str, track_index: int, media_type: int) -> list[ClipSpec]:
    specs = []
    for item in sorted(timeline.GetItemListInTrack(track_type, track_index) or [], key=lambda clip: clip.GetStart()):
        mpi = item.GetMediaPoolItem()
        if not mpi:
            raise RuntimeError(f"{track_type}{track_index} item {item.GetName()!r} has no MediaPoolItem")
        start = int(item.GetStart())
        duration = int(item.GetDuration())
        specs.append(
            ClipSpec(
                item=mpi,
                name=item.GetName() or "",
                start=start,
                end=start + duration,
                duration=duration,
                left=int(item.GetLeftOffset()),
                media_type=media_type,
                track_index=track_index,
                clip_color=item.GetClipColor() or "",
            )
        )
    return specs


def append_payload(pool, payload: list[dict], label: str, batch_size: int = 75) -> list[object]:
    placed: list[object] = []
    for index in range(0, len(payload), batch_size):
        batch = payload[index:index + batch_size]
        got = pool.AppendToTimeline(batch) or []
        placed.extend(got)
        print(f"{label}: appended {min(index + batch_size, len(payload))}/{len(payload)}; placed={len(placed)}", flush=True)
    return placed


def set_clip_colors(items: list[object], colors: list[str]) -> int:
    changed = 0
    for item, color in zip(items, colors):
        if not color:
            continue
        try:
            if item.SetClipColor(color):
                changed += 1
        except Exception:
            pass
    return changed


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_shift_fn(gap_events: list[dict]):
    ordered = sorted(gap_events, key=lambda event: int(event["timeline_frame"]))

    def shifted_frame(original_frame: int) -> int:
        return int(original_frame) + sum(
            int(event["actual_gap_frames"])
            for event in ordered
            if int(event["timeline_frame"]) <= int(original_frame)
        )

    return shifted_frame


def next_pokemon_marker_after(markers: list[dict], frame: int) -> dict | None:
    pokemon = [m for m in markers if m.get("kind") == "pokemon_start" and int(m["timeline_frame"]) > frame]
    return min(pokemon, key=lambda marker: int(marker["timeline_frame"])) if pokemon else None


def build_hold_plans(plan: dict, features: dict[int, dict], visual_markers: dict) -> list[HoldPlan]:
    holds: list[HoldPlan] = []
    gap_events = plan["gap_events"]
    markers = plan["markers"]
    shift = build_shift_fn(gap_events)

    paras = next(marker for marker in markers if marker["name"] == "Pokemon Start - Paras")
    holds.append(
        HoldPlan(
            key="challenge_setup_overview",
            label="Challenge setup overview hold",
            start=0,
            end=int(paras["timeline_frame"]),
            source_clip_index=1,
            source_sec=float(features[1]["source_sec"]),
            kind="setup_overview",
        )
    )

    for event in gap_events:
        if event.get("kind") != "recap_screen":
            continue
        clip_index = int(event["clip_index"])
        hold_start = int(event["video_gap_cover_start_frame"])
        if clip_index == 2008:
            first_final = min(
                (
                    row for row in visual_markers["markers"]
                    if row.get("kind") == "final_scene" and int(row["clip_index"]) >= 2010
                ),
                key=lambda row: int(row["timeline_frame"]),
            )
            hold_end = shift(int(first_final["timeline_frame"]))
        else:
            next_pokemon = next_pokemon_marker_after(markers, int(event["event_frame_after_gap"]) - 1)
            if not next_pokemon:
                continue
            hold_end = int(next_pokemon["timeline_frame"])
        if hold_end > hold_start:
            holds.append(
                HoldPlan(
                    key=f"recap_c{clip_index:04d}",
                    label=f"Recap overview hold c{clip_index}",
                    start=hold_start,
                    end=hold_end,
                    source_clip_index=clip_index,
                    source_sec=float(features[clip_index]["source_sec"]),
                    kind="recap_overview",
                )
            )

    final_scene_rows = [
        row for row in visual_markers["markers"]
        if row.get("kind") == "final_scene" and int(row["clip_index"]) >= 2010
    ]
    final_scene_rows.sort(key=lambda row: int(row["timeline_frame"]))
    outro_marker = next(marker for marker in plan["markers"] if marker["kind"] == "outro_start")
    source_end = int(plan["timeline_end_frame"])

    for index, row in enumerate(final_scene_rows):
        clip_index = int(row["clip_index"])
        start = shift(int(row["timeline_frame"]))
        if index + 1 < len(final_scene_rows):
            end = shift(int(final_scene_rows[index + 1]["timeline_frame"]))
        else:
            end = int(outro_marker["timeline_frame"])
        if end - start >= FPS:
            holds.append(
                HoldPlan(
                    key=f"wrap_scene_c{clip_index:04d}",
                    label=f"Wrap-up visual hold c{clip_index}",
                    start=start,
                    end=end,
                    source_clip_index=clip_index,
                    source_sec=float(features[clip_index]["source_sec"]),
                    kind="wrap_up",
                )
            )

    clean: list[HoldPlan] = []
    last_end = -1
    for hold in sorted(holds, key=lambda h: (h.start, h.end)):
        if hold.duration <= 0:
            continue
        if hold.start < last_end:
            raise RuntimeError(f"Overlapping hold plan near {hold.key}: {hold.start} < {last_end}")
        clean.append(hold)
        last_end = hold.end
    return clean


def build_v1_hold_spine(v1_specs: list[ClipSpec], holds: list[HoldPlan], timeline_fps: float) -> tuple[list[V1Segment], list[dict]]:
    """Rewrite the V1 spine so visual holds are real V1 clip extensions.

    A hold here is not a still-image overlay. The V1 clips inside the approved
    range are replaced by one continuous V1 segment anchored at the source clip
    that introduced the visual state. A1 stays cut underneath it.
    """
    specs = sorted(v1_specs, key=lambda spec: spec.start)
    ordered_holds = sorted(holds, key=lambda hold: (hold.start, hold.end))
    anchors = {index + 1: spec for index, spec in enumerate(specs)}
    media_durations: dict[int, int] = {}
    segments: list[V1Segment] = []
    inserted: set[str] = set()
    report: list[dict] = []
    hold_index = 0

    def append_normal(spec: ClipSpec, start: int, end: int) -> None:
        if end <= start:
            return
        segments.append(
            V1Segment(
                item=spec.item,
                name=spec.name,
                start=start,
                end=end,
                left=spec.left + (start - spec.start),
                kind="normal",
                hold_key="",
                clip_color=spec.clip_color,
            )
        )

    def append_hold(hold: HoldPlan) -> None:
        anchor = anchors.get(hold.source_clip_index)
        if not anchor:
            raise RuntimeError(f"Hold {hold.key} references missing V1 clip index {hold.source_clip_index}")
        if not (anchor.start <= hold.start < anchor.end):
            raise RuntimeError(
                f"Hold {hold.key} anchor clip {hold.source_clip_index} does not contain hold start "
                f"{hold.start}; anchor range is {anchor.start}-{anchor.end}"
            )
        left = anchor.left + (hold.start - anchor.start)
        media_key = id(anchor.item)
        if media_key not in media_durations:
            media_durations[media_key] = media_duration_tl_frames(anchor.item, timeline_fps)
        media_duration = media_durations[media_key]
        if left + hold.duration > media_duration:
            raise RuntimeError(
                f"Hold {hold.key} would run past source media: left={left} duration={hold.duration} "
                f"media_duration={media_duration}"
            )
        segments.append(
            V1Segment(
                item=anchor.item,
                name=anchor.name,
                start=hold.start,
                end=hold.end,
                left=left,
                kind="hold",
                hold_key=hold.key,
                clip_color=anchor.clip_color,
            )
        )
        inserted.add(hold.key)
        report.append(
            {
                "key": hold.key,
                "label": hold.label,
                "kind": hold.kind,
                "start": hold.start,
                "end": hold.end,
                "duration_frames": hold.duration,
                "source_clip_index": hold.source_clip_index,
                "source_left": left,
                "source_end": left + hold.duration,
            }
        )

    for spec in specs:
        pos = spec.start
        while pos < spec.end:
            while hold_index < len(ordered_holds) and ordered_holds[hold_index].end <= pos:
                hold_index += 1
            hold = ordered_holds[hold_index] if hold_index < len(ordered_holds) and ordered_holds[hold_index].start < spec.end else None
            if not hold:
                append_normal(spec, pos, spec.end)
                break
            if pos < hold.start:
                normal_end = min(spec.end, hold.start)
                append_normal(spec, pos, normal_end)
                pos = normal_end
                continue
            if pos < hold.end:
                if hold.key not in inserted:
                    append_hold(hold)
                pos = min(spec.end, hold.end)
                if pos >= hold.end:
                    hold_index += 1
                continue
            append_normal(spec, pos, spec.end)
            break

    missing = [hold.key for hold in ordered_holds if hold.key not in inserted]
    if missing:
        raise RuntimeError(f"V1 hold spine did not insert holds: {missing}")

    segments.sort(key=lambda segment: (segment.start, segment.end))
    for prev, cur in zip(segments, segments[1:]):
        if prev.end > cur.start:
            raise RuntimeError(f"V1 hold spine overlaps: {prev.hold_key or prev.name} ends {prev.end}, next starts {cur.start}")
    return segments, report


def extract_hold_stills(source_path: Path, holds: list[HoldPlan]) -> dict[str, Path]:
    STILLS_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for hold in holds:
        png = STILLS_DIR / f"{hold.key}_c{hold.source_clip_index:04d}.png"
        out[hold.key] = png
        if png.exists() and png.stat().st_size > 0:
            continue
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{hold.source_sec:.3f}",
            "-i",
            str(source_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=3840:2160",
            str(png),
        ]
        print(f"Extracting hold still {png.name} from {hold.source_sec:.3f}s", flush=True)
        subprocess.run(cmd, check=True)
    return out


def render_hold_videos(stills: dict[str, Path], holds: list[HoldPlan]) -> dict[str, Path]:
    HOLD_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for hold in holds:
        mp4 = HOLD_VIDEO_DIR / f"{hold.key}_c{hold.source_clip_index:04d}_{hold.duration:06d}f.mp4"
        out[hold.key] = mp4
        if mp4.exists() and mp4.stat().st_size > 0:
            continue
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-i",
            str(stills[hold.key]),
            "-frames:v",
            str(hold.duration),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "stillimage",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4),
        ]
        print(f"Rendering hold video {mp4.name} ({hold.duration} frames)", flush=True)
        subprocess.run(cmd, check=True)
    return out


def list_bgm_files() -> list[Path]:
    exts = {".wav", ".mp3", ".m4a", ".flac", ".aiff", ".aif"}
    files = [path for path in BGM_DIR.iterdir() if path.is_file() and path.suffix.lower() in exts]
    if not files:
        raise RuntimeError(f"No BGM files found in {BGM_DIR}")
    first = [path for path in files if path.name.lower() == "dual screen lovelife.wav"]
    rest = [path for path in files if path not in first]
    rng = random.Random(19031)
    rng.shuffle(rest)
    return first + rest


def build_bgm_payload(media: dict[str, object], bgm_paths: list[Path], timeline_fps: float, total_end: int, track_index: int = 2) -> tuple[list[dict], list[dict]]:
    payload = []
    report = []
    cur = 0
    index = 0
    while cur < total_end:
        path = bgm_paths[index % len(bgm_paths)]
        mpi = media[norm_path(path)]
        timing = media_timing(mpi, timeline_fps)
        timeline_duration = timing.timeline_frames
        place_duration = min(timeline_duration, total_end - cur)
        if place_duration <= 0:
            raise RuntimeError(f"BGM duration issue for {path}")
        if place_duration == timeline_duration:
            source_duration = timing.source_frames
        else:
            source_duration = max(1, round((place_duration / timeline_fps) * timing.source_fps))
        payload.append(
            {
                "mediaPoolItem": mpi,
                "startFrame": 0,
                # Resolve trims audio in the media item's source-frame units.
                # The record position below is still in timeline frames.
                "endFrame": source_duration,
                "recordFrame": cur,
                "trackIndex": track_index,
                "mediaType": 2,
            }
        )
        report.append(
            {
                "path": str(path),
                "name": path.name,
                "record_frame": cur,
                "duration_frames": place_duration,
                "end_frame": cur + place_duration,
                "source_fps": timing.source_fps,
                "source_duration_frames": source_duration,
                "source_full_duration_frames": timing.source_frames,
                "timeline_full_duration_frames": timeline_duration,
            }
        )
        cur += place_duration
        index += 1
    return payload, report


def build_markers(plan: dict, intro_frames: int, source_end: int, final_end: int) -> list[dict]:
    markers = [
        {
            "frame": 0,
            "color": INTRO_MARKER_COLOR,
            "name": "Intro Clip Start",
            "note": "RSE intro clip begins; A2 BGM starts here.",
        },
        {
            "frame": intro_frames,
            "color": INTRO_MARKER_COLOR,
            "name": "Source Content Start",
            "note": "Reduced-gap source timeline begins after intro.",
        },
    ]
    for marker in plan["markers"]:
        if marker.get("kind") == "pokemon_start":
            markers.append(
                {
                    "frame": intro_frames + int(marker["timeline_frame"]),
                    "color": POKEMON_MARKER_COLOR,
                    "name": marker["name"],
                    "note": marker.get("note") or "",
                }
            )
        elif marker.get("kind") == "outro_start":
            markers.append(
                {
                    "frame": intro_frames + int(marker["timeline_frame"]),
                    "color": OUTRO_MARKER_COLOR,
                    "name": "Source Outro Start",
                    "note": marker.get("note") or "",
                }
            )

    for event in plan["gap_events"]:
        if event.get("kind") != "recap_screen":
            continue
        clip_index = int(event["clip_index"])
        markers.append(
            {
                "frame": intro_frames + int(event["video_gap_cover_start_frame"]),
                "color": RECAP_MARKER_COLOR,
                "name": f"Recap Start - c{clip_index:04d}",
                "note": (
                    f"{event.get('label', 'recap')} visual hold starts here; "
                    "the A1 one-second gap runs under the first 60 frames."
                ),
            }
        )

    markers.append(
        {
            "frame": intro_frames + source_end,
            "color": OUTRO_MARKER_COLOR,
            "name": "Outro Clip Start",
            "note": "Appended RSE outro clip begins; A2 BGM continues underneath.",
        }
    )
    markers.append(
        {
            "frame": final_end,
            "color": OUTRO_MARKER_COLOR,
            "name": "Final Timeline End",
            "note": "End of appended outro/BGM coverage.",
        }
    )
    return sorted(markers, key=lambda marker: int(marker["frame"]))


def clear_and_add_markers(timeline, markers: list[dict]) -> dict:
    try:
        timeline.DeleteMarkersByColor("All")
    except Exception:
        for raw in list((timeline.GetMarkers() or {}).keys()):
            timeline.DeleteMarkerAtFrame(int(round(float(raw))))
    added = []
    failed = []
    for marker in markers:
        ok = timeline.AddMarker(
            int(marker["frame"]),
            marker.get("color") or "Blue",
            marker.get("name") or "",
            marker.get("note") or "",
            1,
            "",
        )
        (added if ok else failed).append(marker)
    return {"requested": len(markers), "added": len(added), "failed": failed}


def track_items(timeline, track_type: str, track_index: int) -> list[dict]:
    rows = []
    for item in sorted(timeline.GetItemListInTrack(track_type, track_index) or [], key=lambda clip: clip.GetStart()):
        mpi = item.GetMediaPoolItem()
        props = mpi.GetClipProperty() if mpi else {}
        start = int(item.GetStart())
        duration = int(item.GetDuration())
        rows.append(
            {
                "name": item.GetName() or "",
                "start": start,
                "end": start + duration,
                "duration": duration,
                "left": int(item.GetLeftOffset()),
                "path": props.get("File Path") or "",
            }
        )
    return rows


def gaps_between(rows: list[dict], start: int | None = None, end: int | None = None) -> list[dict]:
    if not rows:
        return []
    rows = sorted(rows, key=lambda row: row["start"])
    gaps = []
    cur = rows[0]["start"] if start is None else start
    for row in rows:
        if row["start"] > cur:
            gaps.append({"start": cur, "end": row["start"], "frames": row["start"] - cur})
        cur = max(cur, row["end"])
    if end is not None and cur < end:
        gaps.append({"start": cur, "end": end, "frames": end - cur})
    return gaps


def is_covered(rows: list[dict], start: int, end: int) -> bool:
    cur = start
    for row in sorted(rows, key=lambda r: r["start"]):
        if row["end"] <= cur:
            continue
        if row["start"] > cur:
            return False
        cur = max(cur, row["end"])
        if cur >= end:
            return True
    return cur >= end


def verify_timeline(
    timeline,
    plan: dict,
    hold_plans: list[HoldPlan],
    expected_v1_segments: list[V1Segment],
    intro_frames: int,
    source_end: int,
    final_end: int,
    expected_markers: list[dict],
    expected_bgm: list[dict] | None = None,
) -> dict:
    v1 = track_items(timeline, "video", 1)
    higher_video = {}
    for index in range(2, int(timeline.GetTrackCount("video") or 0) + 1):
        rows = track_items(timeline, "video", index)
        if rows:
            higher_video[f"V{index}"] = rows
    a1 = track_items(timeline, "audio", 1)
    a2 = track_items(timeline, "audio", 2)
    video_overhang_tracks = {"V1": v1}
    for index in range(2, int(timeline.GetTrackCount("video") or 0) + 1):
        video_overhang_tracks[f"V{index}"] = track_items(timeline, "video", index)
    higher_audio = {}
    for index in range(3, int(timeline.GetTrackCount("audio") or 0) + 1):
        higher_audio[f"A{index}"] = track_items(timeline, "audio", index)

    source_start = intro_frames
    source_finish = intro_frames + source_end

    expected_a1_gaps = [
        {
            "start": intro_frames + int(event["video_gap_cover_start_frame"]),
            "end": intro_frames + int(event["event_frame_after_gap"]),
            "frames": int(event["actual_gap_frames"]),
            "label": event["label"],
        }
        for event in plan["gap_events"]
    ]
    actual_a1_gaps = gaps_between(a1)
    expected_gap_set = {(g["start"], g["end"]) for g in expected_a1_gaps}
    actual_gap_set = {(g["start"], g["end"]) for g in actual_a1_gaps}

    v1_gap_cover_failures = [
        gap for gap in expected_a1_gaps
        if not any(item["start"] <= gap["start"] and item["end"] >= gap["end"] for item in v1)
    ]

    expected_source_v1 = [
        {
            "start": intro_frames + segment.start,
            "end": intro_frames + segment.end,
            "duration": segment.duration,
            "left": segment.left,
            "kind": segment.kind,
            "hold_key": segment.hold_key,
        }
        for segment in expected_v1_segments
    ]
    actual_source_v1 = [
        row for row in v1
        if row["start"] >= source_start and row["start"] < source_finish
    ]
    v1_structure_mismatches = []
    if len(actual_source_v1) != len(expected_source_v1):
        v1_structure_mismatches.append(
            {
                "reason": "source V1 segment count mismatch",
                "actual": len(actual_source_v1),
                "expected": len(expected_source_v1),
            }
        )
    for index, (actual, expected) in enumerate(zip(actual_source_v1, expected_source_v1), start=1):
        for key in ("start", "end", "duration", "left"):
            if actual[key] != expected[key]:
                v1_structure_mismatches.append(
                    {"index": index, "field": key, "actual": actual, "expected": expected}
                )
                break
        if len(v1_structure_mismatches) >= 12:
            break

    hold_failures = []
    for hold in hold_plans:
        start = intro_frames + hold.start
        end = intro_frames + hold.end
        matches = [
            row for row in actual_source_v1
            if row["start"] == start and row["end"] == end
        ]
        if len(matches) != 1:
            hold_failures.append(
                {"key": hold.key, "start": start, "end": end, "frames": end - start, "matches": len(matches)}
            )

    hold_ranges = [(intro_frames + hold.start, intro_frames + hold.end) for hold in hold_plans]
    gap_ranges = [(gap["start"], gap["end"]) for gap in expected_a1_gaps]

    def inside_any(frame: int, ranges: list[tuple[int, int]]) -> bool:
        return any(start <= frame < end for start, end in ranges)

    def covering_audio(frame: int) -> dict | None:
        for row in a1:
            if row["start"] <= frame < row["end"]:
                return row
        return None

    sync_probe_mismatches = []
    sync_probe_count = 0
    normal_synced = 0
    skipped_hold_segments = 0
    for index, (actual, expected) in enumerate(zip(actual_source_v1, expected_source_v1), start=1):
        if expected["kind"] == "hold":
            skipped_hold_segments += 1
            continue
        probes = sorted({actual["start"], (actual["start"] + actual["end"]) // 2, actual["end"] - 1})
        for frame in probes:
            if inside_any(frame, hold_ranges) or inside_any(frame, gap_ranges):
                continue
            audio = covering_audio(frame)
            if not audio:
                sync_probe_mismatches.append({"index": index, "frame": frame, "video": actual, "reason": "no A1 clip covers probe"})
                break
            video_media_frame = actual["left"] + (frame - actual["start"])
            audio_media_frame = audio["left"] + (frame - audio["start"])
            sync_probe_count += 1
            if video_media_frame != audio_media_frame:
                sync_probe_mismatches.append(
                    {
                        "index": index,
                        "frame": frame,
                        "video": actual,
                        "audio": audio,
                        "video_media_frame": video_media_frame,
                        "audio_media_frame": audio_media_frame,
                    }
                )
                break
        else:
            normal_synced += 1
        if len(sync_probe_mismatches) >= 12:
            break

    markers = {int(round(float(frame))): data for frame, data in (timeline.GetMarkers() or {}).items()}
    missing_markers = []
    for marker in expected_markers:
        data = markers.get(int(marker["frame"]))
        if not data or data.get("name") != marker["name"]:
            missing_markers.append(marker)

    unexpected_higher_audio = {
        track: rows for track, rows in higher_audio.items() if rows
    }

    a2_gaps = gaps_between(a2, start=0, end=final_end)
    v1_gaps = gaps_between(v1, start=0, end=final_end)
    a2_non_bgm = [
        row for row in a2
        if "Roxanne Minimum_COMBINED" in row["name"] or row["path"].lower().endswith("combined_tracks/2.wav")
    ]
    bgm_mismatches = []
    if expected_bgm is not None:
        if len(a2) != len(expected_bgm):
            bgm_mismatches.append(
                {
                    "reason": "A2 BGM clip count mismatch",
                    "actual": len(a2),
                    "expected": len(expected_bgm),
                }
            )
        for index, (actual, expected) in enumerate(zip(a2, expected_bgm), start=1):
            expected_row = {
                "name": expected["name"],
                "start": int(expected["record_frame"]),
                "end": int(expected["end_frame"]),
                "duration": int(expected["duration_frames"]),
                "left": int(expected.get("source_start_frame", 0)),
            }
            mismatch_fields = [
                key for key in ("name", "start", "end", "duration", "left")
                if actual.get(key) != expected_row[key]
            ]
            if mismatch_fields:
                bgm_mismatches.append(
                    {
                        "index": index,
                        "fields": mismatch_fields,
                        "actual": actual,
                        "expected": expected_row,
                        "expected_source_fps": expected.get("source_fps"),
                        "expected_source_duration_frames": expected.get("source_duration_frames"),
                    }
                )
            if len(bgm_mismatches) >= 12:
                break
    overhanging_items = []
    for track_name, rows in video_overhang_tracks.items():
        overhanging_items.extend([{**row, "track": track_name} for row in rows if row["end"] > final_end])
    overhanging_items.extend([{**row, "track": "A1"} for row in a1 if row["end"] > final_end])
    overhanging_items.extend([{**row, "track": "A2"} for row in a2 if row["end"] > final_end])
    for track, rows in higher_audio.items():
        overhanging_items.extend([{**row, "track": track} for row in rows if row["end"] > final_end])

    failures = []
    if len(actual_a1_gaps) != len(expected_a1_gaps) or expected_gap_set != actual_gap_set:
        failures.append("A1 gap set does not match the reduced gap plan")
    if v1_gap_cover_failures:
        failures.append("One or more A1 gaps are not covered by V1")
    if a2_gaps:
        failures.append("A2 BGM bed has coverage gaps")
    if a2_non_bgm:
        failures.append("A2 contains non-BGM/source audio")
    if bgm_mismatches:
        failures.append("A2 BGM clips do not match the source-duration placement plan")
    if unexpected_higher_audio:
        failures.append("Audio tracks above A2 contain clips")
    if higher_video:
        failures.append("Higher video tracks contain clips; visual holds must be continuous V1, not overlays")
    if v1_structure_mismatches:
        failures.append("Source V1 does not match the rewritten continuous-hold spine")
    if sync_probe_mismatches:
        failures.append("Source V1/A1 sync probe mismatch outside holds and A1 gaps")
    if hold_failures:
        failures.append("One or more planned visual holds are not represented by a single V1 clip")
    if missing_markers:
        failures.append("Expected markers missing or mismatched")
    if v1_gaps:
        failures.append("V1 has gaps across intro/source/outro")
    if overhanging_items:
        failures.append("One or more timeline clips extend past the intended final end")

    return {
        "schema": "roxanne_finished_timeline_verify_v2_continuous_v1_holds",
        "generated_at": now(),
        "timeline_name": timeline.GetName(),
        "timeline_start_frame": timeline.GetStartFrame(),
        "timeline_end_frame": timeline.GetEndFrame(),
        "intro_frames": intro_frames,
        "source_start_frame": source_start,
        "source_end_frame": source_finish,
        "final_end_frame": final_end,
        "track_counts": {
            "video": timeline.GetTrackCount("video"),
            "audio": timeline.GetTrackCount("audio"),
        },
        "item_counts": {
            "V1": len(v1),
            "source_V1_expected": len(expected_source_v1),
            "source_V1_actual": len(actual_source_v1),
            "V1_hold_segments_expected": len(hold_plans),
            "V1_hold_segments_actual": len([row for row in expected_source_v1 if row["kind"] == "hold"]),
            "higher_video_items": sum(len(rows) for rows in higher_video.values()),
            "A1": len(a1),
            "A2": len(a2),
        },
        "expected_a1_gaps": expected_a1_gaps,
        "actual_a1_gaps": actual_a1_gaps,
        "v1_gap_cover_failures": v1_gap_cover_failures,
        "v1_gaps": v1_gaps,
        "a2_gaps": a2_gaps,
        "a2_non_bgm": a2_non_bgm,
        "a2_bgm_mismatches": bgm_mismatches,
        "higher_video_nonempty": higher_video,
        "higher_audio_nonempty": unexpected_higher_audio,
        "overhanging_items": overhanging_items,
        "v1_structure_mismatches": v1_structure_mismatches,
        "sync": {
            "source_v1_count": len(actual_source_v1),
            "source_a1_count": len(a1),
            "normal_segments_probe_synced": normal_synced,
            "hold_segments_skipped": skipped_hold_segments,
            "probe_count": sync_probe_count,
            "mismatches": sync_probe_mismatches,
        },
        "hold_failures": hold_failures,
        "marker_count": len(markers),
        "expected_marker_count": len(expected_markers),
        "missing_markers": missing_markers,
        "failures": failures,
        "ok": not failures,
    }


def main() -> int:
    for path in (PLAN_PATH, FEATURES_PATH, VISUAL_MARKERS_PATH, INTRO_ASSET, OUTRO_ASSET, BGM_DIR):
        if not path.exists():
            raise RuntimeError(f"Required path missing: {path}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan = load_json(PLAN_PATH)
    features_data = load_json(FEATURES_PATH)
    visual_markers = load_json(VISUAL_MARKERS_PATH)
    features = {int(row["clip_index"]): row for row in features_data["features"]}

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Resolve not connected")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No current Resolve project")
    pool = project.GetMediaPool()

    current_page = ""
    try:
        current_page = resolve.GetCurrentPage()
    except Exception:
        pass

    source_timeline = find_timeline(project, SOURCE_TIMELINE_NAME) or project.GetCurrentTimeline()
    if not source_timeline or source_timeline.GetName() != SOURCE_TIMELINE_NAME:
        raise RuntimeError(
            f"Expected source timeline {SOURCE_TIMELINE_NAME!r}, got "
            f"{source_timeline.GetName() if source_timeline else None!r}"
        )
    project.SetCurrentTimeline(source_timeline)

    timeline_fps = float(project.GetSetting("timelineFrameRate") or FPS)
    source_start = int(source_timeline.GetStartFrame())
    source_end = max(item.GetEnd() for item in (source_timeline.GetItemListInTrack("video", 1) or [])) - source_start
    plan["timeline_end_frame"] = source_end

    v1_specs = collect_track_specs(source_timeline, "video", 1, 1)
    a1_specs = collect_track_specs(source_timeline, "audio", 1, 2)
    if not v1_specs or not a1_specs:
        raise RuntimeError("Source timeline does not have both V1 and A1 clips")

    source_path = Path((v1_specs[0].item.GetClipProperty() or {}).get("File Path") or "")
    if not source_path.exists():
        raise RuntimeError(f"Could not resolve source video path from V1: {source_path}")

    holds = build_hold_plans(plan, features, visual_markers)
    v1_segments, v1_hold_report = build_v1_hold_spine(v1_specs, holds, timeline_fps)
    bgm_paths = list_bgm_files()

    media_paths = [INTRO_ASSET, OUTRO_ASSET, *bgm_paths]
    media = find_or_import_media(pool, media_paths)

    output_name = unique_timeline_name(project, OUTPUT_TIMELINE_BASE)
    target = pool.CreateEmptyTimeline(output_name)
    if not target:
        raise RuntimeError(f"CreateEmptyTimeline failed for {output_name!r}")
    project.SetCurrentTimeline(target)
    try:
        target.SetStartTimecode("00:00:00:00")
    except Exception:
        pass
    target.SetSetting("timelineFrameRate", str(FPS))
    target.SetSetting("timelinePlaybackFrameRate", str(FPS))
    target.SetSetting("timelineResolutionWidth", "3840")
    target.SetSetting("timelineResolutionHeight", "2160")
    ensure_tracks(target, video_tracks=1, audio_tracks=2)
    target_start = int(target.GetStartFrame())
    print(f"Target timeline start frame after setup: {target_start}", flush=True)
    if target_start != 0:
        raise RuntimeError(f"Target timeline start frame is {target_start}; expected 0 after SetStartTimecode")

    intro_item = media[norm_path(INTRO_ASSET)]
    outro_item = media[norm_path(OUTRO_ASSET)]

    print(f"Placing intro on V1: {INTRO_ASSET.name}", flush=True)
    intro_placed = append_payload(
        pool,
        [{"mediaPoolItem": intro_item, "recordFrame": target_start, "trackIndex": 1, "mediaType": 1}],
        "intro",
        batch_size=1,
    )
    if not intro_placed:
        raise RuntimeError("Intro placement failed")
    intro_frames = int(intro_placed[0].GetDuration())
    print(f"Intro duration in final timeline: {intro_frames} frames", flush=True)

    source_shift = target_start + intro_frames - source_start
    v1_payload = []
    v1_colors = []
    for segment in v1_segments:
        v1_payload.append(
            {
                "mediaPoolItem": segment.item,
                "startFrame": segment.left,
                "endFrame": segment.left + segment.duration,
                "recordFrame": segment.start + source_shift,
                "trackIndex": 1,
                "mediaType": 1,
            }
        )
        v1_colors.append(segment.clip_color)
    a1_payload = []
    a1_colors = []
    for spec in a1_specs:
        a1_payload.append(
            {
                "mediaPoolItem": spec.item,
                "startFrame": spec.left,
                "endFrame": spec.left + spec.duration,
                "recordFrame": spec.start + source_shift,
                "trackIndex": 1,
                "mediaType": 2,
            }
        )
        a1_colors.append(spec.clip_color)

    v1_placed = append_payload(pool, v1_payload, "source V1")
    a1_placed = append_payload(pool, a1_payload, "source A1")
    if len(v1_placed) != len(v1_payload) or len(a1_placed) != len(a1_payload):
        raise RuntimeError(f"Source placement incomplete: V1 {len(v1_placed)}/{len(v1_payload)} A1 {len(a1_placed)}/{len(a1_payload)}")
    set_clip_colors(v1_placed, v1_colors)
    set_clip_colors(a1_placed, a1_colors)

    final_source_end = target_start + intro_frames + source_end
    print(f"Placing outro on V1 at frame {final_source_end}: {OUTRO_ASSET.name}", flush=True)
    outro_placed = append_payload(
        pool,
        [{"mediaPoolItem": outro_item, "recordFrame": final_source_end, "trackIndex": 1, "mediaType": 1}],
        "outro",
        batch_size=1,
    )
    if not outro_placed:
        raise RuntimeError("Outro placement failed")
    outro_frames = int(outro_placed[0].GetDuration())
    final_end = final_source_end + outro_frames

    bgm_media = {norm_path(path): media[norm_path(path)] for path in bgm_paths}
    bgm_payload, bgm_report = build_bgm_payload(bgm_media, bgm_paths, timeline_fps, final_end, track_index=2)
    bgm_placed = append_payload(pool, bgm_payload, "A2 BGM", batch_size=50)
    if len(bgm_placed) != len(bgm_payload):
        raise RuntimeError(f"BGM placement incomplete: {len(bgm_placed)}/{len(bgm_payload)}")

    markers = build_markers(plan, intro_frames, source_end, final_end)
    marker_report = clear_and_add_markers(target, markers)
    if marker_report["failed"]:
        raise RuntimeError(f"Marker placement failures: {marker_report['failed']}")

    save_result = bool(resolve.GetProjectManager().SaveProject())
    build_report = {
        "schema": "roxanne_finished_timeline_build_v2_continuous_v1_holds",
        "generated_at": now(),
        "project_name": project.GetName(),
        "source_timeline": SOURCE_TIMELINE_NAME,
        "output_timeline": target.GetName(),
        "current_page_before": current_page,
        "timeline_fps": timeline_fps,
        "source_video": str(source_path),
        "source_end_frame": source_end,
        "intro_asset": str(INTRO_ASSET),
        "intro_frames": intro_frames,
        "outro_asset": str(OUTRO_ASSET),
        "outro_frames": outro_frames,
        "final_end_frame": final_end,
        "source_v1_clips_original": len(v1_specs),
        "source_v1_segments_after_holds": len(v1_payload),
        "source_a1_clips": len(a1_payload),
        "hold_count": len(holds),
        "holds": [
            {
                "key": hold.key,
                "label": hold.label,
                "kind": hold.kind,
                "start": target_start + intro_frames + hold.start,
                "end": target_start + intro_frames + hold.end,
                "duration_frames": hold.duration,
                "source_clip_index": hold.source_clip_index,
                "source_sec": hold.source_sec,
            }
            for hold in holds
        ],
        "v1_hold_report": [
            {
                **row,
                "start": target_start + intro_frames + int(row["start"]),
                "end": target_start + intro_frames + int(row["end"]),
            }
            for row in v1_hold_report
        ],
        "hold_chunk_count": 0,
        "bgm_count": len(bgm_report),
        "bgm": bgm_report,
        "markers": markers,
        "marker_report": marker_report,
        "project_save_result": save_result,
    }
    BUILD_REPORT.write_text(json.dumps(build_report, indent=2), encoding="utf-8")

    verify = verify_timeline(target, plan, holds, v1_segments, target_start + intro_frames, source_end, final_end, markers, bgm_report)
    VERIFY_REPORT.write_text(json.dumps(verify, indent=2), encoding="utf-8")

    print(f"Build report: {BUILD_REPORT}", flush=True)
    print(f"Verify report: {VERIFY_REPORT}", flush=True)
    print(f"Verification ok: {verify['ok']}", flush=True)
    if not verify["ok"]:
        print(json.dumps(verify["failures"], indent=2), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
