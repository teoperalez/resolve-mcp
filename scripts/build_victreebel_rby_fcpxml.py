from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Iterable


PROJECT_DIR = Path(r"E:\Victreebel Red and Blue Ultra Minimum Battles")
CODEX_DIR = PROJECT_DIR / "CODEx"
CODEX_ASSETS_DIR = CODEX_DIR / "assets"
SESSION_DIR = Path(r"C:\Users\teope\AppData\Roaming\rbypc-frontend\logs\2026-05-16T04_28_56_871__Victreebel__Ultra_Minimum_Battles")
RBY_ROOT = Path(r"C:\Programming\RBYNewLayout")
LEADER_DIR = RBY_ROOT / "gymLeaders" / "LeaderIntros"
INTRO_SOURCE = RBY_ROOT / "Blue Version Intro.mp4"
BGM_SOURCE = RBY_ROOT / "audio" / "bgm" / "Dual Screen Lovelife.mp3"
OUTRO_SOURCE = Path(r"E:\RBY Assets\RBY Outro w audio.mov")
PART1_DIALOGUE = PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 1_tracks" / "Victreebel Red and Blue Ultra Minimum Battles part 1_3.wav"
PART2_DIALOGUE = PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2_tracks" / "Victreebel Red and Blue Ultra Minimum Battles part 2_3.wav"
INTRO_PATH = INTRO_SOURCE
BGM_PATH = BGM_SOURCE
OUTRO_PATH = OUTRO_SOURCE

FPS = 60
FRAME_DURATION = f"1/{FPS}s"
FINAL_NAME = "Victreebel Red and Blue Ultra Minimum Battles CODEx RBY log rebuild"


@dataclass
class Clip:
    part: int
    src: Path
    dialogue: Path | None
    offset: int
    start: int
    duration: int
    name: str


@dataclass
class Marker:
    label: str
    note: str
    color: str
    category: str
    name: str
    session_elapsed_sec: float
    source_part: int
    source_sec: float
    source_frame: int
    part_timeline_frame: int
    combined_frame: int
    snapped: bool


def _run_json(cmd: list[str]) -> dict:
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(p.stdout)


def ffprobe(path: Path) -> dict:
    return _run_json([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])


def media_duration_frames(path: Path) -> int:
    data = ffprobe(path)
    dur = float(data["format"]["duration"])
    return int(round(dur * FPS))


def creation_time(path: Path) -> datetime:
    data = ffprobe(path)
    raw = (data.get("format", {}).get("tags", {}) or {}).get("creation_time")
    if not raw:
        raise RuntimeError(f"No creation_time in {path}")
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_time_to_frames(value: str) -> int:
    value = value.strip()
    if not value.endswith("s"):
        raise ValueError(value)
    value = value[:-1]
    if "/" in value:
        num, den = value.split("/", 1)
        return int(round(float(num) / float(den) * FPS))
    return int(round(float(value) * FPS))


def frames_to_time(frames: int) -> str:
    return f"{int(frames)}/{FPS}s"


def path_to_uri(path: Path) -> str:
    p = str(path.resolve()).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://" + urllib.parse.quote(p, safe="/:")


def path_to_uri_localhost(path: Path) -> str:
    p = str(path.resolve()).replace("\\", "/")
    return "file://localhost/" + urllib.parse.quote(p, safe="/:")


def fraction_to_time(value: Fraction) -> str:
    value = Fraction(value)
    return f"{value.numerator}/{value.denominator}s"


def video_stream(path: Path) -> dict | None:
    data = ffprobe(path)
    return next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)


def parse_rate(rate: str | None) -> Fraction:
    if not rate or rate == "0/0":
        return Fraction(FPS, 1)
    if "/" in rate:
        num, den = rate.split("/", 1)
        return Fraction(int(num), int(den))
    return Fraction(rate)


def video_duration_frames(path: Path) -> int:
    stream = video_stream(path)
    if not stream:
        return media_duration_frames(path)
    rate = parse_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    frames = int(stream.get("nb_frames") or 0)
    if frames > 0:
        return int(round(Fraction(frames, 1) * FPS / rate))
    dur = Fraction(str(stream.get("duration") or ffprobe(path)["format"]["duration"]))
    return int(round(dur * FPS))


