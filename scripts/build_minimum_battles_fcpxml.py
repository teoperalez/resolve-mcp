from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator import DEFAULT_WORKFLOW_CONFIG, load_catalog
from resolve_mcp.orchestrator.fcpxml_review import load_fcpxml_review_model


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def norm_file_uri(uri: str) -> str:
    if uri.startswith("file:///"):
        return uri[8:].replace("%20", " ").replace("/", "\\")
    return uri


def source_name_from_path(path: str) -> str:
    return Path(norm_file_uri(path)).name


def build_review_base(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.config)
    profile = catalog.profile(args.profile)
    mapping = profile.mapping(catalog.repo)
    fps = float(mapping.get("timeline_fps") or 60)

    parts_manifest_path = Path(mapping["parts_manifest"])
    parts_manifest = read_json(parts_manifest_path)
    parts = parts_manifest.get("parts") or []
    if not parts:
        raise SystemExit(f"No parts in {parts_manifest_path}")
    if len(parts) != 1:
        raise SystemExit(
            "The first implemented review-base slice supports the profile's combined source export. "
            f"Got {len(parts)} parts. Use a combined source/FCPXML profile or implement multi-part stitching next."
        )

    part = parts[0]
    source_media = Path(part["source_media"])
    raw_fcpxml = Path(part["fcpxml"])
    dialogue_audio = Path(part["dialogue_audio"])
    if not raw_fcpxml.exists():
        raise FileNotFoundError(raw_fcpxml)
    if not source_media.exists():
        raise FileNotFoundError(source_media)
    if not dialogue_audio.exists():
        raise FileNotFoundError(dialogue_audio)

    review_fcpxml = Path(mapping["review_fcpxml"])
    review_manifest = Path(mapping["review_manifest"])
    html_clips = Path(mapping["html_clips"])
    source_map_path = Path(mapping["source_map"])

    review_fcpxml.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(raw_fcpxml, review_fcpxml)

    model = load_fcpxml_review_model(review_fcpxml, fps=fps, video_only=True)
    rows: list[dict[str, Any]] = []
    source_map_rows: list[dict[str, Any]] = []
    for index, segment in enumerate(model.video_segments):
        src = norm_file_uri(segment.source_path) or str(source_media)
        row = {
            "i": index,
            "timeline_i": index,
            "name": segment.name or source_name_from_path(src) or source_media.name,
            "start": segment.offset_frames,
            "dur": segment.duration_frames,
            "left": segment.source_start_frames,
            "combined_left": segment.source_start_frames,
            "fps": fps,
            "color": "",
            "src": src,
            "role": "minimum_battles_review_section",
            "part": 1,
            "part_source_left": segment.source_start_frames,
            "segment_id": segment.id,
        }
        rows.append(row)
        source_map_rows.append(
            {
                "i": index,
                "segment_id": segment.id,
                "review_start_frame": segment.offset_frames,
                "review_end_frame": segment.offset_frames + segment.duration_frames,
                "part_index": 1,
                "source_media": str(source_media),
                "source_start_frame": segment.source_start_frames,
                "source_end_frame": segment.source_end_frames,
            }
        )

    timeline_duration = max((row["start"] + row["dur"] for row in rows), default=0)
    clips_payload = {
        "schema": "minimum_battles_review_clips_v1",
        "generated_at": now(),
        "profile": profile.id,
        "timeline": mapping.get("profile_name") or profile.name,
        "timeline_start_frame": 0,
        "fps": fps,
        "source_video": str(source_media),
        "dialogue_audio": str(dialogue_audio),
        "clips": rows,
    }
    write_json(html_clips, clips_payload)
    write_json(
        source_map_path,
        {
            "schema": "minimum_battles_source_map_v1",
            "generated_at": now(),
            "profile": profile.id,
            "fps": fps,
            "review_fcpxml": str(review_fcpxml),
            "source_video": str(source_media),
            "dialogue_audio": str(dialogue_audio),
            "timeline_duration_frames": timeline_duration,
            "clips": source_map_rows,
        },
    )
    write_json(
        review_manifest,
        {
            "schema": "minimum_battles_review_base_manifest_v1",
            "generated_at": now(),
            "profile": profile.id,
            "stage": "review_base",
            "timeline_name": mapping.get("profile_name") or profile.name,
            "fps": fps,
            "source_video": str(source_media),
            "dialogue_audio": str(dialogue_audio),
            "raw_autoeditor_fcpxml": str(raw_fcpxml),
            "review_base_fcpxml": str(review_fcpxml),
            "clips": str(html_clips),
            "source_map": str(source_map_path),
            "timeline_duration_frames": timeline_duration,
            "clip_count": len(rows),
            "parts_manifest": str(parts_manifest_path),
        },
    )
    print(f"Wrote review FCPXML: {review_fcpxml}")
    print(f"Wrote review manifest: {review_manifest}")
    print(f"Wrote review clips: {html_clips}")
    print(f"Wrote source map: {source_map_path}")
    print(f"Review clips: {len(rows)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build generic minimum-battles review/final FCPXML artifacts.")
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("ORCHESTRATOR_CONFIG_PATH") or DEFAULT_WORKFLOW_CONFIG))
    parser.add_argument("--profile", default=os.environ.get("ORCHESTRATOR_PROFILE_ID") or "")
    parser.add_argument("--review-base", action="store_true")
    args = parser.parse_args()
    if not args.profile:
        raise SystemExit("No profile supplied. Use --profile or ORCHESTRATOR_PROFILE_ID.")
    if args.review_base:
        return build_review_base(args)
    raise SystemExit("No build mode selected. Use --review-base.")


if __name__ == "__main__":
    raise SystemExit(main())
