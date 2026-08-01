from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from resolve_mcp.orchestrator import gsc_gym_recovery_receipt as receipt
from resolve_mcp.orchestrator import gsc_gym_video_recovery as recovery


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GscGymRecoveryReceiptTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[dict[str, Path], dict]:
        session = root / "session-fixture"
        session.mkdir(parents=True)
        main = root / "main.mp4"
        main.write_bytes(b"immutable-main-source")
        events = session / "events.json"
        events.write_text("[]", encoding="utf-8")
        meta = session / "meta.json"
        capture = session / "vertical.webm"
        capture.write_bytes(b"immutable-finalized-vertical")
        manifest = session / "recording-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema": recovery.VERTICAL_MANIFEST_SCHEMA,
                    "status": "finalized",
                    "session": {
                        "id": session.name,
                        "recordingId": "recording-1",
                        "segmentId": "segment-1",
                    },
                    "correlation": {
                        "linkedLogRefs": {
                            "sessionId": session.name,
                            "metaPath": str(meta),
                            "eventsPath": str(events),
                        }
                    },
                    "canvas": {"width": 1080, "height": 1920, "frameRate": 60},
                    "codec": {"container": "webm"},
                    "durationMs": 100_000,
                    "bytes": capture.stat().st_size,
                    "sha256": _sha256(capture),
                    "output": {"fileName": capture.name, "finalized": True},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        meta.write_text(
            json.dumps(
                {
                    "verticalRecording": {
                        "status": "finalized",
                        "recordingId": "recording-1",
                        "segmentId": "segment-1",
                        "manifestPath": str(manifest),
                        "filePath": str(capture),
                    }
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        raw_runs = (
            recovery.RawStateRun(1, "battle", 100, 200, 0.01, 0.03, 0.20),
            recovery.RawStateRun(2, "battle", 250, 251, 0.01, 0.03, 0.20),
            recovery.RawStateRun(3, "battle", 300, 450, 0.01, 0.03, 0.20),
        )
        semantics = tuple(
            recovery.FixedHeaderSemanticEvidence(
                raw_run_ordinal=ordinal,
                probe_frame=probe,
                title_template_sha256=title_template,
                title_evidence_sha256=f"{ordinal + 10:064x}",
                title_normalized_distance=0.01,
                title_runner_up_distance=0.08,
                attempt=1,
                matched_attempt=1,
                attempt_template_sha256="3" * 64,
                attempt_evidence_sha256=f"{ordinal + 20:064x}",
                attempt_normalized_distance=0.01,
                attempt_runner_up_distance=0.08,
            )
            for ordinal, probe, title_template in (
                (1, 130, "1" * 64),
                (2, 250, "1" * 64),
                (3, 330, "2" * 64),
            )
        )
        proof = recovery.validate_projection_proof(
            (
                recovery.ProjectionAnchor(
                    vertical_frame=1000,
                    main_frame=994,
                    normalized_distance=0.01,
                    runner_up_distance=0.03,
                    vertical_window_sha256="1" * 64,
                    main_window_sha256="2" * 64,
                ),
                recovery.ProjectionAnchor(
                    vertical_frame=2000,
                    main_frame=1994,
                    normalized_distance=0.01,
                    runner_up_distance=0.03,
                    vertical_window_sha256="3" * 64,
                    main_window_sha256="4" * 64,
                ),
                recovery.ProjectionAnchor(
                    vertical_frame=3000,
                    main_frame=2995,
                    normalized_distance=0.01,
                    runner_up_distance=0.03,
                    vertical_window_sha256="5" * 64,
                    main_window_sha256="6" * 64,
                ),
            ),
            residual_tolerance_frames=1,
        )
        payload = {
            "schema": receipt.RECOVERY_RECEIPT_SCHEMA,
            "status": receipt.RECOVERY_RECEIPT_STATUS,
            "fps": 60,
            "no_ocr": True,
            "no_model": True,
            "no_llm": True,
            "main_source": {
                "path": str(main),
                "bytes": main.stat().st_size,
                "mtime_ns": main.stat().st_mtime_ns,
                "frame_count": 5000,
                "sha256": _sha256(main),
            },
            "canonical_logs": {
                "events": {"path": str(events), "sha256": _sha256(events)},
                "meta": {"path": str(meta), "sha256": _sha256(meta)},
            },
            "vertical": {
                "manifest": {
                    "path": str(manifest),
                    "bytes": manifest.stat().st_size,
                    "mtime_ns": manifest.stat().st_mtime_ns,
                    "sha256": _sha256(manifest),
                },
                "capture": {
                    "path": str(capture),
                    "bytes": capture.stat().st_size,
                    "mtime_ns": capture.stat().st_mtime_ns,
                    "sha256": _sha256(capture),
                },
            },
            "raw_battle_resolution": {
                "policy_id": recovery.SEMANTIC_RUN_RESOLUTION_POLICY_ID,
                "raw_runs_sha256": recovery.raw_runs_sha256(raw_runs),
                "raw_battle_runs": [row.__dict__ for row in raw_runs],
                "fixed_header_semantics_sha256": (
                    recovery.fixed_header_semantics_sha256(semantics)
                ),
                "fixed_header_semantics": [row.__dict__ for row in semantics],
                "decisions": [
                    {
                        "raw_run_ordinal": 1,
                        "decision": "retained",
                        "resolved_battle_ordinal": 1,
                        "evidence": "continuous physical Battle state",
                    },
                    {
                        "raw_run_ordinal": 2,
                        "decision": "retained",
                        "resolved_battle_ordinal": 1,
                        "evidence": "same fixed title+attempt after party replacement",
                    },
                    {
                        "raw_run_ordinal": 3,
                        "decision": "retained",
                        "resolved_battle_ordinal": 2,
                        "evidence": "continuous physical Battle state",
                    },
                ],
                "resolved_battles": [
                    {
                        "ordinal": 1,
                        "start_frame": 100,
                        "end_frame": 251,
                        "source_raw_run_ordinals": [1, 2],
                        "identity_probe_frame": 130,
                    },
                    {
                        "ordinal": 2,
                        "start_frame": 300,
                        "end_frame": 450,
                        "source_raw_run_ordinals": [3],
                        "identity_probe_frame": 330,
                    },
                ],
            },
            "projection": {
                "method": recovery.PROJECTION_METHOD,
                "expected_offset_frames": -6,
                "residual_tolerance_frames": 1,
                "proof_sha256": proof.evidence_sha256,
                "anchors": [row.__dict__ for row in proof.anchors],
            },
            "special_identities": [
                {
                    "resolved_battle_ordinal": 1,
                    "vertical_start_frame": 100,
                    "vertical_end_frame": 251,
                    "identity_probe_frame": 130,
                    "display_text": "LEADER FALKNER",
                    "trainer_id": 1,
                    "normalized_distance": 0.02,
                    "runner_up_distance": 0.05,
                    "evidence_sha256": "a" * 64,
                },
                {
                    "resolved_battle_ordinal": 2,
                    "vertical_start_frame": 300,
                    "vertical_end_frame": 450,
                    "identity_probe_frame": 330,
                    "display_text": "RIVAL1",
                    "trainer_id": 8,
                    "normalized_distance": 0.02,
                    "runner_up_distance": 0.05,
                    "evidence_sha256": "b" * 64,
                },
            ],
        }
        receipt_path = root / "recovery-receipt.json"
        receipt_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return {
            "receipt": receipt_path,
            "main": main,
            "events": events,
            "meta": meta,
            "capture": capture,
        }, payload

    def _validate(self, paths: dict[str, Path]) -> dict:
        return receipt.validate_and_map_recovery_receipt(
            paths["receipt"],
            main_source_path=paths["main"],
            events_path=paths["events"],
            meta_path=paths["meta"],
            deadline=recovery.RecoveryDeadline.start(5),
            expected_main_frame_count=5000,
        )

    def test_valid_receipt_maps_ordered_content_bound_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _payload = self._fixture(Path(temporary))
            result = self._validate(paths)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["mode"], receipt.RECOVERY_MODE)
        self.assertEqual(len(result["mapped_attempts"]), 2)
        leader, rival = result["mapped_attempts"]
        self.assertEqual((leader["source_start_frame"], leader["source_end_frame"]), (94, 245))
        self.assertEqual(leader["battle_key"], "FALKNER:1")
        self.assertEqual(rival["battle_key"], "RIVAL1:8")
        self.assertEqual(rival["trainer_id"], 8)
        self.assertEqual(result["source_alignment"]["expected_offset_frames"], -6)
        self.assertEqual(
            result["source_alignment"]["maximum_audited_residual_frames"], 1
        )
        self.assertRegex(result["mapped_attempts_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            result["recovery_binding"]["content_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertTrue(result["recovery_binding"]["no_llm"])
        self.assertFalse(result["recovery_binding"]["synthetic_session_events"])

    def test_main_source_full_hash_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _payload = self._fixture(Path(temporary))
            paths["main"].write_bytes(paths["main"].read_bytes() + b"tamper")
            with self.assertRaisesRegex(
                receipt.GscGymRecoveryReceiptError, "main source SHA-256"
            ):
                self._validate(paths)

    def test_canonical_log_hash_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _payload = self._fixture(Path(temporary))
            paths["events"].write_text("[{}]", encoding="utf-8")
            with self.assertRaisesRegex(
                receipt.GscGymRecoveryReceiptError, "events.json SHA-256"
            ):
                self._validate(paths)

    def test_vertical_manifest_and_capture_linkage_is_revalidated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _payload = self._fixture(Path(temporary))
            paths["capture"].write_bytes(paths["capture"].read_bytes() + b"tamper")
            with self.assertRaises(recovery.GscVideoRecoveryError):
                self._validate(paths)

    def test_every_raw_battle_run_requires_one_explicit_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, payload = self._fixture(Path(temporary))
            altered = copy.deepcopy(payload)
            altered["raw_battle_resolution"]["decisions"][2] = copy.deepcopy(
                altered["raw_battle_resolution"]["decisions"][0]
            )
            paths["receipt"].write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(
                receipt.GscGymRecoveryReceiptError, "duplicate decisions"
            ):
                self._validate(paths)

    def test_retained_decision_must_match_resolved_source_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, payload = self._fixture(Path(temporary))
            altered = copy.deepcopy(payload)
            altered["raw_battle_resolution"]["decisions"][0][
                "resolved_battle_ordinal"
            ] = 2
            paths["receipt"].write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(
                receipt.GscGymRecoveryReceiptError, "not bound"
            ):
                self._validate(paths)

    def test_party_replacement_runs_must_not_be_split_or_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, payload = self._fixture(Path(temporary))
            altered = copy.deepcopy(payload)
            altered["raw_battle_resolution"]["resolved_battles"] = [
                {
                    "ordinal": 1,
                    "start_frame": 100,
                    "end_frame": 200,
                    "source_raw_run_ordinals": [1],
                    "identity_probe_frame": 130,
                },
                {
                    "ordinal": 2,
                    "start_frame": 250,
                    "end_frame": 251,
                    "source_raw_run_ordinals": [2],
                    "identity_probe_frame": 250,
                },
                {
                    "ordinal": 3,
                    "start_frame": 300,
                    "end_frame": 450,
                    "source_raw_run_ordinals": [3],
                    "identity_probe_frame": 330,
                },
            ]
            for decision, battle_ordinal in zip(
                altered["raw_battle_resolution"]["decisions"],
                (1, 2, 3),
            ):
                decision["resolved_battle_ordinal"] = battle_ordinal
            paths["receipt"].write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(
                receipt.GscGymRecoveryReceiptError,
                "semantic groups",
            ):
                self._validate(paths)

    def test_attempt_three_evidence_cannot_be_declared_as_attempt_four(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, payload = self._fixture(Path(temporary))
            altered = copy.deepcopy(payload)
            evidence = altered["raw_battle_resolution"]["fixed_header_semantics"][2]
            evidence["attempt"] = 4
            evidence["matched_attempt"] = 3
            semantics = tuple(
                recovery.FixedHeaderSemanticEvidence(**row)
                for row in altered["raw_battle_resolution"]["fixed_header_semantics"]
            )
            altered["raw_battle_resolution"]["fixed_header_semantics_sha256"] = (
                recovery.fixed_header_semantics_sha256(semantics)
            )
            paths["receipt"].write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(
                receipt.GscGymRecoveryReceiptError,
                "declares 4, matched 3",
            ):
                self._validate(paths)

    def test_obsolete_bounce_policy_requires_receipt_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, payload = self._fixture(Path(temporary))
            altered = copy.deepcopy(payload)
            altered["raw_battle_resolution"]["policy_id"] = (
                "first-fixed-title-attempt-run-only-v1"
            )
            paths["receipt"].write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(
                receipt.GscGymRecoveryReceiptError,
                "obsolete.*regenerate",
            ):
                self._validate(paths)

    def test_projection_must_be_minus_six_with_at_most_one_frame_residual(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, payload = self._fixture(Path(temporary))
            altered = copy.deepcopy(payload)
            altered["projection"]["anchors"][2]["main_frame"] = 2997
            paths["receipt"].write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(
                recovery.GscVideoRecoveryError, "residual/drift"
            ):
                self._validate(paths)

    def test_special_identity_is_finite_range_bound_and_rival_id_positive(self) -> None:
        cases = (
            ("display_text", "TRAINER YOUNGSTER", "finite KOMIKAX"),
            ("vertical_start_frame", 101, "range/probe-bound"),
            ("trainer_id", 0, "at least 1"),
        )
        for key, value, message in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                paths, payload = self._fixture(Path(temporary))
                altered = copy.deepcopy(payload)
                altered["special_identities"][1][key] = value
                paths["receipt"].write_text(json.dumps(altered), encoding="utf-8")
                with self.assertRaisesRegex(receipt.GscGymRecoveryReceiptError, message):
                    self._validate(paths)

    def test_declared_mapped_content_hash_is_checked_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, payload = self._fixture(Path(temporary))
            altered = copy.deepcopy(payload)
            altered["mapped_attempts_sha256"] = "0" * 64
            paths["receipt"].write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(
                receipt.GscGymRecoveryReceiptError, "mapped_attempts_sha256 is stale"
            ):
                self._validate(paths)

    def test_schema_status_and_no_llm_flags_are_exact(self) -> None:
        cases = (
            ("schema", "v2", "schema"),
            ("status", "draft", "status"),
            ("no_llm", False, "no_llm"),
        )
        for key, value, message in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                paths, payload = self._fixture(Path(temporary))
                altered = copy.deepcopy(payload)
                altered[key] = value
                paths["receipt"].write_text(json.dumps(altered), encoding="utf-8")
                with self.assertRaisesRegex(receipt.GscGymRecoveryReceiptError, message):
                    self._validate(paths)


if __name__ == "__main__":
    unittest.main()
