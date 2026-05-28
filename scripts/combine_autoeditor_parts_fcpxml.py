"""Combine multiple auto-editor FCPXML parts into one video-only FCPXML.

This is for split recordings that should behave as one source file in the
editing pipeline. The output references a pre-concatenated media file, keeps
only the video asset-clips from each input FCPXML, shifts later parts on the
timeline, and shifts later parts' source starts by the raw duration of the
earlier parts.
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_time_frames(value: str, den: int = 60) -> int:
    value = (value or "0s").strip()
    if value == "0s":
        return 0
    m = re.fullmatch(r"(\d+)/(\d+)s", value)
    if m:
        num, in_den = int(m.group(1)), int(m.group(2))
        return round(num * den / in_den)
    m = re.fullmatch(r"(\d+)s", value)
    if m:
        return int(m.group(1)) * den
    raise ValueError(f"Cannot parse FCPXML time {value!r}")


def fmt_time(frames: int, den: int = 60) -> str:
    return "0s" if frames == 0 else f"{frames}/{den}s"


def attrs_from_match(attr_text: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=\"([^\"]*)\"", attr_text))


def media_path_from_asset(asset: ET.Element) -> str:
    rep = asset.find("media-rep")
    return rep.get("src", "") if rep is not None else ""


def local_path_from_file_uri(uri: str) -> str:
    if uri.startswith("file:///"):
        raw = uri[8:]
        return raw.replace("/", "\\")
    return uri


def file_uri(path: Path) -> str:
    return "file:///" + str(path.resolve()).replace("\\", "/").replace(" ", "%20")


def parse_part(path: Path, den: int) -> dict:
    xml = path.read_text(encoding="utf-8")
    root = ET.fromstring(xml)
    resources = root.find("resources")
    if resources is None:
        raise ValueError(f"{path} has no <resources>")

    video_assets = []
    for asset in resources.findall("asset"):
        if asset.get("hasVideo") == "1":
            video_assets.append(asset)
    if len(video_assets) != 1:
        raise ValueError(f"{path} expected exactly one video asset, found {len(video_assets)}")
    video = video_assets[0]
    video_ref = video.get("id")
    raw_duration = parse_time_frames(video.get("duration", "0s"), den)
    source_name = video.get("name") or path.stem
    source_uri = media_path_from_asset(video)

    clips = []
    for m in re.finditer(r"<asset-clip\s+([^>]+?)\s*/>", xml, re.S):
        attrs = attrs_from_match(m.group(1))
        if attrs.get("ref") != video_ref:
            continue
        clips.append({
            "name": attrs.get("name", source_name),
            "offset": parse_time_frames(attrs.get("offset", "0s"), den),
            "duration": parse_time_frames(attrs.get("duration", "0s"), den),
            "start": parse_time_frames(attrs.get("start", "0s"), den),
            "tcFormat": attrs.get("tcFormat", "NDF"),
        })

    if not clips:
        raise ValueError(f"{path} has no video clips for ref {video_ref}")
    edited_duration = max(c["offset"] + c["duration"] for c in clips)

    return {
        "path": str(path),
        "source_name": source_name,
        "source_uri": source_uri,
        "source_path": local_path_from_file_uri(source_uri),
        "raw_duration_frames": raw_duration,
        "edited_duration_frames": edited_duration,
        "clips": clips,
    }


def build_fcpxml(parts: list[dict], combined_media: Path, project_name: str, den: int) -> str:
    combined_duration = sum(p["raw_duration_frames"] for p in parts)
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        '<fcpxml version="1.11">',
        "  <resources>",
        f'    <format height="1080" id="r1" colorSpace="1-1-1 (Rec. 709)" '
        f'name="FFVideoFormatRateUndefined" width="1920" frameDuration="1/{den}s" />',
        f'    <asset audioSources="1" format="r1" duration="{fmt_time(combined_duration, den)}" '
        f'id="r2" audioChannels="2" hasAudio="1" start="0s" '
        f'name="{escape_attr(combined_media.stem)}" hasVideo="1">',
        f'      <media-rep src="{file_uri(combined_media)}" kind="original-media" />',
        "    </asset>",
        "  </resources>",
        "  <library>",
        '    <event name="Codex Combined Media">',
        f'      <project name="{escape_attr(project_name)}">',
        '        <sequence tcStart="0s" format="r1" tcFormat="NDF" audioLayout="stereo" audioRate="48k">',
        "          <spine>",
    ]

    timeline_shift = 0
    source_shift = 0
    for idx, part in enumerate(parts, start=1):
        part_name = f"part {idx}"
        for c in part["clips"]:
            offset = timeline_shift + c["offset"]
            start = source_shift + c["start"]
            lines.append(
                f'                <asset-clip name="{escape_attr(project_name)} {part_name}" '
                f'ref="r2" offset="{fmt_time(offset, den)}" '
                f'duration="{fmt_time(c["duration"], den)}" '
                f'start="{fmt_time(start, den)}" tcFormat="{c["tcFormat"]}" />'
            )
        timeline_shift += part["edited_duration_frames"]
        source_shift += part["raw_duration_frames"]

    lines += [
        "          </spine>",
        "        </sequence>",
        "      </project>",
        "    </event>",
        "  </library>",
        "</fcpxml>",
        "",
    ]
    return "\n".join(lines)


def escape_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--combined-media", required=True, type=Path)
    ap.add_argument("--project-name", required=True)
    ap.add_argument("-o", "--output", required=True, type=Path)
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--den", type=int, default=60)
    args = ap.parse_args()

    parts = [parse_part(p, args.den) for p in args.inputs]
    xml = build_fcpxml(parts, args.combined_media, args.project_name, args.den)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(xml, encoding="utf-8")

    manifest = {
        "project_name": args.project_name,
        "combined_media": str(args.combined_media),
        "output_fcpxml": str(args.output),
        "timeline_duration_frames": sum(p["edited_duration_frames"] for p in parts),
        "raw_source_duration_frames": sum(p["raw_duration_frames"] for p in parts),
        "parts": parts,
    }
    manifest_path = args.manifest or args.output.with_suffix(".combine_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {args.output}")
    print(f"Wrote {manifest_path}")
    print(f"Parts: {len(parts)}")
    print(f"Edited duration: {manifest['timeline_duration_frames'] / args.den:.2f}s")
    print(f"Raw source duration: {manifest['raw_source_duration_frames'] / args.den:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
