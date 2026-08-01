from __future__ import annotations

import unittest

from resolve_mcp.orchestrator.project_discovery import (
    challenge_type_from_label,
    workflow_for_challenge,
)


class ProjectDiscoveryWorkflowRoutingTests(unittest.TestCase):
    def test_ordinary_gym_leader_label_routes_to_deterministic_gsc_workflow(self) -> None:
        challenge_type = challenge_type_from_label("Gym Leader Challenge")

        self.assertEqual(challenge_type, "gym_leader_challenge")
        self.assertEqual(
            workflow_for_challenge(challenge_type),
            "gsc_gym_leader_deterministic_single_build",
        )

    def test_rby_minimum_battle_routes_are_unchanged(self) -> None:
        self.assertEqual(
            workflow_for_challenge("minimum_battles"),
            "gen1_rby_umb_review_first",
        )
        self.assertEqual(
            workflow_for_challenge("ultra_minimum_battles"),
            "gen1_rby_umb_review_first",
        )

    def test_non_gym_generic_challenges_keep_legacy_route(self) -> None:
        self.assertEqual(
            workflow_for_challenge("standard_challenge"),
            "pokemon_gym_leader_challenge",
        )
        self.assertEqual(
            workflow_for_challenge("solo_challenge"),
            "pokemon_gym_leader_challenge",
        )


if __name__ == "__main__":
    unittest.main()