def timecode_to_seconds(tc: str, rate: Fraction) -> Fraction:
    hh, mm, ss, ff = [int(x) for x in tc.replace(";", ":").split(":", 3)]
    return Fraction(hh * 3600 + mm * 60 + ss, 1) + Fraction(ff, 1) / rate


def source_timecode_start(path: Path) -> Fraction:
    stream = video_stream(path)
    if not stream:
        return Fraction(0, 1)
    tags = stream.get("tags") or {}
    tc = tags.get("timecode")
    if not tc:
        return Fraction(0, 1)
    rate = parse_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    return timecode_to_seconds(tc, rate)


def copy_asset(src: Path, group: str) -> Path:
    dst = CODEX_ASSETS_DIR / group / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copy2(src, dst)
    return dst


def escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def write_path_corrected(src: Path, out: Path) -> None:
    text = src.read_text(encoding="utf-8")
    text = text.replace(
        "file:///C:/Users/teope/Videos/Victreebel%20Red%20and%20Blue%20Ultra%20Minimum%20Battles/",
        "file:///E:/Victreebel%20Red%20and%20Blue%20Ultra%20Minimum%20Battles/",
    )
    text = text.replace(
        "file:///C:/Users/teope/Videos/Victreebel Red and Blue Ultra Minimum Battles/",
        "file:///E:/Victreebel Red and Blue Ultra Minimum Battles/",
    )
    out.write_text(text, encoding="utf-8")


def video_asset_path(asset: ET.Element) -> Path:
    rep = asset.find("media-rep")
    if rep is None:
        raise RuntimeError(f"Asset {asset.get('id')} has no media-rep")
    uri = rep.get("src") or ""
    if not uri.startswith("file://"):
        raise RuntimeError(f"Unsupported URI: {uri}")
    raw = urllib.parse.unquote(uri[7:])
    if re.match(r"^/[A-Za-z]:/", raw):
        raw = raw[1:]
    return Path(raw)


def load_video_clips(fcpxml: Path, part: int, dialogue: Path | None) -> list[Clip]:
    root = ET.parse(fcpxml).getroot()
    assets = {a.get("id"): a for a in root.findall(".//asset")}
    video_ids = {aid for aid, a in assets.items() if a.get("hasVideo") == "1"}
    if len(video_ids) != 1:
        raise RuntimeError(f"Expected one video asset in {fcpxml}, got {sorted(video_ids)}")
    video_id = next(iter(video_ids))
    src_path = video_asset_path(assets[video_id])
    clips: list[Clip] = []
    for ac in root.findall(".//spine/asset-clip"):
        if ac.get("ref") != video_id:
            continue
        clips.append(Clip(
            part=part,
            src=src_path,
            dialogue=dialogue.resolve() if dialogue else None,
            offset=parse_time_to_frames(ac.get("offset", "0s")),
            start=parse_time_to_frames(ac.get("start", "0s")),
            duration=parse_time_to_frames(ac.get("duration", "0s")),
            name=ac.get("name") or src_path.stem,
        ))
    clips.sort(key=lambda c: c.offset)
    return clips


def map_source_frame(clips: list[Clip], src_frame: int) -> tuple[int | None, bool]:
    for c in clips:
        if c.start <= src_frame < c.start + c.duration:
            return c.offset + (src_frame - c.start), False
    next_clip = next((c for c in sorted(clips, key=lambda x: x.start) if c.start > src_frame), None)
    if next_clip is None:
        return None, False
    return next_clip.offset, True


def load_intended_markers() -> list:
    scripts = RBY_ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import session_marker_labels as sml  # type: ignore
    events = json.loads((SESSION_DIR / "events.json").read_text(encoding="utf-8-sig"))
    return sml.replay_markers(events)


