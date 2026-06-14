from __future__ import annotations

import argparse
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


STRUCTURAL_NAME_HINTS = (
    "blue version intro",
    "rby outro",
    "__2x_resolve2.mp4",
    "-battle-intro.mov",
    "battle intro",
)


def ffprobe(path: Path) -> dict:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(proc.stdout)


def parse_rate(rate: str | None) -> Fraction:
    if not rate or rate == "0/0":
        return Fraction(0, 1)
    if "/" in rate:
        num, den = rate.split("/", 1)
        return Fraction(int(num), int(den))
    return Fraction(rate)


def video_info(path: Path, timeline_fps: Fraction) -> dict:
    data = ffprobe(path)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not stream:
        raise RuntimeError(f"No video stream: {path}")
    media_fps = parse_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    if media_fps <= 0:
        media_fps = timeline_fps
    native_frames = int(stream.get("nb_frames") or 0)
    if native_frames > 0:
        duration_sec = Fraction(native_frames, 1) / media_fps
    else:
        duration_sec = Fraction(str(stream.get("duration") or data["format"]["duration"]))
        native_frames = int(round(duration_sec * media_fps))
    expected_timeline_frames = int(round(duration_sec * timeline_fps))
    return {
        "codec": stream.get("codec_name"),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "media_fps": float(media_fps),
        "native_frames": native_frames,
        "duration_sec": float(duration_sec),
        "expected_timeline_frames": expected_timeline_frames,
    }


def source_path(item) -> Path | None:
    mpi = item.GetMediaPoolItem()
    if not mpi:
        return None
    try:
        raw = mpi.GetClipProperty("File Path") or ""
    except Exception:
        raw = ""
    return Path(raw) if raw else None


def source_name(item) -> str:
    mpi = item.GetMediaPoolItem()
    if mpi:
        try:
            return mpi.GetName() or item.GetName()
        except Exception:
            pass
    return item.GetName()


def is_structural_clip(name: str, path: Path | None) -> bool:
    haystack = f"{name} {path or ''}".lower()
    return any(hint in haystack for hint in STRUCTURAL_NAME_HINTS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", default="")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--tolerance", type=int, default=1)
    args = parser.parse_args()

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Resolve scripting connection failed")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No current Resolve project")
    timeline = project.GetCurrentTimeline()
    if args.timeline:
        for index in range(1, project.GetTimelineCount() + 1):
            candidate = project.GetTimelineByIndex(index)
            if candidate and candidate.GetName() == args.timeline:
                timeline = candidate
                project.SetCurrentTimeline(timeline)
                break
    if not timeline:
        raise RuntimeError("No current timeline")

    timeline_fps = Fraction(str(project.GetSetting("timelineFrameRate") or "60"))
    clips = []
    violations = []
    for track_index in range(1, timeline.GetTrackCount("video") + 1):
        for clip in timeline.GetItemListInTrack("video", track_index) or []:
            name = source_name(clip)
            path = source_path(clip)
            if not is_structural_clip(name, path):
                continue
            record_start = int(clip.GetStart())
            record_end = int(clip.GetEnd())
            placed_frames = record_end - record_start
            record = {
                "track": f"V{track_index}",
                "name": name,
                "path": str(path) if path else None,
                "record_start": record_start,
                "record_end": record_end,
                "placed_frames": placed_frames,
            }
            if path and path.exists():
                info = video_info(path, timeline_fps)
                delta = placed_frames - info["expected_timeline_frames"]
                record.update(info)
                record["delta_frames"] = delta
                if abs(delta) > args.tolerance:
                    violations.append(
                        {
                            "name": name,
                            "path": str(path),
                            "placed_frames": placed_frames,
                            "expected_timeline_frames": info["expected_timeline_frames"],
                            "delta_frames": delta,
                            "media_fps": info["media_fps"],
                        }
                    )
            else:
                record["warning"] = "source path missing or not found"
                violations.append({"name": name, "path": str(path) if path else None, "issue": record["warning"]})
            clips.append(record)

    report = {
        "project": project.GetName(),
        "timeline": timeline.GetName(),
        "timeline_fps": float(timeline_fps),
        "timeline_start": timeline.GetStartFrame(),
        "timeline_end": timeline.GetEndFrame(),
        "structural_video_clips": clips,
        "violations": violations,
        "ok": not violations,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
