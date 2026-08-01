from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from resolve_mcp.orchestrator.gsc_gym_deterministic import (
    GscGymDeterministicError,
    build_overlay_intro_plan,
)


CANONICAL_CRYSTAL_RIVAL_ASSETS = {
    ("RIVAL1", 1): "silver-initial-chikorita-battle-intro.mov",
    ("RIVAL1", 2): "silver-initial-cyndaquil-battle-intro.mov",
    ("RIVAL1", 3): "silver-initial-totodile-battle-intro.mov",
    ("RIVAL1", 4): "silver-azalea-grass-battle-intro.mov",
    ("RIVAL1", 5): "silver-azalea-fire-battle-intro.mov",
    ("RIVAL1", 6): "silver-azalea-water-battle-intro.mov",
    ("RIVAL1", 7): "silver-burnedtower-grass-battle-intro.mov",
    ("RIVAL1", 8): "silver-burnedtower-fire-battle-intro.mov",
    ("RIVAL1", 9): "silver-burnedtower-water-battle-intro.mov",
    ("RIVAL1", 10): "silver-goldenrod-grass-battle-intro.mov",
    ("RIVAL1", 11): "silver-goldenrod-fire-battle-intro.mov",
    ("RIVAL1", 12): "silver-goldenrod-water-battle-intro.mov",
    ("RIVAL1", 13): "silver-victoryroad-grass-battle-intro.mov",
    ("RIVAL1", 14): "silver-victoryroad-fire-battle-intro.mov",
    ("RIVAL1", 15): "silver-victoryroad-water-battle-intro.mov",
    ("RIVAL2", 1): "silver-mtmoon-grass-battle-intro.mov",
    ("RIVAL2", 2): "silver-mtmoon-fire-battle-intro.mov",
    ("RIVAL2", 3): "silver-mtmoon-water-battle-intro.mov",
    ("RIVAL2", 4): "silver-indigoplateau-grass-battle-intro.mov",
    ("RIVAL2", 5): "silver-indigoplateau-fire-battle-intro.mov",
    ("RIVAL2", 6): "silver-indigoplateau-water-battle-intro.mov",
}


class GscGymRivalAssetTests(unittest.TestCase):
    @staticmethod
    def _battle(trainer_class: str, trainer_id: int, ordinal: int = 1) -> dict:
        return {
            "session_start_frame": 1000 + ordinal * 600,
            "role": "rival",
            "identity": "Silver",
            "battle_key": f"{trainer_class}:{trainer_id}",
            "trainer_class": trainer_class,
            "trainer_id": trainer_id,
        }

    def test_every_canonical_crystal_rival_record_selects_exact_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            leaders = root / "leaders"
            rivals = root / "rivals"
            leaders.mkdir()
            rivals.mkdir()
            for filename in CANONICAL_CRYSTAL_RIVAL_ASSETS.values():
                (rivals / filename).write_bytes(b"rival")
            battles = [
                self._battle(trainer_class, trainer_id, ordinal)
                for ordinal, (trainer_class, trainer_id) in enumerate(
                    CANONICAL_CRYSTAL_RIVAL_ASSETS,
                    start=1,
                )
            ]

            rows = build_overlay_intro_plan(
                battles,
                leaders_dir=leaders,
                rivals_dir=rivals,
                boundary_is_final_timeline=False,
            )

            actual = {
                (row["trainer_class"], row["trainer_id"]): Path(row["asset"]).name
                for row in rows
            }
            self.assertEqual(actual, CANONICAL_CRYSTAL_RIVAL_ASSETS)

    def test_override_keeps_location_and_selects_requested_branch(self) -> None:
        cases = (
            ("RIVAL1", 2, "silver-initial-totodile-battle-intro.mov"),
            ("RIVAL1", 11, "silver-goldenrod-water-battle-intro.mov"),
            ("RIVAL2", 5, "silver-indigoplateau-water-battle-intro.mov"),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            leaders = root / "leaders"
            rivals = root / "rivals"
            leaders.mkdir()
            rivals.mkdir()
            for _trainer_class, _trainer_id, filename in cases:
                (rivals / filename).write_bytes(b"rival")

            for ordinal, (trainer_class, trainer_id, expected) in enumerate(cases, start=1):
                with self.subTest(trainer_class=trainer_class, trainer_id=trainer_id):
                    rows = build_overlay_intro_plan(
                        [self._battle(trainer_class, trainer_id, ordinal)],
                        leaders_dir=leaders,
                        rivals_dir=rivals,
                        rival_starter_type="water",
                        boundary_is_final_timeline=False,
                    )
                    self.assertEqual(Path(rows[0]["asset"]).name, expected)

    def test_unknown_rival_class_or_id_fails_closed(self) -> None:
        unsupported = (("RIVAL1", 16), ("RIVAL2", 7), ("RIVAL3", 1))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            leaders = root / "leaders"
            rivals = root / "rivals"
            leaders.mkdir()
            rivals.mkdir()
            for ordinal, (trainer_class, trainer_id) in enumerate(unsupported, start=1):
                with self.subTest(trainer_class=trainer_class, trainer_id=trainer_id):
                    with self.assertRaisesRegex(
                        GscGymDeterministicError,
                        "No deterministic rival asset mapping exists",
                    ):
                        build_overlay_intro_plan(
                            [self._battle(trainer_class, trainer_id, ordinal)],
                            leaders_dir=leaders,
                            rivals_dir=rivals,
                            boundary_is_final_timeline=False,
                        )

    def test_legacy_initial_type_name_does_not_mask_missing_canonical_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            leaders = root / "leaders"
            rivals = root / "rivals"
            leaders.mkdir()
            rivals.mkdir()
            (rivals / "silver-initial-grass-battle-intro.mov").write_bytes(b"legacy")

            with self.assertRaisesRegex(
                GscGymDeterministicError,
                "silver-initial-chikorita-battle-intro.mov",
            ):
                build_overlay_intro_plan(
                    [self._battle("RIVAL1", 1)],
                    leaders_dir=leaders,
                    rivals_dir=rivals,
                    boundary_is_final_timeline=False,
                )


if __name__ == "__main__":
    unittest.main()
