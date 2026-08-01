from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator import load_catalog
from resolve_mcp.orchestrator.models import ProjectProfile
from resolve_mcp.orchestrator.status import collect_artifact_status, step_readiness
from resolve_mcp.orchestrator_app import (
    DIRECTORY_KEYS,
    FILE_KEYS,
    PATH_ORDER,
    OrchestratorApp,
)


WORKFLOW_ID = "gsc_gym_leader_deterministic_single_build"


def gsc_profile() -> ProjectProfile:
    app = OrchestratorApp.__new__(OrchestratorApp)
    parameters = app._default_parameters_for_workflow(WORKFLOW_ID)
    parameters.update(
        {
            "source_media": "F:/recordings/Whitney Crystal (final).mp4",
            "source_name": "Whitney Crystal (final)",
            "session_dir": "F:/sessions/whitney",
        }
    )
    return ProjectProfile(
        id="whitney_crystal",
        name="Whitney Crystal",
        workflow_id=WORKFLOW_ID,
        game_version="pokemon_crystal",
        challenge_type="gym_leader_challenge",
        project_dir="F:/recordings",
        codex_dir="F:/recordings/CODEx",
        parameters=parameters,
        paths=app._default_paths_for_workflow(WORKFLOW_ID),
    )


class GscDeterministicProfileTests(unittest.TestCase):
    def test_defaults_expand_every_registered_gsc_tool_placeholder(self) -> None:
        catalog = load_catalog(REPO_DIR / "config" / "orchestrator_workflows.json")
        profile = gsc_profile()
        mapping = profile.mapping(REPO_DIR)

        self.assertEqual(mapping["resolve_project_name"], "Whitney Crystal")
        self.assertEqual(mapping["resolve_project"], "Whitney Crystal")
        self.assertEqual(mapping["dialogue_audio_ordinal"], "5")
        self.assertEqual(mapping["source_safe_stem"], "Whitney-Crystal-final")
        self.assertEqual(
            mapping["output_dir"],
            "F:/CodexTemp/resolve-mcp/gsc-gym/whitney_crystal",
        )
        self.assertEqual(
            mapping["deterministic_plan"],
            f'{mapping["output_dir"]}/orchestrator-result.json',
        )
        self.assertNotEqual(
            mapping["deterministic_plan"],
            f'{mapping["output_dir"]}/Whitney-Crystal-final__GSC_GYM_DETERMINISTIC.plan.json',
        )

        tool_ids = {
            "deterministic_gsc_gym_full",
            "deterministic_gsc_gym_prepare",
            "deterministic_gsc_gym_build_offline",
            "deterministic_gsc_gym_resolve_dry_run",
        }
        commands = {
            tool.id: tool.expanded_command(mapping)
            for tool in catalog.tools
            if tool.id in tool_ids
        }
        self.assertEqual(set(commands), tool_ids)
        for command in commands.values():
            self.assertFalse(
                any("{" in part or "}" in part for part in command),
                command,
            )
            self.assertIn("F:/sessions/whitney", command)
            self.assertIn("5", command)
        full = commands["deterministic_gsc_gym_full"]
        self.assertIn("full", full)
        self.assertIn("--resolve-project", full)
        self.assertNotIn("--require-resolve", full)
        self.assertEqual(
            [step.id for step in catalog.workflow(WORKFLOW_ID).steps],
            ["full"],
        )
        self.assertEqual(
            catalog.workflow(WORKFLOW_ID).steps[0].tool,
            "deterministic_gsc_gym_full",
        )
        self.assertIn("Whitney Crystal", commands["deterministic_gsc_gym_resolve_dry_run"])
        self.assertEqual(
            mapping["dialogue_pcm24"],
            f'{mapping["output_dir"]}/Whitney-Crystal-final__dialogue-a5.wav',
        )
        self.assertEqual(
            mapping["deterministic_fcpxml"],
            f'{mapping["output_dir"]}/Whitney-Crystal-final__GSC_GYM_DETERMINISTIC.fcpxml',
        )

    def test_declared_artifacts_are_bound_for_status_and_readiness(self) -> None:
        catalog = load_catalog(REPO_DIR / "config" / "orchestrator_workflows.json")
        workflow = catalog.workflow(WORKFLOW_ID)
        profile = gsc_profile()

        statuses = collect_artifact_status(profile, workflow, REPO_DIR)
        declared = {
            artifact.key
            for step in workflow.steps
            for artifact in (*step.artifacts_in, *step.artifacts_out)
        }
        self.assertEqual({status.key for status in statuses}, declared)
        self.assertEqual(
            set(step_readiness(profile, workflow, REPO_DIR)),
            {step.id for step in workflow.steps},
        )

    def test_gsc_outputs_have_typed_profile_editor_fields(self) -> None:
        for key in (
            "output_dir",
            "deterministic_plan",
            "deterministic_fcpxml",
            "deterministic_manifest",
            "resolve_dry_run_receipt",
            "media_pool_bins_report",
            "fairlight_report",
        ):
            self.assertIn(key, PATH_ORDER)
        self.assertIn("output_dir", DIRECTORY_KEYS)
        self.assertIn("deterministic_plan", FILE_KEYS)
        self.assertIn("media_pool_bins_report", FILE_KEYS)
        self.assertIn("fairlight_report", FILE_KEYS)


if __name__ == "__main__":
    unittest.main()
