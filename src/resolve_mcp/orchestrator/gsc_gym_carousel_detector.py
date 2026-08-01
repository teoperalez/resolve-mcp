from __future__ import annotations

"""Fixed-pixel, zero-model detection of the GSC member-carousel transition.

The GSC layout changes both lower corner patches from the normal full-frame
layout to the carousel's black 25vh bed in a single source frame.  This module
only recognizes that documented transition after a caller-provided final
battle boundary.  It never classifies arbitrary images and it fails closed
when the fixed 3840x2160/60 three-patch lifecycle contract is not satisfied.
"""

import math
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Sequence


FPS = 60
WIDTH = 3840
HEIGHT = 2160
PATCH_SIZE = 160
CONTROL_PATCH_X = (WIDTH - PATCH_SIZE) // 2
CONTROL_PATCH_Y = 0
PRE_ROLL_FRAMES = 6
# Preserved Surge source frames 299957..300080 prove at least 124 frames of
# dark lower corners with a bright control; require a conservative 120 frames.
SUSTAIN_FRAMES = 120
# Bound candidate onsets to the original two-minute post-battle search policy,
# then decode the already-required sustain window so a transition near the end
# of that policy can still be proved.  MAX_SCAN_FRAMES is therefore a decode
# bound, not a broader candidate-onset window.
MAX_ONSET_SEARCH_FRAMES = 120 * FPS
MAX_SCAN_FRAMES = MAX_ONSET_SEARCH_FRAMES + SUSTAIN_FRAMES
PRE_MIN_LUMA = 40
CAROUSEL_MAX_LUMA = 8
CONTROL_MIN_LUMA = 40


class GscCarouselDetectionError(RuntimeError):
    pass


def detect_transition_from_luma_samples(
    samples: Sequence[tuple[int, int, int]],
    *,
    source_start_frame: int,
    pre_roll_frames: int = PRE_ROLL_FRAMES,
    sustain_frames: int = SUSTAIN_FRAMES,
    pre_min_luma: int = PRE_MIN_LUMA,
    carousel_max_luma: int = CAROUSEL_MAX_LUMA,
    control_min_luma: int = CONTROL_MIN_LUMA,
) -> dict[str, Any]:
    """Select the final lower-corner transition with a non-dark control.

    Each sample contains integer luma for the left and right 160x160 lower
    corners followed by a fixed top-center control patch.  A candidate requires
    a bright pre-roll in both lower patches and a two-second sustained dark bed
    in both lower patches while the control stays non-dark.  The control rejects
    full-frame fades.  Multiple valid transitions are retained as evidence and
    the last one is authoritative, matching the final-cycle telemetry rule.
    """

    if source_start_frame < 0:
        raise GscCarouselDetectionError("Carousel scan start must be non-negative.")
    if pre_roll_frames <= 0 or sustain_frames <= 0:
        raise GscCarouselDetectionError("Carousel detector windows must be positive.")
    if len(samples) < pre_roll_frames + sustain_frames:
        raise GscCarouselDetectionError(
            "Carousel scan is too short for its fixed transition contract."
        )
    for index, sample in enumerate(samples):
        if (
            not isinstance(sample, tuple)
            or len(sample) != 3
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= 255
                for value in sample
            )
        ):
            raise GscCarouselDetectionError(
                f"Carousel luma sample {index} is not an unsigned-byte triple."
            )

    candidates: list[int] = []
    last_start = len(samples) - sustain_frames
    for index in range(pre_roll_frames, last_start + 1):
        before = samples[index - pre_roll_frames:index]
        after = samples[index:index + sustain_frames]
        if not all(
            left >= pre_min_luma
            and right >= pre_min_luma
            and control >= control_min_luma
            for left, right, control in before
        ):
            continue
        if not all(
            left <= carousel_max_luma
            and right <= carousel_max_luma
            and control >= control_min_luma
            for left, right, control in after
        ):
            continue
        candidates.append(source_start_frame + index)

    if not candidates:
        raise GscCarouselDetectionError(
            "No fixed GSC bright-corners to black-carousel transition was found."
        )
    selected = candidates[-1]
    return {
        "schema": "gsc_fixed_pixel_carousel_boundary_v2",
        "status": "pass",
        "source_frame": selected,
        "source_start_frame": source_start_frame,
        "scanned_frame_count": len(samples),
        "candidate_source_frames": candidates,
        "selected_candidate_ordinal": len(candidates),
        "selection_policy": "final_qualifying_transition_after_final_battle",
        "fixed_contract": {
            "fps": FPS,
            "width": WIDTH,
            "height": HEIGHT,
            "patch_size": PATCH_SIZE,
            "patches": [
                {"x": 0, "y": HEIGHT - PATCH_SIZE},
                {"x": WIDTH - PATCH_SIZE, "y": HEIGHT - PATCH_SIZE},
            ],
            "control_patch": {
                "x": CONTROL_PATCH_X,
                "y": CONTROL_PATCH_Y,
                "size": PATCH_SIZE,
            },
            "pre_roll_frames": pre_roll_frames,
            "sustain_frames": sustain_frames,
            "pre_min_luma": pre_min_luma,
            "carousel_max_luma": carousel_max_luma,
            "control_min_luma": control_min_luma,
            "sustain_seconds": sustain_frames / FPS,
        },
        "boundary_authority": (
            "fixed_three_patch_contract_for_GSC_showCarousel_black_bed_transition"
        ),
        "source_mapping_required": False,
        "final_timeline_mapping_required": True,
    }


