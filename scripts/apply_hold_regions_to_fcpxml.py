from __future__ import annotations

"""Apply source-frame hold regions to an auto-editor FCPXML.

For each hold region, the auto-editor's micro-cut pieces inside that source
window are replaced with one continuous source span. Downstream timeline
offsets are rebuilt/rippled deterministically.

This is intended for visual-card sections in RBY Ultra Minimum Battles:
intro stats/moveset cards, post-battle data cards, final tierlist, and the
continuous V1 bed under the member carousel.

Input hold JSON may be either:
  {"regions": [{"source_start_frame": 123, "source_end_frame": 456, ...}]}
or a bare list of such objects.

Example:
  python scripts/apply_hold_regions_to_fcpxml.py input_ALTERED.fcpxml ^
    --holds _data\\rby-umb-holds.json ^
    --out output_HOLDS.fcpxml
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import apply_cuts_to_fcpxml as F


def load_holds(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("regions", data) if isinstance(data, dict) else data
    holds = []
    for i, row in enumerate(rows, start=1):
        start = row.get("source_start_frame")
        end = row.get("source_end_frame")
        if start is None or end is None:
            continue
        start = int(round(float(start)))
        end = int(round(float(end)))
        if end <= start:
            continue
        holds.append({
            "start": start,
            "end": end,
            "label": row.get("label") or f"hold_{i:02d}",
            "kind": row.get("kind") or "hold",
            "reason": row.get("reason") or "",
        })
    holds.sort(key=lambda h: (h["start"], h["end"]))

    merged: list[dict] = []
    for h in holds:
        if merged and h["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], h["end"])
            merged[-1]["label"] += f"+{h['label']}"
            if h["kind"] not in merged[-1]["kind"].split("+"):
                merged[-1]["kind"] += f"+{h['kind']}"
            continue
        merged.append(dict(h))
    return merged


def group_spine_clips(clips: list[dict], keep_refs: set[str]) -> list[dict]:
    by_offset: dict[int, list[dict]] = {}
    for clip in clips:
        if clip["ref"] in keep_refs:
            by_offset.setdefault(clip["offset"], []).append(clip)

    groups = []
    for offset in sorted(by_offset):
        refs = by_offset[offset]
        # Anchor each group by its video clip. If there is more than one kept
        # ref, all auto-editor refs at this position share the same source span.
        anchor = refs[0]
        groups.append({
            "offset": offset,
            "start": anchor["start"],
            "end": anchor["start"] + anchor["duration"],
            "duration": anchor["duration"],
            "clips": refs,
        })
    return groups


def first_intersecting_hold(holds: list[dict], src_start: int, src_end: int, hold_index: int) -> int | None:
    i = hold_index
    while i < len(holds):
        h = holds[i]
        if h["end"] <= src_start:
            i += 1
            continue
        if h["start"] >= src_end:
            return None
        return i
    return None


def emit_piece(out: list[dict], source_to_new: list[dict], group: dict,
               src_start: int, src_end: int, record_frame: int,
               role: str, label: str | None = None) -> int:
    dur = src_end - src_start
    if dur <= 0:
        return record_frame
    for clip in group["clips"]:
        out.append({
            **clip,
            "offset": record_frame,
            "start": src_start,
            "duration": dur,
            "_role": role,
            "_label": label,
        })
    source_to_new.append({
        "source_start": src_start,
        "source_end": src_end,
        "record_start": record_frame,
        "record_end": record_frame + dur,
        "role": role,
        "label": label,
    })
    return record_frame + dur


def source_at_old_timeline(groups: list[dict], frame: int) -> int | None:
    for g in groups:
        if g["offset"] <= frame < g["offset"] + g["duration"]:
            return g["start"] + (frame - g["offset"])
    return None


def new_timeline_for_source(source_to_new: list[dict], source_frame: int) -> int | None:
    for seg in source_to_new:
        if seg["source_start"] <= source_frame < seg["source_end"]:
            return seg["record_start"] + (source_frame - seg["source_start"])
    return None


def attrs_to_xml(attrs: dict[str, str]) -> str:
    ordered = []
    for key in ("name", "ref", "offset", "duration", "start", "tcFormat"):
        if key in attrs:
            ordered.append(key)
    ordered.extend(k for k in attrs if k not in ordered)
    return " ".join(
        f'{k}="{v}"'
        for k, v in ((k, attrs[k]) for k in ordered)
        if not (k == "tcFormat" and v == "")
    )


def rebuild_spine(xml: str, clips: list[dict], den: int = 60) -> str:
    indent = "\t" * 8
    lines = []
    for clip in sorted(clips, key=lambda c: (c["offset"], c["ref"])):
        attrs = dict(clip["_attrs"])
        attrs["offset"] = F.fmt_rational(int(clip["offset"]), den)
        attrs["duration"] = F.fmt_rational(int(clip["duration"]), den)
        attrs["start"] = F.fmt_rational(int(clip["start"]), den)
        lines.append(f"{indent}<asset-clip {attrs_to_xml(attrs)} />")

    body = "\n" + "\n".join(lines) + "\n" + "\t" * 5
    return re.sub(
        r"(<spine\b[^>]*>)([\s\S]*?)(</spine>)",
        lambda m: m.group(1) + body + m.group(3),
        xml,
        count=1,
    )


def remap_markers(xml: str, old_groups: list[dict], source_to_new: list[dict],
                  den: int = 60) -> tuple[str, int, int]:
    marker_pat = re.compile(r"<marker\s+([^/]+?)/>", re.DOTALL)
    kept = dropped = 0

    def repl(match: re.Match) -> str:
        nonlocal kept, dropped
        attrs = F.parse_attrs(match.group(1))
        try:
            old_frame, _ = F.parse_rational(attrs.get("start", "0s"))
        except ValueError:
            dropped += 1
            return ""
        src = source_at_old_timeline(old_groups, old_frame)
        if src is None:
            dropped += 1
            return ""
        new_frame = new_timeline_for_source(source_to_new, src)
        if new_frame is None:
            dropped += 1
            return ""
        attrs["start"] = F.fmt_rational(new_frame, den)
        kept += 1
        return f"<marker {attrs_to_xml(attrs)} />"

    return marker_pat.sub(repl, xml), kept, dropped


def update_sequence_duration(xml: str, total_frames: int, den: int = 60) -> str:
    return re.sub(
        r'(<sequence\b[^>]*\bduration=")([^"]*)(")',
        lambda m: f'{m.group(1)}{F.fmt_rational(total_frames, den)}{m.group(3)}',
        xml,
        count=1,
    )


def apply_holds(xml: str, holds: list[dict], keep_linked_audio: bool) -> tuple[str, dict]:
    all_clips = F.parse_spine_clips(xml)
    video_refs = F.find_video_refs(xml)
    if not video_refs:
        raise RuntimeError("No video refs found in FCPXML resources")

    keep_refs = {c["ref"] for c in all_clips} if keep_linked_audio else set(video_refs)
    groups = group_spine_clips(all_clips, keep_refs)
    if not groups:
        raise RuntimeError("No kept spine groups after ref filtering")

    out_clips: list[dict] = []
    source_to_new: list[dict] = []
    record = 0
    hold_index = 0
    emitted_holds: set[int] = set()

    for group in groups:
        g_start = group["start"]
        g_end = group["end"]
        cursor = g_start

        # If a hold falls entirely in an auto-editor-removed gap before this
        # group, emit it at the current record position.
        while hold_index < len(holds) and holds[hold_index]["end"] <= g_start:
            if hold_index not in emitted_holds:
                record = emit_piece(
                    out_clips,
                    source_to_new,
                    group,
                    holds[hold_index]["start"],
                    holds[hold_index]["end"],
                    record,
                    "hold",
                    holds[hold_index]["label"],
                )
                emitted_holds.add(hold_index)
            hold_index += 1

        while cursor < g_end:
            hi = first_intersecting_hold(holds, cursor, g_end, hold_index)
            if hi is None:
                record = emit_piece(out_clips, source_to_new, group, cursor, g_end, record, "auto")
                cursor = g_end
                break

            hold = holds[hi]
            if cursor < hold["start"]:
                before_end = min(g_end, hold["start"])
                record = emit_piece(out_clips, source_to_new, group, cursor, before_end, record, "auto")
                cursor = before_end
                continue

            if hi not in emitted_holds:
                record = emit_piece(
                    out_clips,
                    source_to_new,
                    group,
                    hold["start"],
                    hold["end"],
                    record,
                    "hold",
                    hold["label"],
                )
                emitted_holds.add(hi)
            cursor = max(cursor, min(g_end, hold["end"]))
            if cursor >= hold["end"] and hi == hold_index:
                hold_index += 1

    # Holds after the last kept group are unusual but valid for end cards.
    last_group = groups[-1]
    while hold_index < len(holds):
        if hold_index not in emitted_holds:
            record = emit_piece(
                out_clips,
                source_to_new,
                last_group,
                holds[hold_index]["start"],
                holds[hold_index]["end"],
                record,
                "hold",
                holds[hold_index]["label"],
            )
            emitted_holds.add(hold_index)
        hold_index += 1

    new_xml = rebuild_spine(xml, out_clips)
    new_xml, markers_kept, markers_dropped = remap_markers(new_xml, groups, source_to_new)
    new_xml = update_sequence_duration(new_xml, record)

    report = {
        "input_spine_clips": len(all_clips),
        "output_spine_clips": len(out_clips),
        "kept_refs": sorted(keep_refs),
        "keep_linked_audio": keep_linked_audio,
        "holds_requested": len(holds),
        "holds_emitted": len(emitted_holds),
        "output_frames": record,
        "markers_kept": markers_kept,
        "markers_dropped": markers_dropped,
        "source_to_new": source_to_new,
    }
    return new_xml, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fcpxml", type=Path)
    ap.add_argument("--holds", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--keep-linked-audio", action="store_true",
                    help="Preserve all auto-editor linked audio refs instead of emitting video refs only")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    xml = args.fcpxml.read_text(encoding="utf-8")
    holds = load_holds(args.holds)
    if not holds:
        raise SystemExit("No closed hold regions found; carousel-only open regions are not applied here")

    new_xml, report = apply_holds(xml, holds, args.keep_linked_audio)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(new_xml, encoding="utf-8")

    report_path = args.report or args.out.with_suffix(args.out.suffix + ".holds.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Wrote {args.out}")
    print(f"Report {report_path}")
    print(f"holds emitted {report['holds_emitted']}/{report['holds_requested']}; "
          f"duration {report['output_frames'] / 60:.2f}s; "
          f"markers kept/dropped {report['markers_kept']}/{report['markers_dropped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
