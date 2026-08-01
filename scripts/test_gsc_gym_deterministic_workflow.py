from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from resolve_mcp.orchestrator.gsc_gym_deterministic import (
    BATTLE_GAP_FRAMES,
    BATTLE_INTRO_FRAMES,
    FAIRLIGHT_PRESET_NAME,
    FAIRLIGHT_PRESET_TYPE,
    INTRO_TRACK,
    OUTRO_TRACK,
    POST_FINAL_REQUIRED_TRACKS,
    WORKFLOW_FAIRLIGHT_FINAL_STAGE_CONTRACT,
    WORKFLOW_BATTLE_GAP_GEOMETRY,
    WORKFLOW_BATTLE_POPULATION_POLICY,
    WORKFLOW_BATTLE_START_CANDIDATE_AUDIT,
    WORKFLOW_NONBATTLE_REPEAT_POLICY,
    WORKFLOW_PARTY_MEMBER_KO_CONTRACT,
    WORKFLOW_PHYSICAL_ATTEMPT_BGM_START_CONTRACT,
    WORKFLOW_POST_BATTLE_BGM_POLICY,
    WORKFLOW_POST_FINAL_BGM_SEQUENCE,
    WORKFLOW_SAME_TRAINER_RETRY_CONTRACT,
    WORKFLOW_ID,
    align_obs_chapters_to_session,
    build_a1_gap_plan,
    build_overlay_intro_plan,
    canonical_battle_groups,
    canonical_battle_attempts,
    canonical_battles,
    canonical_carousel_boundary,
    choose_nonbattle_tracks,
    choose_battle_tracks,
    map_battle_groups_to_source,
    map_battle_attempts_to_source,
    validate_mapped_geometry,
    validate_zero_llm_workflow,
    GscGymDeterministicError,
    IncompleteBattleTelemetryError,
)