def _ffmpeg_command(
    source: Path,
    *,
    source_start_frame: int,
    frame_count: int,
    hardware: str | None,
    ffmpeg: str,
) -> list[str]:
    command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if hardware:
        command.extend(["-hwaccel", hardware])
    command.extend([
        "-ss",
        f"{source_start_frame / FPS:.9f}",
        "-i",
        str(source),
        "-frames:v",
        str(frame_count),
        "-filter_complex",
        (
            f"[0:v]crop={PATCH_SIZE}:{PATCH_SIZE}:0:{HEIGHT - PATCH_SIZE},"
            "scale=1:1:flags=area,format=gray[left];"
            f"[0:v]crop={PATCH_SIZE}:{PATCH_SIZE}:{WIDTH - PATCH_SIZE}:{HEIGHT - PATCH_SIZE},"
            "scale=1:1:flags=area,format=gray[right];"
            f"[0:v]crop={PATCH_SIZE}:{PATCH_SIZE}:{CONTROL_PATCH_X}:{CONTROL_PATCH_Y},"
            "scale=1:1:flags=area,format=gray[control];"
            "[left][right][control]hstack=inputs=3,format=gray[out]"
        ),
        "-map",
        "[out]",
        "-an",
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "pipe:1",
    ])
    return command


def _decode_samples(
    source: Path,
    *,
    source_start_frame: int,
    frame_count: int,
    timeout_seconds: float,
    ffmpeg: str,
) -> tuple[list[tuple[int, int, int]], str]:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise GscCarouselDetectionError(
            "Fixed-pixel carousel scan requires a positive finite timeout."
        )
    deadline = time.monotonic() + timeout_seconds
    failures: list[str] = []
    # CUDA is substantially faster for the OBS AV1 captures.  CPU is a
    # deterministic compatibility fallback; both feed the same fixed pixel
    # reducer and must produce the requested number of samples.
    for hardware in ("cuda", None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GscCarouselDetectionError(
                "Fixed-pixel carousel scan exhausted its shared decode deadline."
            )
        command = _ffmpeg_command(
            source,
            source_start_frame=source_start_frame,
            frame_count=frame_count,
            hardware=hardware,
            ffmpeg=ffmpeg,
        )
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=max(0.001, remaining),
            )
        except subprocess.TimeoutExpired as exc:
            raise GscCarouselDetectionError(
                "Fixed-pixel carousel scan exceeded its workflow deadline."
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            failures.append(f"{hardware or 'cpu'}: {detail}")
            continue
        payload = completed.stdout
        if len(payload) % 3:
            failures.append(
                f"{hardware or 'cpu'}: non-triple raw-pixel byte count {len(payload)}"
            )
            continue
        samples = [
            (payload[index], payload[index + 1], payload[index + 2])
            for index in range(0, len(payload), 3)
        ]
        if len(samples) != frame_count:
            failures.append(
                f"{hardware or 'cpu'}: decoded {len(samples)}/{frame_count} requested frames"
            )
            continue
        return samples, hardware or "cpu"
    raise GscCarouselDetectionError(
        "ffmpeg could not produce the fixed carousel pixel stream: " + " | ".join(failures)
    )


def detect_carousel_source_frame(
    source: Path,
    *,
    source_start_frame: int,
    source_end_frame: int,
    timeout_seconds: float,
    ffmpeg: str = "ffmpeg",
    deadline_check: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Decode and detect a bounded post-battle carousel transition."""

    source = source.resolve()
    if not source.is_file() or source.stat().st_size <= 0:
        raise GscCarouselDetectionError(f"Missing carousel source media: {source}")
    if source_end_frame <= source_start_frame:
        raise GscCarouselDetectionError("Carousel scan has a non-positive source range.")
    frame_count = source_end_frame - source_start_frame
    if frame_count > MAX_SCAN_FRAMES:
        raise GscCarouselDetectionError(
            "Post-battle carousel scan exceeds the fixed 120-second onset search "
            "window plus its two-second sustain proof: "
            f"{frame_count} frames. Exact telemetry is required."
        )
    if deadline_check:
        deadline_check("starting fixed-pixel GSC carousel scan")
    samples, decoder = _decode_samples(
        source,
        source_start_frame=source_start_frame,
        frame_count=frame_count,
        timeout_seconds=timeout_seconds,
        ffmpeg=ffmpeg,
    )
    result = detect_transition_from_luma_samples(
        samples,
        source_start_frame=source_start_frame,
    )
    result["source"] = str(source)
    result["decoder"] = decoder
    if deadline_check:
        deadline_check("completed fixed-pixel GSC carousel scan")
    return result
