from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_gsc_gym_deterministic_workflow as workflow
from resolve_mcp.orchestrator.gsc_gym_fcpxml_plan import parse_autoeditor_fcpxml


def _undersized_auto_editor_fcpxml(source: Path) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.11">
  <resources>
    <format id="r1" frameDuration="1/60s" width="3840" height="2160"/>
    <asset id="r2" name="source" start="0s" duration="120/60s" hasVideo="1">
      <media-rep kind="original-media" src="{source.resolve().as_uri()}"/>
    </asset>
  </resources>
  <library><event><project><sequence format="r1" tcStart="0s" duration="60/60s">
    <spine>
      <asset-clip name="retained" ref="r2" offset="0s" start="180/60s" duration="60/60s"/>
    </spine>
  </sequence></project></event></library>
</fcpxml>
"""


class GscGymAutoEditorRepairIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "source.mp4"
        self.destination = self.root / "raw.fcpxml"
        self.report_path = self.root / "raw.asset-duration-repair.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_auto_editor_result(self, command: list[str], **_: object) -> None:
        output = Path(command[command.index("--output") + 1])
        output.write_text(_undersized_auto_editor_fcpxml(self.source), encoding="utf-8")

    def test_repair_precedes_parse_and_atomic_promotion(self) -> None:
        with patch.object(
            workflow,
            "_run_external",
            side_effect=self._write_auto_editor_result,
        ):
            report = workflow._run_auto_editor(
                self.source,
                self.destination,
                repair_report_path=self.report_path,
                source_duration_frames=300,
                ordinal=4,
                command_prefix=["auto-editor"],
                deadline=workflow._Deadline(10),
            )

        retained = parse_autoeditor_fcpxml(self.destination.read_text(encoding="utf-8-sig"))
        persisted = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertEqual(retained.source_duration_frames, 300)
        self.assertTrue(report["changed"])
        self.assertEqual(report["repaired_asset_count"], 1)
        self.assertEqual(persisted["input_fcpxml"], str(self.destination.resolve()))
        self.assertEqual(persisted["output_fcpxml"], str(self.destination.resolve()))
        self.assertNotIn(".tmp-", self.report_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["promoted_fcpxml"], str(self.destination.resolve()))
        self.assertEqual(
            persisted["promotion_validation"]["parse_autoeditor_fcpxml"],
            "pass",
        )
        validated = workflow._validate_auto_editor_repair_report(
            self.report_path,
            self.destination,
            self.source,
            300,
            workflow._Deadline(10),
        )
        self.assertEqual(validated["output_sha256"], persisted["output_sha256"])

    def test_parse_failure_never_promotes_or_keeps_a_receipt(self) -> None:
        def write_malformed(command: list[str], **_: object) -> None:
            output = Path(command[command.index("--output") + 1])
            output.write_text("<not-fcpxml/>", encoding="utf-8")

        with patch.object(workflow, "_run_external", side_effect=write_malformed):
            with self.assertRaises(workflow.GscGymDeterministicError):
                workflow._run_auto_editor(
                    self.source,
                    self.destination,
                    repair_report_path=self.report_path,
                    source_duration_frames=240,
                    ordinal=4,
                    command_prefix=["auto-editor"],
                    deadline=workflow._Deadline(10),
                )

        self.assertFalse(self.destination.exists())
        self.assertFalse(self.report_path.exists())

    def test_fixed_pixel_carousel_authority_is_normalized_for_geometry(self) -> None:
        detector_receipt = {
            "schema": "gsc_fixed_pixel_carousel_boundary_v2",
            "status": "pass",
            "source_frame": 395026,
            "boundary_authority": "fixed_three_patch_contract",
        }
        with patch.object(
            workflow,
            "detect_carousel_source_frame",
            return_value=detector_receipt,
        ):
            result = workflow._carousel_source_boundary(
                telemetry=None,
                alignment={},
                source=self.source,
                source_frames=401980,
                last_battle_source_end=390000,
                deadline=workflow._Deadline(10),
            )

        self.assertEqual(result["source_frame"], 395026)
        self.assertEqual(
            result["source_boundary_authority"],
            detector_receipt["boundary_authority"],
        )


if __name__ == "__main__":
    unittest.main()