class GscGymDeterministicTests(unittest.TestCase):
    @staticmethod
    def _event(frame: int, category: str, name: str, data: dict | None = None) -> dict:
        return {
            "tElapsedMs": frame * 1000 / 60,
            "category": category,
            "name": name,
            "data": data or {},
        }

    def _attempt_events(
        self,
        *,
        base: int,
        trainer_class: str,
        trainer_id: int,
        trainer: str,
        win: bool,
        main: bool = False,
    ) -> list[dict]:
        data = {
            "trainer": trainer,
            "trainerClass": trainer_class,
            "trainerId": trainer_id,
            "checkpointKey": trainer.casefold() if main else None,
            "isMainBoss": main,
        }
        rows = [
            self._event(base, "state", "mapper-state", {"from": "Overworld", "to": "To Battle"}),
            self._event(base + 5, "battle", "battle-start", data),
            self._event(
                base + 5,
                "trainer-ai",
                "gym-leader-battle-start",
                {"trainerClass": "ERIKA", "reason": "battle-start", "modelHistoryDeviated": False},
            ),
            self._event(base + 6, "state", "mapper-state", {"from": "To Battle", "to": "Battle"}),
        ]
        if win:
            rows.append(self._event(base + 60, "battle", "battle-end", {**data, "outcome": "Win"}))
        rows.append(self._event(base + 60, "state", "mapper-state", {"from": "Battle", "to": "From Battle"}))
        return rows

    def test_reserved_tracks_never_enter_random_bed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in (*POST_FINAL_REQUIRED_TRACKS, OUTRO_TRACK, "A.mp3", "B.mp3"):
                (root / name).write_bytes(b"x")
            selected = choose_nonbattle_tracks(root, seed="01" * 32)
            self.assertEqual({path.name for path in selected}, {"A.mp3", "B.mp3"})

    def test_missing_required_post_final_track_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in (INTRO_TRACK, OUTRO_TRACK, "Motivated By Clouds.mp3", "A.mp3"):
                (root / name).write_bytes(b"x")
            with self.assertRaisesRegex(GscGymDeterministicError, "Roll Me in Stardust"):
                choose_nonbattle_tracks(root, seed="01" * 32)

    def test_battle_shuffle_bags_have_no_immediate_repeat(self) -> None:
        paths = [Path(f"{letter}.mp3") for letter in "ABCDEF"]
        selected = choose_battle_tracks(paths, count=15, seed="02" * 32)
        self.assertEqual(len(selected), 15)
        self.assertEqual(set(selected[:6]), set(paths))
        self.assertFalse(any(a == b for a, b in zip(selected, selected[1:])))

    def test_exact_parser_ignores_ai_controller_starts(self) -> None:
        events = self._attempt_events(
            base=60,
            trainer_class="FALKNER",
            trainer_id=1,
            trainer="Falkner",
            win=True,
            main=True,
        )
        starts = canonical_battles(events)
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["battle_key"], "FALKNER:1")
        groups = canonical_battle_groups(events)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["attempt_count"], 1)
        self.assertEqual(groups[0]["outcome"], "Win")

    def test_retries_collapse_but_every_group_gets_a_gap(self) -> None:
        events = [
            *self._attempt_events(
                base=60,
                trainer_class="RIVAL1",
                trainer_id=4,
                trainer="Silver",
                win=False,
                main=True,
            ),
            *self._attempt_events(
                base=140,
                trainer_class="RIVAL1",
                trainer_id=4,
                trainer="Silver",
                win=True,
                main=True,
            ),
            *self._attempt_events(
                base=240,
                trainer_class="YOUNGSTER",
                trainer_id=3,
                trainer="Honest Abe",
                win=True,
            ),
        ]
        groups = canonical_battle_groups(events)
        self.assertEqual([row["attempt_count"] for row in groups], [2, 1])
        gaps = build_a1_gap_plan(groups)
        self.assertEqual(len(gaps), 2)
        self.assertTrue(all(row["duration_frames"] == BATTLE_GAP_FRAMES for row in gaps))

    def test_mapped_retries_do_not_receive_additional_a1_gaps(self) -> None:
        def attempt(
            attempt_id: str,
            key: str,
            identity_ordinal: int,
            start: int,
            end: int,
        ) -> dict:
            return {
                "attempt_id": attempt_id,
                "battle_key": key,
                "canonical_identity": key,
                "identity_attempt_ordinal": identity_ordinal,
                "identity": key,
                "role": "leader" if key == "MORTY:1" else "trainer",
                "trainer_class": "MORTY" if key == "MORTY:1" else "YOUNGSTER",
                "trainer_id": 1,
                "session_start_frame": start,
                "session_end_frame": end,
                "source_start_frame": start,
                "source_end_frame": end,
                "source_duration_frames": end - start,
                "source_start_authority": "fixture",
                "source_end_authority": "fixture",
                "end_authority": "fixture",
                "outcome": "Unknown",
            }

        physical = [
            attempt("MORTY:1:attempt-1", "MORTY:1", 1, 100, 200),
            attempt("MORTY:1:attempt-2", "MORTY:1", 2, 300, 400),
            attempt("YOUNGSTER:1:attempt-1", "YOUNGSTER:1", 1, 500, 600),
        ]
        gaps = build_a1_gap_plan(physical)
        self.assertEqual(len(gaps), 2)
        self.assertEqual(
            [row["battle_key"] for row in gaps],
            ["MORTY:1", "YOUNGSTER:1"],
        )

        nonconsecutive = build_a1_gap_plan([physical[0], physical[2], physical[1]])
        self.assertEqual(
            [row["battle_key"] for row in nonconsecutive],
            ["MORTY:1", "YOUNGSTER:1"],
        )
        self.assertEqual(build_a1_gap_plan([physical[1]]), [])

    def test_missing_generic_start_fails_closed(self) -> None:
        events = [
            self._event(60, "state", "mapper-state", {"from": "Overworld", "to": "To Battle"}),
            self._event(61, "trainer-ai", "gym-leader-battle-start", {"trainerClass": "ERIKA"}),
            self._event(62, "state", "mapper-state", {"from": "To Battle", "to": "Battle"}),
            self._event(100, "state", "mapper-state", {"from": "Battle", "to": "From Battle"}),
        ]
        with self.assertRaises(GscGymDeterministicError):
            canonical_battle_groups(events)

    def test_open_physical_interval_has_typed_recovery_signal(self) -> None:
        events = [
            self._event(60, "state", "mapper-state", {"from": "Overworld", "to": "To Battle"}),
            self._event(
                61,
                "battle",
                "battle-start",
                {"trainer": "Falkner", "trainerClass": "FALKNER", "trainerId": 1},
            ),
            self._event(62, "state", "mapper-state", {"from": "To Battle", "to": "Battle"}),
        ]
        with self.assertRaises(IncompleteBattleTelemetryError):
            canonical_battle_attempts(events)

    def test_overlay_intros_overlap_v1_and_end_at_gap_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            leaders = root / "leaders"
            rivals = root / "rivals"
            leaders.mkdir()
            rivals.mkdir()
            (leaders / "falkner-battle-intro.mov").write_bytes(b"leader")
            (rivals / "silver-initial-cyndaquil-battle-intro.mov").write_bytes(b"rival")
            rows = build_overlay_intro_plan(
                [
                    {
                        "session_start_frame": 1000,
                        "final_timeline_start_frame": 1000,
                        "role": "leader",
                        "identity": "Falkner",
                        "battle_key": "FALKNER:1",
                        "trainer_class": "FALKNER",
                        "trainer_id": 1,
                        "checkpoint_key": "falkner",
                    },
                    {
                        "session_start_frame": 2000,
                        "final_timeline_start_frame": 2000,
                        "role": "rival",
                        "identity": "Rival 1",
                        "battle_key": "RIVAL1:2",
                        "trainer_class": "RIVAL1",
                        "trainer_id": 2,
                    },
                ],
                leaders_dir=leaders,
                rivals_dir=rivals,
            )
            self.assertEqual(rows[0]["record_start_frame"], 700)
            self.assertEqual(rows[0]["record_end_frame"], 1000)
            self.assertEqual(rows[0]["a1_gap_start_frame"], 940)
            self.assertEqual(rows[0]["a1_gap_end_frame"], 1000)
            self.assertTrue(rows[0]["ends_at_a1_gap_end"])
            self.assertEqual(rows[0]["v1_policy"], "continuous_under_v2_overlay")

    def test_rival_asset_uses_trainer_id_not_observed_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            leaders = root / "leaders"
            rivals = root / "rivals"
            leaders.mkdir()
            rivals.mkdir()
            expected = rivals / "silver-azalea-grass-battle-intro.mov"
            expected.write_bytes(b"rival")
            rows = build_overlay_intro_plan(
                [{
                    "session_start_frame": 1000,
                    "role": "rival",
                    "identity": "Silver",
                    "battle_key": "RIVAL1:4",
                    "trainer_class": "RIVAL1",
                    "trainer_id": 4,
                }],
                leaders_dir=leaders,
                rivals_dir=rivals,
                boundary_is_final_timeline=False,
            )
            self.assertEqual(Path(rows[0]["asset"]), expected.resolve())

    def test_rival_starter_type_comes_from_exact_rom_trainer_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            leaders = root / "leaders"
            rivals = root / "rivals"
            leaders.mkdir()
            rivals.mkdir()
            expected = rivals / "silver-burnedtower-water-battle-intro.mov"
            expected.write_bytes(b"rival")
            rows = build_overlay_intro_plan(
                [{
                    "session_start_frame": 1000,
                    "role": "rival",
                    "identity": "Silver",
                    "battle_key": "RIVAL1:9",
                    "trainer_class": "RIVAL1",
                    "trainer_id": 9,
                }],
                leaders_dir=leaders,
                rivals_dir=rivals,
                boundary_is_final_timeline=False,
            )
            self.assertEqual(Path(rows[0]["asset"]), expected.resolve())

    def test_manual_gap_and_intro_drift_are_rejected(self) -> None:
        gap = {
            "battle_key": "BUGSY:1",
            "record_start_frame": 100,
            "record_end_frame": 100 + BATTLE_GAP_FRAMES + 7,
        }
        intro = {
            "battle_key": "BUGSY:1",
            "record_start_frame": 200,
            "record_end_frame": 200 + BATTLE_INTRO_FRAMES - 10,
        }
        with self.assertRaises(GscGymDeterministicError):
            validate_mapped_geometry([gap], [intro])

    def test_carousel_requires_completed_cycle_and_channel_exp_handoff(self) -> None:
        self.assertIsNone(canonical_carousel_boundary([]))
        events = [
            self._event(500, "view", "member-carousel-started"),
            self._event(600, "view", "member-carousel-ended"),
            self._event(600, "view", "channel-exp-bar-shown"),
        ]
        boundary = canonical_carousel_boundary(events)
        self.assertIsNotNone(boundary)
        assert boundary is not None
        self.assertEqual(boundary["session_frame"], 500)
        self.assertEqual(boundary["end_session_frame"], 600)
        self.assertIsNone(
            canonical_carousel_boundary([self._event(500, "view", "member-carousel-start")])
        )

    def test_chapter_alignment_and_exact_group_mapping(self) -> None:
        chapters = [101, 247, 433, 701, 1019, 1391]
        marker_frames = [frame + 503 for frame in chapters]
        keys = [
            ("meta", "pokemon-changed"),
            ("event", "first-pokemon-received"),
            ("battle", "battle-start"),
            ("battle", "battle-end"),
            ("view", "post-battle-tiercard-shown"),
            ("view", "post-battle-tiercard-closed"),
        ]
        events = [
            self._event(frame, category, name)
            for frame, (category, name) in zip(marker_frames, keys)
        ]
        alignment = align_obs_chapters_to_session(
            chapters,
            events,
            minimum_matches=6,
            minimum_match_ratio=1.0,
            minimum_span_ratio=1.0,
        )
        self.assertEqual(alignment["offset_frame"], 503)
        group = {
            "battle_key": "FALKNER:1",
            "attempts": [{"start_event_index": 2}],
            "direct_end_event_index": 3,
        }
        mapped = map_battle_groups_to_source([group], alignment)
        self.assertEqual(mapped[0]["source_start_frame"], chapters[2])
        self.assertEqual(mapped[0]["source_end_frame"], chapters[3])

    def test_every_physical_retry_maps_to_an_independent_source_range(self) -> None:
        events = [
            *self._attempt_events(
                base=600,
                trainer_class="ERIKA",
                trainer_id=1,
                trainer="Erika",
                win=False,
                main=True,
            ),
            *self._attempt_events(
                base=800,
                trainer_class="ERIKA",
                trainer_id=1,
                trainer="Erika",
                win=True,
                main=True,
            ),
        ]
        attempts = canonical_battle_attempts(events)
        # Bind exact starts and the retry Win.  The first mapper exit is
        # deliberately unchaptered and proven by tight local brackets.
        marker_rows = []
        for event_index, event in enumerate(events):
            marker_rows.append(
                {
                    "event_index": event_index,
                    "marker_session_frame": round(event["tElapsedMs"] * 60 / 1000),
                    "chapter_frame": round(event["tElapsedMs"] * 60 / 1000) - 100,
                    "residual_frames": 0,
                }
            )
        # Remove only the first attempt's mapper exit so strict projection is
        # exercised while its neighboring events still bracket it.
        first_exit_index = attempts[0]["mapper_end_event_index"]
        matches = [row for row in marker_rows if row["event_index"] != first_exit_index]
        alignment = {"offset_frame": 100, "matches": matches}
        mapped = map_battle_attempts_to_source(attempts, alignment)
        self.assertEqual(len(mapped), 2)
        self.assertEqual(
            [row["attempt_id"] for row in mapped],
            ["ERIKA:1:attempt-1", "ERIKA:1:attempt-2"],
        )
        self.assertEqual([row["identity_attempt_ordinal"] for row in mapped], [1, 2])
        self.assertIsNotNone(mapped[0]["source_end_projection"])
        self.assertEqual(
            mapped[1]["source_end_authority"],
            "matched_embedded_OBS_chapter_for_exact_battle-end_Win",
        )

    def test_llm_or_review_steps_fail_closed(self) -> None:
        base = {
            "id": WORKFLOW_ID,
            "llm_tasks": [],
            "review_surfaces": [],
            "tooling": {
                "runtime_limit_seconds": 600,
                "outer_process_tree_watchdog_seconds": 600,
                "post_battle_bgm_transition_policy": WORKFLOW_POST_BATTLE_BGM_POLICY,
                "nonbattle_bgm_repeat_policy": WORKFLOW_NONBATTLE_REPEAT_POLICY,
                "post_final_bgm_sequence": WORKFLOW_POST_FINAL_BGM_SEQUENCE,
                "physical_attempt_bgm_start_contract": (
                    WORKFLOW_PHYSICAL_ATTEMPT_BGM_START_CONTRACT
                ),
                "battle_population": WORKFLOW_BATTLE_POPULATION_POLICY,
                "battle_a1_gap_geometry": WORKFLOW_BATTLE_GAP_GEOMETRY,
                "same_trainer_retry_contract": (
                    WORKFLOW_SAME_TRAINER_RETRY_CONTRACT
                ),
                "party_member_ko_contract": WORKFLOW_PARTY_MEMBER_KO_CONTRACT,
                "battle_start_candidate_audit": (
                    WORKFLOW_BATTLE_START_CANDIDATE_AUDIT
                ),
                "fairlight_preset": FAIRLIGHT_PRESET_NAME,
                "fairlight_preset_type": FAIRLIGHT_PRESET_TYPE,
                "fairlight_final_stage_contract": WORKFLOW_FAIRLIGHT_FINAL_STAGE_CONTRACT,
            },
            "steps": [
                {
                    "id": "full",
                    "kind": "script",
                    "tool": "deterministic_gsc_gym_full",
                    "requires_resolve": True,
                    "artifacts_out": ["fairlight_report"],
                }
            ],
        }
        validate_zero_llm_workflow(base)
        with self.assertRaises(GscGymDeterministicError):
            validate_zero_llm_workflow({**base, "steps": [{"id": "x", "kind": "llm_prompt"}]})
        with self.assertRaises(GscGymDeterministicError):
            validate_zero_llm_workflow(
                {
                    **base,
                    "tooling": {
                        "runtime_limit_seconds": 601,
                        "outer_process_tree_watchdog_seconds": 600,
                    },
                }
            )
        with self.assertRaises(GscGymDeterministicError):
            validate_zero_llm_workflow({**base, "steps": []})
        with self.assertRaisesRegex(GscGymDeterministicError, "BGM contract"):
            validate_zero_llm_workflow(
                {
                    **base,
                    "tooling": {
                        **base["tooling"],
                        "nonbattle_bgm_repeat_policy": "allow_repeats",
                    },
                }
            )
        required_fairlight_fields = {
            "fairlight_preset": FAIRLIGHT_PRESET_NAME,
            "fairlight_preset_type": FAIRLIGHT_PRESET_TYPE,
            "fairlight_final_stage_contract": WORKFLOW_FAIRLIGHT_FINAL_STAGE_CONTRACT,
        }
        for key in required_fairlight_fields:
            with self.subTest(fairlight_field=key, mutation="missing"):
                changed_tooling = dict(base["tooling"])
                changed_tooling.pop(key)
                with self.assertRaisesRegex(
                    GscGymDeterministicError,
                    "Fairlight final-stage contract",
                ):
                    validate_zero_llm_workflow({**base, "tooling": changed_tooling})
            with self.subTest(fairlight_field=key, mutation="altered"):
                changed_tooling = {
                    **base["tooling"],
                    key: f"altered-{required_fairlight_fields[key]}",
                }
                with self.assertRaisesRegex(
                    GscGymDeterministicError,
                    "Fairlight final-stage contract",
                ):
                    validate_zero_llm_workflow({**base, "tooling": changed_tooling})
        with self.assertRaises(GscGymDeterministicError):
            validate_zero_llm_workflow(
                {
                    **base,
                    "steps": [
                        *base["steps"],
                        {
                            "id": "prepare",
                            "kind": "script",
                            "tool": "deterministic_gsc_gym_prepare",
                        },
                    ],
                }
            )

    def test_registered_workflow_requires_final_fairlight_report(self) -> None:
        config_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "orchestrator_workflows.json"
        )
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        workflow = next(
            row for row in payload["workflows"] if row.get("id") == WORKFLOW_ID
        )
        validate_zero_llm_workflow(workflow)
        self.assertIn("fairlight_report", workflow["steps"][0]["artifacts_out"])


if __name__ == "__main__":
    unittest.main()
