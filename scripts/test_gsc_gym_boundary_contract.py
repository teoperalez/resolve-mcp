from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from resolve_mcp.orchestrator.gsc_gym_deterministic import (
    GscGymDeterministicError,
    build_overlay_intro_plan,
    canonical_carousel_boundary,
    map_battle_groups_to_source,
)


class GscGymBoundaryContractTests(unittest.TestCase):
    @staticmethod
    def _event(frame: int, name: str, *, category: str = "view", ms_delta: float = 0.0) -> dict:
        return {
            "tElapsedMs": frame * 1000.0 / 60.0 + ms_delta,
            "category": category,
            "name": name,
            "data": {},
        }

    def test_carousel_selects_final_completed_cycle_with_channel_handoff(self) -> None:
        events = [
            self._event(100, "member-carousel-started"),
            self._event(200, "member-carousel-ended"),
            self._event(300, "member-carousel-started"),
            self._event(400, "member-carousel-ended"),
            self._event(400, "channel-exp-bar-shown", ms_delta=1.0),
        ]
        boundary = canonical_carousel_boundary(events)
        self.assertIsNotNone(boundary)
        assert boundary is not None
        self.assertEqual(boundary["session_frame"], 300)
        self.assertEqual(boundary["end_session_frame"], 400)
        self.assertEqual(boundary["channel_exp_session_frame"], 400)
        self.assertEqual(boundary["completed_cycle_count"], 2)
        self.assertEqual(boundary["qualifying_cycle_count"], 1)
        self.assertEqual(boundary["selected_cycle_ordinal"], 2)

    def test_carousel_rejects_earlier_handoff_when_final_cycle_has_none(self) -> None:
        events = [
            self._event(100, "member-carousel-started"),
            self._event(200, "member-carousel-ended"),
            self._event(200, "channel-exp-bar-shown", ms_delta=1.0),
            self._event(300, "member-carousel-started"),
            self._event(400, "member-carousel-ended"),
        ]
        self.assertIsNone(canonical_carousel_boundary(events))

    def test_carousel_rejects_trailing_incomplete_cycle_after_valid_pair(self) -> None:
        events = [
            self._event(100, "member-carousel-started"),
            self._event(200, "member-carousel-ended"),
            self._event(200, "channel-exp-bar-shown", ms_delta=1.0),
            self._event(300, "member-carousel-started"),
        ]
        with self.assertRaises(GscGymDeterministicError):
            canonical_carousel_boundary(events)

    def test_carousel_absence_or_old_aliases_fail_closed(self) -> None:
        self.assertIsNone(canonical_carousel_boundary([]))
        self.assertIsNone(
            canonical_carousel_boundary([self._event(100, "member-carousel-start")])
        )
        self.assertIsNone(
            canonical_carousel_boundary([
                self._event(100, "member-carousel-started"),
                self._event(200, "member-carousel-ended"),
                self._event(203, "channel-exp-bar-shown"),
            ])
        )

    def test_carousel_malformed_cycle_is_rejected(self) -> None:
        with self.assertRaises(GscGymDeterministicError):
            canonical_carousel_boundary([
                self._event(100, "member-carousel-started"),
                self._event(101, "member-carousel-started"),
            ])
        with self.assertRaises(GscGymDeterministicError):
            canonical_carousel_boundary([self._event(100, "member-carousel-ended")])

    def test_lt_surge_checkpoint_maps_to_approved_asset_stem(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            leaders = root / "leaders"
            rivals = root / "rivals"
            leaders.mkdir()
            rivals.mkdir()
            approved = leaders / "lt-surge-battle-intro.mov"
            approved.write_bytes(b"approved")
            rows = build_overlay_intro_plan(
                [{
                    "session_start_frame": 1000,
                    "role": "leader",
                    "identity": "Lt. Surge",
                    "battle_key": "LT_SURGE:1",
                    "trainer_class": "LT_SURGE",
                    "trainer_id": 1,
                    "checkpoint_key": "surge",
                }],
                leaders_dir=leaders,
                rivals_dir=rivals,
                boundary_is_final_timeline=False,
            )
            self.assertEqual(Path(rows[0]["asset"]), approved.resolve())

    @staticmethod
    def _unlogged_end_group() -> dict:
        return {
            "battle_key": "ERIKA:1",
            "attempts": [{"start_event_index": 2}],
            "direct_end_event_index": None,
            "session_end_frame": 400,
        }

    def test_mapper_exit_projects_only_through_local_constant_offset(self) -> None:
        alignment = {
            "offset_frame": 100,
            "matches": [
                {"event_index": 2, "marker_session_frame": 300, "chapter_frame": 200},
                {"event_index": 7, "marker_session_frame": 350, "chapter_frame": 250},
                {"event_index": 8, "marker_session_frame": 450, "chapter_frame": 350},
            ],
        }
        mapped = map_battle_groups_to_source([self._unlogged_end_group()], alignment)
        self.assertEqual(mapped[0]["source_start_frame"], 200)
        self.assertEqual(mapped[0]["source_end_frame"], 300)
        self.assertIsNotNone(mapped[0]["source_end_projection"])
        self.assertIn("constant_session_offset", mapped[0]["source_end_authority"])

    def test_mapper_exit_projection_rejects_unstable_or_wide_brackets(self) -> None:
        unstable = {
            "offset_frame": 100,
            "matches": [
                {"event_index": 2, "marker_session_frame": 300, "chapter_frame": 200},
                {"event_index": 7, "marker_session_frame": 350, "chapter_frame": 246},
                {"event_index": 8, "marker_session_frame": 450, "chapter_frame": 350},
            ],
        }
        with self.assertRaises(GscGymDeterministicError):
            map_battle_groups_to_source([self._unlogged_end_group()], unstable)

        wide = {
            "offset_frame": 100,
            "matches": [
                {"event_index": 2, "marker_session_frame": 300, "chapter_frame": 200},
                {"event_index": 8, "marker_session_frame": 1000, "chapter_frame": 900},
            ],
        }
        with self.assertRaises(GscGymDeterministicError):
            map_battle_groups_to_source([self._unlogged_end_group()], wide)


if __name__ == "__main__":
    unittest.main()
