from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from resolve_mcp.orchestrator.gsc_gym_bgm import (
    BATTLE_EDGE_FADE_FRAMES,
    BattleAudioRange,
    GscGymBgmError,
    OPENING_AUDIO_SOURCE_OFFSET_FRAMES,
    plan_gsc_gym_bgm,
)
from resolve_mcp.orchestrator.gsc_gym_fcpxml import MediaAsset


class GscGymBgmTests(unittest.TestCase):
    @staticmethod
    def asset(path: str, duration: int) -> MediaAsset:
        return MediaAsset(Path(path), Path(path).name, duration)

    def required(self, opening: MediaAsset, duration: int = 2_000) -> tuple[MediaAsset, ...]:
        return (
            opening,
            self.asset("F:/Programming/GSCNewLayout/audio/bgm/Motivated By Clouds.mp3", duration),
            self.asset("F:/Programming/GSCNewLayout/audio/bgm/Roll Me in Stardust.mp3", duration),
        )

    @staticmethod
    def identity_starts(rows):
        result = []
        for index, row in enumerate(rows):
            if row.role == "battle":
                continue
            previous = rows[index - 1] if index else None
            if previous is None or previous.role == "battle" or previous.asset.path != row.asset.path:
                result.append(row)
        return result

    def test_every_positive_battle_gap_gets_fresh_track_and_final_sequence_is_complete(self) -> None:
        opening = self.asset(
            "F:/Programming/GSCNewLayout/audio/bgm/Dual Screen Lovelife.mp3",
            2_000,
        )
        general = (
            self.asset("F:/Programming/GSCNewLayout/audio/bgm/Apricot.mp3", 5_000),
            self.asset("F:/Programming/GSCNewLayout/audio/bgm/Aura.mp3", 5_000),
        )
        battle_one = self.asset(
            "F:/Programming/GSCNewLayout/audio/Gen 2 battle audio/143 Battle.mp3",
            500,
        )
        battle_two = self.asset(
            "F:/Programming/GSCNewLayout/audio/Gen 2 battle audio/118 Battle.mp3",
            400,
        )
        rows = plan_gsc_gym_bgm(
            opening_track=opening,
            post_final_required_tracks=self.required(opening),
            randomized_nonbattle_tracks=general,
            battles=(
                BattleAudioRange("whitney-attempt-1", 900, 1_200, battle_one),
                BattleAudioRange("whitney-attempt-2", 1_500, 2_100, battle_two),
            ),
            carousel_start_frame=3_000,
            fill_end_frame=3_500,
        )
        self.assertEqual(rows[0].record_start_frame, 0)
        self.assertEqual(rows[0].source_start_frame, OPENING_AUDIO_SOURCE_OFFSET_FRAMES)
        self.assertIs(rows[0].asset, opening)
        self.assertEqual(rows[0].asset.source_start_frame, 0)
        self.assertEqual(rows[0].asset.duration_frames, opening.duration_frames)
        battles = [row for row in rows if row.role == "battle"]
        self.assertEqual({row.battle_id for row in battles}, {"whitney-attempt-1", "whitney-attempt-2"})
        self.assertEqual(sum(row.duration_frames for row in battles), 900)
        self.assertEqual(rows[-1].record_end_frame, 3_500)
        self.assertEqual(rows[-1].role, "carousel")
        self.assertEqual(rows[-1].fade_out_frames, BATTLE_EDGE_FADE_FRAMES)

        # A positive post-battle gap discards the prior identity and starts a
        # new randomized source at frame zero.
        before = next(row for row in rows if row.record_end_frame == 900)
        after = next(row for row in rows if row.record_start_frame == 1_200)
        self.assertNotEqual(after.asset.path, before.asset.path)
        self.assertEqual(after.source_start_frame, 0)
        self.assertEqual(before.fade_out_frames, 30)
        self.assertEqual(after.fade_in_frames, 30)

        suffix = [row for row in self.identity_starts(rows) if row.record_start_frame >= 2_100]
        self.assertEqual(
            [row.asset.name for row in suffix[:4]],
            [
                "Dual Screen Lovelife.mp3",
                "Motivated By Clouds.mp3",
                "Roll Me in Stardust.mp3",
                "Aura.mp3",
            ],
        )
        self.assertEqual([row.record_start_frame for row in suffix[:4]], [2_100, 2_450, 2_800, 3_150])
        self.assertTrue(all(row.source_start_frame == 0 for row in suffix[:4]))

    def test_zero_gap_retry_handoff_restarts_each_physical_battle_source(self) -> None:
        opening = self.asset(
            "F:/Programming/GSCNewLayout/audio/bgm/Dual Screen Lovelife.mp3",
            2_000,
        )
        filler = self.asset(
            "F:/Programming/GSCNewLayout/audio/bgm/Aura.mp3",
            5_000,
        )
        first_theme = replace(
            self.asset(
                "F:/Programming/GSCNewLayout/audio/Gen 2 battle audio/143 Battle.mp3",
                150,
            ),
            source_start_frame=17,
        )
        retry_theme = replace(
            self.asset(
                "F:/Programming/GSCNewLayout/audio/Gen 2 battle audio/118 Battle.mp3",
                150,
            ),
            source_start_frame=23,
        )
        rows = plan_gsc_gym_bgm(
            opening_track=opening,
            post_final_required_tracks=self.required(opening),
            randomized_nonbattle_tracks=(filler,),
            battles=(
                BattleAudioRange("whitney-attempt-1", 900, 1_100, first_theme),
                BattleAudioRange("whitney-attempt-2", 1_100, 1_300, retry_theme),
            ),
            carousel_start_frame=1_800,
            fill_end_frame=2_300,
        )

        first_slices = {
            battle_id: next(
                row
                for row in rows
                if row.role == "battle" and row.battle_id == battle_id
            )
            for battle_id in ("whitney-attempt-1", "whitney-attempt-2")
        }
        self.assertEqual(first_slices["whitney-attempt-1"].record_start_frame, 900)
        self.assertEqual(first_slices["whitney-attempt-1"].source_start_frame, 17)
        self.assertEqual(
            first_slices["whitney-attempt-1"].source_start_frame,
            first_theme.source_start_frame,
        )
        self.assertEqual(first_slices["whitney-attempt-2"].record_start_frame, 1_100)
        self.assertEqual(first_slices["whitney-attempt-2"].source_start_frame, 23)
        self.assertEqual(
            first_slices["whitney-attempt-2"].source_start_frame,
            retry_theme.source_start_frame,
        )
        direct = next(row for row in rows if row.record_start_frame == 1_100)
        self.assertEqual(direct.role, "battle")
        self.assertEqual(direct.battle_id, "whitney-attempt-2")
        self.assertFalse(
            any(
                row.role != "battle" and row.record_start_frame == 1_100
                for row in rows
            )
        )

    def test_long_battle_loops_one_assigned_track_without_internal_fades(self) -> None:
        opening = self.asset(
            "F:/Programming/GSCNewLayout/audio/bgm/Dual Screen Lovelife.mp3",
            2_000,
        )
        general = self.asset("F:/Programming/GSCNewLayout/audio/bgm/Aura.mp3", 5_000)
        battle = self.asset(
            "F:/Programming/GSCNewLayout/audio/Gen 2 battle audio/143 Battle.mp3",
            200,
        )
        rows = plan_gsc_gym_bgm(
            opening_track=opening,
            post_final_required_tracks=self.required(opening),
            randomized_nonbattle_tracks=(general, self.asset("F:/Programming/GSCNewLayout/audio/bgm/B.mp3", 5_000)),
            battles=(BattleAudioRange("falkner-1", 700, 1_250, battle),),
            carousel_start_frame=1_500,
            fill_end_frame=1_800,
        )
        loops = [row for row in rows if row.role == "battle"]
        self.assertEqual([row.duration_frames for row in loops], [200, 200, 150])
        self.assertEqual([row.fade_in_frames for row in loops], [30, 0, 0])
        self.assertEqual([row.fade_out_frames for row in loops], [0, 0, 30])

    def test_reserved_tracks_and_wrong_battle_lineage_fail_closed(self) -> None:
        opening = self.asset(
            "F:/Programming/GSCNewLayout/audio/bgm/Dual Screen Lovelife.mp3",
            2_000,
        )
        golden = self.asset("F:/Programming/GSCNewLayout/audio/bgm/Golden Goose.mp3", 2_000)
        battle = self.asset("F:/music/not-the-gsc-library.mp3", 500)
        with self.assertRaisesRegex(GscGymBgmError, "Reserved track"):
            plan_gsc_gym_bgm(
                opening_track=opening,
                post_final_required_tracks=self.required(opening),
                randomized_nonbattle_tracks=(golden,),
                battles=(),
                carousel_start_frame=1_000,
                fill_end_frame=1_500,
            )
        with self.assertRaisesRegex(GscGymBgmError, "not lineaged"):
            plan_gsc_gym_bgm(
                opening_track=opening,
                post_final_required_tracks=self.required(opening),
                randomized_nonbattle_tracks=(),
                battles=(BattleAudioRange("x", 800, 900, battle),),
                carousel_start_frame=1_000,
                fill_end_frame=1_500,
            )

    def test_duplicate_nonbattle_asset_fails_closed(self) -> None:
        opening = self.asset(
            "F:/Programming/GSCNewLayout/audio/bgm/Dual Screen Lovelife.mp3",
            2_000,
        )
        general = self.asset("F:/Programming/GSCNewLayout/audio/bgm/Aura.mp3", 2_000)
        with self.assertRaisesRegex(GscGymBgmError, "repeated"):
            plan_gsc_gym_bgm(
                opening_track=opening,
                post_final_required_tracks=self.required(opening),
                randomized_nonbattle_tracks=(general, replace(general)),
                battles=(),
                carousel_start_frame=1_000,
                fill_end_frame=1_500,
            )

    def test_required_post_final_order_and_random_reservations_fail_closed(self) -> None:
        opening = self.asset(
            "F:/Programming/GSCNewLayout/audio/bgm/Dual Screen Lovelife.mp3",
            2_000,
        )
        motivated, roll = self.required(opening)[1:]
        battle = self.asset(
            "F:/Programming/GSCNewLayout/audio/Gen 2 battle audio/143 Battle.mp3",
            500,
        )
        random_track = self.asset("F:/Programming/GSCNewLayout/audio/bgm/Aura.mp3", 2_000)
        with self.assertRaisesRegex(GscGymBgmError, "must be exactly"):
            plan_gsc_gym_bgm(
                opening_track=opening,
                post_final_required_tracks=(opening, roll, motivated),
                randomized_nonbattle_tracks=(random_track,),
                battles=(BattleAudioRange("x", 800, 900, battle),),
                carousel_start_frame=1_200,
                fill_end_frame=1_500,
            )
        with self.assertRaisesRegex(GscGymBgmError, "Reserved track"):
            plan_gsc_gym_bgm(
                opening_track=opening,
                post_final_required_tracks=self.required(opening),
                randomized_nonbattle_tracks=(motivated, random_track),
                battles=(BattleAudioRange("x", 800, 900, battle),),
                carousel_start_frame=1_200,
                fill_end_frame=1_500,
            )

    def test_post_final_rebalances_to_exact_next_unused_identity(self) -> None:
        opening = self.asset(
            "F:/Programming/GSCNewLayout/audio/bgm/Dual Screen Lovelife.mp3",
            2_000,
        )
        battle = self.asset(
            "F:/Programming/GSCNewLayout/audio/Gen 2 battle audio/143 Battle.mp3",
            500,
        )
        short = self.asset("F:/Programming/GSCNewLayout/audio/bgm/Short.mp3", 50)
        long = self.asset("F:/Programming/GSCNewLayout/audio/bgm/Long.mp3", 2_000)
        rows = plan_gsc_gym_bgm(
            opening_track=opening,
            post_final_required_tracks=self.required(opening),
            randomized_nonbattle_tracks=(short, long),
            battles=(BattleAudioRange("x", 800, 900, battle),),
            carousel_start_frame=1_200,
            fill_end_frame=1_500,
        )
        suffix = [
            row
            for row in self.identity_starts(rows)
            if row.record_start_frame >= 900
        ]
        self.assertEqual(len(suffix), 4)
        self.assertEqual(suffix[-1].asset.name, "Short.mp3")
        self.assertEqual(suffix[-1].duration_frames, 50)
        self.assertEqual(suffix[-1].record_end_frame, 1_500)


if __name__ == "__main__":
    unittest.main()
