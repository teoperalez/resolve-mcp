from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from resolve_mcp.orchestrator import gsc_gym_video_recovery as recovery


_RECORDED_TITLE_MASKS_B85 = {
    # Tight dark masks from the finalized Erika vertical recording.  These are
    # image fixtures, not transcribed/OCR input.  BUGSY and CHUCK are the two
    # closed-atlas confusers that exact FreeType/Skia pixel overlap reversed.
    "LEADER BUGSY": (
        242,
        29,
        "c-pO*(Q*VK2n6B(e>zE3s^aSO4CZ#<&gIlbKwzuBpYDREe;)Ij2kD&?{u2l?tE3qeYsY_Xug)PUhHp?<{O4EXAsRNb4a%3R6fMknJrUfOLFAUxiFr?Ht!DjF+0hIH_o&BlQU>nB08!i8Mu^xd3PH>!XT+U}d)u5*Hcp|`m5J+9V&X}}O~l3=(s_B}5LVh+B83JKIL=ia@pFOm*tN-v$<zJ7WaMLb=Q!f0)9Fo1M?Vjd_C&-QScJUnCoCEy^fAfMW-KHfNPkKkkJz2@;CfTG1&4T?`USCYoPQH{BDR4GJj6LX`rjpSUlW@JbmX%}{mfgP1(#QNI)N#1I>5FX6;nYjb*jN9D(!R30ddh8OSN7kAi>nvKTA=7aml!r0%Cg`9#J+ElWnBSb1OMq?)46_x1@O;f$oo~#J=M<i0d`t%9T?j#x+bTHz^gPlLe#hNufyPi@k9!k-3r3-LYUkiQC4e$UCs2Ostv5#JP|wP;V+iro=w02rU`rA)V9}G1u@M8gh;aS%nWnpoF?2Zda_It01v!+S$vSiPz156>H-43VVzw&!#M0dLie&MBJ$qEWD$wy-dq|p{3Nh!dUNGv*)BKhM_f-FU3=P#+b#dk-0Ug$9+9hJlGtxQ(=mCAh&&8rU934>IU$YJ+Pv-E$0-Lut)1%&P-X*bhgOzF9k_Cx%of?`a?=;mza+U^Up6{s}+)`{Ml#rtlO{Gp1ZA$NuFX~b{Y>J",
    ),
    "LEADER CHUCK": (
        243,
        29,
        "c-p<0(RRcj2t?ukf4c3%_9QxY7&qJcv|%-H1rbfvck3=_{nN}d3+X@CIe1wOt?%R40k7v)YWmWI(00Rrurn&S^?d!Y332?Q>i20gqL)S#opfB)IOf(GRu@X4F>nu|$>1i78hR=@zO-<vSJQqU);Q2E*vUv9lIV_|Blko+AumETUfLfa*HdKK6|+Ze!|o<4U1~hdm_;^D0OY$|4i?D+OnMJ_UG%~zG|$FeLD<0yREUw20a?bi_NW+c)0%g})!v3Y!pKI0G)d0sJIL&+*~tgU=;RuRJ+e({S80h<QU}QULP6v(u1DmfrK}dtHXl<VG9vdevQZ%3brRRgmIC5%DXWTTKqer$AE>J50dg&<!<4(iOCc9|*;WBOrGBQ8EIt&@yzVFz0GY}T>5M~U+|~V7@9XA|A(unuYBMPX=D3cCkC5wQ$o2ooMpt%D=yi9+aymOVTHk*nuAQ##9uLqva@zzo9+dwaxdLRbc|}I&KSFMCIC}2o!0iFDxyi7rDnjNA;!50S$gPp-u!zW&u4OTKeS&-+t`oM_vnMZ60Pl<UCNHj;Q-@Z;PY5kKHK*r(c~R<bvoPcHDGlf{WI3qkn#pW2dM#x4pjU(3$<$nAz?2L(1vq!^Qc<i~xF_^iXX|xxNBa>5JL$Drr!bUrAY;((d)mt(v&IZRD+sMqm8}H&8_INnVm>J(pDIdZ@xlYB_I&tVXm0$~=UIDbSv33$M<fp6",
    ),
    "SWIMMER F": (
        194,
        29,
        "c-qaF%Z@`a2t&>P|MW<scGQ4voZHQ0Q#B952?WRm-mQKcwzkiJ6+;Kd)`2cv-}-B>KW5$M48ncNVXA%fRUJF`KCQYFRL&f22HC1e<0nOD$(2gF-ZeS^GTDkM*VuSSP?o@G06zO6LFpr22+9&T)LVjkfR3;b^!qTb-cC?4f%iZa9sT9PM$k8(0?XQy)5}QZ2xO<T4~F8G1j1!#Abvu?LoFp>PE_8{HGx(yC8(HSp57HfJ#r#WfS4e6qH@XNj==cKcLc^5G#J7Tnv%l+tOSsuCL!Rz@C4j%vUDJA2QUKdP95BU6r@c^q}WojiU7TSQv_h7(iEd=OsbouEGr$M2mvzzXj*Ut99pLQlmMIwUlA;L0YUyYkhw$zeH&FV3E&BYdhTIHNA+PS0tg)q0a+psID1+qc>${aJml%j?Fm8`aoGUVb@-WH5-<xPA_zQ1nq?)xMleUguYQ|$%3VW|?#u|-6C@#^D`r99?rZpV*7sTyK<W610REjHWr;FH);$3v%dCB!zaUC<d!3s+WYu>!^`f31>dFh(4AFD%*i(Jh<D>4FNugkt2d$+W{L}UWlFkg8",
    ),
}


