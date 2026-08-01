"""
Apply V1 recap holds to an FCPXML — AFTER all cut decisions are final.

For each APPROVED recap region (from detect_recap_regions.py + human review),
merge the run of video spine clips inside the region into ONE clip:

  * timeline extent  = unchanged (first clip's offset .. last clip's end);
    audio timing stays authoritative — the edit's length does not change.
  * source anchor    = first clip's source start; the held clip plays the
    static screen 1:1 from there.
  * audio clips      = untouched. Their silence cuts remain, so the region
    becomes audio-only cuts under one continuous video clip (no visible
    jump-cuts on the static screen).
  * exit             = the next video clip after the region keeps its own
    synced source anchor, so A/V sync resumes instantly (the source-time
    drift accumulated during the hold is absorbed at that cut).

Must run AFTER approved cuts (and battle-gap insertion, if used) have been
applied to the FCPXML, and BEFORE importing the timeline into Resolve.

Usage:
    python apply_recap_holds_to_fcpxml.py INPUT.fcpxml \
        --regions CODEx/recap_regions/recap_regions.json \
        [--part 6] [-o OUTPUT.fcpxml] [--report report.json] [--no-markers]

Multi-part projects run this once per part FCPXML with --part N (only that
part's approved regions are applied), or once on the combined FCPXML with
region source times already remapped to the combined source space.
"""
import sys
import os
import re
import json
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from insert_battle_gaps_fcpxml import (  # noqa: E402
    parse_rational, fmt_rational, parse_spine_clips,
)


def approved_regions(regions_path: Path, part: str | None) -> list[dict]:
    data = json.loads(regions_path.read_text(encoding="utf-8"))
    regs = data.get("regions", data if isinstance(data, list) else [])
    out = []
    for r in regs:
        if r.get("status") != "approved":
            continue
        if part is not None and str(r.get("part")) != str(part):
            continue
        out.append(r)
    return out


