from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from resolve_mcp.orchestrator.gsc_gym_fcpxml import (
    BgmSegment,
    GscGymFcpxmlSpec,
    IntroOverlay,
    MediaAsset,
    OpeningSpec,
    OutroSpec,
    assemble_gsc_gym_fcpxml,
)
from resolve_mcp.orchestrator.gsc_gym_fcpxml_plan import (
    BATTLE_BOUNDARY_POLICY,
    AutoEditorRetained,
    BattleAttemptSourceBoundary,
    CarouselSourceBoundary,
    GscGymGeometryError,
    RetainedSourceInterval,
    map_carousel_boundary,
    parse_autoeditor_fcpxml,
    plan_gsc_gym_geometry,
)


AUTOEDITOR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.11">
  <resources>
    <format id="r1" name="FFVideoFormatRateUndefined" frameDuration="1/60s" width="3840" height="2160"/>
    <asset id="r2" name="Erika Run" start="0s" duration="2500/60s" hasVideo="1" hasAudio="1" format="r1">
      <media-rep kind="original-media" src="file:///F:/media/erika-run.mp4"/>
    </asset>
  </resources>
  <library><event name="Auto-Editor"><project name="Erika Run">
    <sequence format="r1" tcStart="0s" tcFormat="NDF"><spine>
      <asset-clip name="Erika Run" ref="r2" offset="0s" start="100/60s" duration="500/60s" tcFormat="NDF"/>
      <asset-clip name="Erika Run" ref="r2" offset="500/60s" start="700/60s" duration="500/60s" tcFormat="NDF"/>
      <asset-clip name="Erika Run" ref="r2" offset="1000/60s" start="1300/60s" duration="400/60s" tcFormat="NDF"/>
      <asset-clip name="Erika Run" ref="r2" offset="1400/60s" start="1800/60s" duration="100/60s" tcFormat="NDF"/>
    </spine></sequence>
  </project></event></library>
