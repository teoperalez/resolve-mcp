from __future__ import annotations

"""Place the RBY Ultra Minimum Battles A2 bed.

This intentionally differs from the generic random BGM script. The Golem-style
RBY UMB formula is:

  - opening: fixed lo-fi sequence, usually Dual Screen Lovelife -> Aurora Rising
  - gauntlet gaps: synchronized console/game audio, not random BGM
  - leader battles: preserve already-placed A2 battle-theme clips
  - leader intro stings on A3 create intentional A2 silence under the intro
  - ending: fixed lo-fi sequence over final tierlist/member carousel

Run this after leader/battle audio has been placed on A2/A3. It deletes old
non-protected A2 clips, renders faded WAV slices, imports them, and places them
around the protected battle-theme ranges.

Example:
  python scripts/place_rby_umb_bgm.py ^
    --game-audio "E:\\Run\\tracks\\Run_2.wav" ^
    --dry-run

Use --end-at-timeline-end for runs that do not have a discrete outro clip at
the end of V1.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401


DEFAULT_BGM_DIR = Path(r"C:\Programming\RBYNewLayout\audio\bgm")
DEFAULT_OPENING = ["Dual Screen Lovelife", "Aurora Rising"]
DEFAULT_ENDING = [
    "Dual Screen Lovelife",
    "Motivated By Clouds",
    "Roll Me in Stardust",
    "Skyline Scroller",
]
CACHE_DIR = Path.home() / ".resolve-mcp" / "cache" / "rby-umb-bgm"
REPORT_PATH = Path("_data") / "qa-reports" / "rby-umb-bgm.json"
MIN_SEGMENT_FRAMES = 12


@dataclass
class Segment:
    role: str
    label: str
    source: Path
    source_start: int
    duration: int
    record_frame: int
    fade_in: int
    fade_out: int
    out_path: str | None = None


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
    return max(1, int(round(float(data["format"]["duration"]) * fps)))


def find_audio_file(root: Path, stem: str) -> Path:
    wanted = stem.lower()
    candidates = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".wav", ".mp3", ".m4a", ".aac", ".flac"}:
            continue
        if path.stem.lower() == wanted or path.name.lower() == wanted:
            candidates.append(path)
    if not candidates:
        raise RuntimeError(f"Could not find BGM track {stem!r} under {root}")
    return sorted(candidates, key=lambda p: (len(str(p)), str(p).lower()))[0]


def clip_source_path(item) -> str:
    getter = getattr(item, "GetMediaPoolItem", None)
    mpi = getter() if callable(getter) else item
    if not mpi:
        return ""
    try:
        return mpi.GetClipProperty("File Path") or ""
    except Exception:
        return ""


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


def import_media(pool, target_folder, paths: list[Path]) -> dict[str, object]:
    wanted = {norm_path(p.resolve()): p for p in paths}
    found = {}
    for item in walk_media(pool.GetRootFolder()):
        p = norm_path(clip_source_path(item))
        if p in wanted:
            found[p] = item

    missing = [p for key, p in wanted.items() if key not in found]
    if missing:
        previous = pool.GetCurrentFolder()
        pool.SetCurrentFolder(target_folder)
        for i in range(0, len(missing), 25):
            pool.ImportMedia([str(p) for p in missing[i:i + 25]]) or []
        if previous:
            pool.SetCurrentFolder(previous)

    for item in walk_media(pool.GetRootFolder()):
        p = norm_path(clip_source_path(item))
        if p in wanted:
            found[p] = item

    unresolved = [str(p) for key, p in wanted.items() if key not in found]
    if unresolved:
        raise RuntimeError("Could not import media: " + json.dumps(unresolved, indent=2))
    return found


def protected_a2_clip(item, extra_regex: re.Pattern | None) -> bool:
    name = item.GetName() or ""
    path = clip_source_path(item).replace("\\", "/").lower()
    if name.lower().startswith("vba_a2_"):
        return True
    if "/victreebel-battle-audio/" in path:
        return True
    return bool(extra_regex and extra_regex.search(name))


def collect_ranges(items) -> list[tuple[int, int, str]]:
    ranges = []
    for item in items:
        start = item.GetStart()
        end = start + item.GetDuration()
        if end > start:
            ranges.append((start, end, item.GetName() or ""))
    return sorted(ranges)


def merge_blocked(ranges: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    for start, end, label in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end), out[-1][2] + "+" + label)
        else:
            out.append((start, end, label))
    return out


def complement(start: int, end: int, blocked: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    gaps = []
    cur = start
    for b0, b1, _label in blocked:
        if b1 <= start or b0 >= end:
            continue
        b0 = max(b0, start)
        b1 = min(b1, end)
        if b0 - cur >= MIN_SEGMENT_FRAMES:
            gaps.append((cur, b0))
        cur = max(cur, b1)
    if end - cur >= MIN_SEGMENT_FRAMES:
        gaps.append((cur, end))
    return gaps


def split_gaps_at(gaps: list[tuple[int, int]], cut_points: list[int]) -> list[tuple[int, int]]:
    pieces: list[tuple[int, int]] = []
    for start, end in gaps:
        points = [start, end]
        points.extend(p for p in cut_points if start < p < end)
        points = sorted(set(points))
        for a, b in zip(points, points[1:]):
            if b - a >= MIN_SEGMENT_FRAMES:
                pieces.append((a, b))
    return pieces


def marker_abs_frames(timeline) -> list[tuple[int, str, str]]:
    tl_start = timeline.GetStartFrame()
    out = []
    for rel, data in (timeline.GetMarkers() or {}).items():
        out.append((tl_start + int(round(float(rel))), data.get("name") or "", data.get("note") or ""))
    return sorted(out)


def first_marker(markers: list[tuple[int, str, str]], predicate) -> int | None:
    for frame, name, note in markers:
        if predicate(name, note):
            return frame
    return None


def last_marker(markers: list[tuple[int, str, str]], predicate) -> int | None:
    for frame, name, note in reversed(markers):
        if predicate(name, note):
            return frame
    return None


def dominant_v1_source(v1) -> str:
    counts: dict[str, int] = {}
    for item in v1:
        path = Path(clip_source_path(item)).name
        if path:
            counts[path] = counts.get(path, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0] if counts else ""


def norm_source_key(path: str | Path) -> str:
    return str(path).replace("\\", "/").lower()


def parse_source_offsets(rows: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        if "=" not in row:
            raise SystemExit(f"Invalid --source-audio-offset value {row!r}; expected SOURCE=FRAMES")
        key, value = row.split("=", 1)
        key = norm_source_key(key.strip())
        try:
            frames = int(value.strip())
        except ValueError as exc:
            raise SystemExit(f"Invalid frame offset in --source-audio-offset {row!r}") from exc
        if not key:
            raise SystemExit(f"Invalid empty source key in --source-audio-offset {row!r}")
        out[key] = frames
    return out


def offset_for_source(source_path: str, offsets: dict[str, int]) -> int | None:
    if not offsets:
        return 0
    full = norm_source_key(source_path)
    name = Path(source_path).name.lower()
    stem = Path(source_path).stem.lower()
    for key, frames in offsets.items():
        if key in {full, name, stem} or key in full:
            return frames
    return None


def build_v1_map(v1, dominant_name: str, fps: float,
                 source_offsets: dict[str, int] | None = None) -> list[dict]:
    out = []
    for item in v1:
        src_path = clip_source_path(item)
        src_name = Path(src_path).name
        source_offset = offset_for_source(src_path, source_offsets or {})
        if source_offsets:
            if source_offset is None:
                continue
        elif src_name != dominant_name:
            continue
        out.append({
            "record_start": item.GetStart(),
            "record_end": item.GetStart() + item.GetDuration(),
            "source_start": item.GetLeftOffset() + int(source_offset or 0),
            "source_end": item.GetLeftOffset() + item.GetDuration() + int(source_offset or 0),
            "name": item.GetName() or "",
            "source_path": src_path,
            "source_offset": int(source_offset or 0),
        })
    return sorted(out, key=lambda r: r["record_start"])


def source_for_record(v1_map: list[dict], record_frame: int) -> int | None:
    for row in v1_map:
        if row["record_start"] <= record_frame < row["record_end"]:
            return row["source_start"] + (record_frame - row["record_start"])
    for row in v1_map:
        if row["record_start"] > record_frame:
            return row["source_start"]
    return None


def clamp_fades(duration: int, fade_in: int, fade_out: int) -> tuple[int, int]:
    fade_in = max(0, min(fade_in, duration))
    fade_out = max(0, min(fade_out, duration))
    if fade_in + fade_out > duration:
        half = max(1, duration // 2)
        fade_in = min(fade_in, half)
        fade_out = min(fade_out, duration - fade_in)
    return fade_in, fade_out


def render_segment(seg: Segment, fps: float) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / (
        f"rbyumb_{safe_name(seg.role)}_{safe_name(seg.label)}"
        f"__{safe_name(seg.source.stem)}"
        f"__s{seg.source_start}_d{seg.duration}"
        f"__fi{seg.fade_in}_fo{seg.fade_out}.wav"
    )
    seg.out_path = str(out)
    if out.exists():
        return out

    fade_in, fade_out = clamp_fades(seg.duration, seg.fade_in, seg.fade_out)
    start_sec = seg.source_start / fps
    dur_sec = seg.duration / fps
    filters = []
    if fade_in:
        filters.append(f"afade=t=in:st=0:d={fade_in / fps:.6f}:curve=hsin")
    if fade_out:
        fade_start = max(0.0, dur_sec - fade_out / fps)
        filters.append(f"afade=t=out:st={fade_start:.6f}:d={fade_out / fps:.6f}:curve=hsin")
    afilter = ",".join(filters) if filters else "anull"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_sec:.6f}",
        "-i",
        str(seg.source),
        "-t",
        f"{dur_sec:.6f}",
        "-af",
        afilter,
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 or not out.exists():
        tail = "\n".join(proc.stderr.splitlines()[-8:])
        raise RuntimeError(f"ffmpeg failed for {seg.label}:\n{tail}")
    return out


def append_music_sequence(
    segments: list[Segment],
    *,
    role: str,
    stems: list[str],
    bgm_dir: Path,
    record_start: int,
    record_end: int,
    fps: float,
    fade_frames: int,
    first_source_offset: int = 0,
) -> int:
    cur = record_start
    for idx, stem in enumerate(stems):
        if record_end - cur < MIN_SEGMENT_FRAMES:
            break
        path = find_audio_file(bgm_dir, stem)
        total = media_duration_frames(path, fps)
        src = first_source_offset if idx == 0 else 0
        src = max(0, min(src, total - 1))
        dur = min(record_end - cur, total - src)
        if dur < MIN_SEGMENT_FRAMES:
            continue
        segments.append(Segment(
            role=role,
            label=f"{idx + 1:02d}_{stem}",
            source=path,
            source_start=src,
            duration=dur,
            record_frame=cur,
            fade_in=0 if cur == record_start else fade_frames,
            fade_out=fade_frames,
        ))
        cur += dur
    return cur


def append_game_audio(
    segments: list[Segment],
    *,
    game_audio: Path,
    game_audio_frames: int,
    v1_map: list[dict],
    record_start: int,
    record_end: int,
    fps: float,
    fade_frames: int,
    label: str,
) -> None:
    dur = record_end - record_start
    if dur < MIN_SEGMENT_FRAMES:
        return
    src = source_for_record(v1_map, record_start)
    if src is None:
        return
    src = max(0, min(src, max(0, game_audio_frames - 1)))
    dur = min(dur, game_audio_frames - src)
    if dur < MIN_SEGMENT_FRAMES:
        return
    segments.append(Segment(
        role="game_audio_bridge",
        label=label,
        source=game_audio,
        source_start=src,
        duration=dur,
        record_frame=record_start,
        fade_in=fade_frames,
        fade_out=fade_frames,
    ))


def parse_sequence(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def marker_name_has(name: str, text: str) -> bool:
    return text.lower() in (name or "").lower()


def segment_report(seg: Segment) -> dict:
    row = asdict(seg)
    row["source"] = str(seg.source)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game-audio", type=Path, required=True,
                    help="console/game-audio WAV used for between-battle bridges")
    ap.add_argument("--bgm-dir", type=Path, default=DEFAULT_BGM_DIR)
    ap.add_argument("--opening-sequence", default=",".join(DEFAULT_OPENING))
    ap.add_argument("--ending-sequence", default=",".join(DEFAULT_ENDING))
    ap.add_argument("--opening-first-source-offset-sec", type=float, default=0.0,
                    help="trim the first opening BGM source by this many seconds")
    ap.add_argument("--source-audio-offset", action="append", default=[],
                    help=(
                        "Map a V1 source into a combined --game-audio file, as "
                        "SOURCE=FRAMES. SOURCE may be a filename, stem, or path "
                        "substring. Repeat for split recordings."
                    ))
    ap.add_argument("--fade-sec", type=float, default=1.0)
    ap.add_argument("--track-index", type=int, default=2)
    ap.add_argument("--protect-name-regex", default=None,
                    help="extra A2 clip-name regex to preserve as battle music")
    ap.add_argument("--end-at-timeline-end", "--no-outro", dest="end_at_timeline_end",
                    action="store_true",
                    help="Fill through timeline end instead of treating the last V1 clip as an outro.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", type=Path, default=REPORT_PATH)
    args = ap.parse_args()

    if not args.game_audio.exists():
        raise SystemExit(f"Missing --game-audio file: {args.game_audio}")

    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    pool = project.GetMediaPool()
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No current timeline")

    fps = float(project.GetSetting("timelineFrameRate"))
    fade_frames = max(1, int(round(args.fade_sec * fps)))
    tl_start = timeline.GetStartFrame()
    print(f'Timeline: "{timeline.GetName()}" fps={fps} fade={fade_frames}f')

    while timeline.GetTrackCount("audio") < args.track_index:
        if args.dry_run:
            break
        timeline.AddTrack("audio", "stereo")

    v1 = sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda c: c.GetStart())
    if args.end_at_timeline_end:
        if not v1:
            raise RuntimeError("V1 has no gameplay clips")
        outro_start = timeline.GetEndFrame()
        print(f"Fill end: timeline end {outro_start}")
    else:
        if len(v1) < 2:
            raise RuntimeError("V1 needs gameplay plus outro, or use --end-at-timeline-end")
        outro_start = v1[-1].GetStart()
        print(f"Fill end: last V1/outro start {outro_start}")
    dominant = dominant_v1_source(v1)
    source_offsets = parse_source_offsets(args.source_audio_offset)
    if source_offsets:
        print("Source offsets into combined game audio:")
        for key, frames in sorted(source_offsets.items()):
            print(f"  {key} -> {frames}f ({frames / fps:.3f}s)")
    v1_map = build_v1_map(v1, dominant, fps, source_offsets)
    if not v1_map:
        raise RuntimeError("Could not build dominant V1 source map")
    mapped_sources = sorted({Path(row["source_path"]).name for row in v1_map})
    print("Mapped V1 source(s): " + ", ".join(mapped_sources))

    extra_re = re.compile(args.protect_name_regex, re.I) if args.protect_name_regex else None
    a2_items = sorted(timeline.GetItemListInTrack("audio", args.track_index) or [], key=lambda c: c.GetStart())
    protected_a2 = [c for c in a2_items if protected_a2_clip(c, extra_re)]
    delete_a2 = [c for c in a2_items if c not in protected_a2]
    a3_items = sorted(timeline.GetItemListInTrack("audio", 3) or [], key=lambda c: c.GetStart())

    markers = marker_abs_frames(timeline)
    first_battle = first_marker(markers, lambda name, _note: marker_name_has(name, "Battle Start"))
    last_battle_finish = last_marker(markers, lambda name, _note: marker_name_has(name, "Battle Finish"))

    blocked = merge_blocked(
        collect_ranges(protected_a2)
        + [(s, e, "A3:" + label) for s, e, label in collect_ranges(a3_items) if s < outro_start]
    )
    gaps = complement(tl_start, outro_start, blocked)
    opening_end = first_battle or (gaps[0][1] if gaps else tl_start)
    ending_start = last_battle_finish or (blocked[-1][1] if blocked else opening_end)
    opening_end = max(tl_start, min(opening_end, outro_start))
    ending_start = max(opening_end, min(ending_start, outro_start))
    gap_pieces = split_gaps_at(gaps, [opening_end, ending_start])

    game_audio_frames = media_duration_frames(args.game_audio, fps)
    opening = parse_sequence(args.opening_sequence)
    ending = parse_sequence(args.ending_sequence)
    first_bgm_offset = int(round(args.opening_first_source_offset_sec * fps))

    segments: list[Segment] = []
    for idx, (g0, g1) in enumerate(gap_pieces, start=1):
        if g1 <= opening_end:
            cur = append_music_sequence(
                segments,
                role="opening_bgm",
                stems=opening,
                bgm_dir=args.bgm_dir,
                record_start=g0,
                record_end=g1,
                fps=fps,
                fade_frames=fade_frames,
                first_source_offset=first_bgm_offset if g0 == tl_start else 0,
            )
            if cur < g1:
                append_game_audio(
                    segments,
                    game_audio=args.game_audio,
                    game_audio_frames=game_audio_frames,
                    v1_map=v1_map,
                    record_start=cur,
                    record_end=g1,
                    fps=fps,
                    fade_frames=fade_frames,
                    label=f"opening_tail_{idx:02d}",
                )
        elif g0 >= ending_start:
            cur = append_music_sequence(
                segments,
                role="ending_bgm",
                stems=ending,
                bgm_dir=args.bgm_dir,
                record_start=g0,
                record_end=g1,
                fps=fps,
                fade_frames=fade_frames,
            )
            if cur < g1:
                append_game_audio(
                    segments,
                    game_audio=args.game_audio,
                    game_audio_frames=game_audio_frames,
                    v1_map=v1_map,
                    record_start=cur,
                    record_end=g1,
                    fps=fps,
                    fade_frames=fade_frames,
                    label=f"ending_tail_{idx:02d}",
                )
        else:
            append_game_audio(
                segments,
                game_audio=args.game_audio,
                game_audio_frames=game_audio_frames,
                v1_map=v1_map,
                record_start=g0,
                record_end=g1,
                fps=fps,
                fade_frames=fade_frames,
                label=f"bridge_{idx:02d}",
            )

    print(f"Protected A2 battle clips: {len(protected_a2)}")
    print(f"Old non-protected A2 clips to delete: {len(delete_a2)}")
    print(f"Blocked ranges (A2 battle + A3 stings): {len(blocked)}")
    print(f"Gaps to fill: {len(gaps)} ({len(gap_pieces)} after opening/ending split)")
    print(f"Planned new A2 segments: {len(segments)}")
    for seg in segments:
        print(
            f"  rel={(seg.record_frame - tl_start) / fps:8.2f}s "
            f"dur={seg.duration / fps:7.2f}s src={seg.source.name} "
            f"src_in={seg.source_start / fps:7.2f}s {seg.role}:{seg.label}"
        )

    report = {
        "timeline": timeline.GetName(),
        "fps": fps,
        "game_audio": str(args.game_audio),
        "dominant_v1_source": dominant,
        "end_mode": "timeline_end" if args.end_at_timeline_end else "last_v1_as_outro",
        "outro_start_abs": outro_start,
        "opening_end_abs": opening_end,
        "ending_start_abs": ending_start,
        "protected_a2_count": len(protected_a2),
        "delete_a2_count": len(delete_a2),
        "blocked_ranges": blocked,
        "gaps": gaps,
        "gap_pieces": gap_pieces,
        "segments": [segment_report(s) for s in segments],
    }

    if args.dry_run:
        print("\nDRY RUN - no changes made.")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {args.report}")
        return 0

    rendered = [render_segment(seg, fps) for seg in segments]
    root = pool.GetRootFolder()
    target_folder = find_subfolder(root, ("Mewtwo CODEx Assets", "Victreebel CODEx Assets", "assets")) or root
    media = import_media(pool, target_folder, sorted({p.resolve() for p in rendered}))

    if delete_a2:
        ok = timeline.DeleteClips(delete_a2)
        print(f"Deleted old non-protected A2 clips: {len(delete_a2)} ok={ok}")

    payload = []
    for seg in segments:
        out = Path(seg.out_path or "")
        item = media[norm_path(out.resolve())]
        payload.append({
            "mediaPoolItem": item,
            "startFrame": 0,
            "endFrame": seg.duration,
            "recordFrame": seg.record_frame,
            "trackIndex": args.track_index,
            "mediaType": 2,
        })

    placed = 0
    for i in range(0, len(payload), 50):
        got = pool.AppendToTimeline(payload[i:i + 50]) or []
        placed += len(got)
    report["placed"] = placed
    report["expected"] = len(payload)
    report["rendered_files"] = [str(p) for p in sorted({p.resolve() for p in rendered})]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Placed: {placed}/{len(payload)}")
    print(f"Report: {args.report}")
    return 0 if placed == len(payload) else 2


if __name__ == "__main__":
    raise SystemExit(main())
