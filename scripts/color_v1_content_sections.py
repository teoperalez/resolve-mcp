from __future__ import annotations

"""Color timeline clips and timeline markers by content section.

This replaces trainer-specific marker colors with editing-category colors:

  Orange  intro/outro source assets
  Lime    leader intro + battle UI sections
  Teal    rival in-battle sections
  Purple  V1-only post-battle tiercard/data-card holds
  Yellow  final tierlist views
  Apricot member carousel clips

Only clip colors and, unless skipped, ruler marker colors are changed. No media,
edits, audio, or clip timing is modified.
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


DEFAULT_REPORT = Path("_data") / "qa-reports" / "section_color_report.json"
DEFAULT_REBUILD_REPORT_DIR = Path(
    r"E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx\full_api_rebuild"
)
EXTRA_REBUILD_REPORT_DIRS = [
    Path(
        r"E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx"
        r"\cut_review_locked_autocut\final_full_rebuild"
    )
]
VISUAL_HOLD_FIX_REPORT_DIRS = [
    Path(
        r"E:\Victreebel Red and Blue Ultra Minimum Battles\CODEx"
        r"\cut_review_locked_autocut\final_full_rebuild_hold_fixed"
    )
]

COLORS = {
    "intro": "Orange",
    "leader_battle": "Lime",
    "rival_battle": "Teal",
    "tiercard": "Purple",
    "tierlist": "Yellow",
    "member_carousel": "Apricot",
}

HOLD_KIND_TO_SECTION = {
    "intro_stats": "intro",
    "intro_moveset": "intro",
    "intro_card": "intro",
    "post_battle_card_phase": "tiercard",
    "post_battle_data_card": "tiercard",
    "final_tierlist": "tierlist",
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
    "tierlist": "Yellow",
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


def marker_parts(marker: dict[str, Any]) -> list[str]:
    parts = [part.strip() for part in (marker.get("name") or "").split("/") if part.strip()]
    return parts or [marker.get("name") or ""]


def marker_has(marker: dict[str, Any], name: str) -> bool:
    return any(part == name for part in marker_parts(marker))


def marker_part_startswith(marker: dict[str, Any], prefix: str) -> bool:
    return any(part.startswith(prefix) for part in marker_parts(marker))


def marker_part_endswith(marker: dict[str, Any], suffix: str) -> bool:
    return any(part.endswith(suffix) for part in marker_parts(marker))


def marker_matching_parts(marker: dict[str, Any], suffix: str) -> list[str]:
    return [part for part in marker_parts(marker) if part.endswith(suffix)]


def is_battle_finish_part(part: str) -> bool:
    return " Battle Finish" in part


def first_marker(markers: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((m for m in markers if marker_has(m, name)), None)


def first_marker_any(markers: list[dict[str, Any]], names: set[str]) -> dict[str, Any] | None:
    return next((m for m in markers if any(marker_has(m, name) for name in names)), None)


def markers_named(markers: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [m for m in markers if marker_has(m, name)]


def parse_tiercard_holds(markers: list[dict[str, Any]], timeline_end_rel: int) -> list[dict[str, Any]]:
    holds = []
    prefixes = ("Visual Hold Fixed:", "Visual Tiercard V1 Hold Start:")
    for marker in markers:
        matched_name = None
        prefix = None
        for part in marker_parts(marker):
            prefix = next((p for p in prefixes if part.startswith(p)), None)
            if prefix:
                matched_name = part
                break
        if not prefix or not matched_name:
            continue
        label = matched_name.removeprefix(prefix).strip()
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


def is_post_battle_card_start(part: str) -> bool:
    return part.endswith(" Post-Battle Card") and not part.startswith("Post-Battle Card:")


def is_post_battle_card_end(part: str) -> bool:
    return part == "Post-Battle Card Closed" or part.startswith("Post-Battle Card -> Final Tierlist")


def is_final_tierlist_part(part: str) -> bool:
    return part.startswith("Final Tierlist") or part.startswith("final-tierlist-")


def is_member_carousel_part(part: str) -> bool:
    return part in {"Member Carousel", "Member Carousel Start", "Member Carousel Ended"}


def parse_marker_post_battle_card_ranges(
    markers: list[dict[str, Any]], timeline_end_rel: int
) -> list[dict[str, Any]]:
    ranges = []
    for marker in markers:
        start_parts = [part for part in marker_parts(marker) if is_post_battle_card_start(part)]
        if not start_parts:
            continue
        next_battle_start = next(
            (
                candidate["rel"]
                for candidate in markers
                if candidate["rel"] > marker["rel"] and marker_part_endswith(candidate, " Battle Start")
            ),
            None,
        )
        end_marker = next(
            (
                candidate
                for candidate in markers
                if candidate["rel"] > marker["rel"]
                and (next_battle_start is None or candidate["rel"] < next_battle_start)
                and any(
                    is_post_battle_card_end(part) or is_final_tierlist_part(part)
                    for part in marker_parts(candidate)
                )
            ),
            None,
        )
        if not end_marker:
            continue
        for part in start_parts:
            ranges.append(
                {
                    "kind": "tiercard",
                    "label": part.removesuffix(" Post-Battle Card"),
                    "start": marker["rel"],
                    "end": min(end_marker["rel"], timeline_end_rel),
                    "color": COLORS["tiercard"],
                    "priority": PRIORITY["tiercard"],
                    "source": "markers",
                }
            )
    return ranges


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
        if any(is_battle_finish_part(part) for part in marker_parts(marker)) and not marker_has(marker, "Rival Battle Finish"):
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
    return "intro" in name or "-battle-intro" in name or "__2x_resolve" in name


def rebuild_report_for_timeline(timeline_name: str) -> Path | None:
    report_dirs = [DEFAULT_REBUILD_REPORT_DIR, *EXTRA_REBUILD_REPORT_DIRS]
    timeline_names = [timeline_name]
    for suffix in (" visual holds fixed", " visual holds old rule fixed"):
        if timeline_name.endswith(suffix):
            timeline_names.append(timeline_name.removesuffix(suffix))
    for name in timeline_names:
        for report_dir in report_dirs:
            exact = report_dir / f"{name}_report.json"
            if exact.exists():
                return exact
    candidates = []
    for report_dir in report_dirs:
        candidates.extend(report_dir.glob("*_report.json"))
    candidates = sorted(
        candidates,
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("timeline") in timeline_names:
            return path
    return None


def visual_hold_fix_report_for_timeline(timeline_name: str) -> Path | None:
    for report_dir in VISUAL_HOLD_FIX_REPORT_DIRS:
        exact = report_dir / f"{timeline_name}_visual_hold_fix_report.json"
        if exact.exists():
            return exact
    for report_dir in VISUAL_HOLD_FIX_REPORT_DIRS:
        for path in sorted(report_dir.glob("*_visual_hold_fix_report.json"), key=lambda p: p.stat().st_mtime, reverse=True):
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


def load_visual_hold_fix_ranges(timeline_name: str) -> list[dict[str, Any]]:
    report_path = visual_hold_fix_report_for_timeline(timeline_name)
    if not report_path:
        return []
    data = json.loads(report_path.read_text(encoding="utf-8"))
    ranges = []
    for hold in data.get("holds") or []:
        ranges.append(
            {
                "kind": "tiercard",
                "label": hold.get("label") or "Visual Hold",
                "start": int(hold["rel_start"]),
                "end": int(hold["rel_end"]),
                "color": COLORS["tiercard"],
                "priority": PRIORITY["tiercard"],
                "source": "visual_hold_fix",
                "report": str(report_path),
            }
        )
    return ranges


def clip_ranges_for_visual_hold(
    video_items: list[Any],
    start_frame: int,
    hold: dict[str, Any],
) -> list[tuple[int, int]]:
    source_start = int(hold["start"])
    duration = int(hold.get("record_duration") or max(1, int(hold["end"]) - source_start))
    exact = []
    loose = []
    for item in video_items:
        if int(item.GetLeftOffset()) != source_start:
            continue
        rel_start = int(item.GetStart()) - start_frame
        rel_end = rel_start + int(item.GetDuration())
        if abs(int(item.GetDuration()) - duration) <= 1:
            exact.append((rel_start, rel_end))
        else:
            loose.append((rel_start, rel_end))
    return exact or loose


def load_manifest_visual_hold_ranges(
    manifest_path: Path | None,
    video_items: list[Any],
    start_frame: int,
) -> list[dict[str, Any]]:
    if not manifest_path or not manifest_path.exists():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    visual_report = (
        ((data.get("spine") or {}).get("visual_hold_report"))
        or data.get("visual_hold_report")
        or data.get("hold_report")
    )
    if not visual_report:
        return []

    ranges = []
    for hold in visual_report.get("holds") or []:
        section = HOLD_KIND_TO_SECTION.get(hold.get("kind"))
        if not section:
            continue
        mapped = clip_ranges_for_visual_hold(video_items, start_frame, hold)
        if not mapped and "record_start" in hold and "record_end" in hold:
            mapped = [(int(hold["record_start"]), int(hold["record_end"]))]
        for start, end in mapped:
            ranges.append(
                {
                    "kind": section,
                    "label": hold.get("label") or hold.get("kind") or section,
                    "start": start,
                    "end": end,
                    "color": COLORS[section],
                    "priority": PRIORITY[section],
                    "source": "manifest_visual_hold_report",
                    "manifest": str(manifest_path),
                }
            )
    return ranges


def all_video_items(timeline) -> list[Any]:
    items = []
    for track in range(1, int(timeline.GetTrackCount("video") or 0) + 1):
        items.extend(timeline.GetItemListInTrack("video", track) or [])
    return items


def build_ranges(timeline, start_frame: int, manifest_path: Path | None = None) -> list[dict[str, Any]]:
    markers = marker_rows(timeline)
    v1_items = timeline.GetItemListInTrack("video", 1) or []
    video_items = all_video_items(timeline)
    timeline_end_rel = int(timeline.GetEndFrame()) - start_frame
    ranges: list[dict[str, Any]] = []
    log_hold_ranges = load_log_hold_ranges(timeline, start_frame, v1_items)
    visual_hold_fix_ranges = load_visual_hold_fix_ranges(timeline.GetName())
    manifest_hold_ranges = load_manifest_visual_hold_ranges(manifest_path, video_items, start_frame)

    rival_starts = markers_named(markers, "Rival Battle Start")
    rival_finishes = markers_named(markers, "Rival Battle Finish")
    intro_marker = first_marker(markers, "Intro")
    intro_finished = first_marker(markers, "Intro Finished")
    if intro_marker and intro_finished and intro_finished["rel"] > intro_marker["rel"]:
        ranges.append(
            {
                "kind": "intro",
                "label": "Intro marker span",
                "start": intro_marker["rel"],
                "end": intro_finished["rel"],
                "color": COLORS["intro"],
                "priority": PRIORITY["intro"],
                "source": "markers",
            }
        )

    for item in video_items:
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
    ranges.extend(visual_hold_fix_ranges)
    ranges.extend(manifest_hold_ranges)
    if not any(
        r["kind"] == "intro" and r.get("source") in {"log_holds", "manifest_visual_hold_report"}
        for r in [*log_hold_ranges, *manifest_hold_ranges]
    ):
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
    marker_post_battle_ranges = parse_marker_post_battle_card_ranges(markers, timeline_end_rel)
    ranges.extend(marker_tiercard_holds)
    ranges.extend(marker_post_battle_ranges)
    # Prefer explicit marker-fixed holds when both the older short log-derived
    # ranges and the repaired visual-hold ranges exist on a timeline.
    tiercard_holds = manifest_hold_ranges + visual_hold_fix_ranges + marker_tiercard_holds + marker_post_battle_ranges + [
        r for r in log_hold_ranges if r["kind"] == "tiercard"
    ]

    rival_gap_markers = [
        m
        for m in markers
        if marker_has(m, "Non-boss Battle Gap") and "Rival Battle Start" in m["note"]
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

    leader_starts = [m for m in markers if marker_part_endswith(m, " Leader Intro Start")]
    handled_leaders = {
        normalize_label(marker_matching_parts(m, " Leader Intro Start")[0].removesuffix(" Leader Intro Start"))
        for m in leader_starts
    }
    for idx, start_marker in enumerate(leader_starts):
        leader = marker_matching_parts(start_marker, " Leader Intro Start")[0].removesuffix(" Leader Intro Start")
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
        if marker_part_endswith(m, " Battle Start") and not marker_has(m, "Rival Battle Start")
    ]
    for idx, start_marker in enumerate(non_rival_battle_starts):
        leader = marker_matching_parts(start_marker, " Battle Start")[0].removesuffix(" Battle Start")
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

    first_tierlist = next((m for m in markers if any(is_final_tierlist_part(part) for part in marker_parts(m))), None)
    carousel = first_marker_any(markers, {"Member Carousel Start", "Member Carousel"})
    carousel_end = first_marker(markers, "Member Carousel Ended")
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
        end = carousel_end["rel"] if carousel_end and carousel_end["rel"] > carousel["rel"] else outro_start
        ranges.append(
            {
                "kind": "member_carousel",
                "label": "Member Carousel",
                "start": carousel["rel"],
                "end": end,
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


def parse_track_selection(timeline, selection: str) -> list[int]:
    max_track = int(timeline.GetTrackCount("video") or 0)
    if selection.strip().lower() == "all":
        return list(range(1, max_track + 1))
    tracks = []
    for raw in selection.split(","):
        raw = raw.strip()
        if not raw:
            continue
        track = int(raw)
        if track < 1 or track > max_track:
            raise ValueError(f"Video track V{track} does not exist; timeline has V1-V{max_track}")
        tracks.append(track)
    return sorted(set(tracks))


def parse_color_selection(selection: str) -> set[str]:
    return {part.strip() for part in selection.split(",") if part.strip()}


def recolor_video_clips(
    timeline,
    start_frame: int,
    ranges: list[dict[str, Any]],
    dry_run: bool,
    clear_existing: bool,
    tracks: list[int],
    preserve_colors: set[str],
    strict_apply: bool,
) -> list[dict[str, Any]]:
    updates = []
    for track in tracks:
        for index, item in enumerate(timeline.GetItemListInTrack("video", track) or [], start=1):
            rel_start = int(item.GetStart()) - start_frame
            rel_end = rel_start + int(item.GetDuration())
            section = section_for_span(ranges, rel_start, rel_end)
            target_color = section["color"] if section else ""
            current_color = item.GetClipColor() or ""
            if current_color == target_color:
                continue
            if current_color in preserve_colors and target_color != current_color:
                updates.append(
                    {
                        "track": track,
                        "clip_index": index,
                        "rel_start": rel_start,
                        "rel_end": rel_end,
                        "name": item.GetName(),
                        "old_color": current_color,
                        "new_color": target_color,
                        "section": section["kind"] if section else "unclassified",
                        "preserved": True,
                    }
                )
                continue
            if target_color or clear_existing:
                updates.append(
                    {
                        "track": track,
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
                ret = item.SetClipColor(target_color)
                actual_color = item.GetClipColor() or ""
                updates[-1]["api_return"] = str(ret)
                updates[-1]["actual_color"] = actual_color
                updates[-1]["applied"] = actual_color == target_color
                if strict_apply and actual_color != target_color:
                    raise RuntimeError(
                        f"SetClipColor({target_color!r}) did not stick for V{track} clip {index} "
                        f"{item.GetName()!r} at rel {rel_start}-{rel_end}"
                    )
            elif clear_existing and current_color:
                item.ClearClipColor()
                actual_color = item.GetClipColor() or ""
                updates[-1]["actual_color"] = actual_color
                updates[-1]["applied"] = actual_color == ""
                if strict_apply and actual_color:
                    raise RuntimeError(
                        f"ClearClipColor() did not stick for V{track} clip {index} "
                        f"{item.GetName()!r} at rel {rel_start}-{rel_end}"
                    )
    return updates


def color_counts(timeline, tracks: list[int]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for track in tracks:
        counts: dict[str, int] = {}
        for item in timeline.GetItemListInTrack("video", track) or []:
            color = item.GetClipColor() or "-"
            counts[color] = counts.get(color, 0) + 1
        out[f"v{track}"] = dict(sorted(counts.items()))
    return out


def probe_clip_color_api(timeline, colors: list[str]) -> dict[str, Any]:
    items = timeline.GetItemListInTrack("video", 1) or []
    if not items:
        return {"available": False, "reason": "No V1 clips found for color validation", "colors": []}
    probe = items[0]
    old_color = probe.GetClipColor() or ""
    rows = []
    for color in colors:
        ret = probe.SetClipColor(color)
        actual_color = probe.GetClipColor() or ""
        rows.append(
            {
                "requested": color,
                "api_return": str(ret),
                "actual_color": actual_color,
                "applied": actual_color == color,
            }
        )
    if old_color:
        probe.SetClipColor(old_color)
    else:
        probe.ClearClipColor()
    return {
        "available": any(row["applied"] for row in rows),
        "colors": rows,
    }


def validate_marker_colors() -> None:
    bad = sorted(set(MARKER_COLORS.values()) - VALID_MARKER_COLORS)
    if bad:
        raise RuntimeError(f"Invalid Resolve marker color(s): {', '.join(bad)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeline", help="Timeline name to select before coloring")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--manifest", help="Final rebuild manifest with visual hold report timing")
    parser.add_argument("--video-tracks", default="all", help="Comma-separated video tracks to color, or 'all'")
    parser.add_argument(
        "--preserve-colors",
        default="Pink",
        help="Comma-separated existing clip colors that should not be overwritten",
    )
    parser.add_argument(
        "--strict-apply",
        action="store_true",
        help="Fail if Resolve exposes SetClipColor but the requested color does not stick.",
    )
    parser.add_argument("--summary", action="store_true", help="Print a concise summary instead of the full report JSON")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear colors outside known sections")
    parser.add_argument("--skip-markers", action="store_true", help="Only color clips; leave ruler markers unchanged")
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
    manifest_path = Path(args.manifest) if args.manifest else None
    tracks = parse_track_selection(timeline, args.video_tracks)
    preserve_colors = parse_color_selection(args.preserve_colors)
    ranges = sorted(build_ranges(timeline, start_frame, manifest_path), key=lambda r: (r["start"], r["priority"]))
    validate_marker_colors()
    clip_color_probe = {"available": None, "colors": []}
    if not args.dry_run:
        clip_color_probe = probe_clip_color_api(timeline, sorted(set(COLORS.values())))
    before_counts = color_counts(timeline, tracks)
    clip_updates = recolor_video_clips(
        timeline,
        start_frame,
        ranges,
        dry_run=args.dry_run,
        clear_existing=not args.no_clear,
        tracks=tracks,
        preserve_colors=preserve_colors,
        strict_apply=args.strict_apply,
    )
    marker_updates = [] if args.skip_markers else recolor_markers(timeline, ranges, args.dry_run)
    after_counts = before_counts if args.dry_run else color_counts(timeline, tracks)

    report = {
        "timeline": timeline.GetName(),
        "dry_run": args.dry_run,
        "clip_colors": COLORS,
        "marker_colors": MARKER_COLORS,
        "manifest": str(manifest_path) if manifest_path else None,
        "video_tracks": tracks,
        "preserve_colors": sorted(preserve_colors),
        "clip_color_probe": clip_color_probe,
        "ranges": ranges,
        "video_color_counts_before": before_counts,
        "video_color_counts_after": after_counts,
        "clip_updates_applied": sum(1 for item in clip_updates if item.get("applied")),
        "clip_updates_failed": sum(1 for item in clip_updates if item.get("applied") is False),
        "clip_updates": clip_updates,
        "marker_updates": marker_updates,
    }

    report_path = Path(args.report)
    if not args.dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.summary:
        summary = {
            "timeline": report["timeline"],
            "dry_run": report["dry_run"],
            "report": str(report_path),
            "clip_color_api_available": clip_color_probe.get("available"),
            "range_count": len(ranges),
            "clip_update_count": len(clip_updates),
            "clip_updates_applied": report["clip_updates_applied"],
            "clip_updates_failed": report["clip_updates_failed"],
            "video_color_counts_after": after_counts,
        }
        print(json.dumps(summary, indent=2))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
