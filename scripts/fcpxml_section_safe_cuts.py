"""
Review cut candidates against FCPXML sections.

Policy:
- If a candidate covers an entire FCPXML video section, mark that section safe
  for automatic removal.
- If a candidate only overlaps part of a section, do not cut it automatically;
  color the matching V1 clip Pink for manual review.

The safe output is section-offset based metadata plus a source-time JSON that is
only used for reporting. The companion apply script consumes the section
metadata so repeated source ranges are not accidentally removed elsewhere.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import apply_cuts_to_fcpxml as F


def _load_cuts(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _video_sections(xml: str) -> list[dict]:
    clips = F.parse_spine_clips(xml)
    video_refs = F.find_video_refs(xml) or ({clips[0]["ref"]} if clips else set())
    sections = []
    for c in clips:
        if c["ref"] not in video_refs:
            continue
        sections.append({
            "offset": c["offset"],
            "duration": c["duration"],
            "start": c["start"],
            "end": c["start"] + c["duration"],
            "name": c.get("name", ""),
            "ref": c["ref"],
        })
    return sorted(sections, key=lambda s: s["offset"])


def _candidate_sections(cuts: list[dict], sections: list[dict],
                        fps: int, tol_frames: int) -> tuple[list[dict], list[dict]]:
    safe_by_offset: dict[int, dict] = {}
    review_by_offset: dict[int, dict] = {}

    for idx, cut in enumerate(cuts):
        cs = int(round(float(cut["start_sec"]) * fps))
        ce = int(round(float(cut["end_sec"]) * fps))
        if ce <= cs:
            continue

        for sec in sections:
            os = max(cs, sec["start"])
            oe = min(ce, sec["end"])
            if oe <= os:
                continue

            covers_whole = cs <= sec["start"] + tol_frames and ce >= sec["end"] - tol_frames
            entry = {
                "candidate_index": idx,
                "candidate_start_sec": float(cut["start_sec"]),
                "candidate_end_sec": float(cut["end_sec"]),
                "confidence": cut.get("confidence", ""),
                "type": cut.get("type", ""),
                "reason": cut.get("reason", ""),
                "section_offset": sec["offset"],
                "section_duration": sec["duration"],
                "section_start": sec["start"],
                "section_end": sec["end"],
                "section_start_sec": sec["start"] / fps,
                "section_end_sec": sec["end"] / fps,
                "overlap_start": os,
                "overlap_end": oe,
            }
            if covers_whole:
                # If a section is already marked for manual review, keep it
                # manual. A partial overlap anywhere makes it unsafe.
                if sec["offset"] not in review_by_offset:
                    safe_by_offset[sec["offset"]] = entry
            else:
                review_by_offset[sec["offset"]] = entry
                safe_by_offset.pop(sec["offset"], None)

    return list(safe_by_offset.values()), list(review_by_offset.values())


def _color_review_clips(review: list[dict], clear_existing: bool) -> int:
    if not review:
        return 0
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError("Could not connect to DaVinci Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("No active timeline")

    review_offsets = {r["section_offset"] for r in review}
    colored = 0
    for clip in sorted(timeline.GetItemListInTrack("video", 1) or [], key=lambda c: c.GetStart()):
        if clear_existing and clip.GetClipColor() in ("Orange", "Yellow", "Pink"):
            clip.ClearClipColor()
        if clip.GetStart() in review_offsets:
            if clip.SetClipColor("Pink"):
                colored += 1
    return colored


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("fcpxml", help="Input FCPXML, normally *_ALTERED_BATTLEGAPS.fcpxml")
    ap.add_argument("--cuts", required=True, help="cut-analysis JSON")
    ap.add_argument("--out", default=None,
                    help="Safe metadata output (default: <fcpxml>_SECTION_SAFE_CUTS.json)")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--tol-frames", type=int, default=1)
    ap.add_argument("--color-review", action="store_true",
                    help="Color partial-overlap V1 clips Pink in the current Resolve timeline")
    ap.add_argument("--clear-existing-colors", action="store_true",
                    help="Clear Orange/Yellow/Pink V1 colors before coloring review clips")
    args = ap.parse_args()

    fcpxml = Path(args.fcpxml).resolve()
    cuts_path = Path(args.cuts).resolve()
    out_path = Path(args.out).resolve() if args.out else fcpxml.with_name(fcpxml.stem + "_SECTION_SAFE_CUTS.json")

    xml = fcpxml.read_text(encoding="utf-8")
    cuts = _load_cuts(cuts_path)
    sections = _video_sections(xml)
    safe, review = _candidate_sections(cuts, sections, args.fps, args.tol_frames)

    safe_source_cuts = [
        {
            "start_sec": round(s["section_start_sec"], 6),
            "end_sec": round(s["section_end_sec"], 6),
            "confidence": s["confidence"],
            "type": "fcpxml_section_delete",
            "reason": f"Whole FCPXML section covered by candidate #{s['candidate_index']}: {s['reason']}",
            "section_offset": s["section_offset"],
        }
        for s in safe
    ]

    payload = {
        "source_fcpxml": str(fcpxml),
        "source_cuts": str(cuts_path),
        "fps": args.fps,
        "safe_section_deletes": safe,
        "manual_review_sections": review,
        "safe_source_cuts": safe_source_cuts,
        "counts": {
            "input_candidates": len(cuts),
            "safe_section_deletes": len(safe),
            "manual_review_sections": len(review),
        },
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Input candidates:       {len(cuts)}")
    print(f"FCPXML video sections:  {len(sections)}")
    print(f"Safe section deletes:   {len(safe)}")
    print(f"Manual review sections: {len(review)}")
    print(f"Wrote: {out_path}")

    if args.color_review:
        colored = _color_review_clips(review, args.clear_existing_colors)
        print(f"Pink review clips colored on current timeline: {colored}/{len(review)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
