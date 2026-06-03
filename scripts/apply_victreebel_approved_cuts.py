"""Apply reviewed Victreebel cuts to the corrected Part 1/Part 2 FCPXML bases.

Input schema accepts either a JSON list or an object with `cuts` or
`approved_cuts`:

[
  {
    "part": "part2",
    "start_sec": 3430.02,
    "end_sec": 3431.70,
    "confidence": "high",
    "type": "false_start",
    "reason": "Mic check before champion attempt"
  }
]

The corrected Victreebel bases use video-only MP4 refs plus explicit `_3.wav`
dialogue refs on A1. This wrapper always preserves linked refs while applying
the same ripple operation to both refs at each FCPXML offset.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from scripts import apply_cuts_to_fcpxml as F
from scripts import build_victreebel_rby_fcpxml as B


DEFAULT_APPROVED = B.CODEX_DIR / "approved_cuts_victreebel.json"
DEFAULT_OUT_DIR = B.CODEX_DIR / "locked_editorial"
PART_INPUTS = {
    "part1": B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 1_ALTERED.fcpxml",
    "part2": B.PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2_ALTERED.fcpxml",
}


def load_approved(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data.get("cuts") or data.get("approved_cuts") or []
    else:
        raise TypeError("Approved cuts JSON must be a list or object")

    out: list[dict] = []
    for i, cut in enumerate(raw):
        if not isinstance(cut, dict):
            raise TypeError(f"Cut #{i} is not an object")
        part = cut.get("part")
        if part not in PART_INPUTS:
            raise ValueError(f"Cut #{i} has invalid part {part!r}")
        start = cut.get("start_sec", cut.get("source_start_sec"))
        end = cut.get("end_sec", cut.get("source_end_sec"))
        if start is None or end is None:
            raise ValueError(f"Cut #{i} is missing start/end seconds")
        start_f = float(start)
        end_f = float(end)
        if end_f <= start_f:
            raise ValueError(f"Cut #{i} has non-positive duration: {start_f}-{end_f}")
        out.append(
            {
                **cut,
                "part": part,
                "start_sec": start_f,
                "end_sec": end_f,
            }
        )
    return out


def by_part(cuts: list[dict]) -> dict[str, list[dict]]:
    grouped = {part: [] for part in PART_INPUTS}
    for cut in cuts:
        grouped[cut["part"]].append(cut)
    for part in grouped:
        grouped[part].sort(key=lambda c: (c["start_sec"], c["end_sec"]))
    return grouped


def with_project_label(xml: str, label: str) -> str:
    return re.sub(
        r'(<project\s+name=")([^"]*)(")',
        lambda m: f"{m.group(1)}{m.group(2)} {label}{m.group(3)}",
        xml,
        count=1,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved", type=Path, default=DEFAULT_APPROVED)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--warn-short-sec",
        type=float,
        default=0.2,
        help="Warn for approved cuts shorter than this duration; do not reject.",
    )
    args = parser.parse_args()

    approved_path = args.approved.resolve()
    if not approved_path.exists():
        print(f"ERROR: approved cuts file not found: {approved_path}", file=sys.stderr)
        print("Create it after review, then re-run this wrapper.", file=sys.stderr)
        return 1

    cuts = load_approved(approved_path)
    grouped = by_part(cuts)
    short = [
        c for c in cuts
        if float(c["end_sec"]) - float(c["start_sec"]) < args.warn_short_sec
    ]
    if short:
        print(f"WARN: {len(short)} approved cut(s) are shorter than {args.warn_short_sec}s")
        for c in short[:20]:
            print(
                f"  {c['part']} {c['start_sec']:.3f}-{c['end_sec']:.3f} "
                f"{c.get('type', '')}: {c.get('reason', '')[:90]}"
            )

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = out_dir / "approved_cuts_normalized.json"
    normalized_path.write_text(json.dumps(cuts, indent=2, ensure_ascii=False), encoding="utf-8")

    replay = {
        "approved_cuts": str(approved_path),
        "normalized_cuts": str(normalized_path),
        "parts": {},
    }
    outputs = {}

    for part, fcpxml in PART_INPUTS.items():
        part_cuts = grouped[part]
        print(f"\n{part}: {len(part_cuts)} approved cut(s)")
        if not fcpxml.exists():
            raise FileNotFoundError(fcpxml)
        xml = fcpxml.read_text(encoding="utf-8")
        labeled = with_project_label(xml, "(locked editorial)")
        out_xml, part_replay = F.apply_cuts(
            labeled,
            part_cuts,
            keep_linked_audio=True,
        )
        out_path = out_dir / f"{part}_LOCKED_ALTERED.fcpxml"
        outputs[part] = str(out_path)
        replay["parts"][part] = {
            "source_fcpxml": str(fcpxml),
            "locked_fcpxml": str(out_path),
            "approved_cuts": part_cuts,
            "replay": part_replay,
        }
        if args.dry_run:
            print(f"  DRY RUN: would write {out_path}")
        else:
            out_path.write_text(out_xml, encoding="utf-8")
            print(f"  Wrote {out_path}")

    replay["outputs"] = outputs
    replay_path = out_dir / "cut_replay.json"
    marker_remap_path = out_dir / "marker_remap.json"
    if not args.dry_run:
        replay_path.write_text(json.dumps(replay, indent=2, ensure_ascii=False), encoding="utf-8")
        marker_remap_path.write_text(
            json.dumps(
                {
                    "note": "Part-local replay only. Combined marker remap is derived in the heavy rebuild from cut_replay.json.",
                    "cut_replay": str(replay_path),
                    "parts": {
                        part: data["replay"].get("removed_tl_ranges_frames", [])
                        for part, data in replay["parts"].items()
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nReplay metadata: {replay_path}")
        print(f"Marker remap stub: {marker_remap_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
