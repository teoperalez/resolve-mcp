from __future__ import annotations

"""Place Victreebel RBY battle audio with Gen 1 leader crossfades.

This is intentionally project-specific. The verified Victreebel timeline has:
  - Rival battle start/finish markers from RBYNewLayout session logs.
  - Gen 1 leader intro audio already inserted on A3.
  - One opening BGM clip on A2 that must be preserved.

For Rival battles, this places the Rival track on A2 from start to finish and
fades out at the end. For leader/E4/champion battles, it continues the same
retimed leader audio source onto A2, starting one second before the A3 intro
audio ends. The A3 clip fades out while the A2 clip fades in over that overlap.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401


PROJECT_DIR = Path(r"E:\Victreebel Red and Blue Ultra Minimum Battles")
LEADER_AUDIO_DIR = PROJECT_DIR / "CODEx" / "assets" / "leader-audio"
RETIME_DIR = Path.home() / ".resolve-mcp" / "cache" / "retimed-gen1-intros"
CACHE_DIR = Path.home() / ".resolve-mcp" / "cache" / "victreebel-battle-audio"
REPORT_PATH = Path("_data") / "qa-reports" / "victreebel-battle-audio.json"

LEADER_RETIMED_AUDIO = {
    "Brock": "Brock__2x_resolve2.mp3",
    "Misty": "Misty__2x_resolve2.mp3",
    "Erika": "Erika__2x_resolve2.mp3",
    "Surge": "Surge__2x_resolve2.mp3",
    "Giovanni": "Giovanni 3__2x_resolve2.mp3",
    "Koga": "Koga__2x_resolve2.mp3",
    "Bruno": "Bruno__2x_resolve2.mp3",
    "Lorelei": "Lorelei__2x_resolve2.mp3",
    "Sabrina": "Sabrina__2x_resolve2.mp3",
    "Blaine": "Blaine__2x_resolve2.mp3",
    "Lance": "Lance__2x_resolve2.mp3",
    "Agatha": "Agatha__2x_resolve2.mp3",
    "Champion": "Champion__2x_resolve2.mp3",
}


@dataclass
class Marker:
    rel: int
    abs: int
    name: str
    color: str
    note: str
    duration: int


@dataclass
class SliceSpec:
    role: str
    label: str
    source: Path
    source_start: int
    duration: int
    record_frame: int
    track: int
    fade_in: int = 0
    fade_out: int = 0
    out_path: Path | None = None


def safe_name(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip())
    return text.strip("_") or "clip"


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"command failed: {cmd}")
    return json.loads(proc.stdout)


def media_duration_frames(path: Path, fps: float) -> int:
    data = run_json([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ])
    dur = float(data["format"]["duration"])
    return max(1, int(round(dur * fps)))


def render_path(spec: SliceSpec) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    label = safe_name(spec.label)
    stem = safe_name(spec.source.stem)
    return CACHE_DIR / (
        f"vba_{spec.role}_{label}__{stem}"
        f"__s{spec.source_start}_d{spec.duration}"
        f"__fi{spec.fade_in}_fo{spec.fade_out}.wav"
    )


def clamp_fades(duration: int, fade_in: int, fade_out: int) -> tuple[int, int]:
    fade_in = max(0, min(fade_in, duration))
    fade_out = max(0, min(fade_out, duration))
    if fade_in + fade_out > duration:
        # Keep both fades present on very short clips without asking ffmpeg to
        # run two full-length fades over a tiny slice.
        half = max(1, duration // 2)
        fade_in = min(fade_in, half)
        fade_out = min(fade_out, duration - fade_in)
    return fade_in, fade_out


def render_slice(spec: SliceSpec, fps: float) -> Path:
    out = render_path(spec)
    spec.out_path = out
    if out.exists():
        return out

    fade_in, fade_out = clamp_fades(spec.duration, spec.fade_in, spec.fade_out)
    start_sec = spec.source_start / fps
    dur_sec = spec.duration / fps

    filters = []
    if fade_in:
        filters.append(f"afade=t=in:st=0:d={fade_in / fps:.6f}:curve=hsin")
    if fade_out:
        start = max(0.0, dur_sec - (fade_out / fps))
        filters.append(f"afade=t=out:st={start:.6f}:d={fade_out / fps:.6f}:curve=hsin")
    afilter = ",".join(filters) if filters else "anull"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_sec:.6f}",
        "-i",
        str(spec.source),
        "-t",
        f"{dur_sec:.6f}",
        "-af",
        afilter,
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 or not out.exists():
        tail = "\n".join(proc.stderr.splitlines()[-6:])
        raise RuntimeError(f"ffmpeg failed for {spec.label}:\n{tail}")
    return out


def find_subfolder(parent, names: tuple[str, ...]):
    wanted = {n.lower() for n in names}
    for sub in parent.GetSubFolderList() or []:
        if (sub.GetName() or "").lower() in wanted:
            return sub
    return None


def walk_media(folder):
    for item in folder.GetClipList() or []:
        yield item
    for sub in folder.GetSubFolderList() or []:
        yield from walk_media(sub)


def norm_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").lower()


def clip_path(item) -> str:
    try:
        return item.GetClipProperty("File Path") or ""
    except Exception:
        return ""


def import_media(pool, target_folder, paths: list[Path]) -> dict[str, object]:
    wanted = {norm_path(p.resolve()): p for p in paths}
    found: dict[str, object] = {}
    for item in walk_media(pool.GetRootFolder()):
        p = norm_path(clip_path(item))
        if p in wanted:
            found[p] = item

    missing = [p for key, p in wanted.items() if key not in found]
    if missing:
        previous = pool.GetCurrentFolder()
        pool.SetCurrentFolder(target_folder)
        for i in range(0, len(missing), 25):
            pool.ImportMedia([str(p) for p in missing[i : i + 25]]) or []
        if previous:
            pool.SetCurrentFolder(previous)

    for item in walk_media(pool.GetRootFolder()):
        p = norm_path(clip_path(item))
        if p in wanted:
            found[p] = item

    unresolved = [str(p) for key, p in wanted.items() if key not in found]
    if unresolved:
        raise RuntimeError("Could not import media: " + json.dumps(unresolved, indent=2))
    return found


def collect_markers(timeline) -> list[Marker]:
    tl_start = timeline.GetStartFrame()
    markers = []
    for raw_rel, data in (timeline.GetMarkers() or {}).items():
        rel = int(round(float(raw_rel)))
        markers.append(
            Marker(
                rel=rel,
                abs=tl_start + rel,
                name=data.get("name") or "",
                color=data.get("color") or "",
                note=data.get("note") or "",
                duration=int(data.get("duration") or 1),
            )
        )
    return sorted(markers, key=lambda m: m.abs)


def next_marker(markers: list[Marker], after_abs: int, predicate) -> Marker | None:
    for marker in markers:
        if marker.abs > after_abs and predicate(marker):
            return marker
    return None


def pair_rival_ranges(markers: list[Marker]) -> list[tuple[Marker, Marker]]:
    ranges = []
    used_finishes: set[int] = set()
    for start in [m for m in markers if m.name == "Rival Battle Start"]:
        finish = next(
            (
                m
                for m in markers
                if m.abs > start.abs
                and m.name == "Rival Battle Finish"
                and m.abs not in used_finishes
            ),
            None,
        )
        if finish:
            used_finishes.add(finish.abs)
            ranges.append((start, finish))
    return ranges


def pair_leader_ranges(markers: list[Marker]) -> list[tuple[str, Marker, Marker]]:
    out = []
    for intro_end in [m for m in markers if m.name.endswith(" Leader Intro End")]:
        leader = intro_end.name.removesuffix(" Leader Intro End")
        if leader not in LEADER_RETIMED_AUDIO:
            continue
        finish = next_marker(
            markers,
            intro_end.abs,
            lambda m: m.name.endswith(" Battle Finish") and not m.name.startswith("Rival "),
        )
        if finish:
            out.append((leader, intro_end, finish))
    return out


def find_a3_intro_clip(timeline, leader: str, intro_end_abs: int):
    leader_stem = safe_name(LEADER_RETIMED_AUDIO[leader].removesuffix(".mp3")).lower()
    for clip in timeline.GetItemListInTrack("audio", 3) or []:
        name = safe_name(clip.GetName() or "").lower()
        end = clip.GetStart() + clip.GetDuration()
        if abs(end - intro_end_abs) <= 3 and leader_stem in name:
            return clip
    return None


def append_looped_slices(
    specs: list[SliceSpec],
    *,
    role: str,
    label: str,
    source: Path,
    source_duration: int,
    record_start: int,
    record_end: int,
    track: int,
    first_source_start: int = 0,
    fade_in_first: int = 0,
    fade_out_last: int = 0,
) -> None:
    cur = record_start
    loop = 0
    source_start = min(max(0, first_source_start), source_duration - 1)
    while cur < record_end:
        remaining = record_end - cur
        source_remaining = source_duration - source_start
        if source_remaining <= 0:
            source_start = 0
            source_remaining = source_duration
        dur = min(remaining, source_remaining)
        if dur <= 0:
            break
        is_first = loop == 0
        is_last = cur + dur >= record_end
        specs.append(
            SliceSpec(
                role=role,
                label=f"{label}_loop{loop}",
                source=source,
                source_start=source_start,
                duration=dur,
                record_frame=cur,
                track=track,
                fade_in=fade_in_first if is_first else 0,
                fade_out=fade_out_last if is_last else 0,
            )
        )
        cur += dur
        loop += 1
        source_start = 0


def is_existing_vba_clip(clip) -> bool:
    path = norm_path(clip_path(clip))
    name = (clip.GetName() or "").lower()
    return "/victreebel-battle-audio/" in path or name.startswith("vba_")


def build_plan(timeline, fps: float, fade_frames: int) -> tuple[list[SliceSpec], list[object], dict]:
    markers = collect_markers(timeline)
    specs: list[SliceSpec] = []
    a3_to_delete = []
    report = {
        "timeline": timeline.GetName(),
        "fade_frames": fade_frames,
        "rival_ranges": [],
        "leader_ranges": [],
        "warnings": [],
    }

    rival_source = LEADER_AUDIO_DIR / "Rival.mp3"
    if not rival_source.exists():
        raise RuntimeError(f"Missing Rival audio: {rival_source}")
    rival_duration = media_duration_frames(rival_source, fps)

    for idx, (start, finish) in enumerate(pair_rival_ranges(markers), start=1):
        if finish.abs <= start.abs:
            report["warnings"].append(f"Rival range {idx} has non-positive duration")
            continue
        append_looped_slices(
            specs,
            role="a2_rival",
            label=f"rival_{idx}",
            source=rival_source,
            source_duration=rival_duration,
            record_start=start.abs,
            record_end=finish.abs,
            track=2,
            fade_out_last=fade_frames,
        )
        report["rival_ranges"].append({
            "index": idx,
            "start": start.abs,
            "end": finish.abs,
            "duration": finish.abs - start.abs,
        })

    for leader, intro_end, finish in pair_leader_ranges(markers):
        source = RETIME_DIR / LEADER_RETIMED_AUDIO[leader]
        if not source.exists():
            raise RuntimeError(f"Missing retimed leader audio for {leader}: {source}")
        a3_clip = find_a3_intro_clip(timeline, leader, intro_end.abs)
        if a3_clip is None:
            report["warnings"].append(f"Could not find A3 intro audio clip for {leader}")
            continue

        a3_start = a3_clip.GetStart()
        a3_duration = intro_end.abs - a3_start
        overlap = min(fade_frames, a3_duration, max(0, finish.abs - a3_start))
        if overlap <= 0:
            report["warnings"].append(f"{leader} has no valid overlap")
            continue

        source_duration = media_duration_frames(source, fps)
        a3_to_delete.append(a3_clip)
        specs.append(
            SliceSpec(
                role="a3_intro_fadeout",
                label=f"{leader}_intro",
                source=source,
                source_start=a3_clip.GetLeftOffset(),
                duration=a3_duration,
                record_frame=a3_start,
                track=3,
                fade_out=overlap,
            )
        )

        a2_start = intro_end.abs - overlap
        append_looped_slices(
            specs,
            role="a2_leader",
            label=leader,
            source=source,
            source_duration=source_duration,
            record_start=a2_start,
            record_end=finish.abs,
            track=2,
            first_source_start=max(0, a3_clip.GetLeftOffset() + a3_duration - overlap),
            fade_in_first=overlap,
            fade_out_last=fade_frames,
        )
        report["leader_ranges"].append({
            "leader": leader,
            "intro_end": intro_end.abs,
            "battle_audio_start": a2_start,
            "battle_finish": finish.abs,
            "overlap": overlap,
            "a3_start": a3_start,
            "a3_duration": a3_duration,
        })

    return specs, a3_to_delete, report


def print_plan(specs: list[SliceSpec], report: dict, tl_start: int, fps: float) -> None:
    print(json.dumps({
        "timeline": report["timeline"],
        "rival_ranges": report["rival_ranges"],
        "leader_ranges": report["leader_ranges"],
        "warnings": report["warnings"],
        "slice_count": len(specs),
    }, indent=2))
    print("\nPlanned slices:")
    for spec in sorted(specs, key=lambda s: (s.record_frame, s.track, s.label)):
        print(
            f"  A{spec.track} rel={(spec.record_frame - tl_start) / fps:8.3f}s "
            f"dur={spec.duration / fps:7.3f}s "
            f"src={spec.source_start:5d} fi={spec.fade_in:3d} fo={spec.fade_out:3d} "
            f"{spec.role} {spec.label}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fade-sec", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No current Resolve project")
    pool = project.GetMediaPool()
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No current timeline")

    fps = float(project.GetSetting("timelineFrameRate"))
    fade_frames = max(1, int(round(args.fade_sec * fps)))
    tl_start = timeline.GetStartFrame()
    print(f'Timeline: "{timeline.GetName()}" fps={fps} fade={fade_frames}f')

    specs, a3_to_delete, report = build_plan(timeline, fps, fade_frames)
    print_plan(specs, report, tl_start, fps)
    if args.dry_run:
        print("\nDRY RUN - no changes made.")
        return 0

    # Render and import everything before deleting timeline clips.
    rendered_paths = []
    for spec in specs:
        rendered_paths.append(render_slice(spec, fps))
    unique_paths = sorted({p.resolve() for p in rendered_paths})

    root = pool.GetRootFolder()
    target_folder = find_subfolder(root, ("Victreebel CODEx Assets", "assets")) or root
    media_items = import_media(pool, target_folder, unique_paths)

    existing_a2 = [
        clip for clip in (timeline.GetItemListInTrack("audio", 2) or [])
        if is_existing_vba_clip(clip)
    ]
    to_delete = existing_a2 + a3_to_delete
    if to_delete:
        ok = timeline.DeleteClips(to_delete)
        print(f"Deleted existing/replaced clips: {len(to_delete)} ok={ok}")

    payload = []
    for spec in specs:
        out = spec.out_path or render_path(spec)
        item = media_items[norm_path(out.resolve())]
        payload.append({
            "mediaPoolItem": item,
            "startFrame": 0,
            "endFrame": spec.duration,
            "recordFrame": spec.record_frame,
            "trackIndex": spec.track,
            "mediaType": 2,
        })

    placed = 0
    for i in range(0, len(payload), 50):
        got = pool.AppendToTimeline(payload[i : i + 50]) or []
        placed += len(got)
    print(f"Placed: {placed}/{len(payload)}")

    report["placed_slices"] = placed
    report["expected_slices"] = len(payload)
    report["rendered_files"] = [str(p) for p in unique_paths]
    report["ok"] = placed == len(payload) and not report["warnings"]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {REPORT_PATH}")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
