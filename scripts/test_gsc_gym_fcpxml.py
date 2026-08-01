from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from resolve_mcp.orchestrator.gsc_gym_fcpxml import (
    BgmSegment,
    BattleSpec,
    CarouselSlice,
    CarouselSpec,
    DialogueInterval,
    GscGymFcpxmlError,
    GscGymFcpxmlSpec,
    IntroOverlay,
    MediaAsset,
    OpeningSpec,
    OutroSpec,
    SourceInterval,
    assemble_gsc_gym_fcpxml,
)


def frames(value: str) -> int:
    parsed = Fraction(value[:-1]) * 60
    if parsed.denominator != 1:
        raise AssertionError(value)
    return parsed.numerator


class GscGymFcpxmlTests(unittest.TestCase):
    @staticmethod
    def asset(path: str, frames_: int, *, name: str | None = None) -> MediaAsset:
        return MediaAsset(path=Path(path), name=name or Path(path).name, duration_frames=frames_)

    def valid_spec(self) -> GscGymFcpxmlSpec:
        source = self.asset("F:/media/erika-run.mp4", 3_000)
        dialogue = self.asset("F:/media/erika-run-dialogue.wav", 3_000)
        opening = replace(
            self.asset("F:/GSC Assets/GSCPC Intro Short__400pct.mp4", 260),
            video_fps=30,
        )
        leader_intro = self.asset("F:/GSC Assets/intros/erika-battle-intro.mov", 300)
        outro = self.asset("F:/GSC Assets/GSC Assets outro.mov", 120)
        dual_screen = self.asset("F:/GSCNewLayout/audio/Dual Screen Lovelife.mp3", 260)
        thinking = self.asset("F:/GSCNewLayout/audio/Just Thinking.mp3", 800)
        fresh = self.asset("F:/GSCNewLayout/audio/Fresh Horizon.mp3", 800)
        clouds = self.asset("F:/GSCNewLayout/audio/Motivated By Clouds.mp3", 500)
        stardust = self.asset("F:/GSCNewLayout/audio/Roll Me in Stardust.mp3", 500)
        filler = self.asset("F:/GSCNewLayout/audio/Afterglow.mp3", 500)
        battle_one = self.asset(
            "F:/Programming/GSCNewLayout/audio/Gen 2 battle audio/gym-leader.mp3",
            500,
        )
        battle_two = self.asset(
            "F:/Programming/GSCNewLayout/audio/Gen 2 battle audio/trainer.mp3",
            500,
        )
        return GscGymFcpxmlSpec(
            timeline_name="Erika Crystal Gym Leader Challenge deterministic dry run",
            source_video=source,
            dialogue_audio=dialogue,
            opening=OpeningSpec(opening, pre_retimed_rate_percent=400),
            body_v1=(
                SourceInterval(260, 100, 340, "body 1"),
                SourceInterval(600, 440, 60, "battle-gap-v1-bridge:erika-1"),
                SourceInterval(660, 500, 200, "body 2"),
                SourceInterval(860, 640, 60, "battle-gap-v1-bridge:trainer-1"),
                SourceInterval(920, 700, 200, "body 3"),
            ),
            dialogue_a1=(
                DialogueInterval(260, 100, 340, "dialogue 1", -4.0),
                DialogueInterval(660, 500, 200, "dialogue 2", -3.0),
                DialogueInterval(920, 700, 200, "dialogue 3", -3.0),
                DialogueInterval(1120, 1200, 120, "carousel dialogue", -3.0),
            ),
            battles=(
                BattleSpec(
                    "erika-1",
                    "leader",
                    660,
                    780,
                    intro=IntroOverlay(leader_intro, "Erika", "leader"),
                    canonical_identity="ERIKA:1",
                    attempt_ordinal=1,
                ),
                BattleSpec(
                    "trainer-1",
                    "trainer",
                    920,
                    1020,
                    canonical_identity="YOUNGSTER:1",
                    attempt_ordinal=1,
                ),
            ),
            bgm_a2=(
                BgmSegment(0, 0, 260, dual_screen, "opening", "opening", -8.4),
                BgmSegment(
                    260, 0, 400, thinking, "nonbattle", "bed 1", -7.0,
                    fade_out_frames=30,
                ),
                BgmSegment(
                    660, 0, 120, battle_one, "battle", "Erika battle", -5.0,
                    battle_id="erika-1", fade_in_frames=30, fade_out_frames=30,
                ),
                BgmSegment(
                    780, 0, 140, fresh, "nonbattle", "fresh after Erika", -7.0,
                    fade_in_frames=30, fade_out_frames=30,
                ),
                BgmSegment(
                    920, 0, 100, battle_two, "battle", "trainer battle", -5.0,
                    battle_id="trainer-1", fade_in_frames=30, fade_out_frames=30,
                ),
                BgmSegment(
                    1020, 0, 50, dual_screen, "nonbattle", "post-final DSL", -6.0,
                    fade_in_frames=30,
                ),
                BgmSegment(
                    1070, 0, 50, clouds, "nonbattle", "post-final clouds", -6.0,
                ),
                BgmSegment(
                    1120, 0, 50, stardust, "carousel", "post-final stardust", -6.0,
                ),
                BgmSegment(
                    1170, 0, 70, filler, "carousel", "post-final filler", -6.0,
                    fade_out_frames=30,
                ),
            ),
            carousel=CarouselSpec(
                v1=SourceInterval(1120, 1200, 120, "member carousel source bed"),
                v2_slices=(
                    CarouselSlice(1120, 1500, 40, "member 1"),
                    CarouselSlice(1160, 1600, 80, "member 2"),
                ),
            ),
            outro=OutroSpec(outro, gain_db=-5.0),
            battle_bgm_library_filenames=("gym-leader.mp3", "trainer.mp3"),
            battle_bgm_seed="fixture-seed",
        )

    def test_build_is_import_ready_and_all_track_geometry_is_exact(self) -> None:
        result = assemble_gsc_gym_fcpxml(self.valid_spec())
        self.assertEqual(result.structural_audit["status"], "pass")
        self.assertEqual(result.structural_audit["passed_count"], result.structural_audit["check_count"])
        self.assertEqual(result.manifest["llm_steps"], 0)
        self.assertTrue(result.manifest["deterministic"])
        self.assertEqual(
            [row["battle_id"] for row in result.manifest["a2"]["battle_assignments"]],
            ["erika-1", "trainer-1"],
        )
        self.assertEqual(result.manifest["a2"]["battle_edge_fade_frames"], 30)
        self.assertEqual(
            result.manifest["a2"]["source_contract"],
            "original_library_media_v1",
        )
        self.assertFalse(result.manifest["a2"]["derived_media_allowed"])
        self.assertFalse(result.manifest["a2"]["renamed_timeline_clips_allowed"])
        self.assertTrue(result.manifest["a2"]["source_trim_handles_editable"])
        self.assertTrue(
            all(
                "baked_gain_db" not in row
                and "timeline_gain_db" not in row
                and row["asset"]["path"] == row["asset"]["origin_path"]
                and row["asset"]["name"] == Path(row["asset"]["path"]).name
                and row["derived_media"] is False
                for row in result.manifest["a2"]["segments"]
            )
        )
        self.assertEqual(result.structural_audit["check_count"], 12)
        contract = result.manifest["a2"]["nonbattle_bgm_contract"]
        self.assertEqual(contract["dual_screen_lovelife_occurrence_starts"], [0, 1020])
        self.assertEqual(
            contract["post_final_first_four_identities"],
            [
                "Dual Screen Lovelife.mp3",
                "Motivated By Clouds.mp3",
                "Roll Me in Stardust.mp3",
                "Afterglow.mp3",
            ],
        )
        self.assertEqual(contract["post_final_occurrence_count"], 4)
        self.assertTrue(result.manifest["a1"]["gap_inserts_timeline_frames"])
        self.assertEqual(result.manifest["a1"]["a1_removed_frames"], 0)
        self.assertEqual(result.manifest["a1"]["inserted_gap_total_frames"], 120)

        root = ET.fromstring(result.xml)
        self.assertEqual(root.get("version"), "1.10")
        fmt = root.find("./resources/format")
        self.assertEqual((fmt.get("frameDuration"), fmt.get("width"), fmt.get("height")), ("1/60s", "3840", "2160"))
        self.assertEqual(root.find("./resources/format[@id='r1']").get("frameDuration"), "1/30s")
        sequence = root.find("./library/event/project/sequence")
        self.assertEqual(sequence.get("format"), "r0")
        self.assertEqual(frames(sequence.get("tcStart")), 216_000)
        self.assertEqual(frames(sequence.get("duration")), 1_360)
        spine = sequence.find("spine")
        primary = [item for item in list(spine) if item.get("lane") is None]
        self.assertEqual(
            [(frames(item.get("offset")) - 216_000, frames(item.get("duration"))) for item in primary],
            [
                (0, 260),
                (260, 340),
                (600, 60),
                (660, 200),
                (860, 60),
                (920, 200),
                (1120, 120),
                (1240, 120),
            ],
        )

        connected: list[tuple[ET.Element, int, int]] = []
        for parent in primary:
            parent_record = frames(parent.get("offset")) - 216_000
            parent_source = frames(parent.get("start"))
            for child in list(parent):
                if child.get("lane") is None:
                    continue
                start = parent_record + frames(child.get("offset")) - parent_source
                connected.append((child, start, frames(child.get("duration"))))

        a1 = sorted((start, duration) for child, start, duration in connected if child.get("lane") == "2")
        self.assertEqual(
            a1,
            [(260, 340), (660, 200), (920, 200), (1120, 120)],
        )
        for gap in ((600, 660), (860, 920)):
            self.assertFalse(any(max(start, gap[0]) < min(start + duration, gap[1]) for start, duration in a1))

        intros = [(child, start, duration) for child, start, duration in connected if child.get("name", "").startswith("GSC V2 Intro")]
        self.assertEqual([(start, duration, start + duration) for _, start, duration in intros], [(360, 300, 660)])
        self.assertEqual(intros[0][0].get("lane"), "1")
        self.assertIsNone(intros[0][0].find("audio"))

        a2 = sorted((start, duration) for child, start, duration in connected if child.get("lane") == "3")
        self.assertEqual(
            a2,
            [
                (0, 260),
                (260, 400),
                (660, 120),
                (780, 140),
                (920, 100),
                (1020, 50),
                (1070, 50),
                (1120, 50),
                (1170, 70),
            ],
        )
        a2_nodes = sorted(
            (
                start,
                child,
            )
            for child, start, _duration in connected
            if child.get("lane") == "3"
        )
        self.assertEqual(
            [node.get("name") for _start, node in a2_nodes],
            [row.asset.name for row in self.valid_spec().bgm_a2],
        )

        carousel = next(item for item in primary if item.get("name", "").startswith("GSC Member Carousel V1"))
        slices = [item for item in list(carousel) if item.get("name", "").startswith("Member Carousel V2")]
        self.assertEqual(len(slices), 2)
        self.assertEqual([frames(item.get("duration")) for item in slices], [40, 80])
        self.assertEqual(
            [item.find("./adjust-crop/trim-rect").get("bottom") for item in slices],
            ["24.537037", "24.537037"],
        )

        outro = primary[-1]
        linked = next(item for item in list(outro) if item.get("lane") == "4")
        self.assertEqual(frames(linked.get("duration")), 120)
        video_ref = outro.find("video").get("ref")
        audio_ref = linked.find("audio").get("ref")
        assets = {item.get("id"): item for item in root.findall("./resources/asset")}
        self.assertNotEqual(video_ref, audio_ref)
        self.assertEqual(
            assets[video_ref].find("media-rep").get("src"),
            assets[audio_ref].find("media-rep").get("src"),
        )

    def test_dual_screen_opening_and_post_final_share_one_full_media_resource(self) -> None:
        spec = self.valid_spec()
        full_dual = replace(
            spec.bgm_a2[0].asset,
            source_start_frame=0,
            duration_frames=5_000,
        )
        rows = list(spec.bgm_a2)
        rows[0] = replace(rows[0], asset=full_dual, source_start_frame=764)
        rows[5] = replace(rows[5], asset=full_dual, source_start_frame=0)

        result = assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

        root = ET.fromstring(result.xml)
        resources = [
            node
            for node in root.findall("./resources/asset")
            if node.get("name") == "Dual Screen Lovelife.mp3"
        ]
        self.assertEqual(len(resources), 1)
        self.assertEqual(frames(resources[0].get("start")), 0)
        self.assertEqual(frames(resources[0].get("duration")), 5_000)
        ref = resources[0].get("id")
        placements = [
            node
            for node in root.iter("asset-clip")
            if node.get("ref") == ref and node.get("lane") == "3"
        ]
        self.assertEqual(
            sorted(frames(node.get("start")) for node in placements),
            [0, 764],
        )
        dual_manifest_rows = [
            row
            for row in result.manifest["a2"]["segments"]
            if row["asset"]["name"] == "Dual Screen Lovelife.mp3"
        ]
        self.assertEqual(
            [row["media_source_range"] for row in dual_manifest_rows],
            [[0, 5_000], [0, 5_000]],
        )
        self.assertEqual(
            dual_manifest_rows[0]["available_handle_frames"]["left"],
            764,
        )

    def test_same_uri_with_conflicting_media_descriptor_fails_closed(self) -> None:
        spec = self.valid_spec()
        full_dual = replace(spec.bgm_a2[0].asset, duration_frames=5_000)
        conflicting_dual = replace(full_dual, duration_frames=4_000)
        rows = list(spec.bgm_a2)
        rows[0] = replace(rows[0], asset=full_dual, source_start_frame=764)
        rows[5] = replace(rows[5], asset=conflicting_dual)

        with self.assertRaisesRegex(
            GscGymFcpxmlError,
            "conflicting full-media descriptors",
        ):
            assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

    def test_same_explicit_inputs_produce_identical_xml_and_manifest(self) -> None:
        first = assemble_gsc_gym_fcpxml(self.valid_spec())
        second = assemble_gsc_gym_fcpxml(self.valid_spec())
        self.assertEqual(first.xml, second.xml)
        self.assertEqual(first.manifest, second.manifest)

    def test_incomplete_a2_plan_fails_closed(self) -> None:
        spec = self.valid_spec()
        broken = replace(spec, bgm_a2=spec.bgm_a2[:-1])
        with self.assertRaisesRegex(GscGymFcpxmlError, "exact end"):
            assemble_gsc_gym_fcpxml(broken)

    def test_noncontiguous_carousel_v2_fails_closed(self) -> None:
        spec = self.valid_spec()
        broken_carousel = replace(
            spec.carousel,
            v2_slices=(spec.carousel.v2_slices[0], replace(spec.carousel.v2_slices[1], record_start_frame=1161)),
        )
        with self.assertRaisesRegex(GscGymFcpxmlError, "exact contiguous start"):
            assemble_gsc_gym_fcpxml(replace(spec, carousel=broken_carousel))

    def test_reserved_and_battle_audio_lineage_rules_fail_closed(self) -> None:
        spec = self.valid_spec()
        golden = self.asset("F:/GSCNewLayout/audio/Golden Goose.mp3", 800)
        rows = list(spec.bgm_a2)
        rows[1] = replace(rows[1], asset=golden)
        with self.assertRaisesRegex(GscGymFcpxmlError, "Golden Goose"):
            assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

        rows = list(spec.bgm_a2)
        rows[2] = replace(rows[2], asset=self.asset("F:/music/not-gsc-battle.mp3", 500))
        with self.assertRaisesRegex(GscGymFcpxmlError, "original MP3|not lineaged"):
            assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

    def test_nonbattle_repeat_nonfresh_handoff_and_wrong_suffix_fail_closed(self) -> None:
        spec = self.valid_spec()

        rows = list(spec.bgm_a2)
        rows[-1] = replace(rows[-1], asset=rows[1].asset)
        with self.assertRaisesRegex(GscGymFcpxmlError, "may not repeat"):
            assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

        rows = list(spec.bgm_a2)
        rows[3] = replace(rows[3], source_start_frame=1)
        with self.assertRaisesRegex(GscGymFcpxmlError, "fresh source-zero"):
            assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

        rows = list(spec.bgm_a2)
        rows[6] = replace(rows[6], asset=spec.bgm_a2[7].asset)
        rows[7] = replace(rows[7], asset=spec.bgm_a2[6].asset)
        with self.assertRaisesRegex(GscGymFcpxmlError, "exactly four identity starts"):
            assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

    def test_post_final_fourth_identity_must_own_the_remainder(self) -> None:
        spec = self.valid_spec()
        extra = self.asset("F:/GSCNewLayout/audio/One More Track.mp3", 500)
        rows = list(spec.bgm_a2)
        rows[-1] = replace(rows[-1], duration_frames=35, fade_out_frames=0)
        rows.append(
            BgmSegment(
                1205,
                0,
                35,
                extra,
                "carousel",
                "forbidden fifth post-final identity",
                -6.0,
                fade_out_frames=30,
            )
        )
        with self.assertRaisesRegex(GscGymFcpxmlError, "exactly four identity starts"):
            assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

    def test_source_native_carousel_split_is_one_continuous_occurrence(self) -> None:
        spec = self.valid_spec()
        rows = list(spec.bgm_a2)
        rows.insert(
            7,
            BgmSegment(
                1120,
                50,
                10,
                spec.bgm_a2[6].asset,
                "carousel",
                "source-native carousel continuation",
                -6.0,
            ),
        )
        rows[8] = replace(rows[8], record_start_frame=1130)
        rows[9] = replace(rows[9], record_start_frame=1180, duration_frames=60)
        result = assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))
        post_final = result.manifest["a2"]["nonbattle_bgm_contract"]
        self.assertEqual(post_final["post_final_occurrence_count"], 4)
        clouds_occurrence = next(
            item for item in post_final["occurrences"]
            if item["identity"].casefold() == "motivated by clouds.mp3"
        )
        self.assertEqual(clouds_occurrence["segment_indices"], [7, 8])

    def test_renamed_or_a2_fades_derivative_is_rejected(self) -> None:
        spec = self.valid_spec()
        derivative = replace(
            spec.bgm_a2[1].asset,
            path=Path("F:/render/a2-fades/Just_Thinking__s0_d400.wav"),
            name="Just_Thinking__s0_d400.wav",
            duration_frames=400,
            origin_path=spec.bgm_a2[1].asset.path,
        )
        rows = list(spec.bgm_a2)
        rows[1] = replace(rows[1], asset=derivative)
        with self.assertRaisesRegex(GscGymFcpxmlError, "original MP3"):
            assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

    def test_battle_without_room_for_distinct_gap_fails_closed(self) -> None:
        spec = self.valid_spec()
        battles = (
            spec.battles[0],
            replace(spec.battles[1], start_frame=780),
        )
        with self.assertRaisesRegex(GscGymFcpxmlError, "distinct 60-frame A1 gap"):
            assemble_gsc_gym_fcpxml(replace(spec, battles=battles))

    def test_gap_that_truncates_dialogue_fails_closed(self) -> None:
        spec = self.valid_spec()
        dialogue = list(spec.dialogue_a1)
        dialogue[0] = replace(dialogue[0], duration_frames=341)
        with self.assertRaisesRegex(
            GscGymFcpxmlError,
            "A1 timeline holes must exactly equal ordinal-1 battle gaps",
        ):
            assemble_gsc_gym_fcpxml(
                replace(spec, dialogue_a1=tuple(dialogue))
            )

    def test_gap_bridge_must_extend_the_complete_incoming_clip(self) -> None:
        spec = self.valid_spec()
        body = list(spec.body_v1)
        body[1] = replace(body[1], source_start_frame=441)
        with self.assertRaisesRegex(
            GscGymFcpxmlError,
            "extend the incoming segment left by exactly 60 source frames",
        ):
            assemble_gsc_gym_fcpxml(replace(spec, body_v1=tuple(body)))

    def test_intro_may_not_overlap_a_prior_battle(self) -> None:
        spec = self.valid_spec()
        rival_intro = IntroOverlay(
            spec.battles[0].intro.asset,
            "Silver",
            "rival",
        )
        battles = (
            spec.battles[0],
            replace(
                spec.battles[1],
                role="rival",
                intro=rival_intro,
                intro_eligible=True,
            ),
        )
        with self.assertRaisesRegex(
            GscGymFcpxmlError,
            "overlaps the opening, a prior battle, or another V2 intro",
        ):
            assemble_gsc_gym_fcpxml(replace(spec, battles=battles))

    def test_structured_battle_ids_fades_and_shuffle_contract_fail_closed(self) -> None:
        spec = self.valid_spec()
        rows = list(spec.bgm_a2)
        rows[2] = replace(rows[2], fade_in_frames=0)
        with self.assertRaisesRegex(GscGymFcpxmlError, "transition fade contract"):
            assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

        rows = list(spec.bgm_a2)
        rows[2] = replace(rows[2], battle_id="trainer-1")
        with self.assertRaisesRegex(GscGymFcpxmlError, "declares"):
            assemble_gsc_gym_fcpxml(replace(spec, bgm_a2=tuple(rows)))

        with self.assertRaisesRegex(GscGymFcpxmlError, "immediate repeat"):
            assemble_gsc_gym_fcpxml(
                replace(
                    spec,
                    bgm_a2=tuple(
                        replace(row, asset=spec.bgm_a2[2].asset)
                        if row.role == "battle"
                        else row
                        for row in spec.bgm_a2
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