def apply_holds(xml: str, regions: list[dict], den: int = 60,
                add_markers: bool = True) -> tuple[str, list[dict]]:
    clips = parse_spine_clips(xml)
    if not clips:
        raise ValueError("No spine clips found")

    refs_in_order: list[str] = []
    seen: set[str] = set()
    for c in clips:
        if c["ref"] not in seen:
            seen.add(c["ref"])
            refs_in_order.append(c["ref"])
    video_ref = refs_in_order[0]

    video_clips = sorted((c for c in clips if c["ref"] == video_ref),
                         key=lambda c: c["offset"][0])

    report = []
    removed_ids: set[int] = set()
    markers = []

    for reg in sorted(regions, key=lambda r: float(r["source_start_sec"])):
        t0u = int(round(float(reg["source_start_sec"]) * den))
        t1u = int(round(float(reg["source_end_sec"]) * den))
        # select video clips whose SOURCE midpoint falls inside the region
        run = [c for c in video_clips
               if id(c) not in removed_ids
               and t0u <= c["start"][0] + c["duration"][0] // 2 < t1u]
        entry = {
            "id": reg.get("id"),
            "source_start_sec": reg["source_start_sec"],
            "source_end_sec": reg["source_end_sec"],
            "clips_in_region": len(run),
        }
        if len(run) < 2:
            entry["result"] = "skipped"
            entry["reason"] = (
                "fewer than 2 video clips in region — nothing to merge "
                "(already held, or region misses the edit)")
            report.append(entry)
            print(f"  [{reg.get('id')}] SKIP: {entry['reason']}")
            continue

        # verify timeline contiguity of the run (holes break the hold)
        holes = []
        for a, b in zip(run, run[1:]):
            a_end = a["offset"][0] + a["duration"][0]
            if b["offset"][0] != a_end:
                holes.append((a_end, b["offset"][0]))
        if holes:
            entry["result"] = "skipped"
            entry["reason"] = f"video not contiguous inside region: holes at {holes[:3]}"
            report.append(entry)
            print(f"  [{reg.get('id')}] SKIP: {entry['reason']}")
            continue

        first, last = run[0], run[-1]
        tl_start = first["offset"][0]
        tl_end = last["offset"][0] + last["duration"][0]
        merged_dur = tl_end - tl_start

        # source-availability: held clip consumes source frames
        # [first.start, first.start + merged_dur). Because silence was only
        # ever REMOVED, merged_dur <= source span of the region, so the top
        # end can never exceed the last clip's source end. Assert anyway.
        src_needed_end = first["start"][0] + merged_dur
        src_region_end = last["start"][0] + last["duration"][0]
        if src_needed_end > src_region_end:
            entry["result"] = "skipped"
            entry["reason"] = (f"source underrun: hold needs source up to "
                               f"{src_needed_end}u but region source ends at "
                               f"{src_region_end}u")
            report.append(entry)
            print(f"  [{reg.get('id')}] SKIP: {entry['reason']}")
            continue

        # merge: first clip absorbs the whole run
        first["duration"] = (merged_dur, den)
        for c in run[1:]:
            removed_ids.add(id(c))

        # exit drift = source jump at the cut out of the hold
        nxt = next((c for c in video_clips
                    if id(c) not in removed_ids and c["offset"][0] >= tl_end), None)
        drift = (nxt["start"][0] - src_needed_end) if nxt else 0

        entry.update({
            "result": "applied",
            "clips_merged": len(run),
            "timeline_start_frame": tl_start,
            "timeline_end_frame": tl_end,
            "timeline_dur_sec": round(merged_dur / den, 3),
            "source_anchor_sec": round(first["start"][0] / den, 3),
            "exit_source_drift_sec": round(drift / den, 3),
        })
        report.append(entry)
        if add_markers:
            markers.append({
                "offset_n": tl_start,
                "name": f"Recap Hold: {reg.get('id')}",
            })
        print(f"  [{reg.get('id')}] merged {len(run)} clips -> 1 "
              f"({merged_dur / den:.1f}s timeline, exit drift {drift / den:.1f}s)")

    # ── rewrite spine, preserving every non-removed clip ──
    indent = "\t" * 8
    new_lines = []
    for c in clips:
        if id(c) in removed_ids:
            continue
        attrs = dict(c["_attrs"])
        attrs["offset"] = fmt_rational(c["offset"][0], den)
        attrs["duration"] = fmt_rational(c["duration"][0], den)
        attrs["start"] = fmt_rational(c["start"][0], den)
        ordered = [k for k in ("name", "ref", "offset", "duration", "start",
                               "tcFormat") if k in attrs]
        ordered += [k for k in attrs if k not in ordered]
        pairs = [f'{k}="{attrs[k]}"' for k in ordered
                 if attrs[k] != "" or k in ("start", "offset", "duration")]
        pairs = [p for p in pairs if p != 'tcFormat=""']
        new_lines.append(f'{indent}<asset-clip {" ".join(pairs)} />')

    new_spine_body = "\n" + "\n".join(new_lines) + "\n" + "\t" * 7
    new_xml = re.sub(
        r"(<spine\b[^>]*>)([\s\S]*?)(</spine>)",
        lambda m: m.group(1) + new_spine_body + m.group(3),
        xml,
        count=1,
    )

    if markers:
        blob = "".join(
            f'<marker start="{fmt_rational(m["offset_n"], den)}" '
            f'duration="1/{den}s" value="{m["name"]}" completed="0" />'
            for m in markers
        )
        new_xml = re.sub(
            r"(</spine>)(\s*)(</sequence>)",
            lambda m: f"{m.group(1)}{blob}{m.group(2)}{m.group(3)}",
            new_xml,
            count=1,
        )

    return new_xml, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("--regions", type=Path, required=True)
    ap.add_argument("--part", default=None,
                    help="Only apply regions of this part label")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="Default: <input>_RECAPHOLDS.fcpxml")
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--den", type=int, default=60)
    ap.add_argument("--no-markers", action="store_true")
    args = ap.parse_args()

    regions = approved_regions(args.regions, args.part)
    if not regions:
        print("No APPROVED regions"
              + (f" for part {args.part}" if args.part else "")
              + " — nothing to do. (Regions must have status='approved'.)")
        # Still a success for orchestration: pass-through copy.
        out = args.output or args.input.with_name(
            args.input.stem + "_RECAPHOLDS.fcpxml")
        out.write_text(args.input.read_text(encoding="utf-8"), encoding="utf-8")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(
                {"input": str(args.input), "applied": [],
                 "note": "no approved regions"}, indent=2), encoding="utf-8")
        print(f"wrote pass-through {out}")
        return 0

    xml = args.input.read_text(encoding="utf-8")
    print(f"{args.input.name}: applying {len(regions)} approved region(s)")
    new_xml, report = apply_holds(xml, regions, den=args.den,
                                  add_markers=not args.no_markers)

    out = args.output or args.input.with_name(args.input.stem + "_RECAPHOLDS.fcpxml")
    out.write_text(new_xml, encoding="utf-8")
    print(f"wrote {out}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(
            {"input": str(args.input), "output": str(out), "applied": report},
            indent=2), encoding="utf-8")
        print(f"wrote {args.report}")

    failed = [r for r in report if r.get("result") == "skipped"]
    if failed:
        print(f"WARNING: {len(failed)} region(s) skipped — check the report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
