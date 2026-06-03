from __future__ import annotations

"""Color V1 clips and timeline markers by content section.

This replaces trainer-specific marker colors with editing-category colors:

  Orange  intro/outro source assets
  Lime    leader intro + battle UI sections
  Teal    rival in-battle sections
  Purple  V1-only post-battle tiercard/data-card holds
  Apricot final tierlist views
  Green   member carousel V1 bed

Only V1 clip colors and ruler marker colors are changed. No media, edits, audio,
or clip timing is modified.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr


DEFAULT_REPORT = Path(
    r"E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx"
    r"\visual_tiercard_pass\section_color_report.json"
)
DEFAULT_REBUILD_REPORT_DIR = Path(
    r"E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\full_api_rebuild"
)

COLORS = {
    "intro": "Orange",
    "leader_battle": "Lime",
    "rival_battle": "Teal",
    "tiercard": "Purple",
    "tierlist": "Apricot",
    "member_carousel": "Green",
}

# Fallback for the pre-corrected manual visual pass. Corrected rebuilds write
# source-offset hold data to full_api_rebuild/*_report.json; prefer that data so
# colors track the FCPXML base currently on the timeline.
EXTRA_INTRO_RANGES = [
    {"label": "Opening highlighted cards", "start": 2056, "end": 10328},
]

LOG_HOLD_SOURCES = {
    "part1": "Victreebel Red and Blue Ultra Minimum Battles part 1.mp4",
    "part2": "Victreebel Red and Blue Ultra Minimum Battles part 2.mp4",
}

LOG_HOLD_KIND = {
    "intro_stats_card": ("intro", "Opening stats card"),
    "intro_moveset_card": ("intro", "Opening moveset card"),
    "post_battle_data_card_01": ("tiercard", "Brock"),
    "post_battle_data_card_02": ("tiercard", "Misty"),
    "post_battle_data_card_03": ("tiercard", "Erika"),
    "post_battle_data_card_04": ("tiercard", "Lt. Surge"),
    "post_battle_data_card_05": ("tiercard", "Giovanni"),
    "post_battle_data_card_06": ("tiercard", "Koga"),
    "post_battle_data_card_07": ("tiercard", "Sabrina"),
    "post_battle_data_card_08": ("tiercard", "Blaine"),
    "final_tierlist": ("tierlist", "Final Tierlist"),
}

MARKER_COLORS = {
    "intro": "Sand",
    "leader_battle": "Lemon",
    "rival_battle": "Cyan",
    "tiercard": "Purple",
    "tierlist": "Cream",
    "member_carousel": "Green",
}

VALID_MARKER_COLORS = {
    "Blue",
    "Cyan",
    "Green",
    "Yellow",
    "Red",
    "Pink",
    "Purple",
    "Fuchsia",
    "Rose",
    "Lavender",
    "Sky",
    "Mint",
    "Lemon",
    "Sand",
    "Cocoa",
    "Cream",
}

DEFAULT_UNCLASSIFIED_MARKER_COLORS = {
    "First Pokemon": "Mint",
}

PRIORITY = {
    "intro": 70,
    "leader_battle": 20,
    "rival_battle": 30,
    "tierlist": 40,
    "member_carousel": 50,
    "tiercard": 60,
}


def clip_path(item) -> str:
    media = item.GetMediaPoolItem()
    if not media:
        return ""
    try:
        return media.GetClipProperty("File Path") or ""
    except Exception:
        return ""


def clip_name(item) -> str:
    return Path(clip_path(item)).name or item.GetName()


def normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def marker_rows(timeline) -> list[dict[str, Any]]:
    rows = []
    for rel, data in (timeline.GetMarkers() or {}).items():
        rel_int = int(round(float(rel)))
        rows.append(
            {
                "rel": rel_int,
                "name": data.get("name") or "",
                "note": data.get("note") or "",
                "color": data.get("color") or "",
                "duration": int(data.get("duration") or 1),
                "customData": data.get("customData") or "",
            }
        )
    rows.sort(key=lambda row: (row["rel"], row["name"]))
    return rows


def first_marker(markers: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((m for m in markers if m["name"] == name), None)


def markers_named(markers: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [m for m in markers if m["name"] == name]


def parse_tiercard_holds(markers: list[dict[str, Any]], timeline_end_rel: int) -> list[dict[str, Any]]:
    holds = []
    prefix = "Visual Tiercard V1 Hold Start:"
    for marker in markers:
        name = marker["name"]
        if not name.startswith(prefix):
            continue
        label = name.removeprefix(prefix).strip()
        duration_match = re.search(r"\bdur=(\d+)\b", marker["note"])
        if duration_match:
            end = marker["rel"] + int(duration_match.group(1))
        else:
            candidates = [m["rel"] for m in markers if m["rel"] > marker["rel"]]
            end = min(candidates) if candidates else timeline_end_rel
        holds.append(
            {
                "kind": "tiercard",
                "label": label,
                "start": marker["rel"],
                "end": end,
                "color": COLORS["tiercard"],
                "priority": PRIORITY["tiercard"],
            }
        )
    return holds


def match_tiercard_for_leader(leader: str, holds: list[dict[str, Any]]) -> dict[str, Any] | None:
    leader_key = normalize_label(leader)
    aliases = {
        "surge": {"ltsurge", "surge"},
        "ltsurge": {"ltsurge", "surge"},
    }
    keys = aliases.get(leader_key, {leader_key})
    for hold in holds:
        if normalize_label(hold["label"]) in keys:
            return hold
    return None


def next_non_rival_finish(
    markers: list[dict[str, Any]], after_rel: int, before_rel: int | None = None
) -> dict[str, Any] | None:
    for marker in markers:
        if marker["rel"] <= after_rel:
            continue
        if before_rel is not None and marker["rel"] >= before_rel:
            return None
        name = marker["name"]
        if name.endswith(" Battle Finish") and not name.startswith("Rival "):
            return marker
    return None


def previous_retimed_intro_start(v1_items: list[Any], start_frame: int, battle_rel: int) -> int | None:
    best = None
    for item in v1_items:
        name = clip_name(item).lower()
        if "__2x_resolve2" not in name:
            continue
        start = int(item.GetStart()) - start_frame
        end = start + int(item.GetDuration())
        if end <= battle_rel and battle_rel - end <= 5:
            if best is None or start > best:
                best = start
    return best


def find_v1_outro_start(v1_items: list[Any], start_frame: int, fallback_rel: int) -> int:
    for item in v1_items:
        if "outro" in clip_name(item).lower():
            return int(item.GetStart()) - start_frame
    return fallback_rel


def is_intro_outro_asset(item) -> bool:
    name = clip_name(item).lower()
    return "intro" in name or "outro" in name


def rebuild_report_for_timeline(timeline_name: str) -> Path | None:
    exact = DEFAULT_REBUILD_REPORT_DIR / f"{timeline_name}_report.json"
    if exact.exists():
        return exact
    candidates = sorted(
        DEFAULT_REBUILD_REPORT_DIR.glob("*_report.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("timeline") == timeline_name:
            return path
    return None


def clip_ranges_for_log_hold(
    v1_items: list[Any],
    start_frame: int,
    source_name: str,
    hold: dict[str, Any],
) -> list[tuple[int, int]]:
    source_start = int(hold["start"])
    duration = int(hold["record_duration"])
    exact = []
    loose = []
    for item in v1_items:
        if Path(clip_path(item)).name != source_name:
            continue
        if int(item.GetLeftOffset()) != source_start:
            continue
        start = int(item.GetStart()) - start_frame
        end = start + int(item.GetDuration())
        if int(item.GetDuration()) == duration:
            exact.append((start, end))
        else:
            loose.append((start, end))
    return exact or loose


def load_log_hold_ranges(timeline, start_frame: int, v1_items: list[Any]) -> list[dict[str, Any]]:
    report_path = rebuild_report_for_timeline(timeline.GetName())
    if not report_path:
        return []
    data = json.loads(report_path.read_text(encoding="utf-8"))
    ranges: list[dict[str, Any]] = []
    for part, source_name in LOG_HOLD_SOURCES.items():
        holds = ((data.get("log_holds") or {}).get(part) or {}).get("holds") or []
        for hold in holds:
            mapped = LOG_HOLD_KIND.get(hold.get("label"))
            if not mapped:
                continue
            kind, label = mapped
            for start, end in clip_ranges_for_log_hold(v1_items, start_frame, source_name, hold):
                ranges.append(
                    {
                        "kind": kind,
                        "label": label,
                        "start": start,
                        "end": end,
                        "color": COLORS[kind],
                        "priority": PRIORITY[kind],
                        "source": "log_holds",
                        "report": str(report_path),
                    }
                )
    return ranges


def build_ranges(timeline, start_frame: int) -> list[dict[str, Any]]:
    markers = marker_rows(timeline)
    v1_items = timeline.GetItemListInTrack("video", 1) or []
    timeline_end_rel = int(timeline.GetEndFrame()) - start_frame
    ranges: list[dict[str, Any]] = []
    log_hold_ranges = load_log_hold_ranges(timeline, start_frame, v1_items)

    rival_starts = markers_named(markers, "Rival Battle Start")
    rival_finishes = markers_named(markers, "Rival Battle Finish")
    for item in v1_items:
        if not is_intro_outro_asset(item):
            continue
        start = int(item.GetStart()) - start_frame
        end = start + int(item.GetDuration())
        ranges.append(
            {
                "kind": "intro",
                "label": "Intro/Outro asset",
                "start": start,
                "end": end,
                "color": COLORS["intro"],
                "priority": PRIORITY["intro"],
            }
        )
    ranges.extend(log_hold_ranges)
    if not any(r["kind"] == "intro" and r.get("source") == "log_holds" for r in log_hold_ranges):
        for item in EXTRA_INTRO_RANGES:
            ranges.append(
                {
                    "kind": "intro",
                    "label": item["label"],
                    "start": item["start"],
                    "end": item["end"],
                    "color": COLORS["intro"],
                    "priority": PRIORITY["intro"],
                }
            )

    marker_tiercard_holds = parse_tiercard_holds(markers, timeline_end_rel)
    ranges.extend(marker_tiercard_holds)
    tiercard_holds = [
        r for r in log_hold_ranges if r["kind"] == "tiercard"
    ] + marker_tiercard_holds

    rival_gap_markers = [
        m
        for m in markers
        if m["name"] == "Non-boss Battle Gap" and "Rival Battle Start" in m["note"]
    ]
    for start_marker in rival_starts:
        finish = next((m for m in rival_finishes if m["rel"] > start_marker["rel"]), None)
        if not finish:
            continue
        gap = next(
            (
                m
                for m in rival_gap_markers
                if 0 <= start_marker["rel"] - m["rel"] <= 10
            ),
            None,
        )
        ranges.append(
            {
                "kind": "rival_battle",
                "label": "Rival",
                "start": gap["rel"] if gap else start_marker["rel"],
                "end": finish["rel"],
                "color": COLORS["rival_battle"],
                "priority": PRIORITY["rival_battle"],
            }
        )

    leader_starts = [m for m in markers if m["name"].endswith(" Leader Intro Start")]
    handled_leaders = {
        normalize_label(m["name"].removesuffix(" Leader Intro Start"))
        for m in leader_starts
    }
    for idx, start_marker in enumerate(leader_starts):
        leader = start_marker["name"].removesuffix(" Leader Intro Start")
        next_leader_rel = (
            leader_starts[idx + 1]["rel"] if idx + 1 < len(leader_starts) else None
        )
        hold = match_tiercard_for_leader(leader, tiercard_holds)
        finish = next_non_rival_finish(markers, start_marker["rel"], next_leader_rel)
        end_candidates = []
        if hold and hold["start"] > start_marker["rel"]:
            end_candidates.append(hold["start"])
        if finish:
            end_candidates.append(finish["rel"])
        if not end_candidates:
            continue
        end_rel = max(end_candidates)
        ranges.append(
            {
                "kind": "leader_battle",
                "label": leader,
                "start": start_marker["rel"],
                "end": end_rel,
                "color": COLORS["leader_battle"],
                "priority": PRIORITY["leader_battle"],
            }
        )

    non_rival_battle_starts = [
        m
        for m in markers
        if m["name"].endswith(" Battle Start") and not m["name"].startswith("Rival ")
    ]
    for idx, start_marker in enumerate(non_rival_battle_starts):
        leader = start_marker["name"].removesuffix(" Battle Start")
        if normalize_label(leader) in handled_leaders:
            continue
        next_start_rel = (
            non_rival_battle_starts[idx + 1]["rel"]
            if idx + 1 < len(non_rival_battle_starts)
            else None
        )
        hold = match_tiercard_for_leader(leader, tiercard_holds)
        finish = next_non_rival_finish(markers, start_marker["rel"], next_start_rel)
        end_candidates = []
        if hold and hold["start"] > start_marker["rel"]:
            end_candidates.append(hold["start"])
        if finish:
            end_candidates.append(finish["rel"])
        if not end_candidates:
            continue
        ranges.append(
            {
                "kind": "leader_battle",
                "label": leader,
                "start": previous_retimed_intro_start(v1_items, start_frame, start_marker["rel"])
                or start_marker["rel"],
                "end": max(end_candidates),
                "color": COLORS["leader_battle"],
                "priority": PRIORITY["leader_battle"],
            }
        )

    first_tierlist = next(
        (m for m in markers if m["name"].startswith("Final Tierlist")),
        None,
    )
    carousel = first_marker(markers, "Member Carousel Start")
    outro_start = find_v1_outro_start(v1_items, start_frame, timeline_end_rel)
    if first_tierlist:
        end = carousel["rel"] if carousel else timeline_end_rel
        end = min(end, outro_start)
        ranges.append(
            {
                "kind": "tierlist",
                "label": "Final Tierlist",
                "start": first_tierlist["rel"],
                "end": end,
                "color": COLORS["tierlist"],
                "priority": PRIORITY["tierlist"],
            }
        )

    if carousel:
        ranges.append(
            {
                "kind": "member_carousel",
                "label": "Member Carousel",
                "start": carousel["rel"],
                "end": outro_start,
                "color": COLORS["member_carousel"],
                "priority": PRIORITY["member_carousel"],
            }
        )

    return [r for r in ranges if r["end"] > r["start"]]


def overlaps(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and end_a > start_b


def section_for_span(ranges: list[dict[str, Any]], start: int, end: int) -> dict[str, Any] | None:
    matches = [r for r in ranges if overlaps(start, end, r["start"], r["end"])]
    if not matches:
        return None
    return max(matches, key=lambda r: (min(end, r["end"]) - max(start, r["start"]), r["priority"]))


def section_for_frame(ranges: list[dict[str, Any]], frame: int) -> dict[str, Any] | None:
    matches = [r for r in ranges if r["start"] <= frame < r["end"]]
    if not matches:
        matches = [r for r in ranges if r["end"] == frame]
    if not matches:
        return None
    return max(matches, key=lambda r: r["priority"])


def recolor_markers(timeline, ranges: list[dict[str, Any]], dry_run: bool) -> list[dict[str, Any]]:
    updates = []
    for marker in marker_rows(timeline):
        section = section_for_frame(ranges, marker["rel"])
        if section:
            target_color = MARKER_COLORS[section["kind"]]
        else:
            target_color = DEFAULT_UNCLASSIFIED_MARKER_COLORS.get(marker["name"])
        if not target_color:
            continue
        if marker["color"] == target_color:
            continue
        updates.append(
            {
                "rel": marker["rel"],
                "name": marker["name"],
                "old_color": marker["color"],
                "new_color": target_color,
                "section": section["kind"] if section else "unclassified",
            }
        )
        if dry_run:
            continue
        timeline.DeleteMarkerAtFrame(marker["rel"])
        timeline.AddMarker(
            marker["rel"],
            target_color,
            marker["name"],
            marker["note"],
            marker["duration"],
            marker["customData"],
        )
    return updates


def recolor_v1_clips(
    timeline,
    start_frame: int,
    ranges: list[dict[str, Any]],
    dry_run: bool,
    clear_existing: bool,
) -> list[dict[str, Any]]:
    updates = []
    for index, item in enumerate(timeline.GetItemListInTrack("video", 1) or [], start=1):
        rel_start = int(item.GetStart()) - start_frame
        rel_end = rel_start + int(item.GetDuration())
        section = section_for_span(ranges, rel_start, rel_end)
        target_color = section["color"] if section else ""
        current_color = item.GetClipColor() or ""
        if current_color == target_color:
            continue
        if target_color or clear_existing:
            updates.append(
                {
                    "clip_index": index,
                    "rel_start": rel_start,
                    "rel_end": rel_end,
                    "name": item.GetName(),
                    "old_color": current_color,
                    "new_color": target_color,
                    "section": section["kind"] if section else "unclassified",
                }
            )
        if dry_run:
            continue
        if target_color:
            ok = item.SetClipColor(target_color)
            if not ok:
                raise RuntimeError(
                    f"SetClipColor({target_color!r}) failed for V1 clip {index} "
                    f"{item.GetName()!r} at rel {rel_start}-{rel_end}"
                )
        elif clear_existing and current_color:
            item.ClearClipColor()
    return updates


def color_counts(timeline) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in timeline.GetItemListInTrack("video", 1) or []:
        color = item.GetClipColor() or "-"
        counts[color] = counts.get(color, 0) + 1
    return dict(sorted(counts.items()))


def validate_clip_colors(timeline, colors: list[str]) -> None:
    items = timeline.GetItemListInTrack("video", 1) or []
    if not items:
        raise RuntimeError("No V1 clips found for color validation")
    probe = items[0]
    old_color = probe.GetClipColor() or ""
    for color in colors:
        if not probe.SetClipColor(color):
            raise RuntimeError(f"Resolve rejected clip color {color!r}")
    if old_color:
        if not probe.SetClipColor(old_color):
            raise RuntimeError(f"Could not restore original probe color {old_color!r}")
    else:
        probe.ClearClipColor()


def validate_marker_colors() -> None:
    bad = sorted(set(MARKER_COLORS.values()) - VALID_MARKER_COLORS)
    if bad:
        raise RuntimeError(f"Invalid Resolve marker color(s): {', '.join(bad)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeline", help="Timeline name to select before coloring")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--no-clear", action="store_true", help="Do not clear colors outside known sections")
    parser.add_argument("--skip-markers", action="store_true", help="Only color V1 clips")
    args = parser.parse_args()

    resolve = dvr.scriptapp("Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No Resolve project is open")

    if args.timeline:
        for i in range(1, project.GetTimelineCount() + 1):
            timeline = project.GetTimelineByIndex(i)
            if timeline and timeline.GetName() == args.timeline:
                project.SetCurrentTimeline(timeline)
                break
        else:
            raise RuntimeError(f"Timeline not found: {args.timeline}")

    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No current timeline")

    start_frame = int(timeline.GetStartFrame())
    ranges = sorted(build_ranges(timeline, start_frame), key=lambda r: (r["start"], r["priority"]))
    validate_marker_colors()
    if not args.dry_run:
        validate_clip_colors(timeline, sorted(set(COLORS.values())))
    before_counts = color_counts(timeline)
    clip_updates = recolor_v1_clips(
        timeline,
        start_frame,
        ranges,
        dry_run=args.dry_run,
        clear_existing=not args.no_clear,
    )
    marker_updates = [] if args.skip_markers else recolor_markers(timeline, ranges, args.dry_run)
    after_counts = before_counts if args.dry_run else color_counts(timeline)

    report = {
        "timeline": timeline.GetName(),
        "dry_run": args.dry_run,
        "clip_colors": COLORS,
        "marker_colors": MARKER_COLORS,
        "ranges": ranges,
        "v1_color_counts_before": before_counts,
        "v1_color_counts_after": after_counts,
        "clip_updates": clip_updates,
        "marker_updates": marker_updates,
    }

    report_path = Path(args.report)
    if not args.dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
