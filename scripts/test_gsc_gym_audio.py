from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from resolve_mcp.orchestrator.gsc_gym_audio import (
    GscGymAudioError,
    SOURCE_CLIP_SCHEMA,
    build_source_a2_contract,
)
from resolve_mcp.orchestrator.gsc_gym_bgm import PlannedBgmSlice
from resolve_mcp.orchestrator.gsc_gym_fcpxml import MediaAsset


class GscGymAudioTests(unittest.TestCase):
    def test_original_mp3_identity_duration_source_range_and_handles_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "Dual Screen Lovelife.mp3"
            source.write_bytes(b"original-library-audio")
            asset = MediaAsset(
                source,
                source.name,
                duration_frames=1_000,
                source_start_frame=10,
            )
            row = PlannedBgmSlice(
                100,
                20,
                120,
                asset,
                "opening",
                "opening bed",
                fade_out_frames=30,
            )

            result = build_source_a2_contract((row,))

            segment = result.segments[0]
            self.assertEqual(segment.asset, asset)
            self.assertEqual(Path(segment.asset.path), source)
            self.assertEqual(segment.asset.name, source.name)
            self.assertEqual(segment.asset.duration_frames, 1_000)
            self.assertEqual(segment.asset.source_start_frame, 10)
            self.assertEqual(segment.source_start_frame, 20)
            self.assertEqual(segment.duration_frames, 120)
            self.assertEqual(segment.gain_db, -8.4)
            self.assertEqual(segment.fade_out_frames, 30)
            self.assertFalse((Path(temp) / "a2-fades").exists())

            clip = result.clips[0]
            self.assertEqual(clip["schema"], SOURCE_CLIP_SCHEMA)
            self.assertEqual(clip["source_path"], str(source.resolve()))
            self.assertEqual(clip["source_name"], source.name)
            self.assertEqual(clip["source_range"], [20, 140])
            self.assertEqual(clip["media_source_start_frame"], 10)
            self.assertEqual(clip["media_duration_frames"], 1_000)
            self.assertEqual(clip["available_handle_frames"], {"left": 10, "right": 870})
            self.assertTrue(clip["source_trim_handles_editable"])
            self.assertFalse(clip["derived_media"])
            self.assertEqual(
                clip["source_sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest().upper(),
            )
            self.assertEqual(
                clip["gain_policy"], "editable_timeline_adjust_volume_not_baked"
            )
            self.assertEqual(
                clip["fade_policy"], "editable_timeline_metadata_not_baked"
            )

    def test_renamed_wav_and_a2_fades_derivatives_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "Aura.mp3"
            original.write_bytes(b"original")

            renamed = root / "Aura__s0_d60.wav"
            renamed.write_bytes(b"derived")
            renamed_asset = MediaAsset(
                renamed,
                renamed.name,
                60,
                origin_path=original,
            )
            with self.assertRaisesRegex(GscGymAudioError, "renamed derivative"):
                build_source_a2_contract(
                    (PlannedBgmSlice(0, 0, 60, renamed_asset, "nonbattle", "bed"),)
                )

            fade_dir = root / "a2-fades"
            fade_dir.mkdir()
            fade_source = fade_dir / "Aura.mp3"
            fade_source.write_bytes(b"copied")
            fade_asset = MediaAsset(fade_source, fade_source.name, 60)
            with self.assertRaisesRegex(GscGymAudioError, "outside a2-fades"):
                build_source_a2_contract(
                    (PlannedBgmSlice(0, 0, 60, fade_asset, "nonbattle", "bed"),)
                )

            wrong_name = MediaAsset(original, "renamed.mp3", 60)
            with self.assertRaisesRegex(GscGymAudioError, "original filename"):
                build_source_a2_contract(
                    (PlannedBgmSlice(0, 0, 60, wrong_name, "nonbattle", "bed"),)
                )

    def test_source_overrun_and_nonfinite_gain_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "Aura.mp3"
            source.write_bytes(b"audio")
            asset = MediaAsset(source, source.name, 100)
            with self.assertRaisesRegex(GscGymAudioError, "exceeds original media bounds"):
                build_source_a2_contract(
                    (PlannedBgmSlice(0, 50, 60, asset, "nonbattle", "bed"),)
                )
            with self.assertRaisesRegex(GscGymAudioError, "No finite gain"):
                build_source_a2_contract(
                    (PlannedBgmSlice(0, 0, 60, asset, "nonbattle", "bed"),),
                    gains_db={"nonbattle": float("nan")},
                )


if __name__ == "__main__":
    unittest.main()
