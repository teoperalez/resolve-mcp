from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.audit_gsc_gym_offline_artifacts import (
    EXPECTED_FCPXML_CHECKS,
    _fcpxml_a2_rows,
    _general_bgm_occurrences,
)


REPO_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_ID = "gsc_gym_leader_deterministic_single_build"


def _segment(
    source: str,
    record_range: list[int],
    *,
    role: str,
    battle_id: str | None = None,
    source_range: list[int] | None = None,
) -> dict[str, object]:
    duration = record_range[1] - record_range[0]
    return {
        "record_range": record_range,
        "source_range": source_range or [0, duration],
        "asset": {
            "path": source,
            "name": Path(source).name,
            "origin_path": source,
        },
        "role": role,
        "battle_id": battle_id,
    }


class GscGymOfflineAuditorTests(unittest.TestCase):
    def test_fcpxml_a2_rows_prove_original_uri_name_media_range_trim_and_gain(self) -> None:
        raw = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <resources>
    <asset id="r2" name="Dual Screen Lovelife.mp3" start="0s" duration="250/3s" hasAudio="1">
      <media-rep kind="original-media" src="file:///F:/music/Dual%20Screen%20Lovelife.mp3" />
    </asset>
  </resources>
  <library><event><project><sequence tcStart="3600s"><spine>
    <clip offset="3600s" start="0s" duration="10s">
      <asset-clip ref="r2" name="Dual Screen Lovelife.mp3" lane="3" offset="0s" start="191/15s" duration="10s">
        <adjust-volume amount="-8.4dB" />
      </asset-clip>
    </clip>
  </spine></sequence></project></event></library>
</fcpxml>
"""

        rows = _fcpxml_a2_rows(raw)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["record_range"], [0, 600])
        self.assertEqual(rows[0]["source_range"], [764, 1_364])
        self.assertEqual(rows[0]["media_source_range"], [0, 5_000])
        self.assertEqual(rows[0]["timeline_name"], "Dual Screen Lovelife.mp3")
        self.assertEqual(rows[0]["resource_name"], "Dual Screen Lovelife.mp3")
        self.assertEqual(rows[0]["gain_db"], -8.4)
        self.assertEqual(Path(rows[0]["source_path"]).name, "Dual Screen Lovelife.mp3")

    def test_occurrences_coalesce_only_contiguous_original_source_ranges(self) -> None:
        dual = "F:/bgm/Dual Screen Lovelife.mp3"
        random = "F:/bgm/Random.mp3"
        battle = "F:/GSCNewLayout/audio/Gen 2 battle audio/Gym.mp3"
        segments = [
            _segment(dual, [0, 100], role="opening", source_range=[764, 864]),
            _segment(battle, [100, 200], role="battle", battle_id="b1"),
            _segment(random, [200, 250], role="nonbattle"),
            _segment(
                random,
                [250, 300],
                role="carousel",
                source_range=[50, 100],
            ),
            _segment(battle, [300, 400], role="battle", battle_id="b2"),
            _segment(random, [400, 450], role="carousel"),
        ]

        occurrences = _general_bgm_occurrences(segments)

        self.assertEqual(len(occurrences), 3)
        self.assertEqual(occurrences[0]["source_range"], [764, 864])
        self.assertEqual(occurrences[1]["record_range"], [200, 300])
        self.assertEqual(occurrences[1]["source_range"], [0, 100])
        self.assertEqual(occurrences[1]["roles"], ["nonbattle", "carousel"])
        self.assertEqual(occurrences[2]["record_range"], [400, 450])

    def test_registered_workflow_has_exact_nonbattle_contract(self) -> None:
        config = json.loads(
            (REPO_DIR / "config" / "orchestrator_workflows.json").read_text(
                encoding="utf-8-sig"
            )
        )
        workflow = next(
            row for row in config["workflows"] if row.get("id") == WORKFLOW_ID
        )
        tooling = workflow["tooling"]
        self.assertEqual(
            tooling["post_battle_bgm_transition_policy"],
            "fresh_unused_source_zero_after_every_positive_post_battle_gap;"
            "zero_gap_direct_battle_handoff",
        )
        self.assertEqual(
            tooling["nonbattle_bgm_repeat_policy"],
            "no_repeats_except_Dual_Screen_Lovelife_exactly_opening_and_post_final",
        )
        self.assertEqual(
            tooling["post_final_bgm_sequence"],
            "Dual Screen Lovelife.mp3;Motivated By Clouds.mp3;"
            "Roll Me in Stardust.mp3;unused_randomized_track",
        )
        self.assertEqual(
            tooling["physical_attempt_bgm_start_contract"],
            "every_physical_attempt_has_distinct_A2_assignment_and_restarts_"
            "original_source_at_asset_source_start_frame",
        )
        self.assertIn(
            "only_supplied_identity_attempt_ordinal_1_gets_an_A1_gap",
            tooling["battle_population"],
        )
        self.assertIn(
            "no_gap_before_same_trainer_retries_even_if_attempt_1_was_removed",
            tooling["battle_a1_gap_geometry"],
        )
        self.assertEqual(
            tooling["intro_bgm"],
            "Dual Screen Lovelife.mp3_source_offset_764_at_opening_and_"
            "source_zero_after_final_battle_only",
        )
        self.assertNotIn("pause_resume", json.dumps(workflow).casefold())
        self.assertIn("without_replacement", tooling["nonbattle_bgm"])
        self.assertIn("deck_never_wraps", tooling["nonbattle_bgm"])

    def test_expected_fcpxml_audit_contract_has_twelve_checks(self) -> None:
        self.assertEqual(len(EXPECTED_FCPXML_CHECKS), 12)
        self.assertIn(
            "nonbattle_bgm_fresh_after_battles_no_repeat_and_post_final_sequence",
            EXPECTED_FCPXML_CHECKS,
        )


if __name__ == "__main__":
    unittest.main()