class GscGymVideoRecoveryTests(unittest.TestCase):
    def _calibration(self) -> recovery.ModeCalibration:
        overworld = bytes([20]) * recovery.MODE_SAMPLE_BYTES
        battle = bytes([230]) * recovery.MODE_SAMPLE_BYTES
        samples = {
            **{frame: overworld for frame in range(0, 3)},
            **{frame: battle for frame in range(10, 13)},
        }
        return recovery.calibrate_mode_templates(
            samples,
            overworld_window=recovery.FrameWindow(0, 3, "exact mapper Overworld window"),
            battle_window=recovery.FrameWindow(10, 13, "exact first battle window"),
        )

    def _raw_runs(self) -> tuple[recovery.RawStateRun, ...]:
        calibration = self._calibration()
        overworld = bytes([20]) * recovery.MODE_SAMPLE_BYTES
        battle = bytes([230]) * recovery.MODE_SAMPLE_BYTES
        return recovery.raw_runs_from_samples(
            [(100, overworld), (101, battle), (102, battle), (103, overworld)],
            calibration=calibration,
        )

    def _proof(self) -> recovery.ProjectionProof:
        return recovery.validate_projection_proof(
            [
                recovery.ProjectionAnchor(
                    vertical_frame=1000 + index * 1000,
                    main_frame=994 + index * 1000,
                    normalized_distance=0.02,
                    runner_up_distance=0.08,
                    vertical_window_sha256=f"{index + 1:064x}",
                    main_window_sha256=f"{index + 11:064x}",
                )
                for index in range(3)
            ]
        )

    def _semantic(
        self,
        *,
        raw_run_ordinal: int = 2,
        probe_frame: int = 102,
        title_template: str = "a" * 64,
        attempt: int = 1,
        matched_attempt: int | None = None,
    ) -> recovery.FixedHeaderSemanticEvidence:
        matched = attempt if matched_attempt is None else matched_attempt
        return recovery.FixedHeaderSemanticEvidence(
            raw_run_ordinal=raw_run_ordinal,
            probe_frame=probe_frame,
            title_template_sha256=title_template,
            title_evidence_sha256=f"{raw_run_ordinal + 20:064x}",
            title_normalized_distance=0.01,
            title_runner_up_distance=0.08,
            attempt=attempt,
            matched_attempt=matched,
            attempt_template_sha256=f"{matched + 40:064x}",
            attempt_evidence_sha256=f"{raw_run_ordinal + 60:064x}",
            attempt_normalized_distance=0.01,
            attempt_runner_up_distance=0.08,
        )

    def test_finalized_vertical_manifest_linkage_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "session-123"
            session.mkdir()
            capture = session / "vertical.webm"
            capture.write_bytes(b"finalized-webm")
            events = session / "events.json"
            events.write_text("[]", encoding="utf-8")
            meta_path = session / "meta.json"
            manifest_path = session / "recording-manifest.json"
            digest = hashlib.sha256(capture.read_bytes()).hexdigest()
            manifest = {
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
                        "metaPath": str(meta_path),
                        "eventsPath": str(events),
                    }
                },
                "canvas": {"width": 1080, "height": 1920, "frameRate": 60},
                "codec": {"container": "webm"},
                "durationMs": 1000,
                "bytes": capture.stat().st_size,
                "sha256": digest,
                "output": {"fileName": capture.name, "finalized": True},
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            meta_path.write_text(
                json.dumps(
                    {
                        "verticalRecording": {
                            "status": "finalized",
                            "recordingId": "recording-1",
                            "segmentId": "segment-1",
                            "manifestPath": str(manifest_path),
                            "filePath": str(capture),
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = recovery.validate_finalized_vertical_linkage(
                meta_path,
                events_path=events,
                deadline=recovery.RecoveryDeadline.start(5),
            )
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["sha256"], digest)
            self.assertEqual(result["declared_frames_at_60fps"], 60)

            manifest["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(recovery.GscVideoRecoveryError, "SHA-256"):
                recovery.validate_finalized_vertical_linkage(
                    meta_path,
                    events_path=events,
                    deadline=recovery.RecoveryDeadline.start(5),
                )

    def test_authoritative_templates_classify_and_preserve_exact_raw_runs(self) -> None:
        calibration = self._calibration()
        self.assertEqual(
            recovery.classify_mode_sample(
                bytes([20]) * recovery.MODE_SAMPLE_BYTES, calibration
            )[0],
            "overworld",
        )
        runs = self._raw_runs()
        self.assertEqual(
            [(row.state, row.start_frame, row.end_frame) for row in runs],
            [("overworld", 100, 101), ("battle", 101, 103), ("overworld", 103, 104)],
        )

    def test_mode_scan_command_is_exact_60fps_fixed_chip_and_has_no_seek(self) -> None:
        command = recovery.mode_scan_ffmpeg_command(Path("vertical.webm"), end_frame=600)
        rendered = " ".join(command)
        self.assertIn("fps=fps=60:round=near", rendered)
        self.assertIn("crop=154:56:852:60", rendered)
        self.assertIn("scale=38:14:flags=area", rendered)
        self.assertNotIn(" -ss ", f" {rendered} ")
        self.assertEqual(command[command.index("-frames:v") + 1], "600")

    def test_header_title_extraction_is_sparse_fixed_geometry_and_deadline_bound(self) -> None:
        command = recovery.header_title_ffmpeg_command(
            Path("vertical.webm"), probe_frames=[120, 4]
        )
        rendered = " ".join(command)
        self.assertIn("fps=fps=60:round=near", rendered)
        self.assertIn("select=eq(n\\,4)+eq(n\\,120)", rendered)
        self.assertIn("crop=470:42:70:48", rendered)
        self.assertIn("format=gray", rendered)
        self.assertNotIn(" -ss ", f" {rendered} ")
        self.assertEqual(command[command.index("-frames:v") + 1], "2")

        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary) / "vertical.webm"
            capture.write_bytes(b"fixture")
            first = bytes([1]) * (
                recovery.HEADER_TITLE_WIDTH * recovery.HEADER_TITLE_HEIGHT
            )
            second = bytes([2]) * (
                recovery.HEADER_TITLE_WIDTH * recovery.HEADER_TITLE_HEIGHT
            )
            with mock.patch.object(
                recovery,
                "_stream_fixed_frames",
                return_value=iter(((0, first), (1, second))),
            ) as stream:
                result = recovery.extract_header_title_frames(
                    capture,
                    probe_frames=[120, 4],
                    deadline=recovery.RecoveryDeadline.start(5),
                )
            self.assertEqual(result, {4: first, 120: second})
            self.assertIsInstance(stream.call_args.kwargs["deadline"], recovery.RecoveryDeadline)

    def test_mode_recovery_may_start_before_calibration_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary) / "vertical.webm"
            capture.write_bytes(b"fixture")
            samples = [
                (frame, bytes([230 if 10 <= frame < 13 else 20]) * recovery.MODE_SAMPLE_BYTES)
                for frame in range(15)
            ]
            with mock.patch.object(
                recovery,
                "_stream_fixed_frames",
                return_value=iter(samples),
            ):
                result = recovery.scan_vertical_mode_runs(
                    capture,
                    overworld_window=recovery.FrameWindow(0, 3, "logged Overworld"),
                    battle_window=recovery.FrameWindow(10, 13, "logged Battle"),
                    recovery_start_frame=0,
                    scan_end_frame=15,
                    deadline=recovery.RecoveryDeadline.start(5),
                )
            self.assertEqual(result["scan_start_frame"], 0)
            self.assertEqual(
                [
                    (row["state"], row["start_frame"], row["end_frame"])
                    for row in result["raw_runs"]
                ],
                [("overworld", 0, 10), ("battle", 10, 13), ("overworld", 13, 15)],
            )
            with self.assertRaisesRegex(recovery.GscVideoRecoveryError, "contained"):
                recovery.scan_vertical_mode_runs(
                    capture,
                    overworld_window=recovery.FrameWindow(0, 3, "logged Overworld"),
                    battle_window=recovery.FrameWindow(10, 13, "logged Battle"),
                    recovery_start_frame=0,
                    scan_end_frame=12,
                    deadline=recovery.RecoveryDeadline.start(5),
                )

    def test_no_implicit_bounce_filter_and_receipt_must_cover_every_battle(self) -> None:
        runs = self._raw_runs()
        with self.assertRaisesRegex(recovery.GscVideoRecoveryError, "no implicit bounce filter"):
            recovery.validate_run_resolution(runs, None)
        stale = recovery.RunResolution(
            policy_id="fixture-identity-v1",
            raw_runs_sha256="0" * 64,
            battles=(),
        )
        with self.assertRaisesRegex(recovery.GscVideoRecoveryError, "stale"):
            recovery.validate_run_resolution(runs, stale)
        receipt = recovery.RunResolution(
            policy_id=recovery.SEMANTIC_RUN_RESOLUTION_POLICY_ID,
            raw_runs_sha256=recovery.raw_runs_sha256(runs),
            battles=(
                recovery.ResolvedBattleRun(
                    ordinal=1,
                    start_frame=101,
                    end_frame=103,
                    source_raw_run_ordinals=(2,),
                    identity_probe_frame=102,
                ),
            ),
            fixed_header_semantics=(self._semantic(),),
        )
        self.assertEqual(recovery.validate_run_resolution(runs, receipt), receipt.battles)

    def test_same_fixed_header_attempt_merges_party_replacement_runs(self) -> None:
        runs = (
            recovery.RawStateRun(1, "battle", 100, 200, 0.01, 0.03, 0.20),
            recovery.RawStateRun(2, "battle", 250, 310, 0.01, 0.03, 0.20),
        )
        semantics = (
            self._semantic(raw_run_ordinal=1, probe_frame=130),
            self._semantic(raw_run_ordinal=2, probe_frame=280),
        )
        merged = recovery.RunResolution(
            policy_id=recovery.SEMANTIC_RUN_RESOLUTION_POLICY_ID,
            raw_runs_sha256=recovery.raw_runs_sha256(runs),
            battles=(recovery.ResolvedBattleRun(1, 100, 310, (1, 2), 130),),
            fixed_header_semantics=semantics,
        )
        self.assertEqual(
            recovery.resolve_battles_from_fixed_header_semantics(runs, semantics),
            merged.battles,
        )
        self.assertEqual(recovery.validate_run_resolution(runs, merged), merged.battles)

        falsely_split = recovery.RunResolution(
            policy_id=recovery.SEMANTIC_RUN_RESOLUTION_POLICY_ID,
            raw_runs_sha256=recovery.raw_runs_sha256(runs),
            battles=(
                recovery.ResolvedBattleRun(1, 100, 200, (1,), 130),
                recovery.ResolvedBattleRun(2, 250, 310, (2,), 280),
            ),
            fixed_header_semantics=semantics,
        )
        with self.assertRaisesRegex(recovery.GscVideoRecoveryError, "semantic groups"):
            recovery.validate_run_resolution(runs, falsely_split)

    def test_declared_attempt_must_match_finite_template_evidence(self) -> None:
        runs = (recovery.RawStateRun(1, "battle", 100, 200, 0.01, 0.03, 0.20),)
        resolution = recovery.RunResolution(
            policy_id=recovery.SEMANTIC_RUN_RESOLUTION_POLICY_ID,
            raw_runs_sha256=recovery.raw_runs_sha256(runs),
            battles=(recovery.ResolvedBattleRun(1, 100, 200, (1,), 130),),
            fixed_header_semantics=(
                self._semantic(
                    raw_run_ordinal=1,
                    probe_frame=130,
                    attempt=4,
                    matched_attempt=3,
                ),
            ),
        )
        with self.assertRaisesRegex(
            recovery.GscVideoRecoveryError,
            "declares 4, matched 3",
        ):
            recovery.validate_run_resolution(runs, resolution)

    def test_erika_morty_attempt_three_four_split_and_party_reentry_merge(self) -> None:
        runs = (
            recovery.RawStateRun(42, "battle", 190297, 193328, 0.01, 0.03, 0.20),
            recovery.RawStateRun(43, "battle", 197486, 200537, 0.01, 0.03, 0.20),
            recovery.RawStateRun(44, "battle", 202224, 203521, 0.01, 0.03, 0.20),
        )
        semantics = (
            self._semantic(
                raw_run_ordinal=42,
                probe_frame=190327,
                title_template="b" * 64,
                attempt=3,
            ),
            self._semantic(
                raw_run_ordinal=43,
                probe_frame=197516,
                title_template="b" * 64,
                attempt=4,
            ),
            self._semantic(
                raw_run_ordinal=44,
                probe_frame=202254,
                title_template="b" * 64,
                attempt=4,
            ),
        )
        resolution = recovery.RunResolution(
            policy_id=recovery.SEMANTIC_RUN_RESOLUTION_POLICY_ID,
            raw_runs_sha256=recovery.raw_runs_sha256(runs),
            battles=(
                recovery.ResolvedBattleRun(1, 190297, 193328, (42,), 190327),
                recovery.ResolvedBattleRun(
                    2,
                    197486,
                    203521,
                    (43, 44),
                    197516,
                ),
            ),
            fixed_header_semantics=semantics,
        )
        self.assertEqual(recovery.validate_run_resolution(runs, resolution), resolution.battles)

    def test_contiguous_same_title_attempt_sequence_cannot_skip_three(self) -> None:
        runs = (
            recovery.RawStateRun(1, "battle", 100, 200, 0.01, 0.03, 0.20),
            recovery.RawStateRun(2, "battle", 250, 350, 0.01, 0.03, 0.20),
        )
        semantics = (
            self._semantic(raw_run_ordinal=1, probe_frame=130, attempt=2),
            self._semantic(raw_run_ordinal=2, probe_frame=280, attempt=4),
        )
        resolution = recovery.RunResolution(
            policy_id=recovery.SEMANTIC_RUN_RESOLUTION_POLICY_ID,
            raw_runs_sha256=recovery.raw_runs_sha256(runs),
            battles=(
                recovery.ResolvedBattleRun(1, 100, 200, (1,), 130),
                recovery.ResolvedBattleRun(2, 250, 350, (2,), 280),
            ),
            fixed_header_semantics=semantics,
        )
        with self.assertRaisesRegex(
            recovery.GscVideoRecoveryError,
            "advance by exactly one",
        ):
            recovery.validate_run_resolution(runs, resolution)

    def test_projection_requires_three_separated_unique_pixel_matches(self) -> None:
        proof = self._proof()
        self.assertEqual(proof.expected_offset_frames, -6)
        self.assertEqual(recovery.project_vertical_frame_to_main(1200, proof), 1194)
        drifting = list(proof.anchors)
        drifting[-1] = recovery.ProjectionAnchor(
            **{**drifting[-1].__dict__, "main_frame": drifting[-1].main_frame + 1}
        )
        with self.assertRaisesRegex(recovery.GscVideoRecoveryError, "residual/drift"):
            recovery.validate_projection_proof(drifting)
        with self.assertRaisesRegex(recovery.GscVideoRecoveryError, "at least 3"):
            recovery.validate_projection_proof(proof.anchors[:2])

    def test_projection_discovery_searches_bounded_window_and_proves_exact_minus_six(self) -> None:
        vertical_frames = (1000, 2000, 3000)

        def extractor(
            path: Path,
            frames: list[int] | tuple[int, ...],
            deadline: recovery.RecoveryDeadline,
        ) -> dict[int, bytes]:
            deadline.check("fixture projection extraction")
            if path.name == "vertical.webm":
                return {
                    frame: bytes([40 + index * 50]) * 32
                    for index, frame in enumerate(vertical_frames)
                    if frame in frames
                }
            rows: dict[int, bytes] = {}
            for frame in frames:
                index = min(
                    range(len(vertical_frames)),
                    key=lambda candidate: abs(
                        frame
                        - (
                            vertical_frames[candidate]
                            + recovery.EXPECTED_MAIN_PROJECTION_FRAMES
                        )
                    ),
                )
                expected = (
                    vertical_frames[index] + recovery.EXPECTED_MAIN_PROJECTION_FRAMES
                )
                rows[frame] = bytes(
                    [40 + index * 50 + abs(frame - expected) * 30]
                ) * 32
            return rows

        proof = recovery.discover_projection_proof(
            Path("vertical.webm"),
            Path("main.mp4"),
            vertical_frames=vertical_frames,
            deadline=recovery.RecoveryDeadline.start(5),
            search_radius_frames=2,
            raw_window_extractor=extractor,
        )
        self.assertEqual(
            [row.main_frame - row.vertical_frame for row in proof.anchors],
            [-6, -6, -6],
        )
        self.assertTrue(all(row.normalized_distance == 0 for row in proof.anchors))
        self.assertEqual(
            recovery.discover_projection_anchors(
                Path("vertical.webm"),
                Path("main.mp4"),
                vertical_frames=vertical_frames,
                deadline=recovery.RecoveryDeadline.start(5),
                search_radius_frames=2,
                raw_window_extractor=extractor,
            ),
            proof.anchors,
        )

    def test_projection_discovery_rejects_drift_and_ambiguous_matches(self) -> None:
        vertical_frames = (1000, 2000, 3000)

        def fixture_extractor(*, drift: bool, ambiguous: bool):
            def extract(
                path: Path,
                frames: list[int] | tuple[int, ...],
                deadline: recovery.RecoveryDeadline,
            ) -> dict[int, bytes]:
                deadline.check("fixture projection extraction")
                if path.name == "vertical.webm":
                    return {
                        frame: bytes([40 + index * 50]) * 32
                        for index, frame in enumerate(vertical_frames)
                        if frame in frames
                    }
                rows: dict[int, bytes] = {}
                for frame in frames:
                    index = min(
                        range(len(vertical_frames)),
                        key=lambda candidate: abs(
                            frame
                            - (
                                vertical_frames[candidate]
                                + recovery.EXPECTED_MAIN_PROJECTION_FRAMES
                            )
                        ),
                    )
                    expected = (
                        vertical_frames[index] + recovery.EXPECTED_MAIN_PROJECTION_FRAMES
                    )
                    exact = expected + (1 if drift and index == 2 else 0)
                    delta = abs(frame - exact)
                    if ambiguous and index == 0 and frame in {expected, expected + 1}:
                        delta = 0
                    rows[frame] = bytes([40 + index * 50 + delta * 30]) * 32
                return rows

            return extract

        with self.assertRaisesRegex(recovery.GscVideoRecoveryError, "residual/drift"):
            recovery.discover_projection_proof(
                Path("vertical.webm"),
                Path("main.mp4"),
                vertical_frames=vertical_frames,
                deadline=recovery.RecoveryDeadline.start(5),
                raw_window_extractor=fixture_extractor(drift=True, ambiguous=False),
            )
        with self.assertRaisesRegex(recovery.GscVideoRecoveryError, "weak or ambiguous"):
            recovery.discover_projection_proof(
                Path("vertical.webm"),
                Path("main.mp4"),
                vertical_frames=vertical_frames,
                deadline=recovery.RecoveryDeadline.start(5),
                raw_window_extractor=fixture_extractor(drift=False, ambiguous=True),
            )

    def test_bundled_komikax_atlas_is_closed_and_matches_its_exact_erika_bitmap(self) -> None:
        titles = recovery.finite_komikax_identity_titles()
        self.assertIn("LEADER ERIKA", titles)
        self.assertIn("RIVAL1", titles)
        self.assertIn("RIVAL2", titles)
        self.assertEqual(len(titles), 24)
        atlas = recovery._load_komikax_atlas()
        template_width, template_height, mask = recovery._unpack_template(
            atlas["LEADER ERIKA"]
        )
        gray = bytearray([220] * (recovery.HEADER_TITLE_WIDTH * recovery.HEADER_TITLE_HEIGHT))
        left = 4
        top = 4
        for y in range(template_height):
            for x in range(template_width):
                if mask[y * template_width + x]:
                    gray[(top + y) * recovery.HEADER_TITLE_WIDTH + left + x] = 0
        match = recovery.match_finite_komikax_identity(bytes(gray))
        self.assertEqual(match.display_text, "LEADER ERIKA")
        self.assertEqual(match.trainer_class, "ERIKA")
        self.assertEqual(match.role, "leader")

    def test_recorded_komikax_confusers_match_and_generic_title_stays_rejected(self) -> None:
        def recorded_gray(title: str) -> bytes:
            mask_width, mask_height, encoded = _RECORDED_TITLE_MASKS_B85[title]
            mask = zlib.decompress(base64.b85decode(encoded.encode("ascii")))
            self.assertEqual(len(mask), mask_width * mask_height)
            gray = bytearray(
                [220] * (recovery.HEADER_TITLE_WIDTH * recovery.HEADER_TITLE_HEIGHT)
            )
            left = 4
            top = 4
            for y in range(mask_height):
                for x in range(mask_width):
                    if mask[y * mask_width + x]:
                        gray[
                            (top + y) * recovery.HEADER_TITLE_WIDTH + left + x
                        ] = 0
            return bytes(gray)

        for title in ("LEADER BUGSY", "LEADER CHUCK"):
            with self.subTest(title=title):
                self.assertEqual(
                    recovery.match_finite_komikax_identity(
                        recorded_gray(title)
                    ).display_text,
                    title,
                )
        with self.assertRaisesRegex(
            recovery.GscVideoRecoveryError,
            "does not uniquely match",
        ):
            recovery.match_finite_komikax_identity(recorded_gray("SWIMMER F"))

    def test_mapped_attempt_seam_uses_proven_minus_six_without_fake_events(self) -> None:
        runs = self._raw_runs()
        resolution = recovery.RunResolution(
            policy_id=recovery.SEMANTIC_RUN_RESOLUTION_POLICY_ID,
            raw_runs_sha256=recovery.raw_runs_sha256(runs),
            battles=(
                recovery.ResolvedBattleRun(1, 101, 103, (2,), 102),
            ),
            fixed_header_semantics=(self._semantic(),),
        )
        identity = recovery.IdentityMatch(
            display_text="LEADER ERIKA",
            identity="Erika",
            role="leader",
            trainer_class="ERIKA",
            trainer_id=1,
            normalized_distance=0.02,
            runner_up_distance=0.20,
            evidence_sha256="a" * 64,
        )
        result = recovery.build_mapped_recovered_attempts(
            resolution=resolution,
            raw_runs=runs,
            projection_proof=self._proof(),
            identity_matches={1: identity},
        )
        attempt = result["attempts"][0]
        self.assertEqual(attempt["source_start_frame"], 95)
        self.assertEqual(attempt["source_end_frame"], 97)
        self.assertEqual(attempt["session_start_frame"], 101)
        self.assertEqual(attempt["session_end_frame"], 103)
        self.assertEqual(attempt["source_duration_frames"], 2)
        self.assertEqual(attempt["battle_key"], "ERIKA:1")
        self.assertEqual(attempt["attempt_id"], "ERIKA:1:attempt-1")
        self.assertEqual(attempt["canonical_identity"], "ERIKA:1")
        self.assertEqual(attempt["identity_attempt_ordinal"], 1)
        self.assertTrue(attempt["final_timeline_mapping_required"])
        self.assertFalse(attempt["synthetic_session_events"])
        self.assertTrue(attempt["already_mapped_to_main_source"])


if __name__ == "__main__":
    unittest.main()
