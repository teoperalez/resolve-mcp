from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from resolve_mcp.orchestrator import gsc_gym_carousel_detector as detector
from resolve_mcp.orchestrator.gsc_gym_carousel_detector import (
    GscCarouselDetectionError,
    detect_transition_from_luma_samples,
)


class GscGymCarouselDetectorTests(unittest.TestCase):
    def test_selects_exact_first_dark_frame(self) -> None:
        samples = [(120, 130, 100)] * 10 + [(3, 2, 100)] * 130
        result = detect_transition_from_luma_samples(samples, source_start_frame=1000)
        self.assertEqual(result["source_frame"], 1010)
        self.assertEqual(result["candidate_source_frames"], [1010])
        self.assertEqual(result["fixed_contract"]["sustain_frames"], 120)

    def test_selects_final_cycle_when_multiple_are_complete(self) -> None:
        samples = (
            [(100, 100, 100)] * 8
            + [(0, 0, 100)] * 125
            + [(90, 90, 100)] * 8
            + [(0, 0, 100)] * 125
        )
        result = detect_transition_from_luma_samples(samples, source_start_frame=200)
        self.assertEqual(result["candidate_source_frames"], [208, 341])
        self.assertEqual(result["source_frame"], 341)

    def test_one_dark_corner_or_short_flash_fails_closed(self) -> None:
        with self.assertRaises(GscCarouselDetectionError):
            detect_transition_from_luma_samples(
                [(100, 100, 100)] * 10 + [(0, 100, 100)] * 130,
                source_start_frame=0,
            )
        with self.assertRaises(GscCarouselDetectionError):
            detect_transition_from_luma_samples(
                [(100, 100, 100)] * 10
                + [(0, 0, 100)] * 5
                + [(100, 100, 100)] * 125,
                source_start_frame=0,
            )

    def test_full_frame_black_transition_fails_closed(self) -> None:
        with self.assertRaises(GscCarouselDetectionError):
            detect_transition_from_luma_samples(
                [(100, 100, 100)] * 10 + [(0, 0, 0)] * 130,
                source_start_frame=0,
            )

    def test_preserved_surge_window_keeps_exact_onset(self) -> None:
        samples = (
            [(133, 113, 143)] * 17
            + [(3, 2, 143)]
            + [(0, 0, 133)] * 123
        )
        result = detect_transition_from_luma_samples(
            samples,
            source_start_frame=299940,
        )
        self.assertEqual(result["source_frame"], 299957)

    def test_two_minute_onset_window_includes_required_sustain_proof(self) -> None:
        samples = (
            [(100, 100, 100)] * detector.MAX_ONSET_SEARCH_FRAMES
            + [(0, 0, 100)] * detector.SUSTAIN_FRAMES
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"immutable source placeholder")
            with mock.patch.object(
                detector,
                "_decode_samples",
                return_value=(samples, "test"),
            ) as decode:
                result = detector.detect_carousel_source_frame(
                    source,
                    source_start_frame=1_000,
                    source_end_frame=1_000 + detector.MAX_SCAN_FRAMES,
                    timeout_seconds=10.0,
                )

        self.assertEqual(
            detector.MAX_SCAN_FRAMES,
            detector.MAX_ONSET_SEARCH_FRAMES + detector.SUSTAIN_FRAMES,
        )
        self.assertEqual(
            result["source_frame"],
            1_000 + detector.MAX_ONSET_SEARCH_FRAMES,
        )
        decode.assert_called_once()

    def test_scan_beyond_onset_window_and_proof_fails_before_decode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"immutable source placeholder")
            with mock.patch.object(detector, "_decode_samples") as decode:
                with self.assertRaisesRegex(
                    GscCarouselDetectionError,
                    "120-second onset search window plus its two-second sustain proof",
                ):
                    detector.detect_carousel_source_frame(
                        source,
                        source_start_frame=0,
                        source_end_frame=detector.MAX_SCAN_FRAMES + 1,
                        timeout_seconds=10.0,
                    )
        decode.assert_not_called()

    def test_cuda_and_cpu_share_one_absolute_timeout(self) -> None:
        failed_cuda = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=b"",
            stderr=b"cuda failed",
        )
        successful_cpu = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=bytes((1, 2, 100)),
            stderr=b"",
        )
        with (
            mock.patch.object(detector.time, "monotonic", side_effect=(100.0, 100.0, 104.0)),
            mock.patch.object(
                detector.subprocess,
                "run",
                side_effect=(failed_cuda, successful_cpu),
            ) as run,
        ):
            samples, decoder = detector._decode_samples(
                Path("source.mp4"),
                source_start_frame=0,
                frame_count=1,
                timeout_seconds=10.0,
                ffmpeg="ffmpeg",
            )
        self.assertEqual(samples, [(1, 2, 100)])
        self.assertEqual(decoder, "cpu")
        self.assertAlmostEqual(run.call_args_list[0].kwargs["timeout"], 10.0)
        self.assertAlmostEqual(run.call_args_list[1].kwargs["timeout"], 6.0)


if __name__ == "__main__":
    unittest.main()