</fcpxml>
"""


class GscGymFcpxmlPlanTests(unittest.TestCase):
    def boundaries(self) -> tuple[BattleAttemptSourceBoundary, ...]:
        return (
            BattleAttemptSourceBoundary(
                attempt_id="erika-attempt-1",
                canonical_identity="Erika",
                attempt_ordinal=1,
                role="leader",
                source_start_frame=700,
                source_end_frame=1000,
                start_authority="exact chapter/source binding",
                end_authority="exact chapter/source binding",
            ),
            BattleAttemptSourceBoundary(
                attempt_id="erika-attempt-2",
                canonical_identity="Erika",
                attempt_ordinal=2,
                role="leader",
                source_start_frame=1250,
                source_end_frame=1400,
                start_authority="exact chapter/source binding",
                end_authority="exact mapper projection",
            ),
        )

    def test_parse_flat_zero_llm_autoeditor_fcpxml(self) -> None:
        retained = parse_autoeditor_fcpxml(AUTOEDITOR_XML)
        self.assertEqual(retained.fcpxml_version, "1.11")
        self.assertEqual(retained.source_ref, "r2")
        self.assertEqual(retained.source_uri, "file:///F:/media/erika-run.mp4")
        self.assertEqual(retained.source_duration_frames, 2500)
        self.assertEqual(retained.record_duration_frames, 1500)
        self.assertEqual(
            [
                (item.record_start_frame, item.source_start_frame, item.duration_frames)
                for item in retained.intervals
            ],
            [(0, 100, 500), (500, 700, 500), (1000, 1300, 400), (1400, 1800, 100)],
        )

    def test_plan_inserts_lossless_a1_boundary_gaps_with_v1_bridges(self) -> None:
        retained = parse_autoeditor_fcpxml(AUTOEDITOR_XML)
        plan = plan_gsc_gym_geometry(
            retained,
            self.boundaries(),
            CarouselSourceBoundary(1500, "mapped final battle exit/carousel boundary"),
            dialogue_gain_db=-4.0,
        )
        self.assertEqual(plan.structural_audit["status"], "pass")
        self.assertEqual(plan.structural_audit["passed_count"], plan.structural_audit["check_count"])
        self.assertEqual(plan.manifest["llm_steps"], 0)
        self.assertEqual(
            plan.manifest["contract"]["boundary_policy"],
            BATTLE_BOUNDARY_POLICY,
        )

        self.assertEqual(
            [
                (item.record_start_frame, item.source_start_frame, item.duration_frames, item.label)
                for item in plan.body_v1
            ],
            [
                (260, 100, 500, "auto-editor retained 0001 part 0001"),
                (760, 640, 60, "battle-gap-v1-bridge:erika-attempt-1"),
                (820, 700, 500, "auto-editor retained 0002 part 0002"),
                (1320, 1300, 200, "auto-editor retained 0003 part before source 1500"),
            ],
        )
        self.assertEqual(
            [
                (item.record_start_frame, item.source_start_frame, item.duration_frames)
                for item in plan.dialogue_a1
            ],
            [
                (260, 100, 500),
                (820, 700, 500),
                (1320, 1300, 200),
                (1520, 1500, 200),
                (1720, 1800, 100),
            ],
        )
        gaps = [
            (item.gap_start_frame, item.gap_end_frame)
            for item in plan.battles
            if item.a1_gap_eligible
        ]
        self.assertEqual(gaps, [(760, 820)])
        self.assertEqual(
            [item.a1_gap_eligible for item in plan.battles],
            [True, False],
        )
        self.assertEqual(
            1,
            sum(item.label.startswith("battle-gap-v1-bridge:") for item in plan.body_v1),
        )
        self.assertEqual(
            plan.carousel.v1.record_end_frame,
            260 + retained.record_duration_frames + 60,
        )

        self.assertEqual(
            [
                (
                    item.battle_id,
                    item.original_record_start_frame,
                    item.original_record_end_frame,
                    item.final_start_frame,
                    item.final_end_frame,
                )
                for item in plan.battles
            ],
            [
                ("erika-attempt-1", 500, 800, 820, 1120),
                ("erika-attempt-2", 1000, 1100, 1320, 1420),
            ],
        )

        self.assertEqual(
            (
                plan.carousel.v1.record_start_frame,
                plan.carousel.v1.source_start_frame,
                plan.carousel.v1.duration_frames,
            ),
            (1520, 1500, 300),
        )
        self.assertEqual(
            [
                (item.record_start_frame, item.source_start_frame, item.duration_frames)
                for item in plan.carousel.v2_slices
            ],
            [(1520, 1500, 200), (1720, 1800, 100)],
        )

        intro = IntroOverlay(
            MediaAsset(Path("F:/GSC Assets/intros/erika.mov"), "erika.mov", 300),
            "Erika",
            "leader",
        )
        self.assertEqual([item.intro_eligible for item in plan.battles], [True, False])
        self.assertEqual(
            [item.start_snap_delta_frames for item in plan.battles],
            [0, 0],
        )
        self.assertEqual(
            [
                (item.effective_source_start_frame, item.start_mapping_policy)
                for item in plan.battles
            ],
            [
                (700, "battle_start_exact_retained_interval_start"),
                (1250, "battle_start_removed_gap_exact_contiguous_edit_join"),
            ],
        )
        assembler_battles = plan.assembler_battles({"erika-attempt-1": intro})
        self.assertEqual(
            [
                (
                    item.battle_id,
                    item.start_frame,
                    item.end_frame,
                    item.intro is not None,
                    item.intro_eligible,
                    item.a1_gap_eligible,
                )
                for item in assembler_battles
            ],
            [
                ("erika-attempt-1", 820, 1120, True, True, True),
                ("erika-attempt-2", 1320, 1420, False, False, False),
            ],
        )

    def test_sparse_retained_retry_needs_no_gap_intro_or_sixty_frame_left_handle(self) -> None:
        retained = AutoEditorRetained(
            fcpxml_version="1.11",
            source_ref="r2",
            source_name="Sparse retry source",
            source_uri="file:///F:/media/sparse-retry.mp4",
            source_start_frame=100,
            source_duration_frames=100,
            intervals=(
                RetainedSourceInterval(0, 100, 20, "outgoing retained segment"),
                RetainedSourceInterval(20, 120, 80, "incoming retained segment"),
            ),
            record_duration_frames=100,
            fcpxml_sha256="fixture",
        )
        retry = BattleAttemptSourceBoundary(
            attempt_id="erika-attempt-2",
            canonical_identity="ERIKA:1",
            attempt_ordinal=2,
            role="leader",
            source_start_frame=120,
            source_end_frame=150,
            start_authority="receipt-retained sparse retry",
            end_authority="receipt-retained sparse retry",
        )

        plan = plan_gsc_gym_geometry(
            retained,
            (retry,),
            CarouselSourceBoundary(160, "fixture carousel"),
            dialogue_gain_db=-4.0,
        )
        battle = plan.battles[0]
        self.assertEqual(battle.attempt_ordinal, 2)
        self.assertFalse(battle.a1_gap_eligible)
        self.assertFalse(battle.intro_eligible)
        self.assertEqual(battle.gap_start_frame, battle.final_start_frame)
        self.assertEqual(battle.gap_end_frame, battle.final_start_frame)
        self.assertFalse(
            any(
                item.label.startswith("battle-gap-v1-bridge:")
                for item in plan.body_v1
            )
        )
        self.assertEqual(
            1,
            sum(
                item.record_end_frame == battle.final_start_frame
                for item in plan.dialogue_a1
            ),
        )
        self.assertEqual(
            1,
            sum(
                item.record_start_frame == battle.final_start_frame
                for item in plan.dialogue_a1
            ),
        )
        self.assertEqual(plan.assembler_battles({})[0].attempt_ordinal, 2)

        with self.assertRaisesRegex(
            GscGymGeometryError,
            "60 source-preroll frames",
        ):
            plan_gsc_gym_geometry(
                retained,
                (replace(retry, attempt_ordinal=1),),
                CarouselSourceBoundary(160, "fixture carousel"),
                dialogue_gain_db=-4.0,
            )

    def test_same_inputs_produce_identical_plan_and_manifest(self) -> None:
        retained = parse_autoeditor_fcpxml(AUTOEDITOR_XML)
        args = (
            retained,
            self.boundaries(),
            CarouselSourceBoundary(1500, "mapped carousel"),
        )
        first = plan_gsc_gym_geometry(*args, dialogue_gain_db=-4.0)
        second = plan_gsc_gym_geometry(*args, dialogue_gain_db=-4.0)
        self.assertEqual(first, second)

    def test_two_physical_retries_keep_one_gap_and_two_battle_bgm_ranges(self) -> None:
        plan = plan_gsc_gym_geometry(
            parse_autoeditor_fcpxml(AUTOEDITOR_XML),
            self.boundaries(),
            CarouselSourceBoundary(1500, "mapped carousel"),
            dialogue_gain_db=-4.0,
        )
        intro = IntroOverlay(
            MediaAsset(Path("F:/GSC Assets/intros/erika.mov"), "erika.mov", 300),
            "Erika",
            "leader",
        )
        battle_specs = plan.assembler_battles({"erika-attempt-1": intro})
        source = MediaAsset(Path("F:/media/erika-run.mp4"), "Erika Run", 2500)
        dialogue = MediaAsset(Path("F:/media/erika-dialogue.wav"), "Erika dialogue", 2500)
        opening = MediaAsset(
            Path("F:/GSC Assets/GSCPC Intro Short__400pct.mp4"),
            "GSCPC Intro Short__400pct.mp4",
            260,
            video_fps=30,
        )
        outro = MediaAsset(
            Path("F:/GSC Assets/GSC Assets outro.mov"),
            "GSC Assets outro.mov",
            120,
        )
        dual = MediaAsset(
            Path("F:/Programming/GSCNewLayout/audio/Dual Screen Lovelife.mp3"),
            "Dual Screen Lovelife.mp3",
            260,
        )
        bed = MediaAsset(
            Path("F:/Programming/GSCNewLayout/audio/Thinking.mp3"),
            "Thinking.mp3",
            3000,
        )
        fresh = MediaAsset(
            Path("F:/Programming/GSCNewLayout/audio/Fresh Horizon.mp3"),
            "Fresh Horizon.mp3",
            3000,
        )
        clouds = MediaAsset(
            Path("F:/Programming/GSCNewLayout/audio/Motivated By Clouds.mp3"),
            "Motivated By Clouds.mp3",
            3000,
        )
        stardust = MediaAsset(
            Path("F:/Programming/GSCNewLayout/audio/Roll Me in Stardust.mp3"),
            "Roll Me in Stardust.mp3",
            3000,
        )
        filler = MediaAsset(
            Path("F:/Programming/GSCNewLayout/audio/Afterglow.mp3"),
            "Afterglow.mp3",
            3000,
        )
        battle_music = MediaAsset(
            Path("F:/Programming/GSCNewLayout/audio/Gen 2 battle audio/leader.mp3"),
            "leader.mp3",
            1000,
        )
        assembled = assemble_gsc_gym_fcpxml(
            GscGymFcpxmlSpec(
                timeline_name="Erika retries deterministic",
                source_video=source,
                dialogue_audio=dialogue,
                opening=OpeningSpec(opening, 400),
                body_v1=plan.body_v1,
                dialogue_a1=plan.dialogue_a1,
                battles=battle_specs,
                bgm_a2=(
                    BgmSegment(0, 0, 260, dual, "opening", "opening"),
                    BgmSegment(
                        260, 0, 560, bed, "nonbattle", "before attempt 1",
                        fade_out_frames=30,
                    ),
                    BgmSegment(
                        820, 0, 300, battle_music, "battle", "attempt 1 battle",
                        battle_id="erika-attempt-1", fade_in_frames=30,
                        fade_out_frames=30,
                    ),
                    BgmSegment(
                        1120, 0, 200, fresh, "nonbattle", "between retries",
                        fade_in_frames=30, fade_out_frames=30,
                    ),
                    BgmSegment(
                        1320, 0, 100, battle_music, "battle", "attempt 2 battle",
                        battle_id="erika-attempt-2", fade_in_frames=30,
                        fade_out_frames=30,
                    ),
                    BgmSegment(
                        1420, 0, 100, dual, "nonbattle", "post-final DSL",
                        fade_in_frames=30,
                    ),
                    BgmSegment(
                        1520, 0, 100, clouds, "carousel", "post-final clouds",
                    ),
                    BgmSegment(
                        1620, 0, 100, stardust, "carousel", "post-final stardust",
                    ),
                    BgmSegment(
                        1720, 0, 100, filler, "carousel", "post-final filler",
                        fade_out_frames=30,
                    ),
                ),
                carousel=plan.carousel,
                outro=OutroSpec(outro, -5.0),
            )
        )
        self.assertEqual(assembled.structural_audit["status"], "pass")
        self.assertEqual(len(assembled.manifest["a1"]["battle_gaps"]), 1)
        self.assertEqual(
            [item["record_range"] for item in assembled.manifest["a2"]["segments"] if item["role"] == "battle"],
            [[820, 1120], [1320, 1420]],
        )
        self.assertEqual(
            [item["intro_eligible"] for item in assembled.manifest["battles"]],
            [True, False],
        )

    def test_explicit_start_end_and_carousel_mapping_policies(self) -> None:
        retained = parse_autoeditor_fcpxml(AUTOEDITOR_XML)
        inside_start = (
            replace(
                self.boundaries()[0],
                source_start_frame=450,
                source_end_frame=750,
            ),
        )
        nearest_following = plan_gsc_gym_geometry(
            retained,
            inside_start,
            CarouselSourceBoundary(1500, "mapped carousel"),
            dialogue_gain_db=-4.0,
        ).battles[0]
        self.assertEqual(
            (
                nearest_following.source_start_frame,
                nearest_following.effective_source_start_frame,
                nearest_following.start_snap_delta_frames,
                nearest_following.start_mapping_policy,
            ),
            (
                450,
                600,
                150,
                "battle_start_inside_retained_nearest_following_adjacent_join",
            ),
        )

        snapped_end_boundary = (
            replace(
                self.boundaries()[0],
                source_start_frame=700,
                source_end_frame=1250,
            ),
        )
        snapped_end = plan_gsc_gym_geometry(
            retained,
            snapped_end_boundary,
            CarouselSourceBoundary(1500, "mapped carousel"),
            dialogue_gain_db=-4.0,
        ).battles[0]
        self.assertEqual(
            (
                snapped_end.source_end_frame,
                snapped_end.effective_source_end_frame,
                snapped_end.end_snap_delta_frames,
                snapped_end.end_mapping_policy,
            ),
            (
                1250,
                1250,
                0,
                "battle_end_removed_gap_exact_contiguous_edit_join",
            ),
        )

        carousel = map_carousel_boundary(
            retained,
            CarouselSourceBoundary(1250, "fixed detector"),
        )
        self.assertEqual(
            (
                carousel.raw_source_frame,
                carousel.effective_source_frame,
                carousel.snap_delta_frames,
                carousel.policy,
            ),
            (
                1250,
                1300,
                50,
                "carousel_removed_gap_snap_to_next_retained_start",
            ),
        )
        carousel_plan = plan_gsc_gym_geometry(
            retained,
            self.boundaries()[:1],
            CarouselSourceBoundary(1250, "fixed detector"),
            dialogue_gain_db=-4.0,
        )
        self.assertEqual(
            {
                key: carousel_plan.manifest["carousel"][key]
                for key in (
                    "raw_source_boundary_frame",
                    "effective_source_boundary_frame",
                    "snap_delta_frames",
                    "mapping_policy",
                    "boundary_authority",
                    "effective_boundary_authority",
                )
            },
            {
                "raw_source_boundary_frame": 1250,
                "effective_source_boundary_frame": 1300,
                "snap_delta_frames": 50,
                "mapping_policy": "carousel_removed_gap_snap_to_next_retained_start",
                "boundary_authority": "fixed detector",
                "effective_boundary_authority": (
                    "fixed detector;deterministic_mapping:"
                    "carousel_removed_gap_snap_to_next_retained_start"
                ),
            },
        )
        mapping_check = next(
            item
            for item in carousel_plan.structural_audit["checks"]
            if item["name"] == "explicit_bounded_deterministic_boundary_mappings"
        )
        self.assertEqual(mapping_check["status"], "pass")
        self.assertTrue(
            all(row["input_authority"] and row["effective_authority"] for row in mapping_check["evidence"]["mappings"])
        )

        with self.assertRaisesRegex(
            GscGymGeometryError,
            "exceeding maximum absolute delta 49",
        ):
            map_carousel_boundary(
                retained,
                CarouselSourceBoundary(1250, "fixed detector"),
                max_snap_frames=49,
            )
        with self.assertRaisesRegex(GscGymGeometryError, "no following"):
            map_carousel_boundary(
                retained,
                CarouselSourceBoundary(2000, "after final retained content"),
            )

        collapsed = (
            replace(
                self.boundaries()[0],
                source_start_frame=750,
                source_end_frame=1250,
            ),
        )
        preserved = plan_gsc_gym_geometry(
            retained,
            collapsed,
            CarouselSourceBoundary(1500, "mapped carousel"),
            dialogue_gain_db=-4.0,
        ).battles[0]
        self.assertEqual(
            (
                preserved.original_record_start_frame,
                preserved.original_record_end_frame,
                preserved.effective_source_start_frame,
                preserved.start_snap_delta_frames,
                preserved.start_mapping_policy,
            ),
            (
                500,
                1000,
                700,
                -50,
                "battle_start_inside_retained_nearest_preceding_adjacent_join",
            ),
        )

        equidistant = (
            replace(
                self.boundaries()[0],
                source_start_frame=950,
                source_end_frame=1500,
            ),
        )
        with self.assertRaisesRegex(
            GscGymGeometryError,
            "exactly equidistant.*fails closed",
        ):
            plan_gsc_gym_geometry(
                retained,
                equidistant,
                CarouselSourceBoundary(1800, "mapped carousel"),
                dialogue_gain_db=-4.0,
            )

    def test_erika_rival2_video_recovery_uses_nearest_preceding_join(self) -> None:
        retained = AutoEditorRetained(
            fcpxml_version="1.11",
            source_ref="r2",
            source_name="Erika Victreebel Crystal Gym Leader Challenge",
            source_uri="file:///F:/media/erika-victreebel.mp4",
            source_start_frame=0,
            source_duration_frames=84_000,
            intervals=(
                RetainedSourceInterval(0, 0, 50_828, "retained before evidence window"),
                RetainedSourceInterval(50_828, 78_363, 339, "Erika interval 157"),
                RetainedSourceInterval(51_167, 78_708, 115, "Erika interval 158"),
                RetainedSourceInterval(51_282, 79_085, 179, "Erika interval 159"),
                RetainedSourceInterval(51_461, 79_270, 1_107, "Erika interval 160"),
                RetainedSourceInterval(52_568, 82_300, 700, "retained after Rival 2"),
            ),
            record_duration_frames=53_268,
            fcpxml_sha256="fixture",
        )
        battles = (
            BattleAttemptSourceBoundary(
                "fixture-leader",
                "Fixture Leader",
                1,
                "leader",
                78_363,
                78_702,
                "exact retained join fixture",
                "exact retained join fixture",
            ),
            BattleAttemptSourceBoundary(
                "RIVAL1:5",
                "Rival 2",
                1,
                "rival",
                79_106,
                82_222,
                "content-bound video recovery receipt; projected -6f",
                "content-bound video recovery receipt; projected -6f",
            ),
        )

        plan = plan_gsc_gym_geometry(
            retained,
            battles,
            CarouselSourceBoundary(82_700, "fixture carousel"),
            dialogue_gain_db=-4.0,
        )
        rival = plan.battles[1]
        self.assertEqual(
            (
                rival.source_start_frame,
                rival.effective_source_start_frame,
                rival.original_record_start_frame,
                rival.start_snap_delta_frames,
                rival.start_mapping_policy,
            ),
            (
                79_106,
                79_085,
                51_282,
                -21,
                "battle_start_inside_retained_nearest_preceding_adjacent_join",
            ),
        )
        self.assertEqual(rival.gap_end_frame, rival.final_start_frame)
        self.assertEqual(60, rival.gap_end_frame - rival.gap_start_frame)
        self.assertEqual(
            260 + 51_282 + 2 * 60,
            rival.final_start_frame,
        )
        planned_dialogue_ranges: list[tuple[int, int]] = []
        for item in plan.dialogue_a1:
            current = (
                item.source_start_frame,
                item.source_start_frame + item.duration_frames,
            )
            if planned_dialogue_ranges and planned_dialogue_ranges[-1][1] == current[0]:
                planned_dialogue_ranges[-1] = (
                    planned_dialogue_ranges[-1][0],
                    current[1],
                )
            else:
                planned_dialogue_ranges.append(current)
        self.assertEqual(
            [
                (item.source_start_frame, item.source_end_frame)
                for item in retained.intervals
            ],
            planned_dialogue_ranges,
        )
        self.assertTrue(
            any(
                item.label == "battle-gap-v1-bridge:RIVAL1:5"
                and item.source_start_frame == 79_025
                and item.duration_frames == 60
                for item in plan.body_v1
            )
        )
        mapping = plan.manifest["battles"][1]
        self.assertEqual(mapping["effective_source_range"][0], 79_085)
        self.assertEqual(mapping["final_record_range"][0], rival.final_start_frame)

    def test_erika_former_midclip_split_shapes_use_preceding_joins_losslessly(self) -> None:
        retained = replace(
            parse_autoeditor_fcpxml(AUTOEDITOR_XML),
            source_duration_frames=4_000,
            intervals=(
                RetainedSourceInterval(0, 1_000, 100, "before 6+54"),
                RetainedSourceInterval(100, 1_200, 200, "contains 54"),
                RetainedSourceInterval(300, 1_500, 100, "before 31+29"),
                RetainedSourceInterval(400, 1_700, 200, "contains 29"),
                RetainedSourceInterval(600, 2_000, 100, "before 53+7"),
                RetainedSourceInterval(700, 2_200, 800, "contains 7"),
                RetainedSourceInterval(1_500, 3_100, 100, "carousel"),
            ),
            record_duration_frames=1_600,
        )
        battles = (
            BattleAttemptSourceBoundary(
                "video-3",
                "video-3",
                1,
                "trainer",
                1_254,
                1_300,
                "fixture",
                "fixture",
            ),
            BattleAttemptSourceBoundary(
                "video-41",
                "video-41",
                1,
                "trainer",
                1_729,
                1_750,
                "fixture",
                "fixture",
            ),
            BattleAttemptSourceBoundary(
                "jasmine-1",
                "jasmine",
                1,
                "leader",
                2_207,
                3_100,
                "fixture",
                "fixture",
            ),
        )

        plan = plan_gsc_gym_geometry(
            retained,
            battles,
            CarouselSourceBoundary(3_100, "fixture carousel"),
            dialogue_gain_db=-4.0,
        )

        self.assertEqual([(6, 54), (31, 29), (53, 7)], [
            (60 - offset, offset)
            for offset in (54, 29, 7)
        ])
        self.assertEqual([100, 400, 700], [
            item.original_record_start_frame for item in plan.battles
        ])
        self.assertEqual([-54, -29, -7], [
            item.start_snap_delta_frames for item in plan.battles
        ])
        self.assertTrue(all(
            item.start_mapping_policy
            == "battle_start_inside_retained_nearest_preceding_adjacent_join"
            for item in plan.battles
        ))
        self.assertFalse(any(
            "exact_split" in item.start_mapping_policy for item in plan.battles
        ))
        self.assertEqual(3, sum(
            item.label.startswith("battle-gap-v1-bridge:")
            for item in plan.body_v1
        ))
        original_a1 = [
            (item.source_start_frame, item.source_end_frame)
            for item in retained.intervals
        ]
        planned_a1 = [
            (item.source_start_frame, item.source_start_frame + item.duration_frames)
            for item in plan.dialogue_a1
        ]
        self.assertEqual(original_a1, planned_a1)
        self.assertEqual(
            retained.record_duration_frames + 3 * 60,
            plan.carousel.v1.record_end_frame - 260,
        )

    def test_erika_pryce_real_geometry_uses_nearest_preceding_join(self) -> None:
        retained = replace(
            parse_autoeditor_fcpxml(AUTOEDITOR_XML),
            source_duration_frames=400_000,
            intervals=(
                RetainedSourceInterval(0, 0, 171_338, "Erika before Pryce"),
                RetainedSourceInterval(
                    171_338, 324_851, 131, "Erika segment 626"
                ),
                RetainedSourceInterval(
                    171_469, 325_179, 248, "Erika segment 627"
                ),
                RetainedSourceInterval(
                    171_717, 325_445, 202, "Erika segment 628"
                ),
                RetainedSourceInterval(
                    171_919, 327_700, 500, "Erika after Pryce"
                ),
            ),
            record_duration_frames=172_419,
            fcpxml_sha256="erika-pryce-fixture",
        )
        pryce = BattleAttemptSourceBoundary(
            "PRYCE:1:attempt-1",
            "PRYCE:1",
            1,
            "leader",
            325_191,
            327_832,
            "fixed-header video recovery projected -6f",
            "fixed-header video recovery projected -6f",
        )

        plan = plan_gsc_gym_geometry(
            retained,
            (pryce,),
            CarouselSourceBoundary(328_100, "fixture carousel"),
            dialogue_gain_db=-4.0,
        )
        planned = plan.battles[0]
        self.assertEqual(
            (
                planned.source_start_frame,
                planned.effective_source_start_frame,
                planned.original_record_start_frame,
                planned.start_snap_delta_frames,
                planned.start_mapping_policy,
            ),
            (
                325_191,
                325_179,
                171_469,
                -12,
                "battle_start_inside_retained_nearest_preceding_adjacent_join",
            ),
        )
        self.assertTrue(planned.a1_gap_eligible)
        self.assertTrue(planned.intro_eligible)
        self.assertEqual(
            [
                (
                    candidate.side,
                    candidate.snap_delta_frames,
                    candidate.absolute_distance_frames,
                    candidate.valid,
                )
                for candidate in planned.start_candidate_evidence
            ],
            [
                ("preceding", -12, 12, True),
                ("following", 236, 236, True),
            ],
        )
        self.assertEqual(planned.gap_end_frame, planned.final_start_frame)
        self.assertEqual(
            (planned.gap_start_frame, planned.gap_end_frame),
            (171_729, 171_789),
        )
        self.assertTrue(
            any(
                item.label == "battle-gap-v1-bridge:PRYCE:1:attempt-1"
                and item.source_start_frame == 325_119
                and item.duration_frames == 60
                for item in plan.body_v1
            )
        )
        mapping = plan.manifest["battles"][0]
        self.assertEqual(mapping["effective_source_range"][0], 325_179)
        self.assertEqual(mapping["final_record_range"][0], 171_789)
        self.assertEqual(
            [row["absolute_distance_frames"] for row in mapping["start_candidate_evidence"]],
            [12, 236],
        )

    def test_source_contiguous_autoeditor_joins_preserve_every_frame(self) -> None:
        retained = replace(
            parse_autoeditor_fcpxml(AUTOEDITOR_XML),
            intervals=(
                RetainedSourceInterval(0, 100, 500, "source-contiguous 1"),
                RetainedSourceInterval(500, 600, 500, "source-contiguous 2"),
                RetainedSourceInterval(1000, 1100, 400, "source-contiguous 3"),
                RetainedSourceInterval(1400, 1500, 100, "source-contiguous 4"),
            ),
        )
        boundary = replace(
            self.boundaries()[0],
            source_start_frame=600,
            source_end_frame=900,
        )
        plan = plan_gsc_gym_geometry(
            retained,
            (boundary,),
            CarouselSourceBoundary(1500, "source-contiguous carousel"),
            dialogue_gain_db=-4.0,
        )
        self.assertEqual(plan.structural_audit["status"], "pass")
        self.assertEqual(
            sum(item.duration_frames for item in retained.intervals),
            sum(item.duration_frames for item in plan.dialogue_a1),
        )

    def test_direct_battle_handoff_receives_a_new_timeline_gap(self) -> None:
        retained = parse_autoeditor_fcpxml(AUTOEDITOR_XML)
        first = replace(self.boundaries()[0], source_end_frame=1300)
        second = BattleAttemptSourceBoundary(
            attempt_id="trainer-attempt-1",
            canonical_identity="Trainer",
            attempt_ordinal=1,
            role="trainer",
            source_start_frame=1300,
            source_end_frame=1500,
            start_authority="exact direct handoff",
            end_authority="exact direct handoff",
        )
        plan = plan_gsc_gym_geometry(
            retained,
            (first, second),
            CarouselSourceBoundary(1500, "direct handoff carousel"),
            dialogue_gain_db=-4.0,
        )
        self.assertEqual(plan.battles[0].final_end_frame, plan.battles[1].gap_start_frame)
        self.assertEqual(
            60,
            plan.battles[1].gap_end_frame - plan.battles[1].gap_start_frame,
        )
        self.assertEqual(
            sum(item.duration_frames for item in retained.intervals),
            sum(item.duration_frames for item in plan.dialogue_a1),
        )

    def test_battle_start_without_a_bounded_adjacent_join_fails_closed(self) -> None:
        retained = parse_autoeditor_fcpxml(AUTOEDITOR_XML)
        boundary = replace(
            self.boundaries()[0],
            source_start_frame=350,
            source_end_frame=750,
        )
        with self.assertRaisesRegex(
            GscGymGeometryError,
            "no adjacent auto-editor segment boundary within 100 frames",
        ):
            plan_gsc_gym_geometry(
                retained,
                (boundary,),
                CarouselSourceBoundary(1500, "mapped carousel"),
                dialogue_gain_db=-4.0,
                max_snap_frames=100,
            )

    def test_preserved_surge_carousel_detector_snaps_33_frames(self) -> None:
        raw_path = Path(
            "F:/Lt Surge Crystal Gym Leader Challenge/"
            "2026-07-22 21-12-04_AUTOEDITOR_RAW.fcpxml"
        )
        if not raw_path.is_file():
            self.skipTest("Preserved Surge raw auto-editor FCPXML is unavailable.")
        retained = parse_autoeditor_fcpxml(raw_path.read_text(encoding="utf-8-sig"))
        mapped = map_carousel_boundary(
            retained,
            CarouselSourceBoundary(299957, "fixed deterministic pixel detector"),
        )
        self.assertEqual(
            (
                mapped.raw_source_frame,
                mapped.effective_source_frame,
                mapped.snap_delta_frames,
                mapped.original_record_frame,
            ),
            (299957, 299990, 33, 157317),
        )
        with self.assertRaisesRegex(
            GscGymGeometryError,
            "exceeding maximum absolute delta 32",
        ):
            map_carousel_boundary(
                retained,
                CarouselSourceBoundary(299957, "fixed deterministic pixel detector"),
                max_snap_frames=32,
            )

    def test_ambiguous_repeated_source_and_bad_record_geometry_fail_closed(self) -> None:
        retained = parse_autoeditor_fcpxml(AUTOEDITOR_XML)
        ambiguous = replace(
            retained,
            intervals=(
                RetainedSourceInterval(0, 100, 500, "one"),
                RetainedSourceInterval(500, 400, 500, "overlap"),
            ),
            record_duration_frames=1000,
        )
        with self.assertRaisesRegex(GscGymGeometryError, "ambiguous source mapping"):
            plan_gsc_gym_geometry(
                ambiguous,
                self.boundaries()[:1],
                CarouselSourceBoundary(800, "mapped carousel"),
                dialogue_gain_db=-4.0,
            )

        broken_xml = AUTOEDITOR_XML.replace('offset="500/60s"', 'offset="501/60s"', 1)
        with self.assertRaisesRegex(GscGymGeometryError, "not contiguous"):
            parse_autoeditor_fcpxml(broken_xml)

    def test_intro_binding_is_exact_not_best_effort(self) -> None:
        plan = plan_gsc_gym_geometry(
            parse_autoeditor_fcpxml(AUTOEDITOR_XML),
            self.boundaries(),
            CarouselSourceBoundary(1500, "mapped carousel"),
            dialogue_gain_db=-4.0,
        )
        with self.assertRaisesRegex(GscGymGeometryError, "exactly match"):
            plan.assembler_battles({})


if __name__ == "__main__":
    unittest.main()
