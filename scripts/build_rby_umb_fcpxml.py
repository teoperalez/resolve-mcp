from __future__ import annotations

"""Build a Gen 1 RBY Ultra Minimum Battles editorial base.

This is the generic, profile-driven RBY UMB builder.
It uses the active orchestrator profile to find the source video, dialogue WAV,
raw auto-editor FCPXML, session log, cut-review artifacts, and any locked
structural source cuts. It maps RBYNewLayout markers through the edited source
spine and optionally imports the resulting FCPXML into Resolve.

The review pipeline should call this first with --review-base. That creates a
minimal V1/A1 timeline for cut review before any heavy visual holds, battle
intros, BGM, carousel layout, or color passes are allowed to run.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

from scripts import build_victreebel_rby_fcpxml as B
from scripts import derive_rby_umb_hold_regions as H


FPS = 60
FRAME_DURATION = f"1/{FPS}s"

def first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


class SafeFormat(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def expand_templates(value: str, mapping: dict[str, str]) -> str:
    previous = str(value)
    for _ in range(8):
        current = previous.format_map(SafeFormat(mapping))
        if current == previous:
            return current
        previous = current
    return previous


def load_json_optional(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def active_profile_mapping() -> tuple[str, dict[str, object]]:
    config_path = Path(os.environ.get("ORCHESTRATOR_CONFIG_PATH") or REPO_DIR / "config" / "orchestrator_workflows.json")
    profile_id = os.environ.get("ORCHESTRATOR_PROFILE_ID") or ""
    if not profile_id or not config_path.exists():
        return profile_id, {}
    data = load_json_optional(config_path)
    if not isinstance(data, dict):
        return profile_id, {}
    profile = next((item for item in data.get("profiles", []) if item.get("id") == profile_id), None)
    if not profile:
        return profile_id, {}
    mapping: dict[str, object] = {
        "repo": str(REPO_DIR),
        "profile_id": str(profile.get("id") or ""),
        "profile_name": str(profile.get("name") or profile.get("id") or ""),
        "workflow_id": str(profile.get("workflow_id") or ""),
        "project_dir": str(profile.get("project_dir") or ""),
        "codex_dir": str(profile.get("codex_dir") or ""),
        "game_version": str(profile.get("game_version") or ""),
        "challenge_type": str(profile.get("challenge_type") or ""),
    }
    for source in (profile.get("parameters") or {}, profile.get("paths") or {}):
        for key, value in source.items():
            if isinstance(value, str):
                mapping[str(key)] = expand_templates(value, {k: str(v) for k, v in mapping.items()})
            elif isinstance(value, (int, float, bool, list, dict)):
                mapping[str(key)] = value
    for _ in range(8):
        changed = False
        for key, value in list(mapping.items()):
            if not isinstance(value, str):
                continue
            expanded = expand_templates(value, {k: str(v) for k, v in mapping.items()})
            if expanded != value:
                mapping[key] = expanded
                changed = True
        if not changed:
            break
    return profile_id, mapping


ACTIVE_PROFILE_ID, PROFILE = active_profile_mapping()
DEFAULT_PROJECT_DIR = Path.cwd()


def profile_text(key: str, default: str = "") -> str:
    value = PROFILE.get(key, default)
    return str(value).strip() if value is not None else default


def profile_path(key: str, default: Path) -> Path:
    value = profile_text(key)
    return Path(value) if value else default


def profile_float(key: str, default: float) -> float:
    value = profile_text(key)
    return float(value) if value else default


def profile_bool(key: str, default: bool = False) -> bool:
    value = profile_text(key)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def safe_file_stem_text(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_. -]+", "_", text).strip(" .") or "rby_umb_timeline"


def source_name() -> str:
    configured = profile_text("source_name")
    if configured:
        return configured
    source_media = profile_text("source_media")
    if source_media:
        return Path(source_media).stem
    return "rby_umb_source"


PROJECT_DIR = profile_path("project_dir", DEFAULT_PROJECT_DIR)
CODEX_DIR = profile_path("codex_dir", PROJECT_DIR / "CODEx")
SESSION_DIR = profile_path(
    "session_dir",
    CODEX_DIR / "session-log",
)
SESSION_EVENTS = profile_path("session_events", SESSION_DIR / "events.json")
SESSION_META = profile_path("session_meta", SESSION_DIR / "meta.json")
VIDEO_PATH = profile_path("source_media", PROJECT_DIR / f"{source_name()}.mp4")
DIALOGUE_PATH = profile_path(
    "dialogue_audio",
    PROJECT_DIR / f"{source_name()}_tracks" / f"{source_name()}_dialogue.wav",
)
RAW_AUTOEDITOR_FCPXML = profile_path(
    "raw_autoeditor_fcpxml",
    PROJECT_DIR / f"{source_name()}_AUTOEDITOR_RAW.fcpxml",
)
HOLD_REGIONS_PATH = profile_path("hold_regions", CODEX_DIR / "cut_review" / "hold_regions.json")
CUT_CANDIDATES_PATH = profile_path("candidate_manifest", CODEX_DIR / "cut_review" / "cut_candidates.json")
HOLD_REGION_STOP_REPORT = CODEX_DIR / "cut_review" / "hold_region_stop.json"
HOLD_REGION_OVERRIDE = profile_path("hold_regions_override", CODEX_DIR / "cut_review" / "hold_regions_override.json")
VISUAL_HOLD_KINDS = {
    "intro_stats",
    "intro_moveset",
    "intro_card",
    "post_battle_data_card",
    "post_battle_card_phase",
    "post_battle_card_manual_override",
    "champion_post_battle_tier_card",
    "final_tierlist",
}

FINAL_NAME = profile_text("final_timeline_name") or f"{source_name()} CODEx final rebuild base"
REVIEW_NAME = profile_text("review_timeline_name") or profile_path("review_fcpxml", CODEX_DIR / "cut_review" / "review_base.fcpxml").stem
MANIFEST_PATH = profile_path("final_manifest", CODEX_DIR / f"{safe_file_stem_text(FINAL_NAME)}_manifest.json")
OUT_FCPXML = PROJECT_DIR / f"{FINAL_NAME}.fcpxml"

SOURCE_START_SEC = profile_float("source_start_sec", 0.0)
SOURCE_START_REASON = profile_text(
    "source_start_reason",
    "start at source beginning",
)


def parse_profile_json(key: str, default):
    raw = PROFILE.get(key)
    if raw in (None, ""):
        return default
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    return default


def configured_structural_source_cuts() -> list[dict]:
    rows = parse_profile_json("structural_source_cuts", None)
    normalized: list[dict] = []
    for index, row in enumerate(rows or [], start=1):
        if not isinstance(row, dict):
            raise RuntimeError(f"structural_source_cuts[{index}] must be an object")
        start_sec = row.get("start_sec", row.get("source_start_sec"))
        end_sec = row.get("end_sec", row.get("source_end_sec"))
        start_frame = row.get("start_frame", row.get("source_start_frame"))
        end_frame = row.get("end_frame", row.get("source_end_frame"))
        if start_frame is None or end_frame is None:
            if start_sec is None or end_sec is None:
                raise RuntimeError(f"structural_source_cuts[{index}] needs start/end seconds or frames")
            start_frame = int(round(float(start_sec) * FPS))
            end_frame = int(round(float(end_sec) * FPS))
        start_i = int(round(float(start_frame)))
        end_i = int(round(float(end_frame)))
        if end_i <= start_i:
            raise RuntimeError(f"structural_source_cuts[{index}] has invalid bounds: {row!r}")
        normalized.append(
            {
                **row,
                "label": row.get("label") or f"structural_source_cut_{index}",
                "start_sec": start_i / FPS,
                "end_sec": end_i / FPS,
                "start_frame": start_i,
                "end_frame": end_i,
                "confidence": row.get("confidence") or "locked",
                "type": row.get("type") or "explicit_structural_cut",
                "reason": row.get("reason") or "profile-configured structural source cut",
            }
        )
    return normalized


STRUCTURAL_SOURCE_CUTS = configured_structural_source_cuts()


@dataclass
class Clip:
    offset: int
    start: int
    duration: int
    role: str = "auto"
    label: str = ""

    @property
    def end(self) -> int:
        return self.start + self.duration

    @property
    def record_end(self) -> int:
        return self.offset + self.duration


@dataclass
class Marker:
    label: str
    note: str
    color: str
    category: str
    name: str
    session_elapsed_sec: float
    source_sec: float
    source_frame: int
    combined_frame: int
    snapped: bool


def log(message: str) -> None:
    print(message, flush=True)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def media_duration_frames(path: Path) -> int:
    return B.media_duration_frames(path)


def video_duration_frames(path: Path) -> int:
    return B.video_duration_frames(path)


def path_to_uri_localhost(path: Path) -> str:
    p = str(path.resolve()).replace("\\", "/")
    return "file://localhost/" + urllib.parse.quote(p, safe="/:")


def source_start_elapsed() -> float:
    if not SESSION_META.exists():
        raise FileNotFoundError(f"Missing session meta for marker mapping: {SESSION_META}")
    meta = H.load_json(SESSION_META)
    fmt = H.ffprobe_format(VIDEO_PATH)
    creation = (fmt.get("tags") or {}).get("creation_time")
    if not creation:
        raise RuntimeError(f"No creation_time metadata in {VIDEO_PATH}")
    return (parse_dt(creation) - parse_dt(meta["startedAt"])).total_seconds()


def source_duration_sec() -> float:
    return float(H.ffprobe_format(VIDEO_PATH)["duration"])


def source_frame(sec: float) -> int:
    return int(round(sec * FPS))


def load_extra_source_cuts(path: Path | None) -> list[dict]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("source_cuts")
            or payload.get("approved_cuts")
            or payload.get("cuts")
            or payload.get("narrative_cuts")
            or payload.get("html_review_cuts")
            or []
        )
    else:
        raise RuntimeError(f"Unsupported extra source cuts payload in {path}")

    cuts: list[dict] = []
    for index, row in enumerate(rows, start=1):
        if row.get("status") in {"reject", "rejected", "keep"}:
            continue
        start_frame = row.get("start_frame", row.get("source_start_frame"))
        end_frame = row.get("end_frame", row.get("source_end_frame"))
        if start_frame is None or end_frame is None:
            start_sec = row.get("start_sec", row.get("source_start_sec"))
            end_sec = row.get("end_sec", row.get("source_end_sec"))
            if start_sec is None or end_sec is None:
                raise RuntimeError(f"Extra cut #{index} lacks frame/sec bounds: {row!r}")
            start_frame = source_frame(float(start_sec))
            end_frame = source_frame(float(end_sec))
        start_i = int(round(float(start_frame)))
        end_i = int(round(float(end_frame)))
        if end_i <= start_i:
            raise RuntimeError(f"Extra cut #{index} has invalid range: {row!r}")
        cuts.append(
            {
                **row,
                "start_frame": start_i,
                "end_frame": end_i,
                "start_sec": start_i / FPS,
                "end_sec": end_i / FPS,
                "source": str(path),
            }
        )
    return cuts


def parse_autoeditor_intervals(fcpxml: Path) -> list[Clip]:
    root = ET.parse(fcpxml).getroot()
    intervals: list[Clip] = []
    for ac in root.findall(".//spine/asset-clip"):
        start = B.parse_time_to_frames(ac.get("start", "0s"))
        duration = B.parse_time_to_frames(ac.get("duration", "0s"))
        if duration <= 0:
            continue
        intervals.append(Clip(0, start, duration))
    intervals.sort(key=lambda c: (c.start, c.duration))
    if not intervals:
        raise RuntimeError(f"No auto-editor intervals found in {fcpxml}")
    return intervals


def subtract_ranges(start: int, end: int, cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    pieces = [(start, end)]
    for cut_start, cut_end in sorted(cuts):
        next_pieces: list[tuple[int, int]] = []
        for a, b in pieces:
            if b <= cut_start or a >= cut_end:
                next_pieces.append((a, b))
                continue
            if a < cut_start:
                next_pieces.append((a, cut_start))
            if b > cut_end:
                next_pieces.append((cut_end, b))
        pieces = next_pieces
    return [(a, b) for a, b in pieces if b > a]


def build_audio_spine(
    raw_intervals: list[Clip],
    *,
    keep_start: int,
    keep_end: int,
    cuts: list[tuple[int, int]],
    force_keep_ranges: list[tuple[int, int]] | None = None,
) -> tuple[list[Clip], list[dict]]:
    source_ranges = [(clip.start, clip.end) for clip in raw_intervals]
    source_ranges.extend(force_keep_ranges or [])
    source_ranges = [
        (max(start, keep_start), min(end, keep_end))
        for start, end in source_ranges
        if min(end, keep_end) > max(start, keep_start)
    ]
    source_ranges.sort()
    merged_ranges: list[tuple[int, int]] = []
    for start, end in source_ranges:
        if merged_ranges and start <= merged_ranges[-1][1]:
            merged_ranges[-1] = (merged_ranges[-1][0], max(merged_ranges[-1][1], end))
        else:
            merged_ranges.append((start, end))

    out: list[Clip] = []
    record = 0
    source_to_record: list[dict] = []
    for start, end in merged_ranges:
        for a, b in subtract_ranges(start, end, cuts):
            clip = Clip(record, a, b - a)
            out.append(clip)
            source_to_record.append(
                {
                    "source_start": a,
                    "source_end": b,
                    "record_start": record,
                    "record_end": record + (b - a),
                    "role": "auto",
                }
            )
            record += b - a
    if not out:
        raise RuntimeError("Manual cuts removed all auto-editor intervals")
    return out, source_to_record


def map_source_frame(clips: list[Clip], frame: int) -> tuple[int | None, bool]:
    ordered = sorted(clips, key=lambda c: (c.start, c.offset))
    for clip in ordered:
        if clip.start <= frame < clip.end:
            return clip.offset + (frame - clip.start), False
    next_clip = next((clip for clip in ordered if clip.start > frame), None)
    if next_clip is None:
        return None, False
    return next_clip.offset, True


def load_holds(path: Path, kinds: set[str], keep_start: int, keep_end: int) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("regions", payload) if isinstance(payload, dict) else payload
    holds: list[dict] = []
    for row in rows:
        if row.get("kind") not in kinds:
            continue
        start = row.get("source_start_frame")
        end = row.get("source_end_frame")
        if start is None or end is None:
            continue
        start_i = max(int(round(float(start))), keep_start)
        end_i = min(int(round(float(end))), keep_end)
        if end_i <= start_i:
            continue
        holds.append(
            {
                "start": start_i,
                "end": end_i,
                "label": row.get("label") or row.get("kind") or "hold",
                "kind": row.get("kind") or "hold",
                "reason": row.get("reason") or "",
            }
        )
    holds.sort(key=lambda h: (h["start"], h["end"]))
    return holds


def apply_visual_holds(base_clips: list[Clip], holds: list[dict]) -> tuple[list[Clip], dict]:
    """Replace V1 picture over compressed record spans without changing length."""
    if not holds:
        return list(base_clips), {
            "input_clips": len(base_clips),
            "output_clips": len(base_clips),
            "holds_requested": 0,
            "holds_emitted": 0,
            "duration_delta": 0,
            "visual_only": True,
        }

    record_holds: list[dict] = []
    for hold in holds:
        record_start, start_snapped = map_source_frame(base_clips, hold["start"])
        record_end, end_snapped = map_source_frame(base_clips, hold["end"])
        if record_start is None or record_end is None or record_end <= record_start:
            continue
        record_holds.append(
            {
                **hold,
                "record_start": record_start,
                "record_end": record_end,
                "record_duration": record_end - record_start,
                "source_duration": hold["end"] - hold["start"],
                "start_snapped": start_snapped,
                "end_snapped": end_snapped,
            }
        )

    record_holds.sort(key=lambda h: (h["record_start"], h["record_end"]))
    merged: list[dict] = []
    for hold in record_holds:
        if merged and hold["record_start"] < merged[-1]["record_end"]:
            raise RuntimeError(
                f"Overlapping visual holds: {merged[-1]['label']} and {hold['label']}"
            )
        merged.append(hold)

    out: list[Clip] = []
    for clip in sorted(base_clips, key=lambda c: (c.offset, c.start)):
        pieces = [(clip.offset, clip.start, clip.duration)]
        for hold in merged:
            h0 = hold["record_start"]
            h1 = hold["record_end"]
            next_pieces: list[tuple[int, int, int]] = []
            for off, src, dur in pieces:
                end = off + dur
                if end <= h0 or off >= h1:
                    next_pieces.append((off, src, dur))
                    continue
                if off < h0:
                    keep = h0 - off
                    next_pieces.append((off, src, keep))
                if end > h1:
                    trim = h1 - off
                    next_pieces.append((h1, src + trim, end - h1))
            pieces = next_pieces
        for off, src, dur in pieces:
            if dur > 0:
                out.append(Clip(off, src, dur))

    for hold in merged:
        out.append(
            Clip(
                hold["record_start"],
                hold["start"],
                hold["record_duration"],
                "visual_hold",
                hold["label"],
            )
        )

    out.sort(key=lambda c: (c.offset, c.start, c.label))
    old_frames = max(c.record_end for c in base_clips)
    new_frames = max(c.record_end for c in out)
    return out, {
        "input_clips": len(base_clips),
        "output_clips": len(out),
        "holds_requested": len(holds),
        "holds_emitted": len(merged),
        "input_frames": old_frames,
        "output_frames": new_frames,
        "duration_delta": new_frames - old_frames,
        "visual_only": True,
        "holds": merged,
    }


def load_intended_markers():
    scripts = profile_path(
        "session_marker_script_dir",
        first_existing_path(
            Path(r"F:\Programming\RBYNewLayout\scripts"),
            Path(r"C:\Programming\RBYNewLayout\scripts"),
        ),
    )
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import session_marker_labels as sml  # type: ignore

    if not SESSION_EVENTS.exists():
        raise FileNotFoundError(f"Missing session events for marker replay: {SESSION_EVENTS}")
    events = H.load_json(SESSION_EVENTS)
    return sml.replay_markers(events)


def map_marker_frame(video_clips: list[Clip], source_frame_i: int) -> tuple[int | None, bool]:
    return map_source_frame(video_clips, source_frame_i)


def build_markers(
    video_clips: list[Clip],
    keep_start: int,
    keep_end: int,
    manual_cuts: list[tuple[int, int]],
) -> tuple[list[Marker], dict]:
    offset = source_start_elapsed()
    markers: list[Marker] = []
    dropped: list[dict] = []
    for im in load_intended_markers():
        elapsed = float(im.t_elapsed_ms) / 1000.0
        source_sec = elapsed - offset
        if source_sec < 0 or source_sec > source_duration_sec():
            continue
        src_frame = int(round(source_sec * FPS))
        if src_frame < keep_start or src_frame >= keep_end:
            dropped.append({"label": im.label, "source_frame": src_frame, "reason": "outside_kept_source"})
            continue
        containing_cut = next((cut for cut in manual_cuts if cut[0] <= src_frame < cut[1]), None)
        if containing_cut:
            dropped.append(
                {
                    "label": im.label,
                    "source_frame": src_frame,
                    "reason": "inside_manual_cut",
                    "cut_start": containing_cut[0],
                    "cut_end": containing_cut[1],
                }
            )
            continue
        record_frame, snapped = map_marker_frame(video_clips, src_frame)
        if record_frame is None:
            dropped.append({"label": im.label, "source_frame": src_frame, "reason": "removed_by_edit"})
            continue
        markers.append(
            Marker(
                label=im.label,
                note=im.note,
                color=im.color,
                category=im.category,
                name=im.name,
                session_elapsed_sec=elapsed,
                source_sec=source_sec,
                source_frame=src_frame,
                combined_frame=record_frame,
                snapped=snapped,
            )
        )
    markers.sort(key=lambda m: (m.combined_frame, m.label))
    return markers, {
        "source_start_elapsed_sec": offset,
        "source_duration_sec": source_duration_sec(),
        "dropped_markers": dropped,
    }


def load_low_confidence_mark_only_candidates(path: Path = CUT_CANDIDATES_PATH) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("low_confidence_mark_only_candidates") or payload.get("mark_only_candidates") or []
    return [
        row
        for row in rows
        if row.get("confidence") == "low" and row.get("disposition") in {"mark_only", "mark"}
    ]


def append_low_confidence_candidate_markers(
    markers: list[Marker],
    video_clips: list[Clip],
    keep_start: int,
    keep_end: int,
    manual_cuts: list[tuple[int, int]],
) -> dict:
    candidates = load_low_confidence_mark_only_candidates()
    offset = source_start_elapsed()
    added = 0
    skipped: list[dict] = []
    for index, candidate in enumerate(candidates, start=1):
        raw_frame = candidate.get("source_start_frame", candidate.get("start_frame"))
        if raw_frame is None:
            skipped.append({"index": index, "reason": "missing_source_start_frame"})
            continue
        src_frame = int(round(float(raw_frame)))
        if src_frame < keep_start or src_frame >= keep_end:
            skipped.append({"index": index, "source_frame": src_frame, "reason": "outside_kept_source"})
            continue
        containing_cut = next((cut for cut in manual_cuts if cut[0] <= src_frame < cut[1]), None)
        if containing_cut:
            skipped.append(
                {
                    "index": index,
                    "source_frame": src_frame,
                    "reason": "inside_approved_cut",
                    "cut_start": containing_cut[0],
                    "cut_end": containing_cut[1],
                }
            )
            continue
        record_frame, snapped = map_marker_frame(video_clips, src_frame)
        if record_frame is None:
            skipped.append({"index": index, "source_frame": src_frame, "reason": "removed_by_edit"})
            continue
        source_sec = src_frame / FPS
        end_frame = int(round(float(candidate.get("source_end_frame", candidate.get("end_frame", src_frame + 1)))))
        note = (
            f"Low-confidence cut candidate; mark only, do not auto-cut. "
            f"Source {source_sec:.2f}-{(end_frame / FPS):.2f}s. "
            f"{candidate.get('type') or 'candidate'}: {candidate.get('reason') or ''}"
        ).strip()
        markers.append(
            Marker(
                label=f"Low-confidence cut candidate {index}",
                note=note,
                color="Pink",
                category="cut_candidate_low",
                name="Low-confidence cut candidate",
                session_elapsed_sec=source_sec + offset,
                source_sec=source_sec,
                source_frame=src_frame,
                combined_frame=record_frame,
                snapped=snapped,
            )
        )
        added += 1
    markers.sort(key=lambda marker: (marker.combined_frame, marker.label))
    return {
        "candidate_manifest": str(CUT_CANDIDATES_PATH),
        "loaded": len(candidates),
        "added": added,
        "skipped": skipped,
    }


def escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def safe_file_stem(text: str) -> str:
    return safe_file_stem_text(text)


def asset_xml(asset_id: str, path: Path, duration: int, *, has_video: bool, has_audio: bool) -> str:
    attrs = [f'id="{asset_id}"', f'name="{escape(path.name)}"']
    if has_audio:
        attrs.extend(['audioSources="1"', 'audioChannels="1"', 'hasAudio="1"'])
    if has_video:
        attrs.extend(['hasVideo="1"', 'format="r0"'])
    attrs.extend([f'duration="{B.frames_to_time(duration)}"', 'start="0s"'])
    return (
        f'  <asset {" ".join(attrs)}>\n'
        f'    <media-rep kind="original-media" src="{path_to_uri_localhost(path)}"/>\n'
        "  </asset>"
    )


def write_fcpxml(
    video_clips: list[Clip],
    audio_clips: list[Clip],
    markers: list[Marker],
    out_path: Path,
    timeline_name: str,
) -> dict:
    video_frames = video_duration_frames(VIDEO_PATH)
    audio_frames = media_duration_frames(DIALOGUE_PATH)
    sequence_tc_start = Fraction(3600, 1)
    sequence_start_frames = int(sequence_tc_start * FPS)
    total_frames = max(
        max(c.record_end for c in video_clips),
        max(c.record_end for c in audio_clips),
    )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.10">',
        "<resources>",
        f'  <format name="FFVideoFormat1080p60" id="r0" frameDuration="{FRAME_DURATION}" width="1920" height="1080" colorSpace="1-1-1 (Rec. 709)"/>',
        asset_xml("r2", VIDEO_PATH, video_frames, has_video=True, has_audio=False),
        asset_xml("r3", DIALOGUE_PATH, audio_frames, has_video=False, has_audio=True),
        "</resources>",
        "<library>",
        f'  <event name="{escape(timeline_name)}">',
        f'    <project name="{escape(timeline_name)}">',
        f'      <sequence duration="{B.frames_to_time(total_frames)}" format="r0" tcStart="{B.fraction_to_time(sequence_tc_start)}" tcFormat="NDF" audioLayout="mono" audioRate="48k">',
        "        <spine>",
    ]

    entries: list[tuple[int, int, str]] = []
    for clip in audio_clips:
        offset = B.frames_to_time(sequence_start_frames + clip.offset)
        start = B.frames_to_time(clip.start)
        duration = B.frames_to_time(clip.duration)
        entries.append(
            (
                clip.offset,
                0,
                f'          <asset-clip ref="r3" name="{escape(DIALOGUE_PATH.stem)}" offset="{offset}" duration="{duration}" start="{start}" tcFormat="NDF"/>',
            )
        )
    for clip in video_clips:
        offset = B.frames_to_time(sequence_start_frames + clip.offset)
        start = B.frames_to_time(clip.start)
        duration = B.frames_to_time(clip.duration)
        name = clip.label or VIDEO_PATH.stem
        entries.append(
            (
                clip.offset,
                1,
                f'          <asset-clip ref="r2" name="{escape(name)}" offset="{offset}" duration="{duration}" start="{start}" tcFormat="NDF"/>',
            )
        )
    for _, _, line in sorted(entries, key=lambda row: (row[0], row[1], row[2])):
        lines.append(line)
    lines.append("        </spine>")

    markers_by_frame: dict[int, list[Marker]] = {}
    for marker in markers:
        markers_by_frame.setdefault(marker.combined_frame, []).append(marker)
    for frame, group in sorted(markers_by_frame.items()):
        labels: list[str] = []
        for marker in group:
            if marker.label not in labels:
                labels.append(marker.label)
        lines.append(
            f'        <marker start="{B.frames_to_time(sequence_start_frames + frame)}" '
            f'duration="{FRAME_DURATION}" value="{escape(" / ".join(labels))}" completed="0"/>'
        )

    lines.extend(
        [
            "      </sequence>",
            "    </project>",
            "  </event>",
            "</library>",
            "</fcpxml>",
            "",
        ]
    )
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "fcpxml": str(out_path),
        "timeline_name": timeline_name,
        "timeline_start_frame": sequence_start_frames,
        "total_frames": total_frames,
        "total_seconds": total_frames / FPS,
        "video_clips": len(video_clips),
        "audio_clips": len(audio_clips),
        "marker_frames_embedded": len(markers_by_frame),
        "video_asset_frames": video_frames,
        "audio_asset_frames": audio_frames,
    }


def coalesced_markers(markers: list[Marker]) -> list[dict]:
    by_frame: dict[int, list[Marker]] = {}
    for marker in markers:
        by_frame.setdefault(int(marker.combined_frame), []).append(marker)
    out: list[dict] = []
    for frame, group in sorted(by_frame.items()):
        labels: list[str] = []
        notes: list[str] = []
        for marker in group:
            if marker.label not in labels:
                labels.append(marker.label)
            note = marker.note or marker.category or ""
            if note and note not in notes:
                notes.append(note)
        out.append(
            {
                "frame": frame,
                "name": " / ".join(labels),
                "note": "\n".join(notes),
                "color": group[0].color or "Blue",
                "events": len(group),
            }
        )
    return out


def unique_timeline_name(project, base: str) -> str:
    existing = set()
    for index in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline:
            existing.add(timeline.GetName())
    if base not in existing:
        return base
    i = 2
    while f"{base} {i}" in existing:
        i += 1
    return f"{base} {i}"


def import_to_resolve(fcpxml: Path, markers: list[Marker], timeline_name: str, report_dir: Path) -> dict:
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError(
            "Could not connect to Resolve. Check Resolve is open and external scripting is Local."
        )
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No current Resolve project")
    media_pool = project.GetMediaPool()
    resolve.OpenPage("edit")

    name = unique_timeline_name(project, timeline_name)
    log(f"Importing FCPXML as timeline: {name}")
    imported = media_pool.ImportTimelineFromFile(str(fcpxml), {"timelineName": name})
    if not imported:
        raise RuntimeError(f"ImportTimelineFromFile returned {imported!r}")

    timeline = imported
    project.SetCurrentTimeline(timeline)
    timeline.SetSetting("timelineFrameRate", "60")
    timeline.SetSetting("timelinePlaybackFrameRate", "60")
    timeline.SetSetting("timelineResolutionWidth", "1920")
    timeline.SetSetting("timelineResolutionHeight", "1080")

    timeline.DeleteMarkersByColor("All")
    added = 0
    for marker in coalesced_markers(markers):
        ok = timeline.AddMarker(
            int(marker["frame"]),
            marker["color"],
            marker["name"],
            marker["note"],
            1,
            "rby_umb_manifest",
        )
        added += 1 if ok else 0

    v1 = timeline.GetItemListInTrack("video", 1) or []
    a1 = timeline.GetItemListInTrack("audio", 1) or []
    track_counts = {
        "v1": len(v1),
        "a1": len(a1),
        "v2": len(timeline.GetItemListInTrack("video", 2) or []),
        "a2": len(timeline.GetItemListInTrack("audio", 2) or []),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    drt_path = report_dir / f"{re.sub(r'[^A-Za-z0-9_. -]+', '_', timeline.GetName())}.drt"
    drt_exported = False
    try:
        drt_exported = bool(timeline.Export(str(drt_path), resolve.EXPORT_DRT, resolve.EXPORT_NONE))
    except Exception as exc:
        log(f"WARN: DRT export failed: {exc!r}")

    try:
        project.Save()
    except Exception:
        try:
            resolve.GetProjectManager().SaveProject()
        except Exception as exc:
            log(f"WARN: project save failed: {exc!r}")

    return {
        "project": project.GetName(),
        "timeline": timeline.GetName(),
        "timeline_start_frame": timeline.GetStartFrame(),
        "timeline_end_frame": timeline.GetEndFrame(),
        "timeline_fps": timeline.GetSetting("timelineFrameRate"),
        "track_counts": track_counts,
        "markers_added": added,
        "marker_frames": len(coalesced_markers(markers)),
        "drt_exported": drt_exported,
        "drt": str(drt_path),
    }


def hold_regions_are_current(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    rows = payload.get("regions", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return False
    return any(row.get("kind") in {"post_battle_card_phase", "post_battle_card_manual_override"} for row in rows)


def stop_for_hold_region_decision(reason: str, regions: list[H.HoldRegion] | None = None) -> None:
    HOLD_REGION_STOP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    fallback_regions = [
        asdict(region)
        for region in (regions or [])
        if region.kind == "post_battle_card_numeric_fallback"
    ]
    payload = {
        "schema": "rby_umb_hold_region_stop_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "source_video": str(VIDEO_PATH),
        "session_events": str(SESSION_EVENTS),
        "hold_regions_path": str(HOLD_REGIONS_PATH),
        "hold_regions_override": str(HOLD_REGION_OVERRIDE),
        "fallback_numeric_regions": fallback_regions,
        "options": [
            "Provide a session/events log with complete post-battle card markers and rerun final assembly.",
            f"Provide explicit hold regions at {HOLD_REGION_OVERRIDE} using session_start_sec/session_end_sec or source_start_sec/source_end_sec.",
            "Tell the agent to continue without post-battle visual holds for this project.",
        ],
    }
    HOLD_REGION_STOP_REPORT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    raise RuntimeError(
        "STOP: Required RBYNewLayout post-battle hold markers are unavailable.\n"
        f"Reason: {reason}\n"
        f"Stop report: {HOLD_REGION_STOP_REPORT}\n"
        "Ask the user whether to provide markers, provide explicit hold regions, or continue without those holds."
    )


def ensure_hold_regions() -> None:
    if hold_regions_are_current(HOLD_REGIONS_PATH):
        return
    CODEX_DIR.mkdir(parents=True, exist_ok=True)
    if not SESSION_EVENTS.exists():
        stop_for_hold_region_decision(f"Missing session events for hold-region derivation: {SESSION_EVENTS}")
    events = H.load_json(SESSION_EVENTS)
    offset = source_start_elapsed()
    override_rows = None
    if HOLD_REGION_OVERRIDE.exists():
        payload = H.load_json(HOLD_REGION_OVERRIDE)
        override_rows = payload.get("regions", payload) if isinstance(payload, dict) else payload
    regions = H.derive_regions(
        events,
        source_offset=offset,
        fps=FPS,
        source_dur=source_duration_sec(),
        pad_post_battle_start=0.0,
        pad_post_battle_end=0.0,
        manual_override_rows=override_rows,
    )
    if not any(region.kind in {"post_battle_card_phase", "post_battle_card_manual_override"} for region in regions):
        stop_for_hold_region_decision(
            "No complete post-battle card open/phase/close markers were found.",
            regions,
        )
    payload = {
        "events": str(SESSION_EVENTS),
        "source_video": str(VIDEO_PATH),
        "fps": FPS,
        "source_offset_sec": offset,
        "source_duration_sec": source_duration_sec(),
        "schema": "rby_umb_hold_regions_v2",
        "regions": [asdict(r) for r in regions],
    }
    HOLD_REGIONS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build(
    import_resolve: bool,
    *,
    with_visual_holds: bool = True,
    timeline_name: str | None = None,
    manifest_path: Path | None = None,
    extra_source_cuts: Path | None = None,
    apply_locked_structural_cuts: bool = False,
) -> dict:
    CODEX_DIR.mkdir(parents=True, exist_ok=True)
    timeline_name = timeline_name or FINAL_NAME
    if timeline_name == REVIEW_NAME:
        out_fcpxml = profile_path("review_fcpxml", PROJECT_DIR / f"{timeline_name}.fcpxml")
    elif timeline_name == FINAL_NAME:
        out_fcpxml = profile_path("final_fcpxml", PROJECT_DIR / f"{timeline_name}.fcpxml")
    else:
        out_fcpxml = PROJECT_DIR / f"{timeline_name}.fcpxml"
    if manifest_path is None:
        if timeline_name == FINAL_NAME:
            manifest_path = MANIFEST_PATH
        elif timeline_name == REVIEW_NAME:
            manifest_path = profile_path("review_manifest", CODEX_DIR / f"{safe_file_stem(timeline_name)}_manifest.json")
        else:
            manifest_path = CODEX_DIR / f"{safe_file_stem(timeline_name)}_manifest.json"
    if not VIDEO_PATH.exists():
        raise FileNotFoundError(VIDEO_PATH)
    if not DIALOGUE_PATH.exists():
        raise FileNotFoundError(DIALOGUE_PATH)
    if not RAW_AUTOEDITOR_FCPXML.exists():
        raise FileNotFoundError(RAW_AUTOEDITOR_FCPXML)

    keep_start = source_frame(SOURCE_START_SEC)
    keep_end = min(video_duration_frames(VIDEO_PATH), media_duration_frames(DIALOGUE_PATH))
    proposed_structural_cut_rows = list(STRUCTURAL_SOURCE_CUTS)
    extra_cut_rows = load_extra_source_cuts(extra_source_cuts)
    locked_manual_cut_rows = proposed_structural_cut_rows if apply_locked_structural_cuts else []
    manual_cut_rows = locked_manual_cut_rows + extra_cut_rows
    manual_cuts = [(int(row["start_frame"]), int(row["end_frame"])) for row in manual_cut_rows]
    raw_intervals = parse_autoeditor_intervals(RAW_AUTOEDITOR_FCPXML)
    holds: list[dict] = []
    if with_visual_holds:
        ensure_hold_regions()
        holds = load_holds(
            HOLD_REGIONS_PATH,
            VISUAL_HOLD_KINDS,
            keep_start,
            keep_end,
        )
    first_auto_after_start = next((clip.start for clip in raw_intervals if clip.end > keep_start), keep_start)
    force_keep_ranges = []
    if first_auto_after_start > keep_start:
        force_keep_ranges.append((keep_start, first_auto_after_start))
    if with_visual_holds:
        force_keep_ranges.extend((int(hold["start"]), int(hold["end"])) for hold in holds)
    audio_clips, audio_map = build_audio_spine(
        raw_intervals,
        keep_start=keep_start,
        keep_end=keep_end,
        cuts=manual_cuts,
        force_keep_ranges=force_keep_ranges,
    )
    if with_visual_holds:
        video_clips, hold_report = apply_visual_holds(audio_clips, holds)
    else:
        video_clips = list(audio_clips)
        hold_report = {
            "input_clips": len(audio_clips),
            "output_clips": len(video_clips),
            "holds_requested": 0,
            "holds_emitted": 0,
            "duration_delta": 0,
            "visual_only": True,
            "disabled_for_review_base": True,
        }
    markers, marker_timing = build_markers(video_clips, keep_start, keep_end, manual_cuts)
    low_candidate_marker_report = (
        append_low_confidence_candidate_markers(markers, video_clips, keep_start, keep_end, manual_cuts)
        if with_visual_holds
        else {"candidate_manifest": str(CUT_CANDIDATES_PATH), "loaded": 0, "added": 0, "skipped": [], "disabled_for_review_base": True}
    )
    fcpxml_report = write_fcpxml(video_clips, audio_clips, markers, out_fcpxml, timeline_name)

    manifest = {
        "schema": "rby_umb_fcpxml_build_v3",
        "stage": "review_base" if not with_visual_holds else "editorial_base_with_visual_holds",
        "timeline_name": timeline_name,
        "project_dir": str(PROJECT_DIR),
        "session_dir": str(SESSION_DIR),
        "source_video": str(VIDEO_PATH),
        "dialogue_audio": str(DIALOGUE_PATH),
        "raw_autoeditor_fcpxml": str(RAW_AUTOEDITOR_FCPXML),
        "hold_regions": str(HOLD_REGIONS_PATH),
        "manual_edits": {
            "source_start": {
                "sec": SOURCE_START_SEC,
                "frame": keep_start,
                "reason": SOURCE_START_REASON,
            },
            "cuts": [
                *manual_cut_rows,
            ],
            "proposed_structural_cuts": proposed_structural_cut_rows,
            "apply_locked_structural_cuts": apply_locked_structural_cuts,
            "extra_source_cuts_file": str(extra_source_cuts) if extra_source_cuts else None,
            "extra_source_cuts": extra_cut_rows,
        },
        "autoeditor": {
            "driver": str(DIALOGUE_PATH),
            "margin": "0.1sec",
            "time_base": FPS,
            "raw_intervals": len(raw_intervals),
            "force_keep_ranges": [
                {
                    "start_frame": start,
                    "end_frame": end,
                    "start_sec": start / FPS,
                    "end_sec": end / FPS,
                    "reason": "restore source-backed lead-in before first auto-editor dialogue",
                }
                for start, end in force_keep_ranges
            ],
        },
        "spine": {
            "audio_clips": len(audio_clips),
            "video_clips": len(video_clips),
            "audio_frames": max(c.record_end for c in audio_clips),
            "video_frames": max(c.record_end for c in video_clips),
            "audio_source_to_record": audio_map,
            "visual_holds_enabled": with_visual_holds,
            "visual_hold_report": hold_report,
        },
        "markers": [asdict(m) for m in markers],
        "marker_timing": marker_timing,
        "low_confidence_candidate_markers": low_candidate_marker_report,
        "fcpxml": fcpxml_report,
        "notes": [
            "OBS/session marker timecodes are not source time; all marker and cut timing uses MP4 creation_time minus meta.startedAt.",
            f"Dialogue audio source: {DIALOGUE_PATH}.",
            (
                "Visual holds are disabled for the review base; add them only in the deterministic final rebuild after cuts are approved."
                if not with_visual_holds
                else "Visual holds are V1-only replacements over the compressed auto-editor record span; A1 remains the dialogue spine."
            ),
            "Member carousel open-region layout is intentionally not expanded here; do a downstream carousel pass if V2 cropped overlay preservation is needed.",
        ],
    }

    if import_resolve:
        manifest["resolve_import"] = import_to_resolve(
            out_fcpxml,
            markers,
            timeline_name,
            CODEX_DIR / "drt-checkpoints",
        )

    manifest["_manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-to-resolve", action="store_true")
    parser.add_argument("--review-base", action="store_true",
                        help=f"Build the lightweight review timeline ({REVIEW_NAME}) with no visual holds.")
    parser.add_argument("--no-visual-holds", action="store_true",
                        help="Disable V1 visual holds for this build.")
    parser.add_argument("--timeline-name", default=None,
                        help="Override the FCPXML/Resolve timeline name.")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="Override the manifest output path.")
    parser.add_argument("--extra-source-cuts", type=Path, default=None,
                        help="Approved source-time cuts to add before final rebuild.")
    parser.add_argument("--apply-locked-structural-cuts", action="store_true",
                        help="Apply the historical default restart cuts without HTML review decisions.")
    args = parser.parse_args()

    timeline_name = args.timeline_name
    if args.review_base and not timeline_name:
        timeline_name = REVIEW_NAME
    manifest = build(
        args.import_to_resolve,
        with_visual_holds=not (args.no_visual_holds or args.review_base),
        timeline_name=timeline_name,
        manifest_path=args.manifest,
        extra_source_cuts=args.extra_source_cuts,
        apply_locked_structural_cuts=args.apply_locked_structural_cuts,
    )
    summary = {
        "fcpxml": manifest["fcpxml"]["fcpxml"],
        "manifest": manifest["_manifest_path"],
        "timeline": manifest.get("resolve_import", {}).get("timeline"),
        "stage": manifest["stage"],
        "duration_seconds": manifest["fcpxml"]["total_seconds"],
        "audio_clips": manifest["spine"]["audio_clips"],
        "video_clips": manifest["spine"]["video_clips"],
        "markers": len(manifest["markers"]),
        "holds_emitted": manifest["spine"]["visual_hold_report"]["holds_emitted"],
    }
    log(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
