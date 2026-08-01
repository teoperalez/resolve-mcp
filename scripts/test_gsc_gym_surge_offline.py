from __future__ import annotations

"""Offline regression against the preserved Lt. Surge editing evidence.

This test is intentionally file-only.  It never connects to DaVinci Resolve,
OBS, the GSC frontend, or the currently active recording session.
"""

import hashlib
import json
from pathlib import Path
import unittest

from src.resolve_mcp.orchestrator.gsc_gym_fcpxml import (
    BATTLE_GAP_FRAMES,
    OPENING_FRAMES,
)
from src.resolve_mcp.orchestrator.gsc_gym_fcpxml_plan import (
    BATTLE_GAP_DUPLICATES_V1_PREROLL,
    BATTLE_GAP_INSERTS_TIMELINE_FRAMES,
    BATTLE_GAP_POLICY,
    BattleAttemptSourceBoundary,
    CarouselSourceBoundary,
    parse_autoeditor_fcpxml,
    plan_gsc_gym_geometry,
)


SURGE_ROOT = Path("F:/Lt Surge Crystal Gym Leader Challenge")
RAW_AUTOEDITOR_FCPXML = SURGE_ROOT / "2026-07-22 21-12-04_AUTOEDITOR_RAW.fcpxml"
STRICT_AUDIT = (
    SURGE_ROOT
    / "CODEx"
    / "qa-reports"
    / "final-gsc-gym-leader-audit-no-flash-intros.json"
)

RAW_AUTOEDITOR_SHA256 = "7359D8960C592BBA58C821CA5BB1E87709386F55465322C4A7DC5AD52D02D2D6"
STRICT_AUDIT_SHA256 = "7936763166F8E5ADE657B6435520B6AE56D030AD50D53AE513D19DE77C575FAF"
CAROUSEL_DETECTOR_FRAME = 299_957
CAROUSEL_RETAINED_FRAME = 299_990
FINAL_RETAINED_SOURCE_END = 308_766

