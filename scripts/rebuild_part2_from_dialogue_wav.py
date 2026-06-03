from __future__ import annotations

"""Build a clean Part 2 FCPXML from auto-editor cuts made on dialogue WAV.

Auto-editor originally cut the Victreebel Part 2 timeline from the MP4's first
audio stream, while the rebuilt timeline intentionally places the extracted
``part 2_3.wav`` dialogue on A1. This utility takes the raw WAV-only Resolve
FCPXML exported by auto-editor and mirrors those intervals onto the Part 2 MP4
video plus the same dialogue WAV, producing a V1+A1-safe source FCPXML.
"""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import build_victreebel_rby_fcpxml as B


PROJECT_DIR = B.PROJECT_DIR
PART2_VIDEO = PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2.mp4"
PART2_DIALOGUE = B.PART2_DIALOGUE
FPS = B.FPS


def read_intervals(raw_fcpxml: Path) -> list[dict]:
    root = ET.parse(raw_fcpxml).getroot()
    intervals = []
    for ac in root.findall(".//spine/asset-clip"):
        start = B.parse_time_to_frames(ac.get("start", "0s"))
        duration = B.parse_time_to_frames(ac.get("duration", "0s"))
        offset = B.parse_time_to_frames(ac.get("offset", "0s"))
        if duration <= 0:
            continue
        intervals.append({"offset": offset, "start": start, "duration": duration})
    intervals.sort(key=lambda x: (x["offset"], x["start"], x["duration"]))
    if not intervals:
        raise RuntimeError(f"No intervals found in {raw_fcpxml}")
    return intervals


def asset_xml(asset_id: str, path: Path, duration: int, has_video: bool, has_audio: bool) -> str:
    attrs = [
        f'id="{asset_id}"',
        f'name="{B.escape(path.stem)}"',
        f'src="{B.path_to_uri(path)}"',
        'start="0s"',
        f'duration="{B.frames_to_time(duration)}"',
        f'hasVideo="{"1" if has_video else "0"}"',
        f'hasAudio="{"1" if has_audio else "0"}"',
        'format="r1"',
    ]
    if has_audio:
        attrs.extend(['audioSources="1"', 'audioChannels="2"', 'audioRate="48000"'])
    if has_video:
        attrs.append('videoSources="1"')
    return (
        f'  <asset {" ".join(attrs)}>\n'
        f'    <media-rep kind="original-media" src="{B.path_to_uri(path)}"/>\n'
        "  </asset>"
    )


def write_clean_fcpxml(raw_fcpxml: Path, out_fcpxml: Path) -> dict:
    intervals = read_intervals(raw_fcpxml)
    video_frames = B.media_duration_frames(PART2_VIDEO)
    audio_frames = B.media_duration_frames(PART2_DIALOGUE)
    total_frames = max(i["offset"] + i["duration"] for i in intervals)

    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        '<fcpxml version="1.11">',
        "  <resources>",
        f'    <format height="1080" id="r1" colorSpace="1-1-1 (Rec. 709)" name="FFVideoFormatRateUndefined" width="1920" frameDuration="1/{FPS}s"/>',
        asset_xml("r2", PART2_DIALOGUE, audio_frames, has_video=False, has_audio=True),
        asset_xml("r4", PART2_VIDEO, video_frames, has_video=True, has_audio=False),
        "  </resources>",
        "  <library>",
        '    <event name="Auto-Editor Media Group">',
        '      <project name="Victreebel Red and Blue Ultra Minimum Battles part 2_3">',
        f'        <sequence tcStart="0s" format="r1" tcFormat="NDF" duration="{B.frames_to_time(total_frames)}" audioLayout="stereo" audioRate="48k">',
        "          <spine>",
    ]
    for interval in intervals:
        offset = B.frames_to_time(interval["offset"])
        start = B.frames_to_time(interval["start"])
        duration = B.frames_to_time(interval["duration"])
        name = B.escape("Victreebel Red and Blue Ultra Minimum Battles part 2_3")
        lines.append(
            f'            <asset-clip offset="{offset}" duration="{duration}" tcFormat="NDF" start="{start}" name="{name}" ref="r2"/>'
        )
        lines.append(
            f'            <asset-clip offset="{offset}" duration="{duration}" tcFormat="NDF" start="{start}" name="{name}" ref="r4"/>'
        )
    lines.extend([
        "          </spine>",
        "        </sequence>",
        "      </project>",
        "    </event>",
        "  </library>",
        "</fcpxml>",
        "",
    ])
    out_fcpxml.write_text("\n".join(lines), encoding="utf-8")
    return {
        "raw_autoeditor_fcpxml": str(raw_fcpxml),
        "clean_fcpxml": str(out_fcpxml),
        "basis": "auto-editor part 2_3.wav --margin 0.1sec --time-base 60 --export resolve",
        "dialogue_wav": str(PART2_DIALOGUE),
        "video_src": str(PART2_VIDEO),
        "interval_count": len(intervals),
        "asset_clip_count": len(intervals) * 2,
        "edited_duration_frames_60fps": total_frames,
        "edited_duration_seconds": total_frames / FPS,
        "first_interval": intervals[0],
        "last_interval": intervals[-1],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_fcpxml", type=Path)
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--validation", type=Path)
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = write_clean_fcpxml(args.raw_fcpxml, args.out)
    validation = args.validation or args.out.with_suffix(".validation.json")
    validation.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
