from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator.fcpxml_review import load_fcpxml_review_model


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def missing_payload(fcpxml: Path, fps: float) -> dict:
    return {
        "schema": "resolve_fcpxml_segment_review_v1",
        "status": "missing_fcpxml",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_fcpxml": str(fcpxml),
        "fps": fps,
        "segments": [],
        "instructions": [
            "Export or select an FCPXML, then load it in the Orchestrator GUI FCPXML Review tab.",
            "Mark full sections as cut only when the downstream apply tool is section-safe.",
            "Mark partial or uncertain cuts as manual_fit.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare an FCPXML segment review JSON artifact.")
    parser.add_argument("--fcpxml", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--video-only", action="store_true", default=True)
    args = parser.parse_args()

    if not args.fcpxml.exists():
        if not args.allow_missing:
            raise FileNotFoundError(args.fcpxml)
        write_json(args.out, missing_payload(args.fcpxml, args.fps))
        print(f"FCPXML missing; wrote pending review artifact: {args.out}")
        return 0

    model = load_fcpxml_review_model(args.fcpxml, fps=args.fps, video_only=args.video_only)
    payload = {
        "schema": "resolve_fcpxml_segment_review_v1",
        "status": "ready",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_fcpxml": str(args.fcpxml),
        "fps": args.fps,
        "segments": [
            {
                **segment.as_decision_row("keep"),
                "timeline_start_sec": round(segment.offset_frames / args.fps, 6),
                "timeline_end_sec": round((segment.offset_frames + segment.duration_frames) / args.fps, 6),
                "source_start_sec": round(segment.source_start_frames / args.fps, 6),
                "source_end_sec": round(segment.source_end_frames / args.fps, 6),
            }
            for segment in model.video_segments
        ],
        "decision_values": ["keep", "cut", "manual_fit"],
    }
    write_json(args.out, payload)
    print(f"Wrote FCPXML review artifact: {args.out} ({len(model.video_segments)} segment(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
