from __future__ import annotations

"""One-command, zero-LLM GSC Gym Leader deterministic Resolve dry run."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
SRC_DIR = REPO_DIR / "src"
for value in (REPO_DIR, SRC_DIR):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from resolve_mcp.orchestrator.gsc_gym_deterministic import (  # noqa: E402
    BATTLE_AUDIO_DIR,
    BATTLE_GAP_FRAMES,
    BATTLE_INTRO_FRAMES,
    FAIRLIGHT_PRESET_NAME,
    FAIRLIGHT_PRESET_TYPE,
    GscGymDeterministicError,
    IncompleteBattleTelemetryError,
    INTRO_TRACK,
    MAX_FULL_RUN_SECONDS,
    OUTRO_TRACK,
    OPENING_INTRO_DERIVATIVE_FRAMES,
    OPENING_INTRO_SPEED_PCT,
    OPENING_INTRO_SOURCE_FRAMES,
    OPENING_INTRO_TIMELINE_FRAMES,
    PLAN_SCHEMA,
    POST_FINAL_REQUIRED_TRACKS,
    WORKFLOW_ID,
    align_obs_chapters_to_session,
    build_a1_gap_plan,
    build_overlay_intro_plan,
    canonical_battle_attempts,
    canonical_carousel_boundary,
    choose_nonbattle_tracks,
    choose_battle_tracks,
    load_events,
    map_battle_attempts_to_source,
    stable_seed,
    validate_zero_llm_workflow,
    _project_mapper_exit_to_source,
)
from resolve_mcp.orchestrator.gsc_gym_recovery_receipt import (  # noqa: E402
    GscGymRecoveryReceiptError,
    validate_and_map_recovery_receipt,
)
from resolve_mcp.orchestrator.gsc_gym_intro_library import (  # noqa: E402
    DEFAULT_GSC_INTRO_LIBRARY_MANIFEST,
)
from resolve_mcp.orchestrator.gsc_gym_video_recovery import RecoveryDeadline  # noqa: E402
from resolve_mcp.orchestrator.gsc_gym_reference import audit_surge_reference  # noqa: E402
from resolve_mcp.orchestrator.gsc_gym_carousel_detector import (  # noqa: E402
    GscCarouselDetectionError,
    MAX_SCAN_FRAMES as CAROUSEL_MAX_SCAN_FRAMES,
    PRE_ROLL_FRAMES as CAROUSEL_PRE_ROLL_FRAMES,
    detect_carousel_source_frame,
)
from resolve_mcp.orchestrator.dependencies import find_auto_editor_command  # noqa: E402
from resolve_mcp.orchestrator.gsc_gym_audio import (  # noqa: E402
    DEFAULT_GAINS_DB,
    SOURCE_A2_SCHEMA,
    SOURCE_CLIP_SCHEMA,
    build_source_a2_contract,
)
from resolve_mcp.orchestrator.gsc_gym_bgm import (  # noqa: E402
    BattleAudioRange,
    plan_gsc_gym_bgm,
)
from resolve_mcp.orchestrator.gsc_gym_fcpxml import (  # noqa: E402
    BATTLE_BGM_ASSIGNMENT_POLICY,
    BATTLE_EDGE_FADE_FRAMES,
    GscGymFcpxmlSpec,
    IntroOverlay,
    MediaAsset,
    OpeningSpec,
    OutroSpec,
    assemble_gsc_gym_fcpxml,
)
from resolve_mcp.orchestrator.gsc_gym_fcpxml_plan import (  # noqa: E402
    BattleAttemptSourceBoundary,
    CarouselSourceBoundary,
    parse_autoeditor_fcpxml,
    plan_gsc_gym_geometry,
)
from resolve_mcp.orchestrator.gsc_gym_resolve import (  # noqa: E402
    resolve_receipt_deployment_ready,
    run_resolve_dry_run,
)
from scripts.orchestrator_auto_editor import (  # noqa: E402
    repair_fcpxml_asset_durations,
)

DEFAULT_CONFIG = REPO_DIR / "config" / "orchestrator_workflows.json"
DEFAULT_LAYOUT = Path("F:/Programming/GSCNewLayout")
DEFAULT_OUTRO = Path("F:/GSC Assets/GSC Assets outro.mov")
DEFAULT_OPENING_INTRO_SOURCE = DEFAULT_LAYOUT / "GSCPC Intro Short.mp4"
DEFAULT_OPENING_INTRO = Path(
    "C:/Users/Teo/.resolve-mcp/cache/retimed-intros/GSCPC Intro Short__400pct.mp4"
)
DEFAULT_REFERENCE_CONTRACT = REPO_DIR / "config" / "gsc_gym_leader_reference_contract.json"
DEFAULT_OUTPUT_ROOT = Path("F:/CodexTemp/gsc-gym-deterministic")
DEFAULT_FAIRLIGHT_PRESET = (
    REPO_DIR
    / "assets"
    / "fairlight-presets"
    / FAIRLIGHT_PRESET_TYPE
    / f"{FAIRLIGHT_PRESET_NAME}.dat"
)
STABLE_DWELL_SECONDS = 2.0
DEFAULT_VIDEO_RECOVERY_RECEIPT_NAME = "gsc-video-recovery-receipt.json"
AUTO_EDITOR_ASSET_DURATION_REPAIR_POLICY = (
    "v2:raise-only-to-max-asset-clip-source-end-and-probed-full-source-duration-"
    "before-parse-and-atomic-promotion"
)


class _Deadline:
    def __init__(self, seconds: float) -> None:
        self.started = time.monotonic()
        self.limit = float(seconds)
        self.ends = self.started + self.limit

    def check(self, activity: str) -> None:
        if time.monotonic() >= self.ends:
            raise GscGymDeterministicError(
                f"Dry-run exceeded its {self.limit:.0f}-second deadline during {activity}."
            )

    def remaining(self, activity: str) -> float:
        self.check(activity)
        return max(0.001, self.ends - time.monotonic())


class _UnsafeResultPathError(GscGymDeterministicError):
    """Raised before any requested result path may be written."""


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path, deadline: _Deadline | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            if deadline is not None:
                deadline.check(f"hashing {path.name}")
            digest.update(chunk)
    return digest.hexdigest().upper()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(path, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))


def _timecode_at_60fps(raw: Any, media_fps: float) -> int:
    value = str(raw or "").strip()
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2}):(\d{2})", value)
    if match is None:
        raise GscGymDeterministicError(
            f"Only non-drop HH:MM:SS:FF media timecode is supported: {value!r}."
        )
    if media_fps <= 0:
        return 0
    hours, minutes, seconds, frames = (int(token) for token in match.groups())
    nominal = int(round(media_fps))
    if frames >= nominal:
        raise GscGymDeterministicError(
            f"Invalid media timecode {value!r} for {nominal} fps."
        )
    native = ((hours * 60 + minutes) * 60 + seconds) * nominal + frames
    rendered = Fraction(native * 60, nominal)
    if rendered.denominator != 1:
        raise GscGymDeterministicError(
            f"Media timecode {value!r} is not frame-aligned on the 60 fps timeline."
        )
    return rendered.numerator


def _resolve_session(source: Path, session_arg: Path | None) -> Path:
    if session_arg:
        return session_arg.resolve()
    root = Path.home() / "AppData/Roaming/gscpc-frontend/logs"
    matches: list[Path] = []
    source_resolved = source.resolve()
    for meta_path in root.glob("*/meta.json"):
        try:
            meta = _read_json(meta_path)
            recorded = Path(meta["verticalRecording"]["filePath"]).resolve()
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            continue
        if recorded == source_resolved:
            matches.append(meta_path.parent)
    if len(matches) != 1:
        raise GscGymDeterministicError(
            f"Recording must match exactly one GSC session manifest; found {len(matches)}. "
            "Pass --session-dir for an OBS recording not named by the vertical manifest."
        )
    return matches[0]


def _required(path: Path, label: str) -> Path:
    if not path.is_file() or path.stat().st_size <= 0:
        raise GscGymDeterministicError(f"Missing {label}: {path}")
    return path.resolve()


def _intro_asset_plan_kwargs(args: argparse.Namespace) -> dict[str, Path]:
    """Select the approved manifest by default; retain explicit legacy diagnostics."""

    legacy_root = getattr(args, "battle_intro_root", None)
    if legacy_root is not None:
        root = Path(legacy_root)
        return {
            "leaders_dir": root / "leaders",
            "rivals_dir": root / "rivals",
        }
    manifest = Path(
        getattr(
            args,
            "battle_intro_manifest",
            DEFAULT_GSC_INTRO_LIBRARY_MANIFEST,
        )
    )
    return {"intro_library_manifest": manifest}


def _contracted_battle_library(
    battle_dir: Path,
    reference_contract_path: Path,
) -> tuple[list[Path], tuple[str, ...]]:
    """Resolve and fail-close the exact Gen 2 library registered by Surge."""

    library = sorted(battle_dir.glob("*.mp3"), key=lambda path: path.name.casefold())
    if not library:
        raise GscGymDeterministicError(f"No GSC battle BGM found in {battle_dir}")

    expected: tuple[str, ...] = ()
    if reference_contract_path.is_file():
        contract = _read_json(reference_contract_path)
        strict = contract.get("strict_invariants") if isinstance(contract, dict) else None
        raw = strict.get("battle_bgm_tracks") if isinstance(strict, dict) else None
        if isinstance(raw, list) and raw:
            expected = tuple(str(value).strip() for value in raw)
            if (
                len(expected) != 6
                or any(not value for value in expected)
                or len(set(expected)) != len(expected)
            ):
                raise GscGymDeterministicError(
                    "Surge reference battle_bgm_tracks must contain six unique filenames."
                )

    actual = tuple(path.name for path in library)
    if expected and set(actual) != set(expected):
        raise GscGymDeterministicError(
            "Gen 2 battle BGM library differs from the exact Surge contract: "
            f"missing={sorted(set(expected) - set(actual))}, "
            f"unexpected={sorted(set(actual) - set(expected))}."
        )
    return library, expected or actual


def _audit_source_a2_contract(planned: tuple[Any, ...], source_a2: Any) -> dict[str, Any]:
    """Cross-check the original-path, non-rendered A2 population."""

    segments = tuple(source_a2.segments)
    clips = tuple(source_a2.clips)
    if len(segments) != len(planned) or len(clips) != len(planned):
        raise GscGymDeterministicError("Source-native A2 population changed.")
    source_hashes: dict[str, str] = {}
    for index, (source, final, clip) in enumerate(
        zip(planned, segments, clips), start=1
    ):
        expected_geometry = (
            source.record_start_frame,
            source.record_end_frame,
            source.source_start_frame,
            source.source_end_frame,
            source.role,
            source.battle_id,
            source.fade_in_frames,
            source.fade_out_frames,
        )
        actual_geometry = (
            final.record_start_frame,
            final.record_end_frame,
            final.source_start_frame,
            final.source_start_frame + final.duration_frames,
            final.role,
            final.battle_id,
            final.fade_in_frames,
            final.fade_out_frames,
        )
        if actual_geometry != expected_geometry:
            raise GscGymDeterministicError(
                f"Source-native A2 slice {index} lost geometry: "
                f"{actual_geometry} != {expected_geometry}."
            )
        source_path = Path(str(source.asset.path)).resolve()
        origin_path = Path(str(source.asset.origin_path or source.asset.path)).resolve()
        source_key = _path_key(source_path)
        source_sha256 = source_hashes.get(source_key)
        if source_sha256 is None:
            source_sha256 = _sha256_file(source_path).upper()
            source_hashes[source_key] = source_sha256
        media_start = int(source.asset.source_start_frame)
        media_end = media_start + int(source.asset.duration_frames)
        expected_gain = float(DEFAULT_GAINS_DB[source.role])
        expected_handles = {
            "left": source.source_start_frame - media_start,
            "right": media_end - source.source_end_frame,
        }
        if (
            _path_key(source_path) != _path_key(origin_path)
            or source_path.suffix.casefold() != ".mp3"
            or source.asset.name != source_path.name
            or any(part.casefold() == "a2-fades" for part in source_path.parts)
            or final.asset != source.asset
            or abs(float(final.gain_db) - expected_gain) > 1e-9
            or clip.get("schema") != SOURCE_CLIP_SCHEMA
            or _path_key(str(clip.get("source_path") or "")) != source_key
            or clip.get("source_name") != source_path.name
            or str(clip.get("source_sha256") or "").upper() != source_sha256
            or list(clip.get("record_range") or [])
            != [source.record_start_frame, source.record_end_frame]
            or list(clip.get("source_range") or [])
            != [source.source_start_frame, source.source_end_frame]
            or type(clip.get("media_source_start_frame")) is not int
            or clip.get("media_source_start_frame") != media_start
            or type(clip.get("media_duration_frames")) is not int
            or clip.get("media_duration_frames") != int(source.asset.duration_frames)
            or type(clip.get("media_source_end_frame")) is not int
            or clip.get("media_source_end_frame") != media_end
            or clip.get("available_handle_frames") != expected_handles
            or clip.get("source_trim_handles_editable") is not True
            or clip.get("derived_media") is not False
            or clip.get("role") != source.role
            or clip.get("battle_id") != source.battle_id
            or clip.get("label") != source.label
            or clip.get("gain_db") != expected_gain
            or clip.get("gain_policy")
            != "editable_timeline_adjust_volume_not_baked"
            or clip.get("fade_in_frames") != source.fade_in_frames
            or clip.get("fade_out_frames") != source.fade_out_frames
            or clip.get("fade_policy") != "editable_timeline_metadata_not_baked"
        ):
            raise GscGymDeterministicError(
                f"A2 slice {index} is not bound to its exact original editable source."
            )
    return {
        "schema": SOURCE_A2_SCHEMA,
        "status": "pass",
        "battle_edge_fade_frames": BATTLE_EDGE_FADE_FRAMES,
        "segment_count": len(segments),
        "original_source_clip_count": len(clips),
        "materialized_derivative_count": 0,
        "derived_media_allowed": False,
        "renamed_media_allowed": False,
        "source_trim_handles_editable": True,
        "source_clips": list(clips),
    }


def _rate(value: Any) -> float:
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _rate_fraction(value: Any) -> Fraction | None:
    try:
        parsed = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    return parsed if parsed > 0 else None


def _probe_media(path: Path, deadline: _Deadline) -> dict[str, Any]:
    deadline.check(f"probing {path.name}")
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                "-show_chapters",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=deadline.remaining(f"probing {path.name}"),
        )
    except subprocess.TimeoutExpired as exc:
        raise GscGymDeterministicError(
            f"Media probe exceeded the workflow deadline: {path}"
        ) from exc
    if completed.returncode != 0:
        raise GscGymDeterministicError(
            f"ffprobe failed for {path}: {completed.stderr.strip()}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GscGymDeterministicError(f"ffprobe returned invalid JSON for {path}.") from exc
    streams = payload.get("streams") or []
    videos = [row for row in streams if row.get("codec_type") == "video"]
    audios = [row for row in streams if row.get("codec_type") == "audio"]
    fmt = payload.get("format") or {}
    try:
        duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    chapters = sorted({
        int(round(float(row.get("start_time") or 0.0) * 60.0))
        for row in payload.get("chapters") or []
    })
    video = videos[0] if videos else {}
    avg_rate_token = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0")
    r_rate_token = str(video.get("r_frame_rate") or "0")
    frame_rate_fraction = _rate_fraction(avg_rate_token)
    r_frame_rate_fraction = _rate_fraction(r_rate_token)
    frame_rate = float(frame_rate_fraction) if frame_rate_fraction is not None else 0.0
    r_frame_rate = float(r_frame_rate_fraction) if r_frame_rate_fraction is not None else 0.0
    try:
        source_frames = int(video.get("nb_frames"))
    except (TypeError, ValueError):
        source_frames = int(round(duration * frame_rate)) if frame_rate > 0 else 0
    timeline_frames = int(round(duration * 60.0))
    if source_frames > 0 and frame_rate_fraction is not None:
        exact_timeline = Fraction(source_frames * 60, 1) / frame_rate_fraction
        if exact_timeline.denominator == 1:
            timeline_frames = exact_timeline.numerator
    timecodes = {
        str((row.get("tags") or {}).get("timecode") or "").strip()
        for row in [video, *streams, fmt]
        if str((row.get("tags") or {}).get("timecode") or "").strip()
    }
    if len(timecodes) > 1:
        raise GscGymDeterministicError(
            f"Conflicting embedded media timecodes for {path}: {sorted(timecodes)}"
        )
    timecode = next(iter(timecodes), "")
    media_start_frame = _timecode_at_60fps(timecode, frame_rate) if timecode else 0
    return {
        "path": str(path.resolve()),
        "duration_sec": duration,
        "video_stream_count": len(videos),
        "audio_stream_count": len(audios),
        "video_width": int(video.get("width") or 0),
        "video_height": int(video.get("height") or 0),
        "video_frame_rate": frame_rate,
        "video_r_frame_rate": r_frame_rate,
        "video_avg_frame_rate_fraction": avg_rate_token,
        "video_r_frame_rate_fraction": r_rate_token,
        "video_native_fps": int(round(frame_rate)) if frame_rate > 0 else 0,
        "video_codec": str(video.get("codec_name") or ""),
        "video_pixel_format": str(video.get("pix_fmt") or ""),
        "video_source_frames": source_frames,
        "timeline_frames_at_60fps": timeline_frames,
        "media_timecode": str(timecode),
        "media_start_frame_at_60fps": media_start_frame,
        "chapter_start_frames": chapters,
        "format_name": str(fmt.get("format_name") or ""),
        "audio_streams": [
            {
                "stream_index": int(row.get("index") or 0),
                "codec": str(row.get("codec_name") or ""),
                "sample_rate": int(row.get("sample_rate") or 0),
                "channels": int(row.get("channels") or 0),
                "timeline_frames_at_60fps": int(
                    round(float(row.get("duration") or duration or 0.0) * 60.0)
                ),
            }
            for row in audios
        ],
    }


def _has_exact_video_rate(probe: dict[str, Any], fps: int) -> bool:
    expected = Fraction(fps, 1)
    return (
        _rate_fraction(probe.get("video_avg_frame_rate_fraction")) == expected
        and _rate_fraction(probe.get("video_r_frame_rate_fraction")) == expected
    )


def _is_exact_4k(probe: dict[str, Any]) -> bool:
    return (
        int(probe.get("video_width") or 0) == 3840
        and int(probe.get("video_height") or 0) == 2160
    )


def _validate_completed_source(
    source: Path,
    probe: dict[str, Any],
    *,
    dialogue_audio_ordinal: int,
    stat_before: tuple[int, int],
) -> dict[str, Any]:
    """Require the immutable 4K60 OBS source and its fixed dialogue stream."""

    current = source.stat()
    stat_after = (int(current.st_size), int(current.st_mtime_ns))
    if stat_after != stat_before:
        raise GscGymDeterministicError(
            "Source size or modification time changed during preflight; recording is still active."
        )
    if probe.get("video_stream_count") != 1:
        raise GscGymDeterministicError("Source must contain exactly one video stream.")
    if (
        int(probe.get("video_width") or 0) != 3840
        or int(probe.get("video_height") or 0) != 2160
    ):
        raise GscGymDeterministicError(
            "Source must be the 3840x2160 main OBS recording, not the vertical capture."
        )
    if not _has_exact_video_rate(probe, 60):
        raise GscGymDeterministicError("Source must be constant-contract 60 fps video.")
    if (
        float(probe.get("duration_sec") or 0.0) <= 0.0
        or int(probe.get("video_source_frames") or 0) <= 0
    ):
        raise GscGymDeterministicError("Source has no usable video duration.")
    audio_streams = probe.get("audio_streams") or []
    if dialogue_audio_ordinal <= 0 or dialogue_audio_ordinal > len(audio_streams):
        raise GscGymDeterministicError(
            "Configured dialogue audio ordinal is absent from the OBS source: "
            f"ordinal={dialogue_audio_ordinal}, audio_streams={len(audio_streams)}."
        )
    dialogue = audio_streams[dialogue_audio_ordinal - 1]
    if int(dialogue.get("sample_rate") or 0) != 48000 or int(dialogue.get("channels") or 0) <= 0:
        raise GscGymDeterministicError(
            "Configured dialogue stream must be a non-empty 48 kHz OBS audio stream."
        )
    return {
        "status": "pass",
        "immutable_during_probe": True,
        "stat_before": {"size": stat_before[0], "mtime_ns": stat_before[1]},
        "stat_after": {"size": stat_after[0], "mtime_ns": stat_after[1]},
        "video_contract": "3840x2160p60_single_video_stream",
        "dialogue_audio_ordinal": dialogue_audio_ordinal,
        "dialogue_stream": dialogue,
    }


def _carousel_source_boundary(
    *,
    telemetry: dict[str, Any] | None,
    alignment: dict[str, Any],
    source: Path,
    source_frames: int,
    last_battle_source_end: int,
    deadline: _Deadline,
) -> dict[str, Any]:
    """Prefer exact state telemetry; use the fixed-pixel contract for old GSC logs."""

    if telemetry is not None:
        event_index = int(telemetry["event_index"])
        direct = next(
            (
                row
                for row in alignment.get("matches") or []
                if int(row.get("event_index", -1)) == event_index
            ),
            None,
        )
        if direct is not None:
            return {
                **telemetry,
                "source_frame": int(direct["chapter_frame"]),
                "source_boundary_authority": (
                    "matched_embedded_OBS_chapter_for_exact_member-carousel-started"
                ),
                "source_mapping_required": False,
            }
        projection = _project_mapper_exit_to_source(
            int(telemetry["session_frame"]), alignment
        )
        projected = int(projection["source_frame"])
        if projected < 0 or projected >= source_frames:
            raise GscGymDeterministicError(
                "Projected carousel telemetry falls outside the immutable source."
            )
        return {
            **telemetry,
            "source_frame": projected,
            "source_boundary_authority": (
                "exact_member-carousel-started_projected_through_strict_local_OBS_chapter_bracket"
            ),
            "source_projection": projection,
            "source_mapping_required": False,
        }

    scan_start = max(0, int(last_battle_source_end) - CAROUSEL_PRE_ROLL_FRAMES)
    scan_end = min(int(source_frames), scan_start + CAROUSEL_MAX_SCAN_FRAMES)
    try:
        detected = detect_carousel_source_frame(
            source,
            source_start_frame=scan_start,
            source_end_frame=scan_end,
            timeout_seconds=deadline.remaining("scanning fixed carousel pixels"),
            deadline_check=deadline.check,
        )
        authority = str(detected.get("boundary_authority") or "").strip()
        if not authority:
            raise GscGymDeterministicError(
                "Fixed-pixel carousel receipt has no boundary authority."
            )
        return {
            **detected,
            "source_boundary_authority": authority,
        }
    except GscCarouselDetectionError as exc:
        raise GscGymDeterministicError(str(exc)) from exc


def _validate_structural_media(
    *,
    opening_derivative: Path,
    opening_source: Path,
    outro: Path,
    intro_placements: list[dict[str, Any]],
    deadline: _Deadline,
) -> dict[str, Any]:
    opening_probe = _probe_media(opening_derivative, deadline)
    if (
        opening_probe["video_stream_count"] != 1
        or opening_probe["audio_stream_count"] != 0
        or opening_probe["video_source_frames"] != OPENING_INTRO_DERIVATIVE_FRAMES
        or opening_probe["timeline_frames_at_60fps"] != OPENING_INTRO_TIMELINE_FRAMES
        or opening_probe["video_native_fps"] != 30
        or not _has_exact_video_rate(opening_probe, 30)
        or not _is_exact_4k(opening_probe)
    ):
        raise GscGymDeterministicError(
            "Approved 4x GSC opening derivative must be one silent 3840x2160 video stream "
            f"lasting exactly {OPENING_INTRO_TIMELINE_FRAMES} frames at 60 fps."
        )
    source_probe = _probe_media(opening_source, deadline)
    if (
        source_probe["video_stream_count"] != 1
        or source_probe["video_source_frames"] != OPENING_INTRO_SOURCE_FRAMES
        or source_probe["video_native_fps"] != 30
        or source_probe["timeline_frames_at_60fps"] != OPENING_INTRO_SOURCE_FRAMES * 2
        or not _has_exact_video_rate(source_probe, 30)
        or not _is_exact_4k(source_probe)
    ):
        raise GscGymDeterministicError(
            "GSC opening source does not match the approved 3840x2160 512-frame lineage."
        )
    outro_probe = _probe_media(outro, deadline)
    if (
        outro_probe["video_stream_count"] != 1
        or outro_probe["audio_stream_count"] != 1
        or outro_probe["video_native_fps"] != 60
        or outro_probe["timeline_frames_at_60fps"] <= 0
        or not _has_exact_video_rate(outro_probe, 60)
        or not _is_exact_4k(outro_probe)
        or outro_probe["audio_streams"][0]["sample_rate"] != 48_000
        or outro_probe["audio_streams"][0]["channels"] != 2
    ):
        raise GscGymDeterministicError(
            "GSC outro must contain one 3840x2160 video stream and one linked stereo 48 kHz source-audio stream."
        )

    intro_probes: dict[str, dict[str, Any]] = {}
    for asset in sorted({Path(row["asset"]) for row in intro_placements}, key=str):
        probe = _probe_media(asset, deadline)
        if (
            probe["video_stream_count"] != 1
            or probe["audio_stream_count"] != 0
            or probe["timeline_frames_at_60fps"] != BATTLE_INTRO_FRAMES
            or probe["video_native_fps"] != 60
            or not _has_exact_video_rate(probe, 60)
            or not _is_exact_4k(probe)
        ):
            raise GscGymDeterministicError(
                "Battle intro must be silent 3840x2160 media and exactly "
                f"{BATTLE_INTRO_FRAMES} frames: {asset}"
            )
        intro_probes[str(asset)] = probe
    return {
        "opening_derivative": opening_probe,
        "opening_source": source_probe,
        "outro": outro_probe,
        "battle_intros": intro_probes,
    }


def _resolve_read_only_snapshot(required: bool, deadline: _Deadline) -> dict[str, Any] | None:
    if not required:
        return None
    deadline.check("connecting to Resolve for read-only preflight")
    from resolve_mcp.connection import ResolveConnection

    connection = ResolveConnection()
    if not connection.connect():
        raise GscGymDeterministicError(
            "Resolve read-only preflight failed: " + (connection.last_error or "not connected")
        )
    resolve = connection.get_resolve()
    manager = resolve.GetProjectManager() if resolve else None
    project = manager.GetCurrentProject() if manager else None
    if not project:
        raise GscGymDeterministicError("Resolve has no current project for the dry run.")
    timeline = project.GetCurrentTimeline()
    deadline.check("reading the current Resolve identity")
    return {
        "resolve_version": str(resolve.GetVersionString() or ""),
        "page": str(resolve.GetCurrentPage() or ""),
        "project_name": str(project.GetName() or ""),
        "project_uid": str(project.GetUniqueId() or "") if hasattr(project, "GetUniqueId") else "",
        "timeline_name": str(timeline.GetName() or "") if timeline else None,
        "timeline_uid": (
            str(timeline.GetUniqueId() or "")
            if timeline and hasattr(timeline, "GetUniqueId")
            else None
        ),
        "mutations": 0,
    }


def build_dry_run(args: argparse.Namespace) -> dict[str, Any]:
    deadline = _Deadline(args.timeout_seconds)
    deadline.check("bootstrap")
    source = _required(args.source, "completed source recording")
    if source.name.casefold().endswith(".partial.webm") or ".partial." in source.name.casefold():
        raise GscGymDeterministicError("Dry-run refuses a partial recording file.")
    session_dir = _resolve_session(source, args.session_dir)
    events_path = _required(session_dir / "events.json", "canonical session events")
    meta_path = _required(session_dir / "meta.json", "canonical session metadata")
    meta = _read_json(meta_path)
    vertical = meta.get("verticalRecording") or {}
    if vertical.get("status") != "finalized":
        raise GscGymDeterministicError("Recording is not finalized; dry-run will not inspect an active recording.")
    if str(meta.get("runType", "")).casefold() != "gym leader challenge":
        raise GscGymDeterministicError("Session runType is not Gym Leader Challenge.")

    deadline.check("loading workflow registration")
    config = _read_json(args.config)
    workflow = next((row for row in config.get("workflows", []) if row.get("id") == WORKFLOW_ID), None)
    if workflow is None:
        raise GscGymDeterministicError(f"Workflow {WORKFLOW_ID!r} is not registered.")
    validate_zero_llm_workflow(workflow)
    fairlight_preset = _required(
        DEFAULT_FAIRLIGHT_PRESET,
        "repository Fairlight preset required by the final Resolve transaction",
    )
    reference_audit = audit_surge_reference(
        contract_path=args.reference_contract,
        workflow_config_path=args.config,
    )
    deadline.check("auditing the fingerprinted Lt. Surge reference")
    if reference_audit.get("status") != "pass":
        raise GscGymDeterministicError(
            "Lt. Surge reference audit failed: "
            + ", ".join(reference_audit.get("failed_checks") or ["unknown check"])
        )

    bgm_dir = args.layout_root / "audio" / "bgm"
    intro = _required(bgm_dir / INTRO_TRACK, "reserved intro BGM")
    outro = _required(bgm_dir / OUTRO_TRACK, "reserved outro BGM")
    opening_intro_video = _required(args.opening_intro_video, "approved 4x GSC opening intro")
    opening_intro_source = _required(args.opening_intro_source, "GSC opening intro source")
    outro_video = _required(args.outro_video, "outro video")
    battle_dir = args.layout_root / "audio" / BATTLE_AUDIO_DIR
    battle_tracks, contracted_battle_names = _contracted_battle_library(
        battle_dir,
        args.reference_contract,
    )

    deadline.check("parsing canonical event telemetry")
    events = load_events(events_path)
    intake = _battle_telemetry_intake(
        events=events,
        source=source,
        requested_recovery_receipt=getattr(args, "video_recovery_receipt", None),
    )
    source_stat = source.stat()
    source_stat_before = (int(source_stat.st_size), int(source_stat.st_mtime_ns))
    source_probe = _probe_media(source, deadline)
    source_contract = _validate_completed_source(
        source,
        source_probe,
        dialogue_audio_ordinal=args.dialogue_audio_ordinal,
        stat_before=source_stat_before,
    )
    battle_mapping = _map_battle_intake_to_source(
        intake=intake,
        events=events,
        source=source,
        source_probe=source_probe,
        events_path=events_path,
        meta_path=meta_path,
        deadline=deadline,
    )
    source_alignment = battle_mapping["source_alignment"]
    source_mapped_battles = battle_mapping["mapped_attempts"]

    seed_paths = [source, events_path, meta_path]
    if intake.get("receipt_path") is not None:
        seed_paths.append(Path(intake["receipt_path"]))
    if getattr(args, "battle_intro_root", None) is None:
        seed_paths.append(
            _required(
                Path(args.battle_intro_manifest),
                "approved Gen 2 battle-intro library manifest",
            )
        )
    seed = stable_seed(
        *seed_paths,
        deadline_check=deadline.check,
    )
    nonbattle = choose_nonbattle_tracks(bgm_dir, seed=seed)
    battle_assignments = choose_battle_tracks(
        battle_tracks,
        count=len(source_mapped_battles),
        seed=seed,
    )
    overlay_intros = build_overlay_intro_plan(
        source_mapped_battles,
        **_intro_asset_plan_kwargs(args),
        rival_starter_type=(
            None if args.rival_starter_type == "auto" else args.rival_starter_type
        ),
        boundary_is_final_timeline=False,
    )
    if not overlay_intros:
        raise GscGymDeterministicError(
            "No first-attempt leader/rival battles were found for deterministic V2 intros."
        )
    a1_gaps = build_a1_gap_plan(source_mapped_battles)
    carousel_telemetry = canonical_carousel_boundary(events)
    carousel_boundary = _carousel_source_boundary(
        telemetry=carousel_telemetry,
        alignment=source_alignment,
        source=source,
        source_frames=int(source_probe["video_source_frames"]),
        last_battle_source_end=int(source_mapped_battles[-1]["source_end_frame"]),
        deadline=deadline,
    )
    media_preflight = _validate_structural_media(
        opening_derivative=opening_intro_video,
        opening_source=opening_intro_source,
        outro=outro_video,
        intro_placements=overlay_intros,
        deadline=deadline,
    )
    resolve_snapshot = _resolve_read_only_snapshot(args.require_resolve, deadline)
    leader = ((vertical.get("project") or {}).get("subject") or meta.get("pokemon"))
    if not leader:
        raise GscGymDeterministicError("Session does not identify the selected Gym Leader profile.")

    deadline.check("finalizing deterministic plan")
    elapsed = time.monotonic() - deadline.started
    deployment_blockers = [
        "the registered offline stage has not yet built the deterministic dialogue edit and final source-to-timeline map",
        "the registered receipt-bound Resolve stage has not yet imported and live-validated this exact build",
    ]
    return {
        "schema": PLAN_SCHEMA,
        "status": "pass",
        "plan_status": "pass",
        "deployment_ready": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workflow_id": WORKFLOW_ID,
        "wall_clock_limit_seconds": args.timeout_seconds,
        "elapsed_seconds": round(elapsed, 3),
        "zero_llm": True,
        "fairlight_preset_source_evidence": _asset_evidence(fairlight_preset, deadline),
        "surge_reference_audit": reference_audit,
        "resolve_read_only_preflight": resolve_snapshot,
        "source": str(source),
        "source_probe": source_probe,
        "source_contract": source_contract,
        "source_alignment": source_alignment,
        "source_session_binding": {
            "status": "pass",
            "authority": battle_mapping["mode"],
            "session_dir": str(session_dir),
            "matched_chapter_count": source_alignment.get("matched_chapter_count"),
            "offset_frame": source_alignment.get("offset_frame"),
            "typed_recovery_trigger": battle_mapping.get("typed_trigger"),
            "recovery_binding": battle_mapping.get("recovery_binding"),
        },
        "session_dir": str(session_dir),
        "leader_profile": str(leader),
        "seed_sha256": seed,
        "canonical_battle_group_count": len(
            {str(row.get("battle_key")) for row in source_mapped_battles}
        ),
        "canonical_battle_attempt_count": len(source_mapped_battles),
        "retained_battle_count": None,
        "retention_policy": (
            "map exact source ranges through the deterministic dialogue-edit map; "
            "map every retained physical attempt through the deterministic dialogue "
            "edit; only supplied identity attempt ordinal 1 receives an A1 gap, "
            "while every physical attempt keeps its own A2 battle range"
        ),
        "battle_plan": source_mapped_battles,
        "structural_video_plan": {
            "opening_intro": {
                "asset": str(opening_intro_video),
                "source_asset": str(opening_intro_source),
                "video_track": 1,
                "record_start_frame": 0,
                "source_retime_pct": OPENING_INTRO_SPEED_PCT,
                "resolve_speed_pct": 100,
                "timeline_duration_frames": OPENING_INTRO_TIMELINE_FRAMES,
                "audio_policy": "video_only; Dual Screen Lovelife supplies intro BGM",
                "lineage_policy": "approved pre-retimed 4x derivative; never apply a second 4x retime",
            },
            "outro": {
                "asset": str(outro_video),
                "video_track": 1,
                "audio_track": 3,
                "anchor": "immediately_after_member_carousel",
                "linked_video_and_source_audio": True,
                "audio_policy": "use the MOV source audio on A3; never place a second standalone outro track",
                "golden_goose_reservation": str(outro),
                "golden_goose_placement": "blocked from A2; identity reservation only because the synchronized outro audio is embedded in the MOV",
            },
            "media_preflight": media_preflight,
        },
        "a1_gap_plan": a1_gaps,
        "a1_gap_population_rule": (
            "one gap before the first retained attempt of each consecutive exact-"
            "trainer editorial group; no gap before same-trainer retries"
        ),
        "intro_plan": {
            "leader_and_rival_from_canonical_events": (
                battle_mapping["mode"] == "canonical_session_telemetry"
            ),
            "leader_and_rival_from_content_bound_video_receipt": (
                battle_mapping["mode"] != "canonical_session_telemetry"
            ),
            "deterministic": True,
            "track": "V2",
            "placement_rule": "overlap continuous V1 and end exactly at the end of the 60-frame A1 pre-battle gap",
            "coordinate_rule": "absolute V2/A1 frames remain unset until the canonical source boundary is mapped through the final edited V1/A1 spine",
            "placements": overlay_intros,
        },
        "carousel_plan": {
            "placement": "end_of_program_before_outro",
            "deterministic": True,
            "boundary_authority": (
                "exact carousel telemetry when present; otherwise the fixed 4K GSC lower-corner pixel transition contract"
            ),
            "canonical_boundary": carousel_boundary,
            "v1_policy": "one continuous source-backed clip through the carousel region",
            "v2_policy": "contiguous source-backed duplicates",
            "v2_crop_bottom": 530.0,
            "outro_follows_immediately": True,
        },
        "audio_plan": {
            "intro": str(intro),
            "outro": str(outro),
            "outro_video": str(outro_video),
            "battle_library": [str(path.resolve()) for path in battle_tracks],
            "contracted_battle_library_filenames": list(contracted_battle_names),
            "battle_assignment_policy": "deterministic_shuffle_bag_no_immediate_repeat",
            "battle_assignments": [
                {
                    "source_start_frame": battle["source_start_frame"],
                    "source_end_frame": battle["source_end_frame"],
                    "identity": battle["identity"],
                    "role": battle["role"],
                    "source": str(track.resolve()),
                    "audio_source_start_frame": 0,
                }
                for battle, track in zip(source_mapped_battles, battle_assignments)
            ],
            "nonbattle_seed": seed,
            "nonbattle_order": [str(path.resolve()) for path in nonbattle],
            "blocked_from_random_nonbattle": [*POST_FINAL_REQUIRED_TRACKS, OUTRO_TRACK],
            "post_final_required_order": list(POST_FINAL_REQUIRED_TRACKS),
            "a2_continuity": "frame-exact from timeline start to outro start",
            "transition_fade_frames": 30,
        },
        "resolve_mutations": 0,
        "deployment_gate": {
            "status": "pending_registered_offline_build_and_resolve_receipt",
            "deployment_ready": False,
            "blockers": deployment_blockers,
            "reference_contract_status": reference_audit.get("status"),
            "resolve_preflight_was_read_only": bool(resolve_snapshot),
        },
    }


def _path_key(path: str | Path) -> str:
    return str(Path(path).resolve()).replace("\\", "/").casefold()


def _safe_stem(value: str) -> str:
    rendered = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return rendered or "gsc-gym-run"


def _require_f_drive(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if resolved.drive.casefold() != "f:":
        raise GscGymDeterministicError(f"{label} must be on the F: work drive: {resolved}")
    return resolved


def _battle_telemetry_intake(
    *,
    events: list[dict[str, Any]],
    source: Path,
    requested_recovery_receipt: Path | None,
) -> dict[str, Any]:
    """Select canonical telemetry or the one typed, receipt-bound fallback."""

    try:
        attempts = canonical_battle_attempts(events)
    except IncompleteBattleTelemetryError as exc:
        receipt = _required(
            requested_recovery_receipt
            or source.parent / "CODEx" / DEFAULT_VIDEO_RECOVERY_RECEIPT_NAME,
            "content-bound video-recovery receipt for incomplete battle telemetry",
        )
        return {
            "mode": "content_bound_video_recovery_receipt_pending",
            "attempts": None,
            "receipt_path": receipt,
            "typed_trigger": type(exc).__name__,
            "typed_trigger_message": str(exc),
        }
    if not attempts:
        raise GscGymDeterministicError(
            "No complete exact physical battle attempts were found; recovery is allowed "
            "only when canonical parsing reports typed incomplete battle telemetry."
        )
    return {
        "mode": "canonical_session_telemetry",
        "attempts": attempts,
        "receipt_path": None,
        "typed_trigger": None,
        "typed_trigger_message": None,
    }


def _map_battle_intake_to_source(
    *,
    intake: dict[str, Any],
    events: list[dict[str, Any]],
    source: Path,
    source_probe: dict[str, Any],
    events_path: Path,
    meta_path: Path,
    deadline: _Deadline,
) -> dict[str, Any]:
    receipt_path = intake.get("receipt_path")
    if receipt_path is None:
        alignment = align_obs_chapters_to_session(
            source_probe["chapter_start_frames"],
            events,
            deadline_check=deadline.check,
        )
        return {
            "mode": "canonical_session_telemetry",
            "mapped_attempts": map_battle_attempts_to_source(
                list(intake["attempts"]), alignment
            ),
            "source_alignment": alignment,
            "recovery_binding": None,
            "typed_trigger": None,
            "typed_trigger_message": None,
        }
    try:
        recovered = validate_and_map_recovery_receipt(
            Path(receipt_path),
            main_source_path=source,
            events_path=events_path,
            meta_path=meta_path,
            deadline=RecoveryDeadline(deadline.ends),
            expected_main_frame_count=int(source_probe["video_source_frames"]),
        )
    except GscGymRecoveryReceiptError as exc:
        raise GscGymDeterministicError(
            "Typed incomplete battle telemetry was found, but its content-bound "
            f"video-recovery receipt failed closed: {exc}"
        ) from exc
    return {
        **recovered,
        "typed_trigger": intake.get("typed_trigger"),
        "typed_trigger_message": intake.get("typed_trigger_message"),
    }


def _require_recovery_media_unchanged(
    recovery_binding: dict[str, Any] | None,
    deadline: _Deadline,
    *,
    activity: str,
) -> None:
    if not recovery_binding:
        return
    deadline.check(activity)
    vertical = recovery_binding.get("vertical") or {}
    manifest = vertical.get("manifest") or {}
    capture = vertical.get("capture") or {}
    manifest_path = _required(Path(str(manifest.get("path") or "")), "bound vertical manifest")
    capture_path = _required(Path(str(capture.get("path") or "")), "bound vertical capture")
    manifest_stat = manifest_path.stat()
    capture_stat = capture_path.stat()
    if (
        int(manifest.get("bytes") or -1),
        int(manifest.get("mtime_ns") or -1),
        str(manifest.get("sha256") or "").casefold(),
    ) != (
        int(manifest_stat.st_size),
        int(manifest_stat.st_mtime_ns),
        _sha256_file(manifest_path, deadline).casefold(),
    ):
        raise GscGymDeterministicError(
            f"The finalized vertical manifest changed during {activity}."
        )
    if (
        int(capture.get("bytes") or -1),
        int(capture.get("mtime_ns") or -1),
    ) != (int(capture_stat.st_size), int(capture_stat.st_mtime_ns)):
        raise GscGymDeterministicError(
            f"The finalized vertical capture changed during {activity}."
        )


def _input_snapshot(
    source: Path,
    events_path: Path,
    meta_path: Path,
    deadline: _Deadline,
    *,
    supplemental_inputs: dict[str, Path] | None = None,
) -> dict[str, Any]:
    source_stat = source.stat()
    snapshot = {
        "source": {
            "path": str(source),
            "size": int(source_stat.st_size),
            "mtime_ns": int(source_stat.st_mtime_ns),
        },
        "events": {
            "path": str(events_path),
            "sha256": _sha256_file(events_path, deadline),
        },
        "meta": {
            "path": str(meta_path),
            "sha256": _sha256_file(meta_path, deadline),
        },
    }
    for key, path in sorted((supplemental_inputs or {}).items()):
        required = _required(path, f"supplemental immutable input {key}")
        stat = required.stat()
        snapshot[key] = {
            "path": str(required),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "sha256": _sha256_file(required, deadline),
        }
    return snapshot


def _supplemental_paths_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for key, value in snapshot.items():
        if key in {"source", "events", "meta"}:
            continue
        if not isinstance(value, dict) or not str(value.get("path") or "").strip():
            raise GscGymDeterministicError(
                f"Immutable input snapshot has an invalid supplemental binding: {key}"
            )
        result[str(key)] = Path(str(value["path"]))
    return result


def _require_unchanged_inputs(
    expected: dict[str, Any],
    source: Path,
    events_path: Path,
    meta_path: Path,
    deadline: _Deadline,
    *,
    activity: str,
    supplemental_inputs: dict[str, Path] | None = None,
) -> None:
    deadline.check(activity)
    actual = _input_snapshot(
        source,
        events_path,
        meta_path,
        deadline,
        supplemental_inputs=supplemental_inputs,
    )
    if actual != expected:
        raise GscGymDeterministicError(
            f"Source or canonical session logs changed during {activity}; refusing a mixed/active run."
        )


def _stabilize_inputs(
    source: Path,
    events_path: Path,
    meta_path: Path,
    deadline: _Deadline,
    *,
    supplemental_inputs: dict[str, Path] | None = None,
) -> dict[str, Any]:
    before = _input_snapshot(
        source,
        events_path,
        meta_path,
        deadline,
        supplemental_inputs=supplemental_inputs,
    )
    if deadline.remaining("stable completed-source dwell") <= STABLE_DWELL_SECONDS:
        raise GscGymDeterministicError("Insufficient deadline remains for the completed-source dwell.")
    time.sleep(STABLE_DWELL_SECONDS)
    _require_unchanged_inputs(
        before,
        source,
        events_path,
        meta_path,
        deadline,
        activity="completed-source stability dwell",
        supplemental_inputs=supplemental_inputs,
    )
    return before


def _terminate_owned_process_tree(process: subprocess.Popen[Any], *, ends: float) -> None:
    """Terminate only a subprocess started by this workflow and its children."""

    if process.poll() is not None:
        return
    remaining = max(0.01, ends - time.monotonic())
    tree_kill_sent = False
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=max(0.01, remaining * 0.8),
            )
            tree_kill_sent = True
        except (OSError, subprocess.TimeoutExpired):
            pass
    if tree_kill_sent:
        try:
            process.wait(timeout=max(0.01, ends - time.monotonic()))
            return
        except subprocess.TimeoutExpired:
            pass
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=max(0.01, ends - time.monotonic()))
    except subprocess.TimeoutExpired:
        process.kill()


def _run_external(command: list[str], *, deadline: _Deadline, activity: str) -> subprocess.CompletedProcess[bytes]:
    deadline.check(activity)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    try:
        stdout, stderr = process.communicate(timeout=deadline.remaining(activity))
    except subprocess.TimeoutExpired as exc:
        _terminate_owned_process_tree(process, ends=deadline.ends)
        raise GscGymDeterministicError(f"{activity} exceeded the workflow deadline.") from exc
    completed = subprocess.CompletedProcess(command, int(process.returncode or 0), stdout, stderr)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise GscGymDeterministicError(f"{activity} failed: {detail}")
    return completed


def _media_asset(
    path: Path,
    probe: dict[str, Any],
    *,
    duration_frames: int | None = None,
    source_start_frame: int | None = None,
    origin_path: Path | None = None,
) -> MediaAsset:
    audio_streams = probe.get("audio_streams") or []
    return MediaAsset(
        path=path.resolve(),
        name=path.name,
        duration_frames=(
            int(duration_frames)
            if duration_frames is not None
            else int(probe.get("timeline_frames_at_60fps") or 0)
        ),
        source_start_frame=(
            int(source_start_frame)
            if source_start_frame is not None
            else int(probe.get("media_start_frame_at_60fps") or 0)
        ),
        audio_channels=int(audio_streams[0].get("channels") or 2) if audio_streams else 2,
        origin_path=origin_path,
        video_fps=int(probe.get("video_native_fps") or 60),
    )


def _source_path_from_uri(uri: str) -> Path:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme.casefold() != "file":
        raise GscGymDeterministicError(f"Auto-editor source URI is not local file media: {uri!r}")
    raw = urllib.parse.unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:/", raw):
        raw = raw[1:]
    return Path(raw).resolve()


def _bound_auto_editor_source_asset_id(xml: str, source: Path) -> str:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise GscGymDeterministicError(f"Invalid auto-editor FCPXML: {exc}.") from exc
    expected = _path_key(source)
    candidates: list[str] = []
    for asset in root.iter():
        if asset.tag.rsplit("}", 1)[-1] != "asset" or asset.get("hasVideo") != "1":
            continue
        asset_id = str(asset.get("id") or "").strip()
        media_uris = [
            str(item.get("src") or "").strip()
            for item in list(asset)
            if item.tag.rsplit("}", 1)[-1] == "media-rep"
            and str(item.get("src") or "").strip()
        ]
        if asset_id and any(
            _path_key(_source_path_from_uri(uri)) == expected for uri in media_uris
        ):
            candidates.append(asset_id)
    if len(candidates) != 1:
        raise GscGymDeterministicError(
            "auto-editor FCPXML must contain exactly one video asset URI bound "
            f"to the selected source; matches={candidates}."
        )
    return candidates[0]


def _artifact_paths(output_dir: Path, source: Path) -> dict[str, Path]:
    stem = _safe_stem(source.stem)
    return {
        "output_dir": output_dir,
        "dialogue": output_dir / f"{stem}__dialogue-a{5}.wav",
        "autoeditor": output_dir / f"{stem}__AUTOEDITOR_RAW.fcpxml",
        "autoeditor_repair": output_dir
        / f"{stem}__AUTOEDITOR_RAW.asset-duration-repair.json",
        "fcpxml": output_dir / f"{stem}__GSC_GYM_DETERMINISTIC.fcpxml",
        "manifest": output_dir / f"{stem}__GSC_GYM_DETERMINISTIC.manifest.json",
        "plan": output_dir / f"{stem}__GSC_GYM_DETERMINISTIC.plan.json",
        "intake": output_dir / f"{stem}__intake.json",
        "receipt": output_dir / f"{stem}__resolve-dry-run.receipt.json",
        "media_pool_bins_report": output_dir
        / f"{stem}__media-pool-bins.report.json",
        "fairlight_report": output_dir / f"{stem}__fairlight.report.json",
    }


def _extract_dialogue(
    source: Path,
    destination: Path,
    *,
    ordinal: int,
    deadline: _Deadline,
) -> None:
    temporary = destination.with_name(f"{destination.stem}.tmp-{os.getpid()}.wav")
    temporary.unlink(missing_ok=True)
    try:
        _run_external(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                f"0:a:{ordinal - 1}",
                "-vn",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-c:a",
                "pcm_s24le",
                str(temporary),
            ],
            deadline=deadline,
            activity="extracting the fixed dialogue stream",
        )
        if not temporary.is_file() or temporary.stat().st_size <= 44:
            raise GscGymDeterministicError("Dialogue extraction produced no usable PCM WAV.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _run_auto_editor(
    source: Path,
    destination: Path,
    *,
    repair_report_path: Path,
    source_duration_frames: int,
    ordinal: int,
    command_prefix: list[str],
    deadline: _Deadline,
) -> dict[str, Any]:
    temporary = destination.with_name(f"{destination.stem}.tmp-{os.getpid()}.fcpxml")
    temporary.unlink(missing_ok=True)
    repair_report_path.unlink(missing_ok=True)
    try:
        _run_external(
            [
                *command_prefix,
                str(source),
                "--export",
                "final-cut-pro",
                "--output",
                str(temporary),
                "--margin",
                "0.2sec",
                "--edit",
                f"audio:stream={ordinal - 1}",
                "--frame-rate",
                "60",
                "--sounded-speed",
                "1",
                "--silent-speed",
                "99999",
                "--no-open",
            ],
            deadline=deadline,
            activity="running deterministic auto-editor silence removal",
        )
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise GscGymDeterministicError("auto-editor did not produce its FCPXML artifact.")
        raw_xml = temporary.read_text(encoding="utf-8-sig")
        source_asset_id = _bound_auto_editor_source_asset_id(raw_xml, source)
        if source_duration_frames <= 0:
            raise GscGymDeterministicError(
                "Probed source duration must be positive before auto-editor normalization."
            )
        repair_report = repair_fcpxml_asset_durations(
            temporary,
            output_path=temporary,
            report_path=repair_report_path,
            minimum_asset_durations={
                source_asset_id: Fraction(source_duration_frames, 60)
            },
        )
        # Repair, then parse before promotion so a malformed partial can never
        # become the cached input.  The later exact source-duration probe check
        # prevents the raise-only normalization from legitimizing an oversized
        # or otherwise mis-bound source range.
        parse_autoeditor_fcpxml(temporary.read_text(encoding="utf-8-sig"))
        os.replace(temporary, destination)
        repair_report.update(
            {
                # Normalize away the PID-bearing temporary path so identical
                # inputs produce byte-identical receipts across executions.
                "input_fcpxml": str(destination.resolve()),
                "output_fcpxml": str(destination.resolve()),
                "report_path": str(repair_report_path.resolve()),
                "promoted_fcpxml": str(destination.resolve()),
                "source_duration_binding": {
                    "asset_id": source_asset_id,
                    "source": str(source.resolve()),
                    "fps": 60,
                    "duration_frames": source_duration_frames,
                    "duration_fraction_seconds": str(
                        Fraction(source_duration_frames, 60)
                    ),
                    "authority": "immutable_completed_source_ffprobe_frame_count",
                },
                "promotion_validation": {
                    "parse_autoeditor_fcpxml": "pass",
                    "output_sha256": str(repair_report["output_sha256"]).upper(),
                },
            }
        )
        _atomic_json(repair_report_path, repair_report)
        return repair_report
    except Exception:
        repair_report_path.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def _validate_auto_editor_repair_report(
    report_path: Path,
    autoeditor_path: Path,
    source_path: Path,
    source_duration_frames: int,
    deadline: _Deadline,
) -> dict[str, Any]:
    report = _read_json(report_path)
    actual_sha256 = _sha256_file(autoeditor_path, deadline).upper()
    duration_binding = report.get("source_duration_binding")
    expected_duration = Fraction(source_duration_frames, 60)
    if (
        report.get("schema_version") != 1
        or report.get("kind") != "auto-editor-fcpxml-asset-duration-repair"
        or str(report.get("input_fcpxml") or "") != str(autoeditor_path.resolve())
        or str(report.get("output_fcpxml") or "") != str(autoeditor_path.resolve())
        or str(report.get("report_path") or "") != str(report_path.resolve())
        or str(report.get("promoted_fcpxml") or "") != str(autoeditor_path.resolve())
        or str(report.get("output_sha256") or "").upper() != actual_sha256
        or report.get("promotion_validation")
        != {
            "parse_autoeditor_fcpxml": "pass",
            "output_sha256": actual_sha256,
        }
        or not isinstance(duration_binding, dict)
        or str(duration_binding.get("source") or "") != str(source_path.resolve())
        or duration_binding.get("fps") != 60
        or duration_binding.get("duration_frames") != source_duration_frames
        or str(duration_binding.get("duration_fraction_seconds") or "")
        != str(expected_duration)
        or duration_binding.get("authority")
        != "immutable_completed_source_ffprobe_frame_count"
    ):
        raise GscGymDeterministicError(
            "auto-editor asset-duration repair receipt is not bound to the promoted FCPXML."
        )
    assets = report.get("assets")
    if not isinstance(assets, list) or len(assets) != int(report.get("asset_count") or -1):
        raise GscGymDeterministicError(
            "auto-editor asset-duration repair receipt has invalid asset evidence."
        )
    repaired_count = 0
    try:
        for row in assets:
            before = Fraction(str(row["declared_duration_before"]["fraction_seconds"]))
            after = Fraction(str(row["declared_duration_after"]["fraction_seconds"]))
            max_row = row.get("max_referenced_source_end")
            max_end = (
                None
                if max_row is None
                else Fraction(str(max_row["fraction_seconds"]))
            )
            minimum_row = row.get("minimum_duration_floor")
            minimum = (
                None
                if minimum_row is None
                else Fraction(str(minimum_row["fraction_seconds"]))
            )
            expected = max(
                value
                for value in (before, max_end, minimum)
                if value is not None
            )
            applied = bool(row.get("repair_applied"))
            if after != expected or applied != (after > before):
                raise ValueError("raise-only duration evidence mismatch")
            repaired_count += int(applied)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise GscGymDeterministicError(
            "auto-editor asset-duration repair receipt violates its raise-only exact-rational policy."
        ) from exc
    if (
        repaired_count != int(report.get("repaired_asset_count") or 0)
        or bool(repaired_count) != bool(report.get("changed"))
    ):
        raise GscGymDeterministicError(
            "auto-editor asset-duration repair receipt count evidence is inconsistent."
        )
    bound_asset_id = str(duration_binding.get("asset_id") or "")
    bound_rows = [row for row in assets if str(row.get("asset_id") or "") == bound_asset_id]
    if (
        len(bound_rows) != 1
        or bound_rows[0].get("minimum_duration_floor") is None
        or Fraction(
            str(bound_rows[0]["minimum_duration_floor"]["fraction_seconds"])
        )
        != expected_duration
    ):
        raise GscGymDeterministicError(
            "auto-editor repair receipt does not bind the selected source asset "
            "to the exact probed duration."
        )
    return report


def _attempt_intersects_retained(attempt: dict[str, Any], retained: Any) -> bool:
    start = int(attempt["source_start_frame"])
    end = int(attempt["source_end_frame"])
    return any(
        max(start, interval.source_start_frame)
        < min(end, interval.source_end_frame)
        for interval in retained.intervals
    )


def _validate_result_path(path: Path | None, protected: list[Path]) -> Path | None:
    if path is None:
        return None
    resolved = _require_f_drive(path, "--result-json")
    if resolved.suffix.casefold() != ".json":
        raise _UnsafeResultPathError("--result-json must name a .json file on F:.")
    if resolved.exists() and resolved.is_dir():
        raise _UnsafeResultPathError("--result-json must name a file, not a directory.")
    protected_keys = {_path_key(item) for item in protected}
    if _path_key(resolved) in protected_keys:
        raise _UnsafeResultPathError(
            "--result-json may not alias a source, session, media input, or generated artifact."
        )
    return resolved


def _asset_evidence(path: Path, deadline: _Deadline) -> dict[str, Any]:
    resolved = _required(path, "manifest-bound media resource")
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sampled_sha256": stable_seed(resolved, deadline_check=deadline.check).upper(),
    }


def _verify_asset_evidence(rows: list[dict[str, Any]], deadline: _Deadline) -> None:
    for row in rows:
        actual = _asset_evidence(Path(str(row["path"])), deadline)
        if actual != row:
            raise GscGymDeterministicError(
                f"Manifest-bound media changed before Resolve import: {row.get('path')}"
            )


def build_offline(args: argparse.Namespace, *, deadline: _Deadline | None = None) -> dict[str, Any]:
    """Build and structurally audit the complete import-ready FCPXML off line."""

    deadline = deadline or _Deadline(args.timeout_seconds)
    source = _required(args.source, "completed source recording")
    if ".partial." in source.name.casefold() or source.name.casefold().endswith(".partial.webm"):
        raise GscGymDeterministicError("The deterministic build refuses partial recording media.")
    session_dir = _resolve_session(source, args.session_dir)
    events_path = _required(session_dir / "events.json", "canonical session events")
    meta_path = _required(session_dir / "meta.json", "canonical session metadata")
    meta = _read_json(meta_path)
    vertical = meta.get("verticalRecording") or {}
    if vertical.get("status") != "finalized":
        raise GscGymDeterministicError("Recording is not finalized; the active recording remains untouched.")
    if str(meta.get("runType") or "").casefold() != "gym leader challenge":
        raise GscGymDeterministicError("Session runType is not Gym Leader Challenge.")
    preliminary_events = load_events(events_path)
    preliminary_intake = _battle_telemetry_intake(
        events=preliminary_events,
        source=source,
        requested_recovery_receipt=getattr(args, "video_recovery_receipt", None),
    )
    supplemental_inputs: dict[str, Path] = {}
    if preliminary_intake.get("receipt_path") is not None:
        supplemental_inputs["video_recovery_receipt"] = Path(
            preliminary_intake["receipt_path"]
        )
    if getattr(args, "battle_intro_root", None) is None:
        supplemental_inputs["battle_intro_manifest"] = _required(
            Path(args.battle_intro_manifest),
            "approved Gen 2 battle-intro library manifest",
        )
    snapshot = _stabilize_inputs(
        source,
        events_path,
        meta_path,
        deadline,
        supplemental_inputs=supplemental_inputs,
    )
    events = load_events(events_path)
    intake = _battle_telemetry_intake(
        events=events,
        source=source,
        requested_recovery_receipt=getattr(args, "video_recovery_receipt", None),
    )
    if (
        intake.get("mode"),
        str(intake.get("receipt_path") or ""),
    ) != (
        preliminary_intake.get("mode"),
        str(preliminary_intake.get("receipt_path") or ""),
    ):
        raise GscGymDeterministicError(
            "Battle telemetry mode changed during completed-source stabilization."
        )

    config = _read_json(args.config)
    workflow = next((row for row in config.get("workflows", []) if row.get("id") == WORKFLOW_ID), None)
    if workflow is None:
        raise GscGymDeterministicError(f"Workflow {WORKFLOW_ID!r} is not registered.")
    validate_zero_llm_workflow(workflow)
    fairlight_preset = _required(
        DEFAULT_FAIRLIGHT_PRESET,
        "repository Fairlight preset required by the final Resolve transaction",
    )
    reference_audit = audit_surge_reference(
        contract_path=args.reference_contract,
        workflow_config_path=args.config,
    )
    if reference_audit.get("status") != "pass":
        raise GscGymDeterministicError(
            "Fingerprint-bound Surge authority failed: "
            + ", ".join(reference_audit.get("failed_checks") or ["unknown check"])
        )

    source_probe = _probe_media(source, deadline)
    source_contract = _validate_completed_source(
        source,
        source_probe,
        dialogue_audio_ordinal=args.dialogue_audio_ordinal,
        stat_before=(snapshot["source"]["size"], snapshot["source"]["mtime_ns"]),
    )
    battle_mapping = _map_battle_intake_to_source(
        intake=intake,
        events=events,
        source=source,
        source_probe=source_probe,
        events_path=events_path,
        meta_path=meta_path,
        deadline=deadline,
    )
    alignment = battle_mapping["source_alignment"]
    mapped_attempts = battle_mapping["mapped_attempts"]
    recovery_binding = battle_mapping.get("recovery_binding")
    seed_paths = [source, events_path, meta_path, *supplemental_inputs.values()]
    seed = stable_seed(*seed_paths, deadline_check=deadline.check)

    leader = ((vertical.get("project") or {}).get("subject") or meta.get("pokemon"))
    if not str(leader or "").strip():
        raise GscGymDeterministicError("Session does not identify the selected Gym Leader profile.")
    output_dir = _require_f_drive(
        args.output_dir
        or DEFAULT_OUTPUT_ROOT / f"{_safe_stem(session_dir.name)}-{seed[:12]}",
        "deterministic output directory",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = _artifact_paths(output_dir, source)
    paths["dialogue"] = output_dir / (
        f"{_safe_stem(source.stem)}__dialogue-a{args.dialogue_audio_ordinal}.wav"
    )
    _validate_result_path(
        args.result_json,
        [
            source,
            events_path,
            meta_path,
            args.config,
            args.reference_contract,
            args.opening_intro_video,
            args.opening_intro_source,
            args.outro_video,
            *(
                [args.battle_intro_manifest]
                if getattr(args, "battle_intro_root", None) is None
                else []
            ),
            *supplemental_inputs.values(),
            *[value for key, value in paths.items() if key != "output_dir"],
        ],
    )

    auto_editor_command, auto_editor_version = find_auto_editor_command(sys.executable)
    if not auto_editor_command:
        raise GscGymDeterministicError(f"auto-editor is unavailable: {auto_editor_version}")
    executable = Path(auto_editor_command[0]).resolve()
    executable_hash = _sha256_file(executable, deadline) if executable.is_file() else ""
    cache_contract_base = {
        "schema": "gsc_gym_deterministic_intake_v1",
        "seed_sha256": seed.upper(),
        "input_snapshot": snapshot,
        "dialogue_audio_ordinal": args.dialogue_audio_ordinal,
        "auto_editor_command": auto_editor_command,
        "auto_editor_version": auto_editor_version,
        "auto_editor_executable_sha256": executable_hash,
        "auto_editor_margin": "0.2sec",
        "auto_editor_edit": f"audio:stream={args.dialogue_audio_ordinal - 1}",
        "auto_editor_frame_rate": 60,
        "auto_editor_sounded_speed": 1,
        "auto_editor_silent_speed": 99_999,
        "auto_editor_no_open": True,
        "auto_editor_asset_duration_repair_policy": (
            AUTO_EDITOR_ASSET_DURATION_REPAIR_POLICY
        ),
        "dialogue_codec": "pcm_s24le",
        "dialogue_sample_rate": 48_000,
        "dialogue_channels": 2,
    }
    cached = None
    if paths["intake"].is_file():
        try:
            cached = _read_json(paths["intake"])
        except (OSError, json.JSONDecodeError):
            cached = None
    reuse = False
    if isinstance(cached, dict):
        cached_base = {key: cached.get(key) for key in cache_contract_base}
        cached_artifacts = cached.get("artifacts")
        if cached_base == cache_contract_base and isinstance(cached_artifacts, list):
            try:
                _verify_asset_evidence(cached_artifacts, deadline)
                expected_cached_paths = {
                    _path_key(paths["dialogue"]),
                    _path_key(paths["autoeditor"]),
                    _path_key(paths["autoeditor_repair"]),
                }
                actual_cached_paths = {
                    _path_key(Path(str(row.get("path") or "")))
                    for row in cached_artifacts
                    if isinstance(row, dict)
                }
                reuse = actual_cached_paths == expected_cached_paths
            except (GscGymDeterministicError, OSError, KeyError, TypeError, ValueError):
                reuse = False
    if not reuse:
        _extract_dialogue(
            source,
            paths["dialogue"],
            ordinal=args.dialogue_audio_ordinal,
            deadline=deadline,
        )
        _run_auto_editor(
            source,
            paths["autoeditor"],
            repair_report_path=paths["autoeditor_repair"],
            source_duration_frames=int(source_probe["timeline_frames_at_60fps"]),
            ordinal=args.dialogue_audio_ordinal,
            command_prefix=list(auto_editor_command),
            deadline=deadline,
        )
        auto_editor_repair = _validate_auto_editor_repair_report(
            paths["autoeditor_repair"],
            paths["autoeditor"],
            source,
            int(source_probe["timeline_frames_at_60fps"]),
            deadline,
        )
        cache_contract = {
            **cache_contract_base,
            "artifacts": [
                _asset_evidence(paths["dialogue"], deadline),
                _asset_evidence(paths["autoeditor"], deadline),
                _asset_evidence(paths["autoeditor_repair"], deadline),
            ],
        }
        _atomic_json(paths["intake"], cache_contract)
    else:
        auto_editor_repair = _validate_auto_editor_repair_report(
            paths["autoeditor_repair"],
            paths["autoeditor"],
            source,
            int(source_probe["timeline_frames_at_60fps"]),
            deadline,
        )

    dialogue_probe = _probe_media(paths["dialogue"], deadline)
    if (
        dialogue_probe["video_stream_count"] != 0
        or dialogue_probe["audio_stream_count"] != 1
        or dialogue_probe["audio_streams"][0]["codec"] != "pcm_s24le"
        or dialogue_probe["audio_streams"][0]["sample_rate"] != 48_000
        or dialogue_probe["audio_streams"][0]["channels"] != 2
    ):
        raise GscGymDeterministicError("Extracted dialogue is not exact stereo PCM at 48 kHz.")
    raw_xml = paths["autoeditor"].read_text(encoding="utf-8-sig")
    retained = parse_autoeditor_fcpxml(raw_xml)
    if _path_key(_source_path_from_uri(retained.source_uri)) != _path_key(source):
        raise GscGymDeterministicError("auto-editor FCPXML is not bound to the exact selected source.")
    if abs(retained.source_duration_frames - int(source_probe["timeline_frames_at_60fps"])) > 2:
        raise GscGymDeterministicError("auto-editor/source duration identity differs by more than two frames.")
    if retained.intervals[-1].source_end_frame > int(dialogue_probe["timeline_frames_at_60fps"]):
        raise GscGymDeterministicError("Extracted dialogue does not cover the final retained source frame.")

    retained_attempts = [row for row in mapped_attempts if _attempt_intersects_retained(row, retained)]
    if not retained_attempts or not any(row["role"] == "leader" for row in retained_attempts):
        raise GscGymDeterministicError("The deterministic dialogue edit retained no leader battle.")
    carousel_telemetry = canonical_carousel_boundary(events)
    carousel_row = _carousel_source_boundary(
        telemetry=carousel_telemetry,
        alignment=alignment,
        source=source,
        source_frames=int(source_probe["video_source_frames"]),
        last_battle_source_end=int(retained_attempts[-1]["source_end_frame"]),
        deadline=deadline,
    )
    carousel_source_frame = int(carousel_row["source_frame"])
    if carousel_source_frame <= int(retained_attempts[-1]["source_end_frame"]):
        raise GscGymDeterministicError("Member carousel boundary does not follow every retained battle.")
    boundaries = tuple(
        BattleAttemptSourceBoundary(
            attempt_id=str(row["attempt_id"]),
            canonical_identity=str(row["canonical_identity"]),
            attempt_ordinal=int(row["identity_attempt_ordinal"]),
            role=str(row["role"]),
            source_start_frame=int(row["source_start_frame"]),
            source_end_frame=int(row["source_end_frame"]),
            start_authority=str(row["source_start_authority"]),
            end_authority=str(row["source_end_authority"]),
        )
        for row in retained_attempts
    )
    geometry = plan_gsc_gym_geometry(
        retained,
        boundaries,
        CarouselSourceBoundary(
            carousel_source_frame,
            str(carousel_row["source_boundary_authority"]),
        ),
        dialogue_gain_db=args.dialogue_gain_db,
        max_snap_frames=args.max_boundary_snap_frames,
    )

    planned_by_id = {row.attempt_id: row for row in geometry.battles}
    intro_input: list[dict[str, Any]] = []
    for row in retained_attempts:
        planned = planned_by_id[str(row["attempt_id"])]
        bound = dict(row)
        bound["final_timeline_start_frame"] = planned.final_start_frame
        intro_input.append(bound)
    intro_placements = build_overlay_intro_plan(
        intro_input,
        **_intro_asset_plan_kwargs(args),
        rival_starter_type=(
            None if args.rival_starter_type == "auto" else args.rival_starter_type
        ),
        boundary_is_final_timeline=True,
    )
    eligible_ids = [row.attempt_id for row in geometry.battles if row.intro_eligible]
    if len(intro_placements) != len(eligible_ids):
        raise GscGymDeterministicError("Deterministic intro identities disagree with planned major battles.")
    intro_placement_by_id = dict(zip(eligible_ids, intro_placements))

    bgm_dir = args.layout_root / "audio" / "bgm"
    opening_bgm_path = _required(bgm_dir / INTRO_TRACK, "reserved Dual Screen Lovelife BGM")
    golden_goose_path = _required(bgm_dir / OUTRO_TRACK, "reserved Golden Goose identity")
    post_final_paths = tuple(
        _required(bgm_dir / name, f"required post-final BGM {name}")
        for name in POST_FINAL_REQUIRED_TRACKS
    )
    nonbattle_paths = choose_nonbattle_tracks(bgm_dir, seed=seed)
    battle_dir = args.layout_root / "audio" / BATTLE_AUDIO_DIR
    battle_library, contracted_battle_names = _contracted_battle_library(
        battle_dir,
        args.reference_contract,
    )
    battle_paths = choose_battle_tracks(battle_library, count=len(geometry.battles), seed=seed)
    opening_video = _required(args.opening_intro_video, "approved 4x GSC opening intro")
    opening_source = _required(args.opening_intro_source, "GSC opening intro lineage source")
    outro_video = _required(args.outro_video, "linked GSC outro MOV")
    media_preflight = _validate_structural_media(
        opening_derivative=opening_video,
        opening_source=opening_source,
        outro=outro_video,
        intro_placements=intro_placements,
        deadline=deadline,
    )

    audio_probe_cache: dict[str, dict[str, Any]] = {}

    def audio_asset(path: Path) -> MediaAsset:
        key = _path_key(path)
        probe = audio_probe_cache.get(key)
        if probe is None:
            probe = _probe_media(_required(path, "audio asset"), deadline)
            if probe["audio_stream_count"] < 1 or probe["timeline_frames_at_60fps"] <= 0:
                raise GscGymDeterministicError(f"Audio asset has no usable 48 kHz timeline duration: {path}")
            audio_probe_cache[key] = probe
        return _media_asset(path, probe)

    opening_bgm = audio_asset(opening_bgm_path)
    post_final_assets = tuple(audio_asset(path) for path in post_final_paths)
    nonbattle_assets = tuple(audio_asset(path) for path in nonbattle_paths)
    battle_assets = tuple(audio_asset(path) for path in battle_paths)
    battle_audio_ranges = tuple(
        BattleAudioRange(
            battle_id=planned.attempt_id,
            record_start_frame=planned.final_start_frame,
            record_end_frame=planned.final_end_frame,
            asset=asset,
        )
        for planned, asset in zip(geometry.battles, battle_assets)
    )
    bgm_plan = plan_gsc_gym_bgm(
        opening_track=opening_bgm,
        post_final_required_tracks=post_final_assets,
        randomized_nonbattle_tracks=nonbattle_assets,
        battles=battle_audio_ranges,
        carousel_start_frame=geometry.carousel.v1.record_start_frame,
        fill_end_frame=geometry.carousel.v1.record_end_frame,
    )
    source_a2 = build_source_a2_contract(
        bgm_plan,
        deadline_check=deadline.check,
    )
    a2_contract_audit = _audit_source_a2_contract(bgm_plan, source_a2)

    intro_overlays: dict[str, IntroOverlay] = {}
    for battle_id, placement in intro_placement_by_id.items():
        asset_path = Path(str(placement["asset"]))
        probe = media_preflight["battle_intros"][str(asset_path)]
        intro_overlays[battle_id] = IntroOverlay(
            _media_asset(asset_path, probe),
            str(placement["identity"]),
            str(placement["role"]),
        )
    source_asset = _media_asset(
        source,
        source_probe,
        duration_frames=retained.source_duration_frames,
        source_start_frame=retained.source_start_frame,
    )
    dialogue_asset = _media_asset(
        paths["dialogue"],
        dialogue_probe,
        duration_frames=retained.source_duration_frames,
        source_start_frame=retained.source_start_frame,
    )
    opening_asset = _media_asset(opening_video, media_preflight["opening_derivative"])
    outro_asset = _media_asset(outro_video, media_preflight["outro"])
    timeline_name = args.timeline_name or (
        f"{leader} {meta.get('version') or 'Crystal'} Gym Leader Challenge deterministic dry run"
    )
    spec = GscGymFcpxmlSpec(
        timeline_name=str(timeline_name),
        source_video=source_asset,
        dialogue_audio=dialogue_asset,
        opening=OpeningSpec(opening_asset, pre_retimed_rate_percent=OPENING_INTRO_SPEED_PCT),
        body_v1=geometry.body_v1,
        dialogue_a1=geometry.dialogue_a1,
        battles=geometry.assembler_battles(intro_overlays),
        bgm_a2=source_a2.segments,
        carousel=geometry.carousel,
        outro=OutroSpec(outro_asset, gain_db=args.outro_gain_db),
        battle_bgm_library_filenames=contracted_battle_names,
        battle_bgm_assignment_policy=BATTLE_BGM_ASSIGNMENT_POLICY,
        battle_bgm_seed=seed.upper(),
    )
    build = assemble_gsc_gym_fcpxml(spec)
    fcpxml_bytes = build.xml.encode("utf-8")
    fcpxml_sha256 = hashlib.sha256(fcpxml_bytes).hexdigest().upper()
    manifest = dict(build.manifest)
    resource_paths = sorted(
        {Path(str(row["path"])).resolve() for row in manifest.get("resources") or []},
        key=lambda item: _path_key(item),
    )
    resource_evidence = [_asset_evidence(path, deadline) for path in resource_paths]
    final_battle_end = geometry.battles[-1].final_end_frame
    post_final_occurrences: list[dict[str, Any]] = []
    for row in bgm_plan:
        if row.role == "battle" or row.record_end_frame <= final_battle_end:
            continue
        origin = Path(str(row.asset.origin_path or row.asset.path)).resolve()
        if (
            post_final_occurrences
            and post_final_occurrences[-1]["origin_key"] == _path_key(origin)
            and post_final_occurrences[-1]["record_range"][1] == row.record_start_frame
        ):
            post_final_occurrences[-1]["record_range"][1] = row.record_end_frame
            post_final_occurrences[-1]["source_range"][1] = row.source_end_frame
            continue
        post_final_occurrences.append(
            {
                "origin_key": _path_key(origin),
                "source": str(origin),
                "filename": origin.name,
                "record_range": [row.record_start_frame, row.record_end_frame],
                "source_range": [row.source_start_frame, row.source_end_frame],
            }
        )
    for row in post_final_occurrences:
        row.pop("origin_key", None)
    post_battle_handoffs: list[dict[str, Any]] = []
    for index, battle in enumerate(geometry.battles):
        next_boundary = (
            geometry.battles[index + 1].final_start_frame
            if index + 1 < len(geometry.battles)
            else geometry.carousel.v1.record_end_frame
        )
        first = next(
            (
                row for row in bgm_plan
                if row.record_start_frame == battle.final_end_frame
            ),
            None,
        )
        post_battle_handoffs.append(
            {
                "battle_id": battle.attempt_id,
                "battle_end_frame": battle.final_end_frame,
                "next_boundary_frame": next_boundary,
                "mode": (
                    "direct_battle_handoff"
                    if next_boundary == battle.final_end_frame
                    else "fresh_source_zero_nonbattle"
                ),
                "source": (
                    None
                    if first is None or first.role == "battle"
                    else str(Path(str(first.asset.origin_path or first.asset.path)).resolve())
                ),
                "source_start_frame": (
                    None if first is None or first.role == "battle" else first.source_start_frame
                ),
            }
        )
    manifest.update(
        {
            "workflow_id": WORKFLOW_ID,
            "zero_llm": True,
            "fcpxml_sha256": fcpxml_sha256,
            "source_binding": {
                "source": str(source),
                "session_dir": str(session_dir),
                "seed_sha256": seed.upper(),
                "input_snapshot": snapshot,
                "chapter_alignment": alignment,
                "battle_mapping_mode": battle_mapping["mode"],
                "typed_recovery_trigger": battle_mapping.get("typed_trigger"),
                "video_recovery": recovery_binding,
            },
            "geometry_plan": geometry.manifest,
            "resource_evidence": resource_evidence,
            "carousel_boundary": carousel_row,
            "a2_original_source_clips": list(source_a2.clips),
            "a2_contract_audit": a2_contract_audit,
            "battle_intro_approvals": [
                dict(row["asset_approval"])
                for row in intro_placements
            ],
            "auto_editor_asset_duration_repair": {
                **auto_editor_repair,
                "policy_id": AUTO_EDITOR_ASSET_DURATION_REPAIR_POLICY,
                "artifact_path": str(paths["autoeditor_repair"]),
            },
            "opening_lineage": {
                "source": str(opening_source),
                "source_probe": media_preflight["opening_source"],
                "derivative": str(opening_video),
                "speed_percent": OPENING_INTRO_SPEED_PCT,
                "timeline_frames": OPENING_INTRO_TIMELINE_FRAMES,
            },
            "audio_reservations": {
                "dual_screen_lovelife": str(opening_bgm_path),
                "post_final_required_tracks": [str(path) for path in post_final_paths],
                "golden_goose_blocked_from_a2": str(golden_goose_path),
                "golden_goose_owned_by_linked_outro_audio": True,
                "battle_library_root": str(battle_dir.resolve()),
            },
            "nonbattle_bgm_contract": {
                "schema": "gsc_gym_nonbattle_bgm_contract_v2",
                "status": "pass",
                "selection_seed": seed.upper(),
                "random_without_replacement": True,
                "only_repeat_exception": INTRO_TRACK,
                "post_final_allocation_policy": (
                    "fair_share_required_three_plus_exact_next_unused_random;"
                    "extend_required_in_reverse_order_to_fit_fourth_natural_duration"
                ),
                "post_final_exact_identity_count": 4,
                "post_final_fourth_identity_policy": (
                    "exact_next_unused_seeded_random_asset_finishes_A2"
                ),
                "post_final_required_filenames": list(POST_FINAL_REQUIRED_TRACKS),
                "post_final_occurrences": post_final_occurrences,
                "post_battle_handoffs": post_battle_handoffs,
            },
            "media_pool_bins": {
                "schema": "gsc_gym_media_pool_bin_inputs_v1",
                "project_dir": str(source.parent.resolve()),
                "nonbattle_bgm_dir": str(bgm_dir.resolve()),
                "battle_bgm_dir": str(battle_dir.resolve()),
                "intro_manifest_path": str(Path(args.battle_intro_manifest).resolve()),
                "opening_intro_path": str(opening_video.resolve()),
                "outro_path": str(outro_video.resolve()),
                "full_reusable_library": True,
                "timeline_creation_count": 0,
            },
            "surge_reference_audit": reference_audit,
        }
    )
    _require_unchanged_inputs(
        snapshot,
        source,
        events_path,
        meta_path,
        deadline,
        activity="final artifact commit",
        supplemental_inputs=supplemental_inputs,
    )
    _require_recovery_media_unchanged(
        recovery_binding,
        deadline,
        activity="final artifact commit",
    )
    _atomic_write(paths["fcpxml"], fcpxml_bytes)
    _atomic_json(paths["manifest"], manifest)
    result = {
        "schema": "gsc_gym_deterministic_execution_v1",
        "status": "pass",
        "deployment_ready": False,
        "resolve_dry_run_ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workflow_id": WORKFLOW_ID,
        "zero_llm": True,
        "wall_clock_limit_seconds": args.timeout_seconds,
        "elapsed_seconds": round(time.monotonic() - deadline.started, 3),
        "cache_reused": reuse,
        "source": str(source),
        "session_dir": str(session_dir),
        "leader_profile": str(leader),
        "timeline_name": str(timeline_name),
        "source_contract": source_contract,
        "battle_mapping_mode": battle_mapping["mode"],
        "typed_recovery_trigger": battle_mapping.get("typed_trigger"),
        "video_recovery_binding": recovery_binding,
        "canonical_physical_attempt_count": len(mapped_attempts),
        "retained_physical_attempt_count": len(retained_attempts),
        "major_intro_count": len(intro_overlays),
        "exact_a1_gap_count": sum(
            battle.a1_gap_eligible for battle in geometry.battles
        ),
        "carousel_v2_slice_count": len(geometry.carousel.v2_slices),
        "artifacts": {
            key: str(value)
            for key, value in paths.items()
            if key != "output_dir"
        },
        "fcpxml_sha256": fcpxml_sha256,
        "manifest_sha256": _sha256_file(paths["manifest"], deadline),
        "offline_structural_audit": build.structural_audit,
        "fairlight_preset_source_evidence": _asset_evidence(
            fairlight_preset, deadline
        ),
        "resolve_mutations": 0,
    }
    _atomic_json(paths["plan"], result)
    return result


def execute_resolve_dry_run(args: argparse.Namespace) -> dict[str, Any]:
    if not str(args.resolve_project or "").strip():
        raise GscGymDeterministicError(
            "The full Resolve build requires --resolve-project with the exact open project name."
        )
    deadline = _Deadline(args.timeout_seconds)
    result = build_offline(args, deadline=deadline)
    manifest_path = Path(result["artifacts"]["manifest"])
    fcpxml_path = Path(result["artifacts"]["fcpxml"])
    receipt_path = Path(result["artifacts"]["receipt"])
    media_pool_report_path = Path(result["artifacts"]["media_pool_bins_report"])
    fairlight_report_path = Path(result["artifacts"]["fairlight_report"])
    manifest = _read_json(manifest_path)
    binding = manifest["source_binding"]
    session_dir = Path(str(binding["session_dir"]))
    recovery_binding = binding.get("video_recovery")
    supplemental_inputs = _supplemental_paths_from_snapshot(
        binding["input_snapshot"]
    )
    _require_unchanged_inputs(
        binding["input_snapshot"],
        Path(str(binding["source"])),
        session_dir / "events.json",
        session_dir / "meta.json",
        deadline,
        activity="pre-Resolve immutable-input revalidation",
        supplemental_inputs=supplemental_inputs,
    )
    _require_recovery_media_unchanged(
        recovery_binding if isinstance(recovery_binding, dict) else None,
        deadline,
        activity="pre-Resolve immutable-input revalidation",
    )
    _verify_asset_evidence(list(manifest["resource_evidence"]), deadline)
    _verify_asset_evidence(
        [dict(result["fairlight_preset_source_evidence"])], deadline
    )
    from resolve_mcp.connection import ResolveConnection

    connection = ResolveConnection()
    if not connection.connect():
        raise GscGymDeterministicError(
            "Resolve connection failed: " + (connection.last_error or "not connected")
        )
    resolve = connection.get_resolve()
    try:
        receipt = run_resolve_dry_run(
            resolve=resolve,
            fcpxml_path=fcpxml_path,
            manifest_path=manifest_path,
            manifest=manifest,
            receipt_path=receipt_path,
            media_pool_report_path=media_pool_report_path,
            fairlight_report_path=fairlight_report_path,
            expected_project_name=str(args.resolve_project),
            deadline_check=deadline.check,
        )
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        receipt_evidence = None
        if receipt_path.is_file():
            try:
                receipt_evidence = _read_json(receipt_path)
            except (OSError, json.JSONDecodeError):
                receipt_evidence = {"status": "unreadable", "path": str(receipt_path)}
        wrapped = GscGymDeterministicError(str(exc))
        wrapped.resolve_receipt = receipt_evidence  # type: ignore[attr-defined]
        raise wrapped from exc
    result.update(
        {
            "deployment_ready": resolve_receipt_deployment_ready(receipt),
            "resolve_dry_run_ready": True,
            "resolve_mutations": int(receipt.get("editorial_import_count") or 0),
            "resolve_dry_run": receipt,
            "elapsed_seconds": round(time.monotonic() - deadline.started, 3),
        }
    )
    _atomic_json(Path(result["artifacts"]["plan"]), result)
    return result


def _watchdog(argv: list[str], timeout_seconds: float) -> int:
    ends = time.monotonic() + timeout_seconds
    reserve = min(5.0, max(0.1, timeout_seconds * 0.02), timeout_seconds / 2)
    worker_budget = max(0.01, ends - time.monotonic() - reserve)
    command = [sys.executable, str(Path(__file__).resolve()), *argv, "--_worker"]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(command, creationflags=creationflags)
    try:
        return int(process.wait(timeout=worker_budget))
    except subprocess.TimeoutExpired:
        _terminate_owned_process_tree(process, ends=ends)
        print(
            f"[deterministic-gsc-gym] ERROR: hard {timeout_seconds:.0f}-second process-tree deadline reached.",
            file=sys.stderr,
        )
        return 124


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("preflight", "dry-run", "build-offline", "resolve-dry-run", "full", "stage"),
    )
    parser.add_argument(
        "--name",
        choices=("prepare", "build-offline", "resolve-dry-run"),
        default="prepare",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--session-dir", type=Path)
    parser.add_argument(
        "--video-recovery-receipt",
        type=Path,
        help=(
            "Optional exact content-bound receipt used only when canonical parsing "
            "raises typed incomplete battle telemetry; defaults to the source CODEx folder."
        ),
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeline-name")
    parser.add_argument("--resolve-project")
    parser.add_argument("--layout-root", type=Path, default=DEFAULT_LAYOUT)
    parser.add_argument("--outro-video", type=Path, default=DEFAULT_OUTRO)
    parser.add_argument("--opening-intro-video", type=Path, default=DEFAULT_OPENING_INTRO)
    parser.add_argument(
        "--opening-intro-source",
        type=Path,
        default=DEFAULT_OPENING_INTRO_SOURCE,
    )
    parser.add_argument(
        "--battle-intro-manifest",
        type=Path,
        default=DEFAULT_GSC_INTRO_LIBRARY_MANIFEST,
        help=(
            "Approved manifest-backed Gen 2 intro library. Selected masters are "
            "validated by status, technical contract, byte count, and SHA-256."
        ),
    )
    parser.add_argument(
        "--battle-intro-root",
        type=Path,
        help=(
            "Diagnostic compatibility only: explicit legacy root containing leaders/ "
            "and rivals/; overrides --battle-intro-manifest."
        ),
    )
    parser.add_argument(
        "--rival-starter-type",
        choices=("auto", "grass", "fire", "water"),
        default="auto",
        help=(
            "Use the exact Crystal RIVAL1 trainer-ID party table by default; "
            "an explicit override remains deterministic for a known ROM hack."
        ),
    )
    parser.add_argument("--dialogue-gain-db", type=float, default=0.0)
    parser.add_argument("--outro-gain-db", type=float, default=0.0)
    parser.add_argument("--max-boundary-snap-frames", type=int, default=600)
    parser.add_argument(
        "--dialogue-audio-ordinal",
        type=int,
        default=5,
        help=(
            "One-based OBS audio-stream ordinal for the isolated narration contract; "
            "the preserved Surge workflow's audio:stream=4 is one-based ordinal 5."
        ),
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--reference-contract", type=Path, default=DEFAULT_REFERENCE_CONTRACT)
    parser.add_argument("--result-json", type=Path)
    parser.add_argument(
        "--require-resolve",
        action="store_true",
        help="Require a read-only connection to the current Resolve project; performs no mutation.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=MAX_FULL_RUN_SECONDS)
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 < args.timeout_seconds <= MAX_FULL_RUN_SECONDS:
        parser.error(f"--timeout-seconds must be in (0, {MAX_FULL_RUN_SECONDS:.0f}]")
    if args.max_boundary_snap_frames <= 0 or args.max_boundary_snap_frames > 600:
        parser.error("--max-boundary-snap-frames must be in [1, 600]")
    if not args._worker:
        return _watchdog(sys.argv[1:], args.timeout_seconds)

    static_protected = [
        args.source,
        args.config,
        args.reference_contract,
        args.opening_intro_video,
        args.opening_intro_source,
        args.outro_video,
    ]
    if args.battle_intro_root is None:
        static_protected.append(args.battle_intro_manifest)
    if args.session_dir:
        static_protected.extend([args.session_dir / "events.json", args.session_dir / "meta.json"])
    if args.video_recovery_receipt:
        static_protected.append(args.video_recovery_receipt)
    safe_result: Path | None = None
    try:
        safe_result = _validate_result_path(args.result_json, static_protected)
        command = args.name if args.command == "stage" else args.command
        if command in {"preflight", "dry-run", "prepare"}:
            plan = build_dry_run(args)
        elif command == "build-offline":
            plan = build_offline(args)
        elif command in {"resolve-dry-run", "full"}:
            plan = execute_resolve_dry_run(args)
        else:
            raise GscGymDeterministicError(f"Unsupported deterministic GSC command: {command}")
        artifact_paths = [Path(value) for value in (plan.get("artifacts") or {}).values()]
        safe_result = _validate_result_path(safe_result, [*static_protected, *artifact_paths])
        if safe_result:
            _atomic_json(safe_result, plan)
        print(json.dumps(plan, indent=2))
        return 0
    except (
        GscGymDeterministicError,
        ValueError,
        RuntimeError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        AttributeError,
    ) as exc:
        if isinstance(exc, _UnsafeResultPathError):
            safe_result = None
        if safe_result:
            receipt_evidence = getattr(exc, "resolve_receipt", None)
            failure = {
                "schema": PLAN_SCHEMA,
                "status": "fail",
                "plan_status": "fail",
                "deployment_ready": False,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "workflow_id": WORKFLOW_ID,
                "zero_llm": True,
                "resolve_mutations": int(
                    (receipt_evidence or {}).get("editorial_import_count") or 0
                ),
                "resolve_receipt": receipt_evidence,
                "error": str(exc),
            }
            _atomic_json(safe_result, failure)
        print(f"[deterministic-gsc-gym] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
