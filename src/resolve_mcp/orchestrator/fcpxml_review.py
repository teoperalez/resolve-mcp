from __future__ import annotations

import json
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_fcpxml_time(value: str | None) -> Fraction:
    if not value or value == "0s":
        return Fraction(0, 1)
    raw = value.strip()
    if not raw.endswith("s"):
        raise ValueError(f"FCPXML time does not end with 's': {value!r}")
    raw = raw[:-1]
    if "/" in raw:
        num, den = raw.split("/", 1)
        return Fraction(int(num), int(den))
    return Fraction(raw)


def seconds_to_frames(seconds: Fraction, fps: float) -> int:
    return int(round(float(seconds) * fps))


@dataclass(frozen=True)
class FCPXMLAsset:
    id: str
    name: str = ""
    src: str = ""
    has_video: bool = False
    has_audio: bool = False


@dataclass(frozen=True)
class FCPXMLSegment:
    id: str
    offset_frames: int
    duration_frames: int
    source_start_frames: int
    ref: str
    name: str = ""
    source_path: str = ""
    lane: str = ""
    is_video: bool = False

    @property
    def source_end_frames(self) -> int:
        return self.source_start_frames + self.duration_frames

    def as_decision_row(self, decision: str = "keep", note: str = "") -> dict[str, Any]:
        return {
            "segment_id": self.id,
            "decision": decision,
            "note": note,
            "offset_frames": self.offset_frames,
            "duration_frames": self.duration_frames,
            "source_start_frames": self.source_start_frames,
            "source_end_frames": self.source_end_frames,
            "ref": self.ref,
            "name": self.name,
            "source_path": self.source_path,
        }


@dataclass
class FCPXMLReviewModel:
    path: Path
    fps: float
    assets: dict[str, FCPXMLAsset]
    segments: list[FCPXMLSegment] = field(default_factory=list)

    @property
    def video_segments(self) -> list[FCPXMLSegment]:
        return [segment for segment in self.segments if segment.is_video]

    def write_decisions(self, path: Path, decisions: dict[str, dict[str, Any]]) -> None:
        payload = {
            "schema": "resolve_fcpxml_segment_decisions_v1",
            "source_fcpxml": str(self.path),
            "fps": self.fps,
            "decisions": list(decisions.values()),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_fcpxml_review_model(path: Path, fps: float = 60.0, video_only: bool = True) -> FCPXMLReviewModel:
    tree = ET.parse(path)
    root = tree.getroot()
    assets = _read_assets(root)
    segments: list[FCPXMLSegment] = []

    for index, elem in enumerate(root.iter(), start=1):
        if _tag_name(elem.tag) != "asset-clip":
            continue
        ref = elem.attrib.get("ref", "")
        asset = assets.get(ref, FCPXMLAsset(id=ref))
        is_video = asset.has_video
        if video_only and not is_video:
            continue
        offset = seconds_to_frames(parse_fcpxml_time(elem.attrib.get("offset")), fps)
        duration = seconds_to_frames(parse_fcpxml_time(elem.attrib.get("duration")), fps)
        start = seconds_to_frames(parse_fcpxml_time(elem.attrib.get("start")), fps)
        name = elem.attrib.get("name") or asset.name or ref
        lane = elem.attrib.get("lane", "")
        segment_id = f"seg-{offset}-{ref}-{index}"
        segments.append(
            FCPXMLSegment(
                id=segment_id,
                offset_frames=offset,
                duration_frames=duration,
                source_start_frames=start,
                ref=ref,
                name=name,
                source_path=asset.src,
                lane=lane,
                is_video=is_video,
            )
        )
    segments.sort(key=lambda item: (item.offset_frames, item.ref))
    return FCPXMLReviewModel(path=path, fps=fps, assets=assets, segments=segments)


def _read_assets(root: ET.Element) -> dict[str, FCPXMLAsset]:
    assets: dict[str, FCPXMLAsset] = {}
    for elem in root.iter():
        if _tag_name(elem.tag) != "asset":
            continue
        asset_id = elem.attrib.get("id")
        if not asset_id:
            continue
        src = ""
        for child in elem.iter():
            if _tag_name(child.tag) == "media-rep":
                src = child.attrib.get("src", "")
                break
        assets[asset_id] = FCPXMLAsset(
            id=asset_id,
            name=elem.attrib.get("name", ""),
            src=src,
            has_video=elem.attrib.get("hasVideo") == "1",
            has_audio=elem.attrib.get("hasAudio") == "1",
        )
    return assets