def build_markers(part2_clips: list[Clip], part2_offset_in_combined: int) -> tuple[list[Marker], dict]:
    meta = json.loads((SESSION_DIR / "meta.json").read_text(encoding="utf-8-sig"))
    session_start = datetime.fromisoformat(meta["startedAt"].replace("Z", "+00:00")).astimezone(timezone.utc)
    part2_start = creation_time(PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2.mp4")
    part2_start_elapsed = (part2_start - session_start).total_seconds()
    part2_duration_sec = media_duration_frames(PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2.mp4") / FPS

    out: list[Marker] = []
    for im in load_intended_markers():
        elapsed = im.t_elapsed_ms / 1000.0
        source_sec = elapsed - part2_start_elapsed
        if source_sec < 0 or source_sec > part2_duration_sec:
            continue
        src_frame = int(round(source_sec * FPS))
        part_frame, snapped = map_source_frame(part2_clips, src_frame)
        if part_frame is None:
            continue
        out.append(Marker(
            label=im.label,
            note=im.note,
            color=im.color,
            category=im.category,
            name=im.name,
            session_elapsed_sec=elapsed,
            source_part=2,
            source_sec=source_sec,
            source_frame=src_frame,
            part_timeline_frame=part_frame,
            combined_frame=part2_offset_in_combined + part_frame,
            snapped=snapped,
        ))
    return out, {
        "session_started_at": meta["startedAt"],
        "part2_creation_time": part2_start.isoformat(),
        "part2_start_elapsed_sec": part2_start_elapsed,
        "part2_duration_sec": part2_duration_sec,
    }


BLUE_VARIANTS = {"Surge", "Erika", "Koga", "Sabrina", "Blaine", "Giovanni", "Champion"}
LEADER_ALIASES = {"Lt. Surge": "Surge", "Rival": "Rival"}


def leader_key(label: str) -> str | None:
    m = re.match(r"^(.*?) Battle Start$", label)
    if not m:
        return None
    leader = m.group(1)
    return LEADER_ALIASES.get(leader, leader)


def leader_video_path(leader: str) -> Path | None:
    if leader == "Rival":
        return None
    preferred = LEADER_DIR / f"{leader}Blue.mp4"
    if leader in BLUE_VARIANTS and preferred.exists():
        return copy_asset(preferred, "leader-intros")
    standard = LEADER_DIR / f"{leader}.mp4"
    return copy_asset(standard, "leader-intros") if standard.exists() else None


def leader_audio_path(leader: str) -> Path | None:
    if leader == "Rival":
        p = LEADER_DIR / "audio" / "Rival.mp3"
    elif leader == "Giovanni":
        p = LEADER_DIR / "audio" / "Giovanni 3.mp3"
    else:
        p = LEADER_DIR / "audio" / f"{leader}.mp3"
    return copy_asset(p, "leader-audio") if p.exists() else None


def battle_pairs(markers: Iterable[Marker]) -> list[tuple[Marker, Marker | None]]:
    starts = [m for m in markers if m.label.endswith("Battle Start")]
    finishes = [m for m in markers if m.label.endswith("Battle Finish")]
    pairs: list[tuple[Marker, Marker | None]] = []
    for st in starts:
        key = st.label.removesuffix(" Battle Start")
        finish = next((m for m in finishes if m.label == f"{key} Battle Finish" and m.combined_frame > st.combined_frame), None)
        pairs.append((st, finish))
    return pairs


def register_asset(
    assets: dict[Path, dict],
    path: Path,
    max_frames: int,
    has_video: bool,
    has_audio: bool = True,
) -> None:
    path = path.resolve()
    current = assets.get(path)
    if current:
        current["duration"] = max(current["duration"], max_frames)
        current["has_video"] = current["has_video"] or has_video
        current["has_audio"] = current["has_audio"] or has_audio
        return
    assets[path] = {
        "id": f"r{len(assets) + 2}",
        "duration": max_frames,
        "has_video": has_video,
        "has_audio": has_audio,
    }


def build_final_fcpxml(part1: list[Clip], part2: list[Clip], markers: list[Marker], out_path: Path) -> dict:
    intro_frames = video_duration_frames(INTRO_PATH)
    bgm_frames = media_duration_frames(BGM_PATH)
    outro_frames = video_duration_frames(OUTRO_PATH)
    sequence_tc_start = Fraction(3600, 1)
    sequence_start_frames = int(sequence_tc_start * FPS)
    intro_start_time = source_timecode_start(INTRO_PATH)
    outro_start_time = source_timecode_start(OUTRO_PATH)

    gameplay_start = intro_frames
    part1_len = max(c.offset + c.duration for c in part1)
    part2_base = gameplay_start + part1_len

    assets: dict[Path, dict] = {}
    entries: list[dict] = []

    def register(
        path: Path,
        max_frames: int,
        has_video: bool,
        has_audio: bool,
        *,
        format_id: str = "r0",
        start_time: Fraction = Fraction(0, 1),
        duration_time: Fraction | None = None,
        name: str | None = None,
    ) -> None:
        path = path.resolve()
        current = assets.get(path)
        if current:
            current["duration"] = max(current["duration"], max_frames)
            current["has_video"] = current["has_video"] or has_video
            current["has_audio"] = current["has_audio"] or has_audio
            if has_video:
                current["format_id"] = format_id
            if duration_time is None:
                current["duration_time"] = None
            return
        assets[path] = {
            "id": f"r{len(assets) + 2}",
            "duration": max_frames,
            "duration_time": duration_time,
            "has_video": has_video,
            "has_audio": has_audio,
            "format_id": format_id,
            "start_time": start_time,
            "name": name or path.name,
        }

    def add_video(path: Path, src_in: int, duration: int, offset: int, name: str, embedded_audio: bool = False) -> None:
        register(path, src_in + duration, True, embedded_audio)
        entries.append({"type": "video", "path": path.resolve(), "src_in": src_in, "duration": duration, "offset": offset, "name": name})

    def add_audio(path: Path, src_in: int, duration: int, offset: int, name: str) -> None:
        register(path, src_in + duration, False, True)
        entries.append({"type": "audio", "path": path.resolve(), "src_in": src_in, "duration": duration, "offset": offset, "name": name})

    register(
        INTRO_PATH,
        intro_frames,
        True,
        False,
        format_id="r1",
        start_time=intro_start_time,
        duration_time=Fraction(intro_frames, FPS),
        name=INTRO_PATH.name,
    )
    register(
        BGM_PATH,
        max(bgm_frames, intro_frames),
        False,
        True,
        duration_time=Fraction(max(bgm_frames, intro_frames), FPS),
        name=BGM_PATH.name,
    )

    for c in part1:
        if c.dialogue:
            add_audio(c.dialogue, c.start, c.duration, gameplay_start + c.offset, c.name)
        add_video(c.src, c.start, c.duration, gameplay_start + c.offset, c.name)
    for c in part2:
        if c.dialogue:
            add_audio(c.dialogue, c.start, c.duration, part2_base + c.offset, c.name)
        add_video(c.src, c.start, c.duration, part2_base + c.offset, c.name)

    leader_plan = [{
        "status": "deferred_to_place_battle_intros_gen1",
        "script": "scripts/place_battle_intros.py --gen1-insert",
    }]

    end_without_outro = max(part2_base + c.offset + c.duration for c in part2)
    register(
        OUTRO_PATH,
        outro_frames,
        True,
        True,
        format_id="r0",
        start_time=outro_start_time,
        duration_time=Fraction(outro_frames, FPS),
        name=OUTRO_PATH.name,
    )
    entries.append({
        "type": "video",
        "path": OUTRO_PATH.resolve(),
        "src_in": int(outro_start_time * FPS),
        "duration": outro_frames,
        "offset": end_without_outro,
        "name": OUTRO_PATH.name,
        "native_start": outro_start_time,
    })
    total = end_without_outro + outro_frames

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.10">',
        "<resources>",
        f'  <format name="FFVideoFormat1080p60" id="r0" frameDuration="{FRAME_DURATION}" width="1920" height="1080" colorSpace="1-1-1 (Rec. 709)"/>',
        '  <format name="FFVideoFormat3840x2160p30" id="r1" frameDuration="1/30s" width="3840" height="2160" colorSpace="1-1-1 (Rec. 709)"/>',
    ]
    for path, meta in assets.items():
        aid = meta["id"]
        attrs = []
        if meta["has_audio"]:
            attrs.extend(['audioSources="1"', 'audioChannels="2"', 'hasAudio="1"'])
        if meta["has_video"]:
            attrs.extend(['hasVideo="1"', f'format="{meta["format_id"]}"'])
        duration = fraction_to_time(meta["duration_time"]) if meta["duration_time"] is not None else frames_to_time(meta["duration"])
        lines.extend([
            f'  <asset id="{aid}" name="{escape(meta["name"])}" {" ".join(attrs)} duration="{duration}" start="{fraction_to_time(meta["start_time"])}">',
            f'    <media-rep kind="original-media" src="{path_to_uri_localhost(path)}"/>',
            "  </asset>",
        ])
    lines.extend([
        "</resources>",
        "<library>",
        f'  <event name="{escape(FINAL_NAME)}">',
        f'    <project name="{escape(FINAL_NAME)}">',
        f'      <sequence duration="{frames_to_time(total)}" format="r0" tcStart="{fraction_to_time(sequence_tc_start)}" tcFormat="NDF" audioLayout="stereo" audioRate="48k">',
        "        <spine>",
    ])
    intro_ref = assets[INTRO_PATH.resolve()]["id"]
    bgm_ref = assets[BGM_PATH.resolve()]["id"]
    intro_duration = fraction_to_time(Fraction(intro_frames, FPS))
    lines.extend([
        f'          <asset-clip ref="{intro_ref}" name="{escape(INTRO_PATH.name)}" enabled="1" offset="{fraction_to_time(sequence_tc_start)}" duration="{intro_duration}" start="{fraction_to_time(intro_start_time)}" format="r1" tcFormat="NDF">',
        '            <adjust-transform scale="1 1" anchor="0 0" position="0 0"/>',
        f'            <asset-clip lane="2" ref="{bgm_ref}" name="{escape(BGM_PATH.name)}" enabled="1" offset="{fraction_to_time(intro_start_time)}" duration="{intro_duration}" start="0/1s"/>',
        "          </asset-clip>",
    ])
    for e in sorted(entries, key=lambda x: (x["offset"], 0 if x["type"] == "audio" else 1)):
        ref = assets[e["path"]]["id"]
        offset = frames_to_time(sequence_start_frames + e["offset"])
        start = fraction_to_time(e["native_start"]) if "native_start" in e else frames_to_time(e["src_in"])
        duration = frames_to_time(e["duration"])
        lines.append(f'          <asset-clip ref="{ref}" name="{escape(e["name"])}" offset="{offset}" duration="{duration}" start="{start}" tcFormat="NDF"/>')
    lines.append("        </spine>")
    markers_by_frame: dict[int, list[Marker]] = {}
    for marker in sorted(markers, key=lambda x: x.combined_frame):
        markers_by_frame.setdefault(marker.combined_frame, []).append(marker)
    for frame, group in sorted(markers_by_frame.items()):
        labels = []
        for marker in group:
            if marker.label not in labels:
                labels.append(marker.label)
        lines.append(
            f'        <marker start="{frames_to_time(sequence_start_frames + frame)}" '
            f'duration="{FRAME_DURATION}" value="{escape(" / ".join(labels))}" completed="0"/>'
        )
    lines.extend([
        "      </sequence>",
        "    </project>",
        "  </event>",
        "</library>",
        "</fcpxml>",
    ])
    out_path.write_text("\n".join(lines), encoding="utf-8")
    manifest_assets = {}
    for path, meta in assets.items():
        manifest_assets[str(path)] = {
            "id": meta["id"],
            "duration": meta["duration"],
            "duration_time": fraction_to_time(meta["duration_time"]) if meta["duration_time"] is not None else None,
            "has_video": meta["has_video"],
            "has_audio": meta["has_audio"],
            "format_id": meta["format_id"],
            "start_time": fraction_to_time(meta["start_time"]),
            "name": meta["name"],
        }

    return {
        "final_name": FINAL_NAME,
        "output_fcpxml": str(out_path),
        "total_frames": total,
        "total_seconds": total / FPS,
        "part1_edit_frames": part1_len,
        "part2_combined_base_frame": part2_base,
        "intro_frames": intro_frames,
        "outro_frames": outro_frames,
        "fcpxml_tc_start": fraction_to_time(sequence_tc_start),
        "timeline_start_frame": sequence_start_frames,
        "markers_embedded": True,
        "embedded_marker_frames": len(markers_by_frame),
        "leader_plan": leader_plan,
        "assets": manifest_assets,
    }


def write_setup_script(path: Path, marker_manifest: Path) -> None:
    path.write_text(f'''from __future__ import annotations
import json, os, sys

sys.path.insert(0, r"C:\\Programming\\resolve-mcp\\scripts")
import _resolve_env  # noqa
import DaVinciResolveScript as dvr

MARKERS = r"{marker_manifest}"

resolve = dvr.scriptapp("Resolve")
project = resolve.GetProjectManager().GetCurrentProject()
timeline = project.GetCurrentTimeline()
if not timeline:
    raise SystemExit("No current timeline. Import/select the CODEx RBY log rebuild FCPXML first.")
data = json.load(open(MARKERS, "r", encoding="utf-8"))
expected_name = data.get("final", {{}}).get("final_name")
print(f"Current timeline: {{timeline.GetName()}}")
if expected_name and expected_name not in timeline.GetName():
    print(f"WARN: expected timeline containing {{expected_name!r}}")
existing = timeline.GetMarkers() or {{}}
manifest_labels = {{m["label"] for m in data["markers"]}}
for frame in list(existing.keys()):
    info = existing.get(frame) or {{}}
    name = info.get("name") or ""
    if name in manifest_labels or any(part in manifest_labels for part in name.split(" / ")):
        timeline.DeleteMarkerAtFrame(int(frame))
by_frame = {{}}
for m in data["markers"]:
    frame = int(m["combined_frame"])
    by_frame.setdefault(frame, []).append(m)
added = 0
for frame, group in sorted(by_frame.items()):
    labels = []
    notes = []
    for m in group:
        if m["label"] not in labels:
            labels.append(m["label"])
        note = m.get("note") or m.get("category") or ""
        if note and note not in notes:
            notes.append(note)
    color = group[0].get("color") or "Blue"
    ok = timeline.AddMarker(frame, color, " / ".join(labels), "\\n".join(notes), 1)
    added += 1 if ok else 0
print(f"Colored markers added: {{added}}/{{len(by_frame)}} unique frames from {{len(data['markers'])}} manifest events")
print("Leader intro rule: Blue-specific intro used when present; standard intro fallback otherwise.")
''', encoding="utf-8")


def write_readme(path: Path, fcpxml: Path, manifest: Path, setup_script: Path, final_info: dict, markers: list[Marker]) -> None:
    placed = [p for p in final_info["leader_plan"] if p["status"] == "placed"]
    missing = [p for p in final_info["leader_plan"] if p["status"] != "placed"]
    blue = [p["leader"] for p in placed if p.get("used_blue_variant")]
    fallback = [p["leader"] for p in placed if not p.get("used_blue_variant")]
    lines = [
        "# Victreebel RBY UMB CODEx Setup",
        "",
        "Import this FCPXML in Resolve:",
        f"- `{fcpxml}`",
        "",
        "After import, select that timeline and run this from the Resolve MCP machine to restore colored markers from the manifest:",
        f"- `C:\\Programming\\resolve-mcp\\.venv\\Scripts\\python.exe C:\\Programming\\resolve-mcp\\scripts\\apply_victreebel_manifest_markers.py \"{manifest}\" --timeline \"<imported timeline name>\" --clear`",
        "",
        "The FCPXML uses native source-timecode declarations for the intro/outro so Resolve's importer accepts those media. Marker labels are also written into the FCPXML, but Resolve may ignore sequence-level marker tags on import; the manifest marker applier is the authoritative restoration step.",
        "",
        "After structural media is inserted, verify intro/outro/leader-intro durations against source FPS:",
        f"- `C:\\Programming\\resolve-mcp\\.venv\\Scripts\\python.exe C:\\Programming\\resolve-mcp\\scripts\\verify_structural_video_durations.py --timeline \"<timeline name>\" --out \"{CODEX_DIR}\\structural_video_duration_check.json\"`",
        "",
        "Source handling:",
        "- Part 1 and Part 2 remain separate source media.",
        f"- Part 1 dialogue is `{PART1_DIALOGUE}`.",
        f"- Part 2 dialogue is `{PART2_DIALOGUE}`.",
        "- Part 1 uses the auto-editor stream closest to silence-stripped `part 1_3.wav`.",
        "- Part 2 uses auto-editor cuts generated directly from `part 2_3.wav` at 60fps.",
        "- Only Part 2 uses RBYNewLayout log markers.",
        "- Marker timing is computed from the RBY session start and Part 2 MP4 creation time, then mapped through the Part 2 auto-editor clip structure.",
        "- Gameplay MP4 assets are declared video-only; A1 dialogue comes from the explicit part-specific `_3.wav` files.",
        "",
        "Leader intro rule:",
        "- This base FCPXML intentionally does not bake leader intros in as overlays.",
        "- After importing/restoring markers, run `scripts\\place_battle_intros.py --gen1-insert` so discrete leader intro video/audio is inserted as real timeline time and later gameplay ripples right.",
        "- The Step 9 Gen 1 audit then protects those leader intro sections in every later audit.",
        "",
        "Known omissions:",
        "- Rival battle start/finish markers are present, but no Rival video intro exists in the RBY leader-intro folder, so Rival intro video was not inserted.",
        "",
        "Generated files:",
        f"- Manifest JSON: `{manifest}`",
        f"- Colored marker setup script: `{setup_script}`",
        "- Progress-logged marker applier: `C:\\Programming\\resolve-mcp\\scripts\\apply_victreebel_manifest_markers.py`",
        "- Structural video duration verifier: `C:\\Programming\\resolve-mcp\\scripts\\verify_structural_video_durations.py`",
        f"- Marker count: {len(markers)}",
        "- Leader intro placements: deferred to Gen 1 ripple insertion step.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    global INTRO_PATH, BGM_PATH, OUTRO_PATH
    CODEX_DIR.mkdir(parents=True, exist_ok=True)
    INTRO_PATH = copy_asset(INTRO_SOURCE, "global")
    BGM_PATH = copy_asset(BGM_SOURCE, "global")
    OUTRO_PATH = copy_asset(OUTRO_SOURCE, "global")

    part1_src = PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 1_ALTERED.fcpxml"
    part2_src = PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2_ALTERED.fcpxml"
    part1_fixed = PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 1_CODEx_E_DRIVE_SOURCE.fcpxml"
    part2_fixed = PROJECT_DIR / "Victreebel Red and Blue Ultra Minimum Battles part 2_CODEx_E_DRIVE_SOURCE.fcpxml"
    write_path_corrected(part1_src, part1_fixed)
    write_path_corrected(part2_src, part2_fixed)

    part1 = load_video_clips(part1_fixed, 1, PART1_DIALOGUE)
    part2 = load_video_clips(part2_fixed, 2, PART2_DIALOGUE)
    intro_frames = media_duration_frames(INTRO_PATH)
    part1_len = max(c.offset + c.duration for c in part1)
    part2_base = intro_frames + part1_len
    markers, timing = build_markers(part2, part2_base)

    out_fcpxml = PROJECT_DIR / f"{FINAL_NAME}.fcpxml"
    final_info = build_final_fcpxml(part1, part2, markers, out_fcpxml)

    manifest = {
        "project_dir": str(PROJECT_DIR),
        "session_dir": str(SESSION_DIR),
        "source_fcpxmls": {
            "part1_original": str(part1_src),
            "part2_original": str(part2_src),
            "part1_e_drive_source": str(part1_fixed),
            "part2_e_drive_source": str(part2_fixed),
        },
        "dialogue_audio": {
            "part1": str(PART1_DIALOGUE),
            "part2": str(PART2_DIALOGUE),
        },
        "part1_autoeditor": {
            "driver": "audio:stream=3",
            "margin": "0.1sec",
            "description": "Part 1 uses the MP4 audio stream whose edited duration is closest to silence-stripped part 1_3.wav.",
        },
        "part2_autoeditor": {
            "driver": str(PART2_DIALOGUE),
            "margin": "0.1sec",
            "time_base": 60,
            "description": "Part 2 uses auto-editor cuts generated directly from part 2_3.wav, the detected dialogue track.",
        },
        "timing": timing,
        "markers": [asdict(m) for m in markers],
        "final": final_info,
        "notes": [
            "Part 1 and part 2 were kept as separate source media.",
            "Only part 2 received RBYNewLayout log markers.",
            "Leader intro selection prefers Blue-specific files and falls back to standard files.",
            "Gameplay video assets are declared video-only; A1 dialogue is explicit part-specific _3.wav audio.",
            "Gen 1 leader intro insertion is deferred to place_battle_intros.py --gen1-insert so gameplay ripples right.",
            "Run scripts/apply_victreebel_manifest_markers.py after importing the FCPXML in Resolve to restore marker colors from the manifest.",
        ],
    }
    manifest_path = CODEX_DIR / "Victreebel_RBY_UMB_CODEx_rebuild_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    setup_script = CODEX_DIR / "Victreebel_RBY_UMB_CODEx_resolve_setup.py"
    write_setup_script(setup_script, manifest_path)
    readme = CODEX_DIR / "EDITOR_SETUP.md"
    write_readme(readme, out_fcpxml, manifest_path, setup_script, final_info, markers)

    print(json.dumps({
        "fcpxml": str(out_fcpxml),
        "manifest": str(manifest_path),
        "setup_script": str(setup_script),
        "readme": str(readme),
        "markers": len(markers),
        "leaders": final_info["leader_plan"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