STRICT_MAJOR_ORDER = (
    "Rival 1",
    "Falkner",
    "Bugsy",
    "Rival 2",
    "Whitney",
    "Rival 3",
    "Morty",
    "Chuck",
    "Pryce",
    "Jasmine",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _source_frame_at_record_boundary(retained, record_frame: int, *, prefer_following: bool) -> int:
    """Invert flat auto-editor record geometry at a preserved audit boundary.

    At a hard cut, one record boundary can describe the prior source end and
    the following source start.  Battle starts use the following selection;
    battle ends use the preceding selection.  Inside a selection there is one
    candidate and the preference has no effect.
    """

    candidates = [
        interval.source_start_frame + record_frame - interval.record_start_frame
        for interval in retained.intervals
        if interval.record_start_frame <= record_frame <= interval.record_end_frame
    ]
    if not candidates:
        raise AssertionError(f"Preserved record frame {record_frame} has no retained source mapping.")
    return max(candidates) if prefer_following else min(candidates)


class PreservedSurgeOfflineRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        missing = [path for path in (RAW_AUTOEDITOR_FCPXML, STRICT_AUDIT) if not path.is_file()]
        if missing:
            raise unittest.SkipTest(f"Preserved Lt. Surge evidence is unavailable: {missing}")

        fingerprints = {
            RAW_AUTOEDITOR_FCPXML: RAW_AUTOEDITOR_SHA256,
            STRICT_AUDIT: STRICT_AUDIT_SHA256,
        }
        for path, expected in fingerprints.items():
            actual = _sha256(path)
            if actual != expected:
                raise AssertionError(
                    f"Preserved Lt. Surge evidence changed: {path}: {actual} != {expected}"
                )
        cls.retained = parse_autoeditor_fcpxml(
            RAW_AUTOEDITOR_FCPXML.read_text(encoding="utf-8-sig")
        )
        cls.audit = json.loads(STRICT_AUDIT.read_text(encoding="utf-8"))

    def _preserved_major_boundaries(self) -> tuple[BattleAttemptSourceBoundary, ...]:
        checks = {
            str(row["name"]): row["evidence"]
            for row in self.audit["checks"]
            if isinstance(row, dict) and row.get("name")
        }
        final_starts = checks["ten_canonical_battle_starts"]
        final_ends = {
            str(row["trainer"]): int(row["end_abs"]) - int(self.audit["timeline_start"])
            for row in checks["ten_exact_battle_theme_ranges"]
        }

        boundaries: list[BattleAttemptSourceBoundary] = []
        for ordinal, identity in enumerate(STRICT_MAJOR_ORDER, start=1):
            # This frozen coordinate inversion preserves the ten realistic
            # raw-source boundary probes used by the original regression.  It
            # is not the desired output geometry: the assertions below prove
            # that the current planner converts each probe to an immutable
            # auto-editor join and inserts a real record-time gap there.
            frozen_fixture_offset = OPENING_FRAMES + BATTLE_GAP_FRAMES * ordinal
            raw_record_start = int(final_starts[identity]) - frozen_fixture_offset
            raw_record_end = int(final_ends[identity]) - frozen_fixture_offset
            boundaries.append(
                BattleAttemptSourceBoundary(
                    attempt_id=f"surge-reference-{ordinal:02d}",
                    canonical_identity=identity,
                    attempt_ordinal=1,
                    role="rival" if identity.startswith("Rival ") else "leader",
                    source_start_frame=_source_frame_at_record_boundary(
                        self.retained,
                        raw_record_start,
                        prefer_following=True,
                    ),
                    source_end_frame=_source_frame_at_record_boundary(
                        self.retained,
                        raw_record_end,
                        prefer_following=False,
                    ),
                    start_authority=(
                        "fingerprinted Surge strict audit battle start; inverted through "
                        "fingerprinted raw auto-editor geometry"
                    ),
                    end_authority=(
                        "fingerprinted Surge strict audit battle end; inverted through "
                        "fingerprinted raw auto-editor geometry"
                    ),
                )
            )
        return tuple(boundaries)

    def test_carousel_tail_and_dialogue_survive_real_boundary_gap_inserts(self) -> None:
        self.assertEqual(len(self.retained.intervals), 592)
        self.assertEqual(self.retained.record_duration_frames, 165_070)
        self.assertEqual(self.retained.intervals[-1].source_end_frame, FINAL_RETAINED_SOURCE_END)

        plan = plan_gsc_gym_geometry(
            self.retained,
            self._preserved_major_boundaries(),
            CarouselSourceBoundary(
                CAROUSEL_DETECTOR_FRAME,
                "fixed deterministic pixel detector on preserved Surge source",
            ),
            dialogue_gain_db=-5.0,
        )

        mapping = plan.carousel_mapping
        self.assertEqual(
            (
                mapping.raw_source_frame,
                mapping.effective_source_frame,
                mapping.snap_delta_frames,
                mapping.original_record_frame,
                mapping.policy,
            ),
            (
                CAROUSEL_DETECTOR_FRAME,
                CAROUSEL_RETAINED_FRAME,
                33,
                157_317,
                "carousel_removed_gap_snap_to_next_retained_start",
            ),
        )
        self.assertEqual(
            BATTLE_GAP_POLICY,
            "real_60f_timeline_insert_only_for_identity_attempt_ordinal_1_at_"
            "adjacent_autoeditor_a1_boundary_preserve_all_a1_source_frames_"
            "with_incoming_v1_bridge_no_retry_gap",
        )
        self.assertTrue(BATTLE_GAP_INSERTS_TIMELINE_FRAMES)
        self.assertTrue(BATTLE_GAP_DUPLICATES_V1_PREROLL)
        bridges = [
            item
            for item in plan.body_v1
            if item.label.startswith("battle-gap-v1-bridge:")
        ]
        self.assertEqual(len(bridges), len(plan.battles))
        self.assertTrue(
            all(
                battle.final_start_frame
                == OPENING_FRAMES
                + battle.original_record_start_frame
                + BATTLE_GAP_FRAMES * ordinal
                and battle.final_end_frame
                == OPENING_FRAMES
                + battle.original_record_end_frame
                + BATTLE_GAP_FRAMES * ordinal
                and battle.gap_start_frame
                == battle.final_start_frame - BATTLE_GAP_FRAMES
                and battle.gap_end_frame == battle.final_start_frame
                for ordinal, battle in enumerate(plan.battles, start=1)
            )
        )
        self.assertEqual(len(plan.dialogue_a1), len(self.retained.intervals))
        self.assertEqual(
            [
                (item.source_start_frame, item.duration_frames)
                for item in plan.dialogue_a1
            ],
            [
                (item.source_start_frame, item.duration_frames)
                for item in self.retained.intervals
            ],
        )
        self.assertEqual(
            sum(item.duration_frames for item in plan.dialogue_a1),
            self.retained.record_duration_frames,
        )
        for battle, bridge in zip(plan.battles, bridges):
            incoming_a1 = [
                item
                for item in plan.dialogue_a1
                if item.record_start_frame == battle.gap_end_frame
            ]
            self.assertEqual(len(incoming_a1), 1)
            self.assertEqual(
                (bridge.record_start_frame, bridge.record_end_frame),
                (battle.gap_start_frame, battle.gap_end_frame),
            )
            self.assertEqual(
                bridge.source_start_frame + bridge.duration_frames,
                incoming_a1[0].source_start_frame,
            )
        self.assertEqual(
            plan.carousel.v1.record_start_frame,
            OPENING_FRAMES
            + mapping.original_record_frame
            + BATTLE_GAP_FRAMES * len(plan.battles),
        )
        self.assertEqual(
            plan.carousel.v1.record_end_frame,
            OPENING_FRAMES
            + self.retained.record_duration_frames
            + BATTLE_GAP_FRAMES * len(plan.battles),
        )

        strict_checks = {
            str(row["name"]): row["evidence"]
            for row in self.audit["checks"]
            if isinstance(row, dict) and row.get("name")
        }
        strict_outro_start = (
            int(strict_checks["continuous_frame_exact_a2_bed"]["outro_start"])
            - int(self.audit["timeline_start"])
        )
        # The historical repaired reference ended 77 frames after the old
        # zero-insert projection.  The corrected plan deliberately adds ten
        # true 60-frame gaps, so it ends 600 - 77 = 523 frames later than that
        # preserved reference instead of deleting 600 frames of dialogue.
        self.assertEqual(
            plan.carousel.v1.record_end_frame - strict_outro_start,
            BATTLE_GAP_FRAMES * len(plan.battles) - 77,
        )

        # These are real boundary adjustments reconstructed from the strict,
        # fingerprinted Surge audit.  Inside-segment markers map to the nearer
        # valid adjacent join instead of always moving forward or splitting
        # V1/A1.
        self.assertEqual(
            [battle.start_snap_delta_frames for battle in plan.battles],
            [-75, -451, 41, 0, 37, 127, -86, 18, -6, 17],
        )
        self.assertTrue(
            all(battle.end_snap_delta_frames == 0 for battle in plan.battles)
        )
        self.assertTrue(
            all(
                battle.start_mapping_policy
                in {
                    "battle_start_exact_retained_interval_start",
                    "battle_start_inside_retained_nearest_preceding_adjacent_join",
                    "battle_start_inside_retained_nearest_following_adjacent_join",
                }
                for battle in plan.battles
            )
        )
        self.assertTrue(
            all("exact_split" not in battle.start_mapping_policy for battle in plan.battles)
        )

        slices = plan.carousel.v2_slices
        self.assertEqual(len(slices), 28)
        self.assertEqual(slices[0].source_start_frame, CAROUSEL_RETAINED_FRAME)
        self.assertTrue(
            all(left.record_end_frame == right.record_start_frame for left, right in zip(slices, slices[1:]))
        )
        self.assertEqual(
            slices[-1].source_start_frame + slices[-1].duration_frames,
            FINAL_RETAINED_SOURCE_END,
        )
        self.assertEqual(
            plan.manifest["carousel"]["final_retained_source_content_end_frame"],
            FINAL_RETAINED_SOURCE_END,
        )
        self.assertEqual(
            plan.manifest["contract"]["gap_policy"],
            BATTLE_GAP_POLICY,
        )
        self.assertTrue(
            plan.manifest["contract"]["battle_gap_inserts_timeline_frames"]
        )
        self.assertTrue(
            plan.manifest["contract"]["battle_gap_duplicates_v1_preroll"]
        )
        self.assertEqual(plan.manifest["contract"]["a1_removed_frames"], 0)
        self.assertEqual(
            plan.manifest["contract"]["v1_bridge_policy"],
            "one_exact_60f_incoming_side_source_backed_bridge_per_gap_"
            "with_source_overlap_allowed",
        )
        self.assertEqual(plan.structural_audit["status"], "pass")


if __name__ == "__main__":
    unittest.main()
