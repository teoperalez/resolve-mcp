from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from scripts import run_gsc_gym_deterministic_workflow as runner


class GscGymRunnerTests(unittest.TestCase):
    @staticmethod
    def _event(frame: int, category: str, name: str, data: dict | None = None) -> dict:
        return {
            "tElapsedMs": frame * 1000 / 60,
            "category": category,
            "name": name,
            "data": data or {},
        }

    def test_reference_contract_enforces_exact_six_gen2_battle_tracks(self) -> None:
        battle_dir = Path("F:/Programming/GSCNewLayout/audio/Gen 2 battle audio")
        contract = Path("config/gsc_gym_leader_reference_contract.json")
        if not battle_dir.is_dir() or not contract.is_file():
            self.skipTest("Installed GSC battle library/reference contract is unavailable.")
        library, names = runner._contracted_battle_library(battle_dir, contract)
        self.assertEqual(len(library), 6)
        self.assertEqual({path.name for path in library}, set(names))

        scratch = Path("F:/CodexTemp")
        scratch.mkdir(parents=True, exist_ok=True)
        expected = json.loads(contract.read_text(encoding="utf-8"))["strict_invariants"][
            "battle_bgm_tracks"
        ]
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            isolated = Path(temporary)
            for name in expected:
                (isolated / name).write_bytes(b"fixture")
            (isolated / "unexpected seventh track.mp3").write_bytes(b"fixture")
            with self.assertRaisesRegex(runner.GscGymDeterministicError, "unexpected"):
                runner._contracted_battle_library(isolated, contract)

    def test_approved_gsc_asset_timecodes_and_video_frame_durations(self) -> None:
        assets = (
            (
                Path("C:/Users/Teo/.resolve-mcp/cache/retimed-intros/GSCPC Intro Short__400pct.mp4"),
                30,
                130,
                260,
                220_134,
            ),
            (
                Path("F:/Programming/GSCNewLayout/GSCPC Intro Short.mp4"),
                30,
                512,
                1_024,
                220_134,
            ),
            (
                Path("F:/GSC Assets/GSC Assets outro.mov"),
                60,
                1_203,
                1_203,
                432_034,
            ),
        )
        if not all(path.is_file() for path, *_expected in assets):
            self.skipTest("Approved local GSC structural assets are not installed.")
        deadline = runner._Deadline(30)
        for path, fps, native_frames, timeline_frames, source_start in assets:
            with self.subTest(path=path.name):
                probe = runner._probe_media(path, deadline)
                self.assertEqual(probe["video_native_fps"], fps)
                self.assertEqual(probe["video_source_frames"], native_frames)
                self.assertEqual(probe["timeline_frames_at_60fps"], timeline_frames)
                self.assertEqual(probe["media_start_frame_at_60fps"], source_start)
                self.assertTrue(runner._is_exact_4k(probe))

    def test_result_json_is_f_drive_json_and_cannot_alias_input(self) -> None:
        source = Path("F:/CodexTemp/example/source.json")
        with self.assertRaisesRegex(runner.GscGymDeterministicError, "alias"):
            runner._validate_result_path(source, [source])
        with self.assertRaisesRegex(runner.GscGymDeterministicError, r"\.json"):
            runner._validate_result_path(Path("F:/CodexTemp/result.txt"), [source])
        self.assertEqual(
            runner._validate_result_path(Path("F:/CodexTemp/result.json"), [source]),
            Path("F:/CodexTemp/result.json").resolve(),
        )
        scratch_root = Path("F:/CodexTemp")
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(suffix=".json", dir=scratch_root) as directory:
            with self.assertRaisesRegex(runner.GscGymDeterministicError, "not a directory"):
                runner._validate_result_path(Path(directory), [source])

    def test_generated_artifact_alias_never_receives_failure_json(self) -> None:
        generated_plan = Path("F:/CodexTemp/gsc-gym-alias-test/plan.json")
        argv = [
            str(Path(runner.__file__).resolve()),
            "build-offline",
            "--source",
            "F:/CodexTemp/source.mp4",
            "--result-json",
            str(generated_plan),
            "--_worker",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(
                runner,
                "build_offline",
                side_effect=runner._UnsafeResultPathError("generated artifact alias"),
            ),
            patch.object(runner, "_atomic_json") as atomic_json,
        ):
            self.assertEqual(runner.main(), 2)
        atomic_json.assert_not_called()

    def test_full_cli_uses_default_600_second_outer_watchdog(self) -> None:
        argv = [
            str(Path(runner.__file__).resolve()),
            "full",
            "--source",
            "F:/CodexTemp/source.mp4",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(runner, "_watchdog", return_value=0) as watchdog,
        ):
            self.assertEqual(runner.main(), 0)
        watchdog.assert_called_once_with(argv[1:], 600.0)

    def test_full_worker_dispatches_to_one_combined_entrypoint(self) -> None:
        argv = [
            str(Path(runner.__file__).resolve()),
            "full",
            "--source",
            "F:/CodexTemp/source.mp4",
            "--resolve-project",
            "Erika Crystal",
            "--_worker",
        ]
        result = {"status": "pass", "artifacts": {}}
        with (
            patch.object(sys, "argv", argv),
            patch.object(runner, "execute_resolve_dry_run", return_value=result) as full,
            patch.object(runner, "build_offline") as offline,
            patch("builtins.print"),
        ):
            self.assertEqual(runner.main(), 0)
        full.assert_called_once()
        offline.assert_not_called()

    def test_video_receipt_is_selected_only_for_typed_incomplete_telemetry(self) -> None:
        scratch_root = Path("F:/CodexTemp")
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch_root) as temporary:
            root = Path(temporary)
            source = root / "recording.mp4"
            source.write_bytes(b"fixture")
            receipt = root / "recovery.json"
            receipt.write_text("{}", encoding="utf-8")
            incomplete = [
                self._event(
                    60,
                    "state",
                    "mapper-state",
                    {"from": "Overworld", "to": "To Battle"},
                ),
                self._event(
                    61,
                    "battle",
                    "battle-start",
                    {"trainerClass": "FALKNER", "trainerId": 1},
                ),
            ]
            selected = runner._battle_telemetry_intake(
                events=incomplete,
                source=source,
                requested_recovery_receipt=receipt,
            )
            self.assertEqual(
                selected["mode"], "content_bound_video_recovery_receipt_pending"
            )
            self.assertEqual(selected["receipt_path"], receipt.resolve())

            with self.assertRaisesRegex(
                runner.GscGymDeterministicError, "allowed only when canonical parsing"
            ):
                runner._battle_telemetry_intake(
                    events=[],
                    source=source,
                    requested_recovery_receipt=receipt,
                )

    def test_recovery_receipt_is_part_of_immutable_input_snapshot(self) -> None:
        scratch_root = Path("F:/CodexTemp")
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch_root) as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            events = root / "events.json"
            meta = root / "meta.json"
            receipt = root / "receipt.json"
            for path, payload in (
                (source, b"source"),
                (events, b"[]"),
                (meta, b"{}"),
                (receipt, b'{"status":"pass"}'),
            ):
                path.write_bytes(payload)
            deadline = runner._Deadline(10)
            snapshot = runner._input_snapshot(
                source,
                events,
                meta,
                deadline,
                supplemental_inputs={"video_recovery_receipt": receipt},
            )
            self.assertIn("video_recovery_receipt", snapshot)
            receipt.write_bytes(b'{"status":"changed"}')
            with self.assertRaisesRegex(
                runner.GscGymDeterministicError, "mixed/active run"
            ):
                runner._require_unchanged_inputs(
                    snapshot,
                    source,
                    events,
                    meta,
                    deadline,
                    activity="fixture revalidation",
                    supplemental_inputs={"video_recovery_receipt": receipt},
                )

    def test_exact_rate_and_non_drop_timecode_contracts(self) -> None:
        exact = {
            "video_avg_frame_rate_fraction": "60/1",
            "video_r_frame_rate_fraction": "60/1",
        }
        ntsc = {
            "video_avg_frame_rate_fraction": "60000/1001",
            "video_r_frame_rate_fraction": "60000/1001",
        }
        self.assertTrue(runner._has_exact_video_rate(exact, 60))
        self.assertFalse(runner._has_exact_video_rate(ntsc, 60))
        with self.assertRaisesRegex(runner.GscGymDeterministicError, "non-drop"):
            runner._timecode_at_60fps("00:00:00;00", 60)

    def test_cached_artifact_evidence_detects_tampering(self) -> None:
        scratch_root = Path("F:/CodexTemp")
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch_root) as temporary_dir:
            artifact = Path(temporary_dir) / "dialogue.wav"
            artifact.write_bytes(b"first deterministic payload")
            deadline = runner._Deadline(10)
            evidence = runner._asset_evidence(artifact, deadline)
            runner._verify_asset_evidence([evidence], deadline)
            artifact.write_bytes(b"tampered payload")
            with self.assertRaisesRegex(
                runner.GscGymDeterministicError, "changed before Resolve import"
            ):
                runner._verify_asset_evidence([evidence], deadline)

    def test_watchdog_kills_only_its_worker_tree_on_timeout(self) -> None:
        process = MagicMock()
        process.pid = 43210
        process.wait.side_effect = [subprocess.TimeoutExpired("worker", 1), 0]
        process.poll.return_value = None
        killed = MagicMock(returncode=0)
        with (
            patch.object(runner.subprocess, "Popen", return_value=process),
            patch.object(runner.subprocess, "run", return_value=killed) as run,
        ):
            code = runner._watchdog(["build-offline", "--source", "x"], 10)
        self.assertEqual(code, 124)
        self.assertEqual(
            run.call_args.args[0],
            ["taskkill.exe", "/PID", "43210", "/T", "/F"],
        )
        process.kill.assert_not_called()

    def test_external_timeout_terminates_only_owned_process_tree(self) -> None:
        process = MagicMock()
        process.communicate.side_effect = subprocess.TimeoutExpired("ffmpeg", 1)
        with (
            patch.object(runner.subprocess, "Popen", return_value=process),
            patch.object(runner, "_terminate_owned_process_tree") as terminate,
        ):
            with self.assertRaisesRegex(runner.GscGymDeterministicError, "deadline"):
                runner._run_external(
                    ["ffmpeg", "-version"],
                    deadline=runner._Deadline(10),
                    activity="testing owned subprocess timeout",
                )
        terminate.assert_called_once_with(process, ends=ANY)

    def test_file_uri_binding_is_exact_and_percent_decoded(self) -> None:
        actual = runner._source_path_from_uri("file:///F:/Run%20Folder/source.mp4")
        self.assertEqual(actual, Path("F:/Run Folder/source.mp4").resolve())
        with self.assertRaisesRegex(runner.GscGymDeterministicError, "not local"):
            runner._source_path_from_uri("https://example.test/source.mp4")


if __name__ == "__main__":
    unittest.main()
